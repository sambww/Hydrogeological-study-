"""Data manifest: which local files back the study, with provenance."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class DataFile:
    key: str
    path: Path
    source: str = ""
    retrieved: str = ""
    crs: str = "EPSG:4326"
    columns: dict = field(default_factory=dict)
    exists: bool = False
    sha256: str = ""
    rows: int | None = None

    def provenance(self) -> dict:
        return {
            "key": self.key, "path": str(self.path), "exists": self.exists, "source": self.source,
            "retrieved": self.retrieved, "crs": self.crs, "sha256": self.sha256, "rows": self.rows,
        }


@dataclass
class Manifest:
    files: dict[str, DataFile]
    hydrography_notes: list = field(default_factory=list)
    springs: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

    def get(self, key: str) -> DataFile | None:
        f = self.files.get(key)
        return f if f and f.exists else None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(project_dir: Path, rel_path: str = "data/manifest.yaml") -> Manifest:
    mpath = project_dir / rel_path
    if not mpath.exists():
        return Manifest(files={})
    raw = yaml.safe_load(mpath.read_text(encoding="utf-8")) or {}
    files = {}
    for key, spec in (raw.get("files") or {}).items():
        p = (mpath.parent / spec.get("path", "")).resolve()
        df = DataFile(key=key, path=p, source=spec.get("source", ""), retrieved=str(spec.get("retrieved", "")),
                      crs=spec.get("crs", "EPSG:4326"), columns=spec.get("columns") or {})
        if p.exists() and p.is_file():
            df.exists = True
            df.sha256 = _sha(p)
            if p.suffix.lower() == ".csv":
                with open(p, encoding="utf-8") as fh:
                    df.rows = max(sum(1 for _ in fh) - 1, 0)
        files[key] = df
    return Manifest(files=files, hydrography_notes=raw.get("hydrography_notes") or [],
                    springs=raw.get("springs") or {}, raw=raw)
