# Venus Reader (venus-reflex)

一個基於 Reflex (Python) 開發的全端本地娛樂平台，支援漫畫與小說閱讀、自定義排版與多設備同步。

## 🚀 快速啟動

### 1. 環境準備
確保您已安裝 `conda` 並且擁有 `toby` 環境。本專案使用 `uv` 進行依賴管理。

```bash
conda activate toby
```

### 2. 安裝依賴
在專案根目錄下執行：
```bash
uv sync
```

### 3. 資料準備
- 將原始漫畫檔（.epub, .pdf 等）放入 `raw/漫畫/`。
- 使用 `script/` 目錄下的轉檔腳本將檔案上架至 `bank/`。
  ```bash
  uv run python script/importer_doraemon.py
  ```

### 4. 啟動服務
執行以下指令以啟動服務，並允許區域網路內的手機與電腦連線：

```bash
uv run reflex run --loglevel info --frontend-port 3001 --backend-port 8003 --backend-host 0.0.0.0
```

- **網頁位址**: `http://localhost:3001`
- **手機連線**: 請連至 `http://[您的電腦IP]:3001`

## 🛠 功能特色
- **VBF 格式**: 自定義 Venus Book Format，支援精準的圖文疊加。
- **自適應翻頁**: 隱形控制層設計，完美適應手機、iPad 與電腦的點擊翻頁。
- **背景音樂**: 內建 BGM 播放器，支援音量調節（預設關閉）。
- **修改建議**: 閱讀時可隨時提交修正建議，並存入本地 JSON。

## 📂 目錄結構
- `venus_reflex/`: 網頁前端與後端邏輯。
- `bank/`: 符合 VBF 規範的內容資料庫（不進入 Git）。
- `raw/`: 原始素材目錄（不進入 Git）。
- `script/`: 各種上架與管理腳本。
- `assets/`: 靜態資源（BGM, Favicon 等）。
