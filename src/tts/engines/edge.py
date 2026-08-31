from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Callable, Optional

import av
import edge_tts
import numpy as np

from src.tts.base import BaseTTS, State
from src.server.reply_streaming.channel import PlayableFragment
from src.server.reply_streaming.retry import RetryBudget
from src.utils.logging import logger


# Keep the first retry budget bounded so a transient websocket stall does not
# consume the entire first-audio SLO before the fallback attempt starts.
EDGE_STREAM_TIMEOUT_SECONDS = 1.5
EDGE_MAX_ATTEMPTS = 2
ACTIVITY_THRESHOLD = 1e-4
ONSET_THRESHOLD = 1e-5
FRAME_SECONDS = 0.01
MAX_PREROLL_SECONDS = 0.16
SILENCE_GUARD_SECONDS = 0.04
TRAILING_PAUSE_SECONDS = 0.12


def trim_edge_silence(
    stream: np.ndarray,
    sample_rate: int,
    threshold: float = ACTIVITY_THRESHOLD,
    leading_pause_seconds: float = SILENCE_GUARD_SECONDS,
    trailing_pause_seconds: float = TRAILING_PAUSE_SECONDS,
    *,
    activity_threshold: Optional[float] = None,
    onset_threshold: float = ONSET_THRESHOLD,
    max_preroll_seconds: float = MAX_PREROLL_SECONDS,
    silence_guard_seconds: Optional[float] = None,
) -> np.ndarray:
    """移除 Edge TTS 供應商 padding，同時保留低能量語音起音與自然停頓。"""
    if stream.size == 0:
        return stream

    trimmer = _StreamingSilenceTrimmer(
        sample_rate,
        threshold=threshold,
        leading_pause_seconds=leading_pause_seconds,
        trailing_pause_seconds=trailing_pause_seconds,
        activity_threshold=activity_threshold,
        onset_threshold=onset_threshold,
        max_preroll_seconds=max_preroll_seconds,
        silence_guard_seconds=silence_guard_seconds,
    )
    trimmed = np.concatenate((trimmer.feed(stream), trimmer.finish()))
    if trimmed.size == 0 and not trimmer.started:
        return stream
    return trimmed


class _StreamingSilenceTrimmer:
    """Incremental equivalent of trim_edge_silence with a buffered tail."""

    def __init__(
        self,
        sample_rate: int,
        threshold: float = ACTIVITY_THRESHOLD,
        leading_pause_seconds: float = SILENCE_GUARD_SECONDS,
        trailing_pause_seconds: float = TRAILING_PAUSE_SECONDS,
        activity_threshold: Optional[float] = None,
        onset_threshold: float = ONSET_THRESHOLD,
        max_preroll_seconds: float = MAX_PREROLL_SECONDS,
        silence_guard_seconds: Optional[float] = None,
    ):
        self.frame_size = max(1, int(sample_rate * FRAME_SECONDS))
        self.activity_threshold = (
            float(threshold) if activity_threshold is None else float(activity_threshold)
        )
        self.onset_threshold = float(onset_threshold)
        guard_seconds = (
            leading_pause_seconds
            if silence_guard_seconds is None
            else silence_guard_seconds
        )
        self.silence_guard_frames = max(0, round(guard_seconds / FRAME_SECONDS))
        self.max_preroll_frames = max(1, round(max_preroll_seconds / FRAME_SECONDS))
        self.trailing_frames = max(0, round(trailing_pause_seconds / FRAME_SECONDS))
        self._remainder = np.empty(0, dtype=np.float32)
        self._preroll: deque[np.ndarray] = deque()
        self._trailing = []
        self._started = False
        self.retained_preroll_samples = 0

    @property
    def started(self) -> bool:
        return self._started

    @property
    def threshold(self) -> float:
        return self.activity_threshold

    def _frame_rms(self, block: np.ndarray) -> float:
        return float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))

    def _trim_preroll(self) -> None:
        while len(self._preroll) > self.max_preroll_frames:
            self._preroll.popleft()
        leading_padding = 0
        for frame in self._preroll:
            if self._frame_rms(frame) <= self.onset_threshold:
                leading_padding += 1
            else:
                break
        drop = max(0, leading_padding - self.silence_guard_frames)
        for _ in range(drop):
            self._preroll.popleft()

    def _flush_preroll(self) -> list[np.ndarray]:
        output = list(self._preroll)
        self.retained_preroll_samples = sum(frame.size for frame in output)
        self._preroll.clear()
        return output

    def _process_block(self, block: np.ndarray) -> list[np.ndarray]:
        rms = self._frame_rms(block)
        output = []
        if not self._started:
            if rms > self.activity_threshold:
                self._started = True
                output.extend(self._flush_preroll())
                output.append(block)
            else:
                self._preroll.append(block)
                self._trim_preroll()
            return output

        if rms > self.activity_threshold:
            output.extend(self._trailing)
            self._trailing.clear()
            output.append(block)
        else:
            self._trailing.append(block)
        return output

    def feed(self, samples: np.ndarray) -> np.ndarray:
        samples = np.asarray(samples, dtype=np.float32).reshape(-1)
        if self._remainder.size:
            samples = np.concatenate((self._remainder, samples))
        complete = (samples.size // self.frame_size) * self.frame_size
        self._remainder = samples[complete:].copy()
        output = []
        for offset in range(0, complete, self.frame_size):
            output.extend(self._process_block(samples[offset : offset + self.frame_size]))
        return (
            np.concatenate(output)
            if output
            else np.empty(0, dtype=np.float32)
        )

    def finish(self) -> np.ndarray:
        output = []
        partial_block = None
        partial_size = 0
        if self._remainder.size:
            partial_size = self._remainder.size
            partial_block = np.pad(
                self._remainder,
                (0, self.frame_size - self._remainder.size),
            )
            output.extend(self._process_block(partial_block))
            self._remainder = np.empty(0, dtype=np.float32)
        if self._started:
            output.extend(self._trailing[: self.trailing_frames])
        self._trailing.clear()
        if partial_block is not None:
            output = [
                item[:partial_size] if item is partial_block else item
                for item in output
            ]
        return (
            np.concatenate(output)
            if output
            else np.empty(0, dtype=np.float32)
        )


class _EdgePCMEmitter:
    """Decode MP3 incrementally and release complete 20ms PCM frames."""

    def __init__(
        self,
        owner: "EdgeTTS",
        text: str,
        textevent: dict,
        *,
        start_event_sent: bool = False,
        start_media_sequence: int = 0,
        chunk_guard: Optional[Callable[[int], bool]] = None,
    ):
        self.owner = owner
        self.text = text
        self.textevent = textevent
        self.decoder = av.CodecContext.create("mp3", "r")
        self.resampler = av.AudioResampler(
            format="s16",
            layout="mono",
            rate=owner.sample_rate,
        )
        self.trimmer = _StreamingSilenceTrimmer(owner.sample_rate)
        self.samples = np.empty(0, dtype=np.float32)
        self.pending_chunk = None
        self.emitted_chunks = 0
        self.emitted_samples = 0
        self.start_event_sent = start_event_sent
        self.media_sequence = start_media_sequence
        self.chunk_guard = chunk_guard
        self.cancelled = False

    @property
    def emitted(self) -> bool:
        return self.emitted_chunks > 0

    def _emit(self, samples: np.ndarray, *, final: bool = False) -> None:
        if self.owner.state != State.RUNNING:
            return
        if self.chunk_guard is not None and not self.chunk_guard(self.media_sequence):
            self.cancelled = True
            return
        turn_aware = {
            "turn_id",
            "generation",
            "fragment_sequence",
        }.issubset(self.textevent)
        eventpoint = dict(self.textevent) if turn_aware else {}
        if turn_aware:
            eventpoint["media_sequence"] = self.media_sequence
            eventpoint["fragment_start"] = not self.start_event_sent
            eventpoint["fragment_end"] = final
        if not self.start_event_sent:
            eventpoint.update({"status": "start"})
            if not turn_aware:
                eventpoint.update({"text": self.text, **self.textevent})
            self.start_event_sent = True
        elif final:
            eventpoint.update({"status": "end"})
            if not turn_aware:
                eventpoint.update({"text": self.text, **self.textevent})
        self.owner.parent.put_audio_frame(samples, eventpoint)
        if self.emitted_chunks == 0:
            mark_stage = getattr(self.owner.parent, "mark_stage_end", None)
            if callable(mark_stage) and self.textevent.get("turn_id"):
                mark_stage("tts_first_pcm")
        self.emitted_chunks += 1
        self.emitted_samples += samples.size
        self.media_sequence += 1

    def _queue_samples(self, samples: np.ndarray) -> None:
        if not samples.size:
            return
        self.samples = np.concatenate((self.samples, samples))
        while self.samples.size >= self.owner.chunk:
            chunk = self.samples[: self.owner.chunk].copy()
            self.samples = self.samples[self.owner.chunk :]
            if self.pending_chunk is not None:
                self._emit(self.pending_chunk)
            self.pending_chunk = chunk

    def _feed_audio_frame(self, frame) -> None:
        for converted in self.resampler.resample(frame):
            pcm = converted.to_ndarray().reshape(-1).astype(np.float32)
            pcm /= 32768.0
            self._queue_samples(self.trimmer.feed(pcm))

    def _decode_packet(self, packet) -> None:
        try:
            frames = self.decoder.decode(packet)
        except av.error.InvalidDataError:
            # Some MP3 streams begin with an ID3/Xing metadata packet which
            # carries no audio.  Later packets remain independently decodable.
            return
        for frame in frames:
            self._feed_audio_frame(frame)

    def feed_mp3(self, data: bytes) -> None:
        for packet in self.decoder.parse(data):
            self._decode_packet(packet)

    def finish(self) -> None:
        for packet in self.decoder.parse(b""):
            self._decode_packet(packet)
        for frame in self.decoder.decode(None):
            self._feed_audio_frame(frame)
        for converted in self.resampler.resample(None):
            pcm = converted.to_ndarray().reshape(-1).astype(np.float32)
            pcm /= 32768.0
            self._queue_samples(self.trimmer.feed(pcm))
        self._queue_samples(self.trimmer.finish())
        if self.samples.size:
            padded = np.pad(
                self.samples,
                (0, self.owner.chunk - self.samples.size),
            )
            if self.pending_chunk is not None:
                self._emit(self.pending_chunk)
            self.pending_chunk = padded.astype(np.float32, copy=False)
            self.samples = np.empty(0, dtype=np.float32)
        if self.pending_chunk is not None:
            self._emit(self.pending_chunk, final=True)
            self.pending_chunk = None


class EdgeTTS(BaseTTS):
    def __init__(self, config, parent):
        super().__init__(config, parent)
        self.retry_after_pcm_count = 0
        self.retry_after_playback_commit_count = 0
        self.last_onset_preroll_ms = 0.0

    def txt_to_audio(self, msg: tuple[str, dict]):
        voicename = self.config.tts.ref_file  # 比如 "zh-CN-YunxiaNeural"
        text, textevent = msg
        started_at = time.perf_counter()
        try:
            asyncio.run(
                self._stream_with_retry(
                    voicename,
                    text,
                    textevent,
                    started_at,
                    fragment_committed=self._fragment_committed_predicate(textevent),
                    discard_uncommitted=self._discard_uncommitted_predicate(textevent),
                )
            )
        except Exception:
            logger.exception("Edge TTS streaming failed")
        finally:
            logger.info(
                "-------edge tts total stream time:%.4fs",
                time.perf_counter() - started_at,
            )

    def synthesize_fragment(
        self,
        fragment: PlayableFragment,
        *,
        chunk_guard: Callable[[int], bool],
        retry_budget: Optional[RetryBudget] = None,
        fragment_committed: Optional[Callable[[], bool]] = None,
        discard_uncommitted: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Synchronously synthesize one fenced fragment into 20ms PCM frames."""
        envelope = fragment.envelope
        textevent = {
            "turn_id": envelope.turn_id,
            "generation": envelope.generation,
            "fragment_sequence": envelope.sequence,
        }
        started_at = time.perf_counter()
        try:
            asyncio.run(
                self._stream_with_retry(
                    self.config.tts.ref_file,
                    fragment.text,
                    textevent,
                    started_at,
                    chunk_guard=chunk_guard,
                    retry_budget=retry_budget,
                    fragment_committed=fragment_committed,
                    discard_uncommitted=discard_uncommitted,
                )
            )
        except Exception:
            logger.exception("Edge TTS fragment streaming failed")

    def _fragment_committed_predicate(
        self, textevent: dict
    ) -> Optional[Callable[[], bool]]:
        checker = getattr(self.parent, "fragment_playback_committed", None)
        if not callable(checker):
            return None
        return lambda: bool(checker(textevent))

    def _discard_uncommitted_predicate(
        self, textevent: dict
    ) -> Optional[Callable[[], bool]]:
        discard = getattr(self.parent, "discard_uncommitted_fragment", None)
        if not callable(discard):
            return None
        return lambda: bool(discard(textevent))

    def _record_onset_preroll(self, emitter: _EdgePCMEmitter) -> None:
        samples = int(getattr(emitter.trimmer, "retained_preroll_samples", 0) or 0)
        self.last_onset_preroll_ms = round(
            samples / float(self.sample_rate) * 1000.0,
            3,
        )
        observe = getattr(self.parent, "observe_tts_onset_preroll_ms", None)
        if callable(observe) and self.last_onset_preroll_ms:
            observe(self.last_onset_preroll_ms)

    def _fail_closed_after_pcm(
        self,
        emitter: _EdgePCMEmitter,
        *,
        committed: bool,
        exc: Exception,
    ) -> None:
        if committed:
            self.retry_after_playback_commit_count += 1
        else:
            self.retry_after_pcm_count += 1
        try:
            emitter.finish()
        except Exception:
            logger.debug("Could not flush interrupted Edge stream", exc_info=True)
        self._record_onset_preroll(emitter)
        logger.warning(
            "Edge TTS stream stopped after PCM without sample splice reason=%s type=%s",
            "playback_commit" if committed else "uncommitted_pcm",
            type(exc).__name__,
        )
        observe = getattr(self.parent, "observe_tts_retry", None)
        if callable(observe):
            observe(after_commit=committed)

    async def _stream_with_retry(
        self,
        voicename: str,
        text: str,
        textevent: dict,
        started_at: float,
        *,
        chunk_guard: Optional[Callable[[int], bool]] = None,
        retry_budget: Optional[RetryBudget] = None,
        fragment_committed: Optional[Callable[[], bool]] = None,
        discard_uncommitted: Optional[Callable[[], bool]] = None,
    ) -> None:
        last_error = None
        start_event_sent = False
        first_audio_logged = False
        first_encoded_logged = False
        retry_timeout_seconds = EDGE_STREAM_TIMEOUT_SECONDS
        for attempt in range(1, EDGE_MAX_ATTEMPTS + 1):
            emitter = _EdgePCMEmitter(
                self,
                text,
                textevent,
                start_event_sent=start_event_sent,
                chunk_guard=chunk_guard,
            )

            def log_first_audio() -> None:
                nonlocal first_audio_logged
                if emitter.emitted and not first_audio_logged:
                    first_audio_logged = True
                    logger.info(
                        "-------edge tts first audio:%.4fs (attempt %d)",
                        time.perf_counter() - started_at,
                        attempt,
                    )

            stream = edge_tts.Communicate(text, voicename).stream()
            iterator = stream.__aiter__()
            try:
                while self.state == State.RUNNING:
                    try:
                        item = await asyncio.wait_for(
                            iterator.__anext__(),
                            timeout=(
                                EDGE_STREAM_TIMEOUT_SECONDS
                                if attempt == 1
                                else retry_timeout_seconds
                            ),
                        )
                    except StopAsyncIteration:
                        break
                    if item.get("type") == "audio":
                        if not first_encoded_logged:
                            first_encoded_logged = True
                            mark_stage = getattr(self.parent, "mark_stage_end", None)
                            if callable(mark_stage) and textevent.get("turn_id"):
                                mark_stage("tts_first_encoded")
                        emitter.feed_mp3(item["data"])
                        log_first_audio()
                        if emitter.cancelled:
                            return
                emitter.finish()
                log_first_audio()
                if emitter.cancelled:
                    return
                self._record_onset_preroll(emitter)
                if emitter.emitted_samples or self.state != State.RUNNING:
                    return
                raise RuntimeError("Edge TTS returned no decodable audio")
            except Exception as exc:
                last_error = exc
                if self.state != State.RUNNING:
                    return
                can_retry = attempt < EDGE_MAX_ATTEMPTS
                if can_retry and retry_budget is not None:
                    permit = retry_budget.claim_retry()
                    can_retry = permit is not None
                    if permit is not None:
                        retry_timeout_seconds = permit.max_wait_seconds
                if emitter.emitted_samples:
                    log_first_audio()
                    committed = bool(
                        fragment_committed is not None and fragment_committed()
                    )
                    if committed:
                        self._fail_closed_after_pcm(
                            emitter, committed=True, exc=exc
                        )
                        return
                    if (
                        can_retry
                        and discard_uncommitted is not None
                        and discard_uncommitted()
                    ):
                        self.retry_after_pcm_count += 1
                        start_event_sent = False
                        logger.warning(
                            "Edge TTS discarded uncommitted PCM; "
                            "retrying fragment from start attempt %d/%d",
                            attempt + 1,
                            EDGE_MAX_ATTEMPTS,
                        )
                        continue
                    self._fail_closed_after_pcm(
                        emitter, committed=False, exc=exc
                    )
                    return
                logger.warning(
                    "Edge TTS attempt %d/%d failed before first audio: %s",
                    attempt,
                    EDGE_MAX_ATTEMPTS,
                    exc,
                )
                if not can_retry:
                    break
            finally:
                aclose = getattr(iterator, "aclose", None)
                if callable(aclose):
                    try:
                        await aclose()
                    except Exception:
                        pass
        raise RuntimeError("Edge TTS exhausted retries") from last_error
