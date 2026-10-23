# 第三方组件与许可

桌面版随包分发以下组件，完整许可文本见各项目主页；发布安装包前应把对应 LICENSE 一并放入 `licenses/`。

| 组件 | 许可 | 用途 |
|---|---|---|
| Qt for Python / PySide6 6.12 | LGPL-3.0（动态链接） | 桌面 UI |
| faster-whisper 1.2 | MIT | 词级时间戳 |
| CTranslate2 4.8 | MIT | Whisper 推理 |
| PyAV / FFmpeg | BSD-3-Clause / LGPL | 音频解码 |
| onnxruntime | MIT | Silero VAD |
| NumPy | BSD-3-Clause | 波形/数值 |
| Tokenizers | Apache-2.0 | 分词 |
| huggingface_hub | Apache-2.0 | 模型下载（仅开发期） |
| Silero VAD v6 | MIT | VAD 模型 |
| Whisper small.en 权重 | MIT（OpenAI Whisper，Systran 转换） | ASR 模型 |

Qt 采用 LGPL 动态链接方式分发；不要静态链接 Qt，否则需要重新评估许可。
