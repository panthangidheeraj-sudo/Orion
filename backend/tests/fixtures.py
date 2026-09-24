"""The §27 test fixtures.

Ten scenarios, generated rather than checked in as binaries so the suite stays
small and every fixture is inspectable as code:

 1. PCB with readable component labels
 2. Electric motor nameplate
 3. Motor + mechanical assembly
 4. Industrial control panel
 5. Damaged / loose component
 6. Text-only manual
 7. Diagram-heavy manual
 8. Wiring schematic
 9. Multi-page service manual
10. Same machine inspected across two sessions  (see test_end_to_end.py)

The images are synthetic line art, not photographs. They are honest about what
they are: they exercise ingest, storage, image statistics, the visual-document
path and the agent loop. They do **not** prove a detector or OCR model works —
that needs real photographs on the target device, and MODEL_STATUS.md says so.
"""

from __future__ import annotations

from io import BytesIO
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw

INK = (232, 234, 238)
DIM = (150, 156, 164)
DARK = (22, 24, 28)
PAPER = (244, 244, 240)


def _jpeg(img: Image.Image, quality: int = 92) -> bytes:
    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


# --------------------------------------------------------------------- images

def pcb_with_labels() -> bytes:
    """1. A board with silkscreen designators — the OCR case."""
    img = Image.new("RGB", (800, 600), (18, 46, 30))
    d = ImageDraw.Draw(img)
    for x in range(60, 740, 90):            # traces
        d.line([(x, 40), (x, 560)], fill=(196, 170, 84), width=2)
    for i, (x, y, ref, val) in enumerate([
        (90, 120, "C14", "470uF"), (250, 120, "R22", "10k"), (410, 120, "U3", "LM2596"),
        (570, 120, "D7", "1N4007"), (90, 340, "Q1", "IRFZ44N"), (250, 340, "L2", "100uH"),
        (410, 340, "J5", "24VDC"), (570, 340, "F1", "T2A"),
    ]):
        d.rectangle([x, y, x + 110, y + 70], outline=INK, width=2)
        d.text((x + 6, y + 78), ref, fill=INK)
        d.text((x + 6, y + 92), val, fill=DIM)
    d.text((60, 20), "PCB REV C  BOARD 4412-B", fill=INK)
    return _jpeg(img)


def motor_nameplate() -> bytes:
    """2. A nameplate — the case where reading the plate is the whole job."""
    img = Image.new("RGB", (760, 520), (58, 60, 64))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 720, 480], fill=(96, 98, 104), outline=INK, width=3)
    rows = [
        ("MANUFACTURER", "SIEMENS"), ("MODEL", "CNC-M04"), ("SERIAL", "SN-99123"),
        ("VOLTAGE", "400 VAC"), ("CURRENT", "11.4 A"), ("POWER", "5.5 kW"),
        ("SPEED", "1450 rpm"), ("INS CLASS", "F"), ("DUTY", "S1"), ("IP", "IP55"),
    ]
    for i, (k, v) in enumerate(rows):
        y = 70 + i * 40
        d.text((70, y), k, fill=DIM)
        d.text((330, y), v, fill=INK)
        d.line([(60, y + 26), (700, y + 26)], fill=(120, 122, 128), width=1)
    return _jpeg(img)


def motor_assembly() -> bytes:
    """3. A motor coupled to a driven load — the mechanical case."""
    img = Image.new("RGB", (860, 520), DARK)
    d = ImageDraw.Draw(img)
    d.rectangle([80, 170, 380, 360], outline=INK, width=3)          # motor body
    for x in range(100, 370, 22):                                    # cooling fins
        d.line([(x, 175), (x, 355)], fill=DIM, width=2)
    d.rectangle([380, 240, 470, 290], outline=INK, width=3)          # shaft
    d.ellipse([460, 215, 560, 315], outline=INK, width=3)            # coupling
    d.rectangle([560, 190, 800, 340], outline=INK, width=3)          # gearbox
    d.rectangle([80, 360, 800, 400], outline=DIM, width=2)           # base plate
    for label, x in (("MOTOR", 180), ("COUPLING", 470), ("GEARBOX", 640)):
        d.text((x, 420), label, fill=DIM)
    d.text((80, 130), "DRIVE END", fill=INK)
    return _jpeg(img)


def control_panel() -> bytes:
    """4. A control panel — many similar components, an ambiguous scene."""
    img = Image.new("RGB", (820, 640), (34, 36, 40))
    d = ImageDraw.Draw(img)
    d.rectangle([30, 30, 790, 610], outline=INK, width=3)
    for r in range(3):                                               # DIN rails
        y = 90 + r * 170
        d.line([(60, y + 110), (760, y + 110)], fill=DIM, width=4)
        for c in range(6):
            x = 70 + c * 115
            d.rectangle([x, y, x + 95, y + 105], outline=INK, width=2)
            d.text((x + 8, y + 112), f"K{r}{c}", fill=DIM)
    d.text((60, 45), "MCC PANEL 2 — LINE 4", fill=INK)
    return _jpeg(img)


def damaged_component() -> bytes:
    """5. A component with visible damage — heat discolouration and a crack."""
    img = Image.new("RGB", (760, 560), DARK)
    d = ImageDraw.Draw(img)
    d.ellipse([200, 140, 560, 420], outline=INK, width=4)            # bearing housing
    d.ellipse([290, 230, 470, 330], outline=DIM, width=3)
    for i, c in enumerate([(140, 78, 40), (168, 96, 44), (196, 120, 52)]):
        d.arc([200 - i * 10, 140 - i * 10, 560 + i * 10, 420 + i * 10], 200, 340,
              fill=c, width=6)                                       # heat bloom
    d.line([(300, 400), (360, 452), (330, 500)], fill=(240, 120, 100), width=4)  # crack
    d.text((210, 470), "DRIVE END BEARING", fill=DIM)
    return _jpeg(img)


def blurred_frame() -> bytes:
    """A frame with almost no edge detail — the agent should say it cannot see."""
    img = Image.new("RGB", (640, 480), (44, 46, 50))
    d = ImageDraw.Draw(img)
    d.ellipse([160, 120, 480, 360], fill=(52, 54, 58))
    return _jpeg(img, quality=60)


def dark_frame() -> bytes:
    """An underexposed frame — a label would not be readable."""
    img = Image.new("RGB", (640, 480), (7, 7, 9))
    d = ImageDraw.Draw(img)
    d.rectangle([200, 180, 440, 300], outline=(24, 24, 28), width=2)
    return _jpeg(img)


# ------------------------------------------------------------------ documents

def _pdf(pages: List[Tuple[str, str]], draw_each=None) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for i, (heading, body) in enumerate(pages, start=1):
        page = doc.new_page()
        page.insert_text((60, 80), heading, fontsize=15)
        if body:
            page.insert_textbox(pymupdf.Rect(60, 110, 540, 700), body, fontsize=11)
        if draw_each:
            draw_each(page, i, pymupdf)
    buf = doc.tobytes()
    doc.close()
    return buf


def text_only_manual() -> bytes:
    """6. Prose, no figures — the plain retrieval case."""
    return _pdf([
        ("1. SAFETY",
         "Isolate the supply and prove dead before removing any terminal cover. "
         "Rotating parts remain hazardous until the shaft has come to rest. Only an "
         "authorised person may work inside the drive enclosure."),
        ("4.3 THERMAL PROTECTION",
         "Fault code E17 indicates a motor thermal overload. The drive latches E17 when "
         "the thermistor circuit at terminals T1 and T2 opens. Expected resistance is "
         "250 ohm cold, rising above 4000 ohm at trip temperature. Reset is manual."),
        ("4.4 BEARING SERVICE",
         "The drive end bearing is NSK 6203-2RS. Replace it when vibration at the drive "
         "end exceeds 7.1 mm/s RMS or audible grinding is present. Torque the end shield "
         "bolts to 24 Nm in a diagonal sequence."),
        ("7. NAMEPLATE",
         "Model CNC-M04. Rated 400 VAC, 11.4 A, 5.5 kW, 1450 rpm. Insulation class F. "
         "Duty S1. Enclosure IP55."),
    ])


def diagram_heavy_manual() -> bytes:
    """7. Figures carrying the meaning — the visual-brain case.

    The text says "see figure"; the answer is only in the drawing. This is what
    ``get_document_page`` exists for.
    """
    def draw(page, i, pymupdf):
        if i == 2:                                   # exploded view
            for j in range(6):
                x = 90 + j * 70
                page.draw_circle(pymupdf.Point(x, 380), 22, width=1.2)
                page.insert_text((x - 8, 430), f"{j + 1}", fontsize=9)
            page.draw_line(pymupdf.Point(80, 470), pymupdf.Point(500, 470), width=1)
            page.insert_text((80, 490), "Fig 2.1 — drive end assembly, exploded", fontsize=9)
        if i == 3:                                   # test point layout
            page.draw_rect(pymupdf.Rect(90, 320, 480, 470), width=1.2)
            for j, label in enumerate(["T1", "T2", "PE", "U", "V", "W"]):
                x = 120 + j * 60
                page.draw_circle(pymupdf.Point(x, 400), 9, width=1)
                page.insert_text((x - 7, 425), label, fontsize=9)
            page.insert_text((90, 495), "Fig 3.1 — terminal layout, cover removed", fontsize=9)

    return _pdf([
        ("1. ABOUT THIS MANUAL",
         "Illustrations are the authoritative reference for component positions. Where "
         "the text and a figure disagree, follow the figure."),
        ("2. DRIVE END ASSEMBLY",
         "See figure 2.1 for the order of assembly. Items are numbered in the order of "
         "removal. Do not reuse the shaft seal."),
        ("3. TERMINAL LAYOUT",
         "See figure 3.1 for terminal positions with the cover removed. Thermistor "
         "terminals T1 and T2 sit to the left of the motor terminals."),
    ], draw_each=draw)


def wiring_schematic() -> bytes:
    """8. A schematic — lines and designators rather than prose."""
    def draw(page, i, pymupdf):
        page.draw_line(pymupdf.Point(70, 160), pymupdf.Point(520, 160), width=1)
        page.draw_line(pymupdf.Point(70, 200), pymupdf.Point(520, 200), width=1)
        page.draw_line(pymupdf.Point(70, 240), pymupdf.Point(520, 240), width=1)
        page.insert_text((40, 163), "L1", fontsize=9)
        page.insert_text((40, 203), "L2", fontsize=9)
        page.insert_text((40, 243), "L3", fontsize=9)
        for j, tag in enumerate(["Q1", "KM1", "F2", "M1"]):
            x = 130 + j * 110
            page.draw_rect(pymupdf.Rect(x, 140, x + 60, 260), width=1.2)
            page.insert_text((x + 18, 285), tag, fontsize=10)
        page.insert_text((70, 330), "Control circuit: X4-1 to X4-2 via E-stop S1", fontsize=10)

    return _pdf([("SCHEMATIC 4412-B SHEET 1",
                  "Three phase supply through isolator Q1, contactor KM1 and overload F2 "
                  "to motor M1. Thermistor loop returns on X4-1 and X4-2.")],
                draw_each=draw)


def multipage_service_manual(pages: int = 24) -> bytes:
    """9. A long manual — retrieval has to find one page among many."""
    body = []
    for n in range(1, pages + 1):
        if n == 17:
            body.append(("17. COOLANT PUMP",
                         "The coolant pump is fed from terminal X4 via contactor KM3. "
                         "Fault code P09 indicates loss of coolant flow. Check the flow "
                         "switch at FS1 before replacing the pump."))
        elif n == 11:
            body.append(("11. GREASING INTERVALS",
                         "Regrease the drive end bearing every 4000 running hours with "
                         "2.5 g of lithium complex grease. Do not mix grease types."))
        else:
            body.append((f"{n}. SECTION {n}",
                         f"General maintenance notes for section {n}. Routine inspection, "
                         "cleaning and record keeping apply as described in section 1."))
    return _pdf(body)


SCENARIOS: Dict[str, str] = {
    "pcb_with_labels": "PCB with readable component labels",
    "motor_nameplate": "Electric motor nameplate",
    "motor_assembly": "Motor + mechanical assembly",
    "control_panel": "Industrial control panel",
    "damaged_component": "Damaged/loose component",
    "text_only_manual": "Text-only manual",
    "diagram_heavy_manual": "Diagram-heavy manual",
    "wiring_schematic": "Wiring schematic",
    "multipage_service_manual": "Multi-page service manual",
    "two_sessions": "Same machine inspected across two sessions",
}
