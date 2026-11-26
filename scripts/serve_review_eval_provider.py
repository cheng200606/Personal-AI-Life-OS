"""Deterministic loopback OpenAI-compatible provider for review evaluation."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class ReviewProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/v1/chat/completions":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 5 * 1024 * 1024:
            self.send_error(413)
            return
        request = json.loads(self.rfile.read(length))
        evidence = json.loads(request["messages"][-1]["content"])
        facts = [
            {"text": str(item.get("text") or item.get("title") or "Synthetic evidence"), "source_ids": [item["source_id"]]}
            for item in evidence[:5]
            if item.get("source_id")
        ]
        content = json.dumps({"facts": facts, "suggestions": []}, ensure_ascii=False)
        body = json.dumps(
            {
                "choices": [{"message": {"content": content}}],
                "usage": {
                    "prompt_tokens": sum(len(str(value)) for value in request["messages"]),
                    "completion_tokens": len(content),
                },
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18114)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ReviewProviderHandler)
    print(f"review evaluation provider listening on http://{args.host}:{args.port}/v1", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
