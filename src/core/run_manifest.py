"""Create and verify non-secret provenance manifests for benchmark runs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_run_manifest(*, run_id: str, metadata: dict[str, Any], artifacts: list[Path], root: Path) -> dict[str, Any]:
    """Build a manifest containing metadata and checksums for existing files."""
    entries: list[dict[str, Any]] = []
    for artifact in artifacts:
        if artifact.is_file():
            try:
                artifact_name = str(artifact.resolve().relative_to(root.resolve()))
            except ValueError:
                artifact_name = str(artifact.resolve())
            entries.append(
                {
                    "path": artifact_name,
                    "sha256": _sha256(artifact),
                    "bytes": artifact.stat().st_size,
                }
            )
    return {
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "metadata": metadata,
        "artifacts": entries,
    }


def write_run_manifest(
    *, output: Path, run_id: str, metadata: dict[str, Any], artifacts: list[Path], root: Path
) -> Path:
    """Write a manifest to disk and return its path."""
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest = build_run_manifest(run_id=run_id, metadata=metadata, artifacts=artifacts, root=root)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return output


def inspect_run_manifest(path: Path, root: Path) -> list[str]:
    """Return actionable integrity errors for a manifest, or an empty list."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read manifest '{path}': {exc}"]
    if not isinstance(payload, dict) or not isinstance(payload.get("artifacts"), list):
        return ["Invalid manifest: expected an object with an 'artifacts' list."]

    errors: list[str] = []
    for entry in payload["artifacts"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append("Invalid artifact entry: missing relative path.")
            continue
        artifact_path = Path(entry["path"])
        artifact = artifact_path if artifact_path.is_absolute() else root / artifact_path
        if not artifact.is_file():
            errors.append(f"Missing artifact: {entry['path']}")
        elif isinstance(entry.get("sha256"), str) and _sha256(artifact) != entry["sha256"]:
            errors.append(f"Checksum mismatch: {entry['path']}")
    return errors
