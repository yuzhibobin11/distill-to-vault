#!/usr/bin/env python3
"""源文件视图：只把「该看的那部分」送进上下文。

写报告时最烧 token 的一步是通读全文。一篇 1.8 万字的公众号 ≈ 1.3 万 token，
而真正被写进报告的往往只有 6–10 段。这个脚本给出三种视图：

    outline  结构骨架：每段一行（编号 + 前 N 字 + 字数），看完全文只花几百 token
    show     按段号 / 节号 / 页号 / 时间取指定位置全文，可设字符预算
    find     按关键词找段，直接命中再取

设计原则：默认输出必须短。任何一次调用打印超过 3000 字都是设计失误。

用法：
    python scripts/view.py outline <src> [--head 24]
    python scripts/view.py show    <src> --para 012,019 --budget 3000
    python scripts/view.py show    <src> --section 3.2
    python scripts/view.py show    <src> --page 7
    python scripts/view.py show    <src> --time 12:34 --minutes 2
    python scripts/view.py find    <src> 凯利 仓位 --ctx 60
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dvlib as d
from audit import Source


# ---------------------------------------------------------------- 估算

def approx_tokens(s: str) -> int:
    """粗估 token：汉字约 0.75 token/字，其余约 1 token/4 字符。只用于提示预算。"""
    cn = len(re.findall(r"[\u4e00-\u9fff]", s))
    return int(cn * 0.75 + (len(s) - cn) / 3.8)


def _clip(s: str, n: int) -> str:
    s = d.normalize(s)
    return s if len(s) <= n else s[:n] + "…"


_SENT_END = "。！？；!?;."


def _cut_at_sentence(s: str, budget: int) -> str:
    """按字数截断，但尽量落在句末，免得切出半句话。

    只在预算 60% 之后找句末；找不到就硬截，不为了凑整句把内容砍掉一半。
    """
    if len(s) <= budget:
        return s
    head = s[:budget]
    floor = int(budget * 0.6)
    for i in range(len(head) - 1, floor - 1, -1):
        if head[i] in _SENT_END:
            # 英文句号后面必须跟空白，避免切在 3.5 这种小数点
            if head[i] in ".!?;" and i + 1 < len(s) and not s[i + 1].isspace():
                continue
            return head[: i + 1]
    return head


def _strip_comments(s: str) -> str:
    """去掉 <!-- page N --> 这类抽取器注释，它们不是正文。"""
    return re.sub(r"<!--.*?-->", " ", s, flags=re.S)


def _fmt_ts(sec: float) -> str:
    sec = int(sec)
    h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ---------------------------------------------------------------- outline

def _check_src(raw: str) -> Path | None:
    """源不存在时给人话，不要抛 traceback —— 别人第一次用最容易写错路径。"""
    p = Path(raw)
    if p.exists():
        return p
    print(f"找不到源：{p}", file=sys.stderr)
    if p.suffix == "":
        print("  如果指的是工作区目录，确认里面有 content.md 或 PDF 转出的 md。", file=sys.stderr)
    print("  先跑 fetch_text.py（网页/视频）或 workbuddy-pdf（论文）把原文落盘。",
          file=sys.stderr)
    return None


def cmd_outline(args) -> int:
    if _check_src(args.src) is None:
        return d.E_USAGE
    src, head, json_out = Path(args.src), args.head, args.json
    s = Source(src)
    kinds: list[str] = []
    if s.paras:
        kinds.append("¶段落")
    if s.sections:
        kinds.append("§节")
    if s.segs:
        kinds.append("时间轴")
    if s.pages:
        kinds.append("页")

    if not kinds:
        print(f"无法识别结构：{s.path}", file=sys.stderr)
        print("（既没有 [¶nnn] 段落标记，也没有页注释、章节标题或时间戳）", file=sys.stderr)
        return d.E_USAGE

    # 段数越多，每行的摘要越短：骨架的价值在「一眼看全」，不在「读得全」。
    if s.sections:
        n_items = len(s.sections)
    elif s.paras:
        n_items = len(s.paras)
    elif s.segs:
        win = max(15, args.window)
        span = s.segs[-1]["end"] - s.segs[0]["start"]
        n_items = int(span // win) + 1
    else:
        n_items = len(s.pages)
    head_eff = head if n_items <= 40 else max(12, head // 2)

    # 主轴：节 > 段落 > 时间段 > 页。节比页细一个数量级，有节就不看页。
    def item(loc: str, raw: str, hd: str, page: int = 0) -> dict:
        body = d.normalize(raw)
        return {"loc": loc, "n": len(body), "tok": approx_tokens(body),
                "head": _clip(hd, head_eff), "page": page}

    if s.sections:
        axis = "section"
        items = [item(f"§{k}", v["text"], v["title"], v["page"])
                 for k, v in sorted(s.sections.items(), key=lambda x: (x[1]["page"], x[0]))]
    elif s.paras:
        axis = "paragraph"
        items = [item(f"[¶{k}]", v, v) for k, v in sorted(s.paras.items())]
    elif s.segs:
        axis = "segment"
        # 转写段是碎片（vad 切出来的，中位 7 字），逐段列等于把全文抄一遍。
        # 按时间窗聚合：AI 要知道的是「哪一分钟在讲什么」。
        win = max(15, args.window)
        buckets: dict[int, list[dict]] = {}
        for g in s.segs:
            buckets.setdefault(int(g["start"] // win), []).append(g)
        items = []
        for k in sorted(buckets):
            grp = buckets[k]
            txt = " ".join(g.get("text", "") for g in grp)
            items.append(item(f"{_fmt_ts(k * win)}", txt, d.normalize(txt), 0))
    else:
        axis = "page"
        items = [item(f"[p.{k}]", v, v) for k, v in sorted(s.pages.items())]

    total = sum(i["n"] for i in items)
    total_tok = sum(i["tok"] for i in items)

    if json_out:
        print(json.dumps({"path": str(s.path), "axis": axis, "kinds": kinds,
                          "total_chars": total, "total_tokens": total_tok,
                          "items": items}, ensure_ascii=False))
        return d.OK

    print(f"源 {s.path}")
    print(f"{axis} · {len(items)} 项 · {total:,} 字 · 全文约 {total_tok:,} tokens")
    print(f"可用定位：{' '.join(kinds)}")
    print()
    shown = items if len(items) <= 60 else items[:60]
    lines: list[str] = []
    for it in shown:
        label = it["head"]
        if axis == "section":
            if it["n"] == 0:
                label = "（正文都在子节）"
            lines.append(f"  {it['loc']:<9} {it['n']:>5}字 p.{it['page']:<3} {label}")
        elif axis == "segment":
            lines.append(f"  {it['loc']:<7} {it['n']:>4}字 {label}")
        else:
            lines.append(f"  {it['loc']:<8} {it['n']:>5}字 {label}")
    if len(items) > len(shown):
        lines.append(f"  … 其余 {len(items) - len(shown)} 项省略，用 show --para/--section 取")
    print("\n".join(lines))

    # 骨架值不值，看它占全文的比重，不看绝对字数：
    # 一篇 300 段的短文，骨架本身可能就有一半长，那还不如直接读。
    skel_tok = approx_tokens("\n".join(lines))
    share = skel_tok / total_tok if total_tok else 0
    print()
    if share > 0.35:
        print(f"⚠ 骨架 {skel_tok} tokens，占全文 {share:.0%} —— 省得有限，"
              f"直接通读 {s.path.name} 更划算。")
    else:
        print(f"骨架 {skel_tok} tokens，全文 {total_tok:,} tokens，省 {1 - share:.0%}。"
              f"下一步：挑 4–8 个关键位置用 show 取全文，不要通读。")
    return d.OK


# ---------------------------------------------------------------- show

def cmd_show(args) -> int:
    if _check_src(args.src) is None:
        return d.E_USAGE
    s = Source(Path(args.src))
    picks: list[tuple[str, str]] = []       # (标签, 文本)
    errs: list[str] = []

    if args.para:
        for k in re.split(r"[,\s]+", args.para.strip()):
            if not k:
                continue
            k = k.zfill(3) if k.isdigit() else k
            if k in s.paras:
                picks.append((f"[¶{k}]", s.paras[k]))
            else:
                errs.append(f"[¶{k}] 不存在（原文共 {len(s.paras)} 段）")
    for sec in args.section or []:
        f, e = s.fragment(f"p.1 §{sec}" if s.pages else f"§{sec}")
        if f is None:
            # 无页码时退回纯节查找
            rec, e2 = s._section(sec)
            f = rec["text"] if rec else None
            e = e or e2
        (picks.append((f"§{sec}", f)) if f else errs.append(f"§{sec} {e}"))
    for pg in args.page or []:
        f, e = s.fragment(f"p.{pg}")
        (picks.append((f"[p.{pg}]", f)) if f else errs.append(e))
    if args.time:
        t0 = d.parse_ts(args.time)
        t1 = t0 + args.minutes * 60
        hit = [g for g in s.segs if g["end"] >= t0 and g["start"] <= t1]
        if hit:
            picks.append((f"{args.time}-{_fmt_ts(t1)}",
                          " ".join(g.get("text", "") for g in hit)))
        else:
            errs.append(f"{args.time} 之后 {args.minutes} 分钟内没有转写文本")

    if not picks:
        for e in errs:
            print(f"ERR {e}", file=sys.stderr)
        print("没有取到内容。用 outline 先看有哪些位置。", file=sys.stderr)
        return d.E_USAGE

    budget = args.budget
    used = 0
    used_tok = 0
    print(f"源 {s.path}")
    for label, text in picks:
        full = d.normalize(_strip_comments(text))
        body = full
        if used and used + len(body) > budget:
            print(f"\n{label} 跳过：超出预算 {budget} 字（已用 {used}）。"
                  f"单独取它，或加大 --budget。")
            continue
        if len(body) > budget:
            body = _cut_at_sentence(body, budget)
            print(f"\n{label} 截断到 {len(body)} 字（原文 {len(full)} 字）")
        print(f"\n{label}  {len(body)}字 ≈ {approx_tokens(body)} tokens")
        print(body)
        used += len(body)
        used_tok += approx_tokens(body)
    print(f"\n-- 本次共 {used} 字 ≈ {used_tok} tokens")
    for e in errs:
        print(f"ERR {e}", file=sys.stderr)
    return d.OK


# ---------------------------------------------------------------- find

def cmd_find(args) -> int:
    if _check_src(args.src) is None:
        return d.E_USAGE
    s = Source(Path(args.src))
    if not s.paras:
        print("find 只对段落级源有效（需要 [¶nnn] 标记）。论文请用 outline 看节标题。",
              file=sys.stderr)
        return d.E_USAGE

    keys = [k.strip() for k in args.words if k.strip()]
    hits = []
    for k, v in sorted(s.paras.items()):
        body = d.normalize(v)
        score = sum(body.count(x) for x in keys)
        if score:
            # 命中位置附近截一段，不打印整段
            pos = min((body.find(x) for x in keys if x in body), default=0)
            start = max(0, pos - args.ctx // 2)
            snippet = body[start:start + args.ctx]
            hits.append((score, k, snippet, len(body)))

    if not hits:
        print(f"没命中：{' '.join(keys)}（共 {len(s.paras)} 段）")
        return d.OK

    hits.sort(key=lambda x: (-x[0], x[1]))
    print(f"命中 {len(hits)} 段，按命中次数排序（片段 {args.ctx} 字）：")
    for score, k, snippet, n in hits[:args.top]:
        print(f"  [¶{k}] {score}次 · 全段{n}字  …{snippet}…")
    if len(hits) > args.top:
        print(f"  … 其余 {len(hits) - args.top} 段省略（--top 调整）")
    print(f"\n下一步：show --para {','.join(k for _, k, _, _ in hits[:3])}")
    return d.OK


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="view.py", description="源文件视图：按需取，不通读")
    sub = p.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("outline", help="结构骨架（每项一行）")
    o.add_argument("src")
    o.add_argument("--head", type=int, default=24, help="每项显示前几个字（默认 24）")
    o.add_argument("--window", type=int, default=60,
                   help="视频按多少秒聚合成一行（默认 60）")
    o.add_argument("--json", action="store_true")

    s = sub.add_parser("show", help="取指定位置全文")
    s.add_argument("src")
    s.add_argument("--para", default=None, help="段号，逗号分隔：012,019")
    s.add_argument("--section", action="append", default=None, help="节号：3.2")
    s.add_argument("--page", action="append", default=None, help="页号：7")
    s.add_argument("--time", default=None, help="起始时间：12:34")
    s.add_argument("--minutes", type=int, default=2, help="时间段长度（默认 2 分钟）")
    s.add_argument("--budget", type=int, default=3000, help="单次输出字符上限（默认 3000）")

    f = sub.add_parser("find", help="按关键词找段")
    f.add_argument("src")
    f.add_argument("words", nargs="+")
    f.add_argument("--ctx", type=int, default=60, help="命中片段长度（默认 60 字）")
    f.add_argument("--top", type=int, default=10, help="最多列几段（默认 10）")

    args = p.parse_args(argv)
    if args.cmd == "outline":
        return cmd_outline(args)
    if args.cmd == "show":
        return cmd_show(args)
    return cmd_find(args)


if __name__ == "__main__":
    sys.exit(main())
