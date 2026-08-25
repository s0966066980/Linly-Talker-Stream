"""設定面板寫入的執行時覆蓋，啟動時疊在主配置之上。"""
from __future__ import annotations

from typing import Any, Dict

import yaml

from src.utils.logging import logger
from src.utils.paths import get_config_dir

RUNTIME_OVERRIDES_FILE = get_config_dir() / "runtime_overrides.yaml"


def load_runtime_overrides() -> Dict[str, Any]:
    if not RUNTIME_OVERRIDES_FILE.exists():
        return {}
    try:
        data = yaml.safe_load(RUNTIME_OVERRIDES_FILE.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning(f"讀取 runtime_overrides.yaml 失敗: {exc}")
        return {}


def persist_runtime_overrides(config) -> None:
    payload = {
        "llm": {
            "model": config.llm.model,
            "provider": getattr(config.llm, "provider", "ollama"),
            "base_url": getattr(config.llm, "base_url", ""),
            "api_key": getattr(config.llm, "api_key", ""),
            "max_tokens": getattr(config.llm, "max_tokens", 128),
            "response_max_chars": getattr(config.llm, "response_max_chars", 120),
            "system_prompt": getattr(config.llm, "system_prompt", ""),
            "extra_body": getattr(config.llm, "extra_body", {}) or {},
        },
        "model": {
            "type": config.model.type,
            "avatar_id": config.model.avatar_id,
        },
    }

    vad = getattr(config, "vad", None)
    if vad is not None:
        payload["vad"] = {
            "enabled": bool(vad.enabled),
            "type": vad.type,
            "threshold": float(vad.threshold),
            "aggressiveness": int(vad.aggressiveness),
            "min_speech_ms": int(vad.min_speech_ms),
            "min_silence_ms": int(vad.min_silence_ms),
            "speech_pad_ms": int(vad.speech_pad_ms),
        }

    asr = getattr(config, "asr", None)
    if asr is not None:
        payload["asr"] = {
            "mode": "server",
            "type": asr.type,
            "model_size": asr.model_size,
            "language": asr.language,
            "device": asr.device,
        }
    tts = getattr(config, "tts", None)
    if tts is not None:
        payload["tts"] = {
            "type": tts.type,
            "ref_file": tts.ref_file,
            "ref_text": tts.ref_text,
            "tts_server": tts.tts_server,
            "model": tts.model,
            "language": tts.language,
            "speaker": tts.speaker,
            "instruct": tts.instruct,
            "device": tts.device,
        }
    RUNTIME_OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# 由設定面板自動生成，請勿手改關鍵結構。\n"
        "# 會在啟動時覆蓋主配置中的 llm / model / vad / asr / tts。\n"
    )
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    RUNTIME_OVERRIDES_FILE.write_text(header + text, encoding="utf-8")
