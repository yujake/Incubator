"""`tools/release_all.py`（一键发布检查的编排层）的测试。

## 这个文件在测什么

编排层是发布门能不能被绕过的地方，所以它的判据必须是硬的。三条最重要的：

1. `unknown` 有独立的出口：解释器起不来 / 超时 ⇒ `unknown`，不是 `fail`、更不是 `pass`。
   （"没跑成"与"跑了发现问题"混起来，会让人去修一个并不存在的缺陷，
   或者更糟 —— 把"没跑成"读成"通过"。）
2. `--skip` 的步骤记成 `unknown` 而不是 `pass` —— 这是本脚本最重要的一条取舍。
   记成 `pass` 会让 `--skip acceptance` 变成"发布门全绿"的捷径。
3. 总判定的优先级：任一 `fail` ⇒ `fail`；否则任一 `unknown` ⇒ `unknown`；全 `pass` ⇒ `pass`。

## 为什么这些测试不跑真的发布检查

真的发布检查要 10~15 分钟（全量测试 + 验收 + 论文复现）。测试不去跑它 ——
那会把套件从 3 分钟变成 15 分钟，而"慢的门最后会被跳过"。
这里测的是判定逻辑（`classify` / `overall` / 跳过语义），
真的端到端由 `python tools/release_all.py` 在发布时跑（并在报告里贴输出）。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "release_all.py"


def _load():
    spec = importlib.util.spec_from_file_location("_release_all_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load()


# ============================================================ classify：三态


def test_classify_pass_and_fail():
    """正向：退出码 0 ⇒ `pass`；非 0 ⇒ `fail`。"""
    assert R.classify(0, started=True, timed_out=False) == "pass"
    assert R.classify(1, started=True, timed_out=False) == "fail"
    assert R.classify(2, started=True, timed_out=False) == "fail"


def test_classify_timeout_is_unknown_even_when_exit_code_looks_like_a_failure():
    """负控（最关键的一条）：超时 ⇒ `unknown`，哪怕拿到的退出码是 1。

    Windows 上被强杀的进程常以 `1` 收场，与"检查发现问题"的 `1` 无法区分。
    所以 `timed_out` 必须先于退出码判断 —— 否则"超时"会被报成"检查失败"，
    而人会去修一个并不存在的缺陷（或者反之：把超时当通过）。
    """
    assert R.classify(1, started=True, timed_out=True) == "unknown"
    assert R.classify(0, started=True, timed_out=True) == "unknown"


def test_classify_not_started_is_unknown_not_fail():
    """负控：进程根本没起来（解释器不在 / 路径不存在）⇒ `unknown`。"""
    assert R.classify(None, started=False, timed_out=False) == "unknown"
    assert R.classify(1, started=False, timed_out=False) == "unknown"


def test_classify_missing_exit_code_is_unknown():
    """负控：拿不到退出码 ⇒ `unknown`（不是 0、也不是 1）。"""
    assert R.classify(None, started=True, timed_out=False) == "unknown"


# ============================================================ 每步自己的码表


def test_tri_state_step_maps_two_to_unknown_not_fail():
    """负控（本轮的真实缺陷）：自带三态的步骤返回 2 ⇒ 必须是 `unknown`，不是 `fail`。

    `scripts/release_check.py` 自带 `0=pass / 1=fail / 2=unknown`。本编排层的第一版
    把所有非零退出码一律判成 `fail`，于是 release-check 返回 2（在这个环境里它必然
    返回 2 —— 第 6 项禁 AI 区门因为"不是 git 仓库"永远是 `unknown`）时，
    编排层报的是 `fail`："没查成"被读成了"发现问题"。

    这条缺陷发生在"用来挡住这类错误的那一层"里 —— 所以它值得一条专门的测试。
    """
    step = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO, exit_map=R.TRI_STATE_EXIT)
    assert R.classify(0, True, False, step) == "pass"
    assert R.classify(1, True, False, step) == "fail"
    assert R.classify(2, True, False, step) == "unknown"     # ← 关键
    assert R.classify(3, True, False, step) == "fail"        # 未声明的码仍是出问题


def test_plain_step_treats_two_as_fail():
    """负控：普通脚本（只声明 `0 = pass`）返回 2 ⇒ `fail`（不许把它当"没查成"）。"""
    step = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO, exit_map=R.PLAIN_EXIT)
    assert R.classify(0, True, False, step) == "pass"
    assert R.classify(2, True, False, step) == "fail"


def test_timeout_beats_the_exit_map():
    """负控：超时 ⇒ `unknown`，与码表无关（进程没跑完，退出码没有意义）。"""
    step = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO, exit_map=R.PLAIN_EXIT)
    assert R.classify(1, True, True, step) == "unknown"
    assert R.classify(0, True, True, step) == "unknown"


def test_real_steps_declare_an_exit_map_matching_their_tool():
    """正向：四个自带三态的工具必须用 `TRI_STATE_EXIT`，普通脚本用 `PLAIN_EXIT`。

    这条把"每个步骤的码表"钉成可审阅的事实 —— 加新步骤时若忘了声明，
    默认的 `{0: pass}` 会把它的 `2` 判成 `fail`（保守方向，但会误报），
    而这条测试会提醒人"你确定这个工具的 2 是 fail 吗"。
    """
    steps = {s.key: s for s in R.build_steps(REPO)}
    assert steps["release-check"].exit_map == R.TRI_STATE_EXIT
    assert steps["role-specs"].exit_map == R.TRI_STATE_EXIT
    assert steps["coverage"].exit_map == R.TRI_STATE_EXIT
    assert steps["acceptance"].exit_map == R.PLAIN_EXIT
    assert steps["repro"].exit_map == R.PLAIN_EXIT


# ============================================================ overall：优先级


def _mk(verdict: str):
    step = R.Step("k", "t", [sys.executable, "-c", "pass"], cwd=REPO)
    return R.Result(step, verdict, None, 0.0, [])


def test_overall_all_pass_is_pass():
    """正向：全 `pass` ⇒ `pass`。"""
    assert R.overall([_mk("pass"), _mk("pass")]) == "pass"


def test_overall_fail_dominates_unknown():
    """负控：有 `fail` 也有 `unknown` ⇒ `fail`（阻断的理由优先）。"""
    assert R.overall([_mk("unknown"), _mk("fail")]) == "fail"
    assert R.overall([_mk("fail"), _mk("pass")]) == "fail"


def test_overall_unknown_without_fail_is_unknown_not_pass():
    """负控（三态的核心）：只有 `unknown`、没有 `fail` ⇒ `unknown`，不是 `pass`。

    这是本项目反复踩过的那个坑：把"没检查"与"检查过了没问题"折叠成同一个"通过"。
    """
    assert R.overall([_mk("pass"), _mk("unknown")]) == "unknown"


def test_overall_empty_is_pass_only_because_there_is_nothing_to_fail():
    """边界：空列表 ⇒ `pass`。并说明它为什么不是缺陷：

    `main()` 不会在没有任何步骤时走到这里（`build_steps` 永远返回非空），
    所以空列表在真实路径上不可达；写这条断言是为了把"这个边界的含义"固定下来 ——
    它表示"没有可失败的项"，而不是"检查过了"。
    """
    assert R.overall([]) == "pass"


def test_exit_codes_are_three_valued():
    """三个结论对应三个不同的退出码（`pass`=0 / `fail`=1 / `unknown`=2）。"""
    assert R.VERDICT_EXIT == {"pass": 0, "fail": 1, "unknown": 2}


# ============================================================ 端到端：跳过语义


def test_cli_skip_is_recorded_as_unknown_and_exit_code_is_two(tmp_path):
    """负控（端到端）：`--skip` 掉一个步骤 ⇒ 该步记 `unknown` ⇒ 退出码 2，不是 0。

    这条测的是"发布门不能被 `--skip` 绕过"。若哪天有人把跳过记成 `pass`，
    这条会红 —— 而它是唯一能抓住那个改动的测试。
    """
    out = tmp_path / "r.json"
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--skip", "acceptance,repro,release-check,coverage",
         "--json", str(out)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    by_key = {s["key"]: s["verdict"] for s in data["steps"]}
    assert by_key["acceptance"] == "unknown"
    assert data["verdict"] == "unknown"


def test_cli_unknown_step_key_is_rejected_with_exit_two():
    """负控：给一个不存在的步骤 key ⇒ 退出码 2（不是 0）。

    "拼错了一个 key"必须与"跑过了没问题"分得开 —— 否则 `--only lint` 打错成
    `--only lin` 会变成一次静默的空跑。
    """
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--only", "lin"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    assert "未知的步骤 key" in (p.stdout + p.stderr)


def test_cli_only_role_specs_passes_and_leaves_the_rest_unknown(tmp_path):
    """正向：`--only role-specs` ⇒ 该步 `pass`，其余记 `unknown` ⇒ 总判定 `unknown`（退出码 2）。

    这正是我们要的：一次只跑一项的调试动作不构成发布检查的绿色结论。
    """
    out = tmp_path / "r.json"
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--only", "role-specs", "--json", str(out)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    by_key = {s["key"]: s["verdict"] for s in data["steps"]}
    assert by_key["role-specs"] == "pass"
    assert by_key["release-check"] == "unknown"
    assert data["verdict"] == "unknown"


# ============================================================ 步骤表与禁改区


def test_step_table_covers_exactly_the_six_named_checks():
    """正向：用户点名的那六项都必须在步骤表里被覆盖。

    用户逐字要求的是"全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter"。
    `scripts/release_check.py` 一次覆盖其中五项，唯独没有验收测试 ——
    这正是本脚本存在的理由。这条断言把"验收测试确实被编排进来了"钉住。
    """
    keys = {s.key for s in R.build_steps(REPO)}
    assert {"release-check", "acceptance", "repro", "role-specs", "coverage"} <= keys
    titles = " ".join(s.title for s in R.build_steps(REPO))
    for needed in ("全量测试", "全部自检", "verify", "工具普查", "linter", "验收测试"):
        assert needed in titles, f"步骤表里没有覆盖 {needed}"


def test_release_all_is_registered_in_the_noai_manifest():
    """正向（也是负控）：`tools/release_all.py` 必须在 `.noai-paths` 里登记。

    它决定"跳过的步骤记成 `unknown` 还是 `pass`" —— 那一条取舍就是
    "发布门能不能被绕过"。发布门自身必须在禁改区里，否则改宽它不需要人审。
    这条断言防的是"有人新建了一个发布门但忘了登记"。
    """
    manifest = (REPO / ".noai-paths").read_text(encoding="utf-8")
    assert "tools/release_all.py" in manifest
    assert "release-deploy" in manifest


def test_every_step_declares_a_working_directory_that_exists():
    """正向：每个步骤的 `cwd` 必须真实存在。

    一个不存在的 `cwd` 会让 `subprocess.run` 抛 `OSError` ⇒ 该步 `unknown`。
    那是正确的结论，但"因为路径写错所以永远 unknown"是一种静默失效
    （门看起来在跑，永远给不出结论），所以在这里直接断言路径存在。
    """
    missing = [s.key for s in R.build_steps(REPO) if not s.cwd.is_dir()]
    assert not missing, f"这些步骤的工作目录不存在：{missing}"
    argv0 = [s.key for s in R.build_steps(REPO) if not Path(s.argv[1]).exists()]
    assert not argv0, f"这些步骤的入口文件不存在：{argv0}"
