import unittest

from src.config.schema import Config
from src.llm.answer_board import (
    BOARD_END,
    BOARD_START,
    AnswerBoardSplitter,
    parse_board_block,
)
from src.llm.base import BaseLLM


class ParseBoardBlockTests(unittest.TestCase):
    def test_parses_titled_list(self):
        payload = parse_board_block(
            "標題：第一次展示\n"
            "- 先定義目標：選定一個情境。\n"
            "- 確認聲音：用短句試播。\n"
            "- 彩排插話：確認新舊內容不混。"
        )
        self.assertIsNotNone(payload)
        self.assertEqual(payload.title, "第一次展示")
        self.assertEqual(len(payload.items), 3)
        self.assertEqual(payload.items[0].title, "先定義目標")
        self.assertEqual(payload.items[0].body, "選定一個情境。")

    def test_rejects_single_item(self):
        self.assertIsNone(parse_board_block("標題：只有一項\n- 問候：你好"))


class AnswerBoardSplitterTests(unittest.TestCase):
    def test_simple_reply_passes_through(self):
        splitter = AnswerBoardSplitter()
        spoken = splitter.feed("你好，我可以幫忙。")
        tail, board = splitter.flush()
        self.assertEqual("".join(spoken) + tail, "你好，我可以幫忙。")
        self.assertIsNone(board)

    def test_holds_partial_marker_then_splits(self):
        splitter = AnswerBoardSplitter()
        first = splitter.feed("先看結論。<<<BO")
        second = splitter.feed(f"ARD\n標題：準備流程\n- 目標：選定情境。\n- 聲音：試播。\n{BOARD_END}")
        tail, board = splitter.flush()
        self.assertEqual("".join(first + second) + tail, "先看結論。")
        self.assertEqual(board.title, "準備流程")
        self.assertEqual([item.title for item in board.items], ["目標", "聲音"])


class GenerateResponseBoardTests(unittest.TestCase):
    def test_board_markup_is_not_queued_for_speech(self):
        class FakeLLM(BaseLLM):
            def chat_stream(self, message, system_prompt=None):
                del message, system_prompt
                yield "先確認目標，再檢查人物與聲音。"
                yield f"\n{BOARD_START}\n標題：第一次展示\n- 目標：選定情境。\n- 聲音：試播短句。\n{BOARD_END}"

        class FakeAvatar:
            def __init__(self):
                self.fragments = []

            def put_msg_txt(self, text, data):
                self.fragments.append(text)

        events = []
        avatar = FakeAvatar()
        spoken = FakeLLM(Config()).generate_response(
            "規劃展示",
            avatar,
            datainfo={
                "turn_id": "turn-board",
                "generation": 1,
                "on_board": events.append,
            },
        )
        self.assertIn("先確認目標", spoken)
        self.assertNotIn(BOARD_START, spoken)
        self.assertTrue(all(BOARD_START not in text for text in avatar.fragments))
        kinds = [event["kind"] for event in events]
        self.assertEqual(kinds[0], "begin")
        self.assertIn("item", kinds)
        self.assertEqual(kinds[-1], "end")
        self.assertEqual(events[0]["title"], "第一次展示")
