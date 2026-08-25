---
status: accepted
---

# 只支援不需外部憑證的語音引擎

產品完整移除需要第三方 API key、token 或雲端訂閱憑證的 TTS 引擎，包括 DashScope CosyVoice API、Doubao、Tencent 與 Azure TTS；同步刪除其工廠註冊、實作、設定、環境變數、專屬依賴與 UI 文案。STT 保留本機 faster-whisper 與 FunASR；其餘 TTS 僅在不需外部憑證的前提下列入支援目錄，藉此縮小部署與秘密管理範圍。
