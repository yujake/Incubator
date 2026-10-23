# -*- coding: utf-8 -*-
"""D-33（`draft/146` 附录）：穷举证明的三格凭据必须能从工具面递下来。

## 真机现场（r34b，2026-10-23 夜）

r34b 跑了 4 条 `exhaustive_search`，`evidence_kind` 全是 `cross_check`；每条
`observations.exhaustion_report` 都是「报告里缺 ['程序设计思路','穷举论证','运行环境']」。
根因不是模型不会写：提示词要求「跑之前先报三件套 + 把 `exhaustive` 写成布尔」，
而 `verify.run_experiment` 的参数面里没有 `design` / `enumeration` / `exhaustive`
这三格 —— 工具面收不下，E 就只能传空 `params`，于是 ②③ 落不成。

## 这一组守六条

1. 工具面收得下那四格（`design` / `enumeration` / `exhaustive` / `search_space`）：
   工具 schema 里真的广告着，且按它调用不会被判成未知参数；
2. 三格齐 + `exhaustive=true` ⇒ 报告非空（`bytes > 0`）且 `numericproof` 判 `proof`；
3. 缺 `enumeration` ⇒ 报告照样落盘（非空）但三块不齐，等级落 `cross_check`，
   并且点名缺 `穷举论证`（不是只说一句「不合格」）；
4. 不给 `exhaustive`、或给 `false` ⇒ 只能 `cross_check`（缺省不是 true）；
5. 反真空：把「三格齐」这条判定打桩成恒真 ⇒ 第 3 条必红；
6. 真机形状复现：用 r34b 那种调用（`method='exhaustive_search'` + 三格齐）跑一次，
   从台账那一行读到 `evidence_kind=proof`、签名者 V、报告字节数与 sha256 都在。

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import hashlib
import inspect
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import capabilities as CAP  # noqa: E402
from agentflow import exhaustionreport as ER  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow.agent_e import AgentE  # noqa: E402
from agentflow.conductor import Conductor, LocalBackend  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

#: r34b 那种脚本：只报结论行，不自己报 ②③（这正是真机里的形态 —— E 交不出那三格）。
_EXHAUSTIVE_SCRIPT = """
import json
print("REPRO_RESULT: " + json.dumps({
    "result": "supports",
    "observations": {"checked": 512, "no_counterexample": True},
}))
"""

_SCRIPT_REL = "code/enum_k9.py"

_CERT = {"kind": "enumeration_bound", "detail": {"n_max": 9}}
_BOUND = {"n_max": 9, "domain": "9 顶点图的全部二染色"}

_DESIGN = ("把 K_9 的二染色归约成逐点检查：按 4-子集布尔赋值编码，遍历全部 2^36 个染色，"
           "每条边两种颜色都试过")
_ENUM = ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form 去掉"
         "对称性重数，再按 3-子集/4-子集的对称性剪枝；K_9 的每个染色都落在枚举里，无一遗漏；"
         "边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖")
_SPACE = "2^36 = 68719476736 个二染色（C(9,2)=36 条边各两种颜色）"

#: 调用时「这一格不给」的哨兵（`None` 是合法的显式取值，不能拿它当缺省）。
_DROP = object()

_BASE = {
    "claim": "R(3,4)=9（K_9 的二染色穷举）",
    "claim_key": "ramsey34=9",
    "script_path": _SCRIPT_REL,
    "method": "exhaustive_search",
    "certificate": _CERT,
    "search_bound": _BOUND,
    "design": _DESIGN,
    "enumeration": _ENUM,
    "exhaustive": True,
    "search_space": _SPACE,
}

_KEYS = ("design", "enumeration", "exhaustive", "search_space")


def _wired(tmp: pathlib.Path, body: str = _EXHAUSTIVE_SCRIPT):
    ws = pathlib.Path(tmp) / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    cond = Conductor(st, backend=LocalBackend({}))
    reg = build_registry(store=st, conductor=cond, workspace_root=str(ws)).registry
    target = ws / _SCRIPT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return st, reg, ws


def _call(reg, **over):
    """按 r34b 的形状调一次 `verify.run_experiment`（`over` 里的 `_DROP` 表示不给那一格）。"""
    params = dict(_BASE)
    for key, value in over.items():
        if value is _DROP:
            params.pop(key, None)
        else:
            params[key] = value
    return reg.call("verify.run_experiment", role="E", **params)


def _row(st: Store, out: dict) -> dict:
    eid = out["experiment_id"]
    rows = [r for r in st.rows("experiments") if r["experiment_id"] == eid]
    assert len(rows) == 1, rows
    return rows[0]


# ---------------------------------------------------------------- ① 工具面收得下


def test_1_the_tool_surface_accepts_the_four_exhaustion_fields(tmp_path: pathlib.Path) -> None:
    """① 那四格在工具 schema 里，且按它调用真的能落地（不是「广告了但收不下」）。"""
    _st, reg, _ws = _wired(tmp_path)
    tool_props = (reg.get("verify.run_experiment").params or {}).get("properties") or {}
    for key in _KEYS:
        assert key in tool_props, f"工具 schema 没广告 {key}：{sorted(tool_props)}"
    # 两层对账（能力表是派活面的真身）：动作表与工具 schema 必须同名
    action = next(a for a in CAP.actions_for("E") if a.action == "run_experiment")
    action_props = (action.params or {}).get("properties") or {}
    for key in _KEYS:
        assert key in action_props, f"动作表没广告 {key}：{sorted(action_props)}"
    # 方法层（实现侧）也得收得住，否则「声明的」与「收得下的」又是两件事
    sig = inspect.signature(AgentE.run_experiment).parameters
    for key in _KEYS:
        assert key in sig, f"AgentE.run_experiment 不收 {key}：{sorted(sig)}"

    res = _call(reg)
    assert res.ok, (res.error, res.meta)


# ---------------------------------------------------------------- ② 三格齐 ⇒ proof


def test_2_all_three_blocks_land_a_non_empty_report_and_numericproof_says_proof(
        tmp_path: pathlib.Path) -> None:
    """② 三格齐 + `exhaustive=true` ⇒ 报告非空，且这一条够 `proof`（判据在 numericproof）。"""
    st, reg, ws = _wired(tmp_path)
    res = _call(reg)
    assert res.ok, (res.error, res.meta)
    out = res.data
    assert out["report_bytes"] > 0, out
    report_file = ws / out["report_path"]
    assert report_file.is_file(), out["report_path"]
    text = report_file.read_text(encoding="utf-8")
    assert text.strip(), "报告是空的（连标题都没落）"
    blocks, missing = ER.blocks_of(text)
    assert missing == [], missing
    for key in ("design", "enumeration", "environment"):
        assert blocks.get(key, 0) > 0, (key, blocks)
    # 报告里那两段就是调用方递下来的原文（不是别处抄来的）
    assert _DESIGN in text and _ENUM in text
    # 等级：numericproof 的那一份判定也必须是 proof（拿行上的同一批事实再算一遍，
    # 判据不在测试里重写一份 —— 包括那一份报告的落盘读数）
    row = _row(st, out)
    obs = dict(row.get("observations") or {})
    verdict = NP.exhaustion_verdict(
        method="exhaustive_search", observations=obs,
        certificate=_CERT, search_bound=_BOUND, code_path=_SCRIPT_REL, result="supports")
    assert verdict["problems"] == [], verdict["problems"]
    assert verdict["evidence_kind"] == "proof", verdict
    # 台账那一行也必须是 proof（它还要过落盘核查那一关）
    assert row["evidence_kind"] == "proof", (row["evidence_kind"], out["report_problems"])
    # observations 里如实记着调用方报的那两格
    assert obs.get("exhaustive") is True, obs.get("exhaustive")
    assert obs.get("search_space") == _SPACE, obs.get("search_space")


# ---------------------------------------------------------------- ③ 缺一格 ⇒ cross_check


def test_3_a_missing_enumeration_still_lands_a_report_but_names_what_is_missing(
        tmp_path: pathlib.Path) -> None:
    """③ 缺 `enumeration` ⇒ 报告非空但不齐，等级落 `cross_check` 并点名缺穷举论证。"""
    st, reg, ws = _wired(tmp_path)
    res = _call(reg, enumeration=_DROP)
    assert res.ok, (res.error, res.meta)
    out = res.data
    report_file = ws / out["report_path"]
    assert report_file.is_file(), "报告照样要落盘（缺一块不是「没有报告」）"
    text = report_file.read_text(encoding="utf-8")
    assert text.strip(), "报告是空文件"
    assert ER.BLOCK_EXHAUSTION in text, "标题应当照写，缺的是那一段正文"
    blocks, missing = ER.blocks_of(text)
    assert ER.BLOCK_EXHAUSTION in missing, missing
    assert blocks.get(ER.DESIGN, 0) > 0, blocks
    assert out["evidence_kind"] == NP.SUPPORTED_ONLY_KIND == "cross_check", out
    # 点名缺哪一格：落盘读数与签名两处都要说得出「穷举论证」
    report_problems = "；".join(str(p) for p in (out["report_problems"] or []))
    assert ER.BLOCK_EXHAUSTION in report_problems, out["report_problems"]
    row = _row(st, out)
    signature = NP.signature_of(row)
    assert any(ER.BLOCK_EXHAUSTION in str(p) or "enumeration" in str(p)
               for p in (signature.get("problems") or [])), signature.get("problems")
    assert NP.is_signed_exhaustion(row) is False


# ---------------------------------------------------------------- ④ 没有 true ⇒ 只能支持


def test_4_without_a_boolean_true_flag_it_can_only_be_cross_check(
        tmp_path: pathlib.Path) -> None:
    """④ 不给 `exhaustive`（或给 `false`）⇒ 只能 `cross_check`（缺省不是 true）。"""
    for label, over in (("absent", _DROP), ("false", False)):
        st, reg, _ws = _wired(pathlib.Path(tmp_path) / label)
        res = _call(reg, exhaustive=over)
        assert res.ok, (label, res.error, res.meta)
        out = res.data
        assert out["evidence_kind"] == "cross_check", (label, out)
        signature = NP.signature_of(_row(st, out))
        problems = "；".join(str(p) for p in (signature.get("problems") or []))
        assert "exhaustive" in problems, (label, signature.get("problems"))


# ---------------------------------------------------------------- ⑤ 反真空


def test_5_stub_the_three_block_verdict_to_true_and_3_goes_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把「三格齐」这条判定打桩成恒真 ⇒ 第 3 条必红。

    「三格齐」的判定分布在两处（`numericproof.exhaustion_problems` 问三格的事实、
    `exhaustionreport.landing_problems` 问落盘那份齐不齐）—— 两处一起打桩才等于
    「不管缺不缺都算齐了」。打桩之后同一次「缺 enumeration」的调用必须被标成 proof；
    它若仍是 cross_check，第 3 条压的就不是这条判据（改前红没有出处）。
    """
    _real_store, real_reg, _ = _wired(pathlib.Path(tmp_path) / "real")
    real = _call(real_reg, enumeration=_DROP)
    assert real.ok, (real.error, real.meta)
    assert real.data["evidence_kind"] == "cross_check", real.data

    monkeypatch.setattr(NP, "exhaustion_problems", lambda **kw: [], raising=True)
    monkeypatch.setattr(ER, "landing_problems", lambda row: [], raising=True)

    _st, stubbed_reg, _ = _wired(pathlib.Path(tmp_path) / "stubbed")
    stubbed = _call(stubbed_reg, enumeration=_DROP)
    assert stubbed.ok, (stubbed.error, stubbed.meta)
    assert stubbed.data["evidence_kind"] == "proof", (
        "打桩之后它仍然落 cross_check ⇒ 第 3 条压的不是「三格齐」这条判据")


# ---------------------------------------------------------------- ⑥ 真机形状复现


def test_6_the_r34b_shape_reads_back_as_proof(tmp_path: pathlib.Path) -> None:
    """⑥ 真机形状：`exhaustive_search` + 三格齐，从台账那一行读到 proof 与报告读数。"""
    st, reg, ws = _wired(tmp_path)
    res = _call(reg)
    assert res.ok, (res.error, res.meta)
    row = _row(st, res.data)
    assert row["method"] == "exhaustive_search", row
    assert row["evidence_kind"] == "proof", (row["evidence_kind"], row.get("notes"))
    signature = NP.signature_of(row)
    assert signature.get("signed_by") == NP.PROOF_SIGNER == "V", signature
    assert signature.get("proof_authors") == [NP.NUMERIC_AUTHOR] == ["E"], signature
    assert signature.get("proof_reason") == NP.PROOF_REASON_EXHAUSTION, signature
    assert NP.is_signed_exhaustion(row) is True
    # 报告读数：字节数、sha256 与盘上那份逐字对得上，三块都有字
    facts = ER.report_facts(row)
    assert facts["ok"] is True, facts
    payload = (ws / facts["path"]).read_bytes()
    assert facts["bytes"] == len(payload) > 0
    assert facts["sha256"] == hashlib.sha256(payload).hexdigest(), facts["sha256"]
    assert ER.landing_problems(row) == [], ER.landing_problems(row)
    assert ER.disk_problems(ws, row) == [], ER.disk_problems(ws, row)
    for key in ("design", "enumeration", "environment"):
        assert int((facts["blocks"] or {}).get(key) or 0) > 0, (key, facts["blocks"])
    # 证明栏三段与报告同一份（B 登记、G 引用认的是它）
    column = NP.parse_proof_column(NP.proof_column(row))
    assert column["problems"] == [], column
    assert column["script"] == _SCRIPT_REL
    assert column["design"] == _DESIGN and column["enumeration"] == _ENUM


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
