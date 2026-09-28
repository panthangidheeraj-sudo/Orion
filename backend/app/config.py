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

    # -------------------------------------------------------------- security
    # Shared access key. When set, every /api route except the public health
    # and model-status probes requires it in the `X-Orion-Key` header (or
    # `Authorization: Bearer <key>`). Leave empty only for a backend bound to
    # 127.0.0.1 — a backend reachable from the internet (Render, a LAN IP)
    # must set VF_ACCESS_TOKEN, or anyone can read and delete its data.
    access_token: str = ""
    # Per-client request budget, per minute. 0 turns a limit off. Live Mode
    # sends a frame about once a second, so this leaves it ample room.
    rate_limit_per_minute: int = 300
    # Tighter budget for the expensive routes: chat, uploads, photo analysis,
    # voice, direct tool calls, model reloads.
    heavy_rate_limit_per_minute: int = 30
    # Trust X-Forwarded-For for the client address. True behind a reverse
    # proxy such as Render's; set False when the port is exposed directly.
    trust_proxy_headers: bool = True
    # Interactive API docs (/docs, /redoc, /openapi.json). Hidden by default
    # once an access key is configured.
    expose_docs: bool = True

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

    # Qwen3-VL-4B-Instruct through Qualcomm GenieX + QAIRT on the Snapdragon
    # NPU (VF_REASONING_PROVIDER=geniex-qwen3-vl). See docs/SNAPDRAGON_SETUP.md.
    geniex_model: str = "ai-hub-models/Qwen3-VL-4B-Instruct"
    # Optional: load a bundle from this folder instead of the GenieX cache.
    geniex_model_path: str = ""
    # Optional AI Hub precision/quant tag; empty uses the bundle default.
    geniex_precision: str = ""
    # "qairt" forces the NPU plugin. Anything else is reported as what it is.
    geniex_device_map: str = "qairt"
    geniex_n_ctx: int = 0              # 0 = the bundle's context length
    geniex_max_new_tokens: int = 768
    geniex_max_images: int = 2
    # Run a short generation at load; the provider is only READY if it works.
    geniex_probe: bool = True
    # Optional QAIRT SDK root to use instead of the runtime bundled with GenieX.
    geniex_qairt_runtime_path: str = ""

    # Any other OpenAI-compatible model server on this machine
    # (VF_REASONING_PROVIDER=local-openai-compat). Loopback only, and off
    # unless a URL is set — nothing is probed by default.
    local_llm_url: str = ""
    local_llm_model: str = ""

    # ------------------------------------------------------------- knowledge
    chunk_target_chars: int = 900
    chunk_overlap_chars: int = 140
    retrieval_top_k: int = 6
    page_render_dpi: int = 144
    # Uploads are streamed and cut off at this size, so an oversized file is
    # refused before it is held in memory.
    max_upload_bytes: int = 50 * 1024 * 1024
    # Hard ceilings on what one untrusted file can make the server do.
    max_pdf_pages: int = 150
    max_image_pixels: int = 50_000_000

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
