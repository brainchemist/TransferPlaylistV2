import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import webbrowser
import requests
from starlette.requests import Request
from starlette.responses import HTMLResponse

from main import app

CLIENT_ID = os.getenv("SCCLIENT_ID")
CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
REDIRECT_URI = os.getenv("SCREDIRECT_URI")
TOKEN_FILE = os.getenv("SCTOKEN_FILE", "soundcloud_token.json")

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)


def soundcloud_callback(port=8000):
    code_container = {}

    class RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed_url = urlparse(self.path)
            query_params = parse_qs(parsed_url.query)
            code = query_params.get("code", [None])[0]
            code_container['code'] = code

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write("✅ Authorization complete. You can close this window.")

        def log_message(self, format, *args):
            return  # Silence the default HTTP server logs

    def run_server():
        server = HTTPServer(("localhost", port), RedirectHandler)
        server.timeout = 60  # fail after 60s
        server.handle_request()

    thread = threading.Thread(target=run_server)
    thread.daemon = True
    thread.start()

    print(f"🌐 Waiting for SoundCloud redirect at http://localhost:{port}/soundcloud/callback ...")
    thread.join(timeout=60)

    if code_container.get("code"):
        return code_container["code"]

    # Fallback if browser didn’t redirect
    print("❌ Auto-redirect failed.")
    print("👉 Paste the full redirected URL from your browser (you’ll see ?code=...):")
    redirected_url = input("📋 URL: ").strip()

    parsed = urlparse(redirected_url)
    code = parse_qs(parsed.query).get("code", [None])[0]

    return code