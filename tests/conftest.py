import pytest


@pytest.fixture
def tmp_libraries(tmp_path):
    """Cria dois diretórios vazios simulando 'Biblioteca A' e 'Biblioteca B'."""
    library_a = tmp_path / "library_a"
    library_b = tmp_path / "library_b"
    library_a.mkdir()
    library_b.mkdir()
    return library_a, library_b
