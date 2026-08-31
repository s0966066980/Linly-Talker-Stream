---
status: accepted
---

# 以輪次隔離與音訊主時鐘串流數位人回覆

數位人回覆採伺服器擁有的可靠串流管線：LLM token 經語意切片進入有界 TTS channel，音訊 chunk 再驅動 MuseTalk 與 WebRTC；每個跨層資料都以 `turn_id`、generation 與 sequence 執行輪次隔離。取消後只提交已播回覆，未播放的文字、音訊與影格一律丟棄；媒體以音訊為主時鐘，嘴型落後時允許丟幀或重複，不得以排隊延遲語音。

## Considered Options

- 保留目前僅清空佇列的盡力取消：拒絕，因 executor 內的舊 LLM 串流可以在清空後重新產生舊輪次資料。
- 以視訊為主時鐘或保留全部嘴型影格：拒絕，因 MuseTalk 推理抖動會累積為語音延遲並破壞插話目標。
- 在使用者尚未說完時提前回覆：不在本決策範圍；系統仍於完整使用者發話完成後才開始模型回覆。

## Consequences

- LLM history 必須延後到輪次結束，並只提交實際播放的助手內容。
- TTS、MuseTalk 與 WebRTC 邊界必須接受並驗證同一份輪次 envelope，不能把 `turn_id` 當成純 metadata。
- 第一階段只保證 Edge TTS＋MuseTalk 的單一活躍會話；其他引擎維持相容但不承諾相同串流 SLO。
- 新管線以功能旗標漸進啟用，達成自動回歸與真實 soak 門檻後才成為預設。
