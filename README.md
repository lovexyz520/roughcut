# Roughcut - 自動剪輯系統

從手機素材資料夾自動產生影片初稿（rough cut），並輸出 Premiere 可匯入的 FCP7 XML。

## 安裝

需要先安裝 [uv](https://docs.astral.sh/uv/) 和 [FFmpeg](https://ffmpeg.org/)。

```bash
# 安裝依賴
cd roughcut
uv sync

# 確認 ffmpeg 可用
ffmpeg -version
```

## 指令總覽

### `roughcut run` — 執行完整流程

```bash
uv run roughcut run --input ../input --profile config/profile_growth.yaml --output ../output
```

| 參數 | 說明 |
|------|------|
| `--input`, `-i` | 輸入素材目錄（包含影片、照片、音樂） |
| `--profile`, `-p` | YAML 設定檔路徑 |
| `--output`, `-o` | 輸出目錄 |
| `--seed`, `-s` | 隨機種子（可重現結果） |
| `--dry-run` | 僅產生報告與 XML，不渲染影片 |
| `--fast-preview` | 以 720p / 6Mbps 快速預覽（約快 3-5x） |
| `--favorites` | 指定 `favorites.txt` 路徑，強制優先選用列出的檔案 |
| `--exclude` | 指定 `exclude.txt` 路徑，強制排除列出的檔案 |
| `--max-workers`, `-w` | 分析階段平行工作數（預設 1） |
| `--verbose`, `-v` | 顯示詳細日誌 |

### `roughcut review` — 先審片再決定

```bash
uv run roughcut review --input ../input --profile config/profile_growth.yaml --output ../output
```

只執行分析，輸出候選清單供人工審核，不進行規劃或渲染。

| 參數 | 說明 |
|------|------|
| `--input`, `-i` | 輸入素材目錄 |
| `--profile`, `-p` | YAML 設定檔路徑 |
| `--output`, `-o` | 輸出目錄 |
| `--max-workers`, `-w` | 平行工作數 |
| `--verbose`, `-v` | 顯示詳細日誌 |

### `roughcut version` — 顯示版本

```bash
uv run roughcut version
```

## 推薦工作流

### 快速出片

```bash
uv run roughcut run -i ../input -p config/profile_growth.yaml -o ../output --fast-preview
```

### 精修工作流（推薦）

```bash
# Step 1: 審片 — 產出候選清單
uv run roughcut review -i ../input -p config/profile_growth.yaml -o ../output

# Step 2: 編輯 favorites.txt / exclude.txt
#   查看 output/review/candidates.csv（按品質排序）
#   複製 favorites_template.txt → favorites.txt，取消註解要優先的檔名
#   複製 exclude_template.txt → exclude.txt，取消註解要排除的檔名

# Step 3: 快速預覽
uv run roughcut run -i ../input -p config/profile_growth.yaml -o ../output \
    --favorites output/review/favorites.txt \
    --exclude output/review/exclude.txt \
    --fast-preview

# Step 4: 確認後正式渲染
uv run roughcut run -i ../input -p config/profile_growth.yaml -o ../output \
    --favorites output/review/favorites.txt \
    --exclude output/review/exclude.txt

# Step 5: 匯入 Premiere 精修
#   File > Import > output/premiere/sequence.xml
```

## 輸出

```
output/
  draft/
    draft.mp4             # 初剪影片（或 preview_720p.mp4）
  premiere/
    sequence.xml          # FCP7 XML（Premiere 匯入用）
  report/
    report.json           # 詳細分析報告（含節奏對齊統計）
    selected_clips.csv    # 入選片段
    rejected_clips.csv    # 未選片段（含排除原因）
  review/                 # roughcut review 輸出
    candidates.csv        # 全部候選鏡頭（按品質排序）
    favorites_template.txt
    exclude_template.txt
  proxies/                # DNG 轉檔暫存
  media_index.json        # 媒體索引
```

## 設定檔說明

設定檔為 YAML 格式，完整欄位如下：

```yaml
project_type: growth          # growth 或 travel
target_duration_sec: 240      # 目標成片時長（秒）
video_photo_ratio: [7, 3]     # 影片:照片時長比例
seed: null                    # 隨機種子（null 為隨機）

clip_duration_sec:
  min: 1.5                    # 單片最短秒數
  max: 6.0                    # 單片最長秒數（高能量段自動縮短）

max_same_event_streak_sec: 20 # 同事件連續最長秒數

music:
  mode: single                # 音樂模式（目前僅支援 single）
  file: ""                    # 音樂檔名（空字串自動偵測）

rhythm:
  snap_to_beat: true          # 切點對齊節拍
  tolerance_ms: 120           # 對齊容差（毫秒）

output:
  resolution: "1920x1080"     # 輸出解析度
  fps: 30                     # 幀率
  draft_bitrate_mbps: 12      # 草稿位元率（Mbps）

diversity:                    # 多樣性控制
  max_consecutive_same_source: 2    # 同來源連續上限
  max_consecutive_same_event: 3     # 同事件連續上限
  max_consecutive_same_role: 2      # 同角色連續上限
  min_event_coverage: 0.3           # 最低事件覆蓋率 (0-1)
  same_source_penalty: 0.15         # 重複來源扣分
  same_angle_penalty: 0.10          # 同角色扣分
  chapter_repeat_penalty: 0.20      # 章節內重複扣分
```

## 支援格式

- 影片：`.mov`, `.mp4`, `.m4v`
- 照片：`.jpg`, `.jpeg`, `.heic`, `.png`, `.dng`
- 音樂：`.mp3`, `.wav`, `.m4a`

## 模板

### growth（小孩成長）

| 章節 | 比例 | 內容 | 偏好鏡頭 |
|------|------|------|----------|
| 開場 opening | 10% | 暖場、日期感 | 穩定、有臉、曝光好 |
| 學習 learning | 45% | 上課、練習、專注 | 穩定、清晰、適度動態 |
| 高光 highlights | 30% | 笑容、成果、互動 | 高臉部分數、動態 |
| 收尾 closing | 15% | 結束動作、照片 | 穩定、安靜、照片加分 |

### travel（家庭旅遊）

| 章節 | 比例 | 內容 | 偏好鏡頭 |
|------|------|------|----------|
| 出發 departure | 15% | 交通、準備 | 穩定、動態、有臉 |
| 景點 exploration | 50% | 地標、活動 | 清晰、動態、寬景 |
| 互動 interaction | 25% | 合照、玩樂 | 高臉部分數、穩定 |
| 結尾 ending | 10% | 夕陽、返程 | 曝光好、穩定、照片 |

## Premiere 匯入注意事項

1. **匯入方式**：File → Import → 選擇 `sequence.xml`
2. **素材路徑**：XML 使用絕對路徑，素材不可搬移
3. **V1 軌**：自動選出的主時間軸
4. **V2 軌（備選）**：每段對應的備選鏡頭，預設停用（Disable），需要替換時在 V2 啟用即可
5. **標記**：
   - 藍色標記 = 章節起點
   - 綠色標記 = 事件起點
6. **音樂軌**：如有指定音樂，會自動放在 A1 軌

## 測試

```bash
# 安裝開發依賴
uv sync --group dev

# 執行測試
uv run pytest tests/ -v
```

## 限制

- 不支援自動語音字幕
- 不支援多機位同步
- 不支援多首音樂接續（僅單首）
- DNG 轉檔需要 FFmpeg 支援
- 音樂段落偵測為啟發式方法，複雜結構可能不精確
- 鏡頭角色分類基於品質指標推斷，無 AI 語意理解

## V2 變更摘要

| 任務 | 內容 | 關鍵檔案 |
|------|------|----------|
| 0. Baseline 修正 | ratio 生效、平行分析、bitrate 套用、音樂錯誤處理 | `pipeline.py`, `draft.py`, `models.py` |
| 1. 事件分群 | 依拍攝時間分群、event_id、報告 event_summary | `planner/events.py`, `models.py` |
| 2. 鏡頭語法 | 4 種角色分類、章節配額、角色覆蓋統計 | `analyze/shot_role.py`, `planner/base.py` |
| 3. 情緒曲線 | 音樂段落偵測、能量曲線、section_fit 評分 | `analyze/beat.py`, `planner/base.py` |
| 4. 多樣性控制 | 同源/同事件/同角色懲罰、事件覆蓋率下限 | `planner/base.py`, `models.py` |
| 5. 使用流程 | review 指令、favorites/exclude、fast-preview | `cli.py`, `pipeline.py` |
| 6. Premiere 輸出 | 章節/事件標記、V2 備選軌、排除原因 | `export/premiere_xml.py`, `report/writer.py` |
| 7. 測試與交付 | 70 項單元測試、交付文件 | `tests/` |

## V3 變更摘要（故事感升級）

核心升級：從「高分片段排序器」→「事件與情緒驅動的故事剪輯器」

| 任務 | 內容 | 關鍵檔案 |
|------|------|----------|
| 0. 必修修復 | DNG proxy 多策略轉換、片長補齊(backfill)、錯誤碼(ErrorCode) | `constants.py`, `scanner.py`, `pipeline.py`, `draft.py`, `base.py` |
| 1. 事件導向規劃 | Event Ranking、Chapter 配事件配額、Event Arc (establishing→action→reaction→detail) | `planner/events.py`, `planner/base.py` |
| 2. 高光偵測 | highlight_score (笑容/互動/注視/動作)、chorus 段加分 | `analyze/highlights.py`, `models.py`, `planner/base.py` |
| 3. 敘事時間軸 | 時間前進性(growth)、行程節點(travel) | `planner/growth.py`, `planner/travel.py` |
| 4. 剪輯語法引擎 | 禁止連續同景別、高動態插入緩衝、章節語意化轉場 | `planner/grammar.py` |
| 5. 音樂敘事對齊 | section 穩定化、section-level mapping (intro→establishing, chorus→highlight) | `analyze/beat.py`, `planner/base.py` |
| 6. 人在迴圈升級 | review 事件級操作、favorites/exclude 支援 event_id、story_notes.md | `pipeline.py`, `report/writer.py` |
| 7. Premiere 交接 | 三層標記(chapter/event/highlight)、marker 含 why_selected | `export/premiere_xml.py` |

### V3 新增輸出

```
output/
  report/
    story_notes.md          # 每章摘要 + 建議替換點
  review/
    events.csv              # 事件級摘要（可標記 keep/drop）
```

### favorites/exclude 新語法

```text
# 支援 event_id（以 event: 開頭）
event:0  (5 shots, 10:03 - 10:28)
event:2  (3 shots, 03:28 - 03:30)

# 也支援檔名
IMG_0827.MOV
IMG_3858.MOV
```

## 後續規劃

- M2：加入旅遊模板 GPS/地點連續性規則
- M3：多首音樂、批次任務、UI
