"""`G-34`：判据工具自己的盲区 —— "别名限定调用"必须被单独认出来。

这条缺陷的全部内容是两个分量必须可分辨：

- `_name_occurrences("G.gateway_main(...)", "gateway_main")` 现在是 0
  （`_name_pattern` 的左边界刻意排除 `.`）；
- `_qualified_occurrences(...)` 必须是 1。

差异本身不大，代价很大：发布门 `coverage` 的那两条假红（`modelgw.gateway_main`、
`formalgw.evidence_of` 被报成"零测试"）全部由它造成，而它们是当时唯一的 `fail`。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "coverage_zero_test.py"


def _load():
    spec = importlib.util.spec_from_file_location("_coverage_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load()


def test_a_qualified_call_is_invisible_to_the_direct_pattern() -> None:
    """本缺陷的核心差分：同一个调用，`direct` 判据说 0、`alias_direct` 判据说 1。"""
    blob = "assert G.gateway_main([]) == 0\n"
    assert C._name_occurrences(blob, "gateway_main") == 0, "前提：左边界排除 `.`，这不是意外"
    assert C._qualified_occurrences(blob, "gateway_main") == 1


def test_the_two_real_call_sites_are_recognized() -> None:
    """把真实的两处调用原样喂进来（它们的行号写在 `G-34` 的条目里）。"""
    cases = (
        ("assert G.gateway_main([]) == 0", "gateway_main"),
        ('ev = FG.evidence_of({"status": status})', "evidence_of"),
    )
    for blob, needle in cases:
        assert C._name_occurrences(blob, needle) == 0, blob
        assert C._qualified_occurrences(blob, needle) == 1, blob


def test_the_qualified_pattern_keeps_the_left_boundary() -> None:
    """负控：补这一档不许把左边界弄松（右边界本来就允许后跟 `_`）。

    如实记录（外部审查第 2 条，我实测复核过）：`_QUALIFIED_TMPL` 的右边界是
    `(?![0-9A-Za-z])`，而 `_` 不在其中 ⇒ `needle="parse"` 会命中 `x.parse_work(`。
    这是刻意的欠报方向（"算它有测试"），不是 bug；本文件早先那句"`parse` 不匹配
    `parse_work`"才是假的。所以这里只钉左边界那两件事。
    """
    # 左边界：不许命中"更长标识符的尾部"
    assert C._qualified_occurrences("x.subparse(1)", "parse") == 0
    assert C._qualified_occurrences("x._parse(1)", "parse") == 0
    # 右边界刻意允许后跟 `_`（欠报方向，外部审查第 2 条我复核过）：裸名 `parse_work`
    # 会让 needle=`parse` 命中。而 `x.parse_work(` 不命中 —— 那是左边界挡的，
    # 也正是一条调用要让两个分量分工的原因。
    assert C._name_occurrences("parse_work(1)", "parse") == 1
    assert C._name_occurrences("x.parse_work(1)", "parse") == 0
    assert C._qualified_occurrences("parse_work(1)", "parse") == 0
    # 多级限定（`mod.sub.fn(`）要认
    assert C._qualified_occurrences("mod.sub.fn(1)", "fn") == 1


def test_mark_tested_labels_a_qualified_hit_as_alias_direct(tmp_path: Path) -> None:
    """集成：小世界里 `m.fn()` 形态必须记成 `via:alias_direct`，不是 `via:direct`。

    分量必须分开记的理由就在这里：`direct` 是"测试里出现了这个独立标识符"，
    `alias_direct` 是"有人用某个前缀调用了它"（前缀是谁本判据不解析，得靠人核）。
    把两者混成一个布尔值，就等于把"真有测试"与"有个前缀像是它"当成同一件事。
    """
    (tmp_path / "src" / "agentflow").mkdir(parents=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "src" / "agentflow" / "m.py").write_text("def fn():\n    return 1\n", encoding="utf-8")
    (tmp_path / "tests" / "test_m.py").write_text(
        "import m\n\n\ndef test_x():\n    assert m.fn() == 1\n", encoding="utf-8"
    )
    funcs, _excluded = C.collect_src(tmp_path, frozenset())
    C.mark_tested(funcs, tmp_path)
    hits = [f for f in funcs if f.bare == "fn"]
    assert hits, [f.bare for f in funcs]
    labels = " ".join(hits[0].tested_by)
    assert hits[0].tested is True, labels
    assert "via:alias_direct" in labels, labels
    assert "via:direct" not in labels, labels


def test_the_two_needles_are_independent_components() -> None:
    """两个分量必须互不覆盖：谁坏了另一条都看不出来，所以两条都要单独断言。

    这也是为什么它们不能用同一个布尔值表示（本脚本的 `tested_by` 就是为此分成
    `via:direct` / `via:alias_direct` / `via:test_name` 三档的）。
    """
    blob = "assert G.gateway_main([]) == 0\n"
    assert C._name_occurrences(blob, "gateway_main") == 0
    assert C._qualified_occurrences(blob, "gateway_main") == 1
    # 反向：裸名调用不许被算成 alias_direct
    bare = "gateway_main([])\n"
    assert C._name_occurrences(bare, "gateway_main") == 1
    assert C._qualified_occurrences(bare, "gateway_main") == 0
