"""`write_lf(path, text)`：把文本按 LF 落盘，永远不做平台换行翻译。

为什么需要它（一条已被实测钉死的机制）：

    Path("x.txt").write_text("a\\nb\\n", encoding="utf-8")   # Windows 上盘里是 b"a\\r\\nb\\r\\n"

`Path.write_text` 缺省 `newline=None` ⇒ 文本层把每个 `\\n` 翻成 `os.linesep`。Windows 的
`os.linesep` 是 `\\r\\n`，于是"跑一次脚本"就把被 git 跟踪的产物改脏：行尾一变，`sha256`
跟着变，而禁 AI 区批准台账钉住的对象正是 `sha256`；`.gitattributes` 的 `text eol=lf`
又会在 `git diff` 时把它折平，所以这种漂移在 diff 里看不见，直到下一次改那个文件。

本模块的落盘不经过文本层：`text.encode(...)` 之后 `Path.write_bytes`。字节是什么就写什么，
`\\r` 只可能来自调用方自己给的文本，不可能来自平台。

用法（一行式）：

    from write_lf import write_lf
    write_lf(dest, "第一行\\n第二行\\n")

    # 从仓库根跑（`tools/` 不在包路径里时）：
    from tools.write_lf import write_lf

纪律：仓库里的文本产物一律 LF。产品代码（`src/agentflow/` 下）不 import 本模块
（交付物不把 `tools/` 带出去），那边的写法是显式 `newline="\\n"` 或 `write_bytes`；
这条纪律的机器判据是 `scripts/lint_rules.py` 的 `R012`，它的报错文案就指到这里。
"""

from __future__ import annotations

import sys
from pathlib import Path

#: 本模块写出的文件永远只有这一个行尾（判据与人类读的是同一个常数，不各写一份）。
LF = "\n"


def write_lf(path: str | Path, text: str, *, encoding: str = "utf-8",
             errors: str = "strict", mkdir: bool = True) -> int:
    """把 `text` 按 LF 落盘到 `path`，返回写入的字节数。

    - `text` 里的 `\\n` 原样成为字节 `0x0a`；不会被翻成 `\\r\\n`（本函数不经过文本模式）；
    - `text` 里如果本来就有 `\\r\\n`，那是调用方的输入，本函数不替它"修"（只保证不新增）；
    - `mkdir=True` 时自动建父目录（产物目录常常还不存在）；
    - 写完不回读：调用方要证明"写进去的就是我给的"，自己回读比对本函数更负责。
    """
    data = text.encode(encoding, errors)
    target = Path(path)
    if mkdir:
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return len(data)


def _selftest() -> int:
    """自检：LF 文本落盘后字节里没有 `\\r`；CRLF 文本不被偷偷"修"；返回三档退出码。"""
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sub" / "a.txt"
        n = write_lf(p, "第一行\n第二行\n")
        raw = p.read_bytes()
        if b"\r" in raw:
            problems.append(f"LF 落盘后出现 CR：{raw!r}")
        if raw != "第一行\n第二行\n".encode("utf-8"):
            problems.append(f"字节与输入不等：{raw!r}")
        if n != len(raw):
            problems.append(f"返回值不是字节数：{n} != {len(raw)}")
        q = Path(d) / "b.txt"
        write_lf(q, "a\r\nb\r\n")
        if q.read_bytes() != b"a\r\nb\r\n":
            problems.append("调用方给的 CRLF 被改掉了（本函数不替人做归一）")
    for msg in problems:
        print(f"[write_lf] FAIL {msg}", file=sys.stderr)
    print(f"[write_lf] {'FAIL' if problems else 'OK'}（写盘一律 LF；平台换行翻译 = 无）")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    """自检入口（`python tools/write_lf.py`）；无参数 ⇒ 跑自检。"""
    _ = argv
    return _selftest()


if __name__ == "__main__":
    raise SystemExit(main())
