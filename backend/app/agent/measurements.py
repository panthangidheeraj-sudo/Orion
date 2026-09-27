"""Readings the technician typed ("87 C", "11.4 A").

This is data parsing, not intent detection: it never decides what a message
is *about*. It exists so a stated reading can be proposed as a measurement
record, and so the safety review can tell a number the technician supplied
from one the model made up.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

MEASURE_UNIT = re.compile(
    # Longer units first: alternation takes the first branch that matches.
    r"(-?\d+(?:\.\d+)?)\s*(°?\s?[cf]\b|deg\b|celsius|volts?\b|vdc\b|vac\b|v\b|amps?\b|a\b|"
    r"ma\b|ohms?\b|hz\b|rpm\b|bar\b|psi\b|mm/s\b|mm\b|kw\b|hp\b|db\b)",
    re.I,
)
UNIT_CANON = {
    "c": "°C", "°c": "°C", "f": "°F", "°f": "°F", "deg": "°", "celsius": "°C",
    "v": "V", "volt": "V", "volts": "V", "vdc": "VDC", "vac": "VAC",
    "a": "A", "amp": "A", "amps": "A", "ma": "mA", "ohm": "Ω", "ohms": "Ω",
    "hz": "Hz", "rpm": "rpm", "bar": "bar", "psi": "psi", "mm": "mm",
    "kw": "kW", "hp": "hp", "db": "dB", "mm/s": "mm/s",
}
UNIT_TO_NAME = {
    "°C": "temperature", "°F": "temperature", "V": "voltage", "VDC": "voltage",
    "VAC": "voltage", "A": "current", "mA": "current", "Ω": "insulation_resistance",
    "Hz": "frequency", "rpm": "speed", "bar": "pressure", "psi": "pressure",
    "mm/s": "vibration", "dB": "sound_level", "kW": "power", "hp": "power",
    "mm": "length",
}


def extract_measurements(text: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for m in MEASURE_UNIT.finditer(text or ""):
        raw_unit = m.group(2).replace(" ", "").lower().lstrip("°")
        unit = UNIT_CANON.get(raw_unit, m.group(2).strip())
        out.append({"value": float(m.group(1)), "unit": unit,
                    "name": UNIT_TO_NAME.get(unit, "reading"), "text": m.group(0).strip(),
                    "source": "technician_statement"})
    return out
