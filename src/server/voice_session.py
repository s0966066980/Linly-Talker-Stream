"""One WebRTC microphone session and its server-owned conversation turns.

The class deliberately exposes only audio/control input and an event sink.  VAD
buffers, turn identity, stale-result protection and STT -> LLM -> TTS ordering
remain private so routes and UI cannot accidentally create competing pipelines.
"""
from __future__ import annotations

import asyncio
import json
from io import BytesIO
from typing import Callable, Optional
from uuid import uuid4

import numpy as np
import soundfile as sf
from av.audio.resampler import AudioResampler

from src.asr.factory import get_asr_engine
from src.llm.service import llm_response
from src.utils.logging import logger
from src.vad.service import create_segmenter


EventSink = Callable[[str], None]


class VoiceTurnSession:
    """Own the complete lifetime of hands-free turns for one peer connection."""

    def __init__(self, sessionid: int, config, avatar) -> None:
        self.sessionid = sessionid
        self.config = config
        self.avatar = avatar
        self._event_sink: Optional[EventSink] = None
        self._sequence = 0
        self._turn_id: Optional[str] = None
        self._generation = 0
        self._capture_requested = True
        self._gate_open = False
        self._manual_pause = False
        self._closed = False
        self._prepare_error = ""
        self._segmenter = None
        self._asr = None
        self._track_task: Optional[asyncio.Task] = None
        self._turn_task: Optional[asyncio.Task] = None
        self._tail_task: Optional[asyncio.Task] = None
        self._output_active = False
        self._silent_output_frames = 0
        self._resampler = AudioResampler(format="s16", layout="mono", rate=16000)

    async def prepare(self) -> None:
        """Prewarm Silero and STT before the session may announce listening."""
        self._emit("state", state="preparing")
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._prepare_sync)
        except Exception as exc:
            self._prepare_error = str(exc)
            self._gate_open = False
            logger.exception("Voice session prewarm failed")
            self._emit("state", state="degraded", error=self._prepare_error)
            return
        self._refresh_gate()

    def _prepare_sync(self) -> None:
        self.config.asr.mode = "server"
        self.config.vad.type = "silero"
        self._segmenter = create_segmenter(self.config.vad, self.config)
        self._segmenter.vad.ensure_ready()
        self._asr = get_asr_engine(
            self.config.asr.type,
            model_size=self.config.asr.model_size,
            config=self.config,
        )
        self._asr.set_language(self.config.asr.language)
        self._asr.ensure_ready()

    def attach_event_sink(self, sink: EventSink) -> None:
        self._event_sink = sink
        if self._prepare_error:
            self._emit("state", state="degraded", error=self._prepare_error)
        else:
            self._refresh_gate()

    def detach_event_sink(self) -> None:
        self._event_sink = None
        self._close_gate()

    def handle_control(self, raw_message: str) -> None:
        try:
            message = json.loads(raw_message)
        except (TypeError, json.JSONDecodeError):
            return
        kind = message.get("type")
        if kind == "capture":
            enabled = bool(message.get("enabled"))
            if not enabled and bool(message.get("finalize")) and self._segmenter is not None:
                segments = list(self._segmenter.flush())
                if segments and self._gate_open:
                    self._close_gate()
                    if self._turn_id is None:
                        self._turn_id = uuid4().hex
                    generation = self._generation
                    segment = segments[0]
                    self._turn_task = asyncio.create_task(
                        self._process_turn(
                            segment.audio,
                            segment.sample_rate,
                            self._turn_id,
                            generation,
                        )
                    )
            self._capture_requested = enabled
            self._manual_pause = not enabled
            if enabled and self._output_active:
                return
            self._refresh_gate()
        elif kind == "interrupt":
            asyncio.create_task(self.interrupt())

    def start_track(self, track) -> None:
        if self._track_task:
            self._track_task.cancel()
        self._track_task = asyncio.create_task(self._consume_track(track))

    async def _consume_track(self, track) -> None:
        try:
            while not self._closed:
                frame = await track.recv()
                for converted in self._resampler.resample(frame):
                    pcm = converted.to_ndarray().reshape(-1).astype(np.int16, copy=False)
                    await self.feed_pcm(pcm)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                logger.warning(f"Microphone track ended: {exc}")
                self._emit("state", state="reconnecting", error="microphone_track_lost")
                self._close_gate()

    async def feed_pcm(self, pcm: np.ndarray) -> None:
        """Feed mono 16 kHz int16 PCM; intentionally a small testable seam."""
        if not self._gate_open or self._closed or self._segmenter is None:
            return
        was_speaking = self._segmenter.is_speaking
        segments = list(self._segmenter.process(pcm))
        if not was_speaking and self._segmenter.is_speaking:
            self._turn_id = uuid4().hex
            self._emit("state", state="speech_detected")
        if not segments:
            return
        # max_speech_ms and normal endpointing both finalize exactly one turn.
        self._close_gate()
        segment = segments[0]
        if self._turn_id is None:
            self._turn_id = uuid4().hex
        generation = self._generation
        self._turn_task = asyncio.create_task(
            self._process_turn(segment.audio, segment.sample_rate, self._turn_id, generation)
        )

    async def _process_turn(
        self, audio: np.ndarray, sample_rate: int, turn_id: str, generation: int
    ) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._emit("state", state="stt", turn_id=turn_id)
            wav = BytesIO()
            sf.write(wav, audio, sample_rate, format="WAV", subtype="PCM_16")
            result = await loop.run_in_executor(None, self._asr.transcribe, wav.getvalue())
            if not self._is_current(turn_id, generation):
                return
            text = str(result.get("text", "")).strip()
            if not text:
                self._turn_id = None
                self._refresh_gate()
                return
            self._emit("user_transcript", text=text, turn_id=turn_id)
            self._emit("state", state="llm", turn_id=turn_id)
            response = await loop.run_in_executor(
                None,
                lambda: llm_response(text, self.avatar, stream_to_avatar=False),
            )
            if not self._is_current(turn_id, generation):
                return
            response = str(response).strip()
            self._emit("assistant_text", text=response, turn_id=turn_id)
            self._emit("state", state="tts_ready", turn_id=turn_id)
            if not response:
                self._turn_id = None
                self._turn_task = None
                self._refresh_gate()
                return
            self.avatar.put_msg_txt(response, {"turn_id": turn_id})
            self._turn_task = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_current(turn_id, generation):
                logger.exception("Voice turn failed")
                self._emit("state", state="error", error=str(exc), turn_id=turn_id)
                self._turn_id = None
                self._turn_task = None
                self._refresh_gate()

    def on_output_audio(self, active: bool) -> None:
        """Called from the outbound WebRTC audio track for frame-accurate gating."""
        if self._closed:
            return
        if active:
            self._silent_output_frames = 0
            if not self._output_active:
                self._output_active = True
                self._close_gate()
                self._emit("speaking_start", turn_id=self._turn_id)
                self._emit("state", state="avatar_speaking", turn_id=self._turn_id)
            return
        if not self._output_active:
            return
        is_still_rendering = getattr(self.avatar, "is_speaking", None)
        if callable(is_still_rendering) and is_still_rendering():
            self._silent_output_frames = 0
            return
        self._silent_output_frames += 1
        if self._silent_output_frames < 3:
            return
        self._output_active = False
        self._silent_output_frames = 0
        self._emit("speaking_end", turn_id=self._turn_id)
        if self._tail_task:
            self._tail_task.cancel()
        self._tail_task = asyncio.create_task(self._finish_tail_guard())

    async def _finish_tail_guard(self) -> None:
        self._emit("state", state="tail_guard", turn_id=self._turn_id)
        await asyncio.sleep(0.3)
        self._turn_id = None
        self._refresh_gate()

    async def interrupt(self) -> None:
        """Cancel the old turn, flush all queued speech, then reopen after a tail guard."""
        self._generation += 1
        self._close_gate()
        if self._turn_task:
            self._turn_task.cancel()
            self._turn_task = None
        if self._tail_task:
            self._tail_task.cancel()
        self.avatar.flush_talk()
        self._output_active = False
        self._emit("turn_cancelled", turn_id=self._turn_id)
        self._emit("state", state="tail_guard", turn_id=self._turn_id)
        await asyncio.sleep(0.3)
        self._turn_id = None
        self._manual_pause = False
        self._capture_requested = True
        self._refresh_gate()

    async def close(self) -> None:
        self._closed = True
        self._generation += 1
        self._close_gate()
        for task in (self._track_task, self._turn_task, self._tail_task):
            if task:
                task.cancel()
        self.avatar.flush_talk()
        self._event_sink = None

    def _is_current(self, turn_id: str, generation: int) -> bool:
        return (
            not self._closed
            and self._turn_id == turn_id
            and self._generation == generation
        )

    def _close_gate(self) -> None:
        self._gate_open = False
        if self._segmenter is not None:
            self._segmenter.reset()

    def _refresh_gate(self) -> None:
        allowed = (
            not self._closed
            and not self._prepare_error
            and self._event_sink is not None
            and self._capture_requested
            and not self._manual_pause
            and not self._output_active
            and self._turn_task is None
            and self._turn_id is None
        )
        self._gate_open = allowed
        if self._segmenter is not None:
            self._segmenter.reset()
        self._emit("state", state="listening" if allowed else "paused")

    def _emit(self, event_type: str, *, turn_id: Optional[str] = None, **payload) -> None:
        if self._event_sink is None:
            return
        self._sequence += 1
        event = {
            "type": event_type,
            "seq": self._sequence,
            "turn_id": turn_id if turn_id is not None else self._turn_id,
            **payload,
        }
        try:
            self._event_sink(json.dumps(event, ensure_ascii=False))
        except Exception as exc:
            logger.warning(f"Voice event channel failed closed: {exc}")
            self._event_sink = None
            self._close_gate()
