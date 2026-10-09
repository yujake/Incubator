# -*- coding: utf-8 -*-
"""S1o：B 只交"定理内容 + 证明过程"，依赖由秘书从证明文本里扫出来（`draft/97` §14.11 乙）。

业主逐字：

> 「14.11关于B"写"工具用乙形式，B需要给的输入就是定理内容、证明过程。」

⇒ 出处、依赖、编号、去重都由秘书从这两样里推出来：依赖 = 证明过程里引用到的那些号。
这一组守五件容易悄悄做错的事：

1. 正控：B 交两样 ⇒ `statements` 一行 + 由证明文本扫出的 `dependencies` 若干行
   （`used_by="stmt:<新号>"`、每条边一个 `path_group`）；
2. 负控（不许整笔拒）：证明里出现一个不在册的号 ⇒ 那条边落 `dangling` 并在读数里
   点名，整笔照写（拒了等于把整条定理丢掉，而"引了一个还不存在的号"最该留痕）；
3. 点名（不许静默丢）：在册但 `Dependency` 没有承载格的前缀（`rel:` / `eval:`）
   进 `deps_unmappable` 并逐条写清为什么；
4. 三态：`deps_state` = `from_proof` / `none_in_proof` / `unknown` 严格分开 ——
   "证明过程这一格没给"（没扫成）不许被读成"这条定理不依赖任何东西"；
5. 不猜分段：给了 `proof_paths` ⇒ 每段一组；没给 ⇒ 全归第 1 组（不按空行/字样猜）。

另有一条与"两件式契约"直接相关的判据：B 只交两样时，`quote_reason` 由秘书补一个受控值
（`Statement.validate` 要求"不是 True 就必须写"），补了必须在读数里看得见；
`line_range` 是字符串那一格也在这里钉住（它此前走的是 `PageRange` 的构造口）。
"""

from __future__ import annotations

from conftest import TS, add_literature
from agentflow import secretary as SEC


def _sec(store, role: str = "B", **kw) -> SEC.Secretary:
    return SEC.Secretary(role, root=store.root, store=store, **kw)


def _deps_of(store, stmt_id: str) -> list[dict]:
    return [dict(d) for d in store.rows("dependencies") if str(d.get("used_by")) == f"stmt:{stmt_id}"]


def _two_things(store, **extra) -> dict:
    """B 交的那两样：定理内容 + 证明过程（其余一概不给 —— 这正是这一批的契约）。"""
    payload = {"kind": "theorem", "label": "T1", "origin": "own_result",
               "statement_full": "定理：对任意群 G，命题 ph 成立。"}
    payload.update(extra)
    return payload


# ==================================================== 一、正控：依赖从证明文本里出来

def test_the_dependencies_come_out_of_the_proof_text(store):
    """正控：只交两样 ⇒ 行落库、边从证明文本里扫出来、号与出处都对得上。"""
    add_literature(store, "0003", title="群论引理", processed=True)
    out = _sec(store).record_statement(_two_things(
        store, proof_text="证明：由 lit:0003 的引理直接推出，再用 stmt:0002 的结论。"))
    assert out["checked"] and out["created"], out
    assert out["deps_state"] == "from_proof" and out["deps_from"] == "proof", out
    row = store.rows("statements")[0]
    assert row["stmt_id"] == out["stmt_id"], (row, out["stmt_id"])
    deps = {d["label"]: d for d in _deps_of(store, out["stmt_id"])}
    assert set(deps) == {"lit:0003", "stmt:0002"}, deps
    assert deps["lit:0003"]["status"] == "closed" and deps["lit:0003"]["source_lit_id"] == "0003"
    assert deps["stmt:0002"]["status"] == "dangling", "不在册的那个号必须落成 dangling"
    assert all(d["path_group"] == 1 for d in deps.values()), deps
    # 读数里两条都点名（一条 closed、一条 dangling），且悬空那条给出为什么
    assert [d["ref"] for d in out["deps_dangling"]] == ["stmt:0002"], out["deps_dangling"]
    assert out["deps_dangling"][0]["why"], out["deps_dangling"]


def test_the_two_things_contract_gets_a_controlled_quote_reason(store):
    """只交两样 ⇒ `quote_reason` 由秘书补受控值（补了看得见），`line_range` 按既有约定落区间。

    `line_range` 那一格不是字符串：仓里的既有约定是 `_normalize_range` 归一化后的
    区间（`tests/test_intake_actions.py` 断言 `["start"] == 120`）—— 本轮一度照
    `Statement.line_range` 的注释改成 `"343-414"` 那种字符串，被那条判据当场判红。
    这里改成钉住既有约定（判据比注释权威），并把"注释与判据对不上"记成一条待办。
    """
    out = _sec(store).record_statement(_two_things(store, proof_text="证明：由定义直接得到。"))
    assert out["checked"] and out["created"], out
    assert out.get("quote_reason_filled") is True, "补了必须留读数（否则'这格为什么有值'无从分辨）"
    row = store.rows("statements")[0]
    assert "own_result" in row["quote_reason"] and len(row["quote_reason"]) > 20, row["quote_reason"]
    # 调用方给归一化过的区间（B 的动作就是这么给的）⇒ 原样落区间，不许写成字符串
    out3 = _sec(store).record_statement(_two_things(
        store, label="T3", statement_full="定理：行范围那一格。", proof_text="证明：略。",
        line_range={"start": 343, "end": 414, "label": ""}))
    assert out3["checked"], out3
    got = next(r for r in store.rows("statements") if r["stmt_id"] == out3["stmt_id"])
    assert got["line_range"]["start"] == 343 and got["line_range"]["end"] == 414, got["line_range"]
    # 调用方给了理由就照用（不覆盖）
    out2 = _sec(store).record_statement(_two_things(
        store, label="T2", statement_full="定理：另一条。", proof_text="证明：略。",
        quote_reason="人工给的理由：我从 A 的抽取件里核过"))
    assert out2["checked"], out2
    assert not out2.get("quote_reason_filled"), out2
    t2 = next(r for r in store.rows("statements") if r["label"] == "T2")
    assert t2["quote_reason"].startswith("人工给的理由"), t2["quote_reason"]


# ==================================================== 二、负控：悬空不整笔拒、不成格的要点名

def test_a_missing_id_in_the_proof_is_dangling_not_a_refusal(store):
    """负控（业主 §14.11 逐字）：悬空引用 ⇒ 那条边 `dangling` + 点名，不整笔拒。"""
    add_literature(store, "0003", title="引理", processed=True)
    out = _sec(store).record_statement(_two_things(
        store, proof_text="证明：只引用一个不存在的号 stmt:0777，其余靠 lit:0003。"))
    assert out["checked"] and out["created"], ("悬空引用不许把整笔拒掉", out)
    assert store.rows("statements"), "命题那一行必须落下去"
    deps = {d["label"]: d for d in _deps_of(store, out["stmt_id"])}
    assert deps["stmt:0777"]["status"] == "dangling", deps
    assert deps["stmt:0777"]["source_stmt_id"] == "0777", (
        "悬空边也要带来源（不带就是一条'四选一都没有'的行）", deps["stmt:0777"])
    assert deps["stmt:0777"]["status_reason"], "`Dependency.validate` 要求 dangling 写理由"
    assert [d["ref"] for d in out["deps_dangling"]] == ["stmt:0777"], out["deps_dangling"]


def test_a_registered_prefix_without_a_carrier_is_named(store):
    """在册但没有承载格的前缀（`rel:` / `eval:`）⇒ 点名进 `deps_unmappable`，不静默丢。"""
    add_literature(store, "0003", title="引理", processed=True)
    out = _sec(store).record_statement(_two_things(
        store, proof_text="证明：见 rel:0009 与 eval:0004 的读数，另有 lit:0003。"))
    assert out["checked"], out
    named = {u["ref"]: u for u in out["deps_unmappable"]}
    assert set(named) == {"rel:0009", "eval:0004"}, named
    assert all(u["why"] for u in named.values()), named
    assert "relations" in named["rel:0009"]["table"], named["rel:0009"]
    assert [d["label"] for d in _deps_of(store, out["stmt_id"])] == ["lit:0003"], "不落没有承载格的边"


# ==================================================== 三、三态：不许把"没扫成"折成"空"

def test_the_three_dependency_states_are_not_folded(store):
    """反真空：`from_proof` / `none_in_proof` / `unknown` 三档必须分得开。"""
    add_literature(store, "0003", title="引理", processed=True)
    sec = _sec(store)
    with_refs = sec.record_statement(_two_things(
        store, label="A1", statement_full="定理：甲。", proof_text="证明：由 lit:0003 推出。"))
    without_refs = sec.record_statement(_two_things(
        store, label="A2", statement_full="定理：乙。", proof_text="证明：由定义直接得到。"))
    not_given = sec.record_statement(_two_things(
        store, label="A3", statement_full="定理：丙。"))
    assert with_refs["deps_state"] == "from_proof", with_refs
    assert without_refs["deps_state"] == "none_in_proof", without_refs
    assert not_given["deps_state"] == "unknown", not_given
    assert len({with_refs["deps_state"], without_refs["deps_state"],
                not_given["deps_state"]}) == 3, "三档被折平了"
    # `none_in_proof` 是"扫了、确实是空的"（不是"没记录"）⇒ 它照样把依赖表读成空
    assert _deps_of(store, without_refs["stmt_id"]) == []
    assert not without_refs["deps_dangling"] and not without_refs["deps_unmappable"]


# ==================================================== 四、路径分组：给就分、不给不猜

def test_explicit_proof_paths_become_path_groups(store):
    """多段可选证明（B 自己分的段）⇒ `path_group` 1,2,…；不给 ⇒ 全归第 1 组。"""
    add_literature(store, "0003", title="引理", processed=True)
    add_literature(store, "0004", title="另一篇", processed=True)
    sec = _sec(store)
    out = sec.record_statement(_two_things(
        store, label="P1", statement_full="定理：两条路。",
        proof_text="（这一段只说明有两条路，本身不引号）",
        proof_paths=["路一：由 lit:0003 推出。", "路二：由 lit:0004 与 stmt:0002 推出。"]))
    assert out["checked"] and out["path_groups"] == 2, out
    groups = {d["label"]: d["path_group"] for d in _deps_of(store, out["stmt_id"])}
    assert groups == {"lit:0003": 1, "lit:0004": 2, "stmt:0002": 2}, groups
    # 不给分段标记 ⇒ 一段（不按空行或"证明一/证明二"这种字样去猜）
    out2 = sec.record_statement(_two_things(
        store, label="P2", statement_full="定理：一条路。",
        proof_text="证明一：由 lit:0003。\n\n证明二：由 lit:0004。"))
    assert out2["path_groups"] == 1, out2
    assert {d["path_group"] for d in _deps_of(store, out2["stmt_id"])} == {1}


# ==================================================== 五、两条路的口径不许互相污染

def test_explicit_deps_keep_the_strict_path(store):
    """显式给的 `deps` 仍走严格那一条（指着一个不在册的号 = 整笔不写）：两条路不许混。"""
    out = _sec(store).record_statement(_two_things(
        store, proof_text="证明：由 stmt:0777 推出。",
        deps=[[{"stmt_id": "0777", "kind": "theorem", "label": "不存在的命题"}]]))
    assert not out["checked"] and out["refused"] == "unresolved_dependency", out
    assert store.rows("statements") == [], "显式依赖悬空 ⇒ 一行都不许落"
    assert store.rows("dependencies") == []


def test_the_scan_is_the_same_implementation_as_the_citation_parser(store):
    """反真空：扫描器与"解析一条 citation"共用一处口径（`textutil`），不是第二份。"""
    from agentflow import schema as S
    from agentflow import textutil as T

    got = T.find_citations("见 lit:0003#p.4、lit:0003 与 stmt:0001，以及不在册的 xyz:0009")
    assert [r["raw"] for r in got] == ["lit:0003#p.4", "stmt:0001"], got
    assert got[0]["table"] == S.CITATION_PREFIXES["lit"] and got[1]["table"] == S.CITATION_PREFIXES["stmt"]
    for r in got:
        assert T.citation_ref_parts(r["raw"]) == (r["prefix"], r["code"]), r
    assert T.find_citations("") == [] and T.find_citations(None) == []
    assert T.find_citations("见 stmt:0001", prefixes=("lit",)) == [], "显式收窄前缀要生效"


# ==================================================== 六、B 那一侧的读数（载体那一步的输入）

def test_b_surfaces_the_pending_definition_and_the_scanned_deps(store):
    """B 的动作要把"依赖是扫出来的"与"哪一条定义待补、该问谁"写进返回值。

    业主 `draft/97` §15.4 的补法优先级是①先问直接父 → ②A 上网搜 → ③B 自撰；
    循环那一层才是"知道自己的父是谁"的地方，所以这一格的职责只有一个：
    把给谁写清楚（`who="direct_parent"`），别让上面那一层去猜。
    """
    from agentflow.agent_b import AgentB

    add_literature(store, "0003", title="群论引理", processed=True)
    b = AgentB(store, extractor=None, extract_text=None)
    out = b.register_statement(
        origin="own_result", kind="theorem", label="T1",
        statement_full="定理：对任意群 G，命题 ph 成立。",
        proof_text="证明：由 lit:0003 的引理推出，并用 stmt:0777（还没进库）。",
        quote_reason="自产：没有第二份文本可比（证明过程见 proof_text）",
        line_range={"start": 1, "end": 9})
    assert out["ok"] is True, out
    assert out["deps_state"] == "from_proof" and out["deps_written"] == 2, out
    assert [d["ref"] for d in out["deps_dangling"]] == ["stmt:0777"], out["deps_dangling"]
    assert out["pending_definitions"] == [], "命题不缺定义 ⇒ 这一档不许凭空冒出来"
    # `own_result` 也要给 `quote_reason`（三态纪律不按 origin 放宽：本轮试过，被
    # `test_action_surface_matches_acceptance` 的"每一级缺失都被拒"判红）⇒ 给一个理由就落得下
    out1b = b.register_statement(
        origin="own_result", kind="theorem", label="T2",
        statement_full="定理：另一条自产命题。", proof_text="证明：由定义直接得到。",
        quote_reason="自产：没有第二份文本可比，所以这一格是'还没核'",
        line_range={"start": 12, "end": 20})
    assert out1b["ok"] is True, out1b
    row1b = next(r for r in store.rows("statements") if r["stmt_id"] == out1b["stmt_id"])
    assert row1b["quote_reason"].startswith("自产"), row1b["quote_reason"]
    assert row1b["line_range"]["start"] == 12, row1b["line_range"]
    # 概念（定义还没抽到，正是 §15.4 那个场景：B 消化 A 查回来的论文时撞到生僻定义）
    # ⇒ 读数点名"问直接父"
    out2 = b.register_statement(origin="external_lit", kind="concept", label="生僻概念 X",
                                statement_full="", source_lit_id="0003",
                                page_range={"start": 3, "end": 4},
                                quote_reason="定义还没从原文里抽到 ⇒ 待补")
    assert out2["ok"] is True, out2
    defs = out2["pending_definitions"]
    assert len(defs) == 1 and defs[0]["kind"] == "pending_definition", defs
    assert defs[0]["who"] == "direct_parent" and defs[0]["id"] == out2["stmt_id"], defs
    assert "直接父" in defs[0]["why"], defs
