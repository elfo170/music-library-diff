from backend.db import Database
from backend.models import Match, TrackInfo


def make_track(path="C:/Music/track.mp3", library="A", file_hash="abc123"):
    return TrackInfo(
        path=path,
        library=library,
        size=1000,
        mtime=123456.0,
        file_hash=file_hash,
        artist="Artist",
        title="Title",
        album="Album",
        album_artist="Artist",
        duration=180.0,
        format="MP3",
        bitrate=320000,
        sample_rate=44100,
        bit_depth=None,
        error=None,
    )


def test_file_cache_roundtrip(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    track = make_track()

    assert db.get_cached_file(track.path) is None

    db.upsert_cached_file(track)
    cached = db.get_cached_file(track.path)

    assert cached is not None
    assert cached["hash"] == "abc123"
    assert cached["artist"] == "Artist"
    assert cached["duration"] == 180.0


def test_file_cache_upsert_overwrites_existing_entry(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    track = make_track()
    db.upsert_cached_file(track)

    updated = make_track(file_hash="different-hash")
    db.upsert_cached_file(updated)

    cached = db.get_cached_file(track.path)
    assert cached["hash"] == "different-hash"


def test_forget_missing_files_removes_stale_entries(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    kept = make_track(path="C:/Music/kept.mp3")
    removed = make_track(path="C:/Music/removed.mp3")
    db.upsert_cached_file(kept)
    db.upsert_cached_file(removed)

    db.forget_missing_files("C:/Music", seen_paths=[kept.path])

    assert db.get_cached_file(kept.path) is not None
    assert db.get_cached_file(removed.path) is None


def test_scan_and_matches_roundtrip(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    scan_id = db.create_scan("C:/Music", "\\\\PC\\Music")

    track_a = make_track(path="C:/Music/a.mp3", library="A")
    track_b = make_track(path="\\\\PC\\Music\\b.mp3", library="B")
    matches = [
        Match(match_type="IDENTICAL", track_a=track_a, track_b=track_b),
        Match(match_type="ONLY_A", track_a=track_a, track_b=None),
    ]
    db.save_matches(scan_id, matches)
    db.finish_scan(scan_id, "done", {"IDENTICAL": 1, "ONLY_A": 1})

    scan = db.get_scan(scan_id)
    assert scan["status"] == "done"

    all_matches = db.get_matches(scan_id)
    assert len(all_matches) == 2

    only_identical = db.get_matches(scan_id, "IDENTICAL")
    assert len(only_identical) == 1
    assert only_identical[0]["track_b"]["path"] == "\\\\PC\\Music\\b.mp3"
