"""Configure a cloned Windows checkout without provisioning cloud resources."""
import argparse
import configparser
import json
import os
from pathlib import Path
import sys

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Autoclick-IA"))


def write_missing(path: Path, text: str) -> None:
    # Exclusive creation preserves every existing local setting.
    if not path.exists():
        with path.open("x", encoding="utf-8", newline="\n") as output:
            output.write(text)
        print(f"Configuracion creada: {path.relative_to(ROOT)}")


def require_values(outputs: dict, names: tuple[str, ...]) -> None:
    missing = [name for name in names
               if not isinstance(outputs.get(name), str) or not outputs[name].strip()]
    if missing:
        raise RuntimeError("Completar Autoclick-Cloud/deployment.json: " + ", ".join(missing))


def configure_files(outputs: dict) -> None:
    require_values(outputs, ("ApiUrl", "Region", "UserPoolId", "DesktopClientId"))
    write_missing(ROOT / "Autoclick-IA/.env",
                  (ROOT / "Autoclick-IA/.env.example").read_text(encoding="utf-8"))
    write_missing(ROOT / "Autoclick-IA/.env.cloud", (
        f"AUTOCLICK_CLOUD_API_URL={outputs['ApiUrl']}\n"
        f"AUTOCLICK_CLOUD_REGION={outputs['Region']}\n"
        "AUTOCLICK_CLOUD_AWS_PROFILE=autoclick-worker\n"
        "AUTOCLICK_AI_HOST=127.0.0.1\nAUTOCLICK_AI_PORT=8001\n"
        "AUTOCLICK_AI_ALLOWED_ORIGINS=http://127.0.0.1:5173,"
        "http://localhost:5173,http://127.0.0.1:5180\n"))
    write_missing(ROOT / "Autoclick-App/frontend/.env.local", (
        f"VITE_AWS_REGION={outputs['Region']}\n"
        f"VITE_COGNITO_USER_POOL_ID={outputs['UserPoolId']}\n"
        f"VITE_COGNITO_CLIENT_ID={outputs['DesktopClientId']}\n"
        f"VITE_AUTOCLICK_CLOUD_URL={outputs['ApiUrl']}\n"
        "VITE_AUTOCLICK_AI_URL=http://127.0.0.1:8001\n"))


def configure_worker(outputs: dict, profile: str) -> None:
    config_path = Path(os.environ.get("AWS_CONFIG_FILE", Path.home() / ".aws/config"))
    config = configparser.RawConfigParser()
    config.read(config_path, encoding="utf-8-sig")
    section = f"profile {profile}"
    if config.has_section(section):
        return
    if profile != "autoclick-worker":
        raise RuntimeError(f"Falta el perfil AWS personalizado {profile}. Configuralo antes de iniciar.")
    identity = Path(os.environ["LOCALAPPDATA"]) / "AutoClick/WorkerIdentity"
    helper, cert, key = (identity / name for name in (
        "aws_signing_helper.exe", "worker.pem", "worker-key.pem"))
    missing = [path.name for path in (helper, cert, key) if not path.is_file()]
    if missing:
        raise RuntimeError(f"Falta la identidad AWS del worker en {identity}: {', '.join(missing)}. "
                           "El administrador del despliegue debe provisionar esta identidad en la PC.")
    command = (
        f'"{helper.as_posix()}" credential-process --certificate "{cert.as_posix()}" '
        f'--private-key "{key.as_posix()}" --trust-anchor-arn {outputs["WorkerTrustAnchorArn"]} '
        f'--profile-arn {outputs["WorkerProfileArn"]} --role-arn {outputs["WorkerRoleArn"]} '
        '--session-duration 900')
    config_path.parent.mkdir(parents=True, exist_ok=True)
    # Append only our absent section; preserve other profiles and their comments.
    with config_path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"\n[{section}]\nregion = {outputs['Region']}\ncredential_process = {command}\n")
    print("Perfil AWS autoclick-worker creado con las rutas de esta PC.")


def check_runtime(outputs: dict) -> None:
    from app.config import Settings

    require_values(outputs, ("WorkerTrustAnchorArn", "WorkerProfileArn", "WorkerRoleArn"))
    settings = Settings(_env_file=(ROOT / "Autoclick-IA/.env", ROOT / "Autoclick-IA/.env.cloud"))
    if settings.host != "127.0.0.1" or settings.port != 8001:
        raise RuntimeError("Este iniciador requiere el backend en 127.0.0.1:8001. "
                           "Ollama puede ser local o remoto: configura OLLAMA_BASE_URL en Autoclick-IA/.env.")
    if not settings.autoclick_cloud_api_url or not settings.autoclick_cloud_aws_profile:
        raise RuntimeError("Falta la autorizacion del worker en Autoclick-IA/.env.cloud.")
    frontend = {}
    for line in (ROOT / "Autoclick-App/frontend/.env.local").read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            frontend[name.strip()] = value.strip().strip("\"'")
    if frontend.get("VITE_AUTOCLICK_AI_URL", "").rstrip("/") != "http://127.0.0.1:8001":
        raise RuntimeError("VITE_AUTOCLICK_AI_URL debe ser http://127.0.0.1:8001 en frontend/.env.local.")
    if frontend.get("VITE_AUTOCLICK_CLOUD_URL", "").rstrip("/") != settings.autoclick_cloud_api_url.rstrip("/"):
        raise RuntimeError("Las URLs del control cloud deben coincidir en frontend/.env.local y .env.cloud.")
    configure_worker(outputs, settings.autoclick_cloud_aws_profile)
    session = boto3.Session(profile_name=settings.autoclick_cloud_aws_profile,
                            region_name=settings.autoclick_cloud_region)
    client = session.client("sts", config=Config(
        connect_timeout=5, read_timeout=10,
        retries={"mode": "standard", "total_max_attempts": 2},
    ))
    try:
        identity = client.get_caller_identity()
    finally:
        client.close()
    expected = outputs["WorkerRoleArn"].split(":")
    role = expected[5].split("/")[-1]
    if (identity["Account"] != expected[4]
            or not identity["Arn"].startswith(f"arn:aws:sts::{expected[4]}:assumed-role/{role}/")):
        raise RuntimeError("El perfil AWS no corresponde al rol limitado del worker AutoClick.")
    print("Identidad AWS del worker verificada; credenciales temporales vigentes.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        deployment_path = ROOT / "Autoclick-Cloud/deployment.json"
        if not deployment_path.is_file():
            raise RuntimeError("Falta Autoclick-Cloud/deployment.json. Solicitar la configuracion "
                               "del despliegue o completar una copia de deployment.example.json.")
        outputs = json.loads(deployment_path.read_text(encoding="utf-8-sig"))
        if not isinstance(outputs, dict):
            raise ValueError("deployment.json debe contener un objeto JSON.")
        configure_files(outputs)
        if args.check:
            check_runtime(outputs)
        return 0
    except ClientError as error:
        print(f"AWS rechazo la verificacion ({error.response['Error']['Code']}). "
              "Revisa la vigencia del certificado del worker y el perfil autoclick-worker.", file=sys.stderr)
        return 1
    except BotoCoreError as error:
        # credential_process errors can contain credential-helper output; never dump it.
        print(f"No se pudo verificar AWS ({type(error).__name__}). Revisa la conexion, "
              "el certificado y las rutas del perfil autoclick-worker.", file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(f"Configuracion incompleta: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
