from uuid import uuid4

def ensure_session_id(request):
    sid = request.query_params.get("session_id") or request.cookies.get("session_id")
    return sid or str(uuid4())


from typing import Dict

_PROGRESS: Dict[str, Dict[str, object]] = {}

def set_progress(session_id: str, percent: int, message: str):
    if percent < 0: percent = 0
    if percent > 100: percent = 100
    _PROGRESS[session_id] = {"percent": percent, "message": message}

def get_progress(session_id: str):
    return _PROGRESS.get(session_id, {"percent": 0, "message": "Queued…"})
