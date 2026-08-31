# Phase 8：保留片段首音並禁止音訊追幀加速

Type: task
Status: ready-for-human

## 問題摘要

目前數字人在文字輸入、語音輸入、`legacy` 與 `streaming` 回覆模式下，都可能出現兩種聽感問題：

1. 每個回覆語音片段的首字沒有聲音，或首字聲母被切掉。
2. 播放過程偶爾短暫加速、跳音，或數個字突然擠在一起。

這兩個現象位於文字／語音輸入分流之後的共用管線，因此不能在前端輸入方式或 reply mode 分支個別修正。修正必須落在共用的 Edge TTS PCM 邊界與 WebRTC 音訊排程邊界，並同時適用於兩種輸入與兩種回覆模式。

本文件只定義分析、修改順序、測試與實機驗收方式；尚未修改 production code。

## 適用範圍

第一階段保證：

- Edge TTS。
- MuseTalk。
- 16 kHz mono PCM、每幀 20 ms。
- `legacy` 與 `streaming` 共用修正。
- 文字輸入與語音輸入共用修正。

本階段不處理：

- 更換 TTS 供應商或聲線。
- 瀏覽器本身的 WebRTC jitter buffer 實作。
- 以 time-stretch 或重採樣掩蓋排程問題。
- 以延後字幕或嘴型來掩蓋音訊錯誤。
- 非 Edge TTS／非 MuseTalk 路徑的相同 SLO 保證。

## 不可違反的既有契約

本修正必須遵守 `CONTEXT.md` 與 ADR-0007：

- 音訊主時鐘是播放進度的權威。
- 音訊不得等待 MuseTalk 保留所有影格。
- 嘴型落後時可以丟幀或重複最近有效影格，音訊不得加速追趕。
- 輪次隔離、generation fence、已播回覆 commit 邊界不得因排程修正而失效。
- 觀測資料預設不得保存逐字稿、模型回覆正文或原始音訊。

## 現況資料流

```text
可播回覆片段
  → EdgeTTS.synthesize_fragment()
  → EdgeTTS._stream_with_retry()
  → 每次建立新的 _EdgePCMEmitter
  → 每次建立新的 _StreamingSilenceTrimmer
  → 16 kHz / 20 ms PCM frame
  → BaseAudioStreamHandler.queue
  → MuseAudioStreamHandler.run_step() 批次取 batch_size * 2 幀
  → MuseTalk inference / process_frames
  → PlayerStreamTrack.audio queue
  → PlayerStreamTrack.recv()
  → PlayerStreamTrack.next_timestamp()
  → WebRTC / browser jitter buffer
```

`legacy` 與 `streaming` 雖然有不同的文字交付與 history 契約，最終仍共用上述 TTS、Avatar 與 WebRTC 音訊路徑，所以兩種模式聽起來都可能發生相同問題。

## 已確認的根因與風險排序

### 根因一：每個 TTS 片段都會重新做破壞性的開頭靜音裁切

可信度：已重現，最高。

`src/tts/engines/edge.py::_StreamingSilenceTrimmer` 使用：

- 10 ms RMS frame。
- `threshold=1e-4`。
- `leading_pause_seconds=0.04`。
- 最多只保留最後 40 ms 的未確認開頭。

在第一個 RMS 高於 `1e-4` 的音框出現之前，較早的取樣會從 `deque(maxlen=4)` 被永久移除。低能量聲母、摩擦音、送氣音或漸強起音可能低於門檻，但仍是有效語音，不應被視為可刪除的供應商 padding。

每個 `_EdgePCMEmitter` 都會建立新的 trimmer，而每個可播回覆片段都會建立新的 emitter。因此裁切不是每輪只做一次，而是每個片段都重新做一次，與「每段首字」的症狀一致。

最小重現：

```bash
.venv/bin/python - <<'PY'
import numpy as np
from src.tts.engines.edge import _StreamingSilenceTrimmer

rate = 16000
quiet_onset = np.full(int(rate * 0.08), 5e-5, dtype=np.float32)
voiced = np.full(int(rate * 0.02), 0.1, dtype=np.float32)
source = np.concatenate((quiet_onset, voiced))
trimmer = _StreamingSilenceTrimmer(rate)
out = np.concatenate((trimmer.feed(source), trimmer.finish()))

print({
    "input_samples": source.size,
    "output_samples": out.size,
    "lost_onset_ms": (source.size - out.size) / rate * 1000,
})
assert out.size == source.size, "首字低能量起音被裁掉"
PY
```

現行結果：

```text
{'input_samples': 1600, 'output_samples': 960, 'lost_onset_ms': 40.0}
AssertionError: 首字低能量起音被裁掉
```

### 根因二：20～100 ms 的播放落後會以零等待追幀

可信度：伺服器排程層已重現；實機聽感仍需用封包間隔與錄音對時確認。

`src/utils/webrtc.py::PlayerStreamTrack.next_timestamp()` 使用：

```python
AUDIO_PTIME = 0.020
MAX_PACING_LAG = 0.100
```

只有 `lag > 100 ms` 才會重設音訊時鐘。當執行緒、GPU 推論或 event loop 落後 20～100 ms 時，數個既定 deadline 已經位於過去，`wait` 會小於等於零，後續多個音訊幀不會 sleep，形成追幀突發。

最小重現使用實際 `PlayerStreamTrack.next_timestamp()` 模擬 90 ms 卡頓，現行結果是：

```text
封包交付間隔：90 ms, 0 ms, 0 ms, 0 ms, 10 ms
```

也就是四個不同 PTS 的 20 ms 音訊幀在相同牆鐘時間交付。瀏覽器 jitter buffer 可能平滑、丟棄或直接呈現這個突發，因此實機可能聽成突然加速、跳音或節奏壓縮。

### 放大因素：MuseTalk 以批次產生媒體

可信度：已確認架構行為，但不是單獨根因。

`MuseAudioStreamHandler.run_step()` 每次讀取 `batch_size * 2` 個 20 ms 音訊幀，MuseTalk 推論與 `process_frames()` 也以批次產生結果。批次產生本身可以接受，前提是 WebRTC 音訊出口要把每幀穩定排成 20 ms；目前 100 ms 門檻留下了可追幀區間，所以批次行為會放大聽感。

### 次要風險：Edge TTS 重試以 sample 數跳過重新合成的開頭

可信度：程式風險已確認；只有 Edge stream 中斷時才會發生，需由 runtime log 關聯實機個案。

`EdgeTTS._stream_with_retry()` 會重新合成完整片段，再用前一次已送出的 `emitted_samples` 當作 `skip_samples`。如果兩次遠端合成的音素時間軸、前置 padding 或語速不完全一致，相同 sample offset 可能落在不同音素內，造成重試接點缺音或局部擠壓。

既有測試使用相同的 deterministic MP3 fixture，只能證明完全相同音訊不會重複，不能證明兩次稍微不同的遠端合成可以安全地 sample-aligned 接續。

## 已排除或不是主要根因的項目

- 取樣率不一致：TTS、Avatar、WebRTC 都使用 16 kHz。
- 音訊幀長不一致：正常輸出為 320 samples，即 20 ms。
- `prepare_speech_start()`：目前只移除沒有 eventpoint 的成對 idle media，看到首個 speech eventpoint 即停止，不是首字裁切的主要位置。
- `MOUTH_ACTIVITY_THRESHOLD`：低能量幀可能改用靜態嘴型，但原始音訊仍會送出；這會影響嘴型，不會直接刪除聲音。
- 文字／語音輸入分流：輸入來源只影響 STT 前置階段，兩者最終共用發生問題的音訊路徑。
- reply mode 設定：`legacy` 與 `streaming` 都共用 Edge TTS、MuseTalk 與 WebRTC 出口，因此不應用 mode-specific workaround。

## 為何現有測試全部通過

現有靜音裁切測試只涵蓋：

- 完全為零的開頭與結尾 padding。
- 明顯高於門檻的固定振幅語音。
- streaming trim 與 batch trim 是否輸出相同。

它沒有驗證「batch 與 streaming 可能同樣錯」，也沒有涵蓋低於 activity threshold 但仍屬於語音起音的取樣。

現有 pacing 測試主要注入約 1 秒卡頓，能觸發 `MAX_PACING_LAG` 保護；它沒有測試 20～100 ms 的門檻下卡頓，所以無法捕捉零等待追幀。

目前相關測試命令：

```bash
.venv/bin/python -m unittest -v \
  tests.test_speech_timing.EdgeTTSStreamingTests \
  tests.test_speech_timing.WebRTCPacingTests \
  tests.test_media_fencing.MuseTalkEnvelopePropagationTests
```

現況為 18 項通過，但不代表使用者回報的兩個症狀已被覆蓋。

## 目標行為契約

### 首音保護契約

1. 靜音裁切只能移除可辨識為供應商／codec padding 的區段，不能移除可能屬於語音的低能量起音。
2. 每個可播回覆片段的第一個音素都必須保留。
3. trimmer 不得因輸入 chunk 邊界不同而改變結果。
4. 尾端 trimming 先維持現況，避免同一修正同時改變過多變數。
5. 全靜音片段不得被錯誤轉成非靜音，也不得造成例外。
6. 不得為了保留首音而恢復數百毫秒的 Edge 前置 padding，造成首音延遲明顯倒退。

### 音訊排程契約

1. 音訊是主時鐘；影像不得反向拖慢或加速音訊。
2. 一個音訊幀已經逾期時，可以立即交付該幀，但後續音訊幀不得為了追上舊 deadline 以零等待連續交付。
3. 發生任何正 lag 並選擇立即交付後，下一個 20 ms 音訊幀必須以新的牆鐘基準排程。
4. RTP PTS 必須維持單調，每幀仍增加 320 ticks；修正牆鐘排程不能倒退或重複 PTS。
5. 影像仍可依共享音訊主時鐘跳過過期 frame，不得由 video track 重設 audio master clock。
6. generation 必須在 dequeue 後及 pacing await 後重新檢查，不能因排程改寫重新放出 stale media。

### 重試接續契約

1. 不得假設兩次遠端 TTS 合成在 sample level 完全相同。
2. 首個 WebRTC 非靜音音訊幀 commit 後，不得重新合成完整片段再以 sample offset 接續。
3. commit 前若要重試，必須能丟棄該片段尚未 commit 的所有 PCM 與 MuseTalk 結果，再從片段開頭重來。
4. 無法證明安全接續時，應 fail closed 並結束剩餘片段，不得輸出可能缺字或重複的接續音訊。

## 目標設計

### A. 使用雙門檻與有限 pre-roll 保護首音

不要只把 `threshold=1e-4` 任意調低，也不要只把 `leading_pause_seconds` 無限制加長。建議把「確認已進入正常語音」和「決定語音可能從哪裡開始」拆成兩個門檻：

- `activity_threshold`：沿用較高 RMS 門檻，用來確認正常語音已開始。
- `onset_threshold`：較低門檻，用來標記可能的低能量語音起點。
- `max_preroll_seconds`：限制最多保留的待判定開頭，避免恢復整段 Edge padding。
- `silence_guard_seconds`：若 onset 前為真正靜音，只保留短安全距離。

建議狀態流程：

```text
尚未確認語音
  ├─ RMS <= onset_threshold
  │    → 視為 padding 候選，只留有限 ring buffer
  ├─ onset_threshold < RMS <= activity_threshold
  │    → 記住最早可能 onset，不立即丟棄
  └─ RMS > activity_threshold
       → 確認語音開始
       → 從最早 onset 候選前的 safety guard 開始輸出
       → 若沒有 onset 候選，只輸出短 silence guard + active frame
```

門檻值不能只憑主觀設定。先用合成 fixture 建立行為範圍，再以數個 Edge TTS 本機臨時樣本觀察 padding RMS 與弱起音 RMS；除非明確開啟本機診斷，正式 log 不得記錄原始 PCM。

保守初始範圍：

- frame：10 ms。
- `activity_threshold`：維持 `1e-4` 作為第一版基準。
- `onset_threshold`：由 PCM 一至數個 LSB 的量級開始驗證，不直接寫死在文件中。
- 最大待判定 pre-roll：120～160 ms。
- onset 前 safety guard：20～40 ms。

如果實際 Edge padding 與弱起音無法僅用能量可靠分離，正確取捨是保留更多開頭而增加少量延遲，不是繼續破壞首音。

### B. 音訊逾期立即重設牆鐘，不做 catch-up burst

音訊排程應與影像排程分開處理：

```python
deadline = audio_start + frame_count * AUDIO_PTIME
lag = now - deadline

if lag > tolerated_clock_jitter:
    rebase_audio_clock_to(now)
    deadline = now

wait = deadline - now
if wait > 0:
    await asyncio.sleep(wait)
```

關鍵不是把 `MAX_PACING_LAG` 從 100 ms 改成另一個任意大門檻，而是建立不追幀的不變條件：一旦當前音訊幀因逾期而立即交付，下一幀的 deadline 必須從這次交付時間往後 20 ms。

可容許極小的 clock jitter tolerance，避免浮點誤差造成每幀 rebase；但 tolerance 不得大到允許一個完整 20 ms frame 的追趕。測試應驗證行為，而不是綁死某個實作常數。

video track 維持以下策略：

- 讀取共享 audio master clock。
- 過期時跳過足夠的 video PTS／frame。
- 不呼叫會移動 audio master clock 的 `rebase()`。
- 可重複最近有效影格，但不得讓 audio queue 等待。

### C. 重試改以 commit 狀態決定，不做不安全的 sample splice

建議將重試判斷分成三種狀態：

| 狀態 | 允許行為 |
|---|---|
| 尚未產生可用 PCM | 在共用 retry budget 內重試完整片段 |
| 已產生 PCM、但該片段尚未 WebRTC commit | 只有能原子清除該片段所有下游資料時，才可從頭重試 |
| 已有非靜音 WebRTC frame commit | 不得重試或 sample splice；終止剩餘片段並回報結構化錯誤 |

若現有 Edge TTS 層無法得知 fragment playback commit，先把 commit-aware predicate／callback 從 `VoiceTurnSession` 或 playback coordinator 傳入，不能以 `_EdgePCMEmitter.emitted` 代替使用者已收到的 commit。

## 完整修改流程

### Step 0：鎖定基線並建立兩個紅燈回饋迴圈

在修改 production code 前，先把已重現的 inline harness 轉成正式測試。

#### 0.1 首音遺失紅燈測試

在 `tests/test_speech_timing.py` 的 `EdgeTTSSilenceTests` 增加：

```python
def test_preserves_low_energy_onset_before_confirmed_speech(self):
    ...
```

fixture 至少包含：

- 80 ms、振幅低於 `activity_threshold` 但非零的 onset。
- 20 ms 明顯有聲 frame。
- 分多次、不規則 chunk size 呼叫 `feed()`。
- `finish()` 後確認低能量 onset 未被截掉。

再增加：

```python
def test_each_fragment_preserves_its_own_low_energy_onset(self):
    ...
```

連續建立兩個獨立 trimmer／emitter，確認第二片段不會因重新初始化而失去首音。

執行：

```bash
.venv/bin/python -m unittest -v \
  tests.test_speech_timing.EdgeTTSSilenceTests.test_preserves_low_energy_onset_before_confirmed_speech \
  tests.test_speech_timing.EdgeTTSSilenceTests.test_each_fragment_preserves_its_own_low_energy_onset
```

修改前兩項都必須失敗；若測試修改前通過，代表測試沒有捕捉目前症狀，不能進入 Step 1。

#### 0.2 追幀加速紅燈測試

在 `WebRTCPacingTests` 增加：

```python
async def test_audio_does_not_catch_up_after_sub_threshold_stall(self):
    ...
```

使用 fake monotonic clock：

1. 送出第一幀。
2. 將牆鐘推進 90 ms。
3. 連續要求至少五個 timestamp。
4. fake `asyncio.sleep()` 必須同步推進 fake clock。
5. 第一個逾期 frame 可以立即交付。
6. 後續 frame 必須恢復接近 20 ms 的間隔，不得出現連續 0 ms 間隔。
7. PTS 必須保持 `0, 320, 640, ...`。

執行：

```bash
.venv/bin/python -m unittest -v \
  tests.test_speech_timing.WebRTCPacingTests.test_audio_does_not_catch_up_after_sub_threshold_stall
```

修改前必須重現 0 ms 間隔並失敗。

### Step 1：只修正首音裁切

修改檔案：

- `src/tts/engines/edge.py`
- `tests/test_speech_timing.py`

執行順序：

1. 將 `_StreamingSilenceTrimmer` 的單一 active threshold 改為「onset candidate + confirmed activity」狀態。
2. 使用固定上限的 ring buffer 保存待判定 pre-roll。
3. confirmed activity 出現時，從最早 onset candidate 加 safety guard 的位置開始輸出。
4. 若只有真正 padding，仍只保留短 leading silence。
5. 保持 trailing trim 行為不變。
6. 保持 `feed()` 與 `finish()` 對任意 chunk boundary 的等價性。
7. 不在 `_EdgePCMEmitter`、MuseTalk 或 WebRTC 加入補零 workaround。

新增或更新測試：

- 低能量 onset 保留。
- 漸強 onset 保留。
- 完全為零的長 padding 仍被裁切。
- 很小的 codec residual 不應保留整段 padding。
- 全靜音 clip 行為維持。
- chunk size 為 1、137、160、320 與隨機固定 seed 時結果一致。
- 兩個相鄰片段各自保留首音。
- `_EdgePCMEmitter` 最終仍只輸出完整 320-sample frame，尾幀正確補零。

Step 1 gate：

```bash
.venv/bin/python -m unittest -v \
  tests.test_speech_timing.EdgeTTSSilenceTests \
  tests.test_speech_timing.EdgeTTSStreamingTests
```

紅燈測試轉綠，既有裁切與串流測試不得退化，才進入 Step 2。

### Step 2：只修正 WebRTC 音訊 pacing

修改檔案：

- `src/utils/webrtc.py`
- `tests/test_speech_timing.py`
- 必要時 `tests/test_media_fencing.py`

執行順序：

1. 將 audio late-frame policy 與 video late-frame policy 拆開，避免共用模糊的 `MAX_PACING_LAG` 分支。
2. audio frame 逾期並立即交付時，將共享 audio master wall-clock origin 推進到 `now`。
3. 保持當前 RTP PTS 不變；下一幀仍只增加 320 ticks。
4. 下一個 audio deadline 必須位於本次交付後約 20 ms，不能追趕舊 deadline。
5. video 不得 rebase shared audio clock；video 落後時只跳 PTS／過期影格。
6. 保留 `recv()` 在 pacing await 後重新檢查 generation 的 fence。
7. 不以擴大 audio queue 或瀏覽器 buffer 掩蓋排程問題。

必要測試：

- 30 ms、50 ms、90 ms、100 ms、1 s stall。
- stall 後第一幀可立即交付，後續幀回到 20 ms。
- 不出現連續兩個低於容許誤差的交付間隔。
- PTS 單調且固定增加 320。
- audio rebase 後 audio/video 仍共用相同 `_start`。
- video track 不得移動 audio master clock。
- pacing await 期間 generation 改變時，舊 frame 仍被丟棄。
- audio/video queue backpressure 上限不變。

Step 2 gate：

```bash
.venv/bin/python -m unittest -v \
  tests.test_speech_timing.WebRTCPacingTests \
  tests.test_media_fencing.WebRTCMediaFenceTests \
  tests.test_media_fencing.MuseTalkEnvelopePropagationTests
```

### Step 3：加入隱私安全的診斷指標

修改候選檔案：

- `src/utils/webrtc.py`
- `src/server/reply_streaming/metrics.py`
- `src/server/voice_session.py`
- 對應 metrics tests

只記錄結構化數值：

- `audio_pacing_lag_ms`。
- `audio_pacing_rebase_count`。
- `audio_release_interval_ms` histogram 或最小值。
- `audio_catch_up_burst_count`，定義為逾期後連續過短的 frame interval。
- `tts_onset_preroll_ms`。
- `tts_retry_after_pcm_count`。
- `tts_retry_after_playback_commit_count`，正常目標為 0。

不得記錄：

- TTS 文字。
- 使用者逐字稿。
- 原始 PCM。
- 可還原內容的音訊特徵。

高頻 frame 指標不可逐幀以 INFO 寫 log。應使用 per-turn aggregate，或低頻 warning 搭配 metrics snapshot，避免 log I/O 反過來造成 event-loop stall。

### Step 4：修正 Edge TTS 重試接續

此步驟獨立成一個 commit，不與首音或 pacing 修正混在一起。

修改候選檔案：

- `src/tts/engines/edge.py`
- `src/server/reply_streaming/pipeline.py`
- `src/server/voice_session.py`
- `tests/test_speech_timing.py`
- `tests/test_playback_commit.py`

執行順序：

1. 把 fragment 是否已 WebRTC commit 的 predicate 傳到 Edge fragment synthesis 層。
2. 移除「重新合成後直接依 `emitted_samples` 跳過」作為一般安全接續策略。
3. commit 前若允許完整重試，必須先用 fragment envelope 清除所有尚未 commit 的同片段 PCM、MuseTalk batch 與 outbound media。
4. commit 後遇到 Edge stream 中斷，停止該片段與後續內容，回報結構化 terminal reason，不重播、不跳字後繼續。
5. 共用 retry budget 與 circuit breaker 行為維持。

必要測試：

- 第一次與第二次合成音訊完全相同：commit 前可安全完整重試。
- 第二次音訊前置 padding 不同。
- 第二次音訊語速／片段長度不同。
- 部分 PCM 已進 Avatar queue、尚未 commit。
- 首個非靜音 WebRTC frame 已 commit。
- retry 同時發生 interrupt／generation advance。
- 不得重播已 commit 開頭，不得以 sample offset 切入不同音素。

如果無法建立「commit 前原子清除同片段所有下游資料」的正確測試 seam，先不要保留 partial-resume 功能；應 fail closed，並在 issue comments 記錄架構阻礙。

### Step 5：完整自動回歸

依序執行最小測試、相關模組、全套測試：

```bash
.venv/bin/python -m unittest -v \
  tests.test_speech_timing.EdgeTTSSilenceTests \
  tests.test_speech_timing.EdgeTTSStreamingTests \
  tests.test_speech_timing.WebRTCPacingTests

.venv/bin/python -m unittest -v \
  tests.test_media_fencing \
  tests.test_playback_commit \
  tests.test_reply_streaming \
  tests.test_voice_session

.venv/bin/python -m unittest discover -s tests -v

cd web
npm test
npm run build
```

最後執行：

```bash
python -m compileall src tests
git diff --check
```

如果專案慣用 `.venv/bin/python`，`compileall` 也應使用相同 interpreter。

### Step 6：實機驗證

自動測試通過後，在實際 Edge TTS＋MuseTalk＋WebRTC 裝置驗證；不得只以伺服器 unit test 宣告完成。

#### 6.1 首音語料

準備至少 20 個短片段，涵蓋：

- 低能量或摩擦音起頭。
- 送氣音起頭。
- 母音起頭。
- 數字、英文與中英混合起頭。
- 連續 3～5 個可播回覆片段，每段都重新啟動 TTS。

範例可包含「是」、「先」、「想」、「謝謝」、「現在」、「可以」、「three」、「system」，但實際驗收應依目前聲線補足最容易重現的詞。

每組分別測試：

| 輸入來源 | legacy | streaming |
|---|---:|---:|
| 文字輸入 | 必測 | 必測 |
| 語音輸入 | 必測 | 必測 |

#### 6.2 排程壓力條件

至少涵蓋：

- 正常負載。
- 人工注入 30 ms、50 ms、90 ms event-loop stall。
- GPU inference 速度接近 real time。
- video queue 接近上限。
- Edge TTS 首包抖動。
- Edge TTS 串流中斷／重試。

觀察：

- 音訊 frame release interval。
- audio pacing lag 與 rebase 次數。
- WebRTC queue 水位。
- A/V offset。
- TTS retry 是否發生在 playback commit 前或後。

#### 6.3 音訊留存邊界

若人耳無法穩定判斷首音，可在開發機明確啟用短生命週期診斷，錄製本機 outbound PCM 與瀏覽器收到的音訊做 waveform 對時。該功能必須：

- 預設關閉。
- 只用測試句，不含真實使用者內容。
- 記錄保存位置與刪除時間。
- 驗證完成後刪除音訊。
- 不併入正式 log 或版本控制。

## 驗收條件

### 自動測試

- 原始低能量 onset repro 由紅轉綠。
- 兩個連續片段各自保留低能量首音。
- 90 ms stall 後不再出現多個 0 ms audio delivery interval。
- stall 後 RTP PTS 仍以每幀 320 ticks 單調前進。
- video 不會重設 audio master clock。
- pacing await 後 generation fence 仍有效。
- Edge retry 音訊不同時不會 sample splice 到不同音素。
- 全套 Python、Web 與 production build 通過。

### 實機結果

- 指定首音語料在四種輸入／模式組合中沒有可重現的首字缺音。
- 人工 30～100 ms stall 不再聽到追幀式突然加速。
- `audio_catch_up_burst_count` 為 0。
- 不新增 stale media、重複片段或 history／字幕 commit 錯誤。
- A/V P95 仍符合 ADR-0007 的 ±80 ms 目標；若原基線尚未達標，至少不得比修正前惡化，並保留原 blocker。
- 首音延遲不得因 onset 保護出現不可解釋的明顯退化；任何增加都要以 retained preroll 指標說明。

## 建議提交拆分

為了可以獨立回退，至少拆成三個 commit：

1. `fix(tts): preserve low-energy fragment onsets`
2. `fix(webrtc): prevent audio catch-up bursts after short stalls`
3. `fix(tts): make fragment retries playback-commit aware`

metrics 若變動較大，可獨立成第四個 commit：

4. `obs(audio): record onset and pacing aggregates`

每個 commit 都必須包含對應 regression test，不接受只有 production code 的修正。

## 回退策略

- 首音與 pacing 修正不得共用同一個 feature flag；兩者是不同根因，必須能獨立回退。
- 若 onset 修正造成 Edge padding 明顯增加，只回退 trimmer patch，不回退 pacing。
- 若 pacing 修正造成 A/V offset 退化，只回退 pacing patch，保留首音修正。
- retry 修正若導致過多 fail-closed，先回退 retry commit，保留已驗證的 onset 與 pacing 修正。
- 不得以重新開放 catch-up burst、擴大 queue 或關閉 generation fence 作為緊急修補。

## 完成定義

只有同時完成以下項目，才能把本 ticket 設為 `resolved`：

- 兩個最小紅燈測試已先確認會失敗。
- 首音、pacing 與 retry 修正各自有 regression test。
- 原始 repro 已重新執行並轉綠。
- 全套自動測試與 Web build 通過。
- 實機四種輸入／模式組合完成驗證。
- 30～100 ms stall 壓力測試沒有 catch-up burst。
- 沒有新增逐字稿、回覆正文或 PCM 留存。
- 所有暫時 debug instrumentation 已移除。
- 實測數值與結論已追加到本文件 `## Comments`。

## Comments

- 2026-08-31：完成程式路徑分析。首字缺音已由低能量 onset harness 穩定重現，現行 trimmer 會刪除 40 ms；90 ms 播放 stall 已由實際 `next_timestamp()` 重現三個連續 0 ms 間隔。
- 2026-08-31：本文件完成修改設計與執行順序；尚未修改 production code。
- 2026-08-31：已完成自動測試迴圈。兩個最小紅燈測試先確認失敗（onset 960≠1600、90 ms stall 出現 0 ms 間隔），再改 production code。
- 2026-08-31：首音修正改為 onset/activity 雙門檻與最多 160 ms preroll；原始 repro 現為 `lost_onset_ms=0`。音訊逾期立即 rebase 牆鐘、不追幀；video 仍只跳幀、不移動 audio master clock。Edge 在已產生 PCM 或 playback commit 後不再以 sample offset 接續，改為 fail closed。
- 2026-08-31：回歸通過：202 Python tests、23 Web tests、Vite production build、compileall、git diff --check。未做實機四格聽感與 30–100 ms stall 人耳驗收，因此本票改為 `ready-for-human`，不得標 resolved。
- 2026-08-31：無法建立「commit 前原子清除同片段所有下游 PCM／MuseTalk／WebRTC」的正確 seam，因此未保留 partial-resume；`discard_uncommitted` 介面已預留，生產路徑未接上。`reply_streaming.enabled` 預設仍為 `false`。
