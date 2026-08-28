import sys
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from types import SimpleNamespace
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


class ASRFactoryConcurrencyTests(unittest.TestCase):
    def test_concurrent_sessions_load_one_shared_engine(self):
        from src.asr import factory

        first_create_started = Event()
        release_create = Event()
        count_lock = Lock()
        create_count = 0

        def slow_create(**_kwargs):
            nonlocal create_count
            with count_lock:
                create_count += 1
            first_create_started.set()
            release_create.wait(timeout=0.5)
            return SimpleNamespace(set_language=Mock())

        config = SimpleNamespace(
            asr=SimpleNamespace(device="cpu", language="zh")
        )
        old_instance = factory._asr_instance
        old_key = factory._asr_instance_key
        factory._asr_instance = None
        factory._asr_instance_key = None
        try:
            with (
                patch("src.asr.factory.create_asr_engine", side_effect=slow_create),
                ThreadPoolExecutor(max_workers=2) as executor,
            ):
                first = executor.submit(
                    factory.get_asr_engine, "whisper", "tiny", config
                )
                self.assertTrue(first_create_started.wait(timeout=0.5))
                second = executor.submit(
                    factory.get_asr_engine, "whisper", "tiny", config
                )
                time.sleep(0.02)
                release_create.set()
                first_engine = first.result(timeout=0.5)
                second_engine = second.result(timeout=0.5)

            self.assertEqual(create_count, 1)
            self.assertIs(first_engine, second_engine)
        finally:
            release_create.set()
            factory._asr_instance = old_instance
            factory._asr_instance_key = old_key


if __name__ == "__main__":
    unittest.main()
