"""判据：同一个 DOI 在 `doi.org` 的四种写法下必须只拿到一个主键（2026-10-22）。

## 为什么这条要单独存在

`dedup.py` 里 `_DOI_URL_PREFIX_RE` 的注释（第 41 行）写着要吃下"带不带 `dx.` / 带不带 `www.`
的组合"，而原实现只吃 `dx.` ⇒ `https://www.doi.org/10.1000/x` 与 `10.1000/x` 拿到两个主键，
同一篇文献在库里变成两行。这不是"格式不统一"，是判重键分家：之后所有"这篇读过没有"的
回答都会错，而没有任何地方会报。

## 四正一负

正的四种写法都要归到同一个键；负控是一条不相关的串不许被误剥（防"正则放宽到把正文吃进去"）。
"""

from __future__ import annotations

import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import dedup as D  # noqa: E402

_WANT = "10.1000/abc"
_FORMS = (
    "10.1000/abc",
    "https://doi.org/10.1000/abc",
    "https://dx.doi.org/10.1000/abc",
    "https://www.doi.org/10.1000/abc",
    "www.doi.org/10.1000/abc",
    "http://dx.doi.org/10.1000/abc",
)


def test_every_spelling_of_the_doi_org_prefix_collapses_to_one_key() -> None:
    got = {D.normalize_doi(form) for form in _FORMS}
    assert got == {_WANT}, f"同一篇文献拿到了多个主键：{sorted(got)}"


def test_an_unrelated_string_is_not_stripped() -> None:
    """负控：正则放宽不许把"正文里恰好写到 doi 字样"的串吃成空。"""
    assert D.normalize_doi("see https://www.doi.org/10.1000/abc for details") != ""
    assert "10.1000/abc" in D.normalize_doi("see https://www.doi.org/10.1000/abc for details")
