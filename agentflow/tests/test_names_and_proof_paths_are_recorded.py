# -*- coding: utf-8 -*-
"""S1r-schema：别名与"第几条证明路径"进台账（业主 2026-10-09 两条裁定）。

> 「别名按乙，毕竟定理也可能有别名」
> 「B走乙。由于B这边出了多依赖写法，C的分析需要做适配」

设计见 `draft/97` §14.4d（别名是 `Statement` 的通用一格，不是概念私产）
与 §12.1（`path_group`：同一 `used_by` + 同一组 = 一条路径（组内 AND），
不同组 = 可选路径（组间 OR））。

## 判据（正控 2 / 负控 3 / 反真空 2）

- 正控①：定理也能有别名（不只是概念）；别名随行存得下来、读得回来；
- 正控②：`path_group` 缺省是 1 ⇒ 历史行与"只有一条路径"的写法语义一个字不变；
- 负控①：别名与自身 `label` 相同 ⇒ 拒（那是"没有别名"）；
- 负控②：空别名 ⇒ 拒（空别名会让查重按空白命中一切）；
- 负控③：`path_group=0` ⇒ 拒；被依赖端给两个 ⇒ 拒；非 `dangling` 却一个都不给 ⇒ 拒；
- 反真空①：`ARRAY_FIELD_KINDS['statements']['aliases'] == 'seq'`（形状与顺序纪律登记在册，
  不是靠某处注释）；
- 反真空②：`dependencies` 的 `source_stmt_id` 接 4 位号（"定理用到定理/概念"这条边有归宿）。
"""
from __future__ import annotations

import pytest

from agentflow import schema as S

TS = "2026-10-09T00:00:00+08:00"


def _stmt(**kw) -> S.Statement:
    base = dict(stmt_id="0000", origin="own_result", kind="theorem", label="Moore bound",
                statement_text="短版", statement_full="若假设 A 成立，则结论 B 成立",
                source_lit_id="0000", quote_verified=True, quote_reason="逐字比对通过",
                evidence_kind="cross_check", status="active", created_at=TS)
    base.update(kw)
    return S.Statement(**base)


def _dep(**kw) -> S.Dependency:
    base = dict(dep_id="0000", used_by="stmt:0007", kind="theorem", label="Moore 界",
                status="closed", source_stmt_id="0003", created_at=TS)
    base.update(kw)
    return S.Dependency(**base)


# ------------------------------------------------------------------ 正控


def test_a_theorem_may_carry_other_names():
    """正控①：定理也能有别名（业主："毕竟定理也可能有别名"）—— 不是概念的私产。"""
    row = _stmt(aliases=["M(k, g)", "Moore bound M(k, g)"])
    row.validate()
    assert row.to_dict()["aliases"] == ["M(k, g)", "Moore bound M(k, g)"]
    # 定义/引理/概念同样能用这一格
    for kind in ("concept", "definition", "lemma"):
        other = _stmt(stmt_id="0001", kind=kind, label="别的名字",
                      aliases=[f"{kind} 的别名"])
        other.validate()
        assert other.aliases == [f"{kind} 的别名"], (kind, other.aliases)


def test_a_dependency_defaults_to_the_first_path_group():
    """正控②：`path_group` 缺省 1 ⇒ 历史行与"只有一条路径"的写法语义不变。"""
    row = _dep()
    row.validate()
    assert row.path_group == 1, row.path_group
    # 两组（业主说的二维列表：外层 = 路径，内层 = 一条路径上的步骤）
    path1 = _dep(dep_id="0001", path_group=1, source_stmt_id="0003")
    path2 = _dep(dep_id="0002", path_group=2, source_experiment_id="0004",
                 source_stmt_id=None)
    path1.validate()
    path2.validate()
    assert (path1.path_group, path2.path_group) == (1, 2)


# ------------------------------------------------------------------ 负控


def test_an_alias_equal_to_the_label_is_refused():
    """负控①：别名与自身 `label` 相同 ⇒ 拒（归一化之后相同也算）。"""
    with pytest.raises(ValueError) as err:
        _stmt(aliases=["moore bound"]).validate()
    assert "没有别名" in str(err.value), err.value


def test_an_empty_alias_is_refused():
    """负控②：空别名 ⇒ 拒（它会让查重按空白命中一切，比漏登记更坏）。"""
    with pytest.raises(ValueError) as err:
        _stmt(aliases=["   "]).validate()
    assert "空串" in str(err.value), err.value


def test_a_bad_path_group_or_source_end_is_refused():
    """负控③：组号必须正整数；被依赖端四选一；只有 `dangling` 才允许"来源还没定"。"""
    with pytest.raises(ValueError) as e1:
        _dep(path_group=0).validate()
    assert "path_group" in str(e1.value), e1.value
    with pytest.raises(ValueError) as e2:
        _dep(source_lit_id="0009").validate()          # 两个被依赖端
    assert "最多给一个" in str(e2.value), e2.value
    with pytest.raises(ValueError) as e3:
        _dep(source_stmt_id=None).validate()           # closed 却一个都不给
    # 这一档由既有的那条更早的规则拦下（"closed 必须指向一个已入库的来源"）——
    # 报文不同但判据同向；本条判的是"一个都不给"这件事必须有规则拦住
    assert "必须指向一个已入库的来源" in str(e3.value), e3.value
    # 反例的另一半（口径，不是缺陷）：`external_unavailable` 天然没有 `source_*`
    # （"引了但拿不到"就是它），所以新规则不要求"非 dangling 就必须给一端"
    ok = _dep(status="external_unavailable", status_reason="那本书我们库里没有，也拿不到",
              source_stmt_id=None)
    ok.validate()
    assert ok.status == "external_unavailable" and not ok.source_stmt_id


# ------------------------------------------------------------------ 反真空


def test_the_alias_shape_is_registered_in_the_shared_table():
    """反真空①：别名的形状/顺序纪律登记在 `ARRAY_FIELD_KINDS` 里（不是靠注释）。"""
    assert S.ARRAY_FIELD_KINDS["statements"]["aliases"] == "seq", \
        S.ARRAY_FIELD_KINDS["statements"]
    assert S.ARRAY_FIELD_KINDS["statements"]["derived_from"] == "set"


def test_a_dependency_may_point_at_another_statement():
    """反真空②：`source_stmt_id` 接 4 位号 ——"定理用到定理/概念"这条边有归宿。

    现场依据（`draft/97` E2）：`Dependency` 的字段表里此前没有这一格，
    而它的注释早就写着"`used_by` → 本表的 `stmt_id` 是自然延伸"。
    """
    row = _dep(source_stmt_id="0003")
    row.validate()
    assert row.source_stmt_id == "0003"
    with pytest.raises(ValueError):
        _dep(source_stmt_id="3").validate()             # 不是 4 位号
