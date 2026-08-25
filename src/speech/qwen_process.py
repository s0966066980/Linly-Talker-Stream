"""Client for the isolated, persistent Qwen speech inference worker."""

from __future__ import annotations

import atexit
import json
import os
import subprocess
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Dict


RESPONSE_PREFIX = "__QWEN_SPEECH_RPC__"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PYTHON = PROJECT_ROOT / ".venv-qwen-speech" / "bin" / "python"
WORKER_SCRIPT = Path(__file__).with_name("qwen_worker.py")


def qwen_speech_python() -> Path:
    configured = os.getenv("QWEN_SPEECH_PYTHON", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_PYTHON


@lru_cache(maxsize=1)
def qwen_worker_available() -> bool:
    python = qwen_speech_python()
    if not python.is_file():
        return False
    try:
        result = subprocess.run(
            [str(python), "-c", "import qwen_asr, qwen_tts"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={**os.environ, "USE_TF": "0"},
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


class QwenWorkerClient:
    """One serialized JSON-RPC connection to a model-holding subprocess."""

    def __init__(self):
        self.process: subprocess.Popen[str] | None = None
        self._lock = Lock()
        atexit.register(self.close)

    def start(self, *, kind: str, model: str, device: str) -> None:
        if self.process is None or self.process.poll() is not None:
            python = qwen_speech_python()
            if not python.is_file():
                raise RuntimeError(
                    "Qwen 語音環境不存在，請執行：bash scripts/setup-qwen-speech.sh"
                )
            self.process = subprocess.Popen(
                [str(python), str(WORKER_SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                bufsize=1,
                env={**os.environ, "USE_TF": "0"},
            )
        self.request("load", kind=kind, model=model, device=device)

    def request(self, action: str, **payload: Any) -> Dict[str, Any]:
        with self._lock:
            process = self.process
            if process is None or process.poll() is not None:
                raise RuntimeError("Qwen 語音 worker 未啟動或已退出")
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(json.dumps({"action": action, **payload}, ensure_ascii=False) + "\n")
            process.stdin.flush()
            while True:
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError(
                        f"Qwen 語音 worker 意外結束（exit={process.poll()}）"
                    )
                if not line.startswith(RESPONSE_PREFIX):
                    continue
                response = json.loads(line[len(RESPONSE_PREFIX):])
                if not response.get("ok"):
                    raise RuntimeError(response.get("error") or "Qwen worker 推論失敗")
                return response

    def close(self) -> None:
        process, self.process = self.process, None
        if process is None or process.poll() is not None:
            return
        try:
            if process.stdin is not None:
                process.stdin.write(json.dumps({"action": "close"}) + "\n")
                process.stdin.flush()
            process.wait(timeout=3)
        except Exception:
            process.terminate()
