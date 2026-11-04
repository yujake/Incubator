# -*- coding: utf-8 -*-
"""判据：H 的手册必须写清 `own_errors` 是必填（与工具面 `required` 逐字一致）。

## 改前实测

`agent_skills.py` 的 H 手册写 `H.review_report(doc_id)`，只提了 `round_no` 是关键字，
没提 `own_errors`；而工具面（`tools/review_tools.py::review.report`）的
`required = ["doc_id", "own_errors"]`，`own_errors=None` 会被 G15 当场退回。
于是模型照手册写会以为"不传就是零错误" —— "没写"被读成"没犯错"。

## 判据（三条）

a. 手册那句同时含"必填"与"`[]` 显式零错误"（以及真实读数名）；
b. 反真空：删掉那句 ⇒ 检查函数点名变红（不是永远返回空）；
c. 与工具面 `required` 现比：读 registry 里 `review.report` 的 schema，
   `required` 里每一个名字都必须出现在手册里；schema 以后加必填项而这句没跟上 ⇒ 红。
"""
from __future__ import annotations

from agentflow import agent_skills as AS
from agentflow.tools import build_registry


def _h_manual_text() -> str:
    """H 的全部 skill 正文（真跑时进提示词的那一份）。"""
    return "\n\n".join(skill.body for skill in AS.CATALOG["H"])


def _review_report_spec():
    return build_registry().registry.get("review.report")


def _problems(text: str, required: tuple[str, ...]) -> list[str]:
    """手册里缺了什么（空列表 = 干净）。"""
    out: list[str] = []
    if "必填" not in text:
        out.append("没写「必填」：模型会以为不传等于零错误")
    if "`[]` 显式零错误" not in text:
        out.append("没写「`[]` 显式零错误」：零错误必须是一种显式声明，不是缺省")
    if "own_errors_registered=True" not in text:
        out.append("没给「已登记」这个读数（`own_errors_registered`）")
    for name in required:
        if name not in text:
            out.append(f"工具面必填 {name!r} 没进手册（required 与手册不一致）")
    return out


def test_manual_states_own_errors_is_required() -> None:
    """a + c：手册与工具面现读的 `required` 逐字一致，且写明零错误怎么交。"""
    spec = _review_report_spec()
    required = tuple(spec.params.get("required") or ())
    assert required == ("doc_id", "own_errors"), (
        f"工具面的 required 变了（{required}）：手册与这条判据要跟着核一遍")
    desc = str(spec.params["properties"]["own_errors"].get("description") or "")
    assert "必填" in desc, f"工具面自己没说必填：{desc!r}"

    bad = _problems(_h_manual_text(), required)
    assert not bad, "H 的手册没把 `own_errors` 的必填说清：\n  " + "\n  ".join(bad)


def test_the_manual_checker_is_not_vacuous() -> None:
    """b：删掉那句 ⇒ 必须点名；schema 多一个必填项 ⇒ 也要点名（现比，不是硬编码）。"""
    text = _h_manual_text()
    required = tuple(_review_report_spec().params.get("required") or ())

    start = text.index("`own_errors` **必填**")
    end = text.index("G15 的判据就是", start)
    cut = text[:start] + text[end:]
    assert cut != text, "夹具前提：手册里有那句「`own_errors` **必填**」"
    hit = _problems(cut, required)
    assert any("必填" in one for one in hit), hit
    assert any("显式零错误" in one for one in hit), hit

    # 现比：schema 若多一个必填项，检查函数必须点名（证明它读的是 required，不是常量）
    hit = _problems(text, required + ("reviewer_note",))
    assert any("reviewer_note" in one for one in hit), hit

    assert len(_problems("", required)) >= 3, _problems("", required)
