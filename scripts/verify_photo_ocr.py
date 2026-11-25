"""Verify real OCR and stored photo metadata against a disposable local Compose stack."""

from __future__ import annotations

import argparse
import time
from io import BytesIO
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", help="Local font file with Latin and Simplified Chinese glyphs")
    parser.add_argument("--font-index", type=int, default=0, help="Font face index for a TTC collection")
    parser.add_argument("--port", type=int, default=8000, help="Loopback port for the API or test tunnel")
    args = parser.parse_args()

    image = Image.new("RGB", (1000, 400), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(args.font, 82, index=args.font_index)
    draw.text((60, 40), "PORTABLE NOTES", fill="black", font=font)
    draw.text((60, 185), "中文测试", fill="black", font=font)
    exif = image.getexif()
    exif[34853] = {1: "N", 2: (1, 2, 3), 3: "E", 4: (4, 5, 6)}
    original = BytesIO()
    image.save(original, "JPEG", exif=exif, quality=95)
    with Image.open(original) as photo:
        assert photo.getexif().get_ifd(34853)

    with httpx.Client(base_url=f"http://127.0.0.1:{args.port}/api/v1", timeout=30) as client:
        account = client.post(
            "auth/register",
            json={"email": f"{uuid4().hex}@example.test", "password": uuid4().hex},
        ).raise_for_status().json()
        client.headers["Authorization"] = "Bearer " + account["access_token"]
        try:
            source = client.post("sources", json={"name": "Synthetic bilingual OCR", "kind": "photo"})
            source_id = source.raise_for_status().json()["id"]
            imported = client.post(
                f"sources/{source_id}/imports",
                files={"file": ("synthetic-ocr.jpg", original.getvalue(), "image/jpeg")},
            ).raise_for_status().json()
            item_id = imported["items"][0]["id"]
            job_id, = imported["job_ids"]
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                job = client.get(f"jobs/{job_id}").raise_for_status().json()
                if job["status"] in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(0.25)
            assert job["status"] == "completed", job
            item = client.get(f"items/{item_id}").raise_for_status().json()
            for query in ("PORTABLE", "中文测试"):
                found = client.get("timeline", params={"q": query}).raise_for_status().json()["items"]
                assert any(match["id"] == item_id for match in found), (query, item["content_text"])
            raw = client.get(f"items/{item_id}/raw").raise_for_status()
            with Image.open(BytesIO(raw.content)) as stored:
                assert 34853 not in stored.getexif()
            print("Worker OCR completed, English and Chinese lookup passed, stored GPS removed.")
        finally:
            client.delete("account").raise_for_status()


if __name__ == "__main__":
    main()
