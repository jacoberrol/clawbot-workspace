#!/usr/bin/env python3
"""
Teller Connect setup server.
Run this, open http://localhost:8000 in Chrome, connect Chase.
The access token will be saved automatically.
"""

import http.server
import json
import os
import sys
import webbrowser
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "teller-config.json"
HTML_FILE = SCRIPT_DIR / "connect.html"

def load_config():
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}

def save_config(data):
    CONFIG_FILE.write_text(json.dumps(data, indent=2))

class Handler(http.server.BaseHTTPRequestHandler):
    app_id = None

    def log_message(self, format, *args):
        pass  # Suppress default logging

    def do_GET(self):
        if self.path == "/" or self.path == "/connect":
            html = HTML_FILE.read_text()
            # Inject the app ID
            html = html.replace(
                "window.TELLER_APP_ID;",
                f'"{self.app_id}";'
            )
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/token":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.request.recv(length) if length else b"{}")
            # Try to read from socket directly
            try:
                length = int(self.headers.get("Content-Length", 0))
                raw = self.rfile.read(length)
                body = json.loads(raw)
            except Exception:
                body = {}

            token = body.get("access_token")
            if token:
                config = load_config()
                config["access_token"] = token
                save_config(config)
                print(f"\n✅ Access token received and saved!")
                print(f"   Token: {token[:8]}...{token[-4:]}")
                print(f"\n   You can now close the browser and Ctrl+C this server.")
                print(f"   Then tell Bot: 'Teller is set up'")

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok": true}')
        else:
            self.send_response(404)
            self.end_headers()


def main():
    config = load_config()

    # Get or prompt for app ID
    app_id = config.get("app_id")
    if not app_id:
        print("Teller Connect Setup")
        print("=" * 40)
        print("Find your Application ID at: https://teller.io/settings/application")
        app_id = input("Enter your Teller Application ID: ").strip()
        if not app_id:
            print("No app ID provided. Exiting.")
            sys.exit(1)
        config["app_id"] = app_id
        save_config(config)

    # Get or prompt for cert paths
    cert = config.get("certificate")
    key = config.get("private_key")

    if not cert or not Path(cert).exists():
        print("\nWhere is your teller.zip or certificate.pem?")
        print("(Download from https://teller.io/settings/certificates)")
        cert_path = input("Path to certificate.pem: ").strip()
        key_path = input("Path to private_key.pem: ").strip()
        config["certificate"] = cert_path
        config["private_key"] = key_path
        save_config(config)

    Handler.app_id = app_id

    port = 8000
    server = http.server.HTTPServer(("localhost", port), Handler)
    url = f"http://localhost:{port}"

    print(f"\n🚀 Server running at {url}")
    print("Opening browser... if it doesn't open, go there manually.")
    print("Press Ctrl+C when done.\n")

    try:
        webbrowser.open(url)
    except Exception:
        pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
