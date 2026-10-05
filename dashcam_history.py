"""Persistent local history for Dashcam Transfer."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


class DownloadHistory:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=10)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                remote_path TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                exact_size INTEGER,
                downloaded_at TEXT NOT NULL,
                local_present INTEGER NOT NULL DEFAULT 1,
                local_deleted_at TEXT
            )
            """
        )
        self.db.execute("CREATE INDEX IF NOT EXISTS idx_downloads_filename ON downloads(filename)")
        self.db.commit()

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def was_downloaded(self, remote_path: str) -> bool:
        row = self.db.execute(
            "SELECT 1 FROM downloads WHERE remote_path = ?", (remote_path,)
        ).fetchone()
        return row is not None

    def record_download(self, remote_path: str, filename: str, exact_size: int) -> None:
        self.db.execute(
            """
            INSERT INTO downloads(remote_path, filename, exact_size, downloaded_at, local_present, local_deleted_at)
            VALUES (?, ?, ?, ?, 1, NULL)
            ON CONFLICT(remote_path) DO UPDATE SET
                filename=excluded.filename,
                exact_size=excluded.exact_size,
                downloaded_at=excluded.downloaded_at,
                local_present=1,
                local_deleted_at=NULL
            """,
            (remote_path, filename, exact_size, self.now()),
        )
        self.db.commit()

    def mark_present_by_filename(self, filename: str, present: bool) -> None:
        self.db.execute(
            """
            UPDATE downloads SET local_present=?, local_deleted_at=? WHERE filename=?
            """,
            (1 if present else 0, None if present else self.now(), filename),
        )
        self.db.commit()

    def reconcile(self, source: Path) -> tuple[int, int]:
        rows = self.db.execute("SELECT filename, local_present FROM downloads").fetchall()
        present = 0
        missing = 0
        for filename, old_present in rows:
            exists = (source / filename).is_file()
            present += int(exists)
            missing += int(not exists)
            if bool(old_present) != exists:
                self.mark_present_by_filename(filename, exists)
        return present, missing

    def import_local_sources(self, source: Path) -> int:
        """Seed history from front clips already on disk, including pre-GUI downloads."""
        imported = 0
        for path in source.glob("*_f.ts"):
            remote_path = f"/mnt/card/video_front/{path.name}"
            if not self.was_downloaded(remote_path):
                self.record_download(remote_path, path.name, path.stat().st_size)
                imported += 1
        return imported

    def stats(self) -> tuple[int, int, int]:
        total = self.db.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        present = self.db.execute(
            "SELECT COUNT(*) FROM downloads WHERE local_present=1"
        ).fetchone()[0]
        return total, present, total - present

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "DownloadHistory":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
