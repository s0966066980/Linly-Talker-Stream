---
status: accepted
---

# 使用 faster-whisper 執行語音轉文字

伺服器使用 faster-whisper 的 Whisper Base 模型執行 STT，GPU 採 FP16 並常駐，GPU 資源不足時以 CPU INT8 降級；Silero 仍是獨立且唯一具權威性的串流 VAD，不使用 faster-whisper 的檔案後處理 VAD。相較原始 openai-whisper 與 Transformers pipeline，CTranslate2 後端更符合即時輪次所需的延遲與記憶體目標，而目前 CUDA 12、cuBLAS 與 cuDNN 9 環境也符合其 GPU 執行需求。
