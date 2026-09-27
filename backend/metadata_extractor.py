"""Extração de metadata de arquivos de áudio usando mutagen (PRD seção 7).

Este módulo apenas LÊ os arquivos; nunca escreve, move ou apaga nada.
Um arquivo problemático (corrompido, sem metadata, formato não
reconhecido) nunca deve derrubar o scan inteiro — em vez de propagar a
exceção, retornamos um MetadataResult com `error` preenchido e um
fallback razoável (título = nome do arquivo) para que a comparação
ainda possa ocorrer por nome/duração/hash.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from mutagen import File as MutagenFile
from mutagen.id3 import ID3

# WAV e AIFF guardam metadata como ID3v2 "cru" (mesmo mecanismo do MP3),
# mas o wrapper easy=True do mutagen não se aplica a esses dois
# contêineres — .tags continua sendo um ID3 de frames, não um dict
# simples. Por isso eles precisam de leitura via frame (TPE1/TIT2/...).
_RAW_ID3_FORMATS = {"WAV", "AIFF", "AIF"}


@dataclass
class MetadataResult:
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


def _first_tag(tags, keys):
    if not tags:
        return None
    for key in keys:
        try:
            value = tags.get(key)
        except Exception:  # noqa: BLE001 - algumas tags não suportam .get uniformemente
            value = None
        if value:
            if isinstance(value, (list, tuple)):
                return str(value[0]) if value else None
            return str(value)
    return None


def _first_id3_frame(tags, frame_ids):
    if not tags:
        return None
    for frame_id in frame_ids:
        frames = tags.getall(frame_id)
        if frames and getattr(frames[0], "text", None):
            return str(frames[0].text[0])
    return None


def extract_metadata(path: Path) -> MetadataResult:
    """Extrai metadata de um arquivo de áudio suportado.

    Nunca levanta exceção: falhas de parsing viram `MetadataResult.error`.
    """
    fmt = path.suffix.lstrip(".").upper()

    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception as exc:  # noqa: BLE001 - qualquer falha de leitura vira erro reportável
        return MetadataResult(title=path.stem, format=fmt, error=str(exc))

    if audio is None:
        return MetadataResult(
            title=path.stem,
            format=fmt,
            error="Formato de áudio não reconhecido pelo mutagen",
        )

    try:
        tags = audio.tags
        info = audio.info

        if fmt in _RAW_ID3_FORMATS and isinstance(tags, ID3):
            artist = _first_id3_frame(tags, ["TPE1"])
            title = _first_id3_frame(tags, ["TIT2"]) or path.stem
            album = _first_id3_frame(tags, ["TALB"])
            album_artist = _first_id3_frame(tags, ["TPE2"])
        else:
            artist = _first_tag(tags, ["artist"])
            title = _first_tag(tags, ["title"]) or path.stem
            album = _first_tag(tags, ["album"])
            album_artist = _first_tag(tags, ["albumartist", "album artist"])

        duration = getattr(info, "length", None)
        bitrate = getattr(info, "bitrate", None)
        sample_rate = getattr(info, "sample_rate", None)
        bit_depth = getattr(info, "bits_per_sample", None)

        return MetadataResult(
            artist=artist,
            title=title,
            album=album,
            album_artist=album_artist,
            duration=float(duration) if duration is not None else None,
            format=fmt,
            bitrate=int(bitrate) if bitrate else None,
            sample_rate=int(sample_rate) if sample_rate else None,
            bit_depth=int(bit_depth) if bit_depth else None,
        )
    except Exception as exc:  # noqa: BLE001 - metadata malformada não pode derrubar o scan
        return MetadataResult(title=path.stem, format=fmt, error=str(exc))
