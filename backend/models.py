"""Modelos de dados usados em todo o pipeline SCAN -> COMPARE -> DISPLAY."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

# Tipos de resultado de uma comparação entre duas bibliotecas.
# Mapeiam diretamente para as 5 categorias da interface (PRD seção 14):
#   IDENTICAL                -> "Em ambas"
#   ONLY_A                   -> "Apenas A"
#   ONLY_B                   -> "Apenas B"
#   POSSIBLE_DUPLICATE       -> "Duplicatas"
#   SAME_SONG_DIFFERENT_FILE -> "Arquivos diferentes"
MATCH_TYPES = (
    "IDENTICAL",
    "SAME_SONG_DIFFERENT_FILE",
    "POSSIBLE_DUPLICATE",
    "ONLY_A",
    "ONLY_B",
)


@dataclass
class TrackInfo:
    """Representa um arquivo de áudio encontrado durante o scan de uma biblioteca."""

    path: str
    library: str  # "A" ou "B"
    size: int
    mtime: float
    file_hash: Optional[str] = None
    artist: Optional[str] = None
    title: Optional[str] = None
    album: Optional[str] = None
    album_artist: Optional[str] = None
    duration: Optional[float] = None
    format: Optional[str] = None
    bitrate: Optional[int] = None
    sample_rate: Optional[int] = None
    bit_depth: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "library": self.library,
            "size": self.size,
            "mtime": self.mtime,
            "hash": self.file_hash,
            "artist": self.artist,
            "title": self.title,
            "album": self.album,
            "album_artist": self.album_artist,
            "duration": self.duration,
            "format": self.format,
            "bitrate": self.bitrate,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "error": self.error,
        }


@dataclass
class Match:
    """Resultado da comparação para um par (ou item avulso) de faixas."""

    match_type: str
    track_a: Optional[TrackInfo] = None
    track_b: Optional[TrackInfo] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "match_type": self.match_type,
            "track_a": self.track_a.to_dict() if self.track_a else None,
            "track_b": self.track_b.to_dict() if self.track_b else None,
        }
