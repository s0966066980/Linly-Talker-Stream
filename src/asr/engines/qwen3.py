"""Local Qwen3-ASR adapter for the server-owned voice pipeline."""

from __future__ import annotations

from typing import Any, Dict

from src.asr.base import BaseASR
from src.speech.qwen_process import QwenWorkerClient
from src.utils.logging import logger


LANGUAGE_NAMES = {
    "zh": "Chinese",
    "en": "English",
    "auto": None,
}

RESULT_LANGUAGE_CODES = {
    "chinese": "zh",
    "zh": "zh",
    "english": "en",
    "en": "en",
}


class Qwen3ASR(BaseASR):
    """Run the official ``qwen-asr`` transformers backend in-process."""

    def __init__(self, config=None, model_size: str = "Qwen/Qwen3-ASR-0.6B"):
        super().__init__(config)
        self.model_name = model_size
        configured = getattr(getattr(config, "asr", None), "device", "auto")
        self.device = self._resolve_device(configured)
        self.worker = None

    @staticmethod
    def _resolve_device(configured: str) -> str:
        if configured != "auto":
            return configured
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_model(self) -> None:
        logger.info(f"[Qwen3-ASR] 正在隔離環境載入 {self.model_name} ({self.device})")
        self.worker = QwenWorkerClient()
        try:
            self.worker.start(
                kind="asr",
                model=self.model_name,
                device=self.device,
            )
        except Exception:
            self.worker.close()
            self.worker = None
            raise
        logger.info("[Qwen3-ASR] 模型載入成功")

    def _transcribe(self, audio_path: str) -> Dict[str, Any]:
        language = LANGUAGE_NAMES.get(self.language, self.language)
        result = self.worker.request(
            "transcribe",
            audio=audio_path,
            language=language,
        )
        detected = str(result.get("language") or self.language).strip().lower()
        return {
            "text": str(result.get("text", "")).strip(),
            "language": RESULT_LANGUAGE_CODES.get(detected, detected or self.language),
        }

    def get_info(self) -> Dict[str, Any]:
        info = super().get_info()
        info.update({"model_name": self.model_name, "device": self.device})
        return info
