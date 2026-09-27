from backend.scanner import scan_directory, validate_library_path


def test_scan_directory_finds_supported_files_recursively(tmp_path):
    (tmp_path / "Techno" / "Artist A").mkdir(parents=True)
    (tmp_path / "House" / "Artist C").mkdir(parents=True)

    mp3_file = tmp_path / "Techno" / "Artist A" / "track.mp3"
    flac_file = tmp_path / "Techno" / "Artist A" / "track.flac"
    wav_file = tmp_path / "House" / "Artist C" / "track.wav"
    text_file = tmp_path / "House" / "readme.txt"

    for f in (mp3_file, flac_file, wav_file, text_file):
        f.write_bytes(b"fake content")

    found, errors = scan_directory(str(tmp_path))
    found_names = sorted(str(p) for p in found)

    assert str(mp3_file) in found_names
    assert str(flac_file) in found_names
    assert str(wav_file) in found_names
    assert str(text_file) not in found_names
    assert errors == []


def test_scan_directory_ignores_unsupported_extensions(tmp_path):
    (tmp_path / "cover.jpg").write_bytes(b"fake image")
    (tmp_path / "playlist.m3u").write_bytes(b"fake playlist")

    found, _errors = scan_directory(str(tmp_path))

    assert found == []


def test_validate_library_path_missing():
    error = validate_library_path(str("/definitely/not/a/real/path/xyz"))
    assert error is not None
    assert "não encontrado" in error.lower() or "nao encontrado" in error.lower()


def test_validate_library_path_not_a_directory(tmp_path):
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hi")

    error = validate_library_path(str(file_path))
    assert error is not None
    assert "pasta" in error.lower()


def test_validate_library_path_valid(tmp_path):
    assert validate_library_path(str(tmp_path)) is None


def test_validate_library_path_empty_string():
    error = validate_library_path("")
    assert error is not None
