#!/usr/bin/env python3
"""Prove Orion runs on the real Qwen3-VL-4B-Instruct through GenieX/QAIRT.

Run on the Snapdragon machine, from backend\\, after docs/SNAPDRAGON_SETUP.md:

    python scripts\\geniex_smoke.py

It boots the whole Orion backend in-process with
VF_REASONING_PROVIDER=geniex-qwen3-vl (against a throwaway data folder, so
your real conversations are untouched), loads the model once, and checks:

  1. Orion reaches the real model          (the provider is READY, not a stand-in)
  2. It runs through GenieX/QAIRT          (the handle and every generation say so)
  3. The runtime reports the NPU           (backend=qairt, device=NPU, probe ran)
  4. Text conversation works               (direct + through /api/chat)
  5. Image + text works                    (two different pictures, answers follow the pixels)
  6. Semantic routing works                (the model's own router decisions)
  7. No Ollama dependency exists           (nothing local-HTTP selected or imported)

Every number printed comes from the runtime. The full evidence is written to
geniex_smoke_report.json next to this script; that file is what goes into
MODEL_STATUS.md. Exit code 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import platform
import socket
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Must be decided before the app reads its settings.
os.environ["VF_REASONING_PROVIDER"] = "geniex-qwen3-vl"
os.environ.setdefault("VF_RATE_LIMIT_PER_MINUTE", "0")
os.environ.setdefault("VF_HEAVY_RATE_LIMIT_PER_MINUTE", "0")

GREEN, RED, YELLOW, DIM, BOLD, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[2m", "\033[1m", "\033[0m")
if os.name == "nt":
    os.system("")  # enable ANSI colours in the Windows console

results: List[Tuple[str, bool, str]] = []
report: Dict[str, Any] = {"started": time.strftime("%Y-%m-%d %H:%M:%S"),
                          "host": {"system": platform.system(), "release": platform.release(),
                                   "machine": platform.machine(),
                                   "python": platform.python_version(),
                                   "processor": platform.processor()}}


def check(name: str, fn: Callable[[], Optional[str]]) -> bool:
    try:
        detail = fn() or ""
        ok = True
    except AssertionError as exc:
        ok, detail = False, str(exc) or "assertion failed"
    except Exception as exc:  # report, keep going
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    results.append((name, ok, detail))
    mark = f"{GREEN}PASS{RESET}" if ok else f"{RED}FAIL{RESET}"
    print(f"  {mark}  {name}" + (f"  {DIM}{detail}{RESET}" if detail else ""), flush=True)
    return ok


def swatch(colour: Tuple[int, int, int], code: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (448, 448), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([74, 40, 374, 340], fill=colour)
    try:
        font = ImageFont.load_default(size=64)
    except TypeError:
        font = ImageFont.load_default()
    d.text((150, 360), code, fill=(0, 0, 0), font=font)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="orion_geniex_smoke_"))

    from app.config import settings

    settings.data_dir = tmp
    settings.access_token = ""
    settings.reasoning_provider = "geniex-qwen3-vl"

    print(f"\n{BOLD}Orion × Qwen3-VL-4B-Instruct × GenieX/QAIRT smoke test{RESET}")
    print(f"{DIM}host: {report['host']['system']} {report['host']['machine']} "
          f"Python {report['host']['python']}   scratch data: {tmp}{RESET}")
    if platform.machine().upper() not in ("ARM64", "AARCH64"):
        print(f"{YELLOW}  note: this Python reports {platform.machine()}; GenieX needs "
              f"ARM64 Python on Windows.{RESET}")
    print(f"{DIM}loading the model (first load can take a minute)...{RESET}\n", flush=True)

    from fastapi.testclient import TestClient

    from app.agent import router
    from app.main import app
    from app.models.base import ImageRef
    from app.models.geniex import GenieXQwen3VLProvider
    from app.models.registry import registry as models

    t0 = time.perf_counter()
    with TestClient(app) as client:
        load_s = round(time.perf_counter() - t0, 1)
        status = client.get("/api/models/status").json()
        role = status["roles"]["reasoning"]
        report["startup_s"] = load_s
        report["reasoning_status"] = role
        reasoner = models.reasoning()

        # ---------------------------------------------------------- 1
        print(f"{BOLD}1. Orion reaches the real model{RESET}")

        def reached():
            why = "; ".join(str(a.get("reason")) for a in role.get("candidates_tried") or [])
            assert isinstance(reasoner, GenieXQwen3VLProvider), \
                f"reasoning is {type(reasoner).__name__}: {why or role.get('reason')}"
            assert role["status"] == "ready", f"not ready: {role.get('reason')}"
            assert role["synthetic"] is False
            assert role["model_id"] == "Qwen3-VL-4B-Instruct", role["model_id"]
            return f"{role['model_id']} ready in {role.get('load_ms')} ms (backend up in {load_s}s)"

        if not check("reasoning provider is the loaded Qwen3-VL-4B-Instruct", reached):
            print(f"\n{RED}The model did not load, so nothing else can be tested.{RESET}")
            print("candidates tried:", json.dumps(role.get("candidates_tried"), indent=2))
            return finish(tmp)

        d = role["detail"]

        # ---------------------------------------------------------- 2
        print(f"\n{BOLD}2. It runs through GenieX/QAIRT{RESET}")
        check("provider is GenieX/QAIRT", lambda: (
            _eq(role["provider"], "GenieX/QAIRT") or
            f"geniex {d.get('geniex_version')}, qairt plugin {d.get('qairt_plugin_version')}"))
        check("model handle created on the qairt plugin", lambda: (
            _eq(d["handle"]["backend"], "qairt") or f"bundle {d['handle'].get('model_path')}"))
        check("probe generation ran on qairt", lambda: (
            _eq(d["probe"]["backend"], "qairt") or
            f"{d['probe']['generated_tokens']} tokens, {d['probe']['decode_speed']:.1f} tok/s"))

        # ---------------------------------------------------------- 3
        print(f"\n{BOLD}3. The runtime reports the NPU{RESET}")
        check("runtime lists QAIRT with an NPU compute unit", lambda: (
            _true("qairt" in d.get("runtimes", []), f"runtimes: {d.get('runtimes')}") or
            _true(any("NPU" in str(u).upper() for cu in d.get("qairt_compute_units") or []
                      for u in cu), f"compute units: {d.get('qairt_compute_units')}") or
            f"chipset {d.get('chipset')}, units {d.get('qairt_compute_units')}"))
        check("handle device is NPU", lambda: (
            _eq(str(d["handle"]["device"]).upper(), "NPU") or "device=NPU"))
        check("status reports accelerator=npu, npu=true", lambda: (
            _true(role["npu"] is True and role["accelerator"] == "npu",
                  f"accelerator={role['accelerator']} npu={role['npu']}: {d.get('npu_verdict')}")
            or d.get("npu_verdict")))

        # ---------------------------------------------------------- 4
        print(f"\n{BOLD}4. Text conversation{RESET}")

        def direct_text():
            out = asyncio.run(reasoner.generate(
                [{"role": "system", "content": "You are Orion. Be brief."},
                 {"role": "user", "content": "Say hello and tell me one thing you can do."}],
                context={"purpose": "conversation", "temperature": 0.6, "max_tokens": 80}))
            p = out["usage"]["profile"]
            report["text_direct"] = {"text": out["text"], "profile": p}
            _true(len(out["text"].strip()) > 5, "empty reply")
            _eq(p["backend"], "qairt")
            return f"{p['generated_tokens']} tok @ {p['decode_speed']:.1f} tok/s: {out['text'][:70]!r}"

        check("direct generation", direct_text)

        def chat_text():
            body = client.post("/api/chat", json={"message": "hey Orion, how's it going?"}).json()
            report["chat_text"] = _brief(body)
            _true(body.get("engine_available") is True, f"engine unavailable: {body.get('text')}")
            _eq(body["kind"], "conversation")
            _eq(body["model"]["model_id"], "Qwen3-VL-4B-Instruct")
            return f"{body['duration_ms']:.0f} ms: {body['text'][:70]!r}"

        check("/api/chat small talk -> conversation", chat_text)

        # ---------------------------------------------------------- 5
        print(f"\n{BOLD}5. Image + text{RESET}")
        swatches = {"red": ((220, 20, 20), "E42"), "blue": ((20, 60, 220), "F17")}
        report["image_direct"] = {}
        for name, (rgb, code) in swatches.items():
            def direct_image(name=name, rgb=rgb, code=code):
                path = tmp / f"{name}.jpg"
                path.write_bytes(swatch(rgb, code))
                ref = ImageRef(id=name, path=str(path), width=448, height=448)
                out = asyncio.run(reasoner.generate(
                    [{"role": "user", "content": "What colour is the large circle, and what code "
                                                 "is printed under it? Answer as: colour, code"}],
                    images=[ref],
                    context={"purpose": "technical", "temperature": 0.0, "max_tokens": 40}))
                p = out["usage"]["profile"]
                report["image_direct"][name] = {"text": out["text"], "profile": p}
                _true(name in out["text"].lower(), f"expected {name}: {out['text']!r}")
                return (f"{out['text'][:50]!r}  media {p.get('media_time')} ms, "
                        f"code read: {code.lower() in out['text'].lower()}")

            check(f"{name} picture -> answer says {name}", direct_image)

        def chat_image():
            up = client.post("/api/photo/upload", files={
                "file": ("panel.jpg", swatch((220, 20, 20), "E42"), "image/jpeg")}).json()
            body = client.post("/api/chat", json={
                "message": "What colour is the indicator in this photo, and what code is shown?",
                "image_ids": [up["image_id"]],
                "attachments": [{"kind": "image", "name": "panel.jpg"}]}).json()
            report["chat_image"] = _brief(body)
            _true(body.get("engine_available") is True, f"engine unavailable: {body.get('text')}")
            _true(body["kind"] != "fallback", "fallback reply")
            full = (body.get("text") or "") + json.dumps(body.get("sections") or [])
            _true("red" in full.lower(), f"reply does not mention red: {body.get('text', '')[:120]!r}")
            return f"kind={body['kind']} in {body['duration_ms']:.0f} ms"

        check("/api/chat with an uploaded photo", chat_image)

        # ---------------------------------------------------------- 6
        print(f"\n{BOLD}6. Semantic routing (the model's own decisions){RESET}")
        cases = [("hellooo", "conversation"), ("do you like cats?", "conversation"),
                 ("my motor is vibrating", "technical"),
                 ("the breaker trips after a few minutes", "technical"),
                 ("something's wrong", "ambiguous")]
        report["routing"] = []
        for msg, want in cases:
            def one(msg=msg, want=want):
                t = time.perf_counter()
                dec = asyncio.run(router.route(reasoner, msg))
                report["routing"].append({"message": msg, "expected": want, "got": dec.intent,
                                          "confidence": dec.confidence, "available": dec.available,
                                          "ms": round((time.perf_counter() - t) * 1000)})
                _true(dec.available, f"router unavailable: {dec.failure}")
                _eq(dec.intent, want)
                return f"{dec.intent} ({dec.confidence:.2f}) in {report['routing'][-1]['ms']} ms"

            check(f"{msg!r} -> {want}", one)

        def chat_technical():
            body = client.post("/api/chat", json={"message": "my motor is vibrating"}).json()
            report["chat_technical"] = _brief(body)
            _true(body["kind"] in ("diagnosis", "clarify"), f"kind={body['kind']}")
            return f"kind={body['kind']}: {body['text'][:70]!r}"

        check("/api/chat 'my motor is vibrating' -> technical workflow", chat_technical)

        # ---------------------------------------------------------- 7
        print(f"\n{BOLD}7. No Ollama dependency{RESET}")

        def no_ollama():
            tried = [a["provider"] for a in role.get("candidates_tried") or []]
            _eq(tried, ["geniex-qwen3-vl"])
            _true(role["runtime"].startswith("geniex"), f"runtime={role['runtime']}")
            _true("ollama" not in sys.modules, "an 'ollama' module is imported")
            _true(type(reasoner).__name__ == "GenieXQwen3VLProvider", type(reasoner).__name__)
            listening = _port_open(11434)
            report["ollama_port_open"] = listening
            notes = []
            if settings.local_llm_url:
                notes.append(f"VF_LOCAL_LLM_URL={settings.local_llm_url} is set in .env but "
                             "not used — you can delete that line")
            if listening:
                notes.append("something listens on :11434 but Orion does not use it")
            return "only geniex-qwen3-vl was tried, in-process" + ("; " + "; ".join(notes)
                                                                 if notes else "")

        check("reasoning never touches Ollama or any local HTTP model", no_ollama)

        report["final_status"] = client.get("/api/models/status").json()["roles"]["reasoning"]

    return finish(tmp)


def finish(tmp: Path) -> int:
    passed = sum(ok for _, ok, _ in results)
    report["results"] = [{"check": n, "ok": ok, "detail": d} for n, ok, d in results]
    report["passed"], report["total"] = passed, len(results)
    out = Path(__file__).resolve().parent / "geniex_smoke_report.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    colour = GREEN if passed == len(results) and results else RED
    print(f"\n{colour}{BOLD}{passed}/{len(results)} checks passed{RESET}")
    print(f"{DIM}evidence written to {out}{RESET}\n")
    return 0 if results and passed == len(results) else 1


# ------------------------------------------------------------------ helpers
def _eq(got, want) -> None:
    assert got == want, f"expected {want!r}, got {got!r}"


def _true(cond, msg) -> None:
    assert cond, msg


def _brief(body: Dict[str, Any]) -> Dict[str, Any]:
    return {k: body.get(k) for k in ("kind", "intent", "route", "engine_available", "text",
                                     "duration_ms", "model")}


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    sys.exit(main())
