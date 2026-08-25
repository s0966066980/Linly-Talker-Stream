"""In-process Qwen3-TTS adapter using the official ``qwen-tts`` package."""

from __future__ import annotations

import os
import tempfile

import numpy as np
import resampy
import soundfile as sf

from src.speech.qwen_process import QwenWorkerClient
from src.tts.base import BaseTTS, State
from src.utils.logging import logger


_WORKER_CACHE = {}


def release_qwen_tts_workers(keep=None) -> None:
    """Release isolated model processes except an optional active cache key."""
    for key, worker in list(_WORKER_CACHE.items()):
        if key == keep:
            continue
        worker.close()
        _WORKER_CACHE.pop(key, None)


class Qwen3TTS(BaseTTS):
    """Support Qwen CustomVoice, Base voice clone, and VoiceDesign checkpoints."""

    def __init__(self, config, parent):
        super().__init__(config, parent)
        tts = config.tts
        self.model_name = tts.model
        self.language = tts.language or "Auto"
        self.speaker = tts.speaker or "Vivian"
        self.instruct = tts.instruct or ""
        self.device = self._resolve_device(tts.device)
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
        if self.worker is not None:
            return
        cache_key = (self.model_name, self.device)
        self.worker = _WORKER_CACHE.get(cache_key)
        if self.worker is None:
            logger.info(f"[Qwen3-TTS] 正在隔離環境載入 {self.model_name} ({self.device})")
            self.worker = QwenWorkerClient()
            try:
                self.worker.start(kind="tts", model=self.model_name, device=self.device)
            except Exception:
                self.worker.close()
                self.worker = None
                raise
            _WORKER_CACHE[cache_key] = self.worker
            logger.info("[Qwen3-TTS] 模型載入成功")

    def _generate(self, text: str):
        fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self.worker.request(
                "synthesize",
                model=self.model_name,
                text=text,
                language=self.language,
                speaker=self.speaker,
                instruct=self.instruct,
                ref_audio=self.config.tts.ref_file,
                ref_text=self.config.tts.ref_text or "",
                output=output_path,
            )
            return sf.read(output_path, dtype="float32")
        finally:
            try:
                os.unlink(output_path)
            except FileNotFoundError:
                pass

    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        self._load_model()
        stream, sample_rate = self._generate(text)
        if stream.size == 0:
            return
        stream = np.asarray(stream, dtype=np.float32).squeeze()
        if stream.ndim != 1:
            raise ValueError(f"Qwen3-TTS 返回了不支援的音訊形狀: {stream.shape}")
        if sample_rate != self.sample_rate and stream.size:
            stream = resampy.resample(stream, sample_rate, self.sample_rate)

        total_chunks = (stream.size + self.chunk - 1) // self.chunk
        emitted = False
        for index in range(total_chunks):
            if self.state != State.RUNNING:
                break
            frame = stream[index * self.chunk : (index + 1) * self.chunk]
            if frame.size < self.chunk:
                frame = np.pad(frame, (0, self.chunk - frame.size))
            event = dict(textevent)
            if index == 0:
                event.update({"status": "start", "text": text})
            self.parent.put_audio_frame(frame.astype(np.float32, copy=False), event)
            emitted = True
        if emitted:
            end_event = dict(textevent)
            end_event.update({"status": "end", "text": text})
            self.parent.put_audio_frame(np.zeros(self.chunk, dtype=np.float32), end_event)
