# -*- coding: utf-8 -*-
"""判据：成稿序列的第 ⓪ 步（`doc.build_document` 落一行 `documents`）必须写在编译之前。

## 缺口（2026-11-04）

`doc.paper_compile` 在 2026-11-04 加了一道门：没有 `documents` 行 ⇒ 受控拒绝
`paper_not_registered`（判据 `tests/test_paper_compile_needs_a_registered_document.py`）。
两处"成稿四步序列"还停在旧口径（① 写正文 → ② 落对应表 → ③ 逐行核 → ④ 编译），
照它做到第 ④ 步会撞门 —— 而序列本身是教学面，读的人会以为 ① 是第一步。

⇒ 序列改成 ⓪ 先 `doc.build_document` → ① … → ④ `doc.paper_compile`。
两处落点：`src/agentflow/specs/g.py` 的 G 动作描述、`src/agentflow/agent_skills.py`
的 G 手册「成稿-正文自己写」。

## 判据

| # | 判据 | 改前为什么红 |
|---|---|---|
| a | 两份序列都：有 ⓪、⓪ 在 ④ 之前、⓪ 那一格点名 `doc.build_document` / `documents` / `paper_not_registered`、且 `build_document` 在 `paper_compile` 之前 | 没有 ⓪ 这一步 |
| b | 反真空：把真身里 ⓪ 那一格删掉 ⇒ 同一份判据必须报缺 | 没有这一格可删，判据会读别处 |
| c | 覆盖：序列只在这两处教（少一处 / 多一处都红） | 两处各缺 ⓪ |

b 为什么必要：`specs/g.py` 那一句的开头（D-38 的引子里）本来就有
`doc.build_document` 四个字 —— 只比 "`build_document` 在 `paper_compile` 之前"的话，
把 ⓪ 整格删掉判据仍然绿（它读到的是引子里那一处）。所以判据钉的是"⓪ 这一格"，
不是"这四个字在不在这一段里"。
"""
from __future__ import annotations

import ast
import pathlib
import re

PROJECT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = (
    PROJECT / "src/agentflow/agent_skills.py",
    PROJECT / "src/agentflow/agent_prompts.py",
    *sorted((PROJECT / "src/agentflow/specs").glob("*.py")),
)

ANCHOR = "成稿是四步动作序列"
#: 这两处是业主 2026-11-04 点名的落点（`specs/g.py:477` 与 `agent_skills.py:3070`）。
EXPECTED = ("src/agentflow/agent_skills.py", "src/agentflow/specs/g.py")

STEP_ZERO = "⓪"
STEP_ONE = "①"
STEP_FOUR = "④"


def _rel(path: pathlib.Path) -> str:
    return str(path.relative_to(PROJECT)).replace("\\", "/")


def surfaces() -> list[tuple[str, int, str]]:
    """模型可见面里教这份序列的段落 ⇒ `[(相对路径, 行号, 段落原文)]`。"""
    rows: list[tuple[str, int, str]] = []
    for path in SOURCES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # 读不动 ⇒ 没查成，不许当成"没有这段"
            raise AssertionError(f"{_rel(path)}: 解析失败（{exc}）⇒ 没查成") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for para in re.split(r"\n\s*\n", node.value):
                    if ANCHOR in para:
                        rows.append((_rel(path), int(node.lineno), para))
    return sorted(rows, key=lambda r: (r[0], r[1]))


def problems(text: str) -> list[str]:
    """这一段缺哪几样（a 用真身；b 把删掉 ⓪ 的正文喂进同一个判据）。"""
    out: list[str] = []
    i0 = text.find(STEP_ZERO)
    i4 = text.find(STEP_FOUR)
    if i0 < 0:
        out.append(f"没有 {STEP_ZERO} 这一步（先调 `doc.build_document` 落一行 `documents`）")
    if i4 < 0:
        out.append(f"没有 {STEP_FOUR} 这一步（`doc.paper_compile` 编译）")
    if i0 >= 0 and i4 >= 0 and not i0 < i4:
        out.append(f"{STEP_ZERO} 不在 {STEP_FOUR} 之前")
    if i0 >= 0:
        i1 = text.find(STEP_ONE, i0)
        zero = text[i0:i1 if i1 > i0 else len(text)]
        if "build_document" not in zero:
            out.append(f"{STEP_ZERO} 那一格没写 `doc.build_document`")
        if "documents" not in zero:
            out.append(f"{STEP_ZERO} 那一格没说落哪张表（`documents`）")
        if "paper_not_registered" not in zero:
            out.append(f"{STEP_ZERO} 那一格没说缺它的后果（`paper_not_registered`）")
        rebuild = zero.find("build_document")
        compile_at = text.find("paper_compile", i0)
        if compile_at < 0:
            out.append("整段没有 `paper_compile`（说不清 ⓪ 要先于哪一步）")
        elif rebuild < 0 or not rebuild < compile_at:
            out.append("`build_document` 不在 `paper_compile` 之前")
    if i4 >= 0 and ("编译" not in text[i4:] and "compile" not in text[i4:]):
        out.append(f"{STEP_FOUR} 那一格没说是编译")
    return out


def _drop_step_zero(text: str) -> str:
    """把真身里的 ⓪ 那一格（到下一个 `→` 为止）整段删掉 —— 反真空用的改前形态。"""
    return re.sub(rf"{STEP_ZERO}.*?→\s*", "", text, count=1, flags=re.S)


# ============================================================ a ⓪ 在 ④ 之前
def test_a_both_copies_start_with_build_document_before_compile() -> None:
    """a：两份序列都有 ⓪，且 `build_document` 写在 `paper_compile` 之前。"""
    rows = surfaces()
    assert rows, f"模型可见面里找不到 {ANCHOR!r} ⇒ 判据没有落点"
    bad = [f"{rel}:{line}  " + "；".join(problems(text)) for rel, line, text in rows
           if problems(text)]
    assert bad == [], "成稿序列没有把 ⓪ 写在编译之前：\n  - " + "\n  - ".join(bad)
    # 正控（同一份判据必须对改后的形态说"不缺"）：绿的前提是真读到了这两处。
    assert len(rows) >= len(EXPECTED), rows


# ============================================================ b 反真空
def test_b_deleting_step_zero_from_the_real_text_turns_it_red() -> None:
    """b：把真身里 ⓪ 那一格删掉 ⇒ a 的判据必须报缺（不许被引子里的四个字骗过）。"""
    for rel, line, text in surfaces():
        if STEP_ZERO not in text:      # 改前形态：没有 ⓪ 可删，a 已经因此判红
            assert problems(text), f"{rel}:{line} 没有 ⓪，且判据不报缺"
            continue
        stripped = _drop_step_zero(text)
        assert stripped != text, f"{rel}:{line} 的 ⓪ 没删掉（打桩没生效）"
        assert STEP_ZERO not in stripped, f"{rel}:{line} 删了 ⓪ 之后还剩 ⓪"
        found = problems(stripped)
        assert found, (f"{rel}:{line} 把 {STEP_ZERO} 整格删掉之后判据仍然全绿 ⇒ "
                       "a 读的不是 ⓪ 这一格")
        assert any(STEP_ZERO in one for one in found), found


# ============================================================ c 覆盖
def test_c_the_sequence_is_taught_in_exactly_these_two_places() -> None:
    """c：序列只在这两处教 —— 少一处（漏改）或多一处（第三份旧口径）都红。"""
    got = sorted({rel for rel, _line, _text in surfaces()})
    assert got == sorted(EXPECTED), (
        "教这份序列的文件变了（业主点名的两处是 "
        + " / ".join(EXPECTED) + "）：\n  实得：" + " / ".join(got))


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    surfaces_got = surfaces()
    print(f"[读数] {ANCHOR!r} 出现在 {len(surfaces_got)} 处：")
    for rel, line, text in surfaces_got:
        missing = problems(text)
        print(f"  {'OK ' if not missing else 'RED'} {rel}:{line}"
              + ("" if not missing else "  " + "；".join(missing)))
    raise SystemExit(0 if all(not problems(t) for _r, _l, t in surfaces_got) else 1)
