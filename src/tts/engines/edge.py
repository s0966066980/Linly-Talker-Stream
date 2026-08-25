from __future__ import annotations

import asyncio
import time
from io import BytesIO

import edge_tts
import numpy as np
import resampy
import soundfile as sf

from src.tts.base import BaseTTS, State
from src.utils.logging import logger


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


class EdgeTTS(BaseTTS):
    def __init__(self, config, parent):
        super().__init__(config, parent)
        # EdgeTTS 需要 BytesIO 緩衝區來累積音訊資料
        self.input_stream = BytesIO()

    def txt_to_audio(self, msg: tuple[str, dict]):
        voicename = self.config.tts.ref_file  # 比如 "zh-CN-YunxiaNeural"
        text, textevent = msg
        t = time.time()

        # 每次呼叫獨立事件迴圈，避免和外部 loop 衝突
        asyncio.new_event_loop().run_until_complete(self.__main(voicename, text))
        logger.info(f"-------edge tts time:{time.time() - t:.4f}s")

        # Edge TTS 失敗保護
        if self.input_stream.getbuffer().nbytes <= 0:
            logger.error("edgetts err!!!!!")
            return

        # 將 BytesIO 轉為 float32 流，並按 chunk 推送給上層
        self.input_stream.seek(0)
        stream = self.__create_bytes_stream(self.input_stream)
        original_samples = stream.shape[0]
        stream = trim_edge_silence(stream, self.sample_rate)
        if stream.shape[0] != original_samples:
            logger.info(
                "[EdgeTTS] trimmed boundary silence: %.3fs -> %.3fs",
                original_samples / self.sample_rate,
                stream.shape[0] / self.sample_rate,
            )
        streamlen = stream.shape[0]
        idx = 0
        while streamlen >= self.chunk and self.state == State.RUNNING:
            eventpoint = {}
            streamlen -= self.chunk
            if idx == 0:
                # 首幀標記 start，方便前端做狀態切換
                eventpoint = {"status": "start", "text": text}
                eventpoint.update(**textevent)
            elif streamlen < self.chunk:
                # 末幀標記 end
                eventpoint = {"status": "end", "text": text}
                eventpoint.update(**textevent)
            self.parent.put_audio_frame(stream[idx : idx + self.chunk], eventpoint)
            idx += self.chunk

        # 清空緩衝區，準備下一次呼叫
        self.input_stream.seek(0)
        self.input_stream.truncate()

    def __create_bytes_stream(self, byte_stream: BytesIO) -> np.ndarray:
        stream, sample_rate = sf.read(byte_stream)  # [T*sample_rate,] float64
        logger.info(f"[INFO]tts audio stream {sample_rate}: {stream.shape}")
        stream = stream.astype(np.float32)

        if stream.ndim > 1:
            logger.info(f"[WARN] audio has {stream.shape[1]} channels, only use the first.")
            stream = stream[:, 0]

        if sample_rate != self.sample_rate and stream.shape[0] > 0:
            logger.info(
                f"[WARN] audio sample rate is {sample_rate}, resampling into {self.sample_rate}."
            )
            stream = resampy.resample(
                x=stream, sr_orig=sample_rate, sr_new=self.sample_rate
            )

        return stream

    async def __main(self, voicename: str, text: str):
        try:
            communicate = edge_tts.Communicate(text, voicename)

            first = True
            async for chunk in communicate.stream():
                if first:
                    first = False
                if chunk["type"] == "audio" and self.state == State.RUNNING:
                    self.input_stream.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    pass
        except Exception:
            logger.exception("edgetts")
