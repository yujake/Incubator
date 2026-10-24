# -*- coding: utf-8 -*-
"""D-43（`draft/146` 末节）：②③ 三件套只对"想升格成数值证明"的那一条要求。

业主原话（唯一权威）：

> 「「程序设计思路/穷举论证」只针对想升格成数值证明的数值实验，对一般数值实验不做要求」

## 现场（r34d 与 cube2 两趟真机同时可见，硬读数）

r34d 的 `000004`-`000009`（`method=numeric`、`evidence_kind=cross_check`/`heuristic`）与
cube2 的 `000001`/`000002`（`numeric`/`cross_check`），
`observations.exhaustion_report.problems` 全都在喊「报告里缺 ['程序设计思路','穷举论证']：
out/experiments/<号>/exhaustion.md」——这些实验本来就不打算当证明，却每条都被要求写三件套，
于是在盘上各落了一份"两块正文各 0 字"的报告，行上还记着 `bytes=0`。

## 口径（改法）

把"要不要 ②③"绑到意图上，而不是绑到 `method` 上。三条入口任一成立才算"想升格"：

1. `method == "exhaustive_search"`；
2. `observations` 里的 `exhaustive` 读到布尔 `true`（与穷尽判定同一读口、同一优先级）；
3. 调用方显式声称 `evidence_kind == "proof"`。

一般数值实验（`numeric` / `cross_check` / `heuristic`）⇒ 不要求报告、不报 `problems`、
不落空文件。已经写了报告的（哪怕不是证明）⇒ 照常读、照常展示，不因此扣分。

## 判据（每条都对着一个改前红）

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | 普通 numeric / cross_check 无报告 ⇒ `problems=[]`、`evidence_kind=cross_check`、不生成 `exhaustion.md` | 改前每条计算类实验都被要求三件套，报告必落、`problems` 必非空 |
| ② | `exhaustive_search` + `exhaustive=true` 缺块 ⇒ 仍报缺块、仍落 cross_check（负控） | 与①同源：改前"要求"是恒真的，②的绿不能证明判据存在 |
| ③ | 三格齐的穷举 ⇒ `evidence_kind=proof`（正控，不许被这次放宽弄坏） | 改前它是绿的；放宽若伤到它，这里必须红 |
| ④ | `heuristic` 那一档 ⇒ 同样不要求报告（它连 cross_check 都不是） | 改前同样被要求三件套 |
| ⑤ | 反真空：把"要不要三件套"的判定打桩成恒 False ⇒ ② 必红；恒 True ⇒ ① 必红 | 判据自身要能红，否则①④的绿可能来自"什么都没判" |

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 一条普通的数值实验脚本：只报"扫了多少点"，没有任何穷尽证据。
#: 它就是 r34d `000004`-`000009` / cube2 `000001`/`000002` 那一档的真身。
NUMERIC_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"points": 100000, "grid": 64},
    "counterexample": None,
    "negation_kind": "not_proved",
}))
"""

#: 一条连结论行都没打的脚本：`_derive` 把它推成 `result=inconclusive`、
#: `evidence_kind=heuristic`（那一档连 cross_check 都不是）。
HEURISTIC_PROBE = """
print("只打印了一些中间读数，没有 REPRO_RESULT")
"""

#: 想升格成证明、但缺第 ③ 块（穷举论证）的脚本：`exhaustive=True` 由调用方递下来，
#: `design` 也有，唯独 `enumeration` 空着。
EXHAUSTIVE_MISSING_ENUM_PROBE = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {"checked": 512, "no_counterexample": True},
}))
"""

#: 三格齐的穷举脚本（正控）：②③ 与 exhaustive 都由脚本自报。
EXHAUSTIVE_FULL_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form "
                        "去掉对称性重数，再按 3-子集/4-子集的对称性剪枝；K_9 的每个染色都落在枚举里，"
                        "无一遗漏；边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None,
    "negation_kind": "not_proved",
    "bound": {"n": 9},
    "strategy": "canonical form + symmetry breaking",
}))
"""

DESIGN = ("把 K_9 的二染色归约成逐点检查：按 4-子集布尔赋值编码，遍历全部 2^36 个染色，"
          "每条边两种颜色都试过")
CERT = {"kind": "enumeration_bound", "detail": {"n_max": 9}}
BOUND = {"n_max": 9, "domain": "9 顶点图的全部二染色"}


def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return rel


def _row(store: Store, out: dict) -> dict:
    rows = [r for r in store.rows("experiments")
            if r["experiment_id"] == out["experiment_id"]]
    assert len(rows) == 1, rows
    return rows[0]


def _run_plain_numeric(tmp_path: pathlib.Path) -> tuple[Store, dict]:
    """跑一条普通数值实验（numeric / cross_check，无意升格成证明）。"""
    store = _store(tmp_path)
    _write(store, "code/scan_points.py", NUMERIC_PROBE)
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "扫描了十万个点", "scan=100000", "code/scan_points.py", method="numeric")
    return store, out


def _run_heuristic(tmp_path: pathlib.Path) -> tuple[Store, dict]:
    """跑一条 heuristic 档的实验（脚本没打结论行）。"""
    store = _store(tmp_path)
    _write(store, "code/no_conclusion.py", HEURISTIC_PROBE)
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "没有结论的一趟", "no_conclusion=1", "code/no_conclusion.py", method="numeric")
    return store, out


def _run_exhaustive_attempt(tmp_path: pathlib.Path,
                            *, with_enumeration: bool) -> tuple[Store, dict]:
    """跑一条"想升格成数值证明"的穷举实验（`method=exhaustive_search` + `exhaustive=true`）。

    `with_enumeration=False` 那一档缺第 ③ 块（穷举论证）——那是 ② 的负控；
    `True` 那一档三格齐 ——那是 ③ 的正控。
    """
    store = _store(tmp_path)
    _write(store, "code/enum_k9.py", EXHAUSTIVE_MISSING_ENUM_PROBE)
    kwargs = dict(method="exhaustive_search", certificate=CERT, search_bound=BOUND,
                  exhaustive=True, design=DESIGN,
                  search_space="2^36 = 68719476736 个二染色")
    if with_enumeration:
        kwargs["enumeration"] = (
            "枚举 K_9 全部 2^36 个二染色；按顶点置换取 canonical form 去掉对称性重数，"
            "再按 3-子集/4-子集的对称性剪枝；每个染色都落在枚举里，无一遗漏；边界 n=9")
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", "code/enum_k9.py", **kwargs)
    return store, out


def _assert_plain_numeric_needs_no_report(tmp_path: pathlib.Path) -> None:
    """① 的正文（被 ⑤-b 打桩之后必须红的那一段）。"""
    store, out = _run_plain_numeric(tmp_path)
    assert out["evidence_kind"] == "cross_check", out
    # 不要求报告 ⇒ 不报 problems
    assert out["report_problems"] == [], out["report_problems"]
    row = _row(store, out)
    assert NP.report_problems(row) == [], NP.report_problems(row)
    # 不落空文件：普通数值实验的目录下没有 exhaustion.md
    report_rel = ER.report_relpath(out["experiment_id"])
    assert out["report_path"] == "", out["report_path"]
    assert out["report_bytes"] == 0, out
    assert not (pathlib.Path(store.root) / report_rel).exists(), (
        f"普通数值实验不该落 {report_rel}")
    # 反真空：这一档仍然是 cross_check，而且"缺什么"照旧说得出（放宽的只是报告那一格）
    signature = NP.signature_of(row)
    assert signature["problems"], "等级判定本身不许被这次放宽弄空"
    assert not any("报告里缺" in str(p) for p in signature["problems"]), signature["problems"]


def _assert_exhaustion_attempt_still_asks_for_the_blocks(tmp_path: pathlib.Path) -> None:
    """② 的正文（被 ⑤-a 打桩之后必须红的那一段）。"""
    store, out = _run_exhaustive_attempt(tmp_path, with_enumeration=False)
    # 想升格的那一条：报告照写（缺块不是"没有报告"），problems 点名缺哪一块
    report_rel = ER.report_relpath(out["experiment_id"])
    assert (pathlib.Path(store.root) / report_rel).is_file(), (
        f"想升格成证明的那一条必须落报告：{report_rel}")
    problems = "；".join(str(p) for p in (out["report_problems"] or []))
    assert ER.BLOCK_EXHAUSTION in problems, out["report_problems"]
    # 缺块 ⇒ 仍落 cross_check
    assert out["evidence_kind"] == NP.SUPPORTED_ONLY_KIND == "cross_check", out
    row = _row(store, out)
    assert NP.report_problems(row), NP.report_problems(row)
    assert NP.is_signed_exhaustion(row) is False
    signature = NP.signature_of(row)
    assert any(ER.BLOCK_EXHAUSTION in str(p) or "enumeration" in str(p)
               for p in (signature.get("problems") or [])), signature.get("problems")


# ------------------------------------------------------------------ ① 普通 numeric 不要求


def test_1_a_plain_numeric_experiment_needs_no_report_and_lands_none(
        tmp_path: pathlib.Path) -> None:
    """① 普通 numeric / cross_check 无报告 ⇒ problems=[]、cross_check、不生成 exhaustion.md。"""
    _assert_plain_numeric_needs_no_report(tmp_path)
    # 再加一条独立的读数：这条实验的盘上确实没有那份报告（不靠 helper 的断言）
    store, out = _run_plain_numeric(pathlib.Path(tmp_path) / "again")
    md_files = list((pathlib.Path(store.root) / ER.REPORT_DIR).glob("*/exhaustion.md"))
    assert md_files == [], [str(p) for p in md_files]
    assert out["evidence_kind"] == "cross_check", out


# ------------------------------------------------------------------ ② 负控：想升格仍要三件套


def test_2_an_exhaustion_attempt_missing_a_block_still_names_it_and_stays_cross_check(
        tmp_path: pathlib.Path) -> None:
    """② exhaustive_search + exhaustive=true 缺块 ⇒ 仍报缺块、仍落 cross_check（负控）。"""
    _assert_exhaustion_attempt_still_asks_for_the_blocks(tmp_path)


def test_2b_the_intent_is_wider_than_the_method_alone(tmp_path: pathlib.Path) -> None:
    """② 的第二半：`method=numeric` 但 `exhaustive=true` 也算"想升格" ⇒ 同样要求三件套。"""
    store = _store(tmp_path)
    _write(store, "code/enum_numeric.py", NUMERIC_PROBE)
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "numeric 但报了 exhaustive=true", "ramsey34=9", "code/enum_numeric.py",
        method="numeric", exhaustive=True, design=DESIGN)
    report_rel = ER.report_relpath(out["experiment_id"])
    assert (pathlib.Path(store.root) / report_rel).is_file(), (
        "exhaustive=true 就是「想升格」的那一条 ⇒ 要落报告")
    problems = "；".join(str(p) for p in (out["report_problems"] or []))
    assert ER.BLOCK_EXHAUSTION in problems, out["report_problems"]
    assert out["evidence_kind"] == "cross_check", out


# ------------------------------------------------------------------ ③ 正控：三格齐仍是 proof


def test_3_a_complete_exhaustion_attempt_is_still_proof(tmp_path: pathlib.Path) -> None:
    """③ 三格齐的穷举 ⇒ evidence_kind=proof（正控；不许被这次放宽弄坏）。"""
    store, out = _run_exhaustive_attempt(tmp_path, with_enumeration=True)
    report_rel = ER.report_relpath(out["experiment_id"])
    report_file = pathlib.Path(store.root) / report_rel
    assert report_file.is_file(), report_rel
    assert out["report_path"] == report_rel, out["report_path"]
    assert out["report_bytes"] > 0, out
    assert out["report_problems"] == [], out["report_problems"]
    assert out["evidence_kind"] == "proof", out
    row = _row(store, out)
    assert NP.is_signed_exhaustion(row) is True, row
    assert NP.report_problems(row) == [], NP.report_problems(row)
    assert ER.landing_problems(row) == [], ER.landing_problems(row)
    blocks, missing = ER.blocks_of(report_file.read_text(encoding="utf-8"))
    assert missing == [], missing
    assert blocks.get(ER.DESIGN, 0) > 0 and blocks.get(ER.ENUMERATION, 0) > 0, blocks


# ------------------------------------------------------------------ ④ heuristic 也不要求


def test_4_a_heuristic_experiment_needs_no_report_either(tmp_path: pathlib.Path) -> None:
    """④ heuristic 那一档 ⇒ 同样不要求报告（它连 cross_check 都不是）。"""
    store, out = _run_heuristic(tmp_path)
    assert out["evidence_kind"] == "heuristic", out
    assert out["report_problems"] == [], out["report_problems"]
    assert out["report_path"] == "", out["report_path"]
    report_rel = ER.report_relpath(out["experiment_id"])
    assert not (pathlib.Path(store.root) / report_rel).exists(), (
        f"heuristic 那一档不该落 {report_rel}")
    row = _row(store, out)
    assert NP.report_problems(row) == [], NP.report_problems(row)
    # 反真空：等级判定本身照旧说得出"缺什么"
    assert NP.signature_of(row)["problems"], "等级判定不许被这次放宽弄空"


# ------------------------------------------------------------------ ⑤ 反真空


def test_5a_stubbing_the_intent_to_false_makes_criterion_2_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤-a 把"要不要三件套"的判定打桩成恒 False ⇒ ② 必红。"""
    monkeypatch.setattr(NP, "wants_numeric_proof", lambda **kw: False, raising=True)
    with pytest.raises(AssertionError):
        _assert_exhaustion_attempt_still_asks_for_the_blocks(tmp_path)


def test_5b_stubbing_the_intent_to_true_makes_criterion_1_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤-b 把"要不要三件套"的判定打桩成恒 True ⇒ ① 必红（普通数值实验又被要求了）。"""
    monkeypatch.setattr(NP, "wants_numeric_proof", lambda **kw: True, raising=True)
    with pytest.raises(AssertionError):
        _assert_plain_numeric_needs_no_report(tmp_path)
