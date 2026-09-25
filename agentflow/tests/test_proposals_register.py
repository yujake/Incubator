"""`docs/PROPOSALS.md` 的编号唯一性与引用完整性。

## 为什么编号值得一条门

`docs/PROPOSALS.md` 的全部价值是"一条编号指向一件确定的事"：
`DEVELOPMENT.md` 的待办表、`tests/` 里的 `xfail(reason=...)`、`src/` 的 `# 待修：`
注释都靠 `G-6` 这样的短号互相指。编号重复 = 引用不可判定。

这不是假想：本轮真的撞了一次号 —— 两条新增条目都被写成 `G-9`（一条讲
`criterion_revision` 的双份漂移，一条讲 106 个零直接测试的公开函数），
而且第二条的号已被 `tests/test_coverage_schema.py:10` 引用，于是"G-9 指哪一条"
在那一刻没有答案。这与 FC-03（"同一份判据两处落地"）是同一族：
编号是一种命名空间，两个人同时加一条就会撞。

本文件同时充当引用完整性的门：文档/测试/源码里提到的每一个编号都必须真实存在 ——
否则读者会去找一条不存在的条目（"虚证"的另一种形态）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROPOSALS = REPO / "docs" / "PROPOSALS.md"

_ID = r"[GPN]-\d+"
_HEAD = re.compile(rf"^##\s+({_ID})[：:]", re.MULTILINE)


def _defined_ids() -> list[str]:
    text = PROPOSALS.read_text(encoding="utf-8")
    return _HEAD.findall(text)


def _all_text_files() -> list[Path]:
    out: list[Path] = []
    for base in (REPO / "docs", REPO / "tests", REPO / "tools", REPO / "src", REPO / "scripts"):
        if base.is_dir():
            out.extend(p for p in base.rglob("*") if p.suffix in (".md", ".py") and "__pycache__" not in p.parts)
    out.extend([REPO / "DEVELOPMENT.md", REPO / "AGENTS.md", REPO / "NOAI-REVIEW-REGISTER.md", PROPOSALS])
    return out


def test_proposals_ids_are_unique():
    """正向（核心）：条目编号必须唯一。

    撞号的后果不是报错，而是"引用变歧义" —— 读者/工具无法判断 `G-9` 指哪一条，
    而没有任何东西会变红（直到这里）。
    """
    ids = _defined_ids()
    assert ids, "从 PROPOSALS.md 里一条编号都没解析到 —— 判据本身失效（**没查成**，不是通过）"
    dup = sorted({i for i in ids if ids.count(i) > 1})
    assert not dup, f"PROPOSALS.md 的条目编号重复：{dup}（引用将变成歧义）"


def test_proposals_ids_are_well_formed():
    """正向：编号形如 `G-7` / `P-11`（字母 + 连字符 + 数字，无前导零）。"""
    bad = [i for i in _defined_ids() if not re.fullmatch(r"[GPN]-[1-9]\d*", i)]
    assert not bad, f"编号格式不合规：{bad}"


def test_every_referenced_id_exists():
    """正向（引用完整性）：提到 PROPOSALS 的地方引用的每个编号都必须真的有一条。

    防的是"读者去找一条不存在的条目"。本轮真的抓到过一条：
    `tests/test_coverage_gates.py` 的 docstring 写着"已登记进 `docs/PROPOSALS.md` 的 G-5 条"，
    而 `G-5` 当时不存在（编号从 `G-4` 跳到了 `G-6`）—— 一条悬空引用。

    判据必须有作用域，否则会假报警：`G-5` 这种形状在别处也合法 ——
    `ROLE-SPECS.md` 的角色动作表里有 `| G-5 |`（角色 G 的第 5 个动作），
    它与本文件的条目编号是两套命名空间。所以只统计同一行或紧邻上文提到 `PROPOSALS`
    的那些引用。这条作用域限制是实测出来的：第一版没有它，`ROLE-SPECS.md` 立刻假红。
    """
    defined = set(_defined_ids())
    missing: dict[str, list[str]] = {}
    for p in _all_text_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(rf"\b({_ID})\b", text):
            ref = m.group(1)
            if ref in defined:
                continue
            # 作用域：同一行，或紧邻的 240 字符内，必须出现 PROPOSALS
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            window = text[max(0, m.start() - 240): (line_end if line_end > 0 else len(text))]
            if "PROPOSALS" not in window and "PROPOSALS" not in text[line_start:line_end]:
                continue
            missing.setdefault(ref, []).append(str(p.relative_to(REPO)))
    assert not missing, f"这些编号被（提到 PROPOSALS 的地方）引用但条目不存在：{missing}"


def test_gap_in_numbering_is_documented():
    """正向：编号的空洞必须被写明"留空、不要复用"。

    `G-5` 从未被使用（`G-4` 之后直接是 `G-6`）。一个没有说明的空洞会招来
    "这里大概是漏了一条" 或者更糟 —— 下一个人把它复用给一件无关的事，
    于是"G-5"在某些上下文里指一件事、在另一些上下文里指另一件。
    """
    text = PROPOSALS.read_text(encoding="utf-8")
    defined = {i for i in _defined_ids() if i.startswith("G-")}
    used = sorted(int(i.split("-")[1]) for i in defined)
    gaps = [n for n in range(1, max(used) + 1) if n not in used]
    if not gaps:
        return
    head = text.split("## P-1", 1)[0]
    for n in gaps:
        assert f"G-{n}" in head, (
            f"`G-{n}` 是编号空洞，但没有在 PROPOSALS.md 的开头说明它『留空、不要复用』"
            "（没有说明的空洞会被复用成一件无关的事）"
        )
