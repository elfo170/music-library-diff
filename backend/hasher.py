"""Hash de arquivos para identificação de duplicatas exatas (PRD seção 9).

Usa BLAKE2b (biblioteca padrão do Python — sem dependência externa),
que é rápido e confiável o suficiente para diferenciar arquivos de
áudio, lendo em blocos para não carregar arquivos grandes inteiros
na memória.
"""

import hashlib

from .config import HASH_CHUNK_SIZE


def hash_file(path: str) -> str:
    """Calcula o hash BLAKE2b de um arquivo, lendo-o em blocos.

    Este módulo apenas LÊ o arquivo (modo "rb"); nunca escreve, move
    ou apaga nada.
    """
    digest = hashlib.blake2b(digest_size=20)
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
