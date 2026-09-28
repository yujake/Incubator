"""终端呈现层：给 CLI 一套统一、好看、且在任何终端上都不会崩的输出原语。

## 为什么单独成模块

好看这件事最容易变成"每个命令各写各的"：一处用 `=== 标题 ===`、一处用 `####`、一处直接
`print` 一个 dict。结果是同一个工具的输出风格随命令变，而用户读到的是"这堆东西是一堆脚本
拼起来的"。这里把"一屏怎么排"收成一套原语，`cli.py` 只负责选原语。

## 三条不许越过的底线（都来自本项目踩过的坑）

1. 编码不许崩。控制台是 GBK 时 `⇒`/制表符/勾号都可能编不出来，`print` 抛
   `UnicodeEncodeError` ⇒ 进程以 1 结束 —— 而 1 在本项目的三态里是"查过了、有问题"。
   `console.pin_utf8()` 钉的是编码；本模块再钉一层：先问编码能不能表示这些符号，
   不能就用 ASCII 版（`+---+` / `[ok]`）。
2. 管道里不许出现转义序列。`stdout` 不是 tty（被重定向、被 `Tee-Object`、被 CI 捕获）时
   一律不带颜色 —— 否则日志里会混进 `\x1b[36m`，而人读的时候只会觉得"这工具脏"。
   判据是 `style_enabled()`：tty + `NO_COLOR` 未设 + `TERM != dumb` + 终端支持 VT。
3. 宽度要一致。所有框、表、分隔线的宽度都取自同一个 `width()` 调用点
   （缺省 100，窄终端自动收窄到 `columns`，最窄 56）。同一屏里两个框宽度不一样，
   看上去就是没做完。

## 样式与语义的对应（三态不许折平）

`badge()` 只认 `USAGE` 里登记的那几个状态名，其中 `ok` / `failed` / `unknown` 正好对上
本项目的三态（成功 / 查过了失败 / 没查成）。把 `unknown` 画成灰色而不是红色，是刻意的：
它说的是"没查成"，不是"坏了" —— 颜色分得开，读的人才会去做不同的动作。
"""

from __future__ import annotations

import os
import shutil
import sys
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

__all__ = [
    "ANSI",
    "Style",
    "badge",
    "bullet",
    "kv_lines",
    "panel",
    "paint",
    "progress_line",
    "rule",
    "set_style",
    "style_enabled",
    "table",
    "truncate",
    "width",
]

#: 颜色码。键就是语义名，不是颜色名 —— 这样换配色不用改调用点。
ANSI: dict[str, str] = {
    "reset": "\x1b[0m",
    "bold": "\x1b[1m",
    "dim": "\x1b[2m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
    "grey": "\x1b[90m",
}

#: Unicode 版与 ASCII 版两套画线字符。选哪一套由"当前编码能不能表示"决定。
_BOX = {
    "unicode": {"h": "─", "v": "│", "tl": "┌", "tr": "┐", "bl": "└", "br": "┘",
                "lt": "├", "rt": "┤", "tt": "┬", "bt": "┴", "x": "┼",
                "ok": "✓", "bad": "✗", "warn": "!", "dot": "·", "arrow": "→"},
    "ascii": {"h": "-", "v": "|", "tl": "+", "tr": "+", "bl": "+", "br": "+",
              "lt": "+", "rt": "+", "tt": "+", "bt": "+", "x": "+",
              "ok": "+", "bad": "x", "warn": "!", "dot": "*", "arrow": "->"},
}

#: 状态名 → (显示文本, 颜色, unicode/ascii 字形键)。键集合是封闭的：
#: 没登记的状态名会被 `badge` 原样打出来（宁可露出一个陌生词，也不编一个颜色）。
USAGE: dict[str, tuple[str, str, str]] = {
    "ok": ("ok", "green", "ok"),
    "pass": ("pass", "green", "ok"),
    "produced": ("produced", "green", "ok"),
    "verified": ("verified", "green", "ok"),
    "success": ("success", "green", "ok"),
    "warm": ("warm", "cyan", "ok"),
    "cold": ("cold", "blue", "dot"),
    "failed": ("failed", "red", "bad"),
    "fail": ("fail", "red", "bad"),
    "error": ("error", "red", "bad"),
    "not_found": ("not_found", "red", "bad"),
    "unknown": ("unknown", "yellow", "warn"),
    "not_checked": ("没查成", "yellow", "warn"),
    "not_produced": ("not_produced", "grey", "dot"),
    "skipped": ("skipped", "grey", "dot"),
    "skipped_limit": ("skipped_limit", "grey", "dot"),
    "already_present": ("已在库", "grey", "dot"),
    "unreadable": ("unreadable", "yellow", "warn"),
    "ingested": ("已登记", "green", "ok"),
}


@dataclass
class Style:
    """一份呈现配置：颜色开关、字符集、宽度。测试里直接造它，不依赖真实终端。"""

    color: bool = False
    charset: str = "ascii"
    width: int = 100

    #: 闭集合，`set_style` 只认这两个取值；别的值当编码错误当场抛。
    CHARSETS: tuple[str, ...] = ("unicode", "ascii")


_STYLE = Style()


def _can_encode(text: str, stream: Any = None) -> bool:
    enc = getattr(stream or sys.stdout, "encoding", None) or "utf-8"
    try:
        text.encode(enc)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def _vt_ok() -> bool:
    """终端能不能吃 ANSI。非 Windows 直接看 isatty；Windows 上还要问一句 VT 模式。"""
    if not getattr(sys.stdout, "isatty", lambda: False)():
        return False
    if os.name != "nt":
        return True
    try:  # pragma: no cover - 只在真 Windows 控制台上走到
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004
        if mode.value & enable_vt:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except Exception:  # noqa: BLE001 - 问不出来就按"不支持"处理（宁可不带色）
        return False


def style_enabled(stream: Any = None) -> bool:
    """颜色总开关：tty + `NO_COLOR` 未设 + `TERM != dumb` + 终端支持 VT。"""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "").lower() == "dumb":
        return False
    return _vt_ok()


def set_style(*, color: bool | None = None, charset: str | None = None,
              width_px: int | None = None) -> Style:
    """设置全局呈现配置，返回新的那份。`None` 表示"按环境自动判断"。"""
    global _STYLE
    cs = charset
    if cs is None:
        cs = "unicode" if _can_encode("─│✓✗") else "ascii"
    if cs not in Style.CHARSETS:
        raise ValueError(f"charset 只能是 {Style.CHARSETS} 之一，收到 {cs!r}")
    _STYLE = Style(
        color=style_enabled() if color is None else bool(color),
        charset=cs,
        width=width_px if width_px is not None else default_width(),
    )
    return _STYLE


def default_width(minimum: int = 56, maximum: int = 100) -> int:
    """一屏多宽：取终端列数，收在 `[minimum, maximum]` 里。"""
    try:
        cols = shutil.get_terminal_size((maximum, 24)).columns
    except OSError:  # pragma: no cover - 极少数环境拿不到
        cols = maximum
    return max(minimum, min(int(cols) - 2, maximum))


def width() -> int:
    """当前一屏宽度（`set_style` 定下的那个值）。所有框 / 表 / 线都取这一个数。"""
    return _STYLE.width


def _glyph(key: str) -> str:
    return _BOX[_STYLE.charset][key]


def paint(text: Any, *styles: str) -> str:
    """按语义名上色。没开颜色时原样返回（调用点不必写 if）。"""
    s = str(text)
    if not _STYLE.color or not styles:
        return s
    codes = "".join(ANSI.get(name, "") for name in styles)
    return f"{codes}{s}{ANSI['reset']}"


def display_width(text: Any) -> int:
    """一行的显示宽度（列数），不是字符数。

    为什么不能用 `len()`：中文、全角标点在等宽终端里占两列。用 `len()` 补空格，
    中文行看起来就会短一截、框线对不齐 —— 而"框对不齐"正是那种"看上去没做完"的
    细节。判定用 `unicodedata.east_asian_width`：`W`(宽) 与 `F`(全角) 记 2，其余记 1。
    零宽字符（组合符、变体选择符）记 0。
    """
    total = 0
    for ch in str(text):
        if unicodedata.combining(ch):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def pad(text: Any, target: int, *, align: str = "left") -> str:
    """按显示宽度补齐到 `target` 列（超了就截）。"""
    s = str(text)
    fill = max(0, target - display_width(s))
    if align == "right":
        return " " * fill + s
    if align == "center":
        left = fill // 2
        return " " * left + s + " " * (fill - left)
    return s + " " * fill


def truncate(text: Any, limit: int, ellipsis: str = "…") -> str:
    """按显示宽度截断（不是按字符数：中文一个字占两列）。"""
    s = " ".join(str(text).split())
    if limit <= 0:
        return ""
    if display_width(s) <= limit:
        return s
    room = limit - display_width(ellipsis)
    if room <= 0:
        ellipsis, room = "", limit
    out = ""
    used = 0
    for ch in s:
        w = display_width(ch)
        if used + w > room:
            break
        out += ch
        used += w
    return out + ellipsis


def rule(title: str = "", *, char: str | None = None) -> str:
    """一条分隔线，可带标题（标题在左，线补满整宽）。"""
    w = width()
    ch = char or _glyph("h")
    if not title:
        return paint(ch * w, "grey")
    head = f"{ch}{ch} {title} "
    return paint(head + ch * max(0, w - display_width(head)), "grey")


def kv_lines(pairs: Iterable[tuple[str, Any]], *, key_width: int = 18,
             indent: str = "  ") -> list[str]:
    """键值对的多行呈现：键按显示宽度对齐、值过长截断而不是撑破屏幕。"""
    out: list[str] = []
    for key, value in pairs:
        text = truncate(value, max(8, width() - key_width - display_width(indent) - 4))
        out.append(f"{indent}{paint(pad(key, key_width), 'grey')}{text}")
    return out


def panel(title: str, pairs: Iterable[tuple[str, Any]] = (), *,
          body: Sequence[str] = (), tone: str = "cyan",
          verbatim: Sequence[tuple[str, Any]] = ()) -> list[str]:
    """一个带标题的框：里面先键值对，再自由正文行。返回行列表（调用方自己 print）。

    宽度以 `width()` 为准，每一行都按显示宽度补齐 —— 中文行也照样对齐。

    `verbatim` 是"不许截断"的那些键值对（路径、命令）：它们画在框外面、
    整行原样打印。为什么不能塞进框里：框内要补齐才能对齐，而值一长就得截断，
    截断后的路径抄不下来 —— 那正是"为了好看把可用性弄没了"那一类缺陷。
    实测（2026-09-28，post7 全量套件抓到）：`产物目录` 被截成 `...\cli-out…`，
    而它的整条路径正是用户下一步要 `cd` 进去的地方。
    """
    w = width()
    b = {k: _glyph(k) for k in ("h", "v", "tl", "tr", "bl", "br")}
    inner = w - 4
    key_w = min(20, max(8, inner // 3))
    head = f"{b['h']}{b['h']} {paint(title, 'bold', tone)} "
    lines = [paint(head + b["h"] * max(0, w - 2 - display_width(head)), tone) + paint(b["tr"], tone)]
    lines[0] = paint(b["tl"], tone) + lines[0]
    for key, value in pairs:
        text = truncate(value, inner - key_w)
        lines.append(f"{paint(b['v'], tone)} {paint(pad(key, key_w), 'grey')}"
                     f"{pad(text, inner - key_w)} {paint(b['v'], tone)}")
    for row in body:
        for chunk in _wrap(str(row), inner):
            lines.append(f"{paint(b['v'], tone)} {pad(chunk, inner)} {paint(b['v'], tone)}")
    lines.append(paint(b["bl"] + b["h"] * (w - 2) + b["br"], tone))
    for key, value in verbatim:
        # 不补齐、不画右边框：这一行的价值就是"整条抄得下来"。
        lines.append(f"  {paint(pad(key, key_w), 'grey')}{value}")
    return lines


def _wrap(text: str, limit: int) -> list[str]:
    """按显示宽度折行（英文按词、超长词硬切、中文逐字）。"""
    words = text.split(" ")
    out: list[str] = []
    cur = ""
    for word in words:
        cand = f"{cur} {word}".strip()
        if display_width(cand) <= limit:
            cur = cand
            continue
        if cur:
            out.append(cur)
        while display_width(word) > limit:
            cut = ""
            used = 0
            for ch in word:
                w = display_width(ch)
                if used + w > limit:
                    break
                cut += ch
                used += w
            out.append(cut)
            word = word[len(cut):]
        cur = word
    out.append(cur)
    return out or [""]


def table(headers: Sequence[str], rows: Sequence[Sequence[Any]], *,
          aligns: Sequence[str] | None = None, max_col: int = 44) -> list[str]:
    """一个画线的表。列宽按显示宽度定，总和超过屏宽时按比例收窄。"""
    cols = len(headers)
    aligns = list(aligns or ["left"] * cols)
    body = [[truncate(c, max_col) for c in row] for row in rows]
    widths = [display_width(str(headers[i])) for i in range(cols)]
    for row in body:
        for i in range(cols):
            widths[i] = max(widths[i], display_width(row[i]))
    budget = width() - (3 * cols + 1)
    if sum(widths) > budget:
        scale = budget / max(1, sum(widths))
        widths = [max(6, int(x * scale)) for x in widths]
    b = {k: _glyph(k) for k in ("h", "v", "tl", "tr", "bl", "br", "lt", "rt", "tt", "bt", "x")}

    def _row(cells: Sequence[str], *, head: bool = False) -> str:
        out = []
        for i, cell in enumerate(cells):
            text = truncate(cell, widths[i])
            out.append(" " + pad(text, widths[i], align="left" if head else aligns[i]) + " ")
        joiner = paint(b["v"], "grey")
        return f"{paint(b['v'], 'grey')}{joiner.join(out)}{paint(b['v'], 'grey')}"

    top = b["tl"] + b["tt"].join(b["h"] * (w + 2) for w in widths) + b["tr"]
    mid = b["lt"] + b["x"].join(b["h"] * (w + 2) for w in widths) + b["rt"]
    bottom = b["bl"] + b["bt"].join(b["h"] * (w + 2) for w in widths) + b["br"]
    lines = [paint(top, "grey"), _row([str(h) for h in headers], head=True),
             paint(mid, "grey")]
    for row in body:
        lines.append(_row(row))
    lines.append(paint(bottom, "grey"))
    return lines


def badge(state: str) -> str:
    """三态徽标。登记过状态名就给颜色与字形；没登记就原样打出来（不编）。"""
    key = str(state)
    known = USAGE.get(key)
    if known is None:
        return f"{paint(_glyph('warn'), 'yellow')} {key}"
    text, tone, glyph = known
    return f"{paint(_glyph(glyph), tone)} {paint(text, tone)}"


def bullet(text: str, *, tone: str = "grey", indent: int = 2) -> str:
    """项目符号行（缩进 + 一个点）。正文行要用它，别自己拼空格。"""
    return f"{' ' * indent}{paint(_glyph('dot'), tone)} {text}"


def progress_line(done: int, total: int, text: str = "", *, bar: int = 24) -> str:
    """一行进度条（调用方自己决定用 `\r` 重画还是逐行打）。"""
    total = max(1, int(total))
    ratio = max(0.0, min(1.0, done / total))
    filled = int(ratio * bar)
    fill_ch = "█" if _STYLE.charset == "unicode" else "#"
    empty_ch = "░" if _STYLE.charset == "unicode" else "-"
    pct = f"{ratio * 100:5.1f}%"
    tail = f" {truncate(text, max(10, width() - bar - 18))}" if text else ""
    return (f"{paint(fill_ch * filled, 'cyan')}{paint(empty_ch * (bar - filled), 'grey')}"
            f" {pct}{tail}")
