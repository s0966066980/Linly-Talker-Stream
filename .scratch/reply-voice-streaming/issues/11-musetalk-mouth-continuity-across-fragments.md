# MuseTalk 段落間嘴型連續控制器

Type: task
Status: completed

## 問題

回覆語音串流在兩個可播回覆片段之間，TTS queue 可能短暫沒有下一個 PCM。MuseTalk 目前把這段時間標為 idle，`BaseAvatar.process_frames()` 會立即從 MuseTalk 貼回影格切換到原始 `frame_list_cycle[idx]`；下一片段開始時又立即切回 MuseTalk。即使底圖索引相同，嘴部顏色、輪廓、開口基準、銳化與 mask 貼回結果仍不同，因此段落邊界會出現嘴型閃跳。

已建立最小重現：同一底圖索引下，說話影格固定為 MuseTalk 合成影格、下一幀固定為原始 idle 影格，嘴部 ROI 單幀平均跳變為 `191.7`，超過測試容許值 `50.0`。

另一個最小重現證實：`get_audio_frames(8)` 只有第一個 PCM 可用時，回傳型別為 `[0, 1, 1, 1, 1, 1, 1, 1]`；也就是同一輪次仍可能繼續產生內容，但批次中暫時沒有 PCM 的影格已被視為一般 idle。

## 目標

1. 段落間不再單幀硬切 MuseTalk 嘴部與原始嘴部。
2. 保留回覆語音串流，不退回等待完整回答或整段影片一次生成。
3. 音訊仍是唯一播放主時鐘；視覺過渡不得延後、重送、丟棄或加速音訊。
4. 首音、音訊 pacing、A/V、插話與重連不得比 `real-soak-audio-quality-fix-final-50.json` 退化。
5. 長時間 idle 不持續執行 MuseTalk GPU inference。
6. 所有視覺狀態以媒體影格數推進，不使用 wall-clock 判斷 transition 長度。

## 非目標

- 不修改 TTS PCM 的內容、frame size、sample rate 或送出間隔。
- 不修改 WebRTC audio queue 大小、speech-start runway、RTP PTS 或 pacing rebase。
- 不重新啟用 `decoupled_audio_clock`。
- 不以 time-stretch、補播、catch-up burst 或較大的 audio buffer 隱藏視覺問題。
- 第一階段不做執行期 silence inference；neutral mouth 必須預先建立或使用純 CPU 過渡 fallback。
- 不把所有 LLM 文字合併後才送 TTS。

## 必須維持的基準

正式基準：`.scratch/reply-voice-streaming/real-soak-audio-quality-fix-final-50.json`

| 指標 | 已通過基準 | 不得低於的 gate |
|---|---:|---:|
| first audio P50 | 1.153 s | ≤ 1.2 s |
| first audio P95 | 1.706 s | ≤ 2.5 s |
| A/V offset P95 | 40 ms | ≤ 80 ms |
| interrupt stop P95 | 0.61 ms | ≤ 200 ms |
| listening resume P95 | 302 ms | ≤ 500 ms |
| max media debt | 240 ms | ≤ 2 s |
| stale output | 0 | 必須為 0 |
| catch-up burst | 0 | 必須為 0 |

## 架構決策

### Seam

在「renderer 已選出當前目標影格」與「建立 `VideoFrame` 並 enqueue」之間建立視覺影格轉換 seam。

新增深模組：

`src/avatars/musetalk/mouth_continuity.py`

外部 interface 保持只有兩個方法：

```python
class MouthContinuityController:
    def compose(
        self,
        target_frame: np.ndarray,
        *,
        index: int,
        is_speech: bool,
        eventpoint: dict | None,
    ) -> np.ndarray: ...

    def reset(self) -> None: ...
```

呼叫端不應知道：

- transition 目前位於哪一幀。
- gap grace、closing、opening 的影格數。
- mouth mask 的座標轉換、feather 或 easing。
- neutral cache 是否存在、版本是否有效及 fallback 規則。
- 上一個 mouth patch、generation 或 fragment 狀態。

controller 是純 in-process 模組：不得讀 queue、不得 await、不得 sleep、不得呼叫 TTS、不得 enqueue WebRTC media、不得執行 GPU inference。

### Adapter

在 `BaseAvatar` 內提供 passthrough adapter；MuseTalk 建立 `MouthContinuityController` adapter。其他 avatar 不改變行為。這使 seam 有兩個真實 adapter，不是只為測試建立的假抽象。

### 音訊隔離

`BaseAvatar.process_frames()` 必須保持下列順序：

```text
generation fence
  → 建立並 enqueue paired audio frames
  → 記錄 webrtc_audio_enqueue
  → 選擇 raw/generated target video frame
  → MouthContinuityController.compose()（純 CPU、有界）
  → 建立 VideoFrame
  → video enqueue/drop
```

任何 controller 錯誤都只能退回 `target_frame`；不得回頭撤銷或等待已 enqueue 的音訊。

## 視覺狀態機

狀態只由已消費的媒體影格推進：

```text
SOURCE_IDLE
  └─ speech → OPENING → SPEAKING

SPEAKING
  ├─ speech → SPEAKING
  └─ idle   → GAP_GRACE

GAP_GRACE
  ├─ speech before grace expires → OPENING → SPEAKING
  └─ grace expires               → CLOSING

CLOSING
  ├─ speech → OPENING → SPEAKING
  └─ done   → GENERATED_NEUTRAL

GENERATED_NEUTRAL
  ├─ speech → OPENING → SPEAKING
  └─ idle   → GENERATED_NEUTRAL
```

初始候選值只作內部常數，不先擴大設定介面：

- `gap_grace_frames = 2`：80 ms。
- `opening_frames = 2`：最多 80 ms，符合 A/V 80 ms gate。
- `closing_frames = 3`：120 ms，發生在音訊結束後。
- easing 使用 monotonic smoothstep；不得依賴 `time.time()`。

實機 A/B 可調整內部常數，但正式設定只暴露單一功能旗標：

```yaml
model:
  musetalk:
    mouth_continuity: false
```

完整 50 輪與人工視覺 gate 通過後才改為 `true`。

## 影格合成規則

1. controller 每次都以呼叫端選出的當前 `target_frame` 作為頭部、身體與背景。
2. transition 只操作現有 MuseTalk mouth mask 覆蓋的 ROI；禁止全畫面 `cv2.addWeighted()`。
3. ROI 外像素必須與 `target_frame` 完全相同。
4. 先將上一個已顯示 mouth patch 對齊到當前 index 的 mouth box，再在當前 mask 內做 alpha blend。
5. mask 使用現有 `mask_list_cycle` 與 `mask_coords_list_cycle`，初始化時預先轉為 full-frame feather mask；hot path 不重建 PIL mask。
6. 新 speech 開始時，音訊照常立即 enqueue；video 最多使用兩幀從目前 neutral/closing mouth 進入第一個 generated mouth，不得延遲 audio。
7. 插話、generation 改變、avatar 切換及 session close 必須呼叫 `reset()`，舊 generation 的 mouth patch 不得進入新輪次。

## Neutral mouth cache

### 目的

單純 crossfade 最後仍會抵達原始嘴型；若原始素材與 MuseTalk 貼回風格差異很大，下一次 speech 開始仍可能看到質感變化。正式方案需要 per-index MuseTalk neutral mouth cache，使 idle 與 speech 使用同一個貼回影像域。

### 儲存格式

角色目錄新增可選 artifact：

```text
data/avatars/<avatar_id>/neutral_mouth/
  manifest.json
  0.png
  1.png
  ...
```

只儲存 mouth ROI patch，不複製完整背景影格。`manifest.json` 至少包含：

- `schema_version`
- `avatar_id`
- `frame_count`
- 原始 full image、coords、mask 與 MuseTalk model 的 fingerprint
- patch box 與影像格式

fingerprint 不符、frame count 不符或檔案缺失時，controller 必須使用 CPU transition fallback，不能阻止 avatar 啟動。

### 建立流程

在 avatar builder 增加獨立步驟，使用固定 neutral/closed-mouth conditioning 對每個 latent 產生一次 mouth patch，再走與 runtime 相同的 `enhance_from_config()` 與 mask blending。產生完成後先寫暫存目錄，驗證數量及 manifest，再原子移入正式目錄。

不得在 WebRTC session 建立時同步生成完整 neutral cache。

### Runtime

- cache 載入與 full-frame mask 建立發生在 avatar 初始化。
- `GENERATED_NEUTRAL` 以目前 index 的原始 frame 為底，只貼 cached mouth patch。
- cache 不存在時仍使用 frame-count、mask-only transition；不得改回單幀硬切。
- neutral patch 總記憶體預算初始設定為 ≤128 MiB；超過時採 lazy decode LRU，不擴大音訊 buffer。

## 詳細修改順序

### Phase 0：鎖定紅色回饋迴路

1. 將現有 throwaway harness 轉為 `tests/test_mouth_continuity.py`。
2. fixture 固定同一 index、原始 frame 為 0、generated frame 為 200、mouth mask 固定。
3. 驗證目前 speech → idle 的 mouth ROI jump 約 191.7，測試必須先失敗。
4. 加入 `get_audio_frames()` 同輪次暫時補 idle 的整合 fixture，確保測試覆蓋真正段落 gap，而不是單一函式的人工狀態。

紅色命令：

```bash
uv run python -m unittest tests.test_mouth_continuity
```

### Phase 1：建立 seam，維持行為不變

1. 新增 passthrough frame-transition adapter。
2. 在 `BaseAvatar.process_frames()` 已選出 `combine_frame` 後、watermark 與 `VideoFrame` 建立前呼叫 adapter。
3. 保持 audio enqueue 位於 compose 之前。
4. MuseTalk 尚未啟用功能旗標時也使用 passthrough adapter。
5. 執行全部既有 pacing、media fencing 與 playback commit tests，結果必須完全不變。

### Phase 2：實作 mask-only、frame-count transition

1. 建立 `MouthContinuityController`。
2. 初始化時預計算每個 index 的 full-frame mouth mask、ROI 及 feather alpha。
3. 實作 `SOURCE_IDLE`、`OPENING`、`SPEAKING`、`GAP_GRACE`、`CLOSING`、`GENERATED_NEUTRAL`。
4. 沒有 neutral cache 時，`GENERATED_NEUTRAL` 使用最後顯示 mouth patch 到原始 neutral mouth 的平滑 fallback；禁止直接硬切。
5. generation 改變或 `flush_talk()` 時 reset。
6. 所有 transition 以 compose 呼叫次數計數，fake clock 任意跳動不得改變輸出序列。

### Phase 3：建立 neutral mouth cache

1. 擴充 MuseTalk avatar builder，新增 neutral patch 產生函式。
2. 共用 runtime 的 resize、enhance、mask 與貼回參數，避免 builder/runtime domain 再次不一致。
3. 寫入 manifest/fingerprint。
4. MuseTalk 載入角色時驗證並載入 cache；失敗只記錄一次 warning 並使用 fallback。
5. 禁止在 speech hot path 做磁碟 I/O；lazy cache 必須有界並預取下一個 mirror index。

### Phase 4：段落狀態整合

1. controller 以最近有效 eventpoint 記住 `turn_id`、generation、fragment sequence。
2. idle eventpoint 為 `None` 時不得假設輪次已結束；先進入 `GAP_GRACE`。
3. 下一個相同 generation speech 到達時從目前狀態進入 `OPENING`。
4. 新 generation、插話或 session reset 清除舊 patch。
5. 不修改 `get_audio_frames()` 的 10 ms poll、padding 策略或任何 audio frame type；本 phase 只解讀既有結果，不改音訊行為。

### Phase 5：測試與效能保護

新增下列自動測試：

1. speech → short gap → speech 不出現 source hard cut。
2. speech → long idle 以固定三幀 closing 到 neutral。
3. idle → speech opening 不超過兩幀。
4. transition 長度不受 fake wall-clock 影響。
5. mouth mask 外像素與當前 target frame 完全相同。
6. cache 缺失、fingerprint 錯誤及單幀損壞都能 fallback。
7. generation 改變後不混入舊 mouth patch。
8. interrupt 發生在 opening、speaking、closing 各狀態時都能 reset。
9. video compose 例外只退回 target frame；audio 已 enqueue 且不重送。
10. controller compose CPU P95 ≤2 ms（目標 450×450，warm cache）。
11. controller 不呼叫 sleep、queue、asyncio、TTS 或 WebRTC track。
12. 既有 audio frame PCM 值、sample rate、samples、media sequence 完全不變。

視覺 fixture gate：

- 同 index mouth ROI 最大單幀跳變 ≤50。
- mask 外最大差值為 0。
- opening 最多 2 幀，closing 最多 3 幀。
- 連續 1,000 個 idle frame 不累積狀態或記憶體。

### Phase 6：實機漸進驗收

依序執行，任何一步失敗立即關閉功能旗標：

1. 5 輪快速 A/B：短句、長句、弱標點、無標點與至少三個可播片段。
2. 15 輪：包含播放中斷、LLM 中斷與重連。
3. 50 輪正式 soak。
4. 人工並排觀看：正常速度及 0.25× 慢速，各檢查至少 10 個段落邊界。

實機必須同時通過：

- first audio P50 ≤1.2 s、P95 ≤2.5 s。
- A/V offset P95 ≤80 ms。
- interrupt stop P95 ≤200 ms。
- listening resume P95 ≤500 ms。
- max media debt ≤2 s。
- stale output = 0。
- catch-up burst = 0。
- 不出現 audio pacing stall warning。
- 段落邊界不得有單幀原始嘴型閃現。
- speech 結束後嘴巴必須自然閉合，不可凍結在張嘴姿勢。

驗證命令：

```bash
uv run python -m unittest tests.test_mouth_continuity
uv run python -m unittest tests.test_speech_timing tests.test_media_fencing tests.test_playback_commit
uv run python -m unittest discover -s tests
cd web && npm test && npm run build
uv run python -m compileall -q src tests
git diff --check
uv run python scripts/run_voice_soak.py \
  --base-url https://localhost:8010 \
  --turns 15 \
  --output .scratch/reply-voice-streaming/mouth-continuity-15.json
uv run python scripts/run_voice_soak.py \
  --base-url https://localhost:8010 \
  --turns 50 \
  --output .scratch/reply-voice-streaming/mouth-continuity-final-50.json
```

## 目標檔案

預計新增：

- `src/avatars/musetalk/mouth_continuity.py`
- `tests/test_mouth_continuity.py`
- neutral cache builder/helper（位置由現有 builder locality 決定）

預計修改：

- `src/avatars/base.py`：frame-transition seam、reset hook；audio-first 順序不可改。
- `src/avatars/musetalk/avatar.py`：建立 controller、提供 mask/cache 素材。
- `src/avatars/musetalk/genavatar_musetalk.py` 或 `src/avatars/builder.py`：離線 neutral cache。
- `src/config/schema.py`：單一 `mouth_continuity` 功能旗標。
- `src/config/overrides.py`：旗標持久化。
- `tests/test_media_fencing.py`：generation/interrupt 與 audio-before-video 保護。
- `tests/test_runtime_settings.py`：旗標 round-trip。

第一階段禁止修改：

- `src/utils/webrtc.py`
- `src/tts/engines/edge.py`
- `src/avatars/audio_stream_handler.py`
- `src/avatars/musetalk/audio_stream_handler.py`
- WebRTC audio track 與 pacing 常數

若實作發現必須修改上述檔案才能完成視覺連續性，先停止並重新審查設計；不得順手擴大 audio path 變更。

## 回退

1. `model.musetalk.mouth_continuity=false` 必須立即恢復目前已通過 50 輪的 renderer 行為。
2. cache 缺失或 controller 例外自動使用 passthrough/fallback，不阻止服務啟動。
3. 回退不修改 `reply_streaming.enabled`、`decoupled_audio_clock`、audio runway 或 WebRTC buffer。
4. neutral cache 是衍生 artifact，可刪除後重建，不影響原始 avatar 素材。

## 禁止捷徑

- 不直接把現有 `enable_transition` 改為 `True`；它使用 wall-clock 且全畫面 blend。
- 不用最後一張張嘴影格長時間凍結等待下一段。
- 不在 runtime session 啟動時同步跑完整 neutral inference。
- 不增加 audio queue runway 或 TTS 前置 buffer 來換視覺平滑。
- 不在 video transition 落後時 burst 追趕。
- 不因視訊處理失敗重新送出音訊。
- 不把 `fragment_end` 當成整個 turn 已完成。
- 不讓 cache/transition 跳過 generation fence。

## 完成定義

只有以下條件全部成立才能標記 resolved：

1. 最小 mouth ROI hard-cut repro 轉綠。
2. mouth continuity 模組只透過小 interface 使用，視覺狀態與 cache 細節沒有散落到 renderer caller。
3. audio-first enqueue 順序與 PCM/PTS/pacing 完全不變。
4. 自動視覺、generation、interrupt、pacing 與完整回歸通過。
5. 15 輪及 50 輪實機 soak 全部 SLO 通過。
6. `stale_output=0`、`catch_up_burst=0`，且沒有 audio pacing stall。
7. 人工檢查確認段落邊界沒有原始嘴型閃現、凍結張嘴或明顯重影。
8. 功能旗標可單獨回退且不會改動音訊設定。

## Comments

- 2026-09-01：依實機回報建立。設計刻意把改動限制在 video compositing seam；上一輪已修復並正式驗收的 coupled audio master、40 ms speech-start runway 與 WebRTC pacing 全部視為不可變基準。
- 2026-09-01：已實作 `MouthContinuityController`，在 `BaseAvatar.process_frames()` 的音訊送出後、VideoFrame 建立前，只對 MuseTalk 嘴部 ROI 做影格數驅動的過渡：段落短暫空檔保留 1 個影格，接著 4 個影格線性閉嘴；新語音恢復時 2 個影格開嘴。新 generation 或 `flush_talk()` 會清除狀態。遮罩支援 MuseTalk 產生的裁切 BGR PNG，會轉為單通道並投影回原始畫布。任何視覺控制器例外都回退原影格，不會阻塞音訊。
- 2026-09-01：設定 `model.musetalk.mouth_continuity: true`（可設為 `false` 回退舊行為）；未修改 PCM frame size、sample rate、音訊 queue、WebRTC PTS 或 pacing。
- 2026-09-01：`uv run python -m unittest discover -s tests -p 'test_*.py'` 232/232 通過；`npm test -- --runInBand` 23/23 通過；`npm run build`、`compileall` 與 `git diff --check` 通過。RTX 4090 + MuseTalk + WebRTC 實機 50 回合 `slo_pass=true`：A/V offset P95 0.06s、首音 P50 1.185525s/P95 1.691548s、打斷停止 P95 0.000345s、恢復 P95 0.301517s、media debt 0.24s、stale output 0。報告：`real-soak-mouth-continuity-50-rerun.json`。
