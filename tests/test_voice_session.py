import asyncio
import json
import unittest
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
        with patch("src.server.voice_session.llm_response", return_value="您好"):
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


if __name__ == "__main__":
    unittest.main()
