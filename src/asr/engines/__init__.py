"""
ASR 引擎實現集中入口

對外只需要從這裡 import 對應的引擎類即可，例如：
    from src.asr.engines import WhisperASR, FunASR
"""

from .funasr import FunASR
from .whisper import WhisperASR

__all__ = [
    "WhisperASR",
    "FunASR",
]
