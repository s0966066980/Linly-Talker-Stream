# Linly-Talker-Stream (https://github.com/Kedreamix/Linly-Talker-Stream). Copyright [Linly-talker-stream@kedreamix]. Apache-2.0.
# Based on LiveTalking (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking (Apache-2.0).

import asyncio
import json
import logging
import threading
import time
from typing import Tuple, Dict, Optional, Set, Union
from av.frame import Frame
from av.packet import Packet
from av import AudioFrame
import fractions
import numpy as np

AUDIO_PTIME = 0.020  # 20ms audio packetization
VIDEO_CLOCK_RATE = 90000
VIDEO_PTIME = 0.040 #1 / 25  # 30fps
VIDEO_TIME_BASE = fractions.Fraction(1, VIDEO_CLOCK_RATE)
SAMPLE_RATE = 16000
AUDIO_TIME_BASE = fractions.Fraction(1, SAMPLE_RATE)
# 排程暫停超過這個時間後，不再高速補送媒體包；重新定位牆鐘基準，讓 RTP
# 時間戳保持連續，同時讓後續 audio/video 包恢復正常節奏。
MAX_PACING_LAG = 0.100
# Keep only a short, equal-duration A/V runway.  A large idle runway makes the
# first spoken frame wait behind old silence after STT finishes.
MAX_MEDIA_BUFFER_SECONDS = 0.240
SPEECH_START_RUNWAY_SECONDS = 0.080

#from aiortc.contrib.media import MediaPlayer, MediaRelay
#from aiortc.rtcrtpsender import RTCRtpSender
from aiortc import (
    MediaStreamTrack,
)

logging.basicConfig()
logger = logging.getLogger(__name__)
from logger import logger as mylogger


class _MediaPacingClock:
    """Shared wall-clock origin for one player's audio and video RTP tracks."""

    def __init__(self):
        self._start: Optional[float] = None

    def ensure_started(self, now: float) -> float:
        if self._start is None:
            self._start = now
        return self._start

    @property
    def start(self) -> float:
        if self._start is None:
            raise RuntimeError("media pacing clock has not started")
        return self._start

    def rebase(self, lag: float) -> None:
        self._start = self.start + lag


class PlayerStreamTrack(MediaStreamTrack):
    """
    A video track that returns an animated flag.
    """

    def __init__(self, player, kind, pacing_clock=None):
        super().__init__()  # don't forget this!
        self.kind = kind
        self._player = player
        self._pacing_clock = pacing_clock or _MediaPacingClock()
        packet_time = VIDEO_PTIME if kind == "video" else AUDIO_PTIME
        self._packet_time = packet_time
        self._queue = asyncio.Queue(
            maxsize=max(1, round(MAX_MEDIA_BUFFER_SECONDS / packet_time))
        )
        self.timelist = [] #記錄最近包的時間戳
        self.current_frame_count = 0
        if self.kind == 'video':
            self.framecount = 0
            self.lasttime = time.perf_counter()
            self.totaltime = 0
    
    _timestamp: int

    @property
    def _start(self) -> float:
        return self._pacing_clock.start

    @property
    def max_buffer_frames(self) -> int:
        return self._queue.maxsize

    @property
    def max_buffer_duration(self) -> float:
        return self.max_buffer_frames * self._packet_time

    @property
    def buffered_duration(self) -> float:
        return self._queue.qsize() * self._packet_time

    async def enqueue(self, frame, eventpoint=None) -> None:
        """Apply media backpressure instead of accumulating stale idle frames."""
        await self._queue.put((frame, eventpoint))

    async def prepare_speech_start(self) -> None:
        if self._player is not None:
            await self._player.prepare_speech_start()

    async def next_timestamp(self) -> Tuple[int, fractions.Fraction]:
        if self.readyState != "live":
            raise Exception

        if self.kind == "video":
            packet_time = VIDEO_PTIME
            clock_rate = VIDEO_CLOCK_RATE
            time_base = VIDEO_TIME_BASE
        else:
            packet_time = AUDIO_PTIME
            clock_rate = SAMPLE_RATE
            time_base = AUDIO_TIME_BASE

        now = time.monotonic()
        if hasattr(self, "_timestamp"):
            self._timestamp += int(packet_time * clock_rate)
            self.current_frame_count += 1
            deadline = self._start + self.current_frame_count * packet_time
            lag = now - deadline
            if lag > MAX_PACING_LAG:
                # 執行緒／event loop 曾被 ASR 或模型推論暫停。若保留舊基準，
                # wait 會長時間為負值，音訊和影像便以最快速度追幀。只平移
                # 牆鐘基準，不改 RTP PTS，下一包開始恢復固定 20/40ms 節奏。
                self._pacing_clock.rebase(lag)
                deadline = now
                mylogger.warning(
                    "[AVSync] %s pacing stalled %.0fms; rebased media clock",
                    self.kind,
                    lag * 1000.0,
                )
            wait = deadline - now
            if wait > 0:
                await asyncio.sleep(wait)
        else:
            self._pacing_clock.ensure_started(now)
            self._timestamp = 0
            self.timelist.append(self._start)
            mylogger.info("%s start:%f", self.kind, self._start)

        return self._timestamp, time_base

    async def recv(self) -> Union[Frame, Packet]:        
        self._player._start(self)

        frame,eventpoint = await self._queue.get()
        if frame is None:
            self.stop()
            raise Exception
        pts, time_base = await self.next_timestamp()
        frame.pts = pts
        frame.time_base = time_base

        # 每 5 秒回報一次「媒體時間 vs 牆鐘」。任一軌若在 _queue.get() 上餓死，
        # current_frame_count 會停住而牆鐘照走，該軌的 pts 就永久落後真實時間。
        # 把兩軌的 drift 相減，就是實際的音影像不同步量與方向。
        now = time.monotonic()
        if now - getattr(self, "_drift_logged_at", 0.0) >= 5.0:
            self._drift_logged_at = now
            rate = VIDEO_CLOCK_RATE if self.kind == "video" else SAMPLE_RATE
            media_s = pts / rate
            elapsed = now - self._start
            mylogger.info(
                "[AVSync] %-5s media=%8.3fs wall=%8.3fs drift=%+7.0fms qsize=%d",
                self.kind, media_s, elapsed, (elapsed - media_s) * 1000.0,
                self._queue.qsize(),
            )
        if eventpoint and self._player is not None:
            self._player.notify(eventpoint)
        if self.kind == 'audio' and self._player is not None:
            try:
                samples = frame.to_ndarray().astype(np.float32, copy=False)
                self._player.notify_audio_activity(bool(np.max(np.abs(samples))) if samples.size else False)
            except Exception:
                self._player.notify_audio_activity(False)
        if self.kind == 'video':
            self.totaltime += (time.perf_counter() - self.lasttime)
            self.framecount += 1
            self.lasttime = time.perf_counter()
            if self.framecount==100:
                mylogger.info(f"------actual avg final fps:{self.framecount/self.totaltime:.4f}")
                self.framecount = 0
                self.totaltime=0
        return frame
    
    def stop(self):
        super().stop()
        # Drain & delete remaining frames
        while not self._queue.empty():
            item = self._queue.get_nowait()
            del item
        if self._player is not None:
            self._player._stop(self)
            self._player = None

def player_worker_thread(
    quit_event,
    loop,
    container,
    audio_track,
    video_track
):
    container.render(quit_event,loop,audio_track,video_track)

class HumanPlayer:

    def __init__(
        self, avatar_stream, format=None, options=None, timeout=None, loop=False, decode=True,
        on_audio_activity=None,
    ):
        self.__thread: Optional[threading.Thread] = None
        self.__thread_quit: Optional[threading.Event] = None

        # examine streams
        self.__started: Set[PlayerStreamTrack] = set()
        self.__audio: Optional[PlayerStreamTrack] = None
        self.__video: Optional[PlayerStreamTrack] = None

        pacing_clock = _MediaPacingClock()
        self.__audio = PlayerStreamTrack(self, kind="audio", pacing_clock=pacing_clock)
        self.__video = PlayerStreamTrack(self, kind="video", pacing_clock=pacing_clock)

        self.__container = avatar_stream
        self.__on_audio_activity = on_audio_activity

    def notify_audio_activity(self, active: bool):
        if self.__on_audio_activity is not None:
            self.__on_audio_activity(active)

    def notify(self,eventpoint):
        if self.__container is not None:
            self.__container.notify(eventpoint)

    async def prepare_speech_start(self) -> None:
        """Trim only paired idle media before releasing the first spoken pair."""
        discarded_pairs = 0
        while (
            self.__audio.buffered_duration > SPEECH_START_RUNWAY_SECONDS
            and self.__video.buffered_duration > SPEECH_START_RUNWAY_SECONDS
            and self.__audio._queue.qsize() >= 2
            and self.__video._queue.qsize() >= 1
        ):
            first_audio = self.__audio._queue._queue[0]
            second_audio = self.__audio._queue._queue[1]
            if first_audio[1] is not None or second_audio[1] is not None:
                break
            self.__audio._queue.get_nowait()
            self.__audio._queue.get_nowait()
            self.__video._queue.get_nowait()
            discarded_pairs += 1
        if discarded_pairs:
            mylogger.info(
                "[AVSync] speech start trimmed %d paired idle frames; audio=%.0fms video=%.0fms",
                discarded_pairs,
                self.__audio.buffered_duration * 1000.0,
                self.__video.buffered_duration * 1000.0,
            )

    @property
    def audio(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains audio.
        """
        return self.__audio

    @property
    def video(self) -> MediaStreamTrack:
        """
        A :class:`aiortc.MediaStreamTrack` instance if the file contains video.
        """
        return self.__video

    def _start(self, track: PlayerStreamTrack) -> None:
        self.__started.add(track)
        if self.__thread is None:
            self.__log_debug("Starting worker thread")
            self.__thread_quit = threading.Event()
            self.__thread = threading.Thread(
                name="media-player",
                target=player_worker_thread,
                args=(
                    self.__thread_quit,
                    asyncio.get_event_loop(),
                    self.__container,
                    self.__audio,
                    self.__video                   
                ),
            )
            self.__thread.start()

    def _stop(self, track: PlayerStreamTrack) -> None:
        self.__started.discard(track)

        if not self.__started and self.__thread is not None:
            self.__log_debug("Stopping worker thread")
            self.__thread_quit.set()
            self.__thread.join()
            self.__thread = None

        if not self.__started and self.__container is not None:
            #self.__container.close()
            self.__container = None

    def __log_debug(self, msg: str, *args) -> None:
        mylogger.debug(f"HumanPlayer {msg}", *args)
