import shutil
import time

from backend.db import Database
from backend.scan_service import ScanManager
from tests.audio_helpers import make_audio_file


def wait_for_scan(manager, scan_id, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        progress = manager.get_progress(scan_id)
        if progress.phase in ("done", "error"):
            return progress
        time.sleep(0.05)
    raise TimeoutError("A análise não terminou dentro do tempo esperado.")


def test_full_pipeline_classifies_every_category(tmp_path, tmp_libraries):
    library_a, library_b = tmp_libraries

    # Mesmo arquivo, byte a byte, nos dois PCs.
    make_audio_file(library_a, "identical.wav", artist="Artist One", title="Identical Song", freq=440)
    shutil.copyfile(library_a / "identical.wav", library_b / "identical.wav")

    # Mesma música, arquivo diferente (conteúdo de áudio diferente, mesmas tags/duração).
    make_audio_file(library_a, "same_song.wav", artist="Artist Two", title="Same Song", freq=440)
    make_audio_file(library_b, "same_song.wav", artist="Artist Two", title="Same Song", freq=523)

    # Só existe em A / só existe em B.
    make_audio_file(library_a, "only_a.wav", artist="Artist Three", title="Only A Song", freq=300)
    make_audio_file(library_b, "only_b.wav", artist="Artist Four", title="Only B Song", freq=660)

    db = Database(str(tmp_path / "test.db"))
    manager = ScanManager(db)

    scan_id = manager.start_scan(str(library_a), str(library_b))
    progress = wait_for_scan(manager, scan_id)

    assert progress.phase == "done"
    assert progress.summary["IDENTICAL"] == 1
    assert progress.summary["ONLY_A"] == 1
    assert progress.summary["ONLY_B"] == 1
    assert progress.summary["SAME_SONG_DIFFERENT_FILE"] == 1
    assert progress.summary["POSSIBLE_DUPLICATE"] == 0

    matches = manager.get_matches(scan_id, "SAME_SONG_DIFFERENT_FILE")
    assert len(matches) == 1
    assert matches[0]["track_a"]["hash"] != matches[0]["track_b"]["hash"]


def test_pipeline_never_modifies_source_files(tmp_path, tmp_libraries):
    """PRD seção 3 / critério de aceitação 16: nenhum arquivo original pode ser alterado."""
    library_a, library_b = tmp_libraries
    file_a = make_audio_file(library_a, "track.wav", artist="Artist", title="Track")
    file_b = make_audio_file(library_b, "other.wav", artist="Other", title="Other")

    before = {
        str(p): (p.stat().st_size, p.stat().st_mtime, p.read_bytes())
        for p in (file_a, file_b)
    }

    db = Database(str(tmp_path / "test.db"))
    manager = ScanManager(db)
    scan_id = manager.start_scan(str(library_a), str(library_b))
    wait_for_scan(manager, scan_id)

    for path_str, (size, mtime, content) in before.items():
        from pathlib import Path

        p = Path(path_str)
        assert p.exists(), "arquivo original não deveria desaparecer"
        assert p.stat().st_size == size
        assert p.stat().st_mtime == mtime
        assert p.read_bytes() == content


def test_incremental_scan_reuses_cache_for_unchanged_files(tmp_path, tmp_libraries):
    """PRD seções 16-17: arquivos inalterados não devem ser reprocessados."""
    library_a, library_b = tmp_libraries
    make_audio_file(library_a, "track.wav", artist="Artist", title="Track")
    make_audio_file(library_b, "track.wav", artist="Artist", title="Track")

    db_path = str(tmp_path / "test.db")
    db = Database(db_path)
    manager = ScanManager(db)

    scan_id_1 = manager.start_scan(str(library_a), str(library_b))
    wait_for_scan(manager, scan_id_1)

    cached_before = db.get_cached_file(str(library_a / "track.wav"))
    assert cached_before is not None
    first_scanned_at = cached_before["last_scanned_at"]

    # Segunda análise: como o arquivo não mudou (mesmo tamanho/mtime),
    # o cache deve ser reaproveitado (last_scanned_at não deve avançar).
    scan_id_2 = manager.start_scan(str(library_a), str(library_b))
    progress_2 = wait_for_scan(manager, scan_id_2)

    cached_after = db.get_cached_file(str(library_a / "track.wav"))
    assert cached_after["last_scanned_at"] == first_scanned_at
    assert progress_2.summary["IDENTICAL"] == 1
