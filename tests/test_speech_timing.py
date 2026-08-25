import unittest
from threading import Event, Thread
from types import SimpleNamespace

import numpy as np

from src.llm.base import TextStreamProcessor
from src.tts.base import BaseTTS


class TextStreamTimingTests(unittest.TestCase):
    def test_comma_clause_waits_for_sentence_end(self):
        emitted = []
        processor = TextStreamProcessor()

        processor.process_chunk("我是 Linly 數字人助手，", emitted.append)
        self.assertEqual(emitted, [])

        processor.process_chunk("很高興為你服務，也可以協助處理各種問題。", emitted.append)
        self.assertEqual(
            emitted,
            ["我是 Linly 數字人助手，很高興為你服務，也可以協助處理各種問題。"],
        )


class MuseTalkAudioWindowTests(unittest.TestCase):
    def test_feature_window_is_centered_on_the_video_frame(self):
        from src.avatars.musetalk.whisper.audio2feature import Audio2Feature

        processor = Audio2Feature.__new__(Audio2Feature)
        features = np.zeros((64, 5, 384), dtype=np.float32)

        _, selected = processor.get_sliced_feature(
            features,
            vid_idx=5,
            audio_feat_length=[2, 2],
            fps=25,
        )

        self.assertEqual(selected, list(range(6, 16)))


class MuseTalkBufferPolicyTests(unittest.TestCase):
    def test_waits_for_pending_tts_while_playback_has_headroom(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        self.assertTrue(
            should_wait_for_tts_audio(
                tts_pending=True,
                queued_audio_frames=8,
                required_audio_frames=32,
                queued_video_frames=5,
            )
        )

    def test_does_not_starve_playback_or_delay_ready_audio(self):
        from src.avatars.musetalk.avatar import should_wait_for_tts_audio

        self.assertFalse(
            should_wait_for_tts_audio(True, 8, 32, queued_video_frames=4)
        )
        self.assertFalse(
            should_wait_for_tts_audio(True, 32, 32, queued_video_frames=5)
        )
        self.assertFalse(
            should_wait_for_tts_audio(False, 0, 32, queued_video_frames=5)
        )

    def test_tts_reports_work_while_synthesis_is_active(self):
        started = Event()
        release = Event()
        quit_event = Event()

        class BlockingTTS(BaseTTS):
            def txt_to_audio(self, msg):
                started.set()
                release.wait(timeout=1)

        config = SimpleNamespace(audio=SimpleNamespace(fps=50))
        tts = BlockingTTS(config, parent=None)
        tts.put_msg_txt("測試語音")
        worker = Thread(target=tts.process_tts, args=(quit_event,), daemon=True)
        worker.start()

        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(tts.has_pending_work())

        quit_event.set()
        release.set()
        worker.join(timeout=1)
        self.assertFalse(tts.has_pending_work())


class EdgeTTSSilenceTests(unittest.TestCase):
    def test_trims_synthesizer_padding_but_keeps_short_natural_pause(self):
        from src.tts.engines.edge import trim_edge_silence

        sample_rate = 16000
        stream = np.concatenate(
            [
                np.zeros(int(sample_rate * 0.10), dtype=np.float32),
                np.full(int(sample_rate * 0.50), 0.1, dtype=np.float32),
                np.zeros(int(sample_rate * 0.72), dtype=np.float32),
            ]
        )

        trimmed = trim_edge_silence(stream, sample_rate)

        self.assertEqual(trimmed.shape[0], int(sample_rate * (0.04 + 0.50 + 0.12)))
        self.assertTrue(np.allclose(trimmed[: int(sample_rate * 0.04)], 0.0))
        self.assertTrue(np.allclose(trimmed[-int(sample_rate * 0.12) :], 0.0))

    def test_does_not_drop_an_entire_quiet_clip(self):
        from src.tts.engines.edge import trim_edge_silence

        stream = np.zeros(1600, dtype=np.float32)
        self.assertIs(trim_edge_silence(stream, 16000), stream)


if __name__ == "__main__":
    unittest.main()
