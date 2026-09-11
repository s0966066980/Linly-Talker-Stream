# 可靠回覆語音串流 v1 完成規格

Status: completed-v1

## 已交付契約

- LLM chunk 只在完整語意邊界形成可播片段，再依序進入有界 TTS／Avatar 管線。
- 所有文字、音訊、影格與 UI 事件帶有 `turn_id`、generation 或 sequence；取消後的舊輪次輸出在每個邊界被拒絕。
- 第一個非靜音音訊幀才提交片段為已播回覆；輪次提交只保存使用者實際收到的內容。
- 音訊是媒體主時鐘；視訊可有限丟幀或重複，但不得阻塞音訊或無界累積。
- `assistant_fragment_end` 只表示文字片段生成完成，不觸發字幕淡出；字幕在 `assistant_speaking_end` 或 `assistant_turn_committed` 後結束。
- MuseTalk 在語音片段邊界融合嘴部 ROI；回答結束時以目前待機影格為目標執行 12 影格 smoothstep settling，避免直接跳回待機循環。
- settling 僅使用 CPU ROI 操作，不增加 TTS、推理或音訊等待。

## 正式保證

v1 正式實機 SLO 適用於 Edge TTS＋MuseTalk、單一活躍 WebRTC 會話。正式 50 回合報告位於 `real-soak-mouth-continuity-50-rerun.json`，結果：首音 P50 1.185525 s、P95 1.691548 s、A/V 偏差 P95 0.06 s、stale output 0。

`reply_streaming.enabled` 預設為 `false`，可由設定頁或 YAML 啟用；舊有與串流模式共用播放提交、字幕、取消與 history 契約。

## v1 驗收

- Python 完整回歸、Web 完整回歸與 Vite production build 通過。
- 專用測試涵蓋語意切片、背壓、逾時、generation fence、播放提交、字幕生命週期、嘴型連續、待機對齊與 settling。
- 720×1280 settling 實測平均 1.596 ms、最大 3.966 ms。

架構決策見 [ADR 0007](../../docs/adr/0007-stream-replies-with-turn-isolation-and-audio-clock.md)、[ADR 0008](../../docs/adr/0008-use-visual-only-musetalk-mouth-continuity.md)、[ADR 0009](../../docs/adr/0009-bounded-stage-caption-window.md) 與 [ADR 0010](../../docs/adr/0010-console-rest-state-follows-turn-commit.md)。
