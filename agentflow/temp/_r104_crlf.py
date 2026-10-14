#!/usr/bin/env python
"""修一个我自己造出来的事故：脚本式改写把 CRLF 文件整篇转成了 LF。

判据：与 HEAD 比，若 HEAD 那一版含 `\r\n` 而工作区这一版不含 ⇒ 就是被转了
（`Path.read_text` 的 universal newlines 干的）。修法：按 HEAD 的行尾风格写回。
"""
from __future__ import annotations

import pathlib
import subprocess

REPO = "D:/Incubator"


def head_bytes(rel: str) -> bytes | None:
    got = subprocess.run(["git", "-C", REPO, "show", f"HEAD:{rel}"],
                         capture_output=True)
    return got.stdout if got.returncode == 0 else None


def main() -> int:
    out = subprocess.run(["git", "-C", REPO, "diff", "--name-only"],
                         capture_output=True, text=True, encoding="utf-8")
    files = [f for f in out.stdout.split() if f.endswith((".py", ".md", ".json", ".txt"))]
    fixed: list[str] = []
    for rel in files:
        p = pathlib.Path(REPO) / rel
        if not p.is_file():
            continue
        old = head_bytes(rel)
        if old is None or b"\r\n" not in old:
            continue
        cur = p.read_bytes()
        if b"\r\n" in cur:
            continue
        p.write_bytes(cur.replace(b"\n", b"\r\n"))
        fixed.append(rel)
        print(f"[crlf] {rel}")
    print(f"修回 CRLF 的文件：{len(fixed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
