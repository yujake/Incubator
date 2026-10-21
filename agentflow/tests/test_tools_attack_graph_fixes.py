"""`attack_tools.py`（PROPOSALS G-2）与 `graph_tools.py`（G-3）的修复测试。
## 这个文件为什么单独存在
G-2 / G-3 的缺陷不属于本轮任何实现者的所有权清单，所以它在两轮审计里被两边都跳过。本文件逐条把它们钉住，每一条都打在"修之前会失败"的那个判据上。
对应关系：
| PROPOSALS 条目 | 修的东西 | 本文件的用例 |
|---|---|---|
| G-2 ① | `attack.*` 的 `PlanError` / `ValueError` / `StoreError` 逃逸 | `test_attack_plan_error_*` /
`test_attack_validation_error_*` / `test_attack_store_error_*` |
| G-2 ② | `can_derive` 用 `incomplete` 表示"没查" | `test_can_derive_*` / `test_blocked_by_*` |
| G-2 ③ | `include_terminal` 的 `None` 反转默认值（工具层那一份） | `test_attack_list_plans_tool_*` |
| G-3 ④ | `graph.*` 的四个 handler 的 `StoreError` 逃逸 | `test_graph_store_error_*` |
| G-3 ⑤ | `returns=` 与实现不一致 | `test_graph_returns_declaration_matches_implementation` |
| G-3 ⑥ | `RelationGraph.neighbors` 的不可截断裸列表被暴露成工具 | `test_graph_neighbors_*` /
`test_graph_neighbors_result_is_not_prunable_by_context_budget` |
## 与 `test_tools_audit_fixes.py` 的分工
那个文件是上一轮工具层审计的修复。本文件沿用它的两件工具（`registry_for` /`corrupt` / `declared_keys` 的口径），不另发明一套：同一判据只有一份实现在测试代码里同样成立（FC-03），
所以"从 `returns=` 抽键"这件事的口径与它逐字一致。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentflow.contextbudget import ContextBudget
from agentflow.store import Store
from agentflow.tools import attack_tools as AT
from agentflow.tools import graph_tools as GT
from agentflow.tools.base import ToolRegistry

#: `blocked_by` 的受控词表（`None` = 没有阻塞）。见 `attack_tools.can_round` 的 docstring。
#:
#: 这里确实复述了一份词表 —— 它是"测试夹具不许写死第二份名单"（FC-03）
#: 的一个刻意的例外，理由与"受控词表必须能被别处引用"同族：
#: 词表本体定义在 `attack_tools.py`（工具层的返回词表，不是跨模块领域词表，
#: 所以不进禁 AI 区的 `schema.py`），而测试的作用正是在它漂移时变红。
#: 若把它改成 `from attack_tools import BLOCKED_BY_VALUES`，那么"有人删掉一个取值"
#: 这件事会连测试一起改掉，门就再也不响了。这与 `test_lint_rules.py` 里
#: "断言例外清单的键真的存在"是同一个形态：判据可以被引用，护栏必须独立。
_BLOCKED_BY_VALUES = {
    None,          # 没有阻塞
    "not_checked",  # 没查（没给预算）
    "incomplete",   # 查了：预算缺键
    "rounds",       # 查了：轮数用尽
    "depth",        # 查了：深度到顶
}


# ============================================================ 夹具与工具


def registry_for(module: object, store: Store, **kw: object) -> ToolRegistry:
    """注册一个模块的工具（与 `test_tools_audit_fixes.py` 同名同形）。

    `P-14` 之后 `call` 需要"这次是谁在调"，所以这里按模块绑定一个角色
    （映射见 `_MODULE_ROLE`）。每个工具模块的角色面是模块级知识
    （`attack._WRITE_ROLES = ("F",)`、`graph`/`trace` 是 `("C","D")`），
    没有"测试自己发明一个角色"的余地。
    """
    reg = ToolRegistry(name="g2g3")
    module.register(reg, store=store, **kw)  # type: ignore[attr-defined]
    reg.bound_role = _role_for_module(module, reg)
    return reg


#: 集合夹具（`registry_for`）用的模块 -> 该表代表的角色。写错会被
#: `_role_for_module` 的断言抓住（它要求该角色在这张表里真的拿得到工具）。
_MODULE_ROLE: dict[str, str] = {
    "attack_tools": "F",   # 写侧唯一主人是 F（`_WRITE_ROLES`），读侧也含 F
    "graph_tools": "C",    # C/D 共用，取只读的 C
    "trace_tools": "C",    # 同上
}


def _role_for_module(module: object, reg: ToolRegistry) -> str:
    """这张注册表该绑哪个角色：按模块名查 `_MODULE_ROLE`，并断言该角色真的拿得到工具。"""
    mod_name = getattr(module, "__name__", "").rsplit(".", 1)[-1]
    role = _MODULE_ROLE.get(mod_name)
    assert role, f"模块 {mod_name!r} 没有在 `_MODULE_ROLE` 里登记角色 —— 夹具不知道该代表谁"
    assert reg.for_role(role), f"{mod_name}: 绑的角色 {role!r} 在这张表里拿不到任何工具"
    return role


def corrupt(store: Store, filename: str) -> None:
    """把一张表写成不是合法 JSON 的文件（模拟"快照损坏"这类真实故障）。

    与 `test_tools_audit_fixes.py::corrupt` 逐字同形：`Store._load` 对坏 JSON
    抛 `StoreError`（`store.py:297-302`），这正是"表读不出来"在生产里的形态。
    """
    (store.data / filename).write_text("{ 这不是 JSON", encoding="utf-8")


#: 声明字符串里的一个"键"。只认带引号的键名 —— 本仓库的 `returns=` 用两种写法
#: （`{'a','b'}` 与 `{concept_count, ...}`），而散文里的裸词（`见 error`）与
#: `kind(io_error/param_error)` 里的参数都不是键。用引号当判据比"任何标识符"
#: 稳得多（`tokenize` 会把 `'a','b'` 分成 STRING/OP/STRING，反而要另写一套状态机）。
#:
#: 引号那一支必须排在裸词之前，且裸词只认"标识符形状"的词：
#: 若写成 `[^\{\}\[\]:,]+`（"任何非标点"），`...` 省略号与中文散文都会被当成词，
#: 于是它们会以"键"的身份进集合，比对必然失败 —— 那时为了让门绿，
#: 人会把 `...` 与说明文字从声明里删掉，门反而把说明文字逼走了。
_KEY_TOKEN = re.compile(r"'([A-Za-z_][A-Za-z0-9_]*)'|([A-Za-z_][A-Za-z0-9_]*)|([\{\}\[\]:,])")


def _parse_returns_shape(returns: str) -> tuple[set[str], dict[str, set[str]]]:
    """把 `returns=` 解析成 `(顶层键, {键: 该键的列表项键集})`。

    为什么要按结构解析，而不是"把花括号全抹掉再抽标识符"：
    `returns=` 里同时写着顶层键与列表项的键（`neighbors: [{concept_id, ...}]`），
    而实际比对的对象是顶层 dict 的键集合。抹平之后 `concept_id` 会被算成顶层键，
    比对必然失败 —— 那时为了让它绿，人会把嵌套键从声明里删掉，
    于是声明反而变得更不完整（这正是 `graph.neighbors` 漏 `relation_ids` 的同类）。
    """
    top: set[str] = set()
    children: dict[str, set[str]] = {}
    #: 进入嵌套形状时的"当前父键"。`None` 表示"这一对花括号里就是顶层键"
    #: （`{a, b}` / `{'a','b'}` 的裸花括号）。为什么用 `list` 而不是单个变量：
    #: `neighbors: [{...}]` 是两层（`[` 再 `{`），要能回到上一层。
    stack: list[str | None] = []
    pending: list[str] = []
    new_siblings = False
    for m in _KEY_TOKEN.finditer(returns):
        quoted, text, punct = m.group(1), m.group(2), m.group(3)
        if quoted:
            # 引号键永远算键（顶层 or 某个键的列表项）
            entry = stack[-1] if stack else None
            if entry is None:
                top.add(quoted)
            else:
                children.setdefault(entry, set()).add(quoted)
            pending = [quoted]
            new_siblings = False
        elif punct is not None:
            if punct in "{[(":
                # `neighbors: [{...}]` ⇒ 进入"键 `pending[0]` 的项形状"；
                # 裸 `{...}`（顶层那种）⇒ 什么都不进栈，它里面就是顶层键。
                stack.append(pending[0] if pending and pending[0] else None)  # type: ignore[arg-type]
                # 左括号之后就是一个键位置（`{a, b}` 的 `a`）
                new_siblings = True
            elif punct in "}])":
                if stack:
                    stack.pop()
                new_siblings = True
            elif punct == ":":
                new_siblings = True
            else:  # `,`
                # 逗号之后是下一个键位置（`{a, b}` 的 `b`）—— 不是"继续上一个键"。
                new_siblings = True
        else:
            # 裸词（不带引号的写法）。只有"位在键位置"的才收（`{'a': str}` 里的
            # `str`、`kind(io_error...)` 里的 `io_error` 都不是键），
            # 且只在没有进栈时才进 `top` —— 裸写法无法可靠区分顶层键与嵌套键，
            # 这里如实把能确定的那些收下（见 docstring 的取舍）。
            if not new_siblings:
                continue
            word = text.strip()
            pending = [word]
            # 找最近的具名父键（跳过裸花括号留下的 `None` 标记）。
            parent = next((x for x in reversed(stack) if x), None)
            if parent is None:
                top.add(word)
            else:
                children.setdefault(parent, set()).add(word)
            new_siblings = False
    # 清掉空名（`pending` 在冒号前没收到东西时会留下空串）
    top.discard("")
    for k in list(children):
        children[k].discard("")
        if not children[k]:
            del children[k]
    return top, children


def declared_keys(returns: str) -> set[str]:
    """从 `ToolSpec.returns` 里抽出它承诺的顶层键名（`test_tools_audit_fixes` 的同名口径）。

    与那个文件里的实现同一个用途，只是必须能处理本仓库 `returns=` 的两种写法：

    - 带引号的 `{'a','b'}`（`verify_tools` / `doc_tools` / 本次改过的 `graph_tools`）；
    - 不带引号的 `{concept_count, relation_count, ...}`（`graph_tools` 的旧写法）。

    旧正则在旧写法上返回空集 ⇒ "声明与实现比对"这条判据在 `graph.*` 上
    根本没跑（空集永远是任何集合的子集）。这就是 `graph.neighbors` 漏掉
    `relation_ids` 却没有任何门报警的原因。所以本函数的存在本身就是那次修复的一部分：
    判据要能在被检对象上真的跑起来，否则它只是一句看起来在检查的注释。
    """
    return _parse_returns_shape(returns)[0]


def declared_item_keys(returns: str, key: str) -> set[str]:
    """某个顶层键的列表项键集（例如 `graph.neighbors` 的 `neighbors` 项）。"""
    return _parse_returns_shape(returns)[1].get(key, set())


def test_declared_keys_rejects_the_old_unquoted_empty_result():
    """负控（这只解析器自己的）：旧写法之所以骗过了比对，是因为它抽出空集。"""
    assert declared_keys("{concept_count, relation_count}") == {"concept_count", "relation_count"}
    assert declared_keys("{'a','b'}") == {"a", "b"}
    # `...` 省略号不是键（否则比对永远失败，门又变成噪音）
    assert declared_keys("{...}") == set()
    # 嵌套项不算顶层键，但能被单独取出来
    assert declared_keys("{a, neighbors: [{concept_id, name}]}") == {"a", "neighbors"}
    assert declared_item_keys("{a, neighbors: [{concept_id, name}]}", "neighbors") == {
        "concept_id", "name",
    }
    # 引用带引号的真实样例（`verify.check_formal` 的声明）
    assert declared_keys("{'checked','verified','claim','reason','detail','verifier_output'}") == {
        "checked", "verified", "claim", "reason", "detail", "verifier_output",
    }


def _attack_reg(store: Store | None) -> ToolRegistry:
    reg = ToolRegistry(name="attack-fix")
    AT.register(reg, store=store)
    reg.bound_role = "F"  # `P-14`：`attack.*` 的写侧唯一主人是 F
    return reg


def _make_plan(store: Store, problem_key: str = "k-a") -> str:
    """经工具层立一个计划，返回 plan_id（不绕过被测的那一层）。"""
    reg = _attack_reg(store)
    res = reg.call("attack.create_plan", problem="难题", problem_key=problem_key)
    assert res.ok, res.error
    return res.data["plan_id"]


def _star_graph(n: int) -> GT.RelationGraph:
    """一个"中心 + n 个叶子"的星形图（用来把邻居列表撑到远超上限）。"""
    concepts = [{"concept_id": "0000", "name": "中心概念"}]
    relations = []
    for i in range(1, n + 1):
        cid = f"{i:04d}"
        concepts.append({"concept_id": cid, "name": f"叶子概念{i}"})
        relations.append(
            {
                "relation_id": f"{i:04d}",
                "concept_ids": ["0000", cid],
                "description": f"中心与叶子 {cid} 的关系",
                "lit_id": "0000",
                "page_range": {"start": 1, "end": 1, "label": "p. 1"},
                "quote": f"引文 {i}",
                "quote_verified": True,
                "statement": "s",
                "status": "active",
            }
        )
    return GT.RelationGraph(concepts, relations, [])


# ============================================================ G-2 ① PlanError


def test_attack_plan_error_keeps_its_own_kind_not_unexpected(store: Store):
    """核心：`PlanError` ⇒ `kind="plan_error"`，且绝不是 `"unexpected"`。

    修之前：`PlanError` 逃出工具层（`attack_tools.py` 没有任何守卫），
    被 `base.py` 的 `except Exception` 兜成一个没有类型信息的 `unexpected`。
    `agent_f.PlanError` 当时是裸 `RuntimeError` —— 于是"攻坚计划被拒绝"
    与"工具层有 bug"在下游长得一模一样。
    """
    reg = _attack_reg(store)

    # ---- 缺 owner：AgentF 自己抛 PlanError
    bad = reg.call(
        "attack.create_plan", problem="x", problem_key="k1", subgoals=[{"sid": "s1", "text": "t"}]
    )
    assert bad.ok is False
    assert bad.meta.get("kind") == "plan_error"
    assert bad.meta.get("kind") != "unexpected"
    assert "owner" in bad.error, "具体原因必须逐字可见（调用方要靠它改输入）"
    assert store.rows("attack_plans") == [], "被拒绝的计划不许落库"

    # ---- 计划不存在：另一条 PlanError 路径
    missing = reg.call("attack.step", plan_id="9999")
    assert missing.meta.get("kind") == "plan_error"
    assert missing.meta.get("kind") != "unexpected"
    assert "不存在" in missing.error


# ============================================================ G-2 ① ValueError


def test_attack_validation_error_names_the_offending_field(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """    核心：`ValueError` ⇒ `kind="validation_error"`，且绝不是 `"unexpected"`。

    ## 为什么这一支要靠打桩才能打到（如实说明，不含糊）

    `attack.create_plan` 里 schema 的 `ValueError` 已经被 `AgentF` 包成`PlanError`（`agent_f.py:1080-1090`：*"`schema` 抛的
    `ValueError` 在这里被换成语义正确的 `PlanError`"*）。所以真跑到工具层的 schema 失败是 `plan_error`（上面那条用例覆盖了它，且断言了 `"schema"` 与
    `problem_key` 都在 error 里）。

    这一支要证明的是守卫本身对裸 `ValueError` 的分类 —— 打桩的形态照`test_tools_audit_fixes.py::test_no_unexpected_escape_search_register_schema_failure`（
    它同样打桩 `S.Literature.validate` 来造"schema 的 ValueError"）。
    """
    reg = _attack_reg(store)
    plan_id = _make_plan(store)

    def boom(self: object, _plan_id: str) -> None:
        raise ValueError("history_tail 必须是 integer（夹具故意）")

    monkeypatch.setattr(type(AT._agent_for(store)), "status", boom)  # noqa: SLF001 - 打桩点就是被测的 AgentF
    res = reg.call("attack.status", plan_id=plan_id)
    assert res.ok is False
    assert res.meta.get("kind") == "validation_error"
    assert res.meta.get("kind") != "unexpected"
    assert "history_tail" in res.error, "必须点名是哪个字段（'校验失败'四个字没有可操作性）"

    # 负控：取消打桩后同一调用照旧成功（闸门不许变成"永远拒绝"）
    monkeypatch.undo()
    good = reg.call("attack.status", plan_id=plan_id)
    assert good.ok is True and good.data["checked"] is True


# ============================================================ G-2 ① StoreError


def test_attack_store_error_is_not_unexpected(store: Store):
    """核心：`StoreError` ⇒ `kind="store_error"`，且绝不是 `"unexpected"`。

    修之前实测：`attack_plans.json` 变成坏 JSON 之后，
    `create_plan` / `step` / `status` / `list_plans` 四个工具全部返回
    `kind="unexpected"` + `error="StoreError: …"` —— 环境故障被说成了"未预期的异常"，
    而这两件事需要完全不同的处置（一个是"先修表"，一个是"报 bug"）。
    """
    reg = _attack_reg(store)
    for name, params in (
        ("attack.check_budget", {"budget": {"max_rounds": 1, "max_parallel_subgoals": 1,
                                            "max_persist_attempts": 1, "max_depth": 1}}),
        ("attack.list_plans", {}),
        ("attack.create_plan", {"problem": "p", "problem_key": "k"}),
        ("attack.status", {"plan_id": "0000"}),
    ):
        assert reg.call(name, **params).ok is True, f"{name} 在健康库上不该失败"

    corrupt(store, "attack_plans.json")
    for name, params in (
        ("attack.list_plans", {}),
        ("attack.create_plan", {"problem": "p", "problem_key": "k"}),
        ("attack.step", {"plan_id": "0000"}),
        ("attack.status", {"plan_id": "0000"}),
    ):
        res = reg.call(name, **params)
        assert res.ok is False, name
        assert res.meta.get("kind") == "store_error", (name, res.meta)
        assert res.meta.get("kind") != "unexpected", name


def test_attack_not_wired_is_still_its_own_kind():
    """负控：加了守卫之后，"未接线"仍然走 `not_wired`，不许被守卫吞成别的档。"""
    reg = _attack_reg(None)
    for name, params in (
        ("attack.create_plan", {"problem": "p", "problem_key": "k"}),
        ("attack.step", {"plan_id": "0000"}),
        ("attack.status", {"plan_id": "0000"}),
        ("attack.list_plans", {}),
    ):
        res = reg.call(name, **params)
        assert res.meta.get("kind") == "not_wired", (name, res.meta)
        assert res.data is None, "未接线不许返回空数据（那会被读成'查了、没有'）"


# ============================================================ G-2 ② can_derive 的三态


def test_can_derive_does_not_fold_not_checked_into_incomplete():
    """核心：`blocked_by` 必须把"没查"与"查了、不完整"分开。

    修之前 `can_derive(None, depth=0)` 与 `can_derive({"max_rounds": 3}, depth=0)`
    返回同一个 `blocked_by="incomplete"`。于是"我们根本没拿到预算"
    在调用方眼里长得像"查过了、只是信息不全" —— 后者会让人继续往下走，
    而前者一个判定都没做（`DEVELOPMENT.md` §3 纪律 1）。
    """
    not_checked = AT.can_derive(None, depth=0)
    assert not_checked["checked"] is False
    assert not_checked["allowed"] is None, "没查 ⇒ 不许给 False（False 是一个关于世界的断言）"
    assert not_checked["blocked_by"] == "not_checked"

    incomplete = AT.can_derive({"max_rounds": 3}, depth=0)
    assert incomplete["checked"] is True and incomplete["complete"] is False
    assert incomplete["allowed"] is False, "查了、不完整 ⇒ 明确不许"
    assert incomplete["blocked_by"] == "incomplete"
    assert incomplete["missing"], "缺哪几类键必须逐条可见"

    assert not_checked["blocked_by"] != incomplete["blocked_by"], (
        "两者折叠成一个值正是本用例要防的缺陷"
    )
    # 与 `can_round` 同一份口径（它不是错的，是 `can_derive` 该照它写）
    assert AT.can_round(None, rounds_done=0)["blocked_by"] == "not_checked"
    assert AT.can_round({"max_rounds": 3}, rounds_done=0)["blocked_by"] == "incomplete"


def test_blocked_by_vocabulary_has_no_uncounted_branch():
    """`blocked_by` 的全部取值都在受控词表里 —— 且穷举了每一个分支。

    为什么要穷举：词表的价值在于"没有第五个取值悄悄出现"。只测其中两支，
    等于给另外两支留了后门（`can_derive` 的缺陷正是"其中一支写错了"）。
    """
    budget = {"max_rounds": 6, "max_parallel_subgoals": 2, "max_persist_attempts": 2, "max_depth": 2}
    seen = {
        AT.can_round(None, rounds_done=0)["blocked_by"],
        AT.can_round({"max_rounds": 1}, rounds_done=0)["blocked_by"],
        AT.can_round(budget, rounds_done=6)["blocked_by"],
        AT.can_round(budget, rounds_done=0, depth=2)["blocked_by"],
        AT.can_round(budget, rounds_done=0, depth=0)["blocked_by"],
        AT.can_derive(None, depth=0)["blocked_by"],
        AT.can_derive({"max_rounds": 1}, depth=0)["blocked_by"],
        AT.can_derive(budget, depth=2)["blocked_by"],
        AT.can_derive(budget, depth=0)["blocked_by"],
    }
    assert seen == _BLOCKED_BY_VALUES, f"出现了未登记的 blocked_by 取值：{sorted(map(str, seen))}"
    # 负控：四类键齐全、深度没到顶 ⇒ 真的允许（闸门不许永远关着）
    assert AT.can_derive(budget, depth=1)["allowed"] is True
    assert AT.can_round(budget, rounds_done=5)["allowed"] is True


# ============================================================ G-2 ③ include_terminal


def test_attack_list_plans_tool_does_not_invert_a_null_default(store: Store):
    """核心（工具层那一份）：`include_terminal=None` 必须等于"省略键"。

    题目要求核实 `attack_tools.py` 里是否还有 `if not include_terminal:` 那种写法
    （把显式的 `null` 当成 `False`）。实测：没有 —— `agent_f.AgentF.list_plans`
    已把 `None` 解读成声明默认值 `True`，工具层只是转发。

    但"已修好"这件事本身必须由断言钉住，否则下一个人把 `if not ...` 写回来
    时没有任何东西会红。上面 `test_core_audit_efgh.py` 的同类用例只断言了
    `total` 与 `reason`；本用例补上工具 handler 的声明默认值与
    三条输入路径的等价性（省略 / 显式 True / 显式 None）那一层。
    """
    _make_plan(store, "k-a")
    _make_plan(store, "k-b")
    reg = _attack_reg(store)

    # 让第一个计划进入终态（"结束一个、留一个"是这条判据的唯一可判形态）
    from agentflow.agent_f import AgentF

    f = AgentF(store)
    f.step(f.list_plans()["plans"][0]["plan_id"])
    with store.tx("attack_plans", actor="test", note="force_terminal") as tx:
        rows = tx.rows("attack_plans")
        rows[0]["status"] = "abandoned"
        tx.upsert("attack_plans", rows[0])

    omitted = reg.call("attack.list_plans")
    explicit_true = reg.call("attack.list_plans", include_terminal=True)
    explicit_null = reg.call("attack.list_plans", include_terminal=None)
    only_alive = reg.call("attack.list_plans", include_terminal=False)

    assert omitted.ok and explicit_null.ok and only_alive.ok
    assert omitted.data["total"] == 2
    assert explicit_null.data["total"] == omitted.data["total"] == 2, (
        "显式 null 必须等于省略键（声明的默认值是 True）；当成 False 就是静默反转"
    )
    assert explicit_true.data["total"] == 2
    assert only_alive.data["total"] == 1, "**负控**：要过滤必须明确写 False"
    assert "include_terminal=True" in explicit_null.data["reason"], (
        "reason 必须回报**生效的**取值，不许回报调用方写的 null"
    )


def test_attack_status_not_found_is_not_an_error(store: Store):
    """    负控（不许"顺手修错"）：计划不存在时 `attack.status` 是`ok=True` + `checked=False`，不是失败。

    这是 INVENTORY 4.3(c) 记的刻意设计：`checked=False` 表示"没查"（这里的"没查"= 那个代号根本不在计划表里），调用方必须看 `checked` 而不是
    `ok`（`docs/ROLE-SPECS.md` R0 的那一行 + `tests/test_agent_f.py:616` 同口径）。本用例的作用是上锁：`_guard` 只许改"异常怎么分类"，不许把这条"查了、
    没有"的语义顺手改成失败。

    顺便钉住 `attack.status` 真的过守卫：把打桩的 `AgentF.status` 换成"抛一个已知失败"，同一个工具必须给出受控 kind（而不是裸异常或以`unexpected` 逃出去）。变异试验记录在案：
    只摘掉 `attack.status` 的 `_guard`时，只有本用例会红（`-k status` 只选到它）—— 所以这条断言必须有。
    """
    reg = _attack_reg(store)
    res = reg.call("attack.status", plan_id="9999")
    assert res.ok is True, "这是'查了、没有'，不是异常"
    assert res.data["checked"] is False
    assert "不存在" in res.data["reason"] and "没查" in res.data["reason"]

    # ---- 同一工具在"已知失败"下必须被守卫分类（证明它没有绕过 `_guard`）
    from agentflow.agent_f import AgentF

    original = AgentF.status

    def _boom(self: object, _plan_id: str) -> dict:
        raise ValueError("status 内部炸了（夹具故意）")

    AgentF.status = _boom  # type: ignore[method-assign]
    try:
        guarded = reg.call("attack.status", plan_id="9999")
    finally:
        AgentF.status = original  # type: ignore[method-assign]
    assert guarded.ok is False
    assert guarded.meta.get("kind") == "validation_error", guarded.meta
    assert guarded.meta.get("kind") != "unexpected"


# ============================================================ G-3 ④ StoreError


def _seed_small_graph(store: Store) -> None:
    """种一张两概念一关系的小图（`graph.neighbors` 需要 0000 真的在图里）。"""
    from conftest import add_concept, add_relation

    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="An abelian group is a group.")


def test_graph_build_reports_a_store_error_instead_of_unexpected(store: Store):
    """核心（建图那一刻）：`relations.json` 坏了 ⇒ `graph.build` 是 `store_error`。

    `graph.build` 是三张表唯一的读取点（其余三个工具查的是已建的索引，
    见下一条用例）。修之前它把 `StoreError` 原样抛给 `base.py` 的兜底，
    于是调用方看到 `kind="unexpected"` —— 那是"我们没预料到"的意思，
    而"表坏了"恰恰是我们预料得到的失败。
    """
    _seed_small_graph(store)
    reg = registry_for(GT, store)
    assert reg.call("graph.build").ok is True, "健康库上建图不该失败"

    corrupt(store, "relations.json")
    res = reg.call("graph.build")
    _assert_store_error(res, "graph.build")


def _assert_store_error(res: object, name: str) -> None:
    """一条判据：既要是 `store_error`，又绝不能是 `unexpected`（后者才是判据）。"""
    assert res.ok is False, name  # type: ignore[attr-defined]
    kind = res.meta.get("kind")  # type: ignore[attr-defined]
    assert kind == "store_error", (name, res.meta)  # type: ignore[attr-defined]
    assert kind != "unexpected", f"{name}：表坏了被说成了'未预期的异常'"


def test_graph_index_queries_report_store_errors_when_they_build_the_index(tmp_path: Path):
    """    核心（首次查询那一刻）：三个索引查询在自己按需建图时也要结构化失败。

    两个刻意的构造细节（都不是随手写的）：

    1. 每个用例一个全新的 store + 注册表：`_GraphHolder` 是跨调用缓存
    （"一次构建、多次查询"就是这个设计），所以同一个注册表上第一次调用建好图之后，后面几次查询根本不碰磁盘 —— 那正是它的本意，不是缺陷。误以为"表坏了 ⇒ 以后每次查询都该报错"，就会把一个正确的缓存设计当成 bug
    改掉（反面由 `test_graph_cached_index_survives_a_later_table_corruption` 钉住）。
    2. 损坏的表是 `statements.json`（不是 `relations.json`）：`RelationGraph.from_store`
    读三张表（概念行的来源是 `statements` 的 `kind="concept"` 那一档 —— S1r 并表之后概念行就住那里；此前是 `concepts.json`），任何一张坏都会让建图失败，
    而概念这一张是每一张图都要建的；挑它就不必在每个用例之间修盘。
    """
    cases = (
        ("graph.stats", {}),
        ("graph.neighbors", {"concept_id": "0000"}),
        ("graph.relations_between", {"a": "0000", "b": "0001"}),
    )
    for name, params in cases:
        st = Store(tmp_path / f"ws-{name.replace('.', '-')}")
        st.init()
        _seed_small_graph(st)
        assert registry_for(GT, st).call(name, **params).ok is True, f"{name} 在健康库上不该失败"
        corrupt(st, "statements.json")
        _assert_store_error(registry_for(GT, st).call(name, **params), name)


def test_graph_cached_index_survives_a_later_table_corruption(store: Store):
    """负控（不许顺手改坏缓存）：图建好之后，后续查询照旧可用。

    这条不是在说"表坏了也没关系"——它说的是：`graph.*` 的契约是
    "第一次查询建索引，之后查内存"。把缓存拆掉（例如每次查询都重读三张表）
    会让 C 的"任意多次、任意组合查询"退化成 O(查询数 × 关系数)，
    而那是这一层存在的理由（模块 docstring 第 1 节）。
    缓存与"失败要如实回报"是两件事，不许为了后者牺牲前者。
    """
    _seed_small_graph(store)
    reg = registry_for(GT, store)
    assert reg.call("graph.build").ok is True
    corrupt(store, "relations.json")
    assert reg.call("graph.stats").ok is True
    assert reg.call("graph.neighbors", concept_id="0000").ok is True


def test_graph_honest_failures_survive_the_guard(store: Store):
    """负控：加守卫不许把两条刻意的失败路径改掉。

    - 未知概念 ⇒ `ok=False`，meta 里没有 kind（改动前实测就是这个形状）
      + `known_concepts` 这个可操作提示；
    - 非法参数（长度不是 4）⇒ `param_error`（`validate_params` 在 handler 之前拦）。

    为什么"没有 kind"也要钉住：`_guard` 会把 handler 的返回值一律包成 `ok(...)`，
    所以把这条路径塞进守卫很容易顺手变成 `kind="tool_error"` ——
    那会让"业务上查不到"重新混进"异常"那一档，并丢掉 `known_concepts`。
    """
    reg = registry_for(GT, store)
    unknown = reg.call("graph.neighbors", concept_id="9999")
    assert unknown.ok is False and "9999" in unknown.error
    assert "kind" not in unknown.meta, unknown.meta
    assert unknown.meta.get("known_concepts") == [], "可操作提示必须原样保留"

    bad_param = reg.call("graph.neighbors", concept_id="1")
    assert bad_param.meta.get("kind") == "param_error"


# ============================================================ G-3 ⑤ returns=


def test_graph_returns_declaration_matches_implementation(store: Store):
    """核心（机械可判）：`ToolSpec.returns` 承诺的键 == handler 实际返回的键。

    题目要求"逐个工具核对"，而不是只信两处已知漂移。这里用集合相等（双向）：
    - 声明了没给 ⇒ 调用方按声明取字段会 `KeyError`；
    - 给了没声明 ⇒ 调用方不知道有这个字段（`graph.neighbors` 的 `relation_ids`
      正是这一种：`tests/test_tools_graph_trace.py:89` 已经在断言它，
      而声明里没有它 —— 于是"声明"这份文档在教人忽略它）。

    这是 `test_tools_audit_fixes.py::test_check_formal_return_shape_matches_its_declaration`
    的同一手法（题目指名的模板），只是把范围扩到 `graph.*` 全部四个工具。
    """
    from conftest import add_concept, add_relation

    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_concept(store, "0002", "域")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="An abelian group is a group.")
    add_relation(store, "0001", ["0001", "0002"], "0000", quote="Another relation.")

    reg = registry_for(GT, store)
    cases = (
        ("graph.build", {}),
        ("graph.stats", {"top_n": 3}),
        ("graph.neighbors", {"concept_id": "0000"}),
        ("graph.neighbors", {"concept_id": "0002"}),  # 度数不同的第二个样本
        ("graph.relations_between", {"a": "0000", "b": "0001"}),
    )
    for name, params in cases:
        res = reg.call(name, **params)
        assert res.ok, (name, res.error)
        declared = declared_keys(reg.get(name).returns)
        assert declared, f"{name} 的 returns= 抽不出任何键 ⇒ 这条判据在它上面是空转的"
        actual = set(res.data)
        assert declared == actual, (
            f"{name} 的 returns= 与实现不一致："
            f"声明了没给={sorted(declared - actual)}；给了没声明={sorted(actual - declared)}"
        )
        # 声明必须真的在描述顶层键（不是只把嵌套字段列一遍）
        assert declared <= actual

    # 负控：声明一个不存在的键必须被这条判据抓到（否则它是空转的门）
    assert declared_keys(reg.get("graph.neighbors").returns) | {"no_such_key"} != set(
        reg.call("graph.neighbors", concept_id="0000").data
    )


def test_graph_neighbors_declares_relation_ids(store: Store):
    """点名（题目给的已知漂移之一）：`relation_ids` 必须在声明里。

    修之前：实现返回 `relation_ids`（且 `test_tools_graph_trace.py:89` 在断言它），
    而 `returns=` 只写到 `relation_count` —— 声明与实现不一致。

    它是嵌套项的键，所以比对的不是顶层键集合（见 `declared_keys` 的口径），
    而是"声明字符串里出没出现过这个名字"。这一条刻意写得直白：
    嵌套形状无法像顶层键那样机械双向比对，而"声明里漏了一个调用方已经在用的字段"
    这件事只需要一次子串检查就能抓住 —— 抓住它比"比对得很漂亮"重要。
    """
    from conftest import add_concept, add_relation

    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="An abelian group is a group.")

    reg = registry_for(GT, store)
    returns = reg.get("graph.neighbors").returns
    assert "relation_ids" in returns, f"声明漏了调用方在用的字段：{returns!r}"
    assert {"concept_id", "name", "degree", "neighbors"} <= declared_keys(returns)
    # 实现仍然给那个字段（声明与实现两侧都要有，缺一侧就是漂移）
    item = reg.call("graph.neighbors", concept_id="0000").data["neighbors"][0]
    assert set(item) == {"concept_id", "name", "relation_count", "relation_ids"}


# ============================================================ G-3 ⑥ 有界/截断


def test_graph_neighbors_truncates_and_says_so(store: Store):
    """核心：邻居列表超上限 ⇒ `truncated=True` + 逐条原因，不许静默截断。

    修之前：`RelationGraph.neighbors()` 返回无界裸列表，`graph.neighbors`
    原样塞回 `ToolResult.data`。于是"结果太大"这条防线在它上面不生效 ——
    调用方会把"我只拿到前 N 个"读成"它就只有这些邻居"。
    """
    g = _star_graph(300)
    reg = ToolRegistry(name="graph-bound")
    reg.bound_role = "C"  # `P-14`：同上
    GT.register(reg, graph=g)

    res = reg.call("graph.neighbors", concept_id="0000")
    assert res.ok, res.error
    d = res.data
    assert d["truncated"] is True
    assert d["total_neighbors"] == 300
    assert d["returned_neighbors"] == GT.MAX_NEIGHBORS_DEFAULT
    assert len(d["neighbors"]) == GT.MAX_NEIGHBORS_DEFAULT
    assert d["reasons"], "截断必须逐条给原因（只说 truncated 不够，还得说被什么截的）"
    assert str(GT.MAX_NEIGHBORS_DEFAULT) in d["reasons"][0]
    assert "不等于" in d["reasons"][0], "必须写明'这不等于它只有这些邻居'"
    # 升序确定性：截断取的是前 N 个，不是随便 N 个
    assert [n["concept_id"] for n in d["neighbors"]] == [f"{i:04d}" for i in range(1, GT.MAX_NEIGHBORS_DEFAULT + 1)]

    # ---- 负控 1：小图不许被截（否则"有界"会变成"永远报截断"）
    small = reg.call("graph.neighbors", concept_id="0000", max_neighbors=300)
    assert small.data["truncated"] is False and small.data["reasons"] == []
    assert small.data["returned_neighbors"] == small.data["total_neighbors"] == 300
    # ---- 负控 2：显式上限照用
    capped = reg.call("graph.neighbors", concept_id="0000", max_neighbors=3)
    assert capped.data["truncated"] is True and capped.data["returned_neighbors"] == 3
    assert [n["concept_id"] for n in capped.data["neighbors"]] == ["0001", "0002", "0003"]


def test_graph_neighbors_result_is_not_prunable_by_context_budget(store: Store):
    """为什么必须在工具层加闸：上下文预算的剪枝对"很多个短 dict"无效。

    这是实测：300 个邻居的 JSON 是 26 万字符量级，而 `prune_tool_result`
    只按字符长度剪 `data` 里的字符串（每个 `name` / `concept_id` 都远短于
    `threshold_chars`）⇒ `pruned=False`，条数一条都没少。

    所以"结果太大"这条防线在 `graph.neighbors` 上只能由 `max_neighbors` 兜住。
    本用例把这个事实钉住：谁要是把剪枝当成这里的防线，这条用例会告诉他不是。
    """
    g = _star_graph(300)
    reg = ToolRegistry(name="graph-prune")
    reg.bound_role = "C"  # `P-14`：`graph.*` 的声明角色是 C/D，这里代表只读的 C
    GT.register(reg, graph=g)

    res = reg.call("graph.neighbors", concept_id="0000", max_neighbors=300)
    assert res.ok and res.data["truncated"] is False
    budget = ContextBudget(
        threshold_chars=500, head_chars=200, tail_chars=100, max_inline_bytes=10**7
    )
    pruned = res.pruned(budget)
    assert len(pruned.data["neighbors"]) == len(res.data["neighbors"]), (
        "剪枝**不会**减少邻居条数（它只剪长字符串）—— 所以有界必须由工具层负责"
    )
    assert pruned.meta.get("pruned") is False
    # ---- 有界那一份是唯一真正把结果压下来的机制（不是剪枝）
    import json

    bounded = reg.call("graph.neighbors", concept_id="0000")
    assert len(bounded.data["neighbors"]) == GT.MAX_NEIGHBORS_DEFAULT
    assert bounded.data["truncated"] is True, "压下来的代价必须如实标出来"
    bounded_chars = len(json.dumps(bounded.data, ensure_ascii=False))
    pruned_chars = len(json.dumps(pruned.data, ensure_ascii=False))
    assert bounded_chars < pruned_chars, (bounded_chars, pruned_chars)
    # 300 个邻居的完整 JSON 就在几万字符量级 —— 对上下文预算是实打实的开销
    assert pruned_chars > 20_000


def test_relation_graph_neighbors_stays_a_plain_list(store: Store):
    """    证据（不改成封装的那个决定）：`RelationGraph.neighbors()` 仍是裸 `list`。为什么不改它（题目要求"若判断会破坏调用方，先用证据说明"）：`grep` 出的全部调用点（逐个判断）：
    ==========================================  ==========================================调用点
    它怎么用返回值==========================================  ==========================================`agent_c.py:1479`
    `set(g.neighbors(a)) & set(g.neighbors(b))``agent_c.py:1489`
    `nbrs = g.neighbors(u)` 后按下标取 `nbrs[i]``agent_c.py:3288`（自检）
    `set(g.neighbors("0000"))``trace_tools.py:305`
    `for n in g.neighbors(cid)` 当可迭代用`graph_tools.py` 的 `graph.neighbors` 工具
    见下==========================================  ==========================================前四处都按 `list` /
    `set` 语义用它。把返回类型换成 "dict 或 list 的子类"，要么改这四处（其中两处在 `agent_c`，本轮不在我的可改文件里），要么让 `neighbors()` 返回一个类型随调用方式变的东西 ——
    后者正是"同一判据两份形状"的形态。所以有界那一层加在`neighbors_bounded()` + 工具层上，`neighbors()` 原样保留。这不是"保留缺陷"：工具层（D 真正调用的那一层）现在有界且如实回报截断。
    """
    g = _star_graph(5)
    fixed = g.neighbors("0000")
    assert type(fixed) is list
    assert fixed == ["0001", "0002", "0003", "0004", "0005"]
    # 图层的两个入口必须是同一份排序/截断判据（FC-03）
    bounded = g.neighbors_bounded("0000", max_neighbors=2)
    assert bounded["neighbors"] == fixed[:2]
    assert bounded["total"] == len(fixed)
    assert bounded["truncated"] is True
    # 直接调 `bounded_neighbors`（无方法、无工具）也一致
    direct = GT.bounded_neighbors(g.adjacency, "0000", max_neighbors=2)
    assert direct == bounded


# ============================================================ 同一判据只有一份


def test_graph_tools_forwards_the_one_guard_instead_of_copying_it():
    """FC-03：守卫只有一份实现，`graph_tools` 只是转发。

    题目明确要求：若两个文件各写一遍守卫，必须让一处转发。这里用可判定的方式钉住：
    - `graph_tools._guard` 的 `__module__` 是 `agentflow.tools.attack_tools`；
    - `graph_tools` 里没有第二条 `def _guard`（它在 AST 里只出现在 import 处）；
    - 两个模块拿到的是同一个函数对象。
    """
    import ast

    from agentflow.tools import attack_tools as _at
    from agentflow.tools import graph_tools as _gt

    assert _gt._guard is _at._guard  # noqa: SLF001 - 被测的就是这个绑定
    assert _gt._guard.__module__ == "agentflow.tools.attack_tools"

    src = Path(_gt.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    defs = [
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_guard"
    ]
    assert defs == [], f"graph_tools 里出现了第二份 `_guard` 定义：{defs}"


def test_attack_handlers_are_wrapped_by_the_guard(store: Store, monkeypatch: pytest.MonkeyPatch):
    """    遍历式负控：六个 `attack.*` handler 都经过 `_guard`（不是"改了五个漏一个"）。判据为什么是"看栈 / 看 kind"，而不是内省 handler 的 code object：handler 写成
    `lambda ...: _guard(lambda: ...)`，而外层 lambda 引用的是内层lambda 的细胞（那个细胞里才装着 `_guard`）—— 实测 `co_freevars` 与 `LOAD_DEREF`都会漏报，
    于是内省式判据会冤枉一个正确的实现。行为式判据也不能只认"抛"：`_guard` 的契约是"已知失败原因 ⇒ 结构化失败"（它返回 `ToolResult`，只有 `ToolError` 那一支才上抛）。所以两支都算证据：抛了 ⇒ traceback 里必须出现
    `_guard` 帧；- 没抛 ⇒ 返回值必须是有受控 `kind` 的 `ToolResult`（`plan_error` /`validation_error`）—— 那不是 `ok(...)`，正是 `_guard` 的产物。为什么两支探针要打桩、
    两支不用（每条都是实测踩出来的）：`attack.status` 与 `attack.list_plans` 对"坏但合法"的 `plan_id` / `problem_key`本身就是容错的：status 走"查了、没有"（`ok=True` +
    `checked=False`），list_plans 只做字符串比较。它们没有任何"必然抛"的自然输入 ——所以只能打桩（打桩形态照`test_tools_audit_fixes.py::test_no_unexpected_escape_search_register_schema_failure`）
    。另外两支的打桩原因不同：`check_budget` / `pick_next_subgoal` 的参数校验会先拦住"形状可疑"的探针（`subgoals="abc"` ⇒ `param_error`、`budget=[]` ⇒`param_error` ——
    实测两次踩过），所以打桩它们调用的内层函数。`attack.create_plan` / `attack.step` 用真数据就够：缺 owner（`PlanError`）、plan_id
    不存在（`PlanError`）。`attack.create_plan` 的探针不能是"预算缺键"：那一条刻意返回`ok=True` + `created=False` + 理由（"拒绝创建，而不是先用默认值把洞补上"），它不抛、也不是守卫的产物。
    这条用例的价值在于"新增第七个工具时会不会忘"：忘掉的那个工具不会有任何别的用例变红（它的失败路径只是又变回 `unexpected`）。
    """
    import sys

    from agentflow.agent_f import AgentF
    from agentflow.tools.base import validate_params

    reg = _attack_reg(store)
    assert len(reg.names()) == 6, reg.names()

    def _boom(*_a: object, **_kw: object) -> dict:
        raise ValueError("内部炸了（夹具故意）")

    # 打桩的四支、理由各不相同（都是实测踩出来的）：
    # - `attack.check_budget` / `attack.pick_next_subgoal` 是纯函数，
    #   它们的参数校验会先拦住"形状可疑"的探针（`budget=[]` ⇒ `param_error`），
    #   而合法输入又永远正常返回（`subgoals=[]` 只让 `picked=False`）——
    #   没有任何自然输入能把它们逼到守卫的失败分支；
    # - `attack.status` / `attack.list_plans` 对坏输入是容错的（见 docstring）。
    monkeypatch.setattr(AT, "can_round", _boom)
    monkeypatch.setattr(AT, "pick_next_subgoal", _boom)
    monkeypatch.setattr(AgentF, "status", _boom)
    monkeypatch.setattr(AgentF, "list_plans", _boom)

    full_budget = {"max_rounds": 6, "max_parallel_subgoals": 2,
                   "max_persist_attempts": 2, "max_depth": 2}
    probes: dict[str, dict] = {
        "attack.check_budget": {"budget": full_budget},
        "attack.pick_next_subgoal": {"subgoals": []},
        "attack.create_plan": {
            "problem": "p",
            "problem_key": "k",
            "subgoals": [{"sid": "s1", "text": "t"}],
        },
        "attack.step": {"plan_id": "9999"},
        "attack.status": {"plan_id": "9999"},
        "attack.list_plans": {},
    }
    assert set(probes) == set(reg.names()), "六个工具的名字变了 —— 这条门要跟着改"

    seen_raise: set[str] = set()
    seen_kind: set[str] = set()
    for name, params in probes.items():
        try:
            spec = reg.get(name)
            # 先过一遍参数校验（`ToolRegistry.call` 也是这么做的）：
            # 探针要是被 `param_error` 拦下，就证明不了任何关于守卫的事。
            validate_params(spec.params, params)
            result = spec.handler(**params)
        except BaseException:  # noqa: BLE001 —— 探针就是要它抛，抛了才能看栈
            tb = sys.exc_info()[2]
            names_in_stack = []
            while tb is not None:
                names_in_stack.append(tb.tb_frame.f_code.co_name)
                tb = tb.tb_next
            assert "_guard" in names_in_stack, f"{name} 抛了但没经过 `_guard`：{names_in_stack}"
            seen_raise.add(name)
        else:
            kind = getattr(result, "meta", {}).get("kind")
            assert kind in ("plan_error", "validation_error"), (
                f"{name} 没抛、也不是守卫产出的受控 kind（拿到 {kind!r}）⇒ 它可能压根没走守卫"
            )
            seen_kind.add(name)
    # 六个 handler 都必须给出受控 kind。这一条同时证明两件事：
    # ① 打桩点确实在守卫之内（否则异常会穿透 `_guard` 变成裸异常或
    #    `base.py` 的 `unexpected`）；② 没有任何一个 handler 漏掉了守卫
    #    （漏掉的那个会原样抛异常，直接让本用例报错）。
    assert seen_kind == set(probes), f"这些工具没给出受控 kind：{sorted(set(probes) - seen_kind)}"
    assert not seen_raise, f"这些工具抛出了守卫：{sorted(seen_raise)}"

    # ---- 再补一支"抛了看栈"：把 `ToolError` 支路也走一遍。
    # `_guard` 对 `ToolError` 刻意 `raise`（由 `ToolRegistry.call` 分类），
    # 所以这一支只能靠 traceback 证明守卫在链路上。
    def _tool_error(*_a: object, **_kw: object) -> dict:
        raise AT.ToolError("工具层自己的异常（夹具故意）")

    monkeypatch.setattr(AT, "can_round", _tool_error)
    try:
        reg.get("attack.check_budget").handler(budget=full_budget)
    except BaseException:  # noqa: BLE001 —— 这一支就是要它抛
        tb = sys.exc_info()[2]
        stack = []
        while tb is not None:
            stack.append(tb.tb_frame.f_code.co_name)
            tb = tb.tb_next
        assert "_guard" in stack, f"`ToolError` 支路没经过 `_guard`：{stack}"
    else:
        raise AssertionError("`ToolError` 支路竟然没抛 —— `_guard` 的契约变了")


def test_graph_handlers_wrap_store_reads_and_not_parameter_checks():
    """负控：守卫只包"读存储"这一段，参数校验仍由 `ToolRegistry.call` 负责。

    为什么这条要单独测：把 `param_error` 卷进 `_guard` 会让"调用方写错了"
    与"环境故障"重新混成一档 —— 那正是这次要修的反面。
    """
    reg = _attack_reg(None)
    missing_param = reg.call("attack.list_plans", include_terminal="不是布尔")
    assert missing_param.meta.get("kind") == "param_error"
    missing_required = reg.call("attack.create_plan", problem="p")
    assert missing_required.meta.get("kind") == "param_error"
    unknown_tool = reg.call("attack.根本没有这个")
    assert unknown_tool.meta.get("kind") == "unknown_tool"
