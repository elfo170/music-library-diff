from backend.comparator import compare_libraries
from backend.models import TrackInfo


def track(path, library, artist="Artist", title="Title", duration=180.0, file_hash="h1", fmt="MP3"):
    return TrackInfo(
        path=path,
        library=library,
        size=1000,
        mtime=1.0,
        file_hash=file_hash,
        artist=artist,
        title=title,
        duration=duration,
        format=fmt,
    )


def match_types(matches):
    return sorted(m.match_type for m in matches)


def test_identical_hash_is_classified_as_identical():
    a = track("A/track.mp3", "A", file_hash="same-hash")
    b = track("B/track.mp3", "B", file_hash="same-hash")

    matches = compare_libraries([a], [b])

    assert match_types(matches) == ["IDENTICAL"]


def test_same_song_different_file_within_tolerance():
    a = track("A/track.mp3", "A", file_hash="hash-a", duration=180.0, fmt="MP3")
    b = track("B/track.flac", "B", file_hash="hash-b", duration=181.0, fmt="FLAC")

    matches = compare_libraries([a], [b])

    assert match_types(matches) == ["SAME_SONG_DIFFERENT_FILE"]


def test_possible_duplicate_when_duration_diverges():
    a = track("A/track.mp3", "A", file_hash="hash-a", duration=180.0)
    b = track("B/track.mp3", "B", file_hash="hash-b", duration=300.0)

    matches = compare_libraries([a], [b])

    assert match_types(matches) == ["POSSIBLE_DUPLICATE"]


def test_only_a_and_only_b_when_no_match():
    a = track("A/unique_a.mp3", "A", artist="Artist Three", title="Only A", file_hash="ha")
    b = track("B/unique_b.mp3", "B", artist="Artist Four", title="Only B", file_hash="hb")

    matches = compare_libraries([a], [b])

    assert match_types(matches) == ["ONLY_A", "ONLY_B"]


def test_versions_are_not_matched_together():
    """PRD seção 11: Original Mix e Extended Mix devem virar ONLY_A / ONLY_B, não um match."""
    a = track("A/track.mp3", "A", title="Track (Original Mix)", file_hash="ha")
    b = track("B/track.mp3", "B", title="Track (Extended Mix)", file_hash="hb")

    matches = compare_libraries([a], [b])

    assert match_types(matches) == ["ONLY_A", "ONLY_B"]


def test_each_b_track_matched_at_most_once():
    a1 = track("A/1.mp3", "A", title="Song", file_hash="h1")
    a2 = track("A/2.mp3", "A", title="Song", file_hash="h2")
    b1 = track("B/1.mp3", "B", title="Song", file_hash="h3")

    matches = compare_libraries([a1, a2], [b1])

    # apenas uma das duas faixas de A pode "consumir" a única faixa de B
    only_a_count = match_types(matches).count("ONLY_A")
    same_song_count = sum(1 for m in matches if m.match_type == "SAME_SONG_DIFFERENT_FILE")
    assert only_a_count == 1
    assert same_song_count == 1
