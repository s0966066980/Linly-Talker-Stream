---
status: accepted
---

# MuseTalk 段落邊界使用純視覺嘴型連續控制

回覆語音串流的相鄰可播回覆片段之間可能出現短暫 PCM 空檔。MuseTalk idle batch 會回到原始 Avatar 影格，下一片段又切回模型生成嘴型；兩者即使使用相同底圖索引，嘴部色彩、輪廓與開口基準仍可能不同，造成單幀閃跳。

在 Avatar renderer 已選出目標影格、且配對音訊已 enqueue 後，加入純 CPU 的嘴型連續控制 seam。控制器只使用既有 MuseTalk mask 的嘴部 ROI，以固定影格數保留短空檔並完成開／閉嘴過渡；generation 變更或 `flush_talk()` 必須清除狀態。

## Considered Options

- 等完整回答或一次生成整段影片：拒絕，會失去回覆語音串流的首音優勢。
- 增加 audio buffer 或放慢音訊等待嘴型：拒絕，違反 ADR-0007 的音訊主時鐘。
- 啟用既有 wall-clock 全畫面 transition：拒絕，會受 queue 延遲影響，且把身體與背景一起混合。
- idle 時持續執行 MuseTalk silence inference：第一階段拒絕，會增加長時間 idle GPU 成本。

## Consequences

- 過渡以媒體影格數推進，不依賴 wall clock。
- 只有嘴部遮罩內像素被時間混合；遮罩外直接使用當前目標影格。
- 視覺控制器不得存取音訊 queue、等待 coroutine 或啟動推理。
- 任何控制器錯誤都回退原影格，不得阻止音訊或影像輸出。
- `model.musetalk.mouth_continuity` 可單獨停用並恢復原行為。
- 此決策改善段落邊界，不取代角色素材、臉框與遮罩品質調校。
