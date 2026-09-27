"""Orquestra o pipeline SCAN -> COMPARE em uma thread de background,
mantendo o estado de progresso em memória para consulta via API
(PRD seção 15: a interface não deve travar durante o scan).
"""

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .comparator import compare_libraries
from .config import DURATION_TOLERANCE_SECONDS
from .db import Database
from .hasher import hash_file
from .metadata_extractor import extract_metadata
from .models import TrackInfo
from .scanner import scan_directory, validate_library_path

# Margem de tolerância (segundos) ao comparar mtime salvo em cache com o
# mtime atual do arquivo, para absorver pequenas diferenças de
# precisão de ponto flutuante entre sistemas de arquivos.
_MTIME_EPSILON = 1e-6


@dataclass
class ScanProgress:
    phase: str = "pending"  # pending | scanning_a | scanning_b | comparing | done | error
    current: int = 0
    total: int = 0
    message: str = ""
    errors: List[Dict[str, str]] = field(default_factory=list)
    summary: Optional[Dict[str, int]] = None
    scan_id: Optional[int] = None
    error_message: Optional[str] = None


class ScanManager:
    """Mantém o estado (em memória, por processo) de todas as análises
    da sessão atual do servidor. Os resultados persistidos (tabela
    `scan_matches`) sobrevivem a um reinício; o progresso ao vivo não
    precisa sobreviver, pois uma análise em andamento não faz sentido
    após o processo cair.
    """

    def __init__(self, db: Database):
        self._db = db
        self._lock = threading.Lock()
        self._progress: Dict[int, ScanProgress] = {}

    def start_scan(self, library_a: str, library_b: str) -> int:
        error_a = validate_library_path(library_a)
        error_b = validate_library_path(library_b)
        if error_a or error_b:
            raise ValueError(" ".join(filter(None, [error_a, error_b])))

        scan_id = self._db.create_scan(library_a, library_b)
        with self._lock:
            self._progress[scan_id] = ScanProgress(phase="pending", scan_id=scan_id)

        thread = threading.Thread(
            target=self._run_scan, args=(scan_id, library_a, library_b), daemon=True
        )
        thread.start()
        return scan_id

    def get_progress(self, scan_id: int) -> Optional[ScanProgress]:
        with self._lock:
            return self._progress.get(scan_id)

    def get_matches(self, scan_id: int, match_type: Optional[str] = None) -> List[Dict[str, Any]]:
        return self._db.get_matches(scan_id, match_type)

    def _set_progress(self, scan_id: int, **kwargs) -> None:
        with self._lock:
            progress = self._progress[scan_id]
            for key, value in kwargs.items():
                setattr(progress, key, value)

    def _append_errors(self, scan_id: int, errors: List[Dict[str, str]]) -> None:
        if not errors:
            return
        with self._lock:
            self._progress[scan_id].errors.extend(errors)

    def _build_track_from_cache(self, path: str, label: str, size: int, mtime: float, cached: Dict[str, Any]) -> TrackInfo:
        return TrackInfo(
            path=path,
            library=label,
            size=size,
            mtime=mtime,
            file_hash=cached["hash"],
            artist=cached["artist"],
            title=cached["title"],
            album=cached["album"],
            album_artist=cached["album_artist"],
            duration=cached["duration"],
            format=cached["format"],
            bitrate=cached["bitrate"],
            sample_rate=cached["sample_rate"],
            bit_depth=cached["bit_depth"],
            error=cached["error"],
        )

    def _scan_one_library(self, scan_id: int, library_path: str, label: str, phase: str) -> List[TrackInfo]:
        self._set_progress(
            scan_id, phase=phase, current=0, total=0, message=f"Procurando arquivos em {library_path}..."
        )
        paths, walk_errors = scan_directory(library_path)
        total = len(paths)
        errors: List[Dict[str, str]] = list(walk_errors)
        tracks: List[TrackInfo] = []
        seen_paths: List[str] = []

        self._set_progress(scan_id, total=total, current=0, message="Extraindo metadata e calculando hashes...")

        for index, path in enumerate(paths, start=1):
            str_path = str(path)
            seen_paths.append(str_path)
            try:
                stat = path.stat()
                size, mtime = stat.st_size, stat.st_mtime
                cached = self._db.get_cached_file(str_path)

                if (
                    cached
                    and cached["size"] == size
                    and abs(cached["mtime"] - mtime) < _MTIME_EPSILON
                    and cached.get("hash")
                ):
                    track = self._build_track_from_cache(str_path, label, size, mtime, cached)
                else:
                    file_hash = hash_file(str_path)
                    meta = extract_metadata(path)
                    track = TrackInfo(
                        path=str_path,
                        library=label,
                        size=size,
                        mtime=mtime,
                        file_hash=file_hash,
                        artist=meta.artist,
                        title=meta.title,
                        album=meta.album,
                        album_artist=meta.album_artist,
                        duration=meta.duration,
                        format=meta.format,
                        bitrate=meta.bitrate,
                        sample_rate=meta.sample_rate,
                        bit_depth=meta.bit_depth,
                        error=meta.error,
                    )
                    self._db.upsert_cached_file(track)

                if track.error:
                    errors.append({"path": str_path, "error": track.error})
                tracks.append(track)
            except OSError as exc:
                errors.append({"path": str_path, "error": str(exc)})

            self._set_progress(scan_id, current=index)

        self._db.forget_missing_files(library_path, seen_paths)
        self._append_errors(scan_id, errors)
        return tracks

    def _run_scan(self, scan_id: int, library_a: str, library_b: str) -> None:
        try:
            tracks_a = self._scan_one_library(scan_id, library_a, "A", "scanning_a")
            tracks_b = self._scan_one_library(scan_id, library_b, "B", "scanning_b")

            self._set_progress(scan_id, phase="comparing", message="Comparando bibliotecas...")
            matches = compare_libraries(tracks_a, tracks_b, DURATION_TOLERANCE_SECONDS)
            self._db.save_matches(scan_id, matches)

            summary = {match_type: 0 for match_type in (
                "IDENTICAL", "SAME_SONG_DIFFERENT_FILE", "POSSIBLE_DUPLICATE", "ONLY_A", "ONLY_B"
            )}
            for match in matches:
                summary[match.match_type] = summary.get(match.match_type, 0) + 1

            self._db.finish_scan(scan_id, "done", summary)
            self._set_progress(scan_id, phase="done", summary=summary, message="Análise concluída.")
        except Exception as exc:  # noqa: BLE001 - qualquer falha inesperada vira estado "error" reportável
            self._db.finish_scan(scan_id, "error", {"error": str(exc)})
            self._set_progress(scan_id, phase="error", error_message=str(exc))
