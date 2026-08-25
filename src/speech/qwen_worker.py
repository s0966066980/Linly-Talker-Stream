"""Standalone Qwen3-ASR/TTS worker. Run only inside the isolated environment."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import traceback

os.environ.setdefault("USE_TF", "0")

RESPONSE_PREFIX = "__QWEN_SPEECH_RPC__"
model = None
model_kind = ""


def respond(**payload):
    print(RESPONSE_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)


def load_model(command):
    global model, model_kind
    import torch

    model_kind = command["kind"]
    device = command.get("device", "auto")
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    device_map = "cuda:0" if device == "cuda" else "cpu"
    dtype = torch.bfloat16 if device == "cuda" else torch.float32
    with contextlib.redirect_stdout(sys.stderr):
        if model_kind == "asr":
            from qwen_asr import Qwen3ASRModel

            model = Qwen3ASRModel.from_pretrained(
                command["model"],
                dtype=dtype,
                device_map=device_map,
                max_inference_batch_size=1,
                max_new_tokens=256,
            )
        elif model_kind == "tts":
            from qwen_tts import Qwen3TTSModel

            model = Qwen3TTSModel.from_pretrained(
                command["model"],
                dtype=dtype,
                device_map=device_map,
            )
        else:
            raise ValueError(f"未知的 Qwen worker 型別: {model_kind}")


def transcribe(command):
    with contextlib.redirect_stdout(sys.stderr):
        results = model.transcribe(
            audio=command["audio"],
            language=command.get("language"),
            return_time_stamps=False,
        )
    if not results:
        return {"text": "", "language": ""}
    result = results[0]
    return {
        "text": str(getattr(result, "text", "")).strip(),
        "language": str(getattr(result, "language", "") or ""),
    }


def synthesize(command):
    kwargs = {
        "text": command["text"],
        "language": command.get("language") or "Auto",
    }
    checkpoint = command["model"].lower()
    with contextlib.redirect_stdout(sys.stderr):
        if "customvoice" in checkpoint:
            wavs, sample_rate = model.generate_custom_voice(
                **kwargs,
                speaker=command["speaker"],
                instruct=command.get("instruct") or "",
            )
        elif "voicedesign" in checkpoint:
            wavs, sample_rate = model.generate_voice_design(
                **kwargs,
                instruct=command["instruct"],
            )
        elif "base" in checkpoint:
            ref_text = command.get("ref_text") or None
            wavs, sample_rate = model.generate_voice_clone(
                **kwargs,
                ref_audio=command["ref_audio"],
                ref_text=ref_text,
                x_vector_only_mode=not bool(ref_text),
            )
        else:
            raise ValueError(f"無法判斷 Qwen3-TTS 模型型別: {command['model']}")

    import soundfile as sf

    sf.write(command["output"], wavs[0], sample_rate)
    return {"sample_rate": sample_rate}


def main():
    for line in sys.stdin:
        try:
            command = json.loads(line)
            action = command.get("action")
            if action == "close":
                respond(ok=True)
                return
            if action == "load":
                load_model(command)
                respond(ok=True)
            elif action == "transcribe" and model_kind == "asr":
                respond(ok=True, **transcribe(command))
            elif action == "synthesize" and model_kind == "tts":
                respond(ok=True, **synthesize(command))
            else:
                raise ValueError(f"不支援的 worker 動作: {action}")
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            respond(ok=False, error=f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
