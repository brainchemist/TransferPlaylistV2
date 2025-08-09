from uuid import uuid4

def ensure_session_id(request):
    sid = request.query_params.get("session_id") or request.cookies.get("session_id")
    return sid or str(uuid4())