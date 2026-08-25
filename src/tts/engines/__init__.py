"""TTS 引擎實現集中入口。

對外只需要從這裡 import 對應的引擎類即可，例如：

    from src.tts.engines import EdgeTTS, SovitsTTS
"""

from src.tts.base import BaseTTS, State
from .edge import EdgeTTS
from .fish import FishTTS
from .sovits import SovitsTTS
from .cosyvoice import CosyVoiceTTS
from .indextts2 import IndexTTS2
from .qwen3 import Qwen3TTS
from .xtts import XTTS

__all__ = [
    "BaseTTS",
    "State",
    "EdgeTTS",
    "FishTTS",
    "SovitsTTS",
    "CosyVoiceTTS",
    "IndexTTS2",
    "Qwen3TTS",
    "XTTS",
]
