"""DISPLAY: API HTTP (Flask) que expõe o scan/compare e serve o
frontend web local (PRD seção 13).
"""

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .config import DATA_DIR, DB_FILENAME
from .db import Database
from .scan_service import ScanManager

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

db = Database(str(DATA_DIR / DB_FILENAME))
scan_manager = ScanManager(db)

app = Flask(__name__, static_folder=None)


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
    matches = scan_manager.get_matches(scan_id, category)
    return jsonify({"matches": matches})


def create_app() -> Flask:
    return app
