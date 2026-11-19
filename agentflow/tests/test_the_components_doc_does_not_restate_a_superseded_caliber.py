# -*- coding: utf-8 -*-
"""判据：「收工门」那一行不许再说 `can_close` 是机械门（2026-11-03，153-U-12）。

## 背景

同一个布尔在今天有三处说法，其中一处正好相反：

| 处 | 说法 |
|---|---|
| `closing.py` 的 `ClosingReport.can_close` | = M 在 `m_verdict.met` 里说的那一句 |
| `closing.py:VERDICT_NOTE`（业主 2026-10-09 的两句裁定） | 同上；机器八格（`status` / `machine_pass`）是读数 |
| `docs/SYSTEM-COMPONENTS.md`（生成物） | 「`ClosingReport（can_close 只在全过为真）`」 |

最后那一句出自 `tools/write_system_docs.py` 的组件表（表是手写的，判据只核"点名的模块与
符号存在"，`tests/test_system_docs_are_generated.py` 逐字节比的是"盘上 == 现算"，散文的
真假不在任何判据的射程里）。于是它一路绿灯地挂在那里，把 2026-10-09 被裁定推翻的口径
当成规格讲给读者 —— 而 `can_close` 是全仓最重要的一个布尔。

## 这条判据钉住什么

1. 生成物里不许再出现那句旧口径（"只在全过为真"）—— 生成物是模型/读者真正看到的那一份；
2. 生成器里也不许留（只改生成物 = 下一次 `python tools/write_system_docs.py` 就回来）；
3. 那个格子必须点名真正的口径（`m_verdict`）—— 删掉旧话而什么都不说，等于把这一格
   挖空，读者照样不知道 `can_close` 是什么；
4. 真值锚点自己也钉住：`can_close` 的实现今天必须读 `m_verdict`（若哪天真的改回机械合取，
   那是业主的另一次裁定 —— 那时本判据的第 1–3 条会一起失效，而不是"文档对了、代码错了"）。

第 4 条是这条判据的反真空：没有它，三条文案断言可以在真值已经换了的情况下继续绿着。
"""
from __future__ import annotations

import importlib.util
import inspect
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
GEN = ROOT / "tools" / "write_system_docs.py"
COMPONENTS_DOC = ROOT / "docs" / "SYSTEM-COMPONENTS.md"

#: 2026-10-09 的裁定要否掉的那句话（生成器里写的是裸 `can_close`，生成物带反引号）。
_SUPERSEDED = "只在全过为真"

#: 真正的口径：`can_close` 读的是 M 那一份判据里的 `met`。
_TRUE_CALIBER = "m_verdict"


def _module():
    spec = importlib.util.spec_from_file_location("write_system_docs_under_test_u12", GEN)
    assert spec and spec.loader, f"生成器不在盘上：{GEN}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _closing_row_in_the_doc() -> str:
    """生成物里「收工门」那一整行（表格一行 = 这个组件全部的说法）。"""
    rows = [ln for ln in COMPONENTS_DOC.read_text(encoding="utf-8").splitlines()
            if ln.startswith("| **收工门** |")]
    assert len(rows) == 1, (
        f"`docs/SYSTEM-COMPONENTS.md` 里应当恰好有一行收工门，实测 {len(rows)} 行"
        "（生成器的组件表动了 ⇒ 这条判据要跟着改，不是把它放宽）")
    return rows[0]


def _closing_how_in_the_generator() -> str:
    mod = _module()
    #: 组件表每条的形态是 `(名字, 模块, 一句话功能, 实现细节, 落点, 判据)` ⇒ 实现细节是第 4 格。
    hits = [name_and_fields[3] for name_and_fields in mod.COMPONENTS if name_and_fields[0] == "收工门"]
    assert len(hits) == 1, f"生成器的组件表里应当恰好有一条收工门，实测 {len(hits)} 条"
    return hits[0]


def test_the_generated_doc_does_not_restate_the_superseded_caliber() -> None:
    """① 生成物里不许再出现"只在全过为真"（今天红）。"""
    row = _closing_row_in_the_doc()
    assert _SUPERSEDED not in row, (
        "`docs/SYSTEM-COMPONENTS.md` 的收工门那一行又在说" + _SUPERSEDED + "：\n"
        f"  {row}\n"
        "按 `closing.py:VERDICT_NOTE`（业主 2026-10-09），`can_close` = M 在 "
        "`m_verdict.met` 里说的那一句；八格（`status` / `machine_pass`）是读数。"
        "改 `tools/write_system_docs.py` 的组件表那一句，再重跑生成器。")


def test_the_generator_itself_does_not_keep_the_superseded_sentence() -> None:
    """② 生成器里也不许留（只改生成物 ⇒ 下一次重生成就回来）。"""
    how = _closing_how_in_the_generator()
    assert _SUPERSEDED not in how, (
        "`tools/write_system_docs.py` 的组件表里还留着" + _SUPERSEDED + " ⇒ "
        "重跑一次生成器就会把旧口径写回文档")


def test_the_row_names_the_real_caliber() -> None:
    """③ 那一格必须点名真正的口径（删掉旧话不等于说对了）。"""
    row = _closing_row_in_the_doc()
    assert _TRUE_CALIBER in row, (
        "收工门那一行没有点名 `m_verdict` ⇒ 读者仍然不知道 `can_close` 是谁的判据：\n"
        f"  {row}")


def test_the_anchor_is_still_the_m_verdict() -> None:
    """④ 反真空：M 的判断那一格今天必须读 `m_verdict`（否则上面三条钉的是空气）。

    2026-11-03（153-U-01/U-02）：那一格改名叫 `m_says_done`；`can_close` 变成了机器口径
    （`bool | None`，`None` = 没接线）。所以锚点也搬过去 —— 文档里"`m_says_done` = M 在
    `m_verdict.met` 里说的那一句"这句话的真身是那个属性。

    2026-11-19（ROOTGATE-①）：`can_close` 不再自己读机器读数，它由
    `closing.closing_verdict` 一处算出；"机器那一格"的真身因此搬到那个函数里
    （`_machine_caliber`），本判据跟着搬，不把旧位置当成永久契约。
    """
    from agentflow import closing as CL
    from agentflow.closing import ClosingReport

    prop = ClosingReport.m_says_done
    source = inspect.getsource(prop.fget if isinstance(prop, property) else prop)
    assert _TRUE_CALIBER in source, (
        "`ClosingReport.m_says_done` 不再读 `m_verdict` ⇒ 真值换人了，"
        "`docs/SYSTEM-COMPONENTS.md` 那一条说法必须重新裁一次，不能继续绿着：\n"
        f"{source}")
    verdict_src = inspect.getsource(CL.closing_verdict)
    assert "_machine_caliber" in verdict_src, (
        "`closing_verdict` 不再读机器读数那一格（2026-11-03 裁决 ①=乙）：\n"
        f"{verdict_src[:800]}")
    assert ClosingReport.can_close.fget.__doc__ and (
        "closing_verdict" in ClosingReport.can_close.fget.__doc__), (
        "`can_close` 的 docstring 没点名唯一来源 `closing_verdict` —— "
        "读者会以为它还在自己算")
