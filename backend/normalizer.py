"""Normalização de texto (artista/título) para identificação de músicas.

Importante (PRD seção 11): versões diferentes (Original Mix, Extended Mix,
Remix, Radio Edit...) devem ser tratadas como músicas DIFERENTES. Por isso
a normalização aqui é propositalmente conservadora: uniformiza acentos,
caixa e espaçamento, mas nunca remove o conteúdo entre parênteses/colchetes,
que é onde essas marcações de versão costumam aparecer.
"""

import re
import unicodedata
from typing import Optional


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def normalize_text(text: Optional[str]) -> str:
    """Normaliza um texto para comparação: minúsculas, sem acentos, sem
    pontuação solta, espaços colapsados. Parênteses/colchetes e seu
    conteúdo são preservados de propósito (ver docstring do módulo).
    """
    if not text:
        return ""
    text = strip_accents(text).lower().strip()
    text = re.sub(r"[_/\\-]+", " ", text)
    text = re.sub(r"[^\w\s()\[\]]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_artist_title(artist: Optional[str], title: Optional[str]) -> Optional[str]:
    """Chave de identificação híbrida (PRD seção 8): combina artista e
    título normalizados. Retorna None quando não há título (nesse caso
    a identificação cai para hash/duração, tratada no comparator).
    """
    norm_title = normalize_text(title)
    if not norm_title:
        return None
    return f"{normalize_text(artist)}::{norm_title}"
