# 數字人即時流式智慧對話系統 - Linly-Talker-Stream

<div align="center">
<h1>全雙工、低延遲、即時互動數字人框架</h1>

[![madewithlove](https://img.shields.io/badge/made_with-%E2%9D%A4-red?style=for-the-badge&labelColor=orange)](https://github.com/Kedreamix/Linly-Talker-Stream)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![WebRTC](https://img.shields.io/badge/WebRTC-%E5%AE%9E%E6%97%B6%E6%B5%81%E5%BC%8F-5A29E4?style=for-the-badge)
![Vue](https://img.shields.io/badge/Vue-3-42b883?style=for-the-badge&logo=vue.js&logoColor=white)

<img src="assets/linly_logo.png" /><br>

[**English**](./README.md) | [**中文簡體**](./README_zh.md)

</div>

## 最新動態
**2026.02 更新** 📆

- 釋出 **Linly-Talker-Stream**：[Linly-Talker](https://github.com/Kedreamix/Linly-Talker) 的即時流式互動架構版本。在複用原有多模態能力的基礎上，引入 **WebRTC 即時鏈路與流式處理框架**，支援低延遲音影片互動與全雙工對話體驗。

---

<details>
<summary>目錄</summary>

<!-- TOC -->

- [最新動態](#最新動態)
- [介紹](#介紹)
- [演示與展示](#演示與展示)
- [亮點](#亮點)
- [環境要求](#環境要求)
- [快速開始（推薦）](#快速開始推薦)
- [手動安裝示例](#手動安裝示例以-wav2lip-為例)
- [啟動方式](#啟動方式)
- [配置說明](#配置說明)
- [配置預設](#配置預設)
- [模型與資料](#模型與資料)
- [後端介面](#後端介面)
- [常見問題](#常見問題)
- [參考連結](#參考連結)
- [致謝](#致謝)
- [許可協議](#許可協議)
- [Star History](#star-history)

<!-- /TOC -->

</details>

## 介紹

## 為什麼選擇 Linly-Talker-Stream？

Linly-Talker-Stream 是 [Linly-Talker](https://github.com/Kedreamix/Linly-Talker) 的**即時流式架構版本**，把傳統“輪次式”問答升級為更接近真人交流節奏的**全雙工對話系統**：

- 🎤 **邊聽邊說**：使用者講話與數字人播放可並行
- ⚡ **低延遲鏈路**：基於 WebRTC 的即時音影片傳輸
- ✋ **可插話可打斷**：支援 barge-in，提高對話自然度
- 🧩 **模組化多模態鏈路**：ASR / LLM / TTS / Avatar 可替換擴充套件

如果你希望搭建 AI 助手、數字人前臺、互動導覽或直播問答場景，這個專案可以作為高可用的即時互動工程基線。

>本專案在複用 [Linly-Talker](https://github.com/Kedreamix/Linly-Talker) 多模態鏈路（ASR / LLM / TTS / Avatar）的基礎上，參考 [LiveTalking](https://github.com/lipku/LiveTalking) 的即時通訊結構，對系統流程進行了 **流式化重構**（Streaming Pipeline Refactor），後續也會持續進行最佳化。

## 演示與展示

> [!NOTE]
>
> - Linly-Talker 演示影片：https://www.bilibili.com/video/BV1rN4y1a76x/
> - Linly-Talker-Stream 演示影片：**TODO（後續補充）**


Linly-Talker-Stream 的定位是"即時流式版本"，核心會複用並擴充套件 **Linly-Talker** 的多模態數字人能力：

- 專案地址：[Linly-Talker](https://github.com/Kedreamix/Linly-Talker)
- 如果這個專案對你有幫助，也歡迎給 **Linly-Talker** 點個 Star 以支援上游的持續更新。

**系統架構圖**

![Linly-Talker 架構](assets/HOI.png)

**Web 介面示意**

![Linly-Talker Stream](assets/linly_web.png)

## 發展路線（TODO）

- [ ] 引入 **Omni 多模態**，從固定 `ASR + LLM + TTS` 進化為更完整端到端鏈路
- [ ] 增加服務端 **VAD**，增強端點檢測、插話打斷與輪次控制穩定性


> [!IMPORTANT]
> 專案處於積極迭代階段，歡迎 PR 與 Issue。

## 亮點

- **WebRTC 即時流式播放**（瀏覽器低延遲）。
- **全雙工互動（當前可用）**：實現**邊聽邊說**（麥克風採集與數字人音影片播放同時進行）。當前全雙工主要基於**瀏覽器語音識別**（內建 VAD / 端點檢測）來完成使用者側的“說話檢測 + 文本轉換”，同時數字人端通過 WebRTC 持續播放音影片流。
- **多 Avatar 引擎可切換**（通過配置檔案）：
  - `wav2lip`（2D）
  - `musetalk`（2D）
  - `ernerf`（3D）
  - `talkinggaussian`（3D）
- **模組化架構**，依賴隔離，便於按需安裝與擴充套件

---

## 專案結構總覽

```text
Linly-Talker-Stream/
├── pyproject.toml                    # 根專案配置（核心依賴）
├── config/                           # 執行配置（YAML）
├── scripts/                          # 環境安裝 / 啟動指令碼
├── models/                           # 模型權重
├── data/                             # 數字人素材 / 錄製檔案
├── web/                              # Vue 前端
└── src/
    ├── server/                       # 後端（WebRTC + API）
    ├── asr/                          # 語音識別引擎
    ├── llm/                          # 大模型適配
    ├── tts/                          # 語音合成引擎
    └── avatars/                      # 數字人引擎（2D/3D）
```

### 即時互動管線

1. 瀏覽器採集麥克風/攝像頭輸入
2. 語音進入 ASR 與對話鏈路
3. LLM 生成響應文本
4. TTS 輸出語音流
5. Avatar 引擎進行口型驅動與影片渲染
6. WebRTC 將生成流即時回傳到瀏覽器

---

## 環境要求

- **Python**：3.10+
- **Node.js**：16+
- **uv**：推薦 Python 包管理器（[安裝檔案](https://docs.astral.sh/uv/getting-started/installation/)）
- **瀏覽器**：推薦 Chrome / Edge（遠端麥克風通常需要 HTTPS）

---

## 快速開始（推薦）

```bash
# 1) 克隆專案
git clone https://github.com/Kedreamix/Linly-Talker-Stream.git
cd Linly-Talker-Stream

# 2) 一鍵環境準備（自動安裝 uv + 建立 .venv + 安裝依賴）
bash scripts/setup-env.sh wav2lip

# 3) 配置 API Key（預設使用阿里雲百鍊的 Qwen-plus 介面）
export DASHSCOPE_API_KEY="your_api_key_here"

# 4) 一鍵啟動前後端
bash scripts/start-all.sh config/config_wav2lip.yaml
```

瀏覽器訪問：`http://localhost:3000`

> **說明**：
> - 支援的 Avatar：`wav2lip`、`musetalk`、`ernerf`、`talkinggaussian`
> - DashScope API Key 申請：[阿里雲百鍊控制台](https://bailian.console.aliyun.com)（有免費額度）
> - uv / Node.js 詳細安裝方法見 [FAQ.md](./FAQ.md)

---

## 手動安裝示例（以 Wav2Lip 為例）

```bash
# 後端依賴
uv venv --python 3.10.19
uv sync
uv pip install -e src/avatars/wav2lip/

# 前端依賴
cd web && npm install && cd ..

# 環境變數
export DASHSCOPE_API_KEY="your_api_key_here"

# 啟動
bash scripts/start-all.sh config/config_wav2lip.yaml
```

### 生成 HTTPS 證書（推薦）

遠端訪問時使用麥克風需要 HTTPS：

```bash
bash scripts/create_ssl_certs.sh
```

然後在配置檔案中設定 `app.ssl: true`，使用 `https://localhost:3000` 訪問。

### 其他 Avatar 模組安裝

```bash
# TalkingGaussian
uv pip install -e src/avatars/talkinggaussian/
uv pip install -e src/avatars/talkinggaussian/submodules/diff-gaussian-rasterization/ --no-build-isolation
uv pip install -e src/avatars/talkinggaussian/submodules/simple-knn/ --no-build-isolation
uv pip install -e src/avatars/talkinggaussian/gridencoder/ --no-build-isolation

# MuseTalk（需要額外的依賴和後處理）
uv pip install chumpy==0.70 --no-build-isolation
uv pip install -e src/avatars/musetalk/
uv run mim install mmengine
uv run mim install mmcv==2.2.0 --no-build-isolation
uv run mim install mmdet==3.1.0
uv run mim install mmpose==1.3.2
bash scripts/post_musetalk_install.sh
```

### 可選 Qwen3 語音引擎

Qwen3-ASR 與 Qwen3-TTS 都在本機執行，不需要 API Key。安裝官方推理套件後，
即可在「設定 → 語音」選擇。第一次套用會下載所選模型，並在儲存前實際預熱／試聽。

```bash
bash scripts/setup-qwen-speech.sh
```

指令碼會建立隔離的 `.venv-qwen-speech`，避免 Qwen 較新的 Transformers 相依覆蓋
數字人環境。建議先使用 0.6B 模型；強烈建議使用 CUDA，CPU 雖可執行但速度會明顯較慢。

如果安裝指令碼提示缺少 SoX，請另行安裝系統的 `sox` 套件，以支援 Base 聲音克隆的參考音訊處理。

## 啟動方式

### A. 分別啟動前後端

```bash
# 後端
bash scripts/start-backend.sh config/config_wav2lip.yaml
# 或
uv run python src/server/app.py --config config/config_wav2lip.yaml

# 前端
bash scripts/start-frontend.sh config/config_wav2lip.yaml
```

### B. 一條命令啟動

```bash
bash scripts/start-all.sh config/config_wav2lip.yaml
```

預設埠：
- 後端：`http://localhost:8010`
- 前端：`http://localhost:3000`

---

## 配置說明

所有配置集中在 `config/*.yaml`，常用項：

- `app.listenport`：後端埠（預設 `8010`）
- `app.ssl`：是否啟用 HTTPS（遠端錄音建議開啟）
- `model.type`：Avatar 型別（`wav2lip` / `musetalk` / `ernerf` / `talkinggaussian`）
- `tts.type`：免額外金鑰的 TTS 引擎（`edgetts`、`gpt-sovits`、`cosyvoice`、`fishtts`、`indextts2` 或 `xtts`）
- `asr.mode`：`browser`（推薦）/ `server` / `auto`
- `llm.*`：大模型配置（預設為阿里百鍊的 Qwen-plus 介面）

預設配置會讀取環境變數：

```bash
export DASHSCOPE_API_KEY="YOUR_KEY_HERE"
```

> ⚠️ **重要提醒**：使用大模型功能需要先去 [阿里雲百鍊](https://bailian.console.aliyun.com) 申請 API 金鑰，有免費使用額度。

## 配置預設

倉庫內已提供了一些可直接執行的配置預設，採用模組化安裝方式：

| 狀態 | 配置檔案 | Avatar 型別 | 2D/3D | 一鍵安裝命令 |
|------|---------|-----------|------|------------|
| ✅ | `config/config_wav2lip.yaml` | wav2lip | 2D | `bash scripts/setup-env.sh wav2lip` |
| ✅ | `config/config_musetalk.yaml` | musetalk | 2D | `bash scripts/setup-env.sh musetalk` |
| ✅ | `config/config_talkinggaussian.yaml` | talkinggaussian | 3D | `bash scripts/setup-env.sh talkinggaussian` |
| ⬜ | `config/config_ernerf.yaml` | ernerf | 3D | `bash scripts/setup-env.sh ernerf` |

切換引擎推薦流程：

1. 安裝對應 Avatar 模組
2. 使用匹配的 config/config_*.yaml 啟動
3. 檢查配置中的模型路徑與素材路徑是否可用

## 模型與資料

### 快速下載

| Avatar | 型別 | 下載方式 |
|--------|------|---------|
| **Wav2Lip** | 2D | [夸克網盤](https://pan.quark.cn/s/83a750323ef0) 下載 `wav2lip256.pth` + `wav2lip256_avatar1.tar.gz`（來自 [LiveTalking](https://github.com/lipku/LiveTalking)） |
| **MuseTalk** | 2D | `bash scripts/download_musetalk_weights.sh` |
| **TalkingGaussian** | 3D | 🔗 待補充 |
| **ER-NeRF** | 3D | 🔗 待補充 |

**放置說明：**

```bash
# Wav2Lip
# 1. wav2lip256.pth 重新命名為 wav2lip.pth，放到 models/
# 2. 解壓 wav2lip256_avatar1.tar.gz 到 data/avatars/

# MuseTalk（自動下載到正確位置）
bash scripts/download_musetalk_weights.sh

# TalkingGaussian
# 解壓 talkinggaussian_obama.tar.gz 到 data/avatars/
```

> 💡 **進階內容**：自定義數字人素材、目錄結構詳解、配置路徑設定等見 [FAQ.md](./FAQ.md)

---

## 後端介面

主要介面（見 `src/server/server.py`）：

- `POST /offer`：WebRTC SDP 握手
- `POST /human`：文字對話（`type=chat` 呼叫 LLM，`type=echo` 文本播報）
- `POST /asr`：上傳音訊 → ASR → LLM → 驅動數字人說話
- `POST /humanaudio`：上傳音訊檔案驅動數字人說話
- `POST /record`：開始/結束錄製
- `GET /download/{filename}`：下載錄製檔案
- `GET /health`：連線檢查

## 常見問題

詳見 [FAQ.md](./FAQ.md) 檔案。

---

## 參考連結

- WebRTC 後端：[aiortc](https://github.com/aiortc/aiortc) + [aiohttp](https://github.com/aio-libs/aiohttp)
- 前端：[Vue 3](https://vuejs.org/) + [Vite](https://vitejs.dev/)
- 語音相關：[Whisper](https://github.com/openai/whisper)、[FunASR](https://github.com/alibaba-damo-academy/FunASR)、[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)、[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)、[edge-tts](https://github.com/rany2/edge-tts)
- 數字人驅動：[Wav2Lip](https://github.com/Rudrabha/Wav2Lip)、[MuseTalk](https://github.com/TMElyralab/MuseTalk)、[ER-NeRF](https://github.com/Fictionarry/ER-NeRF)、[TalkingGaussian](https://github.com/Fictionarry/TalkingGaussian)
- 數字人互動：[Linly-Talker](https://github.com/Kedreamix/Linly-Talker)、[LiveTalking](https://github.com/lipku/LiveTalking)、[OpenAvatarChat](https://github.com/HumanAIGC-Engineering/OpenAvatarChat)

其他可以參考 [Linly-Talker](https://github.com/Kedreamix/Linly-Talker) 專案和 [LiveTalking](https://github.com/lipku/LiveTalking) 中的介紹。

## 致謝

- [LiveTalking](https://github.com/lipku/LiveTalking)：在即時數字人/WebRTC 流式鏈路方面提供了很好的參考，本倉庫在此基礎上做了結構重構與功能擴充套件。
- [Linly-Talker](https://github.com/Kedreamix/Linly-Talker)：上游多模態數字人系統，本倉庫將其能力整合到即時流式版本中。

## 許可協議

本倉庫採用 **Apache License 2.0**（與 LiveTalking 保持一致）。

> [!CAUTION]
> 請在使用和部署時遵守所在地法律法規（版權、隱私、資料保護等）。

詳情見 `LICENSE` 與 `NOTICE`。

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Kedreamix/Linly-Talker-Stream&type=date&legend=top-left)](https://www.star-history.com/#Kedreamix/Linly-Talker-Stream&type=date&legend=top-left)
