# -*- coding: utf-8 -*-
"""把调用信封多包一层时，工具分发要受控拒（带 `kind` 与 `how_to_fix`），不许裸异常。

## 现场（R10 真机 lp-ball-10，2026-11-19 14:18:09，会话行 3419）

M 那一拍给 `conductor.closing` 的 `args` 是：

```json
{"name": "conductor.closing", "args": {…全量实参…}}
```

即整个「调用信封」被又包进了 `args` 一层。分发点是
`self.registry.call(name, role=..., args)` ⇒ 序列化之后是这样：

```text
TypeError: ToolRegistry.call() got multiple values for argument 'name'
```

结果里没有 `data` / `meta` / `kind`，也没有"怎么改"；11 秒后 M 按正确形状重发才
拿到八格读数。一次真调用白花，读数里只有一行 Python 异常。

## 判据

| # | 判据 | 造的是什么现场 |
|---|---|---|
| a | 信封被多包一层 ⇒ `ok=False` + `kind=param_error` + `meta.how_to_fix`，工具没被执行 | 真机那一份 `args` |
| a-负控 | 同一份 `args` 直接喂给 `registry.call`（改前的分发）必须抛 `TypeError` | 证明 a 的绿灯压在这一格上 |
| b | 正确形状照旧执行（拒的判据只认会崩的那一个键） | `{"name": …, "args": {…}}` 在外层 |
| c | 别的工具（不是只对 `conductor.closing`）同样受控拒 | `fs.list` |

"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import agent_loop as AL
from agentflow.agent_loop import AgentLoop
from agentflow.store import Store
from agentflow.tools import build_registry


# ---------------------------------------------------------------- 夹具


def _registry(tmp_path: pathlib.Path):
    (tmp_path / "data").mkdir(exist_ok=True)
    st = Store(tmp_path)
    st.init()
    return build_registry(store=st, workspace_root=tmp_path).registry


def _loop(tmp_path: pathlib.Path) -> AgentLoop:
    return AgentLoop(role="M", session_root=tmp_path, registry=_registry(tmp_path),
                     seam=None)


#: 真机那一份形状（内层是这件工具真正的实参）
WRAPPED = {"name": "fs.list", "args": {"path": "."}}


# ============================================================ a 受控拒


def test_a_a_double_wrapped_envelope_is_refused_with_kind_and_how_to_fix(
        tmp_path: pathlib.Path) -> None:
    """a：信封被多包一层 ⇒ 受控拒；工具一个字节都没执行。"""
    loop = _loop(tmp_path)
    res = loop._do_tool({"name": "fs.list", "args": dict(WRAPPED), "why": "真机形状"})

    assert res.get("ok") is False, res
    assert res.get("tool") == "fs.list", res
    assert res.get("kind") == "param_error", res
    assert res.get("meta", {}).get("kind") == "param_error", res
    fix = str(res.get("meta", {}).get("how_to_fix") or "")
    assert fix, "受控拒必须带改法（`how_to_fix`）"
    assert "`args`" in fix and "直接" in fix, fix
    error = str(res.get("error") or "")
    assert "参数形状不对" in error and "name" in error, error
    assert "multiple values" not in error, "受控拒里不许再出现解释器那句裸异常：" + error
    # 工具没执行：结果里没有 `data` 的条目（`fs.list` 真跑会返回 entries）。
    assert not (res.get("data") or {}).get("entries"), res


def test_a2_the_same_args_would_crash_the_old_dispatch(tmp_path: pathlib.Path) -> None:
    """a-负控：同一份 `args` 喂给改前的分发（`registry.call(name, **args)`）必须抛。"""
    reg = _registry(tmp_path)
    with pytest.raises(TypeError) as caught:
        reg.call("fs.list", role="M", **WRAPPED)
    assert "multiple values" in str(caught.value), str(caught.value)
    # 同一份东西走分发点 ⇒ 不抛、给出受控拒。
    out = AL.dispatch_arg_refusal("fs.list", dict(WRAPPED))
    assert out.get("kind") == "param_error" and out.get("how_to_fix"), out


# ============================================================ b 正确形状照旧


def test_b_the_correct_shape_still_runs(tmp_path: pathlib.Path) -> None:
    """b：外层形状不变，只把实参放在 `args` 里 ⇒ 照旧执行（拒的射程只有那一个键）。"""
    loop = _loop(tmp_path)
    res = loop._do_tool({"name": "fs.list", "args": {"path": "."}})
    assert res.get("ok") is True, res
    assert (res.get("data") or {}).get("entries") is not None, res


# ============================================================ c 不是只对一件工具


def test_c_the_refusal_is_not_special_cased_to_one_tool(tmp_path: pathlib.Path) -> None:
    """c：`fs.list` 之外的工具同样受控拒（判据在分发点，不在某一件工具的壳里）。"""
    for name in ("fs.stat", "fs.list", "conductor.board"):
        out = AL.dispatch_arg_refusal(name, {"name": name, "args": {"path": "."}})
        assert out.get("kind") == "param_error", (name, out)
        assert out.get("how_to_fix"), (name, out)
    # 没有 `name` 键 ⇒ 放行（不是所有 args 都被拒）。
    assert AL.dispatch_arg_refusal("fs.list", {"path": "."}) == {}
    assert AL.dispatch_arg_refusal("fs.list", {}) == {}
