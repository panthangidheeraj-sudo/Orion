"""ONNX Runtime / QNN plumbing and on-disk asset discovery.

§5 of the specification: on Windows the documented target runtime is ONNX
Runtime, which reaches the Snapdragon NPU through the QNN execution provider.
This module is the single place that talks to onnxruntime, and the single
place allowed to decide whether the NPU is in play.

The decision is made from what onnxruntime *reports after a session is built*,
never from what was requested.  ``session.get_providers()`` is the ground
truth; if QNN was asked for and is not in that list, the session is running on
CPU and every status surface says so.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.config import settings
from app.logging_setup import get_logger
from app.util import ms

log = get_logger(__name__)

NPU_PROVIDERS = {"QNNExecutionProvider"}
GPU_PROVIDERS = {"DmlExecutionProvider", "CUDAExecutionProvider", "ROCMExecutionProvider"}


@dataclass
class RuntimeInfo:
    onnxruntime_available: bool = False
    onnxruntime_version: Optional[str] = None
    available_providers: List[str] = field(default_factory=list)
    qnn_available: bool = False
    machine: str = platform.machine()
    system: str = platform.system()
    python: str = platform.python_version()
    note: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "onnxruntime_available": self.onnxruntime_available,
            "onnxruntime_version": self.onnxruntime_version,
            "available_providers": self.available_providers,
            "qnn_execution_provider_available": self.qnn_available,
            "host": {"system": self.system, "machine": self.machine, "python": self.python},
            "note": self.note,
        }


_info: Optional[RuntimeInfo] = None


def runtime_info(refresh: bool = False) -> RuntimeInfo:
    global _info
    if _info is not None and not refresh:
        return _info
    info = RuntimeInfo()
    try:
        import onnxruntime as ort  # type: ignore

        info.onnxruntime_available = True
        info.onnxruntime_version = getattr(ort, "__version__", None)
        info.available_providers = list(ort.get_available_providers())
        info.qnn_available = "QNNExecutionProvider" in info.available_providers
        if not info.qnn_available:
            info.note = (
                "QNNExecutionProvider is not in this onnxruntime build; models "
                "will run on CPU. Install onnxruntime-qnn on a Snapdragon host."
            )
    except Exception as exc:
        info.note = f"onnxruntime not importable: {type(exc).__name__}: {exc}"
    _info = info
    return info


def _provider_list() -> Tuple[List[str], List[dict]]:
    """Requested providers, filtered to the ones this build actually has."""
    info = runtime_info()
    wanted = [p for p in settings.onnx_execution_providers if p in info.available_providers]
    if "CPUExecutionProvider" not in wanted and "CPUExecutionProvider" in info.available_providers:
        wanted.append("CPUExecutionProvider")
    options: List[dict] = []
    for p in wanted:
        if p == "QNNExecutionProvider":
            options.append({"backend_path": settings.qnn_backend_path})
        else:
            options.append({})
    return wanted, options


@dataclass
class LoadedSession:
    session: Any
    providers: List[str]
    accelerator: str
    npu: bool
    load_ms: float
    path: str
    input_names: List[str]
    output_names: List[str]


def load_onnx_session(model_path: Path) -> LoadedSession:
    """Build an InferenceSession and report the accelerator it truly received.

    Raises if onnxruntime is missing or the file is not there; callers turn
    that into the §25 ``MODEL_UNAVAILABLE`` envelope.
    """
    import onnxruntime as ort  # type: ignore

    if not model_path.exists():
        raise FileNotFoundError(f"model asset missing: {model_path.name}")

    providers, provider_options = _provider_list()
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3

    t0 = ms()
    try:
        sess = ort.InferenceSession(
            str(model_path), sess_options=so,
            providers=providers or None, provider_options=provider_options or None,
        )
    except Exception as exc:
        # A QNN failure must degrade to CPU loudly, not silently claim the NPU.
        if "QNNExecutionProvider" in providers:
            log.warning("QNN session failed for %s (%s); retrying on CPU", model_path.name, exc)
            sess = ort.InferenceSession(
                str(model_path), sess_options=so, providers=["CPUExecutionProvider"]
            )
        else:
            raise
    load_ms = round(ms() - t0, 2)

    actual = list(sess.get_providers())
    npu = bool(NPU_PROVIDERS & set(actual))
    if npu:
        accelerator = "npu"
    elif GPU_PROVIDERS & set(actual):
        accelerator = "gpu"
    else:
        accelerator = "cpu"

    return LoadedSession(
        session=sess,
        providers=actual,
        accelerator=accelerator,
        npu=npu,
        load_ms=load_ms,
        path=str(model_path),
        input_names=[i.name for i in sess.get_inputs()],
        output_names=[o.name for o in sess.get_outputs()],
    )


# ----------------------------------------------------------- asset discovery

ASSET_SUFFIXES = (".onnx", ".ort", ".bin", ".tflite", ".dlc", ".so", ".gguf")


def model_dir(model_id: str) -> Path:
    return settings.models_dir / model_id


def find_asset(model_id: str, *names: str) -> Optional[Path]:
    """Locate a deployable asset for ``model_id`` under ``data/models/``.

    The layout mirrors what ``qai-hub-models fetch`` / ``export`` drops:

        data/models/<model_id>/<file>

    Nothing is downloaded here.  If the directory is empty the adapter reports
    ``unavailable`` and the pipeline degrades per §25.
    """
    root = model_dir(model_id)
    if not root.exists():
        return None
    for n in names:
        p = root / n
        if p.exists():
            return p
    for suffix in ASSET_SUFFIXES:
        hits = sorted(root.rglob(f"*{suffix}"))
        if hits:
            return hits[0]
    return None


def asset_inventory() -> Dict[str, Any]:
    """What is actually present on disk, for /api/models/status."""
    root = settings.models_dir
    out: Dict[str, Any] = {"models_dir": str(root), "entries": []}
    if not root.exists():
        return out
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        files = [f for f in sorted(child.rglob("*")) if f.is_file()]
        out["entries"].append({
            "model_id": child.name,
            "files": len(files),
            "bytes": sum(f.stat().st_size for f in files),
            "sample": [f.name for f in files[:5]],
        })
    return out
