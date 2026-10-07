"""负控演示：把 server.py 的哈希正则临时改回旧的"只认十六进制"版本，看判据是否变红。

用法：
    python -B temp/_negctl_hash.py break     # 改回旧正则（该红）
    python -B temp/_negctl_hash.py restore   # 还原（该绿）
为什么写成文件而不是内联：PowerShell here-string 会吃掉反引号与反斜杠，
内联 python 里的正则字面量会被改写（我在这上面栽过三次）。
"""

from __future__ import annotations

import pathlib
import sys

SERVER = pathlib.Path(r"D:\Incubator\agentflow\src\agentflow\webui\server.py")
NEW = "[A-Za-z0-9_-]{8,}"
OLD = "[0-9a-fA-F]{8,}"


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "break"
    text = SERVER.read_text(encoding="utf-8")
    if mode == "break":
        if NEW not in text:
            print(f"找不到新正则 {NEW} —— 先确认盘上状态")
            return 2
        SERVER.write_text(text.replace(NEW, OLD, 1), encoding="utf-8", newline="")
        print(f"已把哈希正则临时改回旧字母表（{OLD}）")
        return 0
    if mode == "restore":
        # 只有那一处 _HASHED 行上的旧字母表要还原（文档里可能也有这句描述，逐行判）
        lines = []
        for line in text.splitlines(keepends=True):
            if line.startswith("_HASHED = re.compile(") and OLD in line:
                line = line.replace(OLD, NEW, 1)
            lines.append(line)
        SERVER.write_text("".join(lines), encoding="utf-8", newline="")
        print(f"已还原为 {NEW}")
        return 0
    print("用法：break | restore")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
