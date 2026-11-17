# -*- coding: utf-8 -*-
"""`docs/DESIGN-BASELINE.md` 落库判据（AU2b 乙组·⑤）。

## 钉住什么

1. 文件在，且是那份基线（51 条 B01–B51 与六层权威序都在，不是一份空壳）；
2. `docs/ROLE-SPECS.md` 顶部有一行指针（指向它、并写明 51 条与六层权威序）；
3. `docs/INDEX.md` 登记了它（`tests/test_docs_index_covers_every_doc.py` 的同一条纪律）；
4. 落库时按现读校正过的那几条不再漂：B19 的工具有 126/123、B22 的收工门是 8 格
   （含 `literature_pending`、不含 `paper`）。这一条是活的：`closing.DEFAULT_CHECKS` 一变就红。

## 反真空

条数不是「扫到几个算几个」：必须恰好 51 条、编号连续；文件长度下限与
权威序/判级规则的存在性一起挡住「复制了一个标题就交」。
"""
from __future__ import annotations

import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
BASELINE = DOCS / "DESIGN-BASELINE.md"
ROLE_SPECS = DOCS / "ROLE-SPECS.md"
INDEX = DOCS / "INDEX.md"


def _text(path: pathlib.Path) -> str:
    assert path.is_file(), f"{path} 不在盘上"
    got = path.read_text(encoding="utf-8")
    assert len(got) > 1000, f"{path} 只有 {len(got)} 字节 ⇒ 读错文件"
    return got


def _baseline() -> str:
    text = _text(BASELINE)
    assert len(text) > 15000, f"基线只有 {len(text)} 字符 ⇒ 不像那份 51 条的正文"
    return text


def test_the_file_has_the_51_items_and_the_six_layer_order() -> None:
    text = _baseline()
    numbers = [int(n) for n in re.findall(r"\*\*B(\d{2}) —", text)]
    assert numbers == list(range(1, 52)), numbers
    assert "B52" not in text

    order = text.split("## §1", 1)[1].split("## §2", 1)[0]
    for layer in ("业主逐字裁定", "实现 + 判据", "声明层", "生成物", "手写规格散文", "设计理由文档"):
        assert layer in order, layer
    assert "不算裁定" in order and "上位吃掉下位" in order
    level = text.split("## §2", 1)[1].split("## §3", 1)[0]
    for kind in ("甲", "乙", "丙", "丁"):
        assert f"**{kind}**" in level, kind


def test_role_specs_has_a_pointer_at_the_top() -> None:
    head = "\n".join(_text(ROLE_SPECS).splitlines()[:16])
    assert "DESIGN-BASELINE.md" in head
    assert "51 条" in head and "六层权威序" in head


def test_the_index_registers_it() -> None:
    assert "DESIGN-BASELINE.md" in _text(INDEX)


def test_the_corrected_readings_still_match_the_disk() -> None:
    """B19 / B22 是落库时按现读校正的：再漂就红。"""
    from agentflow import closing

    text = _baseline()
    b22 = text.split("**B22 —", 1)[1].split("**B23 —", 1)[0]
    checks = tuple(closing.DEFAULT_CHECKS)
    assert len(checks) == 8, checks
    assert "8 格" in b22
    for key in checks:
        assert f"`{key}`" in b22, key
    assert "`paper` 不在格内" in b22
    assert "126 件 / Lean 关 123 件" in text
