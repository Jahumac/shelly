"""Manual DB backup / list.

Usage:
    python scripts/backup.py run        # create a backup now
    python scripts/backup.py list       # list existing backups

Backups live in data/backups/. The scheduler runs one automatically at
03:00 UK time every day; this CLI is for ad-hoc snapshots before a risky
change, migration, or upgrade.
"""
import sys
from pathlib import Path

from app import create_app
from app.services.backups import list_backups, run_backup


def main(argv):
    if len(argv) < 2 or argv[1] not in ("run", "list"):
        print(__doc__)
        sys.exit(1)

    app = create_app()
    db_path = Path(app.config["DB_PATH"])
    data_dir = Path(app.config.get("DATA_DIR", db_path.parent))

    if argv[1] == "run":
        dest = run_backup(db_path, data_dir)
        print(f"Backup written: {dest}")
    else:
        rows = list_backups(data_dir)
        if not rows:
            print("No backups yet.")
            return
        print(f"{'Name':<30} {'Size':>10}  {'Modified'}")
        for r in rows:
            size_mb = r["size_bytes"] / (1024 * 1024)
            print(f"{r['name']:<30} {size_mb:>8.2f} MB  {r['modified']}")


if __name__ == "__main__":
    main(sys.argv)
