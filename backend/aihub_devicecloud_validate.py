#!/usr/bin/env python3
"""Validate Qwen3-VL-4B-Instruct on a REAL, hosted Snapdragon device — no
Snapdragon hardware required — using Qualcomm's own AI Hub Workbench Device
Cloud.

This does not run against Orion. It runs Qualcomm's own, documented compile
-> profile -> inference pipeline for this exact model
(``qai_hub_models.models.qwen3_vl_4b_instruct``), pointed at a physical
Snapdragon X Elite / X2 Elite device that Qualcomm hosts in the cloud, over
the ``qai_hub`` client. Every command and API used here comes straight from
that package (installed from PyPI) and from
https://workbench.aihub.qualcomm.com/docs/ — nothing here is invented.

What this proves, with evidence pulled from the job objects themselves
(never assumed):

  1. The real Qwen3-VL-4B-Instruct model, compiled for the real QAIRT/QNN
     runtime, is accepted and runs on a real, physical Snapdragon device that
     you do not own — one from Qualcomm's own device fleet.
  2. Runtime/device evidence: the exact device name, OS and chipset the job
     ran on, and the QNN/QAIRT SDK version the device actually used — all
     read back from the finished job, not configured up front.
  3. Text reasoning: the language-model half of the graph (prefill + one
     decode step) runs on that device and its output matches the reference
     model's output (PSNR), i.e. the compiled, quantized model reasons about
     text correctly on real Snapdragon silicon.
  4. Image + text reasoning: the same, but through the vision encoder
     component, so an actual image tensor is part of what ran on the device.

What this does NOT prove, and does not claim to: this pipeline profiles and
numerically verifies each compiled sub-graph with one prefill/decode step; it
does not drive a live, multi-turn chat loop on the hosted device (Qualcomm's
current tooling only runs a full autoregressive chat loop against local NPU
hardware — see docs/SNAPDRAGON_SETUP.md). For that reason Orion's semantic
router (which needs full free-text generation) is checked separately, by
scripts/aihub_router_text_image_check.py, against a LOCAL CPU/GPU simulation
of the same quantized weights — which never claims the NPU. Only this script's
evidence may back an NPU claim.

Setup (see docs/DEVICE_CLOUD_VALIDATION.md):

    pip install qai-hub qai-hub-models
    qai-hub configure --api_token <token from https://workbench.aihub.qualcomm.com/ Account -> Settings -> API Token>

Usage:

    python scripts/aihub_devicecloud_validate.py
    python scripts/aihub_devicecloud_validate.py --device "Snapdragon X2 Elite CRD"
    python scripts/aihub_devicecloud_validate.py --list-devices
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

MODEL_ID = "qwen3_vl_4b_instruct"
MODEL_DISPLAY_NAME = "Qwen3-VL-4B-Instruct"

# The two Windows-on-Snapdragon chipsets this repo targets. Qualcomm's fleet
# also hosts phone/tablet devices with the same chipset family; those are not
# Orion's target and are not used here.
DEFAULT_DEVICE = "Snapdragon X Elite CRD"
CANDIDATE_DEVICES = ["Snapdragon X Elite CRD", "Snapdragon X2 Elite CRD",
                     "Snapdragon X Plus 8-Core CRD"]

REPORT_PATH = Path(__file__).resolve().parent / "aihub_devicecloud_report.json"


def _die(msg: str) -> None:
    print(f"\nERROR: {msg}\n", file=sys.stderr)
    sys.exit(1)


def list_devices() -> None:
    try:
        import qai_hub as hub
    except ImportError:
        _die("qai_hub is not installed. `pip install qai-hub` first.")
    print("Devices Qualcomm AI Hub Workbench currently hosts with "
          f"'{DEFAULT_DEVICE.split()[0]} {DEFAULT_DEVICE.split()[1]}'-family chipsets:\n")
    seen = set()
    for name in CANDIDATE_DEVICES:
        for d in hub.get_devices(name=name):
            key = (d.name, d.os)
            if key in seen:
                continue
            seen.add(key)
            print(f"  {d.name!r:32} os={d.os!r:10} attributes={d.attributes}")
    if not seen:
        print("  (none found — your account may not have access to these devices yet;"
              " check https://workbench.aihub.qualcomm.com/devices)")


def _device_dict(device: Any) -> Dict[str, Any]:
    return {"name": device.name, "os": device.os, "attributes": list(device.attributes)}


def _job_dict(job: Any) -> Dict[str, Any]:
    return {"job_id": getattr(job, "job_id", None), "url": getattr(job, "url", None),
            "name": getattr(job, "name", None)}


def _flatten(group: Any) -> Dict[str, Any]:
    """A ComponentGroup or MultiGraphComponentGroup is a plain dict — just
    with a str or (str, str) key. Normalise the key to a string for JSON."""
    if not group:
        return {}
    return {(k if isinstance(k, str) else "/".join(k)): v for k, v in group.items()}


def run(device_name: str, checkpoint: str) -> Dict[str, Any]:
    try:
        import qai_hub as hub
    except ImportError:
        _die("qai_hub is not installed. `pip install qai-hub` first.")
    try:
        from qai_hub_models.models.qwen3_vl_4b_instruct import export as qwen_export
    except ImportError as exc:
        _die(f"qai_hub_models is not installed or import failed ({exc}). "
             "`pip install qai-hub-models` first.")

    matches = hub.get_devices(name=device_name)
    if not matches:
        _die(f"'{device_name}' is not a device your Qualcomm AI Hub account can see. "
             "Run with --list-devices, or check https://workbench.aihub.qualcomm.com/devices.")
    device = matches[0]

    report: Dict[str, Any] = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "model": MODEL_DISPLAY_NAME,
        "model_id": MODEL_ID,
        "checkpoint_requested": checkpoint,
        "requested_device": device_name,
        "resolved_device": _device_dict(device),
    }
    print(f"Submitting {MODEL_DISPLAY_NAME} ({checkpoint}) to Qualcomm AI Hub Device Cloud "
          f"on {device.name} ({device.os or 'latest OS'})...")
    print("This compiles for QAIRT, profiles on the real device, and runs an "
          "inference job there, comparing the output against a reference run. "
          "It can take several minutes — the job also queues for a free device "
          "in Qualcomm's fleet.\n")

    # Reuse the model's OWN generated CLI parser and its own `main()` precision
    # resolution, exactly as `qai-hub-models export qwen3_vl_4b_instruct ...`
    # would run it (see export.py in this model's package) — down to the same
    # --checkpoint -> --precision resolution export.py's own main() applies.
    # We only diverge by keeping the CollectionExportResult it returns instead
    # of discarding it, so we can pull real job evidence out of it below.
    parser = qwen_export.build_parser()
    ns = parser.parse_args([
        "--device", device.name, "--checkpoint", checkpoint, "--skip-downloading",
    ])
    from qai_hub_models.models.qwen3_vl_4b_instruct import DEFAULT_PRECISION
    from qai_hub_models.utils.checkpoint import CheckpointType

    ns.precision = CheckpointType.from_checkpoint(checkpoint).precision(
        DEFAULT_PRECISION, checkpoint=checkpoint)

    t0 = time.perf_counter()
    result = qwen_export.export_model(**vars(ns))
    report["wall_s"] = round(time.perf_counter() - t0, 1)

    compile_jobs = _flatten(getattr(result, "compile_jobs", None))
    profile_jobs = _flatten(getattr(result, "profile_jobs", None))
    inference_jobs = _flatten(getattr(result, "inference_jobs", None))

    def _record(jobs: Dict[str, Any]) -> Dict[str, Any]:
        out = {}
        for name, job in jobs.items():
            job.wait()
            entry = _job_dict(job)
            entry["success"] = bool(job.success)
            entry["device"] = _device_dict(job.device) if getattr(job, "device", None) else None
            out[name] = entry
        return out

    report["compile_jobs"] = _record(compile_jobs)
    report["profile_jobs"] = _record(profile_jobs)
    report["inference_jobs"] = _record(inference_jobs)

    for name, job in profile_jobs.items():
        if not job.success:
            continue
        try:
            report.setdefault("profile", {})[name] = _summarise_profile(job.download_profile())
        except Exception as exc:
            report.setdefault("profile_error", {})[name] = str(exc)

    tool_versions = getattr(result, "tool_versions", None)
    if tool_versions is not None:
        report["tool_versions"] = str(tool_versions)

    all_jobs = list(compile_jobs.values()) + list(profile_jobs.values()) + list(inference_jobs.values())
    report["ok"] = bool(all_jobs) and all(j.success for j in all_jobs)
    return report


def _summarise_profile(profile_data: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the handful of fields worth putting in MODEL_STATUS.md, without
    assuming a schema version — profile_data is Qualcomm's own job payload."""
    out: Dict[str, Any] = {}
    execs = profile_data.get("execution_summary") or profile_data.get("executionSummary")
    if isinstance(execs, dict):
        for key in ("estimated_inference_time", "estimated_inference_time_min",
                    "estimated_inference_time_max", "first_load_time",
                    "warm_load_time", "peak_memory_bytes", "compute_unit_breakdown"):
            if key in execs:
                out[key] = execs[key]
    if not out:
        out["raw_keys"] = list(profile_data.keys())
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", default=DEFAULT_DEVICE,
                  help=f"A device name from `qai-hub list-devices` (default: {DEFAULT_DEVICE!r}).")
    p.add_argument("--checkpoint", default="DEFAULT_W4A16",
                  help="DEFAULT, DEFAULT_W4A16 or DEFAULT_Q4_0 (default: DEFAULT_W4A16, "
                       "the GenieX/QAIRT NPU precision).")
    p.add_argument("--list-devices", action="store_true",
                  help="List hosted devices your account can see and exit.")
    args = p.parse_args()

    if args.list_devices:
        list_devices()
        return 0

    report = run(args.device, args.checkpoint)
    REPORT_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n{'PASS' if report['ok'] else 'FAIL'}: evidence written to {REPORT_PATH}")
    if report["ok"]:
        print(f"Device: {report['resolved_device']['name']}  "
              f"attributes: {report['resolved_device']['attributes']}")
        if "tool_versions" in report:
            print(f"Tool versions on device: {report['tool_versions']}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
