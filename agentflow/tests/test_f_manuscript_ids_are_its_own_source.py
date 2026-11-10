# -*- coding: utf-8 -*-
"""F 自己的手稿号源（业主 2026-11-10 裁定）。

逐字：「F 的稿自己维护一套号源，不依赖命题号和计划号。停掉错误的口径。」

## 这一份钉什么

| 格 | 判据 |
|---|---|
| a | 分配器：`counters.manuscript` + 1、`reports/` 里核占用（已存在 ⇒ 推进、绝不覆盖）、六位用尽受控错 |
| b | 命名：`manuscript_path` 只返回 `reports/f-proof-<稿号>.md`；收录不改稿名；老盘上的旧约定名可签 |
| c | 一个计划期间两份稿（两个稿号）各自送审、各自签、各自收录成两个命题号 |
| d | 四条反真空：命名又用命题号 / 又用计划号 / 收录又转名 / 旧约定名又不能签 —— 各打一次回归，判据必须红 |

不做的事：不跑真机、不碰 `projects/`、不写全量。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import manuscriptfamily as MF
from agentflow import manuscriptids as MID
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.agent_f import AgentF
from agentflow.store import Store

SID = "000001"
SID2 = "000002"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _f(store: Store) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root})


def _product(text: str = "由定义直接得到") -> dict:
    return {"product": "proof", "strategy": "直接计算", "why_strategy": "由定义与假设直接得到",
            "steps": [{"n": 1, "text": text, "cites": [], "assumption": False}]}


def _round(store: Store, mid: str, *, text: str = "由定义直接得到",
           sid: str = "s1") -> dict:
    got = _f(store).proof_manuscript(
        _product(text), sg={"sid": sid, "text": "一条自产引理", "testable": ""},
        plan={"plan_id": "000000"}, manuscript_id=mid, label="夹具", proof_no=1)
    assert got.get("ok") is True, got
    assert got.get("manuscript_id") == mid, got
    return got


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None)


def _register(store: Store, *, rel: str, statement: str, proof_text: str,
              label: str = "") -> dict:
    """B 收录口：`proof_manuscript` 给 F 的稿；签在稿的 `## 证明` 那一节上（正文 sha）。"""
    from conftest import sign_before_registration

    from agentflow import depsection as DS

    whole = str(proof_text)
    body = DS.proof_body(whole).strip("\n") or whole.strip("\n")
    sign_before_registration(store.root, proof_text=body)
    agent = _b(store)
    # 这一份量的是"稿号 / 收录不改名 / 两个命题号"，不是 B 的命题同一性判定
    # （那一问要模型；没模型时 fail-closed 会整笔拒）。夹具把"不是同一条"判死。
    agent._resolve_same_statement = lambda **_kw: {  # type: ignore[method-assign]
        "checked": True, "found": "", "refused": "",
        "why": "夹具：判过、不是同一条"}
    return agent.register_statement(
        statement_full=statement, statement_text=statement[:30],
        origin="own_result", kind="conjecture", label=label or statement[:30],
        proof_text=body, proof_manuscript=rel, evidence_kind="heuristic",
        line_range={"label": rel}, quote_reason="夹具：F 的稿由 B 收录")


# ------------------------------------------------------------------ a 分配器

def test_a_the_allocator_issues_consecutive_ids_and_never_overwrites(tmp_path) -> None:
    """a：连发三个号 ⇒ 000000 / 000001 / 000002，且既有文件一个字节都没动。"""
    st = _ws(tmp_path)
    reports = pathlib.Path(st.root) / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    fresh = pathlib.Path(tmp_path) / "fresh"
    (fresh / "data").mkdir(parents=True)
    (fresh / "data" / "counters.json").write_text(
        json.dumps({"schema_version": 2, "counters": {}}), encoding="utf-8")
    got = [MID.next_manuscript_id(fresh) for _ in range(3)]
    assert got == ["000000", "000001", "000002"], got

    # 有稿的工作区：先占住前三个号，再发 ⇒ 跳到空位，既有文件逐字不变
    for mid in ("000000", "000001", "000002"):
        (reports / f"f-proof-{mid}.md").write_text(f"既有稿 {mid}", encoding="utf-8")
    assert MID.next_manuscript_id(st) == "000003"
    assert MID.next_manuscript_id(st) == "000004"
    for mid in ("000000", "000001", "000002"):
        assert (reports / f"f-proof-{mid}.md").read_text(encoding="utf-8") == f"既有稿 {mid}"


def test_a_existing_manuscript_pushes_the_allocator_forward(tmp_path) -> None:
    """a（占用）：已存在 `f-proof-000002.md` 时再发 ⇒ 跳到 000003（不覆盖）。"""
    st = _ws(tmp_path)
    reports = pathlib.Path(st.root) / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "f-proof-000002.md").write_text("别人的稿", encoding="utf-8")
    counters = pathlib.Path(st.root) / "data" / "counters.json"
    counters.write_text(json.dumps({"schema_version": 2,
                                    "counters": {"manuscript": 2}}), encoding="utf-8")

    assert MID.next_manuscript_id(st) == "000003"
    assert (reports / "f-proof-000002.md").read_text(encoding="utf-8") == "别人的稿"


def test_a_six_digit_exhaustion_is_a_controlled_error(tmp_path) -> None:
    """a（越界）：六位用尽 ⇒ 受控抛 `ManuscriptIdError`（不静默升位宽）。"""
    st = _ws(tmp_path)
    counters = pathlib.Path(st.root) / "data" / "counters.json"
    counters.write_text(json.dumps({"schema_version": 2,
                                    "counters": {"manuscript": 1000000}}),
                        encoding="utf-8")
    with pytest.raises(MID.ManuscriptIdError):
        MID.next_manuscript_id(st)


# ------------------------------------------------------------------ b 命名

def test_b_the_manuscript_path_is_only_the_f_manuscript_number(tmp_path) -> None:
    """b：`manuscript_path` 只按 F 的稿号命名；收录不改稿名；旧约定名只读兼容可签。"""
    st = _ws(tmp_path)
    f = _f(st)
    assert f.manuscript_path("000007") == "reports/f-proof-000007.md"
    assert f.manuscript_path("000007", proof_no=2) == "reports/f-proof-000007-p2.md"
    assert f.manuscript_path("abc") == ""
    # 改前那三条回退（命题号 / 计划号 / 子目标号）必须已经删掉：给了就 TypeError
    for bad in ({"statement_id": SID}, {"plan_id": "000000"}, {"sid": "s1"}):
        with pytest.raises(TypeError):
            f.manuscript_path(**bad)

    got = _round(st, "000007")
    rel = got["path"]
    assert rel == "reports/f-proof-000007.md", got
    assert "plan" not in rel and SID not in rel, got
    out = _register(st, rel=rel, statement="自产引理：稿名不随收录变",
                    proof_text=str(got["text"]))
    assert out.get("ok") is True, out
    # 收录不改稿名：同一份稿还在原路径上；没有按命题号命名的第二份
    assert (pathlib.Path(st.root) / rel).is_file(), rel
    named = sorted(p.name for p in (pathlib.Path(st.root) / "reports").glob("f-proof-*.md"))
    assert "f-proof-000007.md" in named, named
    assert not [n for n in named if n.startswith("f-proof-000001")], named
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == str(out["stmt_id"]))
    assert str(row.get("manuscript_id") or "") == "000007", row

    # 老盘上的旧约定名：只读兼容（能分类、能读正文），且是签的载体
    old = "reports/f-proof-plan-0004.md"
    assert MF.classify_manuscript(old)["tier"] == MF.TIER_FAMILY, MF.classify_manuscript(old)
    assert VS.manuscript_id_of(old) == "plan-0004"
    assert MF.sign_carrier(old)["ok"] is True, MF.sign_carrier(old)


def test_b_publish_does_not_rename(tmp_path) -> None:
    """b（改前/改后）：`publish_manuscript` 拿到命题号也不改名（它是稿号，不是命题号）。"""
    st = _ws(tmp_path)
    got = _round(st, "000009")
    out = _f(st).publish_manuscript(got, statement_id=SID)
    assert out.get("published") is False, out
    assert out.get("path") == got["path"], out
    assert out.get("name_changed") is False, out
    assert "不改稿名" in str(out.get("why") or ""), out


# ------------------------------------------------------------------ c 一计划两稿

def test_c_one_plan_two_independent_manuscripts(tmp_path) -> None:
    """c：同一计划期间两份稿（两个稿号）各自签、各自收录成两个命题号。"""
    st = _ws(tmp_path)
    a = _round(st, "000000", text="第一份稿的第一步", sid="s1")
    b = _round(st, "000001", text="第二份稿的第一步", sid="s2")
    assert a["manuscript_id"] != b["manuscript_id"]
    assert a["path"] != b["path"]

    out_a = _register(st, rel=a["path"],
                      statement="若 n 为大于 2 的整数，则 n 与 n+2 不能同时为素数。",
                      proof_text=str(a["text"]))
    out_b = _register(st, rel=b["path"],
                      statement="任何平面图的顶点都可以用四种颜色染色，使相邻顶点不同色。",
                      proof_text=str(b["text"]))
    assert out_a.get("ok") is True and out_b.get("ok") is True, (out_a, out_b)
    assert str(out_a["stmt_id"]) != str(out_b["stmt_id"]), (out_a, out_b)

    rows = {str(r.get("stmt_id")): dict(r) for r in st.rows("statements")}
    assert rows[str(out_a["stmt_id"])].get("manuscript_id") == "000000"
    assert rows[str(out_b["stmt_id"])].get("manuscript_id") == "000001"
    assert rows[str(out_a["stmt_id"])].get("proof_no") == 1
    # 两份稿都还在各自的稿号上（收录不改名、也不合并成一份）
    assert (pathlib.Path(st.root) / a["path"]).is_file()
    assert (pathlib.Path(st.root) / b["path"]).is_file()


# ------------------------------------------------------------------ d 反真空四条

def _forward_ok(store: Store, out: dict) -> bool:
    """新口径的"这一份稿命名对"判据（d 的四条都打在这一个谓词上）。"""
    rel = str(out.get("manuscript_path") or out.get("path") or "")
    mid = str(out.get("manuscript_id") or "")
    return (bool(re.fullmatch(r"\d{6}", mid))
            and rel == f"reports/f-proof-{mid}.md"
            and "plan-" not in rel)


def test_d_naming_with_the_statement_number_turns_it_red(tmp_path, monkeypatch) -> None:
    """d-1 反真空：命名又用命题号 ⇒ 红。"""
    st = _ws(tmp_path)
    got = _round(st, "000004")
    assert _forward_ok(st, got) is True, got

    monkeypatch.setattr(AgentF, "manuscript_path",
                        lambda self, mid="", *, proof_no=1: f"reports/f-proof-{SID}.md")
    regressed = _round(st, "000004")
    assert _forward_ok(st, regressed) is False, regressed


def test_d_naming_with_the_plan_number_turns_it_red(tmp_path, monkeypatch) -> None:
    """d-2 反真空：命名又用计划号 ⇒ 红。"""
    st = _ws(tmp_path)
    monkeypatch.setattr(AgentF, "manuscript_path",
                        lambda self, mid="", *, proof_no=1: "reports/f-proof-plan-000000.md")
    regressed = _round(st, "000005")
    assert _forward_ok(st, regressed) is False, regressed


def test_d_renaming_at_collection_turns_it_red(tmp_path) -> None:
    """d-3 反真空：收录又转名 ⇒ 红。

    判据本体是一个纯读谓词 `_no_renamed_copy`：收录之后盘上只许有 `f-proof-<稿号>.md`，
    不许出现 `f-proof-<命题号>.md`。正控（真收录）必须是 True；把旧口径那一笔"按命题号
    改名"手工重放一次（复制成 `f-proof-<命题号>.md`）之后它必须变 False —— 这就是
    "收录又转名"那条回归会被抓住的证明。
    """
    st = _ws(tmp_path)
    got = _round(st, "000006")
    before = str(got["path"])
    out = _register(st, rel=before, statement="命题：收录不许转名",
                    proof_text=str(got["text"]))
    assert out.get("ok") is True, out
    assert _no_renamed_copy(st, mid="000006", stmt=str(out["stmt_id"])) is True

    # 旧口径那一笔的重放：把同一份正文复制成按命题号命名的名字
    (pathlib.Path(st.root) / f"reports/f-proof-{out['stmt_id']}.md").write_text(
        str(got["text"]), encoding="utf-8")
    assert _no_renamed_copy(st, mid="000006", stmt=str(out["stmt_id"])) is False


def _no_renamed_copy(store: Store, *, mid: str, stmt: str) -> bool:
    """收录之后：稿只在自己稿号上，没有按命题号命名的第二份。"""
    reports = pathlib.Path(store.root) / "reports"
    own = (reports / f"f-proof-{mid}.md").is_file()
    renamed = (reports / f"f-proof-{stmt}.md").is_file() and stmt != mid
    return bool(own and not renamed)


def test_d_the_old_convention_name_must_stay_signable(tmp_path, monkeypatch) -> None:
    """d-4 反真空：老的旧约定名又不能签 ⇒ 红（签载体那条排除不许回来）。"""
    old = "reports/f-proof-plan-0004.md"
    assert MF.sign_carrier(old)["ok"] is True

    real = MF.sign_carrier

    def _regressed(rel):
        got = dict(real(rel))
        if str(got.get("name") or "").startswith("f-proof-plan-"):
            got.update(ok=False, code=MF.CODE_PLAN_NOT_SIGN)
        return got

    monkeypatch.setattr(MF, "sign_carrier", _regressed)
    assert MF.sign_carrier(old)["ok"] is False, "旧约定名又被判成不可签 ⇒ d-4 应该红"
    assert MF.CODE_PLAN_NOT_SIGN, "历史码必须保留（老读数还要解释）"
