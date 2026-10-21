"""FC-17 的接线：从"有骨架"到"真的会有预算"。

## 背景（这是一次如实报告的后果）

FC-17 的实现方交付后主动报了一件不利的事：

> `grep 'call\\([^)]*budget\\s*='` 在 `src\\` 0 命中；所有调用点都是裸的
> `self.tools.call(name, **params)`。也就是说：这条约束现在有了骨架
> （可实例化的预算对象、可验证的剪枝/落盘/压缩函数、有配置块、有 37 条测试），
> 但没有任何主流程接线。

"有测试、有实现、有配置"与"真的会生效"是两件事。把预算做成
装配期属性（`ToolRegistry.default_budget`）之后，"开启剪枝"只需要在装配处
做一次决定，而不是指望每个 `_call` 都记得传参数 —— 那种"靠人记得"的设计
在本项目里已经失败过多次（`roles` 拼错、`mark_dirty` 忘了调、`concept_pair_key`
忘了算）。

## 本文件守什么

- `default_budget=None`（默认）⇒ 行为与加 FC-17 之前逐字节一致（既有测试零影响）
- 装了预算 ⇒ 大结果被剪枝，且原文仍可取回（内联片段 或 spill 文件）
- spill 真的会发生（需要 `head+tail > max_inline_bytes` 这个几何条件 —— 见下）
- 工具自己声明了 `budget` 参数时，默认预算不适用（名字消歧的另一半）
- "开没开"是可打印的事实（`RegistryBuild.summary()`），不是靠 grep 源码去猜
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from agentflow.contextbudget import ContextBudget, load_budget
from agentflow.tools import ToolError, build_registry
from agentflow.tools.base import ToolSpec, ok

BIG = "X" * 5000


def _big_tool(reg, *, declares_budget: bool = False) -> None:
    """装一个"返回大字符串"的工具，并把注册表绑定到 `A`（`P-14`）。

    为什么在这里绑角色：本模块的用例全部走 `build_registry(...).registry`，而那张
    完整注册表默认不绑定任何角色（`bound_role=None`）⇒ 每次 `call` 都会被
    "调用方没有声明角色"拒掉。`zz.big` 声明的角色是 `A`，所以这张表代表 `A`。
    """
    if reg.bound_role is None:
        reg.bound_role = "A"
    props = {"type": "object", "properties": {}, "additionalProperties": False}
    if declares_budget:
        props["properties"] = {"budget": {"type": "object"}}
    reg.register(ToolSpec(
        name="zz.big",
        summary="返回一个大字符串（测试用）",
        params=props,
        handler=lambda **kw: ok({"blob": BIG, "seen_budget": kw.get("budget")}),
        side_effect="none",
        roles=("A",),
        returns="{'blob','seen_budget'}（测试用的大字符串）",
    ))


def _cfg(**over) -> dict:
    block = {"threshold_chars": 200, "head_chars": 50, "tail_chars": 50, "max_inline_bytes": 300}
    block.update(over)
    return {"context_budget": block}


# ============================================================ load_budget 三态


def test_load_budget_three_states():
    """三态：没给配置 / 没配预算 / 配了预算，是三件不同的事。

    `ContextBudget.from_mapping({})` 会填出一整套默认值（"配了但用默认"）；
    而配置里压根没有 `context_budget` 块时，正确语义是"这台部署没启用"。
    折叠成同一个对象之后，"剪枝到底开没开"就答不上来了。
    """
    assert load_budget(None) is None, "没给配置 ⇒ None（不是'没配预算'）"
    assert load_budget({}) is None, "没有 context_budget 块 ⇒ 没启用"
    got = load_budget(_cfg())
    assert isinstance(got, ContextBudget) and got.threshold_chars == 200


def test_load_budget_rejects_bad_values():
    """负控：块里的值非法要抛，不许静默兜底（`threshold_char` 少个 s 会被吞）。"""
    with pytest.raises(Exception):
        load_budget({"context_budget": {"threshold_chars": 0}})
    with pytest.raises(Exception):
        load_budget({"context_budget": {"not_a_key": 1}})


# ============================================================ 装配期装上预算


def test_registry_without_budget_keeps_old_behaviour(store):
    """负控（兼容性）：没装预算时，大结果原样返回。

    这一条是"接线不能改变既有行为"的判据。没有它，`default_budget` 一旦被
    默认打开，所有既有调用方的返回值都会悄悄变短 —— 而"没开剪枝"与"开了没超阈值"
    就再也分不开了。
    """
    store.init()
    reg = build_registry(store=store, workspace_root=store.root, strict=True).registry
    _big_tool(reg)
    r = reg.call("zz.big")
    assert r.ok and r.data["blob"] == BIG, "没装预算时不该剪"
    assert r.meta.get("pruned") in (None, False)


def test_registry_with_budget_prunes_by_default(store):
    """核心：装了预算 ⇒ 不传 `budget=` 也会剪（这才是"接线"）。"""
    store.init()
    reg = build_registry(store=store, workspace_root=store.root, strict=True, config=_cfg()).registry
    _big_tool(reg)
    r = reg.call("zz.big")
    assert r.ok, "剪枝不改结论（ok 必须保持 True）"
    assert r.meta.get("pruned") is True
    assert len(r.data["blob"]) < len(BIG)
    # 原文仍可取回：内联的是 head + tail（都是原文的子串）
    head, tail = r.data["blob"][:20], r.data["blob"][-20:]
    assert head in BIG and tail in BIG, "剪枝后的内联片段必须是原文的子串"


def test_summary_reports_whether_pruning_is_on(store):
    """"开没开"必须是可打印的事实，而不是靠 grep 源码去猜。

    这正是 FC-17 当时的困境：实现齐备、测试齐备，但没有任何调用方会传 budget ——
    而外部只看 `summary()` 是看不出来的。
    """
    store.init()
    off = build_registry(store=store, workspace_root=store.root, strict=True)
    assert off.summary()["context_budget"] is None
    on = build_registry(store=store, workspace_root=store.root, strict=True, config=_cfg())
    cb = on.summary()["context_budget"]
    assert cb["enabled"] is True and cb["threshold_chars"] == 200


def test_bad_context_budget_fails_at_assembly_not_at_first_call(store):
    """负控：类型不对的预算必须在装配期炸。

    否则它会一路活到第一次 `call()` 才炸，而那时错误信息里已经没有
    "是装配时配错的"这个线索了。
    """
    store.init()
    with pytest.raises(ToolError):
        build_registry(store=store, workspace_root=store.root, strict=True, context_budget={"threshold_chars": 1})


def test_explicit_budget_still_wins_over_the_default(store):
    """显式传入的 `budget` 优先于注册表默认值（否则调用方就失去控制了）。"""
    store.init()
    reg = build_registry(store=store, workspace_root=store.root, strict=True, config=_cfg()).registry
    _big_tool(reg)
    looser = ContextBudget(threshold_chars=10_000, head_chars=100, tail_chars=100, max_inline_bytes=10_000_000)
    r = reg.call("zz.big", budget=looser)
    assert r.meta.get("pruned") in (None, False) or len(r.data["blob"]) == len(BIG), (
        "显式给了更宽的预算 ⇒ 不该按注册表那个更窄的剪"
    )


# ============================================================ 名字消歧的另一半


def test_tool_declaring_its_own_budget_is_not_given_the_context_budget(store):
    """负控（真实的名字冲突）：`attack.check_budget` / `attack.create_plan`
    自己就有 `budget` 参数（FC-18 的四维预算）。

    所以"默认预算"不能在没有调用方传参的情况下被塞给它们 ——
    那会让工具收到一个它根本不认识的 `ContextBudget` 对象。
    """
    store.init()
    reg = build_registry(store=store, workspace_root=store.root, strict=True, config=_cfg()).registry
    _big_tool(reg, declares_budget=True)
    r = reg.call("zz.big")
    assert r.ok
    assert r.data["seen_budget"] is None, "工具自己声明了 budget ⇒ 默认预算不该被当成它的参数"
    # 而且它自己的 budget 参数仍然照常可用
    r2 = reg.call("zz.big", budget={"max_rounds": 3})
    assert r2.data["seen_budget"] == {"max_rounds": 3}


# ============================================================ spill 真的会发生


def test_spill_actually_happens_when_geometry_allows(store):
    """FC-17 的实现方报告过一条几何事实：`head+tail < max_inline_bytes` 时，
    "落盘"分支不可达（剪枝后内联最多 head+tail 个字符，永远进不了 spill）。

    所以要验证 spill 真的能发生，必须把 `max_inline_bytes` 配得小于 `head+tail`。
    这条测试同时把那段算术钉死：`config.yaml` 的默认数值一变，这里就会红。
    """
    store.init()
    # 几何必须同时满足两个条件：
    #   head + tail < threshold（ContextBudget.validate 的硬约束：
    #     否则"剪枝"会把内容变长）
    #   max_inline_bytes < head + tail（否则落盘分支不可达）
    # 两者合起来就是： max_inline_bytes < head+tail < threshold_chars。
    # 三个条件必须同时满足：
    #   len(BIG)=5000 > threshold_chars=3000   （否则根本不剪）
    #   head + tail = 2000 < threshold_chars   （validate 的硬约束：否则越剪越长）
    #   max_inline_bytes = 100 < head + tail   （否则落盘分支不可达）
    cfg = {"context_budget": {"threshold_chars": 3000, "head_chars": 1000, "tail_chars": 1000,
                              "max_inline_bytes": 100}}
    reg = build_registry(store=store, workspace_root=store.root, strict=True, config=cfg).registry
    _big_tool(reg)
    r = reg.call("zz.big")
    assert r.ok
    assert r.meta.get("spilled") is True, (
        "head+tail=700 > max_inline_bytes=100 ⇒ 必须落盘（否则 spill 这一件套永远走不到）"
    )
    sp = r.meta.get("spill_path")
    assert sp, r.meta
    p = Path(sp)
    assert p.exists(), f"落盘路径不存在：{sp}"
    assert p.read_text(encoding="utf-8") == BIG, "落盘的必须与原文逐字节相同"
    # 内联里必须带路径与 sha256 —— 否则读者无法判断落盘的是不是他以为的那份
    inline = json.dumps(r.data, ensure_ascii=False)
    assert "sha256" in inline and "已落盘" in inline


def test_default_spill_root_is_the_workspace(store):
    """spill 的默认落点必须是工作区内的 `spill/`。

    若 `default_spill_root` 不设，`default_budget` 生效时剪枝的内容想落盘却没地方落
    （`prune` 的语义是"没给 root ⇒ 不落盘但如实报告"），于是 spill 那一件套在
    生产路径上永远走不到 —— 而它恰恰是唯一能保证"原文没丢"的机制。
    """
    store.init()
    # 几何必须同时满足两个条件：
    #   head + tail < threshold（ContextBudget.validate 的硬约束：
    #     否则"剪枝"会把内容变长）
    #   max_inline_bytes < head + tail（否则落盘分支不可达）
    # 两者合起来就是： max_inline_bytes < head+tail < threshold_chars。
    # 三个条件必须同时满足：
    #   len(BIG)=5000 > threshold_chars=3000   （否则根本不剪）
    #   head + tail = 2000 < threshold_chars   （validate 的硬约束：否则越剪越长）
    #   max_inline_bytes = 100 < head + tail   （否则落盘分支不可达）
    cfg = {"context_budget": {"threshold_chars": 3000, "head_chars": 1000, "tail_chars": 1000,
                              "max_inline_bytes": 100}}
    reg = build_registry(store=store, workspace_root=store.root, strict=True, config=cfg).registry
    _big_tool(reg)
    r = reg.call("zz.big")
    sp = Path(r.meta["spill_path"])
    assert store.root.resolve() in sp.resolve().parents, (
        f"spill 落到了工作区外：{sp}（工作区 {store.root}）"
    )
