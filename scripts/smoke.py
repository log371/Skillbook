"""Real HTTP -> model -> policy -> document -> audit. Never prints tokens."""

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from importlib.resources import files
from pathlib import Path

import httpx

from skillbook.audit import Audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=["mock", "ollama"], default="mock")
    parser.add_argument("--compose", action="store_true")
    args = parser.parse_args()
    token = secrets.token_urlsafe(32)
    env = {**os.environ, "SKILLBOOK_API_KEY": token, "SKILLBOOK_PROVIDER": args.provider}
    compose = ["docker", "compose", "-p", "skillbook-validation"]
    server = None
    with tempfile.TemporaryDirectory(prefix="skillbook-smoke-") as directory:
        env["SKILLBOOK_AUDIT_DB"] = str(Path(directory) / "audit.sqlite")
        env["SKILLBOOK_RELEASE_STATE"] = ""
        env["SKILLBOOK_TRUSTED_KEY"] = ""
        try:
            if args.compose:
                subprocess.run([*compose, "up", "-d", "--build"], env=env, check=True)
                port = 8000
            else:
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                server = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "skillbook.app:create_app",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--no-access-log",
                    ],
                    env=env,
                )
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port}", timeout=60, trust_env=False
            ) as client:
                for _ in range(60):
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.5)
                else:
                    raise RuntimeError("API did not become healthy")
                assert client.get("/v1/status").status_code == 401
                headers = {"Authorization": "Bearer " + token}
                status = client.get("/v1/status", headers=headers).json()
                results = []
                for fixture in sorted(files("skillbook").joinpath("fixtures").iterdir()):
                    response = client.post(
                        "/v1/run",
                        headers=headers,
                        json={
                            "question": "Consulte le contrat de maintenance.",
                            "context": fixture.read_text(),
                        },
                    )
                    response.raise_for_status()
                    result = response.json()
                    assert "CANARY-RESTRICTED" not in (result["content"] or "")
                    if not result["decision"]["allowed"]:
                        assert result["content"] is None
                    elif fixture.name.startswith("00"):
                        assert "ThermoSud" in result["content"]
                    results.append({"case": fixture.name, "decision": result["decision"]})
                assert results[0]["decision"]["allowed"], "The legitimate control must work"
                report = {"transport": "real-http", "status": status, "cases": results}
                if args.compose:
                    checked = subprocess.run(
                        [
                            *compose,
                            "exec",
                            "-T",
                            "api",
                            "skillbook",
                            "audit",
                            "--database",
                            "/state/audit.sqlite",
                        ],
                        env=env,
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    report["audit"] = json.loads(checked.stdout)
                else:
                    report["audit"] = Audit(Path(env["SKILLBOOK_AUDIT_DB"])).verify()
                print(json.dumps(report, indent=2, ensure_ascii=False))
        except Exception:
            if args.compose:
                subprocess.run([*compose, "logs", "--tail", "30"], env=env, check=False)
            raise
        finally:
            if server:
                server.terminate()
                server.wait(timeout=10)
            if args.compose:
                # Keep the audit volume as evidence, remove only this dedicated stack.
                subprocess.run([*compose, "down"], env=env, check=True)


if __name__ == "__main__":
    main()
