# 桌面版（Windows exe）

目标：用户只选「音频 + 文稿 + 输出目录」，双击 exe 就能跑完对齐并校对。Python、ffmpeg、模型、Qt 全部随安装包提供，不需要联网。

## 现状

- UI：PySide6 6.12（Qt Widgets），单窗口，四个页面：首页 / 运行中 / 完成 / 校对。
- 推理：复用 `audio_align.py` 的解析、归一化、对齐；`desktop/pipeline.py` 负责写 `episode.json`、`preview.html`、`asr_words.json` 和波形峰值。
- 模型：`models/small.en`（Faster-Whisper CTranslate2 格式，约 484MB），随安装包附带。
- 打包：PyInstaller **onedir**，不用 onefile（模型大，onefile 每次启动解压到 temp，启动 10–30 秒且容易被杀软误报）。
- 体积：`dist/AudioAlign` 约 **826MB**，绿色 zip 约 **564MB**（small.en 484MB + Qt/推理运行时）。
- 安装器：`installer/AudioAlign.iss` 已就绪（Inno Setup 6，按用户安装）；当前机器下载源被网络阻断，尚未编译出 `Setup.exe`。绿色 zip 可直接解压运行。

## 源码结构

```text
desktop/
  app.py        # QApplication、顶栏、页面切换、任务生命周期
  pages.py      # HomePage / RunPage / DonePage / ReviewPage
  widgets.py    # 拖放区、文件行、波形 QWidget
  worker.py     # QThread + 信号；把 pipeline 的回调转给 UI
  pipeline.py   # 对齐管线、写文件、计算 peaks
  theme.py      # QSS 与配色
run_desktop.py  # 入口
tools/
  build_desktop.py  # PyInstaller 构建 + 可选 zip
```

## 开发运行

```bash
# 1) 基础依赖（与 CLI 相同）
.venv\Scripts\activate
pip install -r requirements.txt

# 2) Qt 依赖
pip install -r requirements-desktop.txt

# 3) 模型放到 models/small.en
python - <<'PY'
import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_XET"] = "1"
from huggingface_hub import snapshot_download
snapshot_download("Systran/faster-whisper-small.en", local_dir="models/small.en")
PY

# 4) 启动
python run_desktop.py
```

模型必须包含：`config.json`、`model.bin`、`tokenizer.json`、`vocabulary.txt`（`preprocessor_config.json` 可选）。

## 构建

```bash
python tools\build_desktop.py --zip
```

产物：

```text
dist/AudioAlign/AudioAlign.exe      # 双击运行
dist/AudioAlign/_internal/…         # Python/Qt/模型
dist/AudioAlign-win64.zip           # 绿色版
```

构建脚本已经带上：

- `--collect-all ctranslate2/av/onnxruntime/faster_whisper/tokenizers`
- `--copy-metadata faster-whisper`
- 排除 QtWebEngine / QtQml / QtQuick3D / QtCharts 等未使用模块
- `models/` 打进 `_internal/models/`；`find_model_path()` 会先看 exe 目录，再看 `sys._MEIPASS`

首次构建建议先 `--no-model` 验证 Qt/推理依赖，再打全量包。

## 安装器

Inno Setup 6，按用户安装（不需要管理员）：

```ini
DefaultDirName={localappdata}\Programs\AudioAlign
PrivilegesRequired=lowest
```

把 `dist/AudioAlign/*` 全部收进去，开始菜单快捷方式指向 `AudioAlign.exe`；卸载时保留用户输出目录不动。

## v1 范围与已知限制

- 文稿只支持 **txt / md**；PDF 需要先自己转文本（排版提取会影响说话人识别）。
- 波形只能看/点，不能拖边界；边界用 `±0.1s`、`重打点` 或数字输入。
- 没有撤销、没有自动保存；改动只在「导出 JSON」时写回，同时重写 `preview.html`。
- 单句播放依赖 QtMultimedia/FFmpeg；极短句的停止精度约 10–20ms。
- 模型是 English-only（`small.en`）；其它语言要换多语种模型，并调整分句/归一化。
- exe 未签名，Windows SmartScreen 首次会提示「更多信息 → 仍要运行」。

## 下一步

1. 全量构建 + 在没有 Python/Node 的干净 Windows VM 上跑一遍。
2. Inno Setup 安装包；图标/版本信息/许可文件。
3. 校对页 v2：波形拖拽、缩放、撤销、草稿恢复。
4. PDF（pdfminer.six，MIT）与 DOCX（python-docx）支持。
