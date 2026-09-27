from backend.hasher import hash_file


def test_same_content_same_hash(tmp_path):
    file_a = tmp_path / "a.bin"
    file_b = tmp_path / "b.bin"
    file_a.write_bytes(b"hello world" * 1000)
    file_b.write_bytes(b"hello world" * 1000)

    assert hash_file(str(file_a)) == hash_file(str(file_b))


def test_different_content_different_hash(tmp_path):
    file_a = tmp_path / "a.bin"
    file_b = tmp_path / "b.bin"
    file_a.write_bytes(b"hello world")
    file_b.write_bytes(b"hello there")

    assert hash_file(str(file_a)) != hash_file(str(file_b))


def test_hash_is_deterministic_across_chunk_boundaries(tmp_path):
    from backend.config import HASH_CHUNK_SIZE

    big_file = tmp_path / "big.bin"
    # conteúdo maior que um único bloco de leitura, para exercitar o loop
    big_file.write_bytes(b"x" * (HASH_CHUNK_SIZE + 12345))

    assert hash_file(str(big_file)) == hash_file(str(big_file))
