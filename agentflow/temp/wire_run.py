# -*- coding: utf-8 -*-
"""真跑一次接线后的生产路径（题 6 选 A = 接线）：从 CLI 出口进去，不 import reviewaccept。

产出：`temp/wire_run_out.txt`（人读的原始输出）。这个脚本只是"开车"，
判据在 `tests/test_release_acceptance_wiring.py` 里。
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from test_review_acceptance import _good  # noqa: E402  （夹具只有一份，不另抄）


def main() -> int:
    ws = pathlib.Path(tempfile.mkdtemp(prefix="wire_revacc_"))
    st, report = _good(ws)
    from agentflow import sessions as SS

    # 夹具的提问落在「缺省会话」里（`ask_user(sid=None)` ⇒ 写入那一刻的
    # `session_id()`）。外部调用方想知道"是哪一段会话"，唯一诚实的来源就是同一处。
    sid = SS.session_id()
    print(f"# 工作区：{st.root}")
    print(f"# 报告：{report}")
    print(f"# 缺省会话号（夹具的提问落在这里）：{sid}")
    print(f"# 命令行：agentflow --root <ws> closing --project-dir <ws> "
          f"--cap-usd 1.0 --acceptance-sid {sid}")
    print("# ---- 以下为 CLI 原始输出 ----")
    from agentflow import cli

    code = cli.main(["--plain", "--root", str(st.root), "closing",
                     "--project-dir", str(st.root),
                     "--report", str(report),
                     "--cap-usd", "1.0",
                     "--acceptance-sid", sid])
    print(f"# ---- CLI 退出码：{code} ----")

    print("")
    print("# ==== 负控对照：把接线摘掉（--no-review-acceptance）====")
    code2 = cli.main(["--plain", "--root", str(st.root), "closing",
                      "--project-dir", str(st.root),
                      "--report", str(report),
                      "--cap-usd", "1.0",
                      "--acceptance-sid", sid,
                      "--no-review-acceptance"])
    print(f"# ---- CLI 退出码：{code2} ----")

    print("")
    print("# ==== 负控对照：不给 --acceptance-sid（会话身份缺 ⇒ 三态分支那一格必须没查成）====")
    code3 = cli.main(["--plain", "--root", str(st.root), "closing",
                      "--project-dir", str(st.root),
                      "--report", str(report),
                      "--cap-usd", "1.0"])
    print(f"# ---- CLI 退出码：{code3} ----")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
