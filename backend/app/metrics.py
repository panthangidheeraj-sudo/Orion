"""Runtime metrics (§23).

§23 lists thirteen figures to collect. This module holds the ones this process
can measure truthfully: latencies it timed itself, and host CPU and memory.

It does not hold the ones it cannot measure. NPU and GPU utilisation come from
Qualcomm's profiler on the device, and tokens/sec needs a real generative model
serving tokens. Those are reported as unavailable, with the reason, because a
plausible-looking number in a demo is exactly the fake Snapdragon claim §4
forbids.

Samples live in memory and reset when the service restarts. That is the right
lifetime for demo metrics, and the endpoint says so.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from app.logging_setup import get_logger

log = get_logger(__name__)
MAX_SAMPLES = 400


class Series:
    """A bounded sample window with the usual summary figures."""

    def __init__(self, unit: str = "ms") -> None:
        self.unit = unit
        self._values: Deque[float] = deque(maxlen=MAX_SAMPLES)
        self._lock = threading.Lock()

    def add(self, value: float) -> None:
        with self._lock:
            self._values.append(float(value))

    def summary(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            vals = sorted(self._values)
        if not vals:
            return None
        n = len(vals)
        return {
            "unit": self.unit,
            "samples": n,
            "min": round(vals[0], 2),
            "median": round(vals[n // 2], 2),
            "p95": round(vals[min(n - 1, int(n * 0.95))], 2),
            "max": round(vals[-1], 2),
            "mean": round(sum(vals) / n, 2),
        }


class Collector:
    def __init__(self) -> None:
        self.end_to_end = Series()
        self.first_token = Series()
        self.reasoning = Series()
        self.started_at = time.time()

    def record_response(self, ms: float) -> None:
        self.end_to_end.add(ms)

    def record_first_token(self, ms: float) -> None:
        self.first_token.add(ms)

    def record_reasoning(self, ms: float) -> None:
        self.reasoning.add(ms)

    # ------------------------------------------------------------------ host
    def host(self) -> Dict[str, Any]:
        """CPU and memory, measured if psutil is present, honest if not."""
        out: Dict[str, Any] = {"cpu_count": os.cpu_count()}
        try:
            import psutil  # type: ignore

            proc = psutil.Process()
            with proc.oneshot():
                mem = proc.memory_info()
                out["process_cpu_percent"] = round(proc.cpu_percent(interval=0.1), 1)
                out["process_rss_mb"] = round(mem.rss / 1e6, 1)
                peak = getattr(mem, "peak_wset", None)  # Windows
                if peak:
                    out["process_peak_memory_mb"] = round(peak / 1e6, 1)
            out["system_cpu_percent"] = round(psutil.cpu_percent(interval=None), 1)
            vm = psutil.virtual_memory()
            out["system_memory_used_percent"] = round(vm.percent, 1)
            out["system_memory_total_mb"] = round(vm.total / 1e6, 1)
            out["source"] = "psutil"
            return out
        except Exception:
            pass

        # Stdlib fallback: peak RSS on POSIX, nothing on Windows.
        try:
            import resource

            peak_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            out["process_peak_memory_mb"] = round(peak_kb / 1024, 1)
            out["source"] = "resource (POSIX)"
            out["note"] = "CPU utilisation needs psutil: pip install psutil"
        except Exception:
            out["source"] = None
            out["note"] = ("CPU and memory utilisation need psutil on this platform: "
                           "pip install psutil")
        return out

    def snapshot(self) -> Dict[str, Any]:
        return {
            "end_to_end_response_latency": self.end_to_end.summary(),
            "first_token_latency": self.first_token.summary(),
            "reasoning_latency": self.reasoning.summary(),
            "window": f"last {MAX_SAMPLES} samples, since this process started",
            "uptime_s": round(time.time() - self.started_at, 1),
        }


collector = Collector()
