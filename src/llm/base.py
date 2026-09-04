"""LLM 基類模組"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable, Generator, Optional
from uuid import uuid4

from src.server.reply_streaming.fragmenter import SemanticFragmenter
from src.utils.logging import logger

if TYPE_CHECKING:
    from src.avatars.base import BaseAvatar


DEFAULT_SYSTEM_PROMPT = 'You are a helpful assistant.'
DEFAULT_RESPONSE_MAX_CHARS = 120
MIN_RESPONSE_MAX_CHARS = 20
MAX_RESPONSE_MAX_CHARS = 2000
# 只在完整句尾切給 TTS。逗號與冒號屬於句內停頓，拆開合成會重置韻律，
# 也會讓 Avatar 在相鄰 TTS 請求之間提前填入靜音幀。
SENTENCE_DELIMITERS = ".!?;。！？；"
MIN_SENTENCE_LENGTH = 24


def validate_response_max_chars(value) -> int:
    """驗證並正規化使用者可調整的約略回覆字數。"""
    if isinstance(value, bool):
        raise ValueError("回覆字數必須是整數")
    try:
        normalized = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("回覆字數必須是整數") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError("回覆字數必須是整數")
    if not MIN_RESPONSE_MAX_CHARS <= normalized <= MAX_RESPONSE_MAX_CHARS:
        raise ValueError(
            f"回覆字數必須介於 {MIN_RESPONSE_MAX_CHARS} 到 {MAX_RESPONSE_MAX_CHARS} 之間"
        )
    return normalized


def response_token_budget(max_chars: int) -> int:
    """Safety ceiling above the character target so the last sentence can finish."""
    estimated = max(64, math.ceil(max_chars * 2.5) + 32)
    return min(4096, estimated)


def with_response_length_instruction(system_prompt: str, max_chars: int) -> str:
    """加入隱藏的柔性長度指令，不污染使用者可編輯的 Prompt。"""
    prompt = (system_prompt or DEFAULT_SYSTEM_PROMPT).rstrip()
    return (
        f"{prompt}\n\n【回覆長度】每次回答必須是結構完整的短答，總長度約 {max_chars} 個字。"
        "先在限制內把話說完；不要開一個無法在限制內結束的長句或列表。"
        "禁止在句子或條目中途停止。"
    )


def load_system_prompt(config=None) -> str:
    """取得設定中的預設 Prompt，未設定時沿用 config/prompt.txt。"""
    llm_config = getattr(config, "llm", None) if config is not None else None
    configured_prompt = getattr(llm_config, "system_prompt", "") or ""
    if configured_prompt.strip():
        return configured_prompt.strip()

    from pathlib import Path

    prompt_file = Path(__file__).parent.parent.parent / "config" / "prompt.txt"
    try:
        prompt = prompt_file.read_text(encoding="utf-8").strip()
        return prompt or DEFAULT_SYSTEM_PROMPT
    except FileNotFoundError:
        logger.warning(f"Prompt file not found: {prompt_file}, using default")
    except Exception as exc:
        logger.error(f"Error loading prompt: {exc}, using default")
    return DEFAULT_SYSTEM_PROMPT


class TextStreamProcessor:
    """文本流處理器，負責分句和緩衝"""
    
    def __init__(self, delimiters: str = SENTENCE_DELIMITERS, min_length: int = MIN_SENTENCE_LENGTH):
        self.delimiters = delimiters
        self.min_length = min_length
        self.buffer = ""
    
    def process_chunk(self, text: str, callback) -> None:
        if not text:
            return
        
        # 以標點為分隔符，儘量保持語義完整再發給 TTS
        last_pos = 0
        for i, char in enumerate(text):
            if char in self.delimiters:
                sentence = self.buffer + text[last_pos:i + 1]
                last_pos = i + 1
                
                if len(sentence) >= self.min_length:
                    callback(sentence)
                    self.buffer = ""
                else:
                    self.buffer = sentence
        
        self.buffer += text[last_pos:]
    
    def flush(self, callback) -> None:
        if self.buffer:
            callback(self.buffer)
            self.buffer = ""


class BaseLLM(ABC):
    """所有 LLM 引擎的基類"""
    
    def __init__(self, config, parent: Optional["BaseAvatar"] = None):
        self.config = config
        self.parent = parent
        self.system_prompt = self._load_system_prompt()
    
    def _load_system_prompt(self) -> str:
        return load_system_prompt(self.config)
    
    @abstractmethod
    def chat_stream(self, message: str, system_prompt: Optional[str] = None) -> Generator[str, None, None]:
        """流式呼叫 LLM，子類必須實現"""
        raise NotImplementedError("子類必須實現 chat_stream 方法")
    
    def generate_response(
        self,
        message: str,
        avatar_stream: Optional["BaseAvatar"] = None,
        *,
        stream_to_avatar: bool = True,
        datainfo: Optional[dict] = None,
        chunk_guard: Optional[Callable[[int], bool]] = None,
        defer_history_commit: bool = False,
    ) -> str:
        """生成完整響應並推送到 avatar"""
        start_time = time.perf_counter()
        semantic_stream = bool(
            stream_to_avatar
            and datainfo
            and datainfo.get("turn_id")
            and datainfo.get("generation") is not None
        )
        text_processor = (
            SemanticFragmenter()
            if semantic_stream
            else TextStreamProcessor()
        )
        full_response = ""
        fenced = False
        history_transaction = None
        history_committed = False

        begin_history = getattr(self, "begin_history_turn", None)
        if callable(begin_history):
            turn_id = str((datainfo or {}).get("turn_id") or uuid4().hex)
            history_transaction = begin_history(message, turn_id=turn_id)
        
        target_avatar = (avatar_stream or self.parent) if stream_to_avatar else None
        fragment_sequence = 0
        
        def send_to_avatar(text: str) -> None:
            nonlocal fragment_sequence
            if target_avatar:
                fragment_info = dict(datainfo or {})
                if (
                    fragment_info.get("turn_id")
                    and fragment_info.get("generation") is not None
                ):
                    fragment_info["fragment_sequence"] = fragment_sequence
                    logger.info(
                        "Queueing turn-aware LLM fragment sequence=%d",
                        fragment_sequence,
                    )
                else:
                    logger.info("Queueing legacy LLM fragment")
                target_avatar.put_msg_txt(text, fragment_info)
                fragment_sequence += 1
        
        try:
            # 記錄首包延遲，方便定位 LLM 響應瓶頸
            first_chunk = True
            if history_transaction is None:
                chunks = self.chat_stream(message)
            else:
                chunks = self.chat_stream(
                    message,
                    history_transaction=history_transaction,
                )
            for sequence, chunk in enumerate(chunks):
                if chunk_guard is not None and not chunk_guard(sequence):
                    fenced = True
                    break
                if first_chunk:
                    first_chunk_time = time.perf_counter()
                    logger.info(f"Time to first chunk: {first_chunk_time - start_time:.3f}s")
                    first_chunk = False
                
                full_response += chunk

                if target_avatar and semantic_stream:
                    notify_chunk = getattr(target_avatar, "notify_llm_chunk", None)
                    if callable(notify_chunk):
                        notify_chunk(
                            chunk,
                            {
                                **dict(datainfo or {}),
                                "llm_sequence": sequence,
                            },
                        )
                
                if target_avatar:
                    if semantic_stream:
                        for fragment in text_processor.feed(chunk):
                            send_to_avatar(fragment)
                    else:
                        text_processor.process_chunk(chunk, send_to_avatar)
            
            if target_avatar:
                if semantic_stream:
                    for fragment in text_processor.flush():
                        send_to_avatar(fragment)
                else:
                    text_processor.flush(send_to_avatar)
            
            total_time = time.perf_counter()
            logger.info(f"Total LLM response time: {total_time - start_time:.3f}s")

            if history_transaction is not None and not defer_history_commit:
                self.commit_history_turn(
                    history_transaction,
                    assistant_text="" if fenced else full_response,
                    terminal_reason="cancelled" if fenced else "completed",
                )
                history_committed = True
            
            return full_response
            
        except Exception as e:
            if (
                history_transaction is not None
                and not history_committed
                and not defer_history_commit
            ):
                try:
                    self.commit_history_turn(
                        history_transaction,
                        assistant_text="",
                        terminal_reason="llm_error",
                    )
                except Exception:
                    logger.exception("Failed to commit terminal LLM history transaction")
            logger.error("LLM response generation failed: %s", type(e).__name__)
            raise
