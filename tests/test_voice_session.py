import asyncio
import json
import time
import unittest
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np

from src.server.voice_session import VoiceTurnSession


class FakeAvatar:
    def __init__(self):
        self.messages = []
        self.flush_count = 0

    def put_msg_txt(self, text, data=None):
        self.messages.append((text, data or {}))

    def flush_talk(self):
        self.flush_count += 1


class FakeSegmenter:
    def __init__(self, segment=None):
        self.segment = segment
        self.is_speaking = False
        self.reset_count = 0

    def process(self, _pcm):
        if self.segment is None:
            return []
        segment, self.segment = self.segment, None
        return [segment]

    def flush(self):
        return []

    def reset(self):
        self.reset_count += 1
        self.is_speaking = False


class FakeASR:
    def transcribe(self, _audio):
        return {"text": "你好", "language": "zh"}


class VoiceTurnSessionTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, segment=None):
        config = SimpleNamespace(
            asr=SimpleNamespace(type="whisper", model_size="base", language="zh"),
            vad=SimpleNamespace(),
        )
        avatar = FakeAvatar()
        session = VoiceTurnSession(7, config, avatar)
        session._segmenter = FakeSegmenter(segment)
        session._asr = FakeASR()
        events = []
        session.attach_event_sink(lambda raw: events.append(json.loads(raw)))
        return session, avatar, events

    async def test_final_transcript_and_response_share_one_turn(self):
        segment = SimpleNamespace(
            audio=np.ones(1600, dtype=np.int16),
            sample_rate=16000,
        )
        session, avatar, events = self.make_session(segment)

        # 逐句串流後，推送 TTS 的責任在 llm_response 內部，輪次只負責把
        # turn_id 交下去。用 side_effect 模擬它逐句回推。
        def fake_llm(text, avatar_stream, *, stream_to_avatar=True, datainfo=None):
            self.assertTrue(stream_to_avatar)
            avatar_stream.put_msg_txt("您好", dict(datainfo or {}))
            return "您好"

        with patch("src.server.voice_session.llm_response", side_effect=fake_llm):
            await session.feed_pcm(np.ones(512, dtype=np.int16))
            task = session._turn_task
            self.assertIsNotNone(task)
            await task

        transcript = next(item for item in events if item["type"] == "user_transcript")
        answer = next(item for item in events if item["type"] == "assistant_text")
        self.assertEqual(transcript["turn_id"], answer["turn_id"])
        self.assertEqual(avatar.messages, [("您好", {"turn_id": answer["turn_id"]})])
        self.assertEqual([item["seq"] for item in events], sorted(item["seq"] for item in events))
        await session.close()

    async def test_streaming_vad_does_not_block_the_media_event_loop(self):
        started = Event()
        release = Event()

        class SlowSegmenter(FakeSegmenter):
            def process(self, _pcm):
                started.set()
                release.wait(timeout=0.15)
                return []

        session, _, _ = self.make_session()
        session._segmenter = SlowSegmenter()

        started_at = time.monotonic()
        feed_task = asyncio.create_task(
            session.feed_pcm(np.ones(512, dtype=np.int16))
        )
        await asyncio.sleep(0)
        heartbeat_delay = time.monotonic() - started_at
        release.set()
        await feed_task

        self.assertTrue(started.is_set())
        self.assertLess(heartbeat_delay, 0.05)
        await session.close()

    async def test_microphone_resampling_does_not_block_the_media_event_loop(self):
        started = Event()
        release = Event()
        keep_track_open = asyncio.Event()

        class SlowResampler:
            def resample(self, _frame):
                started.set()
                release.wait(timeout=0.15)
                return []

        class OneFrameTrack:
            def __init__(self):
                self.calls = 0

            async def recv(self):
                self.calls += 1
                if self.calls == 1:
                    return object()
                await keep_track_open.wait()

        session, _, _ = self.make_session()
        session._resampler = SlowResampler()

        started_at = time.monotonic()
        session.start_track(OneFrameTrack())
        await asyncio.sleep(0)
        heartbeat_delay = time.monotonic() - started_at
        release.set()

        self.assertTrue(started.is_set())
        self.assertLess(heartbeat_delay, 0.05)
        await session.close()

    async def test_push_to_talk_finalize_does_not_block_the_media_event_loop(self):
        started = Event()
        release = Event()

        class SlowFlushSegmenter(FakeSegmenter):
            def flush(self):
                started.set()
                release.wait(timeout=0.15)
                return []

        session, _, _ = self.make_session()
        session._segmenter = SlowFlushSegmenter()

        started_at = time.monotonic()
        session.handle_control(
            json.dumps({"type": "capture", "enabled": False, "finalize": True})
        )
        control_delay = time.monotonic() - started_at
        await asyncio.sleep(0)
        heartbeat_delay = time.monotonic() - started_at
        release.set()

        self.assertLess(control_delay, 0.05)
        self.assertLess(heartbeat_delay, 0.05)
        await session.close()

    async def test_outbound_audio_closes_gate_and_emits_speaking_edges(self):
        session, _, events = self.make_session()
        self.assertTrue(session._gate_open)
        session.on_output_audio(True)
        self.assertFalse(session._gate_open)
        session.on_output_audio(False)
        session.on_output_audio(False)
        session.on_output_audio(False)
        kinds = [item["type"] for item in events]
        self.assertIn("speaking_start", kinds)
        self.assertIn("speaking_end", kinds)
        await session.close()

    async def test_interrupt_flushes_old_turn_and_reopens_after_guard(self):
        session, avatar, events = self.make_session()
        session._turn_id = "old-turn"
        with patch("src.server.voice_session.asyncio.sleep", new=AsyncMock()):
            await session.interrupt()
        self.assertEqual(avatar.flush_count, 1)
        self.assertTrue(session._gate_open)
        self.assertTrue(any(item["type"] == "turn_cancelled" for item in events))
        await session.close()


class WebRTCOfferCapacityTests(unittest.IsolatedAsyncioTestCase):
    async def test_offer_rejects_before_loading_when_session_capacity_is_full(self):
        from src.server.routes.webrtc import offer
        from src.server.state import state

        request = AsyncMock()
        request.json.return_value = {
            "client_role": "console",
            "sdp": "offer",
            "type": "offer",
        }
        config = SimpleNamespace(app=SimpleNamespace(max_session=1))
        with (
            patch.object(state, "model_ready", True),
            patch.object(state, "model", object()),
            patch.object(state, "avatar", object()),
            patch.object(state, "config", config),
            patch.object(state, "avatar_streams", {1: object()}),
            patch.object(state, "session_roles", {1: "console"}, create=True),
        ):
            response = await offer(request)

        self.assertEqual(response.status, 429)
        request.json.assert_awaited_once()

    async def test_console_and_stage_have_independent_capacity(self):
        from src.server.routes.webrtc import offer
        from src.server.state import state

        class ReachedOfferParsing(Exception):
            pass

        request = AsyncMock()
        request.json.return_value = {
            "client_role": "console",
            "sdp": "offer",
            "type": "offer",
        }
        config = SimpleNamespace(app=SimpleNamespace(max_session=1))
        with (
            patch.object(state, "model_ready", True),
            patch.object(state, "model", object()),
            patch.object(state, "avatar", object()),
            patch.object(state, "config", config),
            patch.object(state, "avatar_streams", {1: object()}),
            patch.object(state, "session_roles", {1: "stage"}, create=True),
            patch(
                "src.server.routes.webrtc.RTCSessionDescription",
                side_effect=ReachedOfferParsing,
            ),
        ):
            with self.assertRaises(ReachedOfferParsing):
                await offer(request)


if __name__ == "__main__":
    unittest.main()
