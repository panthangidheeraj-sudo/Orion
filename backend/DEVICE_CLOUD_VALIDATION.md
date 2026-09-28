# Validating Qwen3-VL-4B-Instruct without a Snapdragon machine

This is for validating the real model and the real QAIRT/NPU runtime using
**Qualcomm AI Hub Workbench's hosted Device Cloud** — real, physical
Snapdragon X Elite / X2 Elite devices in Qualcomm's own fleet, reachable from
any machine (this Intel laptop included). It does not need a Snapdragon
device on hand, and it does **not** change Orion's own on-device GenieX
provider (`app/models/geniex.py`) or how Orion runs in production — that
stays exactly as documented in [SNAPDRAGON_SETUP.md](SNAPDRAGON_SETUP.md), for
when a Snapdragon Windows machine is available.

Two scripts, two different questions:

| Script | Runs where | Proves | Never claims |
|---|---|---|---|
| `scripts/aihub_devicecloud_validate.py` | A real, hosted Snapdragon device (Qualcomm's Device Cloud) | The real model, compiled for QAIRT, loads and runs correctly on real Snapdragon silicon — with the device name, chipset, QNN/QAIRT version and profiling numbers read back from the finished job | A live, multi-turn chat — Device Cloud jobs run one fixed compile→profile→inference pass, not a chat loop |
| `scripts/aihub_router_text_image_check.py` | This machine's own CPU/GPU | Real generated text and image answers from the real Qwen3-VL-4B-Instruct weights (a local quantization-accuracy simulation), and that Orion's own router prompt gets valid routing decisions from those weights | The NPU — every result is labelled `accelerator: cpu (simulated)`, `npu: false` |

Only the first script's evidence may ever be read as an NPU claim. The
second is real generation from the real model, useful for validating Orion's
prompts and router today, on hardware you already have.

## Why not run everything through the CLI's `chat`/`demo --device` flow?

Qualcomm's own tooling (`qai_hub_models`, current as of this writing) only
drives a full autoregressive chat loop against a **physically present**
device — either locally over the GenieX/ONNX+QNN path, or a Genie bundle
pushed to a device attached over USB/ADB. There is no documented hosted
chat-completion endpoint yet. Device Cloud jobs (`submit_compile_job` /
`submit_profile_job` / `submit_inference_job`) run a single, fixed-shape
graph invocation on the hosted hardware and return — which is exactly what
this doc uses them for.

---

## 1. Set up Qualcomm AI Hub Workbench (for the Device Cloud script)

1. Sign up at <https://myaccount.qualcomm.com/signup> if you don't already
   have a Qualcomm ID, then sign in at
   <https://workbench.aihub.qualcomm.com/>.
2. `Account -> Settings -> API Token`, copy the token.
3. On this machine:

   ```bash
   pip install qai-hub qai-hub-models
   qai-hub configure --api_token <your token>
   ```

4. Confirm your account can see the target devices:

   ```bash
   python scripts/aihub_devicecloud_validate.py --list-devices
   ```

   You should see `Snapdragon X Elite CRD` and/or `Snapdragon X2 Elite CRD`
   (Qualcomm's hosted reference devices for these chipsets). If neither
   appears, your account does not yet have access to that device class —
   check <https://workbench.aihub.qualcomm.com/devices> or ask on
   [AI Hub's Slack](https://aihub.qualcomm.com/community/slack).

## 2. Run the Device Cloud validation

```bash
python scripts/aihub_devicecloud_validate.py
# or: python scripts/aihub_devicecloud_validate.py --device "Snapdragon X2 Elite CRD"
```

This compiles Qwen3-VL-4B-Instruct (the same `w4a16` precision GenieX/QAIRT
uses on-device) for the chosen device, then submits a profile job and an
inference job against it — genuinely queued and run on Qualcomm's hosted
hardware, which can take several minutes. It writes
`scripts/aihub_devicecloud_report.json` with, straight from the finished job
objects:

- the resolved device's name, OS and chipset attributes;
- the compile/profile/inference job URLs (open them at
  `https://workbench.aihub.qualcomm.com/jobs/<id>` to see Qualcomm's own
  dashboard for that run);
- whether each job succeeded;
- the QNN/QAIRT SDK version the device actually reported (`tool_versions`);
- profile timing and memory figures for that device.

Do not hand-edit this file. If the run fails, the reason is in the job's own
`failure_reason` (visible at its URL) — most commonly account/device access,
or a quota/queue timeout on a busy device.

## 3. Run the text / image / router check

```bash
pip install qai-hub-models
huggingface-cli login   # needs access to Qwen/Qwen3-VL-4B-Instruct on Hugging Face
python scripts/aihub_router_text_image_check.py
```

First run downloads the model (several GB) and runs the real weights on this
machine's CPU (or GPU if `torch.cuda.is_available()`). It writes
`scripts/aihub_router_text_image_report.json` with the actual generated
replies for a text prompt, an image + text prompt, and Orion's own router
prompt against five clear-cut router-QA messages — every one labelled
`accelerator: cpu (simulated)`, `npu: false`.

`--skip-image` skips the (slower) vision-encoder pass if you only need text
and the router checked quickly.

## 4. Recording the result

Only after both scripts have actually been run and their JSON reports exist,
copy the real numbers from them into the "Device Cloud remote validation"
section of [MODEL_STATUS.md](../MODEL_STATUS.md) — never write that section
from what this doc expects to happen, only from what the reports say did
happen.

## What this does and does not settle

- **Settles**: the real Qwen3-VL-4B-Instruct, compiled for QAIRT, is accepted
  and runs correctly (profiled and numerically verified) on real Snapdragon X
  Elite / X2 Elite silicon that Qualcomm hosts — without owning that
  hardware. And: Orion's router prompt gets valid, correctly-routed JSON back
  from the real model weights.
- **Does not settle**: that Orion's `GenieXQwen3VLProvider`
  (`app/models/geniex.py`) itself runs correctly end to end on an NPU — that
  still needs the actual Snapdragon Windows machine and
  `scripts/geniex_smoke.py`, per [SNAPDRAGON_SETUP.md](SNAPDRAGON_SETUP.md).
  This Device Cloud path validates the model and the runtime; it is not a
  substitute for that smoke test once real hardware is available.
