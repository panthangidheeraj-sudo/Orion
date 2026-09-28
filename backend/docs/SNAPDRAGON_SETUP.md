# Running Orion on Qwen3-VL-4B-Instruct (GenieX + QAIRT, Snapdragon NPU)

This is the setup for the real reasoning model: **Qwen3-VL-4B-Instruct**
running on the **Hexagon NPU** through Qualcomm **GenieX** with the **QAIRT**
runtime, on Windows on Snapdragon.

Supported chipsets for this model (Qualcomm AI Hub): **Snapdragon X Elite,
Snapdragon X Plus 8-Core, Snapdragon X2 Elite**. AI Hub models run on the NPU
only.

Orion loads the model **in-process** through the GenieX Python API
(`app/models/geniex.py`). No model server, no Ollama, nothing listening on a
port. The same model does all three jobs: routing each message
(conversation / technical / ambiguous), ordinary conversation, and the
technical reasoning loop with photos.

---

## 1. ARM64 Python (required)

GenieX's Python package supports **Windows arm64** only; x64 Python under
emulation will not work.

1. Install **Python 3.10 or newer, "Windows installer (ARM64)"** from python.org.
2. Check it in a new terminal:

   ```bat
   python -c "import platform; print(platform.machine(), platform.python_version())"
   ```

   It must print `ARM64 3.1x.x`. If it prints `AMD64`, you are on an x64
   Python — use the full path to the ARM64 one (e.g. `py -3.12-arm64`) or fix
   PATH.

> Note: Qualcomm's *qai_hub_models* tooling (used to compile/export models in
> the cloud) has historically asked for x64 Python. That is a different tool.
> For **running** Qwen3-VL-4B through GenieX you need ARM64 Python.

## 2. Backend environment with GenieX

From `backend\`:

```bat
py -3.12-arm64 -m venv .venv-arm64
.venv-arm64\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-snapdragon.txt
```

`requirements-snapdragon.txt` installs `geniex-qairt` — the GenieX Python
bindings with the QAIRT (NPU) plugin only. Its installer downloads the native
SDK slice (~210 MB) on first install.

Do not install `llama-cpp-python` into this environment (GenieX warns about
DLL conflicts).

Check the runtime sees the NPU:

```bat
geniex-py version
geniex-py devices
```

`devices` should list the `qairt` plugin with an NPU device.

## 3. Download the model

The command Qualcomm documents for this model uses the GenieX CLI:

```bat
geniex pull ai-hub-models/Qwen3-VL-4B-Instruct
```

(The CLI is a separate installer from the GenieX GitHub releases. It is not
code-signed; Windows SmartScreen may ask you to confirm "Run anyway".)

Then confirm the **Python binding** sees the same cached bundle:

```bat
geniex-py ls
```

`ai-hub-models/Qwen3-VL-4B-Instruct` must be listed. If it is not (e.g. the
CLI and the Python package use different cache folders on your machine), either
pull it with the Python CLI instead —

```bat
geniex-py pull ai-hub-models/Qwen3-VL-4B-Instruct
```

— or point Orion straight at the downloaded bundle folder (the one containing
`metadata.json`):

```bat
set VF_GENIEX_MODEL_PATH=C:\path\to\Qwen3-VL-4B-Instruct
```

Optional sanity check outside Orion:

```bat
geniex infer ai-hub-models/Qwen3-VL-4B-Instruct
```

Orion never downloads the model by itself: a multi-GB download must not start
from inside a chat request. If the bundle is missing, the model status says
exactly which command to run.

## 4. Select the provider

In `backend\.env` (or the environment):

```ini
VF_REASONING_PROVIDER=geniex-qwen3-vl
```

Optional settings (defaults shown):

```ini
VF_GENIEX_MODEL=ai-hub-models/Qwen3-VL-4B-Instruct
# Load a bundle folder directly instead of the GenieX cache
VF_GENIEX_MODEL_PATH=
VF_GENIEX_PRECISION=
# qairt = the NPU plugin
VF_GENIEX_DEVICE_MAP=qairt
# 0 = the bundle's context length
VF_GENIEX_N_CTX=0
VF_GENIEX_MAX_NEW_TOKENS=768
VF_GENIEX_MAX_IMAGES=2
# READY only after a real test generation
VF_GENIEX_PROBE=true
# Use a separate QAIRT SDK instead of the one bundled with GenieX
VF_GENIEX_QAIRT_RUNTIME_PATH=
```

If your `.env` was copied from an older `.env.example`, delete any
`VF_LOCAL_LLM_URL=http://127.0.0.1:11434/v1` line — Orion no longer points at
Ollama by default, and with `geniex-qwen3-vl` selected it is never used.

With the provider named explicitly, **only** GenieX is tried. If it cannot
load, reasoning is reported unavailable and Orion replies "I'm here. Tell me a
little more about what you need." — it does not fall back to another model.

## 5. Prove it: the smoke test

```bat
python scripts\geniex_smoke.py
```

It boots Orion in-process against a throwaway data folder, loads the model
once, and checks:

1. Orion reaches the real model (READY, not a stand-in)
2. It runs through GenieX/QAIRT (the model handle and every generation say so)
3. The runtime reports the NPU (backend `qairt`, device `NPU`, NPU compute unit listed, probe ran)
4. Text conversation works (direct and through `/api/chat`)
5. Image + text works (a red and a blue picture; the answers must follow the pixels)
6. Semantic routing works (the model's own decisions on real messages)
7. No Ollama dependency (only `geniex-qwen3-vl` tried, in-process)

It writes the runtime evidence (versions, chipset, compute units, token
counts and speeds, every answer) to `scripts\geniex_smoke_report.json`.

The real-model pytest suite (router QA + multimodal) runs the same way:

```bat
set ORION_GENIEX_TEST=1
python -m pytest tests\test_geniex_hardware.py -v
```

## 6. Run Orion

```bat
python -m app.main
```

Then:

```bat
curl http://127.0.0.1:8756/api/models/status
```

`roles.reasoning` should show:

```json
"provider": "GenieX/QAIRT",
"model_id": "Qwen3-VL-4B-Instruct",
"status": "ready",
"accelerator": "npu",
"npu": true
```

and `detail.npu_verdict` lists the checks that passed. The front-end's status
chip reads "Local AI Ready" with the model and NPU only in that state.

## What "npu: true" means

It is set only when **all** of these come from the runtime:

- the model handle was created on the `qairt` plugin with device `NPU`;
- `qairt` is in the runtime list libgeniex registered;
- that runtime lists an NPU compute unit;
- a probe generation produced tokens, and its profile is stamped `qairt` / `NPU`.

Anything less is reported as what it is (`cpu`, `unknown`, or unavailable
with the reason).

## Troubleshooting

| Status reason | Fix |
|---|---|
| `geniex is not importable` | You are on x64 Python or GenieX is not installed in this venv (steps 1–2). |
| `QAIRT runtime is not registered` | Reinstall `geniex-qairt`; check `geniex-py devices`. |
| `not in the GenieX model cache` | Step 3, or set `VF_GENIEX_MODEL_PATH`. |
| `could not load … with device_map='qairt'` | Unsupported chipset, or an outdated NPU driver. Update Windows / the Qualcomm NPU driver; check `geniex config get chipset`. Run with `set GENIEX_LOG=debug`. |
| `probe produced no tokens` | The model loaded but did not generate; check the GenieX log. |

## The hosted (Render) deployment

The cloud deployment does not have a Snapdragon NPU and does not install
GenieX. There, reasoning reports `unavailable`, which is correct. Nothing on
Render depends on this machine.
