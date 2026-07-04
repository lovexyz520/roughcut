# Roughcut — 自動剪輯系統規格書

版本：V2.2.0
日期：2026-07-04

## 1. 專案概覽

Roughcut 是一套自動影片初剪系統，從手機拍攝的素材資料夾自動產生影片初稿（rough cut），並輸出 Adobe Premiere 可匯入的 FCP7 XML 時間軸。

### 核心目標

1. 從影片與照片素材自動產生具敘事節奏的 rough cut
2. 配合背景音樂節拍安排切點
3. 產出 Premiere 可匯入的時間軸，縮短人工初剪時間

### 技術棧

- Python 3.11+
- FFmpeg（影片處理）
- OpenCV（影像分析）
- librosa（音樂節拍分析）
- pandas（資料處理）
- Typer（CLI 框架）
- PyYAML（設定檔）
- hatchling（build system）

---

## 2. 專案結構

```
roughcut/
  CLAUDE.md               ← 本檔案（完整規格書）
  README.md               ← 使用說明
  autocut/
    pyproject.toml         ← 套件定義與版本
    src/roughcut/          ← 主程式碼
      __init__.py
      cli.py               ← CLI 進入點 (Typer)
      constants.py         ← 常數、閾值、錯誤碼
      models.py            ← 資料模型 (dataclass)
      pipeline.py          ← 主流程協調器
      analyze/             ← 分析模組
        beat.py            ← 節拍/音樂段落分析
        highlights.py      ← 高光偵測
        quality.py         ← 品質評分（多幀聚合）
        shot_detect.py     ← 鏡頭切分
        shot_role.py       ← 鏡頭角色分類
        expression.py      ← 真實笑容/表情偵測（V2.2）
        audio_energy.py    ← 素材音訊分析（笑聲/興奮，V2.2）
        composition.py     ← 構圖評分（三分法/頭部空間，V2.2）
        camera_motion.py   ← 相機運鏡分類（pan/tilt/zoom/shake，V2.2）
        color.py           ← 色溫/色彩連續性（V2.2）
        dedup.py           ← 近似重複偵測（pHash，V2.2）
      editor/              ← 剪輯模組
        ken_burns.py       ← Ken Burns 照片運鏡
        timeline.py        ← 時間軸組裝
      export/              ← 輸出模組
        draft.py           ← MP4 草稿渲染
        premiere_xml.py    ← FCP7 XML 匯出
      ingest/              ← 輸入模組
        scanner.py         ← 媒體掃描、索引、去重
      planner/             ← 規劃模組
        base.py            ← 基礎規劃器（選片、評分、多樣性）
        events.py          ← 事件分群與排名
        grammar.py         ← 剪輯語法引擎
        growth.py          ← 成長影片規劃器
        preference.py      ← 使用者偏好學習
        travel.py          ← 旅遊影片規劃器
      report/              ← 報告模組
        writer.py          ← 報告/CSV/story_notes 生成
    config/
      profile_growth.yaml  ← 成長影片設定
      profile_travel.yaml  ← 旅遊影片設定
    tests/                 ← 測試（140 tests）
```

---

## 3. Pipeline 流程

```
[Ingest] → [Analyze] → [Plan] → [Edit] → [Export] → [Report]
```

### 3.1 Ingest（掃描）

- `scanner.py`：遞迴掃描輸入目錄
- 讀取 metadata（建立時間、解析度、幀率、時長、GPS）
- 以 hash + 檔案大小 + 時長做去重
- DNG 照片自動建立 proxy（多策略：rawpy → imageio → ffmpeg）
- 產生 `media_index.json`

### 3.2 Analyze（分析）

支援 `--max-workers` 平行分析。

- **shot_detect.py**：鏡頭切分（histogram diff + optical flow + luminance jump）
- **quality.py**：品質評分（清晰度、曝光、穩定度、人臉、動態強度）→ `QualityScores`
  - V2.2：point metrics 改為**多幀聚合**（取樣幀中的最佳/中位數），不再只看中間幀
  - V2.2：一次取樣同時計算表情、構圖、色溫、運鏡、pHash
- **expression.py**（V2.2）：真實笑容/表情偵測（bundled smile cascade + 眼睛驗證）→ `smile_score`
- **audio_energy.py**（V2.2）：素材本身音軌分析（RMS 響度 + 笑聲/興奮啟發式）→ `audio_energy`, `laughter_score`
- **composition.py**（V2.2）：構圖評分（三分法主體位置、臉部頭部空間、水平線）→ `composition`
- **camera_motion.py**（V2.2）：相機運鏡分類（static/pan/tilt/zoom/shake，Farneback 光流）
- **color.py**（V2.2）：色溫（冷暖）與相鄰鏡頭色彩連續性距離
- **dedup.py**（V2.2）：事件內近似重複偵測（DCT pHash），連拍只留最佳一顆
- **shot_role.py**：鏡頭角色分類（establishing / action / reaction / detail，V2.2 納入運鏡與構圖）
- **highlights.py**：高光偵測（**真實笑容**/笑聲/注視/動作，chorus 段加分）→ `highlight_score`
- **beat.py**：音樂分析（節拍、段落偵測 intro/verse/chorus/bridge/outro、能量曲線）

### 3.3 Plan（規劃）

- **events.py**：
  - 依拍攝時間分群（gap > threshold → 新事件）
  - Event Ranking（品質/多樣性/高光綜合排名）
  - Event Arc（establishing → action → reaction → detail）
- **base.py**：
  - 章節配額分配
  - 評分模型：`total_score = quality + face + motion + story_fit + rhythm_fit - penalties`
  - 音樂段落對應（intro→establishing, chorus→highlight）
  - 多樣性控制（同源/同事件/同角色懲罰、事件覆蓋率下限）
- **grammar.py**：
  - 禁止連續同景別
  - 高動態鏡頭後插入緩衝
  - 章節語意化轉場
- **growth.py** / **travel.py**：
  - 模板專屬規劃邏輯
  - 時間前進性（growth）、行程節點（travel）
  - 敘事模式：chronological / energy_first / hybrid
- **preference.py**：
  - 從 favorites/exclude 學習使用者偏好
  - 產出 `user_profile.json`

### 3.4 Edit（剪輯）

- **timeline.py**：組裝 `TimelineClip` 序列，beat-snap 切點對齊
- **ken_burns.py**：照片套用 Ken Burns 運鏡（zoom 1.0-1.15, pan 0.05）

### 3.5 Export（輸出）

- **draft.py**：
  - 正式渲染（1080p / 12Mbps）
  - 快速預覽（720p / 6Mbps，`--fast-preview`）
  - 支援 `--dry-run` 跳過渲染
  - 片長不足時自動 backfill
- **premiere_xml.py**：
  - FCP7 XML 格式
  - V1 軌（主時間軸）+ V2 軌（備選鏡頭，預設 Disable）
  - 三層標記：chapter（藍）、event（綠）、highlight
  - Marker 含 `why_selected` 說明

### 3.6 Report（報告）

- **writer.py**：
  - `report.json`：完整分析報告（含節奏對齊統計）
  - `selected_clips.csv` / `rejected_clips.csv`
  - `story_notes.md`：每章摘要 + 建議替換點
  - `user_profile.json`：使用者偏好分析
  - Review 模式輸出：`candidates.csv`、`events.csv`、模板檔

---

## 4. 模板系統

### 4.1 Growth（小孩成長）

| 章節 | 比例 | 內容 | 偏好鏡頭 |
|------|------|------|----------|
| opening | 10% | 暖場、日期感 | 穩定、有臉、曝光好 |
| learning | 45% | 上課、練習、專注 | 穩定、清晰、適度動態 |
| highlights | 30% | 笑容、成果、互動 | 高臉部分數、動態 |
| closing | 15% | 結束動作、照片 | 穩定、安靜、照片加分 |

權重：人臉與情緒高、穩定度中高、過暗/模糊懲罰高。

### 4.2 Travel（家庭旅遊）

| 章節 | 比例 | 內容 | 偏好鏡頭 |
|------|------|------|----------|
| departure | 15% | 交通、準備 | 穩定、動態、有臉 |
| exploration | 50% | 地標、活動 | 清晰、動態、寬景 |
| interaction | 25% | 合照、玩樂 | 高臉部分數、穩定 |
| ending | 10% | 夕陽、返程 | 曝光好、穩定、照片 |

權重：風景廣角與地標分數高、時間連續性高、避免同景別重複。

---

## 5. 設定檔格式

完整 YAML 欄位（以 growth 為例）：

```yaml
project_type: growth              # growth | travel
target_duration_sec: 240          # 目標成片時長（秒）
video_photo_ratio: [7, 3]         # 影片:照片時長比例
seed: null                        # 隨機種子（null 為隨機）
narrative_mode: chronological     # chronological | energy_first | hybrid

clip_duration_sec:
  min: 1.5                        # 單片最短秒數
  max: 6.0                        # 單片最長秒數

max_same_event_streak_sec: 20     # 同事件連續最長秒數

shot_detect:                      # 鏡頭切分參數
  min_duration: 0.5               # 最短鏡頭長度（秒）
  max_duration: 8.0               # 強制切分長度（秒）
  histogram_threshold: 0.4        # 色彩直方圖差異閾值
  optical_flow_threshold: 12.0    # 光流位移閾值（像素）
  luminance_threshold: 30.0       # 亮度跳變閾值
  sample_interval: 3              # 每 N 幀取樣一次

music:
  mode: single                    # 音樂模式（目前僅 single）
  file: ""                        # 音樂檔名（空字串自動偵測）

rhythm:
  snap_to_beat: true              # 切點對齊節拍
  tolerance_ms: 120               # 對齊容差（毫秒）

diversity:                        # 多樣性控制
  max_consecutive_same_source: 2  # 同來源連續上限
  max_consecutive_same_event: 3   # 同事件連續上限
  max_consecutive_same_role: 2    # 同角色連續上限
  min_event_coverage: 0.3         # 最低事件覆蓋率 (0-1)
  same_source_penalty: 0.15       # 重複來源扣分
  same_angle_penalty: 0.10        # 同角色扣分
  chapter_repeat_penalty: 0.20    # 章節內重複扣分

output:
  resolution: "1920x1080"         # 輸出解析度
  fps: 30                         # 幀率
  draft_bitrate_mbps: 12          # 草稿位元率（Mbps）
```

---

## 6. 輸入/輸出規格

### 6.1 輸入

素材放入任意目錄（遞迴掃描），支援格式：

| 類型 | 格式 |
|------|------|
| 影片 | `.mov`, `.mp4`, `.m4v` |
| 照片 | `.jpg`, `.jpeg`, `.heic`, `.png`, `.dng` |
| 音樂 | `.mp3`, `.wav`, `.m4a` |

### 6.2 輸出

```
output/
  draft/
    draft.mp4                  # 初剪影片（或 preview_720p.mp4）
  premiere/
    sequence.xml               # FCP7 XML（Premiere 匯入用）
  report/
    report.json                # 詳細分析報告
    selected_clips.csv         # 入選片段
    rejected_clips.csv         # 未選片段（含排除原因）
    story_notes.md             # 每章摘要 + 建議替換點
    user_profile.json          # 使用者偏好分析
  review/                      # roughcut review 輸出
    candidates.csv             # 全部候選鏡頭（按品質排序）
    events.csv                 # 事件級摘要（可標記 keep/drop）
    favorites_template.txt
    exclude_template.txt
  proxies/                     # DNG 轉檔暫存
  media_index.json             # 媒體索引
```

---

## 7. CLI 指令

### `roughcut run` — 執行完整流程

```bash
uv run roughcut run --input <dir> --profile <yaml> --output <dir> [options]
```

| 參數 | 說明 |
|------|------|
| `--input`, `-i` | 輸入素材目錄 |
| `--profile`, `-p` | YAML 設定檔路徑 |
| `--output`, `-o` | 輸出目錄 |
| `--seed`, `-s` | 隨機種子 |
| `--dry-run` | 僅產生報告與 XML，不渲染 |
| `--fast-preview` | 720p / 6Mbps 快速預覽 |
| `--favorites` | favorites.txt 路徑 |
| `--exclude` | exclude.txt 路徑 |
| `--max-workers`, `-w` | 平行工作數（預設 1） |
| `--verbose`, `-v` | 詳細日誌 |

### `roughcut review` — 審片模式

```bash
uv run roughcut review --input <dir> --profile <yaml> --output <dir>
```

只執行分析，輸出候選清單供人工審核。

### `roughcut version` — 顯示版本

---

## 8. 資料模型

核心 dataclass（`models.py`）：

| 類別 | 用途 |
|------|------|
| `MediaItem` | 單一媒體檔案（含 metadata、proxy 路徑） |
| `QualityScores` | 品質評分（sharpness, exposure, stability, face_score, motion_intensity；V2.2 新增 smile_score, composition, audio_energy, laughter_score，及 `emotion` 語意情緒屬性） |
| `SignalsConfig` | V2.2 語意訊號開關與權重（expression/source_audio/composition/camera_motion/color_continuity/dedup 及各自權重） |
| `Shot` | 鏡頭切分結果（含 event_id, shot_role, highlight_score, best window） |
| `MusicSection` | 音樂段落（label, start, end, avg_energy, repeat_index） |
| `BeatInfo` | 節拍資訊（beat_times, downbeat_times, tempo, sections, energy_curve） |
| `TimelineClip` | 時間軸上的片段（含轉場、chapter、score、selection_reason） |
| `Chapter` | 故事章節（name, ratio, description） |
| `ProjectConfig` | 完整專案設定（從 YAML 載入） |
| `ShotDetectConfig` | 鏡頭切分參數 |
| `DiversityConfig` | 多樣性控制參數 |

---

## 9. 錯誤碼

| 代碼 | 常數 | 說明 |
|------|------|------|
| 10 | `E_NO_USABLE_MEDIA` | 無可用素材 |
| 11 | `E_MUSIC_NOT_FOUND` | 指定音樂檔不存在 |
| 12 | `E_PROXY_FAIL` | DNG proxy 轉換失敗 |
| 20 | `E_RENDER_FAIL` | 渲染失敗 |
| 21 | `E_EXPORT_FAIL` | XML 匯出失敗 |

---

## 10. 版本歷史

### V1.0（初版 MVP）
- 基礎 pipeline：ingest → analyze → plan → edit → export → report
- Growth / Travel 雙模板
- 音樂節拍對齊
- FCP7 XML + draft.mp4 輸出

### V1.1（V2 任務）
- 事件分群（依拍攝時間）
- 鏡頭角色分類（establishing/action/reaction/detail）
- 情緒曲線（音樂段落偵測 + 能量曲線）
- 多樣性控制（同源/同事件/同角色懲罰）
- 使用流程升級（review 指令、favorites/exclude、fast-preview）
- Premiere 輸出升級（章節/事件標記、V2 備選軌）
- 70 項單元測試

### V2.0.0（V3 + V4 故事感升級）
- **V3 — 故事感升級**：
  - DNG proxy 多策略轉換、片長補齊（backfill）、ErrorCode
  - Event Ranking + Chapter 事件配額 + Event Arc
  - 高光偵測（highlight_score）
  - 敘事時間軸（chronological/energy_first/hybrid）
  - 剪輯語法引擎（景別衝突、動態緩衝、語意轉場）
  - 音樂段落穩定化 + section-level mapping
  - Review 事件級操作、story_notes.md
  - Premiere 三層標記（chapter/event/highlight）
- **V4 — 故事感優化**：
  - 鏡頭切分引擎（histogram + optical flow + luminance）
  - 高光窗口（best sub-segment within shot）
  - 使用者偏好學習（user_profile.json）
  - 全部 140 項測試通過

### V2.1.0（V5 故事節奏優化）
- **節奏與能量**：
  - Clip 時長連續跟隨能量曲線（energy_clip_duration）
  - 高光主動鎖定 Chorus（預留機制 + 跨 chorus 多樣性）
  - 章節情緒弧線分配（emotion-aware event allocation）
  - 音樂段落對齊加強（chorus highlight 權重提升、verse 動態懲罰）
- **電影感與轉場**：
  - 電影感首尾（FADE_FROM_BLACK / FADE_TO_BLACK）
  - 語意轉場（時間跳躍、情緒對比、媒體切換）
  - Grammar 2.0（擴大 swap 搜索、emotion gradient score）
- **穩定性與報表**：
  - P0 穩定性（smoke test、logger 抑制、tmp_path 清理）
  - P0 DNG 可用性追蹤（skipped_dng 報告）
  - P0 目標片長收斂（95% backfill + 105% trim）
  - 情緒曲線寫入報表（chapter_energy）
  - KPI 摘要（total_clips、duration、event_coverage、highlight_rate、beat_alignment_rate）
- **進階偵測**：
  - Chorus repeat 指紋偵測（chroma cosine similarity → repeat_index）
  - 全部 177 項測試通過

### V2.2.0（語意訊號升級）

從「純啟發式低階 CV 指標」提升為「輕量語意訊號層」，全部沿用既有 OpenCV/librosa/ffmpeg，**零新增相依套件**。

- **表情與情緒**：
  - 真實笑容偵測（`expression.py`，bundled smile cascade + 眼睛驗證），取代舊版「有臉即笑容」的假訊號
  - `QualityScores.emotion` 語意情緒屬性（smile/audio 驅動，並保留 face+motion fallback），貫穿高光、情緒弧線、語意轉場
- **素材音訊**：
  - `audio_energy.py` 分析每個鏡頭自身音軌（RMS 響度 + 笑聲/興奮啟發式），笑出聲的片段直接進高光
- **畫面感**：
  - 構圖評分（`composition.py`：三分法、頭部空間、水平線）
  - 相機運鏡分類（`camera_motion.py`：static/pan/tilt/zoom/shake）
  - 色溫與色彩連續性（`color.py`），相鄰色調突跳自動加溶接
  - 照片 Ken Burns 改為**主體導向**（推向偵測到的人臉/顯著區）
- **選片品質**：
  - 多幀聚合品質評分（不再只看中間幀，抓到「中途才轉頭笑」的瞬間）
  - 近似重複抑制（`dedup.py`，事件內 DCT pHash），連拍只留最佳一顆
  - 高光窗口改抓「最佳瞬間」（納入 smile），並修正每幀重建 cascade 的效能問題
- **設定與報表**：
  - `SignalsConfig`（`signals:` 區塊）可逐項開關與調權重
  - `candidates.csv` 新增 smile/composition/audio/camera_motion/color_temp/near_dup 欄位
- 全部 197 項測試通過（新增 `test_v22_signals.py`）

---

## 11. 測試

```bash
cd autocut
uv sync --group dev
uv run pytest tests/ -v      # 197 tests
uv run pytest tests/ -q      # 快速模式
```

測試檔案涵蓋：
- `test_models.py` — 資料模型
- `test_planner.py` — 規劃邏輯
- `test_events.py` — 事件分群
- `test_grammar.py` — 剪輯語法
- `test_highlight_window.py` — 高光窗口
- `test_music_mapping.py` — 音樂對應
- `test_shot_detect.py` — 鏡頭切分
- `test_shot_role.py` — 鏡頭角色
- `test_story_arc.py` — 故事弧線
- `test_timeline.py` — 時間軸
- `test_xml.py` — XML 匯出
- `test_preference_learning.py` — 偏好學習
- `test_comparison_v4.py` — V4 對比驗證
- `test_energy_duration.py` — 能量→時長映射
- `test_smoke.py` — Smoke 測試
- `test_duration_convergence.py` — 片長收斂
- `test_chorus_highlight.py` — Chorus 高光鎖定
- `test_emotion_arc.py` — 情緒弧線分配
- `test_cinematic_edges.py` — 電影感首尾
- `test_semantic_transitions.py` — 語意轉場
- `test_chorus_fingerprint.py` — Chorus 指紋 + KPI 報表
- `test_v22_signals.py` — 表情/構圖/運鏡/色彩/去重/情緒/設定（V2.2）

---

## 12. 開發指引

### 環境設置

```bash
cd autocut
uv sync --group dev
```

### 程式碼慣例

- 使用 `dataclass` 定義資料模型
- 模組化設計：每個子目錄有明確職責
- Pipeline 函式以 `run_pipeline()` 為進入點
- Config 從 YAML → `ProjectConfig.from_dict()`
- 所有 shot/clip 資料流經 `models.py` 定義的型別

### 新增模板

1. 在 `planner/` 建立新的 planner 檔案（參考 `growth.py` / `travel.py`）
2. 在 `config/` 新增對應 profile YAML
3. 在 `pipeline.py` 中註冊新 project_type
4. 新增對應測試

### 限制

- 不支援自動語音字幕
- 不支援多機位同步
- 不支援多首音樂接續（僅單首）
- DNG 轉檔需要 FFmpeg 支援
- 音樂段落偵測為啟發式方法
- 鏡頭角色分類基於品質指標推斷
- V2.2 語意訊號（表情、笑聲、構圖、運鏡）為**傳統 CV/DSP 啟發式**，非深度學習模型：
  - 笑容偵測用 Haar cascade，側臉/遮擋/低光下可能漏判
  - 笑聲偵測為音訊能量/調變啟發式，非訓練分類器
  - 無人物身分辨識（無法建立以特定人物為主的敘事線）
