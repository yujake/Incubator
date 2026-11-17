# -*- coding: utf-8 -*-
"""判据甲：正文点了在册命题而 `## 依赖` 表 0 行 ⇒ 整份退回（先红后绿 + 反真空）。

## 现场（2026-11-05 真机 `projects/R-mk-infinite-90`，只读）

手稿正文里逐字写着「（依据：stmt:000013）」，而 `## 依赖` 那一节只有表头 + 分隔行、
0 行数据 ⇒ 正文引了、表里没写。`deps_missing_reading` 把这一形态读成"说不一致"
（`depsection.deps_missing_reading` 的第二档），但读数不拦人：
`manuscriptform.dependency_section_problem` 与 B 的登记入口都只看"那一节在不在"
（`section["present"]`），于是整份静默放行，依赖边 0 行而读数一切正常。

## 断在哪一跳

引用只有一个来源：每一步的 `cites`（`attackround._clean_step` 只读 JSON 的 `cites`
数组）。F 的渲染器把同一份 `cites` 同时写进正文的「（依据：…）」与 `## 依赖`
（`agent_f/manuscript.py::proof_manuscript` 的 226 / 221 两行）——所以只要稿是框架
渲染的，两处就不会分家。分家发生在"稿不是这一段渲染出来的"那一档（手写 / 转正 /
别的写口），而改前没有任何一处把"表 0 行"与"正文点了号"放在一起判。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 正文点号而表 0 行 | 受控拒 `deps_table_disagrees_with_proof`，点名第几步 | 改前 `ok=True`（静默放行） |
| b 正文与表一致 | 放行（正控：别把正常路径弄坏） | —— |
| c 正文没点号且声明自足 | 放行（不误伤自足证明） | —— |
| d 反真空 | 把一致性判据摘掉 ⇒ a 必红 | —— |

不扩大：自足那一档（正文一条 `stmt:` 都没有）仍然放行 —— 空表是声明，不是缺陷。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest

from conftest import sign_for_the_gate
from agentflow import depsection as DS
from agentflow import manuscriptform as MF
from agentflow import schema as S
from agentflow.agent_b import AgentB
from agentflow.store import Store

SID = S.format_id(13)
HEAD = ("| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | "
        "路径号（第几条证明） |\n|---|---|---|---|\n")
CITES = ("1. 设 G 是连通、简单、3-正则的有限图。（前提）\n"
         "2. 由在册定理，G 的每条边至少落在两个三角形上（依据：stmt:000013）。\n"
         "3. 于是 G 同构于 K_4。")
SELF = ("1. 设 G 是连通、简单、3-正则的有限图。（前提）\n"
        "2. 逐边双重计数给出每条边至少落在两个三角形上。\n"
        "3. 于是 G 同构于 K_4。")


def _manuscript(*, body: str, rows: str = "", sid: str = "") -> str:
    text = ("# F 的证明手稿：判据\n\n"
            + (f"\n" if sid else "")
            + "## 命题\n\n判据命题（夹具）。\n\n## 证明\n\n" + body + "\n\n"
            + "## 依赖\n\n" + HEAD + rows)
    return text


# ============================================================ a 受控拒
def test_a_a_cited_statement_with_an_empty_table_is_refused() -> None:
    """a：正文点了 `stmt:000013` 而表 0 行 ⇒ 受控拒，`why` 点名第几步。

    改前红：`validate_manuscript` 给 `ok=True`（那一节在就算合格）。
    """
    got = MF.validate_manuscript(_manuscript(body=CITES))
    assert got.get("ok") is False, got
    assert got.get("code") == DS.REFUSED_TABLE_DISAGREES, got
    why = str(got.get("why") or "")
    assert f"stmt:{SID}" in why, why
    assert "第 2 步" in why, why
    # 教法在拒信里：写进 `cites` 才会被渲染成表；散文不会被读回成引用。
    assert "cites" in why, why


# ============================================================ b 正控
def test_b_a_consistent_table_passes() -> None:
    """b：正文与表说的是同一件事 ⇒ 放行。"""
    rows = f"| 第 2 步的原话 | stmt:{SID} | 第 2 步 | 1 |\n"
    got = MF.validate_manuscript(_manuscript(body=CITES, rows=rows))
    assert got.get("ok") is True, got


# ============================================================ c 不误伤
def test_c_a_self_sufficient_empty_table_passes() -> None:
    """c：正文一条 `stmt:` 都没点、表空 ⇒ 自足，放行。"""
    got = MF.validate_manuscript(_manuscript(body=SELF))
    assert got.get("ok") is True, got


# ============================================================ d 反真空
def test_d_without_the_consistency_check_a_goes_red(monkeypatch) -> None:
    """d：把一致性判据摘掉 ⇒ a 必须退化成"静默放行"。

    这证明 a 的绿来自那道检查，而不是来自某句碰巧出现的文案。
    """
    monkeypatch.setattr(DS, "dependency_consistency_problem", lambda text: ("", ""))
    got = MF.validate_manuscript(_manuscript(body=CITES))
    assert got.get("ok") is True, (
        f"摘掉一致性判据之后 a 居然仍然被拒 ⇒ a 的绿不是这道检查给的：{got}")


# ============================================================ e 收方同一个判据
#: 2026-11-06（业主口径的纠正）：这一条被测的"可引"是"在册 ∧ 等级 ≥ pre_theorem"。
#: 所以夹具分两档造目标：`_registered_citable`（够格，正路）与
#: `_registered_conjecture`（在册但不够格 ⇒ 引用它本身就是缺陷，见 f）。
pytestmark = pytest.mark.usefixtures("signed_v_handoffs")

_TARGET_TEXT = "证明：判据夹具，由定义直接得到。"


def _register_target(store: Store, *, proof_text: str = "") -> dict:
    b = AgentB(store, extractor=None, extract_text=None, config={})
    return b.register_statement(
        statement_full="引理：由在册定理推出结论（判据夹具）。",
        statement_text="由在册定理推出结论", proof_text=proof_text,
# 2026-11-17（语义纠正）：`derived_from` / `source_lit_id` 是可选信息（`origin` 只是状态：自产/引用）；这一份夹具不测来路。
        origin="own_result", derived_from=["999999"], kind="conjecture",
        quote_reason="判据夹具：自产命题", doc_id=SID)


def _registered_citable(store: Store) -> str:
    """落一条真正够格被引的引理：在册 且 `pre_theorem`（读数逐格断言）。"""
    got = _register_target(store, proof_text=_TARGET_TEXT)
    assert got.get("ok") is True, got
    sid = str(got["stmt_id"])
    sign_for_the_gate(store.root, statement_id=sid, proof_text=_TARGET_TEXT,
                      store=store)
    row = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == sid)
    grade = DS.statement_grade(row)
    assert grade == DS.CITATION_MIN_LEVEL, (
        f"夹具要把被引的这条抬到可引门槛；实得等级 {grade!r}")
    assert sid in DS.citable_pool([row]), (
        f"可引池里必须有它：{DS.citable_pool([row])}")
    return sid


def _registered_conjecture(store: Store) -> str:
    """落一条在册但"不够格"的引理：等级停在 `conjecture`（只可作反例，不可作依据）。"""
    got = _register_target(store)
    assert got.get("ok") is True, got
    sid = str(got["stmt_id"])
    row = next(dict(r) for r in store.rows("statements")
               if str(r.get("stmt_id")) == sid)
    grade = DS.statement_grade(row)
    assert grade == "conjecture", f"夹具要的是不够格那一档；实得 {grade!r}"
    assert sid not in DS.citable_pool([row]), (
        f"可引池里不许有它：{DS.citable_pool([row])}")
    return sid


def _register_again(store: Store):
    return AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        statement_full="引理：由在册定理推出结论（判据夹具）。",
        statement_text="由在册定理推出结论", proof_text="", origin="own_result", derived_from=["999999"],
        kind="conjecture", quote_reason="判据夹具：自产命题", doc_id=SID)


def _write_manuscript(store: Store, sid: str) -> None:
    rel = DS.manuscript_relpath(statement_id=sid)
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        DS.mark_washed(_manuscript(body=CITES.replace(SID, sid), sid=sid),
                       actor="secretary-F"),
        encoding="utf-8")


def test_e_b_registration_refuses_the_same_mismatch(tmp_path: pathlib.Path) -> None:
    """e：收方（B）读稿登记走同一个判据 —— 表 0 行而正文点了可引号 ⇒ 整笔受控拒。

    为什么还要这一条：`commit_manuscript` 与 B 的登记入口是两条路（作者落稿 / 收方
    读稿），只堵一处的话"绕过落稿那一道、直接把稿交给 B"仍然静默。

    2026-11-06（业主口径的纠正）：被引的那个号必须"真够格"才轮得到"表与正文对不上"
    这一档 —— 口径是 `在册 ∧ 等级 ≥ pre_theorem`。所以夹具先把目标签成 `pre_theorem`
    （`_registered_citable` 逐格断言），正文引它。
    """
    store = Store(tmp_path / "ws")
    store.init()
    sid = _registered_citable(store)
    _write_manuscript(store, sid)

    got = _register_again(store)
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_TABLE_DISAGREES, got
    assert "第 2 步" in str(got.get("error") or ""), got
    # 整笔不写：不许顺手落一行命题或依赖边。
    assert [r for r in store.rows("dependencies")
            if str(r.get("used_by") or "") == f"stmt:{sid}"] == [], store.rows("dependencies")


def test_f_the_same_target_below_the_citation_floor_is_refused(tmp_path: pathlib.Path) -> None:
    """f：在册但 `conjecture` 的号被正文引用 ⇒ 受控拒（等级不够），拒信点名等级与门槛。

    这一条是 2026-11-06 口径的直接钉子：在册不够，还要等级够。拒信不能说成
    "表与正文对不上"（那是另一档），而要点名"它现在是 conjecture，低于 pre_theorem"。
    """
    store = Store(tmp_path / "ws")
    store.init()
    sid = _registered_conjecture(store)
    _write_manuscript(store, sid)

    got = _register_again(store)
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_LEVEL_TOO_LOW, got
    err = str(got.get("error") or "")
    assert f"stmt:{sid}" in err, err
    assert "conjecture" in err, err
    assert DS.CITATION_MIN_LEVEL in err, err
    assert store.rows("dependencies") == [], store.rows("dependencies")
