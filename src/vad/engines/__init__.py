"""
VAD 引擎實現集中入口

對外只需要從這裡 import 對應的引擎類即可，例如：
    from src.vad.engines import SileroVAD
"""

from .silero import SileroVAD

__all__ = [
    "SileroVAD",
]
