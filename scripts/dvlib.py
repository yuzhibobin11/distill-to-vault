#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dvlib.py - distill-to-vault 共享库。

只做四件「不该由 agent 手感决定」的事：

  1. 错误码与 URL 安全校验（SSRF / 大小 / 重定向逐跳）
  2. 锚点语法：解析、渲染、与原文比对（引文必填，这是可审计的底座）
  3. 文本规范化与 sha256（快照可复现的前提）
  4. manifest / frontmatter 的生成与解析（环境无 pyyaml，自实现受限子集）

设计原则：任何「靠 agent 自觉」的判断都下沉到代码，判断不出来就报错。
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import socket
import sys
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

TZ = timezone(timedelta(hours=8))
SCHEMA = 2

# ---------------------------------------------------------------- 错误码

OK = 0
E_USAGE = 2
E_DEP = 3
E_NET = 4
E_BLOCKED = 5
E_EMPTY = 6
E_UNSUPPORTED = 7
E_DL = 8
E_STT = 9
E_VAULT = 10
E_SAFETY = 11      # 新增：URL 不安全（私网 / 非 http / 重定向到内网）
E_TOOBIG = 12      # 新增：超过大小上限

CODE_LABEL = {
    OK: "OK", E_USAGE: "E_USAGE", E_DEP: "E_DEP", E_NET: "E_NET",
    E_BLOCKED: "E_BLOCKED", E_EMPTY: "E_EMPTY", E_UNSUPPORTED: "E_UNSUPPORTED",
    E_DL: "E_DL", E_STT: "E_STT", E_VAULT: "E_VAULT",
    E_SAFETY: "E_SAFETY", E_TOOBIG: "E_TOOBIG",
}

# 校验器专用退出码，与取源错误码错开，避免二义
V_OK, V_ERROR, V_WARN = 0, 20, 21


class SafetyError(Exception):
    """URL 不可请求。绝不允许降级放行。"""


class TooBigError(Exception):
    """超过大小上限。"""


# ---------------------------------------------------------------- 大小上限

LIMITS = {
    "html": 20 * 1024 * 1024,
    "pdf": 50 * 1024 * 1024,
    "media": 2 * 1024 * 1024 * 1024,
    "plain": 20 * 1024 * 1024,
}


# ---------------------------------------------------------------- 文本规范化

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\ufeff\u2060"), None)
_WS = re.compile(r"\s+")
# PDF 文本层会夹带 \x01 \x02 这类控制字符（连字符与软换行的残渣）。
# 它们不是原文的一部分，保留就永远对不上。
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalize(s: str) -> str:
    """比对用的规范化：全半角统一、去零宽与控制字符、空白压成一个、去首尾空白。

    不做大小写折叠 —— 逐字核对必须大小写敏感。
    """
    if not s:
        return ""
    s = s.translate(_ZERO_WIDTH)
    # PDF 抽取常在断行处留下 \x02 之类的控制字符（不是字，是残渣），
    # 不清掉的话人写引文永远命中不了。
    s = _CTRL.sub("", s)
    s = unicodedata.normalize("NFKC", s)   # 全角→半角，兼容字符归一
    s = s.replace("\u00a0", " ").replace("\u3000", " ")
    s = _WS.sub(" ", s)
    return s.strip()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_text(s: str) -> str:
    return sha256_bytes(s.encode("utf-8"))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


# ---------------------------------------------------------------- vault 定位

def _vault_candidates() -> list[Path]:
    """常见 Obsidian 库位置。顺序即优先级，只认「像库」的目录。"""
    home = Path.home()
    docs = home / "Documents"
    out: list[Path] = []
    for base in (docs, home):
        out += [
            base / "Obsidian" / "知识库",
            base / "Obsidian" / "Obsidian Vault",
            base / "Obsidian" / "Notes",
            base / "Obsidian",
            base / "我的知识库",
            base / "knowledge-base",
        ]
    # 老版本硬编码过的默认值，留着防止升级后原地失联
    out.append(Path("E:/football/足球"))
    return out


def _looks_like_vault(p: Path) -> bool:
    if not p.is_dir():
        return False
    return (p / ".obsidian").is_dir() or (p / "知识库").is_dir()


def resolve_vault() -> tuple[Path | None, str]:
    """返回 (vault 目录, 来源)。

    来源：`env`（DISTILL_VAULT）/ `probe`（自动探测到）/ `unset`（没找到，返回 None）。
    没找到时调用方负责打印配置指引，不要静默用某个不存在的路径。
    """
    env = os.environ.get("DISTILL_VAULT")
    if env:
        return Path(env).expanduser(), "env"
    for c in _vault_candidates():
        if _looks_like_vault(c):
            return c, "probe"
    return None, "unset"


def vault_hint(default_path: str = r"D:\我的笔记库") -> str:
    """vault 未配置时给用户看的可复制命令（三选一）。"""
    return "\n".join([
        "vault 没配置。三选一，不要跳过：",
        "  1) 已有 Obsidian 库：设环境变量（设完要重开终端）",
        f'       setx DISTILL_VAULT "{default_path}"',
        "  2) 就这一次：write 时带 --vault <你的库目录>",
        "  3) 还没有库：建一个空目录当知识库也行",
        f'       mkdir "{default_path}" && setx DISTILL_VAULT "{default_path}"',
    ])


# ---------------------------------------------------------------- URL 安全

_PRIVATE_NETS = [
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_BAD_HOSTS = {
    "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal", "metadata", "instance-data",
}


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        return False
    if ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    return not any(ip in net for net in _PRIVATE_NETS)


def assert_url_safe(url: str, allow_private: bool = False) -> str:
    """请求前的硬校验。不通过就抛 SafetyError，不允许「先试一下」。"""
    if allow_private:
        p = urlparse(url)
        if p.scheme not in ("http", "https"):
            raise SafetyError(f"只允许 http/https，收到 scheme={p.scheme!r}")
        return url

    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise SafetyError(f"只允许 http/https，收到 scheme={p.scheme!r}")
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise SafetyError("URL 缺少主机名")
    if host in _BAD_HOSTS:
        raise SafetyError(f"拒绝访问本机/元数据主机: {host}")

    # 直接给 IP 的情况，先按字面判一次（防 DNS 不可用时漏判）
    try:
        if not _ip_is_public(ipaddress.ip_address(host)):
            raise SafetyError(f"拒绝访问内网/保留地址: {host}")
        return url
    except ValueError:
        pass  # 不是字面 IP，继续走 DNS

    try:
        infos = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        # DNS 解析不了就不放行，避免后续行为不可预期
        raise SafetyError(f"域名解析失败: {host} ({e})") from e

    if not infos:
        raise SafetyError(f"域名无可用地址: {host}")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not _ip_is_public(ip):
            raise SafetyError(f"域名 {host} 解析到内网/保留地址 {ip}，拒绝请求")
    return url


# ---------------------------------------------------------------- 安全抓取

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def safe_get(url: str, *, timeout: int = 20, max_bytes: int | None = None,
             referer: str | None = None, allow_private: bool = False,
             max_redirects: int = 5, retries: int = 3):
    """流式抓取：逐跳校验重定向目标，边读边计字节，超限立即中断。

    返回 (final_url, content_bytes, resp_headers)。
    """
    import requests  # 延迟导入，doctor 在无 requests 时仍可跑

    headers = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if referer:
        headers["Referer"] = referer

    limit = max_bytes or LIMITS["html"]
    cur = url
    for hop in range(max_redirects + 1):
        assert_url_safe(cur, allow_private=allow_private)

        last_err = None
        resp = None
        for attempt in range(retries):
            try:
                resp = requests.get(cur, headers=headers, timeout=timeout,
                                    allow_redirects=False, stream=True)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < retries - 1:
                    time.sleep(0.8 * (attempt + 1))
        if resp is None:
            raise ConnectionError(f"请求失败: {last_err}")

        # 429 / 5xx 重试，403 不重试（反爬，重试只会更糟）
        if resp.status_code in (429, 500, 502, 503, 504) and hop == 0:
            time.sleep(1.5)
            continue

        if resp.status_code in (301, 302, 303, 307, 308):
            loc = resp.headers.get("Location")
            resp.close()
            if not loc:
                raise SafetyError("重定向缺少 Location")
            cur = urljoin(cur, loc)
            continue

        buf = bytearray()
        for chunk in resp.iter_content(65536):
            buf.extend(chunk)
            if len(buf) > limit:
                resp.close()
                raise TooBigError(f"超过大小上限 {limit} 字节: {cur}")
        return cur, bytes(buf), dict(resp.headers)

    raise SafetyError(f"重定向超过 {max_redirects} 跳")


# ---------------------------------------------------------------- 锚点语法
#
# 统一形态：  [locator "逐字引文"]
#   段落   [¶012 "该段里逐字出现的一句话"]
#   时间   [12:34 "转写文本里逐字出现的一句"]
#   页节   [p.7 §3.2 "该页该节里逐字出现的一句"]
#   表格   [p.8 Table 2 r5c3 "41.8"]        （单元格拿不到时降级并标 degraded）
#   公式   [p.4 eq.1]                        （无引文＝不可校验，必须显式标注）
#
# 引文可以含 … 或 ... 表示省略，校验时按段顺序查找。

_SEC = r"§\s*(?:\d+(?:\.\d+)*|[A-Za-z][A-Za-z0-9.\-]*(?:\s+[A-Z][A-Za-z0-9.\-]*){0,3}|附录\s*[A-Z]?)"
_PAGE = r"p\.\d{1,4}(?!\d)(?:-\d{1,4})?"
LOCATOR = (r"(?:¶\d{3,4}"
           r"|\d{1,3}:\d{2}(?::\d{2})?"
           r"|" + _PAGE +
           r"(?:\s*" + _SEC + r")?"
           r"(?:\s*Table\s*\d+(?:\s*[rR][A-Za-z0-9]+(?:[cC]\d+)?)?)?"
           r"(?:\s*eq\.\d+)?"
           r"(?:\s*(?:n|fn|脚注)\s*\d+)?"
           r")")
ANCHOR_RE = re.compile(r"\[(" + LOCATOR + r")(?:\s+\"([^\"]{0,400})\")?\]")
CITE_RE = re.compile(r"\[\^(\d{1,3})\]")   # 可选的脚注式引用，供密集报告用

# 疑似锚点：方括号里以 p. / ¶ / 时间戳 / § 开头。用来抓格式漂移——
# 写成 [p.8 脚注 5] 这种，校验器若认不出，就等于没校验，而报告看上去「有锚点」。
SUSPECT_RE = re.compile(r"\[((?:p\.|¶|§|\d{1,3}:\d{2})[^\]\n]{0,60})\]")

QUOTE_MIN, QUOTE_MAX = 8, 160


def parse_anchors(text: str) -> list[dict]:
    """抽出一段文本里所有锚点。"""
    out = []
    for m in ANCHOR_RE.finditer(text):
        out.append({
            "raw": m.group(0),
            "locator": normalize(m.group(1)),
            "quote": normalize(m.group(2) or ""),
            "span": (m.start(), m.end()),
        })
    return out


def render_anchor(locator: str, quote: str = "") -> str:
    locator = normalize(locator)
    quote = normalize(quote)
    if not quote:
        return f"[{locator}]"
    q = quote if len(quote) <= QUOTE_MAX else quote[:QUOTE_MAX - 1] + "…"
    return f'[{locator} "{q}"]'


def split_quote_segments(quote: str) -> list[str]:
    """把含省略号的引文切成有序片段。"""
    parts = re.split(r"…|\.\.\.", quote)
    return [normalize(p) for p in parts if normalize(p)]


def quote_hit(quote: str, haystack: str) -> tuple[bool, str]:
    """引文是否在 haystack 中按序逐字出现。

    返回 (命中, 失败原因)。
    """
    q = normalize(quote)
    h = normalize(haystack)
    if not q:
        return False, "引文为空（v2 要求必须带逐字引文）"
    if len(q) < QUOTE_MIN:
        return False, f"引文过短（{len(q)}<{QUOTE_MIN}），无法构成可核对的证据"

    segs = split_quote_segments(q)
    if not segs:
        return False, "引文只含省略号"
    if len(segs) == 1:
        return (True, "") if q in h else (False, f"引文未在该位置逐字出现: {q[:40]!r}")

    pos = 0
    for seg in segs:
        idx = h.find(seg, pos)
        if idx < 0:
            return False, f"省略片段未按序出现: {seg[:40]!r}"
        pos = idx + len(seg)
    return True, ""


# 支持度四档：替代「标不上就删」
SUPPORT_LEVELS = {
    "S": "supported    位置命中 + 引文逐字命中，可作正文结论",
    "M": "mentioned    位置命中、原文提到但未证明，进局限节，不得当结论",
    "I": "inferred     无原文支持，属我的推断，进判断节并标注非原文",
    "X": "unsupported  校验失败，删除",
}


# ---------------------------------------------------------------- 原文装载


def load_paragraphs(content_md: Path) -> dict[str, str]:
    """解析 fetch 产物：[¶001] 段落文本。"""
    out: dict[str, str] = {}
    for m in re.finditer(r"^\[¶(\d{3,4})\]\s?(.*)$", content_md.read_text(encoding="utf-8"), re.M):
        out[m.group(1)] = m.group(2)
    return out


def load_pages(md: Path) -> dict[int, str]:
    """按 <!-- page N --> 切分，返回页号 → 该页全文。"""
    text = md.read_text(encoding="utf-8")
    marks = [(m.start(), int(m.group(1))) for m in re.finditer(r"<!--\s*page\s+(\d+)\s*-->", text)]
    if not marks:
        return {}
    # page N 的内容从标记之后开始，到「page N+1 标记之前」
    out: dict[int, str] = {}
    for i, (off, num) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        out[num] = text[off:end]
    return out


# PDF 抽取器把章节标题抽成 markdown 标题（`# 3.2 Attention`），但漏抽的也常见，
# 它们退化成独立成行的一行（`3.2.1 Scaled Dot-Product Attention`）。两种都认。
# 正文里被误判成标题的行（`# of the values, …`）不以编号开头，自然排除。
SECTION_RE = re.compile(r"^(#{1,6})[ \t]+(\d+(?:\.\d+)*)[ \t]+(\S.{1,58})$", re.M)
SECTION_BARE = re.compile(r"^(\d+(?:\.\d+)+)[ \t]+([A-Z][^.!?。！？]{2,58})$", re.M)
HEADING_ANY = re.compile(r"^(#{1,6})[ \t]+", re.M)


class Sections(dict):
    """§号 → 节。`by_name` 按标题名索引，供 §Abstract / §References 这类无编号节使用。"""

    def __init__(self):
        super().__init__()
        self.by_name: dict[str, dict] = {}


def _heading_text(text: str, m: re.Match) -> str:
    end = text.find("\n", m.end())
    return text[m.end(): end if end > 0 else len(text)].strip()


def _is_heading(text: str, m: re.Match) -> bool:
    """标题不会是一整段话：短、不以句末标点结尾。"""
    t = _heading_text(text, m)
    if not t or len(t) > 60:
        return False
    return not t.endswith(("。", ".", "!", "?", "；", ";", ","))


def name_key(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())


def load_sections(md: Path) -> Sections:
    """按标题切节，返回 Sections：§号 → {title, text, page, end_page}。

    节文本从该标题之后到「下一个任意标题」之前，所以 §3.2 的文本含它的子节。
    页码用于核对「§3.2 到底在第几页」，防止页码与节号互相矛盾。
    """
    text = md.read_text(encoding="utf-8")
    marks = [(m.start(), int(m.group(1)))
             for m in re.finditer(r"<!--\s*page\s+(\d+)\s*-->", text)]

    def page_at(off: int) -> int:
        cur = 0
        for start, num in marks:
            if start <= off:
                cur = num
            else:
                break
        return cur

    numbered = {m.start(): (m.end(), m.group(2), m.group(3).strip())
                for m in SECTION_RE.finditer(text)}
    numbered.update({m.start(): (m.end(), m.group(1), m.group(2).strip())
                     for m in SECTION_BARE.finditer(text)})

    # 无编号标题（Abstract / References / 附录）也要能按名字定位
    for m in HEADING_ANY.finditer(text):
        if m.start() in numbered:
            continue
        line_end = text.find("\n", m.end())
        title = text[m.end(): line_end if line_end > 0 else len(text)].strip()
        if 0 < len(title) <= 60:
            numbered[m.start()] = (line_end if line_end > 0 else m.end(), None, title)

    heads = sorted(numbered.items())
    if not heads:
        return Sections()

    # 所有标题（含无编号的 References、Abstract）都是节的边界。
    # 但 PDF 抽取会把长段落也标成 heading（`# We also experimented with…`），
    # 那种不能当边界，否则整段内容就掉到节外面去了。
    bounds = {m.start() for m in HEADING_ANY.finditer(text) if _is_heading(text, m)}
    bounds |= {h[0] for h in heads}
    bounds = sorted(bounds)

    out = Sections()
    for off, (body_off, num, title) in heads:
        nxt = next((b for b in bounds if b > off), len(text))
        raw_body = text[body_off:nxt]
        # 尾部只剩页标记/空白时，本节的结束页要按最后一段真正文算，
        # 否则节会「跨到下一页」，页与节互相矛盾就查不出来。
        tail = re.search(r"(?:\s*<!--.*?-->)*\s*$", raw_body, re.S)
        content_end = body_off + (tail.start() if tail else len(raw_body))
        # 页标记/图注注释夹在句子里会让跨页引文无法逐字命中，先清成空格
        seg = re.sub(r"<!--.*?-->", " ", raw_body, flags=re.S).strip()
        start_pg = page_at(off)
        end_pg = page_at(max(off, content_end - 1)) if content_end > body_off else start_pg
        rec = {"title": title, "text": seg, "page": start_pg,
               "end_page": max(start_pg, end_pg)}
        out.by_name.setdefault(name_key(title), rec)
        if num is None:
            continue
        # 同一编号出现多次（PDF 页眉重复标题）时保留最长的那段
        if num in out and len(out[num]["text"]) >= len(seg):
            continue
        out[num] = rec
        out.by_name.setdefault(name_key(num + " " + title), rec)
    return out


def load_segments(path: Path) -> list[dict]:
    """解析 segments.jsonl：{"start":float,"end":float,"text":str}。"""
    segs = []
    if not path.exists():
        return segs
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            segs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return segs


def parse_ts(ts: str) -> float:
    parts = [int(x) for x in ts.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


# ---------------------------------------------------------------- manifest


def write_manifest(path: Path, data: dict) -> None:
    payload = {"schema": SCHEMA, **data}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- frontmatter
#
# 环境没有 pyyaml，且不允许为了一个 frontmatter 去装依赖。
# 这里只实现「我们自己产出的那一种形态」：全部双引号标量 + 块序列。
# 值一律双引号包裹，彻底规避 Windows 路径里的 \f \t 被当成转义。

FM_ORDER = [
    "title", "aliases", "type", "branch", "platform", "source", "source_title",
    "author", "published", "fetched", "tags", "status", "confidence", "coverage",
    "raw_chars", "summary_chars", "degraded", "distill_version", "related",
]

FM_REQUIRED = [
    "title", "type", "branch", "platform", "source", "source_title", "author",
    "published", "fetched", "tags", "status", "confidence", "coverage",
    "raw_chars", "summary_chars", "related",
]

_DQ_ESC = str.maketrans({"\\": "\\\\", '"': '\\"'})


def _scalar(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v) if isinstance(v, float) else str(v)
    s = str(v).translate(_DQ_ESC).replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return f'"{s}"'


def dumps_frontmatter(fm: dict) -> str:
    keys = [k for k in FM_ORDER if k in fm] + [k for k in fm if k not in FM_ORDER]
    lines = ["---"]
    for k in keys:
        v = fm[k]
        if isinstance(v, (list, tuple)):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {_scalar(item)}")
        else:
            lines.append(f"{k}: {_scalar(v)}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _unscalar(s: str):
    s = s.strip()
    if s in ("null", "~", ""):
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if s == "[]":
        return []
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        body = s[1:-1]
        out, i = [], 0
        while i < len(body):
            c = body[i]
            if c == "\\" and i + 1 < len(body):
                n = body[i + 1]
                out.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(n, n))
                i += 2
                continue
            out.append(c)
            i += 1
        return "".join(out)
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if re.fullmatch(r"-?\d+\.\d+", s):
        return float(s)
    return s


def parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    if not m:
        return {}, text
    fm: dict = {}
    cur_list: str | None = None
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and cur_list:
            fm.setdefault(cur_list, []).append(_unscalar(line.lstrip()[2:]))
            continue
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if v == "":
                cur_list = k
                fm[k] = []
            else:
                fm[k] = _unscalar(v)
                cur_list = None
    return fm, text[m.end():]


# ---------------------------------------------------------------- 文件名

_ILLEGAL = re.compile(r'[\\/:*?"|#^\[\]\x00-\x1f]')


def sanitize_name(title: str, max_len: int = 40) -> str:
    s = _ILLEGAL.sub("", title or "")
    s = re.sub(r"\s+", " ", s).strip().strip(".")
    if len(s) > max_len:
        s = s[:max_len].rstrip()
    return s or "untitled"


def unique_path(directory: Path, stem: str, ext: str = ".md", max_total: int = 90) -> Path:
    """重名追加 -2 -3，永不覆盖。"""
    base = stem
    if len(base) + len(ext) > max_total:
        base = base[: max_total - len(ext)]
    p = directory / f"{base}{ext}"
    n = 2
    while p.exists():
        suffix = f"-{n}"
        cut = base[: max_total - len(suffix) - len(ext)]
        p = directory / f"{cut}{suffix}{ext}"
        n += 1
    return p


def atomic_write(path: Path, text: str) -> None:
    """临时文件 + os.replace，避免写一半留下半截报告。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
        f.flush()
    tmp.replace(path)
