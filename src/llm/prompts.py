"""Runtime prompt composition for SIMPLE and BOARD reply modes."""

from __future__ import annotations

from typing import Optional

from src.llm.router import ReplyMode

DEFAULT_BASE_PROMPT = "You are a helpful assistant."

SIMPLE_MODE_PROMPT = (
    "You are answering in SIMPLE mode.\n\n"
    "Respond naturally and directly.\n"
    "Do not artificially produce a long list or board structure unless necessary.\n"
    "Keep the answer concise enough for spoken conversation."
)

BOARD_MODE_PROMPT = """You are answering in BOARD mode.

Your response has two separate channels:
SPEECH
BOARD_JSON

Output exactly in this format:
[[SPEECH]]
<short conversational summary>

[[BOARD_JSON]]
<valid JSON>

[[END]]

Rules:
SPEECH:
- Must be natural spoken language.
- Explain the overall conclusion only.
- Do NOT read every board item.
- Do NOT say "first item", "second item", etc unless essential.
- Prefer about 1-3 sentences.
- Must make sense without seeing the board.

BOARD_JSON:
- Contains the structured details.
- Must be valid JSON.
- Do not use Markdown fences.
- Do not include comments.
- Do not repeat unnecessary prose from SPEECH.

Schema:
{
  "title": "string",
  "summary": "optional string",
  "items": [
    {
      "title": "string",
      "content": "string"
    }
  ]
}"""


def compose_system_prompt(
    base_prompt: str,
    reply_mode: ReplyMode = ReplyMode.SIMPLE,
    response_max_chars: Optional[int] = None,
) -> str:
    """Compose runtime system prompt without mutating base configuration.

    Combines:
    1. Base system prompt (user editable)
    2. Mode instruction (SIMPLE / BOARD)
    3. Response length instruction (optional soft ceiling)
    """
    base = (base_prompt or DEFAULT_BASE_PROMPT).strip()
    mode_instruction = (
        BOARD_MODE_PROMPT if reply_mode == ReplyMode.BOARD else SIMPLE_MODE_PROMPT
    )

    parts = [base, mode_instruction]

    if response_max_chars is not None and response_max_chars > 0:
        length_instruction = (
            f"【回覆長度】每次回答必須是結構完整的短答，總長度約 {response_max_chars} 個字。"
            "先在限制內把話說完；不要開一個無法在限制內結束的長句或列表。"
            "禁止在句子或條目中途停止。"
        )
        parts.append(length_instruction)

    return "\n\n".join(parts)
