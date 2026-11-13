#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit.py - 把「可审计」从格式变成能失败的机制。

子命令:
  verify <report.md> --src <content.md|pages.md> [--segments seg.jsonl] [--json]
  write  <draft.md>  --vault <dir> [--src ...] [--force] [--json]
  eval   <cases_dir> [--json]

退出码: 0 全过 / 20 存在 ERROR / 21 仅 WARN

verify 的九类检查:
  LOC-EXISTS      定位符在原文里是否存在
  QUOTE-MISSING   v2 要求锚点必须带逐字引文（公式/表格单元格例外）
  QUOTE-HIT       引文是否在**该定位范围内**逐字出现
  BIDIR           正文锚点 ↔ 定位表 双向一致
  LEVEL           支持度四档是否用在正确的节（结论节只准 S）
  COARSE          长结论挂粗锚点（段落级锚点但该段很长）
  THIN            空节/灌水节
  SCHEMA          frontmatter 必填、类型、范围
  CLAIM           声明的 coverage / summary_chars 与实际不符
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import dvlib as d

LEVELS = ("S", "M", "I", "X")


# ---------------------------------------------------------------- 源装载

class Source:
    def __init__(self, src: Path, segments: Path | None = None):
        self.paras: dict[str, str] = {}
        self.pages: dict[int, str] = {}
        self.segs: list[dict] = []
        self.kind = "unknown"

        if src.is_dir():
            cand = src / "content.md"
            if cand.exists():
                src = cand
            else:
                pdf = list(src.glob("*.md"))
                if pdf:
                    src = pdf[0]

        text = src.read_text(encoding="utf-8") if src.exists() else ""
        self.path = src

        if re.search(r"^\[¶\d{3,4}\]", text, re.M):
            self.paras = d.load_paragraphs(src)
            self.kind = "paragraph"
        pg = d.load_pages(src)
        if pg:
            self.pages = pg
            if self.kind == "unknown":
                self.kind = "page"

        seg_path = segments or (src.parent / "segments.jsonl")
        if seg_path.exists():
            self.segs = d.load_segments(seg_path)
            if self.kind == "unknown":
                self.kind = "segment"

        # 时间轴锚点也允许从 content.md 的 [mm:ss] 前缀取
        if not self.segs and re.search(r"^\[\d{1,3}:\d{2}\]", text, re.M):
            for m in re.finditer(r"^\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s?(.*)$", text, re.M):
                t = d.parse_ts(m.group(1))
                self.segs.append({"start": t, "end": t + 8.0, "text": m.group(2)})
            if self.kind == "unknown":
                self.kind = "segment"

    # -- 定位符 → 原文片段
    def fragment(self, locator: str) -> tuple[str | None, str]:
        loc = locator.strip()
        if loc.startswith("¶"):
            key = loc[1:].zfill(3)
            if key in self.paras:
                return self.paras[key], ""
            return None, f"段落 ¶{key} 不存在（原文共 {len(self.paras)} 段）"
        if loc.startswith("p."):
            m = re.match(r"p\.(\d+)", loc)
            num = int(m.group(1))
            if num in self.pages:
                return self.pages[num], ""
            return None, f"第 {num} 页不存在（原文共 {len(self.pages)} 页）"
        m = re.match(r"(\d{1,3}:\d{2}(?::\d{2})?)", loc)
        if m:
            t = d.parse_ts(m.group(1))
            # 相邻转写段共享边界（上一段 end == 下一段 start），若按「第一个命中」返回，
            # t 落在边界时会错误命中上一段。此处优先取 start 与 t 最接近的段。
            best, best_delta = None, 1e9
            for s in self.segs:
                delta = abs(float(s.get("start", -1)) - t)
                if delta <= 0.6 and delta < best_delta:
                    best, best_delta = s, delta
            if best is not None:
                return str(best.get("text", "")), ""
            for s in self.segs:
                if float(s.get("start", -1)) - 0.6 <= t <= float(s.get("end", -1)) + 0.6:
                    return str(s.get("text", "")), ""
            dur = max([float(s.get("end", 0)) for s in self.segs], default=0)
            return None, f"时间点 {m.group(1)} 未落在任何转写段（时长约 {dur:.0f}s）"
        return None, f"无法识别的定位符: {locator}"


# ---------------------------------------------------------------- 报告结构

def split_sections(body: str) -> list[tuple[str, str]]:
    """按 ## 切节，返回 [(标题, 内容)]，首个为前言。"""
    parts = re.split(r"^##\s+(.+)$", body, flags=re.M)
    out = [("", parts[0])]
    for i in range(1, len(parts), 2):
        out.append((parts[i].strip(), parts[i + 1]))
    return out


def strip_noise(body: str) -> str:
    """去掉代码块与表格分隔行，避免把模板示例当锚点。"""
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    body = re.sub(r"^\|[\s:|-]+\|$", "", body, flags=re.M)
    return body


def is_example_anchor(line: str, pos: int, quote: str) -> bool:
    """判断是不是「格式说明里的锚点示例」，例：> 定位：`[¶012]` = 第 12 段

    判据三条同时成立：没有引文（裸定位）、在引用块里、被行内代码包着。
    真的引用即便写在反引号里（有人爱这么排版）只要带引文就不算示例。
    """
    if quote:
        return False
    if not line.lstrip().startswith(">"):
        return False
    return any(s <= pos < e
               for s, e in (x.span() for x in re.finditer(r"`[^`\n]*`", line)))


def drop_example_anchors(body: str) -> str:
    lines = []
    for ln in body.splitlines():
        if ln.lstrip().startswith(">"):
            for m in reversed(list(d.ANCHOR_RE.finditer(ln))):
                if is_example_anchor(ln, m.start(), m.group(2) or ""):
                    ln = ln[:m.start()] + ln[m.end():]
        lines.append(ln)
    return "\n".join(lines)


LOC_TABLE_HEAD = re.compile(r"^##\s*附[：:]\s*定位表", re.M)
LOC_ROW = re.compile(
    r"^\|\s*\[?(" + d.LOCATOR + r")\]?\s*\|", re.M)


def anchor_planes(body: str) -> tuple[list[dict], list[dict]]:
    """把锚点分成两部分：正文锚点、定位表锚点。"""
    m = LOC_TABLE_HEAD.search(body)
    if m:
        main, table = body[: m.start()], body[m.start():]
    else:
        main, table = body, ""
    return (d.parse_anchors(drop_example_anchors(strip_noise(main))),
            d.parse_anchors(drop_example_anchors(strip_noise(table))))


# ---------------------------------------------------------------- verify

def verify_text(raw: str, src: Path, segments: Path | None = None) -> dict:
    items: list[dict] = []

    def add(level: str, code: str, detail: str, loc: str = "", line: int = 0):
        items.append({"level": level, "code": code, "locator": loc,
                      "detail": detail, "line": line})

    if not raw.startswith("---"):
        add("ERROR", "SCHEMA", "文件不以 YAML frontmatter 开头（必须是 --- 起首）")
        return _finish(items, {})

    fm, body = d.parse_frontmatter(raw)
    # 两种成稿：distill-report（结论表版，全量校验）/ distill-note（叙事知识库版，跳过表格类检查）
    is_note = fm.get("type") == "distill-note"

    # ---------- SCHEMA
    for k in d.FM_REQUIRED:
        if k not in fm:
            if k == "summary_chars" and is_note:
                continue  # 叙事版由 write 时自动补算
            add("ERROR", "SCHEMA", f"frontmatter 缺少必填字段 {k}")
        elif k == "published":
            continue  # 发布日期允许未知（短视频/未标注），但键必须存在
        elif fm[k] in (None, "", []):
            if k == "summary_chars" and is_note:
                continue  # 叙事版由 write 时自动补算
            add("ERROR", "SCHEMA", f"frontmatter 必填字段 {k} 为空")
    if fm.get("type") not in ("distill-report", "distill-note"):
        add("ERROR", "SCHEMA",
            f"type 必须是 distill-report 或 distill-note，当前 {fm.get('type')!r}")
    cov = fm.get("coverage")
    if not isinstance(cov, (int, float)) or not (0 <= cov <= 1):
        add("ERROR", "SCHEMA", f"coverage 必须是 0-1 的数，当前 {cov!r}")
    if fm.get("confidence") not in ("low", "medium", "high"):
        add("ERROR", "SCHEMA", f"confidence 必须是 low/medium/high，当前 {fm.get('confidence')!r}")
    for k in ("raw_chars", "summary_chars"):
        v = fm.get(k)
        if is_note and k == "summary_chars" and v is None:
            continue
        if not isinstance(v, int) or v <= 0:
            add("ERROR", "SCHEMA", f"{k} 必须是正整数，当前 {v!r}")

    body_nows = re.sub(r"\s", "", body)
    actual_chars = len(body_nows)
    declared = fm.get("summary_chars")
    if isinstance(declared, int) and declared > 0:
        delta = abs(declared - actual_chars) / max(declared, 1)
        if delta > 0.20:
            add("WARN", "CLAIM",
                f"summary_chars 声明 {declared}，实际 {actual_chars}，偏差 {delta:.0%}")

    total_lines = raw.count("\n") + 1

    # ---------- 锚点存在性 / 引文
    srcobj = Source(src, segments)
    main_anchors, table_anchors = anchor_planes(body)

    if srcobj.kind == "unknown":
        add("ERROR", "LOC-EXISTS", f"源文件无法识别格式（既无 [¶nnn] 也无 <!-- page --> 也无时间轴）: {src}")

    stats = {"anchors": 0, "quoted": 0, "S": 0, "M": 0, "I": 0, "X": 0, "levels_missing": 0}
    seen_locs: set[str] = set()

    for a in main_anchors:
        stats["anchors"] += 1
        loc, quote = a["locator"], a["quote"]
        seen_locs.add(loc)
        line = raw[: a["span"][0]].count("\n") + 1

        frag, err = srcobj.fragment(loc)
        if frag is None:
            add("ERROR", "LOC-EXISTS", err, loc, line)
            continue

        is_formula = "eq." in loc
        is_cell = bool(re.search(r"\br\d+c\d+\b", loc))
        if not quote:
            if is_formula:
                if "unverified:formula" not in body:
                    add("ERROR", "QUOTE-MISSING",
                        "公式锚点无引文，必须在报告内显式声明 unverified:formula", loc, line)
            elif is_cell:
                add("WARN", "QUOTE-MISSING",
                    "表格单元格锚点无引文：表格拉平后无法逐字核对，须人工回原 PDF", loc, line)
            else:
                add("ERROR", "QUOTE-MISSING",
                    "v2 要求锚点必须带逐字引文（[¶012 \"原文一句\"]），裸定位不可审计", loc, line)
            continue

        stats["quoted"] += 1
        ok, reason = d.quote_hit(quote, frag)
        if not ok:
            add("ERROR", "QUOTE-HIT", reason, loc, line)

    # ---------- BIDIR（仅表格版；叙事版把定位表折叠在文末，不要求双向一一对应）
    table_locs = {a["locator"] for a in table_anchors}
    table_locs |= {m.group(1).strip() for m in LOC_ROW.finditer(body)}
    if not is_note:
        for loc in sorted(seen_locs - table_locs):
            add("ERROR", "BIDIR", f"正文引用了 {loc}，但定位表里没有这一条")
        for loc in sorted(table_locs - seen_locs):
            add("WARN", "ORPHAN", f"定位表有 {loc}，但正文从未引用")

    # ---------- LEVEL 四档 × 节位 / THIN 密度门（仅表格版）
    secs = split_sections(body)
    for title, content in secs:
        lv = re.findall(r"\{([SMIX])\}", content)
        for x in lv:
            stats[x] = stats.get(x, 0) + 1
        n_anchor_lines = sum(1 for ln in content.splitlines() if d.parse_anchors(ln))

        if is_note:
            continue

        if re.match(r"^1[.．]?\s*核心主张", title):
            bad = [x for x in lv if x != "S"]
            if bad:
                add("ERROR", "LEVEL",
                    f"「{title}」是结论节，只允许 {{S}}，出现了 {{{'/'.join(sorted(set(bad)))}}}")
            if n_anchor_lines and not lv:
                add("WARN", "LEVEL", f"「{title}」有 {n_anchor_lines} 条带锚点的主张，但没有标支持度档位")
        elif re.match(r"^6[.．]?\s*(局限|原文未证明|未证明)", title):
            bad = [x for x in lv if x != "M"]
            if bad:
                add("ERROR", "LEVEL",
                    f"「{title}」是局限节，只允许 {{M}}（原文提到但未证明），出现了 {{{'/'.join(sorted(set(bad)))}}}")
        elif re.match(r"^7[.．]?\s*我的判断", title):
            bad = [x for x in lv if x != "I"]
            if bad:
                add("ERROR", "LEVEL",
                    f"「{title}」是我的判断节，只允许 {{I}}，出现了 {{{'/'.join(sorted(set(bad)))}}}")

        # ---------- THIN 密度门
        if title.startswith("附") or title.startswith("附录") or "一句话结论" in title:
            continue  # 定位表与一句话结论不参与密度门
        if title and not content.strip():
            add("WARN", "THIN", f"「{title}」是空节")
        elif title and n_anchor_lines < 2 and "thin-ok" not in content:
            add("WARN", "THIN",
                f"「{title}」只有 {n_anchor_lines} 条带锚点内容；"
                f"确实不适用请写 <!-- thin-ok --> 并说明原因，不要灌水")

    # ---------- COARSE 粒度
    for a in main_anchors:
        line = raw[: a["span"][0]].count("\n") + 1
        line_text = raw.splitlines()[line - 1] if line - 1 < total_lines else ""
        claim = d.ANCHOR_RE.sub("", line_text)
        claim = re.sub(r"\|", "", claim).strip()
        loc = a["locator"]
        if loc.startswith("¶") and len(claim) > 40:
            frag, _ = srcobj.fragment(loc)
            if frag and len(d.normalize(frag)) > 300:
                add("WARN", "COARSE",
                    f"结论句 {len(claim)} 字，只挂段落级锚点，而该段 {len(frag)} 字 —— "
                    f"位置对不代表句子被支持，建议换成段内更短的引文", loc, line)

    # ---------- X 档残留
    if stats.get("X"):
        add("ERROR", "LEVEL", f"存在 {stats['X']} 处 {{X}}（校验失败）标注，必须删除该条而不是留在报告里")

    return _finish(items, stats, fm)


def verify(report: Path, src: Path, segments: Path | None = None) -> dict:
    return verify_text(report.read_text(encoding="utf-8"), src, segments)


def _finish(items: list[dict], stats: dict, fm: dict | None = None) -> dict:
    errs = [i for i in items if i["level"] == "ERROR"]
    warns = [i for i in items if i["level"] == "WARN"]
    status = "error" if errs else ("warn" if warns else "ok")
    return {"status": status, "counts": {"error": len(errs), "warn": len(warns)},
            "items": items, "stats": stats, "frontmatter": fm or {}}


def exit_code_for(res: dict) -> int:
    return {"error": d.V_ERROR, "warn": d.V_WARN}.get(res["status"], d.V_OK)


def print_verify(res: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return
    for it in res["items"]:
        tag = "ERROR" if it["level"] == "ERROR" else "WARN "
        where = f" @{it['locator']}" if it["locator"] else ""
        ln = f" L{it['line']}" if it["line"] else ""
        print(f"[{tag}] {it['code']:<13}{where}{ln}  {it['detail']}")
    s = res["stats"]
    print()
    print(f"锚点 {s.get('anchors', 0)} 个，其中带引文 {s.get('quoted', 0)} 个"
          f"（S={s.get('S', 0)} M={s.get('M', 0)} I={s.get('I', 0)} X={s.get('X', 0)}）")
    c = res["counts"]
    verdict = {"ok": "通过", "warn": "通过（有告警）", "error": "不通过"}[res["status"]]
    print(f"校验结论：{verdict} —— {c['error']} 个错误，{c['warn']} 个告警")


# ---------------------------------------------------------------- write

LIB_DIR = "知识库"
INDEX_NAME = "00-知识库总纲.md"
TOPIC_FALLBACK = "待归类"

# 学科归一：先精确命中标准名，再命中别名，再按包含关系收敛。
# 收敛不了就原样建新学科——目录树要能生长，不能因为不在白名单就丢进「待归类」。
TOPIC_ALIASES = {
    "人工智能": ["ai", "AI", "机器学习", "深度学习", "大模型", "llm", "算法",
                 "神经网络", "transformer", "论文", "论文精读"],
    "心理学": ["心理", "心理学", "自我关怀", "自我评价", "情绪", "认知", "成长", "正念"],
    "方法论": ["方法", "方法论", "效率", "知识管理", "skill", "技能工程", "写作",
               "思维模型", "工作流"],
    "商业": ["商业", "经济", "投资", "金融", "产品", "管理", "营销", "创业"],
    "健康": ["健康", "医学", "运动", "睡眠", "营养"],
    "人文": ["人文", "历史", "哲学", "社会学", "文学", "艺术"],
}

INDEX_SKELETON = """---
title: "知识库总纲"
type: index
updated: "{today}"
---

# 知识库总纲

外部内容读进来的知识都放这里：论文、公众号长文、视频、播客、报告。
**按学科分目录，一篇文档一件完整的事**，每句话都能回到原文核对。

## 这个库怎么用

- **找某方面内容** → 看学科分节，每篇只挂一句结论，不读全文也能判断要不要点开
- **判断可不可信** → 每篇 frontmatter 有 `coverage`（覆盖度），低于 0.6 说明原文没读透；台账的「审计」列 `v2` = 每个锚点都带逐字引文且校验通过，`v1 待补` = 只有位置没引文，核对得自己翻原文
- **核对某句话** → 出处折不打断阅读，全在文末定位表：「位置 + 逐字引文」
- **补充或纠错** → 直接改正文，别改引文；引文一改校验器就报 QUOTE-HIT

## 归档台账

按入库时间排，用于溯源。学科看目录，这里不重复。

| 加入日期 | 条目 | 来源 | 形式 | 覆盖 | 审计 |
|---------|------|------|------|------|------|

## 命名与归档规则

- **学科目录**：一级按学科，不按月份。月份只会让同一个主题散在十几个文件夹里。
- **条目名**：用内容标题，中文在前，不带日期、不带平台码、不带英文项目名前缀。
- **一条目一主题**：宁可拆成两篇，也不要写「XX 合集」。合集没法被单独引用。
- **不写「摘要」**：库里存的是结论与依据，不是原文缩写。

#知识库 #MOC
"""

_SRC_LABEL = {"paper": "论文原文", "wx": "公众号", "douyin": "抖音",
              "bilibili": "B站", "xiaohongshu": "小红书", "web": "网页",
              "youtube": "YouTube", "podcast": "播客"}
_FORM_LABEL = {"paper": "论文", "text-image": "图文", "short-video": "视频",
               "long-video": "视频", "audio": "音频"}


def normalize_topic(raw: str) -> str:
    s = (raw or "").strip().strip("/\\")
    if not s:
        return TOPIC_FALLBACK
    for canon, aliases in TOPIC_ALIASES.items():
        if s == canon:
            return canon
        if any(s.lower() == a.lower() for a in aliases):
            return canon
        if canon in s:
            return canon
    return d.sanitize_name(s, max_len=16) or TOPIC_FALLBACK


def ledger_row(date: str, filename: str, platform: str, branch: str,
               author: str, coverage, audit: str = "v2") -> str:
    src = _SRC_LABEL.get(platform, platform or "网页")
    if author and author not in ("未标注", "unknown", "-"):
        src += f" · {d.sanitize_name(author, 16)}"
    form = _FORM_LABEL.get(branch, branch or "—")
    try:
        cov = f"{float(coverage):.2f}"
    except (TypeError, ValueError):
        cov = "—"
    return f"| {date} | [[{filename}]] | {src} | {form} | {cov} | {audit} |"


def _h2(lines: list[str], name: str) -> int | None:
    for i, ln in enumerate(lines):
        if ln.strip() == f"## {name}":
            return i
    return None


def _block(lines: list[str], start: int) -> tuple[int, int]:
    """## 标题所在节的 [start, end)，end 指下一个 ## 或文件尾。"""
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            return start, i
    return start, len(lines)


def update_index(index: Path, topic: str, filename: str, summary: str,
                 ledger: str) -> dict:
    """幂等维护：学科分节里挂一条结论，台账里挂一行溯源。同文件重写不重复。"""
    today = d.now_iso()[:10]
    created = False
    if not index.exists():
        index.parent.mkdir(parents=True, exist_ok=True)
        d.atomic_write(index, INDEX_SKELETON.format(today=today))
        created = True

    lines = index.read_text(encoding="utf-8").splitlines()
    link = f"[[{filename}]]"
    item = f"- {link} —— {summary}" if summary else f"- {link}"

    # ---- 学科节
    h = _h2(lines, topic)
    if h is None:
        anchor = _h2(lines, "归档台账")
        if anchor is None:
            lines += ["", f"## {topic}", "", item]
        else:
            lines[anchor:anchor] = [f"## {topic}", "", item, ""]
        res_item = "section-new"
    else:
        s, e = _block(lines, h)
        hit = next((i for i in range(s + 1, e) if link in lines[i]), None)
        if hit is not None:
            lines[hit] = item
            res_item = "updated"
        else:
            last = next((i for i in range(e - 1, s, -1) if lines[i].startswith("- ")), None)
            lines.insert((last + 1) if last is not None else s + 1, item)
            res_item = "appended"

    # ---- 台账
    res_ledger = "no-section"
    h = _h2(lines, "归档台账")
    if h is not None:
        s, e = _block(lines, h)
        hit = next((i for i in range(s + 1, e) if link in lines[i]), None)
        if hit is not None:
            lines[hit] = ledger
            res_ledger = "updated"
        else:
            last = next((i for i in range(e - 1, s, -1) if lines[i].lstrip().startswith("|")), None)
            if last is None:
                res_ledger = "no-table"
            else:
                lines.insert(last + 1, ledger)
                res_ledger = "appended"

    lines = [re.sub(r'^updated:.*$', f'updated: "{today}"', ln)
             if re.match(r"^updated:", ln) else ln for ln in lines]
    d.atomic_write(index, "\n".join(lines) + "\n")
    return {"items": res_item, "ledger": res_ledger, "created": created}


def cmd_write(args) -> int:
    draft = Path(args.draft)
    if not draft.exists():
        print(f"E_USAGE: 草稿不存在 {draft}", file=sys.stderr)
        return d.E_USAGE

    raw = draft.read_text(encoding="utf-8")
    fm, body = d.parse_frontmatter(raw)
    if not fm:
        print("E_VAULT: 草稿缺少 frontmatter", file=sys.stderr)
        return d.E_VAULT

    # summary_chars 不该由人填：先按实际正文长度修正，再拿修正后的文本去校验
    fm["summary_chars"] = len(re.sub(r"\s", "", body))
    fixed = d.dumps_frontmatter(fm) + body

    if args.src and not args.force:
        res = verify_text(fixed, Path(args.src),
                          Path(args.segments) if args.segments else None)
        if res["status"] == "error":
            print("拒绝写盘：verify 未通过（用 --force 可强制，但会留下不可审计的报告）", file=sys.stderr)
            print_verify(res, False)
            return d.V_ERROR


    vault = Path(args.vault)
    branch = fm.get("branch", "text-image")
    platform = fm.get("platform", "web")
    published = str(fm.get("published") or "")[:10]
    date = published if re.fullmatch(r"\d{4}-\d{2}-\d{2}", published) else \
        d.now_iso()[:10]

    # 学科目录：--topic 优先，其次 frontmatter 的 topic，最后「待归类」
    topic = normalize_topic(args.topic or fm.get("topic") or "")
    fm["topic"] = topic
    fixed = d.dumps_frontmatter(fm) + body

    subdir = vault / LIB_DIR / topic
    # 文件名用内容标题，不带日期与平台码（日期在台账与 frontmatter 的 fetched 里）
    stem = d.sanitize_name(fm.get("title") or fm.get("source_title") or "", max_len=48)
    target = (subdir / f"{stem}.md") if args.overwrite else d.unique_path(subdir, stem, ".md")

    d.atomic_write(target, fixed)

    index = vault / LIB_DIR / INDEX_NAME
    summary = re.sub(r"\s+", " ", str(args.summary or fm.get("oneliner") or
                                      fm.get("summary") or "")).strip()
    if len(summary) > 80:
        summary = summary[:80].rstrip() + "…"
    ledger = ledger_row(date, target.stem, platform, branch,
                        str(fm.get("author") or ""), fm.get("coverage"))
    action = update_index(index, topic, target.stem, summary, ledger)

    if args.json:
        print(json.dumps({"status": "ok", "path": str(target), "topic": topic,
                          "index": action, "summary_chars": fm["summary_chars"]},
                         ensure_ascii=False))
    else:
        print(f"写入: {target}")
        print(f"学科: {topic}")
        print(f"索引: {action['items']}/{action['ledger']} ({index})")
        print(f"summary_chars: {fm['summary_chars']}")
    return d.OK


# ---------------------------------------------------------------- upgrade

_SENT_SPLIT = re.compile(
    r"(?<=[。！？；!?;])"          # 中文标点与英文问号叹号
    r"|(?<=\.)\s+(?=[A-Z0-9\"“(])"  # 英文句号：后面是空格加大写/数字/引号
    r"|\n+"
)


def _noisy(s: str) -> bool:
    """PDF 抽取残渣：邮箱、链接、符号占比过高的行，不该当引文候选。"""
    if "@" in s or "http" in s.lower() or "www." in s.lower():
        return True
    solid = sum(1 for c in s if c.isalnum() or "\u4e00" <= c <= "\u9fff")
    return solid / max(len(s), 1) < 0.5


def _split_sentences(text: str) -> list[str]:
    """切句，只留长度落在引文区间（8–160）内、且不是抽取残渣的完整句。"""
    t = d.normalize(text)
    out: list[str] = []

    def push(x: str) -> None:
        x = x.strip()
        if d.QUOTE_MIN <= len(x) <= d.QUOTE_MAX and not _noisy(x):
            out.append(x)

    for seg in _SENT_SPLIT.split(t):
        seg = (seg or "").strip()
        if not seg:
            continue
        if len(seg) <= d.QUOTE_MAX:
            push(seg)
            continue
        # 过长：按逗号再切，拼到上限
        buf = ""
        for piece in re.split(r"(?<=[，,])", seg):
            if len(buf) + len(piece) > d.QUOTE_MAX:
                push(buf)
                buf = piece
            else:
                buf += piece
        push(buf)
    return out


def _grams(s: str) -> set[str]:
    s = re.sub(r"[^\w\u4e00-\u9fff]", "", s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def _relevance(ctx: str, cand: str) -> float:
    """候选句被结论覆盖的字符二元组比例。只用来排序，不当作证据。"""
    a, b = _grams(ctx), _grams(cand)
    if not a or not b:
        return 0.0
    return len(a & b) / len(b)


def cmd_upgrade(args) -> int:
    """把只有定位符的旧锚点，按原文列出候选引文，供人工挑或批量回填。

    这是「升级工具」不是「代笔」：候选只按字面重合排序，语义是否真的支撑
    那条结论必须人来判断。--apply 会把高于阈值的候选直接写进报告，写完仍要
    跑 verify，并且要在交付时说明哪些引文是机器挑的。
    """
    rep = Path(args.report)
    if not rep.exists():
        print(f"E_USAGE: 报告不存在 {rep}", file=sys.stderr)
        return d.E_USAGE

    raw = rep.read_text(encoding="utf-8")
    src = Source(Path(args.src), Path(args.segments) if args.segments else None)
    lines = raw.splitlines()

    plan: list[dict] = []
    missed: list[dict] = []
    for no, ln in enumerate(lines, 1):
        anchors = [a for a in d.parse_anchors(ln)
                   if not is_example_anchor(ln, a["span"][0], a["quote"])]
        if not anchors:
            continue
        ctx = d.ANCHOR_RE.sub("", ln)
        for a in anchors:
            if a["quote"]:
                continue
            frag, err = src.fragment(a["locator"])
            if frag is None:
                missed.append({"line": no, "locator": a["locator"], "error": err})
                continue
            scored = sorted(((_relevance(ctx, c), c) for c in _split_sentences(frag)),
                            key=lambda x: -x[0])
            # 页级锚点一页几千字，字面重合挑出来的句子大概率不支撑结论。
            # 标出来，别让人以为「有候选就能用」。
            coarse = a["locator"].startswith("p.") and len(frag) > 1500
            plan.append({
                "line": no,
                "locator": a["locator"],
                "context": ctx.strip()[:160],
                "coarse": coarse,
                "frag_len": len(frag),
                "candidates": [(round(s, 2), c) for s, c in scored[:3]],
            })

    applied = 0
    if args.apply and plan:
        by_line: dict[int, list[dict]] = {}
        for p in plan:
            if p["candidates"] and p["candidates"][0][0] >= args.threshold:
                by_line.setdefault(p["line"], []).append(p)
        for no, items in by_line.items():
            line = lines[no - 1]
            for a in sorted(d.parse_anchors(line), key=lambda x: -x["span"][0]):
                if a["quote"] or is_example_anchor(line, a["span"][0], a["quote"]):
                    continue
                hit = next((it for it in items if it["locator"] == a["locator"]), None)
                if hit is None:
                    continue
                new = d.render_anchor(a["locator"], hit["candidates"][0][1])
                line = line[:a["span"][0]] + new + line[a["span"][1]:]
                applied += 1
            lines[no - 1] = line
        d.atomic_write(rep, "\n".join(lines) + "\n")

    if args.json:
        print(json.dumps({"report": str(rep), "pending": len(plan),
                          "locate_failed": missed, "applied": applied,
                          "items": plan}, ensure_ascii=False, indent=2))
        return d.OK

    if not plan and not missed:
        print("没有裸锚点，全部已带引文。")
        return d.OK

    print(f"待补引文：{len(plan)} 处；定位失败：{len(missed)} 处\n")
    coarse_n = sum(1 for p in plan if p.get("coarse"))
    if coarse_n:
        print(f"其中 {coarse_n} 处是页级锚点（一页上千字），候选只能算「大致相关」，"
              f"建议改成节级锚点再回填。\n")
    for p in plan:
        print(f"L{p['line']}  [{p['locator']}]")
        if p.get("coarse"):
            print(f"   ⚠ 页级锚点：原文该位置 {p['frag_len']} 字，候选可靠性低")
        print(f"   结论：{p['context']}")
        if not p["candidates"]:
            print("   候选：（该位置无可切割的句子，需手写引文）")
        for score, cand in p["candidates"]:
            flag = " ← 首选" if score == p["candidates"][0][0] else ""
            print(f"   [{score:.2f}] {cand}{flag}")
        print()

    if missed:
        print("定位失败（原文里没有这个位置，先修定位符）：")
        for m in missed:
            print(f"   L{m['line']} [{m['locator']}] —— {m['error']}")

    if args.apply:
        print(f"\n已回填 {applied} 处（阈值 {args.threshold}）。请立即跑 verify 复核，"
              f"并按 references/audit-protocol.md 人工确认语义是否支撑。")
    else:
        print("\n未改动文件。确认候选后用 --apply 回填，或逐条手写。")
    return d.OK


# ---------------------------------------------------------------- eval

def cmd_eval(args) -> int:
    """跑标注用例。判定的是「校验器行为是否符合预期」，不是「报告有没有错」。

    每个用例可带 expect.json：
      {"status": "error", "codes": ["QUOTE-HIT"], "forbid": ["SCHEMA"]}
    有 expect 的用例才算 PASS/FAIL；没带的只报统计（n/a），不参与判定。
    """
    root = Path(args.cases)
    cases = sorted([p for p in root.iterdir() if p.is_dir()]) if root.exists() else []
    if not cases:
        print(f"E_USAGE: 没有测试用例目录 {root}", file=sys.stderr)
        return d.E_USAGE

    rows, fails = [], 0
    tot_e = tot_w = tot_a = tot_q = 0

    for c in cases:
        rep, src = c / "report.md", c / "content.md"
        if not rep.exists() or not src.exists():
            rows.append({"case": c.name, "status": "SKIP", "error": 0, "warn": 0,
                         "anchors": 0, "quoted": 0, "verdict": "-", "codes": []})
            continue

        seg = c / "segments.jsonl"
        res = verify(rep, src, seg if seg.exists() else None)
        s = res["stats"]
        codes = sorted({i["code"] for i in res["items"]})

        verdict = "n/a"
        exp_p = c / "expect.json"
        if exp_p.exists():
            exp = json.loads(exp_p.read_text(encoding="utf-8"))
            want = exp.get("status")
            must = exp.get("codes", [])
            forbid = exp.get("forbid", [])
            ok = ((want is None or res["status"] == want)
                  and all(x in codes for x in must)
                  and all(x not in codes for x in forbid))
            verdict = "PASS" if ok else "FAIL"
            if not ok:
                fails += 1

        rows.append({"case": c.name, "status": res["status"],
                     "error": res["counts"]["error"], "warn": res["counts"]["warn"],
                     "anchors": s.get("anchors", 0), "quoted": s.get("quoted", 0),
                     "verdict": verdict, "codes": codes})
        tot_e += res["counts"]["error"]
        tot_w += res["counts"]["warn"]
        tot_a += s.get("anchors", 0)
        tot_q += s.get("quoted", 0)

    rate = round(tot_q / tot_a, 3) if tot_a else 0
    if args.json:
        print(json.dumps({"cases": rows, "total": {
            "error": tot_e, "warn": tot_w, "anchors": tot_a, "quoted": tot_q,
            "quote_rate": rate, "failed_cases": fails}}, ensure_ascii=False, indent=2))
    else:
        print(f"{'case':<22}{'校验':<8}{'判定':<7}{'err':>4}{'warn':>5}{'锚点':>6}{'带引文':>7}  发现")
        for r in rows:
            print(f"{r['case']:<22}{r['status']:<8}{r['verdict']:<7}{r['error']:>4}"
                  f"{r['warn']:>5}{r['anchors']:>6}{r['quoted']:>7}  {','.join(r['codes']) or '-'}")
        print(f"\n合计 {tot_a} 个锚点，带引文 {tot_q} 个，引文覆盖率 {rate:.1%}；"
              f"错误 {tot_e}，告警 {tot_w}；用例失败 {fails}")
    return d.V_ERROR if fails else d.OK


# ---------------------------------------------------------------- CLI

def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="audit.py", description="蒸馏报告的校验与写盘")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("verify", help="校验报告锚点")
    v.add_argument("report")
    v.add_argument("--src", required=True, help="原文 content.md 或 PDF 转出的 md")
    v.add_argument("--segments", default=None)
    v.add_argument("--json", action="store_true")

    w = sub.add_parser("write", help="校验后原子写入知识库并更新总纲")
    w.add_argument("draft")
    w.add_argument("--vault", required=True)
    w.add_argument("--topic", default=None,
                   help="学科目录：人工智能/心理学/方法论/商业/健康/人文，也可自定；缺省取 frontmatter 的 topic")
    w.add_argument("--summary", default=None,
                   help="总纲里挂的一句话结论；缺省取 frontmatter 的 oneliner")
    w.add_argument("--src", default=None)
    w.add_argument("--segments", default=None)
    w.add_argument("--force", action="store_true")
    w.add_argument("--overwrite", action="store_true", help="覆盖同名报告（仅当用户明确要求更新那篇）")
    w.add_argument("--json", action="store_true")

    e = sub.add_parser("upgrade", help="给只有定位符的旧锚点找候选引文")
    e.add_argument("report")
    e.add_argument("--src", required=True)
    e.add_argument("--segments", default=None)
    e.add_argument("--apply", action="store_true", help="把首选候选直接写回报告")
    e.add_argument("--threshold", type=float, default=0.3,
                   help="自动回填的最低字面重合度（默认 0.3）")
    e.add_argument("--json", action="store_true")

    e2 = sub.add_parser("eval", help="跑标注测试集")
    e2.add_argument("cases")
    e2.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    if args.cmd == "verify":
        res = verify(Path(args.report), Path(args.src),
                     Path(args.segments) if args.segments else None)
        print_verify(res, args.json)
        return exit_code_for(res)
    if args.cmd == "write":
        return cmd_write(args)
    if args.cmd == "upgrade":
        return cmd_upgrade(args)
    if args.cmd == "eval":
        return cmd_eval(args)
    p.print_help()
    return d.E_USAGE


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
