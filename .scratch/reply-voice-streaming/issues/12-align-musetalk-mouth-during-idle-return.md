# 修正 MuseTalk 待機回復過渡的嘴部座標錯位

Type: task
Status: completed

## 背景與根因

回答結束後，MuseTalk 會從最後一張生成嘴型影格回到原始待機影格。現有 `MouthContinuityController` 會保留上一張完整影格，並在 `gap_grace_frames` 與 `closing_frames` 期間，使用目前待機索引的 mask 將上一張嘴部混入目前底圖。

待機素材的頭部及嘴部位置會隨索引移動，因此「上一張嘴部像素」與「目前 mask 座標」不一定對齊。現有靜止影格測試無法捕捉這個問題；真實素材會在約 7 幀的待機回復過渡中出現嘴部往返、錯位或鬼影。

次要問題是 renderer 以單一 audio pair 判斷 speech/idle。低能量尾音或 speech/idle 混合批次可能過早啟動 closing，使幾何錯位更容易被看見。

## 目標

1. 保持移動中的自然待機動作，不凍結完整影格。
2. 將上一個已顯示嘴部 ROI 對齊到目前待機嘴部座標後再混合。
3. 短暫 idle 不立即觸發 closing；speech 恢復時立即取消 closing。
4. 維持音訊主時鐘、audio-first enqueue 順序與現有 A/V SLO。
5. 新行為可獨立啟用、量測及回退。

## 非目標

- 不啟用全畫面 crossfade。
- 不延長 audio buffer、不等待視訊、不修改 RTP pacing。
- 不加入旋轉、剪切、optical flow 或執行期人臉特徵點模型。
- 不在 idle 時持續執行 MuseTalk GPU inference。
- 不改變非 MuseTalk Avatar 的行為。
- 不把本票擴展為 neutral-mouth cache 重建工程。

## 模組與 interface

`MouthContinuityController` 繼續作為深模組；renderer 只需提供目前目標影格、索引、speech 狀態與 eventpoint。幾何對齊、狀態計數、異常回退與診斷統計均留在其 implementation 內，不能散落到 `BaseAvatar.process_frames()`。

外部 interface 維持：

```python
compose(
    target_frame: np.ndarray,
    *,
    index: int,
    is_speech: bool,
    eventpoint: dict | None,
) -> np.ndarray

reset() -> None
```

不得把 previous/current bbox、transform matrix、hysteresis counter 或 fallback reason 暴露成 caller 必須管理的參數。若需要讀取測試／觀測結果，可提供單一不可變的 metrics snapshot，而不是多個狀態 getter。

## 詳細修改流程

### Phase 0：建立可重現基準

1. 在 `tests/test_mouth_continuity.py` 新增多影格 fixture：至少 8 張待機影格，每張嘴部 mask 的中心向同一方向移動，並包含小幅等比例尺寸變化。
2. 生成的 speech mouth patch 使用清楚且非對稱的圖樣，確保座標偏移可被像素差與 centroid 測出。
3. 建立 `speech → idle → idle...` 序列，使用目前 implementation 證明過渡期間出現 ROI centroid 往返或差異尖峰。
4. 加入 A/B 基準：停用 controller，或把 grace 設為 0、closing 設為 1；記錄抖動是否消失，以確認問題位於嘴型連續控制而非 WebRTC pacing。
5. 基準測試不得依賴 wall clock、GPU、網路或真實 Avatar 檔案。

Gate：新測試在舊 implementation 上穩定失敗，且 failure message 能指出哪一幀、哪個 bbox 與哪項差異超標。

### Phase 1：保存嘴部 ROI 與幾何資訊

修改 `src/avatars/musetalk/mouth_continuity.py`：

1. `_remember()` 不再只保存上一張完整畫面；保存上一個已顯示的 mouth patch、來源 bbox、來源 mask 與必要的 generation 資訊。
2. bbox 統一使用 full-frame 座標 `(x1, y1, x2, y2)`，並在初始化時驗證寬高為正、沒有超出影格。
3. mask/bbox 預處理留在初始化或索引 cache；hot path 不重建 PIL mask，也不做磁碟 I/O。
4. `reset()` 清除 patch、bbox、狀態、hysteresis counter 與當次 transition 統計，避免跨 generation 使用舊嘴型。

Gate：既有靜止影格、reset、mask 投影及 ROI 外像素測試全部維持通過。

### Phase 2：實作受限的 ROI 對齊

在 controller implementation 內新增私有對齊流程：

1. 從 previous bbox 與 current bbox 計算中心位置和寬高。
2. scale 使用寬高比例的穩健單值，例如兩者比例的幾何平均；只允許等比例縮放。
3. 先 resize previous mouth patch，再平移到 current bbox 中心；裁切時必須正確處理 frame edge，不可負索引繞回。
4. 只在目前 feather mask 內 blend；ROI 外輸出必須逐像素等於 `target_frame`。
5. 使用現有 monotonic easing 推進 alpha，不引入 wall-clock 判斷。

安全限制：

- current/previous 中心位移不得超過 previous mouth width 的 25%。
- scale 必須位於 `0.85–1.15`。
- bbox/mask 空白、shape 不符、非有限值或 OpenCV 例外均視為不安全變換。

不安全時不得強行 warp，也不得回用上一張完整影格；改用目前索引的 neutral/source mouth 完成短 closing，並增加 fallback 計數。任何未預期錯誤最終仍回退 caller 提供的 `target_frame`，不得影響音訊或中止 renderer。

Gate：移動 mask fixture 不再出現 centroid 往返；ROI 外最大差值為 0；異常 transform 全部 deterministic fallback。

### Phase 3：加入 speech → idle hysteresis

1. 在 controller 內新增連續 idle pair counter，預設門檻為 2 個 compose frame pair，對應約 80 ms。
2. `SPEAKING` 收到第一個 idle 時只進入待確認狀態，繼續保持視覺連續，不立即 closing。
3. 連續第二個 idle 才進入 closing。
4. 待確認或 closing 期間收到 speech，立即清除 idle counter 並進入 opening/speaking；音訊仍照原路立即 enqueue。
5. generation 改變、`flush_talk()`、插話及 session close 必須 reset counter。
6. hysteresis 可由 MuseTalk 設定提供預設值，但 caller 不得自行實作計數邏輯。

注意：目前 `process_frames()` 對每個 result batch 以兩個 audio frame type 推導 `is_speech`。本票先保留 renderer 的既有輸入契約，將抖動抑制集中在 controller；只有測試證明 mixed pair 仍造成錯誤狀態時，才將判斷抽成具名 helper，並以 `any(frame_type == 0)` 表示該 video frame 含可聽 speech。不得同時改動音訊 frame type 的生產規則。

Gate：單一 idle pair 不啟動 closing；兩個連續 idle pair 會啟動；任一 speech 能立即恢復，且 transition 長度不受 fake clock 影響。

### Phase 4：設定、觀測與隱私

修改 `src/config/schema.py` 及對應設定範例：

1. 保留 `model.musetalk.mouth_continuity` 作總開關。
2. 新增獨立幾何對齊開關，預設先關閉，供 canary 與快速回退。
3. 將 `idle_hysteresis_pairs=2`、最大位移比 `0.25`、最小／最大 scale `0.85/1.15` 定義為有驗證範圍的設定；若專案傾向縮小設定面，可先作 controller 常數，只暴露總開關與對齊開關。
4. 正常模式只聚合：transition 次數、fallback 次數、fallback reason、最大位移比、最大／最小 scale、video repeat/drop。
5. 逐幀 `frame_type`、index、bbox、queue 水位只在診斷開關啟用時輸出；不得記錄 frame 像素、使用者音訊或回答內容。

Gate：無效設定在載入時提供明確錯誤；預設關閉時輸出與目前版本一致；正常 log 不含內容資料。

### Phase 5：自動回歸與效能

新增或更新以下測試：

1. 移動 bbox 的 speech → idle closing 能保持嘴部中心單向且平滑移動。
2. bbox 同時平移和縮放時只使用等比例 transform。
3. 位移恰好 25% 可對齊，超過門檻會 fallback。
4. scale 邊界 `0.85`、`1.15` 可對齊，超界會 fallback。
5. 空 mask、零面積 bbox、frame edge 裁切與 shape mismatch 不會拋出至 renderer。
6. ROI 外像素與每一張目前 `target_frame` 完全相同。
7. 一個 idle pair 不 closing；兩個 idle pair closing；speech 恢復立即取消。
8. generation/reset 不保留 previous patch 或 counter。
9. compose 例外只回退 target video；配對音訊不等待、不撤銷、不重送。
10. 連續 1,000 個 idle frame 不累積記憶體或未界定狀態。
11. 目標 450×450 warm-cache `compose()` CPU P95 ≤ 2 ms。
12. `tests/test_speech_timing.py` 與 `tests/test_media_fencing.py` 證明 audio PTS、video PTS 單調且 audio-first 順序不變。

自動視覺 gate 採每個 Avatar/fixture 的相對待機基準：

- 待機回復過渡的臉部 ROI 相鄰影格差異不得超過正常待機 p95 的 1.5 倍。
- ROI 外差異相對未啟用 controller 的同幀 target 不得增加超過 5%；純 controller 單元測試仍要求 ROI 外最大像素差為 0。
- 過渡期間不得出現連續方向反轉的嘴部 centroid 位移。
- 不得增加音訊 enqueue 延遲、media debt 或 catch-up burst。

建議驗證命令：

```bash
uv run python -m unittest tests.test_mouth_continuity
uv run python -m unittest tests.test_speech_timing tests.test_media_fencing tests.test_playback_commit
uv run python -m unittest discover -s tests
uv run python -m compileall -q src tests
git diff --check
```

## 修改檔案

主要修改：

- `src/avatars/musetalk/mouth_continuity.py`：ROI 保存、幾何對齊、安全回退、hysteresis 與 metrics。
- `src/avatars/musetalk/avatar.py`：建立 controller、讀取 MuseTalk 設定；不得搬入狀態機細節。
- `src/config/schema.py`：功能開關與受限參數。
- `tests/test_mouth_continuity.py`：移動遮罩與幾何回歸測試。
- `tests/test_media_fencing.py`：audio-first、reset 與 renderer fallback 整合測試。
- `tests/test_speech_timing.py`：PTS、pacing 與無額外音訊延遲驗證。

只有在 mixed speech/idle pair 測試證明必要時修改：

- `src/avatars/base.py`：將 speech 判斷抽成小型具名 helper；不得改變 audio enqueue 順序。

## 完成條件

- 所有 Phase 0–5 gate 通過。
- v1 預設啟用待機嘴部對齊；設定可立即回退原行為。
- Edge TTS＋MuseTalk 自動測試無 regression。
- ADR-0007 的音訊主時鐘與 ADR-0008 的純視覺嘴型 seam 均未被破壞。
- 回答結束另由 12 影格 settling 接續至移動中的待機影格。

## Comments

- 2026-09-11: 根據待機回復抖動分析與三輪設計決策建立；Issue 11 的靜止影格測試不足以涵蓋移動待機素材。
- 2026-09-11: 已完成 controller ROI 對齊、25% 位移與 `0.85–1.15` scale 安全回退、設定開關，以及 2-frame grace 預設。新增移動 mask regression、停用回退與 settling regression；完整 suite 的過期 Rule 文案預期亦已同步至目前預設規則。
