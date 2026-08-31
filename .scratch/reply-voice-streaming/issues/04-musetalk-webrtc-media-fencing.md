# Phase 4: MuseTalk and WebRTC media fencing

Type: task
Status: resolved
Completed: 2026-08-31

## Objective

將 Phase 0–3 已建立的 turn envelope 與 generation fence 延伸到 MuseTalk 和 WebRTC 完整媒體路徑，並以音訊為主時鐘。

## Work

- audio feature、inference batch、result frame 與 outbound media 全部保留 turn、generation、fragment 與 media sequence。
- producer enqueue 前、consumer dequeue 後、WebRTC commit 前都驗證 generation。
- 取消時清除或拒絕舊 queue item 與已完成的 GPU batch result。
- 實作 audio master clock；視訊落後時可 drop late frame 或 repeat 最近有效 frame，不得阻塞音訊。
- 只記錄結構化 A/V offset 與 stale-drop metadata。

## Gate

- deterministic tests 覆蓋取消發生在 batch 前、中、後。
- queue 滿載、GPU 慢於 real time、WebRTC buffer stall/rebase 與 frame pairing tests 通過。
- 驗證舊語音停止 P95 不超過 200 ms、恢復收音 P95 不超過 500 ms、A/V P95 在 ±80 ms。
- 完整 Python、Web、build 與 baseline replay 全數通過。

## Comments

- 2026-08-28: 使用者要求先維持目前可用版本，本任務延後執行。
- 2026-08-31: 完成 MuseTalk feature/batch/result 與 WebRTC enqueue/commit generation fence、2 秒音訊入口容量、全階段取消清理、音訊主時鐘、late-video drop/repeat 與結構化 stale/A-V metrics。Gate 通過：162 Python tests、20 Web tests、production build、deterministic baseline SLO；`reply_streaming.enabled` 仍為 `false`。
