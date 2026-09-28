"""Real-model tests: Qwen3-VL-4B-Instruct through GenieX/QAIRT on the Snapdragon NPU.

Skipped everywhere except the Snapdragon machine, where they are switched on
explicitly:

    set ORION_GENIEX_TEST=1
    python -m pytest tests/test_geniex_hardware.py -v

Once switched on they never skip: a model that does not load is a failure.
The model is loaded once for the whole module.
"""

from __future__ import annotations

import asyncio
import os

import pytest
from PIL import Image, ImageDraw, ImageFont

pytestmark = pytest.mark.skipif(
    os.environ.get("ORION_GENIEX_TEST") != "1",
    reason="real GenieX/QAIRT model test; set ORION_GENIEX_TEST=1 on the Snapdragon machine")


@pytest.fixture(scope="module")
def qwen():
    from app.models.geniex import GenieXQwen3VLProvider

    provider = GenieXQwen3VLProvider()
    h = provider.health()
    assert h.status == "ready", f"GenieX model did not load: {h.reason}"
    return provider


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------ runtime state

def test_model_is_qwen3_vl_on_geniex(qwen):
    h = qwen.health()
    assert h.provider == "GenieX/QAIRT"
    assert h.model_id == "Qwen3-VL-4B-Instruct"
    assert h.synthetic is False
    assert h.detail["probe"]["generated_tokens"] > 0


def test_npu_is_reported_by_the_runtime(qwen):
    h = qwen.health()
    if qwen.device_map not in ("qairt", "npu", "qairt:npu"):
        pytest.skip(f"VF_GENIEX_DEVICE_MAP={qwen.device_map}: NPU not requested")
    assert h.npu is True and h.accelerator == "npu", h.detail.get("npu_verdict")
    assert h.detail["handle"]["backend"] == "qairt"
    assert str(h.detail["handle"]["device"]).upper() == "NPU"


# ------------------------------------------------------------- text + route

def test_text_conversation(qwen):
    out = run(qwen.generate(
        [{"role": "system", "content": "You are Orion, a friendly assistant. Be brief."},
         {"role": "user", "content": "Hi! In one sentence, what can you help me with?"}],
        context={"purpose": "conversation", "temperature": 0.6, "max_tokens": 80}))
    assert len(out["text"].strip()) > 5
    assert out["usage"]["completion_tokens"] > 0
    assert out["usage"]["profile"]["backend"] == "qairt"


# Clear-cut cases: any competent router gets these right.
ROUTER_QA = [
    ("hellooo", "conversation"),
    ("do you like cats?", "conversation"),
    ("why are you called Orion?", "conversation"),
    ("my motor is vibrating", "technical"),
    ("the breaker trips after a few minutes", "technical"),
    ("what torque does this manual specify?", "technical"),
    ("there are sparks coming from the panel", "technical"),
]

# Deliberately vague: the router should ask, but reasonable models differ.
AMBIGUOUS = ["something's wrong", "it isn't working", "can you help?"]


@pytest.mark.parametrize("message,expected", ROUTER_QA)
def test_router_qa(qwen, message, expected):
    from app.agent import router

    decision = run(router.route(qwen, message))
    assert decision.available, decision.failure
    assert decision.intent == expected, f"{message!r} -> {decision.intent} ({decision.reason})"


def test_router_ambiguous_mostly_clarifies(qwen):
    from app.agent import router

    intents = [run(router.route(qwen, m)).intent for m in AMBIGUOUS]
    assert all(i in router.INTENTS for i in intents)
    assert sum(i == "ambiguous" for i in intents) >= 2, intents


def test_router_uses_conversation_context(qwen):
    from app.agent import router

    history = [{"role": "user", "content": "The conveyor motor on line 3 is overheating."},
               {"role": "assistant", "content": "How hot is the casing, and is it drawing "
                                                "more current than the nameplate rating?"}]
    decision = run(router.route(qwen, "about 90 degrees", history=history))
    assert decision.intent == "technical", decision.reason


# ---------------------------------------------------------------- image+text

def _swatch(path, colour, code):
    img = Image.new("RGB", (448, 448), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse([74, 40, 374, 340], fill=colour)
    try:
        font = ImageFont.load_default(size=64)
    except TypeError:                       # Pillow < 10.1
        font = ImageFont.load_default()
    d.text((150, 360), code, fill=(0, 0, 0), font=font)
    img.save(path)
    return path


@pytest.mark.parametrize("colour,name,code", [
    ((220, 20, 20), "red", "E42"),
    ((20, 60, 220), "blue", "F17"),
])
def test_image_and_text_reasoning(qwen, tmp_path, colour, name, code):
    """Two different pictures, the same question: the answers must follow the
    pixels, which a model that ignored the image could not do."""
    from app.models.base import ImageRef

    path = _swatch(tmp_path / f"{name}.png", colour, code)
    ref = ImageRef(id=name, path=str(path), width=448, height=448, mime_type="image/png")
    out = run(qwen.generate(
        [{"role": "user", "content": "What colour is the large circle, and what code is "
                                     "printed under it? Answer as: colour, code"}],
        images=[ref], context={"purpose": "technical", "temperature": 0.0, "max_tokens": 40}))
    answer = out["text"].lower()
    assert name in answer, out["text"]
    assert out["usage"]["images"] == 1
    assert (out["usage"]["profile"].get("media_time") or 0) >= 0
