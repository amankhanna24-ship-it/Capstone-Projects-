"""
run_api.py - start the mock API in a background thread (used by demo.py, chat.py and the tests).

You can also run the API on its own in a second terminal:
    uvicorn mock_api:app --reload --port 8000
"""

import threading
import time

import requests


def api_is_up(base: str) -> bool:
    try:
        return requests.get(base + "/docs", timeout=1).status_code == 200
    except requests.RequestException:
        return False


def start_background(port: int = 8000) -> str:
    base = f"http://127.0.0.1:{port}"
    if api_is_up(base):
        print(f"ℹ️  Mock API already running at {base}")
        return base

    import uvicorn
    from mock_api import app
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):
        if api_is_up(base):
            print(f"✅ Mock API running at {base}  (docs: {base}/docs)")
            return base
        time.sleep(0.1)
    raise RuntimeError("Mock API did not start - is port %d in use?" % port)
