from backend.normalizer import normalize_artist_title, normalize_text


def test_normalize_text_lowercases_and_strips_accents():
    assert normalize_text("Música Eletrônica") == "musica eletronica"


def test_normalize_text_collapses_punctuation_and_whitespace():
    assert normalize_text("  Artist_Name -- Track!!  ") == "artist name track"


def test_normalize_text_empty_returns_empty_string():
    assert normalize_text(None) == ""
    assert normalize_text("") == ""


def test_normalize_artist_title_builds_composite_key():
    key = normalize_artist_title("Artist", "Track")
    assert key == "artist::track"


def test_normalize_artist_title_none_without_title():
    assert normalize_artist_title("Artist", None) is None
    assert normalize_artist_title("Artist", "") is None


def test_versions_and_remixes_stay_distinct():
    """PRD seção 11: versões diferentes devem ser tratadas como músicas diferentes."""
    original = normalize_artist_title("Artist", "Track (Original Mix)")
    extended = normalize_artist_title("Artist", "Track (Extended Mix)")
    radio_edit = normalize_artist_title("Artist", "Track (Radio Edit)")
    plain = normalize_artist_title("Artist", "Track")

    keys = {original, extended, radio_edit, plain}
    assert len(keys) == 4, "cada versão deve gerar uma chave normalizada distinta"
