"""Runtime configuration.

Every value can be overridden by an environment variable or a ``.env`` file
next to the ``backend/`` folder.  Nothing secret is ever written here: §24 of
the specification requires that API keys never live in source code, so the
only way a token reaches this process is the environment.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_prefix="VF_",
        extra="ignore",
    )

    # ---------------------------------------------------------------- server
    host: str = "127.0.0.1"
    port: int = 8756
    log_level: str = "INFO"
    # Requests are only accepted from the local front-end.  Local-first (§24)
    # means the service should not be reachable as a general web API.
    cors_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:1420",
            "tauri://localhost",
        ]
    )

    # ----------------------------------------------------------------- paths
    data_dir: Path = BACKEND_ROOT / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "database" / "visionfield.sqlite3"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    # ---------------------------------------------------------------- models
    # Adapter selection.  "auto" walks the candidate list and takes the first
    # provider whose asset is actually present on disk; it never pretends.
    reasoning_provider: str = "auto"
    detector_provider: str = "auto"
    classifier_provider: str = "auto"
    segmenter_provider: str = "auto"
    tracker_provider: str = "auto"
    ocr_provider: str = "auto"
    embedding_provider: str = "auto"
    stt_provider: str = "auto"
    tts_provider: str = "auto"

    reasoning_model_id: str = "qwen3_vl_2b_instruct"
    embedding_model_id: str = "nomic_embed_text"
    detector_model_id: str = "yolov11_det"
    classifier_model_id: str = "efficientnet_b4"
    segmenter_model_id: str = "yolov11_seg"
    tracker_model_id: str = "edgetam"
    ocr_model_id: str = "easyocr"
    stt_model_id: str = "whisper_base"
    tts_model_id: str = "pipertts_en"

    # ONNX Runtime execution providers, highest priority first.  QNN is the
    # Snapdragon NPU path on Windows; the loader verifies it is genuinely
    # available before using it and records what it actually got (§4).
    onnx_execution_providers: List[str] = Field(
        default_factory=lambda: ["QNNExecutionProvider", "CPUExecutionProvider"]
    )
    qnn_backend_path: str = "QnnHtp.dll"

    # Allow the deterministic offline reasoner when no real VLM asset exists.
    # It is reported as ``synthetic`` everywhere and never claims NPU use.
    allow_heuristic_reasoning: bool = True

    # ------------------------------------------------------------- knowledge
    chunk_target_chars: int = 900
    chunk_overlap_chars: int = 140
    retrieval_top_k: int = 6
    page_render_dpi: int = 144
    max_upload_bytes: int = 200 * 1024 * 1024

    # ------------------------------------------------------------------ live
    live_detect_interval_ms: int = 700
    live_ocr_interval_ms: int = 1800
    live_vlm_min_gap_ms: int = 2500
    live_scene_change_threshold: float = 0.28
    live_session_ttl_s: int = 1800

    # ------------------------------------------------------------------- web
    # Off unless the technician turns it on.  §16: web search is an optional
    # online tool, never the default knowledge path.
    web_search_enabled: bool = False
    web_search_provider: str = "none"
    web_search_endpoint: str = ""
    web_search_api_key: str = ""
    web_search_max_results: int = 5

    # ---------------------------------------------------------------- agent
    agent_max_tool_rounds: int = 4
    agent_tool_timeout_s: float = 20.0

    @field_validator("data_dir", mode="before")
    @classmethod
    def _expand(cls, v):
        return Path(os.path.expanduser(str(v))).resolve()

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir / "database",
            self.documents_dir,
            self.images_dir,
            self.audio_dir,
            self.reports_dir,
            self.models_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


settings = get_settings()
