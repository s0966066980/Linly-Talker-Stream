"""Low-cost temporal compositing for MuseTalk mouth transitions.

The controller owns only visual state.  It never waits for audio, touches a
media queue, or runs inference, so it cannot add latency to the audio master.
"""
from __future__ import annotations

from collections.abc import Sequence

import cv2
import numpy as np


class MouthContinuityController:
    """Blend only the mouth ROI when MuseTalk and idle frames meet."""

    def __init__(
        self,
        source_frames: Sequence[np.ndarray],
        masks: Sequence[np.ndarray],
        mask_coords: Sequence[Sequence[int]] | None = None,
        *,
        neutral_frames: Sequence[np.ndarray] | None = None,
        gap_grace_frames: int = 2,
        opening_frames: int = 2,
        closing_frames: int = 4,
    ) -> None:
        if len(source_frames) != len(masks):
            raise ValueError("source_frames and masks must have the same length")
        if mask_coords is not None and len(mask_coords) != len(masks):
            raise ValueError("mask_coords and masks must have the same length")
        if neutral_frames is not None and len(neutral_frames) != len(source_frames):
            raise ValueError("neutral_frames and source_frames must have the same length")
        self._source_frames = tuple(np.asarray(frame) for frame in source_frames)
        self._masks = tuple(np.asarray(mask) for mask in masks)
        self._mask_coords = tuple(mask_coords) if mask_coords is not None else None
        self._neutral_frames = (
            tuple(np.asarray(frame) for frame in neutral_frames)
            if neutral_frames is not None
            else None
        )
        self._gap_grace_frames = max(0, int(gap_grace_frames))
        self._opening_frames = max(1, int(opening_frames))
        self._closing_frames = max(1, int(closing_frames))
        self._full_masks = tuple(self._build_full_mask(index) for index in range(len(masks)))
        self.reset()

    def reset(self) -> None:
        self._previous_frame: np.ndarray | None = None
        self._previous_is_speech = False
        self._generation = None
        self._gap_remaining = 0
        self._transition_origin: np.ndarray | None = None
        self._transition_target: np.ndarray | None = None
        self._transition_step = 0
        self._transition_total = 0

    def compose(
        self,
        target_frame: np.ndarray,
        *,
        index: int,
        is_speech: bool,
        eventpoint: dict | None,
    ) -> np.ndarray:
        """Return a frame with a bounded, mask-only temporal transition."""
        target = np.asarray(target_frame)
        if target.ndim != 3 or target.shape[2] != 3 or not self._source_frames:
            return target.copy()
        index %= len(self._source_frames)

        generation = (
            eventpoint.get("generation")
            if isinstance(eventpoint, dict)
            else None
        )
        if (
            generation is not None
            and self._generation is not None
            and generation != self._generation
        ):
            self.reset()
        if generation is not None:
            self._generation = generation

        mask = self._full_masks[index]
        if mask.shape != target.shape[:2]:
            return target.copy()

        if self._previous_frame is None or self._previous_frame.shape != target.shape:
            output = target.copy()
            self._remember(output, is_speech)
            return output

        if is_speech:
            if not self._previous_is_speech:
                self._start_transition(target, self._opening_frames)
            output = self._transition_or_target(target, mask)
            self._gap_remaining = 0
            self._remember(output, True)
            return output

        if self._previous_is_speech:
            self._gap_remaining = self._gap_grace_frames
            self._start_transition(
                self._neutral_target(index, target),
                self._closing_frames,
            )

        if self._gap_remaining > 0:
            self._gap_remaining -= 1
            output = self._blend_mouth(
                self._previous_frame,
                target,
                mask,
                0.0,
            )
        else:
            output = self._transition_or_target(target, mask)
        self._remember(output, False)
        return output

    def _remember(self, frame: np.ndarray, is_speech: bool) -> None:
        self._previous_frame = frame.copy()
        self._previous_is_speech = bool(is_speech)

    def _start_transition(self, target: np.ndarray, total: int) -> None:
        self._transition_origin = (
            self._previous_frame.copy()
            if self._previous_frame is not None
            else target.copy()
        )
        self._transition_target = target.copy()
        self._transition_step = 0
        self._transition_total = max(1, int(total))

    def _transition_or_target(
        self,
        target: np.ndarray,
        mask: np.ndarray,
    ) -> np.ndarray:
        if self._transition_origin is None or self._transition_target is None:
            return target.copy()
        if self._transition_step >= self._transition_total:
            self._transition_origin = None
            self._transition_target = None
            return target.copy()
        self._transition_step += 1
        progress = self._transition_step / self._transition_total
        # Linear interpolation keeps the per-frame pixel delta bounded and
        # predictable, which is more important here than easing a transition.
        alpha = progress
        output = self._blend_mouth(
            self._transition_origin,
            self._transition_target,
            mask,
            alpha,
            base_frame=target,
        )
        if self._transition_step >= self._transition_total:
            self._transition_origin = None
            self._transition_target = None
        return output

    @staticmethod
    def _blend_mouth(
        previous: np.ndarray,
        target: np.ndarray,
        mask: np.ndarray,
        alpha: float,
        *,
        base_frame: np.ndarray | None = None,
    ) -> np.ndarray:
        output = (base_frame if base_frame is not None else target).copy()
        weights = np.asarray(mask, dtype=np.float32)
        if weights.max(initial=0.0) > 1.0:
            weights /= 255.0
        weights = np.clip(weights * float(alpha), 0.0, 1.0)
        if not np.any(mask):
            return output
        old = previous.astype(np.float32, copy=False)
        new = target.astype(np.float32, copy=False)
        mixed = old * (1.0 - weights[..., None]) + new * weights[..., None]
        active = np.asarray(mask) > 0
        output[active] = np.clip(mixed[active], 0, 255).astype(output.dtype)
        return output

    def _neutral_target(self, index: int, target: np.ndarray) -> np.ndarray:
        if self._neutral_frames is None:
            return target
        neutral = self._neutral_frames[index]
        if neutral.shape != target.shape:
            return target
        return neutral

    def _build_full_mask(self, index: int) -> np.ndarray:
        mask = self._masks[index]
        source = self._source_frames[index]
        if mask.shape[:2] == source.shape[:2]:
            return self._feather(mask)
        if self._mask_coords is None:
            return np.zeros(source.shape[:2], dtype=np.float32)
        coords = tuple(int(value) for value in self._mask_coords[index])
        if len(coords) != 4:
            return np.zeros(source.shape[:2], dtype=np.float32)
        x0, y0, x1, y1 = coords
        x0 = max(0, min(source.shape[1], x0))
        x1 = max(x0, min(source.shape[1], x1))
        y0 = max(0, min(source.shape[0], y0))
        y1 = max(y0, min(source.shape[0], y1))
        canvas = np.zeros(source.shape[:2], dtype=np.uint8)
        if x1 > x0 and y1 > y0:
            resized = cv2.resize(mask, (x1 - x0, y1 - y0), interpolation=cv2.INTER_LINEAR)
            if resized.ndim == 3:
                resized = resized[..., 0]
            canvas[y0:y1, x0:x1] = np.asarray(resized, dtype=np.uint8)
        return self._feather(canvas)

    @staticmethod
    def _feather(mask: np.ndarray) -> np.ndarray:
        values = np.asarray(mask, dtype=np.float32)
        if values.ndim == 3:
            values = values[..., 0]
        maximum = float(values.max()) if values.size else 0.0
        if maximum > 1.0:
            values /= 255.0
        return np.clip(values, 0.0, 1.0)
