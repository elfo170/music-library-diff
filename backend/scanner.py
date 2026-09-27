"""Scanner recursivo de bibliotecas de música (PRD seção 5).

Este módulo NUNCA modifica, move, renomeia, copia ou apaga arquivos —
apenas percorre o sistema de arquivos (local ou compartilhamento SMB
já acessível pelo Windows) e retorna os caminhos encontrados.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import SUPPORTED_EXTENSIONS


def is_supported_audio_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def validate_library_path(path_str: str) -> Optional[str]:
    """Valida se um caminho de biblioteca existe e é acessível.

    Retorna None se válido, ou uma mensagem de erro legível para exibir
    na interface (PRD seções 4.1 e 18).
    """
    if not path_str or not path_str.strip():
        return "Informe o caminho da biblioteca."

    path = Path(path_str)
    try:
        if not path.exists():
            return f"Caminho não encontrado ou inacessível: {path_str}"
        if not path.is_dir():
            return f"O caminho não é uma pasta: {path_str}"
        # Força uma listagem para detectar falta de permissão ou
        # compartilhamento de rede que existe mas não responde.
        next(os.scandir(path_str), None)
    except PermissionError:
        return f"Sem permissão para acessar: {path_str}"
    except OSError as exc:
        return f"Não foi possível acessar '{path_str}': {exc}"
    return None


def scan_directory(root_path: str) -> Tuple[List[Path], List[Dict[str, str]]]:
    """Percorre `root_path` recursivamente e retorna os arquivos de áudio
    suportados encontrados em todos os níveis de subpasta.

    Retorna (arquivos, erros). Uma subpasta problemática é registrada em
    `erros` e não interrompe o restante do scan (PRD seção 18).
    """
    found: List[Path] = []
    errors: List[Dict[str, str]] = []

    def on_walk_error(os_error: OSError) -> None:
        errors.append(
            {
                "path": getattr(os_error, "filename", None) or root_path,
                "error": str(os_error),
            }
        )

    for dirpath, _dirnames, filenames in os.walk(root_path, onerror=on_walk_error):
        for fname in filenames:
            candidate = Path(dirpath) / fname
            try:
                if is_supported_audio_file(candidate):
                    found.append(candidate)
            except OSError as exc:
                errors.append({"path": str(candidate), "error": str(exc)})

    return found, errors
