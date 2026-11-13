# distill-to-vault

把一篇长内容（公众号、论文、视频）拆成**每句话都能回原文核对**的笔记，直接写进 Obsidian 知识库。

和「让 AI 总结一下」的区别只有一条：**报告里的每个实质结论都必须挂一段原文逐字引文**，挂不上的会被校验器拦下来。校验不通过，文件写不进库。

## 它解决什么问题

AI 摘要的通病是：读起来通顺，但你没法确认哪句是原文说的、哪句是模型自己编的。等到要引用、要决策的时候，全部要重读一遍。

这个 skill 把「可核对」做成能失败的机制，而不是排版风格：

- 每个锚点 = **定位符 + 逐字引文**：`[¶012 "原文里逐字出现的一句"]`、`[12:34 "…"]`、`[p.7 §3.2 "…"]`
- 只有定位符、没有引文的，校验器直接判 ERROR
- 引文与原文差一个字，判 ERROR（实测抓过自己漏抄一个「也」）
- 结论按支持度分四档：`{S}` 原文证明、`{M}` 只提到、`{I}` 我的推断、`{X}` 查不到 → 前两档进正文，第三档进判断节，第四档删掉

## 安装

需要 Python 3.10+。

```bash
git clone https://github.com/yuzhibobin11/distill-to-vault.git ~/.workbuddy/skills/distill-to-vault
cd ~/.workbuddy/skills/distill-to-vault
pip install requests yt-dlp faster-whisper "av==16.1.0"
```

`av` 必须钉在 16.x。PyAV 19 移除了 `metadata_errors` 参数，faster-whisper 会直接抛 `TypeError`。

装完自检：

```bash
python scripts/fetch_text.py doctor
```

## 用法

```
把这个链接蒸馏一下：https://mp.weixin.qq.com/s/xxxx
```

或者手动跑三步：

```bash
# 1. 取原文，落盘到工作区（不整篇读进上下文）
python scripts/fetch_text.py fetch <url> --out-dir C:\Temp\distill\job1

# 2. 校验（退出码 20 = 不通过，不许交付）
python scripts/audit.py verify 草稿.md --src C:\Temp\distill\job1\content.md

# 3. 按学科写进知识库，总纲自动更新
python scripts/audit.py write 草稿.md --vault E:/football/足球 \
  --topic 人工智能 --summary "一句话结论" --src C:\Temp\distill\job1\content.md
```

视频走 `video` 子命令（下载音轨 + 转写 + 合并语义句群）：

```bash
python scripts/fetch_text.py video <抖音/B站链接> --out-dir C:\Temp\distill\job2 --model small
```

## 校验器在查什么

`audit.py verify` 九类检查，任何一条 ERROR 都会阻止写盘：

| 检查 | 拦的是什么 |
|---|---|
| LOC-EXISTS | 定位符指向的位置原文里不存在 |
| QUOTE-MISSING | 只有位置、没有逐字引文 |
| QUOTE-HIT | 引文在该定位范围内找不到（差一个字也算） |
| BIDIR | 正文锚点和文末定位表对不上 |
| LEVEL | `{S}` 结论放进了「我的判断」节，或 `{I}` 混进结论 |
| COARSE | 长结论挂在很粗的锚点上（整页/整段却只有一句引文） |
| THIN | 空节、灌水节 |
| SCHEMA | frontmatter 缺字段或类型不对 |
| CLAIM | 声明的字数/覆盖度与实际不符 |

自带三个标注用例，`python scripts/audit.py eval eval/cases` 可跑。用例判定的是「校验器行为符不符合预期」，不是「报告写得对不对」。

## 旧笔记升级

早期版本只写了定位符、没写引文。用 `upgrade` 批量找候选：

```bash
python scripts/audit.py upgrade 旧笔记.md --src content.md          # 只列候选，不改文件
python scripts/audit.py upgrade 旧笔记.md --src content.md --apply  # 回填高于阈值的
```

候选按「结论与候选句的字面重合度」排序。**它只解决找句子的体力活，语义是否真支撑那条结论必须人判断**——这是工具的边界，写在 `references/audit-protocol.md` 里。

## 三个坑（都踩过）

1. **抖音 yt-dlp 已经失效**。extractor 依赖 `a_bogus` 签名，源码里是 TODO，报「Fresh cookies needed」是误导。可行路径是 headless 浏览器 + CDP 拦截网络请求取音轨直链，细节在 `references/route-short-video.md`。
2. **PyAV 版本**：见上，必须 16.x。
3. **模型下载慢**：设 `HF_ENDPOINT=https://hf-mirror.com`。国内默认源拉 faster-whisper 模型可能二十分钟不动。

## 它做不到什么

写清楚，免得误解：

- **语义支持度无法自动验证**。校验器能确认「这句话原文里真有」，不能确认「这句话证明了你的结论」。后者仍需人看。
- **PDF 表格到单元格级不可靠**。复杂表格抽取会错列。
- **图片和图表不做 OCR**。原文信息主要在图片里时，报告会缺那块，会在头部注明。
- **抖音以外的部分平台取源不稳**，视频号没有可用路径。

## 目录

```
SKILL.md                  入口：分支路由、写入规则、脚本契约
scripts/fetch_text.py     取源：SSRF 校验、限长、快照、转写
scripts/audit.py          校验 + 写盘 + 升级 + 用例评估
scripts/dvlib.py          公共库：规范化、锚点解析、原子写
references/               三个分支的维度表 + 审计协议
templates/                叙事版 / 结论表版骨架
eval/cases/               标注用例
```
