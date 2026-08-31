# Phase 5: Playback commit, subtitles, and recovery

Type: task
Status: resolved
Blocked by: 04
Scheduling: deferred by user on 2026-08-28

## Objective

以實際送出的非靜音 WebRTC audio frame 作為字幕、已播回覆與 history 的唯一 commit 邊界，並完成錯誤恢復與 circuit breaker。

## Work

- 首個非靜音 frame 觸發 fragment commit 與字幕顯示。
- 字幕至少維持到片段最後一個 audio frame，舊淡出 timer 不得清除新片段。
- 輪次結束時只提交 user 與已播 assistant 文字，排除未播放內容。
- 處理 interrupt、disconnect、背壓截斷與首幀 commit 前後的錯誤 reason。
- 5 分鐘內連續 3 輪管線錯誤時，從下一輪改用 legacy；健康探測成功後才恢復。

## Gate

- 字幕不領先語音，history 只含已播內容。
- 取消、斷線與錯誤後沒有舊字幕、舊音訊或舊 history 殘留。
- 三次錯誤後的下一輪才降級，同輪不 fallback；健康探測可恢復。
- 隱私 logging 測試確認無逐字稿、回覆正文與原始音訊。
- 完整 regression gate 通過。

## Comments

- 2026-08-28: 使用者要求先維持目前可用版本，本任務延後執行。
- 2026-08-31: 已完成。非靜音 WebRTC audio frame 現為字幕與已播回覆的唯一 commit boundary；fragment end 由最後一幀標記，前端以 turn/revision 防止舊 timer 清除新字幕，取消與斷線立即清除舞台字幕。
- 2026-08-31: OpenAI-compatible history 改由 voice session 在 completed／interrupt／disconnect／pipeline error 時依 turn id 一次提交，assistant 僅包含已播放片段。片段間靜音不會提前完成，缺少輸出達 1 秒會以首幀前／後結構化 reason fail closed。
- 2026-08-31: 已加入 5 分鐘三次錯誤熔斷、下一輪 legacy、成功 health probe 恢復與成功輪次重設連續錯誤；一般 log 不帶逐字稿、回覆正文或 media event text。
- 2026-08-31: Gate 通過：175 Python tests、21 Web tests、Vite production build、compileall、git diff check、deterministic legacy baseline SLO。`reply_streaming.enabled` 維持 `false`，待 Phase 6 真實 soak。
