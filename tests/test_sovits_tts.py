import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tts.engines.sovits import SovitsTTS


class RecordingParent:
    def __init__(self):
        self.frames = []

    def put_audio_frame(self, audio_chunk, datainfo=None):
        self.frames.append((audio_chunk, dict(datainfo or {})))


class SovitsTTSFailureTests(unittest.TestCase):
    def _make_tts(self):
        parent = RecordingParent()
        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(
                ref_file="/tmp/ref.wav",
                ref_text="你好",
                tts_server="http://127.0.0.1:9880",
            ),
        )
        return SovitsTTS(config, parent), parent

    def test_connection_refused_does_not_emit_silent_preview_audio(self):
        tts, parent = self._make_tts()
        with patch(
            "src.tts.engines.sovits.requests.post",
            side_effect=ConnectionError("Connection refused"),
        ):
            with self.assertRaisesRegex(RuntimeError, "127.0.0.1:9880"):
                tts.txt_to_audio(("測試語音", {}))
        self.assertEqual(parent.frames, [])

    def test_http_error_does_not_emit_silent_end_frame(self):
        tts, parent = self._make_tts()

        class ErrorResponse:
            status_code = 500
            text = "server error"

            def iter_content(self, chunk_size=None):
                return iter(())

        with patch(
            "src.tts.engines.sovits.requests.post",
            return_value=ErrorResponse(),
        ):
            with self.assertRaisesRegex(RuntimeError, "沒有產生音訊"):
                tts.txt_to_audio(("測試語音", {}))
        self.assertEqual(parent.frames, [])
