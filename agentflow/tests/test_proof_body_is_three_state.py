# -*- coding: utf-8 -*-
"""`depsection.proof_body` 的三态（2026-11-09，审计 D4）。

## 缺陷（真机 + 源码）

`depsection.proof_body`（`depsection.py:593-608`）在 `## 证明` 缺节时会回退到
`## 依赖` 节正文、再回退到整份全文 ⇒ "没这一块"变成"拿了别的块"。真机实测：
`reports/e-num-000000.md` 的 `proof_body` = 1597 字符 = 整份文件（被绿色通道
`_green.ok` 挡住，纯运气）。E 侧早就有正确口径（`exhaustionreport.proof_body_of`：
缺节 ⇒ 空串，不许冒充）。

## 这一份判据钉什么

1. `present`：拿到 `## 证明` 那一节的正文（且只有那一节）；
2. `absent`：明确说"没有这一节"，正文是空串 —— 反真空：把回退加回去（退到
   `## 依赖` / 整份全文）⇒ `test_absent_does_not_fall_back_to_another_block` 必红；
3. `unreadable`：文件读不出来（不是 UTF-8）⇒ 说"读不出"，不是 `absent`
   （"没读到"与"没有这一节"是两件事，不许折平）；
4. 穷举档换名后的口径（`exhaustionreport.proof_body_of`）与 `depsection` 同一处，
   缺节同样返回空串（业主 2026-11-08 的 E 侧口径，行为不变）。

全部纯函数 / tmp 文件，零模型调用，不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import re

from agentflow import depsection as DS
from agentflow import exhaustionreport as ER
from agentflow import manuscriptform as MF
from agentflow import proofregistry as PR
from agentflow.agent_b import register_statement as RS

#: 有一节 `## 证明`：present。
WITH_PROOF = (
    "\n"
    "## 命题\n"
    "命题正文（这一行不是证明）。\n"
    "\n"
    "## 证明\n"
    "第一步：由定义直接推出。\n"
    "第二步：两步合起来就是结论。\n"
    "\n"
    "## 依赖\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| 第一步用了它 | stmt:000001 | 1 | 1 |\n"
)

#: 没有 `## 证明`（e-num-* 那一族的形状：命题 + 数值结果 + 依赖段）。
WITHOUT_PROOF = (
    "\n"
    "## 命题\n"
    "命题正文（这一行不是证明）。\n"
    "\n"
    "## 数值结果\n"
    "n=1..100 全部成立。\n"
    "\n"
    "## 依赖\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| 第一步用了它 | stmt:000001 | 1 | 1 |\n"
)

#: `## 证明` 里那一节的正文（present 时应当逐字拿到的这一串）。
PROOF_BODY = "第一步：由定义直接推出。\n第二步：两步合起来就是结论。\n"

#: 真机 DCT 彩排的形状（2026-11-10）：`## 证明` 下面用同级的 `## 记号` /
#: `## 第一步` 分小节 —— 真实数学写作最常见的样子。改前这些行每一行都被当成
#: "下一节的标题" ⇒ 证明正文被截成空串 ⇒ 落稿闸报 `empty_proof_section`。
WITH_LEVEL2_SUBHEADS = (
    "\n"
    "## 命题\n"
    "命题正文（这一行不是证明）。\n"
    "\n"
    "## 证明\n"
    "\n"
    "## 记号与约定\n"
    "以下所有不等式均按 μ-几乎处处理解。\n"
    "\n"
    "## 第一步：f 可积\n"
    "由控制函数 g 直接得到。\n"
    "\n"
    "## 依赖\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| 第一步用了它 | stmt:000001 | 1 | 1 |\n"
)
LEVEL2_PROOF_BODY = ("\n## 记号与约定\n"
                     "以下所有不等式均按 μ-几乎处处理解。\n"
                     "\n"
                     "## 第一步：f 可积\n"
                     "由控制函数 g 直接得到。\n")

#: 更深的 `###` 小标题：按层级它本来就比 `## 证明` 深，改前也不该截断（回归钉）。
WITH_LEVEL3_SUBHEADS = (
    "## 命题\n"
    "命题正文。\n"
    "\n"
    "## 证明\n"
    "第一步：分两种情形。\n"
    "\n"
    "### 情形一：g 有界\n"
    "由控制收敛直接得到。\n"
    "\n"
    "### 情形二：g 无界\n"
    "用截断逼近。\n"
    "\n"
    "## 依赖\n"
    "| 引用 | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号 |\n"
    "|---|---|---|---|\n"
)
LEVEL3_PROOF_BODY = ("第一步：分两种情形。\n"
                     "\n"
                     "### 情形一：g 有界\n"
                     "由控制收敛直接得到。\n"
                     "\n"
                     "### 情形二：g 无界\n"
                     "用截断逼近。\n")


def test_present_reads_only_the_proof_section() -> None:
    """present：拿到的是 `## 证明` 那一节的正文，不是别的块、也不是整份稿。"""
    reading = DS.proof_body_reading(WITH_PROOF)
    assert reading["state"] == DS.PROOF_PRESENT, reading
    assert reading["present"] is True
    assert reading["heading_line"] > 0
    assert reading["body"] == PROOF_BODY, reading["body"]
    assert reading["chars"] == len(PROOF_BODY.strip())
    assert DS.proof_body(WITH_PROOF) == PROOF_BODY
    # 只取那一节：命题正文 / 依赖段的表都不在返回值里。
    assert "命题正文" not in DS.proof_body(WITH_PROOF)
    assert "| 第一步用了它" not in DS.proof_body(WITH_PROOF)


def test_absent_says_absent_and_does_not_fall_back_to_another_block() -> None:
    """absent：明确说没有这一节，正文是空串。

    反真空：把回退加回去（缺节 ⇒ `## 依赖` 节正文，或整份全文）⇒ 这一条必红。
    判据写成两条：① 状态是 `absent`；② 正文里不许出现别的块的任何一行。
    """
    reading = DS.proof_body_reading(WITHOUT_PROOF)
    assert reading["state"] == DS.PROOF_ABSENT, reading
    assert reading["present"] is False
    assert reading["heading_line"] == 0
    assert reading["body"] == ""
    assert reading["chars"] == 0
    assert "没有" in str(reading["why"])
    # 严格口径：`proof_body` 一个字节都不许退。
    body = DS.proof_body(WITHOUT_PROOF)
    assert body == "", f"缺 `## 证明` 时不许回退；实际拿到 {len(body)} 字符：{body[:80]!r}"
    assert "命题正文" not in body
    assert "数值结果" not in body
    assert "| 第一步用了它" not in body
    # 依赖段本身仍读得出来（这一改动不碰 `## 依赖` 那一格）。
    assert DS.parse_dependency_section(WITHOUT_PROOF)["present"] is True


def test_absent_and_empty_section_stay_distinguishable() -> None:
    """有那一节但为空 ≠ 没有那一节：两种读数都在 `present` / `absent` 里分得开。"""
    empty = "## 命题\n命题\n\n## 证明\n\n## 依赖\n"
    reading = DS.proof_body_reading(empty)
    assert reading["state"] == DS.PROOF_PRESENT, reading
    assert reading["body"] == ""
    assert reading["chars"] == 0


def test_unreadable_file_says_unreadable_not_absent(tmp_path: pathlib.Path) -> None:
    """unreadable：文件在盘上、但读不出来 ⇒ 说"读不出"，不是"没有这一节"。"""
    target = tmp_path / "reports" / "f-proof-000000.md"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00\x00not-utf8")
    got = DS.read_proof_body(tmp_path, "reports/f-proof-000000.md")
    assert got["checked"] is False, got
    assert got["state"] == DS.PROOF_UNREADABLE, got
    assert got["state"] != DS.PROOF_ABSENT
    assert got["body"] == ""
    assert "读不出来" in str(got["why"])


def test_missing_file_is_unreadable_not_absent(tmp_path: pathlib.Path) -> None:
    """文件不在盘上也落 `unreadable`：没读到 ≠ 稿里没有这一节。"""
    got = DS.read_proof_body(tmp_path, "reports/f-proof-999999.md")
    assert got["state"] == DS.PROOF_UNREADABLE, got
    assert got["checked"] is False
    assert "没读到" in str(got["why"])


def test_read_proof_body_present_carries_the_whole_text_for_dependents(
        tmp_path: pathlib.Path) -> None:
    """读文件那一档：present 时同时给整份稿（依赖段 / 签块还要用）与那一节正文。"""
    target = tmp_path / "reports" / "f-proof-000000.md"
    target.parent.mkdir(parents=True)
    target.write_text(WITH_PROOF, encoding="utf-8")
    got = DS.read_proof_body(tmp_path, "reports/f-proof-000000.md")
    assert got["checked"] is True, got
    assert got["state"] == DS.PROOF_PRESENT, got
    assert got["text"] == WITH_PROOF
    assert got["body"] == PROOF_BODY
    assert got["path"] == "reports/f-proof-000000.md"


def test_absent_source_in_verbatim_reading_is_not_the_proof_section() -> None:
    """B 的 `verbatim_vs_source` 在来源稿缺节时如实报 absent，不拿别的块当"证明正文"。"""
    got = RS.verbatim_vs_source(
        proof_text="另一段与稿无关的正文", source_text=WITHOUT_PROOF, source="param")
    assert got["checked"] is True, got
    assert got["same"] is False
    assert got["source_state"] == DS.PROOF_ABSENT
    assert "没有" in str(got["why"])
    # "整份稿"那一档仍显式认（它不是"证明正文那一节"）。
    same_whole = RS.verbatim_vs_source(
        proof_text=WITHOUT_PROOF, source_text=WITHOUT_PROOF, source="param")
    assert same_whole["same"] is True
    assert same_whole["matched"] == "manuscript"


def test_proof_body_or_whole_is_explicit_and_flags_the_fallback() -> None:
    """确实需要"退而取全文"的地方只走这个另起的名字，且 `fell_back` 必须看得见。"""
    got = DS.proof_body_or_whole(WITHOUT_PROOF)
    assert got["fell_back"] is True, got
    assert got["state"] == DS.PROOF_ABSENT
    assert got["body"] == WITHOUT_PROOF
    same = DS.proof_body_or_whole(WITH_PROOF)
    assert same["fell_back"] is False, same
    assert same["state"] == DS.PROOF_PRESENT
    assert same["body"] == PROOF_BODY


def test_exhaustionreport_proof_body_of_has_the_same_strict_reading() -> None:
    """穷举档的换名口径与 `depsection` 同源：present 逐字一致、absent 空串。"""
    assert ER.proof_body_of(WITH_PROOF) == DS.proof_body(WITH_PROOF).strip("\n")
    assert ER.proof_body_of(WITH_PROOF) == PROOF_BODY.rstrip("\n")
    assert ER.proof_body_of(WITHOUT_PROOF) == ""


# ============================================================ 2026-11-10：按层级 / 按"是不是一节"切
def test_level_two_subheads_inside_a_proof_are_body_not_boundaries() -> None:
    """真机 DCT 彩排：`## 证明` 下用 `## 记号` / `## 第一步` 分小节 ⇒ 正文非空且逐字全取。

    这些标题与 `## 证明` 同级；只按层级判结束仍会截空。判据是"同级 ∧ 是手稿的
    一节"才算边界，所以它们留在正文里，`## 依赖` 照旧结束这一节。
    """
    reading = DS.proof_body_reading(WITH_LEVEL2_SUBHEADS)
    assert reading["state"] == DS.PROOF_PRESENT, reading
    assert reading["present"] is True
    assert reading["chars"] > 0, reading
    assert reading["body"] == LEVEL2_PROOF_BODY, reading["body"]
    assert DS.proof_body(WITH_LEVEL2_SUBHEADS) == LEVEL2_PROOF_BODY
    for line in ("## 记号与约定", "## 第一步：f 可积"):
        assert line in DS.proof_body(WITH_LEVEL2_SUBHEADS), line
    # 边界仍然只在 `## 依赖` 前：依赖段的表与标题一个字节都不进正文。
    body = DS.proof_body(WITH_LEVEL2_SUBHEADS)
    assert "## 依赖" not in body
    assert "| 第一步用了它" not in body
    # `## 命题` 那一节同样不被小标题截断（同一份切节口径）。
    assert DS.statement_body(WITH_LEVEL2_SUBHEADS) == "命题正文（这一行不是证明）。"


def test_level_three_subheads_inside_a_proof_are_body_not_boundaries() -> None:
    """`### ` 比 `## 证明` 深 ⇒ 节内内容；正控是 `## 依赖` 仍结束这一节。"""
    body = DS.proof_body(WITH_LEVEL3_SUBHEADS)
    assert body == LEVEL3_PROOF_BODY, body
    assert "### 情形一：g 有界" in body and "### 情形二：g 无界" in body
    assert "## 依赖" not in body


def test_the_known_dependency_section_still_ends_the_proof_section() -> None:
    """原来的行为不变：`## 证明` 之后接 `## 依赖` ⇒ 正文到 `## 依赖` 前为止。"""
    # 与上面两份夹具同一形状，但没有小标题：正文就是那两行，依赖段不进正文。
    assert DS.proof_body(WITH_PROOF) == PROOF_BODY
    assert "## 依赖" not in DS.proof_body(WITH_PROOF)
    assert DS.proof_body_reading(WITH_PROOF)["chars"] == len(PROOF_BODY.strip())


def test_a_higher_level_heading_always_ends_the_section() -> None:
    """更高级的标题一定是新的一节：`## 证明` 之后接 `# 附录`（无论叫什么名）。"""
    text = "## 证明\n证明正文。\n\n# 附录\n附录正文。\n"
    assert DS.proof_body(text) == "证明正文。\n"


def test_split_sections_shares_the_same_boundary_rule() -> None:
    """`proofregistry.split_sections` 是同一份口径：同级小标题不另起一节。

    它是第三处按 `##` 切块的地方（`section_hashes` / 重写只换 `## 证明` 都走它）：
    改前一份 DCT 形状的证明会被切成 `## 证明`（空）+ `## 记号` + `## 第一步` 三节。
    """
    _head, sections = PR.split_sections(WITH_LEVEL2_SUBHEADS)
    assert [name for name, _body in sections] == ["命题", "证明", "依赖"]
    proof = dict(sections)["证明"]
    assert "## 记号与约定" in proof and "## 第一步：f 可积" in proof
    assert set(PR.section_hashes(WITH_LEVEL2_SUBHEADS)) == {
        "## 命题", "## 证明", "## 依赖"}


def test_the_three_readers_share_one_section_table() -> None:
    """② `SECTION_TITLES` 是框架渲染节名的单一来源：三处读的是同一张表。

    钉三件事：
    1. 名单只有一处（`depsection.SECTION_TITLES`），节序是 命题/证明/依赖/数值结果；
    2. `manuscriptform` 的形状正则与渲染都从这张表取名字（没有第二份 `## 命题` /
       `## 证明` 字面量）；
    3. 同一份样稿在渲染 / 切节 / 形状闸三处得到同一组节名。
    """
    names = [title.lstrip("# ").strip() for title in DS.SECTION_TITLES]
    assert names == ["命题", "证明", "依赖", "数值结果"], names
    assert MF._DS is DS and PR._DS is DS, "两处引用的不是同一个 depsection 模块"
    assert MF._PROPOSITION_HEAD_RE.pattern == r"^##\s*" + re.escape(names[0])
    assert MF._PROOF_HEAD_RE.pattern == r"^##\s*" + re.escape(names[1])
    rendered = MF.render_proof_manuscript(
        family=MF.FAMILY_F, title="样稿", statement_id="000001",
        proposition="命题正文。", proof_text="## 记号与约定\n证明正文。",
        dependency_section=DS.render_dependency_section([]))
    for title in DS.SECTION_TITLES[:3]:
        assert f"\n{title}\n" in rendered, (title, rendered)
    _head, sections = PR.split_sections(rendered)
    assert [name for name, _body in sections] == names[:3], sections
    assert DS.proof_body(rendered).strip(), "渲染出来的证明正文是空串"
    assert MF.formal_shape_problem(rendered) == ("", "")


# ---------------------------------------------------------------- d 反真空
def _old_any_hash_truncates(line: str) -> int:
    """改前的口径：任何以 `#` 开头的行都算边界（所有标题同权）。"""
    return 1 if str(line or "").lstrip().startswith("#") else 0


def test_d_old_any_hash_rule_truncates_the_first_case(monkeypatch) -> None:
    """d 反真空：把切节打桩成"任何 `#` 都截断" ⇒ 第一条（二级小标题）必红。

    基线先证明不打桩时它是绿的；再只换掉"层级 + 是不是一节"这两格，`## 记号与约定`
    立刻变成边界、证明正文回到空串 —— 于是 `test_level_two_subheads_...` 的第一条
    断言会红。打桩不碰 `section_lines` 本身，判据仍在看那两格。
    """
    baseline = DS.proof_body(WITH_LEVEL2_SUBHEADS)
    assert baseline == LEVEL2_PROOF_BODY, baseline
    monkeypatch.setattr(DS, "heading_level", _old_any_hash_truncates)
    monkeypatch.setattr(DS, "is_section_heading", lambda line: True)
    assert DS.proof_body(WITH_LEVEL2_SUBHEADS) == "", (
        "把规则改回「任何 # 都截断」之后证明正文仍非空 ⇒ 判据没在看切节")
