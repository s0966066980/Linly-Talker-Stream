# Qwen3 Speech Integration Notes

Date: 2026-08-24

## Scope

This note summarizes the current official integration surface for adding local, keyless Qwen3 speech engines to this repository:

- `Qwen3-ASR` for STT
- `Qwen3-TTS` for TTS

Only official Qwen GitHub, Hugging Face, and PyPI sources were used.

## Executive Summary

`Qwen3-ASR` and `Qwen3-TTS` both expose local Python package APIs and do not require an external API key when used through the official `qwen-asr` and `qwen-tts` packages. The main integration risk is dependency drift: both packages currently pin very recent `transformers` and `accelerate` versions, and the official READMEs recommend a fresh isolated environment.[^qwen-asr-readme][^qwen-tts-readme][^qwen-asr-pypi][^qwen-tts-pypi]

For this codebase, the lowest-risk path is to keep both engines optional at runtime, detect package availability in settings, and treat model IDs or local directories as configuration inputs. That matches the official `from_pretrained(...)` usage for both packages.[^qwen-asr-readme][^qwen-tts-readme]

## Qwen3-ASR

### Official package and Python API

The official local package is `qwen-asr`, published on PyPI as version `0.0.6` with `Requires-Python >=3.9`.[^qwen-asr-pypi]

The official transformers-backend usage is:

- import `Qwen3ASRModel` from `qwen_asr`
- initialize with `Qwen3ASRModel.from_pretrained(...)`
- call `model.transcribe(...)` for inference[^qwen-asr-readme]

The README examples show these key init arguments:

- `model="Qwen/Qwen3-ASR-1.7B"` or another released checkpoint
- `dtype=torch.bfloat16`
- `device_map="cuda:0"`
- `max_inference_batch_size=...`
- `max_new_tokens=...`[^qwen-asr-readme]

### Released model IDs

Official released local model IDs currently include:

- `Qwen/Qwen3-ASR-0.6B`
- `Qwen/Qwen3-ASR-1.7B`
- `Qwen/Qwen3-ForcedAligner-0.6B` for timestamps / alignment[^qwen-asr-readme][^qwen-asr-hf]

There are also newer native-transformers model cards named `*-hf`, but the top-level README still documents `Qwen/Qwen3-ASR-0.6B` and `Qwen/Qwen3-ASR-1.7B` as the standard `qwen-asr` package targets.[^qwen-asr-readme]

### Input / output interface

The official README states that ASR audio inputs can be:

- a local file path
- a URL
- base64 data
- a `(np.ndarray, sr)` tuple[^qwen-asr-readme]

`transcribe(...)` returns objects whose examples access:

- `results[0].language`
- `results[0].text`
- optional `time_stamps` when timestamp mode is enabled[^qwen-asr-readme]

### Language support

The README says Qwen3-ASR supports language identification and ASR for 52 languages and dialects, including 30 languages plus 22 Chinese dialects.[^qwen-asr-readme][^qwen-asr-hf]

The examples pass either:

- `language=None` for automatic language detection
- explicit values such as `"English"` or lists like `["Chinese", "English"]`[^qwen-asr-readme]

Implication for this repo: current `zh` / `en` / `auto` UI values need a small mapping layer to official names such as `Chinese`, `English`, or `None`.

### Streaming

Officially, Qwen3-ASR supports both offline and streaming inference, but the README is explicit that current streaming inference is only available with the vLLM backend. It also notes that streaming mode does not support batch inference or timestamp return.[^qwen-asr-readme]

Implication for this repo: if the current server path uses in-process transformers inference, the safe first integration is non-streaming `transcribe(...)`. True incremental streaming would require the vLLM path rather than the simple `from_pretrained(...)` path.

### Dependency and hardware notes

Official sources currently show:

- PyPI `qwen-asr==0.0.6`
- `transformers==4.57.6`
- `accelerate==1.12.0`
- optional extra `vllm==0.14.0` for the vLLM backend[^qwen-asr-pypi]

The README recommends:

- a fresh Python 3.12 environment
- optional FlashAttention 2 for lower memory and faster inference
- `torch.float16` or `torch.bfloat16` when using FlashAttention 2[^qwen-asr-readme]

## Qwen3-TTS

### Official package and Python API

The official local package is `qwen-tts`, published on PyPI as version `0.1.1` with `Requires-Python >=3.9`.[^qwen-tts-pypi]

The official Python API imports `Qwen3TTSModel` from `qwen_tts` and initializes it with `Qwen3TTSModel.from_pretrained(...)`.[^qwen-tts-readme]

The README documents three main generation entry points:

- `generate_custom_voice(...)`
- `generate_voice_design(...)`
- `generate_voice_clone(...)`[^qwen-tts-readme]

All examples return `(wavs, sr)`, which is the cleanest fit for this repo’s existing “synthesize then frame audio” pattern.[^qwen-tts-readme][^qwen-tts-hf]

### Released model IDs

Official released checkpoints currently include:

- `Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`
- `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`
- `Qwen/Qwen3-TTS-12Hz-0.6B-Base`
- `Qwen/Qwen3-TTS-12Hz-1.7B-Base`
- `Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign`
- tokenizer `Qwen/Qwen3-TTS-Tokenizer-12Hz`[^qwen-tts-readme]

### Input / output interface

Official TTS generation methods:

- `generate_custom_voice(text=..., language=..., speaker=..., instruct=...)`
- `generate_voice_design(text=..., language=..., instruct=...)`
- `generate_voice_clone(text=..., language=..., ref_audio=..., ref_text=..., x_vector_only_mode=...)`[^qwen-tts-readme]

The README says `ref_audio` for voice cloning can be:

- a local file path
- a URL
- a base64 string
- a `(numpy_array, sample_rate)` tuple[^qwen-tts-readme]

Implication for this repo: one engine can support multiple UI shapes depending on model kind:

- `CustomVoice`: built-in speaker plus optional instruction
- `VoiceDesign`: instruction required
- `Base`: reference audio required, `ref_text` optional when `x_vector_only_mode=True`

### Languages and built-in speakers

Official sources say Qwen3-TTS supports 10 major languages:

- Chinese
- English
- Japanese
- Korean
- German
- French
- Russian
- Portuguese
- Spanish
- Italian[^qwen-tts-readme][^qwen-tts-hf]

The CustomVoice variants expose nine built-in speakers:

- `Vivian`
- `Serena`
- `Uncle_Fu`
- `Dylan`
- `Eric`
- `Ryan`
- `Aiden`
- `Ono_Anna`
- `Sohee`[^qwen-tts-readme][^qwen-tts-hf]

The README also mentions helper methods `model.get_supported_speakers()` and `model.get_supported_languages()` for the current checkpoint.[^qwen-tts-readme]

### Streaming

Official Qwen3-TTS materials describe the models as supporting streaming and non-streaming generation, with low-latency speech output in the architecture overview.[^qwen-tts-readme][^qwen-tts-hf]

However, the README’s vLLM section currently states that `vLLM-Omni` support is day-0 for deployment, but “now only offline inference is supported” and online serving will be supported later.[^qwen-tts-readme]

Implication for this repo: the conservative integration path is to use the direct Python package generation APIs and then chunk the returned waveform into the project’s existing streaming frames, rather than relying on an official incremental Python streaming API surface today.

### Dependency and hardware notes

Official sources currently show:

- PyPI `qwen-tts==0.1.1`
- `transformers==4.57.3`
- `accelerate==1.12.0`
- additional runtime deps including `torchaudio`, `soundfile`, `onnxruntime`, `einops`[^qwen-tts-pypi]

The README recommends:

- a fresh Python 3.12 environment
- FlashAttention 2 to reduce GPU memory
- `torch.float16` or `torch.bfloat16` for FlashAttention 2 usage[^qwen-tts-readme]

## API key / license status

For local package usage, both projects document direct Python package installation and `from_pretrained(...)` loading without any API key parameter. The same READMEs separately document cloud API usage through DashScope, so local package usage should be treated as keyless while cloud API usage is a separate integration mode.[^qwen-asr-readme][^qwen-tts-readme]

PyPI metadata for both packages lists Apache-2.0 licenses.[^qwen-asr-pypi][^qwen-tts-pypi]

## Practical integration guidance for this repository

### Recommended STT shape

Use one `qwen3-asr` engine with:

- `type="qwen3-asr"`
- `model_size` storing either `Qwen/Qwen3-ASR-0.6B`, `Qwen/Qwen3-ASR-1.7B`, or a local model directory
- existing `language` values mapped to `None` / `Chinese` / `English`
- existing `device` values mapped to `cpu` or `cuda:0` for official API calls

This matches official `Qwen3ASRModel.from_pretrained(...).transcribe(...)` usage.[^qwen-asr-readme]

### Recommended TTS shape

Use one `qwen3-tts` engine with:

- `type="qwen3-tts"`
- `model` storing the selected official model ID or local directory
- `language`
- `speaker` for CustomVoice
- `instruct` for CustomVoice or VoiceDesign
- `ref_file` / `ref_text` for Base clone models

This matches the three official generation methods without needing multiple engine classes.[^qwen-tts-readme]

### Dependency policy recommendation

Because official package metadata currently pins very recent `transformers` versions and the READMEs recommend isolated environments, the safest repository policy is:

- keep Qwen speech dependencies optional
- detect them at runtime in the settings catalog
- show explicit install commands when missing
- avoid forcing them into the base environment unless the rest of the stack is upgraded around them[^qwen-asr-readme][^qwen-tts-readme][^qwen-asr-pypi][^qwen-tts-pypi]

## Sources and References

1. Qwen3-ASR official GitHub README: https://github.com/QwenLM/Qwen3-ASR
2. Qwen3-TTS official GitHub README: https://github.com/QwenLM/Qwen3-TTS
3. Qwen3-ASR PyPI metadata: https://pypi.org/project/qwen-asr/
4. Qwen3-TTS PyPI metadata: https://pypi.org/project/qwen-tts/
5. Qwen3-ASR Hugging Face model card: https://huggingface.co/Qwen/Qwen3-ASR-0.6B
6. Qwen3-TTS Hugging Face model card: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice

[^qwen-asr-readme]: Qwen3-ASR official README, GitHub: https://github.com/QwenLM/Qwen3-ASR
[^qwen-tts-readme]: Qwen3-TTS official README, GitHub: https://github.com/QwenLM/Qwen3-TTS
[^qwen-asr-pypi]: Qwen-ASR PyPI package metadata: https://pypi.org/project/qwen-asr/
[^qwen-tts-pypi]: Qwen-TTS PyPI package metadata: https://pypi.org/project/qwen-tts/
[^qwen-asr-hf]: Qwen3-ASR-0.6B Hugging Face model card: https://huggingface.co/Qwen/Qwen3-ASR-0.6B
[^qwen-tts-hf]: Qwen3-TTS-12Hz-0.6B-CustomVoice Hugging Face model card: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice
