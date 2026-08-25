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


def _qwen_nvidia_library_dirs(python: Path) -> tuple[Path, ...]:
    """Find NVIDIA wheel libraries installed inside the isolated Qwen env."""
    env_root = python.expanduser().absolute().parent.parent
    patterns = (
        "lib/python*/site-packages/nvidia/*/lib",
        "lib64/python*/site-packages/nvidia/*/lib",
        "Lib/site-packages/nvidia/*/bin",
    )
    directories = {
        path
        for pattern in patterns
        for path in env_root.glob(pattern)
        if path.is_dir()
    }
    return tuple(sorted(directories, key=str))


def qwen_worker_env(python: Path) -> Dict[str, str]:
    """Build a worker environment that can load CUDA libraries from pip wheels."""
    env = dict(os.environ)
    env["USE_TF"] = "0"
    library_variable = "PATH" if os.name == "nt" else "LD_LIBRARY_PATH"
    existing = env.get(library_variable, "")
    candidates = [str(path) for path in _qwen_nvidia_library_dirs(python)]
    candidates.extend(path for path in existing.split(os.pathsep) if path)

    unique_paths = []
    seen = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        unique_paths.append(path)
    if unique_paths:
        env[library_variable] = os.pathsep.join(unique_paths)
    return env


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
            env=qwen_worker_env(python),
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
                env=qwen_worker_env(python),
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
