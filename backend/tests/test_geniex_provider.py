"""The GenieX/QAIRT adapter's plumbing and honesty, against a fake ``geniex``.

These run anywhere. They check what the adapter does with what the runtime
reports — never that the real model or NPU works; that is proven on the
Snapdragon machine by scripts/geniex_smoke.py and tests/test_geniex_hardware.py.
"""

from __future__ import annotations

import asyncio
import json
import sys

import pytest
from PIL import Image

from app.config import settings
from app.models.base import READY, UNAVAILABLE, ImageRef
from app.models import geniex as geniex_mod
from app.models.geniex import GenieXQwen3VLProvider, display_name, to_geniex_messages
from tests import fake_geniex


@pytest.fixture(autouse=True)
def _snapdragon_host(monkeypatch):
    """These tests exercise the adapter as it behaves on its target host
    (Windows ARM64). The AMD64 gate has its own tests below."""
    monkeypatch.setattr(geniex_mod, "_host",
                        lambda: {"system": "Windows", "machine": "ARM64", "python": "3.12.10"})


def _bundle(tmp_path, **over):
    """A geniex_qairt bundle folder shaped like the real AI Hub Models export
    (metadata.json keys and file list), with tiny placeholder files."""
    d = tmp_path / "qwen3_vl_4b_instruct-geniex_qairt-w4a16-qualcomm_snapdragon_x_elite"
    d.mkdir()
    files = ["vision_encoder.bin", "part1_of_4.bin", "part2_of_4.bin", "part3_of_4.bin", "part4_of_4.bin"]
    meta = {
        "model_id": "qwen3_vl_4b_instruct", "model_name": "Qwen3-VL-4B-Instruct",
        "runtime": "geniex_qairt", "precision": "w4a16",
        "tool_versions": {"qairt": "2.45.0.260326154327"},
        "model_files": {f: {"inputs": {}, "outputs": {}} for f in files},
        "genie": {"supports_vision": True},
        "chipset_attributes": {"name": "qualcomm-snapdragon-x-elite", "htp_version": 73,
                               "soc_model": 60, "reference_device": "Snapdragon X Elite CRD"},
    }
    meta.update(over)
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    for f in files + ["tokenizer.json"]:
        (d / f).write_bytes(b"x")
    return d


def _install(monkeypatch, **kw):
    mod, state = fake_geniex.make(**kw)
    monkeypatch.setitem(sys.modules, "geniex", mod)
    return state


def _route_reply(intent="conversation"):
    def reply(messages, images):
        last = messages[-1]["content"]
        text = last if isinstance(last, str) else last[-1]["text"]
        if "Return the JSON object now" in text:
            return json.dumps({"intent": intent, "confidence": 0.9, "reason": "fake",
                               "requires_safety_gate": False})
        if "single word: ready" in text:
            return "ready"
        return "Hello! What are you working on today?"
    return reply


# ----------------------------------------------------------------- honesty

def test_not_installed_is_unavailable_not_npu(monkeypatch):
    monkeypatch.setitem(sys.modules, "geniex", None)
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE
    assert h.npu is False and h.accelerator == "none"
    assert "geniex is not importable" in h.reason


def test_missing_qairt_runtime_is_unavailable(monkeypatch):
    _install(monkeypatch, runtimes=("llama_cpp",))
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and h.npu is False
    assert "QAIRT runtime is not registered" in h.reason


def test_model_not_pulled_is_unavailable(monkeypatch):
    state = _install(monkeypatch, cached=False)
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE
    assert "geniex pull ai-hub-models/Qwen3-VL-4B-Instruct" in h.reason
    assert state["loads"] == []          # never tries to download from a request path


def test_load_failure_is_unavailable(monkeypatch):
    _install(monkeypatch, load_error="Invalid model format")
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and h.npu is False
    assert "Invalid model format" in h.reason


def test_installed_and_loaded_but_no_tokens_is_not_ready(monkeypatch):
    state = _install(monkeypatch, generated_tokens=0)
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE
    assert "probe produced no tokens" in h.reason
    assert state["model"].closed


def test_ready_on_qairt_npu_reports_real_evidence(monkeypatch):
    state = _install(monkeypatch)
    h = GenieXQwen3VLProvider().health()
    assert h.status == READY
    assert h.provider == "GenieX/QAIRT"
    assert h.model_id == "Qwen3-VL-4B-Instruct"
    assert h.accelerator == "npu" and h.npu is True and h.synthetic is False
    assert state["loads"][0]["device_map"] == "qairt"
    d = h.detail
    assert d["handle"]["backend"] == "qairt" and d["handle"]["device"] == "NPU"
    assert d["probe"]["generated_tokens"] > 0 and d["probe"]["backend"] == "qairt"
    assert d["npu_verdict"].startswith("all checks passed")
    assert d["chipset"] == "qualcomm-snapdragon-x-elite"


def test_non_npu_execution_is_reported_as_cpu(monkeypatch):
    _install(monkeypatch, backend="llama_cpp", device="CPU")
    monkeypatch.setattr(settings, "geniex_device_map", "cpu")
    h = GenieXQwen3VLProvider().health()
    assert h.status == READY
    assert h.npu is False and h.accelerator == "cpu"
    assert "handle_on_qairt" in h.detail["npu_verdict"]


def test_no_npu_compute_unit_means_no_npu_claim(monkeypatch):
    _install(monkeypatch, compute_units=(("CPU", "cpu"),))
    h = GenieXQwen3VLProvider().health()
    assert h.npu is False and "qairt_lists_npu" in h.detail["npu_verdict"]


def test_probe_disabled_never_claims_npu(monkeypatch):
    _install(monkeypatch)
    monkeypatch.setattr(settings, "geniex_probe", False)
    h = GenieXQwen3VLProvider().health()
    assert h.status == READY and h.npu is False
    assert "probe_ran" in h.detail["npu_verdict"]


# ------------------------------------------------- host gate and bundle

def test_amd64_host_with_bundle_is_unavailable_and_says_why(monkeypatch, tmp_path):
    state = _install(monkeypatch)                 # even an importable geniex is not used
    monkeypatch.setattr(geniex_mod, "_host",
                        lambda: {"system": "Windows", "machine": "AMD64", "python": "3.12.10"})
    monkeypatch.setattr(settings, "geniex_model_path", str(_bundle(tmp_path)))
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and h.npu is False and h.accelerator == "none"
    assert "Qwen3-VL-4B-Instruct asset installed" in h.reason
    assert "requires a Windows ARM64 Snapdragon machine" in h.reason
    assert "Windows AMD64" in h.reason and "Snapdragon X Elite CRD" in h.reason
    assert state["loads"] == []


def test_amd64_host_without_bundle_is_unavailable(monkeypatch):
    monkeypatch.setattr(geniex_mod, "_host",
                        lambda: {"system": "Linux", "machine": "x86_64", "python": "3.12.3"})
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and h.npu is False
    assert "requires a Windows ARM64 Snapdragon machine" in h.reason


def test_bundle_path_without_metadata_is_rejected(monkeypatch, tmp_path):
    _install(monkeypatch)
    monkeypatch.setattr(settings, "geniex_model_path", str(tmp_path))
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and "no metadata.json" in h.reason


def test_bundle_for_a_different_model_is_rejected(monkeypatch, tmp_path):
    _install(monkeypatch)
    monkeypatch.setattr(settings, "geniex_model_path", str(_bundle(tmp_path, model_id="llama_v3_2_3b")))
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and "not qwen3_vl_4b_instruct" in h.reason


def test_incomplete_bundle_is_rejected(monkeypatch, tmp_path):
    state = _install(monkeypatch)
    d = _bundle(tmp_path)
    (d / "part3_of_4.bin").unlink()
    monkeypatch.setattr(settings, "geniex_model_path", str(d))
    h = GenieXQwen3VLProvider().health()
    assert h.status == UNAVAILABLE and "missing: part3_of_4.bin" in h.reason
    assert state["loads"] == []


def test_bundle_path_loads_that_folder_on_qairt(monkeypatch, tmp_path):
    state = _install(monkeypatch)
    d = _bundle(tmp_path)
    monkeypatch.setattr(settings, "geniex_model_path", str(d))
    h = GenieXQwen3VLProvider().health()
    assert h.status == READY and h.npu is True
    load = state["loads"][0]
    assert load["source"] == str(d) and load["device_map"] == "qairt"
    assert load["precision"] == "w4a16" and "n_ctx" not in load
    b = h.detail["bundle"]
    assert b["model_name"] == "Qwen3-VL-4B-Instruct" and b["qairt_version"].startswith("2.45")
    assert h.detail["bundle_chipset_match"] is True


# ------------------------------------------------------------- conversion

def test_display_name():
    assert display_name("ai-hub-models/Qwen3-VL-4B-Instruct") == "Qwen3-VL-4B-Instruct"
    assert display_name("ai-hub-models/Qwen3-VL-4B-Instruct:w4a16") == "Qwen3-VL-4B-Instruct"


def test_messages_fold_system_and_attach_images_to_last_user_turn():
    out = to_geniex_messages([
        {"role": "system", "content": "persona"},
        {"role": "system", "content": "evidence"},
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "look at this"},
        {"role": "user", "content": "and this"},
    ], ["C:/a.jpg", "C:/b.jpg"])
    assert out[0] == {"role": "system", "content": "persona\n\nevidence"}
    assert [m["role"] for m in out] == ["system", "user", "assistant", "user"]
    last = out[-1]["content"]
    assert last[:2] == [{"type": "image", "image": "C:/a.jpg"},
                        {"type": "image", "image": "C:/b.jpg"}]
    assert last[2] == {"type": "text", "text": "look at this\n\nand this"}


def test_generate_passes_images_resets_kv_and_parses_tools(monkeypatch, tmp_path):
    seen = {}

    def reply(messages, images):
        seen["messages"], seen["images"] = messages, images
        if images:
            return ('The nameplate reads 415 V.\n<tool_call>{"name": "ocr_extract", '
                    '"arguments": {"image_id": "img1"}}</tool_call>')
        return "ready"

    state = _install(monkeypatch, reply=reply)
    p = GenieXQwen3VLProvider()
    assert p.health().status == READY
    path = tmp_path / "plate.jpg"
    Image.new("RGB", (64, 64), (200, 30, 30)).save(path)
    ref = ImageRef(id="img1", path=str(path), width=64, height=64)

    result = asyncio.run(p.generate(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": "what is this?"}],
        images=[ref], context={"purpose": "technical", "temperature": 0.2, "max_tokens": 99}))

    model = state["model"]
    call = model.generate_calls[-1]
    assert call["images"] == [str(path)]
    assert call["max_new_tokens"] == 99 and call["temperature"] == 0.2
    assert model.resets >= 2                        # probe + this request
    assert seen["messages"][-1]["content"][0] == {"type": "image", "image": str(path)}
    assert result["text"] == "The nameplate reads 415 V."
    assert result["tool_calls"] == [{"tool": "ocr_extract", "arguments": {"image_id": "img1"}}]
    assert result["usage"]["profile"]["backend"] == "qairt"


def test_route_purpose_is_greedy(monkeypatch):
    state = _install(monkeypatch, reply=_route_reply())
    p = GenieXQwen3VLProvider()
    asyncio.run(p.generate([{"role": "user", "content": "x\n\nReturn the JSON object now."}],
                           context={"purpose": "route", "temperature": 0.0, "max_tokens": 160}))
    call = state["model"].generate_calls[-1]
    assert call["top_k"] == 1 and "temperature" not in call and call["max_new_tokens"] == 160


# --------------------------------------------------------- registry + API

def test_explicit_provider_never_substitutes(isolated_data, monkeypatch):
    from app.models.registry import registry as models

    monkeypatch.setitem(sys.modules, "geniex", None)
    monkeypatch.setattr(settings, "reasoning_provider", "geniex-qwen3-vl")
    monkeypatch.setattr(settings, "local_llm_url", "http://127.0.0.1:9/v1")
    models.reload()
    status = models.status()["roles"]["reasoning"]
    assert status["status"] == UNAVAILABLE and status["npu"] is False
    assert [a["provider"] for a in status["candidates_tried"]] == ["geniex-qwen3-vl"]


def test_unknown_provider_name_is_not_silently_replaced(isolated_data, monkeypatch):
    from app.models.registry import registry as models

    monkeypatch.setattr(settings, "reasoning_provider", "geniex-qwen3vl-typo")
    models.reload()
    tried = models.status()["roles"]["reasoning"]["candidates_tried"]
    assert tried[0]["provider"] == "geniex-qwen3vl-typo"
    assert "unknown provider" in tried[0]["reason"]


def test_chat_routes_and_answers_through_geniex(client, monkeypatch):
    from app.models.registry import registry as models

    _install(monkeypatch, reply=_route_reply("conversation"))
    monkeypatch.setattr(settings, "reasoning_provider", "geniex-qwen3-vl")
    models.reload()

    status = client.get("/api/models/status").json()["roles"]["reasoning"]
    assert status["provider"] == "GenieX/QAIRT" and status["npu"] is True

    body = client.post("/api/chat", json={"message": "hellooo"}).json()
    assert body["kind"] == "conversation"
    assert body["engine_available"] is True
    assert body["text"] == "Hello! What are you working on today?"
    assert body["model"]["model_id"] == "Qwen3-VL-4B-Instruct"
    assert body["model"]["accelerator"] == "npu"
