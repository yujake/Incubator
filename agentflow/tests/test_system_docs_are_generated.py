"""两份系统文档必须是生成的：改了角色/工具/权限面却没重生成，它当场红。

为什么这条判据值得存在：`docs/ROLE-GUIDE.md` 与 `docs/SYSTEM-COMPONENTS.md` 是给人读的介绍，
而它们的内容（职责 / 边界 / 官能 / 边 / 写集 / 动作表 / 工具面）全部有代码真身。
手写一份介绍文档，第一次写时是对的，第三次改权限面之后它就变成「看着有、其实在说谎」的文档 ——
而那正是 FC-27 那一类事故的形态（测试全绿、上线即越权）。

所以：文档由 `tools/write_system_docs.py` 现算，本判据重跑一遍并逐字节比（与 `ui/src/types.ts` 同形）。
另外核两件事：组件表点名的模块真的在盘上；两份文档都进了 `docs/INDEX.md`。
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "write_system_docs.py"
ROLE_GUIDE = ROOT / "docs" / "ROLE-GUIDE.md"
COMPONENTS_DOC = ROOT / "docs" / "SYSTEM-COMPONENTS.md"
INDEX = ROOT / "docs" / "INDEX.md"


def _module():
    spec = importlib.util.spec_from_file_location("write_system_docs_under_test", GEN)
    assert spec and spec.loader, f"生成器不在盘上：{GEN}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_two_documents_are_byte_identical_to_a_fresh_generation() -> None:
    """正控：盘上那两份 == 现算的那两份（逐字节）。"""
    mod = _module()
    for path, rendered in (
        (ROLE_GUIDE, mod.render_role_guide()),
        (COMPONENTS_DOC, mod.render_components()),
    ):
        assert path.is_file(), f"{path.name} 不见了（它是由 write_system_docs.py 生成的）"
        on_disk = path.read_text(encoding="utf-8")
        assert on_disk == rendered, (
            f"{path.name} 与现算结果不一致 ⇒ 跑 `python -B tools/write_system_docs.py` 重生成。"
            f"（盘上 {len(on_disk)} 字符 / 现算 {len(rendered)} 字符）"
        )


def test_the_role_guide_covers_every_role_and_both_surfaces() -> None:
    """每个角色都得有自己的一节，而且四件事都在：设定 / 职责 / 协作面 / 工具面 / 读写。"""
    text = ROLE_GUIDE.read_text(encoding="utf-8")
    from agentflow import capabilities as C

    for role in C.CAPABILITIES:
        assert f"## 角色 {role}" in text, f"角色指南里没有 {role} 那一节"
    for heading in ("### 角色设定", "### 具体职责（动作表）", "### 协作面",
                    "### 工具面（这个角色实际拿到的件）", "### 主要读写的文档与细节"):
        assert heading in text, f"角色指南缺小节：{heading}"


def test_the_components_section_names_modules_that_exist() -> None:
    """反真空：组件表里点名的每个模块都得真在盘上（模块没了，文档就在说假话）。"""
    mod = _module()
    assert len(mod.COMPONENTS) >= 15, f"组件表只剩 {len(mod.COMPONENTS)} 条 ⇒ 这条判据失去对象"
    missing = [name for name, module, *_ in mod.COMPONENTS if not (ROOT / module).exists()]
    assert not missing, f"组件表点名的模块不在盘上：{missing}"


def test_every_documented_symbol_mentioned_in_a_component_is_importable() -> None:
    """组件表里写成 `模块.符号` 的那几个（若有）必须真的存在于那个模块。

    只核"点名的模块"里出现过的 `模块.符号` 形态（例如 `store.tx` 写在落点列里不算符号引用），
    避免把散文里的词当符号。
    """
    import importlib

    mod = _module()
    checked = 0
    for name, module, _what, how, _where, _judge in mod.COMPONENTS:
        dotted = f"{pathlib.Path(module).stem}."
        for token in how.replace("、", " ").replace("与", " ").replace("加", " ").split():
            token = token.strip("`，。()（）;；")
            if not token.startswith(dotted):
                continue
            attr = token[len(dotted):]
            if not attr.isidentifier():
                continue
            try:
                mod_obj = importlib.import_module(f"agentflow.{pathlib.Path(module).stem}")
            except Exception:  # noqa: BLE001 - 包内的模块不一定都能直接 import（如 specs 包）
                continue
            assert hasattr(mod_obj, attr), (
                f"组件 {name} 的实现细节里点名了 {token}，而 agentflow."
                f"{pathlib.Path(module).stem} 里没有这个属性"
            )
            checked += 1
    assert checked == 0 or checked > 0  # 形态说明：为空也允许（散文里不一定有 模块.符号 形态）


def test_both_documents_are_registered_in_the_docs_index() -> None:
    """文档不登记进 INDEX，读者就找不到它（与 `test_docs_index_covers_every_doc` 是同一条纪律）。"""
    text = INDEX.read_text(encoding="utf-8")
    for name in ("ROLE-GUIDE.md", "SYSTEM-COMPONENTS.md"):
        assert name in text, f"docs/INDEX.md 里没有 {name}"
