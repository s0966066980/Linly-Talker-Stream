# 專案狀態

更新日期：2026-09-01

Linly-Talker-Stream 的核心單機即時數字人對話流程已完成並可用：WebRTC 上行、服務端 VAD、STT、LLM、TTS、Avatar、影音回傳、免按對話、插話與執行期設定已串成同一個伺服器擁有的對話輪次。可靠回覆語音串流已完成主力組合的實作與實機驗證，但仍以功能旗標保留舊有模式作為跨引擎回退。

## 完成度矩陣

| 領域 | 狀態 | 已完成 | 尚未完成或限制 |
| --- | --- | --- | --- |
| WebRTC 與互動 | 可用 | 雙向音訊、Avatar 影像、事件通道、免按對話、按住說話、插話、斷線清理 | 公網部署的驗證、rate limit 與多使用者隔離 |
| 使用者語音 | 可用 | Silero 服務端端點偵測、Whisper／FunASR、繁體轉換、STT 預熱與設定 | partial STT、使用者尚未說完即預測回覆不在目前範圍 |
| LLM | 可用 | Ollama／llama.cpp、串流 token、Prompt、柔性回覆字數、交易式 history | llama.cpp 與 Avatar 同 GPU 時仍需自行規劃 VRAM；無多模型排程 |
| llama.cpp 生命週期 | 完成 | 按需啟動；正常退出、Ctrl-C、SIGTERM 與 aiohttp shutdown 自動停止 owned process | SIGKILL、斷電無法執行清理；外部服務刻意不終止 |
| 回覆語音串流 | 主力組合完成 | 語意切片、有界背壓、generation fence、取消、播放提交、字幕、history、錯誤恢復與指標 | 預設關閉；正式 SLO 僅保證 Edge TTS＋MuseTalk、單一會話 |
| 音訊品質與 A/V | 主力組合完成 | 單一 renderer-owned audio producer、40 ms speech runway、bounded media queue、無 catch-up burst | direct PCM／decoupled audio clock 為關閉的實驗功能 |
| MuseTalk 嘴型 | 完成 | Lanczos／銳化、遮罩品質參數、段落邊界嘴部 ROI 連續控制、generation reset | 人工外觀仍受角色素材、臉框與遮罩品質影響 |
| 其他 Avatar／TTS | 相容 | Wav2Lip、Ultralight、ER-NeRF、TalkingGaussian 與多種 TTS adapter 保留 | 尚未逐一取得與 Edge＋MuseTalk 相同的 streaming SLO |
| 設定與前端 | 可用 | LLM、Avatar、VAD、STT、TTS、Prompt、回覆字數、回覆模式、角色預覽／匯入 | 設定面板拆分與通用 EngineRegistry 尚未完成 |
| 測試與觀測 | 可用 | 單元／整合測試、Web 測試、stage metrics、content-free 50-turn soak | 完整 UI E2E、長期 soak、資源儀表板與 session leak gate 尚未完成 |
| 部署 | 開發／本機 | HTTPS、自動安裝與整合啟動腳本、health endpoint | Docker Compose、受信任 TLS、反向代理、監控與備援 |

## 已驗證的正式基準

環境：NVIDIA RTX 4090、本機 llama.cpp、Edge TTS、MuseTalk、WebRTC、單一活躍會話。

正式報告：`.scratch/reply-voice-streaming/real-soak-mouth-continuity-50-rerun.json`

| 指標 | 結果 | Gate |
| --- | ---: | ---: |
| 回合數 | 50 | 至少 50 |
| 首音 P50 | 1.185525 s | ≤ 1.2 s |
| 首音 P95 | 1.691548 s | ≤ 2.5 s |
| A/V 偏差 P95 | 0.06 s | ≤ 0.08 s |
| 插話停止 P95 | 0.000345 s | ≤ 0.2 s |
| 恢復收音 P95 | 0.301517 s | ≤ 0.5 s |
| 最大媒體債務 | 0.24 s | ≤ 2 s |
| stale output | 0 | 必須為 0 |

情境包含短句、長句、弱標點、無標點、播放中插話與 LLM 階段中斷。報告只保留彙總遙測，不保存使用者音訊或對話內容。

## 自動驗證快照

在 commit `2c32597` 上：

- Python：234 tests passed。
- Web：23 tests passed。
- Vite production build：passed。
- Python compileall：passed。
- `git diff --check`：passed。
- owned llama-server SIGTERM 實機清理：passed，backend 關閉後 llama PID 於 1 秒內消失。

## 正式執行設定

- `reply_streaming.enabled` 預設 `false`，由設定頁或 YAML 明確選擇串流模式。
- `reply_streaming.decoupled_audio_clock` 預設 `false`，避免未驗證的 direct PCM fan-out 形成第二個音訊 producer。
- `model.musetalk.mouth_continuity` 預設 `true`；可單獨關閉並回退原始嘴型切換行為。
- 音訊是媒體主時鐘；視訊不得讓音訊等待，也不得以 catch-up burst 追趕。

## 下一階段

1. 完成 Phase 10 尚未交付的資源工作：Edge persistent worker、bounded prefetch、idle cache、hot log 降頻與 session lifecycle leak 測試。
2. 對更多 TTS／Avatar 組合執行相同 50 回合 SLO，而不是沿用主力組合結論。
3. 建立前端延遲與資源儀表板，呈現 VAD、STT、LLM、TTS、Avatar 與 WebRTC 各階段時間。
4. 補齊 Docker Compose、反向代理、受信任 TLS、驗證、rate limit 與多使用者 GPU 排程。
5. 完成跨瀏覽器人工聽感與嘴型長期驗收後，再評估將串流模式改為預設。
