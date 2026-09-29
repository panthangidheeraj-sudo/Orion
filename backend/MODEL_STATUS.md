# MODEL_STATUS.md

Required by §4 of the backend specification:

> If a chosen model fails current Compute validation:
> 1. keep its adapter interface;
> 2. find the closest currently supported Qualcomm model;
> 3. record the replacement in `MODEL_STATUS.md`;
> 4. never fake Snapdragon/NPU support.

This file records what is actually running. It is meant to be edited on the
target machine as exports are validated, not left as written here.

---

## Where this build stands

**No Qualcomm AI Hub model has been compiled, profiled or exported for this
project yet.** The adapters are written and the runtime path to the NPU is
implemented, but nothing has been validated on Snapdragon hardware from this
environment, because this environment has no Snapdragon device attached.

Rather than shipping code that asserts NPU acceleration, every adapter reports
the accelerator the runtime actually gave it, and `GET /api/models/status`
prints the whole picture — including which roles are running deterministic
stand-ins. If a demo claims the NPU, that endpoint should be able to back it.

Run this to see the live state:

```bash
curl http://127.0.0.1:8756/api/models/status
```

---

## Reasoning on Snapdragon: Qwen3-VL-4B-Instruct via GenieX + QAIRT

| | |
|---|---|
| Model | Qwen3-VL-4B-Instruct (`ai-hub-models/Qwen3-VL-4B-Instruct`, Apache-2.0) |
| Runtime | Qualcomm GenieX, QAIRT plugin (Hexagon NPU), in-process Python API |
| Supported chipsets (AI Hub) | Snapdragon X Elite, X Plus 8-Core, X2 Elite |
| Host | Windows on Snapdragon, ARM64 Python 3.10+ |
| Orion provider | `VF_REASONING_PROVIDER=geniex-qwen3-vl` (`app/models/geniex.py`) |
| Used for | routing, conversation, technical reasoning, image + text |
| Setup | [docs/SNAPDRAGON_SETUP.md](docs/SNAPDRAGON_SETUP.md) |

**Asset on disk (not a validation).** The Qualcomm AI Hub Models export
`qwen3_vl_4b_instruct-geniex_qairt-w4a16-qualcomm_snapdragon_x_elite` has been
downloaded: runtime `geniex_qairt`, precision `w4a16`, QAIRT 2.45.0, built for
Snapdragon X Elite (reference device Snapdragon X Elite CRD, `soc_model` 60,
HTP v73) — per its own `metadata.json`. Orion is wired to it with
`VF_GENIEX_MODEL_PATH`. The development PC runs x64 Python 3.12.10 (its packages are
`win_amd64` builds) on an Intel machine, where GenieX has no native runtime, so the provider there correctly reports:
*asset installed, but local GenieX/QAIRT NPU execution requires a Windows
ARM64 Snapdragon machine.* Nothing below may be filled in from that machine.

**Validation status: NOT YET VALIDATED ON HARDWARE.** The provider, the
smoke test and the real-model tests are written and their plumbing is tested
against a stand-in of the GenieX API. Nothing here has run on a Snapdragon NPU
yet. This section is to be filled in from `scripts/geniex_smoke_report.json`
only after `python scripts\geniex_smoke.py` passes on the target machine.

The provider becomes `ready` only after the model bundle loads and a probe
generation produces tokens. `npu: true` requires the runtime to report the
`qairt` plugin with device `NPU` for the model handle and for the probe, an NPU
compute unit in the QAIRT device list, and QAIRT registered with libgeniex.

### Validated result

_Pending — fill from the smoke report:_

| Field | Value |
|---|---|
| Date | |
| Device / chipset | |
| Windows build | |
| Python | |
| geniex / QAIRT plugin version | |
| Model load time | |
| Accelerator reported (`/api/models/status`) | |
| Probe: prompt / generated tokens, decode tok/s | |
| Text conversation | |
| Image + text (red / blue) | |
| Router checks | |
| Smoke test | _/19 checks passed |

---

## Device Cloud remote validation (no Snapdragon hardware needed)

A separate, hosted-only path validates the real model and the real
QAIRT/NPU runtime on a physical, hosted Snapdragon device — without owning
one — using Qualcomm AI Hub Workbench's Device Cloud. This does **not**
change or substitute for `GenieXQwen3VLProvider` above; it validates the
model and runtime on real Snapdragon silicon, at the granularity Qualcomm's
current tooling actually supports (a compile → profile → inference job, not a
live chat loop). Full steps: [docs/DEVICE_CLOUD_VALIDATION.md](docs/DEVICE_CLOUD_VALIDATION.md).

**Status: NOT YET RUN.** This section is to be filled in from
`scripts/aihub_devicecloud_report.json` and
`scripts/aihub_router_text_image_report.json` only after both scripts have
actually been run.

### Hosted Device Cloud job (`scripts/aihub_devicecloud_validate.py`)

_Pending — fill from `aihub_devicecloud_report.json`:_

| Field | Value |
|---|---|
| Date | |
| Requested device | |
| Resolved device (name / OS / chipset attributes) | |
| Compile job | |
| Profile job — status, latency, peak memory | |
| Inference job — status, accuracy vs. reference | |
| Tool versions (QNN/QAIRT SDK) on the device | |
| Job URLs | |

This is the only evidence in this document that may back an NPU claim for
the Device Cloud path — it comes from a real, physical Snapdragon device.

### Text / image / router check (`scripts/aihub_router_text_image_check.py`)

_Pending — fill from `aihub_router_text_image_report.json`. Every row here
ran on this machine's own CPU/GPU (a local quantization-accuracy simulation
of the real weights) — **never** report `npu: true` for this section:_

| Field | Value |
|---|---|
| Date | |
| Host (CPU/GPU) | |
| Text conversation reply | |
| Image + text reply | |
| Router: hellooo -> | |
| Router: my motor is vibrating -> | |
| Router: there are sparks coming from the panel -> | |
| Checks passed | _/N |

---

## Role status

| Role | Intended model (§3) | Adapter | Status in this build | Notes |
|---|---|---|---|---|
| Reasoning VLM | **Qwen3-VL-4B-Instruct** (GenieX + QAIRT) | `GenieXQwen3VLProvider` (`geniex-qwen3-vl`); alternates `QwenVLGenAIProvider`, `LocalOpenAICompatProvider` | **Implemented — pending validation on the Snapdragon machine** | See "Reasoning on Snapdragon" below. With no model loaded there is no stand-in: reasoning is `unavailable` and Orion says it cannot interpret requests. |
| Detection | YOLO11-Detection / YOLO-WORLD | `YoloOnnxDetector`, `YoloWorldDetector` | **Not exported** | Pre/post-processing is complete and real; drop an ONNX export into `data/models/yolov11_det/` and it runs. See the Compute caveat below. |
| Classification | EfficientNet-B4 | `EfficientNetOnnxClassifier` | **Not exported** | §7's optional stage. Pre/post-processing complete (ImageNet normalisation, softmax, top-k, crop-to-bbox). Absent, the pipeline skips the stage rather than guessing a class. |
| Segmentation | SAM2 / MobileSAM / YOLO11-Seg | `OnnxSegmenter` | **Not exported** | Session and prototype read-out implemented; mask assembly is finished against the exported head layout. |
| Tracking | Track-Anything / EdgeTAM | `EdgeTAMTracker`, `CentroidTracker` | **Classical fallback active** | `CentroidTracker` is a real IoU/centroid associator on CPU, labelled `cpu-classical`. Not a learned tracker and does not claim to be. |
| OCR | EasyOCR / TrOCR | `EasyOCRProvider`, `TrOCROnnxProvider` | **Not installed** | `pip install easyocr` gives a working CPU path today; an exported asset replaces it later. |
| Embeddings | Nomic-Embed-Text / MiniLM-v2 | `NomicOnnxEmbedder` | **Not exported** | Falls back to `LexicalHashEmbedder`, reported as `synthetic: true`. Local RAG works; recall is lexical, not semantic. |
| Speech-to-text | Whisper-Base | `WhisperOnnxProvider`, `FasterWhisperProvider` | **Not installed** | API returns a degraded response so the front-end keeps its own recogniser (§25). |
| Text-to-speech | PiperTTS-EN | `PiperTTSProvider` | **Not installed** | Needs the `piper` binary plus a voice in `data/models/pipertts_en/`. |

### Selecting an alternate

§3 says "Do not hard-wire one model." Every candidate it names is reachable by
configuration, not by editing code:

| Role | Selectable providers |
|---|---|
| reasoning | `geniex-qwen3-vl`, `onnxruntime-genai`, `local-openai-compat` |
| detector | `yolo-onnx`, `yolo-world-onnx` |
| classifier | `efficientnet-onnx` |
| segmenter | `onnx-seg`, `sam2-onnx`, `mobilesam-onnx` |
| tracker | `edgetam-onnx`, `track-anything-onnx`, `cpu-classical` |
| ocr | `easyocr`, `trocr-onnx` |
| embedding | `nomic-onnx`, `minilm-onnx`, `lexical-hash` |
| stt | `whisper-onnx`, `faster-whisper` |
| tts | `piper` |

Set `VF_<ROLE>_PROVIDER` to pin one, or leave it `auto` to take the first that
actually loads. A pinned provider is the only one tried — if it cannot load,
the role is unavailable; another model is never substituted. `/api/models/status` lists every candidate that was tried and
why each one was skipped.

---

## The Compute-support caveat (§4)

§4 warns that an AI Hub model page can show X-series device metadata while
also reporting a current Compute-support limitation, and names
**YOLOv11-Detection**, **YOLO-WORLD** and **YOLOv11-Segmentation** as current
examples. Those three are therefore treated as **experimental** here until a
Workbench export and profile succeed on the target device.

Before integrating any model, follow §26 and read the current model card and
the repository's own files — `README.md`, `demo.py`, `export.py`, the model
implementation, its dependencies, runtime support, precision options and
device support — rather than assuming any command in this file still works:

```
https://github.com/qualcomm/ai-hub-models
src/qai_hub_models/models/<model>/
```

---

## Validating a model on the target machine

The commands below are the ones §5 documents. Check them against the current
repository before running; do not invent integration commands.

```bash
pip install qai_hub_models
qai-hub configure --api_token <token from your environment>

qai-hub-models devices
qai-hub-models chipsets
qai-hub-models info  <MODEL>
qai-hub-models perf  <MODEL>
qai-hub-models numerics <MODEL>

qai-hub-models install <MODEL_ID>
qai-hub-models fetch <MODEL> --runtime <runtime> --precision <precision>
# For licence-restricted assets, use the documented export workflow instead.
```

**Windows note (§5):** Qualcomm's current README says Snapdragon X Elite /
X2 Elite Windows users should use AMD64/x86-64 Python for `qai_hub_models`.
Verify that this is still the current requirement before setting up the
machine.

Place the resulting asset here:

```
backend/data/models/<model_id>/model.onnx
backend/data/models/<model_id>/labels.json        # detectors, optional
backend/data/models/<model_id>/tokenizer.json     # embedders
backend/data/models/qwen3_vl_2b_instruct/         # a genai export directory
```

Then, without restarting:

```bash
curl -X POST http://127.0.0.1:8756/api/models/reload
curl http://127.0.0.1:8756/api/models/status
```

Confirm in the response that `accelerator` is `npu` and `npu` is `true` for
that role. If it says `cpu`, the QNN execution provider was not applied — the
service will have logged the reason — and the honest claim is CPU.

---

## Record replacements here

When a model fails Compute validation and is swapped, append a row:

| Date | Intended model | Why it failed | Replacement | Measured latency | Accelerator |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

---

## What "synthetic" means

One role ships a deterministic stand-in:

- **`lexical_hash_v1`** — stop-filtered hashed word and character-trigram bag,
  L2-normalised. A real lexical embedding, genuinely useful for part numbers
  and error codes, but not semantic.

There is deliberately **no reasoning stand-in**. The rule-based
`heuristic_offline_v1` reasoner and the regex intent classifier were removed:
routing and diagnosis come from a real language model, and without one Orion
says it can't interpret requests rather than imitating understanding.

It is flagged `synthetic: true` in `/api/models/status`, logged at startup,
and surfaced in every chat response under `model`. Replacing them with real
exports is Phase 9 of §22.
