# Roughcut V2.0.0 — 自動剪輯系統

從手機素材資料夾自動產生影片初稿（rough cut），並輸出 Premiere 可匯入的 FCP7 XML。

## 功能特色

- **自動選片與排程**：依品質評分、事件分群、鏡頭角色自動選片
- **故事感剪輯**：事件導向規劃、高光偵測、剪輯語法引擎
- **音樂節拍對齊**：段落偵測（intro/verse/chorus）、能量曲線、beat-snap 切點
- **雙模板**：Growth（小孩成長）/ Travel（家庭旅遊）
- **Premiere 整合**：FCP7 XML、V1+V2 備選軌、三層標記（章節/事件/高光）
- **審片工作流**：review 指令 → favorites/exclude → 快速預覽 → 正式渲染
- **使用者偏好學習**：從 favorites/exclude 分析偏好，輸出 user_profile.json

## 安裝

需要先安裝 [uv](https://docs.astral.sh/uv/) 和 [FFmpeg](https://ffmpeg.org/)。

```bash
cd autocut
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
| `--fast-preview` | 以 720p / 6Mbps 快速預覽 |
| `--favorites` | 指定 favorites.txt，強制優先選用 |
| `--exclude` | 指定 exclude.txt，強制排除 |
| `--max-workers`, `-w` | 分析階段平行工作數（預設 1） |
| `--verbose`, `-v` | 顯示詳細日誌 |

### `roughcut review` — 審片模式

```bash
uv run roughcut review --input ../input --profile config/profile_growth.yaml --output ../output
```

只執行分析，輸出候選清單與事件摘要供人工審核。

### `roughcut version` — 顯示版本

## 推薦工作流

### 快速出片

```bash
uv run roughcut run -i ../input -p config/profile_growth.yaml -o ../output --fast-preview
```

### 精修工作流（推薦）

```bash
# Step 1: 審片
uv run roughcut review -i ../input -p config/profile_growth.yaml -o ../output

# Step 2: 編輯 favorites/exclude
#   查看 output/review/candidates.csv 與 events.csv
#   編輯 favorites.txt / exclude.txt（支援檔名與 event:N 語法）

# Step 3: 快速預覽
uv run roughcut run -i ../input -p config/profile_growth.yaml -o ../output \
    --favorites output/review/favorites.txt \
    --exclude output/review/exclude.txt \
    --fast-preview

# Step 4: 正式渲染
uv run roughcut run -i ../input -p config/profile_growth.yaml -o ../output \
    --favorites output/review/favorites.txt \
    --exclude output/review/exclude.txt

# Step 5: 匯入 Premiere 精修
#   File > Import > output/premiere/sequence.xml
```

### favorites/exclude 語法

```text
# 支援 event_id（以 event: 開頭）
event:0  (5 shots, 10:03 - 10:28)
event:2  (3 shots, 03:28 - 03:30)

# 支援檔名
IMG_0827.MOV
IMG_3858.MOV
```

## 輸出

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

## 設定檔說明

設定檔為 YAML 格式，兩個主要 profile：

- `config/profile_growth.yaml` — 小孩成長影片
- `config/profile_travel.yaml` — 家庭旅遊影片

完整欄位說明請參閱 [CLAUDE.md](CLAUDE.md#5-設定檔格式)。

## 模板

### Growth（小孩成長）

| 章節 | 比例 | 偏好鏡頭 |
|------|------|----------|
| opening | 10% | 穩定、有臉、曝光好 |
| learning | 45% | 穩定、清晰、適度動態 |
| highlights | 30% | 高臉部分數、動態 |
| closing | 15% | 穩定、安靜、照片加分 |

### Travel（家庭旅遊）

| 章節 | 比例 | 偏好鏡頭 |
|------|------|----------|
| departure | 15% | 穩定、動態、有臉 |
| exploration | 50% | 清晰、動態、寬景 |
| interaction | 25% | 高臉部分數、穩定 |
| ending | 10% | 曝光好、穩定、照片 |

## Premiere 匯入注意事項

1. **匯入方式**：File → Import → 選擇 `sequence.xml`
2. **素材路徑**：XML 使用絕對路徑，素材不可搬移
3. **V1 軌**：自動選出的主時間軸
4. **V2 軌（備選）**：每段對應的備選鏡頭，預設停用
5. **標記**：藍色 = 章節起點、綠色 = 事件起點
6. **音樂軌**：自動放在 A1 軌

## 支援格式

| 類型 | 格式 |
|------|------|
| 影片 | `.mov`, `.mp4`, `.m4v` |
| 照片 | `.jpg`, `.jpeg`, `.heic`, `.png`, `.dng` |
| 音樂 | `.mp3`, `.wav`, `.m4a` |

## 測試

```bash
cd autocut
uv sync --group dev
uv run pytest tests/ -v    # 140 tests
```

## 限制

- 不支援自動語音字幕
- 不支援多機位同步
- 不支援多首音樂接續（僅單首）
- DNG 轉檔需要 FFmpeg 支援
- 音樂段落偵測為啟發式方法
- 鏡頭角色分類基於品質指標推斷，無 AI 語意理解

## 詳細規格

完整技術規格、模組結構、資料模型、版本歷史等請參閱 [CLAUDE.md](CLAUDE.md)。

## V2.0.0 變更摘要

整合 V3（故事感升級）與 V4（故事感優化）：

- **鏡頭切分引擎**：histogram + optical flow + luminance 多指標切分
- **事件導向規劃**：Event Ranking、Chapter 事件配額、Event Arc
- **高光偵測**：highlight_score + 高光窗口（最佳子片段）
- **剪輯語法引擎**：景別衝突、動態緩衝、語意轉場
- **音樂敘事對齊**：段落穩定化、section-level mapping
- **使用者偏好學習**：從 favorites/exclude 分析偏好
- **Premiere 三層標記**：chapter / event / highlight
- **DNG 多策略轉換**、片長補齊（backfill）、ErrorCode
- **140 項測試**全部通過
