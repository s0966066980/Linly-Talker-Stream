from __future__ import annotations

import time
from pathlib import Path
from typing import Iterator

import numpy as np
import requests
import resampy

from src.tts.base import BaseTTS, State
from src.tts.cosyvoice_runtime import (
    DEFAULT_PROMPT_TEXT,
    DEFAULT_PROMPT_WAV,
    build_instruct,
    cosyvoice_family,
    parse_server_url,
    prepare_prompt_wav,
    resolve_prompt_source,
    server_url,
)
from src.utils.logging import logger


class CosyVoiceTTS(BaseTTS):
    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        started_at = time.perf_counter()
        try:
            emitted = self.stream_tts(
                self.cosy_voice(
                    text,
                    self._prompt_wav(),
                    self._prompt_text(),
                    self._server_url(),
                ),
                msg,
            )
            if not emitted:
                raise RuntimeError("CosyVoice returned no decodable audio")
        except Exception:
            logger.exception("cosyvoice")
            self.notify_fragment_synthesis_failed(
                textevent,
                "tts_exhausted_before_audio",
            )
            raise

    def _server_url(self) -> str:
        configured = str(getattr(self.config.tts, "tts_server", "") or "").strip()
        if configured:
            host, port = parse_server_url(configured)
            return server_url(host, port)
        return server_url()

    def _prompt_wav(self) -> str:
        configured = str(getattr(self.config.tts, "ref_file", "") or "").strip()
        source = configured or str(DEFAULT_PROMPT_WAV)
        try:
            return str(prepare_prompt_wav(resolve_prompt_source(source)))
        except FileNotFoundError:
            if DEFAULT_PROMPT_WAV.is_file():
                return str(DEFAULT_PROMPT_WAV)
            raise

    def _prompt_text(self) -> str:
        configured = str(getattr(self.config.tts, "ref_text", "") or "").strip()
        if configured:
            return configured
        wav = str(getattr(self.config.tts, "ref_file", "") or "")
        if Path(wav).name.startswith("cosyvoice_prompt"):
            return DEFAULT_PROMPT_TEXT
        return ""

    def _family(self) -> str:
        return cosyvoice_family(getattr(self.config.tts, "type", "cosyvoice"))

    def _tts_request(self, text: str, prompt_text: str = "") -> tuple[str, dict]:
        family = self._family()
        instruct = build_instruct(
            getattr(self.config.tts, "language", "zh"),
            getattr(self.config.tts, "instruct", "") or "",
            family=family,
        )
        if instruct:
            return "inference_instruct2", {
                "tts_text": text,
                "instruct_text": instruct,
            }
        cleaned = (prompt_text or "").strip()
        if cleaned:
            if family == "cosyvoice3" and "<|endofprompt|>" not in cleaned:
                cleaned = f"You are a helpful assistant.<|endofprompt|>{cleaned}"
            return "inference_zero_shot", {
                "tts_text": text,
                "prompt_text": cleaned,
            }
        return "inference_cross_lingual", {"tts_text": text}

    def cosy_voice(
        self,
        text: str,
        reffile: str,
        reftext: str,
        server_url: str,
    ) -> Iterator[bytes]:
        started_at = time.perf_counter()
        endpoint, payload = self._tts_request(text, reftext)
        with Path(reffile).open("rb") as prompt:
            response = requests.post(
                f"{server_url.rstrip('/')}/{endpoint}",
                data=payload,
                files={
                    "prompt_wav": ("prompt.wav", prompt, "application/octet-stream"),
                },
                stream=True,
                timeout=(5, 60),
            )
        if response.status_code != 200:
            raise RuntimeError(
                f"CosyVoice HTTP {response.status_code}: {response.text[:300]}"
            )
        first = True
        for chunk in response.iter_content(chunk_size=9600):
            if not chunk or self.state != State.RUNNING:
                continue
            if first:
                logger.info(
                    "cosy_voice first audio:%.4fs",
                    time.perf_counter() - started_at,
                )
                first = False
                mark_stage = getattr(self.parent, "mark_stage_end", None)
                if callable(mark_stage):
                    mark_stage("tts_first_encoded")
                    mark_stage("tts_first_pcm")
            yield chunk

    def stream_tts(self, audio_stream, msg: tuple[str, dict]) -> bool:
        text, textevent = msg
        remainder = np.empty(0, dtype=np.float32)
        media_sequence = 0
        emitted = False
        turn_aware = {"turn_id", "generation", "fragment_sequence"}.issubset(
            textevent or {}
        )
        for chunk in audio_stream:
            if not chunk:
                continue
            stream = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32767.0
            stream = resampy.resample(x=stream, sr_orig=24000, sr_new=self.sample_rate)
            remainder = np.concatenate((remainder, stream))
            while remainder.size >= self.chunk and self.state == State.RUNNING:
                frame = remainder[: self.chunk].copy()
                remainder = remainder[self.chunk :]
                self._emit_frame(
                    frame,
                    text,
                    textevent,
                    media_sequence=media_sequence,
                    start=not emitted,
                    final=False,
                    turn_aware=turn_aware,
                )
                emitted = True
                media_sequence += 1
        if remainder.size and self.state == State.RUNNING:
            padded = np.pad(remainder, (0, self.chunk - remainder.size))
            self._emit_frame(
                padded.astype(np.float32, copy=False),
                text,
                textevent,
                media_sequence=media_sequence,
                start=not emitted,
                final=True,
                turn_aware=turn_aware,
            )
            emitted = True
        elif emitted and self.state == State.RUNNING:
            self._emit_frame(
                np.zeros(self.chunk, np.float32),
                text,
                textevent,
                media_sequence=media_sequence,
                start=False,
                final=True,
                turn_aware=turn_aware,
            )
        return emitted

    def _emit_frame(
        self,
        samples: np.ndarray,
        text: str,
        textevent: dict,
        *,
        media_sequence: int,
        start: bool,
        final: bool,
        turn_aware: bool,
    ) -> None:
        eventpoint: dict = dict(textevent or {})
        if turn_aware:
            eventpoint["media_sequence"] = media_sequence
            eventpoint["fragment_start"] = start
            eventpoint["fragment_end"] = final
        if start:
            eventpoint.update({"status": "start", "text": text})
        elif final:
            eventpoint.update({"status": "end", "text": text})
        self.parent.put_audio_frame(samples, eventpoint)
