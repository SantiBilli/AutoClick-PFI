"""Restore the published AutoClick 8B model and verify its contents."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import zipfile


BUFFER_SIZE = 8 * 1024 * 1024
MODEL_DIRECTORY = Path(__file__).resolve().parent


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(BUFFER_SIZE):
            digest.update(block)
    return digest.hexdigest()


def destination_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError(f"Ruta fuera del destino de instalacion: {relative}")
    return target


def matches(path: Path, expected: dict) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == expected["size"]
        and checksum(path) == expected["sha256"]
    )


def restore(source_path: Path, destination: Path, *, single_archive: bool = False) -> None:
    specification = json.loads(
        (MODEL_DIRECTORY / "entrega33-download.json").read_text(encoding="utf-8")
    )
    if specification["schema_version"] != 1:
        raise ValueError("Version de paquete no compatible.")
    expected_files = {item["path"]: item for item in specification["files"]}
    targets = {
        name: destination_path(destination, name) for name in expected_files
    }
    if all(matches(targets[name], item) for name, item in expected_files.items()):
        print(f"{specification['model']} ya esta instalado y verificado.", flush=True)
        return

    if single_archive:
        print(f"Verificando {source_path.name}...", flush=True)
        if not source_path.is_file() or checksum(source_path) != specification["archive_sha256"]:
            raise ValueError("Falta el ZIP o su contenido no coincide con el publicado.")
    else:
        for part in specification["parts"]:
            source = destination_path(source_path, part["name"])
            print(f"Verificando {part['name']}...", flush=True)
            if not matches(source, part):
                raise ValueError(
                    f"Falta {part['name']} o su contenido no coincide. "
                    "Descargar nuevamente desde el enlace de Google Drive del README."
                )

    temporary_directory = (
        nullcontext(None)
        if single_archive
        else tempfile.TemporaryDirectory(prefix="autoclick-entrega33-")
    )
    with temporary_directory as temporary:
        archive_path = source_path
        if not single_archive:
            archive_path = Path(temporary) / "autoclick-8b-entrega33.zip"
            archive_digest = hashlib.sha256()
            print("Uniendo las partes...", flush=True)
            with archive_path.open("xb") as archive_output:
                for part in specification["parts"]:
                    with (source_path / part["name"]).open("rb") as source:
                        while block := source.read(BUFFER_SIZE):
                            archive_output.write(block)
                            archive_digest.update(block)
            if archive_digest.hexdigest() != specification["archive_sha256"]:
                raise ValueError("El paquete reconstruido no coincide con el publicado.")

        with zipfile.ZipFile(archive_path) as archive:
            if (
                len(archive.infolist()) != len(expected_files)
                or set(archive.namelist()) != set(expected_files)
            ):
                raise ValueError("El paquete contiene una lista de archivos inesperada.")
            for name, expected in expected_files.items():
                target = targets[name]
                if target.exists():
                    if matches(target, expected):
                        continue
                    raise ValueError(
                        f"Ya existe un archivo diferente: {target}. "
                        "Conservarlo en otra ubicacion o elegir otro --destination."
                    )
                if archive.getinfo(name).file_size != expected["size"]:
                    raise ValueError(f"Tamano inesperado en el paquete: {name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                print(f"Restaurando {name}...", flush=True)
                temporary_file = None
                try:
                    digest = hashlib.sha256()
                    with (
                        archive.open(name) as source,
                        tempfile.NamedTemporaryFile(
                            dir=target.parent,
                            prefix=".autoclick-entrega33-",
                            suffix=".tmp",
                            delete=False,
                        ) as output,
                    ):
                        temporary_file = Path(output.name)
                        while block := source.read(BUFFER_SIZE):
                            output.write(block)
                            digest.update(block)
                    if digest.hexdigest() != expected["sha256"]:
                        raise ValueError(f"Contenido incorrecto en el paquete: {name}")
                    os.replace(temporary_file, target)
                finally:
                    if temporary_file is not None:
                        temporary_file.unlink(missing_ok=True)

    print(f"Modelo restaurado: {specification['model']}", flush=True)
    print(f"Almacen de Ollama: {destination / 'ollama-models'}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Instalar autoclick-8b:entrega33 desde la descarga de Google Drive."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--parts-dir",
        type=Path,
        help="Carpeta que contiene todas las partes numeradas del ZIP.",
    )
    source.add_argument(
        "--archive",
        type=Path,
        help="Archivo autoclick-8b-entrega33.zip completo, sin dividir.",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=MODEL_DIRECTORY,
        help="Carpeta Autoclick-Models de destino; por defecto, la de este repositorio.",
    )
    arguments = parser.parse_args()
    try:
        restore(
            (arguments.archive or arguments.parts_dir).resolve(),
            arguments.destination.resolve(),
            single_archive=arguments.archive is not None,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"No se pudo instalar el modelo: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
