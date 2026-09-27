"""COMPARE: classifica as faixas das duas bibliotecas (PRD seções 8, 10-12).

Abordagem híbrida de identificação, em ordem de prioridade:

1. Hash idêntico             -> IDENTICAL (mesmo arquivo, byte a byte).
2. Mesma chave normalizada
   (artista+título) e duração
   compatível (tolerância)    -> SAME_SONG_DIFFERENT_FILE
   (mesma música, arquivo/formato diferente).
3. Mesma chave normalizada,
   duração fora da tolerância -> POSSIBLE_DUPLICATE (precisa revisão manual).
4. Sem correspondência        -> ONLY_A / ONLY_B.

Versões/remixes (PRD seção 11) permanecem distintos "de graça": a chave
normalizada inclui qualquer texto entre parênteses/colchetes (ex.
"(Extended Mix)"), então duas versões da mesma faixa nunca colidem.
"""

from collections import defaultdict
from typing import Dict, List, Optional

from .config import DURATION_TOLERANCE_SECONDS
from .models import Match, TrackInfo
from .normalizer import normalize_artist_title


def _duration_close(a: Optional[float], b: Optional[float], tolerance: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tolerance


def compare_libraries(
    tracks_a: List[TrackInfo],
    tracks_b: List[TrackInfo],
    duration_tolerance: float = DURATION_TOLERANCE_SECONDS,
) -> List[Match]:
    by_hash_b: Dict[str, List[TrackInfo]] = defaultdict(list)
    by_key_b: Dict[str, List[TrackInfo]] = defaultdict(list)

    for track in tracks_b:
        if track.file_hash:
            by_hash_b[track.file_hash].append(track)
        key = normalize_artist_title(track.artist, track.title)
        if key:
            by_key_b[key].append(track)

    matched_b_paths = set()
    matches: List[Match] = []

    for track_a in tracks_a:
        # 1. Correspondência exata por hash.
        hash_candidates = [
            t for t in by_hash_b.get(track_a.file_hash, []) if t.path not in matched_b_paths
        ] if track_a.file_hash else []

        if hash_candidates:
            track_b = hash_candidates[0]
            matches.append(Match(match_type="IDENTICAL", track_a=track_a, track_b=track_b))
            matched_b_paths.add(track_b.path)
            continue

        # 2/3. Mesma chave normalizada (artista+título).
        key = normalize_artist_title(track_a.artist, track_a.title)
        key_candidates = [
            t for t in by_key_b.get(key, []) if t.path not in matched_b_paths
        ] if key else []

        if key_candidates:
            track_b = min(
                key_candidates,
                key=lambda t: abs((t.duration or 0.0) - (track_a.duration or 0.0)),
            )
            if _duration_close(track_a.duration, track_b.duration, duration_tolerance):
                match_type = "SAME_SONG_DIFFERENT_FILE"
            else:
                match_type = "POSSIBLE_DUPLICATE"
            matches.append(Match(match_type=match_type, track_a=track_a, track_b=track_b))
            matched_b_paths.add(track_b.path)
            continue

        # 4. Nenhuma correspondência em B.
        matches.append(Match(match_type="ONLY_A", track_a=track_a, track_b=None))

    for track_b in tracks_b:
        if track_b.path not in matched_b_paths:
            matches.append(Match(match_type="ONLY_B", track_a=None, track_b=track_b))

    return matches
