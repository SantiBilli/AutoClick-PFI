import copy
import hashlib
import importlib.resources
import json
import unicodedata
from typing import Any

from autoclick_mcp.models import (
    ActionDetail,
    ActionFieldDetail,
    ActionOutputDetail,
    ActionSchemasData,
    ActionSearchData,
    ActionSummary,
    McpIssue,
    McpResult,
)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


class ActionCatalog:
    def __init__(self, actions: list[dict[str, Any]] | None = None) -> None:
        self._raw_actions = copy.deepcopy(actions) if actions is not None else self._load_canonical_actions()
        ids = [action.get("id") for action in self._raw_actions]
        if any(not isinstance(action_id, str) or not action_id for action_id in ids):
            raise ValueError("catalog contains an invalid action ID")
        if len(ids) != len(set(ids)):
            raise ValueError("catalog contains duplicate action IDs")
        self._actions_by_id: dict[str, dict[str, Any]] = {
            a["id"]: a for a in self._raw_actions
        }
        canonical = json.dumps(
            self._raw_actions, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.catalog_version = 1
        self.catalog_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _load_canonical_actions(self) -> list[dict[str, Any]]:
        try:
            data = importlib.resources.files("autoclick_mcp").joinpath("data")
            metadata = json.loads(
                data.joinpath("catalog_metadata.json").read_text(encoding="utf-8")
            )
            actions = json.loads(
                data.joinpath(metadata["registryResource"]).read_text(encoding="utf-8")
            )
            if not isinstance(actions, list) or not actions:
                raise ValueError("packaged action registry has no actions")
            clean_actions: list[dict[str, Any]] = []
            for raw in actions:
                if not isinstance(raw, dict):
                    raise ValueError("packaged action registry contains an invalid action")
                action = {
                    key: copy.deepcopy(value)
                    for key, value in raw.items()
                    if not (key == "platform" and value is None)
                    and not (key == "slots" and value == [])
                }
                fields = action.get("fields")
                if not isinstance(fields, list):
                    raise ValueError("packaged action registry contains invalid fields")
                action["fields"] = [
                    {key: value for key, value in field.items() if value is not None}
                    for field in fields
                ]
                clean_actions.append(action)
            canonical = json.dumps(
                clean_actions,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            calculated_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if metadata.get("catalogVersion") != 1:
                raise ValueError("packaged action registry has an invalid catalog version")
            if metadata.get("actionCount") != len(clean_actions):
                raise ValueError("packaged action registry has a mismatched action count")
            if metadata.get("catalogHash") != calculated_hash:
                raise ValueError("packaged action registry has a mismatched catalog hash")
            return clean_actions
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise RuntimeError("cannot load canonical packaged action registry") from error

    def get_all_actions(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._raw_actions)

    def search_actions(
        self,
        query: str,
        category: str | None = None,
        platform: str | None = None,
        limit: int = 5,
    ) -> McpResult[ActionSearchData]:
        if not query or len(query.strip()) < 1:
            return McpResult(
                ok=False,
                data=None,
                issues=[
                    McpIssue(
                        code="INVALID_ARGUMENT",
                        message="El parámetro 'query' es obligatorio y no puede estar vacío.",
                        path="query",
                    )
                ],
            )
        clean_limit = max(1, min(limit, 10))
        plain_query = _plain(query)
        query_words = plain_query.split()

        scored: list[tuple[int, dict[str, Any]]] = []
        for action in self._raw_actions:
            act_cat = action.get("category", "")
            if category and act_cat.casefold() != category.casefold():
                continue
            act_plat = action.get("platform")
            if platform and platform != "any" and act_plat and act_plat.casefold() != platform.casefold():
                continue

            score = 0
            act_id = _plain(action.get("id", ""))
            act_title = _plain(action.get("title", ""))
            act_desc = _plain(action.get("description", ""))
            act_cat_name = _plain(action.get("categoryName", action.get("category_name", "")))
            field_names = " ".join(_plain(f.get("name", "")) for f in action.get("fields", []))

            target_corpus = f"{act_id} {act_title} {act_desc} {act_cat} {act_cat_name} {field_names}"

            if plain_query in target_corpus:
                score += 10
            for word in query_words:
                if word in act_id or word in act_title:
                    score += 5
                elif word in act_desc:
                    score += 2
                elif word in target_corpus:
                    score += 1

            if score > 0:
                scored.append((score, action))

        scored.sort(key=lambda x: x[0], reverse=True)
        matched_actions = scored[:clean_limit]

        summaries = []
        for _, action in matched_actions:
            outputs = action.get("outputs", [])
            output_val = action.get("output")
            has_output = bool(outputs or output_val)
            summaries.append(
                ActionSummary(
                    id=action["id"],
                    category=action.get("category", ""),
                    categoryName=action.get("categoryName", action.get("category_name", "")),
                    title=action.get("title", ""),
                    summary=action.get("description", ""),
                    platform=action.get("platform"),
                    hasOutput=has_output,
                    slots=action.get("slots", []),
                )
            )

        return McpResult(
            ok=True,
            data=ActionSearchData(
                actions=summaries,
                totalMatches=len(scored),
                catalogVersion=self.catalog_version,
                catalogHash=self.catalog_hash,
            ),
            issues=[],
        )

    def get_action_schemas(
        self, action_ids: list[str]
    ) -> McpResult[ActionSchemasData]:
        if not action_ids or not (1 <= len(action_ids) <= 10):
            return McpResult(
                ok=False,
                data=None,
                issues=[
                    McpIssue(
                        code="INVALID_ARGUMENT",
                        message="Se deben solicitar entre 1 y 10 identificadores únicos de acción.",
                        path="actionIds",
                    )
                ],
            )
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("duplicate action schema IDs are not allowed")

        details = []
        issues = []
        for aid in action_ids:
            raw = self._actions_by_id.get(aid)
            if not raw:
                issues.append(
                    McpIssue(
                        code="UNKNOWN_ACTION",
                        message=f"La acción '{aid}' no existe en el catálogo.",
                        actionId=aid,
                        path="actionIds",
                    )
                )
                continue

            fields = [
                ActionFieldDetail(
                    name=f["name"],
                    label=f.get("label", f["name"]),
                    type=f.get("type", "text"),
                    required=f.get("required", False),
                    min=f.get("min"),
                    max=f.get("max"),
                    minLength=f.get("minLength", f.get("min_length")),
                    maxLength=f.get("maxLength", f.get("max_length")),
                    pattern=f.get("pattern"),
                    options=f.get("options"),
                )
                for f in raw.get("fields", [])
            ]
            outputs = [
                ActionOutputDetail.model_validate(output).model_dump()
                for output in raw.get("outputs", [])
            ]
            output = raw.get("output")
            details.append(
                ActionDetail(
                    id=raw["id"],
                    category=raw.get("category", ""),
                    categoryName=raw.get("categoryName", raw.get("category_name", "")),
                    title=raw.get("title", ""),
                    description=raw.get("description", ""),
                    fields=fields,
                    defaults=raw.get("defaults", {}),
                    output=(
                        ActionOutputDetail.model_validate(output).model_dump()
                        if output is not None else None
                    ),
                    outputs=outputs,
                    slots=raw.get("slots", []),
                    platform=raw.get("platform"),
                )
            )

        return McpResult(
            ok=len(issues) == 0,
            data=ActionSchemasData(
                actions=details,
                catalogVersion=self.catalog_version,
                catalogHash=self.catalog_hash,
            ) if len(issues) == 0 else None,
            issues=issues,
        )
