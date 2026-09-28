"""`scripts/release_check.py` 的逐项判据测试（`c-10` / `c-11` / `c-12` / `D9` / `H-5` / `H-6`）。

## 这个文件在测什么

发布门本身的行为由 `tests/test_release_check_noai.py` 覆盖（第 6 项）。这里补的是
其余几项在 `draft/28` 里被点名的缺口，每条都带「能证明注入生效」的负控：

- `c-10`：`--skip` 的重复 / 逗号 / 空格三种写法必须等价（argparse 对同名选项是「覆盖」）；
- `c-11`：产物路径的回退分支「不许」落在仓库里（`.release-lint.json` 被 git 跟踪）；
- `c-12`：`--json` 产物必须是「纯 LF」（`Path.write_text` 在 Windows 上刷 CRLF）；
- `D9`：模块自检的四条判据与 docstring 表第 2 行一一对应；
- `H-5`：`Report.overall()` 的空 `items` 必须是 `unknown`（不是 `pass`）；
- `H-6`：`item_linter` 必须走 `--strict`，且 error / warning 分开读。

## 为什么这些测试不去跑真的那八项

真跑一次发布门要十几分钟。这里的用例只碰判据本身（`_parse_skip_values` /
`_artifact_path` / `_read_lint_counts` / `_selftest_verdict` / `Report.overall` /
`item_linter`），要跑子进程时也只用「桩树」（临时目录里的几行 python）或直接
`--skip` 全部八项（等于只测记账与产物，不跑检查）。
"""

from __future__ import annotations

import argparse
import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import release_check as RC

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "release_check.py"
ALL_ITEMS = ("tests", "selftests", "tools", "verify", "lint", "noai", "contract", "imports")


def _lint_tree(root: Path, files: dict[str, str]) -> None:
    """在 `root` 下造一棵桩树（`write_text(..., newline="")`：判据本身不许引入 CR）。"""
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8", newline="")


#: 桩 `lint_rules.py` 树里必须有的几个文件与它们的理由（三处 `--root` 调用共用）：
#:
#: - `scripts/keep.py` 要「自带三档退出码」，否则 R008 会报 error；
#: - `.noai-paths` 是 R009 判定禁改区用的（桩树里没有它 ⇒ R009 报一条 error
#:   "禁改区清单读不到"）；
#: - 豁免表里的 `tools/make_demo_dataset.py` 必须存在（登记指向不存在的文件会报 info，
#:   而"登记过期"这件事本身就是 R012 要说的话，不该混进别的用例）。
_STUB_KEEP_PY = ('"""k。"""\n\n\ndef main():\n    return 0\n\n\n'
                 'if __name__ == "__main__":\n    raise SystemExit(main())\n')


def _reference_lint_tree(root: Path, src_body: str) -> None:
    _lint_tree(root, {
        "src/agentflow/m.py": src_body,
        "scripts/keep.py": _STUB_KEEP_PY,
        ".noai-paths": (REPO / ".noai-paths").read_text(encoding="utf-8"),
        "tools/make_demo_dataset.py": (REPO / "tools" / "make_demo_dataset.py").read_text(
            encoding="utf-8"),
    })


# ============================================================ c-10：--skip 的三种写法


def test_skip_three_spellings_are_equivalent_through_real_argparse():
    """正控（`c-10`）：重复 flag / 逗号分隔 / 空格分隔三种写法解析出同一个集合。

    改前的实测（`temp/auditC-05-skip-bypass.txt` 第一段）：
    `parse_args(["--skip","x","--skip","y"]).skip == ["y"]` —— 按最自然的重复写法
    传 7 个 `--skip` 时只有最后一个生效，「其余七项真的跑了」。

    这里用与生产文件「逐字一致」的那两行定义来解析（另有
    `test_skip_definition_in_the_real_file_is_append_plus_nargs` 守住"逐字一致"本身）。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", action="append", nargs="+", default=[], metavar="KEY")

    repeated = ap.parse_args(["--skip", "a", "--skip", "b"]).skip
    comma = ap.parse_args(["--skip", "a,b"]).skip
    spaced = ap.parse_args(["--skip", "a", "b"]).skip
    got = {frozenset(RC._parse_skip_values(x)) for x in (repeated, comma, spaced)}
    assert got == {frozenset({"a", "b"})}, (
        f"三种写法必须等价，实测：重复={repeated} 逗号={comma} 空格={spaced}"
    )


def test_negative_control_the_old_nargs_star_would_break_repeated_flags():
    """负控（`c-10`）：把定义换回 `nargs="*"` ⇒ "重复 flag" 与 "空格分隔" 不再等价。

    这条测的不是产物、而是「解析层本身」：它证明上面那条正控不是恒真 ——
    `nargs="*"` 下重复给只保留最后一次，两种写法结果不同。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip", nargs="*", default=[])
    old_repeated = ap.parse_args(["--skip", "a", "--skip", "b"]).skip
    old_spaced = ap.parse_args(["--skip", "a", "b"]).skip
    assert old_spaced == ["a", "b"]
    assert old_repeated == ["b"], f"旧写法的覆盖行为变了：{old_repeated}"
    assert old_spaced != old_repeated, "旧写法下两种写法本来就不同 —— 这正是 c-10 的缺陷"


def test_skip_definition_in_the_real_file_is_append_plus_nargs():
    """正控（`c-10`）：真实文件里的 `--skip` 必须同时是 `action="append"` 与 `nargs="+"`。

    `nargs="+"` 是「兼容旧写法」的那一半：只给 `append` 时 `--skip a b` 会让 argparse
    把 `b` 当成非法位置参数（可见的用法错误，但仍是破坏）。
    """
    text = SCRIPT.read_text(encoding="utf-8")
    block = text.split('"--skip",', 1)[1].split(")\n", 1)[0]
    assert 'action="append"' in block, block
    assert 'nargs="+"' in block, block
    assert 'nargs="*"' not in block, block


def test_cli_skip_all_eight_items_reports_unknown(tmp_path):
    """正控（`c-10` 的端到端）：用「重复 flag」 写法跳过全部八项 ⇒ 退出码 2、八项全 unknown。

    改前这种写法只让最后一项生效，于是其余七项真的跑了（那一次的报告里
    "跳过"两个字也几乎不出现）。
    """
    out = tmp_path / "skipped.json"
    argv = [sys.executable, str(SCRIPT)]
    for key in ALL_ITEMS:
        argv += ["--skip", key]
    argv += ["--json", str(out)]
    p = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    assert p.returncode == 2, p.stdout[-600:] + p.stderr[-600:]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["counts"]["skipped"] == 8, data["counts"]
    assert data["counts"]["pass"] == 0 and data["counts"]["fail"] == 0
    assert set(data["skipped"]) == set(ALL_ITEMS), data["skipped"]


# ============================================================ c-11：产物回退不许落在仓库里


def test_artifact_path_prefers_the_ignored_temp_dir(monkeypatch, tmp_path):
    """正控（`c-11`）：正常路径是 `GATE_ARTIFACT_DIR`（被 `.gitignore` 排除的 `temp/`）。"""
    monkeypatch.setattr(RC, "GATE_ARTIFACT_DIR", tmp_path / "temp")
    artifact, why = RC._artifact_path()
    assert artifact == tmp_path / "temp" / "release-lint.json"
    assert why == ""


def test_artifact_path_fallback_never_lands_in_the_repo(monkeypatch):
    """正控（`c-11`）：`GATE_ARTIFACT_DIR` 建不出来 ⇒ 回退到「系统临时目录」，不在仓库里。

    改前的回退是 `REPO_ROOT / ".release-lint.json"`，而那个文件「被 git 跟踪」
    （`git ls-files --error-unmatch agentflow/.release-lint.json` 实测成功）——
    于是回退分支下"跑一次门就改一次仓库状态"，而"本次改动集"正是禁改区门的输入。
    """
    monkeypatch.setattr(RC, "GATE_ARTIFACT_DIR", REPO / "no-such-dir" / "\0bad")
    artifact, why = RC._artifact_path()
    assert artifact.name == "release-lint.json"
    assert REPO not in artifact.parents, f"回退产物落在仓库里了：{artifact}"
    assert "临时目录" in why, why
    # 直接点名旧路径：回退结果不许是它
    assert artifact != REPO / ".release-lint.json"


def test_the_old_fallback_path_really_is_tracked_by_git():
    """负控（`c-11`）的「前提」：旧回退路径确实被 git 跟踪（否则这条缺陷不成立）。

    这条直接问 git，不依赖源码里有没有那个字符串 —— 它证明的是"注入有判别力"：
    如果哪天这个文件不再被跟踪，那么"不许回退到它"这条判据的对象就换了，
    必须回来重新校准（所以这里在"不再被跟踪"时也要求看得见的结论，不是静默跳过）。
    """
    p = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "agentflow/.release-lint.json"],
        cwd=str(REPO.parent), capture_output=True, text=True,
    )
    assert p.returncode == 0, (
        "`agentflow/.release-lint.json` 不再被 git 跟踪了 —— `c-11` 的负控对象变了，"
        f"请重新校准（git 说：{p.stdout!r}{p.stderr!r}）"
    )
    assert "agentflow/.release-lint.json" in p.stdout


def test_item_linter_artifact_is_outside_the_repo_for_the_real_run():
    """正控（`c-11`）：跑一次真的 `item_linter` ⇒ 它落下的产物路径不在仓库里。

    这一条会真的跑一遍全仓 linter（几秒钟），所以它同时是 `H-6` 的正控：
    `strict` / `strict_command_has_flag` 必须为真。
    """
    rep = RC.Report()
    it = RC.item_linter(rep)
    artifact = Path(it.detail["artifact"])
    assert REPO not in artifact.parents, artifact
    assert it.detail.get("strict") is True, it.detail
    assert it.detail.get("strict_command_has_flag") is True, it.detail


# ============================================================ c-12：产物必须是纯 LF


def test_negative_control_write_text_would_leave_crlf_on_this_platform(tmp_path):
    """负控（`c-12`）：在「本平台」上 `Path.write_text` 确实会写出 CRLF。

    先证明"注入有判别力"（这条负控真的能红），上面那条正控才有意义：
    如果这个平台上 `write_text` 本来就不刷 CRLF，`c-12` 的判据就是恒真的。
    两种写法在这里各跑一遍，方向必须相反。
    """
    if sys.platform != "win32":
        pytest.skip("这一条只有 Windows 上才有判别力")
    a = tmp_path / "via_write_text.txt"
    a.write_text("x\ny\n", encoding="utf-8")
    b = tmp_path / "via_open_newline.txt"
    with open(b, "w", encoding="utf-8", newline="") as fh:
        fh.write("x\ny\n")
    assert b"\r\n" in a.read_bytes(), (
        "`Path.write_text` 在这台机器上没有刷 CRLF ⇒ 这条负控没有判别力，"
        "请重新校准 `c-12`（换个注入方式）"
    )
    assert b"\r" not in b.read_bytes(), 'open(newline="") 的产物里出现了 CR'


def test_linter_json_artifact_is_pure_lf(tmp_path):
    """正控（`c-12`）：`lint_rules.py --json` 的产物「逐字节纯 LF」（不含 CR）。

    桩树里放一份「真的」`tools/make_demo_dataset.py` 副本：豁免登记是全局表，
    而"登记指向的文件在不在"是逐 root 判的 —— 不放它，R012 会因为
    "豁免登记指向一个不存在的文件"报一条 `info`（那是它该说的话，
    但本用例只关心产物的字节）。
    """
    tree = tmp_path / "tree"
    _reference_lint_tree(
        tree,
        '"""m。"""\n\n\ndef f(x):\n    """做事。\n\n    为什么：因为需要。\n    """\n    return x\n',
    )
    out = tmp_path / "lint.json"
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "lint_rules.py"), "--root", str(tree),
         "--json", str(out)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    raw = out.read_bytes()
    assert b"\r" not in raw, f"产物里有 CR（{raw.count(chr(13).encode())} 处）⇒ 不是纯 LF"


def test_release_check_json_artifact_is_pure_lf_when_every_item_is_skipped(tmp_path):
    """正控（`c-12`）：发布门自己的 `--json` 产物也是纯 LF。

    做法：把八项「全部 `--skip`」（于是不跑检查、只走记账与写文件那条路径），
    然后断言写出来的文件里没有 CR。这同时覆盖了 `c-10` 的记账口径。
    """
    out = tmp_path / "release.json"
    argv = [sys.executable, str(SCRIPT), "--json", str(out)]
    for key in ALL_ITEMS:
        argv += ["--skip", key]
    p = subprocess.run(argv, cwd=str(REPO), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=300)
    assert p.returncode == 2, p.stdout[-600:] + p.stderr[-600:]
    raw = out.read_bytes()
    assert b"\r" not in raw, f"发布门产物里有 CR（{raw.count(chr(13).encode())} 处）⇒ 不是纯 LF"
    assert b"\n" in raw


# ============================================================ D9：模块自检的四条判据


def test_selftest_verdict_has_a_branch_for_every_documented_criterion():
    """正控（`D9`）：四条分支各自给一个输入，返回四种不同的结论。

    改前的 docstring 只写"全部退出码 0"，漏了 `has_selftest` 那一支；
    实现比文档严，是文档该改 —— 但改完之后必须有判据把两处铆住。
    """
    assert RC._selftest_verdict(True, True, False, 0) == "pass"
    assert RC._selftest_verdict(True, True, False, 1) == "fail"
    assert RC._selftest_verdict(True, False, False, None) == "unknown"
    assert RC._selftest_verdict(True, True, True, 0) == "unknown"
    # 最关键的一支：没有自检块 ⇒ unknown（「不是」 pass）
    assert RC._selftest_verdict(False, True, False, 0) == "unknown"
    assert RC._selftest_verdict(False, False, False, None) == "unknown"


def test_negative_control_deleting_the_has_selftest_branch_changes_the_answer():
    """负控（`D9`）：删掉 `has_selftest` 那一支 ⇒ "没有自检块"会被读成 pass。

    这里把「旧实现的判据」写在一个局部函数里（它只少那一支），
    然后断言两者的结论「不同」 —— 差异本身就是"注入生效"的证据。
    """
    def old_verdict(started: bool, timed_out: bool, exit_code: int | None) -> str:
        if not started or timed_out:
            return "unknown"
        if exit_code != 0:
            return "fail"
        return "pass"

    assert old_verdict(True, False, 0) == "pass"        # 旧的错法：没有自检块也 pass
    assert RC._selftest_verdict(False, True, False, 0) == "unknown"


def test_selftest_verdict_source_contains_the_no_selftest_branch():
    """负控（`D9`）：`has_selftest` 那一支必须「在实现里」，不能只在文档里。

    这条直接读源码文本：删掉 `if not has_selftest: return "unknown"`，
    断言立刻红（只删 docstring 里的说明不会让它红 —— 两个注入方向是分开的）。
    """
    src = inspect.getsource(RC._selftest_verdict)
    assert "has_selftest" in src, src
    assert src.count('"unknown"') >= 2, src
    assert 'return "pass"' in src and 'return "fail"' in src, src


def test_selftest_criteria_are_named_in_the_module_docstring():
    """正控（`D9`）：四条判据必须逐条在模块 docstring 里有落点（与 `SELFTEST_CRITERIA` 对应）。

    八项表第 2 行的判据栏写的是那一段的「摘要」：改前漏掉的那一条
    （`no_selftest_block`）必须「逐字」写在那一行里；另外三条以
    `反引号 + 判据名 + 反引号` 的形式逐条点名。两处都是机器可查的 ——
    改判据而不同步文档，这条就红。
    """
    doc = RC.__doc__ or ""
    rows = [ln for ln in doc.splitlines() if ln.startswith("| 2 |")]
    assert rows, "八项表里找不到第 2 行（模块自检）"
    row = rows[0]
    assert RC.SELFTEST_CRITERIA[0][1] in row, (
        f"docstring 第 2 行没有逐字写上改前漏掉的那一条判据：{RC.SELFTEST_CRITERIA[0][1]!r}"
    )
    assert "自检块" in row and "unknown" in row, row
    # 四条判据「逐条点名」：判据名写在模块级常量、它的注释块与 `item_selftests`
    # 的 docstring 里（`inspect.getsource` / `__doc__` 都读得到），三处一起查。
    names_blob = (doc
                  + inspect.getsource(RC)
                  + (RC._selftest_verdict.__doc__ or "")
                  + (RC.item_selftests.__doc__ or ""))
    for key, _phrase in RC.SELFTEST_CRITERIA:
        assert f"`{key}`" in names_blob, f"源码/注释/docstring 里都没有点名判据名 {key}"


# ============================================================ H-5：空 items ⇒ unknown


def test_report_overall_empty_items_is_unknown_not_pass():
    """正控（`H-5`）：`Report().overall()` 在空 `items` 上必须给 `unknown`。

    改前给 `"pass"`（"三项计数都是 0 ⇒ 其余 ⇒ pass"），而姊妹实现
    `tools/release_all.py::verdict_from_subitems([])` 返回 `None`（没查成）——
    两份"逐字相同"的实现只在非空时相同，空集这一档的交叉防线整个失效。
    """
    assert RC.Report(items=[], skipped=[]).overall() == "unknown"
    assert RC.Report().overall() == "unknown"


def test_report_overall_non_empty_combinations_unchanged():
    """正控（`H-5`）：非空组合的优先级不许被这次修改带偏。"""
    def mk(v: str) -> RC.Item:
        return RC.Item(key="k", title="t", verdict=v)

    assert RC.Report(items=[mk("pass")]).overall() == "pass"
    assert RC.Report(items=[mk("pass"), mk("pass")]).overall() == "pass"
    assert RC.Report(items=[mk("pass"), mk("unknown")]).overall() == "unknown"
    assert RC.Report(items=[mk("pass"), mk("fail")]).overall() == "fail"
    assert RC.Report(items=[mk("unknown"), mk("fail")]).overall() == "fail"
    assert RC.Report(items=[mk("pass")], skipped=["tests"]).overall() == "unknown"


def test_negative_control_the_old_empty_branch_would_return_pass():
    """负控（`H-5`）：旧实现（不区分空表，最后一行 `return "pass"`）会给 `pass`。

    不复制一份实现当探针：这里把「那条被否掉的结论」直接写出来，
    断言它与今天的结论不同 —— 差异即"注入生效"。
    """
    old_behaviour = "pass"  # 旧实现：counts 全 0 ⇒ return "pass"
    assert RC.Report().overall() != old_behaviour, (
        "空表又回到 pass 了 —— `H-2`/`H-5` 的修法被撤掉了"
    )


def test_report_to_dict_note_matches_the_empty_table_verdict():
    """正控（`H-5`）：报告正文（`note`）必须与总判定同口径，不许正文比总判定乐观。"""
    d = RC.Report().to_dict()
    assert d["overall"] == "unknown"
    assert "一项都没有判到" in d["note"], d["note"]


# ============================================================ H-6：严格档 + error/warning 分开读


def test_lint_rules_prints_error_warning_info_counts_on_a_stub_tree(tmp_path):
    """正控（`H-6`）：`lint_rules.py --strict` 的 JSON 里 error 与 warning 是两栏。

    这是 `item_linter` 读计数的前提：它必须能分开读，而不是只看退出码。
    """
    # 桩树见 `_reference_lint_tree`（`scripts/keep.py` 的三档退出码、`.noai-paths`、
    # 豁免表里那个文件都在，否则 R008/R009/R012 会各报一条与本用例无关的 finding）。
    tree = tmp_path / "tree"
    _reference_lint_tree(tree, '"""m。"""\n\n\ndef f(x):\n    return x\n')
    out = tmp_path / "lint.json"
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "lint_rules.py"), "--root", str(tree),
         "--strict", "--json", str(out)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["error_count"] == 0, data["errors"]
    assert data["warning_count"] >= 1, "桩树上的缺 docstring 必须在严格档下成为 warning"
    assert p.returncode == 1, "严格档下 warning 非空 ⇒ 退出码 1（这正是不能只看退出码的原因）"


def test_read_lint_counts_reads_both_columns(tmp_path):
    """正控（`H-6`）：`_read_lint_counts` 把 error 与 warning 「分开」读回来。"""
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"error_count": 0, "warning_count": 39, "info_count": 20}),
                 encoding="utf-8")
    assert RC._read_lint_counts(p) == {"error_count": 0, "warning_count": 39, "info_count": 20}


def test_read_lint_counts_returns_none_when_unreadable(tmp_path):
    """负控（`H-6`）：读不到 / 结构不对 ⇒ `None`（调用方必须记 unknown，不许猜）。"""
    assert RC._read_lint_counts(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"error_count": "zero"}), encoding="utf-8")
    assert RC._read_lint_counts(bad) is None
    bad.write_text("not json", encoding="utf-8")
    assert RC._read_lint_counts(bad) is None


def test_item_linter_notes_carry_the_strict_warning_count():
    """正控（`H-6`）：跑一次真的 `item_linter` ⇒ notes 里必须出现严格档的 warning 数。

    linter 全仓扫描一次只要几秒；这条同时证明 `--strict` 真的被传下去，
    以及"error=0 而 warning 非空"这一档在报告里有名字、有计数。
    """
    rep = RC.Report()
    it = RC.item_linter(rep)
    assert it.detail.get("strict") is True, it.detail
    assert it.detail.get("strict_command_has_flag") is True, it.detail
    assert isinstance(it.detail.get("warning_count"), int), it.detail
    blob = " ".join(it.notes)
    assert "warning" in blob, blob
    assert "严格档" in blob, blob
    if it.detail["error_count"] == 0:
        assert it.verdict == "pass", (it.verdict, it.notes)
    else:
        assert it.verdict == "fail", (it.verdict, it.notes)


# ============================================================ REAUDIT2-R1-3：尾注不许说谎

#: 在任何一档下都「不许」出现的措辞（除了 pass 档那句明确限定范围的说法之外）。
#:
#: 注意判据的「粒度」：要打的是"宣称这八项/全部项都通过了"这个「说法本身」，
#: 不是"通过"这两个字。有一段解释性的句子「引用」了旧措辞（『这一句不写
#: 「这八项检查都通过了」』），它恰恰是在说明"本次没有"，所以只按整句匹配。
_FORBIDDEN_TAIL_WORDING = (
    "overall=pass 只说明这八项",
    "只表示这八项检查都通过了",
    "八项都通过，",
    "这八项都通过了，不构成",
)

_RUNNER_ATTRS = {
    "tests": "item_test_suite",
    "selftests": "item_selftests",
    "tools": "item_tool_census",
    "verify": "item_verify",
    "lint": "item_linter",
    "contract": "item_contract",
    "imports": "item_imports",
}


def _stub_all_items(monkeypatch, verdicts: dict[str, str]) -> None:
    """把八个 runner 换成「已定档的假项」（键名与 `_main` 里一致），不动判据本身。"""
    for key, attr in _RUNNER_ATTRS.items():
        verdict = verdicts[key]

        def make(v: str, k: str):
            def fn(rep: RC.Report) -> RC.Item:
                return rep.add(RC.Item(k, f"{k} 标题", v, {}, []))
            return fn

        monkeypatch.setattr(RC, attr, make(verdict, key))
    monkeypatch.setattr(RC, "item_noai",
                        lambda rep, changed, **kw: rep.add(
                            RC.Item("noai", "禁 AI 区门", verdicts["noai"], {}, [])))


_ALL_PASS = {k: "pass" for k in ("tests", "selftests", "tools", "verify", "lint",
                                 "noai", "contract", "imports")}
_ALL_FAIL = {k: "fail" for k in _ALL_PASS}
_WITH_UNKNOWN = {**_ALL_PASS, "tests": "unknown", "noai": "unknown"}


def test_negative_control_a_failing_run_never_claims_all_eight_passed(tmp_path, capsys,
                                                                     monkeypatch):
    """正控 + 负控（`REAUDIT2-R1-3`）：尾注必须按「实际 overall」 分流。

    改前（HEAD 版）的两处尾注（`Report._note()` 与 `main()` 的收尾打印）只在
    `skipped` 上分流：`skipped == 0` 时不论 overall 是 `fail` 还是 `unknown`，
    都逐字写"overall=pass 只说明这八项检查都通过了"。重审者的实测是
    "八项全 fail ⇒ 输出仍挂着那句'只说明这八项都通过了'"。

    这条用例把八项换成「已定档的假项」再走真 `main()`，对三种档位分别断言：
    违禁措辞一个字都不许出现，且尾注必须点出本次实际的 pass/fail/unknown 计数。
    把任一处尾注改回"只看 skipped"的旧写法 ⇒ 这条立刻红。
    """
    cases = {
        "pass": (_ALL_PASS, 0, "PASS"),
        "fail": (_ALL_FAIL, 1, "FAIL"),
        "unknown": (_WITH_UNKNOWN, 2, "UNKNOWN"),
    }
    seen: dict[str, str] = {}
    for label, (verdicts, want_rc, want_word) in cases.items():
        _stub_all_items(monkeypatch, verdicts)
        out = tmp_path / f"{label}.json"
        # `release_check.main` 没有 `-q`（那是编排层 `release_all` 的开关），
        # 所以这里只给 `--json`：反正输出被 capsys 收走，不会淹掉测试输出。
        rc = RC.main(["--json", str(out)])
        captured = capsys.readouterr()
        blob = captured.out + captured.err
        seen[label] = "".join(ln for ln in blob.splitlines() if "总判定" in ln)
        assert rc == want_rc, f"{label} 档退出码应为 {want_rc}，实测 {rc}；输出：{blob[-400:]}"
        assert want_word in seen[label], seen[label]
        for bad in _FORBIDDEN_TAIL_WORDING:
            assert bad not in blob, (
                f"{label} 档的输出里出现了违禁措辞 {bad!r}（`REAUDIT2-R1-3`）：\n{blob[-500:]}"
            )
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["overall"] in {"pass", "fail", "unknown"}
        assert data["overall"] == label, (
            f"JSON 的总判定与桩的档位不符：{data['overall']!r} != {label!r}"
        )
        note = data["note"]
        assert note, "报告必须有 note"
        for bad in _FORBIDDEN_TAIL_WORDING:
            assert bad not in note, f"JSON 的 note 里有违禁措辞 {bad!r}：{note[:200]}"
        if label != "pass":
            # 非 pass 档必须「说清本次的事实」（而不是宣称全过）
            assert "本次" in note, note
            assert ("没通过" in note) or ("没查成" in note) or ("一项都没有判到" in note), note
        # 另一条路径：`_note()` 与 `main()` 的尾注必须「同口径」（两处都改过才有意义）
        rep = RC.Report(items=[RC.Item(k, k, v) for k, v in verdicts.items()])
        assert rep._note() == note, (
            "`Report._note()` 与 `main()` 打印的尾注分家了：\n"
            f"note={note[:160]!r}\nmain={blob[-160:]!r}"
        )
    # 探针自校：三种档位确实被判成了三种不同的 overall（否则上面比的是同一个空壳）
    assert len({v.split("总判定")[-1][:8] for v in seen.values()}) == 3, seen


def test_note_for_a_failing_run_names_the_failure_not_a_pass():
    """正控（`REAUDIT2-R1-3`）：`_note()` 在 fail / unknown 档各说各的，且都点出计数。

    与上一条的分工：那条走「整条 CLI」（含 `main()` 的收尾打印），这条直接测
    `Report._note()`（`--json` 里那个 `note` 字段的本体）。
    """
    def mk(v: str) -> RC.Item:
        return RC.Item(key="k", title="t", verdict=v)

    fail_note = RC.Report(items=[mk("fail"), mk("pass")])._note()
    for bad in _FORBIDDEN_TAIL_WORDING:
        assert bad not in fail_note, (bad, fail_note)
    assert "本次有 1 项" in fail_note and "没通过" in fail_note, fail_note
    unknown_note = RC.Report(items=[mk("unknown"), mk("pass")])._note()
    for bad in _FORBIDDEN_TAIL_WORDING:
        assert bad not in unknown_note, (bad, unknown_note)
    assert "unknown" in unknown_note and "没查成" in unknown_note, unknown_note
    pass_note = RC.Report(items=[mk("pass")])._note()
    assert "本次跑到的那 1 项" in pass_note, pass_note
    # 三种档位的 note 必须互不相同（"按实际 overall 分流"的可判定形式）
    assert len({fail_note, unknown_note, pass_note}) == 3
