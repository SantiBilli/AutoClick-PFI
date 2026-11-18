"""AutoClick control plane. Lambda HTTP API v2; no prompts or bot data are stored.

Business rules are independent of AWS. Data API persists a normalized relational
schema with JSONB documents matching the existing frontend contract. A transaction
advisory lock serializes short control-plane mutations, including quota reservations.
"""
from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

LOG = logging.getLogger(__name__)
TABLES = {
    "users": "users", "organizations": "organizations", "areas": "areas",
    "organizationMemberships": "organization_memberships",
    "areaMemberships": "area_memberships", "requests": "token_usage",
    "businessRequests": "business_requests",
    "adminRequests": "platform_usage",
    "accountDeletions": "account_deletions",
}
SCHEMA = [
    "CREATE TABLE IF NOT EXISTS account_deletions (id text PRIMARY KEY, data jsonb NOT NULL)",
    "CREATE TABLE IF NOT EXISTS users (id text PRIMARY KEY, data jsonb NOT NULL, cognito_sub text GENERATED ALWAYS AS (data->>'cognitoSub') STORED UNIQUE NOT NULL)",
    "CREATE TABLE IF NOT EXISTS organizations (id text PRIMARY KEY, data jsonb NOT NULL, CHECK ((data->>'monthlyTokenLimit')::bigint >= 0))",
    "CREATE TABLE IF NOT EXISTS areas (id text PRIMARY KEY, data jsonb NOT NULL, organization_id text GENERATED ALWAYS AS (data->>'organizationId') STORED NOT NULL REFERENCES organizations(id), CHECK ((data->>'tokenLimit')::bigint >= 0))",
    "CREATE TABLE IF NOT EXISTS organization_memberships (id text PRIMARY KEY, data jsonb NOT NULL, user_id text GENERATED ALWAYS AS (data->>'userId') STORED NOT NULL REFERENCES users(id), organization_id text GENERATED ALWAYS AS (data->>'organizationId') STORED NOT NULL REFERENCES organizations(id), UNIQUE(user_id, organization_id))",
    "CREATE UNIQUE INDEX IF NOT EXISTS organization_memberships_one_per_user ON organization_memberships (user_id)",
    "CREATE TABLE IF NOT EXISTS area_memberships (id text PRIMARY KEY, data jsonb NOT NULL, user_id text GENERATED ALWAYS AS (data->>'userId') STORED NOT NULL REFERENCES users(id), area_id text GENERATED ALWAYS AS (data->>'areaId') STORED NOT NULL REFERENCES areas(id), UNIQUE(user_id, area_id))",
    "CREATE TABLE IF NOT EXISTS token_usage (id text PRIMARY KEY, data jsonb NOT NULL, user_id text GENERATED ALWAYS AS (data->>'userId') STORED NOT NULL REFERENCES users(id), organization_id text GENERATED ALWAYS AS (data->>'organizationId') STORED NOT NULL REFERENCES organizations(id), area_id text GENERATED ALWAYS AS (data->>'areaId') STORED NOT NULL REFERENCES areas(id), CHECK (data->>'status' IN ('AUTHORIZED','RUNNING','COMPLETED','FAILED','EXPIRED')), CHECK ((data->>'reservedTokens')::bigint >= 0))",
    "CREATE INDEX IF NOT EXISTS token_usage_period ON token_usage (organization_id, (data->>'period'))",
    "CREATE TABLE IF NOT EXISTS business_requests (id text PRIMARY KEY, data jsonb NOT NULL)",
    "CREATE TABLE IF NOT EXISTS platform_usage (id text PRIMARY KEY, data jsonb NOT NULL, user_id text GENERATED ALWAYS AS (data->>'userId') STORED NOT NULL REFERENCES users(id), CHECK (data->>'status' IN ('AUTHORIZED','RUNNING','COMPLETED','FAILED','EXPIRED')))",
]

DELETED_USER_ID = "deleted-accounts"


def deletion_key(sub):
    # A one-way tombstone also blocks a request authenticated just before deletion.
    return hashlib.sha256(sub.encode()).hexdigest()


def finish_account_deletion(store, identifier):
    """Durable, retryable cleanup. Never report completion before all stores agree."""
    with store.transaction() as state:
        job = next((j for j in state["accountDeletions"] if j["id"] == identifier), None)
        if not job or job["status"] == "deleted":
            return
        job = copy.deepcopy(job)
    avatar_storage().delete_object(Bucket=os.environ["AVATAR_BUCKET"], Key=f"avatars/{job['userId']}.jpg")
    import boto3
    from botocore.config import Config
    client = boto3.client("cognito-idp", config=Config(connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2}))
    try:
        client.admin_delete_user(UserPoolId=os.environ["USER_POOL_ID"], Username=job["sub"])
    except client.exceptions.UserNotFoundException:
        pass  # A previous attempt may have deleted Cognito before a DB failure.
    with store.transaction() as state:
        current_job = next(j for j in state["accountDeletions"] if j["id"] == identifier)
        if current_job["status"] == "deleted":
            return
        uid = job["userId"]
        user = next(u for u in state["users"] if u["id"] == uid)
        # Keep measured organization usage without retaining the person's profile.
        rows = [r for key in ("requests", "adminRequests") for r in state[key] if r["userId"] == uid]
        if rows and not any(u["id"] == DELETED_USER_ID for u in state["users"]):
            state["users"].append({"id": DELETED_USER_ID, "cognitoSub": "internal:deleted-accounts",
                                   "name": "Cuentas eliminadas", "email": "", "status": "inactive", "avatarInitials": "CE"})
        for row in rows:
            row["userId"] = DELETED_USER_ID
            if row["status"] == "AUTHORIZED":
                row.update(status="FAILED", inputTokens=0, outputTokens=0, totalTokens=0,
                           usageKnown=True, completedAt=utcnow().isoformat())
        for key in ("organizationMemberships", "areaMemberships"):
            state[key] = [r for r in state[key] if r["userId"] != uid]
        state["businessRequests"] = [r for r in state["businessRequests"]
                                      if r["contactEmail"].strip().lower() != user["email"].lower()]
        state["users"] = [u for u in state["users"] if u["id"] != uid]
        current_job.clear()
        current_job.update(id=identifier, status="deleted", completedAt=utcnow().isoformat())


def retry_account_deletions(store):
    with store.transaction() as state:
        pending = [j["id"] for j in state["accountDeletions"] if j["status"] == "deleting"][:5]
    failures = 0
    for identifier in pending:
        try:
            finish_account_deletion(store, identifier)
        except Exception:
            failures += 1
            LOG.error("Account deletion remains pending; retry scheduled")
    if failures:
        raise RuntimeError("Account deletion retry incomplete")
    return {"processed": len(pending)}


class ApiError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


def require(ok, message="No tenés permisos para esta operación.", status=403, code="FORBIDDEN"):
    if not ok:
        raise ApiError(status, code, message)


def text(value, field, maximum=160):
    require(isinstance(value, str) and 1 <= len(value.strip()) <= maximum,
            f"El campo {field} es inválido.", 422, "INVALID_INPUT")
    return value.strip()


def integer(value, field, maximum=1_000_000_000):
    require(type(value) is int and 0 <= value <= maximum, f"El campo {field} es inválido.", 422, "INVALID_INPUT")
    return value


def date_value(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        raise ApiError(422, "INVALID_INPUT", "La fecha es inválida.") from None


def new_id():
    return str(uuid.uuid4())


def utcnow():
    return datetime.now(timezone.utc)


def current(record, today):
    return bool(record and record.get("status") == "active"
                and record.get("startsAt", today) <= today
                and (not record.get("endsAt") or record["endsAt"] >= today))


def groups(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return re.findall(r"[A-Za-z0-9_-]+", value)
    return []


def active_platform_admin(user):
    unlimited_sub = os.getenv("DESKTOP_UNLIMITED_SUB", "").strip()
    if not unlimited_sub or user.get("cognitoSub") != unlimited_sub:
        return False
    import boto3
    response = boto3.client("cognito-idp").admin_list_groups_for_user(
        UserPoolId=os.environ["USER_POOL_ID"], Username=user["cognitoSub"])
    return any(group["GroupName"] == "AUTOCLICK_ADMIN" for group in response["Groups"])


def decode_avatar(encoded):
    """Accept bounded, small JPEG thumbnails only; never SVG or arbitrary URLs."""
    require(isinstance(encoded, str) and len(encoded) <= 140000,
            "La foto es demasiado grande.", 422, "INVALID_PHOTO")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise ApiError(422, "INVALID_PHOTO", "La foto es inválida.") from None
    valid = len(data) <= 100 * 1024 and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9")
    dimensions = None
    offset = 2
    while valid and offset + 4 <= len(data):
        if data[offset] != 255:
            break
        marker = data[offset + 1]
        length = int.from_bytes(data[offset + 2:offset + 4], "big")
        if length < 2 or offset + 2 + length > len(data):
            break
        if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
            dimensions = (int.from_bytes(data[offset + 5:offset + 7], "big"), int.from_bytes(data[offset + 7:offset + 9], "big"))
            break
        offset += 2 + length
    require(valid and dimensions is not None and all(1 <= size <= 512 for size in dimensions),
            "Usá una foto JPG válida de hasta 512 × 512 píxeles.", 422, "INVALID_PHOTO")
    return data


def avatar_storage():
    import boto3
    from botocore.config import Config
    return boto3.client("s3", config=Config(signature_version="s3v4", connect_timeout=3, read_timeout=5, retries={"total_max_attempts": 2}))


def save_avatar(user, encoded):
    data = decode_avatar(encoded)
    revision = new_id()
    # A fixed key prevents orphan uploads; the revision changes signed cache URLs.
    avatar_storage().put_object(Bucket=os.environ["AVATAR_BUCKET"], Key=f"avatars/{user['id']}.jpg",
                              Body=data, ContentType="image/jpeg", CacheControl="private, max-age=300")
    user["avatarRevision"] = revision


def attach_avatar_urls(result):
    if not isinstance(result, dict) or "users" not in result:
        return result
    client = None
    for user in result["users"]:
        revision = user.pop("avatarRevision", None)
        if revision:
            client = client or avatar_storage()
            user["avatarUrl"] = client.generate_presigned_url("get_object", Params={
                "Bucket": os.environ["AVATAR_BUCKET"], "Key": f"avatars/{user['id']}.jpg",
                "ResponseContentDisposition": f'inline; filename="{revision}.jpg"',
            }, ExpiresIn=3600)
    return result


class Service:
    def __init__(self, state, identity=None, now=None):
        self.s = state
        self.identity = identity or {}
        self.now = now or utcnow()
        self.today = self.now.date().isoformat()
        self.period = self.today[:7]
        self.user = None
        self.admin = False

    def item(self, collection, identifier):
        result = next((x for x in self.s[collection] if x["id"] == identifier), None)
        require(result is not None, "El recurso no está disponible.", 404, "NOT_FOUND")
        return result

    def sign_in(self, allow_inactive=False, allow_deleting=False):
        sub = self.identity.get("sub")
        require(bool(sub), "Iniciá sesión para continuar.", 401, "UNAUTHENTICATED")
        job = next((j for j in self.s["accountDeletions"] if j["id"] == deletion_key(sub)), None)
        require(not job or (allow_deleting and job["status"] == "deleting"),
                "La eliminación de esta cuenta fue solicitada y el acceso está bloqueado.", 403, "ACCOUNT_DELETED")
        self.user = next((x for x in self.s["users"] if x.get("cognitoSub") == sub), None)
        if self.user is None:
            email = text(self.identity.get("email"), "email", 254).lower()
            name = self.identity.get("name") or email.split("@")[0]
            self.user = {"id": new_id(), "cognitoSub": sub, "name": name,
                         "email": email, "status": "active", "avatarInitials": name[:2].upper()}
            self.s["users"].append(self.user)
        require(self.user["status"] == "active" or (allow_inactive and self.user["status"] == "inactive")
                or (allow_deleting and self.user["status"] == "deleting"),
                "Tu cuenta está desactivada. Contactá a un administrador de AutoClick para reactivarla.",
                403, "ACCOUNT_INACTIVE")
        self.admin = "AUTOCLICK_ADMIN" in groups(self.identity.get("groups"))

    def membership(self, org_id, user_id=None):
        uid = user_id or self.user["id"]
        return next((x for x in self.s["organizationMemberships"]
                     if x["organizationId"] == org_id and x["userId"] == uid
                     and current(x, self.today)), None)

    def desktop_unlimited(self):
        unlimited_sub = os.getenv("DESKTOP_UNLIMITED_SUB", "").strip()
        return bool(unlimited_sub and self.admin and self.user.get("cognitoSub") == unlimited_sub)

    def organization_assignment(self):
        assignments = [m for m in self.s["organizationMemberships"] if m["userId"] == self.user["id"]]
        require(len(assignments) <= 1, "La asignación de tu organización necesita una corrección administrativa. Contactá al administrador.",
                409, "ORGANIZATION_ASSIGNMENT_INVALID")
        return assignments[0] if assignments else None

    def require_unassigned_user(self, user_id):
        # Inactive or expired memberships retain the user's organization.
        require(not any(m["userId"] == user_id for m in self.s["organizationMemberships"]),
                "La persona ya está asignada a una organización. Cada usuario puede pertenecer a una sola organización.",
                409, "USER_ALREADY_ASSIGNED")

    def desktop_organization(self):
        # Desktop belongs to the account's active organization, not a client
        # preference. Platform administration does not confer Desktop membership.
        assignment = self.organization_assignment()
        org = next((o for o in self.s["organizations"] if assignment and o["id"] == assignment["organizationId"]), None)
        require(current(assignment, self.today) and current(org, self.today), "Para ingresar a Desktop, un administrador debe incorporarte a una organización activa.",
                403, "DESKTOP_MEMBERSHIP_REQUIRED")
        return org

    def desktop_areas(self, org):
        member = self.membership(org["id"])
        owner = member and member["role"] == "ORGANIZATION_OWNER"
        assigned = {m["areaId"] for m in self.s["areaMemberships"]
                    if m["userId"] == self.user["id"] and current(m, self.today)}
        # Organizational owners retain their existing access to all their areas.
        # A global admin role alone does not broaden an enterprise user's scope.
        return [a for a in self.s["areas"] if a["organizationId"] == org["id"]
                and current(a, self.today) and (owner or a["id"] in assigned)]

    def desktop_area(self, org):
        areas = self.desktop_areas(org)
        require(areas, "Un administrador debe asignarte un área activa para usar IA.",
                403, "DESKTOP_AREA_REQUIRED")
        # Configured monthly limit, not remaining balance. Ties are stable by ID.
        return min(areas, key=lambda a: (-a["tokenLimit"], a["id"]))

    def desktop_session(self):
        if self.desktop_unlimited():
            return {"user": {k: v for k, v in self.user.items() if k != "cognitoSub"},
                    "organization": None, "organizations": [], "areas": [], "tokenUsage": [],
                    "period": self.period, "unlimited": True}
        org = self.desktop_organization()
        # Use membership permissions, including for platform administrators.
        member_view = Service(self.s, now=self.now)
        member_view.user = self.user
        profile = member_view.portal(org["id"])
        return {"user": profile["user"], "organization": org, "organizations": [org],
                "areas": self.desktop_areas(org),
                "tokenUsage": [r for r in profile["tokenUsage"] if r["organizationId"] == org["id"]],
                "period": self.period}

    def org_access(self, org_id, owner=False):
        org = self.item("organizations", org_id)
        member = self.membership(org_id)
        require(self.admin or (current(org, self.today) and member
                and (not owner or member["role"] == "ORGANIZATION_OWNER")))
        return org

    def area_access(self, area_id, manage=False):
        area = self.item("areas", area_id)
        self.org_access(area["organizationId"])
        member = self.membership(area["organizationId"])
        owner = self.admin or (member and member["role"] == "ORGANIZATION_OWNER")
        am = next((x for x in self.s["areaMemberships"] if x["areaId"] == area_id
                   and x["userId"] == self.user["id"] and current(x, self.today)), None)
        require(owner or (current(area, self.today) and am and (not manage or am["role"] == "AREA_ADMIN")))
        return area, bool(owner)

    def expire(self):
        for req in self.s["requests"] + self.s["adminRequests"]:
            if req["status"] == "AUTHORIZED" and req["expiresAt"] <= self.now.isoformat():
                req["status"] = "EXPIRED"
        # Only the trusted worker settles RUNNING requests with measured usage.

    def usage(self, org_id, area_id=None):
        rows = [x for x in self.s["requests"] if x["organizationId"] == org_id
                and x["period"] == self.period and (not area_id or x["areaId"] == area_id)]
        return {"used": sum(x.get("totalTokens", 0) for x in rows if x["status"] in ("COMPLETED", "FAILED")),
                "reserved": sum(x["reservedTokens"] for x in rows if x["status"] in ("AUTHORIZED", "RUNNING"))}

    def portal(self, selected=None):
        if self.admin:
            orgs = self.s["organizations"]
            org = next((o for o in orgs if o["id"] == selected), None)
        else:
            assignment = self.organization_assignment()
            orgs = [o for o in self.s["organizations"] if assignment and o["id"] == assignment["organizationId"] and current(assignment, self.today)]
            org = orgs[0] if orgs else None
            require(not selected or (org and selected == org["id"]), "La organización está determinada por tu cuenta y no puede cambiarse desde la aplicación.",
                    403, "ORGANIZATION_SELECTION_NOT_ALLOWED")
        org_ids = {o["id"] for o in orgs}
        owner_ids = {o["id"] for o in orgs if self.admin or (self.membership(o["id"]) or {}).get("role") == "ORGANIZATION_OWNER"}
        own_areas = {m["areaId"] for m in self.s["areaMemberships"] if m["userId"] == self.user["id"] and current(m, self.today)}
        areas = [a for a in self.s["areas"] if a["organizationId"] in org_ids and (a["organizationId"] in owner_ids or a["id"] in own_areas)]
        managed = {a["id"] for a in areas if a["organizationId"] in owner_ids or any(m["areaId"] == a["id"] and m["userId"] == self.user["id"] and m["role"] == "AREA_ADMIN" and current(m, self.today) for m in self.s["areaMemberships"])}
        ams = [m for m in self.s["areaMemberships"] if m["areaId"] in managed or (m["areaId"] in own_areas and m["userId"] == self.user["id"])]
        managed_orgs = owner_ids | {a["organizationId"] for a in areas if a["id"] in managed}
        oms = [m for m in self.s["organizationMemberships"] if m["organizationId"] in org_ids and (m["organizationId"] in managed_orgs or m["userId"] == self.user["id"])]
        uids = {self.user["id"]} | {m["userId"] for m in oms} | {m["userId"] for m in ams}
        users = [{k: v for k, v in u.items() if k != "cognitoSub"} for u in self.s["users"] if self.admin or u["id"] in uids]
        records = [r for r in self.s["requests"] if r["organizationId"] in org_ids and (r["organizationId"] in owner_ids or r["areaId"] in managed or r["userId"] == self.user["id"])]
        aggregate = {}
        for r in records:
            key = (r["organizationId"], r["areaId"], r["userId"], r["period"])
            row = aggregate.setdefault(key, {"id": ":".join(key), "organizationId": key[0], "areaId": key[1], "userId": key[2], "period": key[3], "tokensUsed": 0, "reservedTokens": 0})
            row["tokensUsed"] += r.get("totalTokens", 0) if r["status"] in ("COMPLETED", "FAILED") else 0
            row["reservedTokens"] += r["reservedTokens"] if r["status"] in ("AUTHORIZED", "RUNNING") else 0
        role = "AREA_MEMBER"
        if self.admin:
            role = "AUTOCLICK_ADMIN"
        elif org and org["id"] in owner_ids:
            role = "ORGANIZATION_OWNER"
        elif org and any(a["organizationId"] == org["id"] and a["id"] in managed for a in areas):
            role = "AREA_ADMIN"
        return {"user": next(u for u in users if u["id"] == self.user["id"]), "role": role,
                "desktopUnlimited": self.desktop_unlimited(),
                "organization": org, "organizations": orgs, "areas": areas, "users": users,
                "organizationMemberships": oms, "areaMemberships": ams, "tokenUsage": list(aggregate.values()),
                "period": self.period, "desktopVersion": os.getenv("DESKTOP_VERSION", "3.0"),
                "downloadUrl": "/v1/desktop/download" if os.getenv("DESKTOP_RELEASE_BUCKET") else "",
                "businessRequests": self.s["businessRequests"] if self.admin else []}

    def dispatch(self, method, path, body, query):
        self.expire()
        if path == "/v1/business-requests" and method == "POST":
            email = text(body.get("contactEmail"), "correo", 254).lower()
            require(bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)), "El correo es inválido.", 422, "INVALID_INPUT")
            row = {"id": new_id(), "companyName": text(body.get("companyName"), "empresa"),
                   "contactName": text(body.get("contactName"), "contacto"), "contactEmail": email,
                   "estimatedUsers": integer(body.get("estimatedUsers"), "usuarios", 100000),
                   "useCase": text(body.get("useCase"), "caso de uso", 2000),
                   "notes": str(body.get("notes", ""))[:2000], "status": "pending", "createdAt": self.now.isoformat()}
            require(row["estimatedUsers"] > 0, "Indicá al menos un usuario.", 422, "INVALID_INPUT")
            self.s["businessRequests"].append(row)
            return {"id": row["id"], "status": "pending"}
        if path in ("/v1/ai/validate", "/v1/ai/complete", "/v1/ai/fail"):
            require(self.identity.get("worker") is True)
            return self.worker(path, body)
        deactivating = method == "POST" and path == "/v1/me/deactivate"
        deleting = method == "DELETE" and path == "/v1/me"
        self.sign_in(allow_inactive=deactivating or deleting, allow_deleting=deleting)
        if deleting:
            require(not self.admin, "La baja de una cuenta administradora debe gestionarla otro administrador.", 409, "SELF_SUSPEND")
            require(set(body) == {"confirmationEmail"} and isinstance(body.get("confirmationEmail"), str)
                    and body["confirmationEmail"].strip().lower() == self.user["email"].lower(),
                    "Escribí el correo de tu cuenta para confirmar la eliminación.", 422, "INVALID_CONFIRMATION")
            identifier = deletion_key(self.identity["sub"])
            if not any(j["id"] == identifier for j in self.s["accountDeletions"]):
                self.s["accountDeletions"].append({"id": identifier, "status": "deleting", "sub": self.identity["sub"],
                                                 "userId": self.user["id"], "requestedAt": self.now.isoformat()})
            self.user["status"] = "deleting"
            return {"accountDeletion": identifier}
        if deactivating:
            require(not self.admin, "Un administrador de AutoClick no puede desactivar su propia cuenta.", 409, "SELF_SUSPEND")
            require(set(body) == {"confirmationEmail"} and isinstance(body.get("confirmationEmail"), str)
                    and body["confirmationEmail"].strip().lower() == self.user["email"].lower(),
                    "Escribí el correo de tu cuenta para confirmar la desactivación.", 422, "INVALID_CONFIRMATION")
            if self.user["status"] == "active":
                self.user.update(status="inactive", deactivatedAt=self.now.isoformat())
            return {"ok": True, "status": "inactive"}
        if path == "/v1/me/avatar" and method == "PATCH":
            save_avatar(self.user, body.get("image"))
            return {"ok": True}
        if path == "/v1/me/avatar" and method == "DELETE":
            avatar_storage().delete_object(Bucket=os.environ["AVATAR_BUCKET"], Key=f"avatars/{self.user['id']}.jpg")
            self.user.pop("avatarRevision", None)
            return {"ok": True}
        if method == "GET" and path == "/v1/desktop/session":
            return self.desktop_session()
        if method == "GET" and path == "/v1/desktop/download":
            if not self.desktop_unlimited():
                self.desktop_organization()
            return {"desktopRelease": True}
        if method == "GET" and path in ("/v1/portal", "/v1/me", "/v1/me/entitlements", "/v1/me/usage"):
            return self.portal(query.get("organizationId"))
        if method == "PATCH" and path == "/v1/me":
            self.user["name"] = text(body.get("name"), "nombre")
            self.user["avatarInitials"] = self.user["name"][:2].upper()
            return {"ok": True}
        if method == "POST" and path == "/v1/ai/authorize":
            return self.authorize(body)
        parts = path.strip("/").split("/")
        if path == "/v1/organizations":
            if method == "GET":
                return self.portal()["organizations"]
            require(method == "POST" and self.admin)
            owner = self.item("users", body.get("ownerId"))
            require(owner["status"] == "active")
            self.require_unassigned_user(owner["id"])
            org = {"id": new_id(), "name": text(body.get("name"), "nombre"), "status": "active",
                   "plan": "PROFESIONAL", "createdAt": self.today, "startsAt": self.today,
                   "endsAt": None, "monthlyTokenLimit": integer(body.get("monthlyTokenLimit", 0), "límite")}
            self.s["organizations"].append(org)
            self.s["organizationMemberships"].append({"id": new_id(), "organizationId": org["id"], "userId": owner["id"], "role": "ORGANIZATION_OWNER", "status": "active", "startsAt": self.today, "endsAt": None})
            return org
        if len(parts) >= 3 and parts[1] == "organizations":
            org = self.org_access(parts[2], owner=method != "GET")
            if len(parts) == 3:
                if method == "GET":
                    return org
                require(method == "PATCH")
                allowed = {"name"} | ({"status", "startsAt", "endsAt", "monthlyTokenLimit"} if self.admin else set())
                self.patch(org, body, allowed)
                require(sum(a["tokenLimit"] for a in self.s["areas"] if a["organizationId"] == org["id"]) <= org["monthlyTokenLimit"], "El límite no cubre los tokens asignados a las áreas.", 409, "LIMIT_CONFLICT")
                return org
            if len(parts) == 4 and parts[3] == "areas":
                if method == "GET":
                    return [a for a in self.portal(org["id"])["areas"] if a["organizationId"] == org["id"]]
                require(method == "POST")
                area = {"id": new_id(), "organizationId": org["id"], "name": text(body.get("name"), "nombre"), "status": "active", "tokenLimit": 0, "createdAt": self.today}
                self.s["areas"].append(area)
                return area
            if len(parts) == 4 and parts[3] == "members" and method == "POST":
                target = next((u for u in self.s["users"] if u["id"] == body.get("userId") or u["email"].lower() == str(body.get("email", "")).lower()), None)
                require(target is not None and target["status"] == "active", "La persona debe registrarse e iniciar sesión primero.", 422, "USER_NOT_REGISTERED")
                require(not any(m["organizationId"] == org["id"] and m["userId"] == target["id"] for m in self.s["organizationMemberships"]), "La persona ya pertenece a la organización.", 409, "ALREADY_MEMBER")
                self.require_unassigned_user(target["id"])
                m = {"id": new_id(), "organizationId": org["id"], "userId": target["id"], "role": "ORGANIZATION_MEMBER", "status": "active", "startsAt": self.today, "endsAt": None}
                self.s["organizationMemberships"].append(m)
                return m
        if len(parts) == 3 and parts[1] == "organization-memberships" and method == "PATCH":
            m = self.item("organizationMemberships", parts[2])
            self.org_access(m["organizationId"], owner=True)
            require(m["role"] != "ORGANIZATION_OWNER" or self.admin, "Solo administración puede modificar al propietario.")
            self.patch(m, body, {"status", "startsAt", "endsAt"})
            return m
        if len(parts) >= 3 and parts[1] == "areas":
            area, owner = self.area_access(parts[2], manage=method != "GET")
            if len(parts) == 3 and method == "PATCH":
                require(owner)
                self.patch(area, body, {"name", "status", "tokenLimit"})
                org = self.item("organizations", area["organizationId"])
                require(sum(a["tokenLimit"] for a in self.s["areas"] if a["organizationId"] == org["id"]) <= org["monthlyTokenLimit"], "La asignación supera el límite de la organización.", 409, "LIMIT_CONFLICT")
                return area
            if len(parts) == 4 and parts[3] == "usage" and method == "GET":
                require(owner or any(m["areaId"] == area["id"] and m["userId"] == self.user["id"] and m["role"] == "AREA_ADMIN" and current(m, self.today) for m in self.s["areaMemberships"]))
                return self.usage(area["organizationId"], area["id"])
            if len(parts) >= 4 and parts[3] == "members":
                if method == "GET":
                    return [m for m in self.portal()["areaMemberships"] if m["areaId"] == area["id"]]
                target = None
                if len(parts) == 5:
                    target = self.item("areaMemberships", parts[4])
                    require(target["areaId"] == area["id"])
                    require(owner or target["role"] != "AREA_ADMIN")
                if method == "DELETE" and target:
                    self.s["areaMemberships"].remove(target)
                    return {"ok": True}
                require(method in ("POST", "PATCH"))
                uid = target["userId"] if target else body.get("userId")
                user = self.item("users", uid)
                require(user["status"] == "active" and self.membership(area["organizationId"], uid), "Se requiere una membresía organizacional activa.", 422, "MEMBERSHIP_REQUIRED")
                role = body.get("role", "AREA_MEMBER")
                require(role in ("AREA_ADMIN", "AREA_MEMBER") and (owner or role == "AREA_MEMBER"))
                existing = next((m for m in self.s["areaMemberships"] if m["userId"] == uid and m["areaId"] == area["id"]), None)
                require(owner or not existing or existing["role"] != "AREA_ADMIN")
                if not existing:
                    existing = {"id": new_id(), "areaId": area["id"], "userId": uid}
                    self.s["areaMemberships"].append(existing)
                require(body.get("status", "active") in ("active", "inactive", "expired"), "Estado inválido.", 422, "INVALID_INPUT")
                existing.update(role=role, status=body.get("status", "active"))
                return existing
        if len(parts) == 3 and parts[1] == "business-requests" and method == "PATCH":
            require(self.admin)
            r = self.item("businessRequests", parts[2])
            require(body.get("status") in ("pending", "reviewing", "approved", "rejected"), "Estado inválido.", 422, "INVALID_INPUT")
            r["status"] = body["status"]
            return r
        if len(parts) == 3 and parts[1] == "users" and method == "PATCH":
            require(self.admin)
            target = self.item("users", parts[2])
            require(target["id"] != DELETED_USER_ID and target["status"] != "deleting",
                    "Una eliminación solicitada no puede reactivarse.", 409, "ACCOUNT_DELETED")
            require(target["id"] != self.user["id"], "No podés suspender tu propia cuenta.", 409, "SELF_SUSPEND")
            self.patch(target, body, {"status"})
            return {"ok": True}
        raise ApiError(404, "NOT_FOUND", "La operación no existe.")

    def patch(self, record, body, allowed):
        require(bool(body) and set(body) <= allowed, "Los campos enviados no están permitidos.", 422, "INVALID_INPUT")
        for key, value in body.items():
            if key in ("monthlyTokenLimit", "tokenLimit"):
                value = integer(value, key)
            elif key == "status":
                require(value in ("active", "inactive", "expired"), "Estado inválido.", 422, "INVALID_INPUT")
            elif key == "name":
                value = text(value, key)
            elif key in ("startsAt", "endsAt"):
                value = None if key == "endsAt" and value is None else date_value(value)
            record[key] = value
        require(not record.get("endsAt") or record["endsAt"] >= record.get("startsAt", self.today), "El vencimiento es anterior al inicio.", 422, "INVALID_INPUT")

    def require_balance(self, org, area):
        # Admission only: an already-started query always finishes at full capacity.
        for limit, usage in ((org["monthlyTokenLimit"], self.usage(org["id"])), (area["tokenLimit"], self.usage(org["id"], area["id"]))):
            require(usage["used"] < limit, "No quedan tokens disponibles en la organización o el área.", 429, "QUOTA_EXCEEDED")

    def authorize(self, body):
        rid = str(body.get("requestId", ""))
        try:
            uuid.UUID(rid)
        except ValueError:
            raise ApiError(422, "INVALID_INPUT", "requestId debe ser UUID.") from None
        unlimited = self.desktop_unlimited()
        org = area = None
        reserve = 0  # Retained in the response for older clients; never withhold tokens.
        if not unlimited:
            org = self.desktop_organization()
            require(body.get("organizationId", org["id"]) == org["id"], "La organización no corresponde a tu cuenta.")
            # Ignore legacy clients' areaId; quota attribution is server-managed.
            area = self.desktop_area(org)
            self.require_balance(org, area)
        require(not any(r["id"] == rid for r in self.s["requests"] + self.s["adminRequests"]), "La solicitud ya fue registrada. Iniciá una nueva.", 409, "REQUEST_EXISTS")
        token = secrets.token_urlsafe(32)
        row = {"id": rid, "userId": self.user["id"], "organizationId": org["id"] if org else None, "areaId": area["id"] if area else None, "status": "AUTHORIZED", "period": self.period,
               "unlimited": unlimited,
               "reservedTokens": reserve, "authorizationHash": hashlib.sha256(token.encode()).hexdigest(),
               "expiresAt": (self.now + timedelta(minutes=2)).isoformat(), "createdAt": self.now.isoformat()}
        self.s["adminRequests" if unlimited else "requests"].append(row)
        return {"requestId": rid, "authorization": token, "expiresAt": row["expiresAt"], "reservedTokens": reserve}

    def worker(self, path, body):
        r = next((row for row in self.s["requests"] + self.s["adminRequests"] if row["id"] == body.get("requestId")), None)
        require(r is not None, "El recurso no está disponible.", 404, "NOT_FOUND")
        if path.endswith("validate"):
            token = str(body.get("authorization", ""))
            require(hmac.compare_digest(r["authorizationHash"], hashlib.sha256(token.encode()).hexdigest()), "La autorización es inválida.", 403, "INVALID_AUTHORIZATION")
            claim = body.get("claimId")
            if claim is not None:
                try:
                    claim = str(uuid.UUID(claim))
                except (ValueError, TypeError, AttributeError):
                    raise ApiError(422, "INVALID_INPUT", "claimId debe ser UUID.") from None
            if r["status"] == "RUNNING" and claim and r.get("claimId") == claim and r.get("worker") == self.identity["principal"]:
                return {"requestId": r["id"], "reservedTokens": r["reservedTokens"], "unlimited": r.get("unlimited", False)}
            require(r["status"] == "AUTHORIZED", "La autorización venció o ya fue utilizada.", 409, "AUTHORIZATION_USED")
            # Re-check revocations that happened between authorization and inference.
            self.user = self.item("users", r["userId"])
            require(self.user["status"] == "active")
            if r.get("unlimited"):
                require(active_platform_admin(self.user), "El acceso de administrador ya no está habilitado.")
            else:
                org = self.desktop_organization()
                require(org["id"] == r["organizationId"])
                area = self.desktop_area(org)
                self.require_balance(org, area)
                # Resolve current memberships/limits immediately before inference.
                # Once RUNNING, the recorded area stays fixed through all retries.
                r["areaId"] = area["id"]
            r.update(status="RUNNING", startedAt=self.now.isoformat(), worker=self.identity["principal"], claimId=claim)
            return {"requestId": r["id"], "reservedTokens": r["reservedTokens"], "unlimited": r.get("unlimited", False)}
        require(r.get("worker") == self.identity.get("principal"))
        status = "COMPLETED" if path.endswith("complete") else "FAILED"
        inp = body.get("inputTokens")
        out = body.get("outputTokens")
        # Charge only measured tokens, including measured rounds before a failure.
        measured = inp is not None and out is not None
        known = measured and body.get("usageKnown", True) is True
        if measured:
            inp, out = integer(inp, "inputTokens"), integer(out, "outputTokens")
        require(known or status == "FAILED", "Faltan las métricas reales.", 422, "USAGE_REQUIRED")
        charge = inp + out if measured else 0
        if r["status"] in ("COMPLETED", "FAILED"):
            require(r["status"] == status and r["totalTokens"] == charge and r.get("inputTokens") == inp and r.get("outputTokens") == out and r.get("usageKnown") == known, "El cierre difiere del registrado.", 409, "COMPLETION_CONFLICT")
            return {"ok": True, "duplicate": True}
        require(r["status"] == "RUNNING", "La solicitud no está en ejecución.", 409, "INVALID_STATE")
        r.update(status=status, inputTokens=inp, outputTokens=out, totalTokens=charge,
                 usageKnown=known, completedAt=self.now.isoformat())
        return {"ok": True, "usageKnown": known}


class DataStore:
    def __init__(self):
        import boto3
        from botocore.config import Config
        self.client = boto3.client("rds-data", config=Config(retries={"mode": "standard", "total_max_attempts": 3}))
        self.args = {"resourceArn": os.environ["DB_CLUSTER_ARN"], "secretArn": os.environ["DB_SECRET_ARN"], "database": "autoclick"}

    def execute(self, sql, params=None, tx=None):
        args = dict(self.args, sql=sql, includeResultMetadata=True)
        if tx:
            args["transactionId"] = tx
        if params:
            args["parameters"] = [{"name": k, "value": {"stringValue": str(v)}} for k, v in params.items()]
        return self.client.execute_statement(**args)

    def migrate(self):
        for sql in SCHEMA:
            self.execute(sql)

    @contextmanager
    def transaction(self):
        # Aurora may need a few seconds to resume from zero ACU. No transaction
        # exists yet, so retrying admission cannot duplicate a business mutation.
        deadline = time.monotonic() + 18
        while True:
            try:
                tx = self.client.begin_transaction(**self.args)["transactionId"]
                break
            except self.client.exceptions.DatabaseResumingException:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(2)
        try:
            self.execute("SELECT pg_advisory_xact_lock(5072026)::text", tx=tx)
            state = {}
            for key, table in TABLES.items():
                # Keyset pages avoid the Data API response-size limit. Each document
                # is bounded on input; all pages remain in the same transaction.
                state[key], after = [], ""
                while True:
                    rows = self.execute(f"SELECT id, data::text FROM {table} WHERE id > :after ORDER BY id LIMIT 100", {"after": after}, tx).get("records", [])
                    state[key].extend(json.loads(row[1]["stringValue"]) for row in rows)
                    if len(rows) < 100:
                        break
                    after = rows[-1][0]["stringValue"]
            before = copy.deepcopy(state)
            yield state
            # Insert the technical usage owner and reassign FK references before
            # removing a deleted profile. Parent inserts precede child updates.
            for key, table in TABLES.items():
                old = {x["id"]: x for x in before[key]}
                for row in state[key]:
                    if old.get(row["id"]) != row:
                        self.execute(f"INSERT INTO {table}(id,data) VALUES (:id,CAST(:data AS jsonb)) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data", {"id": row["id"], "data": json.dumps(row)}, tx)
            for key, table in reversed(list(TABLES.items())):
                old = {x["id"]: x for x in before[key]}
                new = {x["id"]: x for x in state[key]}
                for identifier in old.keys() - new.keys():
                    self.execute(f"DELETE FROM {table} WHERE id=:id", {"id": identifier}, tx)
            self.client.commit_transaction(resourceArn=self.args["resourceArn"], secretArn=self.args["secretArn"], transactionId=tx)
        except BaseException:
            self.client.rollback_transaction(resourceArn=self.args["resourceArn"], secretArn=self.args["secretArn"], transactionId=tx)
            raise


def identity_for(event):
    auth = event.get("requestContext", {}).get("authorizer", {})
    iam = auth.get("iam", {})
    worker_role = os.getenv("WORKER_ROLE_NAME", "autoclick-ia-worker")
    principal = iam.get("userArn", "")
    if f":assumed-role/{worker_role}/" in principal:
        return {"worker": True, "principal": worker_role}
    claims = auth.get("jwt", {}).get("claims", {})
    require(claims.get("token_use") == "access", "Se requiere un access token.", 401, "UNAUTHENTICATED")
    # GetUser verifies the access token and supplies verified user attributes;
    # access-token JWTs do not normally carry email/name.
    import boto3
    headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    token = headers.get("authorization", "").removeprefix("Bearer ")
    client = boto3.client("cognito-idp")
    try:
        user = client.get_user(AccessToken=token)
    except (client.exceptions.NotAuthorizedException, client.exceptions.UserNotFoundException):
        raise ApiError(401, "UNAUTHENTICATED", "La sesión ya no es válida. Iniciá sesión para continuar.") from None
    attrs = {a["Name"]: a["Value"] for a in user["UserAttributes"]}
    require(attrs.get("sub") == claims.get("sub") and attrs.get("email_verified") == "true", "Confirmá tu correo para continuar.", 403, "EMAIL_UNVERIFIED")
    return {"sub": attrs["sub"], "email": attrs.get("email"), "name": attrs.get("name"), "groups": claims.get("cognito:groups", [])}


def handler(event, context):
    correlation = getattr(context, "aws_request_id", new_id())
    try:
        store = DataStore()
        if event.get("task") == "migrate" and "requestContext" not in event:
            store.migrate()
            return {"ok": True}
        if event.get("task") == "retry-account-deletions" and "requestContext" not in event:
            return retry_account_deletions(store)
        method = event.get("requestContext", {}).get("http", {}).get("method", "")
        path = event.get("rawPath", "")
        raw = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw).decode()
        max_body = 145000 if method == "PATCH" and path == "/v1/me/avatar" else 16384
        require(len(raw.encode()) <= max_body, "La solicitud es demasiado grande.", 413, "BODY_TOO_LARGE")
        body = json.loads(raw)
        require(isinstance(body, dict), "Solicitud inválida.", 422, "INVALID_INPUT")
        public = method == "POST" and path == "/v1/business-requests"
        identity = {} if public else identity_for(event)
        with store.transaction() as state:
            result = Service(state, identity).dispatch(method, path, body, event.get("queryStringParameters") or {})
        status = 200
        if "accountDeletion" in result:
            try:
                finish_account_deletion(store, result["accountDeletion"])
                result = {"ok": True, "status": "deleted"}
            except Exception:
                # Durable request is committed; a scheduled worker retries it.
                LOG.error("Account deletion pending request_id=%s", correlation)
                result = {"ok": True, "status": "deleting"}
                status = 202
        result = attach_avatar_urls(result)
        if result == {"desktopRelease": True}:
            import boto3
            s3 = boto3.client("s3")
            obj = {"Bucket": os.environ["DESKTOP_RELEASE_BUCKET"], "Key": os.environ["DESKTOP_RELEASE_KEY"]}
            s3.head_object(**obj)
            result = {"url": s3.generate_presigned_url("get_object", Params=obj, ExpiresIn=300)}
        return {"statusCode": status, "headers": {"content-type": "application/json", "cache-control": "no-store"}, "body": json.dumps(result)}
    except ApiError as error:
        return {"statusCode": error.status, "headers": {"content-type": "application/json", "cache-control": "no-store"}, "body": json.dumps({"code": error.code, "message": error.message, "requestId": correlation})}
    except (ValueError, TypeError, KeyError):
        LOG.exception("Invalid request or configuration request_id=%s", correlation)
        return {"statusCode": 422, "body": json.dumps({"code": "INVALID_REQUEST", "message": "No se pudo procesar la solicitud.", "requestId": correlation})}
    except Exception as error:
        # Never log event/body/tokens. SDK exceptions may include SQL metadata only.
        code = getattr(error, "response", {}).get("Error", {}).get("Code", type(error).__name__)
        LOG.error("Control plane unavailable request_id=%s code=%s", correlation, code)
        return {"statusCode": 503, "headers": {"retry-after": "5"}, "body": json.dumps({"code": "SERVICE_UNAVAILABLE", "message": "El servicio no está disponible. Volvé a intentar.", "requestId": correlation})}
