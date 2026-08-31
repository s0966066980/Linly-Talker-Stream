import time
import unittest
from types import SimpleNamespace

from src.llm.base import BaseLLM


FIRST_SENTENCE = "這是一段足夠長度的第一句話用來觸發分段語音合成開始。"
SECOND_SENTENCE = "這是接在後面的第二句，用來模擬模型還在繼續生成內容。"
TOKEN_GAP_SECONDS = 0.12


class RecordingAvatar:
    def __init__(self):
        self.events = []

    def put_msg_txt(self, text, datainfo=None):
        self.events.append(
            {
                "at": time.perf_counter(),
                "text": text,
                "datainfo": dict(datainfo or {}),
            }
        )


class SlowSentenceLLM(BaseLLM):
    def chat_stream(self, message, system_prompt=None, **kwargs):
        yield FIRST_SENTENCE
        time.sleep(TOKEN_GAP_SECONDS)
        yield SECOND_SENTENCE


class StreamingVersusOneShotTtsTests(unittest.TestCase):
    def setUp(self):
        self.config = SimpleNamespace(llm=SimpleNamespace(system_prompt="測試"))

    def test_streaming_starts_tts_and_avatar_before_legacy_one_shot(self):
        streaming_avatar = RecordingAvatar()
        oneshot_avatar = RecordingAvatar()

        streaming_started = time.perf_counter()
        SlowSentenceLLM(self.config).generate_response(
            "請回答",
            streaming_avatar,
            stream_to_avatar=True,
        )
        streaming_first = streaming_avatar.events[0]["at"] - streaming_started

        oneshot_started = time.perf_counter()
        full_text = SlowSentenceLLM(self.config).generate_response(
            "請回答",
            oneshot_avatar,
            stream_to_avatar=False,
        )
        oneshot_avatar.put_msg_txt(full_text)
        oneshot_first = oneshot_avatar.events[0]["at"] - oneshot_started

        self.assertGreaterEqual(len(streaming_avatar.events), 2)
        self.assertEqual(len(oneshot_avatar.events), 1)
        self.assertEqual(oneshot_avatar.events[0]["text"], FIRST_SENTENCE + SECOND_SENTENCE)
        self.assertLess(streaming_first, TOKEN_GAP_SECONDS / 2)
        self.assertGreater(oneshot_first, TOKEN_GAP_SECONDS * 0.8)
        self.assertLess(streaming_first, oneshot_first)
        self.assertIn(FIRST_SENTENCE.strip("。"), streaming_avatar.events[0]["text"])
