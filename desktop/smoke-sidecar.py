"""Verify desktop lifecycle against the packaged executable and temporary user data."""

import argparse
import hmac
import json
import secrets
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep, time

import httpx
from PIL import Image, ImageDraw, ImageFont


def _wait_for_state(client, path, headers, running):
    started = monotonic()
    while monotonic() - started < 45:
        result = client.get(path, headers=headers).raise_for_status().json()
        if result["state"] not in running:
            return result
        sleep(0.1)
    raise AssertionError(f"Timeout waiting for {path}")


def verify_large_chat(client, root, headers, path_key, pid):
    export = root / "large-synthetic-chat.json"
    with export.open("wb") as stream:
        stream.write(b'{"conversations":[')
        text = "Synthetic conversation filler. " * 36_160
        for index in range(510):
            body = "SELECTED-SYNTHETIC-EVIDENCE" if index == 42 else text
            record = {"id": f"chat-{index}", "title": f"Chat {index}", "messages": [
                {"id": "message", "role": "user", "content": body},
            ]}
            stream.write((b"," if index else b"") + json.dumps(record).encode())
        stream.write(b"]}")
    assert export.stat().st_size >= 500 * 1024**2
    payload = json.dumps({"path": str(export), "purpose": "chat", "issued": time()})
    grant = {"payload": payload, "signature": hmac.digest(path_key, payload.encode(), "sha256").hex()}
    start = monotonic()
    task = client.post("/desktop/chats/preview", json=grant, headers=headers).raise_for_status().json()
    path = "/desktop/chats/" + task["id"]
    ready = _wait_for_state(client, path, headers, {"previewing"})
    duration = monotonic() - start
    assert ready["state"] == "ready" and ready["total_conversations"] == 510, ready
    assert duration < 30
    peak = int(subprocess.check_output([
        "powershell.exe", "-NoProfile", "-Command", f"(Get-Process -Id {pid}).PeakWorkingSet64",
    ], text=True).strip())
    assert peak < 250 * 1024**2, peak
    client.post(path + "/import", json={"conversation_ids": ["chat-42"]}, headers=headers).raise_for_status()
    imported = _wait_for_state(client, path, headers, {"importing"})
    assert imported["state"] == "complete" and imported["items_created"] == 1, imported
    timeline = client.get("/timeline", headers=headers).raise_for_status().json()["items"]
    assert [row["content_text"] for row in timeline] == ["SELECTED-SYNTHETIC-EVIDENCE"], timeline
    print(f"Large chat: {export.stat().st_size} bytes, {duration:.2f}s preview, {peak / 1024**2:.1f} MiB peak.")
    export.unlink()


def verify_ocr(client, root, headers):
    source = client.post("/sources", headers=headers, json={
        "kind": "photo", "name": "OCR synthetic", "consent_version": "smoke",
    }).raise_for_status().json()
    path = root / "ocr-fixture.png"
    image = Image.new("RGB", (800, 170), "white")
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size=54)
    ImageDraw.Draw(image).text((30, 45), "LIFEOS OCR 2026", font=font, fill="black")
    image.save(path)
    with path.open("rb") as file:
        result = client.post(f"/sources/{source['id']}/imports", headers=headers, files={
            "file": ("ocr.png", file, "image/png"),
        }).raise_for_status().json()
    [job_id] = result["job_ids"]
    start = monotonic()
    while monotonic() - start < 30:
        job = client.get("/jobs/" + job_id, headers=headers).raise_for_status().json()
        if job["status"] == "completed":
            items = client.get("/timeline", headers=headers).raise_for_status().json()["items"]
            assert any("LIFEOS OCR 2026" in item["content_text"] for item in items), job
            return
        if job["status"] == "failed":
            raise AssertionError(job)
        sleep(0.2)
    raise AssertionError("OCR timed out.")


def smoke(executable: Path, root: Path, expected_profile: str | None = None, *, verify=False) -> str:
    secret = secrets.token_hex(32)
    path_key = secrets.token_bytes(32)
    with subprocess.Popen(
        [str(executable), str(root)],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            process.stdin.write(f"{secret}\n{path_key.hex()}\n")
            process.stdin.flush()
            line = process.stdout.readline()
            if not line:
                log = root / "logs" / "sidecar.log"
                raise RuntimeError(log.read_text(encoding="utf-8") if log.exists() else "Sidecar exited.")
            port = json.loads(line)["port"]
            with httpx.Client(base_url=f"http://127.0.0.1:{port}/api/v1", trust_env=False) as client:
                assert client.get("/ready").status_code == 401
                headers = {"X-LifeOS-Desktop": secret, "Origin": "http://tauri.localhost"}
                ready = client.get("/ready", headers=headers)
                assert ready.headers["access-control-allow-origin"] == headers["Origin"]
                assert ready.json()["status"] == "ready"
                profile = client.get("/auth/desktop-profile", headers=headers)
                if expected_profile is None:
                    assert profile.status_code == 404
                    profile = client.post("/auth/desktop-profile", headers=headers, json={
                        "timezone": "Asia/Shanghai",
                    })
                profile.raise_for_status()
                result = profile.json()
                profile_id = result["user"]["id"]
                if expected_profile is not None:
                    assert profile_id == expected_profile
                headers["Authorization"] = "Bearer " + result["access_token"]
                assert client.get("/auth/me", headers=headers).json()["timezone"] == "Asia/Shanghai"
                if verify:
                    verify_large_chat(client, root, headers, path_key, process.pid)
                    verify_ocr(client, root, headers)
                    provider_path = "/desktop/analysis/provider"
                    config = {
                        "base_url": "http://127.0.0.1:9/v1", "model": "synthetic",
                        "input_cost_per_million_usd": "1", "output_cost_per_million_usd": "1",
                        "monthly_budget_usd": "0", "max_cost_per_call_usd": "0.05",
                        "privacy_url": "https://example.test/privacy", "retention": "Synthetic local smoke fixture.",
                        "api_key": "not-a-real-model-secret",
                    }
                    try:
                        saved = client.put(provider_path, headers=headers, json=config).raise_for_status().json()
                        assert saved["key_configured"] and "api_key" not in saved
                    finally:
                        client.delete(provider_path, headers=headers).raise_for_status()
            process.stdin.close()
            assert process.wait(timeout=12) == 0
            return profile_id
        finally:
            if process.poll() is None:
                process.kill()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", nargs="?", default="desktop/dist/lifeos-sidecar/lifeos-sidecar.exe")
    parser.add_argument("--full", action="store_true", help="Also verify credentials, OCR and a synthetic 500 MiB import.")
    arguments = parser.parse_args()
    executable = Path(arguments.executable).resolve(strict=True)
    with TemporaryDirectory(prefix="lifeos-sidecar-smoke-") as directory:
        root = Path(directory)
        smoke(executable, root, smoke(executable, root, verify=arguments.full))
    print("Packaged sidecar readiness, access control, persisted profile and graceful exit passed.")
