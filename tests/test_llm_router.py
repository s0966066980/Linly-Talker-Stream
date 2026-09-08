import time
import unittest
from unittest.mock import MagicMock

from src.llm.router import (
    LLMFallbackClassifier,
    ReplyMode,
    ReplyModePreference,
    ReplyRoute,
    ReplyRouter,
    RuleRouter,
)


class RuleRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = RuleRouter(board_threshold=3.0, simple_threshold=0.0)

    def test_simple_queries(self):
        cases = [
            "你好",
            "您好！",
            "LLM 是什麼？",
            "PostgreSQL 要錢嗎？",
            "可以嗎？",
            "為什麼？",
            "現在幾點？",
        ]
        for query in cases:
            with self.subTest(query=query):
                mode, score, reason = self.router.evaluate(query)
                self.assertEqual(
                    mode,
                    ReplyMode.SIMPLE,
                    f"Expected SIMPLE for {query!r}, got {mode} (score={score}, reason={reason})",
                )

    def test_board_queries(self):
        cases = [
            "列出三種實作方式",
            "幫我整理 Python 學習清單",
            "比較 PostgreSQL、MySQL、SQLite",
            "我要怎麼部署？列出完整步驟",
            "分析這個專案需要哪些 skill",
            "給我五個建議",
            "有哪些方法可以改善？",
            "設計一個完整開發流程",
            "列出目前所有可以使用的方法",
        ]
        for query in cases:
            with self.subTest(query=query):
                mode, score, reason = self.router.evaluate(query)
                self.assertEqual(
                    mode,
                    ReplyMode.BOARD,
                    f"Expected BOARD for {query!r}, got {mode} (score={score}, reason={reason})",
                )

    def test_edge_cases(self):
        # 1. 介紹 PostgreSQL -> SIMPLE
        mode, score, reason = self.router.evaluate("介紹 PostgreSQL")
        self.assertEqual(mode, ReplyMode.SIMPLE, f"score={score}, reason={reason}")

        # 2. 詳細介紹 PostgreSQL -> SIMPLE
        mode, score, reason = self.router.evaluate("詳細介紹 PostgreSQL")
        self.assertEqual(mode, ReplyMode.SIMPLE, f"score={score}, reason={reason}")

        # 3. PostgreSQL 有哪些優點？ -> BOARD
        mode, score, reason = self.router.evaluate("PostgreSQL 有哪些優點？")
        self.assertEqual(mode, ReplyMode.BOARD, f"score={score}, reason={reason}")

        # 4. PostgreSQL 跟 MySQL 差在哪？ -> BOARD
        mode, score, reason = self.router.evaluate("PostgreSQL 跟 MySQL 差在哪？")
        self.assertEqual(mode, ReplyMode.BOARD, f"score={score}, reason={reason}")

        # 5. 我該怎麼選？ -> AMBIGUOUS (score between 0 and 3)
        mode, score, reason = self.router.evaluate("我該怎麼選？")
        self.assertEqual(mode, ReplyMode.AMBIGUOUS, f"score={score}, reason={reason}")

    def test_performance_sub_two_milliseconds(self):
        queries = [
            "你好",
            "列出三種實作方式",
            "幫我規劃這個專案的架構並給出五個步驟與比較",
            "PostgreSQL 要錢嗎？",
        ]
        for query in queries:
            start = time.perf_counter()
            for _ in range(100):
                self.router.evaluate(query)
            avg_ms = ((time.perf_counter() - start) / 100) * 1000.0
            self.assertLess(
                avg_ms,
                2.0,
                f"Rule router too slow ({avg_ms:.3f}ms) on {query!r}",
            )


class LLMFallbackClassifierTests(unittest.TestCase):
    def test_classify_board_token(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "BOARD"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

        classifier = LLMFallbackClassifier(llm_client_getter=lambda: mock_client)
        mode, reason = classifier.classify("這兩個架構在效能上有何差別？")
        self.assertEqual(mode, ReplyMode.BOARD)
        self.assertIn("llm_classified_board", reason)

    def test_classify_simple_token(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "SIMPLE"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

        classifier = LLMFallbackClassifier(llm_client_getter=lambda: mock_client)
        mode, reason = classifier.classify("今天天氣如何？")
        self.assertEqual(mode, ReplyMode.SIMPLE)
        self.assertIn("llm_classified_simple", reason)

    def test_classify_unrecognized_output_falls_back_to_simple(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "I don't know"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

        classifier = LLMFallbackClassifier(llm_client_getter=lambda: mock_client)
        mode, reason = classifier.classify("模糊問題")
        self.assertEqual(mode, ReplyMode.SIMPLE)

    def test_classify_exception_falls_back_to_simple(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = TimeoutError("Connection timed out")

        classifier = LLMFallbackClassifier(llm_client_getter=lambda: mock_client)
        mode, reason = classifier.classify("模糊問題")
        self.assertEqual(mode, ReplyMode.SIMPLE)
        self.assertIn("llm_classifier_error", reason)


class ReplyRouterOrchestrationTests(unittest.TestCase):
    def test_forced_mode(self):
        router = ReplyRouter()
        route_simple = router.route("列出三種實作方式", preference=ReplyModePreference.SIMPLE)
        self.assertEqual(route_simple.mode, ReplyMode.SIMPLE)
        self.assertEqual(route_simple.source, "forced")

        route_board = router.route("你好", preference="board")
        self.assertEqual(route_board.mode, ReplyMode.BOARD)
        self.assertEqual(route_board.source, "forced")

    def test_disabled_router_falls_back_to_simple(self):
        router = ReplyRouter(enabled=False)
        route = router.route("列出五個步驟")
        self.assertEqual(route.mode, ReplyMode.SIMPLE)
        self.assertEqual(route.source, "disabled")

    def test_ambiguous_triggers_llm_fallback(self):
        mock_client = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "BOARD"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])

        classifier = LLMFallbackClassifier(llm_client_getter=lambda: mock_client)
        router = ReplyRouter(classifier=classifier)

        # "我該怎麼選？" is ambiguous in rule router
        route = router.route("我該怎麼選？")
        self.assertEqual(route.mode, ReplyMode.BOARD)
        self.assertEqual(route.source, "llm")
