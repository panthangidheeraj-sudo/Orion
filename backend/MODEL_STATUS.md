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

## Role status

| Role | Intended model (§3) | Adapter | Status in this build | Notes |
|---|---|---|---|---|
| Reasoning VLM | Qwen3-VL-2B-Instruct | `QwenVLGenAIProvider` (onnxruntime-genai), `LocalOpenAICompatProvider` | **Not exported** | Falls back to `HeuristicReasoningProvider`, reported as `synthetic: true`, `npu: false`. |
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
| reasoning | `onnxruntime-genai`, `local-openai-compat`, `heuristic-offline` |
| detector | `yolo-onnx`, `yolo-world-onnx` |
| classifier | `efficientnet-onnx` |
| segmenter | `onnx-seg`, `sam2-onnx`, `mobilesam-onnx` |
| tracker | `edgetam-onnx`, `track-anything-onnx`, `cpu-classical` |
| ocr | `easyocr`, `trocr-onnx` |
| embedding | `nomic-onnx`, `minilm-onnx`, `lexical-hash` |
| stt | `whisper-onnx`, `faster-whisper` |
| tts | `piper` |

Set `VF_<ROLE>_PROVIDER` to pin one, or leave it `auto` to take the first that
actually loads. `/api/models/status` lists every candidate that was tried and
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

Two roles ship deterministic stand-ins so the full agent loop runs before any
export exists:

- **`heuristic_offline_v1`** — rule-based tool selection plus evidence-bound
  composition in the §18 technician structure. Not a language model. It
  cannot generalise, and it produces no tokens/sec or NPU figures.
- **`lexical_hash_v1`** — stop-filtered hashed word and character-trigram bag,
  L2-normalised. A real lexical embedding, genuinely useful for part numbers
  and error codes, but not semantic.

Both are flagged `synthetic: true` in `/api/models/status`, logged at startup,
and surfaced in every chat response under `model`. Replacing them with real
exports is Phase 9 of §22.
