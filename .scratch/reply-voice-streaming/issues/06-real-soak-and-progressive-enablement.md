# Phase 6: Real soak and progressive enablement

Type: task
Status: ready-for-human
Blocked by: 05
Scheduling: deferred by user on 2026-08-28

## Objective

在實際 RTX 4090、本機 llama.cpp、Edge TTS 與 MuseTalk 環境完成 50 輪 soak 與 SLO 審核，通過後才漸進啟用新管線。

## Work

- 至少 50 輪實際互動，覆蓋短／長回答、弱標點、無標點、插話、Edge 抖動、LLM 中斷、GPU 降速與 WebRTC 重連。
- 產出 first-audio、interrupt-stop、listening-resume、A/V offset、media debt 與 stale-drop histogram。
- 產出 failure summary，不儲存逐字稿、回覆正文或原始音訊。
- 先小範圍設為 `reply_streaming.enabled: true`；觀察穩定後才評估預設開啟。

## Gate

- 首音 P50 ≤ 1.2 s、P95 ≤ 2.5 s。
- 插話停止 P95 ≤ 200 ms，恢復收音 P95 ≤ 500 ms。
- A/V P95 在 ±80 ms，沒有 stale output，沒有 queue 無界增長。
- 完整測試零 regression，circuit breaker 與 legacy rollback 可用。
- 上述項目全部通過後，才允許討論將旗標改為預設開啟。

## Comments

- 2026-08-28: 使用者要求先維持目前可用版本，本任務延後執行。
- 2026-08-31: 以 process-scoped `LINLY_REPLY_STREAMING_ENABLED=1` 啟動 RTX 4090／llama.cpp／Edge TTS／MuseTalk 實機 canary；checked-in YAML 仍維持 `false`。
- 2026-08-31: 5-turn preflight 暴露並修正三個問題：soak broker 丟棄未匹配事件、WebRTC 幀在 pacing await 後缺少第二次 generation fence、中斷 metrics 在停止輸出與恢復收音前過早提交。逐幀媒體日誌亦縮減為 fragment boundary。
- 2026-08-31: 修正後的單回合播放中斷 canary：interrupt-stop 2.2 ms、listening-resume 302 ms、A/V P95 40 ms、media debt 240 ms、stale output 0；首音 2.59 s，單樣本略高於 2.5 s P95 目標，需由完整樣本判定。
- 2026-08-31: 完整回歸通過：184 Python tests、21 Web tests、Vite production build。50-turn soak 尚未執行，因此本任務與預設旗標維持未完成／關閉。
- 2026-08-31: 第二次完整 50-turn 實機 soak 已完成並保存至 `real-soak-report.json`。50/50 回合、所有情境、中斷停止／恢復、media debt、stale output 均通過；首音 P50 1.991518s（目標 1.2s）、P95 3.928302s（目標 2.5s），A/V P95 0.095s（目標 0.08s），故整體 `slo_pass=false`。
- 2026-08-31: blocker 為 Edge TTS 外部 websocket 首音／retry 延遲及媒體節拍殘餘偏移；未以放寬門檻或改寫指標掩蓋。`reply_streaming.enabled` 仍維持預設 `false`，等待人工作業決定是否改用低延遲 TTS、調整產品 SLO，或繼續媒體時鐘優化。
- 2026-08-31: 設定面板新增可持久化的「舊有／串流」回覆模式選擇，於下一回合生效；預設仍為舊有模式，環境變數 canary override 行為保留。另在共用 TTS 入口統一移除 Markdown 標記與 emoji，避免朗讀「星號星號」等格式符號。回歸更新為 187 Python tests、22 Web tests 與 Vite production build 全數通過；上述實機 SLO blocker 不變。
