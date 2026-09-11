# 按需回答看板 v1 完成規格

Status: completed

## 已交付行為

- 同一個 LLM 以固定協定產生 `SIMPLE` 或 `BOARD` 回覆；模式與內容由後端驗證。
- `SIMPLE` 直接口述；`BOARD` 將 1–3 句口語摘要送入 TTS，完整項目只送往控制台與舞台看板。
- 看板項目帶有輪次與項目識別碼；只有 presenter 確認顯示的完整項目會提交為後續追問上下文。
- 已播語音與已顯示看板項目分開記錄，分別維持「已出聲」與「已呈現」的語意。
- 插話、取消、重送與重連遵守 generation fence；未顯示的舊輪次內容不會提交。
- 舞台支援看板位置、尺寸與透明度設定，且不改變字幕與語音播放契約。

## v1 驗收

- 簡答不建立看板；需要分項閱讀的回答可同時得到口語摘要與看板項目。
- 看板本文不會進入 TTS，模式標記與無效輸出不會顯示給使用者。
- 「第二點」等追問只引用已確認顯示的項目。
- 對應回歸測試保留於 `tests/test_answer_protocol.py`、`tests/test_reply_streaming.py`、`tests/test_server_routes.py` 與 `web/tests/` 的看板測試。

設計決策見 [ADR 0011](../../docs/adr/0011-separate-spoken-and-displayed-answer-commit.md)。
