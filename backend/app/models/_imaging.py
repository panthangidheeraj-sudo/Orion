"""Image helpers shared by the vision adapters (private to app.models)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
from PIL import Image

from app.models.base import ImageRef


def open_image(ref: ImageRef) -> Image.Image:
    img = Image.open(ref.path)
    img.load()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    elif img.mode == "L":
        img = img.convert("RGB")
    return img


def letterbox(img: Image.Image, size: int = 640) -> Tuple[np.ndarray, float, int, int]:
    """Resize preserving aspect, pad to a square, return CHW float32 in [0,1]."""
    w, h = img.size
    scale = min(size / w, size / h)
    nw, nh = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = img.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    dx, dy = (size - nw) // 2, (size - nh) // 2
    canvas.paste(resized, (dx, dy))
    arr = np.asarray(canvas, dtype=np.float32) / 255.0
    return np.transpose(arr, (2, 0, 1))[None, ...], scale, dx, dy


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float = 0.45) -> List[int]:
    """Plain greedy non-maximum suppression on [x1,y1,x2,y2] boxes."""
    if boxes.size == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.maximum(0.0, x2 - x1) * np.maximum(0.0, y2 - y1)
    order = scores.argsort()[::-1]
    keep: List[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
        iou = inter / np.maximum(1e-9, areas[i] + areas[rest] - inter)
        order = rest[iou <= iou_threshold]
    return keep


def scene_signature(ref: ImageRef, grid: int = 12) -> List[float]:
    """A small fingerprint of *what is in frame*, not how bright it is.

    Live mode uses this per frame to decide whether the scene changed enough to
    be worth waking a sense (§8), so it has to survive a technician moving in a
    workshop: auto-exposure shifts, a lamp coming on, a hand passing the lens.

    A raw grayscale grid does not. Two completely different scenes that happen
    to share an average brightness — a dark motor and a dark control panel —
    come out nearly identical, and the detector never wakes.

    So the signature is built from two standardised grids:

      * luma, z-scored, which removes global brightness and contrast and leaves
        the *pattern* of light and dark;
      * edge density, z-scored, which describes where the structure is.

    Both are invariant to exposure, and together they move when the subject
    moves rather than when the lighting does.
    """
    img = open_image(ref).convert("L")
    small = np.asarray(img.resize((grid * 4, grid * 4), Image.BILINEAR),
                       dtype=np.float32) / 255.0

    gy, gx = np.gradient(small)
    edges = np.sqrt(gx * gx + gy * gy)

    def _cells(a: np.ndarray) -> np.ndarray:
        # Average each 4x4 block down to one cell.
        return a.reshape(grid, 4, grid, 4).mean(axis=(1, 3))

    def _standardise(a: np.ndarray) -> np.ndarray:
        flat = _cells(a).flatten()
        std = float(flat.std())
        if std < 1e-4:                      # a flat frame carries no structure
            return np.zeros_like(flat)
        return (flat - float(flat.mean())) / std

    return [round(float(v), 4) for v in
            np.concatenate([_standardise(small), _standardise(edges)])]


def signature_distance(a: List[float], b: List[float]) -> float:
    """0 for the same scene, ~1 for an unrelated one.

    Cosine distance over the standardised signature, halved into 0..1 and
    clamped, so the configured threshold means the same thing whatever the
    grid size.
    """
    if not a or not b or len(a) != len(b):
        return 1.0
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na < 1e-6 or nb < 1e-6:
        return 0.0 if na == nb else 1.0
    cosine = float(np.dot(va, vb) / (na * nb))
    return round(min(1.0, max(0.0, (1.0 - cosine) / 2.0)), 4)


def image_stats(ref: ImageRef) -> Dict[str, Any]:
    """Facts an adapter-free pipeline can still state truthfully about a frame."""
    img = open_image(ref)
    g = np.asarray(img.convert("L"), dtype=np.float32) / 255.0
    gy, gx = np.gradient(g)
    edge = float(np.sqrt(gx * gx + gy * gy).mean())
    return {
        "width": img.width,
        "height": img.height,
        "mean_luma": round(float(g.mean()), 4),
        "contrast": round(float(g.std()), 4),
        "edge_density": round(edge, 4),
        "underexposed": bool(g.mean() < 0.16),
        "overexposed": bool(g.mean() > 0.88),
        "likely_blurred": bool(edge < 0.012),
    }


def save_bytes_as_image(data: bytes, dest: Path) -> Tuple[int, int, str]:
    """Validate that bytes really are an image before anything touches them.

    §24: uploaded files are never executed.  Pillow decodes and re-encodes, so
    what lands on disk is a picture and nothing else.
    """
    from io import BytesIO

    with Image.open(BytesIO(data)) as probe:
        probe.verify()
    with Image.open(BytesIO(data)) as img:
        img = img.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="JPEG", quality=90)
        return img.width, img.height, "image/jpeg"
