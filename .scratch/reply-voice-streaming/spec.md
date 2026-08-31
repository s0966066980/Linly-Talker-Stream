# Reliable Reply Voice Streaming

Status: implementation-complete-real-soak-slo-blocked

## Current Implementation Snapshot

截至 2026-08-31，Phase 0–5 已實作並通過完整回歸測試；Phase 6 已完成 50 輪實機 soak，但首音與 A/V SLO 未達標。

- 目前正式使用的仍是 legacy 語音路徑。
- `config/config.yaml` 的 `reply_streaming.enabled` 必須維持 `false`。
- 在 Phase 4–6 的 gate 與 50 輪實機 soak 全數通過前，不得將新管線接到正式輸出，也不得改為預設開啟。
- Phase 5 已完成；Phase 6 報告與 blocker 記錄在 `issues/06-real-soak-and-progressive-enablement.md` 與 `real-soak-report.json`。

## Objective

將既有部分串流路徑提升為可靠的「回覆語音串流」：使用者完整發話經 STT 完成後，LLM token 持續產生可播回覆片段，經有界 TTS channel 合成音訊 chunk，再由 MuseTalk 與 WebRTC 即時輸出。所有階段共同遵守輪次隔離、取消、背壓、已播回覆提交、音訊主時鐘與錯誤恢復契約。

## Scope

第一階段保證：

- Edge TTS＋MuseTalk。
- 單一活躍語音會話。
- 既有 WebRTC 上行、Silero 端點偵測與完整發話 STT 不變。
- 其他 TTS／Avatar 不得發生既有功能 regression，但不要求達成本規格的串流 SLO。

不包含：

- partial／streaming STT。
- 使用者尚未說完就啟動 LLM 或 TTS。
- 同時聽與說的全雙工預測回覆。
- 多租戶 GPU 公平排程。
- WebRTC 重連後續播舊輪次音訊。

## Current Baseline and Gaps

現有程式已具備 LLM token streaming、句尾文字切分、TTS queue、Edge 音訊 chunk 解碼及 20 ms WebRTC 音訊幀，但可靠性契約尚未跨層成立：

- `VoiceTurnSession.interrupt()` 取消 asyncio task，不能停止 executor 內仍在執行的 LLM 串流。
- 舊 LLM 串流可在 `flush_talk()` 後重新把文字加入 TTS queue。
- TTS 文字 queue、音訊輸入 queue 與部分 multiprocessing queue 無界。
- `turn_id` 已進入 TTS metadata，但下游沒有用它拒絕舊資料。
- LLM 在串流開始時直接寫入 user history，完成時直接寫入完整 assistant history；取消後 history 可能包含未播放內容。
- MuseTalk batch 結果沒有 generation fence，取消後仍可能輸出舊影格與配對音訊。
- 完整 `assistant_text` 事件晚於已開始的 TTS，字幕與實際播放的承諾點不同。

## Domain Contracts

領域用語以根目錄 `CONTEXT.md` 為準，特別是：回覆語音串流、輪次隔離、回覆背壓、可播回覆片段、首音延遲、已播回覆、輪次提交與音訊主時鐘。

### Turn context

每輪建立唯一且不可重用的 turn context，至少包含：

- `turn_id`
- monotonic `generation`
- cancellation signal and terminal reason
- per-stage sequence counters
- first/last media commit markers
- media debt and queue watermarks
- structured timing and stale-drop counters

所有文字、音訊、MuseTalk batch 與 WebRTC frame 必須攜帶可驗證的 turn envelope。任何 producer 在 enqueue 前、consumer 在 dequeue 後、輸出端在 commit 前都要檢查該輪是否仍有效。

### Turn lifecycle

正常輪次只能沿單向狀態前進：

```text
created → llm_streaming → synthesizing → speaking → draining → completed
              │                │            │
              └──────────── cancel / fail ──┴→ cancelled | failed
```

terminal state 不可回復，同一 turn 不得在 fallback 後重新播放。WebRTC 斷線視為取消：丟棄未播資料、提交已播回覆，重連建立新輪次。

## Text Segmentation

LLM token 先進入增量語意切片器，再形成可播回覆片段：

- 強句尾 `。！？；.!?;`：形成非空片段後立即送出。
- 弱停頓 `，、：, :`：累積至少 12 個中英文字元才送出。
- 無標點內容：24 字後尋找最近安全詞界限，最遲 32 字必須切出。
- LLM 正常結束：flush 剩餘非空內容。
- 不得在 UTF-8 code point、英文單字、數字序列或已知標記內切片。
- 切片器必須可增量處理 token 邊界落在標點或詞語中間的情況。

## Bounded Pipeline and Backpressure

容量以「尚未播放的估算／實際媒體時間」計算，不以句子數或 queue item 數量代表：

- 高水位：2 秒，達到後停止從上游接納新的可播回覆片段並向 LLM reader 施加背壓。
- 低水位：1 秒，降到此水位才恢復上游，避免頻繁啟停。
- 文字尚未合成時使用保守語速估算；音訊產生後以實際 sample duration 取代估算。
- 高水位連續維持 3 秒，要求 LLM 在下一個可播回覆片段邊界結束；不得切斷正在播放的片段。
- 所有中間 channel 都必須有容量或媒體債務限制；不得只限制 TTS 文字 queue 而讓音訊／影格在下游無界累積。

## Cancellation and Stale Data

取消採強隔離：

- 插話被伺服器確認後，舊輪次 producer 立即收到 cancellation signal。
- 無法取消的底層推理可以在背景收尾，但其結果必須被 generation fence 丟棄。
- 清除 TTS 待合成片段、音訊 queue、MuseTalk 待推理／已完成 batch，以及尚未 commit 的 WebRTC media。
- 已進瀏覽器 jitter buffer 的極短尾音無法撤回；P95 舊語音停止目標仍為 200 ms。
- P95 恢復可收音目標為 500 ms，並沿用尾音保護以避免回音被辨識成新發話。
- 每個 stale drop 都只記結構化計數與 stage，不記內容。

## Playback Commit, Subtitles, and History

- 可播回覆片段送出第一個非靜音 WebRTC 音訊幀時，才成為已播回覆並顯示字幕。
- 字幕至少維持到該片段最後一個音訊幀送出；輪次間的舊淡出計時不得提前清除新片段。
- 對話 UI 與 LLM history 只累積已播回覆，不使用 LLM 完整生成字串冒充使用者已收到內容。
- 使用者發話在輪次開始時形成 pending history entry；助手已播內容與 terminal reason 在輪次提交時一次完成。
- 插話、背壓截斷或斷線後，保留使用者發話與已播助手部分，排除未播放文字。

## Error Recovery

- 首個音訊幀 commit 前，全管線共用最多一次重試，所有階段合計額外等待不得超過 1 秒。
- 首個音訊幀 commit 後發生錯誤，不重播或切換聲線；保留已播內容、取消剩餘資料、回報結構化錯誤並恢復收音。
- 不跳過失敗片段後繼續後文，避免產生語意缺口。
- 不在同一輪切回 legacy，避免重複開頭。
- 5 分鐘內連續 3 輪發生管線級錯誤時開啟 circuit breaker，從下一輪暫時使用 legacy；健康探測成功後才恢復新管線。

## A/V Synchronization

音訊是媒體主時鐘：

- 每個 20 ms 音訊幀帶 turn、fragment、media sequence 與單調時間資訊。
- MuseTalk 嘴型影格必須對應相同輪次與音訊時間軸。
- MuseTalk 落後時允許丟棄過期影格或短暫重複最近有效影格，不得延後音訊等待所有影格。
- 不允許取消前的 batch 在新 generation 輸出。
- 暖機後 P95 A/V 偏差必須維持在 ±80 ms。

## SLOs

所有延遲指標以暖機後、Edge TTS＋MuseTalk、單一活躍會話量測：

| Metric | Target |
| --- | --- |
| 發話結束至首個非靜音 WebRTC 音訊幀 | P50 ≤ 1.2 s；P95 ≤ 2.5 s |
| 插話確認至舊語音停止 | P95 ≤ 200 ms |
| 插話確認至恢復可收音 | P95 ≤ 500 ms |
| A/V 偏差 | P95 within ±80 ms |
| 待播媒體時間 | 穩態低於 2 s 高水位；降至 1 s 才解除背壓 |
| stale output after cancellation | 伺服器 commit 邊界為 0；僅容許瀏覽器既有 buffer 尾音 |

## Observability and Privacy

預設只記結構化 metadata：

- 匿名 session／turn identifier
- 每階段開始、首包、完成與取消時間
- fragment／media sequence、queue media debt、高低水位停留時間
- retry、timeout、truncation、circuit-breaker 與 stale-drop reason codes
- first-audio、interrupt、listening-resume 與 A/V offset histogram

一般 log 不記逐字稿、模型回覆正文或原始音訊。內容型排障只允許在明確啟用、短生命週期且可追蹤的 debug 模式中進行；不得改變 ADR-0004 的預設資料留存邊界。

## Rollout

- 新管線由 `reply_streaming.enabled` 類型的設定旗標控制，初始預設關閉。
- legacy 與新管線共享外部 WebRTC／設定介面，避免前端維護兩套協議。
- 開發與測試期間可做相同輸入的差異量測，但不得讓 shadow 路徑產生使用者可見音訊或寫入正式 history。
- 自動測試與 50 輪真實 soak 全部達標後改為預設開啟。
- 穩定觀察期結束後才移除 legacy；不永久維護雙模式。

## Delivery Phases and Gates

任何階段只有在既有完整測試、該階段新測試與原始端到端重播全部通過後，才能開始下一階段。

### Phase 0 — Baseline and flag

- 建立 feature flag、per-turn monotonic timing、media-debt estimator 與可自動執行的原始情境重播。
- 擷取 legacy 首音、插話、queue 水位與 A/V baseline，不改變輸出行為。

Gate：完整既有測試；指標不含文字／音訊；baseline harness 可重複且能判定 SLO。

### Phase 1 — Turn context and transactional history

- 建立 turn context、terminal state、cancellation signal 與 generation fence。
- 將 OpenAI-compatible LLM history 改為 pending／commit，停止在 generator 內直接提交完整 assistant 回覆。
- 所有舊輪次 LLM token 在進入切片器前可被拒絕。

Gate：插話、task cancellation、executor 繼續運行、LLM error 與 disconnect 的 deterministic tests；history 只含已播內容。

### Phase 2 — Semantic fragments and bounded TTS channel

- 實作增量混合語意切片器與精確門檻。
- 建立以媒體時間計量的 bounded channel、高低水位與 3 秒截斷。
- LLM reader 可被 cooperative cancellation／backpressure 控制。

Gate：任意 token 邊界、標點、長無標點、Unicode、queue 飽和、hysteresis 與截斷 property/integration tests；queue 不可無界成長。

### Phase 3 — Turn-aware Edge audio streaming

- Edge TTS 接受 fragment envelope，音訊 chunk 帶 turn／fragment／media sequence。
- 共用 retry budget；首音 commit 後不得重播。
- cancellation 能停止接納或丟棄舊 Edge chunk。

Gate：首 byte 前後錯誤、部分 MP3、timeout、retry、cancel during decode、stale chunk 與 20 ms PCM 邊界 tests；既有 Edge 續傳與靜音裁切測試不退化。

### Phase 4 — MuseTalk and WebRTC media fencing

- audio feature、inference batch、result frame 與 outbound media 全部保留 envelope。
- 清除或拒絕舊 generation 的 queue item 與 batch result。
- 實作音訊主時鐘、late-video drop／repeat 與 A/V offset 指標。

Gate：取消落在 batch 前／中／後、queue 滿載、GPU 慢於 real time、WebRTC buffer stall／rebase 與 frame pairing tests；驗證 200 ms／500 ms 插話目標與 ±80 ms A/V 目標。

### Phase 5 — Playback commit, subtitles, and recovery

- 首個非靜音音訊幀觸發 fragment commit 與字幕顯示。
- 片段結束／取消／錯誤正確維持或清除字幕。
- 實作輪次提交、錯誤 reason、disconnect recovery 與 circuit breaker。

Gate：只記已播內容、字幕不領先語音、取消不殘留、三次錯誤下一輪降級、探測恢復與隱私 logging tests。

### Phase 6 — Real soak and progressive enablement

- 在實際 RTX 4090、本機 llama.cpp、Edge TTS 與 MuseTalk 上跑至少 50 輪。
- 涵蓋短／長回答、弱標點、無標點、插話、Edge 抖動、LLM 中斷、GPU 降速與 WebRTC 重連。
- 產出 SLO histogram 與 failure summary，不保存內容或音訊。

Gate：所有 SLO 達標、無 stale output、無 queue 無界增長、完整測試零 regression，才將 feature flag 改為預設開啟。

## Acceptance Criteria

- 使用者說完後，回答在 LLM 尚未完整生成前開始播放。
- 正常負載下首音、插話、恢復收音與 A/V 指標達成 SLO。
- 取消確認後，伺服器不再 commit 任何舊輪次文字、音訊或影格。
- 任一 queue 的容量都可解釋為媒體時間預算，且在壓力測試中有界。
- 字幕與 history 不包含未播放內容。
- 中途失敗不重播開頭、不跳過片段後續播、不在新連線續播舊資料。
- 其他既有 STT、TTS、Avatar、WebRTC、VAD 與設定功能測試全部通過。
