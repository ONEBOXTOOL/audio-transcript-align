# 实现过程与复盘

这篇文档记录 `audio_align.py` 是怎么从「一个想法」跑到「真实 BBC 一期 76 句、0 待校对」的：每一层做什么、为什么这么做、真实数据打脸了哪些地方。

## 1. 目标与约束

目标不是「转写」，而是「给已有文稿配时间轴」：

```text
mp3 + transcript.txt  →  [{text, speaker, start, end, confidence}, ...]
```

约束决定了设计：

- **文稿不是逐字稿**。BBC 6 Minute English 明确写 `not a word-for-word transcript`；音频里的 filler、口误、重复，文稿里没有。因此只做句级，不做词级。
- **不能要求用户手打时间戳**。一期 6 分钟约 76 句，手打不可行。
- **本地优先**。音频不上传；ASR 用本地 `faster-whisper`；校对页是本地 `file://`。
- **必须能校对**。自动对齐一定会有错，交付物要能让用户在 1–2 分钟内把错的几句修掉，而不是重跑整条管线。

## 2. 数据模型

```python
@dataclass
class Word:      # ASR 词级时间戳
    word: str
    start: float
    end: float

@dataclass
class Seed:      # 文稿里的一句（尚未有时间）
    speaker: str
    text: str
```

对齐后的句子是普通 `dict`：

```json
{"i": 0, "speaker": "Alex", "text": "Hi Sam.",
 "start": 0.0, "end": 0.81, "confidence": 1.0, "needs_review": false}
```

没有引入数据库、没有 pydantic；JSON 是唯一契约。

## 3. 八个阶段

### 3.1 文稿清洗：先找到正文

BBC 页面/PDF 在 `TRANSCRIPT` 之前还有标题、`This week's question`、Vocabulary；照单全收会把词表当正文。

规则：

- 找**最后一次** `TRANSCRIPT`（页面顶部可能还有同名导航链接），从它之后开始。
- 跳过 `Note: This is not a word-for-word transcript.`、`BBC LEARNING ENGLISH`、节目名。
- 跳过页脚：`©British Broadcasting Corporation`、`bbclearningenglish.com`、`Page N of M`、`|...|` 表格行。
- 在 `VOCABULARY` / `VOCAB` 处**停止**（不是跳过，是 break）。
- 第一个说话人之前的残余文字，在 `set_speaker()` 里清掉，不生成 0 置信度句子。

**踩过的坑**：最初把 `^6 Minute English` 当页脚，结果把正文 `6 Minute English, we'll be talking about…` 整行删了，句子少了 18 个词。页脚规则只能按 ©、域名、页码判，不能按节目名。

### 3.2 说话人

支持四种写法：

| 写法 | 来源 |
|---|---|
| `**Neil**` | 网页复制 |
| `Neil:` | 网页/字幕 |
| 单独一行 `Neil` | PDF `pdftotext -layout` |
| `### Alex` | PDF 提取器/Markdown |

裸名字行只在「上一行是句末/空行/标题」且「下一行是文本」时认；否则会把独词句误判成说话人。

**踩过的坑**：

- 用 `pdftotext` **plain** 模式，说话人和正文并成 `Alex Hi Sam.`，四种规则全失效；必须 `-layout`。
- 网页复制可能把 `**Alex**` 拆成两行：`**Alex` + `** Hello...`；只认单个短名字，避免把 `** Hello, this is...` 当说话人。

### 3.3 分句

按 `.` `!` `?` + 空白切，跳过：

- 缩写：`Mr. / Mrs. / Dr. / Prof. / U.S. / U.K. / e.g. / i.e. / etc. / vs.`
- 小数点：`3.14`
- 句末引号/括号：`He said "Stop."` 整句

**省略号碎片合并**：`It's...`（≤3 词、以 `...` 结尾）并进下一句（同说话人），否则会得到 0 置信度的空句。实测把 77 句降到 76 句，并消掉唯一的待校对项。

### 3.4 归一化

ASR 和文稿的「同一个词」经常长得不一样。`expand_token()` 做这些：

| 输入 | 输出 | 为什么 |
|---|---|---|
| `don't` | `do`, `not` | ASR 可能展开 |
| `thirty` / `30` | `30` | 数字统一 |
| `long-term` | `long`, `term` | 连字符 |
| `okay` | `ok` | 文稿写 `OK.` |
| `tonnes` | `tons` | 英式/美式 |
| `jewellery` / `colour` / `programme` | 美式 | BBC 英式 vs ASR |
| `50,000` | `50`, `000` | ASR 常切成两个词 |
| `bbclearningenglish.com` | `bbclearningenglish`, `com` | 域名 |

不做这些，`OK.` 会一片 0 置信度、数字列表只能对 1/3。

### 3.5 ASR

`faster-whisper`：

```python
model.transcribe(
    audio,
    language="en",
    beam_size=5,
    word_timestamps=True,
    vad_filter=True,
    condition_on_previous_text=False,
)
```

- `word_timestamps=True` 是硬要求；没有词级时间戳就无法做句内边界。
- `vad_filter=True` 去掉长静音。
- `condition_on_previous_text=False` 降低重复/幻觉传播。
- 依赖锁 `av<19`：PyAV 19 移除了 `metadata_errors`，faster-whisper 1.2.1 会直接 `TypeError`。
- 脚本默认 `HF_HUB_DISABLE_XET=1`：部分网络在 Xet 上卡 0 字节，普通 HTTP 反而能下。

### 3.6 对齐：SequenceMatcher + 聚簇 + 补边

1. ASR 和文稿各归一化成 token 序列（ASR token 保留指向原始词的索引）。
2. `SequenceMatcher(ASR, transcript, autojunk=False)`，得到 `transcript token → ASR token` 的匹配表。
3. 对每一句，把匹配对按 **ASR 原始词序号**聚簇；间隔 ≥4 个词就切开。
4. 取词数最多的簇；平票取靠后的。
5. 簇没覆盖句首/句尾时，若相邻 ASR 词能一一对上，补回来。
6. `confidence = 命中的 token 数 / 该句 token 数`。

为什么要聚簇：句首重复的 `That's` 会被匹配到上一句的 `That's`，整句起点提前 1.8 秒。聚簇 + 补边把它救回，句子边界回到 49.47–51.29。

### 3.7 插值

完全没匹配上的句子（文稿有、音频没有，或 ASR 漏了整段）：

- 找前一个已知 `end` 和后一个已知 `start`；
- 按字符数分配这段 gap；
- 标 `needs_review`。

实测 `base.en` 把一段 6 秒的过渡句吞成一个 `from`，这句话只能插值，置信度 0.44；换 `small.en` 后正常。

### 3.8 收口：padding 必须用原始边界

先给每句留 0.15s 句首、0.25s 句尾，但不能吃掉邻居的词。

错误做法：

```text
先 padding，再和邻居的 padded start 比较
→ 下一句的 start 被提前了 0.15s
→ 上一句的 end 被压到下一句 padded start
→ "Is it:" 只剩 "Is"
```

正确做法：

```python
raw = [(s["start"], s["end"]) for s in sentences]
start = max(0, raw[i][0] - 0.15)
end   = min(duration, raw[i][1] + 0.25)
if i > 0:            start = max(start, raw[i-1][1])
if i < len-1:        end   = min(end,   raw[i+1][0])
```

邻居用**未加 padding 的原始词边界**。实测 `Is it:` 从 0.27 秒恢复到 0.55 秒，`value.` 的尾音也不再被切。

## 4. 校对页

### 4.1 结构与数据流

`render_preview()` 把 `PREVIEW_TEMPLATE`（约 330 行内嵌 HTML/CSS/JS）里的三个占位符替换成最终单文件：

| 占位符 | 内容 | 注意 |
|---|---|---|
| `__TITLE__` | 节目标题 | `html.escape` |
| `__AUDIO__` | 音频 URL | 同盘相对路径；跨盘 `file:///` |
| `__DATA__` | 完整 `episode.json` | JSON 内联，`</` 转义为 `<\/` |

数据流很短：`episode.json → 内联 data → 页面交互直接改内存里的 data.sentences → Blob 下载`。没有请求、没有服务端、音频不内嵌。

### 4.2 交互边界

现在能做：

- 点句播放，`currentTime` 定位起点。
- 短句（<0.6s）靠 `timeupdate` 会过冲 0.1–0.2 秒；播放时用 `requestAnimationFrame` 每帧检查 `currentTime >= end - 0.01` 再暂停。
- 时间显示到 0.01 秒，否则 0.1 秒的微调屏幕上看不出变化。
- 选中行起点/终点 ±0.1、重打点、删除本句、整体偏移。
- 低置信度行标黄，可只看低置信度。
- 导出 JSON 覆盖原文件。

做不到（也是三种 UI 方案要解决的）：

- 看不到波形，判断「切首词/切尾词」只能靠听。
- 没有搜索、没有跳句；76 句只能滚。
- 改动只在内存，刷新即丢；没有撤销。
- 没有词级对照：`asr_words.json` 在旁边，但页面不读。
- 长音频只能整段载入，没有按句懒加载。

### 4.3 扩展点

- **波形**：生成时用 `av` 解码，10ms RMS 聚合成 2400 点（全片）和 12000 点（放大/单句），约 160KB JSON，内联即可。
- **词级对照**：`asr_words.json` 已有词和起止；生产版在 `align()` 里记录 token→word 索引，页面就能显示「本句命中了哪些词」。
- **持久化**：`localStorage` 存草稿；导出仍以 `episode.json` 为准。不建议第一版直接写文件。
- **UI 演进**：三个方向的真实数据原型、成本对比和架构建议见 **[ui/README.md](ui/README.md)**。

## 5. 真实数据复盘

### 5.1 素材

- 6:28.82 BBC 6 Minute English，48kHz 立体声，7.8MB。
- 文稿 PDF 用 `pdftotext -layout` 提取。
- 音频和文稿不进仓库（版权）。

### 5.2 结果

| 模型 | 句子 | 平均置信度 | 待校对 | 备注 |
|---|---|---|---|---|
| `base.en` | 76 | 0.979 | 1 | 6 秒过渡句被吞成 `from` |
| `small.en` | 76 | 0.993 | 0 | 0 处切首词/切末词 |

自动检查：

- 每句 `start/end` 内至少有一个 ASR 词；
- `start` 不晚于首词 `start + 0.06`；
- `end` 不早于末词 `end - 0.06`；
- 76 句全部通过，只有 1 个 ASR 词落在句间（过渡碎片）。

### 5.3 七个真实问题

| # | 症状 | 根因 | 修复 |
|---|---|---|---|
| 1 | 说话人全丢 | `pdftotext` plain 把名字和正文并成一行 | 改用 `-layout`，并在 README 写明 |
| 2 | 说话人变成正文 | PDF 提取器输出 `### Alex` | 标题分支认 `### Name`，`### VOCABULARY` 停止 |
| 3 | 正文少 18 个词 | `^6 Minute English` 被当页脚 | 页脚只按 ©、域名、页码判 |
| 4 | 开头多出 0 置信度句 | 标题/说明在第一个说话人之前 | `set_speaker()` 清 buffer；`VOCABULARY` 处 break |
| 5 | `OK.` 一片 0 置信度、数字列表只对 1/3 | `okay/tonnes/50,000/域名` 没归一 | 同义词 + 千分位拆分 + 域名拆分 |
| 6 | `Is it:` 只剩 `Is` | padding 后和 padded 邻居 clamp | 用原始词边界做邻居上限/下限 |
| 7 | 0.27 秒短句拖到下一句 | `timeupdate` 只有 4Hz | `requestAnimationFrame` 每帧检查 |

### 5.4 为什么 base 和 small 差这么多

`base.en` 在 163–170 秒把一句 6 秒的话吞成一个长词 `from`，时间戳本身错了，不是对齐算法能修的。`small.en` 在同一段正常输出。

结论：**base 适合先跑通，small 才是正式用**。如果 `base` 的结果里出现「超长词」（duration > 3s 的单词）或低置信度集中在长句，直接换 small。

## 6. 设计取舍

### 句级 vs 词级

非逐字稿做词级一定漂。句级边界落在停顿上，人耳可接受；词级需要逐词时间戳和文稿逐词对应，BBC 文稿做不到。听写只判 1–2 个目标词，正好绕开 filler。

### 本地 ASR vs 云 API

本地：隐私、离线、无按次成本；代价是模型下载和 CPU 时间。
云：快、准，但要上传音频、要 key、要网络。这个项目选本地。

### 单文件 vs 包

单文件 1216 行，约 300 行是对齐核心，其余是内嵌校对页 HTML；好处是复制即用，坏处是测试/维护。长期可以拆成 `parse.py / align.py / preview.py`，但当前阶段不拆，避免为了结构而结构。

### 为什么不直接解析 SRT

有 SRT/VTT 就不要跑本流程：直接读字幕时间轴，准确率更高、成本更低。这个工具解决的是「只有音频 + 文稿」的场景。

## 7. 可复现命令

```bash
pdftotext -layout -enc UTF-8 ep.pdf ep.txt

python audio_align.py \
  --audio ep.mp3 \
  --transcript ep.txt \
  --out out \
  --title "Episode title" \
  --model small.en
```

如果模型下载失败：

```bash
# 手动下 config.json / model.bin / tokenizer.json / vocabulary.txt 到一个目录
python audio_align.py ... --model /path/to/faster-whisper-small.en
```

## 8. 下一步

- 批量模式：一个目录多期，输出索引。
- 手动校准持久化：把 preview 的微调写回 JSON 后，App 直接读。
- 句级置信度低于阈值时，自动用 `small.en` 重跑该段（而不是整期）。
- 与 Android 精听对接：`AudioTrack + AudioSentence`，播放 `seekTo(start)` 到 `end` 暂停，听写只判 1–2 个空。
