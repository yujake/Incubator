# -*- coding: utf-8 -*-
"""ROLE-GUIDE 的工具面数字必须等于现场装配，且跳过不许静默（审计 C 第 ① 条）。

背景（draft/173 §二 E-11）：`tools/write_system_docs.py::_registry()` 调
`build_registry()` 时不传 `store` / `workspace_root`，于是 `fs_tools` 与
`research_tools` 在装配期被跳过，生成物里六个角色的工具数系统性偏小 4–13 件
（A 46 / C 32 / E 32 / G 46 / H 42 / L 31，而现场是 54 / 36 / 40 / 54 / 46 / 39）。
更坏的是这件事在 diff 里长得像"文档没重生成"：`test_system_docs_are_generated`
只比"盘上 == 现算"，两边一起错它也绿。

所以这一条判两件事：

1. 生成器的量法 == 生产的量法（逐角色工具名集合相等，不只是数字相等）；
2. 任何模块被跳过时，生成器必须报错，而不是安静地少几件（反真空）。
"""

from __future__ import annotations

import importlib.util
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
GEN = REPO / "tools" / "write_system_docs.py"
GUIDE = REPO / "docs" / "ROLE-GUIDE.md"


def _module():
    spec = importlib.util.spec_from_file_location("write_system_docs_under_test_counts", GEN)
    assert spec and spec.loader, f"生成器不在盘上：{GEN}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _live_build(tmp_path: pathlib.Path):
    """与生产同源：`Store` + `workspace_root` + `strict=True`（照 `build_registry` 的签名）。"""
    from agentflow.store import Store
    from agentflow.tools import ROLES, build_registry

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    store = Store(ws)
    store.init()
    return build_registry(store=store, workspace_root=ws, roles=tuple(ROLES), strict=True)


def test_the_generators_tool_face_is_the_live_tool_face(tmp_path):
    """正控：生成器现算的每个角色工具名集合 == 现场装配的 `for_role`。"""
    mod = _module()
    live = _live_build(tmp_path).registry
    generated = mod._registry()

    assert set(generated.names()) == set(live.names()), (
        "生成器装到的工具全集与现场不一致："
        f"少 {sorted(set(live.names()) - set(generated.names()))} / "
        f"多 {sorted(set(generated.names()) - set(live.names()))}"
    )
    bad: dict[str, dict[str, list[str]]] = {}
    for role in mod.ROLES:
        live_names = {s.name for s in live.for_role(role)}
        generated_names = {s.name for s in generated.for_role(role)}
        if live_names != generated_names:
            bad[role] = {
                "现场有而生成器没有": sorted(live_names - generated_names),
                "生成器有而现场没有": sorted(generated_names - live_names),
            }
    assert not bad, f"这些角色的工具面在生成器里与现场不一致：{bad}"


def test_the_document_count_is_the_live_count_for_every_role(tmp_path):
    """正控：盘上 ROLE-GUIDE 的逐角色件数 == 现场（不只看总数）。"""
    mod = _module()
    text = GUIDE.read_text(encoding="utf-8")
    live = _live_build(tmp_path).registry
    got: dict[str, int] = {}
    for role in mod.ROLES:
        m = re.search(rf"^## 角色 {role}$\n(.*?)(?=^## 角色 |\Z)", text, re.M | re.S)
        assert m, f"ROLE-GUIDE 里读不到角色 {role} 那一节"
        n = re.search(r"共 \*\*(\d+)\*\* 件", m.group(1))
        assert n, f"角色 {role} 那一节里读不到『共 N 件』"
        got[role] = int(n.group(1))
    want = {role: len(live.for_role(role)) for role in mod.ROLES}
    assert got == want, f"ROLE-GUIDE 的逐角色件数 {got} != 现场 {want}"


def test_a_skipped_module_is_never_silent(monkeypatch):
    """反真空：装配里有一个模块被跳过 ⇒ 生成器必须报错（不许少而无声）。"""
    import agentflow.tools as T

    real_build = T.build_registry
    mod = _module()

    def fake_build(**kwargs):
        build = real_build(**kwargs)
        build.skipped.append(
            {"module": "fs_tools", "stage": "register", "error": "注入：故意让一个模块跳过"}
        )
        return build

    monkeypatch.setattr(T, "build_registry", fake_build)
    with pytest.raises(RuntimeError) as exc:
        mod._registry()
    message = str(exc.value)
    assert "fs_tools" in message, f"报错里没有点出被跳过的模块：{message}"
    assert "skipped" in message or "跳过" in message, f"报错没说清这是跳过：{message}"
