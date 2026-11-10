# -*- coding: utf-8 -*-
"""判据：pending 台账行要认领第 3 位，先得有一份载体（业主 2026-11-04 裁定 · 乙-14）。

## 这一条堵的是什么

`vsigns._claim_pending_sign` 是"没有签文件、没有签块也能翻第 3 位"的唯一一条正路：
B 新建命题时按正文 sha 去 `verifications/pending/<sha>.jsonl` 认领 V 在命题还没在册时
审过的那一签。改前只要 pending 里有这一份正文就认 —— 纯内联旧行（`object_path=""`，
没有手稿、没有 e-proof 读数报告）也能把 `bits.reviewed` 翻上去。业主的口径：这一签的
合法性来自「V 对一份稿出过结论」，所以只认 `object_path` 是一份手稿
（`reports/{f,e,b}-proof-*.md`）或 E 的穷举读数报告
（`out/experiments/<实验号>/exhaustion.md`）的 pending 行；纯内联旧行不认。

## 判据（每条都两向）

| # | 造什么 | 期望 |
|---|---|---|
| a | `object_path=""` 的 pending 行 | 不认领：`proof_without_v_sign`、`bits.reviewed` 不翻、台账不回写号 |
| b | `object_path="reports/f-proof-<号>.md"` | 照旧认领：`bits.reviewed=True`、台账回写号 |
| c | `object_path="out/experiments/<实验号>/exhaustion.md"` | 照旧认领（E 那一档） |
| d | 反真空：把载体闸打桩成恒放行 | a 的裸行被认领（`bits.reviewed=True`）—— a 量的是这道闸 |
| e | 载体形状（纯读） | 手稿三前缀 / e-proof 报告 / 老盘计划名（`f-proof-plan-*`，2026-11-10 只读兼容）认；空串、`notes/…`、`foo.txt`、`b-proof` 的 plan 名不认 |

零模型调用；夹具走生产的写口（`verifications.record_pending_sign` +
`AgentB.register_statement`），不手写台账。
"""
from __future__ import annotations

import pathlib

from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
OK = {"verdict": "成立", "why": "逐步核过，没有缺陷"}
PROOF_MANUSCRIPT = "reports/f-proof-000000.md"
E_REPORT = "out/experiments/000000/exhaustion.md"


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _pending(st: Store, *, object_path: str = "") -> dict:
    return VR.record_pending_sign(
        st.root, proof_text=PROOF, verdict=dict(OK), object_path=object_path, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})


def _manuscript_text() -> str:
    """B 登记这一笔必须带的手稿（2026-11-04 甲之后在册也要稿）。"""
    from agentflow import depsection as DS

    return ("# F 的证明手稿（夹具）\n\n- 命题号：stmt:（待登记）\n- 计划：0000\n\n"
            "## 命题\n\n" + FULL + "\n\n## 证明\n\n" + PROOF + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _register(st: Store) -> dict:
    return AgentB(st, extractor=None, extract_text=None).register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=PROOF,
        proof_manuscript=_manuscript_text(),
        kind="conjecture", label="探针命题", origin="own_result",
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": "reports/probe.md"})


def _reviewed(st: Store) -> bool:
    rows = [dict(r) for r in st.rows("statements")]
    assert len(rows) == 1, rows
    return bool(dict(rows[0].get("bits") or {}).get("reviewed"))


def _pending_row(st: Store) -> dict:
    rows, problems = VR.pending_rows(st.root)
    assert problems == [], problems
    assert len(rows) == 1, rows
    return dict(rows[0])


# ====================================================================== a 无载体
def test_a_an_inline_pending_row_is_not_claimed(tmp_path: pathlib.Path) -> None:
    """`object_path=""` 的 pending 行 ⇒ 不认领；B 的准入闸整笔拒（没有签）。"""
    st = _ws(tmp_path)
    _pending(st)
    got = _register(st)
    assert got.get("ok") is False, got
    assert got.get("kind") == "proof_without_v_sign", got
    assert str(_pending_row(st).get("statement_id") or "") == "", _pending_row(st)
    assert st.rows("statements") == [], st.rows("statements")
    # 认签那一格自己的读数（B 的准入闸只把 `proof_gate` 带出来，载体那一句在这里读）
    _, v_sign = VS.bits_after_sign(
        {"proof": True}, root=st.root, proof_text=PROOF, statement_id="",
        proof_no=1, kind="conjecture", store=st)
    assert v_sign.get("applied") is not True, v_sign
    assert "载体" in str(v_sign.get("why") or ""), v_sign


# ====================================================================== b 手稿载体
def test_b_a_pending_row_with_a_manuscript_carrier_is_claimed(
        tmp_path: pathlib.Path) -> None:
    """`object_path` 是 `reports/f-proof-<号>.md` ⇒ 照旧认领、翻第 3 位。"""
    st = _ws(tmp_path)
    _pending(st, object_path=PROOF_MANUSCRIPT)
    got = _register(st)
    assert got.get("ok") is True, got
    assert _reviewed(st) is True
    assert str(_pending_row(st).get("statement_id") or "") != "", _pending_row(st)


# ====================================================================== c E 的报告载体
def test_c_an_e_proof_report_pending_row_is_claimed(tmp_path: pathlib.Path) -> None:
    """`object_path` 是 `out/experiments/<实验号>/exhaustion.md` ⇒ 照旧认领（E 那一档）。"""
    st = _ws(tmp_path)
    _pending(st, object_path=E_REPORT)
    got = _register(st)
    assert got.get("ok") is True, got
    assert _reviewed(st) is True


# ====================================================================== d 反真空
def test_d_without_the_carrier_gate_the_inline_row_is_claimed(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """反真空：把载体闸打桩成恒放行 ⇒ a 的裸行被认领（a 量的是这道闸）。"""
    monkeypatch.setattr(VS, "_pending_carrier_path", lambda _row: PROOF_MANUSCRIPT)
    st = _ws(tmp_path)
    _pending(st)
    got = _register(st)
    assert got.get("ok") is True, got
    assert _reviewed(st) is True, (
        "打桩之后仍然没认领 ⇒ a 的拒信不来自载体闸（这一条量错了东西）")


# ====================================================================== e 载体形状
def test_e_the_carrier_shapes() -> None:
    """纯读：正式手稿三前缀 / e-proof 报告 / 老盘计划名认；其余不认。

    ## 改前钉什么 / 改后钉什么

    改前（业主 2026-11-05 晚）：`reports/f-proof-plan-<数字>` 是"计划稿"——合法的落稿名，
    但不是签的载体（真机 `f-proof-plan-000011` 上那块 3/3 被读成假签），所以它在
    `no` 这一列。

    2026-11-10 业主裁定：「F 的稿自己维护一套号源，不依赖命题号和计划号」「计划不拥有
    稿件」⇒ `manuscriptfamily.sign_carrier` 撤掉了 `f-proof-plan-*` 那条排除：老盘上的
    计划名是只读兼容名，与数字名同等（可签）。于是它从 `no` 搬回 `yes` ——
    只搬 `f-proof` 这一族：同一个 `plan-` 号形在 `b-proof` 里仍是认不出的坏名
    （`reports/b-proof-plan-000016.md` 留在 `no`，这是反向断言：翻转不是"凡 plan 都放行"）。

    另外三条留在 `no` 当反向：目录不对（`notes/…`）、号形坏（`plan-abc`）、
    不是手稿（`foo.txt`）—— 载体判据没有因为这一撤而变成"什么都认"。
    """
    yes = [
        "reports/f-proof-000000.md", "reports/e-proof-000001.md",
        "reports/b-proof-000002.md", "reports/f-proof-000000-p2.md",
        # 老盘只读兼容名（2026-11-10 裁定；新稿不再写这种名字）。
        "reports/f-proof-plan-0001.md", "reports/f-proof-plan-0001-p2.md",
    ]
    e_report = "out/experiments/000000/exhaustion.md"
    no = ["", "notes/proof.md", "foo.txt", "reports/f-proof-000000",
          "reports/f-proof-.md", "out/experiments/000000/report.md",
          "out/experiments//exhaustion.md", "reports/x/f-proof-000000.md",
          # 反向：`plan-` 号形只属于 f-proof 的老盘兼容；b-proof 里它仍是坏名。
          "reports/b-proof-plan-000016.md",
          # 反向：目录 / 号形不对时，计划名也不认。
          "notes/f-proof-plan-0001.md", "reports/f-proof-plan-abc.md"]
    #: `no` 里这几条同时也不是「手稿族的签载体」（另外两条 `f-proof-000000` /
    #: `f-proof-.md` 是"名字像手稿、目录对、少了 `.md`"的边缘形，两条判据故意不同源，
    #: 这里不拿 `is_sign_carrier` 断言它们 —— 免得把 `_pending_carrier_path` 的
    #: `.md` 尾巴要求混进载体族判据）。
    not_a_carrier = ["", "notes/proof.md", "foo.txt",
                     "out/experiments/000000/report.md",
                     "out/experiments//exhaustion.md",
                     "reports/x/f-proof-000000.md",
                     "reports/b-proof-plan-000016.md",
                     "notes/f-proof-plan-0001.md",
                     "reports/f-proof-plan-abc.md"]
    for path in yes:
        assert VS._pending_carrier_path({"object_path": path}) == path, path
        assert VS.is_sign_carrier(path) is True, path
    # E 的穷举读数报告是认领的载体，不是「手稿签载体」：两条判据不许折成一条。
    assert VS._pending_carrier_path({"object_path": e_report}) == e_report
    assert VS.is_sign_carrier(e_report) is False, e_report
    for path in no:
        assert VS._pending_carrier_path({"object_path": path}) == "", path
    for path in not_a_carrier:
        assert VS.is_sign_carrier(path) is False, path
