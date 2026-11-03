"""Private per-generation preview caching; authorization remains in the routes."""
import hashlib
from pathlib import Path


def preview_key(gen: Path) -> str:
    from ansys_report.geometry import check, figures, viewer_data, rvs_core
    digest = hashlib.sha256((gen / "input.json").read_bytes())
    for module in (check, figures, viewer_data, rvs_core):
        digest.update(Path(module.__file__).read_bytes())
    return digest.hexdigest()


def cache_headers(path: Path) -> dict:
    stat = path.stat()
    return {"Cache-Control": "private, max-age=0, must-revalidate", "ETag": f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'}


def preview_is_cached(gen: Path, key: str) -> bool:
    import json
    pv = gen / "preview"
    try:
        manifest = json.loads((pv / "cache-key").read_text())
        required = {"viewer.json", "prev_points.png", "prev_surface.png", "prev_unfold.png"}
        files = manifest["files"]
        return manifest["key"] == key and (pv / "ready").exists() and required.issubset(files) and all((pv / name).is_file() for name in files)
    except (OSError, ValueError, KeyError, TypeError):
        return False
