# -*- coding: utf-8 -*-
"""FC-27 禁 AI 区门禁的测试。

覆盖：
- 判据①：`.noai-paths` 与 `AGENTS.md` 标记区块逐条一致（`check_manifest_consistency()` 空差异）
- 判据①负控：在内存字符串上改掉 `AGENTS.md` 的一条 ⇒ 必须报出差异（不真改文件）
- 判据②负控：命中禁改区的改动 ⇒ `requires_human` + `required_approvals == 2`
- 防误伤：不命中的改动 ⇒ `clean` + `required_approvals == 0`
- 三态：清单读不到 ⇒ `unknown`（断言 不是 `clean`）
- 退出码：`clean=0` / `requires_human=1` / `unknown=2`
- 解析负控：缺 `category` 的行 ⇒ 抛且消息带行号
- 七类齐全：清单覆盖 FC-27 平移后的七类（按 `category` 计数）
- 非 git 仓库下 `--git` ⇒ `unknown`（退出码 2），不是 `clean`
- hash 台账（批准记录）：`.noai-approvals.json` 的三态纪律
  （台账读不到/解析不了/结构不对 ⇒ `unknown`，不是 `clean`）、
  理由码区分 `unregistered`（从没登记）与 `stale`（登记过但批准的那一版不是现在这一版，
  消息里必须有两个 hash）、`1 < 2` 证明门槛真的是 2、台账不能批准自己、
  `--baseline` 绝不写 `reviewers`（登记 ≠ 批准）、`--approve` 在 hash 不一致时
  拒绝写入并以退出码 2 结束
- 归属的依据：`authored`（结论）与 `authored_basis`（结论有多强：`attested` / `inferred`）
  必须成对出现，缺依据 ⇒ 结构不合规 ⇒ `unknown`（不给默认值：
  "我没写依据"与"依据是推断"不是同一种东西）；`inferred` 的条目在人读的理由行里
  必须标注"推断，非独立证据"
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

#: 把仓库根注入 sys.path（`scripts` 是顶层包 `scripts`；conftest.py 只注入了 `src/`）。
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts import noai_gate as G  # noqa: E402

#: 真实清单与真实 AGENTS.md（判据①的对象就是它们）。
REAL_MANIFEST = _ROOT / G.MANIFEST_NAME
REAL_AGENTS = _ROOT / G.AGENTS_NAME

#: 只是登记路径、当前刻意不存在的条目（发布脚本的另一个落位）。
#: 这是"先登记路径"的落地形态：一旦有人真的建了它，它自动落入清单而不是绕过门。
#: 该文件一旦出现，`test_manifest_globs_point_at_real_files` 会要求把它从这里摘掉。
DELIBERATELY_ABSENT = {
    "src/agentflow/release_check.py",
}


# --------------------------------------------------------------------------- 判据①：一致


def test_manifest_and_agents_are_consistent() -> None:
    """判据①：两处清单逐条一致（空差异）。"""
    diffs = G.check_manifest_consistency()
    assert diffs == [], f"`.noai-paths` 与 `AGENTS.md` 的清单不一致：{diffs}"


def test_consistency_compares_reason_too() -> None:
    """一致性不是"条目数一样"：理由也必须一致（只在一边写理由 = 另一边没理由）。"""
    text = REAL_AGENTS.read_text(encoding="utf-8")
    mutated = text.replace("检索口径一旦偏移", "检索口径偏移了", 1)
    assert mutated != text, "负控前提失败：没能在 AGENTS.md 文本里改出一个差异"

    diffs = G.check_manifest_consistency(agents_md=mutated)
    assert diffs, "改了一条理由却没有报出差异 —— 一致性检查漏掉了理由"
    assert any("第 1 条" in d for d in diffs), f"差异里没有指出是哪一条：{diffs}"


def test_consistency_negative_control_mutated_entry() -> None:
    """判据①的负控：在内存字符串上删掉 `AGENTS.md` 的一条 ⇒ 报出差异。

    只改内存里的字符串，不碰磁盘上的 `AGENTS.md`。
    """
    text = REAL_AGENTS.read_text(encoding="utf-8")
    target = "src/agentflow/extract.py"
    assert target in text, "负控前提失败：AGENTS.md 里找不到要删的那一条"

    mutated = "\n".join(ln for ln in text.splitlines() if target not in ln)
    diffs = G.check_manifest_consistency(agents_md=mutated)
    assert diffs, "删掉一条后两处清单不可能还一致，但检查器说一致"
    assert any("条目数不一致" in d or "只存在于" in d for d in diffs), diffs

    # 反向确认：原文件没被动过（这条断言是"不真改文件"的机器证据）。
    assert REAL_AGENTS.read_text(encoding="utf-8") == text
    assert G.check_manifest_consistency() == []


def test_consistency_negative_control_changed_category() -> None:
    """负控之二：把一条的类别换成另一个合法类别 ⇒ 报差异。

    换成合法类别而不是乱码，是为了让这条用例只检验"一致性比对"，而不被
    "未知类别"这条解析规则抢先拦截 —— 两条规则要各自有自己的负控。
    """
    text = REAL_AGENTS.read_text(encoding="utf-8")
    lines = text.splitlines()
    hit = [
        i
        for i, ln in enumerate(lines)
        if "EVAL_REQUIRED_FIELDS" in ln and "eval-criteria" in ln
    ]
    assert hit, "负控前提失败：AGENTS.md 里找不到 eval-criteria 那一条"
    i = hit[0]
    lines[i] = lines[i].replace("eval-criteria", "solver-core")
    mutated = "\n".join(lines)
    assert mutated != text

    diffs = G.check_manifest_consistency(agents_md=mutated)
    assert diffs, "类别被改成另一个合法类别却没报差异 —— 一致性检查漏掉了类别"
    assert REAL_AGENTS.read_text(encoding="utf-8") == text, "不该真改 AGENTS.md"


# --------------------------------------------------------------------------- 判据②：命中


@pytest.mark.parametrize(
    "path, category",
    [
        ("src/agentflow/dedup.py", "solver-core"),
        ("src/agentflow/providers.py", "solver-core"),
        ("src/agentflow/extract.py", "solver-core"),
        ("src/agentflow/tools/verify_tools.py", "prover-bridge"),
        ("src/agentflow/schema.py", "schema-migration"),
        ("src/agentflow/store.py", "schema-migration"),
        ("pyproject.toml", "release-deploy"),
        ("src/agentflow/tools/__init__.py", "auth-audit"),
        ("src/agentflow/tools/base.py", "auth-audit"),
        ("src/agentflow/verify.py", "auth-audit"),
        ("src/agentflow/interactions.py", "auth-audit"),
    ],
)
def test_hit_requires_two_approvals(path: str, category: str) -> None:
    """判据②：命中禁改区 ⇒ `requires_human` 且 `required_approvals == 2`。"""
    result = G.check_paths([path])
    assert result.verdict == "requires_human", result.explanation
    assert result.required_approvals == G.REQUIRED_APPROVALS_ON_HIT == 2
    assert category in {v["category"] for v in result.violations}
    assert all(v["reason"].strip() for v in result.violations), "命中条目必须带理由"


def test_hit_from_absolute_windows_path() -> None:
    """绝对路径（含盘符/反斜杠）也要命中 —— 否则是静默假阴性。"""
    result = G.check_paths([str(REAL_MANIFEST.parent / "src" / "agentflow" / "dedup.py")])
    assert result.verdict == "requires_human", result.explanation
    assert result.required_approvals == 2


def test_clean_path_requires_no_approval() -> None:
    """防误伤：不命中的改动 ⇒ `clean` 且批准数 0。"""
    for path in ("docs/notes.md", "docs/x.md", "node_modules/x", "tests/test_noai_gate.py"):
        result = G.check_paths([path])
        assert result.verdict == "clean", f"{path} 被误判为 {result.verdict}"
        assert result.required_approvals == 0
        assert result.violations == []


def test_mixed_changes_hit_wins() -> None:
    """一批改动里只要有一条命中，整批就得走人工（不能"多数是干净的"就放行）。"""
    result = G.check_paths(["docs/notes.md", "src/agentflow/store.py", "README.md"])
    assert result.verdict == "requires_human"
    assert result.required_approvals == 2
    assert {v["path"] for v in result.violations} == {"src/agentflow/store.py"}


def test_empty_change_set_is_clean() -> None:
    """空改动集 = 查过了、没有命中 ⇒ clean（与"没给改动集"的 unknown 区分开）。"""
    result = G.check_paths([])
    assert result.verdict == "clean"
    assert result.required_approvals == 0


# --------------------------------------------------------------------------- 三态


def test_missing_manifest_is_unknown_not_clean(tmp_path: Path) -> None:
    """三态纪律：清单读不到 ⇒ `unknown`，绝不是 `clean`。"""
    result = G.check_paths(["src/agentflow/dedup.py"], manifest=tmp_path / "nope" / G.MANIFEST_NAME)
    assert result.verdict == "unknown"
    assert result.verdict != "clean"
    assert result.required_approvals == 0
    assert result.manifest_issues, "unknown 必须说明为什么会没查成"
    assert "没有检查" in result.explanation or "读不到" in result.explanation


def test_broken_manifest_is_unknown_not_clean(tmp_path: Path) -> None:
    """清单解析失败也必须是 unknown：解析不了 = 没查成。"""
    bad = tmp_path / G.MANIFEST_NAME
    bad.write_text("[category: solver-core] 一、算法\nsrc/a.py  [category: typo-cat]  理由\n", encoding="utf-8")
    result = G.check_paths(["src/agentflow/dedup.py"], manifest=bad)
    assert result.verdict == "unknown"
    assert result.verdict != "clean"


def test_unknown_verdict_explanation_says_not_checked() -> None:
    """`unknown` 的说明必须显式说"本次没有检查"，不能只留一个空结论。"""
    result = G.check_paths(["src/agentflow/dedup.py"], manifest=Path("no/such/manifest"))
    assert "没有检查" in result.explanation
    assert result.verdict == "unknown"


def test_empty_rule_sequence_is_unknown() -> None:
    """传进来一个空 Rule 序列 ⇒ unknown（空清单等于没有门，不能当 clean）。"""
    result = G.check_paths(["src/agentflow/dedup.py"], manifest=[])
    assert result.verdict == "unknown"


# --------------------------------------------------------------------------- 退出码


def test_exit_code_clean() -> None:
    assert G.main(["--quiet", "--paths", "docs/notes.md"]) == 0


def test_exit_code_requires_human() -> None:
    assert G.main(["--quiet", "--paths", "src/agentflow/dedup.py"]) == 1


def test_exit_code_unknown_on_missing_manifest(tmp_path: Path) -> None:
    code = G.main(["--quiet", "--paths", "docs/notes.md", "--manifest", str(tmp_path / "absent")])
    assert code == 2


def test_exit_code_unknown_on_no_input() -> None:
    """没给改动集 ⇒ 没有检查 ⇒ 2（不是"没问题"的 0）。"""
    assert G.main(["--quiet"]) == 2


def test_exit_code_unknown_on_ambiguous_input() -> None:
    """`--paths` 与 `--git` 同时给 ⇒ 无法判断检查了哪些路径 ⇒ 2。"""
    assert G.main(["--quiet", "--paths", "docs/notes.md", "--git"]) == 2


def test_exit_codes_are_distinct_and_match_verdict() -> None:
    """三个退出码必须互不相同 —— 否则"unknown"会被 CI 读成"clean"。"""
    assert G.GateResult(verdict="clean").exit_code == 0
    assert G.GateResult(verdict="requires_human").exit_code == 1
    assert G.GateResult(verdict="unknown").exit_code == 2
    codes = {G.GateResult(verdict=v).exit_code for v in ("clean", "requires_human", "unknown")}
    assert codes == {0, 1, 2}


def test_check_consistency_cli_exit_codes() -> None:
    """一致性检查也是门：一致 ⇒ 0；不一致 ⇒ 2。"""
    assert G.main(["--quiet", "--check-consistency"]) == 0

    text = REAL_AGENTS.read_text(encoding="utf-8")
    mutated = "\n".join(ln for ln in text.splitlines() if "src/agentflow/extract.py" not in ln)
    broken = REAL_AGENTS.parent / "_agents_broken_for_test.md"
    broken.write_text(mutated, encoding="utf-8")
    try:
        code = G.main(["--quiet", "--check-consistency", "--agents-md", str(broken)])
        assert code == 2
    finally:
        broken.unlink(missing_ok=True)


# --------------------------------------------------------------------------- 解析负控


@pytest.mark.parametrize(
    "line, hint",
    [
        # 缺 category 标记
        ("src/agentflow/dedup.py  理由随便是啥", "[category:"),
        # 缺理由
        ("src/agentflow/dedup.py  [category: solver-core]", "缺少理由"),
        # 未知类别
        ("src/agentflow/dedup.py  [category: 不存在的类别]  理由", "未知类别"),
    ],
)
def test_parse_negative_control_names_line_number(tmp_path: Path, line: str, hint: str) -> None:
    """解析负控：坏行 ⇒ 抛错，且消息带行号（没有行号的报错等于没报错）。"""
    head = "[category: solver-core] 一、数值求解器的核心算法\n"
    body = f"src/agentflow/providers.py  [category: solver-core]  合法的一条\n{line}\n"
    p = tmp_path / G.MANIFEST_NAME
    p.write_text(head + body, encoding="utf-8")

    with pytest.raises(G.NoaiError) as ei:
        G.load_manifest(p)
    msg = str(ei.value)
    assert hint in msg, f"报错信息没点出问题类型 {hint!r}：{msg}"
    # 行号按 1 起算：第 1 行分组头、第 2 行合法条目、第 3 行是这条坏行。
    assert "第 3 行" in msg, f"报错信息没有行号（期望第 3 行）：{msg}"
    assert ei.value.line_no == 3


def test_parse_negative_control_entry_before_any_section(tmp_path: Path) -> None:
    """条目出现在任何分组之前 ⇒ 抛错（分组头不可省略）。"""
    p = tmp_path / G.MANIFEST_NAME
    p.write_text("src/a.py  [category: solver-core]  理由\n", encoding="utf-8")
    with pytest.raises(G.NoaiError) as ei:
        G.load_manifest(p)
    assert "分组" in str(ei.value)
    assert ei.value.line_no == 1


def test_parse_negative_control_category_contradicts_section(tmp_path: Path) -> None:
    """条目的 category 与所属分组不一致 ⇒ 抛错（FC-03：类别只有一处声明）。"""
    p = tmp_path / G.MANIFEST_NAME
    p.write_text(
        "[category: solver-core] 一、算法\nsrc/a.py  [category: auth-audit]  理由\n",
        encoding="utf-8",
    )
    with pytest.raises(G.NoaiError) as ei:
        G.load_manifest(p)
    assert "不一致" in str(ei.value)
    assert ei.value.line_no == 2


def test_parse_empty_manifest_is_error(tmp_path: Path) -> None:
    """空清单 ⇒ 抛错（"空清单等于没有门"，绝不能当 clean）。"""
    p = tmp_path / G.MANIFEST_NAME
    p.write_text("# 只有注释\n\n", encoding="utf-8")
    with pytest.raises(G.NoaiError):
        G.load_manifest(p)


def test_unknown_line_is_not_silently_skipped(tmp_path: Path) -> None:
    """看不懂的行不许静默跳过 —— 跳过一行就是放过一个禁改区。"""
    p = tmp_path / G.MANIFEST_NAME
    p.write_text(
        "[category: solver-core] 一、算法\nsrc/a.py  [category: solver-core]  理由\n这不是任何合法格式\n",
        encoding="utf-8",
    )
    with pytest.raises(G.NoaiError) as ei:
        G.load_manifest(p)
    assert ei.value.line_no == 3


def test_agents_block_requires_exactly_one_block() -> None:
    """标记区块必须恰好一个：两个区块时"该信哪一份"没有答案。"""
    text = REAL_AGENTS.read_text(encoding="utf-8")
    doubled = text + "\n" + G.BLOCK_BEGIN + "\n" + G.BLOCK_END + "\n"
    with pytest.raises(G.NoaiError) as ei:
        G.parse_agents_block(doubled)
    assert "恰好一个" in str(ei.value)


def test_agents_block_missing_markers() -> None:
    with pytest.raises(G.NoaiError):
        G.parse_agents_block("# 啥都没有\n")


# --------------------------------------------------------------------------- 七类齐全


def test_manifest_covers_all_seven_categories() -> None:
    """七类齐全：FC-27 判据③的七类都必须至少有一条（按 `category` 计数）。"""
    rules = G.load_manifest()
    counts = {c: 0 for c in G.CATEGORY_ORDER}
    for r in rules:
        counts[r.category] += 1
    missing = [c for c, n in counts.items() if n == 0]
    assert not missing, f"缺少类别：{missing}"
    assert len(counts) == 7, f"类别数必须是 7（FC-27 的七类），实际 {len(counts)}：{sorted(counts)}"
    assert set(counts) == set(G.CATEGORY_TITLES)


def test_agents_block_covers_all_seven_categories() -> None:
    rules = G.parse_agents_block()
    got = {r.category for r in rules}
    assert got == set(G.CATEGORY_ORDER), f"AGENTS.md 清单的类别不齐：{sorted(got)}"


def test_every_category_is_in_manifest_docstring_order() -> None:
    """清单里的分组头顺序 = `CATEGORY_ORDER`（顺序本身携带信息，FC-05）。"""
    text = REAL_MANIFEST.read_text(encoding="utf-8")
    heads = re.findall(r"^\[category:\s*([a-z\-]+)\]", text, flags=re.MULTILINE)
    assert heads == list(G.CATEGORY_ORDER), f"分组头顺序/内容与 CATEGORY_ORDER 不符：{heads}"


def test_manifest_globs_point_at_real_files() -> None:
    """每条 glob（除 `src/agentflow/release_check.py` 这条刻意预登记外）都必须指向真实存在的文件。

    理由：写错的 glob 不会报错，它只会永远不命中 —— 那是一个静默的假阴性。
    """
    for rule in G.load_manifest():
        if rule.glob in DELIBERATELY_ABSENT:
            assert not (REAL_MANIFEST.parent / rule.glob).is_file(), (
                f"{rule.glob} 已经存在了 —— 那么它不该再留在『刻意预登记』名单里，"
                "本条用例的豁免要摘掉（否则它永远不被检查）"
            )
            continue
        assert (REAL_MANIFEST.parent / rule.glob).is_file(), f"{rule.glob} 在仓库里不存在"


def test_manifest_globs_are_all_hit_by_themselves() -> None:
    """自洽性：每条 glob 本身必须命中它自己（否则 glob 的形状和匹配器不一致）。"""
    for rule in G.load_manifest():
        result = G.check_paths([rule.glob], manifest=[rule])
        assert result.verdict == "requires_human", f"{rule.glob} 没能命中它自己"


def test_required_approvals_constant_is_two() -> None:
    """FC-27 判据②写死为 2 —— 不是可配置项（可配置的门槛等于没有门槛）。"""
    assert G.REQUIRED_APPROVALS_ON_HIT == 2


# --------------------------------------------------------------------------- 理由里的符号必须真实存在


def test_python_manifest_referenced_symbols_exist() -> None:
    """理由里用反引号写出的符号名，必须真的存在于对应的源文件里。

    为什么需要这条：清单的"理由"是给人读的，写错一个函数名不会报错 ——
    它只会把人指向一段不存在的代码，而禁改区仍然"看起来被登记了"。
    这比行号更强：行号漂了它不响（行号本来就易失），符号没了它必响。

    同时它给清单加了一道真实性约束：一条 glob 不能靠"理由里随便写点什么"来通过。

    只对 `.py` 条目做符号检查：`pyproject.toml` 里没有函数名；
    发布脚本（`release_check.py` 的两种落位）是并行子任务正在写的文件，
    本用例不替它背书 —— 它们由"存在性/预登记"用例单独覆盖。
    """
    root = REAL_MANIFEST.parent
    checked = 0
    for rule in G.load_manifest():
        target = root / rule.glob
        if not target.is_file() or target.suffix != ".py":
            continue
        if rule.category == "release-deploy":
            continue
        checked += 1
        text = target.read_text(encoding="utf-8")
        if not text.strip():
            # 本仓库有并行子任务在原子写这些文件，存在"读到正在被替换的空文件"的
            # 瞬时窗口。空文件不是符号消失，跳过一个瞬间不算放过一个禁改区
            # （禁改区的判定只依赖 glob，与文件内容无关）。
            continue

        # 理由里提到的文件名必须就是这条 glob 自己（防止抄错行的理由）。
        for fname in re.findall(r"`([A-Za-z_][\w.\-]*\.py)`", rule.reason):
            assert fname == target.name, (
                f"{rule.glob} 的理由里提到 {fname}，但它不是本条目指向的文件 —— "
                "理由与条目对不上"
            )

        # 首要符号（理由里第一个包裹完整标识符的反引号项）必须在文件里出现。
        symbols = re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", rule.reason)
        assert symbols, f"{rule.glob} 的理由里没有写出任何符号名：{rule.reason!r}"
        head = symbols[0]
        assert head in text, (
            f"{rule.glob} 的理由里写的第一处符号 `{head}` 在该文件里找不到 —— "
            "清单指向了一段不存在的代码"
        )
    assert checked >= 12, f"实际只检查了 {checked} 条 .py 条目，清单可能被改瘦了"


def test_manifest_symbol_pins_are_the_intended_ones() -> None:
    """把关键条目的符号逐条钉死，防止"理由里换成另一个存在的符号"就蒙混过去。

    键是 `(glob, category)` 而不是单独的 glob：`dedup.py` / `providers.py`
    在两类里各有一条（刻意重复，见 `.noai-paths` 顶部说明），
    单用 glob 做键会让后一条把前一条覆盖掉。
    """
    rules = {(r.glob, r.category): r for r in G.load_manifest()}
    expected = {
        ("src/agentflow/dedup.py", "solver-core"): "decide_relation",
        ("src/agentflow/dedup.py", "provenance-dedup"): "normalize_doi",
        ("src/agentflow/providers.py", "solver-core"): "_plan_mode",
        ("src/agentflow/providers.py", "provenance-dedup"): "normalize_doi",
        ("src/agentflow/extract.py", "solver-core"): "extract_text",
        ("src/agentflow/tools/verify_tools.py", "prover-bridge"): "detect_verifier",
        ("src/agentflow/quoteverify.py", "prover-bridge"): "check_quote",
        ("src/agentflow/schema.py", "schema-migration"): "SCHEMA_VERSION",
        ("src/agentflow/schema.py", "eval-criteria"): "EVAL_REQUIRED_FIELDS",
        ("src/agentflow/store.py", "schema-migration"): "LOCK_ORDER",
        ("src/agentflow/tools/__init__.py", "auth-audit"): "ROLES",
        ("src/agentflow/tools/base.py", "auth-audit"): "for_role",
        ("src/agentflow/verify.py", "auth-audit"): "verify_all",
        ("src/agentflow/interactions.py", "auth-audit"): "check_conflict",
    }
    for key, symbol in expected.items():
        assert key in rules, f"清单里没有 {key}"
        assert f"`{symbol}`" in rules[key].reason, (
            f"{key[0]}[{key[1]}] 的理由必须点到符号 `{symbol}`，实际是：{rules[key].reason!r}"
        )


# --------------------------------------------------------------------------- 非 git 仓库


def _make_non_git_dir(tmp_path: Path) -> Path:
    """造一个保证不在任何 git 仓库里的目录。

    单靠 `tmp_path` 不够：如果临时目录本身在一个 git 仓库下（例如系统把 TMPDIR
    指到某个被版本控制的目录），`git rev-parse` 会成功，用例前提就不成立了。
    所以逐级向上确认没有任何 `.git`。
    """
    d = tmp_path / "not-a-repo"
    d.mkdir(parents=True, exist_ok=True)
    for cand in (d, *d.parents):
        assert not (cand / ".git").exists(), f"前提失败：{cand} 在 git 仓库里"
    return d


def test_git_returns_unknown_outside_git_repo(tmp_path: Path) -> None:
    """非 git 仓库 ⇒ `--git` 报 `unknown`，不是 `clean`。"""
    d = _make_non_git_dir(tmp_path)
    (d / G.MANIFEST_NAME).write_text(
        "[category: solver-core] 一、算法\nsrc/a.py  [category: solver-core]  理由\n", encoding="utf-8"
    )
    code = G.main(["--quiet", "--git", "--root", str(d)])
    assert code == 2, "非 git 仓库下 --git 必须是 unknown（2），不能是 clean（0）"


def test_git_helper_reports_reason_not_empty() -> None:
    """取不到改动集时，辅助函数必须给出人能看懂的原因，而不是空字符串。"""
    import subprocess

    proc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(REAL_MANIFEST.parent),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        pytest.skip("当前仓库是 git 仓库，此用例（非 git 行为）不适用")

    paths, reason = G.git_changed_paths(REAL_MANIFEST.parent)
    assert paths is None
    assert reason.strip(), "原因不能为空 —— 空原因等于让下游自己猜"


def test_git_flag_verdict_is_unknown_not_clean() -> None:
    """直接断言 verdict（不只是退出码）：`unknown` 与 `clean` 不是同一件事。"""
    result = G.check_paths(["src/agentflow/dedup.py"], manifest=Path("no/such/manifest"))
    assert result.verdict == "unknown"
    assert result.verdict != "clean"
    assert result.exit_code == 2


# --------------------------------------------------------------------------- hash 台账（批准记录）
#
# 这一节的每条用例都对着一个具体的失败形态：三态纪律（unknown ≠ clean）、
# 理由码必须可区分、门槛真的是 2、台账自指禁止、登记与批准不许合并成一个动作。


#: 造小世界用的分组中文名（真实清单里的分组头一行也不能少）。
_GROUP_TITLES = {
    "solver-core": "一、算法",
    "auth-audit": "七、权限与审计",
    "provenance-dedup": "三、去重键",
}


def _write_manifest(root: Path, entries: list[tuple[str, str]]) -> Path:
    """写一份最小的合法清单：`[(glob, category), …]`。"""
    lines: list[str] = []
    section = ""
    for glob, cat in entries:
        if cat != section:
            lines.append(f"[category: {cat}] {_GROUP_TITLES[cat]}")
            section = cat
        lines.append(f"{glob}  [category: {cat}]  测试用理由")
    p = root / G.MANIFEST_NAME
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _make_sandbox(
    tmp_path: Path,
    rel: str = "src/a.py",
    body: str = "x = 1\n",
    extra: tuple[tuple[str, str], ...] = (),
) -> tuple[Path, Path, str]:
    """造一个小世界：`<root>/<rel>` 存在且被清单登记。返回 `(root, manifest, rel)`。"""
    root = tmp_path / "repo"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    manifest = _write_manifest(root, [(rel, "solver-core"), *extra])
    return root, manifest, rel


def _entry(rel: str, sha: str, reviewers: list[dict] | None = None, **kw) -> dict:
    e = {
        "path": rel,
        "glob": rel,
        "category": "solver-core",
        "sha256": sha,
        "authored": "ai-agent",
        # `authored` 是结论，`authored_basis` 是"这个结论有多强"。
        # 这里显式给出：缺了它就是结构不合规（有一条专门的负控用例）。
        "authored_basis": "inferred",
        "change_note": "测试用说明",
        "changed_this_session": True,
        "reviewers": list(reviewers or []),
    }
    e.update(kw)
    return e


def _reviewer(name: str) -> dict:
    return {
        "name": name,
        "at": "2026-09-24T00:00:00+08:00",
        "scope": "逐行走查（全文）",
        "note": "测试用",
        "verdict": "通过",
    }


def _write_ledger(path: Path, entries: list[dict], *, version: int = G.LEDGER_VERSION) -> Path:
    path.write_text(
        json.dumps(
            {
                "ledger_version": version,
                "generated_at": "2026-09-24T00:00:00+08:00",
                "entries": entries,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _approvals(result: G.GateResult) -> dict[str, dict]:
    return {a["path"]: a for a in result.approvals}


# ---- 三态纪律：读不到 / 解析不了 / 结构不对 ⇒ unknown(2)，不是 clean


def test_approvals_missing_ledger_is_unknown_not_clean(tmp_path: Path) -> None:
    """命中禁改区但台账文件不存在 ⇒ `unknown`(2)，不是 `clean`。

    这是本机制最容易写错的一条：把"台账没有记录"读成"没有未批准的改动"。
    `unknown` 与 `clean` 折叠是本项目反复踩过的坑（"没查成"读成"没问题"）。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    result = G.check_approvals(
        [rel], manifest=manifest, root=root, ledger_path=root / "nope" / G.LEDGER_NAME
    )
    assert result.verdict == "unknown", result.explanation
    assert result.verdict != "clean"
    assert result.exit_code == 2
    assert result.manifest_issues, "unknown 必须说明为什么没查成"


def test_approvals_broken_json_is_unknown_not_clean(tmp_path: Path) -> None:
    """台账不是合法 JSON ⇒ `unknown`(2)。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    broken = root / G.LEDGER_NAME
    broken.write_text("{ 这不是 JSON", encoding="utf-8")
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=broken)
    assert result.verdict == "unknown"
    assert result.verdict != "clean"
    assert result.exit_code == 2


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(["不是对象"], id="顶层是数组"),
        pytest.param({"ledger_version": G.LEDGER_VERSION}, id="缺 entries"),
        pytest.param({"ledger_version": G.LEDGER_VERSION, "entries": {"a": 1}}, id="entries 不是数组"),
        pytest.param({"ledger_version": 999, "entries": []}, id="版本不认识"),
        pytest.param(
            {"ledger_version": G.LEDGER_VERSION, "entries": [{"path": "src/a.py"}]},
            id="条目缺 sha256",
        ),
        pytest.param(
            {"ledger_version": G.LEDGER_VERSION,
             "entries": [{"path": "src/a.py", "sha256": "0" * 64, "reviewers": "甲"}]},
            id="reviewers 不是数组",
        ),
        pytest.param(
            {"ledger_version": G.LEDGER_VERSION,
             "entries": [_entry("src/a.py", "0" * 64), _entry("src/a.py", "1" * 64)]},
            id="同一路径两条",
        ),
    ],
)
def test_approvals_bad_structure_is_unknown_not_clean(
    tmp_path: Path, payload: object
) -> None:
    """台账结构不合规 ⇒ `unknown`(2)：结构读不懂就不能按"没有批准记录"处理。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    bad = root / G.LEDGER_NAME
    bad.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=bad)
    assert result.verdict == "unknown", f"{payload!r} ⇒ {result.verdict}"
    assert result.verdict != "clean"
    assert result.exit_code == 2


def test_approvals_unreadable_hit_file_is_unknown(tmp_path: Path) -> None:
    """命中路径内容读不到（文件被删/变成目录）⇒ `unknown`(2)：拿不到 hash 就是没查成。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    (root / rel).unlink()
    ledger = _write_ledger(root / G.LEDGER_NAME, [_entry(rel, "0" * 64, [_reviewer("甲"), _reviewer("乙")])])
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=ledger)
    assert result.verdict == "unknown", result.explanation
    assert result.exit_code == 2
    assert _approvals(result)[rel]["approval_reason"] == G.REASON_HASH_UNAVAILABLE


# ---- 命中之后的四条判定（理由码必须能区分）


def test_approvals_unregistered_is_unapproved_with_own_reason(tmp_path: Path) -> None:
    """命中路径在台账里没有条目 ⇒ `requires_human`(1)，理由码 `unregistered`。

    它必须与 `stale` 分开：前者是"从没登记"（动作：`--baseline`），
    后者是"登记过、但批准的不是这一版"（动作：确认版本后重新走查）。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    ledger = _write_ledger(root / G.LEDGER_NAME, [])
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=ledger)
    assert result.verdict == "requires_human"
    assert result.exit_code == 1
    assert result.required_approvals == 2
    got = _approvals(result)[rel]
    assert got["approval_reason"] == G.REASON_UNREGISTERED
    assert "从没登记" in got["detail"]


def test_approvals_stale_hash_is_unapproved_and_shows_both_hashes(tmp_path: Path) -> None:
    """stale：台账记的那一版 ≠ 盘上这一版 ⇒ `requires_human`(1)，且两个 hash 都要出现。

    这是本机制存在的理由（git 只知道"文件变了"，不知道"变的不是被批准的那一版"），
    所以消息里必须能看出是哪两版。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    real = G.sha256_file(root / rel)
    fake = "a" * 64
    assert real != fake
    ledger = _write_ledger(root / G.LEDGER_NAME, [_entry(rel, fake, [_reviewer("甲"), _reviewer("乙")])])
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=ledger)
    assert result.verdict == "requires_human"
    assert result.exit_code == 1
    got = _approvals(result)[rel]
    assert got["approval_reason"] == G.REASON_STALE
    assert fake[:12] in got["detail"], f"消息里必须有台账那一版：{got['detail']}"
    assert real[:12] in got["detail"], f"消息里必须有盘上那一版：{got['detail']}"
    # 两个 hash 也必须能从 CLI 文本输出里看到（人是在终端上读它的）。
    assert fake[:12] in result.explanation or fake[:12] in got["detail"]


def test_approvals_one_reviewer_is_not_enough(tmp_path: Path) -> None:
    """hash 一致但只有 1 名 reviewer ⇒ `requires_human`(1)：证明"2"真的是 2。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    sha = G.sha256_file(root / rel)
    ledger = _write_ledger(root / G.LEDGER_NAME, [_entry(rel, sha, [_reviewer("甲")])])
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=ledger)
    assert result.verdict == "requires_human"
    assert result.exit_code == 1
    assert result.required_approvals == G.REQUIRED_APPROVALS_ON_HIT == 2
    got = _approvals(result)[rel]
    assert got["approval_reason"] == G.REASON_FEW_REVIEWERS
    assert "1/2" in got["detail"], got["detail"]


def test_approvals_two_distinct_reviewers_is_clean_and_says_so(tmp_path: Path) -> None:
    """hash 一致且 2 名不同 reviewer ⇒ `clean`(0)，且 explanation 必须写明来源是台账。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    sha = G.sha256_file(root / rel)
    ledger = _write_ledger(
        root / G.LEDGER_NAME, [_entry(rel, sha, [_reviewer("甲"), _reviewer("乙")])]
    )
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=ledger)
    assert result.verdict == "clean", result.explanation
    assert result.exit_code == 0
    assert result.required_approvals == 0
    assert "台账" in result.explanation, "clean 必须说明结论来自台账"
    assert "不是靠 git" in result.explanation, "clean 必须说明这不是 git 给的结论"
    assert result.ledger, "clean 也要给出台账位置（结论的来源要可追）"


def test_approvals_same_reviewer_twice_is_still_not_enough(tmp_path: Path) -> None:
    """同一个人签两次不是 2 名 reviewer：批准数按不同姓名计。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    sha = G.sha256_file(root / rel)
    ledger = _write_ledger(
        root / G.LEDGER_NAME,
        [_entry(rel, sha, [_reviewer("甲"), _reviewer("甲")])],
    )
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=ledger)
    assert result.verdict == "requires_human", "同一姓名两条签名被当成了 2 名 reviewer"
    got = _approvals(result)[rel]
    assert got["approval_reason"] == G.REASON_FEW_REVIEWERS
    assert got["distinct_reviewers"] == 1
    assert len(got["reviewers"]) == 2, "重复签名要照实保留（它是事实）"


# ---- 台账自指禁止


def test_ledger_never_approves_itself(tmp_path: Path) -> None:
    """台账不能批准自己：命中集里出现台账本身 ⇒ 永远 `unapproved`。

    这条堵的是"AI 把自己的改动写进台账并声称已批准"。
    为了证明它优先于 hash 与人数判定，这里刻意给台账自己造一条
    "2 名 reviewer"的条目（hash 故意不对）—— 结论仍必须是自指，不是 `stale`。
    """
    root, manifest, rel = _make_sandbox(
        tmp_path, extra=((G.LEDGER_NAME, "auth-audit"),)
    )
    ledger = _write_ledger(
        root / G.LEDGER_NAME,
        [_entry(G.LEDGER_NAME, "0" * 64, [_reviewer("甲"), _reviewer("乙")],
                category="auth-audit")],
    )
    result = G.check_approvals(
        [G.LEDGER_NAME], manifest=manifest, root=root, ledger_path=ledger
    )
    assert result.verdict == "requires_human"
    assert result.exit_code == 1
    got = _approvals(result)[G.LEDGER_NAME]
    assert got["approval_reason"] == G.REASON_SELF
    assert "台账不能批准自己" in got["detail"]
    assert result.verdict != "clean"


def test_approve_refuses_to_sign_the_ledger_itself(tmp_path: Path) -> None:
    """`--approve` 也不许给台账自己签字（退出码 2，不写入）。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    ledger = _write_ledger(root / G.LEDGER_NAME, [_entry(rel, G.sha256_file(root / rel))])
    before = Path(ledger).read_bytes()
    code = G.main(
        ["--approve", G.LEDGER_NAME, "--reviewer", "甲", "--scope", "全文", "--root", str(root)]
    )
    assert code == 2
    assert Path(ledger).read_bytes() == before, "拒绝之后台账不许被改动"


# ---- 登记 ≠ 批准（--baseline 绝不写 reviewers）


def test_baseline_never_writes_reviewers(tmp_path: Path) -> None:
    """`--baseline` 生成的条目 `reviewers == []`：登记 ≠ 批准，两个动作不许合并。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    code = G.main(["--baseline", "--paths", rel, "--root", str(root), "--note", "初版登记"])
    assert code == 0
    ledger = G.load_ledger(root / G.LEDGER_NAME)
    entry = ledger.entry_for(rel)
    assert entry is not None
    assert list(entry.reviewers) == [], "`--baseline` 顺手写了 reviewers —— 那就是 AI 自己给自己发批准"
    assert entry.sha256 == G.sha256_file(root / rel)
    # 登记完仍然是"未批准"（这正是"登记 ≠ 批准"的行为证据）。
    result = G.check_approvals([rel], manifest=root / G.MANIFEST_NAME, root=root)
    assert result.verdict == "requires_human"
    assert _approvals(result)[rel]["approval_reason"] == G.REASON_FEW_REVIEWERS


def test_baseline_without_reviewers_keeps_cli_exit_zero(tmp_path: Path, capsys) -> None:
    """`--baseline` 的输出必须自己说清"登记 ≠ 批准"（人读的那一行也要有这个信息）。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    assert G.main(["--baseline", "--paths", rel, "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "登记 ≠ 批准" in out, out


def test_baseline_refresh_clears_reviewers_when_content_changed(tmp_path: Path) -> None:
    """批准之后又被悄悄改了：内容一变，旧签名必须清空（它们批准的是旧那一版）。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    assert G.main(["--baseline", "--paths", rel, "--root", str(root), "--note", "初版"]) == 0
    assert G.main(["--approve", rel, "--reviewer", "甲", "--scope", "全文", "--root", str(root)]) == 0
    assert G.main(["--approve", rel, "--reviewer", "乙", "--scope", "全文", "--root", str(root)]) == 0
    assert G.check_approvals([rel], manifest=manifest, root=root).verdict == "clean"

    (root / rel).write_text("x = 2  # 悄悄改了\n", encoding="utf-8")
    assert G.main(["--baseline", "--paths", rel, "--root", str(root), "--note", "第二版"]) == 0
    entry = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel)
    assert entry is not None
    assert list(entry.reviewers) == [], "内容变了却把旧签名留在了新 hash 上"
    assert G.check_approvals([rel], manifest=manifest, root=root).verdict == "requires_human"


def test_baseline_unchanged_content_keeps_reviewers(tmp_path: Path) -> None:
    """内容没变时重跑 `--baseline` 不清空签名：无改动的重跑不该毁掉人工记录。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    assert G.main(["--baseline", "--paths", rel, "--root", str(root)]) == 0
    assert G.main(["--approve", rel, "--reviewer", "甲", "--scope", "全文", "--root", str(root)]) == 0
    assert G.main(["--approve", rel, "--reviewer", "乙", "--scope", "全文", "--root", str(root)]) == 0
    assert G.main(["--baseline", "--paths", rel, "--root", str(root)]) == 0
    entry = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel)
    assert entry is not None
    assert len(entry.reviewers) == 2
    assert G.check_approvals([rel], manifest=manifest, root=root).verdict == "clean"


# ---- --approve 的 hash 前置断言


def test_approve_refuses_when_hash_differs(tmp_path: Path) -> None:
    """`--approve` 发现台账 hash 与磁盘不一致 ⇒ 拒绝写入并以退出码 2 结束。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    ledger = _write_ledger(root / G.LEDGER_NAME, [_entry(rel, "0" * 64)])
    before = Path(ledger).read_bytes()
    code = G.main(
        ["--approve", rel, "--reviewer", "张三", "--scope", "全文逐行走查", "--root", str(root)]
    )
    assert code == 2, "hash 不一致却签字成功 —— 批准了一个不在盘上的版本"
    assert Path(ledger).read_bytes() == before, "拒绝之后台账不许被改动"


def test_approve_requires_registered_entry(tmp_path: Path) -> None:
    """没登记就签字 ⇒ 拒绝（退出码 2）：批准不能替代登记。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    _write_ledger(root / G.LEDGER_NAME, [])
    code = G.main(["--approve", rel, "--reviewer", "甲", "--scope", "全文", "--root", str(root)])
    assert code == 2


def test_approve_requires_scope_and_reviewer(tmp_path: Path) -> None:
    """空 `--scope` / 空 `--reviewer` ⇒ 拒绝：匿名签字与"写看过了"都不算走查。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, G.sha256_file(root / rel))])
    assert G.main(["--approve", rel, "--reviewer", "甲", "--scope", "  ", "--root", str(root)]) == 2
    assert G.main(["--approve", rel, "--reviewer", " ", "--scope", "全文", "--root", str(root)]) == 2


def test_approve_records_note_scope_and_verdict(tmp_path: Path) -> None:
    """`--approve` 的记录必须含 `{name, at, scope, note, verdict}`（登记表 §3.1 的字段）。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, G.sha256_file(root / rel))])
    code = G.main([
        "--approve", rel,
        "--reviewer", "张三",
        "--scope", "extract_text + _finish_pdf（全文）",
        "--note", "判据未被放宽",
        "--root", str(root),
    ])
    assert code == 0
    entry = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel)
    assert entry is not None
    rec = entry.reviewers[0].to_dict()
    assert set(rec) == {"name", "at", "scope", "note", "verdict"}
    assert rec["name"] == "张三"
    assert rec["scope"] == "extract_text + _finish_pdf（全文）"
    assert rec["note"] == "判据未被放宽"
    assert rec["at"], "签字时间不许省（谁在什么时候签的是台账的主要内容）"


# ---- 台账只在"需要它"的时候才是必需的


def test_no_hit_stays_clean_even_without_ledger(tmp_path: Path) -> None:
    """没有命中 ⇒ `clean`(0)，台账读不读都不影响这个结论（台账不是万能前置门）。"""
    root, manifest, _rel = _make_sandbox(tmp_path)
    missing = root / "nope" / G.LEDGER_NAME
    result = G.check_approvals(["docs/notes.md"], manifest=manifest, root=root, ledger_path=missing)
    assert result.verdict == "clean"
    assert result.exit_code == 0
    assert result.approvals == [], "没命中就没有台账判定这一层"


def test_empty_change_set_with_check_approvals_is_still_clean(tmp_path: Path) -> None:
    root, manifest, _rel = _make_sandbox(tmp_path)
    assert G.main(["--quiet", "--check-approvals", "--paths", "--manifest", str(manifest), "--root", str(root)]) == 0


# ---- CLI 面：`--check-approvals` / `--json` / `--git` 的既有行为不许被改动


def test_check_approvals_cli_json_exposes_approvals_and_ledger(tmp_path: Path, capsys) -> None:
    """`--check-approvals --json` 必须把台账判定这一层打出来（否则看不出 clean 的来源）。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    sha = G.sha256_file(root / rel)
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, sha, [_reviewer("甲"), _reviewer("乙")])])
    code = G.main([
        "--check-approvals", "--paths", rel, "--json",
        "--manifest", str(manifest), "--root", str(root),
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "clean"
    assert payload["ledger"].endswith(G.LEDGER_NAME)
    assert payload["approvals"][0]["approval_status"] == "approved"
    assert payload["approvals"][0]["current_sha256"] == sha


def test_check_approvals_cli_exit_codes_are_three_valued(tmp_path: Path, capsys) -> None:
    """三档退出码在台账这条路上也要真的分开：1=未批准、2=没查成、0=靠台账 clean。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    args = ["--check-approvals", "--paths", rel, "--manifest", str(manifest), "--root", str(root)]
    # 台账不存在 ⇒ 2（不是 0）
    assert G.main([*args, "-q"]) == 2
    # 台账存在但没条目 ⇒ 1
    _write_ledger(root / G.LEDGER_NAME, [])
    assert G.main([*args, "-q"]) == 1
    # 台账齐了 ⇒ 0
    _write_ledger(
        root / G.LEDGER_NAME,
        [_entry(rel, G.sha256_file(root / rel), [_reviewer("甲"), _reviewer("乙")])],
    )
    assert G.main([*args, "-q"]) == 0
    capsys.readouterr()


def test_git_flag_behaviour_is_unchanged_by_check_approvals(tmp_path: Path) -> None:
    """既有的 `--git` 行为未被改动：非 git 仓库下仍报 `unknown`(2)，不是 `clean`。

    加上 `--check-approvals` 也一样 —— 台账不能把"取不到改动集"变成"没问题"。
    """
    d = _make_non_git_dir(tmp_path)
    (d / G.MANIFEST_NAME).write_text(
        "[category: solver-core] 一、算法\nsrc/a.py  [category: solver-core]  理由\n",
        encoding="utf-8",
    )
    assert G.main(["--quiet", "--git", "--root", str(d)]) == 2
    assert G.main(["--quiet", "--check-approvals", "--git", "--root", str(d)]) == 2
    assert G.main(["--quiet"]) == 2


def test_check_approvals_still_needs_a_change_set(tmp_path: Path) -> None:
    """`--check-approvals` 单独给（没有改动集）⇒ 仍是 `unknown`(2)：没有输入就没有检查。"""
    assert G.main(["--quiet", "--check-approvals"]) == 2


# ---- 清单：台账自己也在禁改区里，且两处仍逐条一致


def test_manifest_consistency_still_clean_after_adding_ledger_entry() -> None:
    """加了 `.noai-approvals.json` 之后，两处清单仍逐条一致（`check_manifest_consistency() == []`）。"""
    assert G.check_manifest_consistency() == []

    key = (G.LEDGER_NAME, "auth-audit")
    manifest = {(r.glob, r.category): r for r in G.load_manifest()}
    agents = {(r.glob, r.category): r for r in G.parse_agents_block()}
    assert key in manifest, f".noai-paths 里没有登记台账自己：{sorted(manifest)}"
    assert key in agents, f"AGENTS.md 标记区块里没有登记台账自己：{sorted(agents)}"
    assert manifest[key].reason == agents[key].reason
    assert manifest[key].reason.strip(), "台账这一条也必须有理由"


def test_baseline_skips_paths_outside_the_manifest(tmp_path: Path) -> None:
    """不命中禁改区的路径不登记（没有 glob / category 可写），且整体退出码 2。

    为什么退出码是 2 而不是 0：有一个路径没做成 —— "部分成功"报 0
    会让"这个文件没登记上"变成一件没人发现的事（静默兜底）。
    """
    root, _manifest, rel = _make_sandbox(tmp_path)
    (root / "docs").mkdir()
    (root / "docs" / "x.md").write_text("# x\n", encoding="utf-8")
    code = G.main(["--baseline", "--paths", rel, "docs/x.md", "--root", str(root)])
    assert code == 2
    ledger = G.load_ledger(root / G.LEDGER_NAME)
    assert ledger.entry_for("docs/x.md") is None, "不命中的路径不该被写进台账"
    assert ledger.entry_for(rel) is not None, "命中的那一条仍要登记（不能整批放弃）"


def test_check_approvals_accepts_absolute_paths(tmp_path: Path) -> None:
    """绝对路径（含盘符/反斜杠）也要能对上台账条目。

    否则会出现一种"假 `unregistered`"：明明登记过、也批准过，只因为调用方给的是
    `D:\\…\\src/a.py` 就报"从没登记" —— 那是一个静默的假阴性
    （人照着提示去重跑 `--baseline`，会覆盖掉已批准的记录）。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    sha = G.sha256_file(root / rel)
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, sha, [_reviewer("甲"), _reviewer("乙")])])
    for raw in (str(root / rel), (root / rel).as_posix()):
        result = G.check_approvals([raw], manifest=manifest, root=root)
        assert result.verdict == "clean", f"{raw} ⇒ {result.explanation}"
        assert _approvals(result)[rel]["approval_reason"] == G.REASON_APPROVED


# ---- `authored_basis`：结论与依据必须分开写


def test_ledger_entry_without_authored_basis_is_invalid(tmp_path: Path) -> None:
    """缺 `authored_basis` ⇒ 结构不合规 ⇒ `unknown`(2)，不是给个默认值就算数。

    三态纪律在这里的用法："我没写依据"与"依据是推断"不是同一种东西。
    若给了默认值（比如默认 `inferred`），一条只有一个 `authored` 字段的记录
    就会在读者眼里长得像事实 —— 而它可能只是推断。缺字段必须失败，
    而且失败方式是 `unknown`（没查成），不是"按老结构硬读"。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    payload = _entry(rel, "0" * 64)
    del payload["authored_basis"]
    bad = root / G.LEDGER_NAME
    bad.write_text(
        json.dumps(
            {"ledger_version": G.LEDGER_VERSION, "generated_at": "x", "entries": [payload]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    result = G.check_approvals([rel], manifest=manifest, root=root, ledger_path=bad)
    assert result.verdict == "unknown", result.explanation
    assert result.verdict != "clean"
    assert result.exit_code == 2
    assert "authored_basis" in " ".join(result.manifest_issues)


def test_baseline_always_writes_authored_basis(tmp_path: Path) -> None:
    """`--baseline` 生成的每条必有 `authored_basis`，且取自受控两个取值。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    assert G.main(["--baseline", "--paths", rel, "--root", str(root), "--note", "初版"]) == 0
    entry = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel)
    assert entry is not None
    assert entry.authored_basis == "inferred", "默认必须是**推断**，不是断言"
    assert entry.authored_basis in G.AUTHORED_BASIS_VALUES

    # 显式声明 attested 时照实写（这条只是写入；它是否属实门无法验证）。
    assert G.main([
        "--baseline", "--paths", rel, "--root", str(root),
        "--authored", "human", "--authored-basis", "attested", "--note", "人自己声明",
    ]) == 0
    entry = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel)
    assert entry is not None
    assert (entry.authored, entry.authored_basis) == ("human", "attested")
    assert entry.to_dict()["authored_basis"] == "attested"


def test_inferred_attribution_is_labelled_non_evidence(tmp_path: Path) -> None:
    """`inferred` 的条目必须在理由行里显式写"推断，非独立证据"。

    理由：读台账的人是在终端上读那一行的，不该把推断当事实。
    （对应的反向要求——"`attested` 必须有证据"——没有机械判据，
    所以这里不造那条测试，而是在 GOVERNANCE 里写明它依赖签名者诚实。）
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    _write_ledger(
        root / G.LEDGER_NAME,
        [_entry(rel, G.sha256_file(root / rel), [_reviewer("甲")], authored_basis="inferred")],
    )
    result = G.check_approvals([rel], manifest=manifest, root=root)
    got = _approvals(result)[rel]
    assert got["authored_basis"] == "inferred"
    assert "推断" in got["detail"] and "非独立证据" in got["detail"], got["detail"]


def test_attested_attribution_says_it_cannot_be_verified(tmp_path: Path) -> None:
    """`attested` 的条目也必须有一句限定语：门无法机械验证这个声明。"""
    root, manifest, rel = _make_sandbox(tmp_path)
    _write_ledger(
        root / G.LEDGER_NAME,
        [_entry(rel, G.sha256_file(root / rel), [_reviewer("甲")],
                authored="human", authored_basis="attested")],
    )
    got = _approvals(G.check_approvals([rel], manifest=manifest, root=root))[rel]
    assert "attested" in got["detail"]
    assert "无法机械验证" in got["detail"], got["detail"]


def test_real_ledger_is_readable_and_registers_the_round() -> None:
    """真实台账：能被解析、覆盖本轮命中的 13 个文件，且不给自己登记。

    这里不断言 `reviewers` 为空 —— 人批准之后它们就会非空，那是预期的。
    断言的是"结构可读 + 覆盖范围"，它不因为人签了字而变红。
    """
    ledger = G.load_ledger(REAL_MANIFEST.parent / G.LEDGER_NAME)
    assert ledger.ledger_version == G.LEDGER_VERSION
    paths = {e.path for e in ledger.entries}
    expected = {
        "pyproject.toml",
        "scripts/release_check.py",
        "src/agentflow/dedup.py",
        "src/agentflow/extract.py",
        "src/agentflow/interactions.py",
        "src/agentflow/providers.py",
        "src/agentflow/quoteverify.py",
        "src/agentflow/schema.py",
        "src/agentflow/store.py",
        "src/agentflow/tools/__init__.py",
        "src/agentflow/tools/base.py",
        "src/agentflow/tools/verify_tools.py",
        "src/agentflow/verify.py",
    }
    missing = expected - paths
    assert not missing, f"台账没有覆盖这些本轮文件：{sorted(missing)}"
    assert G.LEDGER_NAME not in paths, "台账不该给自己登记（它永远 unapproved，登记只会制造噪音）"
    for e in ledger.entries:
        assert len(e.sha256) == 64 and e.sha256 == e.sha256.lower()
        assert e.authored in G.AUTHORED_VALUES
        # 真台账里每一条也必须有依据，且本轮全部是推断（没有一条自称有直接证据）。
        assert e.authored_basis in G.AUTHORED_BASIS_VALUES, e.path
        assert e.authored_basis == "inferred", (
            f"{e.path} 标成 attested —— 那需要直接证据；本轮没有任何一条有"
            "（若确实有，请把证据写进 change_note 并在此处放行）"
        )
        assert isinstance(e.changed_this_session, (bool, type(None)))


