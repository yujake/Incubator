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
（台账读不到/解析不了/结构不对 ⇒ `unknown`，不是 `clean`）、理由码区分 `unregistered`（从没登记）与 `stale`（登记过但批准的那一版不是现在这一版，消息里必须有两个
hash）、`1 < 2` 证明门槛真的是 2、台账不能批准自己、`--baseline` 绝不写 `reviewers`（登记 ≠ 批准）、`--approve` 在 hash 不一致时拒绝写入并以退出码 2 结束
- 归属的依据：`authored`（结论）与 `authored_basis`（结论有多强：`attested` / `inferred`）
必须成对出现，缺依据 ⇒ 结构不合规 ⇒ `unknown`（不给默认值："我没写依据"与"依据是推断"不是同一种东西）；`inferred` 的条目在人读的理由行里必须标注"推断，非独立证据"
"""

from __future__ import annotations

import json
import os
import re
import subprocess
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


# ------------------------------------------------------------------ G-46：可疑的 --paths 取值


def test_comma_in_paths_value_is_unknown_not_clean() -> None:
    """负控（`G-46`）：`--paths "a.py,b.py"` 曾经是 `clean(0)` 假绿，现在必须是 `unknown(2)`。

    `--paths` 是 `nargs="*"` ⇒ 逗号不是分隔符，整串被当成一条路径、不匹配任何 glob
    ⇒ 门报 clean。这条用例钉住"不许再那样"。
    """
    code = G.main(["--quiet", "--paths", "src/agentflow/schema.py,src/agentflow/verify.py"])
    assert code == 2, f"含逗号的 --paths 必须 unknown(2)（没查成），得到 {code}"


def test_newline_in_paths_value_is_unknown_not_clean() -> None:
    """负控（`G-46`）：取值含换行 ⇒ 同样 `unknown(2)`（多行变量/命令替换传进来就是这个形状）。"""
    code = G.main(["--quiet", "--paths", "src/agentflow/schema.py\nsrc/agentflow/verify.py"])
    assert code == 2, f"含换行的 --paths 必须 unknown(2)，得到 {code}"


def test_suspect_paths_message_echoes_the_value_verbatim() -> None:
    """可疑取值必须原样回显 —— 只说"格式不对"会让人不知道该改哪一个参数。"""
    bad = "src/agentflow/schema.py,src/agentflow/verify.py"
    suspect = G._suspect_paths_values([bad])
    assert suspect == [bad], "判别函数必须原样返回可疑取值（供消息回显与逐条列举）"
    assert G._suspect_paths_values(["a.py", "b.py", "dir/c.py"]) == [], "正常路径不许被判为可疑"


def test_space_separated_paths_still_behave_as_before() -> None:
    """正控（`G-46`）：只有可疑输入形态被拒 —— 空格分隔的多条仍然照常判定。

    若这条变红，说明修法把正常通路一起改坏了（那不是修 G-46，那是把门关掉）。
    """
    assert G.main(["--quiet", "--paths", "src/agentflow/schema.py", "src/agentflow/verify.py"]) == 1
    assert G.main(["--quiet", "--paths", "docs/notes.md"]) == 0


def test_suspect_paths_is_refused_before_the_baseline_write() -> None:
    """`--baseline` 通路也要挡：把整串逗号值当一条 glob 登记进台账，是不可逆的脏数据。

    它比一次假 clean 更难发现（假 clean 只影响这一次判定；脏台账会在仓库里一直留着）。
    这里只断言"退出了、且没写台账"—— 台账文件由 `--ledger` 指向 tmp。
    """
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "ledger.json"
        code = G.main(["--quiet", "--baseline", "--ledger", str(ledger),
                       "--paths", "src/agentflow/schema.py,src/agentflow/verify.py"])
        assert code == 2, f"可疑取值下的 --baseline 必须 unknown(2)，得到 {code}"
        assert not ledger.exists(), "拒绝的动作不许已经写了台账"


def test_agentflow_prefixed_paths_still_hit() -> None:
    """负控（X-9）：伞仓库给的是 `agentflow/src/...` 形态的路径，门必须照样命中。

    本仓库的 `.git` 在上一级（`D:\\Incubator`），交付物在 `agentflow/` 子目录里 ⇒
    `git diff --name-only` 回来的是仓库根相对路径。若门只认"项目根相对"形态，
    "改了禁改区"就会被判成 `clean` —— 那正是"假 clean"里最贵的一种（门对着 A 回答 B）。
    """
    for prefixed in (
        "agentflow/src/agentflow/dedup.py",
        "D:/Incubator/agentflow/src/agentflow/dedup.py",
        "./agentflow/scripts/release_check.py",
    ):
        assert G.main(["--quiet", "--paths", prefixed]) == 1, f"{prefixed} 没有被认出来"


def test_agentflow_prefixed_clean_path_does_not_hit() -> None:
    """正控：同样前缀、但不在清单里的路径必须仍是 clean（前缀匹配不许变成"什么都命中"）。"""
    for prefixed in ("agentflow/README.md", "agentflow/docs/INDEX.md"):
        assert G.main(["--quiet", "--paths", prefixed]) == 0, f"{prefixed} 不该命中"


#: 一致性检查的副本里删掉的那一条（负控必须逐字点名它）。
_CONSISTENCY_DROPPED_ENTRY = "src/agentflow/extract.py"


def _agents_md_variants(tmp_path: Path) -> tuple[Path, Path]:
    """写两份 `AGENTS.md` 副本，返回 `(与清单逐条一致的, 删掉一条的)`。

    两份都写在 `tmp_path` 里（判据不往仓内写文件），差别只有那一行 ——
    于是"读的是文件内容"与"参数串里恰好没有标记"这两件事可以被分开。
    """
    text = REAL_AGENTS.read_text(encoding="utf-8")
    assert _CONSISTENCY_DROPPED_ENTRY in text, "负控前提失败：AGENTS.md 里找不到要删的那一条"
    same = tmp_path / "agents_same.md"
    broken = tmp_path / "agents_broken.md"
    # 按字节写：本机 `write_text` 会把 LF 翻成 CRLF，两份副本要只差那一行。
    same.write_bytes(text.encode("utf-8"))
    broken.write_bytes(
        "\n".join(ln for ln in text.splitlines() if _CONSISTENCY_DROPPED_ENTRY not in ln).encode("utf-8")
    )
    return same, broken


def test_check_consistency_cli_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """一致性检查也是门：一致 ⇒ 0；不一致 ⇒ 1（确凿的失败）；读不到 ⇒ 2（没查成）。

    这里曾经断言 2。2 在本项目里是 `unknown`（没查成），而"清单两处确实不一致"是
    查过了、结论是坏了 —— 让同一个码背两个互相排斥的含义，调用方就没法据码行事
    （`AGENTS.md` 逐字写"2 = unknown：没查成，绝不是 clean"）。

    `--agents-md` 按 `--help` 是路径（不是文件内容）：这条用例因此真的写两份文件、
    真的读它们。改前实现把路径串当文件内容交给解析器（串里没有标记 ⇒ 解析失败 ⇒
    有差异 ⇒ 1），于是"完好副本"与"少一条的副本"输出逐字相同 —— 用例为错误的理由通过。
    """
    assert G.main(["--quiet", "--check-consistency"]) == 0

    same, broken = _agents_md_variants(tmp_path)
    assert G.main(["--quiet", "--check-consistency", "--agents-md", str(same)]) == 0, (
        "与清单逐条一致的 AGENTS.md 副本必须判一致(0) —— 改前这一档也是 1（读的是路径串）"
    )
    code = G.main(["--check-consistency", "--agents-md", str(broken)])
    out = capsys.readouterr().out
    assert code == 1, "不一致是确凿的失败(1)，不是没查成(2)"
    assert _CONSISTENCY_DROPPED_ENTRY in out, (
        f"差异里必须逐字点名被删掉的那一条 {_CONSISTENCY_DROPPED_ENTRY}：{out}"
    )


def test_check_consistency_honors_root(tmp_path: Path) -> None:
    """`--check-consistency --root X` 必须读 `X` 下的两处清单，不能读"脚本恰好在哪棵树"。

    为什么这条判据必须有：仓里两处是逐条一致的 ⇒ "`--root` 被忽略"的读数恰好是
    exit 0，于是一份被改坏的副本会被判成"逐条相同"（对着错误的对象给出假绿）。
    这里要求坏副本 ⇒ 1、好副本 ⇒ 0：同一个调用只换 `--root` 就得出相反结论，
    `--root` 才算真的生效。
    """
    ok = tmp_path / "ok"
    bad = tmp_path / "bad"
    for d in (ok, bad):
        d.mkdir()
        (d / G.MANIFEST_NAME).write_bytes(REAL_MANIFEST.read_bytes())
    text = REAL_AGENTS.read_text(encoding="utf-8")
    (ok / G.AGENTS_NAME).write_bytes(text.encode("utf-8"))
    (bad / G.AGENTS_NAME).write_bytes(
        "\n".join(ln for ln in text.splitlines() if _CONSISTENCY_DROPPED_ENTRY not in ln).encode("utf-8")
    )

    assert G.main(["--quiet", "--check-consistency", "--root", str(ok)]) == 0
    assert G.main(["--quiet", "--check-consistency", "--root", str(bad)]) == 1, (
        "`--root` 指向的那棵树里 AGENTS.md 少了一条 ⇒ 必须判不一致(1)；"
        "改前这一档读的是「脚本恰好在哪棵树」（那两处一致）⇒ 0"
    )


def test_check_consistency_read_failure_is_unknown_not_disagreement(tmp_path: Path) -> None:
    """读不到 ⇒ 2（没查成）自成一档，不许折成 1（有人只改了一处）。

    `check_manifest_consistency` 按设计把 parse 级错误当差异返回（另有用例依赖这一点），
    所以这一档由 CLI 在调用它之前把"读不到"分出来。四种输入逐一钉住，末尾再补一条
    "读得到 ⇒ 0"的正控（免得这四档被一条恒真的 2 吞掉）。
    """
    root = tmp_path / "root"
    root.mkdir()
    (root / G.MANIFEST_NAME).write_bytes(REAL_MANIFEST.read_bytes())
    (root / G.AGENTS_NAME).write_bytes(REAL_AGENTS.read_bytes())

    # ① `--agents-md` 指的是路径：不存在的路径 ⇒ 读不到 ⇒ 2。
    assert G.main(
        ["--quiet", "--check-consistency", "--agents-md", str(tmp_path / "no_such_agents.md")]
    ) == 2

    # ② `--root` 那棵树里没有 AGENTS.md。
    no_agents = tmp_path / "no_agents"
    no_agents.mkdir()
    (no_agents / G.MANIFEST_NAME).write_bytes(REAL_MANIFEST.read_bytes())
    assert G.main(["--quiet", "--check-consistency", "--root", str(no_agents)]) == 2

    # ③ `--root` 那棵树里没有 .noai-paths。
    no_manifest = tmp_path / "no_manifest"
    no_manifest.mkdir()
    (no_manifest / G.AGENTS_NAME).write_bytes(REAL_AGENTS.read_bytes())
    assert G.main(["--quiet", "--check-consistency", "--root", str(no_manifest)]) == 2

    # ④ `--manifest` 指的是路径：不存在的清单 ⇒ 读不到 ⇒ 2。
    assert G.main(
        ["--quiet", "--check-consistency", "--manifest", str(tmp_path / "no_such_manifest")]
    ) == 2

    # 正控：参数同样显式、两处都读得到 ⇒ 0。
    assert G.main(["--quiet", "--check-consistency", "--root", str(root)]) == 0


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

    ## A11：通配行按"至少命中一个真实文件"判（2026-10-06 起）

    清单此前只有逐文件的行，所以这条断言可以写成"这个路径必须是一个文件"。F15 把 `tests/golden/*.json` 登记进来了（两份冻结快照的集合才是那一格的口径：将来加第三份快照时不该再来改一次清单），
    于是这里必须能处理通配：含 `*`/`?`/`[`/`` 的行按 `Path.glob` 展开，要求至少命中一个真实文件 ——一个都不命中的通配与写错的逐文件行是同一种假阴性（永远不命中）。
    逐文件的行仍按"必须是一个文件"判，一个字都没放宽。
    """
    root = REAL_MANIFEST.parent
    wildcard = 0
    for rule in G.load_manifest():
        if rule.glob in DELIBERATELY_ABSENT:
            assert not (root / rule.glob).is_file(), (
                f"{rule.glob} 已经存在了 —— 那么它不该再留在『刻意预登记』名单里，"
                "本条用例的豁免要摘掉（否则它永远不被检查）"
            )
            continue
        if any(ch in rule.glob for ch in "*?["):
            wildcard += 1
            hits = [p for p in root.glob(rule.glob) if p.is_file()]
            assert hits, (
                f"{rule.glob} 是通配行，但在仓库里一个真实文件都没命中 —— "
                "永远不命中的 glob 与写错的路径是同一种假阴性"
            )
            continue
        assert (root / rule.glob).is_file(), f"{rule.glob} 在仓库里不存在"
    # 反真空（2026-10-12 业主裁定 ① 之后改准）：原先要求"清单里至少有一条通配行"——
    # 那是为了让上面那段通配分支不是死代码。裁定 ① 把 `tests/golden/*.json` 拆成四条
    # 逐文件行（glob 条目只能存一个 sha256，四份快照里必有三份永远判 stale），
    # "必须还有通配行"这条前提随之消失。新的反真空钉在解析出来的保护面上：
    # 受检路径数必须够多 —— 空集/被截断的清单照样红，而不再要求某种写法的行存在
    # （要求写法存在，就是拿判据去钉实现细节）。
    checked = [r.glob for r in G.load_manifest() if r.glob not in DELIBERATELY_ABSENT]
    assert len(checked) >= 30, (
        f"清单解析出来只有 {len(checked)} 条受检路径 ⇒ 判据可能空转了（解析器坏了或被截断）")


def test_manifest_globs_are_all_hit_by_themselves() -> None:
    """自洽性：每条 glob 本身必须命中它自己（否则 glob 的形状和匹配器不一致）。"""
    for rule in G.load_manifest():
        result = G.check_paths([rule.glob], manifest=[rule])
        assert result.verdict == "requires_human", f"{rule.glob} 没能命中它自己"


def test_required_approvals_constant_is_two() -> None:
    """FC-27 判据②写死为 2 —— 不是可配置项（可配置的门槛等于没有门槛）。"""
    assert G.REQUIRED_APPROVALS_ON_HIT == 2


# --------------------------------------------------------------------------- 理由里的符号必须真实存在
#
# 口径（`X-96.4-1`）：理由里的每一个反引号符号都必须有出处。
# 改前只断言"第一个反引号符号"，于是排在第二的错名结构上抓不到
# （`draft/28` §96.4 第 1 条逐字记着这件事：P-18 那处错理由里排第二的符号漏过去了）。

#: 理由里的"符号"：整条反引号项必须恰好是一个标识符。
_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
#: 理由里提到的 Python 文件路径（可带目录）—— 跨文件引用写"出处"用。
_REASON_PYPATH_RE = re.compile(r"`([A-Za-z_][\w./\-]*\.py)`")
#: 同一句里承认"这个符号的出处不在本文件"的写法（跨文件引用的显式标记）。
_CROSS_FILE_MARKERS = ("本文件", "本条", "本条目", "不在这里", "不在本文件")
#: 切句：句号 / 分号 / 换行 / 破折号。出处必须与那处引用落在同一句里。
_SENTENCE_SPLIT_RE = re.compile(r"[。；;\n]|——")


def _reason_sentences(reason: str) -> list[str]:
    """把一段理由切成"句"（判据要求出处与引用同句，所以必须先能切句）。"""
    return [s for s in _SENTENCE_SPLIT_RE.split(reason) if s.strip()]


def _sentence_of(reason: str, symbol: str) -> str:
    """含这一处引用的那一句；找不到时退回整段理由。

    退回是刻意的保守方向：多给上下文只会让判据更宽一点，而"切句切丢了"若判成
    "没有出处"会造出假红，假红会把这条判据训练成背景噪音。
    """
    needle = f"`{symbol}`"
    for s in _reason_sentences(reason):
        if needle in s:
            return s
    return reason


def _manifest_python_files(root: Path) -> tuple[str, ...]:
    """清单登记过的、盘上存在的 `.py` 条目（跨文件引用的解析面）。

    解析面取"清单登记的 .py"而不是整棵树：判据问的是"这条理由指向的符号在
    被保护的那批代码里真的存在吗"。把测试也算进来，会允许一条理由拿测试里的
    同名片段冒充真身（`CAPABILITIES` 在测试里是个路径常量，不是矩阵真身）。
    """
    out: list[str] = []
    for rule in G.load_manifest():
        t = root / rule.glob
        if t.is_file() and t.suffix == ".py":
            out.append(rule.glob)
    return tuple(dict.fromkeys(out))


def _resolve_py_reference(ref: str, py_files: tuple[str, ...]) -> str | None:
    """理由里写出的 `.py` 出处 ⇒ 清单登记过的那个条目（认不出返回 `None`）。"""
    if ref in py_files:
        return ref
    hits = [g for g in py_files if Path(g).name == Path(ref).name]
    return hits[0] if len(hits) == 1 else None


def manifest_symbol_problems(
    rule: "G.Rule",
    root: Path,
    target_text: str = "",
    py_files: tuple[str, ...] | None = None,
) -> list[str]:
    """一条理由里的每一个反引号符号都必须有出处；返回问题清单（空 = 全都有出处）。

    ## 三种"有出处"

    1. 符号出现在本条指向的文件里（同文件符号）—— 这是改前唯一被查过的那一种；
    2. 同一句里写出了它出自哪个 `.py` 文件，且那个文件里真的有它（跨文件引用 + 出处）；
    3. 同一句里显式声明它不在这里（`本文件` 一类标记），且它在清单登记的 `.py` 里
    唯一可解析 —— 出处不写出文件名时，至少要求它没有第二种解释。为什么允许跨文件引用而不是一律禁掉：`interactions.py` 那条理由要说明"矩阵真身不在本文件里"，`tools/vocab_census.py`
    那条要说明"lint 判据加载本文件当判据用" —— 两句话都必须能提到对面的符号，禁掉它们等于逼着理由说半句话。代价是给出处，而这正是本判据要的。
    """
    text = target_text or (root / rule.glob).read_text(encoding="utf-8")
    files = py_files if py_files is not None else _manifest_python_files(root)
    problems: list[str] = []
    for symbol in _SYMBOL_RE.findall(rule.reason):
        if symbol in text:
            continue
        sentence = _sentence_of(rule.reason, symbol)
        # 出处之二：同一句里写出了它出自哪个 .py 文件。
        stated = False
        for ref in _REASON_PYPATH_RE.findall(sentence):
            glob = _resolve_py_reference(ref, files)
            if glob is None or glob == rule.glob:
                continue
            if symbol in (root / glob).read_text(encoding="utf-8"):
                stated = True
                break
        if stated:
            continue
        # 出处之三：同一句里显式声明它是跨文件引用。
        if any(m in sentence for m in _CROSS_FILE_MARKERS):
            hits = [
                g for g in files
                if g != rule.glob and symbol in (root / g).read_text(encoding="utf-8")
            ]
            if len(hits) == 1:
                continue
            problems.append(
                f"{rule.glob} 的理由里 `{symbol}` 不在本文件里，那句只说了它出自别处，"
                f"但它在清单登记的 .py 里解析结果不唯一（命中 {hits}）—— "
                "写法是'本文件'这一档时，要求它唯一可解析"
            )
            continue
        problems.append(
            f"{rule.glob} 的理由里 `{symbol}` 在本文件里找不到，同一句里也没写出它出自哪个 "
            ".py 文件（跨文件引用必须在同一句里写明出处）"
        )
    return problems


def test_python_manifest_referenced_symbols_exist() -> None:
    """理由里用反引号写出的符号名，必须真的存在于对应的源文件里。

    为什么需要这条：清单的"理由"是给人读的，写错一个函数名不会报错 ——它只会把人指向一段不存在的代码，而禁改区仍然"看起来被登记了"。这比行号更强：行号漂了它不响（行号本来就易失），符号没了它必响。

    同时它给清单加了一道真实性约束：一条 glob 不能靠"理由里随便写点什么"来通过。

    只对 `.py` 条目做符号检查：`pyproject.toml` 里没有函数名；发布脚本（`release_check.py` 的两种落位）是并行子任务正在写的文件，本用例不替它背书 ——
    它们由"存在性/预登记"用例单独覆盖。

    口径（`X-96.4-1`）：核理由里的每一个反引号符号，不再只看第一个。跨文件引用允许，但必须在同一句里写出它出自哪个 `.py` 文件；出处只写"本文件"一类标记时，要求它在清单登记的 `.py` 里唯一可解析。
    """
    root = REAL_MANIFEST.parent
    py_files = _manifest_python_files(root)
    checked = 0
    symbols_checked = 0
    problems: list[str] = []
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

        # 理由里的每一个符号都必须在文件里出现（或按上面的三种"有出处"之一落定）。
        # 改前这里只取 `symbols[0]`：排在第二的错名结构上抓不到（`X-96.4-1`）。
        symbols = _SYMBOL_RE.findall(rule.reason)
        assert symbols, f"{rule.glob} 的理由里没有写出任何符号名：{rule.reason!r}"
        symbols_checked += len(symbols)
        problems.extend(manifest_symbol_problems(rule, root, text, py_files))

    assert not problems, (
        "清单理由里有符号找不到出处（`X-96.4-1` 之后核的是理由里的每一个反引号符号，"
        "不再只看第一个）：\n  - " + "\n  - ".join(problems)
    )
    assert checked >= 12, f"实际只检查了 {checked} 条 .py 条目，清单可能被改瘦了"
    assert symbols_checked >= 45, (
        f"只核到 {symbols_checked} 个反引号符号 —— 反真空下限是 45 个。"
        "判据解析出空集时会无条件通过，所以这里必须有一个下限，"
        "而'下限被踩到'与'清单真的变干净了'不是同一种情况"
    )


def test_symbol_check_catches_a_wrong_name_in_the_second_slot() -> None:
    """`X-96.4-1` 的负控：把一条理由里排在第二位的符号改成错名 ⇒ 判据必须报出来。

    改前那条判据只断言 `symbols[0]`，所以这一处改动静默地通过
    （`draft/28` §96.4 第 1 条逐字：P-18 那处错理由里排第二的符号结构上抓不到）。

    夹具在内存里构造，错名是拼出来的、不逐字写进本文件：本仓另有一条悬空引用判据
    （`tests/test_r5_orchestration_cost.py` 的引用体检）会扫注释与 docstring 里
    反引号包着的私有名，把错名逐字写下来会让那一条变红 —— 那是另一条判据的东西，
    不该由本用例来付账。
    """
    root = REAL_MANIFEST.parent
    rule = next(
        r for r in G.load_manifest()
        if r.glob == "src/agentflow/providers.py" and r.category == "solver-core"
    )
    symbols = _SYMBOL_RE.findall(rule.reason)
    assert len(symbols) >= 2, f"负控前提失败：这条理由只有 {len(symbols)} 个符号"
    second = symbols[1]
    bogus = second[:-1] + ("q" if second[-1] != "q" else "z")
    assert bogus != second and bogus not in rule.reason
    mutated = G.Rule(
        glob=rule.glob,
        category=rule.category,
        reason=rule.reason.replace(f"`{second}`", f"`{bogus}`", 1),
    )
    assert mutated.reason != rule.reason, "负控前提失败：理由没有被改动"

    # 正控：原样的那条理由没有出处问题（否则这条负控证明不了任何东西）。
    assert manifest_symbol_problems(rule, root) == []
    # 负控：错名排在第二位 ⇒ 必须被抓到。
    problems = manifest_symbol_problems(mutated, root)
    assert problems, f"排在第二位的符号被改成错名，判据却说没有出处问题：{second!r}"
    assert any(bogus in p for p in problems), problems


def test_cross_file_symbol_must_state_its_source_in_the_same_sentence() -> None:
    """`X-96.4-1` 的另一半：跨文件引用必须在同一句里写明出处。

    正控用清单里真实存在的两处跨文件引用（`interactions.py` 那条写出了
    `capabilities.py`、`tools/vocab_census.py` 那条写的是"本文件"）⇒ 全绿。
    负控把"本文件"这一处声明抹掉 ⇒ 同一个真符号必须当场被报出来。
    """
    root = REAL_MANIFEST.parent
    rule = next(r for r in G.load_manifest() if r.glob == "tools/vocab_census.py")
    assert "本文件" in rule.reason, "夹具前提失败：这条理由里没有跨文件标记"
    assert manifest_symbol_problems(rule, root) == []

    mutated = G.Rule(
        glob=rule.glob,
        category=rule.category,
        reason=rule.reason.replace("本文件", "别处", 1),
    )
    assert mutated.reason != rule.reason
    problems = manifest_symbol_problems(mutated, root)
    assert problems, "跨文件引用的出处声明被抹掉之后，判据却说没有出处问题"
    assert any("rule_R011_dead_vocab" in p for p in problems), problems


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


def _make_non_git_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """造一个确定不被 git 当仓库的目录，并实测这个前提。

    为什么不再用"逐级向上找 `.git`"：那条判据只在"临时目录恰好在仓库外"时成立。
    本机已真实发生过 TMP 落在仓库内（`--basetemp` 放进 `D:\\Incubator`）⇒ 前提断言
    自己失败，一条负控因为环境而消失 —— 那比红更危险（绿灯看起来更绿）。

    这里改用 git 自己的机制：`GIT_CEILING_DIRECTORIES` 让向上查找在 `tmp_path` 截断，
    然后用 `git rev-parse` 验这个前提，而不是假设它。
    """
    d = tmp_path / "not-a-repo"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    proc = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(d),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0, f"前提失败：{d} 仍被 git 认为是仓库内（天花板没生效）"
    return d


def test_git_returns_unknown_outside_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非 git 仓库 ⇒ `--git` 报 `unknown`，不是 `clean`。"""
    d = _make_non_git_dir(tmp_path, monkeypatch)
    (d / G.MANIFEST_NAME).write_text(
        "[category: solver-core] 一、算法\nsrc/a.py  [category: solver-core]  理由\n", encoding="utf-8"
    )
    code = G.main(["--quiet", "--git", "--root", str(d)])
    assert code == 2, "非 git 仓库下 --git 必须是 unknown（2），不能是 clean（0）"


def test_git_helper_reports_reason_not_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """取不到改动集时，辅助函数必须给出人能看懂的原因，而不是空字符串。

    改写理由（原来它会在"当前仓库是 git 仓库"时直接 `pytest.skip`）：本仓库现在
    就是一个 git 仓库，于是这条负控长期不执行，而 `-q` 只显一个 `1 skipped` ——
    没人知道少跑了一条负控。负控不许依赖环境：这里自己造一个不被 git 认作仓库
    的目录（`GIT_CEILING_DIRECTORIES` 截断向上查找），让这条负控在任何机器上都真执行。
    """
    d = _make_non_git_dir(tmp_path, monkeypatch)
    paths, reason = G.git_changed_paths(d)
    assert paths is None
    assert reason.strip(), "原因不能为空 —— 空原因等于让下游自己猜"


def test_git_flag_verdict_is_unknown_not_clean() -> None:
    """直接断言 verdict（不只是退出码）：`unknown` 与 `clean` 不是同一件事。"""
    result = G.check_paths(["src/agentflow/dedup.py"], manifest=Path("no/such/manifest"))
    assert result.verdict == "unknown"
    assert result.verdict != "clean"
    assert result.exit_code == 2


# --------------------------------------------------------------------------- `--git` 的改动集范围
#
# 这一节钉的是两条实测过的绕过路径 —— 都能让"改了禁改区"被判成 clean：
#   ① 提交即隐身：`git diff --name-only HEAD` 比的是"工作区 vs HEAD"；
#   ② 新建即隐身：`git diff` 只报已跟踪文件，未跟踪的新文件它看不见。
# 每一条都配一个"修前会是 clean"的负控，和一个"正常用法不许被误伤"的正控。


def _git(repo: Path, *argv: str) -> subprocess.CompletedProcess[str]:
    """在 `repo` 里跑一条 git 命令（身份与行尾都写死，免得吃全局配置）。"""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@local",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@local",
    }
    return subprocess.run(["git", *argv], cwd=str(repo), capture_output=True, text=True, env=env)


def _make_git_repo(tmp_path: Path, rel: str = "src/a.py") -> tuple[Path, Path, str]:
    """造一个已经提交过的小世界（清单登记 `rel`，`rel` 存在）。返回 `(root, manifest, rel)`。"""
    root, manifest, rel = _make_sandbox(tmp_path, rel=rel)
    assert _git(root, "init", "-q").returncode == 0, "前提：git init 要成功"
    _git(root, "config", "core.autocrlf", "false")
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "init").returncode == 0
    assert _git(root, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    return root, manifest, rel


def test_git_sees_a_committed_zone_change_when_a_baseline_is_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控①（提交即隐身）：`--since <基线>` 必须能看见已经提交的禁改区改动。"""
    root, _manifest, rel = _make_git_repo(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / rel).write_text("x = 2\n", encoding="utf-8")
    assert _git(root, "commit", "-aqm", "改禁改区").returncode == 0

    # 前提：这条改动确实"隐身"了 —— 未提交改动集合为空。
    assert _git(root, "diff", "--name-only", "HEAD").stdout.strip() == "", "前提：改动已提交"

    code = G.main(["--git", "--since", base, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1, f"已提交的禁改区改动在给基线时仍须 requires_human(1)：\n{out}"
    assert rel in out, f"命中路径必须被点名：\n{out}"


def test_git_with_a_degenerate_baseline_is_unknown_not_clean(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控①的第三个形态（`F-R1d-01`，最后一次集中审查抓到）：`--since HEAD` 是退化基线。

    `HEAD..HEAD` 恒为空 ⇒ 已提交的禁改区改动在这一跑里整体隐身；而改前这里会报
    clean(0)：改动集为空，且"给了基线"这一条把真空保护关掉。本仓的标准起跑方式
    `release_all --since HEAD` 恰恰是这个形态 —— 那时 `release_check.item_noai([])`
    会把 `noai` 记成 pass，于是一个已提交、从未被批准的禁改区改动就这样过了门。

    判据两条：① 退化基线判 unknown(2) 并说明原因；② 同一个仓库给一个真基线时
    仍然必须看见那条已提交的改动（不许把这条修复做成"一律判 unknown"）。
    """
    root, _manifest, rel = _make_git_repo(tmp_path)
    (root / rel).write_text("x = 2\n", encoding="utf-8")
    assert _git(root, "commit", "-aqm", "改禁改区").returncode == 0
    assert _git(root, "diff", "--name-only", "HEAD").stdout.strip() == "", "前提：改动已提交"

    code = G.main(["--git", "--since", "HEAD", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 2, f"退化基线必须判没查成(2)，不许 clean(0)：\n{out}"
    assert "退化基线" in out, f"理由里必须点名'退化基线'：\n{out}"

    base = _git(root, "rev-parse", "HEAD~1").stdout.strip()
    code2 = G.main(["--git", "--since", base, "--root", str(root)])
    out2 = capsys.readouterr().out
    assert code2 == 1 and rel in out2, f"真基线仍须 requires_human(1) 并点名路径：\n{out2}"


def test_git_without_a_baseline_never_reports_clean_on_an_empty_change_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控①的真空保护：提交掉禁改区改动、又不给 `--since` ⇒ `unknown`(2)，不是 `clean`(0)。

    这是本门最容易骗人的一格：改动集为空，而"空"的真实含义是"没有未提交改动"，
    不是"没有改动"。三态纪律要求它判"没查成"。
    """
    root, _manifest, rel = _make_git_repo(tmp_path)
    (root / rel).write_text("x = 2\n", encoding="utf-8")
    _git(root, "commit", "-aqm", "改禁改区")

    code = G.main(["--git", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 2, f"空改动集 + 没有基线 ⇒ 没查成(2)：\n{out}"
    assert "看不见已经提交的改动" in out, f"解释必须说清为什么不是 clean：\n{out}"


def test_git_empty_change_set_explanation_states_the_scope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """空集时的解释必须写清本门看了哪些范围（否则读者会把 unknown 读成 clean）。"""
    root, _manifest, _rel = _make_git_repo(tmp_path)
    code = G.main(["--git", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 2
    assert "未提交改动" in out and "未跟踪新文件" in out, out


def test_git_sees_an_untracked_new_file_registered_by_the_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控②（新建即隐身）：清单登记过的路径上新建文件（未跟踪）⇒ 必须命中。

    修前实测：`git diff` 看不见未跟踪文件 ⇒ `clean`(0)。而清单里
    `src/agentflow/release_check.py` 的登记理由逐字就是"一旦有人在这里新建它，
    会自动落入清单" —— 这条负控守的正是那句话。
    """
    root, _manifest, rel = _make_git_repo(tmp_path)
    new_rel = "src/b.py"
    _write_manifest(root, [(rel, "solver-core"), (new_rel, "solver-core")])
    _git(root, "commit", "-aqm", "把新路径登记进清单")
    assert _git(root, "diff", "--name-only", "HEAD").stdout.strip() == "", "前提：工作区干净"

    (root / new_rel).write_text("y = 1\n", encoding="utf-8")
    assert _git(root, "ls-files", "--others", "--exclude-standard").stdout.strip() == new_rel, (
        "前提：新文件确实是未跟踪状态（否则这条负控测的是别的东西）"
    )

    code = G.main(["--git", "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1, f"未跟踪的新文件也是改动，必须命中禁改区：\n{out}"
    assert new_rel in out, out


def test_git_with_a_baseline_and_no_change_is_still_clean(tmp_path: Path) -> None:
    """正控：给了真基线且真的没有禁改区改动 ⇒ `clean`(0)。真空保护不许把正常用法也判 unknown。

    2026-09-28（`F-R1d-01` 的修复）：这一条原先拿 `rev-parse HEAD` 当基线，
    而那正是"退化基线"（`HEAD..HEAD` 恒空 ⇒ 已提交的改动整体看不见）。退化基线
    现在判 unknown(2)（见 `test_git_with_a_degenerate_baseline_is_unknown_not_clean`），
    所以这里改成先造第二个提交、再用 `HEAD~1` 当真基线 —— 判据的原意
    （真基线 + 无禁改区改动 ⇒ clean）逐字保留，而"用 HEAD 当基线"这个偶然的
    写法不再被当成正常用法。
    """
    root, _manifest, _rel = _make_git_repo(tmp_path)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "n.md").write_text("hi\n", encoding="utf-8")
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-qm", "第二个提交（非禁改区）").returncode == 0
    base = _git(root, "rev-parse", "HEAD~1").stdout.strip()
    assert base != _git(root, "rev-parse", "HEAD").stdout.strip(), "前提：HEAD~1 是真基线"
    assert G.main(["--quiet", "--git", "--since", base, "--root", str(root)]) == 0


def test_git_ignores_a_change_outside_the_manifest(tmp_path: Path) -> None:
    """正控：非禁改区路径的改动 ⇒ `clean`(0)（门不许把无关改动算成命中）。"""
    root, _manifest, _rel = _make_git_repo(tmp_path)
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "n.md").write_text("hi\n", encoding="utf-8")
    assert G.main(["--quiet", "--git", "--root", str(root)]) == 0


# --------------------------------------------------------------------------- `--root` 决定用哪份清单


def test_root_decides_which_manifest_is_used(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """负控：`--root` 指到另一个工作区 ⇒ 判据必须用那个工作区的清单。

    修前实测：`check_paths(manifest=None)` 走 `load_manifest(None)` → `project_root()`
    （"这个脚本恰好在哪个目录"），与 `--root` 无关 ⇒ 在沙箱里改一个"沙箱自己登记过"
    的禁改区路径会被判成 `clean` —— 门对着 A 工作区回答了关于 B 仓库的问题。
    """
    root, _manifest, rel = _make_sandbox(tmp_path)
    code = G.main(["--paths", rel, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1, f"沙箱自己登记过的路径必须命中（而不是用本仓库的清单）：\n{out}"
    assert rel in out, out


def test_root_without_a_manifest_is_unknown_not_a_borrowed_manifest(tmp_path: Path) -> None:
    """负控（fail-closed）：`--root` 指到没有清单的目录 ⇒ `unknown`(2)。

    修前它会静默借用本仓库的清单 ⇒ 对"另一个工作区"给出关于本仓库的结论。
    没有清单就是没查成，不是 clean，也不是"用别人的清单凑一个结论"。
    """
    d = tmp_path / "empty-ws"
    d.mkdir()
    assert not (d / G.MANIFEST_NAME).exists(), "前提：这个目录确实没有清单"
    assert G.main(["--quiet", "--paths", "src/a.py", "--root", str(d)]) == 2


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


def test_record_audit_refuses_to_audit_the_ledger_itself(tmp_path: Path) -> None:
    """`--record-audit` 也不许给台账自己记审计（退出码 2，不写入）。

    与上面那条 `--approve` 的用例逐字对称：两条通路的前置条件必须一样（`c-19`）。
    改前只有人审那条有这条拒绝，于是"往台账自己那条记录里追加一次审计"写得进去 ——
    放行确实仍被 `evaluate_approval` 的自指分支挡住，所以它不是一条提权路径；
    但两条通路不对称这件事本身就是下一个读者手里的口子。
    """
    root, _manifest, rel = _make_sandbox(tmp_path)
    ledger = _write_ledger(root / G.LEDGER_NAME, [_entry(rel, G.sha256_file(root / rel))])
    before = Path(ledger).read_bytes()

    # 第一档：直接调函数。拒绝必须在所有其它校验之前，所以这里给的是最小参数 ——
    # 参数越少，越能证明拦下它的是自指判据本身，而不是后面某一条恰好也报了错。
    with pytest.raises(G.LedgerError) as ei:
        G.record_audit(
            G.load_ledger(root / G.LEDGER_NAME),
            G.LEDGER_NAME,
            auditor="subagent-X",
            dimension="axes",
            evidence="夹具",
            negative_control="夹具",
            root=root,
        )
    assert "自指" in str(ei.value), str(ei.value)

    # 第二档：CLI。退出码 2（"没做成"），且台账一个字节都没动。
    code = G.main(
        [
            "--record-audit", G.LEDGER_NAME,
            "--auditor", "subagent-X",
            "--dimension", "axes",
            "--evidence", "夹具",
            "--root", str(root),
        ]
    )
    assert code == 2, "台账自指却记审计成功 —— 两条通路的前置条件不对称"
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
    # `FINAL-R1d-04` 之后多两格可选的证据锚（不给就是两个空串）。
    assert set(rec) == {"name", "at", "scope", "note", "verdict",
                        "evidence_path", "evidence_sha256"}, sorted(rec)
    assert rec["evidence_path"] == "" and rec["evidence_sha256"] == "", (
        "没给 --evidence-path 时锚必须是空的（不是编一个）"
    )
    assert rec["name"] == "张三"
    assert rec["scope"] == "extract_text + _finish_pdf（全文）"
    assert rec["note"] == "判据未被放宽"
    assert rec["at"], "签字时间不许省（谁在什么时候签的是台账的主要内容）"


# ---- `FINAL-R1d-04` / `FINAL-R1d-05`：人审通路的内容锚与固定保留


def _anchored_approvals(root: Path, rel: str, *, evidence_text: str = "逐行走查记录\n") -> Path:
    """在沙箱里给 `rel` 签两条带证据锚的人审记录，返回那份走查记录的路径。"""
    ev = root / "walkthrough.txt"
    ev.write_text(evidence_text, encoding="utf-8")
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, G.sha256_file(root / rel))])
    for who in ("owner-1", "owner-2"):
        assert G.main([
            "--approve", rel, "--reviewer", who, "--scope", "全文（带锚）",
            "--evidence-path", "walkthrough.txt", "--root", str(root),
        ]) == 0
    return ev


def test_positive_anchored_human_approvals_are_verified_and_the_line_carries_the_reservation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """正控：带证据锚的人审批准 ⇒ 锚逐字节核对通过 ⇒ `approved`，
    且那一行必须写明"几条带锚"与本门证明不了独立性。"""
    root, _manifest, rel = _make_sandbox(tmp_path)
    _anchored_approvals(root, rel)

    code = G.main(["--check-approvals", "--paths", rel, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "2/2 条带**内容锚**" in out, out
    assert "证明不了这几个人/这几次走查真的互相独立" in out, (
        "approved 那一行必须带上这条固定保留（`FINAL-R1d-05`）："
        "门只能证明台账里有几个不同字符串，不能证明是几个人"
    )


def test_negative_control_a_tampered_anchor_takes_the_approval_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控：走查记录被改一个字节 ⇒ 那几条批准不算数（`reviewer_evidence_anchor_unverifiable`）。

    装置自控：同一个沙箱里先证明"未篡改时是 approved"（上面那条正控覆盖），
    这里再篡改 —— 所以这里的红只可能来自锚的核对。
    """
    root, _manifest, rel = _make_sandbox(tmp_path)
    ev = _anchored_approvals(root, rel)
    assert G.main(["--quiet", "--check-approvals", "--paths", rel, "--root", str(root)]) == 0

    ev.write_text("逐行走查记录（被改过）\n", encoding="utf-8")

    code = G.main(["--check-approvals", "--paths", rel, "--root", str(root)])
    out = capsys.readouterr().out
    assert code == 1, out
    assert G.REASON_REVIEW_ANCHOR in out, out
    assert "内容变了" in out, out


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


def test_git_flag_behaviour_is_unchanged_by_check_approvals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """既有的 `--git` 行为未被改动：非 git 仓库下仍报 `unknown`(2)，不是 `clean`。

    加上 `--check-approvals` 也一样 —— 台账不能把"取不到改动集"变成"没问题"。
    """
    d = _make_non_git_dir(tmp_path, monkeypatch)
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


#: 本轮（`F10` 之前）命中的 13 个禁改区文件。这是下界：登记范围只会随新文件落入
#: 清单而扩大，不会因为谁签了字而变小 —— 所以它可以当"覆盖范围"的判据。
_ROUND_COVERED = {
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

#: 台账里每一条必须有的键（少一个 ⇒ 结构不合规 ⇒ `load_ledger` 抛 `LedgerError`）。
#: 在原始 JSON 上断言而不是只看解析后的对象：解析层是"读进来的东西合不合规"，
#: 这一条要钉的是"文件里到底写了什么"。
_REQUIRED_ENTRY_KEYS = (
    "path", "glob", "category", "sha256", "authored", "authored_basis",
    "change_note", "changed_this_session", "reviewers",
)


def test_real_ledger_is_readable_and_registers_the_round() -> None:
    """真实台账：可读、结构合规、覆盖本轮命中的文件（不断言签字状态）。

    `F10` 重写了这一条。改前它逐字断言两件"签字前"的形态：`G.LEDGER_NAME not in paths`（台账不给自己登记）与每条`authored_basis == "inferred"`。所有者
    2026-09-27 完成逐行走查并签字之后，这两条同时变成假的（实测第一条的原始输出：AssertionError: 台账不该给自己登记（它永远 unapproved，登记只会制造噪音）assert
    '.noai-approvals.json' not in {'.noai-approvals.json', ...}

    17 条拿到了 2 名不同 reviewer、`authored_basis` 变成 `attested`、台账也把自己登记了进去）。那是预期的世界变化，不是回归 —— 所以这一条现在只断言"不随人签字而变"的结构性不变量：
    条数下界、覆盖范围、每条的必需键、`sha256` 是 64 位小写 hex、`authored` / `authored_basis` 取自受控取值。至于"谁签了字"，那是台账里的事实，
    不是这一条该背的契约（未批准那一档的机器判据见下面 `test_real_ledger_registers_itself_but_can_never_approve_itself`与那批
    `test_approvals_*` 用例）。
    """
    real = REAL_MANIFEST.parent / G.LEDGER_NAME
    ledger = G.load_ledger(real)
    assert ledger.ledger_version == G.LEDGER_VERSION

    # `generated_at` 必须可解析：读不出的时间戳等于"这份台账是什么时候生成的"没有答案。
    assert G._parse_audit_at(ledger.generated_at) is not None, (
        f"台账的 `generated_at` 不是一个可解析的 ISO-8601 时间戳：{ledger.generated_at!r}"
    )

    raw = json.loads(real.read_text(encoding="utf-8"))
    items = raw["entries"]
    assert len(items) >= len(_ROUND_COVERED), (
        f"台账条目数只有 {len(items)} 条，少于本轮命中的 {len(_ROUND_COVERED)} 个文件"
    )

    paths = {e.path for e in ledger.entries}
    missing = _ROUND_COVERED - paths
    assert not missing, f"台账没有覆盖这些本轮文件：{sorted(missing)}"

    for item in items:
        where = item.get("path") or "<没有 path>"
        absent = [k for k in _REQUIRED_ENTRY_KEYS if k not in item]
        assert not absent, f"台账条目 {where!r} 缺必需的键：{absent}"
        assert re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])), (
            f"台账条目 {where!r} 的 `sha256` 不是 64 位小写 hex：{item['sha256']!r}"
        )
        assert item["authored"] in G.AUTHORED_VALUES, (
            f"台账条目 {where!r} 的 `authored` 不是受控取值：{item['authored']!r}"
        )
        assert item["authored_basis"] in G.AUTHORED_BASIS_VALUES, (
            f"台账条目 {where!r} 的 `authored_basis` 不是受控取值：{item['authored_basis']!r}"
        )
        assert isinstance(item["reviewers"], list), (
            f"台账条目 {where!r} 的 `reviewers` 不是数组（同一姓名重复签名是事实，"
            f"但结构必须是数组）：{type(item['reviewers']).__name__}"
        )

    for e in ledger.entries:
        assert len(e.sha256) == 64 and e.sha256 == e.sha256.lower()
        assert e.authored in G.AUTHORED_VALUES
        assert e.authored_basis in G.AUTHORED_BASIS_VALUES
        assert isinstance(e.changed_this_session, (bool, type(None)))
        # 记账不变量：批准数按不同姓名计，不可能超过签名记录条数。
        assert len(e.distinct_reviewers) <= len(e.reviewers), e.path


def test_real_ledger_registers_itself_but_can_never_approve_itself() -> None:
    """真实台账登记了自己，而门对它必须恒判 `unapproved` / 自指。

    这是"未批准形态仍然报未批准"在真实台账上的那一档：判据的第 1 条就是自指
    （`evaluate_approval`：台账不能批准自己），它排在 hash 与人数之前 ⇒
    无论谁给多少条签名记录，这一档的结论都不变。所以这条用例不会因为将来有人签字而失效。

    改前本文件的 `test_real_ledger_is_readable_and_registers_the_round` 断言"台账不给自己
    登记"；签字之后台账把自己登记了（`reviewers` 为空）。判据这一侧没有变 ——
    `test_ledger_never_approves_itself` 早就钉住了自指这一档（人造世界），
    这里补的是"真实台账上的那一条也走同一档"。
    """
    result = G.check_approvals([G.LEDGER_NAME])
    assert result.verdict == "requires_human", result.explanation
    assert result.exit_code == 1
    got = _approvals(result)[G.LEDGER_NAME]
    assert got["approval_status"] == "unapproved", got
    assert got["approval_reason"] == G.REASON_SELF, got
    assert "台账不能批准自己" in got["detail"], got["detail"]


# ----------------------------------------------------------------- R1c：七条 finding
#
# 这一节是第 5 轮独立重审（`REAUDIT5-R1b`）报出的 7 条 finding 的正控 + 注入负控。
#
# 每条 finding 一个正控（修完之后合法形态仍然通过）+ 一个负控（把修法那一行/那一处
# 在内存里改回改前形态 ⇒ 攻击必须变绿，证明"这条判据的分辨力就在那一行上"）。
# 负控一律用内存注入（`monkeypatch`）而不是改文件：改文件会把禁改区实现改坏，
# 而且那种"负控"跑完就没法再跑正控。
#
# 负控还要守探针自己：每个注入都先断言"注入确实生效"，否则读数就是假绿。

_REAL_TARGET_SRC = (
    '"""R1c 测试的被审对象：定义了四个符号 alpha / beta / gamma / delta。"""\n'
    "\n"
    "alpha = 1\n"
    "beta = 2\n"
    "gamma = 3\n"
    "delta = 4\n"
    "\n"
    "\n"
    "def total() -> int:\n"
    "    return alpha + beta + gamma + delta\n"
)
#: 四个两两不相交的观察面（口径裁决①：计数的维度必须各有独立落点）。
#: 名字都用 ≥3 字符：`_scope_tokens` 只收长度 ≥3 的 token（判据本来的口径）。
_R1C_SCOPES = (
    "src/a.py alpha",
    "src/a.py beta",
    "src/a.py gamma",
    "src/a.py delta",
)
#: 负控正文（合格）：长度 ≥40、有"怎么比"（改前）+ "比出来什么"（报红）。
_R1C_NC = (
    "负控：拿同一套判据去审改前那一版（`git show HEAD:src/a.py`）—— "
    "改前那一版没有 `alpha` 这个符号，判据必须报红，否则说明它没有分辨力。"
)
#: 独立性声明（合格）。
_R1C_INDEP = "我是子审计代理 r1c，与该条目的作者不是同一主体（署名者未知）"


def _r1c_root(tmp_path: Path) -> tuple[Path, Path, str]:
    """造一个小世界：一个真实可解析的被审对象 + 一份真证据文件。

    返回 `(root, manifest, rel)`（与 `_make_sandbox` 同形，方便直接套用既有夹具写法）。
    不用 `_make_sandbox`：它的被审对象是 `x = 1`，
    定义不出 `alpha`/`total`，而这一节的好几条判据要看被审对象里真的有哪些符号。
    """
    root = tmp_path / "repo"
    rel = "src/a.py"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(_REAL_TARGET_SRC, encoding="utf-8", newline="\n")
    manifest = _write_manifest(root, [(rel, "solver-core")])
    ev = root / "temp" / "r1c-ev.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(_R1C_NC + "\n", encoding="utf-8", newline="\n")
    return root, manifest, rel


def _r1c_evidence(root: Path, tag: str, *, auditor: str = "", sha256: str = "",
                  scope: str = "") -> tuple[str, str]:
    """`(绝对路径, sha256)` —— 每条记录一份内容不同的证据。

    为什么必须不同：`counted_audits` 的键是 `(归一化路径, 内容 hash)`，共用一份证据会被正确地折叠成一条（那正是 `c-17` 的行为）。这一节要测的是维度/身份的判据，
    所以先让"三条记录真的是三条独立的证据"这件事成立。

    证据正文里必须同时出现审计者标识与所审版本的 sha 前缀：判定侧的`_check_audit_evidence` 会逐条交叉核对这两件事（`H-1b`），缺了它整条通路会判`unknown`，
    那样这一节测的就成了"证据锚"而不是"维度/身份判据"。

    为什么给绝对路径：`evaluate_approval` 的默认 `repo` 是 `project_root()`（`agentflow/`），相对路径在临时目录里会解析错地方。
    """
    ev = root / "temp" / f"r1c-ev-{tag}.txt"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(
        f"审计者标识（独立词）：{auditor}\n"
        f"开审版本 sha256 = {sha256}\n"
        f"覆盖 scope 符号：{scope}\n"
        f"{_R1C_NC}\n（这条证据属于 {tag}）\n",
        encoding="utf-8", newline="\n",
    )
    return str(ev), G.sha256_file(ev)


def _r1c_audit(
    root: Path,
    sha: str,
    *,
    auditor: str,
    dimension: str,
    tag: str,
    scope: str = "src/a.py alpha",
    independence: str = _R1C_INDEP,
    at: str = "2026-09-27T00:00:00+08:00",
    evidence_path: str | None = None,
    evidence_sha256: str | None = None,
) -> dict:
    """一条合规审计的字段（要造攻击就覆盖其中一两项）。

    注意： `scope` 的缺省值是单个观察面（`src/a.py alpha`）—— 它只适合"单独一条"的场景。
    口径裁决① 之后，任何"应当通过"的多条审计都必须显式传 `_R1C_SCOPES` 里
    两两不相交的落点，否则"3 个维度共用 1 个观察面"会先被判 unapproved
    （那正是判据在做事）。要造"共用观察面"的攻击就显式传同一个 `scope`。
    """
    eff_scope = scope
    ev_abs, ev_sha = _r1c_evidence(root, tag, auditor=auditor, sha256=sha, scope=eff_scope)
    return {
        "auditor": auditor,
        "dimension": dimension,
        "at": at,
        "sha256": sha,
        "evidence": f"temp/r1c-ev-{tag}.txt",
        "negative_control": _R1C_NC,
        "findings": [],
        "scope": eff_scope,
        "evidence_path": ev_abs if evidence_path is None else evidence_path,
        "evidence_sha256": ev_sha if evidence_sha256 is None else evidence_sha256,
        "audit_started_sha256": sha,
        "independence": independence,
    }


def _r1c_ledger_json(rel: str, sha: str, audits: list[dict], **entry_kw) -> dict:
    """一条台账条目的 JSON。`authored` 默认 `unknown`（真台账里 16 条有 13 条是它）。

    为什么要显式给：`_entry` 的默认 `authored="ai-agent"` 会让
    `clean_audits` 里的 `need_independence` 为假 ⇒ `H-1e` 的独立性声明那一条
    无从适用（那是刻意的设计：署名者已知时它的独立性由 `c-16` 另行保证）。
    这一节要测独立性判据，所以夹具必须落在"署名者未知"这一档。
    """
    return _entry(rel, sha, audits=audits, authored="unknown", **entry_kw)


def _r1c_judge(root: Path, manifest: Path, rel: str, audits: list[dict], **entry_kw) -> dict:
    """把台账手写到盘上，再走真判定侧（`check_approvals`）读回来判。

    刻意不经过 `record_audit`：这一节要测的是判定侧的判据，而写入侧可能已经
    把某条攻击拒掉了（那样判定侧的读数就无从谈起）。手写台账是文档化的复跑方式。

    回执链也要建：机审通路在证据锚之外还有一层"只增链"（`check_receipt_chain`），
    链缺失会让整条通路判 `unknown` —— 那样测的就成了回执链，而不是这一节的判据。
    链用 `append_receipt()` 真的写一遍（手搓的链一旦与判据的规范化方式不一致，
    测的就是"我搓的对不对"）。
    """
    sha = G.sha256_file(root / rel)
    _write_ledger(root / G.LEDGER_NAME, [_r1c_ledger_json(rel, sha, audits, **entry_kw)])
    receipt_log = root / G.AUDIT_RECEIPT_NAME
    if receipt_log.exists():
        receipt_log.unlink()
    for a in audits:
        G.append_receipt(action="record_audit", path=rel, entry_sha256=sha,
                         detail=f"{a['auditor']}/{a['dimension']}",
                         log_path=receipt_log, root=root)
    result = G.check_approvals(
        [rel], manifest=manifest, root=root, ledger_path=root / G.LEDGER_NAME,
        receipt_log=receipt_log,
    )
    got = _approvals(result)[rel]
    got["_verdict"] = result.verdict
    got["_exit"] = result.exit_code
    return got


#: 把 `distinct_reviewers` 换回 改前形态（原始字符串比较）。
#: 它是 `R5-R1b-3` 的分辨力所在：`r.name not in out` 一处归一化都没有。
class _RawNameReviewers:
    def __init__(self, inner):
        self._inner = inner

    @property
    def distinct_reviewers(self):
        out: list[str] = []
        for r in self._inner.reviewers:
            if r.name not in out:          # ← 改前那一行，逐字
                out.append(r.name)
        return tuple(out)


#: 把 `normalize_subject` 换回 H-1a 之前的形态（不 NFKC、不去 Cf/Mn/Me）。
def _pre_h1a_normalize(name: str) -> str:
    return " ".join(str(name or "").split()).casefold()


#: 把 `normalize_subject` 换成"只去 Cf"（`H-1a` 之后、`R5-R1b-2` 之前）的形态。
def _cf_only_normalize(name: str) -> str:
    import unicodedata

    s = unicodedata.normalize("NFKC", str(name or ""))
    kept = [(" " if unicodedata.category(c) in ("Zs", "Zl", "Zp") else c)
            for c in s if unicodedata.category(c) != "Cf"]
    return " ".join("".join(kept).split()).casefold()


#: 把 `_identifiers_of` 换回 改前形态（纯词法扫描，关键字/内建名也算标识符）。
def _lexical_identifiers_of(text: str) -> set[str]:
    return {m.group(0) for m in re.finditer(r"[A-Za-z_][A-Za-z0-9_.]{2,}", text or "")}


def test_r1c_f2_distinct_reviewers_normalizes_name_collation(tmp_path: Path) -> None:
    """`R5-R1b-3`：同一个可见姓名的 4 种写法只能算 1 名 reviewer。

    正控：`reviewer-甲` / `ｒｅｖｉｅｗｅｒ－甲` / `reviewer-甲\\u200b` / `reviewer-甲 `（全角、
    零宽、尾空格）是同一个人 ⇒ `distinct_reviewers == 1` ⇒ 不批准。
    负控：把 `distinct_reviewers` 换回改前的原始字符串比较 ⇒ 同一条台账变成 3 名不同
    reviewer ⇒ 门打印"已有 3 名不同 reviewer 完成逐行走查"并 approved（改前实测形态）。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    sha = G.sha256_file(root / rel)
    names = ["reviewer-甲", "ｒｅｖｉｅｗｅｒ－甲", "reviewer-甲\u200b", "reviewer-甲 "]
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, sha, [_reviewer(n) for n in names])])
    got = _approvals(
        G.check_approvals([rel], manifest=manifest, root=root, ledger_path=root / G.LEDGER_NAME)
    )[rel]
    assert got["distinct_reviewers"] == 1, (
        f"4 种同形写法被算成 {got['distinct_reviewers']} 名 reviewer：{got['distinct_reviewers']}"
    )
    assert got["approval_status"] == "unapproved", got["detail"]
    assert got["approval_reason"] == G.REASON_FEW_REVIEWERS
    assert len(got["reviewers"]) == 4, "重复签名要照实保留（它是事实）"

    # ---- 负控：把那一行改回改前形态 ⇒ 攻击必须变绿（否则这条正控不是判据给的）
    real = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel)
    before = G.load_ledger(root / G.LEDGER_NAME)
    injected = _RawNameReviewers(before.entry_for(rel))
    # `_parse_reviewer` 会 strip 首尾空白 ⇒ 盘上第 4 条是 `reviewer-甲`（与第 1 条逐字相同），
    # 改前的原始字符串比较把全角那条与零宽那条算成另外两名 ⇒ 3 >= 2 ⇒ approved。
    assert injected.distinct_reviewers == (
        "reviewer-甲", "ｒｅｖｉｅｗｅｒ－甲", "reviewer-甲\u200b"
    ), "负控注入没生效：改前形态本应把同形写法算成多名"
    assert len(injected.distinct_reviewers) >= G.REQUIRED_APPROVALS_ON_HIT, (
        "负控注入没生效：改前形态本应达到批准门槛（3 >= 2）"
    )
    assert real is not None
    assert real.distinct_reviewers == ("reviewer-甲",), real.distinct_reviewers


def test_r1c_f3_normalize_subject_folds_combining_marks(tmp_path: Path) -> None:
    """`R5-R1b-2`：`Mn`/`Me`（变体选择符、组合用圈）必须被折掉。

    正控：`reaudit5-H` 与 `reaudit5-H`+`U+FE0F` / `+U+FE0E` / `+U+20E3` / `+U+0301`
    全部归一到同一个字符串。
    负控：把归一化换回 `H-1a` 之后、`R5-R1b-2` 之前的"只去 `Cf`"那一版 ⇒
    `reaudit5-H`+`U+FE0F` 与原名不相等 ⇒ 同一个可见名字算出 2 名审计者（改前实测形态）。
    """
    suffix_forms = ["\ufe0f", "\ufe0e", "\u20e3", "\u0301"]
    base = G.normalize_subject("reaudit5-H")
    plain = G.normalize_subject("ｒｅａｕｄｉｔ５-Ｈ\u200b ")   # 全角 + 零宽 + 尾空格
    for suf in suffix_forms:
        got = G.normalize_subject("reaudit5-H" + suf)
        assert got == base == plain, (
            f"U+{ord(suf):04X} 没被折掉：{got!r} != {base!r}"
        )

    keys = {G.normalize_subject("reaudit5-H" + s) for s in suffix_forms}
    keys.add(base)
    assert len(keys) == 1, keys

    # ---- 负控：注入"只去 Cf"的改前形态
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "normalize_subject", _cf_only_normalize)
        after = {G.normalize_subject("reaudit5-H" + s) for s in suffix_forms}
        after.add(G.normalize_subject("reaudit5-H"))
        assert len(after) == 5, (
            f"负控注入没生效：只去 Cf 的形态本应把它们算成 5 个不同名字，实际 {len(after)}"
        )
    # 再把它换回 H-1a 之前那一版（连 NFKC 都没有）
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "normalize_subject", _pre_h1a_normalize)
        assert G.normalize_subject("ｒｅａｕｄｉｔ５-Ｈ") != G.normalize_subject("reaudit5-H"), (
            "负控注入没生效：H-1a 之前那一版本应认不出全角同形字"
        )


def test_r1c_f3_reviewer_writer_requires_a_readable_name(tmp_path: Path) -> None:
    """`R5-R1b-3` 写入侧：姓名归一化后必须还剩一个可读字符。

    正控：中文姓名（人写的正常形态）写得进去；负控：只有一个零宽空格的"姓名"、
    以及纯标点姓名被拒（它们无法与匿名/同形噪声区分）。
    """
    root, manifest, rel = _make_sandbox(tmp_path)
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, G.sha256_file(root / rel))])
    assert G.main(["--approve", rel, "--reviewer", "张三", "--scope", "全文",
                   "--root", str(root), "--manifest", str(manifest)]) == 0
    for bad in ("\u200b", "···", "  \u200b  "):
        with pytest.raises(G.LedgerError) as exc:
            G.add_approval(G.load_ledger(root / G.LEDGER_NAME), rel,
                           reviewer=bad, scope="全文", root=root)
        assert "reviewer" in str(exc.value)
    assert G._reviewer_identity_problem("张三") == ""
    assert G._reviewer_identity_problem("\u200b") != ""


def test_r1c_f1_same_auditor_cannot_supply_all_dimensions(tmp_path: Path) -> None:
    """`R5-R1b-1` + `R6-R1d-4`：判据 0 守的是"一名审计者供给了太多计入维度"。

    它现在不只是挡"完全独占"：`R6-R1d-4` 把判定从 `len(owned) == len(dims)`
    改成 `len(owned) > max_share`（`max_share = max(1, (require+1)//2)`，`require = 3`
    时是 2）。所以 `SOLO` 那种一次供满 3 个维度的形态仍然被挡，而"2 名审计者各供 2 个
    维度"这种同样把门槛攥在一只手里的形态也开始被挡（那时文案说的是"供给了太多"，
    不是"独占"）—— 两者走同一个理由码。

    正控：3 名审计者各交 1 条、各一个维度 ⇒ approved（每人只供 1 个，远在上限内）。
    负控（攻击形态本身）：`SOLO` 交 3 条（3 个维度、3 份只差空格的证据副本，hash 各不相同）
    + `ONE` 交 1 条 ⇒ 修前实测 approved（`temp/reaudit5-R1b-solo.txt` 对照 B）。
    """
    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)

    def trio(prefix: str) -> list[dict]:
        """3 名不同审计者各 1 条，各占一个两两不相交的观察面（正控形态）。"""
        return [
            _r1c_audit(root, sha, auditor=f"{prefix}-{i}", dimension=d,
                       scope=_R1C_SCOPES[i], tag=f"{prefix}-{i}")
            for i, d in enumerate(("axes", "roles", "errors"))
        ]

    ok = _r1c_judge(root, manifest, rel, trio("r1c-OK"))
    assert ok["approval_status"] == "approved", ok["detail"]
    assert ok["distinct_auditors"] == 3 and len(ok["distinct_dimensions"]) == 3

    # 攻击形态：一名审计者独占 3 个维度（3 份只差尾部空格的证据副本、hash 各不相同）
    # + 另一名只交 1 条（`temp/reaudit5-R1b-solo.txt` 对照 B）
    attack = [
        _r1c_audit(root, sha, auditor="r1c-SOLO", dimension=d, scope="src/a.py alpha",
                   tag=f"SOLO-{d}")
        for d in ("axes", "roles", "errors")
    ] + [_r1c_audit(root, sha, auditor="r1c-ONE", dimension="docs",
                    scope="src/a.py alpha", tag="ONE-docs")]
    bad = _r1c_judge(root, manifest, rel, attack)
    assert bad["approval_status"] == "unapproved", bad["detail"]
    assert bad["approval_reason"] == G.REASON_DIMENSION_SURFACE, bad["approval_reason"]
    assert bad["_exit"] == 1, bad["_exit"]
    assert "同一名审计者" in bad["detail"], bad["detail"]

    # ---- 负控：判据本体（绕开真 CLI，直接在内存对象上跑）⇒ 撤掉判据 0 必须变空串
    solo = tuple(G.ReviewAudit(**a) for a in attack)
    assert G.dimension_independence_problem(solo, _REAL_TARGET_SRC) != "", (
        "判据本体没报出一名审计者独占全部维度"
    )
    real_fn = G.dimension_independence_problem

    def _without_rule_zero(audits, target_text, **kw):
        """改前形态：只按"不同 dimension 字符串"数，不问它们是不是同一双眼睛看的。"""
        return ""

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "dimension_independence_problem", _without_rule_zero)
        green = _r1c_judge(root, manifest, rel, attack)
    assert green["approval_status"] == "approved", (
        "负控注入没生效：撤掉维度独立性判据之后攻击本应被放行（改前形态）"
    )
    assert green["distinct_auditors"] == 2 and len(green["distinct_dimensions"]) == 4
    assert real_fn(solo, _REAL_TARGET_SRC) != ""


def test_r1c_f1_same_auditor_cannot_reuse_one_observation_surface(tmp_path: Path) -> None:
    """`R5-R1b-1` 的同族：同一名审计者的多条记录不许共用同一个观察面。

    攻击：`SOLO` 的 3 条记录标 3 个维度、但 `scope` 逐字相同（同一份观察复制）；
    另一名审计者补齐第 2 个名字 ⇒ 修前 approved（`temp/reaudit5-R1b-attack.py` 的 N4）。
    """
    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)
    # 攻击：`SOLO` 的 3 条标 3 个维度、`scope` 逐字相同（同一份观察复制）；
    # 另一名审计者补齐第 2 个名字 ⇒ 修前 approved（`reaudit5-R1b-attack.py` 的 N4）。
    #
    # `R6-R1d-4` 之后要摆成"判据 0 先放行、判据 1 才报红"的形态：判据 0 现在直接判
    # 一名审计者的贡献是否超过 `max_share`（`require=3` 时是 2），所以这里的形态是
    # P1 供 2 个维度（撞上限但不超）、P2 供 1 个 —— 判据 0 放行，报红的是
    # "P1 的两条记录共用同一个观察面"（判据 1）。若沿用"P1 独占 3 个维度"的老形态，
    # 报红的会是判据 0，这条用例就测不到判据 1 了（测成了别的东西而照样"绿"）。
    specs = [("axes", "src/a.py alpha"), ("roles", "src/a.py alpha"),
             ("errors", "src/a.py alpha")]
    audits = [
        _r1c_audit(root, sha, auditor="r1c-P1" if i < 2 else "r1c-P2",
                   dimension=d, scope=sc, tag=f"r1c-P{i}")
        for i, (d, sc) in enumerate(specs)
    ]
    got = _r1c_judge(root, manifest, rel, audits)
    assert got["approval_status"] == "unapproved", got["detail"]
    assert got["approval_reason"] == G.REASON_DIMENSION_SURFACE
    assert "共用了同一个观察面" in got["detail"], got["detail"]

    # 正控：同一批维度，但每条用两两不相交的 scope 落点 ⇒ 放行
    # （证明判据挡的是重复/相交，不是"一名审计者交多条"这件事本身）。
    # 三条要落在三名审计者身上：`R6-R1d-4` 之后判据 0 直接判"一名审计者供给了
    # 太多计入维度"（`require=3` 时上限 2），所以"一名审计者交 2 条"这种形态
    # 现在会被判红 —— 那不是判据挡错了，而是那正是它要挡的东西。
    ok_audits = [
        _r1c_audit(root, sha, auditor=f"r1c-Q{i}", dimension=d, scope=_R1C_SCOPES[i],
                   tag=f"ok-{i}")
        for i, d in enumerate(("axes", "roles", "errors"))
    ]
    ok = _r1c_judge(root, manifest, rel, ok_audits)
    assert ok["approval_status"] == "approved", ok["detail"]

    # ---- 负控：撤掉判据 1 ⇒ 攻击变绿
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "dimension_independence_problem", lambda *a, **k: "")
        green = _r1c_judge(root, manifest, rel, audits)
    assert green["approval_status"] == "approved", "负控注入没生效"


def test_r1c_f4_independence_must_be_a_statement(tmp_path: Path) -> None:
    """`R5-R1b-4`：`independence` 不能只判 non-empty（`--independence x` 曾经三条全过）。

    正控：一段真声明 ⇒ 该条计入清白审计。
    负控(1) 判定侧：把它换成 `x` ⇒ 三条全掉出 `clean_audits` ⇒ 门槛不够、不放行。
    负控(2) 写入侧：`record_audit` 直接拒写（两处共用 `_independence_problem`）。
    """
    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)
    good = [
        _r1c_audit(root, sha, auditor=f"r1c-I{i}", dimension=d, scope=_R1C_SCOPES[i],
                   tag=f"I{i}")
        for i, d in enumerate(("axes", "roles", "errors"))
    ]
    assert _r1c_judge(root, manifest, rel, good)["approval_status"] == "approved"

    for junk in ("x", "  x  ", "独立"):
        bad = [
            _r1c_audit(root, sha, auditor=f"r1c-J{i}", dimension=d,
                       scope=_R1C_SCOPES[i], independence=junk, tag=f"J{i}")
            for i, d in enumerate(("axes", "roles", "errors"))
        ]
        got = _r1c_judge(root, manifest, rel, bad)
        assert got["approval_status"] == "unapproved", f"{junk!r} 通过了：{got['detail']}"
        assert got["clean_audits"] == [], f"{junk!r} 竟然算清白审计"
    assert G._independence_problem("x") != ""
    assert G._independence_problem(_R1C_INDEP) == ""

    # 写入侧同一条判据（条目署名必须落在"未知"这一档，否则 `H-1e` 无从适用）
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, sha, authored="unknown")])
    ev_abs, _ = _r1c_evidence(root, "w", auditor="r1c-K1", sha256=sha,
                              scope="src/a.py alpha")
    _, info = G.record_audit(
        G.load_ledger(root / G.LEDGER_NAME), rel, auditor="r1c-K1", dimension="axes",
        evidence="temp/r1c-ev-w.txt", negative_control=_R1C_NC,
        evidence_path=ev_abs,
        scope="src/a.py alpha", audit_started_sha256=sha,
        independence=_R1C_INDEP, root=root, receipt_log=root / "r.jsonl",
    )
    assert info["clean_audits"] == 1
    with pytest.raises(G.LedgerError):
        G.record_audit(
            G.load_ledger(root / G.LEDGER_NAME), rel, auditor="r1c-K2", dimension="roles",
            evidence="temp/r1c-ev-w.txt", negative_control=_R1C_NC,
            evidence_path=ev_abs,
            scope="src/a.py alpha", audit_started_sha256=sha,
            independence="x", root=root, receipt_log=root / "r.jsonl",
        )
    # ---- 负控：撤掉判据（回到 bool(...strip())）⇒ `x` 必须重新变得"可通过"
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "_independence_problem", lambda text: "")
        assert G._independence_problem("x") == "", "负控注入没生效"


def test_r1c_f5_scope_must_name_a_real_symbol(tmp_path: Path) -> None:
    """`R5-R1b-5`：`scope` 的标识符必须是目标里真的定义过的符号，关键字/内建名不算。

    正控：`_identifiers_of(被审对象)` = `{alpha, beta, gamma, delta, total}`；
    `scope='src/a.py alpha'` 通过。
    负控：`scope='src/a.py import return int'` ⇒ 判据 3 报出、整体 `unapproved`；
    内存注入回改前的纯词法扫描 ⇒ 攻击词重新"落在目标上"（改前形态）。
    """
    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)
    idents = G._identifiers_of(_REAL_TARGET_SRC)
    assert idents == {"alpha", "beta", "gamma", "delta", "total"}, idents
    for kw in ("import", "return", "int", "def", "class", "for", "while"):
        assert kw not in idents, f"{kw} 不该算标识符"

    ok = _r1c_judge(root, manifest, rel, [
        _r1c_audit(root, sha, auditor=f"r1c-S{i}", dimension=d, scope=_R1C_SCOPES[i],
                   tag=f"S{i}")
        for i, d in enumerate(("axes", "roles", "errors"))
    ])
    assert ok["approval_status"] == "approved", ok["detail"]

    # 判据本体：关键字落点必须报红；目标文本读不到 ⇒ 标识符集合为空 ⇒ 也必须报红
    counted = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel).counted_audits
    assert G.dimension_independence_problem(counted, _REAL_TARGET_SRC) == ""
    assert G.dimension_independence_problem(counted, "") != ""

    atk = _r1c_judge(root, manifest, rel, [
        _r1c_audit(root, sha, auditor=f"r1c-W{i}", dimension=d, scope=sc, tag=f"W{i}")
        for i, (d, sc) in enumerate((("axes", "src/a.py import"),
                                     ("roles", "src/a.py return int"),
                                     ("errors", "src/a.py def class")))
    ])
    assert atk["approval_status"] == "unapproved", atk["detail"]
    assert atk["approval_reason"] == G.REASON_DIMENSION_SURFACE, atk["approval_reason"]
    assert "真实存在的标识符" in atk["detail"], atk["detail"]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "_identifiers_of", _lexical_identifiers_of)
        # 分辨力在"抽哪一类词"上：同一段源码，词法扫描把关键字算成标识符，`ast` 口径不算
        sample = "import math\n\n\ndef helper(a):\n    return int(a)\n"
        lex = _lexical_identifiers_of(sample)
        assert {"import", "def", "return", "int"} <= lex, (
            f"负控注入没生效：改前的纯词法扫描本应把这些关键字算成标识符（得到 {sorted(lex)}）"
        )
        assert "return" in G._identifiers_of(sample), "负控注入没生效（monkeypatch 未生效）"
    # 撤掉注入之后：`ast` 口径只认定义处的名字
    clean = G._identifiers_of(sample)
    assert {"helper", "a"} <= clean, clean
    assert not ({"import", "def", "return", "int"} & clean), (
        f"`_identifiers_of` 又把关键字/内建名算成标识符了：{sorted(clean)}"
    )


def test_r1c_f6_negative_control_must_say_what_was_seen(tmp_path: Path) -> None:
    """`R5-R1b-6`：四种空话必须被拒 —— 长度、标记词、比出来什么、不是重复填充。

    正控：写清"拿什么比 + 比出来什么"且够长的负控通过（`_R1C_NC`）。负控：四种空话逐条报出问题，且 `record_audit` 拒写。

    注意： 口径裁决②（2026-09-27）：长度下限 `NEGCTL_MIN_CHARS = 40` 恢复为必经之路。本函数一度为了让 `tests/test_noai_gate_audit_channel.py` 里那句
    13 字符的夹具负控（`'改前会报出 network'`）通过而移除了它 —— 那个理由不成立：那个测试文件今天已经有13 条红（根因是它的写入侧夹具没给 `--audit-scope`，与负控判据无关；
    实测把那个文件对着改前那一版 `noai_gate.py` 跑也是 13 failed）。为一个本来就在红的夹具放宽判据= 拿门的强度换一个假绿。 所以这里明确断言：13 字符的短句被拒，那是预期结果；
    专门修那个夹具的批次会把夹具连同样例一起改成合规写法。
    """
    assert G.negative_control_problem(_R1C_NC) == ""
    # 口径裁决②：短句被拒（长度门恢复了）—— 它是"预期"，不是回归
    short = "改前会报出 network"
    assert len(short) < G.NEGCTL_MIN_CHARS
    assert G.negative_control_problem(short) != "", (
        "13 字符的短句通过了 —— 长度下限被放宽了（口径裁决② 要求它必须是必经之路）"
    )
    assert "太短" in G.negative_control_problem(short)
    # 四种空话：长度够但内容不达标（缺"比出来什么"/是重复填充），或长度本来就不够
    for junk in ("negative " + "x" * 60,
                 "负控：（此栏无内容）" + "占位" * 20 + " 改前",
                 "改前" + "啊" * 60,
                 "改前" + "占位" * 30,
                 "n/a " + " " * 40 + " HEAD " + " " * 10,
                 "改前",
                 ""):
        assert G.negative_control_problem(junk) != "", f"空话通过了：{junk[:24]!r}"

    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)
    _write_ledger(root / G.LEDGER_NAME, [_entry(rel, sha)])
    with pytest.raises(G.LedgerError) as exc:
        G.record_audit(
            G.load_ledger(root / G.LEDGER_NAME), rel, auditor="r1c-N1", dimension="axes",
            evidence="temp/r1c-ev-w.txt", negative_control="改前" + "占位" * 30,
            evidence_path=_r1c_evidence(root, "w", auditor="r1c-N1", sha256=sha,
                                        scope="src/a.py alpha")[0],
            scope="src/a.py alpha", audit_started_sha256=sha,
            independence=_R1C_INDEP, root=root, receipt_log=root / "r.jsonl",
        )
    assert "negative-control" in str(exc.value)

    # ---- 负控：撤掉"比出来什么"这一条（回到只有长度 + 标记词的改前形态）⇒ 空话变绿
    def pre_r1c_nc(text: str) -> str:
        t = str(text or "").strip()
        if len(t) < G.NEGCTL_MIN_CHARS:
            return "太短"
        low = t.casefold()
        if not any(m.casefold() in low for m in G.NEGCTL_MARKERS):
            return "没有怎么比"
        return ""

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "negative_control_problem", pre_r1c_nc)
        for junk in ("negative " + "x" * 60,
                     "负控：（此栏无内容）" + "占位" * 20 + " 改前",
                     "改前" + "占位" * 30,
                     "改前" + "啊" * 60):
            assert G.negative_control_problem(junk) == "", (
                f"负控注入没生效：改前那条规则本应放过 {junk[:20]!r}"
            )
        # 改前那条规则也拒的形态：证明注入不是"什么都放过"
        assert G.negative_control_problem("n/a") != "", "改前那条规则本来也拒 `n/a`（太短）"


def test_r1c_f6_length_floor_is_restored() -> None:
    """钉住口径裁决②：长度下限 `≥40` 是必经之路，短负控被拒。

    本函数一度为了迁就 `tests/test_noai_gate_audit_channel.py` 里那句 13 字符的夹具负控
    而移除长度门；裁决② 判定那个理由不成立（那个文件今天已经有 13 条红，且与负控判据无关），
    要求恢复。这条用例是标尺：若有人再把长度门去掉，它会变红。
    """
    short = "改前会报出 network"
    assert len(short) == 13 and len(short) < G.NEGCTL_MIN_CHARS
    assert G.negative_control_problem(short) != "", "长度下限被去掉了（口径裁决② 要求保留）"
    assert "太短" in G.negative_control_problem(short)
    # 够长且内容达标 ⇒ 通过（正控）
    assert len(_R1C_NC) >= G.NEGCTL_MIN_CHARS
    assert G.negative_control_problem(_R1C_NC) == ""
    # 够长但内容不达标 ⇒ 仍然被拒（"门只加不减"）
    assert G.negative_control_problem("改前" + "啊" * 60) != ""
    assert G.negative_control_problem("negative " + "x" * 60) != ""


def test_r1c_f1_dimensions_must_lie_on_pairwise_disjoint_surfaces(tmp_path: Path) -> None:
    """口径裁决①：计数的维度必须落在两两不相交的观察面上。

    这条比"数不同的观察面字符串"强：`alpha beta` 与 `alpha` 是两个不同字符串、
    却相交（后者是前者的子集）⇒ 它们算一次观察、不算两次。

    攻击：4 个维度、2 名审计者，观察面是 `{alpha} {beta} {gamma} {alpha beta}`
    ⇒ 两两不相交的只有 3 个 < 4 个维度 ⇒ 必须不放行（修前 approved）。
    正控：同一批 (审计者, 维度)，每条一个不相交的落点 ⇒ approved。
    负控：内存里撤掉这条判据（回到只含判据 0/1 的改前形态）⇒ 攻击必须 approved。
    """
    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)

    def quartet(scopes: tuple[str, ...], label: str) -> list[dict]:
        # `tag` 里带 `label`：两批（攻击 / 正控）各自落到不同的证据文件上。
        # 否则第二批会把第一批的证据文件覆盖掉，判定侧按登记 hash 重算时对不上 ⇒ `unknown`，
        # 那样测的就成了"证据锚被覆盖"，而不是这一节的判据。
        return [
            _r1c_audit(root, sha, auditor="r1c-Q1" if i < 2 else "r1c-Q2",
                       dimension=d, scope=scopes[i], tag=f"{label}-{i}")
            for i, d in enumerate(("axes", "roles", "errors", "docs"))
        ]

    attack = quartet(("src/a.py alpha", "src/a.py beta",
                      "src/a.py gamma", "src/a.py alpha beta"), "atk")
    got = _r1c_judge(root, manifest, rel, attack)
    assert got["approval_status"] == "unapproved", got["detail"]
    assert got["approval_reason"] == G.REASON_DIMENSION_SURFACE, got["approval_reason"]
    assert "两两不相交" in got["detail"], got["detail"]
    counted = G.load_ledger(root / G.LEDGER_NAME).entry_for(rel).counted_audits
    # `R7-R1d-1`：这里显式传被审对象的文本 —— `R7-R1d-1` 之后"没有 target_text"
    # 不再是判定侧的口径（判定侧在任何分支都先读对象、按标识符过滤），而是"读不到对象"
    # 那一支的退路。而退路启用时本条自己的 `scope` 会被剔掉（`drop_self_scope`）⇒
    # 这个夹具里 `alpha`/`beta` 两条的 token 只出现在别条 scope 里、`gamma` 只出现在自己
    # 那条里 ⇒ 退路下的面集合与判定口径不是同一个。这个断言要钉的是判定口径，
    # 所以把文本传进去（读数是 3 —— 与本地那份合成对象的标识符集合一致）。
    assert G._disjoint_face_count(counted, _REAL_TARGET_SRC) == 3, \
        G._disjoint_face_count(counted, _REAL_TARGET_SRC)

    # 正控：同一批 (审计者, 维度)，四条各占一个不相交的落点 ⇒ approved
    ok = _r1c_judge(root, manifest, rel, quartet(_R1C_SCOPES, "ctl"))
    assert ok["approval_status"] == "approved", ok["detail"]
    assert ok["independent_observation_surfaces"] == 4, ok["independent_observation_surfaces"]

    # ---- 负控：把判据 2 撤掉（只留判据 0/1）⇒ 攻击必须变绿
    def without_rule2(audit_seq, target_text, **kw):
        counted2 = list(audit_seq)
        dims2 = {a.dimension for a in counted2}
        if len(dims2) <= 1:
            return ""
        by_aud: dict[str, set[str]] = {}
        for a in counted2:
            by_aud.setdefault(G.normalize_subject(a.auditor), set()).add(a.dimension)
        if len(dims2) > max(1, (G.MIN_DISTINCT_DIMENSIONS + 1) // 2):
            _owner, owned = max(by_aud.items(), key=lambda kv: len(kv[1]))
            if len(owned) == len(dims2):
                return "（改前形态）同一名审计者独占全部维度"
        by_surf: dict[str, list[str]] = {}
        for a in counted2:
            key = G._observation_key(a.scope)
            if key:
                by_surf.setdefault(G.normalize_subject(a.auditor), []).append(key)
        for who, keys in by_surf.items():
            if any(keys.count(k) > 1 for k in keys):
                return f"（改前形态）{who} 在同一观察面上重复"
        return ""

    real = G.dimension_independence_problem
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "dimension_independence_problem", without_rule2)
        green = _r1c_judge(root, manifest, rel, attack)
    assert green["approval_status"] == "approved", (
        f"负控注入没生效：撤掉判据 2 之后那条分摊攻击本应被放行："
        f"{green['approval_status']}/{green.get('approval_reason')} "
        f"{str(green.get('detail'))[:300]} "
        f"evidence={green.get('evidence_problems')}"
    )
    assert G.dimension_independence_problem is real, "注入没有还原（后面几条用例会受污染）"


def test_r1c_f7_at_must_be_parseable_and_not_from_the_future(tmp_path: Path) -> None:
    """`R5-R1b-7`：`at` 必须可解析、不许写在未来，而且判定侧要把它报出来。

    正控：正常时间戳 ⇒ 计入清白审计；判定输出里带 `audit_timestamps`。
    负控：手写一条 `at=2099` 的台账 ⇒ 该条掉出 `clean_audits`（门槛不够 ⇒ 不放行）；
    内存注入回"写了就信"的改前形态 ⇒ 它重新计入（改前实测形态）。
    """
    root, manifest, rel = _r1c_root(tmp_path)
    sha = G.sha256_file(root / rel)
    future = "2099-01-01T12:00:00+08:00"          # 远未来：不会因为跑测试的时刻而变
    assert G.audit_timestamp_problem("不是时间") != ""
    assert G.audit_timestamp_problem("") != ""
    assert G.audit_timestamp_problem(future) != ""
    # 用"注入的判定时刻"证明"未来"那一支真的在判，而不是碰巧被别的规则拒了
    ref = G._dt.datetime(2026, 9, 27, 0, 0, 0, tzinfo=G._dt.timezone(G._dt.timedelta(hours=8)))
    assert G.audit_timestamp_problem("2026-09-26T15:59:59Z", now=ref) == ""   # 早于 ref
    assert G.audit_timestamp_problem("2026-09-26T16:00:00Z", now=ref) == ""   # 恰等于 ref
    assert G.audit_timestamp_problem("2026-09-26T16:00:01Z", now=ref) != ""   # 晚于 ref = 未来
    assert G.audit_timestamp_problem("2026-09-27T00:00:01+08:00", now=ref) != ""
    try:
        _today = G.audit_timestamp_problem(
            G._dt.datetime.now().astimezone().replace(microsecond=0).isoformat())
    except Exception:   # pragma: no cover - 不该发生
        _today = "boom"
    assert _today == "", _today

    ok = _r1c_judge(root, manifest, rel, [
        _r1c_audit(root, sha, auditor=f"r1c-T{i}", dimension=d, scope=_R1C_SCOPES[i],
                   tag=f"T{i}")
        for i, d in enumerate(("axes", "roles", "errors"))
    ])
    assert ok["approval_status"] == "approved", ok["detail"]
    # `R6-R1d-3`：`audit_timestamps` 的元素从裸字符串变成"自报时间戳 + 门判了什么"
    # （每个元素带 `basis`/`gate_checked`），所以这里按元素的 `at` 取值 ——
    # 裸字符串形态会让读报告的人以为"谁在什么时候走查的"从此可核。
    assert [t["at"] for t in ok["audit_timestamps"]] == ["2026-09-27T00:00:00+08:00"] * 3, \
        ok["audit_timestamps"]
    assert all(t["basis"] == "self_reported" for t in ok["audit_timestamps"]), ok["audit_timestamps"]
    assert all("non_decreasing_order" in t["gate_checked"] for t in ok["audit_timestamps"]), \
        ok["audit_timestamps"]

    future_audits = [
        _r1c_audit(root, sha, auditor=f"r1c-F{i}", dimension=d, at=future,
                   scope=_R1C_SCOPES[i], tag=f"F{i}")
        for i, d in enumerate(("axes", "roles", "errors"))
    ]
    bad = _r1c_judge(root, manifest, rel, future_audits)
    assert bad["approval_status"] == "unapproved", bad["detail"]
    assert bad["_exit"] == 1
    assert bad["clean_audits"] == [], "未来时间戳的审计被算成了清白审计"
    assert bad["audit_timestamps"] == [], "未来时间戳的记录不该进『计数的那些』"
    # 判定侧确实读了这个字段：盘上那条记录的时间戳被它判成了不合格
    raw = [a.at for a in G.load_ledger(root / G.LEDGER_NAME).entry_for(rel).clean_audits]
    assert raw == [], raw
    ledger_ats = [a.at for a in G.load_ledger(root / G.LEDGER_NAME).entry_for(rel).audits]
    assert ledger_ats == [future] * 3, ledger_ats
    assert all(G.audit_timestamp_problem(x) for x in ledger_ats), "判定侧没读 `at`"

    # ---- 负控：把判定侧那条检查撤掉（改前形态：写了就信）⇒ 它们重新计入并放行
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(G, "audit_timestamp_problem", lambda at, **k: "")
        green = _r1c_judge(root, manifest, rel, future_audits)
    assert green["approval_status"] == "approved", (
        "负控注入没生效：撤掉时间戳判据之后那三条本应重新计入（改前实测就是 approved）"
    )
    assert len(green["clean_audits"]) == 3
    # 判据没被撤掉时输出里必须能看见这些时间戳（"判定侧要读它"的可观察形态）。
    # `R6-R1d-3`：元素现在是"自报时间戳 + 门判了什么"，所以按 `at` 取。
    assert [t["at"] for t in green["audit_timestamps"]] == [future] * 3



