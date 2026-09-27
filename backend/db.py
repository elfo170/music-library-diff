"""Camada de persistência SQLite (PRD seções 16-17).

Duas responsabilidades:

* `file_cache`: cache incremental indexado pelo caminho absoluto do
  arquivo. Se um arquivo não mudou (mesmo tamanho e mesma data de
  modificação) entre duas análises, seu hash e metadata são
  reaproveitados em vez de recalculados.
* `scans` / `scan_matches`: histórico de cada análise executada e do
  resultado da comparação, para consulta pela API sem precisar manter
  tudo em memória e como base para uma futura camada de sincronização.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import Match, TrackInfo

SCHEMA = """
CREATE TABLE IF NOT EXISTS file_cache (
    path TEXT PRIMARY KEY,
    library TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    hash TEXT,
    artist TEXT,
    title TEXT,
    album TEXT,
    album_artist TEXT,
    duration REAL,
    format TEXT,
    bitrate INTEGER,
    sample_rate INTEGER,
    bit_depth INTEGER,
    error TEXT,
    last_scanned_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    library_a_path TEXT NOT NULL,
    library_b_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    summary_json TEXT
);

CREATE TABLE IF NOT EXISTS scan_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    match_type TEXT NOT NULL,
    track_a_json TEXT,
    track_b_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_scan_matches_scan_id ON scan_matches(scan_id);
CREATE INDEX IF NOT EXISTS idx_scan_matches_type ON scan_matches(scan_id, match_type);
"""


class Database:
    """Wrapper fino sobre sqlite3.

    Uma única conexão compartilhada protegida por lock: simples e
    suficiente para o volume de um MVP local de um usuário só, e evita
    problemas de `sqlite3` com acesso concorrente entre a thread de
    scan (background) e a thread de requisições HTTP.
    """

    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    @contextmanager
    def _cursor(self):
        with self._lock:
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cur.close()

    # ---------- file_cache (análise incremental) ----------

    def get_cached_file(self, path: str) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM file_cache WHERE path = ?", (path,))
            row = cur.fetchone()
            return dict(row) if row else None

    def upsert_cached_file(self, track: TrackInfo) -> None:
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO file_cache (
                    path, library, size, mtime, hash, artist, title, album,
                    album_artist, duration, format, bitrate, sample_rate,
                    bit_depth, error, last_scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    library=excluded.library,
                    size=excluded.size,
                    mtime=excluded.mtime,
                    hash=excluded.hash,
                    artist=excluded.artist,
                    title=excluded.title,
                    album=excluded.album,
                    album_artist=excluded.album_artist,
                    duration=excluded.duration,
                    format=excluded.format,
                    bitrate=excluded.bitrate,
                    sample_rate=excluded.sample_rate,
                    bit_depth=excluded.bit_depth,
                    error=excluded.error,
                    last_scanned_at=excluded.last_scanned_at
                """,
                (
                    track.path,
                    track.library,
                    track.size,
                    track.mtime,
                    track.file_hash,
                    track.artist,
                    track.title,
                    track.album,
                    track.album_artist,
                    track.duration,
                    track.format,
                    track.bitrate,
                    track.sample_rate,
                    track.bit_depth,
                    track.error,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def forget_missing_files(self, library_root: str, seen_paths: Iterable[str]) -> None:
        """Remove do cache entradas de `library_root` que não apareceram
        no scan mais recente (arquivo apagado/movido fora da aplicação).
        """
        seen = set(seen_paths)
        with self._cursor() as cur:
            cur.execute(
                "SELECT path FROM file_cache WHERE path LIKE ? ESCAPE '\\'",
                (library_root.replace("%", "\\%").replace("_", "\\_") + "%",),
            )
            stale = [row["path"] for row in cur.fetchall() if row["path"] not in seen]
            if stale:
                cur.executemany("DELETE FROM file_cache WHERE path = ?", [(p,) for p in stale])

    # ---------- scans / scan_matches ----------

    def create_scan(self, library_a_path: str, library_b_path: str) -> int:
        with self._cursor() as cur:
            cur.execute(
                "INSERT INTO scans (library_a_path, library_b_path, started_at, status) "
                "VALUES (?, ?, ?, 'running')",
                (library_a_path, library_b_path, datetime.now(timezone.utc).isoformat()),
            )
            return cur.lastrowid

    def finish_scan(self, scan_id: int, status: str, summary: Dict[str, Any]) -> None:
        with self._cursor() as cur:
            cur.execute(
                "UPDATE scans SET finished_at = ?, status = ?, summary_json = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), status, json.dumps(summary), scan_id),
            )

    def save_matches(self, scan_id: int, matches: Iterable[Match]) -> None:
        rows = [
            (
                scan_id,
                m.match_type,
                json.dumps(m.track_a.to_dict()) if m.track_a else None,
                json.dumps(m.track_b.to_dict()) if m.track_b else None,
            )
            for m in matches
        ]
        if not rows:
            return
        with self._cursor() as cur:
            cur.executemany(
                "INSERT INTO scan_matches (scan_id, match_type, track_a_json, track_b_json) "
                "VALUES (?, ?, ?, ?)",
                rows,
            )

    def get_scan(self, scan_id: int) -> Optional[Dict[str, Any]]:
        with self._cursor() as cur:
            cur.execute("SELECT * FROM scans WHERE id = ?", (scan_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_matches(self, scan_id: int, match_type: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._cursor() as cur:
            if match_type and match_type != "all":
                cur.execute(
                    "SELECT * FROM scan_matches WHERE scan_id = ? AND match_type = ? ORDER BY id",
                    (scan_id, match_type),
                )
            else:
                cur.execute("SELECT * FROM scan_matches WHERE scan_id = ? ORDER BY id", (scan_id,))
            rows = cur.fetchall()

        return [
            {
                "match_type": row["match_type"],
                "track_a": json.loads(row["track_a_json"]) if row["track_a_json"] else None,
                "track_b": json.loads(row["track_b_json"]) if row["track_b_json"] else None,
            }
            for row in rows
        ]

    def close(self) -> None:
        self._conn.close()
