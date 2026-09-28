#!/usr/bin/env python3
"""Exercise text reasoning, image + text reasoning, and Orion's own router
prompt against the REAL Qwen3-VL-4B-Instruct weights — without Snapdragon
hardware — using Qualcomm's own quantization-accuracy demo.

This is the companion to scripts/aihub_devicecloud_validate.py, and the two
are not interchangeable:

* aihub_devicecloud_validate.py submits real compile/profile/inference JOBS
  to a physical, hosted Snapdragon device (Device Cloud). It proves the model
  and the QAIRT/NPU runtime on real Snapdragon silicon, but Qualcomm's
  documented tooling only lets that job run one fixed prefill/decode step —
  it does not drive a free-form, multi-turn chat loop remotely.

* THIS script runs `qai-hub-models demo qwen3_vl_4b_instruct`, Qualcomm's own
  demo entry point for this model, LOCALLY on whatever CPU/GPU this machine
  has. With no on-device checkpoint supplied it uses the AIMET-ONNX quantized
  simulation of the exact same weights that ship to QAIRT — real generated
  text from the real model — but it never touches an NPU. Every result this
  script reports carries "accelerator: cpu (simulated)" and "npu: false", and
  nothing it produces may be read as an NPU claim. It exists to answer text
  reasoning, image + text reasoning, and Orion's router — which need full
  generation — using Qualcomm's own supported code path, honestly labelled.

Neither script touches app/models/geniex.py, the registry, or Orion's own
`/api/models/status`: that provider is unchanged and still reports its own,
separately-earned NPU status only when it actually runs on Snapdragon
(docs/SNAPDRAGON_SETUP.md).

Setup: `pip install qai-hub-models`, plus Hugging Face access to
https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct (`huggingface-cli login`).
No Qualcomm AI Hub account is needed for this script — it never contacts
Device Cloud.

Usage:

    python scripts/aihub_router_text_image_check.py
    python scripts/aihub_router_text_image_check.py --image path/to/photo.jpg
    python scripts/aihub_router_text_image_check.py --skip-image   # faster, no ViT pass
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Tuple

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

MODEL_MODULE = "qai_hub_models.models.qwen3_vl_4b_instruct.demo"
REPORT_PATH = Path(__file__).resolve().parent / "aihub_router_text_image_report.json"

# Router QA set, same clear-cut cases as tests/test_geniex_hardware.py, so the
# two validation paths (on-device NPU, and this CPU simulation of the real
# weights) can be compared against the same bar.
ROUTER_QA: List[Tuple[str, str]] = [
    ("hellooo", "conversation"),
    ("do you like cats?", "conversation"),
    ("my motor is vibrating", "technical"),
    ("the breaker trips after a few minutes", "technical"),
    ("there are sparks coming from the panel", "technical"),
]


def run_demo(prompt: str, image: str | None, max_tokens: int = 200) -> str:
    """Call Qualcomm's own `qai-hub-models demo qwen3_vl_4b_instruct` in
    process (import + call main(), Qualcomm's own tested entry point) and
    capture what it prints, since the demo writes the generated text to
    stdout rather than returning it."""
    argv = [sys.argv[0], "--prompt", prompt, "--max-output-tokens", str(max_tokens),
            "--raw"]
    if image:
        argv += ["--image", image]
    old_argv = sys.argv
    buf = io.StringIO()
    try:
        sys.argv = argv
        import importlib

        demo = importlib.import_module(MODEL_MODULE)
        with redirect_stdout(buf):
            demo.main()
    finally:
        sys.argv = old_argv
    return buf.getvalue()


def _generated_text(demo_output: str) -> str:
    """The demo prints prompt/config lines then streams the reply; take
    everything after the last '-'*85 divider, which the demo prints right
    before generation starts."""
    parts = demo_output.split("-" * 85)
    return (parts[-1] if parts else demo_output).strip()


def check(name: str, fn) -> Tuple[bool, str, Any]:
    try:
        detail, payload = fn()
        return True, detail, payload
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--image", default=None,
                  help="Path to a real photo for the image+text check. Defaults to "
                       "this model's own bundled sample image (a dog).")
    p.add_argument("--skip-image", action="store_true",
                  help="Skip the image+text check (the ViT pass is the slow part).")
    p.add_argument("--max-tokens", type=int, default=200)
    args = p.parse_args()

    report: Dict[str, Any] = {"started": time.strftime("%Y-%m-%d %H:%M:%S"),
                              "model": "Qwen3-VL-4B-Instruct",
                              "accelerator": "cpu (simulated)", "npu": False,
                              "note": "Local AIMET-ONNX quantization simulation — NOT "
                                      "an on-device NPU run. See this script's docstring."}
    results: List[Dict[str, Any]] = []

    print("Loading Qwen3-VL-4B-Instruct (quantized simulation)... this downloads the "
          "weights on first run and can take a while.\n")

    def _text_check():
        out = run_demo("Hi! In one short sentence, what can you help me with?",
                       image=None, max_tokens=args.max_tokens)
        text = _generated_text(out)
        assert len(text) > 3, f"empty/short reply: {text!r}"
        return text[:120], {"reply": text}

    ok, detail, payload = check("text conversation", _text_check)
    results.append({"check": "text_conversation", "ok": ok, "detail": detail})
    if ok:
        report["text_conversation"] = payload

    if not args.skip_image:
        def _image_check():
            image_path = args.image
            if image_path is None:
                from qai_hub_models.models.qwen3_vl_4b_instruct.model import SAMPLE_IMAGE

                image_path = str(SAMPLE_IMAGE.fetch())
            out = run_demo("Describe what is in this image in one sentence.",
                           image=image_path, max_tokens=args.max_tokens)
            text = _generated_text(out)
            assert len(text) > 3, f"empty/short reply: {text!r}"
            return text[:160], {"image": image_path, "reply": text}

        ok, detail, payload = check("image + text reasoning", _image_check)
        results.append({"check": "image_text_reasoning", "ok": ok, "detail": detail})
        if ok:
            report["image_text_reasoning"] = payload

    # Orion's real router prompt and real schema, against this real model —
    # only the generation path (local simulation, not GenieX/QAIRT) differs
    # from what runs in production.
    from app.agent import router as orion_router

    routing: List[Dict[str, Any]] = []
    router_ok = True
    for message, expected in ROUTER_QA:
        def _one(message=message, expected=expected):
            messages = orion_router.build_messages(message, history=(), mode="normal",
                                                    attachments=())
            prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]
            out = run_demo(prompt, image=None, max_tokens=200)
            raw = _generated_text(out)
            parsed = orion_router.validate(orion_router._extract_json(raw))
            assert parsed is not None, f"not valid router JSON: {raw[:200]!r}"
            got = parsed["intent"]
            routing.append({"message": message, "expected": expected, "got": got,
                            "confidence": parsed["confidence"]})
            assert got == expected, f"expected {expected}, got {got}"
            return f"{got} ({parsed['confidence']:.2f})", None

        ok, detail, _ = check(f"router: {message!r} -> {expected}", _one)
        results.append({"check": f"router_{message!r}", "ok": ok, "detail": detail})
        router_ok = router_ok and ok

    report["router_results"] = routing
    report["results"] = results
    report["ok"] = all(r["ok"] for r in results)

    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    print()
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  {mark}  {r['check']}  —  {r['detail']}")
    print(f"\n{'PASS' if report['ok'] else 'FAIL'}: "
          f"{sum(r['ok'] for r in results)}/{len(results)} checks. "
          f"Every result above ran on {report['accelerator']} — never claim this as an "
          f"NPU result. Evidence written to {REPORT_PATH}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
