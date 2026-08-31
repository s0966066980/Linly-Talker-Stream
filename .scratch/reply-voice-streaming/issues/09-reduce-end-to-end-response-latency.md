# Phase 9：縮短端到端回覆延遲

Type: task
Status: ready-for-human

## 文件目的

本文件把目前的效能分析轉成可逐步執行、逐階段驗收、可安全回退的修改計畫。主要目標是縮短：

- 文字送出至首個可見回覆的時間。
- 文字送出至首個非靜音 WebRTC 音訊幀的時間。
- 使用者停止說話至首個非靜音 WebRTC 音訊幀的體感時間。
- 完整回覆播放時間與片段間停頓。

本文件定義修改流程與驗收標準；實作變更會依階段拆分，需通過本文件的自動測試與實機 Gate 後才可標記完成。

## 現況摘要

截至 2026-08-31，現有 50 輪實機 soak 報告顯示：

| 指標 | 現況 | 目標 | 差距 |
| --- | ---: | ---: | ---: |
| 首音訊 P50 | 1.991518 s | ≤ 1.2 s | +0.791518 s |
| 首音訊 P95 | 3.928302 s | ≤ 2.5 s | +1.428302 s |
| A/V 偏差 P95 | 95 ms | ≤ 80 ms | +15 ms |
| 插話停止 P95 | 3.354 ms | ≤ 200 ms | 通過 |
| 恢復收音 P95 | 304.174 ms | ≤ 500 ms | 通過 |
| 最大媒體債務 | 240 ms | ≤ 2 s | 通過 |
| stale output | 0 | 0 | 通過 |

基準環境：

- NVIDIA GeForce RTX 4090。
- llama.cpp，LFM2.5-2.6B-Q4_K_M。
- Edge TTS。
- MuseTalk。
- WebRTC。
- 單一活躍會話。

目前 llama.cpp 已使用 CUDA 全層 offload、Flash Attention 與 KV cache 量化。近期 runtime log 顯示 prompt eval 約 9～29 ms、生成約 245～259 tokens/s；LLM 本體不是目前最值得先處理的延遲來源。

現有 soak 報告未包含 ASR、LLM 首 token、首片段、TTS 首 PCM、MuseTalk 首批與 WebRTC commit 的分段時間，也未完整驗證目前工作樹內 Phase 8 的首音保護與 pacing 修改。開始效能修改前，必須先建立新的可歸因基準。

## 適用範圍

第一階段保證：

- Edge TTS。
- MuseTalk。
- llama.cpp OpenAI-compatible streaming。
- FunASR `paraformer-zh`。
- Silero VAD。
- 16 kHz mono PCM、每幀 20 ms。
- `legacy` 與 `streaming` 兩種回覆模式。
- 文字輸入與語音輸入。

本階段不包含：

- 使用者尚未說完就啟動 speculative LLM/TTS。
- partial/streaming STT。
- 多使用者 GPU 排程與租戶公平性。
- 以 time-stretch 加速已產生的語音。
- 為速度犧牲 generation fence、playback commit、history 或隱私契約。
- 一次直接切換全部使用者到新的 TTS 供應商。

## 不可違反的契約

修改必須遵守 `CONTEXT.md`、`spec.md` 與 ADR-0007：

1. 音訊是播放進度的主時鐘。
2. 視訊落後時可以丟幀或重複最近有效影格，不得延後或加速音訊。
3. 所有文字片段、PCM、MuseTalk batch 與 WebRTC media 必須保留 turn/generation fence。
4. 插話後不得輸出舊 generation 的文字、音訊或影格。
5. 對話 history 與字幕只能提交已播放內容。
6. 首個播放 commit 後不得重新播放片段開頭。
7. 效能 telemetry 不得記錄逐字稿、模型回覆正文或原始音訊。
8. `legacy` 必須保留為可回退模式，直到新的實機 SLO 連續通過。

## 現行延遲路徑

### 語音輸入

```text
使用者停止說話
  → Silero VAD 等待 min_silence_ms
  → segment finalize / speech padding
  → 記憶體 WAV 編碼
  → FunASR
  → LLM request
  → LLM first token
  → TextStreamProcessor 形成首片段
  → Edge TTS request / WebSocket / MP3 decode
  → 20 ms PCM queue
  → MuseTalk 累積首批音訊與推論
  → WebRTC audio queue
  → 首個非靜音 audio commit
```

### 文字輸入

```text
使用者送出文字
  → LLM request
  → LLM first token
  → TextStreamProcessor 形成首片段
  → Edge TTS
  → MuseTalk
  → WebRTC audio commit
```

### 回覆模式差異

- `legacy`：等待完整 LLM 回覆後，才把完整文字送入 TTS。因此首音主要受完整 LLM 回覆、TTS 與 MuseTalk 影響。
- `streaming`：理論上可重疊 LLM、TTS 與 MuseTalk，但目前首片段切分太晚，短回覆可能退化成接近 legacy 的行為。

## 已確認的改善機會

### A. 缺少 stage-level latency，現有資料不能歸因

`TurnMetrics` 目前有 speech end、first audio、interrupt、resume、media debt、A/V、pacing、onset 與 retry 計數，但缺少：

- VAD endpoint confirmed。
- ASR start/end。
- LLM request/first token/end。
- first playable fragment。
- TTS request/first encoded chunk/first PCM/end。
- MuseTalk first batch queued/start/end。
- WebRTC audio enqueue/first non-silent commit。

任何下一步參數調整都必須能回答「節省的時間發生在哪一段」。

### B. 正式串流仍使用舊的 24 字切分器

`BaseLLM.generate_response()` 每輪建立 `TextStreamProcessor()`。它只在遇到強標點且累積至少 24 字時送出；短句與弱標點內容常等到後續句子或 LLM 完成才 flush。

專案已有 `SemanticFragmenter`：

- 強句尾可立即切分。
- 弱標點至少 12 字。
- 24～32 字在安全邊界切分。

但 production `src` 路徑沒有建立 `ReplyFragmentProducer`，所以新切片器沒有成為正式 LLM→TTS 路徑。

### C. MuseTalk startup batch 與序列 polling

MuseTalk `batch_size=8`，每個 `run_step()` 讀取 `batch_size * 2` 個 20 ms 音訊幀，即 320 ms 音訊內容。

`BaseAudioStreamHandler.get_audio_frame()` 每次 queue 為空時最多等 10 ms。空 queue 下，一個 batch 會序列執行 16 次等待；隔離實測約 162 ms wall time。這會增加 startup 與短片段 jitter。

### D. Edge TTS 是最大的 P95 外部變數

每個可播文字片段都會建立新的 Edge `Communicate(...).stream()`。每個片段都重新支付遠端 request、WebSocket、首 MP3 與 decode 起始成本。

目前每個片段也使用新的 `asyncio.run()`。event loop 建立成本可消除，但相較遠端網路延遲通常只是次要改善。

### E. 語音 endpoint 有固定 500 ms 體感等待

runtime `min_silence_ms=500`。現有 first-audio SLO 在 VAD 已確認 speech end 後才開始計時，因此這 500 ms 不一定出現在現有 SLO，卻會完整出現在使用者體感。

### F. FunASR device 設定沒有被 adapter 明確使用

runtime 有 `device:auto`，但 `FunASR._load_model()` 只呼叫：

```python
AutoModel(model=self.model_name, disable_update=True)
```

adapter 沒有把 device 傳入模型。這不代表目前一定跑 CPU，但代表 runtime 設定不能保證實際裝置，且無法穩定比較 CPU/GPU 延遲。

### G. 前端沒有獨立的 LLM token delta 路徑

`VoiceTurnSession._generate_turn()` 等 `llm_response()` 完成後才取得完整文字；`assistant_response` 目前只在 legacy 分支發送。畫面文字與語音片段形成綁在不同的完成點，無法用 LLM first token 提前改善可見回覆時間。

## 目標指標與暫定階段預算

最終 SLO 沿用既有規格：

| 指標 | 最終目標 |
| --- | ---: |
| speech-end 至首個非靜音 WebRTC 音訊幀 | P50 ≤ 1.2 s；P95 ≤ 2.5 s |
| interrupt 至舊語音停止 | P95 ≤ 200 ms |
| interrupt 至恢復收音 | P95 ≤ 500 ms |
| A/V 絕對偏差 | P95 ≤ 80 ms |
| stale output after cancellation | 0 |

新增 user-perceived 與 stage 指標：

| 指標 | 暫定目標 | 說明 |
| --- | ---: | --- |
| 使用者實際停止說話至 VAD endpoint | P50 ≤ 350 ms | 噪音環境另分群觀察 |
| LLM request 至 first token | P95 ≤ 150 ms | 本機暖機後 |
| first token 至 first playable fragment | P95 ≤ 250 ms | 強標點短句應更低 |
| fragment enqueue 至 TTS first PCM | 先建立 baseline | Edge 外部變數，不先假設固定門檻 |
| first PCM 至 MuseTalk first batch ready | P95 ≤ 200 ms | startup microbatch 後 |
| avatar PCM enqueue 至 WebRTC first commit | P95 ≤ 250 ms | 不犧牲音訊 pacing |
| 文字送出至第一個 assistant delta | P95 ≤ 250 ms | 只表示可見文字，不代表已播放 |

stage 目標在第一次新 baseline 後可以調整，但最終端到端 SLO不可放寬。

## 修改流程總覽

```text
Phase 9.0 乾淨基準與分段量測
  → Phase 9.1 統一語意切片與自適應首片段
  → Phase 9.2 MuseTalk startup microbatch 與 queue 讀取
  → Phase 9.3 VAD endpoint A/B 與 FunASR device
  → Phase 9.4 Edge TTS 首包與後續片段策略
  → Phase 9.5 前端 assistant delta
  → Phase 9.6 次要熱點與完整回覆時間
  → Phase 9.7 50 輪實機 soak 與漸進啟用
```

不得同時合併 Phase 9.1、9.2、9.3 與 9.4 的核心行為修改。每階段都要保留前一階段報告，才能比較增量成效。

## Phase 9.0：建立可歸因的現行基準

### 修改範圍

- `src/server/reply_streaming/metrics.py`
- `src/server/reply_streaming/soak.py`
- `src/server/voice_session.py`
- `src/llm/base.py`
- `src/llm/engines/openai.py`
- `src/tts/engines/edge.py`
- `src/avatars/musetalk/audio_stream_handler.py`
- `src/avatars/musetalk/avatar.py`
- `src/utils/webrtc.py`
- `tests/test_reply_streaming.py`
- `tests/test_voice_session.py`
- `tests/test_speech_timing.py`

### 實作步驟

1. 在 `TurnMetrics` 加入固定欄位，不接受任意 payload：
   - `capture_endpoint_ms`
   - `asr_ms`
   - `llm_first_token_ms`
   - `llm_total_ms`
   - `first_fragment_ms`
   - `tts_first_encoded_ms`
   - `tts_first_pcm_ms`
   - `musetalk_first_batch_ms`
   - `avatar_to_webrtc_commit_ms`
2. 所有時間使用 monotonic clock。
3. 每個 marker 必須 idempotent；重複呼叫只保留第一次或明確定義的 aggregate。
4. `legacy` 與 `streaming` 都輸出相同 schema；不適用欄位為 `null`，不可偷偷用 `0`。
5. text input 與 speech input 都標記 `input_source`，但不記錄輸入內容。
6. soak report 增加每個 stage 的 P50/P95、樣本數與缺失值數量。
7. report 記錄：git commit、dirty flag、runtime config hash、模型、avatar、TTS、GPU 與冷/暖狀態。
8. 新增 queue watermark：TTS text、PCM、MuseTalk feature/result、WebRTC audio/video。

### 先寫測試

- 同一 marker 重複呼叫不覆蓋首次時間。
- 時間順序錯誤時回報結構化 invalid-order，而不是輸出負值。
- 不適用 stage 保持 `null`。
- metrics snapshot 不包含輸入文字、回覆文字或 PCM。
- soak percentile 忽略 `null`，同時保留有效樣本數。
- legacy/streaming 與 text/speech 四種組合都能輸出相同 schema。

### Gate

- 完整測試通過。
- 10 輪 smoke test 每輪都有可解釋的 stage timeline。
- stage 加總與端到端時間差異在排程允許範圍內，不出現負值。
- telemetry 隱私測試通過。
- 建立一份修改前的 50 輪或至少 30 輪 baseline；若 Edge 波動過大，延長至 50 輪。

### 回退

metrics 只能觀測，不得影響 queue、重試或播放。若觀測程式拋例外，應停用該輪 metrics，而不是中止使用者回覆。

## Phase 9.1：統一語意切片與自適應首片段

### 修改範圍

- `src/llm/base.py`
- `src/server/reply_streaming/fragmenter.py`
- `src/server/reply_streaming/producer.py`
- `src/config/schema.py`
- `config/config.yaml`
- `config/runtime_overrides.yaml`
- `tests/test_reply_streaming.py`
- `tests/test_voice_session.py`
- 新增或擴充文字切片 property tests

### 目標設計

production 只保留一個 canonical fragmenter。建議由 `BaseLLM.generate_response()` 接受 fragment callback 或 fragmenter factory，不再自行建立舊 `TextStreamProcessor`。

首片段與後續片段採不同策略：

- 第一個強句尾：內容非空且達安全最小長度後立即送出。
- 第一個弱標點：至少 8～12 個內容字元。
- 首 token 後達 150～250 ms 尚未形成句子：在最近安全邊界送出。
- 後續弱標點：至少 12 字。
- 後續 soft/hard limit：24/32 字。
- LLM 完成：flush 剩餘非空內容。

時間上限不能在 UTF-8 code point、英文單字、數字、小數、URL、Markdown marker 或 SSML-like marker 中間切斷。

### 設定建議

```yaml
reply_streaming:
  enabled: false
  first_fragment_min_chars: 8
  first_fragment_max_wait_ms: 200
  weak_min_chars: 12
  soft_limit_chars: 24
  hard_limit_chars: 32
```

正式預設值必須由實測決定。若 schema 不希望暴露所有低階參數，至少保留一個 `latency_profile: balanced|fast|natural`，並在後端映射成固定、可測試的參數組。

### 實作步驟

1. 先把舊 `TextStreamProcessor` 的現有行為轉成 golden tests。
2. 將 `SemanticFragmenter` 接入真正的 LLM→TTS production 路徑。
3. 讓 first-fragment deadline 使用 monotonic clock，並可在 deterministic fake clock 下測試。
4. fragment 形成時標記 `first_fragment_ms`。
5. fragment callback 必須先檢查 turn cancellation 與 generation fence。
6. 保持 fragment sequence 單調，不能因 flush 或 deadline 重複發送相同文字。
7. `legacy` 維持完整回覆後送 TTS，不共享串流 deadline。

### 測試矩陣

- `好的。`
- `好的。我先確認目前設定，接著再回答。`
- 全程無標點中文。
- 中英混合。
- 小數 `3.14`、版本 `v1.2.3`。
- URL、email、Markdown code span。
- emoji 與標點相鄰。
- token 邊界落在標點前後。
- LLM 在首片段前取消。
- LLM 在首片段後取消。
- deadline 與正常標點同時發生。
- Edge TTS queue 背壓期間不得丟字或重複字。

### Gate

- 串流模式 first-token→first-fragment P95 ≤ 250 ms。
- 強標點短句不得等待完整回覆。
- fragment 數量不能因過度切碎，使每 100 字片段數比 baseline 增加超過 50%，除非 TTS first PCM 與片段間隔實測仍改善。
- 所有既有 transactional history、cancel、stale fence 測試通過。
- 10 輪 A/B 中 first-audio P50 有統計上穩定改善，且首字與語調沒有明顯退化。

### 回退

保留 `legacy`。若新 fragmenter 產生異常，可只回退到既有固定切片策略，不得在同一輪將已播串流重新從開頭播放。

## Phase 9.2：MuseTalk startup microbatch 與 queue 讀取

### 修改範圍

- `src/avatars/audio_stream_handler.py`
- `src/avatars/musetalk/audio_stream_handler.py`
- `src/avatars/musetalk/avatar.py`
- `src/config/schema.py`
- `config/config.yaml`
- `tests/test_media_fencing.py`
- `tests/test_speech_timing.py`
- 新增 MuseTalk startup latency tests

### 目標設計

1. 不再對一個空 batch 執行 `batch_size * 2` 次 10 ms 阻塞等待。
2. speech startup 使用小批次，穩定播放後恢復正常 batch。
3. idle 期間仍可輸出靜態影格，但不應用序列 timeout 人為累積 wall delay。
4. 不改變每個 audio frame 的 20 ms RTP 時間軸。

### 建議 queue 讀取流程

```text
等待第一個 frame（單次 bounded wait）
  → non-blocking drain 現有 frame
  → startup 時達 microbatch 門檻即送推論
  → 不足的 feature context 依既有規則補靜音
  → 播放穩定後恢復 batch_size=8
```

候選設定：

```yaml
model:
  batch_size: 8
  startup_batch_size: 2  # A/B 2 與 4
  audio_queue_wait_ms: 10
```

### 實作步驟

1. 把 `get_audio_frame()` 分成：
   - `wait_for_first_audio_frame(timeout)`。
   - `try_get_audio_frame()`。
   - 明確的 idle/silence frame 建立函式。
2. `run_step()` 一個 batch 最多只做一次 blocking wait。
3. inference batch envelope 增加實際 batch size，不假設永遠等於設定 batch size。
4. 確認 audio feature extractor、UNet、VAE 與 `process_frames()` 都接受 startup batch。
5. 首個非靜音 PCM 抵達時切換 startup 狀態；累積足夠 runway 或第一批完成後回到 normal batch。
6. interrupt、flush、generation change 時重設 startup 狀態。
7. 記錄 first PCM→first MuseTalk batch、batch inference time 與 sustained real-time factor。

### 先寫測試

- 空 queue 的單次 `run_step()` wall time 不隨 `batch_size * 2` 線性增加。
- startup batch 2/4 的 feature 與 paired audio 數量一致。
- 可變 batch 不會破壞 frame index、avatar cycle 或 A/V 對應。
- cancel before inference、during inference、after inference 都不輸出 stale media。
- normal batch 仍維持 batch 8 throughput。
- TTS 暫停時不插入片段中間的可聽靜音。
- startup 與 normal 切換不重複或漏掉 PCM。

### Gate

- 隔離測試中的空 batch 等待由約 162 ms 降到單次 timeout 等級。
- first PCM→first MuseTalk batch P95 ≤ 200 ms。
- sustained inference throughput ≥ 1.0× real time，保留至少 20% 建議餘裕。
- A/V P95 不惡化，目標仍為 ≤ 80 ms。
- 首字保護、音訊不追幀與 stale fence 測試全數通過。

### 回退

以設定關閉 startup microbatch，恢復固定 batch 8。queue 讀取的單次 bounded wait 可獨立保留，但必須先通過原有 idle/custom-audio 行為測試。

## Phase 9.3：VAD endpoint 與 FunASR 執行裝置

### 修改範圍

- `src/config/schema.py`
- `src/vad/` 對應 Silero endpoint 邏輯
- `src/server/voice_session.py`
- `src/asr/engines/funasr.py`
- `config/config.yaml`
- `config/runtime_overrides.yaml`
- `tests/test_vad.py`
- `tests/test_funasr.py`
- `tests/test_voice_session.py`

### VAD 修改步驟

1. 增加「最後一個 speech frame」時間戳，區分：
   - 使用者實際停止說話。
   - VAD endpoint confirmed。
   - 現有 `mark_speech_end()`。
2. 先以設定做 A/B，不立即改全域預設：
   - control：500 ms。
   - candidate：350 ms。
   - aggressive lab：300 ms，只做內部測試。
3. 保留 `speech_pad_ms=150`，避免句尾吃字。
4. 情況允許時加入自適應 endpoint：
   - 短句且高信心結尾可縮短。
   - 噪音、長句、猶豫停頓維持較長等待。
5. 記錄 premature-finalization、空 ASR、使用者立即續講造成的新 turn 次數。

### FunASR 修改步驟

1. 將 schema 的 `device` 明確傳給 FunASR adapter。
2. `auto` 必須解析成實際裝置並記錄 `resolved_device`。
3. 啟動時 warm up 一次短靜音或固定 fixture，不把模型冷啟動計入第一個使用者 turn。
4. 分別測量 WAV serialization、model inference 與 script conversion。
5. 確認 FunASR 版本支援後，A/B 比較 bytes/WAV 與直接 PCM array；不先假設 array 一定更快或格式相容。
6. 比較 CPU 與 CUDA。若 FunASR CUDA 與 MuseTalk/LLM 爭用造成 P95 變差，允許固定使用 CPU。

### 測試矩陣

- 150、250、350、500、800 ms 句中停頓。
- 中文短句、長句、數字、低音量、背景風扇聲。
- 句尾爆破音、摩擦音、輕聲。
- speech pad 不吃首尾字。
- `device=auto|cpu|cuda` 解析與錯誤訊息。
- 無 CUDA 時 `device=cuda` fail fast，不靜默退回。
- 模型只載入一次，warmup 不寫入對話 history。

### Gate

- candidate 的 user-stop→endpoint P50 至少改善 120 ms。
- premature cut rate 不高於 control 的可接受誤差；人工腳本不得出現可重現吃字。
- ASR 空結果率與字錯率不得明顯惡化。
- ASR P95 必須有實際數字後才決定 CPU/GPU 預設。
- speech-end→first-audio、interrupt 與 resume SLO 不退化。

### 回退

VAD 可立即回到 500 ms；ASR 可回到 `auto` 或實測較穩定裝置。所有回退都只影響下一輪，不中斷正在處理的 turn。

## Phase 9.4：Edge TTS 首包與後續片段策略

### 修改範圍

- `src/tts/base.py`
- `src/tts/engines/edge.py`
- `src/server/reply_streaming/channel.py`
- `src/server/reply_streaming/metrics.py`
- `src/config/schema.py`
- `tests/test_speech_timing.py`
- `tests/test_reply_mode_tts_timing.py`
- TTS provider comparison harness

### 先量測再決策

每個 fragment 必須記錄：

- queue wait。
- request start。
- first encoded audio chunk。
- first decoded PCM。
- synthesis end。
- retry 次數與發生在 playback commit 前或後。
- fragment 字數與估算/實際音訊長度，但不記內容。

按 fragment sequence 分開統計：第一片段的首包延遲與後續片段不能混成同一 histogram。

### Edge 保留方案

1. 建立長生命週期 async TTS worker/event loop，避免每片段 `asyncio.run()`。
2. 第一片段優先送出；後續 LLM token 在第一片段合成/播放期間適度合併。
3. channel 以媒體債務限制，不能為減少 request 數無界累積文字。
4. 只在首個 PCM/playback commit 前依既有安全契約重試。
5. 不共用會造成 turn 交叉污染的 decoder/emitter 狀態。

必須注意：`edge-tts` 是否能真正重用底層 WebSocket 要以目前版本的 API 與封包實測確認。若 library 每次 `Communicate` 必然新連線，持久 event loop 只能消除本機 event-loop 建立成本，不能宣稱已消除網路握手。

### 本機或低延遲 TTS 候選方案

若暖機 Edge 的 `fragment enqueue→first PCM` P95 持續占端到端 P95 的最大比例，建立 provider A/B：

- Edge 作 control。
- 本機 streaming TTS 或支援持久連線的 provider 作 candidate。
- 比較首 PCM P50/P95、RTF、GPU/CPU/VRAM、中文自然度、首字完整性與取消時間。

切換 provider 必須走既有 TTS interface，不可繞過 turn envelope、playback commit 或 metrics。

### 先寫測試

- event loop/worker 跨 fragment 重用但不跨 turn 污染。
- 第一片段優先，後續合併不重排文字。
- queue backpressure、cancel、timeout、retry。
- first PCM 前重試可安全清空；commit 後 fail closed。
- fragment 合併後 history/字幕仍以實際播放內容提交。
- Phase 8 的 onset/preroll 測試必須持續通過。

### Gate

- 若只改 Edge worker，必須在至少 30 輪暖機測試證明首 PCM P50/P95 有穩定改善，否則不保留複雜度。
- 若更換 provider，candidate 的首 PCM P95、首字完整性、自然度與取消行為必須同時通過。
- 不得新增片段重複、缺字或插話後殘留。
- 首音訊端到端 P50/P95 朝既有 SLO 改善。

### 回退

provider 與合併策略使用設定旗標。故障只能讓下一輪切回 Edge/legacy；已播放中的 turn 不可從頭重播。

## Phase 9.5：前端 assistant delta 與可見回覆時間

### 修改範圍

- `src/llm/base.py`
- `src/server/voice_session.py`
- WebRTC/data-channel 事件 schema
- `web/src/App.vue`
- `tests/test_voice_session.py`
- `web/tests/*.test.js`

### 目標事件模型

```text
assistant_response_start(turn_id, mode, input_source)
assistant_response_delta(turn_id, sequence, text_delta)
assistant_response_done(turn_id, terminal_reason)
```

可見文字與已播放字幕必須是不同概念：

- `assistant_response_delta`：模型正在生成，可作聊天視窗的即時文字。
- playback-committed subtitle：使用者已經聽到的片段，仍由 WebRTC 首個非靜音 commit 觸發。

前端不得把未播放的 delta 寫成「已播放字幕」或 history commit。

### 實作步驟

1. `BaseLLM.generate_response()` 增加 token observer，不改變 TTS fragment callback。
2. observer 在 executor thread 發生時，使用 thread-safe 方式轉送到 session event loop。
3. 每個 delta 帶 monotonic sequence，前端去重並拒絕舊 turn。
4. cancel 時停止接受 delta，保留已顯示文字或依 UI 決策標記為中止，但不得污染 committed history。
5. legacy 可選擇維持單次完整事件，以確保模式差異清楚。
6. 記錄 text-submit→first-delta，但 metrics 不記 delta 內容。

### 測試

- delta 順序、去重、漏序偵測。
- cancel 與 generation change 後拒絕舊 delta。
- streaming UI 逐步顯示；legacy 仍一次顯示。
- TTS 失敗時可見模型文字與已播放字幕狀態不混淆。
- XSS/Markdown rendering 仍沿用既有 sanitization。
- reconnect 不重播舊 delta。

### Gate

- 文字送出→first delta P95 ≤ 250 ms（本機 LLM 暖機後）。
- 不改變首音訊、history、subtitle commit 與 interruption SLO。
- Web tests、production build 與後端 session tests 通過。

### 回退

前端未知事件必須可忽略。可用 capability/version flag 關閉 delta，退回既有完整 `assistant_response`。

## Phase 9.6：完整回覆時間與次要熱點

這一階段只處理 profiling 證明仍值得修改的部分。

### 回覆長度

runtime `response_max_chars=200`，實際 token budget 會依字數換算為約 300 tokens。這主要影響完整回覆與 legacy 首音，不會顯著改善 streaming first token。

建議提供可理解的設定：

- 精簡：80 字。
- 平衡：120 字。
- 詳細：200 字。

設定變更必須清楚告知使用者這是回答長度，不是模型速度模式。

### 對話歷史與 prompt cache

目前 llama.cpp 已有 slot prefix reuse，先量測 history 輪數與 prompt eval。只有 prompt eval P95 明顯上升時才：

- 縮短 system prompt。
- 降低 history turn 上限。
- 對較舊歷史做摘要。

不得為幾十毫秒節省而破壞對話連貫性。

### MuseTalk frame composition

profile 以下 CPU 路徑：

- `paste_back_frame()`。
- mask blending。
- mouth enhancement。
- OpenCV copy/resize/putText。
- `VideoFrame` 建立。

只有 process queue 持續累積或 CPU frame time 接近 40 ms 才考慮：

- 預計算不變 mask/座標。
- 減少 deep copy 與陣列配置。
- 降低 debug watermark 成本。
- 把不必要的畫質增強改為可設定。

畫質優化不得與 latency 修正在同一 commit 混合。

### WebRTC runway

現有 speech-start runway 約 80 ms、最大 media buffer 約 240 ms。只有 `avatar PCM enqueue→WebRTC commit` 指標證明此段占比過高才逐步降低；每次最多調整 20 ms，並重新驗證 starvation、A/V、首字與 pacing。

## Phase 9.7：完整驗收與漸進啟用

### 自動測試順序

每一階段先跑最小相關集合：

```bash
.venv/bin/python -m unittest -v \
  tests.test_reply_streaming \
  tests.test_voice_session \
  tests.test_speech_timing \
  tests.test_media_fencing \
  tests.test_reply_mode_tts_timing \
  tests.test_vad \
  tests.test_funasr \
  tests.test_llamacpp \
  tests.test_runtime_settings
```

之後跑完整 Python suite：

```bash
.venv/bin/python -m unittest discover -s tests -v
```

前端：

```bash
cd web
npm test
npm run build
```

若專案實際以 `uv run` 管理環境，可用等價命令；CI 與文件應統一一種入口。

### 實機測試矩陣

四個核心組合都要測：

| 輸入 | 模式 | 主要觀察 |
| --- | --- | --- |
| 文字 | legacy | 完整 LLM、完整 TTS、首音與總時間 |
| 文字 | streaming | first delta、first fragment、first PCM、first audio |
| 語音 | legacy | endpoint、ASR、完整 LLM、首音 |
| 語音 | streaming | 全部 stage 與重疊效果 |

每組至少涵蓋：

- 短句 12 輪。
- 弱標點 11 輪。
- 無標點 10 輪。
- 長回覆 10 輪。
- 插話至少 4 輪。
- LLM/TTS 中斷與故障至少 3 輪。

總數至少 50 輪，並分開標記：

- 第一輪 cold start。
- warm steady state。
- Edge retry/no retry。
- 文字/語音輸入。
- legacy/streaming。

### 人工聽感驗收

固定腳本需由同一聲線、相同音量與相同裝置重播：

1. 每片段首字完整，沒有聲母消失。
2. 沒有追幀加速、跳音或數字擠在一起。
3. 片段間停頓自然，不因過度切分變成逐字朗讀。
4. 句中短暫停頓不會被 VAD 提前截斷。
5. 字幕、聊天文字與已播語音的語意狀態不混淆。
6. 插話後不再出現舊回覆文字、語音或嘴型。

### 最終 Gate

- 50 輪 soak 全部完成。
- first-audio P50 ≤ 1.2 s、P95 ≤ 2.5 s。
- A/V P95 ≤ 80 ms。
- interrupt stop P95 ≤ 200 ms。
- listening resume P95 ≤ 500 ms。
- stale output = 0。
- 首音/追幀人工驗收通過。
- 完整 Python tests、Web tests、Web build 通過。
- report 記錄乾淨 commit；若 dirty，報告必須標為不可發布。

只有全部通過後，才允許把 `reply_streaming.enabled` 的主配置預設改為 `true`。runtime override 可以用於受控實驗，但不能取代正式 rollout gate。

## 建議 commit 拆分

為了讓效能差異可追蹤，建議至少拆成：

1. `test: add stage-level reply latency telemetry`
2. `perf: use adaptive semantic first-fragment streaming`
3. `perf: reduce MuseTalk startup batch latency`
4. `perf: tune voice endpoint and resolve FunASR device`
5. `perf: reduce TTS first-audio latency`
6. `feat: stream assistant text deltas to the client`
7. `test: add real-device latency soak report`

每個 commit 都要能獨立通過相關測試。不要把格式化、嘴型畫質、設定 UI 重構或無關清理混入效能 commit。

## 風險與防護

| 風險 | 觸發原因 | 防護 |
| --- | --- | --- |
| TTS 片段過短、語調不自然 | 首片段門檻過低 | 首片段與後續片段分離；限制每 100 字片段數 |
| Edge request 數增加、P95 變差 | 每個短片段新連線 | 第一片段優先，後續合併；量測 request 次數 |
| MuseTalk throughput 不足 | startup batch 長期維持過小 | 只在 startup 使用 microbatch，之後回 batch 8 |
| 中途插入靜音 | queue drain/pad 錯誤 | pending TTS 時不得用 silence 填滿 speech batch |
| VAD 吃掉句尾或拆成兩輪 | endpoint 過短 | A/B、保留 150 ms pad、監控 premature cuts |
| GPU contention 增加 P95 | ASR、LLM、MuseTalk 同時用 CUDA | CPU/GPU 分組實測，依 P95 選擇裝置 |
| 未播放文字污染 history | UI delta 與 playback commit 混淆 | delta 僅顯示，history 仍以 audio commit 為準 |
| metrics 反而影響延遲 | 同步 log 或高頻序列化 | 固定 scalar、批次輸出、觀測失敗不阻塞回覆 |
| 實機報告無法重現 | config/commit 未記錄 | report 加 commit、dirty flag、config hash 與環境 |

## 不應優先實作的項目

- 重新調整 llama.cpp GPU layers；目前已全層 offload。
- 單純更換更小 LLM；現有本機 LLM 已很快，可能損失品質但只省少量首 token 時間。
- 把 WebRTC audio buffer 一次大幅降到接近零。
- 以音訊 time-stretch 掩蓋 backlog。
- 在沒有 stage metrics 前重寫整個 TTS 或 MuseTalk pipeline。
- 把 `response_max_chars` 降低當作首音優化；它主要改善完整回覆時間。

## 預估效益

以下是工程估算，不是已驗收結果：

| 修改 | 可能改善 |
| --- | ---: |
| 自適應首片段 | 約 50～300 ms |
| MuseTalk 單次等待＋startup microbatch | 約 80～240 ms |
| VAD 500→350 ms | 語音體感約 150 ms |
| TTS provider/首包策略 | 數百毫秒至 1 秒以上，需實測 |
| UI assistant delta | 文字可見時間接近 LLM first token |
| WAV→PCM 直接輸入 | 幾毫秒至數十毫秒，低優先 |
| 持久 async TTS event loop | 通常為幾毫秒，網路握手仍存在 |

前四個主要階段完成後，文字輸入的 streaming first audio 有機會再縮短約 0.3～0.8 秒；語音輸入另可由 endpoint 節省約 0.15～0.2 秒。最終 P95 是否達標主要取決於 Edge TTS 的首包分布。

## 執行檢查表

### Phase 9.0

- [x] 新增所有 stage metrics。
- [x] 加入隱私與時間順序測試。
- [ ] 產生修改前 baseline。

目前實作狀態：stage marker、content-free stage aggregation 與對應測試已完成；仍需用目前乾淨 commit 重新產生 30～50 輪實機 baseline。

### Phase 9.1

- [x] production 接入 canonical `SemanticFragmenter`。
- [ ] 實作自適應首片段 deadline。
- [ ] 驗證 fragment 數量、自然度、取消與背壓。

目前實作狀態：turn-aware streaming 已接入 `SemanticFragmenter`，legacy 保持舊路徑；仍需實機確認 Edge request 數與聽感。

### Phase 9.2

- [x] 移除每 batch 多次序列 blocking poll。
- [x] 實作 startup microbatch。
- [ ] 驗證 sustained RTF、A/V 與 stale fencing。

目前實作狀態：已完成單次 blocking poll 與可變 batch inference；首批使用較小 batch，後續恢復 steady-state batch。仍需以完整 soak 驗證 sustained RTF、A/V 與 stale fencing。

### Phase 9.3

- [ ] VAD 350/500 ms A/B。
- [x] FunASR device 真正接入並記錄 resolved device。
- [ ] 比較 CPU/GPU 與 WAV/PCM。

目前實作狀態：FunASR 已明確解析並傳入 `device`；VAD 350/500 ms 與 CPU/GPU 的選擇仍需實機 A/B。

### Phase 9.4

- [x] 建立 Edge first PCM 分布 marker。
- [ ] 實作第一片段優先與後續合併。
- [ ] 只有數據支持時才導入新 provider。

目前實作狀態：已加入 TTS encoded/PCM stage marker；Edge 持久 worker、片段合併與 provider A/B 尚未完成。

### Phase 9.5

- [x] 新增後端 assistant delta 事件。
- [x] 前端拒絕 stale/out-of-order delta。
- [x] 保持可見文字與已播放字幕語意分離。

目前實作狀態：後端已提供 turn-aware `assistant_response_start/delta/done`；前端以 turn/sequence fence 丟棄重複、逆序及完成後 delta，並維持可見預覽與播放提交事件分離。

### Phase 9.6～9.7

- [ ] profile 後才處理次要 CPU/WebRTC 熱點。
- [x] 完整 Python/Web 回歸通過。
- [ ] 50 輪實機 soak 通過。
- [ ] 人工首字、語速、停頓、插話驗收通過。
- [ ] 乾淨 commit 上產生正式報告。
- [ ] 全部 gate 通過後才調整正式預設。

## 完成定義

此議題只有在以下條件全部成立時才可標記 resolved：

1. stage-level telemetry 能清楚歸因首音延遲。
2. streaming 不再因固定 24 字門檻退化成近似 legacy。
3. MuseTalk startup 不再支付 `batch_size * 2` 次空 queue timeout。
4. 語音 endpoint 與 FunASR device 已由實測決定，不是猜測。
5. TTS first PCM P50/P95 有正式數據，且最大瓶頸已有對應方案。
6. 文字 delta、播放字幕與 history commit 契約沒有混淆。
7. 四種輸入/模式組合均通過回歸與實機驗收。
8. 既有可靠性、首字保護、音訊 pacing、A/V 與隱私契約全部不退化。
9. 最終 50 輪 soak 達成完整 SLO。

## Comments

- 2026-08-31：根據現行程式路徑、runtime 設定、llama.cpp runtime log、MuseTalk 空 queue 隔離量測與既有 50 輪 soak 報告建立本修改計畫。
- 2026-08-31：已實作並測試 stage metrics、turn-aware SemanticFragmenter、MuseTalk 單次 blocking poll 與 startup microbatch、FunASR device 傳遞、TTS/Avatar stage markers、後端 assistant delta callback，以及前端 turn/sequence stale fence。完整 Python 219 項、前端 23 項與 Vite production build 通過；Edge provider/持久連線、VAD 實機 A/B 與 50 輪新 soak 尚未完成。WebRTC 80 ms buffer A/B 造成 starvation（首音 4.61 s），已恢復 240 ms 安全值。
- 2026-08-31：後續音訊主時鐘解耦、MuseTalk runtime 瘦身、Edge 預取、PCM-native ASR 與前端 delta batching 已拆至 [Phase 10 詳細規劃](10-decouple-audio-clock-and-reduce-runtime-overhead.md)。
