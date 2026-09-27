"""Configurações e constantes centrais do Music Library Diff."""

from pathlib import Path

# Extensões de áudio suportadas pelo MVP (PRD seção 6).
SUPPORTED_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".aiff",
    ".aif",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
}

# Tamanho do bloco de leitura usado no cálculo de hash (1 MB).
HASH_CHUNK_SIZE = 1024 * 1024

# Tolerância (em segundos) para considerar duas durações "equivalentes"
# ao comparar a mesma música em arquivos/formatos diferentes.
DURATION_TOLERANCE_SECONDS = 2.0

# Diretório de dados da aplicação (banco de dados / cache incremental).
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Nome do arquivo SQLite dentro de DATA_DIR.
DB_FILENAME = "music_library_diff.db"
