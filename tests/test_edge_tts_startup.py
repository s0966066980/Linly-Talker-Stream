from types import SimpleNamespace
from threading import Event
from unittest import TestCase
from unittest.mock import patch

from src.server.app import _await_edge_tts_prewarm, _start_edge_tts_prewarm


class EdgeTTSStartupTests(TestCase):
    @staticmethod
    def _config(engine: str = "edgetts"):
        return SimpleNamespace(
            tts=SimpleNamespace(
                type=engine,
                ref_file="zh-TW-YunJheNeural",
            )
        )

    def test_edge_prewarm_finishes_before_readiness(self):
        called = Event()

        with patch(
            "src.tts.engines.edge.prewarm_edge_tts",
            side_effect=lambda voice: called.set(),
        ) as prewarm:
            worker = _start_edge_tts_prewarm(self._config())
            _await_edge_tts_prewarm(worker)

        self.assertTrue(called.is_set())
        prewarm.assert_called_once_with("zh-TW-YunJheNeural")
        self.assertFalse(worker.is_alive())

    def test_non_edge_engine_does_not_start_edge_prewarm(self):
        with patch("src.tts.engines.edge.prewarm_edge_tts") as prewarm:
            worker = _start_edge_tts_prewarm(self._config("cosyvoice"))
            _await_edge_tts_prewarm(worker)

        self.assertIsNone(worker)
        prewarm.assert_not_called()
