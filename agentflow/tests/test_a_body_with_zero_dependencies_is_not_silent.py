# -*- coding: utf-8 -*-
"""依赖面读数：有正文而依赖 0 行，必须看得见（缺陷 1a）。

## 现场（`temp/dep_probe/REPORT-dependency-surface.md` 第 2 条 / 第 5 条）

`depsection.deps_missing_reading` 在 `refs<=0` 时一律给 `not_applicable`，把底层
`secretary._deps_missing_reading` 对"有证明正文而零依赖"给的 `missing` 盖掉；
而那句 `why` 只说"没有引用任何在册命题"，不点出"这一份有 N 字正文、0 条依赖边"。
于是写 0 条与写 5 条在读数上同价（盘上 41 份手稿里 35 份是空表，一路静默）。

## 口径（三态词表一个字不改）

* 自足仍然放行：`state` 仍是 `not_applicable`（不判红、不拒收）；
* 但 `why` 必须点出三件事：这一份有 N 字正文、0 条依赖边、作者声明自足；
* "缺整节"与"自足"分开说：空表是声明，缺节是格式没交；
* 正文有 `stmt:` 引用而表 0 行 ⇒ 说不一致（`state` 仍是三态里的 `missing`，不判红），
  且 `why` 要点出"正文点了 N 条" —— 否则读的人分不清"真自足"与"该写没写"
  （业主 2026-11-05 追加裁定）。
"""
from __future__ import annotations

from agentflow import depsection as DS

PROOF_CHARS = 3000
HEAD = ("| 引用 | 命题号 | 用在哪一步 | 路径号 |\n"
        "|---|---|---|---|\n")


def _body(extra: str = "") -> str:
    text = "归纳：基例成立。\n" + ("这一步由前一步直接推出。" * (PROOF_CHARS // 14))
    return (extra + text) if extra else text


def _manuscript(*, dep_section: bool, body: str = "") -> str:
    text = "## 命题\n\n引理。\n\n" + "## 证明\n\n" + (body or _body()) + "\n"
    if dep_section:
        text += "\n## 依赖\n\n" + HEAD
    return text


def _reading(text: str) -> dict:
    body = DS.proof_body(text)
    refs = DS.stmt_refs(body)
    return DS.deps_missing_reading(
        proof_text=body, deps_written=0, derived_from=refs, refs=len(refs),
        section=DS.parse_dependency_section(text))


# ============================================================ a 自足：可见但放行
def test_a_a_body_with_an_empty_table_says_how_big_it_is_and_why_it_is_self_sufficient():
    """a：3000 字正文 + 空表 ⇒ 仍是 `not_applicable`，但 `why` 点出三个数。"""
    got = _reading(_manuscript(dep_section=True))
    assert got.get("state") == "not_applicable", got
    why = str(got.get("why") or "")
    assert f"{PROOF_CHARS}" in why or str(got.get("proof_chars")) in why, why
    assert "0 条依赖边" in why, why
    assert "声明自足" in why, why
    # 三态没有被折成判红：这一档仍然是"放行"的那一档。
    assert got.get("state") == "not_applicable"


# ============================================================ b 缺整节 ≠ 自足
def test_b_no_section_is_said_as_missing_section_not_as_self_sufficient():
    """b：没有 `## 依赖` 那一节 ⇒ `why` 说「缺节」，不能说成「声明自足」。"""
    got = _reading(_manuscript(dep_section=False))
    why = str(got.get("why") or "")
    assert "缺节" in why, why
    assert "声明自足" not in why, why


# ============================================================ c 说不一致（可达）
def test_c_a_stmt_reference_with_an_empty_table_is_an_inconsistency():
    """c：正文点了 2 条 `stmt:` 引用而表 0 行 ⇒ 说不一致，且 `why` 点出条数。"""
    got = _reading(_manuscript(dep_section=True,
                               body=_body("由 stmt:000001 与 stmt:000002 推出。\n")))
    assert got.get("state") == "missing", got
    why = str(got.get("why") or "")
    assert "说不一致" in why, why
    assert "2 条" in why, why
    assert "0 行" in why, why


# ============================================================ d 反真空
def test_d_the_sentence_is_what_makes_the_zero_visible():
    """d：a 的可见性挂在那句逐字读数上 —— 摘掉它，a 与这条一起红。

    同时钉住"它不许变成判红档"：这一档的 `state` 只能是 `not_applicable`
    （不是 `missing`），调用方据此仍放行。
    """
    got = _reading(_manuscript(dep_section=True))
    why = str(got.get("why") or "")
    assert ("这一份有" in why and "字正文" in why and "0 条依赖边" in why), why
    assert got.get("state") == "not_applicable", (
        f"自足的证明被读成 {got.get('state')!r} ⇒ 这一档变成判红档了：{got}")
