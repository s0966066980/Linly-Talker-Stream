import sys
import types
import unittest
from unittest.mock import Mock, patch

from src.asr.engines.whisper import WhisperASR


class WhisperASRLoadingTests(unittest.TestCase):
    def test_loads_faster_whisper_with_cpu_int8(self):
        engine = WhisperASR.__new__(WhisperASR)
        engine.model_size = "base"
        engine.device = "cpu"
        engine.compute_type = "int8"
        engine.model = None
        engine.model_type = None

        faster_whisper = types.ModuleType("faster_whisper")
        model = object()
        faster_whisper.WhisperModel = Mock(return_value=model)

        with patch.dict(
            sys.modules,
            {"faster_whisper": faster_whisper},
        ):
            engine._load_model()

        self.assertIs(engine.model, model)
        self.assertEqual(engine.model_type, "faster-whisper")
        faster_whisper.WhisperModel.assert_called_once_with(
            "base",
            device="cpu",
            compute_type="int8",
        )


if __name__ == "__main__":
    unittest.main()
