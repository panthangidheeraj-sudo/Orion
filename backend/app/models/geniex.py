"""Qwen3-VL-4B-Instruct on the Snapdragon NPU, through Qualcomm GenieX + QAIRT.

This is the reasoning provider selected with
``VF_REASONING_PROVIDER=geniex-qwen3-vl``. It talks to GenieX through its
in-process Python API (``pip install geniex``, Windows ARM64 Python 3.10+):

    AutoModelForVision2Seq.from_pretrained("ai-hub-models/Qwen3-VL-4B-Instruct",
                                            device_map="qairt")

The Python API was chosen over ``geniex serve`` (the OpenAI-compatible local
server) for one reason: it is the only path where *this* process can see the
runtime's own execution evidence — the plugin and compute unit the handle was
created on, the runtimes libgeniex registered, and a per-generation profile
(prompt/decode token counts and speeds) stamped with that backend and device.
Over HTTP the server would be a black box and the honest NPU claim would be
"unknown".

What READY means here — nothing is inferred from configuration or from the
package being installed:

0. This is an ARM64 Python on a Snapdragon-class host. GenieX ships native
   runtimes only for Windows ARM64 and Linux aarch64 (its own install-time SDK
   fetcher refuses anything else), so an AMD64/x86-64 host is reported as
   unavailable with that reason — even when the model bundle is on disk.
1. ``geniex`` imports and ``geniex.init()`` succeeds.
2. The model bundle is present in the GenieX cache (``geniex pull ...``) or at
   ``VF_GENIEX_MODEL_PATH`` — a Qualcomm AI Hub Models ``geniex_qairt`` export
   folder (metadata.json, genie configs, the part*_of_N.bin context binaries,
   vision_encoder.bin, tokenizer.json). The folder is checked file by file
   before anything is loaded; GenieX reads metadata.json from it directly.
3. ``from_pretrained`` actually creates the model handle.
4. A short probe generation returns real tokens.

``npu`` is True only when, additionally, the handle was created on the
``qairt`` plugin with device ``NPU``, ``qairt`` is in the runtime list that
libgeniex reports, that runtime lists an NPU compute unit, and the probe's
profile is stamped ``qairt``/``NPU``. Anything less is reported as it is.

There is no fallback inside this provider: if any step fails the provider is
UNAVAILABLE with the reason, and the registry does not quietly substitute a
different model (app/models/registry.py).
"""

from __future__ import annotations

import asyncio
import json
import platform
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from app.config import settings
from app.errors import ModelUnavailable
from app.logging_setup import get_logger
from app.models.base import READY, ImageRef, ModelHealth, ReasoningProvider
from app.models.qwen_vl import parse_tool_calls

log = get_logger(__name__)

PROVIDER = "GenieX/QAIRT"
FALLBACK = "none — Orion will say it cannot interpret requests until the model runs"
QAIRT = "qairt"

# A tiny, deterministic generation used to prove the model really runs before
# the provider calls itself ready.
# Where GenieX's native runtime exists (geniex 0.7.0 `_sdk_fetch._detect_platform`).
GENIEX_HOSTS = {("Windows", "ARM64"), ("Linux", "AARCH64"), ("Linux", "ARM64")}
BUNDLE_RUNTIME = "geniex_qairt"
BUNDLE_MODEL_ID = "qwen3_vl_4b_instruct"

PROBE_MESSAGES = [{"role": "user", "content": "Reply with the single word: ready"}]
PROBE_TOKENS = 8


def display_name(model_ref: str) -> str:
    """``ai-hub-models/Qwen3-VL-4B-Instruct[:w4a16]`` -> ``Qwen3-VL-4B-Instruct``."""
    tail = model_ref.replace("\\", "/").rstrip("/").split("/")[-1]
    return tail.split(":")[0] or model_ref


def to_geniex_messages(messages: Sequence[Dict[str, Any]],
                       image_paths: Sequence[str]) -> List[Dict[str, Any]]:
    """Orion's chat messages -> the GenieX VLM chat-template format.

    * Every system message is folded into one leading system turn — Qwen's
      chat template expects at most one, first.
    * Consecutive turns from the same speaker are joined, so the template sees
      a clean user/assistant alternation.
    * Images belong to the current (last) user turn, as ``{"type": "image",
      "image": <path>}`` blocks before its text. GenieX requires the same paths
      to be passed to ``generate(images=...)``.
    """
    system: List[str] = []
    turns: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, list):  # already-structured content: keep the text parts
            content = "\n".join(str(p.get("text", "")) for p in content
                                if isinstance(p, dict) and p.get("type") == "text")
        text = str(content or "").strip()
        if not text:
            continue
        if role == "system":
            system.append(text)
            continue
        if role not in ("user", "assistant"):
            # Tool output and the like reach the model as context the user supplied.
            role = "user"
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n\n" + text
        else:
            turns.append({"role": role, "content": text})

    if not turns or turns[-1]["role"] != "user":
        turns.append({"role": "user", "content": "Continue."})

    out: List[Dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": "\n\n".join(system)})
    out.extend(turns)

    if image_paths:
        last = out[-1]
        blocks: List[Dict[str, Any]] = [{"type": "image", "image": p} for p in image_paths]
        blocks.append({"type": "text", "text": last["content"]})
        out[-1] = {"role": "user", "content": blocks}
    return out


def _profile_dict(profile: Any) -> Dict[str, Any]:
    keys = ("backend", "device", "quant", "prompt_tokens", "generated_tokens",
            "ttft", "media_time", "prompt_time", "decode_time",
            "prefill_speed", "decode_speed", "stop_reason")
    return {k: getattr(profile, k, None) for k in keys}


class GenieXQwen3VLProvider(ReasoningProvider):
    """Qwen3-VL-4B-Instruct via GenieX (QAIRT plugin -> Hexagon NPU)."""

    def __init__(self, model_ref: Optional[str] = None,
                 device_map: Optional[str] = None) -> None:
        self.model_ref = model_ref or settings.geniex_model
        super().__init__(display_name(self.model_ref), PROVIDER)
        self.device_map = (device_map or settings.geniex_device_map or QAIRT).lower()
        self.max_new_tokens = settings.geniex_max_new_tokens
        self._gx: Any = None
        self._model: Any = None
        # One model handle, one KV cache: generations are strictly serialised.
        self._gen_lock = threading.Lock()
        self._last_profile: Dict[str, Any] = {}

    # ------------------------------------------------------------------ load
    def _unavailable(self, reason: str) -> ModelUnavailable:
        return ModelUnavailable(reason, model=self.model_id, fallback=FALLBACK)

    def _load(self) -> None:
        host = _host()
        # The bundle is inspected first, on any host, so the status can say
        # truthfully whether the asset is installed even where it cannot run.
        bundle: Optional[Dict[str, Any]] = None
        if settings.geniex_model_path:
            bundle = self._inspect_bundle(Path(settings.geniex_model_path))

        if (host["system"], host["machine"].upper()) not in GENIEX_HOSTS:
            where = f"{host['system']} {host['machine']}, Python {host['python']}"
            if bundle:
                raise self._unavailable(
                    f"{bundle['model_name']} asset installed ({bundle['precision']}, QAIRT "
                    f"{bundle['qairt_version']}, built for {bundle['chipset']}) at {bundle['path']}, "
                    "but local GenieX/QAIRT NPU execution requires a Windows ARM64 Snapdragon "
                    f"machine with ARM64 Python. This host is {where}. Remote validation on a "
                    "hosted Snapdragon device: scripts/aihub_devicecloud_validate.py.")
            raise self._unavailable(
                "local GenieX/QAIRT NPU execution requires a Windows ARM64 Snapdragon machine "
                f"with ARM64 Python; this host is {where}.")

        try:
            import geniex as gx  # type: ignore
        except Exception as exc:
            raise self._unavailable(
                f"geniex is not importable ({type(exc).__name__}: {exc}). On the Snapdragon "
                "machine: ARM64 Python 3.10+, then `pip install -r requirements-snapdragon.txt`. "
                f"This host is {host['system']} {host['machine']}.")
        self._gx = gx

        if settings.geniex_qairt_runtime_path:
            gx.set_qairt_runtime_path(settings.geniex_qairt_runtime_path)
        try:
            gx.init()
        except Exception as exc:
            raise self._unavailable(f"geniex.init() failed: {type(exc).__name__}: {exc}")

        evidence: Dict[str, Any] = {"host": host, "model_ref": self.model_ref,
                                    "device_map_requested": self.device_map}
        if bundle:
            evidence["bundle"] = bundle
        evidence["geniex_version"] = _safe(gx.version) or getattr(gx, "__version__", None)
        runtimes = _safe(gx.get_runtime_list) or []
        evidence["runtimes"] = runtimes
        if QAIRT in runtimes:
            evidence["qairt_plugin_version"] = _safe(lambda: gx.get_plugin_version(QAIRT))
            evidence["qairt_compute_units"] = [
                list(cu) for cu in (_safe(lambda: gx.get_compute_unit_list(QAIRT)) or [])]
        evidence["chipset"] = _safe(lambda: gx.model_manager.detect_chipset(offline=True))
        if bundle and evidence["chipset"]:
            # Context binaries are compiled per SoC; record whether this one matches.
            evidence["bundle_chipset_match"] = _same_chipset(evidence["chipset"], bundle)

        wants_npu = self.device_map in (QAIRT, "npu", "qairt:npu")
        if wants_npu and QAIRT not in runtimes:
            raise self._unavailable(
                "the GenieX QAIRT runtime is not registered on this machine "
                f"(runtimes: {', '.join(runtimes) or 'none'}), so the NPU cannot be used. "
                "Qualcomm AI Hub models run on the NPU only.")

        source = self._resolve_source(gx, evidence)

        started = time.perf_counter()
        try:
            kwargs: Dict[str, Any] = {"device_map": self.device_map}
            if settings.geniex_precision:
                kwargs["precision"] = settings.geniex_precision
            elif bundle:
                kwargs["precision"] = bundle["precision"]
            # QAIRT takes the context length from the bundle and ignores n_ctx.
            if settings.geniex_n_ctx and not self.device_map.startswith(QAIRT):
                kwargs["n_ctx"] = settings.geniex_n_ctx
            self._model = gx.AutoModelForVision2Seq.from_pretrained(source, **kwargs)
        except Exception as exc:
            raise self._unavailable(
                f"GenieX could not load {self.model_ref} with device_map='{self.device_map}': "
                f"{type(exc).__name__}: {exc}")
        load_ms = round((time.perf_counter() - started) * 1000, 1)

        meta = dict(getattr(self._model, "_meta", None) or {})
        evidence["handle"] = {k: meta.get(k) for k in ("backend", "device", "quant", "model_path")}

        # Proof of life: a real generation, not just a created handle.
        probe: Dict[str, Any] = {}
        if settings.geniex_probe:
            try:
                out = self._generate_blocking(PROBE_MESSAGES, [], max_new_tokens=PROBE_TOKENS,
                                              temperature=0.0)
            except Exception as exc:
                self._close()
                raise self._unavailable(
                    f"{self.model_id} loaded but the probe generation failed: "
                    f"{type(exc).__name__}: {exc}")
            probe = {"text": (out.text or "")[:40], **_profile_dict(out.profile)}
            if not probe.get("generated_tokens"):
                self._close()
                raise self._unavailable(
                    f"{self.model_id} loaded but the probe produced no tokens "
                    f"(stop_reason={probe.get('stop_reason')})")
        evidence["probe"] = probe

        npu, why = self._npu_verdict(evidence)
        evidence["npu_verdict"] = why
        self._health = ModelHealth(
            role=self.role, provider=self.provider, model_id=self.model_id, status=READY,
            runtime=f"geniex {evidence.get('geniex_version') or '?'} / {meta.get('backend') or '?'}",
            accelerator="npu" if npu else _accelerator_from(meta),
            npu=npu, synthetic=False,
            asset_path=str(meta.get("model_path") or source),
            load_ms=load_ms,
            detail={**evidence, "multimodal": True, "max_new_tokens": self.max_new_tokens},
        )
        log.info("GenieX %s ready: backend=%s device=%s npu=%s load_ms=%s",
                 self.model_id, meta.get("backend"), meta.get("device"), npu, load_ms)

    def _inspect_bundle(self, p: Path) -> Dict[str, Any]:
        """Check a Qualcomm AI Hub Models ``geniex_qairt`` export folder on disk:
        it must be the Qwen3-VL-4B-Instruct VLM bundle and every file its own
        metadata.json lists must be present. Reads only small JSON files."""
        if not p.is_dir():
            raise self._unavailable(f"VF_GENIEX_MODEL_PATH is not a folder: {p}")
        meta_path = p / "metadata.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise self._unavailable(
                f"{p} has no metadata.json — point VF_GENIEX_MODEL_PATH at the extracted "
                "Qualcomm AI Hub Models geniex_qairt bundle folder itself")
        except (OSError, ValueError) as exc:
            raise self._unavailable(f"{meta_path} is unreadable: {type(exc).__name__}: {exc}")
        if meta.get("runtime") != BUNDLE_RUNTIME:
            raise self._unavailable(
                f"{p} is a '{meta.get('runtime')}' export, not a {BUNDLE_RUNTIME} bundle")
        if meta.get("model_id") != BUNDLE_MODEL_ID:
            raise self._unavailable(
                f"{p} holds '{meta.get('model_id')}', not {BUNDLE_MODEL_ID} (Qwen3-VL-4B-Instruct)")
        genie = meta.get("genie") or {}
        if not genie.get("supports_vision"):
            raise self._unavailable(f"{p} metadata.json does not declare a vision-capable bundle")
        needed = list((meta.get("model_files") or {}).keys()) + ["tokenizer.json"]
        missing = [f for f in needed if not (p / f).is_file()]
        if missing:
            raise self._unavailable(f"{p} is incomplete — missing: {', '.join(missing)}")
        chip = meta.get("chipset_attributes") or {}
        return {
            "source": "path", "path": str(p),
            "model_name": meta.get("model_name") or display_name(self.model_ref),
            "precision": meta.get("precision") or "",
            "qairt_version": (meta.get("tool_versions") or {}).get("qairt"),
            "chipset": chip.get("reference_device") or chip.get("marketing_name") or "unknown",
            "chipset_name": chip.get("name") or chip.get("marketing_name"),
            "htp_version": chip.get("htp_version"), "soc_model": chip.get("soc_model"),
            "context_bins": [f for f in needed if f.endswith(".bin")],
            "bytes": sum((p / f).stat().st_size for f in needed),
        }

    def _resolve_source(self, gx: Any, evidence: Dict[str, Any]) -> str:
        """The bundle must already be on disk — a multi-GB download never starts
        from inside a chat request."""
        if settings.geniex_model_path:
            # Already inspected in _load(); GenieX reads metadata.json from it.
            return str(Path(settings.geniex_model_path))
        key = self.model_ref + (f":{settings.geniex_precision}" if settings.geniex_precision else "")
        try:
            paths = gx.model_manager.get_paths(key)
        except Exception as exc:
            raise self._unavailable(
                f"{self.model_ref} is not in the GenieX model cache ({type(exc).__name__}). "
                f"Run `geniex pull {self.model_ref}` on this machine first.")
        evidence["bundle"] = {"source": "geniex-cache", "model_dir": getattr(paths, "model_dir", None),
                              "runtime": getattr(paths, "runtime", None),
                              "model_type": getattr(paths, "model_type", None)}
        return self.model_ref

    def _npu_verdict(self, ev: Dict[str, Any]) -> tuple[bool, str]:
        handle = ev.get("handle") or {}
        probe = ev.get("probe") or {}
        units = [str(u).upper() for pair in (ev.get("qairt_compute_units") or []) for u in pair]
        checks = {
            "handle_on_qairt": handle.get("backend") == QAIRT,
            "handle_on_npu": str(handle.get("device") or "").upper() == "NPU",
            "qairt_runtime_registered": QAIRT in (ev.get("runtimes") or []),
            "qairt_lists_npu": any("NPU" in u for u in units),
            "probe_ran": bool(probe.get("generated_tokens")),
            "probe_on_qairt_npu": (probe.get("backend") == QAIRT
                                   and str(probe.get("device") or "").upper() == "NPU"),
        }
        failed = [k for k, ok in checks.items() if not ok]
        return (not failed), ("all checks passed: " + ", ".join(checks)) if not failed \
            else ("not claimed; failed: " + ", ".join(failed))

    def _close(self) -> None:
        if self._model is not None:
            try:
                self._model.close()
            except Exception:
                pass
        self._model = None

    # ------------------------------------------------------------ generation
    def capabilities(self) -> Dict[str, Any]:
        return {**super().capabilities(), "streaming": False, "images": True,
                "tool_calls": "prompted", "runtime": "geniex-qairt"}

    def _generate_blocking(self, messages: Sequence[Dict[str, Any]], image_paths: Sequence[str],
                           *, max_new_tokens: int, temperature: float) -> Any:
        model = self._model
        if model is None:
            raise self._unavailable("model handle is not loaded")
        with self._gen_lock:
            # Every Orion request carries its full context, so start from an
            # empty KV cache rather than continuing the previous request.
            model.reset()
            prompt = model.tokenizer.apply_chat_template(
                to_geniex_messages(messages, image_paths),
                tokenize=False, add_generation_prompt=True)
            sampling: Dict[str, Any] = {"max_new_tokens": max_new_tokens}
            if temperature and temperature > 0:
                sampling["temperature"] = float(temperature)
            else:
                # GenieX treats temperature 0 as "bundle default"; greedy is top_k=1.
                sampling["top_k"] = 1
            return model.generate(prompt, images=list(image_paths) or None, **sampling)

    async def generate(self, messages, images: Optional[Sequence[ImageRef]] = None,
                       tools=None, context=None) -> Dict[str, Any]:
        self.require_ready(fallback=FALLBACK)
        ctx = context or {}
        paths = [str(ref.path) for ref in (images or [])
                 if ref and Path(str(ref.path)).is_file()][: settings.geniex_max_images]
        max_new = int(ctx.get("max_tokens") or self.max_new_tokens)
        temperature = float(ctx.get("temperature", 0.2))
        try:
            out = await asyncio.to_thread(self._generate_blocking, messages, paths,
                                          max_new_tokens=max_new, temperature=temperature)
        except ModelUnavailable:
            raise
        except Exception as exc:
            raise ModelUnavailable(f"GenieX generation failed: {type(exc).__name__}: {exc}",
                                   model=self.model_id, fallback=FALLBACK)
        profile = _profile_dict(out.profile)
        self._last_profile = profile
        text, calls = parse_tool_calls(out.text or "")
        return {"text": text, "tool_calls": calls, "model": self.model_id,
                "usage": {"prompt_tokens": profile.get("prompt_tokens"),
                          "completion_tokens": profile.get("generated_tokens"),
                          "images": len(paths), "profile": profile}}

    def last_profile(self) -> Dict[str, Any]:
        return dict(self._last_profile)


def _host() -> Dict[str, str]:
    return {"system": platform.system(), "machine": platform.machine(),
            "python": platform.python_version()}


def _same_chipset(detected: Any, bundle: Dict[str, Any]) -> bool:
    d = str(detected).lower().replace("_", "-")
    names = {str(bundle.get(k) or "").lower().replace("_", "-") for k in ("chipset_name", "chipset")}
    return any(n and (n in d or d in n) for n in names)


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _accelerator_from(meta: Dict[str, Any]) -> str:
    device = str(meta.get("device") or "").lower()
    if device in ("cpu", "gpu"):
        return device
    return "unknown"
