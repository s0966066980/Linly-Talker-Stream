"""Content-free, monotonic measurements for one voice turn."""
from __future__ import annotations

import time
from collections import Counter
from typing import Callable, Optional


Clock = Callable[[], float]


def _duration(start: Optional[float], end: Optional[float]) -> Optional[float]:
    if start is None or end is None:
        return None
    return round(max(0.0, end - start), 6)


class TurnMetrics:
    """Collect the fixed, privacy-safe measurements for a single turn.

    The API deliberately has no arbitrary payload or content field. This keeps
    transcripts, generated text, and audio out of the baseline telemetry path.
    """

    def __init__(self, turn_id: str, *, clock: Clock = time.monotonic) -> None:
        self._turn_id = turn_id
        self._clock = clock
        self._speech_end_at: Optional[float] = None
        self._first_audio_at: Optional[float] = None
        self._interrupt_at: Optional[float] = None
        self._output_stopped_at: Optional[float] = None
        self._listening_resumed_at: Optional[float] = None
        self._max_media_debt_seconds = 0.0
        self._max_abs_av_offset_seconds = 0.0
        self._stale_drops: Counter[str] = Counter()

    def mark_speech_end(self) -> None:
        if self._speech_end_at is None:
            self._speech_end_at = self._clock()

    def mark_first_audio(self) -> None:
        if self._first_audio_at is None:
            self._first_audio_at = self._clock()

    def mark_interrupt(self) -> None:
        if self._interrupt_at is None:
            self._interrupt_at = self._clock()

    def mark_output_stopped(self) -> None:
        if self._interrupt_at is not None and self._output_stopped_at is None:
            self._output_stopped_at = self._clock()

    def mark_listening_resumed(self) -> None:
        if self._listening_resumed_at is None:
            self._listening_resumed_at = self._clock()

    def observe_media_debt(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("media debt cannot be negative")
        self._max_media_debt_seconds = max(self._max_media_debt_seconds, seconds)

    def observe_av_offset(self, seconds: float) -> None:
        self._max_abs_av_offset_seconds = max(
            self._max_abs_av_offset_seconds,
            abs(seconds),
        )

    def record_stale_drop(self, stage: str, reason: str) -> None:
        if not stage or not reason:
            raise ValueError("stale drop stage and reason are required")
        self._stale_drops[f"{stage}:{reason}"] += 1

    def snapshot(self) -> dict:
        """Return scalar metadata suitable for logs and SLO aggregation."""
        return {
            "turn_id": self._turn_id,
            "first_audio_seconds": _duration(
                self._speech_end_at,
                self._first_audio_at,
            ),
            "interrupt_stop_seconds": _duration(
                self._interrupt_at,
                self._output_stopped_at,
            ),
            "listening_resume_seconds": _duration(
                self._interrupt_at,
                self._listening_resumed_at,
            ),
            "max_media_debt_seconds": round(self._max_media_debt_seconds, 6),
            "max_abs_av_offset_seconds": round(
                self._max_abs_av_offset_seconds,
                6,
            ),
            "stale_drops": dict(sorted(self._stale_drops.items())),
        }
