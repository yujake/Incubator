"""`tools/run_each_test_file.py` 的判据：逐文件起进程、按文件报红、没查成不是过。

这一节钉的是 G-27：审计期实测某个文件单独跑 6 failed，而全量里全过 —— 绿灯是排序给的。
所以本门的存在意义是"把排序给的那部分收回去"，而它自己必须满足两件事：

1. 一个文件一条命令、一个进程（`test_each_file_runs_in_its_own_process` 用假测试文件
   的"导入期互斥标记"实测这一点：合并成一次 pytest 调用会让第二个文件在收集期就看到第一个
   的标记而报错）；
2. 单文件红必须点名到文件，不许只给一个总数。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "run_each_test_file.py"


def _load():
    spec = importlib.util.spec_from_file_location("_run_each_test_file_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load()

#: 一个必然通过的文件 / 一个必然失败的文件。内容刻意最小：这一节测的是跑法，不是测试本身。
_PASSING = "def test_ok():\n    assert True\n"
_FAILING = "def test_bad():\n    assert False, 'boom'\n"

#: 导入期互斥标记：每个假测试文件在收集期先检查有没有别的文件已经跑过。
#: 一个进程一个文件 ⇒ 永远看不到别人的标记；被合并成一次调用 ⇒ 第二个文件立刻看到。
_MUTEX = '''
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ME = _HERE.parent / (".ran-" + Path(__file__).name)
_OTHERS = sorted(p.name for p in _HERE.parent.glob(".ran-*") if p.name != _ME.name)
assert not _OTHERS, f"同一个进程里还跑了 {_OTHERS}"
_ME.write_text("1", encoding="utf-8")


def teardown_module(module):  # pytest 钩子：本文件跑完就擦掉自己的标记
    _ME.unlink(missing_ok=True)


def test_placeholder():
    assert True
'''


def _fake_root(tmp_path: Path, *, names: list[str], body: str = _PASSING) -> Path:
    root = tmp_path / "fake"
    (root / "tests").mkdir(parents=True)
    for name in names:
        (root / "tests" / f"test_{name}.py").write_text(body, encoding="utf-8")
    return root


def test_list_prints_exactly_one_command_per_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """`--list`：每个文件一条命令，命令里只出现那一个文件（这是"逐文件"的字面证据）。"""
    root = _fake_root(tmp_path, names=["alpha", "beta"])
    assert R.main(["--root", str(root), "--list"]) == 0
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len(lines) == 2, lines
    for line, name in zip(lines, ("alpha", "beta")):
        assert f"tests/test_{name}.py" in line or f"tests\\test_{name}.py" in line, line
        assert "-m pytest" in line
        assert line.count(".py") == 1, f"一行里出现了多个文件，不是逐文件：{line}"


def test_all_passing_files_give_zero(tmp_path: Path) -> None:
    """正控：都过 ⇒ 0。"""
    root = _fake_root(tmp_path, names=["alpha", "beta"])
    assert R.main(["--root", str(root), "-q"]) == 0


def test_one_failing_file_is_named_and_fails_the_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """负控：一个过、一个不过 ⇒ 1，并且点名那个不过的文件（不许只给总数）。"""
    root = _fake_root(tmp_path, names=["alpha"])
    (root / "tests" / "test_beta.py").write_text(_FAILING, encoding="utf-8")
    assert R.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "test_beta.py" in out, out
    assert "单独跑不过 1" in out, out
    assert "排序给的" in out, out


def test_missing_tests_dir_is_unknown_not_pass(tmp_path: Path) -> None:
    """负控（三态）：没有 `tests/` ⇒ 2（没查成），不是 0。"""
    empty = tmp_path / "nosuch"
    empty.mkdir()
    assert R.main(["--root", str(empty), "-q"]) == 2


def test_empty_tests_dir_is_unknown_not_pass(tmp_path: Path) -> None:
    """负控（三态）：`tests/` 在但一个 `test_*.py` 都没有 ⇒ 2，不是 0。

    这条防的是"发现集为空 ⇒ 全过"那种真空通过（P16 族）。
    """
    root = tmp_path / "fake"
    (root / "tests").mkdir(parents=True)
    assert R.main(["--root", str(root), "-q"]) == 2


def test_each_file_runs_in_its_own_process(tmp_path: Path) -> None:
    """本门的核心断言：一个文件一个进程。

    假测试文件在收集期检查"有没有别的文件已经在这个进程里跑过"（互斥标记）。
    逐文件起进程 ⇒ 每个文件都看不到别人的标记 ⇒ 全过、退 0。
    若有人把本门改成"一次 pytest 跑完整个目录"，第二个文件会在收集期断言失败 ⇒ 本用例变红。
    """
    root = _fake_root(tmp_path, names=["alpha", "beta"], body=_MUTEX)
    code = R.main(["--root", str(root), "-q"])
    assert code == 0, "逐文件起进程时不该有任何互斥标记冲突"
    assert not list((root).glob(".ran-*")), "每个文件的标记都该在它自己的 teardown 里被擦掉"


def test_exit_5_with_deselected_is_not_a_failure() -> None:
    """负控（本门接进 `release_all` 第一次就抓到的假红）：用例全被 marker 筛掉不是失败。

    实测：`tests/test_providers_online.py` 的用例全带 `network` 标记，而默认
    `-m "not network"` ⇒ pytest `exit=5`、汇总行 `8 deselected in 0.08s`。
    第一版把它记成"单独跑不过"，于是发布检查多了一条假红。
    """
    status, detail = R.classify_pytest_result(5, "8 deselected in 0.08s\n")
    assert status == "deselected", (status, detail)


def test_exit_5_without_deselected_means_the_file_has_no_tests() -> None:
    """负控（三态）：`exit=5` 且没有 `deselected` ⇒ 这个文件空了 ⇒ 判没查成，不许读过。"""
    status, detail = R.classify_pytest_result(5, "no tests ran in 0.01s\n")
    assert status == "no_tests", (status, detail)


def test_classify_pytest_result_basics() -> None:
    """正控：0 ⇒ ok；断言失败/收集错误 ⇒ fail（两条都不许被上面的特例吃掉）。"""
    assert R.classify_pytest_result(0, "12 passed in 0.4s")[0] == "ok"
    assert R.classify_pytest_result(1, "1 failed, 11 passed in 0.4s")[0] == "fail"
    assert R.classify_pytest_result(2, "ERROR collecting x.py")[0] == "fail"


# ============================================================ `I-2`：整文件被跳过不许报绿


def test_exit_0_with_only_skipped_is_all_skipped_not_ok() -> None:
    """负控（`I-2` 核心）：`exit=0` + 汇总行只有 `skipped` ⇒ 不是 ok。

    改前这一格返回 `("ok", "1 skipped in 0.01s")` —— 于是"给用例加一个 skip"
    就能把一个文件整文件消音，而门报绿。
    """
    status, detail = R.classify_pytest_result(0, "1 skipped in 0.01s\n")
    assert status == "all_skipped", (status, detail)


def test_a_partially_skipped_file_is_still_ok() -> None:
    """正控（别把判据做成"有 skip 就红"）：`14 passed, 1 skipped` ⇒ 仍然 `ok`。

    `tests/test_agent_e_formal_path.py` 就是这一形态：它确实跑了 14 条、
    跳了 1 条（本机 PATH 上没有 lean 检查器）。判据要的是"有没有 passed"，
    不是"有没有 skipped" —— 后者会把一个正常的文件判红（假红比假绿好，但它仍是错的）。
    """
    assert R.classify_pytest_result(0, "14 passed, 1 skipped in 2.81s")[0] == "ok"
    assert R.classify_pytest_result(0, "3 passed, 2 skipped in 0.14s")[0] == "ok"


def test_exit_0_with_no_passed_and_no_skipped_is_no_tests() -> None:
    """边界：`exit=0` 却既没 passed 也没 skipped ⇒ 归到"一个用例都没有"那一档。"""
    assert R.classify_pytest_result(0, "no tests ran in 0.01s")[0] == "no_tests"


# ============================================================ `R6-7`：整文件 xfail


#: 一个整文件 xfail 的假测试文件：用例确实在，但每一条都被标了"预期失败"。
#: pytest 对它的汇总行是 `1 xfailed in ...`、退出码 0 —— 一个用例都没真过。
_XFAIL_ONLY = '''import pytest


@pytest.mark.xfail(reason="登记为已知缺陷（桩）", strict=False)
def test_expected_to_fail():
    assert False, "boom"
'''


def test_a_whole_file_xfail_file_is_never_read_as_ok() -> None:
    """正控（`R6-7` 的安全侧）：整文件 xfail 绝不许被读成 `ok`。

    pytest 对"全 xfail"的文件给 `exit=0`，汇总行是 `1 xfailed in ...`：
    一个用例都没真过，却配着一个成功退出码。所以第一条判据是它不属于 `ok`，
    第二条是原始汇总行必须留痕（判据要能看到证据，而不是只看到一个桶名）。
    """
    status, detail = R.classify_pytest_result(0, "1 xfailed in 0.01s\n")
    assert status != "ok", (status, detail)
    assert "xfailed" in detail, detail


def test_a_file_that_really_passed_alongside_an_xfail_is_still_ok() -> None:
    """对照（别把判据做成"有 xfail 就红"）：`1 passed, 1 xfailed` ⇒ 仍然 `ok`。

    与上面 `test_a_partially_skipped_file_is_still_ok` 同一个道理：判据要问的是
    "有没有真的 passed"，不是"有没有 xfail"。把后者当成红会让正常的文件变假红。
    """
    assert R.classify_pytest_result(0, "1 passed, 1 xfailed in 0.31s")[0] == "ok"


def test_the_xfail_only_bucket_is_its_own_registered_state() -> None:
    """`R6-7` 工具侧（本批修好）：整文件 xfail 单列一档 `all_xfail`，措辞不许说"一个用例都没有"。

    这一条原来钉的是改前形态（`status == "no_tests"`），而它的 docstring 逐字
    写着"修法落在 `tools/run_each_test_file.py`，不归本批次；哪天它改了，这条会红，
    逼人回来改成新桶名" —— 本批就是那一天。改前的缺陷有两半：

    1. 桶错了：`no_tests` 的语义是"这个文件一个用例都没有"，而整文件 xfail 的文件
       用例在、只是都被标成了预期失败；
    2. 措辞错了：`main()` 对 `no_tests` 打印"文件里一个用例都没有"，
       并把它算进 `[per-file] … 一个用例都没有 M` 那一栏。

    安全侧没有丢：`all_xfail` 仍然走退出码 2（没查成），绝不是过 ——
    由下面的端到端用例钉住。
    """
    status, detail = R.classify_pytest_result(0, "1 xfailed in 0.01s\n")
    assert status == "all_xfail", (
        "整文件 xfail 必须单列一档（`R6-7`）；桶名若再变，请同步更新这里与 `draft/28`"
    )
    assert "一个用例都没有" not in detail, (
        "分类器不该把那句话写进 detail：那句话由 main() 生成，要改的是那一档"
    )


def test_the_xfail_only_bucket_is_not_read_as_skipped() -> None:
    """负控（`R6-7` 的分档边界）：`1 xfailed` 不许被上面那条 `skipped` 分支吃掉。

    注入形态：汇总行里同时出现 `xfailed` 与 `skipped`（pytest 真的会这么打），
    这时必须优先报"整文件 xfail/xpass" —— 那句话对两个形态都成立，
    而"被跳过"只对一半成立（另外一半是"预期失败"）。
    """
    status, _ = R.classify_pytest_result(0, "1 xfailed, 1 skipped in 0.01s\n")
    assert status == "all_xfail", status


def test_xpass_only_is_also_the_xfail_bucket() -> None:
    """同族：整文件 `xpassed`（预期失败却通过了）同样不是"过"，也入这一档。

    它比 xfail 更该被人看：那说明"登记为已知缺陷"的判据其实已经成立，
    而文件还在说自己坏着（`strict=False` 不会让它红）。
    """
    status, _ = R.classify_pytest_result(0, "1 xpassed in 0.02s\n")
    assert status == "all_xfail", status


def test_a_whole_file_xfail_file_makes_the_gate_unknown_not_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """端到端负控（`R6-7`）：整文件 xfail ⇒ 退出码 2，且输出里绝不许说"一个用例都没有"。

    改前这一跑的逐文件行是
    `[????] tests/test_xfailonly.py  1 xfailed in 0.22s` + 一行
    "文件里一个用例都没有（不是过，也不许当没看见）" —— 后半句对它是假话：
    用例在，只是都被标成了预期失败。读报告的人会去查一个不存在的问题。

    判据只打"这个文件自己那一行"：汇总栏里"一个用例都没有 0"是另一档的桶名
    （0 个文件落在那一档），把它一起禁掉就变成一条会误伤的断言。
    """
    root = _fake_root(tmp_path, names=["xfailonly"], body=_XFAIL_ONLY)
    code = R.main(["--root", str(root), "-q"])
    out = capsys.readouterr().out
    assert code == 2, out
    own = [ln for ln in out.splitlines() if "test_xfailonly.py" in ln]
    assert own, out
    assert any("整文件 xfail" in ln for ln in own), own
    assert not any("一个用例都没有" in ln for ln in own), own
    assert "过 0" in out, out


def test_an_unexempted_all_skipped_file_fails_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控（端到端）：100% 被 skip 的文件不在豁免名单里 ⇒ 整体退出码 2。

    改前这一跑是 `[ok  ] tests/test_allskip.py  1 skipped in 0.01s` + exit 0
    （`draft/28` 的 `I-2` 逐字记了这个对抗性负控）。
    """
    root = _fake_root(
        tmp_path, names=["allskip"],
        body='import pytest\npytestmark = pytest.mark.skip(reason="对抗性负控")\n\n\n'
             "def test_guard_that_would_fail_if_it_ran():\n    assert False\n",
    )
    assert R.main(["--root", str(root)]) == 2
    out = capsys.readouterr().out
    assert "不在" in out and "EXEMPT_ALL_SKIPPED" in out, out


def test_the_same_file_passes_once_it_really_runs(tmp_path: Path,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    """负控 2（成对写）：把那个 skip 去掉、让它真跑且失败 ⇒ 必报 `FAIL` 且退 1。

    没有这一条，"一律退 2"也能让上一条通过 —— 那就把"跳过"与"真的不过"混成一档了。
    """
    root = _fake_root(
        tmp_path, names=["allskip"],
        body="def test_guard_that_really_runs():\n    assert False\n",
    )
    assert R.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "[FAIL]" in out, out


def test_the_known_exempt_file_is_still_allowed() -> None:
    """正控：真仓库里那个"全被 marker 筛掉"的文件必须仍被判 `deselected`。

    它是 `EXEMPT_ALL_SKIPPED` 里唯一一条（联网回归测试，默认不出网是设计），
    而豁免的意义正是"保留这个形态、并把它写下来"。
    """
    assert "tests/test_providers_online.py" in R.EXEMPT_ALL_SKIPPED
    net = REPO / "tests" / "test_providers_online.py"
    status, detail = R.run_one(REPO, net, 60.0)
    assert status == "deselected", (status, detail)


def test_every_exemption_carries_a_reason() -> None:
    """登记表自己的判据（`R6-1` 之后走 `audit_exemptions`，不再在测试里重写一遍）。

    旧版这一条只断言"理由 ≥ 20 字符"，而这正是重审报的那个缺陷的形状：
    约束太弱 ⇒ 往表里加一行凑够 20 个字符就能把一个整文件被跳过的目录从
    `exit 2` 变回 `exit 0`。现在三条判据（上限 / 存在 / 理由有实质）在被测模块里
    只有一份实现，这里只断言"真仓库的表通过它"。
    """
    problems, notes = R.audit_exemptions(root=REPO)
    assert problems == [], problems
    assert notes == [], notes  # 真仓库里那个豁免文件必须在盘上
    for rel in R.EXEMPT_ALL_SKIPPED:
        assert rel.startswith("tests/") and rel.endswith(".py"), rel


def test_adding_a_second_exemption_is_refused_by_the_gate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`R6-1` 负控：往豁免表里加一行必须让门停下（`exit 2`），而不是静默放行。

    这一条的形态就是重审实测的那条绕过路径：`temp/` 副本里加一条名字
    ⇒ 同一个 allskip 目录由 `exit 2` 变成 `exit 0`。现在加一行会先撞
    `MAX_EXEMPT_ALL_SKIPPED`，门以"没查成"（2）退出并说明原因。
    """
    root = _fake_root(tmp_path, names=["allskip"],
                      body='import pytest\npytestmark = pytest.mark.skip(reason="负控")\n\n\n'
                           "def test_would_fail():\n    assert False\n")
    monkeypatch.setitem(R.EXEMPT_ALL_SKIPPED, "tests/test_allskip.py",
                        "凑够二十个字符的一段理由，提到 skip 的形态")
    assert R.main(["--root", str(root), "-q"]) == 2
    err = capsys.readouterr().err
    assert "MAX_EXEMPT_ALL_SKIPPED" in err, err
    assert "没查成" in err, err


def test_an_exemption_with_a_hollow_reason_is_refused() -> None:
    """`R6-1` 负控之二：理由必须说清"为什么整文件会被筛掉"（三个关键词之一）。

    只判长度是不够的：`"x" * 25` 能过长度、过不了这一条。
    """
    problems, _notes = R.audit_exemptions(
        {"tests/test_providers_online.py": "x" * 25}, root=REPO)
    assert any("为什么整文件会被筛掉" in p for p in problems), problems
    problems2, _ = R.audit_exemptions(
        {"tests/test_providers_online.py": "太短"}, root=REPO)
    assert any("字符" in p for p in problems2), problems2


def test_the_classifier_and_the_exemption_audit_are_the_only_places_that_decide() -> None:
    """正控（口径唯一）：真仓库的表过判据、且 `discover` 与 pytest 的收集口径一致。

    "两处各写一套"是本项目反复记过的形态：这一条把"表自己合不合规"指向
    `audit_exemptions`、把"哪些文件要跑"指向 `discover` —— 两个都只有一份实现。
    """
    assert R.audit_exemptions(root=REPO)[0] == []
    assert R.discover(REPO) == sorted(p for p in (REPO / "tests").rglob("test_*.py")
                                      if p.is_file())


def test_a_nested_failing_test_file_makes_the_gate_red(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`R6-2` 负控：`tests/sub/` 里的失败用例必须让门变红。

    旧版 `discover` 只 `glob` 顶层，而 `pyproject.toml` 的 `testpaths=["tests"]`
    是递归的 ⇒ 实测同一个 root：逐文件门 exit 0，`pytest` 是 `1 failed`。
    门绿而仓库红，正是本门立项要抓的形态。
    """
    root = _fake_root(tmp_path, names=["ok"])
    sub = root / "tests" / "sub"
    sub.mkdir(parents=True)
    (sub / "test_nested.py").write_text(_FAILING, encoding="utf-8")
    assert R.main(["--root", str(root)]) == 1
    out = capsys.readouterr().out
    assert "test_nested.py" in out, out


def test_a_nested_passing_test_file_is_discovered_and_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """正控（别把递归做成假红）：`tests/sub/` 里的通过用例仍必须整体 `exit 0`。

    没有这一条，"一律退 1"也能让上一条通过。
    """
    root = _fake_root(tmp_path, names=["ok"])
    sub = root / "tests" / "sub"
    sub.mkdir(parents=True)
    (sub / "test_nested.py").write_text(_PASSING, encoding="utf-8")
    assert R.main(["--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "共 2 个文件" in out, out


def test_a_file_with_no_tests_makes_the_gate_unknown_not_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """负控：某个文件真的一点用例都没有 ⇒ 整体 2（没查成），不是 0。"""
    root = _fake_root(tmp_path, names=["ok"])
    (root / "tests" / "test_empty.py").write_text("VALUE = 1\n", encoding="utf-8")
    assert R.main(["--root", str(root)]) == 2
    out = capsys.readouterr().out
    assert "一个用例都没有" in out, out


def test_the_real_network_file_is_reported_as_deselected_not_failed() -> None:
    """集成负控：真仓库里那个"全被 marker 筛掉"的文件必须报 `deselected`。

    这条直接对着发布检查里那条假红，而且便宜（该文件被筛掉，约 0.1 秒）。
    """
    net = REPO / "tests" / "test_providers_online.py"
    assert net.is_file(), "前提：这个文件存在"
    status, detail = R.run_one(REPO, net, 60.0)
    assert status == "deselected", (status, detail)


def test_list_covers_the_real_test_suite() -> None:
    """正向：对真仓库 `--list` 时，发现到的文件集合与目录里的一致（不是只看了一部分）。

    判据刻意不写"至少 N 个"这种魔法阈值：文件数会随开发变化，
    而"发现集 == 目录里的 `test_*.py` 全集"才是这条门该守的东西。
    `R6-2` 之后这一条用 `rglob`（与 pytest 的 `testpaths=["tests"]` 一样递归），
    所以"全集"也必须按递归口径算 —— 旧版这里写的是顶层 `glob`，
    于是它和被测实现一起错（两边同错 ⇒ 用例恒绿，是典型的假正控）。
    """
    real = sorted(p for p in (REPO / "tests").rglob("test_*.py") if p.is_file())
    assert real, "真仓库的 tests/ 下没有 test_*.py，说明这个用例的前提不成立"
    assert R.discover(REPO) == real
    assert "test_" in " ".join(R.pytest_argv(real[0]))
    # 本用例自己也是被发现的一个文件（自指检：路径形态与 `--list` 的输出形态一致）
    assert any(p.name == "test_run_each_test_file.py" for p in real)
