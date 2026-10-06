"""CRTD: operações de escrita sobre os resultados de uma análise.

Create (copiar para a outra biblioteca), Read (já existente), Transfer
(cópia entre PCs pela rede) e Delete. Não existe Update.

Regras de segurança:
* Só se opera sobre arquivos que pertencem a uma análise e que estão
  dentro da raiz da biblioteca correspondente.
* Toda operação exige um plano prévio (`build_plan`) e confirmação.
* Cópia: grava em arquivo temporário, confere o hash e só então renomeia.
* Exclusão: lixeira no disco local; em pasta de rede o Windows não tem
  lixeira, então a exclusão é permanente (sinalizada no plano).
"""

import hashlib
import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .comparator import compare_libraries
from .config import DURATION_TOLERANCE_SECONDS, HASH_CHUNK_SIZE
from .db import Database
from .hasher import hash_file
from .models import MATCH_TYPES, TrackInfo

try:
    from send2trash import send2trash as _send2trash
except ImportError:  # pragma: no cover
    _send2trash = None

TEMP_PREFIX = ".mld-tmp-"
RESOLUTIONS = ("skip", "overwrite", "keep_both")


class OperationError(Exception):
    pass


class OperationBusy(Exception):
    pass


def is_network_path(path: str) -> bool:
    """True para caminhos UNC (\\\\servidor\\share) e unidades de rede mapeadas."""
    if str(path).startswith("\\\\"):
        return True
    if os.name == "nt":
        try:
            import ctypes

            drive = os.path.splitdrive(str(path))[0]
            if drive:
                return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 4  # DRIVE_REMOTE
        except Exception:  # noqa: BLE001
            return False
    return False


def is_within(root: str, path: str) -> bool:
    root_n = os.path.normcase(os.path.abspath(root))
    path_n = os.path.normcase(os.path.abspath(path))
    try:
        return os.path.commonpath([root_n, path_n]) == root_n
    except ValueError:
        return False


def send_to_trash(path: str) -> None:
    if _send2trash is None:
        raise OperationError("Dependência send2trash não instalada.")
    _send2trash(str(path))


def free_name(path: str) -> str:
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem} ({n}){ext}"):
        n += 1
    return f"{stem} ({n}){ext}"


def copy_verified(src_path: str, dest_path: str) -> str:
    """Copia src -> dest via arquivo temporário e confere o hash. Retorna o hash."""
    dest_dir = os.path.dirname(dest_path)
    os.makedirs(dest_dir, exist_ok=True)
    tmp = os.path.join(dest_dir, f"{TEMP_PREFIX}{uuid.uuid4().hex}.tmp")
    digest = hashlib.blake2b(digest_size=20)
    try:
        with open(src_path, "rb") as fin, open(tmp, "wb") as fout:
            while True:
                chunk = fin.read(HASH_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
                fout.write(chunk)
        expected = digest.hexdigest()
        if hash_file(tmp) != expected:
            raise OperationError("A verificação de hash da cópia falhou; cópia descartada.")
        try:
            shutil.copystat(src_path, tmp)
        except OSError:
            pass  # preservar datas é desejável, mas não essencial
        os.replace(tmp, dest_path)
        return expected
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def rebuild_scan_results(db: Database, scan_id: int) -> Dict[str, int]:
    """Recalcula a comparação a partir do cache e substitui os resultados da análise."""
    scan = db.get_scan(scan_id)
    tracks_a = [TrackInfo.from_cache_row(r, "A") for r in db.get_cached_files_under(scan["library_a_path"])
                if is_within(scan["library_a_path"], r["path"])]
    tracks_b = [TrackInfo.from_cache_row(r, "B") for r in db.get_cached_files_under(scan["library_b_path"])
                if is_within(scan["library_b_path"], r["path"])]
    matches = compare_libraries(tracks_a, tracks_b, DURATION_TOLERANCE_SECONDS)
    db.replace_matches(scan_id, matches)
    summary = {t: 0 for t in MATCH_TYPES}
    for m in matches:
        summary[m.match_type] += 1
    db.update_scan_summary(scan_id, summary)
    return summary


@dataclass
class OperationProgress:
    op_id: int
    scan_id: int
    status: str = "running"  # running | done | error
    total: int = 0
    done: int = 0
    results: List[Dict[str, Any]] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)
    summary: Optional[Dict[str, int]] = None
    error_message: Optional[str] = None


def parse_request(request: Dict[str, Any]) -> Dict[str, Any]:
    op_type = request.get("type")
    if op_type not in ("transfer", "delete"):
        raise ValueError("Tipo de operação inválido.")
    ids = request.get("match_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, int) and not isinstance(i, bool) for i in ids):
        raise ValueError("Selecione ao menos um item.")
    parsed: Dict[str, Any] = {"type": op_type, "match_ids": list(dict.fromkeys(ids))}
    if op_type == "transfer":
        if request.get("direction") not in ("A_TO_B", "B_TO_A"):
            raise ValueError("Direção de transferência inválida.")
        parsed["direction"] = request["direction"]
    else:
        if request.get("sides") not in ("A", "B", "both"):
            raise ValueError("Lado da exclusão inválido.")
        parsed["sides"] = request["sides"]
    return parsed


class OperationManager:
    def __init__(self, db: Database, scan_manager=None):
        self._db = db
        self._scan_manager = scan_manager
        self._lock = threading.Lock()
        self._ops: Dict[int, OperationProgress] = {}
        self._running = False

    # ---------- plano ----------

    def build_plan(self, scan_id: int, request: Dict[str, Any]) -> List[Dict[str, Any]]:
        req = parse_request(request)
        scan = self._db.get_scan(scan_id)
        if scan is None:
            raise LookupError("Análise não encontrada.")
        roots = {"A": scan["library_a_path"], "B": scan["library_b_path"]}
        items: List[Dict[str, Any]] = []

        for match_id in req["match_ids"]:
            match = self._db.get_match(scan_id, match_id)
            if match is None:
                continue
            ref = match["track_a"] or match["track_b"] or {}
            label = f"{ref.get('artist') or 'Artista desconhecido'} - {ref.get('title') or '(sem título)'}"

            if req["type"] == "transfer":
                src = "A" if req["direction"] == "A_TO_B" else "B"
                dest = "B" if src == "A" else "A"
                track = match["track_a" if src == "A" else "track_b"]
                item = self._item(match_id, src, "copy", label, track, dest)
                if track is None:
                    item["skip_reason"] = "Sem arquivo na origem."
                elif match["match_type"] == "IDENTICAL":
                    item["skip_reason"] = "Já existe arquivo idêntico no destino."
                elif not is_within(roots[src], track["path"]):
                    item["skip_reason"] = "Arquivo fora da biblioteca."
                else:
                    rel = os.path.relpath(track["path"], roots[src])
                    dest_path = os.path.join(roots[dest], rel)
                    item["dest_path"] = dest_path
                    if os.path.exists(dest_path):
                        st = os.stat(dest_path)
                        item["conflict"] = {"size": st.st_size, "mtime": st.st_mtime}
                items.append(item)
            else:
                sides = ["A", "B"] if req["sides"] == "both" else [req["sides"]]
                for side in sides:
                    track = match["track_a" if side == "A" else "track_b"]
                    if track is None:
                        continue
                    item = self._item(match_id, side, "delete", label, track, None)
                    if not is_within(roots[side], track["path"]):
                        item["skip_reason"] = "Arquivo fora da biblioteca."
                    else:
                        item["permanent"] = is_network_path(track["path"])
                    items.append(item)
        return items

    @staticmethod
    def _item(match_id, side, action, label, track, dest_label) -> Dict[str, Any]:
        return {
            "key": f"{match_id}:{side}",
            "match_id": match_id,
            "action": action,
            "label": label,
            "src_label": side,
            "dest_label": dest_label,
            "src_path": track["path"] if track else None,
            "dest_path": None,
            "permanent": False,
            "conflict": None,
            "skip_reason": None,
            "track": track,
        }

    @staticmethod
    def public_plan(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{k: v for k, v in i.items() if k != "track"} for i in items]

    # ---------- execução ----------

    def start(self, scan_id: int, request: Dict[str, Any], resolutions: Dict[str, str]) -> int:
        items = self.build_plan(scan_id, request)
        req = parse_request(request)
        with self._lock:
            if self._running:
                raise OperationBusy("Já existe uma operação em andamento.")
            self._running = True
        try:
            op_id = self._db.create_operation(scan_id, req["type"], req)
            progress = OperationProgress(op_id=op_id, scan_id=scan_id, total=len(items))
            with self._lock:
                self._ops[op_id] = progress
            threading.Thread(
                target=self._run, args=(progress, items, resolutions or {}), daemon=True
            ).start()
        except Exception:
            with self._lock:
                self._running = False
            raise
        return op_id

    def get_progress(self, op_id: int) -> Optional[OperationProgress]:
        with self._lock:
            return self._ops.get(op_id)

    def _run(self, progress: OperationProgress, items, resolutions) -> None:
        try:
            for item in items:
                status, message = self._execute(item, resolutions.get(item["key"]))
                self._db.add_operation_item(
                    progress.op_id, item["action"], item["src_path"], item["dest_path"], status, message
                )
                with self._lock:
                    progress.done += 1
                    progress.counts[status] = progress.counts.get(status, 0) + 1
                    progress.results.append(
                        {"key": item["key"], "label": item["label"], "action": item["action"],
                         "src_path": item["src_path"], "status": status, "message": message}
                    )
            summary = rebuild_scan_results(self._db, progress.scan_id)
            if self._scan_manager is not None:
                self._scan_manager.set_summary(progress.scan_id, summary)
            self._db.finish_operation(progress.op_id, "done", progress.counts)
            with self._lock:
                progress.summary = summary
                progress.status = "done"
        except Exception as exc:  # noqa: BLE001
            self._db.finish_operation(progress.op_id, "error", {"error": str(exc)})
            with self._lock:
                progress.status = "error"
                progress.error_message = str(exc)
        finally:
            with self._lock:
                self._running = False

    def _execute(self, item: Dict[str, Any], resolution: Optional[str]):
        if item["skip_reason"]:
            return "skipped", item["skip_reason"]
        if item["action"] == "copy":
            return self._execute_copy(item, resolution)
        return self._execute_delete(item)

    def _execute_copy(self, item, resolution):
        src, dest = item["src_path"], item["dest_path"]
        if not os.path.exists(src):
            return "failed", "Arquivo de origem não encontrado."
        if os.path.exists(dest):
            if resolution == "keep_both":
                dest = free_name(dest)
            elif resolution == "overwrite":
                pass
            elif resolution == "skip":
                return "skipped", "Mantido o arquivo existente no destino."
            else:
                return "skipped", "Conflito sem resolução; nada foi alterado."
        try:
            file_hash = copy_verified(src, dest)
            st = os.stat(dest)
            track = dict(item["track"])
            self._db.upsert_cached_file(
                TrackInfo(
                    path=dest, library=item["dest_label"], size=st.st_size, mtime=st.st_mtime,
                    file_hash=file_hash, artist=track.get("artist"), title=track.get("title"),
                    album=track.get("album"), album_artist=track.get("album_artist"),
                    duration=track.get("duration"), format=track.get("format"),
                    bitrate=track.get("bitrate"), sample_rate=track.get("sample_rate"),
                    bit_depth=track.get("bit_depth"), error=None,
                )
            )
            return "ok", f"Copiado para {dest}"
        except Exception as exc:  # noqa: BLE001
            return "failed", str(exc)

    def _execute_delete(self, item):
        path = item["src_path"]
        if not os.path.exists(path):
            self._db.delete_cached_file(path)
            return "skipped", "Arquivo não encontrado (removido dos resultados)."
        try:
            if item["permanent"]:
                os.remove(path)
                message = "Excluído permanentemente."
            else:
                send_to_trash(path)
                message = "Enviado para a lixeira."
            self._db.delete_cached_file(path)
            return "ok", message
        except Exception as exc:  # noqa: BLE001
            return "failed", str(exc)
