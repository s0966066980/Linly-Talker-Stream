---
status: accepted
---

# 控制台靜態紀錄以輪次提交的已播回覆為準

回覆語音串流期間，控制台可以顯示回覆預覽；輪次一結束，該則訊息必須改為這一輪的已播回覆。伺服器在每次輪次提交送出 `turn_committed`（`turn_id`、`played_text`、`reason`），控制台以此為靜態紀錄的唯一依據。沒有已播回覆時刪除該則預覽。成功不是 cancelled。

## Considered Options

- 控制台只顯示 `assistant_fragment`：拒絕，會失去生成中的即時文字。
- 用 `assistant_response_done` 剪掉預覽：拒絕，那只代表模型寫完，後面的可播回覆片段可能還在合成。
- 前端從 fragment 自行組已播回覆：拒絕，開了預覽後 fragment 被忽略，已播回覆的所有權也不在前端。
- 失敗沿用 `turn_cancelled`、成功另開事件：拒絕，被背壓截斷的成功輪次同樣需要對齊。

## Consequences

- `turn_cancelled` 仍可供舞台清空字幕；控制台文字不靠它對齊。
- 對話歷史與控制台靜態紀錄都只含已播回覆，未出聲的模型文字不得留下。
- 此決策不改變 Edge 片段串行合成，也不把本機 TTS 設為預設。
