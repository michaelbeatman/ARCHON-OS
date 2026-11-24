# -*- coding: utf-8 -*-
"""Audit D10/E2E: Dead-Man-Switch ueber die bestehende Alertmanager-Route."""
import http.server
import json
import threading


def test_alertmanager_heartbeat_posts_self_expiring_alert(monkeypatch):
    captured = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            captured.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]

    try:
        from backend import fleet_self_healing as fsh

        monkeypatch.setenv(
            "ARCHON_HEARTBEAT_ALERTMANAGER_URL",
            f"http://127.0.0.1:{port}/api/v2/alerts",
        )
        monkeypatch.setenv("ARCHON_HEARTBEAT_ALERT_TTL_S", "180")
        monkeypatch.setattr(fsh, "_ALERTMANAGER_LAST_TS", 0.0)

        assert fsh._post_alertmanager_heartbeat("ok", force=True, tick_count=7) is True
        assert len(captured) == 1
        alert = captured[0][0]
        assert alert["labels"]["alertname"] == "ArchonHeartbeat"
        assert alert["labels"]["service"] == "archon-os"
        assert alert["labels"]["status"] == "ok"
        assert alert["endsAt"] > alert["startsAt"]
        assert "tick_count" in alert["annotations"]["description"]

        # Ohne URL ist der Sender ein No-op (fail-closed, kein Crash).
        monkeypatch.delenv("ARCHON_HEARTBEAT_ALERTMANAGER_URL")
        assert fsh._post_alertmanager_heartbeat("ok", force=True) is False
    finally:
        server.shutdown()
        server.server_close()
