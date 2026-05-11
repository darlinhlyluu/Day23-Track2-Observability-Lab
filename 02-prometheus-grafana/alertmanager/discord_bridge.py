"""Alertmanager-to-Discord webhook bridge.

Alertmanager's Slack payload uses attachments that Discord's Slack-compatible
endpoint may reject. This bridge accepts Alertmanager webhook JSON and posts a
plain Discord `content` message to the real Discord webhook URL.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"].removesuffix("/slack")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        status = payload.get("status", "unknown").upper()
        alerts = payload.get("alerts", [])

        lines = [f"Alertmanager {status}"]
        for alert in alerts:
            labels = alert.get("labels", {})
            annotations = alert.get("annotations", {})
            name = labels.get("alertname", "alert")
            service = labels.get("service", "unknown-service")
            severity = labels.get("severity", "unknown")
            summary = annotations.get("summary", "")
            description = annotations.get("description", "")
            lines.append(f"- {name} [{severity}] on {service}")
            if summary:
                lines.append(f"  {summary}")
            if description:
                lines.append(f"  {description}")

        body = json.dumps({"content": "\n".join(lines)[:1900]}).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Day23-Observability-Lab/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                ok = 200 <= response.status < 300
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"HTTP {exc.code}: {detail}".encode("utf-8"))
            return
        except Exception as exc:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return

        self.send_response(204 if ok else 502)
        self.end_headers()

    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 9119), Handler).serve_forever()
