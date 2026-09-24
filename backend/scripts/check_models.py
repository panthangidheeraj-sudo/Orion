#!/usr/bin/env python3
"""Print exactly what this machine can and cannot do, and why.

    python scripts/check_models.py

Run it before a demo. It loads every adapter, reports the accelerator each one
actually received from the runtime, and prints the §25 reason for anything
unavailable. Nothing here guesses: if it says NPU, the runtime said NPU.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.memory.sqlite import init_db  # noqa: E402
from app.models.registry import registry  # noqa: E402
from app.models.runtime import asset_inventory, runtime_info  # noqa: E402

GREEN, YELLOW, RED, DIM, RESET = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"


def colour(status: str, synthetic: bool) -> str:
    if status != "ready":
        return RED
    return YELLOW if synthetic else GREEN


def main() -> int:
    settings.ensure_dirs()
    init_db()

    rt = runtime_info()
    print(f"\n{'=' * 78}\nVisionField Copilot — model status\n{'=' * 78}\n")
    print(f"Host          {rt.system} {rt.machine}, Python {rt.python}")
    print(f"onnxruntime   {rt.onnxruntime_version or 'not installed'}")
    print(f"providers     {', '.join(rt.available_providers) or 'none'}")
    print(f"QNN (NPU)     {GREEN + 'available' + RESET if rt.qnn_available else RED + 'not available' + RESET}")
    if rt.note:
        print(f"{DIM}              {rt.note}{RESET}")

    print(f"\n{'-' * 78}\nRoles\n{'-' * 78}")
    status = registry.status()
    for role, info in status["roles"].items():
        c = colour(info["status"], info["synthetic"])
        tag = " (stand-in)" if info["synthetic"] else ""
        print(f"\n{c}{role:<11}{RESET} {info['provider']:<22} {info['model_id']}{tag}")
        print(f"            status      {c}{info['status']}{RESET}")
        print(f"            accelerator {info['accelerator']}  npu={info['npu']}")
        if info["reason"]:
            print(f"{DIM}            reason      {info['reason']}{RESET}")
        for attempt in info["candidates_tried"]:
            if attempt["status"] != "ready":
                print(f"{DIM}            tried {attempt['provider']}: {attempt['reason']}{RESET}")

    inv = asset_inventory()
    print(f"\n{'-' * 78}\nAssets in {inv['models_dir']}\n{'-' * 78}")
    if not inv["entries"]:
        print(f"{DIM}  (empty — export models here with qai-hub-models, see MODEL_STATUS.md){RESET}")
    for e in inv["entries"]:
        print(f"  {e['model_id']:<28} {e['files']:>3} file(s)  {e['bytes'] / 1e6:>8.1f} MB")

    s = status["summary"]
    print(f"\n{'=' * 78}")
    print(f"ready        {', '.join(s['ready']) or 'none'}")
    print(f"unavailable  {', '.join(s['unavailable']) or 'none'}")
    print(f"stand-ins    {YELLOW}{', '.join(s['synthetic']) or 'none'}{RESET}")
    print(f"NPU claim    {GREEN + 'yes: ' + ', '.join(s['npu_accelerated']) + RESET if s['npu_claim'] else RED + 'no — nothing is running on the NPU' + RESET}")
    print(f"{'=' * 78}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
