# -*- coding: utf-8 -*-
"""`docs/` 下每一份文档都要在 `docs/INDEX.md` 里有落点（2026-10-27 业主裁定，R-DOC 那块）。

## 为什么这是判据

`docs/INDEX.md` 自称"权威地图：哪份算数、哪份只作依据"，而"哪份算数"这件事只有它一处维护
（它自己第 4 节第 2 条写着"新增文档必须在这里登记，否则下一个人只能靠猜"）。
一句话没有判据就只是愿望：新增一份 `docs/*.md` 而不登记，`docs/` 里就多出一份没人知道
该不该引的文件，而没有任何东西会响。

三档口径（与 INDEX 的分节一致）：

- 入册：文件名在 INDEX 正文里出现过（§1 入口 / §2 当前规格 / §3 历史证据 / §3.1 送审页与停摆记录
  的取代表，哪一处都算）；
- 不入册：登记进 INDEX §6 那张表，并写清理由 —— "没登记"与"登记了不打算登记"必须分得开；
- 漏登记：两边都没有 ⇒ 红。

## 反真空

`len(docs) >= 30` 且"INDEX 里认得出的"也要 ≥ 30：盘上只剩几份文档、或 INDEX 被清空，
都不能让这条判据以"全都登记过了"的形态绿。另有一条负控：喂一份伪造的"盘上多一份"，
必须报出来。
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
INDEX = DOCS / "INDEX.md"

#: 反真空下限：今天的盘上是 33 份。
MIN_DOCS = 30

#: §6「不入册」表里的一行：`| `名字.md` | 理由 |`。
_UNREGISTERED_ROW = re.compile(r"^\|\s*`([^`]+\.md)`\s*\|\s*(.+?)\s*\|", re.M)


def _disk_docs() -> list[str]:
    """盘上的文档名（INDEX 自己不算"要被索引的文档"）。"""
    return sorted(p.name for p in DOCS.glob("*.md") if p.name != INDEX.name)


def _index_text() -> str:
    if not INDEX.is_file():
        pytest.skip(f"{INDEX} 不在盘上")
    return INDEX.read_text(encoding="utf-8")


def _unregistered(text: str) -> dict[str, str]:
    """§6「不入册」那张表：`{文件名: 理由}`（只认有理由的那些行）。"""
    section = text.split("## 6.", 1)
    if len(section) != 2:
        return {}
    out: dict[str, str] = {}
    for m in _UNREGISTERED_ROW.finditer(section[1]):
        name, why = m.group(1).strip(), m.group(2).strip()
        if name.endswith(".md") and why and "（今天没有这一档）" not in name:
            out[name] = why
    return out


def unregistered_problems(names: list[str], text: str) -> list[str]:
    """`names` 里既不在 INDEX 正文、也没登记进 §6 的那些（纯函数，负控喂它）。"""
    exempt = _unregistered(text)
    body = text.split("## 6.", 1)[0]
    return [f"{name} 既不在 docs/INDEX.md 里，也没登记进 §6「不入册」"
            for name in names
            if name not in body and name not in exempt]


# ====================================================================== 正控
def test_every_doc_is_registered_or_explicitly_not() -> None:
    """盘上每一份 `docs/*.md` 都在 INDEX 里有落点（入册或 §6 登记）。"""
    names = _disk_docs()
    assert len(names) >= MIN_DOCS, f"盘上只认出 {len(names)} 份文档 ⇒ 扫描可能失配"
    problems = unregistered_problems(names, _index_text())
    assert not problems, "；".join(problems)


def test_the_index_really_names_most_of_them() -> None:
    """反真空：INDEX 正文里真点到了 ≥ 30 份（不是靠 §6 的"不入册"凑出来的）。"""
    text = _index_text()
    body = text.split("## 6.", 1)[0]
    named = {name for name in _disk_docs() if name in body}
    assert len(named) >= MIN_DOCS, f"INDEX 正文里只点到 {len(named)} 份文档 ⇒ 索引可能被清空过"


def test_the_superseded_table_names_the_five_historical_ones() -> None:
    """§3.1 那张"谁被谁取代"的表必须覆盖那 5 份历史件（3 份 FC27-PENDING + 2 份 NOAI-SUSPENSION）。"""
    text = _index_text()
    section = text.split("### 3.1", 1)
    assert len(section) == 2, "INDEX 里没有 §3.1（谁被谁取代）那一节"
    body = section[1].split("## 4.", 1)[0]
    for name in ("FC27-PENDING-2026-10-21.md", "FC27-PENDING-CLEANING-2026-10-21.md",
                 "FC27-PENDING-LEAN.md", "NOAI-SUSPENSION-2026-09-25.md",
                 "NOAI-SUSPENSION-2026-09-28.md"):
        assert name in body, f"§3.1 里没有 {name} 的取代关系"


# ====================================================================== 负控
def test_a_new_unregistered_doc_turns_this_red() -> None:
    """负控：喂一份"盘上多出来、INDEX 里没有"的文档 ⇒ 必须报出来。

    这一条不碰盘：它证明的是 `unregistered_problems` 真的会红，而不是"这次没红"。
    """
    text = _index_text()
    assert unregistered_problems(["A-DOC-THAT-DOES-NOT-EXIST.md"], text) == [
        "A-DOC-THAT-DOES-NOT-EXIST.md 既不在 docs/INDEX.md 里，也没登记进 §6「不入册」"]
    # 反向：真在 INDEX 里的一份必须不报（否则"报出来"证明不了任何事）
    assert unregistered_problems(["USER-GUIDE.md"], text) == []


def test_the_unregistered_table_needs_a_reason() -> None:
    """负控：§6 里登记了却没写理由 ⇒ 不算登记（"没写为什么"与"漏登记"同档）。"""
    fake = ("## 6. 不入册（显式登记 + 理由）\n\n"
            "| 文件 | 为什么不入册 |\n|---|---|\n"
            "| `TEMP-THING.md` |  |\n")
    assert unregistered_problems(["TEMP-THING.md"], fake) != []
    good = ("## 6. 不入册（显式登记 + 理由）\n\n"
            "| 文件 | 为什么不入册 |\n|---|---|\n"
            "| `TEMP-THING.md` | 一次性复算输出，不是文档 |\n")
    assert unregistered_problems(["TEMP-THING.md"], good) == []
