import os
import shutil
import time

import pytest

from backend import operations
from backend.app import create_app
from backend.operations import copy_verified, free_name, is_within
from tests.audio_helpers import make_audio_file


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "test.db"))
    return app.test_client()


def wait_for(client, url, done_values, key, timeout=15):
    start = time.time()
    while time.time() - start < timeout:
        data = client.get(url).get_json()
        if data[key] in done_values:
            return data
        time.sleep(0.05)
    raise TimeoutError(url)


def run_scan(client, lib_a, lib_b):
    resp = client.post("/api/scans", json={"library_a": str(lib_a), "library_b": str(lib_b)})
    scan_id = resp.get_json()["scan_id"]
    wait_for(client, f"/api/scans/{scan_id}", ("done", "error"), "phase")
    return scan_id


def matches_of(client, scan_id, category="all"):
    return client.get(f"/api/scans/{scan_id}/matches?category={category}").get_json()["matches"]


def run_operation(client, scan_id, payload):
    payload = {**payload, "confirm": True}
    resp = client.post(f"/api/scans/{scan_id}/operations", json=payload)
    assert resp.status_code == 201, resp.get_json()
    op_id = resp.get_json()["operation_id"]
    return wait_for(client, f"/api/operations/{op_id}", ("done", "error"), "status")


def test_transfer_keeps_relative_structure_and_updates_results(client, tmp_libraries):
    lib_a, lib_b = tmp_libraries
    src = make_audio_file(lib_a / "Techno" / "Artist", "track.wav", artist="Artist", title="Track")
    scan_id = run_scan(client, lib_a, lib_b)
    match = matches_of(client, scan_id, "ONLY_A")[0]

    op = run_operation(client, scan_id, {"type": "transfer", "direction": "A_TO_B", "match_ids": [match["id"]]})

    dest = lib_b / "Techno" / "Artist" / "track.wav"
    assert op["status"] == "done" and op["counts"] == {"ok": 1}
    assert dest.read_bytes() == src.read_bytes()
    assert op["summary"]["IDENTICAL"] == 1 and op["summary"]["ONLY_A"] == 0
    assert len(matches_of(client, scan_id, "IDENTICAL")) == 1
    assert not [p for p in os.listdir(dest.parent) if p.startswith(operations.TEMP_PREFIX)]


def test_conflict_requires_resolution_and_supports_each_choice(client, tmp_libraries):
    lib_a, lib_b = tmp_libraries
    src = make_audio_file(lib_a, "song.wav", artist="Artist", title="Song", freq=440)
    other = make_audio_file(lib_b, "song.wav", artist="Artist", title="Song", freq=523)
    original_b = other.read_bytes()
    scan_id = run_scan(client, lib_a, lib_b)
    match = matches_of(client, scan_id, "SAME_SONG_DIFFERENT_FILE")[0]
    body = {"type": "transfer", "direction": "A_TO_B", "match_ids": [match["id"]]}

    plan = client.post(f"/api/scans/{scan_id}/operations/plan", json=body).get_json()["items"]
    assert plan[0]["conflict"] is not None
    key = plan[0]["key"]

    # sem resolução: nada muda
    op = run_operation(client, scan_id, body)
    assert op["counts"] == {"skipped": 1} and other.read_bytes() == original_b

    # skip explícito (os ids mudam após cada operação: busca o atual)
    match = matches_of(client, scan_id, "SAME_SONG_DIFFERENT_FILE")[0]
    body["match_ids"] = [match["id"]]
    key = f"{match['id']}:A"
    op = run_operation(client, scan_id, {**body, "resolutions": {key: "skip"}})
    assert op["counts"] == {"skipped": 1} and other.read_bytes() == original_b

    # manter os dois
    match = matches_of(client, scan_id, "SAME_SONG_DIFFERENT_FILE")[0]
    body["match_ids"] = [match["id"]]
    key = f"{match['id']}:A"
    op = run_operation(client, scan_id, {**body, "resolutions": {key: "keep_both"}})
    assert op["counts"] == {"ok": 1}
    assert (lib_b / "song (2).wav").read_bytes() == src.read_bytes()
    assert other.read_bytes() == original_b


def test_overwrite_resolution_replaces_destination(client, tmp_libraries):
    lib_a, lib_b = tmp_libraries
    src = make_audio_file(lib_a, "song.wav", artist="Artist", title="Song", freq=440)
    other = make_audio_file(lib_b, "song.wav", artist="Artist", title="Song", freq=523)
    scan_id = run_scan(client, lib_a, lib_b)
    match = matches_of(client, scan_id, "SAME_SONG_DIFFERENT_FILE")[0]

    op = run_operation(
        client, scan_id,
        {"type": "transfer", "direction": "A_TO_B", "match_ids": [match["id"]],
         "resolutions": {f"{match['id']}:A": "overwrite"}},
    )

    assert op["counts"] == {"ok": 1}
    assert other.read_bytes() == src.read_bytes()
    assert op["summary"]["IDENTICAL"] == 1


def test_transfer_skips_identical_and_missing_source(client, tmp_libraries):
    lib_a, lib_b = tmp_libraries
    make_audio_file(lib_a, "same.wav", artist="A", title="Same")
    shutil.copyfile(lib_a / "same.wav", lib_b / "same.wav")
    make_audio_file(lib_b, "only_b.wav", artist="B", title="Only B")
    scan_id = run_scan(client, lib_a, lib_b)
    ids = [m["id"] for m in matches_of(client, scan_id)]

    op = run_operation(client, scan_id, {"type": "transfer", "direction": "A_TO_B", "match_ids": ids})

    assert op["counts"] == {"skipped": 2}
    assert not (lib_a / "only_b.wav").exists()


def test_failed_hash_verification_discards_copy(client, tmp_libraries, monkeypatch):
    lib_a, lib_b = tmp_libraries
    make_audio_file(lib_a, "track.wav", artist="A", title="Track")
    scan_id = run_scan(client, lib_a, lib_b)
    match = matches_of(client, scan_id, "ONLY_A")[0]
    monkeypatch.setattr(operations, "hash_file", lambda path: "wrong")

    op = run_operation(client, scan_id, {"type": "transfer", "direction": "A_TO_B", "match_ids": [match["id"]]})

    assert op["counts"] == {"failed": 1}
    assert os.listdir(lib_b) == []


def test_delete_uses_trash_locally_and_is_permanent_on_network(client, tmp_libraries, monkeypatch):
    lib_a, lib_b = tmp_libraries
    local = make_audio_file(lib_a, "local.wav", artist="A", title="Local")
    remote = make_audio_file(lib_b, "remote.wav", artist="B", title="Remote")
    scan_id = run_scan(client, lib_a, lib_b)
    trashed = []
    monkeypatch.setattr(operations, "send_to_trash", lambda p: (trashed.append(p), os.remove(p)))
    monkeypatch.setattr(operations, "is_network_path", lambda p: str(p).startswith(str(lib_b)))
    ids = [m["id"] for m in matches_of(client, scan_id)]

    plan = client.post(
        f"/api/scans/{scan_id}/operations/plan", json={"type": "delete", "sides": "both", "match_ids": ids}
    ).get_json()["items"]
    assert sorted(i["permanent"] for i in plan) == [False, True]

    op = run_operation(client, scan_id, {"type": "delete", "sides": "both", "match_ids": ids})

    assert op["counts"] == {"ok": 2}
    assert trashed == [str(local)]
    assert not local.exists() and not remote.exists()
    assert matches_of(client, scan_id) == []


def test_requires_confirmation_and_valid_input(client, tmp_libraries):
    lib_a, lib_b = tmp_libraries
    make_audio_file(lib_a, "t.wav", artist="A", title="T")
    scan_id = run_scan(client, lib_a, lib_b)
    mid = matches_of(client, scan_id)[0]["id"]
    body = {"type": "delete", "sides": "A", "match_ids": [mid]}

    assert client.post(f"/api/scans/{scan_id}/operations", json=body).status_code == 400
    assert client.post(f"/api/scans/{scan_id}/operations/plan", json={**body, "sides": "X"}).status_code == 400
    assert client.post(f"/api/scans/{scan_id}/operations/plan", json={**body, "match_ids": []}).status_code == 400
    assert client.post("/api/scans/999/operations/plan", json=body).status_code == 404
    assert (lib_a / "t.wav").exists()


def test_helpers(tmp_path):
    assert is_within(str(tmp_path), str(tmp_path / "a" / "b.mp3"))
    assert not is_within(str(tmp_path / "a"), str(tmp_path / "a" / ".." / "b.mp3"))
    (tmp_path / "x.wav").write_bytes(b"1")
    assert free_name(str(tmp_path / "x.wav")) == str(tmp_path / "x (2).wav")
    (tmp_path / "src.bin").write_bytes(b"data")
    copy_verified(str(tmp_path / "src.bin"), str(tmp_path / "new" / "dir" / "dst.bin"))
    assert (tmp_path / "new" / "dir" / "dst.bin").read_bytes() == b"data"
