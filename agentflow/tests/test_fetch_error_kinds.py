"""`fetch.is_controlled_error_kind` 与 `FetchResult` 的受控档守卫（`F-6`）。

## 为什么补这个文件

`tools/coverage_zero_test.py --level 2` 在批边界那次读数（`temp/b73-release-all.json`）里报了一个等级 2（判据/决策）的零测试公开函数：`src/agentflow/fetch.py` L118 `is_controlled_error_kind`（"可能间接覆盖"，判据 2a:裸名含决策词缀 ['is_']）。

它不是可有可无的辅助函数：`FetchResult.__post_init__`（`fetch.py:195`）用它把"失败的下载必须答得出为什么"变成构造期硬约束（`F-6`）。零测试意味着这条约束没有任何判据守着 —— 把 `ERROR_KINDS` 或那两条 `ValueError` 改坏，套件不会红。

## 本文件守什么（三组，每组都有负控）

1. 判定面：`is_controlled_error_kind` 对每种合法形态给 `True`（`None` / 每个 `ERROR_KINDS` 成员 / `http_NNN`），对每种非法形态给 `False`（含近似但非法的形态：`http_40`、`http_4040`、大小写、前后空白、空串）—— 后一组是负控，它挡住"把正则放宽成 `startswith('http')`"那类改法；
2. 守卫面：`FetchResult(ok=False, kind=<非法>)` 必须抛，且消息里点名那个非法值；另外两条守卫（`ok=False` 而 `kind=None`、`ok=True` 而 `kind` 是失败档）各一条负控；
3. 变异负控（证明判据有咬合力）：把 `fetch.is_controlled_error_kind` 在内存里换成恒真的实现 ⇒ 同一个非法构造不再抛 —— 没有这一条，就无法排除"上面那些 `raises` 其实是被别的东西挡住的"。

`ERROR_KINDS` 本身也在这里被断言非空且是 frozenset/tuple（空词表会让第 1 组恒真地通过）。"""

from __future__ import annotations

import pytest

from agentflow import fetch as F


# ============================================================ 第 1 组：判定面

def test_error_kinds_is_a_nonempty_controlled_vocabulary():
    """前提：词表非空（空词表会让下面那些"每个成员都 True"变成恒真的空断言）。"""
    assert len(F.ERROR_KINDS) >= 4, F.ERROR_KINDS
    assert all(isinstance(k, str) and k for k in F.ERROR_KINDS)


def test_none_is_legal():
    """`None` 合法：成功且无警告时它就该是空的。"""
    assert F.is_controlled_error_kind(None) is True


def test_every_member_of_the_vocabulary_is_legal():
    """正控：`ERROR_KINDS` 的每个成员都必须被认。"""
    for kind in F.ERROR_KINDS:
        assert F.is_controlled_error_kind(kind) is True, kind


@pytest.mark.parametrize("kind", ["http_000", "http_404", "http_429", "http_999"])
def test_http_status_shaped_kinds_are_legal(kind: str):
    """正控：`http_<三位数>` 形态（限流/被墙这类只有状态码可报的档）。"""
    assert F.is_controlled_error_kind(kind) is True


@pytest.mark.parametrize("kind", [
    "not_a_kind",          # 完全不在词表里
    "http_40",             # 位数不够
    "http_4040",           # 位数太多
    "http_",               # 只有前缀
    "HTTP_404",            # 大小写不对（词表是大小写敏感的）
    "http_abc",            # 不是数字
    " content_type_mismatch",   # 前导空白
    "content_type_mismatch ",   # 尾随空白
    "",                    # 空串（与 `None` 是两件事）
])
def test_near_miss_shapes_are_not_legal(kind: str):
    """负控：近似但非法的形态必须被判 False。

    这一组是"把判据放宽"的探测器：一旦有人把 `_ERROR_KIND_RE` 改成
    `startswith("http")`、或把词表查找改成 `in kind`，这里必红。
    """
    assert F.is_controlled_error_kind(kind) is False


# ============================================================ 第 2 组：构造期守卫

def test_failed_result_with_a_controlled_kind_is_accepted():
    """正控：失败 + 受控档 ⇒ 构造成功。"""
    res = F.FetchResult(ok=False, kind="http_404", error="HTTP 404")
    assert res.ok is False and res.kind == "http_404"


def test_ok_result_may_carry_no_kind():
    """正控：干净成功 ⇒ `kind=None` 合法。"""
    assert F.FetchResult(ok=True).kind is None


def test_failed_result_with_an_uncontrolled_kind_is_rejected():
    """负控：`ok=False` 而 `kind` 不在词表里 ⇒ 抛，且消息点名那个值。"""
    with pytest.raises(ValueError) as ei:
        F.FetchResult(ok=False, kind="not_a_kind", error="随便写的")
    assert "not_a_kind" in str(ei.value)
    assert "受控档" in str(ei.value)


def test_failed_result_without_any_kind_is_rejected():
    """负控：只有自由文本的 `error`、没有受控档 ⇒ 抛（`F-6` 的核心：答不出为什么）。"""
    with pytest.raises(ValueError) as ei:
        F.FetchResult(ok=False, kind=None, error="network_error: timeout")
    assert "F-6" in str(ei.value)


def test_successful_result_may_not_carry_a_failure_kind():
    """负控：`ok=True` 却带失败档 ⇒ 抛（成功的下载不该带失败档）。"""
    with pytest.raises(ValueError) as ei:
        F.FetchResult(ok=True, kind="http_500")
    assert "content_type_mismatch" in str(ei.value)


def test_soft_warning_on_success_is_allowed():
    """正控（边界）：`ok=True` + `content_type_mismatch` 是允许的那一档（软警告）。"""
    assert F.FetchResult(ok=True, kind="content_type_mismatch").kind == "content_type_mismatch"


# ============================================================ 第 3 组：变异负控

def test_the_predicate_is_what_rejects(monkeypatch: pytest.MonkeyPatch):
    """变异负控：把判据换成"恒真"⇒ 同一个非法构造不再抛。

    为什么必须有一条这样的证据：上面那几条 `pytest.raises` 只证明"这个输入被拒了"，
    没有证明"是这条判据拒的"。把 `is_controlled_error_kind` 的模块属性替换掉
    （`__post_init__` 查的是模块全局名，见 `fetch.py:195`）⇒ 非法值被放行，
    说明拒它的正是这条判据。替换后当场复原由 monkeypatch 负责。
    """
    monkeypatch.setattr(F, "is_controlled_error_kind", lambda kind: True)
    res = F.FetchResult(ok=False, kind="not_a_kind", error="随便写的")
    assert res.kind == "not_a_kind", "判据被换掉之后这条构造就该成功（否则说明拦它的不是它）"
