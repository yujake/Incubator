# -*- coding: utf-8 -*-
"""判据（NT2，2026-11-15）：三个读点给的命题级读数 = 各路径 min，且逐路径可核。

这一份只钉"读侧三处（页面 / 收工分布 / 论文侧与 T4 清单）读同一份折叠"。
写侧与折叠本体的判据在 `tests/test_nontriviality_is_per_path.py`（P1–P6 / N / V）。

零模型钱：台账由 `secretary.append_nontriviality` 直接落行；工作区全在 `tmp_path`。
"""
from __future__ import annotations

import json
import pathlib
import sys
from typing import Any

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import closing as CL  # noqa: E402
from agentflow import secretary as SEC  # noqa: E402
from agentflow.webui import readers as R  # noqa: E402

_SID = "000901"
_TEXT = "设 G 是有限群，p 是素数；则 G 的 Sylow p-子群存在。"
_PROOF_1 = "证明：取一个极大 p-子群 P，用共轭作用数轨道。"
_PROOF_2 = "证明：用类方程与同余计数，另证一次。"
_LOW = "设 H 是有限群；则 H 的中心非平凡。"
_TEX = ("\\begin{theorem}" + _LOW + "\\end{theorem}\n"
        "标准论证见附录 A.2。\n")


def _ws(tmp_path: pathlib.Path, *, rows: list[dict[str, Any]],
        tex: str = "") -> pathlib.Path:
    root = tmp_path / "ws"
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "statements.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    if tex:
        (root / "out" / "paper").mkdir(parents=True, exist_ok=True)
        (root / "out" / "paper" / "main.tex").write_text(tex, encoding="utf-8")
    return root


def _append(root: pathlib.Path, *, stmt_id: str, path_group: int, level: int,
            text: str, proof: str) -> None:
    before = len(_ledger(root))
    SEC.append_nontriviality(
        root, statement_full=text, level=level, stmt_id=stmt_id,
        path_group=path_group, judged_body_sha256=SEC._judged_body_sha(text, proof),
        landed_body_sha256=SEC._statement_sha(text), basis=f"路径 {path_group}")
    assert len(_ledger(root)) == before + 1, "写入没有真的落一行（夹具造的是空集）"


def _ledger(root: pathlib.Path) -> list[dict[str, Any]]:
    path = SEC.nontriviality_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def test_p7_every_read_point_gives_the_same_statement_min(tmp_path: pathlib.Path) -> None:
    """P7：页面 / 收工分布 / high_tier / 论文侧 / T4 造梯子 五处读同一个命题级 min。

    两路径 T3@1 + T0@2 ⇒ 命题级是 T0：论文侧不许再把"T3 框架塞进附录"报出来
    （它读的是命题级读数，不是某一条路径的读数）。另加一条只有 T3 的命题作为对照，
    证明 T3 那一支仍然有牙（不是"恒不报"）。

    改前红：读侧按 `stmt_id` 折叠成一条、后写胜 ⇒ 这一条读到 T0 还是 T3 取决于写入
    顺序；页面与收工两栏都没有 `paths`/`min_of` 可核（探针 F-2 的键集合里没有它们）。
    """
    root = _ws(tmp_path, rows=[
        {"stmt_id": _SID, "statement_full": _LOW,
         "manuscripts": {"1": "reports/f-proof-000001.md",
                         "2": "reports/f-proof-000002.md"}},
        {"stmt_id": "000905", "statement_full": _TEXT},
    ], tex=_TEX)
    _append(root, stmt_id=_SID, path_group=1, level=3, text=_LOW, proof=_PROOF_1)
    _append(root, stmt_id=_SID, path_group=2, level=0, text=_LOW, proof=_PROOF_2)
    _append(root, stmt_id="000905", path_group=1, level=3, text=_TEXT, proof=_PROOF_1)

    page = R._statement_tier_reading(root, {
        "stmt_id": _SID, "statement_full": _LOW,
        "manuscripts": {"1": "a", "2": "b"}})
    reading = CL.nontriviality_reading(root)
    assert (page["level"], page["label"]) == (0, "T0"), page
    assert len(page["paths"]) == 2 and page["min_of"] == [0, 3], page
    assert reading["counts"]["T0"] == 1 and reading["counts"]["unjudged"] == 0, reading
    assert reading["paths_total"] == 3 and reading["partial_total"] == 0, reading
    high = {h["stmt_id"]: h for h in reading["high_tier"]}
    assert _SID not in high, high   # T3 路径存在，但命题级 min=0 ⇒ 不进 T3/T4 清单
    assert high["000905"]["level"] == 3 and high["000905"]["min_of"] == [3], high
    # 论文侧：T0 的那一条不许被报成"T3 框架塞进附录"；T3 那一条作为对照有牙
    problems = CL.paper_proof_scaffolding_problems(root)
    assert not any(_LOW[:10] in p for p in problems), problems
    t4 = CL.t4_ladder_problems(root)
    assert t4 == [], t4  # 没有任何 T4 ⇒ 空清单（不是"判据失效"：000905 是 T3）
    # cli 那一行读的是同一份读数（结构判据：它必须读 `paths_total` / `partial_total`，
    # 否则"逐路径"只活在 readings 字典里、人看不见）。
    cli_src = (pathlib.Path(_SRC) / "agentflow" / "cli.py").read_text(encoding="utf-8")
    assert "paths_total" in cli_src and "partial_total" in cli_src, (
        "cli 的非平凡性那一行没有逐路径读数（只塞进 readings 字典 = 接线只接了一半）")
