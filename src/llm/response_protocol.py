"""Streaming response protocol parser, thinking suppression, and board validation.

Provides streaming separation of conversational speech and visual board JSON,
with robust stateful suppression of <think>...</think> tags across chunk boundaries.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generator, Optional

from src.llm.router import ReplyMode

logger = logging.getLogger(__name__)

TAG_SPEECH = "[[SPEECH]]"
TAG_BOARD = "[[BOARD_JSON]]"
TAG_END = "[[END]]"

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


@dataclass
class BoardItem:
    """A single item inside an answer board."""

    title: str
    content: str
    subtitle: Optional[str] = None
    badge: Optional[str] = None

    @property
    def body(self) -> str:
        """Backward-compatibility alias for body/content."""
        return self.content


@dataclass
class BoardPayload:
    """Structured data for an answer board."""

    title: str
    summary: Optional[str] = None
    items: list[BoardItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "items": [
                {
                    "title": item.title,
                    "content": item.content,
                    "body": item.content,
                    **({"subtitle": item.subtitle} if item.subtitle else {}),
                    **({"badge": item.badge} if item.badge else {}),
                }
                for item in self.items
            ],
        }


@dataclass
class SessionBoardContext:
    """Recent board state retained per session for follow-up queries."""

    turn_id: str
    title: str
    summary: Optional[str]
    items: list[BoardItem]
    created_at: float = field(default_factory=time.time)


class ThinkFilter:
    """Stateful stream filter that suppresses <think>...</think> blocks.

    Handles opening and closing tags that may be split arbitrarily across chunks
    (e.g. '<th' + 'ink>', '</thi' + 'nk>').
    """

    def __init__(self) -> None:
        self._in_think = False
        self._buffer = ""

    def feed(self, chunk: str) -> list[str]:
        if not chunk:
            return []

        self._buffer += chunk
        out: list[str] = []

        while self._buffer:
            if not self._in_think:
                pos = self._buffer.find(THINK_OPEN)
                if pos != -1:
                    pre = self._buffer[:pos]
                    if pre:
                        out.append(pre)
                    self._buffer = self._buffer[pos + len(THINK_OPEN) :]
                    self._in_think = True
                    continue

                # Buffer might end with a partial prefix of <think>
                hold_len = self._prefix_overlap(self._buffer, THINK_OPEN)
                if hold_len > 0:
                    emit_len = len(self._buffer) - hold_len
                    if emit_len > 0:
                        out.append(self._buffer[:emit_len])
                        self._buffer = self._buffer[emit_len:]
                    break
                else:
                    out.append(self._buffer)
                    self._buffer = ""
                    break
            else:
                # Inside thinking block: discard text until </think> is found
                pos = self._buffer.find(THINK_CLOSE)
                if pos != -1:
                    self._buffer = self._buffer[pos + len(THINK_CLOSE) :]
                    self._in_think = False
                    continue

                # Buffer might end with a partial prefix of </think>
                hold_len = self._prefix_overlap(self._buffer, THINK_CLOSE)
                if hold_len > 0:
                    self._buffer = self._buffer[-hold_len:]
                else:
                    self._buffer = ""
                break

        return [s for s in out if s]

    def flush(self) -> list[str]:
        """Flush any held characters at the end of the stream."""
        out: list[str] = []
        if not self._in_think and self._buffer:
            out.append(self._buffer)
        self._buffer = ""
        self._in_think = False
        return [s for s in out if s]

    @staticmethod
    def _prefix_overlap(text: str, target: str) -> int:
        """Returns the length of the longest suffix of `text` that is a prefix of `target`."""
        max_k = min(len(text), len(target) - 1)
        for k in range(max_k, 0, -1):
            if target.startswith(text[-k:]):
                return k
        return 0


class ParserState(str, Enum):
    WAIT_SPEECH = "wait_speech"
    IN_SPEECH = "in_speech"
    WAIT_BOARD = "wait_board"
    IN_BOARD = "in_board"
    DONE = "done"


class ResponseProtocolParser:
    """Streaming state machine for parsing speech and board channels.

    Guarantees:
    1. Speech chunks are emitted immediately (zero waiting for the board).
    2. Thinking tags are suppressed across chunk boundaries.
    3. Protocol tags ([[SPEECH]], [[BOARD_JSON]], [[END]]) never leak into speech.
    4. Board JSON is buffered separately and parsed at [[END]] or stream end.
    5. Malformed board JSON logs a warning without crashing or discarding speech.
    """

    def __init__(
        self,
        mode: ReplyMode = ReplyMode.SIMPLE,
        *,
        max_items: int = 8,
        on_speech: Optional[Callable[[str], None]] = None,
        on_board: Optional[Callable[[BoardPayload], None]] = None,
    ) -> None:
        self.mode = mode
        self.max_items = max_items
        self.on_speech = on_speech
        self.on_board = on_board

        self._think_filter = ThinkFilter()
        self._state = ParserState.WAIT_SPEECH if mode == ReplyMode.BOARD else ParserState.IN_SPEECH
        self._buffer = ""
        self._board_buffer = ""
        self._speech_accumulator = ""
        self._board_payload: Optional[BoardPayload] = None

    @property
    def speech_text(self) -> str:
        return self._speech_accumulator

    @property
    def board_payload(self) -> Optional[BoardPayload]:
        return self._board_payload

    def feed(self, chunk: str) -> list[str]:
        """Feed a raw LLM chunk. Returns a list of speech chunks to output."""
        clean_chunks = self._think_filter.feed(chunk)
        if not clean_chunks:
            return []

        speech_outputs: list[str] = []
        for clean_text in clean_chunks:
            if self.mode == ReplyMode.SIMPLE:
                self._speech_accumulator += clean_text
                speech_outputs.append(clean_text)
                if self.on_speech:
                    self.on_speech(clean_text)
            else:
                outputs = self._process_board_mode_chunk(clean_text)
                speech_outputs.extend(outputs)

        return speech_outputs

    def _process_board_mode_chunk(self, chunk: str) -> list[str]:
        self._buffer += chunk
        speech_outputs: list[str] = []

        while self._buffer:
            if self._state == ParserState.WAIT_SPEECH:
                pos = self._buffer.find(TAG_SPEECH)
                if pos != -1:
                    # Found [[SPEECH]]
                    self._buffer = self._buffer[pos + len(TAG_SPEECH) :].lstrip("\r\n ")
                    self._state = ParserState.IN_SPEECH
                    continue

                # Check if buffer could be a prefix of [[SPEECH]]
                overlap = ThinkFilter._prefix_overlap(self._buffer, TAG_SPEECH)
                if overlap > 0:
                    # Keep overlap, check if preceding text exists
                    pre = self._buffer[:-overlap]
                    if pre.strip():
                        # Model didn't output [[SPEECH]], went straight to text
                        self._state = ParserState.IN_SPEECH
                        self._speech_accumulator += pre
                        speech_outputs.append(pre)
                        if self.on_speech:
                            self.on_speech(pre)
                        self._buffer = self._buffer[-overlap:]
                    break
                else:
                    # If buffer has non-prefix characters, model skipped [[SPEECH]]
                    if self._buffer.strip():
                        self._state = ParserState.IN_SPEECH
                        text = self._buffer
                        self._buffer = ""
                        self._speech_accumulator += text
                        speech_outputs.append(text)
                        if self.on_speech:
                            self.on_speech(text)
                    else:
                        break

            elif self._state == ParserState.IN_SPEECH:
                pos = self._buffer.find(TAG_BOARD)
                if pos != -1:
                    # Speech section ends here
                    speech_part = self._buffer[:pos]
                    if speech_part:
                        self._speech_accumulator += speech_part
                        speech_outputs.append(speech_part)
                        if self.on_speech:
                            self.on_speech(speech_part)
                    self._buffer = self._buffer[pos + len(TAG_BOARD) :].lstrip("\r\n ")
                    self._state = ParserState.IN_BOARD
                    continue

                # Check if buffer ends with a prefix of [[BOARD_JSON]]
                overlap = ThinkFilter._prefix_overlap(self._buffer, TAG_BOARD)
                if overlap > 0:
                    emit_len = len(self._buffer) - overlap
                    if emit_len > 0:
                        part = self._buffer[:emit_len]
                        self._speech_accumulator += part
                        speech_outputs.append(part)
                        if self.on_speech:
                            self.on_speech(part)
                        self._buffer = self._buffer[emit_len:]
                    break
                else:
                    part = self._buffer
                    self._buffer = ""
                    self._speech_accumulator += part
                    speech_outputs.append(part)
                    if self.on_speech:
                        self.on_speech(part)
                    break

            elif self._state == ParserState.IN_BOARD:
                pos = self._buffer.find(TAG_END)
                if pos != -1:
                    board_part = self._buffer[:pos]
                    self._board_buffer += board_part
                    self._buffer = self._buffer[pos + len(TAG_END) :]
                    self._state = ParserState.DONE
                    self._parse_and_emit_board()
                    continue

                # Check if buffer ends with a prefix of [[END]]
                overlap = ThinkFilter._prefix_overlap(self._buffer, TAG_END)
                if overlap > 0:
                    emit_len = len(self._buffer) - overlap
                    if emit_len > 0:
                        self._board_buffer += self._buffer[:emit_len]
                        self._buffer = self._buffer[emit_len:]
                    break
                else:
                    self._board_buffer += self._buffer
                    self._buffer = ""
                    break

            elif self._state == ParserState.DONE:
                self._buffer = ""
                break

        return speech_outputs

    def flush(self) -> tuple[list[str], Optional[BoardPayload]]:
        """Flush any held buffers and finalize board JSON parsing."""
        clean_chunks = self._think_filter.flush()
        speech_outputs: list[str] = []

        for clean_text in clean_chunks:
            if self.mode == ReplyMode.SIMPLE:
                self._speech_accumulator += clean_text
                speech_outputs.append(clean_text)
                if self.on_speech:
                    self.on_speech(clean_text)
            else:
                outputs = self._process_board_mode_chunk(clean_text)
                speech_outputs.extend(outputs)

        if self.mode == ReplyMode.BOARD:
            if self._state == ParserState.IN_SPEECH and self._buffer:
                # No board was started; whatever remains is speech
                leftover = self._buffer
                self._buffer = ""
                self._speech_accumulator += leftover
                speech_outputs.append(leftover)
                if self.on_speech:
                    self.on_speech(leftover)
            elif self._state == ParserState.IN_BOARD:
                if self._buffer:
                    self._board_buffer += self._buffer
                    self._buffer = ""
                self._state = ParserState.DONE
                self._parse_and_emit_board()

        return speech_outputs, self._board_payload

    def _parse_and_emit_board(self) -> None:
        raw = self._board_buffer.strip()
        if not raw:
            return

        # Strip markdown fences if present (e.g. ```json ... ```)
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                logger.warning("board_parse_success=false reason=json_root_not_dict")
                return

            title = str(parsed.get("title") or "看板回覆").strip()
            summary = parsed.get("summary")
            if summary is not None:
                summary = str(summary).strip() or None

            raw_items = parsed.get("items") or []
            if not isinstance(raw_items, list):
                raw_items = []

            items: list[BoardItem] = []
            for entry in raw_items:
                if isinstance(entry, dict):
                    i_title = str(entry.get("title") or "").strip()
                    i_content = str(
                        entry.get("content") or entry.get("body") or entry.get("description") or ""
                    ).strip()
                    if i_title or i_content:
                        items.append(
                            BoardItem(
                                title=i_title or i_content,
                                content=i_content,
                                subtitle=str(entry.get("subtitle")).strip() if entry.get("subtitle") else None,
                                badge=str(entry.get("badge")).strip() if entry.get("badge") else None,
                            )
                        )
                elif isinstance(entry, str) and entry.strip():
                    items.append(BoardItem(title=entry.strip(), content=""))

            # Truncate items to max_items
            if len(items) > self.max_items:
                logger.info(
                    "Truncating board items from %d to max_items=%d",
                    len(items),
                    self.max_items,
                )
                items = items[: self.max_items]

            if not items:
                logger.warning("board_parse_success=false reason=empty_items")
                return

            payload = BoardPayload(title=title, summary=summary, items=items)
            self._board_payload = payload
            logger.info(
                "board_parse_success=true board_items=%d title=%r",
                len(items),
                title,
            )
            if self.on_board:
                self.on_board(payload)

        except json.JSONDecodeError as exc:
            logger.warning(
                "board_parse_success=false error=%s raw_length=%d",
                exc,
                len(raw),
            )
            # Fault tolerance: do not raise or crash
        except Exception as exc:
            logger.warning("board_parse_success=false unexpected_error=%s", exc)
