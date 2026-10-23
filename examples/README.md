# Examples

这里的文本和词级时间戳都是**合成数据**，不是 BBC 内容：

- `sample_transcript.txt`：15 句英文对谈，带 `**Alex**` / `**Sam**` 说话人。
- `sample_asr_words.json`：同一段文本的假词级时间戳（114 个词，约 41 秒）。

用途：

1. 跑纯逻辑/对齐，不需要 Whisper 模型：

```bash
python audio_align.py \
  --audio your_audio.mp3 \
  --transcript examples/sample_transcript.txt \
  --asr-json examples/sample_asr_words.json \
  --out /tmp/sample-align \
  --title "Sample"
```

`--audio` 需要一个真实存在的音频文件（脚本要读时长）；时间戳按 sample 的 45 秒生成，所以预览里的播放位置只对 sample 音频有意义。拿它验证 JSON 结构、校对页交互、导出流程即可。

2. 跑单测：

```bash
python tests/test_audio_align.py -v
```

真实使用时，把 `--asr-json` 去掉，脚本会用 `faster-whisper` 重新转写你的音频。
