"""Real-provider check for the hosted (Groq) AI path — text, image + text, streaming, status.

Run from backend/ with the key in the environment (it is never printed):

    set GROQ_API_KEY=gsk_...            (PowerShell: $env:GROQ_API_KEY="gsk_...")
    python scripts/hosted_smoke.py [photo.jpg]     (--help for usage)

It uses the same provider class the server uses, so a pass here means Orion's
hosted path works with your key, model and network.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ARGS = argparse.ArgumentParser(
    description="Real-provider check of Orion's hosted (Groq) AI: readiness, text, streaming, "
                "image + text. Needs GROQ_API_KEY (or VF_HOSTED_LLM_API_KEY) in the environment "
                "or backend/.env; the key is never printed.")
ARGS.add_argument("image", nargs="?", type=Path,
                  help="optional photo for the image + text check (a generated nameplate is used otherwise)")

if __name__ == "__main__":
    ARGS.parse_args()  # so --help / bad arguments exit here, before any network use

from app.config import settings  # noqa: E402
from app.models.base import ImageRef  # noqa: E402
from app.models.hosted import HostedGroqProvider  # noqa: E402


def step(name: str, ok: bool, detail: str = "") -> None:
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        sys.exit(1)


async def main() -> None:
    p = HostedGroqProvider()
    h = p.health()
    print(json.dumps({k: getattr(h, k) for k in
                      ("provider", "model_id", "status", "hosted", "accelerator", "npu",
                       "synthetic", "reason")}, indent=2))
    step("provider ready", h.status == "ready", h.reason or "")
    step("no NPU / not synthetic", h.npu is False and h.synthetic is False and h.hosted is True)

    t = time.time()
    out = await p.generate([{"role": "user", "content": "Reply with exactly: pong"}])
    step("text request", bool(out["text"].strip()), f"{out['text'].strip()[:60]!r} in {time.time()-t:.1f}s")

    chunks = []
    async for ev in p.stream([{"role": "user", "content": "Count from 1 to 5, separated by spaces."}]):
        if ev["type"] == "text":
            chunks.append(ev["value"])
    step("streaming", len(chunks) > 1, f"{len(chunks)} chunks: {''.join(chunks).strip()[:60]!r}")

    img = ARGS.parse_args().image
    if img is None:
        from io import BytesIO
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (640, 320), (250, 250, 250))
        ImageDraw.Draw(im).text((40, 140), "NAMEPLATE  CNC-M04  400 VAC", fill=(0, 0, 0))
        img = Path("_smoke.jpg")
        im.save(img, "JPEG")
    ref = ImageRef(id="smoke", path=str(img), mime_type="image/jpeg")
    out = await p.generate([{"role": "user", "content": "What text is written in this image?"}], images=[ref])
    step("image + text request", bool(out["text"].strip()), out["text"].strip()[:100])
    print("\nAll hosted checks passed. Key configured:", bool(settings.hosted_llm_api_key), "(value not shown)")


asyncio.run(main())
