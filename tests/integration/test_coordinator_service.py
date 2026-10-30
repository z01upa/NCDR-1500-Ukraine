"""Live lifecycle check for the paused, local coordinator service."""

from __future__ import annotations

import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.parse
import urllib.error
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=3) as response:
        return response.status, response.read()


def _control(url: str, token: str, state: str) -> dict:
    body = json.dumps({"state": state}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-NCDR-Control": token,
        "Origin": urllib.parse.urlunsplit((*urllib.parse.urlsplit(url)[:2], "", "", "")),
    })
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


class CoordinatorServiceTests(unittest.TestCase):
    def test_pause_stop_restart_and_persistent_checkpoint(self) -> None:
        from src.agent.coordinator_runtime import set_control

        port = _free_port()
        base = f"http://127.0.0.1:{port}"
        set_control("PAUSED", "service lifecycle integration test")
        process: subprocess.Popen | None = None
        try:
            for cycle in range(2):
                process = subprocess.Popen(
                    [sys.executable, "-m", "src.agent.coordinator", "--service", "--dashboard-port", str(port)],
                    cwd=PROJECT_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                page = b""
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    try:
                        _status, page = _get(base + "/")
                        break
                    except (OSError, urllib.error.URLError):
                        if process.poll() is not None:
                            self.fail(f"service exited during startup with {process.returncode}")
                        time.sleep(0.2)
                self.assertIn(b"live-readiness", page)
                token_match = re.search(rb"const NCDR_TOKEN=\"([^\"]+)\"", page)
                self.assertIsNotNone(token_match, "live dashboard omitted the control token")
                token = token_match.group(1).decode("ascii")
                _status, state_bytes = _get(base + "/api/state")
                state = json.loads(state_bytes)
                self.assertEqual(state["sqlite_integrity"], "ok")
                self.assertIn("OSM Ukraine", state["system_readiness"])
                if cycle == 0:
                    self.assertEqual(state["control"]["desired_state"], "PAUSED")
                result = _control(base + "/api/control", token, "STOP_REQUESTED")
                self.assertTrue(result["ok"])
                process.wait(timeout=15)
                self.assertEqual(process.returncode, 0)
                process = None

            import sqlite3
            with sqlite3.connect(PROJECT_ROOT / "project_state.sqlite") as conn:
                desired, worker = conn.execute(
                    "SELECT desired_state,worker_state FROM coordinator_control WHERE id=1"
                ).fetchone()
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            self.assertEqual((desired, worker, integrity), ("STOPPED", "STOPPED", "ok"))
        finally:
            if process is not None and process.poll() is None:
                try:
                    page = _get(base + "/")[1]
                    token_match = re.search(rb"const NCDR_TOKEN=\"([^\"]+)\"", page)
                    if token_match:
                        _control(base + "/api/control", token_match.group(1).decode("ascii"), "STOP_REQUESTED")
                    process.wait(timeout=10)
                except Exception:
                    process.terminate()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
