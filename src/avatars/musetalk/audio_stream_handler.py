"""MuseTalk 音訊流處理器 - 使用 Whisper 提取音訊特徵"""
import time
import numpy as np
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any

import queue
from queue import Queue
from src.avatars.audio_stream_handler import BaseAudioStreamHandler
from src.avatars.musetalk.whisper.audio2feature import Audio2Feature


@dataclass(frozen=True)
class MuseInferenceBatch:
    """One atomic MuseTalk feature batch and its paired 20 ms audio frames."""

    features: Any
    audio_frames: tuple[tuple[np.ndarray, int, dict | None], ...]
    batch_size: int | None = None


class MuseAudioStreamHandler(BaseAudioStreamHandler):
    """Whisper 音訊特徵提取器
    
    用於 MuseTalk Avatar 模型，提取 Whisper 音訊特徵。
    """
    def __init__(self, config, parent, audio_processor: Audio2Feature):
        super().__init__(config, parent)
        self.audio_processor = audio_processor
        self.queue = Queue(maxsize=max(1, round(self.fps * 2.0)))
        self._paired_audio_frames = deque()
        self._paired_audio_lock = Lock()
        # A short first batch gets the first mouth/audio frame onto WebRTC
        # without waiting for the steady-state model batch to fill.
        self.startup_batch_size = max(1, min(self.batch_size, 4))
        self._startup_batch_emitted = False

    @property
    def startup_batch_emitted(self) -> bool:
        return self._startup_batch_emitted

    def warm_up(self):
        """Prime feature context and paired audio without an intermediate queue."""
        offset = self.av_offset_frames()
        primed = []
        for _ in range(self.stride_left_size + self.stride_right_size):
            audio_frame, frame_type, eventpoint = self.get_audio_frame()
            self.frames.append(audio_frame)
            primed.append((audio_frame, frame_type, eventpoint))

        paired = [
            (np.zeros(self.chunk, dtype=np.float32), 1, None)
            for _ in range(max(0, -offset))
        ]
        paired.extend(
            primed[self.stride_left_size + max(0, offset):]
        )
        with self._paired_audio_lock:
            self._paired_audio_frames.extend(paired)

    def flush_talk(self):
        super().flush_talk()
        with self._paired_audio_lock:
            self._paired_audio_frames.clear()
        self._startup_batch_emitted = False

    def run_step(self):
        """執行一步音訊特徵提取"""
        start_time = time.time()
        effective_batch_size = (
            self.batch_size
            if self._startup_batch_emitted
            else self.startup_batch_size
        )
        for audio_frame, type, eventpoint in self.get_audio_frames(effective_batch_size * 2):
            self.frames.append(audio_frame)
            item = (audio_frame, type, eventpoint)
            with self._paired_audio_lock:
                self._paired_audio_frames.append(item)
        
        if len(self.frames) <= self.stride_left_size + self.stride_right_size:
            return
        
        inputs = np.concatenate(self.frames)  # [N * chunk]
        whisper_feature = self.audio_processor.audio2feat(inputs)
        # for feature in whisper_feature:
        #     self.audio_feats.append(feature)        
        #print(f"processing audio costs {(time.time() - start_time) * 1000}ms, inputs shape:{inputs.shape} whisper_feature len:{len(whisper_feature)}")
        whisper_chunks = self.audio_processor.feature2chunks(
            feature_array=whisper_feature,
            fps=self.fps / 2,
            batch_size=effective_batch_size,
            start=self.stride_left_size / 2
        )
        #print(f"whisper_chunks len:{len(whisper_chunks)},self.audio_feats len:{len(self.audio_feats)},self.output_queue len:{self.output_queue.qsize()}")
        #self.audio_feats = self.audio_feats[-(self.stride_left_size + self.stride_right_size):]
        with self._paired_audio_lock:
            if len(self._paired_audio_frames) < effective_batch_size * 2:
                return
            paired_audio_frames = tuple(
                self._paired_audio_frames.popleft()
                for _ in range(effective_batch_size * 2)
            )
        self.feat_queue.put(
            MuseInferenceBatch(
                features=whisper_chunks,
                audio_frames=paired_audio_frames,
                batch_size=effective_batch_size,
            )
        )
        self._startup_batch_emitted = True
        mark_stage = getattr(self.parent, "mark_stage_end", None)
        if callable(mark_stage) and any(
            isinstance(eventpoint, dict) and eventpoint.get("turn_id")
            for _frame, _frame_type, eventpoint in paired_audio_frames
        ):
            mark_stage("musetalk_first_batch")
        # discard the old part to save memory
        self.frames = self.frames[-(self.stride_left_size + self.stride_right_size):]
