"""逐个工具的参数校验门（objective 第 (3) 条："参数校验"那一项的机械化判据）。

## 为什么需要它

`DEVELOPMENT.md` §4.3 的"工具 DoD"要求每个工具声明 `params`（JSON Schema 子集），
而 `ToolRegistry.call` 在调 handler 之前调 `validate_params`（`tools/base.py`）。
于是"参数校验"这件事有两半，而两半都可能坏：

1. 声明存在但没生效：schema 写错（例如 `additionalProperties` 没设成 `False`），
   于是垃圾参数静默通过，一路走到 handler 里 —— 而 handler 往往对多出来的键
   要么忽略（静默）要么在深处炸（`unexpected`）。两种都不是"参数错误"。
2. 校验发生了但 handler 还是被调了：那意味着"校验"只是个装饰。
   判据必须打在副作用是否发生上，不是打在返回值上 ——
   一个"先干活再报参数错"的实现，返回值看起来完全一样。

## 本文件怎么判（55 个工具，逐个）

对注册表里的每一个工具：
- (A) schema 形状：`type == "object"`、`properties` 是 dict、`additionalProperties is False`；
- (B) 额外参数必须被拒：`kind == "param_error"`，且 handler 未被调用；
- (C) 缺必填参数必须被拒：同上；
- (D) 通过校验的调用必须真的调到 handler（否则 (B)(C) 可能只是"永远不调用"的假门）。

## 三态

`param_error` 是受控的拒绝（`schema.REFUSAL_REASONS` 的同族口径），
不是"失败"。所以 (B)(C) 断言的是"恰好是 `param_error`"，
而不是"`ok is False`" —— 后者对 `unexpected`/`tool_error` 也成立，
于是一个把参数错误报成"未知异常"的实现照样能通过。那正是三态纪律要挡的形态。
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agentflow import store as _store  # noqa: E402
from agentflow.tools import ROLES, build_registry  # noqa: E402
from agentflow.tools.base import ToolRegistry  # noqa: E402


@pytest.fixture(scope="module")
def registry():
    """真的装配一次注册表（与 `cli tools` / `release_check` 同一条路径）。"""
    with tempfile.TemporaryDirectory(prefix="params_gate_") as td:
        st = _store.Store(Path(td))
        st.init()
        build = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES))
        yield build.registry


def _kind(res) -> str:
    """取受控的失败种类。`fail(kind=...)` 把它放在 `meta` 里。"""
    return str((res.meta or {}).get("kind") or "")


def _names(registry) -> list[str]:
    return sorted(registry.names())


def _spy_registry(registry, hits: list[str]) -> ToolRegistry:
    """把每个 handler 换成"一被调用就往 `hits` 里记一笔"的探针，装进一个新注册表。

    为什么不能直接 `monkeypatch.setattr(spec, "handler", spy)`：
    `ToolSpec` 是 `frozen=True` 的 dataclass（`dataclasses.FrozenInstanceError`）。
    那本身是一道很好的防线（规格不可被就地篡改），所以这里不绕它，
    而是用 `dataclasses.replace` 造一份改了 handler 的新规格装进新注册表 ——
    被测的 `ToolRegistry.call` 与 `validate_params` 仍是同一个实现。

    为什么要 spy 而不是只看返回值：判据必须打在"副作用是否发生"上。
    一个"先干活再报参数错"的实现，返回值看起来与正确实现完全一样。
    `FrozenInstanceError` 挡住的是"测试篡改规格"，挡不住"`call` 里的顺序写反了"。
    """
    spy_reg = ToolRegistry(name="param-gate-spy")

    def make(_original, _name: str):
        def spy(*args, **kwargs):
            hits.append(_name)
            return _original(*args, **kwargs)

        return spy

    for name in _names(registry):
        spec = registry.get(name)
        spy_reg.register(replace(spec, handler=make(spec.handler, name)))
    # 装配期自检：探针注册表必须与真注册表工具面完全一致，
    # 否则下面的断言测的是另一个工具集（那是"换了个对象测"，不是"测了它"）。
    assert sorted(spy_reg.names()) == _names(registry), "探针注册表与真注册表的工具面不一致"
    return spy_reg


def test_registry_is_not_empty(registry):
    """三态的前置：装配出 0 个工具 ⇒ 后面所有断言都会"真空通过"。

    所以这一步单独断言："没装配出工具"与"所有工具都合规"必须分得开。
    """
    names = _names(registry)
    assert len(names) >= 50, f"只装配出 {len(names)} 个工具 —— 这不是'都合规'，是**没查成**"


def test_every_tool_declares_a_strict_object_schema(registry):
    """(A) 逐个工具：schema 形状必须是"严格的 object"。

    `additionalProperties is False` 是必需的：没有它，垃圾参数会静默通过校验，
    一路走到 handler —— 而那时"参数错误"与"工具内部出错"就分不开了。
    """
    bad: dict[str, str] = {}
    for name in _names(registry):
        p = registry.get(name).params or {}
        why = []
        if p.get("type") != "object":
            why.append(f"type={p.get('type')!r}")
        if not isinstance(p.get("properties"), dict):
            why.append("properties 不是 dict")
        if p.get("additionalProperties") is not False:
            why.append(f"additionalProperties={p.get('additionalProperties')!r}（必须是 False）")
        if why:
            bad[name] = "；".join(why)
    assert not bad, f"这些工具的 params schema 不合规：{bad}"


def test_every_tool_rejects_an_extra_parameter_without_calling_the_handler(registry):
    """(B) 逐个工具（核心）：额外参数 ⇒ `param_error`，且 handler 没被调用。

    判据打在"副作用是否发生"上，不打在返回值上：
    一个"先干活再报参数错"的实现，返回值看起来完全一样。
    """
    hits: list[str] = []
    spy = _spy_registry(registry, hits)
    leaked: list[tuple[str, str]] = []
    called: list[str] = []
    covered = 0

    for name in _names(registry):
        before = len(hits)
        res = spy.call(name, __bogus_extra_param__="x")
        covered += 1
        got = _kind(res)
        if got != "param_error":
            leaked.append((name, got or f"ok={res.ok} kind=(空)"))
        if len(hits) > before:
            called.append(name)

    # 零发现必须自证（参考体例 G13 的同一条制度）：一个"因为一个工具都没测到
    # 所以全过"的门是橡皮图章。这里把覆盖面钉成数字 —— 实测 55 个工具全覆盖。
    assert covered >= 50, f"只覆盖了 {covered} 个工具 —— 这不是'都合规'，是**没查全**"
    assert not leaked, (
        f"这些工具**没有**把额外参数拒成 `param_error`（{covered} 个里）：{leaked}"
    )
    assert not called, f"这些工具在**参数非法**的情况下仍然被调用了（校验只是装饰）：{called}"


def test_every_required_parameter_is_actually_enforced(registry):
    """(C) 逐个工具：缺一个必填参数 ⇒ `param_error`，且 handler 没被调用。

    逐个把每一个 required 键各去掉一次（不是只去掉第一个）——
    "只测第一个必填项"会让后面几个必填项的声明从未被执行过。
    """
    hits: list[str] = []
    spy = _spy_registry(registry, hits)
    leaked: list[tuple[str, str, str]] = []   # (工具, 缺的键, 实际 kind)
    checked = 0
    for name in _names(registry):
        spec = registry.get(name)
        required = list((spec.params or {}).get("required") or [])
        if not required:
            continue
        # 给所有必填项一个类型正确的占位值，然后逐个抽掉一个 ——
        # 这样"被拒"就只可能是因为缺了那一个，而不是因为别的参数类型不对。
        base = {k: _placeholder(spec.params["properties"].get(k) or {}) for k in required}
        for key in required:
            params = {k: v for k, v in base.items() if k != key}
            before = len(hits)
            res = spy.call(name, **params)
            checked += 1
            got = _kind(res)
            if got != "param_error":
                leaked.append((name, key, got or f"ok={res.ok} kind=(空)"))
            if len(hits) > before:
                leaked.append((name, key, "handler 被调用了！"))
            hits.clear()

    assert checked > 0, "一个带 required 的工具都没有 —— 判据没生效（**没查成**）"
    # 自证数字：实测 41 个工具 / 66 个 (工具, 必填键) 组合。门槛设在 50，
    # 于是"有人删掉一批 required 声明"会让这条断言红，而不是让门悄悄变松。
    assert checked >= 50, f"只检查了 {checked} 个 (工具, 必填键) 组合 —— **没查全**"
    assert not leaked, f"这些必填参数**没有被强制**（{checked} 个组合里）：{leaked}"


def _placeholder(schema: dict):
    """按声明的类型造一个占位值（只为"补全其它必填项"，不追求语义合法）。"""
    t = schema.get("type")
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "object":
        return {}
    return "x"


def test_a_legal_call_really_reaches_the_handler(registry):
    """(D) 负控的反面：参数合法时 handler 必须真的被调用。

    没有这一条，(B)(C) 就可能被一个"永远不调用 handler"的实现骗过 ——
    那种实现会把所有参数校验测试都变成绿灯，而工具一个也不能用。
    这里挑一个参数最简单、且不需要外部后端的工具（`table.count`）来证。
    """
    hits: list[str] = []
    spy = _spy_registry(registry, hits)
    res = spy.call("table.count", table="literature")
    assert hits == ["table.count"], (
        f"合法参数没能到达 handler（工具层是死的）：ok={res.ok} err={res.error} meta={res.meta}"
    )


def test_param_error_is_a_controlled_refusal_not_a_crash(registry):
    """三态：参数错误必须是受控拒绝（`param_error`），不是 `unexpected`。

    把参数错误报成"未知异常"会让调用方以为框架坏了（于是去查框架），
    而真相是"你自己传错了"。两者必须能分开 —— 这是本项目三态纪律在工具层的落点。
    """
    res = registry.call("table.count", __bogus_extra_param__="x")
    assert res.ok is False
    assert _kind(res) == "param_error", res.meta
    assert "参数错误" in (res.error or ""), res.error
