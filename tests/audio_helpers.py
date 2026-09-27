"""Helpers de teste: gera arquivos de áudio sintéticos (senoides curtas)
para exercitar o pipeline real (scan -> metadata -> hash -> compare)
sem depender de nenhum arquivo de áudio externo no repositório.

WAV é gerado apenas com a biblioteca padrão (`wave`), então os testes
baseados em WAV sempre rodam. Os demais formatos usam `ffmpeg`, e são
pulados automaticamente quando ele não está disponível no ambiente.
"""

import math
import shutil
import struct
import subprocess
import wave
from pathlib import Path

import pytest

HAS_FFMPEG = shutil.which("ffmpeg") is not None

_FFMPEG_CODEC_ARGS = {
    ".mp3": ["-c:a", "libmp3lame"],
    ".flac": ["-c:a", "flac"],
    ".aiff": ["-c:a", "pcm_s16be"],
    ".aif": ["-c:a", "pcm_s16be"],
    ".m4a": ["-c:a", "aac"],
    ".aac": ["-c:a", "aac"],
    ".ogg": ["-c:a", "libvorbis"],
    ".opus": ["-c:a", "libopus"],
}

# WAV e AIFF guardam metadata como ID3v2 "cru" (mesmo mecanismo do MP3),
# mas o wrapper easy=True do mutagen não se aplica a esses dois
# contêineres: precisam de frames ID3 explícitos (TPE1/TIT2/TALB) em
# vez da atribuição por dict usada nos demais formatos.
_RAW_ID3_EXTENSIONS = {".wav", ".aiff", ".aif"}


def _make_wav(path: Path, seconds: float, freq: int, sample_rate: int = 44100) -> None:
    n_samples = int(seconds * sample_rate)
    frames = bytearray()
    for i in range(n_samples):
        value = int(10000 * math.sin(2 * math.pi * freq * (i / sample_rate)))
        frames += struct.pack("<h", value)

    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))


def _make_via_ffmpeg(path: Path, seconds: float, freq: int) -> None:
    codec_args = _FFMPEG_CODEC_ARGS.get(path.suffix.lower(), [])
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            *codec_args, str(path),
        ],
        check=True,
        capture_output=True,
    )


def _tag_with_mutagen(path: Path, artist: str, title: str, album: str = "Test Album") -> None:
    from mutagen import File as MutagenFile
    from mutagen.id3 import TALB, TIT2, TPE1

    audio = MutagenFile(str(path), easy=True)
    if audio is None:
        return
    if audio.tags is None:
        audio.add_tags()

    if path.suffix.lower() in _RAW_ID3_EXTENSIONS:
        audio.tags.setall("TPE1", [TPE1(encoding=3, text=[artist])])
        audio.tags.setall("TIT2", [TIT2(encoding=3, text=[title])])
        if album:
            audio.tags.setall("TALB", [TALB(encoding=3, text=[album])])
    else:
        audio["artist"] = artist
        audio["title"] = title
        if album:
            audio["album"] = album

    audio.save()


def make_audio_file(
    directory: Path,
    filename: str,
    artist: str,
    title: str,
    seconds: float = 1.0,
    freq: int = 440,
) -> Path:
    """Cria `directory/filename` como um arquivo de áudio real e válido,
    com tags de artista/título/álbum, e retorna o Path criado.

    Usa `pytest.skip` quando o formato pedido exige ffmpeg e ele não
    está disponível no ambiente de teste.
    """
    directory.mkdir(parents=True, exist_ok=True)
    dest = directory / filename
    ext = dest.suffix.lower()

    if ext == ".wav":
        _make_wav(dest, seconds=seconds, freq=freq)
    else:
        if not HAS_FFMPEG:
            pytest.skip(f"ffmpeg não disponível; pulando teste para o formato {ext}")
        _make_via_ffmpeg(dest, seconds=seconds, freq=freq)

    _tag_with_mutagen(dest, artist=artist, title=title)
    return dest
