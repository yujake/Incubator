"""三份读数的手工复算脚本（题15 选B，2026-10-07）。

跑法（在 agentflow/ 下，PYTHONPATH 指向 src）：

    python -B temp/fanout-fix-readings/probe-anti-vacuum.py

它打印的是"反真空 + 两档上限 + 拒绝报文"，与 `tests/test_fanout_admission.py`
的断言同源（复用那份文件的替身与装配），所以读数与判据不会各说各话。
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "tests"))

import test_fanout_admission as T  # noqa: E402

from agentflow import policy as P  # noqa: E402


def _show(label: str, res) -> None:
    print(f"{label}: outcome={res.outcome} refusal_reason={res.refusal_reason}")
    print(f"          detail={res.detail}")


def main() -> int:
    pol = P.Policy()
    print(f"默认档（工人）上限 = {P.fanout_limit_for(pol, 'H')}；"
          f"主控档上限 = {P.fanout_limit_for(pol, 'M')}")
    with tempfile.TemporaryDirectory(prefix="fanout-probe-") as td:
        c = T._mk_conductor(T._mk_store(pathlib.Path(td)), max_fanout=5)

        # 读数三之一：工人档在 5 处仍然被拒（闸门没被拆掉）
        worker_parent = T._parent(c, doc_id="0001")
        for i in range(5):
            assert T._revise(c, worker_parent, f"w{i}", by="H").outcome == "ok"
        _show("工人档第 6 件（H）", T._revise(c, worker_parent, "w5", by="H"))

        # 读数三之二：触顶后连续尝试，读数不涨（自我毒化已修）
        for i in range(3):
            T._revise(c, worker_parent, f"w-over{i}", by="H")
        print(f"工人档触顶后又试了 3 次：台账子行 = "
              f"{len(c._children_of(worker_parent))}，受理数 = "
              f"{len(c._admitted_children_of(worker_parent))}（后者不随拒绝上涨）")

        # 读数二：主控在同一代码路径上派得进 20 件，第 21 件才被拒且报文写着 20
        boss_parent = T._parent(c, doc_id="0002")
        got = [T._revise(c, boss_parent, f"m{i:02d}", by="M") for i in range(20)]
        print(f"主控档前 20 件 outcome = {sorted({k.outcome for k in got})}")
        _show("主控档第 21 件（M）", T._revise(c, boss_parent, "m20", by="M"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
