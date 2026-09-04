# Phase 10：解耦音訊主時鐘並降低執行期開銷

Type: task
Status: in-progress

## 文件目的

本文件把 Phase 9 實機量測後仍存在的效能瓶頸，拆成按優先級執行、可逐階段驗收、可安全回退的修改計畫。

主要目標是：

1. 讓第一個非靜音 WebRTC 音訊幀不再等待 MuseTalk 推理、嘴型貼回、OpenCV 處理或影片佇列。
2. 保留 ADR-0007 定義的音訊主時鐘、輪次隔離、播放提交及插話契約。
3. 降低 MuseTalk 靜音期間的 CPU、GPU、記憶體複製及 queue 開銷。
4. 降低 Edge TTS 後續片段的連線與片段間停頓。
5. 消除 llama.cpp 冷啟動首 token 尖峰。
6. 降低語音辨識格式轉換及前端 token 級重繪成本。

本文件只定義下一階段的修改與驗收流程。任何正式預設值都必須等自動回歸、實機 soak 與人工聽感 gate 全部通過後才調整。

## 現況與證據

### 實機延遲

目前 Phase 9 的實機樣本顯示：

| 指標 | 觀測範圍 | 說明 |
| --- | ---: | --- |
| 首音延遲 | 約 2.1～3.4 s | 尚未達成 P50 ≤ 1.2 s、P95 ≤ 2.5 s |
| ASR | P50 約 0.18～0.39 s | 次要瓶頸 |
| LLM first token | warm 約 0.05～0.06 s；cold 約 0.80 s | warm 很快，冷啟動仍影響 P95 |
| first fragment | warm 約 0.11 s；cold 約 0.85 s | 主要跟隨 LLM first token |
| Edge first PCM | 約 0.25～0.75 s | 有網路分布抖動 |
| MuseTalk first batch | 約 0.28～0.44 s | startup microbatch 已有效降低等待 |
| `avatar_to_webrtc_commit` | 約 1.87～2.17 s | 目前最大且仍混合多階段的指標 |
| A/V 偏差 P95 | 約 40 ms 的近期短 soak；舊 50 輪為 95 ms | 需以新架構重新驗證 |
| 最大媒體債務 | 240 ms | 通過現有 gate |

### 資源基準

目前單一會話、MuseTalk 與 llama.cpp 啟動後的觀測值：

- Python backend 約佔 9.2 GiB GPU 記憶體。
- llama.cpp 約佔 2.1 GiB GPU 記憶體。
- 24 GiB GPU 尚有餘裕，現階段不是顯存不足。
- backend 閒置 CPU 約 2%，但仍持續維持多條媒體與模型執行緒。
- 前端 production bundle 約 1.17 MiB minified、385 KiB gzip，Vite 會發出大 chunk 警告。

### 已知負向 A/B

WebRTC media buffer 從 240 ms 直接降到 80 ms 後，單輪首音惡化到約 4.61 s，原因是 audio/video starvation 與 pacing 重建。此值已恢復為 240 ms。

因此 Phase 10 不再以大幅縮小 media buffer 作為首音策略。只有在音訊與影片已解耦，且 stage metrics 證明 queue runway 仍是瓶頸時，才允許每次最多 20 ms 的小幅 A/B。

## 現行關鍵路徑

目前 MuseTalk 回覆路徑仍然是：

```text
Edge TTS PCM
  → MuseTalk audio queue
  → Whisper feature extraction
  → MuseTalk UNet / VAE inference
  → result queue
  → paste_back_frame
  → OpenCV watermark
  → VideoFrame 建立
  → video WebRTC queue
  → audio WebRTC queue
  → WebRTC audio commit
```

在 `BaseAvatar.process_frames()` 中，音訊 enqueue 發生在嘴型貼回、影像處理與影片 enqueue 之後。影片 queue 發生 backpressure 時，音訊也會等待。

這與 ADR-0007 的音訊主時鐘方向不一致：影片允許落後、丟幀或短暫重複，但不得延後音訊。

## 不可違反的契約

所有階段都必須維持：

1. 音訊是播放時間與輪次完成判定的主時鐘。
2. TTS PCM、MuseTalk batch、影片影格與 WebRTC media 保留相同的 `turn_id`、generation、fragment sequence 與 media sequence。
3. 插話後不得送出舊 generation 的文字、PCM、嘴型影格或字幕。
4. 字幕與 history 只提交實際播放的音訊內容。
5. 首個播放 commit 後不得重播片段開頭。
6. 不得用 time-stretch、無界 queue 或追趕式 burst 掩蓋延遲。
7. 首字 onset、自然語速、片段停頓與 A/V 都不得退化。
8. telemetry 只記錄 monotonic timestamp、scalar、計數與環境資訊，不記錄逐字稿、回覆正文或音訊。
9. legacy 回覆模式保持可用，直到新路徑連續通過完整 gate。

## 優先級總覽

| 優先級 | 修改群組 | 目的 |
| --- | --- | --- |
| P0 | 分解 critical-path metrics | 把 1.9～2.1 s 的混合 stage 拆成可歸因數據 |
| P0 | 先送音訊、後處理影片 | 移除 paste-back 與影片 queue 對音訊的阻塞 |
| P0 | TTS PCM 與 MuseTalk 完整解耦 | 讓第一個音訊幀不等待 GPU 嘴型推理 |
| P1 | MuseTalk 靜音 fast path | 靜音時跳過不必要的 Whisper feature extraction |
| P1 | MuseTalk thread queue 瘦身 | 移除同程序 `multiprocessing.Queue` 的序列化與 pipe 開銷 |
| P1 | Edge TTS persistent worker 與後續預取 | 降低片段間連線與停頓，不延遲第一片段 |
| P1 | llama.cpp inference warm-up | 消除冷啟動 first-token 尖峰 |
| P2 | PCM-native ASR 與 VAD A/B | 降低語音輸入格式轉換與 endpoint 體感時間 |
| P2 | 前端 delta 批次更新與 Markdown cache | 降低 token 級 Vue 重繪與重複解析 |
| P3 | 影片靜態內容快取與 hot log 降頻 | 降低穩態 CPU 與 I/O |

## 目標模組與 seam

### `AudioClockOutput` 深模組

新增一個由 WebRTC media player 擁有的音訊主時鐘模組。建議檔案位置：

- `src/utils/audio_clock_output.py`，或
- 若實作與現有 WebRTC track 高度內聚，放在 `src/utils/webrtc.py` 的私有實作，待介面穩定後再抽檔。

外部 interface 應保持小：

```python
class AudioClockOutput:
    def submit_pcm(self, pcm, eventpoint) -> bool: ...
    def submit_video(self, frame, eventpoint, audio_position) -> bool: ...
    def discard_stale(self) -> dict[str, int]: ...
```

介面契約：

- `submit_pcm()` 是可靠、有界、按序的音訊輸出；不得因影片 queue 滿而等待影片。
- `submit_video()` 允許丟棄過期影格或替換 queue 內最舊影格。
- 兩條路徑使用相同 envelope，模組內部執行 generation fence。
- `discard_stale()` 在插話後同步清除舊 generation media。
- 第一個非靜音 PCM commit 仍觸發 `assistant_fragment`、`speaking_start` 與 history playback commit。
- 音訊不得在 queue 落後時縮短 frame interval 或 burst 追趕。

模組內部隱藏：

- asyncio queue 操作與 event-loop thread handoff。
- speech-start idle runway 修剪。
- audio pacing clock。
- video drop/repeat policy。
- stage timestamp 與 media debt 計算。
- stale generation drop 計數。

呼叫端不應知道 queue 大小、track 私有欄位、pacing rebase 或 subtitle commit 細節。

### TTS PCM fan-out seam

`BaseAvatar.put_audio_frame()` 保留現有呼叫介面，但在 decoupled 模式下深化其實作：

```text
TTS PCM
  ├─ AudioClockOutput.submit_pcm() → WebRTC audio
  └─ MuseAudioStreamHandler.put_audio_frame() → 嘴型推理副本
```

`MuseTalkAvatar.process_frames()` 在 decoupled 模式只負責影片輸出，不再把 paired audio 第二次送到 WebRTC。

legacy 與其他 avatar adapter 在第一階段保持現行 coupled 路徑；MuseTalk＋Edge 通過 gate 後，再評估是否共用新模組。

## Phase 10.0：建立可歸因基準

優先級：P0

### 修改項目

1. 將目前重疊的 `avatar_to_webrtc_commit` 拆為固定 stage：

   - `musetalk_feature_ready`
   - `musetalk_inference_first_result`
   - `avatar_pasteback_done`
   - `webrtc_audio_enqueue`
   - `webrtc_audio_commit`
   - `webrtc_video_enqueue`

2. 保留舊 `avatar_to_webrtc_commit` 一個 schema 版本作相容欄位，但文件清楚註明其值會重疊 TTS、MuseTalk 與 WebRTC，不可與其他 stage 相加。
3. `TurnMetrics` 僅允許固定 stage name，start/end 必須 idempotent。
4. soak report 增加：

   - 每個 stage 的 P50/P95。
   - Edge request 數與 retry 次數。
   - MuseTalk inference FPS。
   - idle/speech queue high-water mark。
   - audio pacing rebase 與 catch-up burst。
   - commit hash、dirty flag、config hash。

5. 產生至少 10 輪快速基準與 50 輪正式基準；快速基準只用於比較，不可取代正式 gate。

### 主要檔案

- `src/server/reply_streaming/metrics.py`
- `src/server/reply_streaming/soak.py`
- `src/server/voice_session.py`
- `src/avatars/musetalk/audio_stream_handler.py`
- `src/avatars/musetalk/avatar.py`
- `src/avatars/base.py`
- `src/utils/webrtc.py`
- `scripts/run_voice_soak.py`
- `tests/test_reply_streaming.py`
- `tests/test_speech_timing.py`

### 測試

- 固定 clock 驗證 stage 順序與 idempotency。
- report 不得包含 transcript、回覆正文、PCM 或 frame payload。
- 缺少 stage 時輸出 `null`，不得以 0 假裝完成。
- `webrtc_audio_commit` 必須由實際非靜音 audio frame 觸發。

### Gate

- 能分辨 MuseTalk inference、paste-back、audio enqueue 與實際 commit。
- 10 輪快速基準可重跑，stage 不再出現錯誤重疊解讀。
- 不改變現有播放行為。

### 回退

移除新 stage marker 即可；保留現有聚合 schema。

## Phase 10.1：現行 renderer 先送音訊

優先級：P0

### 修改項目

在尚未完整 fan-out 前，先調整 `BaseAvatar.process_frames()`：

1. 從 `res_frame_queue` 取得 paired audio 後，先完成 generation fence。
2. 先建立並 enqueue 兩個 20 ms audio frame。
3. audio enqueue 完成後才執行：

   - `paste_back_frame()`
   - OpenCV watermark
   - `VideoFrame.from_ndarray()`
   - video enqueue

4. video queue 滿時維持 drop/replace policy，不得回頭阻塞已排程音訊。
5. speech-start runway 由 audio queue 狀態決定；影片只參與 A/V 修剪，不擁有音訊 release 權限。

### 主要檔案

- `src/avatars/base.py`
- `src/utils/webrtc.py`
- `tests/test_speech_timing.py`
- `tests/test_media_fencing.py`
- `tests/test_playback_commit.py`

### 必要回歸測試

1. video queue 人為填滿時，audio enqueue 仍在兩個 audio packet interval 內完成。
2. `paste_back_frame()` 人為阻塞時，audio 不等待該函式。
3. audio envelope sequence 保持單調且沒有 duplicate。
4. video 可丟幀，audio 不丟幀、不 burst、不 time-stretch。
5. interrupt 發生於 audio enqueue 前後時，舊 generation 都不會 commit。
6. fragment subtitle 仍只在第一個非靜音 audio commit 後送出。

### Gate

- `avatar_pasteback_done` 不再位於 audio critical path。
- `webrtc_audio_enqueue` P95 不受 video queue 或 paste-back 延遲影響。
- 首字、pacing、A/V、插話測試全部通過。

### 回退

以 `reply_streaming.audio_first_renderer` 功能旗標恢復原先 video-first 順序。

## Phase 10.2：TTS PCM 與 MuseTalk 完整解耦

優先級：P0

### 修改項目

1. 建立 `AudioClockOutput` 深模組。
2. `HumanPlayer` 建立 audio/video tracks 後，把 `AudioClockOutput` 注入 avatar。
3. `BaseAvatar.put_audio_frame()` 在 feature flag 開啟時：

   - 先驗證 envelope。
   - 將 PCM 直接提交至 `AudioClockOutput`。
   - 將 PCM 副本提交至 MuseTalk audio handler。

4. MuseTalk inference 保留 paired eventpoint 與 media sequence，用於嘴型對齊與 stale fence。
5. `MuseTalkAvatar.process_frames()` 在 decoupled 模式只提交影片。
6. video frame 綁定對應 audio media position：

   - 準時：正常提交。
   - 落後一個 video frame 以內：允許提交。
   - 超過 lag budget：丟棄過期 frame。
   - 暫時沒有新 frame：短暫重複最近有效 frame。

7. audio queue 滿時使用既有 bounded backpressure；video queue 滿時 replace/drop，不得讓 audio 等待。
8. interrupt 同時清除：

   - TTS PCM queue。
   - MuseTalk feature/result queue。
   - WebRTC audio/video 舊 generation queue。
   - last repeated video item 的舊 generation。

### 主要檔案

- `src/avatars/base.py`
- `src/avatars/musetalk/avatar.py`
- `src/avatars/musetalk/audio_stream_handler.py`
- `src/utils/webrtc.py`
- 建議新增 `src/utils/audio_clock_output.py`
- `src/server/routes/webrtc.py`
- `src/server/voice_session.py`
- `tests/test_media_fencing.py`
- `tests/test_playback_commit.py`
- `tests/test_speech_timing.py`
- `tests/test_voice_session.py`

### 必要回歸測試

1. MuseTalk inference 永久阻塞時，TTS PCM 仍能正常送出 WebRTC audio。
2. video track 未啟動或 queue 滿時，audio track 仍持續 20 ms pacing。
3. audio first commit 觸發 `speaking_start`、subtitle 與 playback history；video commit 不觸發這些事件。
4. stale audio、stale video、repeated stale video 全部被丟棄。
5. 取消後沒有舊片段首字重播。
6. first PCM onset sample 不被截斷。
7. audio release interval 不低於既有 jitter 下限，catch-up burst 維持 0。
8. legacy flag 關閉時，行為與原路徑相同。

### Gate

- TTS first PCM → WebRTC audio enqueue P95 ≤ 50 ms。
- WebRTC audio enqueue → first non-silent commit P95 ≤ 250 ms。
- MuseTalk inference 或 paste-back 延遲不再增加首音時間。
- A/V offset P95 ≤ 80 ms。
- interrupt stop P95 ≤ 200 ms。
- listening resume P95 ≤ 500 ms。
- stale output = 0。

### 回退

關閉 `reply_streaming.decoupled_audio_clock`，恢復 Phase 10.1 或 Phase 9 coupled renderer。保留新 metrics。

## Phase 10.3：MuseTalk 靜音 fast path 與 thread queue

優先級：P1

### 10.3A 靜音 fast path

在 `MuseAudioStreamHandler.run_step()` 收到一個全 idle batch 時：

1. 先從 paired audio 的 `frame_type` 判斷是否全部為 idle/custom state。
2. 全 idle 時不執行：

   - `np.concatenate(self.frames)`
   - `audio2feat()`
   - `feature2chunks()`

3. 建立沒有 Whisper feature payload 的 `MuseInferenceBatch`。
4. inference thread 直接走現有 all-silence/static-frame path。
5. 任何 `frame_type == 0` 的 speech frame 都不得走 fast path。
6. custom audio/video state 維持既有行為，不得誤判為一般靜音。

### 10.3B thread queue 瘦身

目前 MuseTalk inference、process_frames 與 TTS 都是同程序 Thread。只針對 MuseTalk adapter：

1. 將 `feat_queue`、paired audio queue 與 `res_frame_queue` 改為 `queue.Queue(maxsize=...)`。
2. 不在 BaseAudioStreamHandler 一次影響所有 avatar；先由 MuseTalk override queue 實作。
3. 保留 bounded put、timeout、flush、quit event 與 generation fence。
4. 移除不再需要的 multiprocessing feeder、pickle 與 semaphore。

### 主要檔案

- `src/avatars/audio_stream_handler.py`
- `src/avatars/musetalk/audio_stream_handler.py`
- `src/avatars/musetalk/avatar.py`
- `tests/test_media_fencing.py`
- `tests/test_speech_timing.py`

### 測試

- 全 idle batch 不呼叫 `audio2feat()`。
- 含一個 speech frame 時一定呼叫 feature extraction。
- custom audio state 維持原自訂影片與音訊。
- queue 滿時可中止，不會造成 render thread 永久卡死。
- interrupt flush 能清除 feature/result/audio 三段 queue。
- envelope 不因改用 thread queue 遺失或重排。

### Gate

- idle CPU、GPU utilization 與 power draw 相對 Phase 10.0 baseline 下降。
- speech inference FPS 不低於 baseline 95%。
- GPU memory 不增加超過 10%。
- sustained 10 分鐘播放沒有 queue growth、deadlock 或 stale output。

### 回退

分別提供 `musetalk.silence_fast_path` 與 `musetalk.thread_queue` 旗標；兩項可獨立回退。

## Phase 10.4：Edge TTS warm path 與後續片段預取

優先級：P1

### 原則

- 第一個可播回覆片段永遠立即開始，不能為了合併等待更多 LLM 文字。
- 第一片段播放 commit 前，不允許無界並行 Edge request。
- 預取只能改善後續片段間停頓，不能改變播放順序或 history commit。

### 10.4A persistent async worker

1. EdgeTTS 建立一條長生命週期 async worker 與 event loop。
2. 移除每個 fragment 的 `asyncio.run()`。
3. worker 接收 `PlayableFragment`，輸出帶 envelope 的 PCM frame stream。
4. close、interrupt 與 provider timeout 必須能取消 active coroutine。
5. Edge provider 仍可能每 fragment 建立遠端 stream；文件不得把 persistent event loop 誤稱為 persistent Edge connection。

### 10.4B bounded prefetch

1. 第一片段開始輸出 PCM 後，允許預取下一個 fragment。
2. 每個 fragment 使用獨立的 bounded PCM buffer 與 envelope。
3. release gate 保證 fragment N 完成或被取消後，才播放 N+1。
4. 最多預取一個 fragment，避免 Edge rate limit 與記憶體膨脹。
5. queue backpressure 超過預算時停止預取，回到序列合成。
6. 不在此階段合併已註冊 fragment 的文字，避免 subtitle/history 邊界混淆。

### 10.4C provider A/B

只有 Edge first PCM 的正式 P95 仍無法達標時才執行：

1. 選擇現有 keyless、本機可部署的 TTS adapter。
2. 以同一組文本比較：

   - first encoded/PCM P50/P95。
   - 完整合成 real-time factor。
   - 首字完整度。
   - 中文自然度與停頓。
   - GPU contention。

3. 沒有數據支持時保持 Edge 為預設。

### 主要檔案

- `src/tts/base.py`
- `src/tts/engines/edge.py`
- `src/server/reply_streaming/channel.py`
- `src/server/reply_streaming/retry.py`
- `tests/test_speech_timing.py`
- `tests/test_playback_commit.py`
- `tests/test_reply_mode_tts_timing.py`

### 測試

- 第一片段不等待第二片段。
- persistent worker 重用同一 event loop。
- 預取片段不能早於前一片段播放。
- interrupt 取消 active 與 prefetched fragment。
- retry 發生於首 PCM 前後時遵守既有 retry budget。
- playback commit 後不得重播 fragment onset。
- worker close 不遺留 Thread、Task 或 queue item。

### Gate

- Edge first PCM P50/P95 不退化。
- 片段間非語意靜音 P95 降低。
- request 數、retry 與 timeout 沒有不可接受增加。
- stale output、重播首字與 sample splice 維持 0。

### 回退

關閉 `tts.edge_persistent_worker` 或 `tts.edge_prefetch`，回復 Phase 9 序列 `asyncio.run()` 路徑。

## Phase 10.5：llama.cpp、ASR 與 VAD 次要延遲

優先級：P1～P2

### 10.5A llama.cpp inference warm-up

1. llama-server health ready 後送出一次不寫入 history 的最小推論。
2. 使用與正式請求相同的 model、chat template 與 system prompt cache 路徑。
3. 限制為 1 個輸出 token，timeout 不得阻止 backend 啟動。
4. warm-up 失敗只記錄 scalar 狀態，正式第一輪仍可重試。

Gate：backend 冷啟動後第一輪 LLM first token P95 接近 warm baseline，不再出現約 0.8 s 的固定冷啟動尖峰。

### 10.5B PCM-native ASR seam

1. ASR interface 增加 PCM-native 輸入：`transcribe_pcm(audio, sample_rate)`。
2. FunASR adapter 直接接收 numpy PCM 或 waveform。
3. 其他只接受檔案的 ASR adapter 由 base fallback 在內部轉成 WAV。
4. `VoiceTurnSession` 不再先建立記憶體 WAV 再交給 FunASR 解碼。
5. 對相同 fixture 比較 PCM 與 WAV 的文字結果及延遲。

Gate：結果相同，ASR P95 不退化；若改善低於量測雜訊，可保留 fallback 而不調整預設。

### 10.5C VAD endpoint A/B

1. 正式接上 `vad_endpoint` stage marker。
2. 新增「最後一個活動語音 frame → 第一個回覆音訊」體感 metric，與 domain 定義的「確認發話結束 → 首音」分開呈現。
3. 比較 `min_silence_ms=500` 與 `350`：

   - premature cut 次數。
   - 吃句尾或拆成兩輪。
   - 使用者停止說話至首音。
   - ASR 文字品質。

4. 維持 `speech_pad_ms=150`，一次只變更 endpoint 變數。

Gate：350 ms 沒有增加 premature cut 或句尾遺失才可成為建議值。

### 主要檔案

- `src/server/server.py`
- `src/llm/`
- `src/asr/base.py`
- `src/asr/engines/funasr.py`
- `src/server/voice_session.py`
- `src/vad/segmenter.py`
- `src/server/runtime_settings.py`
- `tests/test_funasr.py`
- `tests/test_voice_session.py`
- VAD 相關測試

## Phase 10.6：前端 delta 與 bundle 效率

優先級：P2

### 修改項目

1. assistant delta 先進 per-turn buffer。
2. 以 `requestAnimationFrame` 或最多每 32 ms 合併一次 DOM 更新。
3. sequence fence 在進 buffer 前執行，stale、duplicate、out-of-order delta 不進 UI。
4. 每個 assistant message 保存：

   - raw streaming text。
   - cached rendered HTML。
   - render dirty flag。

5. streaming 時只做必要 Markdown 更新；完整 `marked` 與 syntax highlight 在 done 或偵測到 code fence 後執行。
6. `highlight.js` 改為動態載入，並只載入實際支援語言。
7. DebugPanel、非首屏設定內容與大型第三方 module 採 dynamic import。
8. disconnect、clear history 與 turn cancelled 時清除 pending animation frame/buffer。

### 主要檔案

- `web/src/App.vue`
- `web/src/components/DebugPanel.vue`
- `web/src/components/SettingsPanel.vue`
- `web/src/composables/useWebRTC.js`
- `web/tests/defaultPromptSettings.test.js`
- 建議新增前端 delta 行為測試

### 測試

- 同一 animation frame 內的多個 delta 只觸發一次 message render。
- stale/out-of-order/duplicate delta 仍被拒絕。
- done 前後 raw text 完全相同。
- disconnect 後沒有延遲 callback 修改已清除訊息。
- Markdown code fence 與一般中文回覆結果不變。
- production build 成功，首屏 chunk 下降且不再把完整 highlight.js 放進主 chunk。

### Gate

- 200 個快速 delta 不造成 200 次完整 Markdown parse。
- 長回覆期間輸入框、麥克風按鈕與設定按鈕維持可互動。
- 前端文字可見時間不晚於目前 assistant delta 行為。

### 回退

以 `ui.batched_assistant_delta` 關閉批次更新，回復現有逐 delta 路徑。

## Phase 10.7：影片穩態成本與清理

優先級：P3

### 修改項目

1. watermark 在 avatar frame 載入或建立時預先合成，不在每個 render frame 重畫。
2. idle/static frame 保存已處理 ndarray；只有嘴型輸出或動態 overlay 才建立新 image。
3. 將高頻 media boundary、queue size 與 FPS log 改為：

   - debug level，或
   - 每 5 秒聚合一次的 scalar log。

4. 移除 Phase 10 診斷用臨時 log、prototype 與未使用 feature flag。
5. 檢查 Thread、event loop、queue 與 semaphore 在 session close 後全部回收。

### Gate

- idle CPU 與 log I/O 相對 Phase 10.0 下降。
- 靜態畫面、水印位置與嘴型品質沒有視覺退化。
- 建立及關閉 20 次 WebRTC session 後，Thread 與 GPU memory 回到穩定範圍。

## 執行順序與停止條件

嚴格依下列順序執行：

```text
10.0 metrics/baseline
  → 10.1 renderer audio-first
  → 10.2 TTS PCM / MuseTalk decoupling
  → 10.3 silence fast path + thread queue
  → 10.4 Edge worker + bounded prefetch
  → 10.5 LLM/ASR/VAD
  → 10.6 frontend delta/bundle
  → 10.7 cleanup + final gate
```

每個 phase 必須：

1. 先建立能對應該症狀的 deterministic regression test。
2. 一次只改一個排程或效能變數。
3. 跑 targeted tests。
4. 跑完整 Python/Web 回歸。
5. 跑 5～10 輪快速實機 A/B。
6. 指標改善且可靠性不退化才進下一 phase。
7. 指標惡化立即回退該 feature flag，不把多個變數混在一起調整。

如果 Phase 10.2 已讓首音達標，仍可執行 10.3 與 10.6 的資源優化；10.4 provider A/B 則只有在 Edge P95 仍是主要瓶頸時執行。

## 測試矩陣

### 自動測試

| 類型 | 必須覆蓋 |
| --- | --- |
| metrics | stage 順序、缺值、隱私、聚合、schema 相容 |
| audio clock | audio 不受 video queue、paste-back、MuseTalk 阻塞 |
| pacing | 20 ms frame interval、無 catch-up burst、PTS 單調 |
| A/V | video lag drop/repeat、offset budget |
| fencing | LLM、TTS PCM、MuseTalk、audio/video queue、repeat frame |
| playback | subtitle/history 只提交已播放 audio |
| onset | 首字低能量 onset、preroll、retry 不重播 |
| interrupt | LLM/TTS/MuseTalk/WebRTC 各時點取消 |
| idle path | silence fast path、custom state、queue flush |
| Edge | persistent loop、prefetch order、retry、close |
| ASR/VAD | PCM/WAV 等價、endpoint A/B fixture |
| frontend | delta batching、sequence fence、Markdown cache、cleanup |

### 實機組合

至少覆蓋：

1. 文字輸入＋legacy。
2. 文字輸入＋streaming。
3. 語音輸入＋legacy。
4. 語音輸入＋streaming。
5. 短句、長句、弱標點、無標點。
6. LLM 階段插話。
7. TTS 尚未出首 PCM 時插話。
8. MuseTalk inference 中插話。
9. 已播放一部分後插話。
10. 斷線、重連、重新建立 session。

## 最終 SLO 與資源 Gate

| 指標 | 最終目標 |
| --- | ---: |
| 首音延遲 P50 | ≤ 1.2 s |
| 首音延遲 P95 | ≤ 2.5 s |
| TTS first PCM → WebRTC enqueue P95 | ≤ 50 ms |
| WebRTC enqueue → first commit P95 | ≤ 250 ms |
| A/V offset P95 | ≤ 80 ms |
| interrupt stop P95 | ≤ 200 ms |
| listening resume P95 | ≤ 500 ms |
| 最大 media debt | ≤ 2 s |
| stale output | 0 |
| catch-up burst | 0 |
| retry after playback commit | 0 |
| startup microbatch 後 sustained inference | 不低於 baseline 95% |
| GPU memory | 不高於 baseline 110% |
| session close 後 Thread/Task leak | 0 |

正式通過條件：

- 至少 50 輪新實機 soak。
- 報告來自同一乾淨 commit。
- 報告包含 config hash、硬體、provider、model 與 dirty flag。
- Python 完整回歸通過。
- Web 完整測試與 production build 通過。
- 人工驗收首字、語速、停頓、嘴型、插話及重連。

## 風險與防護

| 風險 | 防護 |
| --- | --- |
| 音訊先播但嘴型尚未準備 | 保留短 video runway；落後時重複最近有效影格，限制 A/V offset |
| 直接 PCM fan-out 造成雙重音訊 | decoupled mode 下 renderer 禁止再次 enqueue paired audio；加 duplicate sequence test |
| video 落後持續累積 | 以 audio media position 丟棄過期 video，不允許無界 queue |
| interrupt 後重複最後舊影格 | repeat cache 也執行 generation fence |
| thread queue 改造產生 deadlock | bounded timeout、quit event、滿 queue 中止測試 |
| 靜音 fast path 誤判首字 | 只以 `frame_type` 判斷，任何 speech frame 都走 feature extraction |
| Edge 預取造成亂序或 rate limit | 最多預取一片、per-fragment buffer、release gate、可獨立關閉 |
| warm-up 污染 history | warm-up 不經 session/history，使用獨立最小 request |
| 350 ms VAD 吃句尾 | 固定 150 ms pad、fixture A/B、premature-cut gate |
| UI batching 延遲可見文字 | 每 frame 或 ≤32 ms flush，done 強制立即 flush |
| 新 metrics 增加 hot-path I/O | 記憶體 scalar 累積，turn 結束一次輸出 |

## 不應執行的捷徑

- 不再把 WebRTC buffer 一次從 240 ms 降到 80 ms。
- 不以持續小 MuseTalk batch 換取 startup 延遲；首批後恢復 batch 8。
- 不以 time-stretch、略過 audio frame 或 burst 追趕。
- 不讓 video queue 擁有 audio release 權限。
- 不把 assistant delta 當成 history 或 subtitle commit。
- 不為降低首音而取消 generation fence 或 retry-after-commit 防護。
- 不在第一片段前等待第二片段以合併 Edge request。
- 不在缺少 provider A/B 時直接更換正式 TTS。

## 執行檢查表

### Phase 10.0

- [x] 拆分 critical-path stage metrics。
- [x] 新增隱私、順序與 schema 測試。
- [ ] 產生 10 輪與 50 輪 baseline。

### Phase 10.1

- [x] renderer 改為 audio-first。
- [x] video blocked / paste-back blocked regression 通過。
- [x] 快速實機 A/B 改善且無 A/V 退化（coupled renderer path：A/V P95 40 ms）。

### Phase 10.2

- [ ] 建立 `AudioClockOutput` 深模組（目前以 BaseAvatar seam 實作，待抽成獨立模組）。
- [x] TTS PCM 直接 fan-out 至 WebRTC 與 MuseTalk。
- [x] MuseTalk renderer 不再重送 speech audio；仍保留 idle runway。
- [x] audio/video stale fence 與 interrupt 測試通過。
- [ ] 首音與 A/V 快速 gate 通過（首音 P50 已接近/達標，A/V 尚未達 80 ms）。

### Phase 10.3

- [x] 全 idle batch 跳過 Whisper feature extraction。
- [x] MuseTalk 改用同程序 bounded thread queue。
- [ ] idle resource 與 sustained RTF gate 通過。

### Phase 10.4

- [x] Edge persistent async worker。
- [x] bounded next-fragment prefetch。
- [x] retry、順序、取消與首字回歸通過。
- [x] 依數據決定是否進行 provider A/B。

### Phase 10.5

- [ ] llama.cpp 最小 inference warm-up。
- [ ] FunASR PCM-native path。
- [ ] VAD endpoint marker 與 350/500 ms A/B。

### Phase 10.6

- [ ] 前端 delta 以 animation frame 批次更新。
- [ ] Markdown render cache。
- [ ] highlight.js 與非首屏 module 動態載入。
- [x] Web test 與 production build 通過。

### Phase 10.7

- [ ] watermark/idle frame cache。
- [ ] hot log 降頻與診斷碼清理。
- [ ] session lifecycle leak 測試。
- [x] Python/Web 完整回歸通過。
- [x] 50 輪正式 soak 通過。
- [ ] 人工驗收通過。
- [ ] 乾淨 commit 上產生正式報告。

## 完成定義

此 ticket 只有在下列條件全部成立時才能標記 resolved：

1. 音訊 critical path 不包含 MuseTalk inference、paste-back 或 video queue wait。
2. audio/video 使用同一 envelope 與 audio media position 對齊。
3. 影片落後時會丟幀或重複，音訊不延遲、不丟幀、不加速。
4. MuseTalk idle batch 不再執行不必要的 Whisper feature extraction。
5. Edge 第一片段不等待合併，後續預取保持順序與 retry 契約。
6. 冷啟動 LLM first token 尖峰已有 warm-up 或正式數據說明。
7. PCM-native ASR 與 VAD endpoint 由 A/B 決定，不以猜測調整預設。
8. 前端 delta batching 不改變可見文字或 stale fence。
9. 全部自動回歸、50 輪實機 soak 與人工驗收通過。
10. 正式 SLO 與資源 gate 全部達標。

## Comments

- 2026-08-31：根據 Phase 9 stage telemetry、5 輪與單輪實機 smoke、舊 50 輪 soak、runtime 資源採樣、ADR-0007 與現行 `BaseAvatar.process_frames()` 路徑建立本規劃。
- 2026-08-31：WebRTC media buffer 80 ms A/B 導致首音約 4.61 s，已確認不可作為首音捷徑並恢復 240 ms。
- 2026-08-31：本規劃選擇 `AudioClockOutput` 作為新 seam，集中 audio pacing、video lag policy、generation fence、speech-start runway 與 commit telemetry，避免這些規則散落在 avatar、voice session 與 WebRTC caller。
- 2026-08-31：Phase 10 實作第一批完成：`BaseAvatar` 提供 direct PCM fan-out；MuseTalk 使用 bounded thread queues、startup microbatch 與 idle fast path；新增 `musetalk_inference_first_result`、paste-back、enqueue、commit stages。後端 unittest 221 項通過，前端 23 項與 production build 通過。
- 2026-08-31：實機 3 輪報告見 `real-soak-phase10-direct-audio-3b.json`：first_audio P50 1.192 s / P95 1.879 s，avatar-to-WebRTC commit P50 0.549 s，A/V offset P95 238 ms，故首音與 A/V gate 尚未全部通過；完整 50 輪 soak 尚未執行。
- 2026-08-31：video runway 強制 80 ms 的 A/B（`real-soak-phase10-direct-audio-3c.json`）使 A/V offset P95 回升至 850 ms，已回退；保留 audio queue runway gate，後續需以獨立 clock seam 解決。

### 實作後差異紀錄（2026-08-31）

| 指標 | Phase 9 近期 5 輪基線 | Phase 10 direct audio 3 輪 | 差異與判讀 |
|---|---:|---:|---|
| first_audio P50 | 2.278 s | 1.192 s | 約降低 1.086 s（47.7%）；已接近 1.2 s 目標 |
| first_audio P95 | 3.426 s | 1.879 s | 約降低 1.547 s（45.1%） |
| avatar-to-WebRTC commit P50 | 1.939 s | 0.549 s | 約降低 1.390 s（71.7%）；證實不再等待 paste-back 才送 PCM |
| TTS first PCM → audio enqueue | 約 0.520 s | 0.302 s | TTS/queue path 約降低 42%；由直接 fan-out 量測 |
| A/V offset P95 | 40 ms | 238 ms | 退化；目前以 audio runway gate 抑制 video 超前，仍需獨立 `AudioClockOutput` 與更細緻 clock 對齊 |
| stale drop | 0 | 379 | direct audio 收尾時 MuseTalk backlog 仍會被 generation fence 丟棄；無 stale output，但需在正式 50 輪前處理資源回收 |

自動驗證：後端 `unittest discover` 221/221、前端 Node tests 23/23、Vite production build、Python compileall 與 `git diff --check` 全部通過。實機 3 輪不是正式 SLO gate；50 輪、interrupt/resume 與人工首字驗收仍列為未完成。

- 2026-09-01：針對實機「斷續電子音與嘴型錯位」完成故障修復。根因是未通過 A/V gate 的 direct PCM fan-out 被 `reply_streaming.enabled` 隱式啟用，與 renderer 音訊形成雙 producer；改為 `decoupled_audio_clock` 明確 opt-in 且預設關閉，恢復單一 coupled audio master。另移除 MuseTalk result queue 的重複 idle backlog，idle queue 滿時不再阻塞 inference，speech-start WebRTC 成對 runway 由 80–120 ms 降至一個 40 ms video frame。
- 2026-09-01：正式 50 輪 WebRTC 實機 soak `real-soak-audio-quality-fix-final-50.json` 全部 gate 通過：first audio P50 1.153 s / P95 1.706 s、A/V offset P95 40 ms、interrupt stop P95 0.61 ms、listening resume P95 302 ms、max media debt 240 ms、stale output 0；涵蓋 4 次播放中斷、3 次 LLM 中斷與 2 次重連。後端回歸 226/226、前端 23/23、production build、compileall 與 diff check 通過。direct PCM 實驗路徑仍維持預設關閉，ticket 其他 Phase 10 資源最佳化與人工聽感 gate 尚未完成，因此狀態維持 in-progress。
- 2026-09-03：完成 Edge 冷啟動修正：服務載入設定後以背景執行緒預熱 Edge，ready 前等待預熱結束；預熱只消費第一個音訊資料塊且失敗不阻止啟動。正常首包逾時改為 2.5 秒，重試與收到首音後的續包逾時分離為 15 秒，避免冷連線無回應或串流中途以首包短逾時提前收尾。新增 startup／continuation regression tests；完整 Python 回歸 251 項（1 項既有 skip）通過，狀態維持 in-progress。
- 2026-09-03：停頓診斷後先做控制台輪次提交對齊（ADR-0010），再完成 Phase 10.4：Edge 長生命週期本機 event loop、第一片段出聲後最多預取下一段、插話丟棄預取、輪詢逾時不得當成合成失敗。正式預設維持 Edge，不在缺少 soak 數據時切本機 TTS。完整 Python 259 項（1 skip）與前端 34 項通過。
