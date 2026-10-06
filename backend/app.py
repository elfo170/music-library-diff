"""DISPLAY: API HTTP (Flask) que expõe scan/compare/operações CRTD e serve
o frontend web local (PRD seção 13).
"""

from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from .config import DATA_DIR, DB_FILENAME
from .db import Database
from .operations import OperationBusy, OperationManager, RESOLUTIONS
from .scan_service import ScanManager

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


def create_app(db_path: Optional[str] = None) -> Flask:
    db = Database(db_path or str(DATA_DIR / DB_FILENAME))
    scan_manager = ScanManager(db)
    op_manager = OperationManager(db, scan_manager)

    app = Flask(__name__, static_folder=None)
    app.config["db"] = db
    app.config["scan_manager"] = scan_manager
    app.config["op_manager"] = op_manager

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/<path:filename>")
    def frontend_assets(filename):
        return send_from_directory(FRONTEND_DIR, filename)

    @app.post("/api/scans")
    def create_scan():
        payload = request.get_json(silent=True) or {}
        library_a = (payload.get("library_a") or "").strip()
        library_b = (payload.get("library_b") or "").strip()
        try:
            scan_id = scan_manager.start_scan(library_a, library_b)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"scan_id": scan_id}), 201

    @app.get("/api/scans/<int:scan_id>")
    def get_scan_status(scan_id):
        progress = scan_manager.get_progress(scan_id)
        if progress is None:
            return jsonify({"error": "Análise não encontrada."}), 404
        percent = int((progress.current / progress.total) * 100) if progress.total else 0
        return jsonify(
            {
                "scan_id": scan_id,
                "phase": progress.phase,
                "current": progress.current,
                "total": progress.total,
                "percent": percent,
                "message": progress.message,
                "errors": progress.errors,
                "summary": progress.summary,
                "error_message": progress.error_message,
            }
        )

    @app.get("/api/scans/<int:scan_id>/matches")
    def get_scan_matches(scan_id):
        if db.get_scan(scan_id) is None:
            return jsonify({"error": "Análise não encontrada."}), 404
        category = request.args.get("category", "all")
        return jsonify({"matches": scan_manager.get_matches(scan_id, category)})

    # ---------- CRTD ----------

    def _check_scan_ready(scan_id):
        if db.get_scan(scan_id) is None:
            return jsonify({"error": "Análise não encontrada."}), 404
        progress = scan_manager.get_progress(scan_id)
        if progress is not None and progress.phase != "done":
            return jsonify({"error": "A análise ainda não terminou."}), 409
        return None

    @app.post("/api/scans/<int:scan_id>/operations/plan")
    def plan_operation(scan_id):
        not_ready = _check_scan_ready(scan_id)
        if not_ready:
            return not_ready
        payload = request.get_json(silent=True) or {}
        try:
            items = op_manager.build_plan(scan_id, payload)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify({"items": op_manager.public_plan(items)})

    @app.post("/api/scans/<int:scan_id>/operations")
    def start_operation(scan_id):
        not_ready = _check_scan_ready(scan_id)
        if not_ready:
            return not_ready
        payload = request.get_json(silent=True) or {}
        if payload.get("confirm") is not True:
            return jsonify({"error": "Confirmação obrigatória."}), 400
        resolutions = payload.get("resolutions") or {}
        if not isinstance(resolutions, dict) or any(v not in RESOLUTIONS for v in resolutions.values()):
            return jsonify({"error": "Resolução de conflito inválida."}), 400
        try:
            op_id = op_manager.start(scan_id, payload, resolutions)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except OperationBusy as exc:
            return jsonify({"error": str(exc)}), 409
        return jsonify({"operation_id": op_id}), 201

    @app.get("/api/operations/<int:op_id>")
    def get_operation(op_id):
        progress = op_manager.get_progress(op_id)
        if progress is None:
            return jsonify({"error": "Operação não encontrada."}), 404
        return jsonify(
            {
                "operation_id": op_id,
                "status": progress.status,
                "total": progress.total,
                "done": progress.done,
                "counts": progress.counts,
                "results": progress.results,
                "summary": progress.summary,
                "error_message": progress.error_message,
            }
        )

    return app
