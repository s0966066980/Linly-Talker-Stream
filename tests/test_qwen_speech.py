import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from src.asr.engines.qwen3 import Qwen3ASR
from src.tts.engines.qwen3 import Qwen3TTS, _WORKER_CACHE


class Qwen3ASRTests(unittest.TestCase):
    def test_load_and_transcribe_through_isolated_worker(self):
        config = SimpleNamespace(asr=SimpleNamespace(device="cpu"))
        engine = Qwen3ASR(config, "Qwen/Qwen3-ASR-0.6B")
        engine.set_language("zh")

        worker = Mock()
        worker.request.return_value = {"text": " 你好世界 ", "language": "Chinese"}
        with patch("src.asr.engines.qwen3.QwenWorkerClient", return_value=worker):
            engine._load_model()
            result = engine._transcribe("sample.wav")

        worker.start.assert_called_once_with(
            kind="asr", model="Qwen/Qwen3-ASR-0.6B", device="cpu"
        )
        worker.request.assert_called_once_with(
            "transcribe",
            audio="sample.wav",
            language="Chinese",
        )
        self.assertEqual(result, {"text": "你好世界", "language": "zh"})


class FakeAudioSink:
    def __init__(self):
        self.frames = []

    def put_audio_frame(self, frame, event=None):
        self.frames.append((frame, event or {}))


class Qwen3TTSTests(unittest.TestCase):
    def setUp(self):
        _WORKER_CACHE.clear()

    def test_custom_voice_generates_fixed_20ms_frames(self):
        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                model="Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
                language="Chinese",
                speaker="Vivian",
                instruct="溫柔地說",
                device="cpu",
                ref_file="",
                ref_text=None,
            ),
        )
        sink = FakeAudioSink()
        engine = Qwen3TTS(config, sink)
        worker = Mock()

        def request(action, **kwargs):
            self.assertEqual(action, "synthesize")
            sf.write(kwargs["output"], np.ones(640, dtype=np.float32), 16000)
            return {"sample_rate": 16000}

        worker.request.side_effect = request

        with patch("src.tts.engines.qwen3.QwenWorkerClient", return_value=worker):
            engine.txt_to_audio(("測試", {"turn_id": "turn-1"}))

        worker.start.assert_called_once_with(
            kind="tts", model=config.tts.model, device="cpu"
        )
        self.assertEqual(len(sink.frames), 3)
        self.assertTrue(all(frame.shape == (320,) for frame, _ in sink.frames))
        self.assertEqual(sink.frames[0][1]["status"], "start")
        self.assertEqual(sink.frames[-1][1]["status"], "end")
        self.assertTrue(np.allclose(sink.frames[-1][0], 0))


if __name__ == "__main__":
    unittest.main()
