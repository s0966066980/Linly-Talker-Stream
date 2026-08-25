#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QWEN_ENV="${QWEN_SPEECH_ENV:-$PROJECT_ROOT/.venv-qwen-speech}"

if [[ ! -x "$QWEN_ENV/bin/python" ]]; then
  uv venv --python 3.10 "$QWEN_ENV"
fi
uv pip install --python "$QWEN_ENV/bin/python" \
  --index https://download.pytorch.org/whl/cu124 \
  'torch==2.5.0' 'torchaudio==2.5.0'
uv pip install --python "$QWEN_ENV/bin/python" 'qwen-asr==0.0.6'
uv pip install --python "$QWEN_ENV/bin/python" --no-deps 'qwen-tts==0.1.1'
uv pip install --python "$QWEN_ENV/bin/python" \
  'onnxruntime>=1.16,<1.24' 'einops==0.8.2'

USE_TF=0 "$QWEN_ENV/bin/python" -c 'import qwen_asr, qwen_tts; print("Qwen speech environment ready")'

if ! command -v sox >/dev/null 2>&1; then
  echo "Warning: SoX executable is not installed; install the 'sox' system package for reference-audio preprocessing."
fi
