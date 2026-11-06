"""Verify and atomically install a fixed local model package."""
import hashlib
import json
import shutil
from pathlib import Path
from uuid import uuid4

import requests


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify(root, manifest):
    for entry in manifest["files"]:
        path = root / entry["path"]
        if (not path.is_file() or path.stat().st_size != entry["bytes"]
                or digest(path) != entry["sha256"]):
            raise ValueError(f"Model verification failed: {path}")


def install_package(manifest_file: Path, models_root: Path, source: Path | None = None):
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    models_root = models_root.resolve()
    models_root.mkdir(parents=True, exist_ok=True)
    target = models_root / manifest["directory"]
    metadata = {"model-manifest.json": manifest_file.read_bytes()}
    if "profile" in manifest:
        metadata["comitrans-model.json"] = (json.dumps(manifest["profile"], indent=2) + "\n").encode("utf-8")
    if target.exists():
        verify(target, manifest)
        if any((target / name).read_bytes() != content for name, content in metadata.items()):
            raise ValueError(f"Existing package metadata differs; preserved: {target}")
        return target
    prefix = "." + manifest["directory"] + "-"
    # The directory becomes the installed package. Inherit the model library's
    # permissions; mkdtemp applies an owner-only ACL on Windows.
    staging = models_root / (prefix + uuid4().hex)
    staging.mkdir()
    try:
        for entry in manifest["files"]:
            path = staging / entry["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            if source is not None:
                shutil.copyfile(source / entry["path"], path)
            else:
                print(f"Downloading {entry['path']}", flush=True)
                with requests.get(entry["url"], stream=True, timeout=(15, 90)) as response:
                    response.raise_for_status()
                    with path.open("wb") as stream:
                        received = 0
                        for chunk in response.iter_content(1024 * 1024):
                            received += len(chunk)
                            if received > entry["bytes"]:
                                raise ValueError(f"Unexpected download size: {entry['path']}")
                            stream.write(chunk)
        verify(staging, manifest)
        for name, content in metadata.items():
            (staging / name).write_bytes(content)
        # On Windows rename fails if target already exists, preserving user data.
        if target.exists():
            raise FileExistsError(target)
        staging.rename(target)
    finally:
        if staging.exists():
            if staging.parent != models_root or not staging.name.startswith(prefix):
                raise RuntimeError("Refusing cleanup outside the staging directory")
            shutil.rmtree(staging)
    return target
