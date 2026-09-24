"""Test fixtures.

Every test runs against a throwaway data directory so the developer's real
knowledge vault, job history and memories are never touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    from app.config import settings
    from app.knowledge import web_search
    from app.memory import sqlite as db
    from app.memory import vector_store as vs
    from app.models.registry import registry as models

    monkeypatch.setattr(settings, "data_dir", tmp_path, raising=False)
    settings.ensure_dirs()
    db.reset_connections()
    db.init_db()
    vs.reset_cache()
    web_search.reset_provider()
    models.reload()
    yield tmp_path
    db.reset_connections()


@pytest.fixture
def client(isolated_data):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def manual_pdf(tmp_path) -> bytes:
    """A small but realistic service manual: safety, a fault code, a part, a nameplate."""
    import pymupdf

    pages = [
        ("1. SAFETY",
         "Isolate the supply and prove dead before removing any terminal cover. "
         "Rotating parts remain hazardous until the shaft has come to rest. "
         "Only an authorised person may work inside the drive enclosure."),
        ("4.3 THERMAL PROTECTION",
         "Fault code E17 indicates a motor thermal overload. The drive latches E17 when "
         "the thermistor circuit at terminals T1 and T2 opens. Expected resistance is "
         "250 ohm cold, rising above 4000 ohm at trip temperature. Reset is manual."),
        ("4.4 BEARING SERVICE",
         "The drive end bearing is NSK 6203-2RS. Replace it when vibration at the drive "
         "end exceeds 7.1 mm/s RMS or audible grinding is present. Torque the end "
         "shield bolts to 24 Nm in a diagonal sequence."),
        ("7. NAMEPLATE",
         "Model CNC-M04. Rated 400 VAC, 11.4 A, 5.5 kW, 1450 rpm. Insulation class F. "
         "Duty S1. Enclosure IP55."),
    ]
    doc = pymupdf.open()
    for heading, body in pages:
        page = doc.new_page()
        page.insert_text((60, 80), heading, fontsize=15)
        page.insert_textbox(pymupdf.Rect(60, 110, 540, 420), body, fontsize=11)
    out = tmp_path / "manual.pdf"
    doc.save(str(out))
    doc.close()
    return out.read_bytes()


@pytest.fixture
def photo_bytes() -> bytes:
    """A synthetic frame with structure, so image statistics are meaningful."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480), (28, 30, 34))
    d = ImageDraw.Draw(img)
    d.rectangle([120, 90, 420, 330], outline=(190, 195, 200), width=4)
    d.ellipse([200, 160, 340, 300], outline=(150, 155, 160), width=3)
    d.text((132, 350), "CNC-M04  400VAC  11.4A", fill=(230, 232, 235))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


@pytest.fixture
def second_frame() -> bytes:
    """A visibly different scene, to exercise live-mode change detection."""
    from io import BytesIO

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 480), (200, 198, 194))
    d = ImageDraw.Draw(img)
    for x in range(0, 640, 40):
        d.line([(x, 0), (x, 480)], fill=(40, 40, 44), width=6)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()
