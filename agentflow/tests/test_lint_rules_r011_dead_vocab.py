"""`G-26` 第二步 / `P-22`+`P-23`：`R011` 的两栏判据（正控 + 负控 + 反真空）。

## 级别不是"固定 info"了（这一版的口径）

- `unclaimed`（无产出且无人认领）非空 ⇒ `error`：它没有任何理由留在词表里，
  三选一（补产出 / 登记为预留 / 删值）之前它就是一条静默的谎；
- `reserved`（无产出但已登记为预留）非空 ⇒ 只报 `info`：那是人的口径裁定，
  用红灯逼一个未经裁决的改法，正是 `P-22`/`P-23` 明确否掉的形态；
- 「两条"没查成"退路（读不到普查工具 / 普查 `checked=False`）⇒ `warning`」
  （`H-7`）：它们与"查过了、干净"「不许同形」—— `info` 在发布门上恰好是
  看不见的那一档（`item_linter` 只看 error），于是"探测器坏了"与"词表很干净"
  会印成同一个样子。`warning` 在 `--strict` 档与 `item_linter` 的严格档里都可见；
- 第三条"没查成"（反向：漏词表）是本版「明确未实现」的能力，今天结构上不可能变绿，
  所以它保持 `info` —— 把它升成 `warning` 就是造一条永远红的灯；
- 两栏分开打印，`reserved` 不是"通过"。

真仓库上 `unclaimed` 今天是 0 且两条退路都没触发 ⇒ 级别集合是 `{"info"}`
（这条断言保留，但它不再等价于"R011 永远不报 error/warning"：
负控给出了 `unclaimed` 非空与"没查成"的形态）。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("_lint_rules_for_r011", ROOT / "scripts" / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load()


def test_r011_is_registered() -> None:
    """规则必须在册 —— 否则"接上了"只是一句注释。"""
    assert any("R011" in str(entry) for entry in L.RULES), "R011 没有注册到 RULES"


def test_r011_reports_the_registered_dead_values_in_the_reserved_column() -> None:
    """正控：登记册点名的那些值必须出现在栏一 reserved，且不在栏二 unclaimed。

    它不许被改成"什么都不报"（那是真空通过），也不许混进 unclaimed（那会把
    已登记为预留的值说成无人认领）。

    ## `E-10`（裁定 (b)，2026-09-27）把 `FINDING_KINDS` 那一条换掉了

    这一批原本点名的两条里，`FINDING_KINDS` 那条（`quote` + `_mismatch`）
    已经随词表值一起删除 —— 它此前是"给一条做不到的承诺做预留"。
    所以正控现在点名的是仍然存在的那几条；删掉的那条另有一条"必须彻底消失"
    的断言（见本文件末尾的 `test_r011_has_no_trace_of_the_deleted_finding_kind`）。
    """
    got = L.rule_R011_dead_vocab(ROOT)
    reserved = " ".join(f.message for f in got if "[栏一 reserved]" in f.message)
    unclaimed = " ".join(f.message for f in got if "[栏二 unclaimed]" in f.message)
    for name in ("reproduction_report", "proposition", "prior_art"):
        assert name in reserved, f"{name} 不在 reserved 栏：{reserved}"
        assert name not in unclaimed, f"{name} 被挪进了 unclaimed 栏：{unclaimed}"


def test_r011_has_no_trace_of_the_deleted_finding_kind() -> None:
    """`E-10` 裁定 (b) 的机器判据：那个被删的取值不许在 R011 的任何一栏里出现。

    为什么这条必需：删掉一个词表取值之后，登记表里残留的那一条会被打进
    栏一附（"登记为预留、而本次普查看不见它是死取值"）—— 那在输出上与
    "同形不同义"完全同形，会长期挂在报告里当背景噪音。本条的判据是
    "登记表残留会当场变红"，所以它守的是"删干净"这件事本身。
    """
    needle = "quote" + "_mismatch"
    blob = " ".join(f.message for f in L.rule_R011_dead_vocab(ROOT))
    assert needle not in blob, f"R011 的输出里仍有 {needle} 的痕迹：{blob[:300]}"


def test_r011_prints_both_columns_and_the_counters_separately() -> None:
    """两栏都必须出现（含空栏），且计数是分开给的 —— 合并等于静默豁免。"""
    got = L.rule_R011_dead_vocab(ROOT)
    blob = " ".join(f.message for f in got)
    assert "reserved" in blob and "unclaimed" in blob
    assert "两栏计数" in blob and "不许用合计代替分栏" in blob
    # 栏一附必须出现（登记了、而机器今天看不见它是死取值的那几条）
    assert any("[栏一附]" in f.message for f in got), "registered_not_dead 那几条没有打印"


def test_r011_always_declares_the_unimplemented_direction() -> None:
    """负控（"没查"不许读成"没问题"）：未实现的"漏词表"方向必须作为一条 info 出现。"""
    got = L.rule_R011_dead_vocab(ROOT)
    assert any("漏词表" in f.message and "未实现" in f.message for f in got), [
        f.message[:60] for f in got
    ]


def test_r011_on_the_real_tree_is_info_only_because_unclaimed_is_empty() -> None:
    """真仓库上：级别集合是 `{"info"}`，因为 `unclaimed` 今天是空的、普查也跑成了。

    这条不再断言"R011 永远是 info 级"（那会与 `P-23` 的口径冲突）：
    它断言的是"今天没有无人认领的死取值"这个事实。
    """
    got = L.rule_R011_dead_vocab(ROOT)
    assert not [f for f in got if "[栏二 unclaimed]" in f.message], "真仓库上出现了无人认领的死取值"
    assert {f.level for f in got} == {"info"}


def test_negative_control_an_unreadable_census_tool_is_a_warning_not_info(
    monkeypatch, tmp_path: Path
) -> None:
    """负控（`H-7`）：「读不到」 `tools/vocab_census.py` ⇒ 必须是 `warning`，不许是 `info`。

    `info` 在发布门上等于看不见（`item_linter` 只看 error），于是"判据自己没跑成"
    与"词表很干净"在报告里同形 —— 那正是本项目最忌的折叠。这里用
    `_load_vocab_census` 返回 `None` 来注入"读不到"，并且「先证明注入生效」：
    断言返回的是一条 Finding（不是空列表），再断言它的级别。
    """
    monkeypatch.setattr(L, "_load_vocab_census", lambda: None)
    got = L.rule_R011_dead_vocab(ROOT)
    assert len(got) == 1, f"注入后应当只有那一条'没查成'：{[f.message for f in got]}"
    assert got[0].level == "warning", (
        f"读不到普查工具居然报了 {got[0].level!r} —— `H-7` 之前是 info，"
        "而 info 在发布报告里看不见"
    )
    assert "没查成" in got[0].message
    # 反向对照：如果这条被改回 info，上面那条断言就红（这就是负控的判别力）
    assert got[0].level != "info"


def test_negative_control_a_not_checked_census_is_a_warning_not_info(
    monkeypatch, tmp_path: Path
) -> None:
    """负控（`H-7`）：普查 `checked=False` ⇒ 必须报 `warning`（不是 `info`、也不是 error）。

    这条注入的是"仪器没跑成"（反真空下限不满足），它与"被检对象有缺陷"是两件事，
    所以既不能折叠成 info，也不该升成 error；但它必须「在严格档里可见」。
    注入生效的证据：返回的 Finding 里带着普查给出的 `reason` 原文。
    """
    fake = type("FakeCensus", (), {"census": staticmethod(lambda root: {
        "checked": False,
        "reason": "（桩）产出点位数低于反真空下限",
    })})
    monkeypatch.setattr(L, "_load_vocab_census", lambda: fake)
    got = L.rule_R011_dead_vocab(ROOT)
    assert len(got) == 1, [f.message for f in got]
    assert got[0].level == "warning", got[0].level
    assert "（桩）产出点位数低于反真空下限" in got[0].message, (
        "没查成必须带上普查给出的理由，否则读的人不知道仪器坏在哪"
    )


def test_prefix_identity_is_a_finding_not_a_warning() -> None:
    """边界：`registered_not_dead` 是 `info`（登记了、而普查看不见它是死取值）。

    这一条与 `H-7` 划清界限：`H-7` 改的是「"没查成"」那两条退路，
    不是把每一条 `info` 都升成 `warning` —— 详见本文件开头的级别表。
    """
    got = L.rule_R011_dead_vocab(ROOT)
    prefix = [f for f in got if "[栏一附]" in f.message]
    assert prefix, "registered_not_dead 那几条没有打印"
    assert {f.level for f in prefix} == {"info"}, [f.level for f in prefix]


def test_negative_control_unclaimed_values_are_an_error(monkeypatch) -> None:
    """负控①：`unclaimed` 非空 ⇒ 必须报 `error`（且两栏分开打印）。

    用一份桩普查结果驱动规则，避免为了造这个前提去改真实的登记表
    （改真表会让"负控"变成一次真的口径变更）。
     """
    fake = type("FakeCensus", (), {"census": staticmethod(lambda root: {
        "checked": True,
        "vocabs": {"V": 2},
        "producer_lines": 99999,
        "dead": {"V": ["dead_one", "dead_two"]},
        "reserved": {"V": ["dead_one"]},
        "unclaimed": {"V": ["dead_two"]},
        "registered_not_dead": {},
        "dead_total": 2,
        "reserved_total": 1,
        "unclaimed_total": 1,
        "registered_not_dead_total": 0,
        "reserved_reasons": {"V.dead_one": "（桩）理由"},
        "known_gap": "（桩）已知缺口",
    })})
    monkeypatch.setattr(L, "_load_vocab_census", lambda: fake)
    got = L.rule_R011_dead_vocab(ROOT)
    errors = [f for f in got if f.level == "error"]
    assert len(errors) == 1 and "dead_two" in errors[0].message, [f.message for f in got]
    assert "[栏二 unclaimed]" in errors[0].message
    # 已登记的那一个仍然只报 info（两栏的级别不同）
    reserved = [f for f in got if "[栏一 reserved]" in f.message]
    assert reserved and {f.level for f in reserved} == {"info"}
    assert "（桩）理由" in reserved[0].message, "预留必须带上登记表里写的理由"


def test_negative_control_a_broken_identity_is_an_error(monkeypatch) -> None:
    """负控②：`reserved + unclaimed != dead` ⇒ 报 error（判据自身漏了值）。"""
    fake = type("FakeCensus", (), {"census": staticmethod(lambda root: {
        "checked": True,
        "vocabs": {"V": 3},
        "producer_lines": 99999,
        "dead": {"V": ["a", "b", "c"]},
        "reserved": {"V": ["a"]},
        "unclaimed": {"V": ["b"]},
        "registered_not_dead": {},
        "dead_total": 3,
        "reserved_total": 1,
        "unclaimed_total": 1,
        "registered_not_dead_total": 0,
        "reserved_reasons": {"V.a": "（桩）理由"},
        "known_gap": "（桩）已知缺口",
    })})
    monkeypatch.setattr(L, "_load_vocab_census", lambda: fake)
    got = L.rule_R011_dead_vocab(ROOT)
    assert any(
        f.level == "error" and "对不上死取值总数" in f.message for f in got
    ), [f.message for f in got]


def test_a_broken_scanner_says_not_checked_instead_of_staying_silent(tmp_path: Path) -> None:
    """反真空：扫描器失效（读不到源码树）⇒ 必须出一条"没查成"，而不是什么都不报。

    "什么都不报"会被读成"没有死取值" —— 那正是这条规则最危险的失败形态。
    """
    got = L.rule_R011_dead_vocab(tmp_path)
    assert got, "扫描器失效时 R011 彻底沉默了"
    assert any("没查成" in f.message or "读不到" in f.message for f in got), [f.message for f in got]
