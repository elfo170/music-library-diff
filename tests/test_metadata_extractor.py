import pytest

from backend.metadata_extractor import extract_metadata
from tests.audio_helpers import make_audio_file


@pytest.mark.parametrize("ext", [".wav", ".mp3", ".flac", ".aiff", ".m4a", ".ogg", ".opus"])
def test_extract_metadata_reads_tags_and_duration(tmp_path, ext):
    path = make_audio_file(tmp_path, f"track{ext}", artist="Test Artist", title="Test Title", seconds=1.0)

    result = extract_metadata(path)

    assert result.error is None
    assert result.artist == "Test Artist"
    assert result.title == "Test Title"
    assert result.format == ext.lstrip(".").upper()
    assert result.duration is not None
    assert result.duration == pytest.approx(1.0, abs=0.3)


def test_extract_metadata_handles_corrupted_file_gracefully(tmp_path):
    """PRD seção 18: arquivo corrompido não deve interromper a análise."""
    bad_file = tmp_path / "corrupted.mp3"
    bad_file.write_bytes(b"this is not a real mp3 file")

    result = extract_metadata(bad_file)

    assert result.error is not None
    # Fallback: usa o nome do arquivo como título para ainda permitir comparação.
    assert result.title == "corrupted"


def test_extract_metadata_falls_back_to_filename_when_untagged(tmp_path):
    import wave

    path = tmp_path / "no_tags.wav"
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(b"\x00\x00" * 44100)

    result = extract_metadata(path)

    assert result.error is None
    assert result.title == "no_tags"
    assert result.artist is None
