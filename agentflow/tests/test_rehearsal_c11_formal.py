# -*- coding: utf-8 -*-
"""彩排 C11：形式化链 —— B 的命题 → L（formalize → check_formal → record）→ C。

## 这一条链怎么真跑

```text
B 已经把命题登记进 statements（`statement_id=0200`，正文与证明都在）
  → L 的工具面 formal.formalize：写 `code/formal/<声明名>.lean` + 真跑 Lean
  → L 的工具面 formal.check_formal：对盘上那份 .lean 再跑一次检查器
  → L 的工具面 formal.record：按 statement_id 读台账正文、现跑检查器、落一行 experiments
  → C 的 proof_chain 能读这条命题（L 的 out 边只有 C）
```

本机装了 Lean 4.7（`tests/conftest.py::lean_path()`）：真检查器跑得过就断言
`status=verified`；本机没有它时断言的是 `unknown + 说得清原因`（不是悄悄跳过）。

## 终态断言（盘上/台账上可查）

| 判据 | 终态 |
|---|---|
| `test_c11_a_l_writes_leans_and_the_checker_really_runs` | `code/formal/*.lean` 在盘上且 sha256 与字节一致；`formal.*` 工具面真的被调用（spy 计数 > 0） |
| `test_c11_b_record_lands_one_experiments_row` | `experiments` 恰好一行：`method=formal`、`claim_key=stmt:0200`、`code_path` 是那份 .lean、`verifier_output` 是检查器原话 |
| `test_c11_c_l_cannot_write_statements` | `WRITE_SETS["L"] == {"experiments"}`；record 前后 statements 行逐字节不变；L 的工具面没有 `table.*`（结构上碰不到命题行） |
| `test_c11_d_c_reads_the_chain_after_l` | `ALLOWED_EDGES` 有 `("L","C")`；C.proof_chain 读得到 0200；experiments 行在台账上 |

## 反真空

把 `check_formal` 打桩成失败（`status=unknown / checked=False`）⇒ `record` 必须把
这一行记成 `unknown`（`evidence_kind != "proof"`、`result=inconclusive`），不许
记成 pass/proof —— `test_..._e`。这一格钉的是「检查器没说话」与「检查器说通过」
是两件事，也是 `evidence_kind="proof"` 唯一的价值来源。

## 零模型

全部 tmp 工作区；`.lean` / `code/formal/*.steps.jsonl` / experiments 行都随 tmp 清掉。
"""
from __future__ import annotations

import pathlib
from typing import Any

import pytest

from agentflow import capabilities as CAP
from agentflow import schema as S
from agentflow.agent_l import AgentL
from agentflow.store import Store
from agentflow.tools import formal_tools as FT
from agentflow.tools import verify_tools as VT
from agentflow.tools.base import ToolRegistry

from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()
SID = "0200"
CLAIM = "forall n : Nat, n + 0 = n"
PROOF = "对任意自然数 n，n + 0 = n 由加法的定义直接成立。"
SOURCE = """import Init.Data.Nat.Basic

namespace LProbe

-- step 1
theorem c11_add_zero (n : Nat) : n + 0 = n := rfl

end LProbe
"""
DECL = "c11_add_zero"
LEAN_REL = f"code/formal/{DECL}.lean"


# ====================================================================== 夹具
def _env(tmp_path: pathlib.Path) -> dict[str, Any]:
    """一个带 B 已登记命题的工作区（C11 的起点）。"""
    st = Store(tmp_path / "ws")
    st.init()
    row = S.Statement(
        stmt_id=SID, origin="own_result", kind="theorem",
        label="C11 的加法恒等式", statement_text=CLAIM, statement_full=CLAIM,
        proof_text=PROOF, source_lit_id=None, quote_verified=None,
        quote_reason="夹具：B 已登记", evidence_kind="cross_check",
        status="active", created_at="2026-01-01T00:00:00+00:00")
    row.validate()
    with st.tx("statements", actor="fixture") as tx:
        tx.upsert("statements", row.to_dict())
    # 一条在册文献作这条命题的前提：这样 C 的 `proof_chain` 才有根可走
    # （没有依赖边又拿不到 proof 证据的命题会被 C 如实报成 `unwritten_dependencies`）。
    lit = S.Literature(lit_id="0000", title="加法定义（夹具）", type="J",
                       summary="s", path=None, added_at="2026-01-01T00:00:00+00:00")
    lit.validate()
    dep = S.Dependency(dep_id="0000", used_by=f"stmt:{SID}", kind="definition",
                       label="加法定义", status="closed", source_lit_id="0000",
                       path_group=1, created_at="2026-01-01T00:00:00+00:00")
    dep.validate()
    with st.tx("literature", "dependencies", actor="fixture") as tx:
        tx.upsert("literature", lit.to_dict())
        tx.upsert("dependencies", dep.to_dict())
    return {"store": st, "root": st.root}


def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """把这一趟的 Lean 落在本机那一版上（绝对路径），并清掉自检读数缓存。"""
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()


def _lint_registry(st: Store) -> ToolRegistry:
    reg = ToolRegistry(name="c11-L")
    reg.bound_role = "L"
    FT.register(reg, store=st, root=st.root)
    return reg


def _experiments(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("experiments")]


def _statement_row(st: Store) -> dict:
    return dict(next(r for r in st.rows("statements") if str(r.get("stmt_id")) == SID))


# ====================================================================== a：写盘
def test_c11_a_l_writes_leans_and_the_checker_really_runs(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`formal.formalize` 真的写盘、真的起检查器；工具面真的被调用（spy）。"""
    env = _env(tmp_path)
    _lean_on(monkeypatch)
    st = env["store"]
    calls: list[str] = []
    real_check = VT.check_formal

    def _spy(*a: Any, **kw: Any) -> Any:
        calls.append("check_formal")
        return real_check(*a, **kw)

    monkeypatch.setattr(VT, "check_formal", _spy)
    reg = _lint_registry(st)
    got = reg.call("formal.formalize", claim=CLAIM, source=SOURCE,
                   declaration_name=DECL, statement_id=SID, path_source="B",
                   role="L")
    problems: list[str] = []
    if not got.ok:
        problems.append(f"formal.formalize 调用失败：{got.error!r}")
    data = dict(got.data or {})
    if not calls:
        problems.append("桥接层 check_formal 一次都没被调用 —— 工具面只是看起来接上了")
    target = pathlib.Path(str(env["root"])) / str(data.get("path") or "")
    if not data.get("written") or not target.is_file():
        problems.append(f".lean 没落盘：written={data.get('written')!r} path={data.get('path')!r}")
    else:
        import hashlib

        blob = target.read_bytes()
        if hashlib.sha256(blob).hexdigest() != str(data.get("sha256") or ""):
            problems.append("返回的 sha256 与盘上字节不一致")
        if "-- step 1" not in blob.decode("utf-8"):
            problems.append("盘上的源码不是这一段（步骤标记不见了）")
    if HAVE_LEAN:
        if data.get("status") != "verified":
            problems.append(f"真 Lean 跑真命题该 verified，实际 {data.get('status')!r}"
                            f"（reason={data.get('reason')!r}，"
                            f"output={data.get('verifier_output')!r}）")
    else:
        if data.get("status") != "unknown" or not data.get("reason"):
            problems.append(f"没有 Lean 时该 unknown + 原因，实际 {data!r}")
    if str(data.get("statement_id") or "") != SID:
        problems.append(f"formalize 没绑定命题号：{data.get('statement_id')!r}")
    # 桥接层的环境探测也走真入口：`verify.detect_verifier`（F/G/H 的工具面；
    # L 的工具面刻意不含 verify.*，它由 Agent 层直接调同一份桥接函数）。
    seen_detect: list[str] = []
    real_detect = VT.detect_verifier

    def _spy_detect(*a: Any, **kw: Any) -> Any:
        seen_detect.append("detect_verifier")
        return real_detect(*a, **kw)

    monkeypatch.setattr(VT, "detect_verifier", _spy_detect)
    from agentflow.tools import build_registry

    reg_h = build_registry(store=st, workspace_root=str(env["root"]),
                           roles=("H",)).registry
    detected = reg_h.call("verify.detect_verifier", role="H")
    if not detected.ok or not seen_detect:
        problems.append(f"verify.detect_verifier 没真的被调用：ok={detected.ok!r} "
                        f"error={detected.error!r} calls={seen_detect!r}")
    assert problems == [], problems


# ====================================================================== b：一行实验
def test_c11_b_record_lands_one_experiments_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`check_formal` 与 `record` 真跑 ⇒ experiments 恰好一行（formal/proof）。"""
    env = _env(tmp_path)
    _lean_on(monkeypatch)
    st = env["store"]
    reg = _lint_registry(st)
    formalized = reg.call("formal.formalize", claim=CLAIM, source=SOURCE,
                          declaration_name=DECL, statement_id=SID,
                          path_source="B", role="L")
    assert formalized.ok, formalized.error
    written = dict(formalized.data or {})
    checked = reg.call("formal.check_formal", claim=CLAIM,
                       script_path=written.get("path"), declaration_name=DECL,
                       role="L")
    problems: list[str] = []
    if not checked.ok:
        problems.append(f"formal.check_formal 调用失败：{checked.error!r}")
    recorded = reg.call("formal.record", statement_id=SID,
                        code_path=written.get("path"), declaration_name=DECL,
                        path_source="L", role="L")
    if not recorded.ok:
        problems.append(f"formal.record 调用失败：{recorded.error!r}")
    data = dict(recorded.data or {})
    rows = _experiments(st)
    if data.get("recorded") is not True:
        problems.append(f"record 没登记：{data!r}")
    if len(rows) != 1:
        problems.append(f"experiments 该恰好 1 行，实际 {len(rows)} 行：{rows}")
    else:
        row = rows[0]
        if str(row.get("method")) != "formal":
            problems.append(f"method 该 formal，实际 {row.get('method')!r}")
        if str(row.get("claim_key")) != f"stmt:{SID}":
            problems.append(f"claim_key 该绑定 stmt:{SID}，实际 {row.get('claim_key')!r}")
        if str(row.get("code_path")) != str(written.get("path")):
            problems.append(f"code_path 不是那份 .lean：{row.get('code_path')!r}")
        if HAVE_LEAN:
            if str(row.get("evidence_kind")) != "proof":
                problems.append(f"真检查器通过该记 proof，实际 {row.get('evidence_kind')!r}")
            if str(row.get("result")) != "supports":
                problems.append(f"真检查器通过该记 supports，实际 {row.get('result')!r}")
            if not str(row.get("verifier_output") or "").strip():
                problems.append("检查器原话被丢了（verifier_output 为空）")
            obs = dict(row.get("observations") or {})
            if not str(obs.get("recorded_by") or "").endswith("L"):
                problems.append(f"observations.recorded_by 该记 L：{obs!r}")
            if str(obs.get("path_source") or "") != "L":
                problems.append(f"observations.path_source 该是 L：{obs!r}")
        else:
            if str(row.get("evidence_kind")) == "proof":
                problems.append("没有 Lean 却记成了 proof（把没查成读成了通过）")
    if not (pathlib.Path(str(env["root"])) / LEAN_REL).is_file():
        problems.append(f"预期落点 {LEAN_REL} 不在盘上")
    assert problems == [], problems


# ====================================================================== c：无 statements 写权
def test_c11_c_l_cannot_write_statements(tmp_path: pathlib.Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """L 的写集只有 experiments：结构上碰不到 statements（V 签不可能被绕过）。"""
    env = _env(tmp_path)
    _lean_on(monkeypatch)
    st = env["store"]
    before = _statement_row(st)
    reg = _lint_registry(st)
    formalized = reg.call("formal.formalize", claim=CLAIM, source=SOURCE,
                          declaration_name=DECL, statement_id=SID,
                          path_source="B", role="L")
    assert formalized.ok, formalized.error
    written = dict(formalized.data or {})
    recorded = reg.call("formal.record", statement_id=SID,
                        code_path=written.get("path"), declaration_name=DECL,
                        path_source="L", role="L")
    assert recorded.ok, recorded.error
    after = _statement_row(st)
    problems: list[str] = []
    if after != before:
        problems.append(f"record 动了 statements：{before!r} → {after!r}")
    write_set = set(CAP.WRITE_SETS["L"])
    if write_set != {"experiments"}:
        problems.append(f"L 的写集该只有 experiments，实际 {sorted(write_set)}")
    # 工具面：L 拿不到 table.* 一类的表写工具（结构上的拦截，不是靠纪律）。
    face = {spec.name for spec in reg.for_role("L").specs()} if hasattr(
        reg.for_role("L"), "specs") else set()
    if face and any(name.startswith(("table.", "graph.")) for name in face):
        problems.append(f"L 的工具面出现了表/图写工具：{sorted(face)}")
    if str(after.get("evidence_kind")) != str(before.get("evidence_kind")):
        problems.append("experiments 的登记把 statements 的证据档改了")
    if str(recorded.data.get("statement_evidence_kind_before")) != str(
            recorded.data.get("statement_evidence_kind_after")):
        problems.append(f"record 自己报的证据档前后不一致：{recorded.data!r}")
    assert problems == [], problems


# ====================================================================== d：L→C
def test_c11_d_c_reads_the_chain_after_l(tmp_path: pathlib.Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """协作面：L 的出边只有 C；C 读得到这条命题的依赖链。"""
    env = _env(tmp_path)
    _lean_on(monkeypatch)
    st = env["store"]
    problems: list[str] = []
    edges = set(CAP.ALLOWED_EDGES.get("L", ())) if hasattr(
        CAP.ALLOWED_EDGES.get("L", ()), "__iter__") else set()
    if "C" not in edges:
        problems.append(f"L 的出边里没有 C：{sorted(edges)}")
    if "B" in edges or "V" in edges:
        problems.append(f"L 不该有 B/V 的出边：{sorted(edges)}")
    reg = _lint_registry(st)
    formalized = reg.call("formal.formalize", claim=CLAIM, source=SOURCE,
                          declaration_name=DECL, statement_id=SID,
                          path_source="B", role="L")
    assert formalized.ok, formalized.error
    written = dict(formalized.data or {})
    recorded = reg.call("formal.record", statement_id=SID,
                        code_path=written.get("path"), declaration_name=DECL,
                        path_source="L", role="L")
    assert recorded.ok, recorded.error
    from agentflow.agent_c import AgentC

    chain = AgentC(st).proof_chain(SID)
    if not chain.ok:
        problems.append(f"C 读不到这条命题的依赖链：{chain.error!r}")
    if str(chain.payload.get("target") or "") != SID:
        problems.append(f"C 的链目标不对：{chain.payload.get('target')!r}")
    if not _experiments(st):
        problems.append("experiments 行不在台账上（L 的产出没进证据链）")
    assert problems == [], problems


# ====================================================================== e：反真空
def test_c11_e_a_stubbed_checker_records_unknown_not_pass(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把 `check_formal` 打桩成失败 ⇒ record 必须记 unknown，不许记 proof。"""
    env = _env(tmp_path)
    _lean_on(monkeypatch)
    st = env["store"]
    reg = _lint_registry(st)
    formalized = reg.call("formal.formalize", claim=CLAIM, source=SOURCE,
                          declaration_name=DECL, statement_id=SID,
                          path_source="B", role="L")
    assert formalized.ok, formalized.error
    written = dict(formalized.data or {})

    def _broken(self: AgentL, claim: str, **kw: Any) -> dict:
        return {"checked": False, "verified": None, "claim": claim,
                "reason": "lean_selfcheck_unusable", "detail": "打桩：检查器没说话",
                "verifier_output": "", "missing_imports": [], "verifier_status":
                "lean_selfcheck_unusable", "exit_code": None, "status": "unknown",
                "problems": ["打桩：检查器没说话"], "lean": "", "lean_path": ""}

    monkeypatch.setattr(AgentL, "check_formal", _broken)
    recorded = reg.call("formal.record", statement_id=SID,
                        code_path=written.get("path"), declaration_name=DECL,
                        path_source="L", role="L")
    problems: list[str] = []
    if not recorded.ok:
        problems.append(f"打桩之后 record 调用失败：{recorded.error!r}")
    data = dict(recorded.data or {})
    rows = _experiments(st)
    if data.get("recorded") is not True:
        problems.append(f"打桩之后这一行该照实登记：{data!r}")
    if len(rows) != 1:
        problems.append(f"experiments 该恰好 1 行，实际 {len(rows)} 行：{rows}")
    else:
        row = rows[0]
        if str(row.get("evidence_kind")) == "proof":
            problems.append(f"检查器没说话却记成了 proof：{row!r}")
        if str(row.get("result")) == "supports":
            problems.append(f"检查器没说话却记成了 supports：{row!r}")
        if str(data.get("status")) == "verified" or data.get("verified") is True:
            problems.append(f"打桩成失败却报 verified：{data!r}")
    if str(data.get("refused")) == "True":
        problems.append(f"「没查成」被折成了受控拒：{data!r}")
    assert problems == [], problems
