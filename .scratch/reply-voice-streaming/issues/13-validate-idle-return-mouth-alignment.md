# 實機驗收 MuseTalk 待機回復嘴部對齊

Type: task
Status: ready-for-human
Blocked by: 12

## 目標

在真實 Edge TTS＋MuseTalk＋WebRTC 環境驗證新的待機回復過渡，確認消除嘴部錯位、鬼影與往返抖動，同時不犧牲音訊主時鐘、首音、A/V、插話及媒體債務 SLO。

## 前置條件

- Issue 12 的全部自動測試與效能 gate 通過。
- 幾何對齊具備獨立設定開關，且可在重啟後快速回退。
- 測試環境可取得原行為與新行為的相同 Avatar、相同設定基準。
- soak 不保存逐字稿、回答正文、原始音訊或完整影格。

## 詳細驗收流程

### Phase 1：5 輪 A/B 因果確認

1. 使用同一 Avatar 先關閉嘴型連續控制，跑 5 輪並記錄待機回復抖動基準。
2. 恢復舊嘴型控制但關閉新幾何對齊，再跑相同情境。
3. 開啟新幾何對齊及 2-pair hysteresis，再跑相同情境。
4. 情境至少包含短句、長句、多片段、低能量尾音及回答尾端快速閉嘴。
5. 比較 transition/fallback、bbox 位移、scale、video repeat/drop 與臉部 ROI frame delta。

Gate：新幾何對齊必須明顯移除舊控制器特有的 7 幀錯位；若停用 controller 後仍有相同全畫面抖動，停止 rollout，改查待機素材索引或 video queue。

### Phase 2：20 輪自動 WebRTC soak

1. 覆蓋短／長回答、弱標點、無標點、至少三個可播回覆片段、低能量尾音、插話、LLM 中斷及 WebRTC 重連。
2. 輸出原有 first-audio、A/V、interrupt、resume、media-debt、stale-output 與 catch-up-burst 指標。
3. 加入 idle-return transition 次數、fallback reason 分布、最大位移比、scale 範圍與 ROI frame-delta p95/p99。
4. 對每輪最後說話影格至穩定 idle 的有限窗口執行自動視覺 gate。

Gate：20/20 輪完成，沒有 crash、stale output、PTS 非單調或新增 audio pacing warning；視覺相對基準全部達標。

### Phase 3：人工慢速視覺檢查

1. 選取至少 10 個待機回復過渡，以正常速度與 0.25× 速度並排比較舊／新行為。
2. 檢查嘴部是否錯位、重影、突然縮放或方向往返。
3. 檢查臉部以外背景與身體是否被混合或凍結。
4. 檢查尾音期間是否提前閉嘴，以及 speech 恢復是否卡在 closing。
5. 檢查 fallback 樣本，確認它是短 neutral closing，而非扭曲 warp 或完整影格凍結。

Gate：正常速度不可察覺異常跳動；0.25× 可看見過渡但不可見嘴部脫離臉部或全畫面重影。

### Phase 4：50 輪正式 soak

1. 使用正式硬體與部署參數執行 50 輪。
2. 保留聚合報告至 `.scratch/reply-voice-streaming/`，檔名包含 `idle-return-alignment-final-50`。
3. 與 `real-soak-mouth-continuity-50-rerun.json` 比較，不得只以新一輪的絕對值自行判定。

正式 gate：

- first audio P50 ≤ 1.2 s、P95 ≤ 2.5 s。
- A/V offset P95 ≤ 80 ms。
- interrupt stop P95 ≤ 200 ms。
- listening resume P95 ≤ 500 ms。
- max media debt ≤ 2 s。
- stale output = 0。
- catch-up burst = 0。
- 臉部 ROI transition delta ≤ 正常待機 p95 × 1.5。
- ROI 外差異增加 ≤ 5%。
- 無連續方向反轉的嘴部 centroid 位移。

### Phase 5：發布與回退

1. 先只對 canary session 啟用新幾何對齊。
2. 觀察 transition fallback rate、video repeat/drop、A/V 與錯誤率。
3. 任一音訊 SLO regression、PTS 錯誤、fallback 異常升高或新視覺 artifact，立即關閉幾何對齊開關；不切換音訊 producer、不修改 buffer。
4. 穩定觀察期完成後，才討論把新對齊改為預設開啟。
5. 保留舊路徑至少一個發布週期；移除時間另開票處理。

## 建議命令

```bash
uv run python scripts/run_voice_soak.py \
  --base-url https://localhost:8010 \
  --turns 20 \
  --output .scratch/reply-voice-streaming/idle-return-alignment-20.json

uv run python scripts/run_voice_soak.py \
  --base-url https://localhost:8010 \
  --turns 50 \
  --output .scratch/reply-voice-streaming/idle-return-alignment-final-50.json
```

## 完成條件

- 5 輪 A/B、20 輪自動 soak、人工慢速檢查及 50 輪正式 soak 全部通過。
- 報告不含使用者內容或原始媒體。
- 新對齊在 canary 穩定，且回退開關已實際演練。
- 驗收結果附加到本票 Comments，狀態改為 `completed`。

## Comments

- 2026-09-11: 由待機回復抖動設計決策建立；等待 Issue 12 完成。
- 2026-09-11: RTX 4090／llama.cpp／Edge TTS／MuseTalk 實機 canary 已完成。5-turn baseline（舊 `config_musetalk.yaml`）與 5-turn alignment canary 都顯示該舊開發設定的 TTS／首批延遲，不作正式比較。正式 `config/config.yaml` 開啟 alignment 後的 20-turn 報告為 `idle-return-alignment-20.json`：interrupt-stop P95 0.000336s、listening-resume P95 0.302085s、media debt 0.24s、stale output 0，皆通過；但 first-audio P50 2.303627s／P95 3.564159s（目標 1.2s／2.5s）及 A/V P95 0.16s（目標 0.08s）未通過。瓶頸在 Edge TTS first PCM P95 2.607324s 與 MuseTalk first result P95 2.933313s，不在待機回復對齊控制器。依 Phase 5 回退規則已將 `mouth_continuity_idle_alignment` 恢復為 false；50-turn gate 等首音與 A/V 基準恢復後再執行。
