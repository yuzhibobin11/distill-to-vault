# 分支 B：短视频（抖音 / 视频号 / B站 / 本地文件）

适用：以口播或演示为主的视频。目标不是复述，而是「钩子怎么做的 + 哪些话有信息 + 哪些是水」。

## 1. 取文本（四级降级，严格按顺序）

```bash
python scripts\fetch_text.py doctor            # 先确认 yt-dlp / faster-whisper
python scripts\fetch_text.py video "<url>"
python scripts\fetch_text.py transcribe "<本地文件>"   # 录屏或下载后的文件走这条
```

| 级 | 动作 | 省时 |
|---|---|---|
| 1 | B站：脚本先试官方 / AI 字幕（`--skip-download`），有就直接用 | 省 5-10 分钟 |
| 2 | 无字幕：`yt-dlp -f bestaudio` 下音频（不加 `--extract-audio`，不调 ffmpeg） | — |
| 3 | `faster-whisper` 转写（PyAV 自带解码，无需系统 ffmpeg） | — |
| 4 | 抖音签名失效 / 视频号无 extractor → 人工录屏或导出 mp4，走 `transcribe` | — |

产物：`segments.jsonl`（带起止秒）、`transcript.srt`、`content.md`（每行 `[mm:ss] 文本`）。

### 抖音必须过 cookie 关（实测，2026-11）

`yt-dlp 2026.10.26` 的 `Douyin` extractor 对未带 cookie 的请求统一报：

```
ERROR: [Douyin] <item_id>: Fresh cookies (not necessarily logged in) are needed
```

**不需要登录**，只要浏览器里存在抖音的匿名 cookie（`ttwid` 一类）。以下三条路按顺序试：

| 序 | 做法 | 实测结果 |
|---|---|---|
| 1 | `yt-dlp --cookies-from-browser edge "<url>"` | 浏览器**必须完全退出**，否则 `Could not copy Chrome cookie database`（SQLite 被独占，报 `Device or resource busy`） |
| 2 | 同上，换 `chrome` | 只有在该浏览器**实际访问过抖音**时才有 cookie。实测 Chrome 库 46 条 cookie 全是 google/youtube，抖音 0 条 → 仍报同样错误 |
| 3 | 无 cookie 抓分享页 `www.iesdouyin.com/share/video/<id>/` | ❌ 页面里的 `window._ROUTER_DATA` 仅约 1.4KB，只含 UA、`itemId`、AB 参数；**无 `play_addr` / `desc`**，视频数据靠前端二次请求 |

结论：**别在无 cookie 时反复重试**，直接让用户二选一 —— ① 在目标浏览器打开一次该视频 → 完全退出浏览器 → 用 `--cookies-from-browser` 重试；② 把 mp4 下到本地走 `transcribe`。后者更稳，也避开 cookie 出现在对话里。

### 抖音的真问题：yt-dlp 这条路已经失效

`yt-dlp 2026.10.26` 的 `Douyin` extractor 只调一个接口：

```
https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=<id>
```

该接口现在要 `a_bogus` 签名，而源码里明写着 `TODO: Run verification challenge code to generate signature cookies`。**签名没实现，带什么 cookie 都可能拿不到 `aweme_detail`。** 报错文案是 `Fresh cookies ... are needed`，但它在 `_real_extract` 里判断的是 `s_v_web_id` 是否存在，跟 cookie 多少无必然关系 —— 别被这句错误提示误导，以为是没登录。

同时排除的还有：

- **浏览器 cookie 解不开**：Edge/Chrome 127+ 用 App-Bound 加密（`encrypted_value` 前缀 `v20`），`--cookies-from-browser` 报 `Failed to decrypt with DPAPI`（yt-dlp issue 10927）。离线拿不到那个 key。
- **Windows 上抢不到 cookie 库**：被运行中的浏览器独占，`cp` 报 `Device or resource busy`，SQLite `immutable=1` / `mode=ro` 都报 `unable to open database file`。`esentutl /y` 也失败。**只能让用户完全退出浏览器**，没有别的办法。
- **匿名 ttwid 不够**：`POST https://ttwid.bytedance.com/ttwid/union/register/` 能拿到合法 `ttwid`，但 `--add-header "Cookie:ttwid=..."` 之后仍报同样错误。

### 可用路径：CDP 拦网络请求，直接取音轨直链

不装 playwright，只用浏览器自带的调试协议。需要 `python -m pip install --user websocket-client`。

```bash
# 1. 起一个带调试端口的 Edge（独立 profile，别用默认 profile，新版拒绝调试默认 profile）
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" \
  --remote-debugging-port=9222 --user-data-dir=C:\Temp\distill\_edge_dbg \
  --headless=new --disable-gpu --mute-audio "about:blank"

# 2. 连 CDP → Network.enable → Page.navigate → 收集 requestWillBeSent
# 3. 过滤 url 含 media-audio 的请求，得到带签名的音轨直链
```

实测拿到的是**纯音频轨**（不是整个视频），这对转写反而最省：

```
https://v26-web.douyinvod.com/<hash>/<ts>/video/tos/cn/tos-cn-vd-0026/<obj>/media-audio-und-mp4a/?a=6383&br=57...
```

- `br=57` 即 57 kbps，**20 分 56 秒的视频只有 9.2 MB**，1.2 秒下完。
- 下载时必须带 `Referer: https://www.douyin.com/`，否则 403。
- 这是 AAC / 44.1 kHz / 双声道，PyAV 可直接解码，不需要 ffmpeg。
- 签名有时效，拿到立刻下，别缓存 URL。

同一次 CDP 会话还能白拿两样东西，值得一起取：

| 数据 | 取法 | 用途 |
|---|---|---|
| 完整文案 | `document.querySelector('h1').innerText` | 视频简介常含大纲，可作转写的交叉校验 |
| 抖音自动「章节要点」 | 页面正文里的时间轴块 | 官方 AI 摘要，含分段标题，用作时间轴骨架的对照，**但不能当证据**（它本身也是机器生成） |

### 依赖版本坑（实测，2026-11，Python 3.13）

| 坑 | 现象 | 处理 |
|---|---|---|
| **PyAV 19 破坏 faster-whisper** | `TypeError: open() got an unexpected keyword argument 'metadata_errors'`，栈在 `faster_whisper/audio.py` 调 `av.open(..., metadata_errors="ignore")` | 降到 `av==16.1.0`。**不要装最新的 av 19** |
| HuggingFace 不可达 | 首次加载模型卡住；`curl huggingface.co` 返回 code 000 | 设 `HF_ENDPOINT=https://hf-mirror.com`。脚本 `_ensure_hf_endpoint()` 已自动探测并回退 |
| pip 默认源极慢 | `faster-whisper` 从 pypi.org 装 20 分钟未完成 | 用 `-i https://mirrors.aliyun.com/pypi/simple`，实测 2 分 38 秒。**清华镜像该包索引缺失**（`from versions: none`） |

装之前值得先核轮子：`ctranslate2` / `av` / `onnxruntime` / `tokenizers` 在 `cp313-win_amd64` 都有预编译包，不会触发源码编译。

### 转写段必须合并后才能当锚点

`faster-whisper` 配 `vad_filter=True` 会切出 1–2 秒的碎片。实测 20 分钟音频得到 **741 段、中位 7 字符、55% 不足 8 字符**。直接拿碎片做锚点有两个硬后果：

1. 引文够不到 8 字符下限，全部报 `QUOTE-HIT 引文过短`；
2. 一句完整结论横跨 3–5 个碎片，落不进任何单段。

`_merge_asr()` 按「停顿 ≥0.8s 且累积 ≥12 字」「累积 ≥28 字」「累积 ≥20 秒」三条阈值合并，同一份音频变成 **172 段、中位 32 字符、中位 7 秒、0 段不足 8 字符**。合并后一段≈一句，锚点和结论才同级。

> 合并只改分段，不改字：总字数不变（5498 字），但 `char_count` 会因时间戳前缀减少而下降，别误判成丢内容。

**视频号是硬限制**：yt-dlp 没有 `weixin/channels` extractor，脚本直接返回 `E_UNSUPPORTED`。只给三条人工路径：系统录屏 / 从视频号导出 mp4 / 复制文案。报告写 `platform: sph` + `method: manual`，不要假装自动完成。

## 2. 定位方式

`[mm:ss "逐字引文"]`，粒度到句。允许 ±2 秒误差。**引文必填**，只有时间点没有引文会被判 `QUOTE-MISSING`。

字幕来自平台自动生成时，报告首行必须写「字幕为平台自动生成，可能存在错字」，并在 `degraded` 记 `auto-caption`。

时间戳本质只到句级：结论句与转写分段不一一对应，`[12:34]` 是「约在此处」。这一点写进报告的锚点说明行，不要暗示精确到词。

## 3. 蒸馏维度（9 项）

| # | 维度 | 抓什么 |
|---|---|---|
| 1 | 钩子 | 0-3 秒做了什么：提问 / 反常识 / 数字 / 痛点 / 身份代入 / 画面冲击 |
| 2 | 核心承诺 | 看完能得到什么，是否在 15 秒内说清 |
| 3 | 信息密度 | 大约每多少秒出现一条有效信息；低于每 40 秒一条即为低密度 |
| 4 | 时间轴结构 | 分段：钩子 → 承诺 → 论证/演示 → 转折 → CTA |
| 5 | 可验证事实 | 数字、案例、引用，标定位；无出处的口头数字不写进台账 |
| 6 | 演示步骤 | 操作类视频抽成可复现步骤，含前置条件 |
| 7 | CTA | 关注 / 评论 / 私信 / 下单，具体到动作 |
| 8 | 说服手法 | 对比、社会证明、权威、损失厌恶、稀缺 |
| 9 | 水分 | 口播填充词、重复段落、无信息转场；写进「删掉的水分」 |

视频普遍信息稀疏，**不要为了凑字数把一句口播扩写成一段分析**。报告可以短，短而准优于长而空。

## 4. 报告差异

用 `templates\report-delta-video.md` 三段增量：

1. 视频信息卡（平台 / 时长 / 作者 / 发布 / 字幕来源 / 是否转写）放在第 0 节之前。
2. 「时间轴要点」替换 base 的第 3 节「论证结构」，按时间组织，不按论点组织。
3. 「一句话可执行」放在最后。

`coverage` 参考：有官方字幕 → 0.9；机器转写 → 0.75；无口播纯 BGM → ≤0.3 并标 `partial`。

## 5. 本分支的坑

1. **无口播视频**（纯 BGM + 字幕卡）：转写结果为空，只能给画面结构描述，标 `coverage: partial`，不要硬编。
2. **B站字幕需登录**：多数视频拿不到 vtt，直接走转写，别反复重试字幕。
3. **抖音签名频繁失效**：报错形如 `Unable to extract`。先 `pip install --user -U yt-dlp`，仍失败转录屏。
4. **首次模型下载**：`tiny` 约 75MB、`small` 约 460MB。国内直连 HF 常失败，可设 `HF_ENDPOINT=https://hf-mirror.com`。先用 `tiny` 跑通链路。
5. **同音错字**：转写稿里的专有名词必须回视频核对，或标「待核」。
6. **时长阈值**：≥40 分钟且用户要「方法论 / 做成 skill」→ 转 `cangjie-skill`，本分支只出报告。
