import asyncio
import time
import unittest
from io import BytesIO
from threading import Event, Thread
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from src.tts.base import State


def _mp3_fixture() -> bytes:
    import av

    sample_rate = 24000
    tone_samples = int(sample_rate * 0.12)
    tone = (
        np.sin(2 * np.pi * 440 * np.arange(tone_samples) / sample_rate) * 8000
    ).astype(np.int16)
    output = BytesIO()
    with av.open(output, mode="w", format="mp3") as container:
        stream = container.add_stream("libmp3lame", rate=sample_rate)
        stream.layout = "mono"
        frame = av.AudioFrame.from_ndarray(
            tone.reshape(1, -1), format="s16", layout="mono"
        )
        frame.sample_rate = sample_rate
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    payload = output.getvalue()
    marker = payload.find(b"\xff\xf3")
    return payload[marker:] if marker >= 0 else payload


class EdgeTTSWorkerTests(unittest.TestCase):
    def _make_tts(self, parent, **tts_fields):
        from src.tts.engines.edge import EdgeTTS

        fields = {
            "ref_file": "zh-TW-YunJheNeural",
            "edge_persistent_worker": True,
            "edge_prefetch": True,
        }
        fields.update(tts_fields)
        config = SimpleNamespace(
            audio=SimpleNamespace(fps=50),
            tts=SimpleNamespace(**fields),
        )
        tts = EdgeTTS(config, parent)
        self.addCleanup(tts.close_worker)
        return tts

    def test_persistent_worker_reuses_the_same_event_loop(self):
        payload = _mp3_fixture()

        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                return None

        class WorkingCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}

        tts = self._make_tts(Parent())
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: WorkingCommunicate(),
        ):
            tts.txt_to_audio(("第一段。", {}))
            loop = tts.worker_loop
            tts.txt_to_audio(("第二段。", {}))

        self.assertIsNotNone(loop)
        self.assertIs(tts.worker_loop, loop)
        self.assertTrue(loop.is_running())

    def test_first_fragment_pcm_does_not_wait_for_the_next_edge_request(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        second_started = Event()
        first_hold = Event()
        emitted = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                emitted.append(eventpoint.get("fragment_sequence"))
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        class SecondCommunicate:
            async def stream(self):
                second_started.set()
                yield {"type": "audio", "data": payload}

        communicates = [FirstCommunicate, SecondCommunicate]

        def communicate(*_args):
            return communicates.pop(0)()

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        tts.put_msg_txt(
            "第二段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 1},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                self.assertTrue(second_started.wait(timeout=1.5))
                self.assertNotIn(1, emitted)
                first_hold.set()
                deadline = time.time() + 1.5
                while 1 not in emitted and time.time() < deadline:
                    time.sleep(0.01)
                self.assertIn(1, emitted)
                self.assertLess(emitted.index(0), emitted.index(1))
            finally:
                quit_event.set()
                worker.join(timeout=2)

    def test_flush_talk_drops_prefetched_fragment_audio(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        second_started = Event()
        first_hold = Event()
        emitted = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                emitted.append(eventpoint.get("fragment_sequence"))
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        class SecondCommunicate:
            async def stream(self):
                second_started.set()
                yield {"type": "audio", "data": payload}
                await asyncio.sleep(0.05)

        communicates = [FirstCommunicate, SecondCommunicate]

        def communicate(*_args):
            return communicates.pop(0)()

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        tts.put_msg_txt(
            "第二段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 1},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch("src.tts.engines.edge.edge_tts.Communicate", side_effect=communicate):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                self.assertTrue(second_started.wait(timeout=1.5))
                tts.flush_talk()
                first_hold.set()
                worker.join(timeout=0.2)
            finally:
                quit_event.set()
                worker.join(timeout=2)

        self.assertNotIn(1, emitted)

    def test_in_flight_poll_timeout_is_not_a_synthesis_failure(self):
        payload = _mp3_fixture()
        first_pcm = Event()
        first_hold = Event()
        failures = []

        class Parent:
            def put_audio_frame(self, _frame, eventpoint):
                if eventpoint.get("fragment_sequence") == 0:
                    first_pcm.set()

            def notify_fragment_synthesis_failed(self, _eventpoint, reason):
                failures.append(reason)

        class FirstCommunicate:
            async def stream(self):
                yield {"type": "audio", "data": payload}
                while not first_hold.is_set():
                    await asyncio.sleep(0.01)

        tts = self._make_tts(Parent())
        tts.put_msg_txt(
            "第一段。",
            {"turn_id": "turn-1", "generation": 1, "fragment_sequence": 0},
        )
        quit_event = Event()
        worker = Thread(target=tts.process_tts, args=(quit_event,))
        with patch(
            "src.tts.engines.edge.edge_tts.Communicate",
            side_effect=lambda *_args: FirstCommunicate(),
        ):
            worker.start()
            try:
                self.assertTrue(first_pcm.wait(timeout=1.5))
                time.sleep(0.2)
                self.assertEqual(failures, [])
            finally:
                first_hold.set()
                quit_event.set()
                worker.join(timeout=2)

        self.assertEqual(failures, [])

    def test_worker_close_stops_the_background_loop(self):
        class Parent:
            def put_audio_frame(self, _frame, _eventpoint):
                return None

        tts = self._make_tts(Parent())
        tts._ensure_worker()
        loop = tts.worker_loop
        thread = tts._worker.thread
        self.assertTrue(loop.is_running())
        tts.close_worker()
        self.assertFalse(loop.is_running())
        self.assertFalse(thread.is_alive())
