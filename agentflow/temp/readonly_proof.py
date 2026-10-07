# -*- coding: utf-8 -*-
"""只读证据（题 6 的硬约束①）：跑一次接线后的出口，工作区逐字节没变。

做法：递归算工作区里每个文件的 sha256 + 每个目录的条目集合，
跑 CLI（`closing`，即接线所在的那个出口），再算一次，逐条对拍。
不依赖 mtime（同一个时钟粒度下 mtime 会骗人），用的是内容哈希。
"""
from __future__ import annotations

import hashlib
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_review_acceptance import _good  # noqa: E402


def snapshot(root: pathlib.Path) -> dict[str, str]:
    """工作区的逐路径读数：文件记内容 sha256，目录记 `dir:` 一行（空目录也算）。"""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        if p.is_dir():
            out[rel + "/"] = "dir:" + ",".join(sorted(q.name for q in p.iterdir()))
        else:
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="wire_readonly_"))
    st, report = _good(ws)
    from agentflow import cli
    from agentflow import sessions as SS

    before = snapshot(ws)
    code = cli.main(["--plain", "--root", str(st.root), "closing",
                     "--project-dir", str(st.root), "--report", str(report),
                     "--cap-usd", "1.0", "--acceptance-sid", SS.session_id()])
    after = snapshot(ws)
    print(f"# 工作区：{ws}")
    print(f"# 出口退出码：{code}")
    print(f"# 跑之前 {len(before)} 个路径读数；跑之后 {len(after)} 个")
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    print(f"# 新增：{added or '（无）'}")
    print(f"# 消失：{removed or '（无）'}")
    print(f"# 内容变了：{changed or '（无）'}")
    print("# 结论：" + ("只读（工作区逐字节没变）" if not (added or removed or changed)
                       else "写了盘 —— 与「只读接线」这条硬约束不符"))
    return 0 if not (added or removed or changed) else 1


if __name__ == "__main__":
    raise SystemExit(main())
