from __future__ import annotations

import asyncio
import time
from collections import deque

import av
import edge_tts
import numpy as np

from src.tts.base import BaseTTS, State
from src.utils.logging import logger


EDGE_STREAM_TIMEOUT_SECONDS = 2.0
EDGE_MAX_ATTEMPTS = 2


def trim_edge_silence(
    stream: np.ndarray,
    sample_rate: int,
    threshold: float = 1e-4,
    leading_pause_seconds: float = 0.04,
    trailing_pause_seconds: float = 0.12,
) -> np.ndarray:
    """移除 Edge TTS 每次請求附帶的長首尾靜音，同時保留自然停頓。"""
    if stream.size == 0:
        return stream

    # Edge 音檔尾端偶爾會殘留數個極小的非零取樣；逐點判斷會把它們誤認成
    # 語音，因而保留整段約 700ms 的 padding。以 10ms RMS 判斷較穩健。
    frame_size = max(1, int(sample_rate * 0.01))
    padded_size = ((stream.shape[0] + frame_size - 1) // frame_size) * frame_size
    framed = np.pad(stream, (0, padded_size - stream.shape[0])).reshape(-1, frame_size)
    frame_rms = np.sqrt(np.mean(np.square(framed, dtype=np.float64), axis=1))
    active_frames = np.flatnonzero(frame_rms > threshold)
    if active_frames.size == 0:
        return stream

    first_active_sample = int(active_frames[0]) * frame_size
    last_active_sample = min(stream.shape[0], (int(active_frames[-1]) + 1) * frame_size)
    start = max(0, first_active_sample - int(sample_rate * leading_pause_seconds))
    end = min(
        stream.shape[0],
        last_active_sample + int(sample_rate * trailing_pause_seconds),
    )
    return stream[start:end]


class _StreamingSilenceTrimmer:
    """Incremental equivalent of trim_edge_silence with a buffered tail."""

    def __init__(
        self,
        sample_rate: int,
        threshold: float = 1e-4,
        leading_pause_seconds: float = 0.04,
        trailing_pause_seconds: float = 0.12,
    ):
        self.frame_size = max(1, int(sample_rate * 0.01))
        self.threshold = threshold
        self.leading_frames = max(0, round(leading_pause_seconds / 0.01))
        self.trailing_frames = max(0, round(trailing_pause_seconds / 0.01))
        self._remainder = np.empty(0, dtype=np.float32)
        self._leading = deque(maxlen=self.leading_frames or 1)
        self._trailing = []
        self._started = False

    def _process_block(self, block: np.ndarray) -> list[np.ndarray]:
        rms = float(np.sqrt(np.mean(np.square(block, dtype=np.float64))))
        active = rms > self.threshold
        output = []
        if not self._started:
            if active:
                self._started = True
                output.extend(self._leading)
                self._leading.clear()
                output.append(block)
            elif self.leading_frames:
                self._leading.append(block)
            return output

        if active:
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
        skip_samples: int = 0,
        start_event_sent: bool = False,
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
        self.skip_samples = max(0, skip_samples)
        self.start_event_sent = start_event_sent

    @property
    def emitted(self) -> bool:
        return self.emitted_chunks > 0

    def _emit(self, samples: np.ndarray, *, final: bool = False) -> None:
        if self.owner.state != State.RUNNING:
            return
        eventpoint = {}
        if not self.start_event_sent:
            eventpoint = {"status": "start", "text": self.text}
            eventpoint.update(self.textevent)
            self.start_event_sent = True
        elif final:
            eventpoint = {"status": "end", "text": self.text}
            eventpoint.update(self.textevent)
        self.owner.parent.put_audio_frame(samples, eventpoint)
        self.emitted_chunks += 1
        self.emitted_samples += samples.size

    def _queue_samples(self, samples: np.ndarray) -> None:
        if not samples.size:
            return
        if self.skip_samples:
            skipped = min(self.skip_samples, samples.size)
            self.skip_samples -= skipped
            samples = samples[skipped:]
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

    def txt_to_audio(self, msg: tuple[str, dict]):
        voicename = self.config.tts.ref_file  # 比如 "zh-CN-YunxiaNeural"
        text, textevent = msg
        started_at = time.perf_counter()
        try:
            asyncio.run(self._stream_with_retry(voicename, text, textevent, started_at))
        except Exception:
            logger.exception("Edge TTS streaming failed")
        finally:
            logger.info(
                "-------edge tts total stream time:%.4fs",
                time.perf_counter() - started_at,
            )

    async def _stream_with_retry(
        self,
        voicename: str,
        text: str,
        textevent: dict,
        started_at: float,
    ) -> None:
        last_error = None
        emitted_samples = 0
        start_event_sent = False
        first_audio_logged = False
        for attempt in range(1, EDGE_MAX_ATTEMPTS + 1):
            emitter = _EdgePCMEmitter(
                self,
                text,
                textevent,
                skip_samples=emitted_samples,
                start_event_sent=start_event_sent,
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
                            timeout=EDGE_STREAM_TIMEOUT_SECONDS,
                        )
                    except StopAsyncIteration:
                        break
                    if item.get("type") == "audio":
                        emitter.feed_mp3(item["data"])
                        log_first_audio()
                emitter.finish()
                log_first_audio()
                emitted_samples += emitter.emitted_samples
                start_event_sent = emitter.start_event_sent
                if emitted_samples or self.state != State.RUNNING:
                    return
                raise RuntimeError("Edge TTS returned no decodable audio")
            except Exception as exc:
                last_error = exc
                emitted_samples += emitter.emitted_samples
                start_event_sent = emitter.start_event_sent
                if self.state != State.RUNNING:
                    return
                if emitted_samples and attempt < EDGE_MAX_ATTEMPTS:
                    log_first_audio()
                    logger.warning(
                        "Edge TTS stream interrupted after %d samples; "
                        "resuming with attempt %d/%d: %s",
                        emitted_samples,
                        attempt + 1,
                        EDGE_MAX_ATTEMPTS,
                        exc,
                    )
                    continue
                if emitted_samples:
                    emitted_before_finish = emitter.emitted_samples
                    try:
                        emitter.finish()
                    except Exception:
                        logger.debug("Could not flush interrupted Edge stream", exc_info=True)
                    emitted_samples += emitter.emitted_samples - emitted_before_finish
                    log_first_audio()
                    logger.warning(
                        "Edge TTS stream remained incomplete after %d attempts: %s",
                        EDGE_MAX_ATTEMPTS,
                        exc,
                    )
                    return
                logger.warning(
                    "Edge TTS attempt %d/%d failed before first audio: %s",
                    attempt,
                    EDGE_MAX_ATTEMPTS,
                    exc,
                )
            finally:
                aclose = getattr(iterator, "aclose", None)
                if callable(aclose):
                    try:
                        await aclose()
                    except Exception:
                        pass
        raise RuntimeError("Edge TTS exhausted retries") from last_error
