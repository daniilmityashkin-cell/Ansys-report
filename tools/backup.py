"""Резервная копия сайта: база (безопасно, при работающем сайте) + файлы генераций -> один zip с датой.

Запуск:  python tools/backup.py <папка данных сайта> <куда складывать> [сколько копий хранить]
Пример:  python tools/backup.py C:\\asr\\server_data D:\\asr_backup 14
"""
from __future__ import annotations
import datetime as dt
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path


def backup(data_dir: Path, dest: Path, keep: int = 14) -> Path:
    data_dir, dest = Path(data_dir), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / f"asr_backup_{dt.datetime.now():%Y-%m-%d_%H%M%S}.zip"
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        db = data_dir / "site.db"
        if db.exists():
            copy = Path(tmp) / "site.db"
            src, dst = sqlite3.connect(db), sqlite3.connect(copy)
            with dst:
                src.backup(dst)                      # согласованная копия, пока сайт пишет в базу
            src.close(); dst.close()
            z.write(copy, "site.db")
        gens = data_dir / "generations"
        if gens.exists():
            for p in gens.rglob("*"):
                if p.is_file():
                    z.write(p, Path("generations") / p.relative_to(gens))
    old = sorted(dest.glob("asr_backup_*.zip"))
    for p in old[:-keep] if keep > 0 else []:
        p.unlink()
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    r = backup(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 14)
    print(f"Копия создана: {r} ({r.stat().st_size / 1e6:.1f} МБ)")
