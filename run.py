"""Ponto de entrada: `python run.py` inicia o Music Library Diff em
http://127.0.0.1:5000
"""

from backend.app import app

if __name__ == "__main__":
    print("Music Library Diff rodando em http://127.0.0.1:5000  (Ctrl+C para parar)")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
