# 常見問題 (FAQ)

## 目錄

- [環境安裝](#環境安裝)
- [啟動相關](#啟動相關)
- [麥克風與音訊](#麥克風與音訊)
- [全雙工與互動](#全雙工與互動)
- [其他問題](#其他問題)

---

## 環境安裝

### Q：如何安裝 uv？

**A：** uv 是一個超快的 Python 包管理工具，推薦使用以下方式安裝：

**官方獨立安裝程式（推薦）**

```bash
# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**PyPI 安裝**

```bash
# 使用 pip
pip install uv

# 使用 pipx（推薦）
pipx install uv
```

**驗證安裝**

```bash
uv --version  # 應顯示版本號，如 0.1.0
```

更多資訊：[uv 官方檔案](https://docs.astral.sh/uv/getting-started/installation/)

### Q：如何安裝 Node.js？

**A：** Node.js 用於執行前端應用，推薦安裝 16+ 版本：

**官方安裝包下載**

訪問 [nodejs.org](https://nodejs.org/) 下載對應平臺的安裝包：
- **LTS（長期支援版）**：推薦用於生產環境，更穩定
- **Current（最新版）**：包含最新特性

**包管理器安裝**

```bash
# macOS（使用 Homebrew）
brew install node

# Windows（使用 Chocolatey）
choco install nodejs

# Ubuntu / Debian
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt-get install -y nodejs

# CentOS / RHEL / Fedora
curl -fsSL https://rpm.nodesource.com/setup_lts.x | sudo bash -
sudo yum install -y nodejs
```

**驗證安裝**

```bash
node --version  # 應顯示 v16.0.0 或更高版本
npm --version   # npm 會隨 Node.js 一起安裝
```

### Q：如何生成 HTTPS 證書？

**A：** 遠端訪問時使用麥克風需要 HTTPS，可以使用以下命令生成自簽名證書：

```bash
bash scripts/create_ssl_certs.sh
```

該指令碼會在專案根目錄生成 `cert.pem` 和 `key.pem` 檔案。

**使用 HTTPS 啟動：**

1. 在配置檔案中設定 `app.ssl: true`
2. 啟動後使用 `https://localhost:3000` 訪問
3. 瀏覽器會提示證書不受信任，點選"高階"→"繼續訪問"即可

**注意**：自簽名證書僅用於開發測試，生產環境請使用正規 CA 簽發的證書。

### Q：如何啟用虛擬環境？

**A：** 使用 uv 建立虛擬環境後，可以選擇啟用或使用 `uv run`：

**方式一：啟用虛擬環境**

```bash
# Linux / macOS
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\Activate.ps1

# Windows (CMD)
.venv\Scripts\activate.bat
```

啟用後，命令列提示符前會顯示 `(.venv)`，此時可以直接執行 `python`、`pip` 等命令。

**方式二：使用 uv run（推薦）**

```bash
# 無需啟用，直接在虛擬環境中執行命令
uv run python src/server/app.py --config config/config_wav2lip.yaml
uv run pip list
```

**退出虛擬環境**

```bash
deactivate
```

### Q：不同 Avatar 模組的依賴有什麼區別？

**A：** 不同的數字人引擎需要不同的依賴：

**Wav2Lip（最簡單）**
```bash
uv pip install -e src/avatars/wav2lip/
```

**TalkingGaussian（需要編譯擴充套件）**
```bash
uv pip install -e src/avatars/talkinggaussian/
uv pip install -e src/avatars/talkinggaussian/submodules/diff-gaussian-rasterization/ --no-build-isolation
uv pip install -e src/avatars/talkinggaussian/submodules/simple-knn/ --no-build-isolation
uv pip install -e src/avatars/talkinggaussian/gridencoder/ --no-build-isolation
```

**MuseTalk（最複雜，需要 mmcv 等）**
```bash
uv pip install chumpy==0.70 --no-build-isolation
uv pip install -e src/avatars/musetalk/
uv run mim install mmengine
uv run mim install mmcv==2.2.0 --no-build-isolation
uv run mim install mmdet==3.1.0
uv run mim install mmpose==1.3.2
bash scripts/post_musetalk_install.sh
```

**推薦**：使用一鍵安裝指令碼 `bash scripts/setup-env.sh [avatar_name]` 自動處理所有依賴。

---

## 模型與資料

### Q：專案的目錄結構是怎樣的？

**A：** 專案使用以下目錄組織模型和資料檔案：

```
Linly-Talker-Stream/
├── models/                              # 模型權重目錄
│   ├── wav2lip.pth                      # Wav2Lip 模型檔案
│   ├── musetalk/                        # MuseTalk 模型目錄
│   │   ├── musetalkV15/                 #    MuseTalk v1.5 模型
│   │   ├── dwpose/                      #    DWPose 姿態檢測模型
│   │   ├── s3fd-619a316812/             #    人臉檢測模型
│   │   └── whisper/                     #    Whisper ASR 模型
│   ├── face-parse-bisent/               # 人臉解析模型
│   └── sd-vae/                          # Stable Diffusion VAE 模型
│
├── data/
│   ├── avatars/                         # 數字人資源目錄
│   │   ├── wav2lip_avatar1/             # Wav2Lip 數字人素材（2D）
│   │   │   ├── coords.pkl               #    面部座標資料
│   │   │   ├── face_imgs/               #    面部影像序列
│   │   │   └── full_imgs/               #    完整影像序列
│   │   │
│   │   ├── musetalk_avatar1/            # MuseTalk 數字人素材（2D）
│   │   │   ├── coords.pkl               #    面部座標資料
│   │   │   ├── mask_coords.pkl          #    掩碼座標資料
│   │   │   ├── latents.pt               #    潛在特徵向量
│   │   │   ├── avator_info.json         #    數字人配置資訊
│   │   │   ├── full_imgs/               #    完整影像序列
│   │   │   └── mask/                    #    掩碼影像序列
│   │   │
│   │   ├── talkinggaussian_obama/       # TalkingGaussian 3D 模型
│   │   │   ├── source/                  #    源資料（訓練用）
│   │   │   │   ├── au.csv               #    動作單後設資料
│   │   │   │   ├── points3d.ply         #    3D 點雲
│   │   │   │   ├── torso_imgs/          #    軀幹影像序列
│   │   │   │   ├── transforms_train.json
│   │   │   │   └── transforms_val.json
│   │   │   └── model/                   #    訓練好的高斯模型
│   │   │       ├── cameras.json
│   │   │       ├── cfg_args
│   │   │       ├── chkpnt_fuse_latest.pth
│   │   │       └── input.ply
│   │   │
│   │   └── ernerf_obama/                # ER-NeRF 3D 模型
│   │       ├── au.csv
│   │       ├── data_kf.json
│   │       └── ngp_kf.pth
│   │
│   └── records/                         # 錄製檔案輸出目錄
```

### Q：如何自定義 2D 數字人素材（Wav2Lip / MuseTalk）？

**A：** 可以使用專案提供的指令碼從影片生成數字人素材：

**Wav2Lip 生成素材：**

```bash
uv run python src/avatars/wav2lip/genavatar.py \
    --avatar_id wav2lip_avatar1 \
    --img_size 256 \
    --video_path xxx.mp4
```

**MuseTalk 生成素材：**

```bash
uv run python src/avatars/musetalk/genavatar_musetalk.py \
    --avatar_id musetalk_avatar1 \
    --file xxx.mp4
```

> ⚠️ **注意**：輸入影片需要使用閉嘴不說話的影片

> 💡 **提示**：詳細教程可參考 [LiveTalking 檔案](https://livetalking-doc.readthedocs.io/zh-cn/latest/usage.html)

### Q：如何訓練 3D 數字人模型（TalkingGaussian / ER-NeRF）？

**A：** 3D 數字人需要預先訓練好的模型資料，檔案結構如下：

**TalkingGaussian 檔案結構：**

```
data/avatars/talkinggaussian_obama/
├── source/                        # 源資料目錄
│   ├── au.csv                     # 動作單元（Action Units）資料
│   ├── points3d.ply               # 3D 點雲
│   ├── torso_imgs/                # 軀幹影像
│   ├── transforms_train.json      # 訓練集變換矩陣
│   └── transforms_val.json        # 驗證集變換矩陣
└── model/                         # 訓練好的高斯模型
    ├── cameras.json               # 相機引數
    ├── cfg_args                   # 配置引數
    ├── chkpnt_fuse_latest.pth     # 模型權重
    └── input.ply                  # 輸入點雲
```

**ER-NeRF 檔案結構：**

```
data/avatars/ernerf_obama/
├── au.csv                     # 動作單元（Action Units）資料
├── data_kf.json               # 關鍵幀資料配置
└── ngp_kf.pth                 # NeRF 模型權重檔案
```

**訓練教程：**
- **TalkingGaussian**：https://github.com/Fictionarry/TalkingGaussian
- **ER-NeRF**：https://github.com/Fictionarry/ER-NeRF

> **注意**：3D 數字人的訓練流程較複雜，建議先使用預訓練模型測試。

### Q：如何在配置檔案中設定模型路徑？

**A：** 所有路徑配置集中在 `config/*.yaml` 檔案中，根據你的 Avatar 型別調整：

**Wav2Lip 示例：**

```yaml
model:
  type: wav2lip
  avatar_id: wav2lip_avatar1  # 對應 data/avatars/wav2lip_avatar1/
  model_path: ./models         # 模型目錄
```

**TalkingGaussian 示例：**

```yaml
model:
  type: talkinggaussian
  avatar_id: talkinggaussian_obama
  talkinggaussian:
    source_path: data/avatars/talkinggaussian_obama/source
    model_path: data/avatars/talkinggaussian_obama/model
    bg_img: "white"
```

**MuseTalk 示例：**

```yaml
model:
  type: musetalk
  avatar_id: musetalk_avatar1
  model_path: ./models
```

---

## 啟動相關

### Q：後端啟動失敗，提示找不到模型或配置檔案？

**A：** 檢查以下幾點：

- 確保已進入虛擬環境（如果使用 uv）：`source .venv/bin/activate`
- 檢查配置檔案路徑正確：`config/config_wav2lip.yaml` 等
- 檢查 `config/*.yaml` 中的 `models/` 和 `data/` 路徑是否指向正確的目錄
- 確保必要的模型權重已下載到 `models/` 目錄

### Q：前端啟動後訪問 localhost:3000 是空白？

**A：** 檢查以下幾點：

- 後端是否已成功啟動（檢視後端埠 8010）
- 前端是否選用了相同的配置檔案
- 瀏覽器控制台（F12）是否有報錯
- 清除瀏覽器快取後重試：Ctrl+Shift+Delete

### Q：後端與前端無法通訊？

**A：** 確保以下配置正確：

- 前端配置中 API 地址指向正確的後端地址（通常 `http://localhost:8010`）
- 防火牆或網路代理沒有阻擋 8010 埠
- 如果使用 HTTPS 模式，檢查證書配置是否正確

### Q：啟動指令碼提示許可權不足？

**A：** 新增執行許可權：

```bash
chmod +x scripts/start-backend.sh
chmod +x scripts/start-frontend.sh
chmod +x scripts/start-all.sh
chmod +x scripts/create_ssl_certs.sh
```

### Q：能否同時啟動多個後端例項？

**A：** 可以，但需要修改埠避免衝突：

```bash
# 終端 1：預設埠 8010
bash scripts/start-backend.sh config/config_wav2lip.yaml

# 終端 2：修改埠為 8011
# 編輯 config/config_wav2lip.yaml，將 app.listenport 改為 8011
bash scripts/start-backend.sh config/config_wav2lip.yaml
```

---

## 麥克風與音訊

### Q：遠端訪問時麥克風不可用？

**A：** 瀏覽器通常會限制非 HTTPS 來源的麥克風許可權。需要：

1. 在配置檔案中開啟 `app.ssl: true`
2. 確保已執行 `bash scripts/create_ssl_certs.sh` 生成證書
3. 使用 HTTPS 訪問前端（`https://localhost:3000`）
4. 接受瀏覽器的自簽名證書警告

### Q：沒有聲音輸出？

**A：** 檢查以下幾點：

- TTS 服務是否已正確配置（配置檔案中的 `tts.type`）
- 檢查 API Key 是否正確設定（如 `DASHSCOPE_API_KEY` 等）
- 瀏覽器音量是否靜音
- 檢查後端日誌是否有 TTS 錯誤

```bash
# 檢視環境變數是否已設定
echo $DASHSCOPE_API_KEY
```

### Q：麥克風輸入沒有反應？

**A：** 檢查以下幾點：

- 瀏覽器是否已獲得麥克風許可權（檢查位址列旁邊的許可權圖示）
- 作業系統級別是否允許瀏覽器訪問麥克風
  - macOS：系統偏好設定 → 安全與隱私 → 麥克風
  - Windows：設定 → 隱私和安全 → 麥克風
- ASR 模式是否正確配置（`asr.mode: browser` 表示在瀏覽器中識別）

---

## 全雙工與互動

### Q：如何實現全雙工對話？

**A：** Linly-Talker-Stream 支援真正的全雙工即時互動，即數字人說話時你也可以隨時打斷對話。

**啟用方法：**

在 Web 介面右上角點選 ⚙️ 設定按鈕，在「語音識別設定」中開啟 **「連續識別」** 和 **「持續監聽語音輸入」**，然後儲存設定即可。

開啟後，系統會持續監聽你的語音輸入，檢測到語音後會自動打斷當前對話並開始新的回應，實現自然的即時互動體驗

---

## 其他問題

### Q：錄製檔案在哪裡？

**A：** 錄製的影片和音訊會儲存到 `data/records/` 目錄，可通過 `/download/{filename}` 下載。

```bash
# 檢視所有錄製檔案
ls -lh data/records/

# 下載最新錄製的檔案
curl http://localhost:8010/download/latest_recording.mp4
```

### Q：如何切換不同的數字人模型？

**A：** 使用不同的配置檔案啟動後端和前端：

```bash
# 1. Wav2Lip（2D，快速）
bash scripts/start-backend.sh config/config_wav2lip.yaml
bash scripts/start-frontend.sh config/config_wav2lip.yaml

# 2. MuseTalk（2D，中等）
bash scripts/start-backend.sh config/config_musetalk.yaml
bash scripts/start-frontend.sh config/config_musetalk.yaml

# 3. ER-NeRF（3D，高質量）
bash scripts/start-backend.sh config/config_ernerf.yaml
bash scripts/start-frontend.sh config/config_ernerf.yaml

# 4. TalkingGaussian（3D，最新）
bash scripts/start-backend.sh config/config_talkinggaussian.yaml
bash scripts/start-frontend.sh config/config_talkinggaussian.yaml
```

### Q：如何除錯系統問題？

**A：** 啟用詳細日誌：

```bash
# 後端日誌
bash scripts/start-backend.sh config/config_wav2lip.yaml --debug

# 前端控制台（F12 開啟開發者工具）
# 檢視 Console、Network、Performance 標籤
```

### Q：如何提交問題或貢獻程式碼？

**A：** 

- 🐛 報告 Bug：[GitHub Issues](https://github.com/Kedreamix/Linly-Talker-Stream/issues)
- 💡 功能建議：[GitHub Discussions](https://github.com/Kedreamix/Linly-Talker-Stream/discussions)
- 🤝 貢獻程式碼：Fork → 修改 → Pull Request

提交前請確保：
- 提供清晰的問題描述和復現步驟
- 附加錯誤日誌和系統資訊
- 遵循專案的程式碼風格和貢獻指南

### Q：該專案有其他資源或社群嗎？

**A：** 

- 📖 檔案：[Linly-Talker](https://github.com/Kedreamix/Linly-Talker)
- 🎬 影片教程：[Bilibili](https://www.bilibili.com/video/BV1rN4y1a76x/)
- 💬 討論社群：[GitHub Discussions](https://github.com/Kedreamix/Linly-Talker-Stream/discussions)

---

## 還有問題？

如果以上內容沒有解答你的問題，請：

1. 檢查 [README_zh.md](./README_zh.md) 中的配置說明
2. 檢視 [QUICKSTART_UV.md](./QUICKSTART_UV.md) 瞭解 uv 相關問題
3. 在 GitHub Issues 中搜索是否已有類似問題
4. 提交新的 Issue 或在 Discussions 中提問
