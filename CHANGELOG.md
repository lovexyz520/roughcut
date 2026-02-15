# Changelog

## v1.0.0 (2026-02-15)

### Initial Release

Roughcut 自動剪輯系統 MVP，從手機素材自動產生影片初稿並輸出 Premiere 可匯入的 FCP7 XML。

### Features

#### 6-Stage Pipeline
- **Ingest**: 遞迴掃描媒體、metadata 提取（ffprobe）、MD5 去重、DNG proxy 轉換
- **Analyze**: 鏡頭切分（histogram-based）、品質評分（清晰度/曝光/穩定度/人臉/動態）、鏡頭角色分類（establishing/action/reaction/detail）
- **Event Segmentation**: 依拍攝時間自動分群事件（>30min gap 切分）
- **Beat Analysis**: librosa 音樂節拍偵測、段落分析（verse/chorus/bridge）、能量曲線
- **Plan**: 故事模板選片、章節配額、多樣性控制、節拍對齊
- **Export**: MP4 渲染（含 Ken Burns 照片動畫）、FCP7 XML、JSON/CSV 報告

#### Story Templates
- **growth**（小孩成長）: 開場(10%) → 學習(45%) → 高光(30%) → 收尾(15%)
- **travel**（家庭旅遊）: 出發(15%) → 景點探索(50%) → 互動(25%) → 結尾(10%)

#### CLI Commands
- `roughcut run` — 完整流程執行
- `roughcut review` — 僅分析產出候選清單
- `roughcut version` — 顯示版本

#### CLI Options
- `--seed` 可重現結果
- `--dry-run` 僅報告不渲染
- `--fast-preview` 720p 快速預覽
- `--favorites` / `--exclude` 人工干預選片
- `--max-workers` 平行分析

#### Premiere Integration
- FCP7 XML 匯出（V1 主軌 + V2 備選軌）
- 章節標記（藍色）與事件標記（綠色）
- 音樂軌自動放入 A1

#### Diversity Controls
- 同來源/同事件/同角色連續上限
- 事件覆蓋率下限
- 章節內重複懲罰

#### Reports
- `report.json` — 完整分析報告含節奏對齊統計
- `selected_clips.csv` — 入選片段詳情
- `rejected_clips.csv` — 未選片段與排除原因

### Supported Formats
- Video: `.mov`, `.mp4`, `.m4v`
- Photo: `.jpg`, `.jpeg`, `.heic`, `.png`, `.dng`
- Music: `.mp3`, `.wav`, `.m4a`

### Tech Stack
- Python 3.11+, FFmpeg, OpenCV, librosa, Typer, uv

### Known Limitations
- 不支援自動語音字幕
- 不支援多機位同步
- 僅支援單首音樂
- 鏡頭角色分類為規則式（無 AI 語意理解）
- 音樂段落偵測為啟發式方法
