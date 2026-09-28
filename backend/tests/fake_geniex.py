"""A stand-in for the ``geniex`` package — TESTS ONLY.

It mirrors the surface of geniex 0.7 that app/models/geniex.py uses, so the
adapter's plumbing (message conversion, image hand-off, KV reset, honest
health) can be tested on any machine. It proves nothing about the real model
or the NPU; that is what scripts/geniex_smoke.py and
tests/test_geniex_hardware.py are for, on the Snapdragon machine.
"""

from __future__ import annotations

import json
import types
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Profile:
    backend: Optional[str] = "qairt"
    device: Optional[str] = "NPU"
    quant: Optional[str] = None
    model_path: Optional[str] = None
    prompt_tokens: int = 12
    generated_tokens: int = 3
    ttft: int = 90
    media_time: int = 0
    prompt_time: int = 40
    decode_time: int = 60
    prefill_speed: float = 300.0
    decode_speed: float = 18.0
    stop_reason: Optional[str] = "eos"


@dataclass
class Output:
    text: str
    profile: Profile
    thinking: Optional[str] = None


class FakeTokenizer:
    def __init__(self, model: "FakeVLM") -> None:
        self.model = model

    def apply_chat_template(self, messages, tokenize=False, add_generation_prompt=True, **_):
        self.model.templates.append(messages)
        return json.dumps(messages)


@dataclass
class FakeVLM:
    meta: Dict[str, Any]
    reply: Callable[[List[Dict[str, Any]], List[str]], str]
    generated_tokens: int = 3
    templates: List[Any] = field(default_factory=list)
    generate_calls: List[Dict[str, Any]] = field(default_factory=list)
    resets: int = 0
    closed: bool = False

    def __post_init__(self) -> None:
        self._meta = self.meta
        self.tokenizer = FakeTokenizer(self)

    def reset(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True

    def generate(self, prompt, images=None, **kw):
        self.generate_calls.append({"prompt": prompt, "images": list(images or []), **kw})
        messages = json.loads(prompt)
        text = self.reply(messages, list(images or []))
        return Output(text=text, profile=Profile(
            backend=self._meta.get("backend"), device=self._meta.get("device"),
            generated_tokens=self.generated_tokens))


def make(*, runtimes=("qairt", "llama_cpp"), compute_units=(("NPU", "Hexagon NPU"),),
         cached=True, backend="qairt", device="NPU", load_error: Optional[str] = None,
         generated_tokens: int = 3,
         reply: Optional[Callable[[List[Dict[str, Any]], List[str]], str]] = None):
    """Build a fake ``geniex`` module. Returns (module, state)."""
    state: Dict[str, Any] = {"model": None, "loads": []}
    mod = types.ModuleType("geniex")
    mod.__version__ = "0.7.0-fake"

    class GenieXError(Exception):
        pass

    mod.GenieXError = GenieXError
    mod.init = lambda: None
    mod.version = lambda: "0.7.0-fake"
    mod.set_qairt_runtime_path = lambda path: None
    mod.get_runtime_list = lambda: list(runtimes)
    mod.get_plugin_version = lambda plugin: f"{plugin}-fake"

    def get_compute_unit_list(runtime):
        if runtime not in runtimes:
            raise GenieXError(f"unknown runtime {runtime}")
        return [tuple(cu) for cu in compute_units] if runtime == "qairt" else [("CPU", "cpu")]

    mod.get_compute_unit_list = get_compute_unit_list

    mm = types.SimpleNamespace()

    def get_paths(name):
        if not cached:
            raise GenieXError(f"model not found: {name}")
        return types.SimpleNamespace(model_dir="C:/geniex/models/Qwen3-VL-4B-Instruct",
                                     model_path="C:/geniex/models/Qwen3-VL-4B-Instruct/metadata.json",
                                     runtime="qairt", model_type="vlm")

    mm.get_paths = get_paths
    mm.detect_chipset = lambda offline=True: "qualcomm-snapdragon-x-elite"
    mod.model_manager = mm

    def from_pretrained(source, device_map="auto", **kw):
        state["loads"].append({"source": source, "device_map": device_map, **kw})
        if load_error:
            raise GenieXError(load_error)
        model = FakeVLM(
            meta={"model_name": source, "backend": backend, "device": device,
                  "quant": None, "model_path": "C:/geniex/models/Qwen3-VL-4B-Instruct"},
            reply=reply or (lambda messages, images: "ready"),
            generated_tokens=generated_tokens)
        state["model"] = model
        return model

    mod.AutoModelForVision2Seq = types.SimpleNamespace(from_pretrained=from_pretrained)
    return mod, state
