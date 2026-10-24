# tiny webhook that receives alerts from alertmanager and prints them
# run: python scripts/alert_receiver.py   (listens on :5001)

import json
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

COLORS = {"firing": "\033[91m", "resolved": "\033[92m"}
RESET = "\033[0m"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        data = json.loads(body or b"{}")
        now = datetime.now().strftime("%H:%M:%S")
        for a in data.get("alerts", []):
            status = a.get("status", "?")
            name = a["labels"].get("alertname")
            sev = a["labels"].get("severity", "")
            desc = a.get("annotations", {}).get("description", "")
            print(f"{COLORS.get(status, '')}[{now}] {status.upper():8} {name} ({sev}){RESET} - {desc}", flush=True)
        with open("alerts.log", "a") as f:
            f.write(json.dumps(data) + "\n")
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass  # keep the terminal clean


print("alert receiver listening on :5001 ...", flush=True)
HTTPServer(("0.0.0.0", 5001), Handler).serve_forever()
