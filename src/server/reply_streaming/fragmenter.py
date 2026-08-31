"""Incremental semantic text fragmentation for reply speech."""
from __future__ import annotations


STRONG_PUNCTUATION = frozenset("。！？；.!?;")
WEAK_PUNCTUATION = frozenset("，、：,:")


def _content_length(text: str) -> int:
    return sum(character.isalnum() for character in text)


class SemanticFragmenter:
    """Turn arbitrary LLM token boundaries into playable text fragments."""

    def __init__(
        self,
        *,
        weak_min_chars: int = 12,
        soft_limit_chars: int = 24,
        hard_limit_chars: int = 32,
    ) -> None:
        if weak_min_chars < 1:
            raise ValueError("weak punctuation threshold must be positive")
        if soft_limit_chars < weak_min_chars:
            raise ValueError("soft limit cannot be below weak punctuation threshold")
        if hard_limit_chars < soft_limit_chars:
            raise ValueError("hard limit cannot be below soft limit")
        self._weak_min_chars = weak_min_chars
        self._soft_limit_chars = soft_limit_chars
        self._hard_limit_chars = hard_limit_chars
        self._buffer = ""

    @property
    def buffered_text(self) -> str:
        return self._buffer

    def feed(self, token: str) -> list[str]:
        if token:
            self._buffer += token
        fragments: list[str] = []
        while self._buffer:
            boundaries = [
                boundary
                for boundary in (
                    self._punctuation_boundary(),
                    self._length_boundary(),
                )
                if boundary is not None
            ]
            split_at = min(boundaries) if boundaries else None
            if split_at is None:
                break
            fragment = self._buffer[:split_at].strip()
            self._buffer = self._buffer[split_at:]
            if fragment:
                fragments.append(fragment)
        return fragments

    def flush(self) -> list[str]:
        fragment = self._buffer.strip()
        self._buffer = ""
        return [fragment] if fragment else []

    def _punctuation_boundary(self) -> int | None:
        for index, character in enumerate(self._buffer):
            if self._is_numeric_punctuation(index):
                continue
            if character in STRONG_PUNCTUATION:
                return index + 1
            if (
                character in WEAK_PUNCTUATION
                and _content_length(self._buffer[: index + 1]) >= self._weak_min_chars
            ):
                return index + 1
        return None

    def _length_boundary(self) -> int | None:
        content_chars = 0
        reached_hard_limit = False
        for boundary, character in enumerate(self._buffer, start=1):
            if character.isalnum():
                content_chars += 1
            if content_chars < self._soft_limit_chars:
                continue
            if content_chars >= self._hard_limit_chars:
                reached_hard_limit = True
            if self._is_safe_boundary(boundary):
                return boundary
            # A long English word, numeric sequence, or marker may legitimately
            # cross 32 characters. Keep reading only until its next safe edge.
            if reached_hard_limit:
                continue
        return None

    def _is_numeric_punctuation(self, index: int) -> bool:
        if self._buffer[index] not in STRONG_PUNCTUATION | WEAK_PUNCTUATION:
            return False
        if index == 0 or index + 1 >= len(self._buffer):
            return False
        return self._buffer[index - 1].isdigit() and self._buffer[index + 1].isdigit()

    def _is_safe_boundary(self, boundary: int) -> bool:
        prefix = self._buffer[:boundary]
        if prefix.count("`") % 2:
            return False
        if prefix.rfind("<") > prefix.rfind(">"):
            return False
        left = self._buffer[boundary - 1]
        if boundary >= len(self._buffer):
            return not self._is_ascii_word_character(left)
        right = self._buffer[boundary]
        # Prefer the punctuation boundary that follows this content instead
        # of emitting a fragment that leaves a sentence-final mark behind.
        if right in STRONG_PUNCTUATION | WEAK_PUNCTUATION:
            return False
        if self._is_ascii_word_character(left) and self._is_ascii_word_character(right):
            return False
        return True

    @staticmethod
    def _is_ascii_word_character(character: str) -> bool:
        return character.isascii() and (character.isalnum() or character in "_'-")
