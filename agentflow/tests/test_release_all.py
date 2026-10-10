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

import ast
import contextlib
import importlib.util
import inspect
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

#: 内层发布门。引它进来只为一条交叉断言（`H-5`）：编排层与发布门对同一批
#: 逐项 verdict 必须给出同一个汇总，而此前没有任何判据把这两处绑在一起。
from scripts import release_check as RC

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "tools" / "release_all.py"

#: `release_all` 小结行里"某一步没跑成（`unknown`）"的打印形态。
#:
#: 这个字面量是一份格式契约，不是排版偏好：`test_every_only_example_in_the_docstring_is_a_real_step_key`
#: 的判据 2/3 靠它认"被点名的 key 有没有真跑到"。`R6-AN-1`（`draft/28` §86.2）实测：
#: 此前全仓没有任何判据看着这个格式（`tests/` 里出现 `[unknown]` 的只有本文件与
#: `test_role_specs_complete.py`，后者是 `verify_role_specs` 的输出）—— 也就是说
#: 只要 `tools/release_all.py` 把 `f"  [{r.verdict:7s}] …"` 改一个字（`[ unknown ] key`、
#: 或者干脆中文），那两条断言不会报错，只会永远为真（判据还活着，但已经空了）。
#:
#: 处置（顺序不许反）：先用 `test_release_all_unknown_verdict_print_format_is_pinned`
#: 把格式钉住，再让判据 2/3 依赖它。改打印格式的人会先撞上那条格式契约用例。
UNKNOWN_LINE_FMT = "[unknown] {key}"

#: `--only` 的取值形态：逗号分隔的步骤 key。`--only=x`（等号）与 `--only x`（空格）都认。
_ONLY_RE = re.compile(r"--only(?:=|\s+)([A-Za-z0-9_,\-]+)")

#: 发布门里"会重算整片东西"的步骤 key（声明面，登记制）。
#:
#: 常规全量只自检判据本体，不替发布门把整步重算一遍 —— 那一步的判定权在发布门自身
#: （`tools/release_all.py` 的 `coverage` / `per-file` / `acceptance` / `repro` 步，
#: 收工与发布时跑）。这里逐条列出"哪些步骤属于那种重活"：
#:
#: * `coverage` —— 逐函数扫全仓，实测 584 s（`draft/37` §124）与 928.6 s（`draft/43-D` §0.3）；
#: * `per-file` —— 逐文件单跑，量级与全量测试相同；
#: * `acceptance` / `repro` —— 端到端跑验收表与论文复现。
HEAVY_STEP_KEYS = frozenset({"coverage", "per-file", "acceptance", "repro"})

#: 常规全量里被摘出的 `--only` 示例 key 及理由（键 = 步骤 key）。
#:
#: 为什么是登记制而不是"按耗时自动判"：自动判会让"哪些判据在常规全量里不跑"随机器
#: 快慢浮动，而"慢的用例最后会被跳过"是本仓库踩过的坑（见
#: `test_release_all_cli_records_skipped_steps_as_unknown` 的 docstring）。
#: 加一条必须写清理由与被摘出后的覆盖落点。
SLOW_E2E_KEYS: dict[str, str] = {
    "coverage": (
        "coverage 步实测 584 s（draft/37 §124）到 928.6 s（draft/43-D §0.3），"
        "占旧全量约两成；摘出后的覆盖落点 = 发布门自身（收工/发布跑 release_all.py 的 "
        "coverage 步）与该判据本体的自检（tests/test_coverage_gates.py 等）。"
    ),
}

#: 环境变量：置 1 时连登记过的重活也真跑（临时要端到端验发布门时用）。
_RUN_E2E_ENV = "AGENTFLOW_RUN_RELEASE_GATE_E2E"


def _keys_to_run(keys: str, *, run_e2e: bool) -> tuple[str, list[str]]:
    """把一段 `--only` 取值拆成（真跑的 key 串, 被摘出的 key 列表）。

    纯函数：两条分支都由用例直接测（`test_the_slow_opt_in_removes_exactly_the_registered_keys`
    的正控 + 把登记表临时清空的负控），不靠"真跑一遍端到端"来证明摘出逻辑对 ——
    否则为了验摘出逻辑，就得先付一次被摘出的成本。
    """
    named = [k for k in keys.split(",") if k]
    slow = [k for k in named if k in SLOW_E2E_KEYS]
    if run_e2e:
        return ",".join(named), []
    return ",".join(k for k in named if k not in SLOW_E2E_KEYS), slow


def only_examples(doc: str) -> list[str]:
    """抽出 docstring 里命令行示例中的 `--only` 取值（`R6-AN-1` 后半条）。

    旧口径有三个漏检面（都是实测出来的，不是推演）：它逐行扫、要求同一行里同时出现
    字面 `release_all.py` 与 `--only`，于是 ① 续行写法抽不到；② `--only=role-specs`
    （等号）抽不到；③ `python -m tools.release_all --only …`（不带 `.py`）抽不到。
    抽不到就等于那个示例没人真跑，等于不查。

    现在的口径把整段扫成命令行文本再正则取（只留命令行那些行）：

    * 命令行行 = 含 `release_all` 的行、或顶格以 `--` 开头的行、或上一行以反斜杠续行的行
      —— 于是 `release_all.py` 与 `--only` 不必在同一行；
    * 散文一律排除在外：docstring 里那句"旧版这里举的例子是 `--only lint,role-specs`"
      是引用，不是示例。把它当示例真跑会造出假红（本用例第一版就这么错过一次）。
    """
    cmd_lines: list[str] = []
    cont = False
    for raw in doc.splitlines():
        s = raw.strip()
        is_cmd = cont or s.startswith("--") or "release_all" in s
        if is_cmd:
            cmd_lines.append(s)
        cont = is_cmd and s.endswith("\\")
    return _ONLY_RE.findall("\n".join(cmd_lines))


def test_only_examples_extractor_catches_the_forms_the_old_one_missed():
    """正控 + 负控（`R6-AN-1`）：抽取口径必须抽得到两类曾经会漏的写法，且不误收散文。

    负控的形态：把改前的口径写在这里当夹具（它要求同一行里出现字面 `release_all.py`
    且 `--only` 与取值之间只有空格），前两例在旧口径下抽不到 —— 这就是"漏掉 = 不查"。
    """
    def old_extractor(text: str) -> list[str]:
        out: list[str] = []
        for line in text.splitlines():
            if "release_all.py" not in line or "--only" not in line:
                continue
            m = re.search(r"--only\s+([A-Za-z0-9_,\-]+)", line)
            if m:
                out.append(m.group(1))
        return out

    no_py = "    python -m tools.release_all --only lint\n"
    equals = "    python tools/release_all.py \\\n        --only=role-specs\n"
    prose = "（`D3` 实测：旧版这里举的例子是 `--only lint,role-specs`，直接以退出码 2 失败，\n"
    assert old_extractor(no_py) == [], "夹具前提：不带 `.py` 的写法在旧口径下确实是漏的"
    assert old_extractor(equals) == [], "夹具前提：`--only=` 在旧口径下确实是漏的"
    assert only_examples(no_py) == ["lint"], "不带 `.py` 的写法今天必须抽得到"
    assert only_examples(equals) == ["role-specs"], "`--only=` 今天必须抽得到"
    assert only_examples(prose) == [], "散文里的引用不许被当成示例（否则是假红）"
    assert only_examples("    python tools/release_all.py --only role-specs,coverage\n") == [
        "role-specs,coverage"], "最基本的写法当然还要抽得到"


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


def test_plain_step_crash_is_downgraded_to_unknown_not_fail():
    """负控（A-19）：普通 0/1 脚本崩了与"检查不通过"在退出码上同形，只能从输出认。

    `test/test2` 的验收与复现脚本只有 0/1 两个码。把崩溃读成 `fail` 会让人去改一个
    没坏的东西；读成 `unknown` 只会让人来查。方向的错法不对称，所以这里保守降级。
    """
    step = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO, exit_map=R.PLAIN_EXIT)
    crash = "Traceback (most recent call last):\n  File \"x.py\", line 1\nValueError: boom\n"
    assert R.classify(1, True, False, step, crash) == "unknown"
    # 反向：真的是"检查不通过"（有失败行、没有崩溃指纹）⇒ 仍然是 fail
    genuine = "通过 8 / 失败 2\n失败：P3 汇总不一致\n"
    assert R.classify(1, True, False, step, genuine) == "fail"
    # 三态步骤不受影响：它自己的码表已经把 2 说成 unknown 了
    tri = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO, exit_map=R.TRI_STATE_EXIT)
    assert R.classify(1, True, False, tri, crash) == "fail"
    assert R.classify(2, True, False, tri, crash) == "unknown"
    # 崩溃指纹也绝不会把 pass 抬上来
    assert R.classify(0, True, False, step, crash) == "pass"


def test_crash_markers_match_a_real_python_traceback() -> None:
    """正向：崩溃指纹要真的认得 Python 的 traceback（用子进程真造一个，不靠字符串想象）。"""
    p = subprocess.run(
        [sys.executable, "-c", "raise ValueError('boom')"],
        capture_output=True,
        text=True,
    )
    assert p.returncode != 0
    assert R._looks_like_a_crash(p.stderr), p.stderr[:400]
    assert not R._looks_like_a_crash("通过 10 / 失败 0\n")


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
    # 前端步（裁定 G2）自带三态（`0=pass / 1=fail / 2=unknown`）⇒ 必须显式声明码表。
    # 漏了它，"本机没装 node"会被判成 `fail`（把没查成读成发现问题）；反过来写成宽码表
    # 则会让"前端产物与源码脱节"永远无法让门变红。两个方向都靠这一行挡住。
    assert steps["frontend"].exit_map == R.TRI_STATE_EXIT


# ============================================================ overall：优先级


def _mk(verdict: str):
    step = R.Step("k", "t", [sys.executable, "-c", "pass"], cwd=REPO)
    return R.Result(step, verdict, None, 0.0, [])


def test_overall_all_pass_is_pass():
    """正向：全 `pass` ⇒ `pass`。"""
    assert R.overall([_mk("pass"), _mk("pass")]) == "pass"


# ============================================================ D-2.3：逐项明细要读得出来


def _sub(key: str, verdict: str, detail: dict | None = None) -> dict:
    return {"key": key, "title": f"{key} 的标题", "verdict": verdict,
            "detail": detail or {}, "notes": []}


def test_verdict_from_subitems_fail_dominates_then_unknown():
    """汇总口径（`D-2.3`）：任一 `fail` ⇒ `fail`；无 `fail` 但任一 `unknown` ⇒ `unknown`。

    与 `scripts/release_check.py::Report.overall` 逐字相同 —— 编排层要能独立重算。
    """
    assert R.verdict_from_subitems([_sub("a", "pass"), _sub("b", "pass")]) == "pass"
    assert R.verdict_from_subitems([_sub("a", "pass"), _sub("b", "unknown")]) == "unknown"
    assert R.verdict_from_subitems([_sub("a", "unknown"), _sub("b", "fail")]) == "fail"
    assert R.verdict_from_subitems([_sub("a", "pass"), _sub("b", "fail"), _sub("c", "unknown")]) == "fail"


def test_verdict_from_subitems_empty_is_none_not_pass():
    """反真空（`D-2.3`）：没有子项时返回 `None`，不许返回 `pass`。

    否则"没读到逐项明细"会被汇总成"全通过" —— 这正是三态纪律要挡的折叠。
    """
    assert R.verdict_from_subitems([]) is None


def test_read_step_json_absent_file_says_so_instead_of_pretending_empty_pass(tmp_path):
    """反真空（`D-2.3`）：声明了 JSON 却没那个文件 ⇒ items 空 且附一条 note。"""
    items, counts, notes = R._read_step_json(tmp_path / "nope.json")
    assert items == [] and counts == {}
    assert notes and "没找到" in notes[0], notes


def test_read_step_json_malformed_is_not_guessed(tmp_path):
    """负控（`D-2.3`）：结构不合规时不猜（返回空 items + 如实记 note）。

    猜出来的逐项明细比"没有逐项明细"更危险：它会装成"这 8 项都查过了"。
    """
    p = tmp_path / "bad.json"
    p.write_text('{"items": [{"key": "a", "verdict": "PASS"}], "counts": {}}', encoding="utf-8")
    items, counts, notes = R._read_step_json(p)
    assert items == [] and notes and "verdict" in notes[0], notes
    p.write_text('{"items": "not-a-list"}', encoding="utf-8")
    items, _, notes = R._read_step_json(p)
    assert items == [] and notes, notes
    p.write_text("not json at all", encoding="utf-8")
    items, _, notes = R._read_step_json(p)
    assert items == [] and notes and "读不了" in notes[0], notes


def test_read_step_json_valid_roundtrip(tmp_path):
    """正控（`D-2.3`）：合规的子 JSON 原样读回（items 与 counts 都不许被改写）。"""
    p = tmp_path / "ok.json"
    payload = {"overall": "unknown", "counts": {"pass": 2, "fail": 0, "unknown": 1},
               "items": [_sub("a", "pass"), _sub("b", "pass"), _sub("c", "unknown")]}
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    items, counts, notes = R._read_step_json(p)
    assert notes == []
    assert [i["key"] for i in items] == ["a", "b", "c"]
    assert counts == payload["counts"]


def test_run_step_embeds_subitems_and_derives_verdict_from_them(tmp_path):
    """正控（`D-2.3`）：跑一个真的会写子 JSON 的步骤 ⇒ 明细被嵌进来、结论按明细汇总。

    用一个"自己写 JSON 的桩子进程"而不是真跑发布门：这里要测的是编排层怎么读，
    不是那八项检查本身对不对（那由 `scripts/release_check.py` 自己的测试管）。
    """
    json_out = tmp_path / "sub.json"
    child = (
        "import json,pathlib;"
        f"pathlib.Path(r'{json_out}').write_text(json.dumps({{"
        "'overall':'unknown','counts':{'pass':2,'fail':0,'unknown':1},"
        "'items':[{'key':'a','title':'A','verdict':'pass','detail':{},'notes':[]},"
        "{'key':'b','title':'B','verdict':'pass','detail':{},'notes':[]},"
        "{'key':'c','title':'C','verdict':'unknown','detail':{},'notes':[]}]}))"
    )
    step = R.Step("s", "t", [sys.executable, "-c", child], cwd=REPO,
                  exit_map=R.TRI_STATE_EXIT, json_out=json_out)
    r = R.run_step(step, timeout=60)
    assert [i["key"] for i in r.subitems] == ["a", "b", "c"]
    assert r.subcounts == {"pass": 2, "fail": 0, "unknown": 1}
    # 退出码 0 单独看是 pass，但逐项里有 unknown ⇒ 该步必须是 unknown（子项为准）。
    assert r.verdict == "unknown", r.verdict
    assert any("子项汇总" in n for n in r.notes), r.notes
    d = r.to_dict()
    assert d["subitems"] and d["subcounts"]["unknown"] == 1


def test_negative_control_one_subitem_error_flips_only_that_step_not_the_others(tmp_path):
    """负控（`D-2.3`）：给一个子项注入错误 ⇒ 该步 `fail`，其它步骤的结论不许跟着变。

    这条防的是"把总判定抄成 N 份"：如果编排层只是把子进程的总判定复制给每一步，
    那么一处注入会让所有步骤一起变色。这里断言"只有被注入的那一项变"。
    """
    json_out = tmp_path / "sub.json"
    child = (
        "import json,pathlib;"
        f"pathlib.Path(r'{json_out}').write_text(json.dumps({{"
        "'overall':'fail','counts':{'pass':2,'fail':1,'unknown':0},"
        "'items':[{'key':'a','title':'A','verdict':'pass','detail':{},'notes':[]},"
        "{'key':'b','title':'B','verdict':'fail','detail':{'tail':['BOOM 注入的错误尾部']},'notes':[]},"
        "{'key':'c','title':'C','verdict':'pass','detail':{},'notes':[]}]}))"
    )
    injected = R.Step("release-check", "t", [sys.executable, "-c", child], cwd=REPO,
                      exit_map=R.TRI_STATE_EXIT, json_out=json_out)
    other = R.Step("role-specs", "t", [sys.executable, "-c", "pass"], cwd=REPO,
                   exit_map=R.TRI_STATE_EXIT)
    r_inj = R.run_step(injected, timeout=60)
    r_other = R.run_step(other, timeout=60)
    assert r_inj.verdict == "fail"
    assert r_other.verdict == "pass", "注入只该影响它所在的那一步"
    # 注入的那一项的 verdict 与被注入的输出尾部都必须能在 JSON 里读到
    bad = [i for i in r_inj.subitems if i["verdict"] == "fail"]
    assert len(bad) == 1 and bad[0]["key"] == "b"
    assert "BOOM 注入的错误尾部" in json.dumps(bad[0]["detail"], ensure_ascii=False)
    # 另外两项的 verdict 不许跟着变
    assert {i["key"]: i["verdict"] for i in r_inj.subitems} == {"a": "pass", "b": "fail", "c": "pass"}
    assert R.overall([r_inj, r_other]) == "fail"


def test_overall_fail_dominates_unknown():
    """负控：有 `fail` 也有 `unknown` ⇒ `fail`（阻断的理由优先）。"""
    assert R.overall([_mk("unknown"), _mk("fail")]) == "fail"
    assert R.overall([_mk("fail"), _mk("pass")]) == "fail"


def test_overall_unknown_without_fail_is_unknown_not_pass():
    """负控（三态的核心）：只有 `unknown`、没有 `fail` ⇒ `unknown`，不是 `pass`。

    这是本项目反复踩过的那个坑：把"没检查"与"检查过了没问题"折叠成同一个"通过"。
    """
    assert R.overall([_mk("pass"), _mk("unknown")]) == "unknown"


def test_overall_empty_is_unknown_not_pass():
    """负控（`H-5` / `T4` / `I-7` 本轮修）：空列表 ⇒ `unknown`，「不是」 `pass`。

    改前这条断言的是 `overall([]) == "pass"`（"没有可失败的项"）—— 而同一文件里的
    姊妹函数 `verdict_from_subitems([])` 返回 `None`（它自己的 docstring 逐字写着
    "反真空：没有子项时返回 None，不许返回 pass"）⇒ 同一个仓库里对空输入有两种口径，
    而"编排层独立重算一遍"这条防线恰好在空集上失效（两边都绿）。

    现在两边都是"没查成"这一档：`overall([])` 给 `unknown`，
    `verdict_from_subitems([])` 给 `None`（由调用方读成没查成）。
    真实路径上这一支仍然不可达（`main()` 对步骤表每一条都 append），
    由下面那条正控钉住 —— 但"不可达"不再是"可以写错"的理由。
    """
    assert R.overall([]) == "unknown"
    assert R.verdict_from_subitems([]) is None, (
        "`verdict_from_subitems([])` 的口径变了？那 `overall([])` 的交叉断言要一起改"
    )


def test_main_records_one_result_per_step_so_the_empty_table_is_unreachable(tmp_path, monkeypatch):
    """正控（`T4`/`I-7` 的第二半）：把"CLI 上不可达"从散文变成一条可红的判据。

    空表那一档之所以可以留着上面那条残余，唯一依据是 `main()` 永远拿不到空表：
    它对 `build_steps(...)` 的每一条都 `results.append(...)`（跳过记 unknown、
    跑了记结果）。所以这里把 `run_step` 换成零成本桩，真跑一遍 `main()`，断言
    写进 JSON 的步骤数与步骤表逐字等长且至少一条。

    一旦 `build_steps` 可能返回空表（例如将来加了"只跑某些 key"的过滤而把全部
    步骤滤掉），这条就红 —— 那时必须回去把 `overall` 的空表分支与
    `verdict_from_subitems` 对齐成 `unknown`，而那一步落在 `tools/release_all.py`
    （FC-27 禁改区 release-deploy），不在本批次范围内。
    """
    steps = R.build_steps(REPO)
    assert len(steps) >= 1, f"步骤表是空的：{steps}"

    seen: list[str] = []

    def fake_run_step(step, timeout):
        seen.append(step.key)
        assert timeout > 0
        return R.Result(step, "pass", 0, 0.0, [])

    monkeypatch.setattr(R, "run_step", fake_run_step)
    out = tmp_path / "stubbed.json"
    code = R.main(["--json", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert code == 0, code
    assert [s["key"] for s in data["steps"]] == [s.key for s in steps]
    assert len(data["steps"]) == len(seen) == len(steps) >= 1
    assert data["verdict"] == "pass"


def test_negative_control_an_empty_step_table_is_read_as_unknown(tmp_path, monkeypatch):
    """负控（`H-5` / `T4` / `I-7` 本轮修）：把 `build_steps` 换成空表 ⇒ 空表读成 `unknown`。

    改前这条故意把"空表 ⇒ pass"这个缺陷钉住（那条断言的理由是"真实路径不可达"）。
    本轮把空表口径与 `verdict_from_subitems([])` 对齐到"没查成"这一档之后，
    这条改成断言 `unknown`：

    - 退出码必须是「2」（`unknown`），不是 0；
    - JSON 顶层的 `verdict` 必须是 `unknown`，`counts` 三档全 0；
    - `steps` 仍然是空表（"一项都没跑"这件事必须看得见，不许被一条假的 pass 掩盖）。
    """
    monkeypatch.setattr(R, "build_steps", lambda *a, **k: [])
    out = tmp_path / "empty.json"
    code = R.main(["--json", str(out)])
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["steps"] == []
    assert data["verdict"] == "unknown", (
        f"空表被读成了 {data['verdict']!r}：没有可判的项不是'全过'（`H-5`）"
    )
    assert code == 2, f"空表必须给 unknown 的退出码 2，实测 {code}"


# ============================================================ H-5：两处汇总口径的交叉断言


#: 逐项 verdict 的组合，覆盖三条口径（任一 fail ⇒ fail；否则任一 unknown ⇒ unknown；
#: 全 pass ⇒ pass）与它们的边界。
_AGGREGATION_COMBOS: tuple[tuple[str, ...], ...] = (
    ("pass",), ("fail",), ("unknown",),
    ("pass", "pass"), ("pass", "unknown"), ("unknown", "unknown"),
    ("pass", "fail"), ("unknown", "fail"), ("fail", "fail", "pass"),
    ("pass", "fail", "unknown"),
)


def _aggregation_from_subitems(verdicts: tuple[str, ...]) -> str | None:
    """编排层那一侧：`tools/release_all.py::verdict_from_subitems`。"""
    return R.verdict_from_subitems([_sub(f"s{i}", v) for i, v in enumerate(verdicts)])


def _aggregation_from_release_check(verdicts: tuple[str, ...]) -> str:
    """发布门那一侧：`scripts/release_check.py::Report.overall`（不给 `skipped`）。"""
    rep = RC.Report(items=[RC.Item(key=f"s{i}", title="t", verdict=v)
                           for i, v in enumerate(verdicts)])
    return rep.overall()


def _assert_same_aggregation(a, b, combos) -> None:
    for combo in combos:
        got_a, got_b = a(combo), b(combo)
        assert got_a == got_b, (
            f"同一批逐项 {combo} 被两处汇总成了不同的结论："
            f"`verdict_from_subitems`={got_a!r} / `Report.overall`={got_b!r} —— "
            "编排层要能独立重算一遍，两处口径一旦分家，"
            "'子进程总判定与逐项明细不一致'就再也发现不了"
        )


def _as_unknown(value: str | None) -> str:
    """把编排层那一侧的 `None` 读成"没查成"（它的 docstring 就是这么要求的）。

    `verdict_from_subitems([]) is None` 与 `Report.overall()` 在空表上给 `"unknown"`
    是同一件事的两种写法：前者把"没有可汇总的东西"交给调用方处置，
    后者是"报告的总判定"这一档直接给结论。两者的「判据」必须一致 ——
    `None` 只许被读成"没查成"，绝不许被读成"通过"（那正是 `H-5` 修掉的那条裂缝）。
    """
    return "unknown" if value is None else value


def test_cross_assertion_both_aggregators_agree_on_every_non_empty_combination():
    """正控（`H-5`）：两份实现（编排层 / 发布门）对同一批逐项 verdict 给同一个汇总。

    此前没有任何判据把这两处绑在一起：它们只在"两处都写对了"时相等，而相等这
    件事没人看着。这里把整张组合表跑一遍 —— 任一侧改了分支顺序或优先级就红。
    """
    _assert_same_aggregation(lambda c: _as_unknown(_aggregation_from_subitems(c)),
                            _aggregation_from_release_check, _AGGREGATION_COMBOS)


def test_cross_assertion_the_empty_table_is_unknown_on_both_sides():
    """正控（`H-5` 的空集档）：空表在两侧都必须读成 `unknown`。

    改前两侧在这一档分家：`verdict_from_subitems([]) -> None`（没查成）、
    `Report.overall() -> "pass"`（全过）。空集是"没有可判的项"，
    两处都必须是没查成 —— 这一条就是那次分家的机器判据。
    """
    assert _as_unknown(_aggregation_from_subitems(())) == "unknown"
    assert _aggregation_from_release_check(()) == "unknown", (
        "发布门对空 items 又给出 pass 了？`H-2`/`H-5` 的修法被撤掉了"
    )
    # 两侧的读法必须一致（`None` 不许被读成 pass）
    assert _as_unknown(_aggregation_from_subitems(())) == _aggregation_from_release_check(())


def test_negative_control_the_cross_assertion_catches_a_diverging_aggregator():
    """负控（`H-5`）：把一侧换成一个会分家的实现 ⇒ 交叉断言必须红。

    没有这条，"两处相等"就无法与"这条断言恒真"区分开。
    """
    def diverging(verdicts: tuple[str, ...]) -> str:
        return "pass"

    with pytest.raises(AssertionError, match="不同的结论"):
        _assert_same_aggregation(diverging, _aggregation_from_release_check,
                                 _AGGREGATION_COMBOS)


def test_the_empty_table_used_to_be_a_divergence_and_now_agrees():
    """负控（`H-5`）：把空表这一档单独拿出来 —— 「两处今天一致，且都是 unknown」。

    这条的前身（`test_the_empty_table_divergence_is_a_registered_residual_until_h2_is_fixed`）
    钉的是"两处口径确实不同"这个残余。残余已经在本轮修掉（空集 ⇒ unknown），
    所以这条反过来钉"一致"这件事：哪一侧被改回去，它立刻红。
    """
    assert R.verdict_from_subitems([]) is None
    assert RC.Report().overall() == "unknown", (
        "内层发布门的空表口径又变成 pass 了 —— 那正是 `H-2`/`H-5` 修掉的那条裂缝"
    )
    assert _as_unknown(R.verdict_from_subitems([])) == RC.Report().overall()


def test_exit_codes_are_three_valued():
    """三个结论对应三个不同的退出码（`pass`=0 / `fail`=1 / `unknown`=2）。"""
    assert R.VERDICT_EXIT == {"pass": 0, "fail": 1, "unknown": 2}


# ============================================================ 端到端：跳过语义


def test_cli_skip_is_recorded_as_unknown_and_exit_code_is_two(tmp_path):
    """负控（端到端）：`--skip` 掉一个步骤 ⇒ 该步记 `unknown` ⇒ 退出码 2，不是 0。

    这条测的是"发布门不能被 `--skip` 绕过"。若哪天有人把跳过记成 `pass`，
    这条会红 —— 而它是唯一能抓住那个改动的测试。

    这里把所有会真跑东西的步骤都 skip 掉（只留 `role-specs` 那种秒级步骤），
    因为本用例测的是"跳过怎么记账"，不是"那些门能不能过"。
    `per-file`（逐文件单跑，量级与全量测试相同）必须在这个列表里 ——
    漏掉它会让这条用例从"秒级"变成"分钟级"，而慢的用例最后会被跳过。
    """
    out = tmp_path / "r.json"
    p = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--skip", "acceptance,repro,release-check,coverage,per-file",
         "--json", str(out)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    by_key = {s["key"]: s["verdict"] for s in data["steps"]}
    assert by_key["acceptance"] == "unknown"
    assert by_key["per-file"] == "unknown", "跳过的步骤必须记 unknown，不是 pass"
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


def test_release_all_unknown_verdict_print_format_is_pinned():
    """格式契约（`R6-AN-1`，`draft/28` §86.2）：`unknown` 这一档的打印形态必须被钉住。

    为什么这条要单独存在：下面那条 docstring 用例的判据 2/3 认的是字面
    `[unknown] <key>`（它来自 `main()` 的小结行 `f"  [{r.verdict:7s}] {r.step.key:14s} …"`）。
    在没有本条之前，那个字面量没有任何判据看着 —— 格式一改，判据 2/3 会静默变真空。
    所以顺序是"先钉格式，后依赖格式"：本用例红 = 有人动了 `release_all` 的打印形态，
    此时必须同步改 `UNKNOWN_LINE_FMT` 与那两条断言，而不是让它们悄悄空掉。

    夹具：`--only role-specs --skip role-specs` 让六个步骤一个都不跑 ⇒ 小结行里
    六个 key 全是 `unknown`（这是真的"没跑成"这一档，不是人造的字符串）。
    跑的是进程内的 `R.main(...)`，不受子进程开销影响；被测的仍是
    `tools/release_all.py` 里那段真正的打印代码。
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = R.main(["--only", "role-specs", "--skip", "role-specs", "-q"])
    blob = buf.getvalue()
    assert code == 2, f"全部跳过的运行必须落回 `unknown`(2)，实测 {code}：\n{blob[-400:]}"
    keys = [s.key for s in R.build_steps(REPO)]
    assert keys, "步骤表是空的 —— 这条格式契约失去对象（空输入不许读成通过）"
    missing = [k for k in keys if UNKNOWN_LINE_FMT.format(key=k) not in blob]
    assert not missing, (
        "`tools/release_all.py` 打印 `unknown` 的形态变了：这些 key 不再以 "
        f"`{UNKNOWN_LINE_FMT.format(key='<key>')}` 出现 —— {missing}。\n"
        "这不是排版洁癖：docstring 用例的判据 2/3 认的就是这个字面量，"
        "格式一改它们会静默变真空（`R6-AN-1`）。改格式就同时改本文件的 "
        "`UNKNOWN_LINE_FMT` 与那两条断言。\n"
        f"实测输出：\n{blob[-700:]}"
    )
    # 反真空：钉住的是"unknown 这一档真的会被打印"，不是一个恰好为空的小结
    assert "一键发布检查总判定：UNKNOWN" in blob, blob[-400:]
    assert blob.count("[unknown]") >= len(keys), blob[-400:]


def test_every_only_example_in_the_docstring_is_a_real_step_key():
    """正控（`D3`）：模块 docstring 里出现的每个 `--only <keys>` 示例都必须真能跑。

    改前 docstring 里「唯一」的那个例子是 `--only lint,role-specs`，而 `lint`
    不是步骤 key（它是 `release-check` 这一步里的第 5 项）⇒ 使用者照抄就直接
    以退出码 2 失败，然后去猜键名。

    这里把 docstring 逐个例子抽出来「真跑一遍」，判据是两条实质条件（不是退出码）：
    stderr 里不得出现 "未知的步骤 key"，且被点名的每个 key 都不得记成 unknown。

    判据 2/3 认的字面量是 `UNKNOWN_LINE_FMT`（`[unknown] <key>`），它是
    `release_all` 的打印形态 —— 那个形态由格式契约用例
    `test_release_all_unknown_verdict_print_format_is_pinned` 先钉住（`R6-AN-1`
    的处置顺序：先钉格式，后依赖格式），所以"打印排版一改，这两条断言静默变真空"
    这条路是堵住的。这个用例里不再写第二份字面量。

    抽取口径见 `only_examples()`：不要求 `release_all.py` 与 `--only` 同行，
    容忍 `--only=role-specs` 与不带 `.py` 的 `python -m tools.release_all`
    （旧口径这三类都漏，而漏掉就等于不查）。

    为什么不能拿「退出码 != 2」当判据：`--only` 是子集运行，未选中的步骤按 `H-5`
    记 `unknown`，而 `unknown` 就是退出码 2（三态 0/1/2）—— 2 在这条命令里既能表示
    "用法错误"、又能表示"跑通了但有步骤未知"，拿它判别用法错误是两种含义混成一种。
    反面教材就在本文件下面那段注释里（2026-09-27 修）：旧判据
    `assert p.returncode != 2` 曾长期为真，原因是当时 `coverage` 那一关红着、
    整体退出码是 1 —— 一条靠另一个门红了才通过的判据，`coverage` 修好后立刻暴露。
    用法错误的唯一判据是那句话本身（见
    `test_cli_unknown_step_key_is_rejected_with_exit_two`）。

    常规全量与端到端的分档（2026-10-07，所有者裁定"全量不该替别的门把它自己的工作重跑"）：
    示例点名的 key 凡落在 `HEAVY_STEP_KEYS` 里的，按 `SLOW_E2E_KEYS` 登记后常规不真跑，
    只保留两条更便宜的判断 —— 它仍是合法步骤 key，以及"示例点名的重活恰好等于被摘出的那些"。
    想在本套件里端到端验一次，置 `AGENTFLOW_RUN_RELEASE_GATE_E2E=1`。

    摘出的代价如实写下：常规全量不再覆盖"发布门 coverage 步端到端跑得通"这一格。
    它的覆盖落点是发布门自身（收工/发布时跑 `release_all.py` 的 coverage 步）与该判据
    本体的自检文件。换来的是常规全量少一次 584 s 到 928.6 s 的重算（约占旧全量两成）。
    """
    doc = R.__doc__ or ""
    examples = only_examples(doc)
    assert examples, "docstring 里一个 `--only` 命令行示例都没有了？那这条判据成了真空"
    run_e2e = os.environ.get(_RUN_E2E_ENV) == "1"
    step_keys = {s.key for s in R.build_steps(REPO)}
    for keys in examples:
        keys_run, slow = _keys_to_run(keys, run_e2e=run_e2e)
        # 被摘出的 key 仍必须是合法步骤 key：示例写错键名与"这个键被摘出"是两件事，
        # 后者是我方调度，前者是文档错误 —— 混成一条会让文档错误被静默放行。
        for one in slow:
            assert one in step_keys, (
                f"docstring 的示例点名 `{one}`，但它不是步骤 key（实际：{sorted(step_keys)}）"
                " —— 这是示例本身写错了，不是被摘出的重活"
            )
        # 反真空（负控 A 实测出来的口子）：若示例点名的 key 全被登记成"重活"，
        # 这条判据就什么都验不到却照样通过 —— 那不是省时间，是判据变成真空。
        # 必须让人显式决定（留至少一个 key 真跑，或换掉这条判据的对象），不许静默通过。
        assert keys_run, (
            f"docstring 的示例 `--only {keys}` 点名的 key 全在 `SLOW_E2E_KEYS` 里 ⇒ "
            "这条判据在常规全量下什么都没验（真空）。留至少一个 key 不在登记表里，"
            "或改掉这条判据的对象；登记表与示例的对账见 "
            "`test_the_slow_opt_in_keys_are_exactly_the_docstring_names_the_heavy_steps`。"
        )
        p = subprocess.run(
            [sys.executable, str(SCRIPT), "--only", keys_run, "-q"],
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
            errors="replace",
            # 这个 timeout 是「防挂死」用的，不是性能判据（判据是"示例里点名的每个 key
            # 都真的跑到了"）。常规全量已经不跑 `coverage` 这一档（见 `SLOW_E2E_KEYS`），
            # 所以这段余量只在 `AGENTFLOW_RUN_RELEASE_GATE_E2E=1` 时才用得上：
            # `--only role-specs,coverage` 实测 615 s（coverage 584 s + role-specs 4 s，
            # `draft/37` §124），另一次实测 928.6 s（`draft/43-D` §0.3）。
            # coverage 那一步为什么慢（`cProfile`：3453 次 `findall`，每次都把整份 tests/
            # 文本从头走一遍 ⇒ 累计约 15 G 字符的走查；口径见 §124 与 2026-10-07 的复算）
            # 与它的修法已登记在 §124；那一步在 FC-27 禁改区，改它要人逐行走查，
            # 所以这里把防挂死的余量给足。
            timeout=1800,
        )
        blob = p.stdout + p.stderr
        # 这里不能拿退出码判"用法错误"（2026-09-27 修正）：
        # `--only` 是子集运行 ⇒ 没被选中的步骤按 `H-5` 记 `unknown`，
        # 而 `unknown` 就是退出码 2（三态：0 pass / 1 fail / 2 unknown）。
        # 旧写法 `assert p.returncode != 2` 把这两种 2 混成一种，本身就是错的判据；
        # 它此前一直"绿"，只是因为当时 `coverage` 那一关红着 ⇒ 退出码是 1 ⇒ 恰好不等于 2
        # —— 也就是这条判据一直是靠另一个门红了才通过的（修好 `coverage` 之后它才暴露）。
        # 用法错误只能看具体那句话：
        assert "未知的步骤 key" not in blob, (
            f"docstring 里的 `--only {keys_run}` 示例里有非法 key：\n{blob[-400:]}"
        )
        # 更实质的一档：被点名的每个 key 都必须真的跑到了（而不是被当成未知跳过）。
        # 形态取自格式契约常量（不是就地再写一遍字面量）。
        for one in keys_run.split(","):
            needle = UNKNOWN_LINE_FMT.format(key=one)
            assert needle not in blob, (
                f"docstring 的示例 `--only {keys_run}` 里 `{one}` 没跑到（被判成 unknown）：\n{blob[-400:]}"
            )
        # 负控（反真空判据）：证明 unknown 这一档在本输出里真的会出现
        # —— 否则上一条断言可能只是「这个字符串永远不出现」的真空判据。
        # 示例是真子集（`role-specs,coverage` ⊂ 六个步骤）⇒ 未选中的步骤必然记 unknown。
        # 形态同样取自格式契约常量。
        if len(keys_run.split(",")) < 6:
            empty = UNKNOWN_LINE_FMT.format(key="")
            assert re.search(re.escape(empty) + r"\S+", blob), (
                f"示例是子集却一个 `{empty}<步骤>` 都没有 ⇒ 上一条断言成了真空判据：\n{blob[-600:]}"
            )
        # 摘出与示例不许脱钩：docstring 点名的重活必须恰好等于本次被摘出的那些。
        # 少了 ⇒ 有个重活其实被真跑了（全量被拖长，而登记表还宣称已摘出）；
        # 多了 ⇒ 摘出面被悄悄扩大。这条是"摘出不许退化成删掉"的第一道守卫，
        # 第二道在 `test_the_slow_opt_in_keys_are_exactly_the_docstring_names_the_heavy_steps`。
        heavy_named = [k for k in keys.split(",") if k in HEAVY_STEP_KEYS]
        if not run_e2e:
            assert heavy_named == slow, (
                f"docstring 示例点名的重活 {heavy_named} 与被摘出的 {slow} 不一致 —— "
                "登记表与示例脱钩了（`SLOW_E2E_KEYS` 该加该删而未动）"
            )
        # 示例必须真的「选到了」步骤（不是"跑了但什么都没选"）
        assert "一键发布检查总判定" in blob, blob[-400:]


def test_the_slow_opt_in_keys_are_exactly_the_docstring_names_the_heavy_steps():
    """守卫（2026-10-07 新增）：常规全量摘出的 key 恰好等于"docstring 点名的重活"。

    两个方向都必须红，否则"摘出"会走样成另外两件事：

    * 少登记 —— docstring 新增一个重活示例（如 `--only acceptance`）而没人登记它，
      它会立刻被常规全量真跑（十几分钟），而没有任何一处会报错；
    * 多登记 —— 把轻活（如 `role-specs`）塞进登记表也一样红：否则登记表就是
      "允许不在全量里跑"的随手扩大面。

    登记表本身的每条理由必须非空：退化成一张 key 列表之后，没人能复核"摘出是否还成立"
    （发布门是否仍然包含那一步、那一步是否仍在收工/发布时跑）。
    """
    doc = R.__doc__ or ""
    named = {k for keys in only_examples(doc) for k in keys.split(",") if k}
    assert named, "docstring 里抽不出任何 `--only` 示例 key —— 这条守卫失去对象"
    step_keys = {s.key for s in R.build_steps(REPO)}
    extra = set(SLOW_E2E_KEYS) - step_keys
    assert not extra, f"登记表里有不是步骤 key 的条目：{sorted(extra)}"
    expected = named & HEAVY_STEP_KEYS
    assert set(SLOW_E2E_KEYS) == expected, (
        f"登记表 {sorted(SLOW_E2E_KEYS)} 与「docstring 点名的重活」{sorted(expected)} 不一致："
        f"多登记 {sorted(set(SLOW_E2E_KEYS) - expected)}，"
        f"少登记 {sorted(expected - set(SLOW_E2E_KEYS))}"
    )
    for key, why in SLOW_E2E_KEYS.items():
        assert why.strip(), f"登记 `{key}` 没写理由 —— 复核者无从判断摘出是否还成立"


def test_the_slow_opt_in_removes_exactly_the_registered_keys(monkeypatch):
    """正控 + 负控：摘出真由登记表驱动，且"置 1 就真跑"这条路没断。

    负控把登记表临时清空 —— 若"摘出"是硬编码的（或从别处推出来的），清空之后仍会摘出，
    这条立刻红。正控另一端：`run_e2e=True` 必须原样返回全部 key，否则"想端到端验一次"
    没有通路，摘出就成了单向的（只能跑轻活，永远验不了重的）。
    """
    keys = "role-specs,coverage"
    run, slow = _keys_to_run(keys, run_e2e=False)
    assert (run, slow) == ("role-specs", ["coverage"]), (run, slow)
    full, none = _keys_to_run(keys, run_e2e=True)
    assert (full, none) == (keys, []), (full, none)
    monkeypatch.setattr(sys.modules[__name__], "SLOW_E2E_KEYS", {})
    run2, slow2 = _keys_to_run(keys, run_e2e=False)
    assert (run2, slow2) == (keys, []), (run2, slow2)


def test_the_judge_actually_consults_the_opt_in_switch():
    """接线判据：光有 `_keys_to_run(run_e2e=...)` 不够 —— 法官本人必须真的读那个环境变量。

    为什么用源码级钉子而不是真跑那条分支：真跑要付 584 s 到 928.6 s，正是本轮要摘掉的东西
    —— 于是"想端到端验一次"这条通路不能靠端到端来证明，否则它等于没被摘出。
    钉两件事：法官函数体里读了 `_RUN_E2E_ENV`，且把结果交给了 `_keys_to_run(..., run_e2e=...)`。

    代价如实写：这条只在源码文本层面成立 —— 若有人换一种写法读同一个变量而这里认不出，
    会误红。红是安全方向（逼人看一眼），不采信"看起来应该有"。
    """
    src = inspect.getsource(test_every_only_example_in_the_docstring_is_a_real_step_key)
    assert "_RUN_E2E_ENV" in src, "法官没读 opt-in 环境变量 ⇒ 端到端通路不存在"
    assert "run_e2e=" in src, "法官没把 opt-in 的结果交给 `_keys_to_run` ⇒ 开关是死的"


def test_step_table_count_is_stated_in_the_build_steps_docstring():
    """正控（`D4`）：`build_steps` docstring 点名的步骤数必须与它实际返回的条数一致。

    改前 docstring 写"用户点名的六项 + 三个结构性门"，按它自己的分解只等于「5」
    （六项落在 2 个步骤里：`release-check` 覆盖 5 项 + `acceptance` 1 项），
    而函数返回「6」—— 多出来的 `repro`（论文独立复现）在清单里根本没提，
    读者按 docstring 数步骤会漏掉一个门。

    这条用"docstring 里写出的那个数字"与 `len(build_steps(...))` 对账：
    往表里加一个步骤而不同步 docstring ⇒ 必红。
    """
    doc = R.build_steps.__doc__ or ""
    steps = R.build_steps(REPO)
    m = re.search(r"3 个结构性门 = (\d+)", doc)
    assert m, f"`build_steps` 的 docstring 里读不出步骤数（原文：{doc[:120]!r}）"
    assert int(m.group(1)) == len(steps), (
        f"docstring 说 {m.group(1)} 个步骤，`build_steps` 实际返回 {len(steps)} 个："
        f"{[s.key for s in steps]}"
    )
    # 清单里点名的每一类都必须在步骤表里有落点。
    #
    # 这里原先只断言了最后一个 needle（`per-file`）落在步骤表里 —— 断言写在 for 循环
    # 外面，于是另外五类"docstring 点名了、步骤表里却没有"不会被判红，判据强度只剩 1/6。
    # 为什么本轮必须修：本轮把常规全量里的 `coverage` 端到端摘出（见 `SLOW_E2E_KEYS`），
    # "摘出之后发布门还必须包含这一步"就全靠这条声明面判据守着 —— 它弱一格，
    # "摘出"就有退化成"删掉"的空间。
    step_keys = {s.key for s in steps}
    for needle in ("release-check", "acceptance", "repro", "role-specs", "coverage",
                   "per-file", "frontend"):
        assert f"`{needle}`" in doc, f"`build_steps` docstring 没有点名 {needle}"
        assert needle in step_keys, (
            f"docstring 点名了 `{needle}`，但 `build_steps` 的步骤表里没有它："
            f"{sorted(step_keys)}"
        )


#: coverage 步耗时声明的下限（秒）：实测 928.6 s（`draft/43-D` §0.3），不是估计值。
_COVERAGE_EXPECT_SECONDS_FLOOR = 928.6
#: 旧值（改前的假声明）：判据必须能认出它 —— 负控拿它当输入，而不是写一句同义反复。
_COVERAGE_EXPECT_SECONDS_OLD = 60


def _duration_claim_ok(seconds: float, *, floor: float = _COVERAGE_EXPECT_SECONDS_FLOOR) -> bool:
    """耗时声明合不合格。判据只有一份：正控与负控都调它（否则负控是空的）。

    `floor` 按步骤给：每一步的实测/读数不同（coverage 928.6 s、per-file 1082.0 s、
    acceptance 135.2 s）。默认值是 coverage 那一条，保持既有调用点逐字不变。
    """
    return float(seconds) >= floor


def test_coverage_step_declares_the_measured_duration():
    """判据（`REL-01` / F11 · C 线的读数 · 本文件的负控）：coverage 步的耗时声明要对得上实测。

    F11 的口径（`draft/52` F 组 / `draft/43-D` §0.3）：`expect_seconds` 只用于打印、
    不参与判定，所以把一句假声明留在表里没有任何判据会红 —— 而读发布报告的人
    会以为这一步几秒钟就跑完（旧值 60 vs 实测 928.6 s，差 15 倍）。

    这一条把那个读数钉成下限：谁把声明改回到一个"看起来很快"的数，这里必红。
    为什么写死 928.6：它是实测值，比它小的任何一个数字都是一句与事实不符的话。

    负控是活体的：同一个 `_duration_claim_ok` 拿旧值 60 必须判否 ——
    若有人把下限放宽到 60 以下，那条负控先红。
    """
    steps = {s.key: s for s in R.build_steps(REPO)}
    assert "coverage" in steps, sorted(steps)
    got = steps["coverage"].expect_seconds
    assert _duration_claim_ok(got), (
        f"coverage 步声明的耗时 {got} s 低于实测下限 {_COVERAGE_EXPECT_SECONDS_FLOOR} s"
        " ⇒ 那会把真机跑成一个假的『超时失败』（F11/REL-01）")
    assert not _duration_claim_ok(_COVERAGE_EXPECT_SECONDS_OLD), (
        f"负控失效：判据认不出旧的假声明（{_COVERAGE_EXPECT_SECONDS_OLD} s）—— "
        "下限被放宽了，这条判据对『有人把声明改回去』失去反应")


#: per-file 步耗时声明的下限（秒）：实测 1082.0 s（默认）/ 1115.7 s（Lean），128 个文件。
#: 来源逐字：`agentflow/docs/NOAI-SUSPENSION-2026-09-28.md:139-140` 的开放期起点读数
#: ```text
#: 3a) 逐文件（默认） exit=0 1082.0s   共 128 个文件：过 127 / 单独跑不过 0
#: 3b) 逐文件（Lean） exit=0 1115.7s   共 128 个文件：过 127 / 单独跑不过 0
#: ```
#: 那份读数是带时刻的（同文件 `:132-133`：窗口从这一版树开始，
#: `2026-09-28T19:50:47` 起、`21:42:32` 止）⇒ 它够格当判据的下限。
#: 下限取默认档那个数（1082.0，比 Lean 档小）：判据要挡的是"声明小于现实"，
#: 而现实至少是默认档这个数。
_PER_FILE_EXPECT_SECONDS_FLOOR = 1082.0
#: 旧值（改前的声明：420 s，比实测小 2.6 倍）：负控拿它当输入，而不是写一句同义反复。
_PER_FILE_EXPECT_SECONDS_OLD = 420


def test_per_file_step_declares_the_measured_duration():
    """判据（`PERF-02` / F11 同族）：per-file 步的耗时声明不得低于带时刻的实测。

    为什么有这条（`PERF-02` 的纪律：不许用一个新的定值换旧的，也不许留一句假声明）：
    `expect_seconds` 只用于打印、不参与判定，所以一句假声明留在表里没有任何门会红
    —— 而读发布报告的人会以为这一步一两分钟就跑完。旧值 420 s 与实测 1082.0 s
    差 2.6 倍：那不是"估算不准"，那是一句与事实不符的话。

    来源（逐字，`agentflow/docs/NOAI-SUSPENSION-2026-09-28.md:139-140`，128 个文件）：
    `3a) 逐文件（默认） exit=0 1082.0s` / `3b) 逐文件（Lean） exit=0 1115.7s`；
    观察窗口在同一文件 `:132-133`（`2026-09-28T19:50:47` 起、`21:42:32` 止）。
    改值由所有者授权、主控代改（1200 s，同量级；`tools/release_all.py` 在禁改区）,
    判据这一侧由本文件补。

    负控是活体的：同一个 `_duration_claim_ok` 拿旧值 420 必须判否 ——
    若有人把下限放宽到 420 以下，那条负控先红。
    """
    steps = {s.key: s for s in R.build_steps(REPO)}
    assert "per-file" in steps, sorted(steps)
    got = steps["per-file"].expect_seconds
    assert _duration_claim_ok(got, floor=_PER_FILE_EXPECT_SECONDS_FLOOR), (
        f"per-file 步声明的耗时 {got} s 低于带时刻的实测下限 {_PER_FILE_EXPECT_SECONDS_FLOOR} s"
        " ⇒ 读发布报告的人会以为这一步很快（F11/PERF-02）")
    assert not _duration_claim_ok(_PER_FILE_EXPECT_SECONDS_OLD,
                                  floor=_PER_FILE_EXPECT_SECONDS_FLOOR), (
        f"负控失效：判据认不出旧的假声明（{_PER_FILE_EXPECT_SECONDS_OLD} s）—— "
        "下限被放宽了，这条判据对『有人把声明改回去』失去反应")


#: acceptance 步在仓库里已有的两条运行读数（秒）：135.2 s 与 132.7 s。
#: 来源逐字：`draft/22-企业级交付与竞争力方案（200万预算）.md` §12.19.1（B1 收口那次
#: `release_all --since 4293989`，`:1303`）与 §12.22.1（B2 检查点，`:1485`）的输出块
#: `[pass] acceptance exit=0 135.2s 通过 10 / 失败 0 / 未执行 0`；
#: 同一对读数也逐字引在 `agentflow/docs/PROPOSALS.md:2984/3011`。
#: 口径（2026-10-02，主控现场更正）：这两块都没有观测时刻（不像 per-file 那份
#: `2026-09-28T19:50:47–21:42:32`）⇒ 按"带时刻的实测"这条口径，acceptance 的声明值属
#: 未核实：既不动它（420 s 原样保留），也不声称它有实测背书。
#: 这条判据因此只做它能做的那一件事：钉住"声明不得低于仓库里已有的读数"。
_ACCEPTANCE_EXPECT_SECONDS_READINGS = (135.2, 132.7)
_ACCEPTANCE_EXPECT_SECONDS_FLOOR = max(_ACCEPTANCE_EXPECT_SECONDS_READINGS)
#: 负控取 `Step` 的 dataclass 默认值（`tools/release_all.py:97` 的 `expect_seconds: int = 60`）
#: —— 那是仓库里真有的一个更小的数，不是我编的。
_ACCEPTANCE_EXPECT_SECONDS_OLD = 60


def test_acceptance_step_declaration_is_not_below_the_known_readings():
    """判据（F11 同族，弱档）：acceptance 的声明不得低于仓库里已有的读数。

    这一条与 coverage / per-file 那两条不同档，理由必须写清（否则就是拿弱证据
    冒充强证据）：

    - per-file：有带时刻的实测（`docs/NOAI-SUSPENSION-2026-09-28.md:139-140`，窗口
      `2026-09-28T19:50:47–21:42:32`）⇒ 那两条是强判据，且逼出了 420 → 1200 的改值；
    - coverage：有 `draft/43-D` §0.3 的 928.6 s ⇒ 同样是强判据；
    - acceptance：只有两条没有观测时刻的运行读数（135.2 s / 132.7 s，
      `draft/22` §12.19.1 与 §12.22.1 的 `release_all` 输出块，同引于
      `docs/PROPOSALS.md:2984/3011`）⇒ 按主控 2026-10-02 的口径，这一步的声明值
      未核实：不凭感觉调大、也不调小，`420` 原样保留。

    于是这条判据只断言它能断言的那一件事：声明不得低于已有的读数（谁把它改成 60
    这种"看起来很快"的数，这里必红）。它不声称 420 有实测背书 —— 那要等一条
    带时刻的 acceptance 实测读数落进仓库。
    """
    steps = {s.key: s for s in R.build_steps(REPO)}
    assert "acceptance" in steps, sorted(steps)
    got = steps["acceptance"].expect_seconds
    assert _duration_claim_ok(got, floor=_ACCEPTANCE_EXPECT_SECONDS_FLOOR), (
        f"acceptance 步声明的耗时 {got} s 低于仓库里已有的读数下限 "
        f"{_ACCEPTANCE_EXPECT_SECONDS_FLOOR} s（{_ACCEPTANCE_EXPECT_SECONDS_READINGS}）")
    assert not _duration_claim_ok(_ACCEPTANCE_EXPECT_SECONDS_OLD,
                                  floor=_ACCEPTANCE_EXPECT_SECONDS_FLOOR), (
        f"负控失效：判据认不出 `Step` 的默认值（{_ACCEPTANCE_EXPECT_SECONDS_OLD} s）—— "
        "下限被放宽了")


def test_step_cancelled_is_a_base_exception_carrying_a_result():
    """正控（`D5`）：`StepCancelled` 的「契约」是"带着三态结论的中断信号"。

    为什么这里只测契约、不试图让 `run_step` 真的抛它：「造不出来」（实测）。
    在 Windows 上让子进程 `raise KeyboardInterrupt`，父进程拿到的只是
    `rc=3221225786`（`0xC000013A` = `STATUS_CONTROL_C_EXIT`）—— 父进程的
    `subprocess.run` 「不抛」 `KeyboardInterrupt`，于是 `run_step` 走的是
    `classify(1, ...)` 那条路。也就是说 `except KeyboardInterrupt` 那一支
    在真跑一个子进程时几乎到不了；它到得了的地方是"父进程自己被 Ctrl-C"
    （`Popen.wait` 里抛上来）。所以这里分两条：
    ① 本用例测「契约」（类层次 + 带 `Result`）；②
    `test_main_records_keyboard_interrupt_with_a_tri_state_exit_code` 在进程内
    注入它，测「记账」（`main()` 记 `unknown`、退出码 2）。
    """
    st = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO,
                exit_map=R.TRI_STATE_EXIT)
    res = R.Result(st, "unknown", None, 0.0, ["（桩）被中断 ⇒ 没跑成"])
    exc = R.StepCancelled(res)
    assert exc.result is res
    assert exc.result.verdict == "unknown"
    # 它必须「不是」`Exception` 的子类（`except Exception` 不许把它吞掉）
    assert issubclass(R.StepCancelled, BaseException)
    assert not issubclass(R.StepCancelled, Exception)
    # 顺带把"为什么不能用真 KeyboardInterrupt 造"这条平台事实记下来
    plain = subprocess.run([sys.executable, "-c", "raise KeyboardInterrupt"],
                           capture_output=True)
    assert plain.returncode != 0


def test_the_windows_ctrl_c_exit_code_is_not_one_of_the_three_verdict_codes():
    """负控（`D5` 的实测依据）：`0xC000013A` 这类码「不在」任何码表里。

    这正是"不属于三态的退出码"的具体形态：`TRI_STATE_EXIT` 只认 0/1/2，
    于是被强杀的进程会落到 `fail`（`classify` 的 `exit_map.get(code, "fail")`）——
    「把"没跑成"读成"发现问题"」。本编排层对普通脚本用崩溃指纹保守降级，
    但对自带三态的步骤没有别的证据；所以"取消"必须由中断信号本身来识别。
    """
    assert 3221225786 not in R.TRI_STATE_EXIT
    assert 3221225786 not in R.PLAIN_EXIT
    step = R.Step("s", "t", [sys.executable, "-c", "pass"], cwd=REPO,
                  exit_map=R.TRI_STATE_EXIT)
    assert R.classify(3221225786, True, False, step, "") == "fail"


def test_main_records_keyboard_interrupt_with_a_tri_state_exit_code(tmp_path, monkeypatch,
                                                                   capsys):
    """正控（`D5`）：`main()` 里那次中断不许逃出去，退出码必须是三态里的 `unknown`(2)。

    两个子形态都要测（它们走的是「两条不同的」代码路径）：
    ① `run_step` 抛 `StepCancelled`（带结论的中断）⇒ 那一步记 `unknown`；
    ② `run_step` 抛裸 `KeyboardInterrupt`（例如中断发生在 `_read_step_json` 那一段，
       还没来得及包成 `StepCancelled`）⇒ 那一步也记 `unknown`。

    两种情况都必须：报告里"哪几步没跑"看得见、退出码 2、绝不静默退出
    （那正是"不属于三态的退出码"）。
    """
    for label, exc_factory in (
        ("StepCancelled", lambda step: R.StepCancelled(
            R.Result(step, "unknown", None, 0.0, ["（桩）被中断 ⇒ 没跑成"]))),
        ("裸 KeyboardInterrupt", lambda step: KeyboardInterrupt()),
    ):
        def boom(self, timeout, _f=exc_factory):
            raise _f(self)

        monkeypatch.setattr(R, "run_step", boom)
        out = tmp_path / f"interrupted-{label[:4]}.json"
        code = R.main(["--json", str(out), "-q"])
        captured = capsys.readouterr()
        assert code == 2, f"[{label}] 中断必须落回 unknown(2)，实测 {code}"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["verdict"] == "unknown", (label, data["verdict"])
        assert all(s["verdict"] == "unknown" for s in data["steps"]), (label, data["steps"])
        assert len(data["steps"]) == len(R.build_steps(REPO)) >= 1, (
            f"[{label}] 被打断的那一轮也要如实列出整张步骤表（每一项都是没查成），"
            "否则报告看起来像'跑完了、都没问题'"
        )
        assert "被中断" in (captured.out + captured.err), (
            f"[{label}] 中断必须在输出里留下一句话（不许静默）"
        )


# ============================================================ 步骤表与禁改区


def test_step_table_covers_exactly_the_six_named_checks():
    """正向：用户点名的那六项都必须在步骤表里被覆盖，且步骤表不许悄悄多出步骤。

    用户逐字要求的是"全量测试 + 全部自检 + 验收测试 + verify + 工具普查 + linter"。
    `scripts/release_check.py` 一次覆盖其中五项，唯独没有验收测试 ——
    这正是本脚本存在的理由。

    `T1`/`I-6`（登记在 `draft/28`）：旧版本这条只断言 `{...} <= keys`（子集），
    而用例名说的是 `exactly` —— 往 `build_steps` 里加任意一个步骤，它完全无感。
    现在两处都收紧：核心五项 + 三个结构性门（`role-specs` / `coverage` / `per-file`）
    必须恰好是这八个；多一个少一个都红（`repro` 是论文独立复现，也在表里）。
    之后又加了第九个 `frontend`（裁定 G2：前端产物新鲜度）—— 同样"恰好"，
    所以往表里加步骤必须同步这一行（否则"加一步"变成静默行为）。
    """
    steps = R.build_steps(REPO)
    keys = [s.key for s in steps]
    assert len(keys) == len(set(keys)), f"步骤 key 有重复：{keys}"
    expected = {"release-check", "acceptance", "repro", "role-specs", "coverage",
                "per-file", "frontend"}
    assert set(keys) == expected, (
        f"步骤表与期望不符：多出 {sorted(set(keys) - expected)}，"
        f"缺少 {sorted(expected - set(keys))}"
    )
    titles = " ".join(s.title for s in steps)
    for needed in ("全量测试", "全部自检", "verify", "工具普查", "linter", "验收测试"):
        assert needed in titles, f"步骤表里没有覆盖 {needed}"


def test_per_file_step_is_wired_and_tri_state():
    """正向 + 负控：逐文件单跑门必须真的被编排进来，而且带三态码表。

    为什么单独钉这一条：这一步守的是"全量绿掩盖单文件红"（`G-27` 的实测形态）。
    它慢，所以最容易被"顺手跳过"；而 `--skip` 在本编排层里记的是 `unknown`（不是 `pass`）。
    若有人把它的 `exit_map` 写成 `PLAIN_EXIT`，它自己报的"没查成(2)"就会被读成"fail" ——
    与 `release-check` 第一版犯的错一模一样，所以这里把它钉住。
    """
    steps = {s.key: s for s in R.build_steps(REPO)}
    assert "per-file" in steps, steps.keys()
    step = steps["per-file"]
    assert step.exit_map is R.TRI_STATE_EXIT
    assert step.argv[1].endswith("run_each_test_file.py"), step.argv
    assert step.cwd.is_dir()
    assert "顺序依赖" in step.title


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


# ==================================================== 文档读数与实测的对账（F8）
#
# `R6-AN-3`/`-4`/`-5`/`-6` 的修法都是"把文档里的数字改成实测值"，而那份审计同时
# 指出：`R6-8`/`H-12` 那类"文档数字过期"已经犯过一次，只改数是治标 —— 数字本身
# 要有一条判据。这批（F8）的文件所有权只有两个测试文件，所以这些对账用例放在这里，
# 并在下面逐条写清它读的是哪一段文本、复跑命令是什么。

DEV_MD = REPO / "DEVELOPMENT.md"
README_MD = REPO / "README.md"
DESIGN_TOOLS_MD = REPO / "DESIGN-TOOLS.md"

#: `DEVELOPMENT.md` 里"当次实测"那一块的界标。判据只读块里的 `名字 = 数字`，
#: 于是"哪些数字是当前值、哪些是历史观测"不再靠读者猜。
LIVE_BEGIN = "LIVE-READINGS:BEGIN"
LIVE_END = "LIVE-READINGS:END"
_LIVE_LINE_RE = re.compile(r"^([a-z_]+)\s*=\s*(\d+)\s*(?:#.*)?$")

#: `R001–R012` 形态；破折号认 U+2013、U+2014 与 ASCII `-`。
_RANGE_RE = re.compile(r"R(\d{3})\s*[\u2013\u2014-]\s*R(\d{3})")
#: "12 条规则" / "规则 12 条" 两种写法。
_RULE_COUNT_RES = (re.compile(r"(\d+)\s*条规则"), re.compile(r"规则\s*(\d+)\s*条"))
#: 明示"这一处是历史观测"的记号（带它的行豁免数字对账）。
#: `R7-R6-2` 之后刻意不含"当次/观测"这两个词：它们在本文里是给当次读数用的
#: （例如"当次 23 条条目"），若把它们当历史记号，新加的 .noai-paths 对账判据
#: 会把自己的对象整行豁免掉 —— 那正是"判据静默变真空"。
_HISTORICAL_MARKERS = ("S1", "S2", "当时", "历史", "原写", "原值", "旧版", "改前")

#: 文档里"更正说明"会逐字引用旧名字/旧数字；带这些记号的行不参与"指路存在性"对账。
#: 刻意与 `_HISTORICAL_MARKERS` 分开：数字对账的豁免面不能被"更正"这个词放大。
_CORRECTION_MARKERS = ("更正", "原来", "原写", "旧名", "改前", "S1", "S2")

#: `R7-R6-3`：本文里被"用例数"点名的那个测试文件。
NOAI_GATE_TEST = "tests/test_noai_gate.py"

#: `CRLF=10` 这类读数；非 0 的一律要问一句"这是当次值吗"。
_CRLF_RE = re.compile(r"CRLF\s*=\s*(\d+)")

_LINTER_MOD = None


def _linter():
    """按路径加载 `scripts/lint_rules.py`（`scripts/` 不是包，不能普通 import）。"""
    global _LINTER_MOD
    if _LINTER_MOD is None:
        spec = importlib.util.spec_from_file_location(
            "_lint_rules_for_f8_readings", REPO / "scripts" / "lint_rules.py")
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod
        spec.loader.exec_module(mod)
        _LINTER_MOD = mod
    return _LINTER_MOD


def rule_numbers() -> list[int]:
    """`RULES` 里真实登记的规则号（按第一栏的 `R0NN` 前缀解析，不靠顺序）。"""
    out: list[int] = []
    for entry in _linter().RULES:
        m = re.match(r"R(\d{3})", str(entry[0]))
        assert m, f"RULES 的第一栏不是 R0NN 形态：{entry[0]!r}"
        out.append(int(m.group(1)))
    assert out, "RULES 里一条规则都没有 —— 判据失去对象（不是通过）"
    return out


def live_readings(text: str) -> dict[str, int]:
    """读出 `LIVE-READINGS` 块声明的读数（名字 -> 数字）。块不在 ⇒ 空字典（判据要报错）。"""
    if LIVE_BEGIN not in text or LIVE_END not in text:
        return {}
    body = text.split(LIVE_BEGIN, 1)[1].split(LIVE_END, 1)[0]
    out: dict[str, int] = {}
    for raw in body.splitlines():
        m = _LIVE_LINE_RE.match(raw.strip())
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


_MEASURED: dict[str, int] = {}


def schema_table_count() -> int:
    """`schema.TABLES` 的条数（`G3` 新增：文档里那个"表声明表"读数此前没有判据守着）。

    量法与文档里写的那条命令逐字等价：
    `python -c "import sys;sys.path.insert(0,'src');import agentflow.schema as s;print(len(s.TABLES))"`
    —— 这里在进程内直读同一个对象，不另起解释器（少一次秒级开销）。
    `schema.py` 在 FC-27 禁改区里，正常情况下这个数只有人签字才会变 —— 但 2026-09-28 起
    FC-27 的"人先写"顺序按 `docs/NOAI-SUSPENSION-2026-09-28.md` 暂停，`conjectures` 表
    就是在这段窗口里加的（15 → 16；台账 hash 已重刷，走查签字仍待补）。钉住它，
    是为了让"文档说 16 张表、而 `schema.TABLES` 已经是别的数"这种漂能被点名。
    """
    import agentflow.schema as _schema  # noqa: PLC0415

    return len(_schema.TABLES)


def measured_readings() -> dict[str, int]:
    """判据认的那几个读数，全部当场量一遍（跑一次 linter + 一次 collect-only，结果缓存）。"""
    if _MEASURED:
        return _MEASURED
    from collections import Counter

    findings = _linter().run_all(REPO).findings
    levels = Counter(str(f.level) for f in findings)
    strict_levels = Counter(str(f.level) for f in _linter().run_all(REPO, strict=True).findings)
    manifest = (REPO / ".noai-paths").read_text(encoding="utf-8")
    rows = [ln for ln in manifest.splitlines() if re.match(r"^\S+\s+\[category:", ln)]
    paths = {ln.split()[0] for ln in rows}
    cats = {m.group(1) for ln in rows
            if (m := re.search(r"\[category:\s*([a-z\-]+)\]", ln))}
    _MEASURED.update({
        "lint_rules_rules": len(rule_numbers()),
        "lint_rules_warning": levels.get("warning", 0),
        "lint_rules_info": levels.get("info", 0),
        "lint_rules_strict_warning": strict_levels.get("warning", 0),
        "lint_rules_strict_info": strict_levels.get("info", 0),
        "noai_paths_glob": len(rows),
        "noai_paths_unique": len(paths),
        "noai_paths_categories": len(cats),
        "tools_star_tools_py": len(list((REPO / "src" / "agentflow" / "tools").glob("*_tools.py"))),
        "schema_tables": schema_table_count(),
        "noai_gate_pytest_collected": collected_test_count(NOAI_GATE_TEST),
    })
    return _MEASURED


def collected_test_count(rel: str) -> int:
    """`pytest <rel> --collect-only -q` 报出来的用例条数（只收集、不跑）。

    这是"用例数"这类读数的可复跑量法：`--collect-only` 把 `pyproject` 的
    `addopts`（`-m 'not network'`）也算进去，所以它与 `N passed` 在
    "没有 skip / 没有 deselect 到 0 / 没有失败" 时相等 —— 那个前提由文档里
    同一行写着的 `0 skipped` 把着，真跑一遍的读数仍是文档里那条复跑命令。
    """
    p = subprocess.run(
        [sys.executable, "-m", "pytest", rel, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
    )
    m = re.search(r"(\d+)\s+tests?\s+collected", p.stdout + p.stderr)
    assert m, f"`--collect-only` 的输出里读不到用例条数（判据失去对象）：\n{(p.stdout + p.stderr)[-400:]}"
    return int(m.group(1))


def live_reading_problems(declared: dict[str, int], measured: dict[str, int]) -> list[str]:
    """声明的读数 vs 实测 ⇒ 问题清单（空 = 成立）。返回清单而不是布尔，红时要能说清差在哪。"""
    if not declared:
        return [f"`DEVELOPMENT.md` 里读不到 `{LIVE_BEGIN}` 块（或块里一行 `名字 = 数字` 都没有）"
                " ⇒ 本判据失去对象：删掉那块不等于数字是对的"]
    problems: list[str] = []
    unknown = sorted(set(declared) - set(measured))
    missing = sorted(set(measured) - set(declared))
    if unknown:
        problems.append(f"`LIVE-READINGS` 块里有判据不认的键（拼错了？）：{unknown}")
    if missing:
        problems.append(f"`LIVE-READINGS` 块缺了判据要对的键：{missing}")
    for key in sorted(set(declared) & set(measured)):
        if declared[key] != measured[key]:
            problems.append(f"`LIVE-READINGS` 里 `{key}` 已过期：文档写 {declared[key]}，实测 {measured[key]}")
    return problems


#: `error A / warning B / info C` 这种 linter 读数三元组。
_TALLY_RE = re.compile(r"error\s*(\d+)\s*/\s*warning\s*(\d+)\s*/\s*info\s*(\d+)")


def tally_claim_problems(text: str, measured: dict[str, int]) -> list[str]:
    """本文里每一处 linter 读数三元组都必须与当次一致（`warning` / `info` 两栏）。

    为什么要有这一条：`R7-R6-2` 的教训是"同族更正在文档里只改了一处，另一处还是旧值"
    —— 上一轮我把 `info 20` 写进了 `LIVE-READINGS` 块，而 §0.2/§0.3/§4.3 的散文里
    各还有一处 `info 20`；块有判据、散文没有，散文就必然会漂。所以口径统一成
    "本文里每一处三元组都对着当次读数"，块只是这些声明里的一个（它的键还多管几个数）。

    `error` 那一栏刻意不比：它由发布门第 5 项按"必须为 0"强制，而且是并行施工期
    最先变的一位（别人在飞时钉它只会造出"我没权改别人文件"的假红）。
    带历史记号的行（S1/S2/当时/…）豁免 —— S1/S2 的当次读数要能留痕。
    """
    problems: list[str] = []
    hits = 0
    for line in text.splitlines():
        if any(mark in line for mark in _HISTORICAL_MARKERS):
            continue
        for _err, warn, info in _TALLY_RE.findall(line):
            hits += 1
            if int(warn) != measured["lint_rules_warning"]:
                problems.append(f"这一行说 `warning {warn}`，当次是 "
                                f"{measured['lint_rules_warning']}：{line.strip()[:80]}")
            if int(info) != measured["lint_rules_info"]:
                problems.append(f"这一行说 `info {info}`，当次是 "
                                f"{measured['lint_rules_info']}：{line.strip()[:80]}")
    if not hits:
        problems.append("一处 linter 读数三元组都读不到 ⇒ 判据失去对象")
    return problems


def rule_claim_problems(text: str, numbers: list[int]) -> list[str]:
    """文本里的规则区间/规则条数 vs `RULES` ⇒ 问题清单。

    带历史记号的行（`S1`/`S2`/`当次`/`历史`/`原写`/`原值`/`旧版`/`改前`）豁免：
    `DEVELOPMENT.md` 刻意保留了 S1/S2 的当次读数（例如 P18 那行"当时 `RULES` 里
    只有 R001–R011"），改它等于伪造历史。豁免是逐行的，所以"把一处当前值随手标成
    历史"这件事在行内看得见。
    """
    problems: list[str] = []
    top = max(numbers)
    hits = 0
    for line in text.splitlines():
        if any(mark in line for mark in _HISTORICAL_MARKERS):
            continue
        for lo, hi in _RANGE_RE.findall(line):
            hits += 1
            if int(hi) != top:
                problems.append(
                    f"规则区间上界 R{hi} != `RULES` 里的最大规则号 R{top:03d}（写的是 R{lo}–R{hi}）："
                    f"{line.strip()[:80]}")
        for rx in _RULE_COUNT_RES:
            for n in rx.findall(line):
                if int(n) != len(numbers):
                    problems.append(f"这一行说『{n} 条规则』，而 `RULES` 里实际 {len(numbers)} 条："
                                    f"{line.strip()[:80]}")
    if not hits:
        problems.append("一处 `R0NN–R0NN` 规则区间都没有 ⇒ 判据失去对象（删掉区间不等于不变量成立）")
    return problems


def test_development_md_linter_readings_and_rule_range_match_the_repo():
    """正控（`R6-AN-4`）：`DEVELOPMENT.md` 的当次读数与规则区间必须与实测一致。

    这一条把"只改数是治标"补上：`LIVE-READINGS` 块里的 `info 20` 改回 `info 21`、
    或把区间写回 `R001–R011`，这里都会红。
    """
    text = DEV_MD.read_text(encoding="utf-8")
    problems = live_reading_problems(live_readings(text), measured_readings())
    problems += rule_claim_problems(text, rule_numbers())
    problems += tally_claim_problems(text, measured_readings())
    assert not problems, problems


def test_the_documented_readings_criterion_is_not_vacuous():
    """负控（`R6-AN-4` 的验收）：把块里的 `info` 打回过期值、或整块删掉 ⇒ 判据必须报问题。

    为什么这两档：第一档是审计给的负控（`info 20` -> `info 21`），第二档是反真空
    （删掉对象不许读成通过，`P16` 族）。
    """
    text = DEV_MD.read_text(encoding="utf-8")
    measured = measured_readings()
    good = live_readings(text)
    assert good, "夹具前提：`DEVELOPMENT.md` 里有 LIVE-READINGS 块"

    stale = re.sub(r"(?m)^lint_rules_info\s*=\s*\d+",
                   f"lint_rules_info = {measured['lint_rules_info'] + 1}", text)
    assert stale != text, "夹具前提：块里有 `lint_rules_info` 这一行"
    assert live_reading_problems(live_readings(stale), measured), (
        "把 `info` 打回过期值之后判据还是绿的 ⇒ 这条判据是恒真的"
    )

    gone = text.replace(LIVE_BEGIN, "LIVE-READINGS-OFF").replace(LIVE_END, "LIVE-READINGS-OFF")
    assert gone != text, "夹具前提：块界标存在"
    assert live_reading_problems(live_readings(gone), measured), "整块删掉之后判据必须报失去对象"

    # 夹具里的区间按 `rule_numbers()` 构造（`G3` 收口，照 `:1287-1296` 那个样板）：
    # 原先这里写死 `"R001–R012"` / `"R001–R011"` 两个字面量，于是规则一改名或区间一换写法，
    # 先红的是"夹具前提"那一句 —— 而它问的不是"判据会不会咬人"。现在构造出来的上界
    # 必然与 `RULES` 里的最大号不同，这一条问的就仍然是"改了区间判据会不会点名"。
    top = max(rule_numbers())
    stale_range = text.replace(f"R001–R{top:03d}", f"R001–R{top - 1:03d}")
    assert stale_range != text, f"夹具前提：文档里有 `R001–R{top:03d}` 可改"
    assert rule_claim_problems(stale_range, rule_numbers()), (
        f"把区间改回 R{top - 1:03d} 之后判据必须报问题（`D11` 那条不变量的同族）"
    )

    cur = measured["lint_rules_info"]
    stale_tally = re.sub(rf"info\s*{cur}\b", f"info {cur + 1}", text)
    assert stale_tally != text, "夹具前提：文档里有当次的三元组可改"
    assert tally_claim_problems(stale_tally, measured), (
        "把散文里的 `info` 打回过期值之后判据必须红（`R7-R6-2` 的形态：块改了、散文没改）"
    )
    assert tally_claim_problems("这一段里没有 linter 读数。", measured), (
        "一处三元组都读不到时必须报失去对象"
    )


# ---- `R7-R6-2`：`.noai-paths` 的计数在本文里只允许一个口径（同一口径只写一处 + 判据守着）

#: 带单位的 `.noai-paths` 计数写法（"（18 条、7 个类别）"那种旧写法也在内）。
_MANIFEST_CLAIM_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("noai_paths_glob", re.compile(r"(\d+)\s*条条目")),
    ("noai_paths_glob", re.compile(r"(\d+)\s*条 glob")),
    # `（18 条、7 个类别）` 这种只写"条、括号"的旧写法：`R7-R6-2` 报的就是它。
    ("noai_paths_glob", re.compile(r"(\d+)\s*条、")),
    ("noai_paths_unique", re.compile(r"(\d+)\s*条唯一路径")),
    ("noai_paths_categories", re.compile(r"(\d+)\s*个分组")),
    ("noai_paths_categories", re.compile(r"(\d+)\s*个类别")),
)
#: §1.5 的"三个数"表：那一格里只有数字、没有单位，所以单独认这三行的行首标签。
_MANIFEST_TABLE_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("noai_paths_glob", re.compile(r"\|\s*\*\*清单 glob 数\*\*[^|]*\|[^|]*\|\s*\*\*(\d+)\*\*")),
    ("noai_paths_unique", re.compile(r"\|\s*\*\*唯一路径数\*\*[^|]*\|[^|]*\|\s*\*\*(\d+)\*\*")),
    ("noai_paths_categories", re.compile(r"\|\s*\*\*禁改区类别数\*\*[^|]*\|[^|]*\|\s*\*\*(\d+)\*\*")),
)


def manifest_claim_problems(text: str, measured: dict[str, int]) -> list[str]:
    """`DEVELOPMENT.md` 里每一处 `.noai-paths` 计数都必须等于实测（`R7-R6-2`）。

    缺陷形态：同一个数在同一份文件里有两种值（`:933`/`:1200` 写 18/21+18，而
    `:70`/`:264` 写 23/20），读者按错的那一处去数就会得出"台账漏了"的结论 ——
    而这两个数正是判据五（禁改区台账）的输入口径。处置就是"同一口径只写一处，
    其余各处由这条判据对账"：任何一处写了别的数，这里立刻点名。

    覆盖面（如实写清边界）：带单位的写法（`N 条条目` / `N 条 glob` / `N 条唯一路径` /
    `N 个分组` / `N 个类别`）与 §1.5 那张"三个数"表的三行都在判据里；
    "台账条目数 / 欠签"两格刻意不在这里钉（它们量的是台账，不是清单，另一条口径）——
    `G3` 的处置是：仍然不钉，但文档里那两处（`DEVELOPMENT.md` §1.5 / §0.1 与
    `README.md` §6.2 / 文件树）都改成了"命令 + 观测时刻"，让读者能判它是不是当次值。
    "要不要给台账计数也配一条判据"是口径决定（每签一个字就变），留给人裁决。

    另一条与它配套的判据是 `historical_marker_leak_problems`：本函数对带历史记号的行
    整行跳过，所以"当前值 + 句尾一句更正说明"会把自己整行豁免掉 ⇒ 静默漂（`G3` 修的漏口）。
    """
    problems: list[str] = []
    hits = 0
    for line in text.splitlines():
        if any(mark in line for mark in _HISTORICAL_MARKERS):
            continue
        # 排版强调标记是噪音：带星号强调的「23 条条目」与不带星号的是同一个声明，
        # 所以按"去掉星号后的同一行"匹配（§1.5 表格那三条规则仍用原行，它们认的是表格写法）。
        plain = line.replace("**", "")
        for key, rx in _MANIFEST_CLAIM_RES:
            for got in rx.findall(plain):
                hits += 1
                if int(got) != measured[key]:
                    problems.append(
                        f"这一行把 `{key}` 写成 {got}，实测 {measured[key]}：{line.strip()[:90]}")
        for key, rx in _MANIFEST_TABLE_RES:
            for got in rx.findall(line):
                hits += 1
                if int(got) != measured[key]:
                    problems.append(
                        f"这一行把 `{key}` 写成 {got}，实测 {measured[key]}：{line.strip()[:90]}")
    if not hits:
        problems.append("一处 `.noai-paths` 计数声明都读不到 ⇒ 判据失去对象"
                        "（删掉这些数不等于它们是对的）")
    return problems


#: `R7-R6-3`：本文里带用例数的那句必须是当次数（`NOAI_GATE_TEST` + `N passed`）。
_PASSED_CLAIM_RE = re.compile(r"(\d+)\s*passed")


def pytest_count_claim_problems(text: str, measured: dict[str, int]) -> list[str]:
    """`DEVELOPMENT.md` 里 `tests/test_noai_gate.py` 的用例数必须等于当次收集条数（`R7-R6-3`）。

    缺陷形态与 `R6-AN-4` 的 `info 21` 完全同族：文档写 `104 passed`，而 `F1`
    这一轮往那个文件里加了 11 例 ⇒ 实测 115。读者按 104 去核对会以为漏跑了 11 例。
    这个数之所以能钉住，是因为它有一个便宜的可复跑量法（`--collect-only -q` 的
    `N tests collected`，本项目实测约 1.4 秒、不真跑用例）。
    """
    problems: list[str] = []
    hits = 0
    for line in text.splitlines():
        if NOAI_GATE_TEST not in line or any(mark in line for mark in _HISTORICAL_MARKERS):
            continue
        for got in _PASSED_CLAIM_RE.findall(line):
            hits += 1
            if int(got) != measured["noai_gate_pytest_collected"]:
                problems.append(
                    f"这一行说 `{NOAI_GATE_TEST}` 有 {got} passed，而 `--collect-only` 报 "
                    f"{measured['noai_gate_pytest_collected']} 条：{line.strip()[:90]}")
    if not hits:
        problems.append(f"读不到一处 `{NOAI_GATE_TEST}` 的用例数 ⇒ 判据失去对象"
                        "（这个数被刻意钉着：它随修复增长，不写就没有东西会红）")
    return problems


def test_development_md_manifest_and_pytest_counts_match_the_repo():
    """正控（`R7-R6-2`/`-3`）：本文里 `.noai-paths` 的每一处计数与那条用例数都必须实测一致。

    这两条判据是上一轮"同族顺带更正漏了两处"（`:933`/`:1200`）的直接处置：
    数字仍然写在文档里（读者要看），但每一处都有判据对着盘上事实。
    """
    text = DEV_MD.read_text(encoding="utf-8")
    problems = manifest_claim_problems(text, measured_readings())
    problems += pytest_count_claim_problems(text, measured_readings())
    assert not problems, problems


def test_the_manifest_and_pytest_count_criteria_are_not_vacuous():
    """负控（`R7-R6-2`/`-3` 的验收）：把 `:1200` 那两个数改回旧值 ⇒ 判据必须报问题。"""
    text = DEV_MD.read_text(encoding="utf-8")
    measured = measured_readings()
    assert not manifest_claim_problems(text, measured), "夹具前提：当前字节上是干净的"
    assert not pytest_count_claim_problems(text, measured), "夹具前提：当前字节上是干净的"

    stale = text.replace(f"**{measured['noai_paths_glob']}** 条条目",
                         f"**{measured['noai_paths_glob'] - 2}** 条条目")
    assert stale != text, "夹具前提：文档里有 `N 条条目` 可改"
    assert manifest_claim_problems(stale, measured), "glob 数改回 21 之后判据必须红"

    stale_unique = text.replace(f"**{measured['noai_paths_unique']}** 条唯一路径",
                                f"**{measured['noai_paths_unique'] - 2}** 条唯一路径")
    assert stale_unique != text, "夹具前提：文档里有 `N 条唯一路径` 可改"
    assert manifest_claim_problems(stale_unique, measured), "唯一路径数改回 18 之后判据必须红"

    # 夹具里刻意不写死当次数（`F8-R11`）：它原先逐字写 `"当次 115 passed"`，于是
    # `F10` 往 `tests/test_noai_gate.py` 加了 1 例、文档同步成 116 之后，这一行
    # `text.replace` 找不到对象 ⇒ `stale_pass == text` ⇒ 负控自己先红，
    # 而那与"判据会不会咬人"无关（是夹具跟着活读数一起漂）。改成按实测值构造旧值：
    # 只要构造出来的数与当次不同，这一条问的就仍然是"改了数判据会不会点名"。
    current = measured["noai_gate_pytest_collected"]
    stale_pass = text.replace(f"当次 {current} passed", f"当次 {current - 11} passed")
    assert stale_pass != text or f"当次 {current} passed" not in text, (
        "夹具前提：文档里那段当次用例数存在（不存在 ⇒ 上面那次 replace 是空操作）")
    assert stale_pass != text, "夹具前提：文档里有当次的用例数可改"
    assert pytest_count_claim_problems(stale_pass, measured), "用例数改回 104 之后判据必须红"

    assert any("失去对象" in p for p in manifest_claim_problems("这一段里一个计数都没有。", measured)), (
        "空输入必须报失去对象（`P16` 族：删掉对象不许读成通过）"
    )
    old_glob = measured["noai_paths_glob"] - 2
    stale_row = re.sub(r"(\|\s*\*\*清单 glob 数\*\*[^|]*\|[^|]*\|\s*\*\*)\d+(\*\*)",
                       rf"\g<1>{old_glob}\g<2>", text)
    assert stale_row != text, "夹具前提：§1.5 的 `清单 glob 数` 那一行还在"
    assert manifest_claim_problems(stale_row, measured), (
        f"§1.5 表格里的 glob 数改回 {old_glob} 之后判据必须红"
    )


# ---- `G3`：当前值声明不许带历史记号（`_HISTORICAL_MARKERS` 的豁免是逐行的）

#: 必须被对账到的那些"当前值 / 当次读数"行的行内特征（刻意不写行号：行号易失）。
#: 用特征而不是行号，是为了让"这些行被删掉"也变成一个可红的结论（见下面的失去对象分支）。
_CURRENT_VALUE_ANCHORS: tuple[str, ...] = (
    "| `.noai-paths` | **已存在**",              # §0.1 的当前值行
    "| **清单 glob 数** |",                       # §1.5 的三个数（当前值）
    "| **唯一路径数** |",
    "| **禁改区类别数** |",
    "| 哪些路径是禁 AI 区（当次",                  # §5 的当次读数
    "| **FC-27** | 禁 AI 区必须显式列出",          # §9.1 的当次读数
)


def historical_marker_leak_problems(text: str) -> list[str]:
    """当前值行被历史记号整行豁免 ⇒ 问题清单（`G3` 修的那个结构性漏口）。

    为什么需要单独一条：`manifest_claim_problems`（以及 `rule_claim_problems` /
    `tally_claim_problems`）对带 `_HISTORICAL_MARKERS` 的行整行跳过；而
    "当前值 + 句尾一句更正说明"这种写法会把自己整行豁免掉 ——
    于是数字漂了也没有任何东西会红。`G3` 实测到的形态就是这一条：
    `DEVELOPMENT.md` §0.1 的 `.noai-paths` 那一行写了当前值 23/20/16/32，
    句尾又带了「本条原写…」⇒ 整行退出对账 ⇒ 清单从 23 加到 26 时只有别处报红，这一处静默漂。

    处置（两步，缺一不可）：
     ① 把更正说明拆到另一段（当前值那一句不许带历史标记）；
     ② 留一条判据看着"它没有被搬回去" —— 否则同一个漏口可以静默复发。
    本条就是第 ② 步。它与"判据变软"相反：它把判据的覆盖面从"行"精确到"当前值那一行"。

    口径：一行只要含 `_CURRENT_VALUE_ANCHORS` 里任一特征，就不许含任何一个历史记号。
    一条锚点都没命中 ⇒ 报"失去对象"（删掉这些行不等于它们的数字是对的）。
    单条锚点在文档里找不到 ⇒ 也报出来：锚点必须是那一行的「逐字副本」，
    锚点自己漂了（例如把成对星号写成别的括号）就等于那一行的数字脱管。
    """
    problems: list[str] = []
    hits = 0
    for i, line in enumerate(text.splitlines(), 1):
        if not any(anchor in line for anchor in _CURRENT_VALUE_ANCHORS):
            continue
        hits += 1
        marks = [m for m in _HISTORICAL_MARKERS if m in line]
        if marks:
            problems.append(
                f"`DEVELOPMENT.md:{i}` 是当前值 / 当次读数声明，却带了历史记号 {marks} ⇒ "
                f"整行退出对账（`G3` 修的那个结构性漏口复发了）：{line.strip()[:90]}")
    for anchor in _CURRENT_VALUE_ANCHORS:
        if anchor not in text:
            problems.append(
                f"当前值锚点 {anchor!r} 在这份文档里找不到 ⇒ 锚点自己漂了"
                "（锚点必须是那一行的逐字副本；锚点漂了，那一行的数字就不受任何判据看管）")
    if not hits:
        problems.append("一处当前值锚点都没命中 ⇒ 判据失去对象"
                        "（把这些行删掉、或改掉它们的行内特征，都不等于数字是对的）")
    return problems


def test_current_value_lines_do_not_carry_historical_markers():
    """正控（`G3`）：§0.1 / §1.5 / §5 / §9.1 的当前值行都不许带历史记号。

    这一条是"把更正说明拆到另一段"那一步的机器验收：拆完必须有一条判据看着它不被搬回去。
    """
    problems = historical_marker_leak_problems(DEV_MD.read_text(encoding="utf-8"))
    assert not problems, problems


def test_the_historical_marker_leak_criterion_is_not_vacuous():
    """负控（`G3` 的验收）：把更正说明搬回当前值那一行 ⇒ 判据必须红；空输入 ⇒ 失去对象。"""
    text = DEV_MD.read_text(encoding="utf-8")
    assert not historical_marker_leak_problems(text), "夹具前提：当前字节上是干净的"

    # 负控夹具按"行内特征"注入（不写行号）：把 `G3` 拆出去的那句更正说明搬回当前值行。
    leaky = re.sub(r"(?m)^(> \| `\.noai-paths` \| \*\*已存在\*\*.*)\|$",
                   r"\1（本条原写 19 条条目 + 7 个分组） |", text)
    assert leaky != text, "夹具前提：§0.1 的 `.noai-paths` 当前值行还在（且以 `|` 收尾）"
    assert historical_marker_leak_problems(leaky), (
        "把更正说明搬回当前值那一行之后判据还是绿的 ⇒ 这条判据是恒真的（`G3` 的漏口又静默了）"
    )

    # 反真空：把锚点行整段删掉 ⇒ 必须报失去对象，不许读成"没问题"
    stripped = "\n".join(ln for ln in text.splitlines()
                         if not any(a in ln for a in _CURRENT_VALUE_ANCHORS))
    assert stripped != text, "夹具前提：锚点行可被删掉"
    assert any("失去对象" in p for p in historical_marker_leak_problems(stripped)), (
        "锚点行全删之后必须报失去对象（`G3`：删掉对象不许读成通过）"
    )

    # 反真空之二：锚点自己漂了（成对星号被改写成别的括号）⇒ 必须报出来。
    # 这一条是 2026-10-03 实测到的形态：一次「清掉注释里的成对星号」的批量改写
    # 把锚点字符串里的成对星号一起换掉了，锚点从此与文档不再逐字相同
    # —— 那一行的数字于是脱管，而上面那条负控仍然绿着。
    drifted = text.replace(_CURRENT_VALUE_ANCHORS[0],
                           _CURRENT_VALUE_ANCHORS[0].replace("**", "「", 1))
    assert drifted != text, "夹具前提：§0.1 的那一行含锚点字面量"
    assert any("找不到" in p for p in historical_marker_leak_problems(drifted)), (
        "锚点写法漂了之后判据必须红：否则被看管的那一行悄悄换了形态而没有东西会红"
    )


# ---- `R7-R6-4`：文档里点名的每个测试对象都必须在盘上存在

#: 带 `::` 的引用形态：文件 + 函数都要能核。
_DOC_TEST_REF_RE = re.compile(r"([\w./-]*tests?/[\w./-]+\.py)::(test_[A-Za-z0-9_]+)")
#: 裸名字形态（`test_xxx`）：解析成 `tests/test_xxx.py` 文件或某个文件里的 `def test_xxx(`。
_DOC_BARE_TEST_RE = re.compile(r"\btest_[A-Za-z0-9_]*[A-Za-z0-9]\b")
#: 路径形态（`tests/test_xxx.py`，可带前缀目录）：让报错能逐字说出"点名的文件不存在"，
#: 而不是把一处死路径降级成一处"测试对象找不到"（两者对读者的指向不同）。
_DOC_TEST_PATH_RE = re.compile(r"[\w./-]*tests?/[\w./-]*\.py")

#: `R7-R6-4` 判据扫的文档面。`R6-AN-2` 的配套把 `NOAI-REVIEW-REGISTER.md` 加了进来：
#: 那份文件是历史档案（它的计数不随盘上事实更新，当前值以 `README.md` §6.2 /
#: `DEVELOPMENT.md` §1.5 为准），但它点名的测试对象必须是今天还在盘上的东西 ——
#: 读者照它去跑一条命令，跑不到就是一条死指路（`R6-4` 实测它原写的
#: `tests/test_extract.py` 已不存在）。判据今天对这份文件原本完全没牙。
_DOC_TEST_REF_DOCS = ("DEVELOPMENT.md", "README.md", "DESIGN-TOOLS.md",
                      "NOAI-REVIEW-REGISTER.md")

_TESTS_INDEX: dict[str, set[str]] = {}


def _tests_index() -> dict[str, set[str]]:
    """盘上真实的测试对象索引（文件名集合 + 全部 `test_*` 函数名），读一次缓存。"""
    if _TESTS_INDEX:
        return _TESTS_INDEX
    names: set[str] = set()
    defined: set[str] = set()
    for p in (REPO / "tests").rglob("*.py"):
        names.add(p.name)
        defined |= set(re.findall(r"^def (test_[A-Za-z0-9_]+)\s*\(",
                                  p.read_text(encoding="utf-8", errors="replace"), re.M))
    _TESTS_INDEX["names"] = names
    _TESTS_INDEX["defined"] = defined
    return _TESTS_INDEX


def doc_test_reference_problems(docs: dict[str, str]) -> list[str]:
    """文档里点名的测试对象 vs 盘上事实 ⇒ 问题清单（`R7-R6-4`）。

    缺陷形态（`R7-R6-4` 实测）：`DEVELOPMENT.md` 的 `LIVE-READINGS` 导语点名
    `test_documented_live_readings_match_the_repo`，而全仓没有这个名字 ——
    判据其实在（真名见那一行），只是文档指不到 ⇒ 照着核对的人会得出相反的结论。
    这与 `R6-AN-3`（文档指一个不存在的工具名）同族，所以处置也一样：让文档的每个
    指路都被一条判据核过。

    口径：`tests/xxx.py::test_yyy` 要求文件与函数都在；裸 `test_xxx` 要求它至少能
    解析成 `tests/test_xxx.py` 文件、或某个测试文件里的 `def test_xxx(`；裸名字若出现在
    路径形态里（`tests/test_xxx.py`）而文件不在盘上，报的就是"点名的文件不存在" ——
    读者照它去跑命令，跑不到是最直接的那一种坏。
    一段文字里一个测试对象都没点名 ⇒ 报"失去对象"（空输入不许读成通过）。

    `R6-AN-2` 的配套把 `NOAI-REVIEW-REGISTER.md` 加进了调用面的文档集合：它是一份历史档案
    （见 `_DOC_TEST_REF_DOCS`），但那不表示它点名的命令可以指到不存在的东西。
    """
    index = _tests_index()
    problems: list[str] = []
    hits = 0
    for name, text in docs.items():
        for i, line in enumerate(text.splitlines(), 1):
            if any(mark in line for mark in _CORRECTION_MARKERS):
                # 更正说明会逐字引用旧名字（那是"它曾经写错成什么"的记录，不是指路）
                continue
            for path, fn in _DOC_TEST_REF_RE.findall(line):
                hits += 1
                p = REPO / path
                if not p.is_file():
                    problems.append(f"{name}:{i} 点名的文件不存在：{path}")
                elif not re.search(rf"^def {re.escape(fn)}\s*\(", p.read_text(
                        encoding="utf-8", errors="replace"), re.M):
                    problems.append(f"{name}:{i} 点名的用例不存在：{path}::{fn}")
            for tok in _DOC_BARE_TEST_RE.findall(line):
                if f"{tok}.py" in index["names"] or tok in index["defined"]:
                    hits += 1
                    continue
                as_path = next((m for m in _DOC_TEST_PATH_RE.findall(line)
                                if m.rsplit("/", 1)[-1] == f"{tok}.py"), "")
                if as_path:
                    problems.append(f"{name}:{i} 点名的文件不存在：{as_path}")
                    continue
                problems.append(f"{name}:{i} 点名的测试对象在盘上找不到（既不是 "
                                f"`tests/{tok}.py`，也不是任何 `def {tok}(`）：{line.strip()[:90]}")
    if not hits:
        problems.append("这几份文档里一个测试对象都没点名 ⇒ 判据失去对象")
    return problems


def test_every_doc_reference_to_a_test_object_exists_on_disk():
    """正控（`R7-R6-4`）：`_DOC_TEST_REF_DOCS` 点名的每个测试对象都必须能在 `tests/` 里找到。

    这一条把"文档指一个不存在的东西"从散文变成判据。它是 `R7-R6-4` 的直接处置：
    那个名字（`test_documented_live_readings_match_the_repo`）今天在盘上不存在，
    改对之后这条绿；再写错一个字母，它立刻红。

    覆盖面本身也被这条判据守着一半：下面那句断言要求文档集合里必须含
    `NOAI-REVIEW-REGISTER.md`（`R6-AN-2` 的配套）—— 把那份历史档案从集合里删掉，
    这一条会当场红，而不是静默地少核一份文件。
    """
    docs = {n: (REPO / n).read_text(encoding="utf-8") for n in _DOC_TEST_REF_DOCS}
    assert "NOAI-REVIEW-REGISTER.md" in docs and len(docs) == 4, (
        "文档集合必须含历史档案 `NOAI-REVIEW-REGISTER.md`（`R6-AN-2` 的配套）："
        "少了它就等于那一整份文件里的指路又没人核")
    problems = doc_test_reference_problems(docs)
    assert not problems, problems


def test_the_doc_reference_criterion_is_not_vacuous():
    """负控（`R7-R6-4` 的验收）：把名字改回那个不存在的名字 ⇒ 判据必须红。

    第三档是 `R6-AN-2` 的配套（register 的验收原文）：在内存里把 register 点名的
    `tests/test_verify_quote_levels.py` 换成 `tests/test_does_not_exist_zzz.py`
    ⇒ 扩展后的判据必须报"点名的文件不存在"，并逐字给出那个路径。
    改前这一注入返回 `[]`（register 不在文档集合里）；盘上那份档案一个字节都不动。
    """
    docs = {n: (REPO / n).read_text(encoding="utf-8") for n in _DOC_TEST_REF_DOCS}
    assert not doc_test_reference_problems(docs), "夹具前提：当前字节上是干净的"

    real = "test_development_md_linter_readings_and_rule_range_match_the_repo"
    bad_dev = docs["DEVELOPMENT.md"].replace(real, "test_documented_live_readings_match_the_repo")
    assert bad_dev != docs["DEVELOPMENT.md"], "夹具前提：文档里有那个真名可改"
    assert doc_test_reference_problems(dict(docs, **{"DEVELOPMENT.md": bad_dev})), (
        "改回那个不存在的名字之后判据必须红（`R7-R6-4` 的原形态）"
    )
    assert doc_test_reference_problems({"DEVELOPMENT.md": "这一行没有点名任何测试。"}), (
        "一个测试对象都没点名时必须报失去对象"
    )

    # `R6-AN-2` 的配套（register 那一档）：改前这一注入返回 `[]`。
    register = docs["NOAI-REVIEW-REGISTER.md"]
    bad_register = register.replace("tests/test_verify_quote_levels.py",
                                    "tests/test_does_not_exist_zzz.py")
    assert bad_register != register, "夹具前提：register 里点名的那个文件还在"
    register_problems = doc_test_reference_problems(
        dict(docs, **{"NOAI-REVIEW-REGISTER.md": bad_register}))
    assert any("点名的文件不存在：tests/test_does_not_exist_zzz.py" in p
               for p in register_problems), (
        f"把 register 点名的文件换成不存在的文件之后判据必须报'点名的文件不存在'："
        f"{register_problems}")


#: `.noai-paths` 在 `README.md` 文件树里那一行的两个数。
_README_MANIFEST_RE = re.compile(
    r"\.noai-paths\s+禁改区清单（\*\*(\d+)\*\*\s*条 glob\s*/\s*\*\*(\d+)\*\*\s*条唯一路径")
#: `README.md` 工具层那一行的模块数（今天的写法是"N 个 `*_tools.py`"）。
_README_TOOLS_RE = re.compile(r"\*\*(\d+)\*\*\s*个 `\*_tools\.py`")


def readme_number_problems(text: str, measured: dict[str, int]) -> list[str]:
    """`README.md` 文件树里的两个数与实测比较（`R6-AN-6`）。"""
    problems: list[str] = []
    m = _README_MANIFEST_RE.search(text)
    if not m:
        problems.append("`README.md` 文件树里读不到 `.noai-paths` 那一行的 glob/唯一路径数 ⇒ 失去对象")
    else:
        if int(m.group(1)) != measured["noai_paths_glob"]:
            problems.append(f"README 写 `{m.group(1)}` 条 glob，实测 {measured['noai_paths_glob']}")
        if int(m.group(2)) != measured["noai_paths_unique"]:
            problems.append(f"README 写 `{m.group(2)}` 条唯一路径，实测 {measured['noai_paths_unique']}")
    t = _README_TOOLS_RE.search(text)
    if not t:
        problems.append("`README.md` 工具层那一行读不到 `N 个 *_tools.py` 的数 ⇒ 失去对象")
    elif int(t.group(1)) != measured["tools_star_tools_py"]:
        problems.append(f"README 写 `{t.group(1)}` 个 `*_tools.py`，实测 {measured['tools_star_tools_py']}")
    return problems


def test_readme_file_tree_numbers_match_the_repo():
    """正控（`R6-AN-6`）：`README.md` 文件树的 `.noai-paths` 数与工具模块数必须实测一致。

    同族的两处数字此前各有一个"另一个值"：文件树写 21/18，而同一文件 §6.2 已经写 23/20；
    工具层写"共 12 个模块"，而实测 11 个 `*_tools.py`。这条把文件树那一行铆在盘上事实上。
    """
    text = README_MD.read_text(encoding="utf-8")
    problems = readme_number_problems(text, measured_readings())
    assert not problems, problems


def test_the_readme_numbers_criterion_is_not_vacuous():
    """负控（`R6-AN-6` 的验收）：把文件树那两个数改回旧值 ⇒ 判据必须报问题。"""
    text = README_MD.read_text(encoding="utf-8")
    measured = measured_readings()
    stale = text.replace(f"**{measured['noai_paths_glob']}** 条 glob",
                         f"**{measured['noai_paths_glob'] - 2}** 条 glob")
    assert stale != text, "夹具前提：README 文件树里有 glob 数可改"
    assert readme_number_problems(stale, measured), "改回 21 之后判据必须红"
    stripped = _README_MANIFEST_RE.sub(".noai-paths  禁改区清单（口径见 §6.2）", text)
    assert stripped != text, "夹具前提：那一行可被替换掉"
    assert readme_number_problems(stripped, measured), "把数字整段删掉必须报失去对象"


# ---- `R11-R6-1`：台账派生量（`reviewers_total` / 欠签 / `entries`）必须带观测时刻或历史记号
#
# 缺陷形态（第 11 轮 `R6` 审计的 `R11-R6-1`）：把已经漂了的台账派生量当"当前值"写死，
# 而那一行既没有观测时刻、也没有历史记号 —— 读者按它判断"还有多少签字工作没做"会得到相反的
# 答案（`README.md` §6.2 写"`reviewers_total` 40 ⇒ 欠签 4、两条 0 签的条目是台账与
# `pyproject.toml`"，而盘上台账是欠签 2、0 签的只剩不能自签的台账自己 —— `pyproject.toml`
# 已由人补签 2/2）。同一族的第二处是 `tests/test_release_check_noai.py` 的 `F10` 分节注释。
#
# 处置不是"把 40 改成 44"（那只把漂移推迟到下一次签字）：这一族的合规形态只有两种 ——
#   ① 不写定值、只留"量它的命令"（本轮 `README.md` §6.2 与 `DEVELOPMENT.md` §1.5 的台账两格就是这么改的）；
#   ② 写了定值就必须在同一行带历史记号（`当时`/`原写`/…，与 `_HISTORICAL_MARKERS` 同一张表），
#      或带"观测时刻（`YYYY-MM-DD HH:MM`）+ 复算命令"。
# 本条把这两种形态变成机器可判的：任何一处台账派生量，两种都不满足就报问题。

#: 台账派生量在散文/表格里的写法（`R11-R6-1` 点名的形态）。
#: 为什么不收裸的 `<N> 条目`（派单里列了这一形态）：它会误收"§4.2 条目号""`A-20` 条目"
#: 这类与台账无关的行（实测命中：`docs/PROPOSALS.md:4100`、`docs/SCHEMA-DRAFT-management.md:122`），
#: 判据会因此变成假红来源。所以只收带台账上下文的形态（`台账 … N 条目` / `N 台账条目`）。
_LEDGER_CLAIM_RES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("`reviewers_total`", re.compile(r"reviewers[_\s]*total\s*[`*=\s]*(\d+)")),
    ("`reviewers` 元素总数", re.compile(r"元素总数\s*[`*=\s]*(\d+)")),
    ("欠签数", re.compile(r"欠签\s*[`*=\s]*(\d+)")),
    ("`entries` 条数", re.compile(r"\bentries\b[`*=\s]*(\d+)")),
    ("`N 条 entry`", re.compile(r"(\d+)\s*条\s*entry")),
    ("reviewers 逐条分布", re.compile(r"\{\s*0\s*:\s*\d+\s*,\s*2\s*:\s*\d+\s*\}")),
    ("台账条目数", re.compile(r"台账[`*=\s]{0,4}(\d+)[`*=\s]{0,4}条目")),
    ("台账条目数", re.compile(r"(\d+)[`*=\s]{0,4}台账[`*=\s]{0,4}条目")),
    ("台账条目数", re.compile(r"台账条目数[^\n]*?\*\*(\d+)\*\*")),
)
#: 可复算的观测时刻：`YYYY-MM-DD HH:MM`（秒可省）。刻意不认 `15:1x` 与裸 `17:20` 两种写法 ——
#: 不可复算的"时刻"与"没有时刻"在"读者能不能自己核"这件事上没有区别（`R11-R6-1` 的原始形态
#: 正是"写了『观测 2026-09-27』却没有时分、也没有命令"）。
#:
#: `R11C-R6-1`（`FIX13` 修过头留下的净变松）：`R11B-R6-1` 把"自称当次"那一档从块级下沉到逐行
#: 是对的，但那一版给这一档认的"观测时刻"是裸 `HH:MM`、并把复算命令去掉了 —— 于是
#: `docs/*.md` 里自称当次的行只要凑出一个 digit:digit（无日期、无命令、无历史记号）就算"有据"：
#: `「回写（观测 17:20）」` 这种写法能把过期的台账派生量继续按"当前值"放行，而同一句写进当前值
#: 文档却是红的 ⇒ 同一形态两档判定相反，且比改前（那一版不认裸 `HH:MM`）更松。处置：这一档改用
#: 当前值文档那一档的口径（两档合一）—— 本行的 `_LEDGER_TS_RE` 与 `_LEDGER_CMD_RE` 必须同时
#: 成立才放行，原来那个更宽的裸时刻形态（_LEDGER_CLOCK_RE = \d{1,2}:\d{2} —— 此处刻意不加反引号：该名字已删、属历史叙述）随之删除。
_LEDGER_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}")
_LEDGER_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
#: 这行/这块里出现它，就说明"给出了复算办法"（与文档里既有的写法一致）。
_LEDGER_CMD_RE = re.compile(
    r"python|Select-String|--check-approvals|--baseline|_ledger_snapshot|"
    r"\.noai-approvals\.json|json\.load|reviewers\.length")
#: `docs/*.md` 是登记册 / 历史档案（`PROPOSALS.md` 首行自陈"不构成判据"、
#: `NOAI-SUSPENSION-*.md` 自陈"治理记录"）：里面的数默认是当时的读数，只有自称当次的行
#: 才算"当前值声明"。这一条是把"哪一种行需要时刻"写清，不是放宽 —— 覆盖面的边界与实测读数
#: 逐条登记在交付报告 FIX12-B.md 里（刻意不加反引号：它落在 temp/ 下、属 scratch 产物、会被清理；
#: 而反引号里那种 temp 路径由 test_r5_orchestration_cost.py 的存在性判据看着）。
_LEDGER_LIVE_WORDS = ("当次", "当前", "今天", "今日", "现在", "实测", "此刻")
#: 逐行硬判的"当前值文档"。为什么它们的口径比 `docs/*.md` 严：读者就是拿这两份文档里的
#: 读数判断"现在要不要签字"，所以一行必须自证它是什么时候的读数。
_LEDGER_LINE_SCOPED_DOCS = ("README.md", "DEVELOPMENT.md")


def ledger_counts(root: Path | None = None) -> dict[str, object]:
    """当次读真实台账（`.noai-approvals.json`）并算出那三个派生量。

    为什么读它：报错信息要能说清"你写的数与当次差在哪"，读者不必再跑一遍命令。
    为什么不拿它当等值判据（"文档里的数必须等于当次"）：台账每被人签一个字就变，而签字是
    正常动作 ⇒ 等值判据会把"人做了对的事"变成一片红，红多了就没人看它了。所以本条落到的
    机器判据是"有没有时刻 / 有没有历史记号"这一档（派单给的退档口径），等值只出现在
    报错信息里供人一眼对拍。

    `root` 只是给"离仓副本"的控制装置用（默认 `REPO`）；判据本体始终读 `REPO` 那一份。
    """
    base = REPO if root is None else root
    from collections import Counter  # noqa: PLC0415

    data = json.loads((base / ".noai-approvals.json").read_text(encoding="utf-8"))
    entries = data["entries"]
    reviewers_total = sum(len(e.get("reviewers", [])) for e in entries)
    dist = Counter(len(e.get("reviewers", [])) for e in entries)
    return {
        "entries": len(entries),
        "reviewers_total": reviewers_total,
        "dist": "{" + ", ".join(f"{k}: {v}" for k, v in sorted(dist.items())) + "}",
        "zero": sorted(e["path"] for e in entries if not e.get("reviewers")),
        "owed": len(entries) * 2 - reviewers_total,
    }


def ledger_docs() -> dict[str, str]:
    """判据扫的三份文档面：`README.md` / `DEVELOPMENT.md` / `docs/*.md`。"""
    docs = {n: (REPO / n).read_text(encoding="utf-8") for n in _LEDGER_LINE_SCOPED_DOCS}
    for p in sorted((REPO / "docs").glob("*.md")):
        docs[f"docs/{p.name}"] = p.read_text(encoding="utf-8")
    return docs


def _ledger_units(name: str, text: str) -> list[list[tuple[int, str]]]:
    """判据的作用域：当前值文档逐行；`docs/*.md` 逐块（连续非空行 = 一段/一张表/一个引用块）。

    为什么要分两档：`docs/*.md` 的登记块是"一次回写"这个单位（块内本来就写明了观测日期），
    按行判会把整本登记册变成假红；而当前值文档里的一行就是一条独立声明，按块判会把
    "表里另一格有日期"读成"这一格有日期" —— 那恰好是唯一能咬人的那一档被放掉。
    """
    lines = text.splitlines()
    if name in _LEDGER_LINE_SCOPED_DOCS:
        return [[(i + 1, ln)] for i, ln in enumerate(lines)]
    blocks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    for i, ln in enumerate(lines, 1):
        if ln.strip():
            cur.append((i, ln))
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    return blocks


def ledger_derived_claim_problems(docs: dict[str, str], ledger: dict[str, object]) -> list[str]:
    """台账派生量 vs "有没有观测时刻 / 历史记号" ⇒ 问题清单（`R11-R6-1` 的根因判据）。

    口径（逐句对应下面每一处 `continue`）：
      * 当前值文档（`README.md` / `DEVELOPMENT.md`）逐行判：一行就是一条独立声明，
        它必须自带历史记号（`_HISTORICAL_MARKERS`）或"观测时刻（`YYYY-MM-DD HH:MM`）+
        复算命令"，否则命中即报问题。这两个文件的块就是"一行"，所以它们的合规形态比
        `docs/*.md` 严一档：同一行自证（"紧邻行"那一档在单行块里没有意义）；
      * `docs/*.md` 里不带现时词（`_LEDGER_LIVE_WORDS`）的行 ⇒ 成立：登记册 / 历史档案
        的正文算"当时的读数"，块带不带日期都放过（这条是"块级豁免"的真身 —— 放行的是
        "行内没有现时词"，不是"块里有日期"）；
      * `docs/*.md` 里自称当次的行（行内有现时词 + 有台账派生量）是"当前值声明"：
        该行自己、或同块里的紧邻行（上一行 / 下一行）必须带历史记号（`_HISTORICAL_MARKERS`），
        或同时具备观测时刻（`YYYY-MM-DD HH:MM`，见 `_LEDGER_TS_RE`）与复算命令
        （`_LEDGER_CMD_RE`），否则报问题 —— 块里带日期不能替它作证（`R11B-R6-1`：旧口径在逐行判
        之前就按块里的日期把整块 `continue` 掉，于是"自称当次 + 只带日期"这一档从来没被咬过）；
      * 裸 `HH:MM`（无日期、无命令）在这一档不算"有据"：它与当前值文档那一档口径一致 ——
        只认可复算的观测时刻 + 复算命令（`R11C-R6-1`：`FIX13` 曾把这一档实现成认裸 `HH:MM`，
        于是 `「回写（观测 17:20）」` 这种写法把过期读数放行成了"当前值"）；
      * 复算命令（`_LEDGER_CMD_RE`）在 `docs/*.md` 这一档是观测时刻的连体条件（不是独立
        通行证）：紧邻行只写命令、只写裸时刻、或块里别处写了命令，都不算数。它同时是当前值文档
        那一档的必需项（第 1 条："`YYYY-MM-DD HH:MM` + 复算命令"），也是本判据推荐的
        "量它的命令"写法。
      * `docs/*.md` 的抬头（前 30 行）写明观测时刻 ⇒ 整份文件按那个时刻读（`NOAI-SUSPENSION-2026-09-25.md`
        就是这种：抬头逐字写着"生效时刻（观测）：2026-09-25（…本地时间 2026-09-25 22:37 起）"）。
        这一档是文件级的，对自称当次的行同样成立 —— 抬头那个时刻就是这份记录里每一行的时刻。
    其余命中一律报问题，并附上当次台账的三个派生量。

    反真空不写成"一处都读不到就报失去对象"：这一族的合规终态就是不写定值
    （`R11-R6-1` 的首选修法），所以"读不到"可能是对的。咬人的证明由
    `test_the_ledger_derived_claim_criterion_is_not_vacuous` 的注入负控承担。
    """
    problems: list[str] = []
    for name, text in docs.items():
        lines = text.splitlines()
        line_scoped = name in _LEDGER_LINE_SCOPED_DOCS
        file_clock = (not line_scoped
                      and bool(_LEDGER_TS_RE.search("\n".join(lines[:30]))))
        for block in _ledger_units(name, text):
            block_text = "\n".join(ln for _, ln in block)
            block_linenos = {no for no, _ in block}
            for lineno, line in block:
                # 日期先从行里摘掉：`2026-09-27` 不是读数（否则 `entries` 后面的 `2026`
                # 会被当成"条目数"）。
                plain = _LEDGER_DATE_RE.sub("<日期>", line)
                hits = [(key, got) for key, rx in _LEDGER_CLAIM_RES
                        for got in rx.findall(plain)]
                if not hits:
                    continue
                if line_scoped:
                    # 当前值文档：一行就是一条独立声明，逐行判（块 == 这一行）。
                    if (any(m in block_text for m in _HISTORICAL_MARKERS)
                            or (_LEDGER_TS_RE.search(block_text)
                                and _LEDGER_CMD_RE.search(block_text))):
                        continue
                elif not any(w in line for w in _LEDGER_LIVE_WORDS):
                    # 登记册 / 历史档案的正文：不带现时词 = 当时的读数（块级豁免的真身）。
                    continue
                else:
                    # 自称当次的那一行：本行或同块紧邻行必须能自证时刻/历史（`R11B-R6-1`）。
                    window = "\n".join(
                        [line] + [lines[no - 1] for no in (lineno - 1, lineno + 1)
                                  if no in block_linenos])
                    # 与当前值文档那一档对齐：观测时刻（`YYYY-MM-DD HH:MM`）与复算命令必须
                    # 同时成立才放行。裸 `HH:MM` 不算 —— 它不可复算、也不唯一
                    # （`R11C-R6-1`：`FIX13` 曾在这一档认裸 `HH:MM`，比改前更松）。
                    if (file_clock
                            or (_LEDGER_TS_RE.search(window)
                                and _LEDGER_CMD_RE.search(window))
                            or any(m in window for m in _HISTORICAL_MARKERS)):
                        continue
                for key, got in hits:
                    problems.append(
                        f"`{name}:{lineno}` 把{key}写成 {got}，既没有历史记号、也没有"
                        f"「观测时刻（YYYY-MM-DD HH:MM）+ 复算命令」（两者必须同时成立；"
                        f"裸 `HH:MM` 不算时刻，它不可复算）。当次台账是 "
                        f"entries {ledger['entries']} / reviewers "
                        f"{ledger['reviewers_total']}（逐条分布 {ledger['dist']}）/ "
                        f"欠签 {ledger['owed']}；0 签的条目是 {ledger['zero']} —— 请改成"
                        f"「不写定值 + 量它的命令」或「观测 <时刻> ⇒ <值>」：{line.strip()[:90]}")
    return problems


def test_doc_ledger_derived_claims_carry_time_or_history():
    """正控（`R11-R6-1`）：三份文档面里的每一处台账派生量都必须带时刻或历史记号。

    这一条是"只把 40 改成 44 不算修好"的机器体现：数字可以写，但必须让读者能判断它是
    什么时候的读数；不带时刻的定值会一直漂，而这一次漂的代价是"还欠多少签字"被读反。
    """
    problems = ledger_derived_claim_problems(ledger_docs(), ledger_counts())
    assert not problems, problems


def test_the_ledger_derived_claim_criterion_is_not_vacuous():
    """负控（`R11-R6-1` 的验收）：把不带时刻/历史记号的定值塞回去 ⇒ 判据必须红。

    八档（在内存里改文本，不碰盘上那三份文档；离仓整树副本上的同型控制读数由
    temp/FIX12B-negctl.py、temp/fix13-negctl.py 与 temp/fix14-negctl.py 产出 —— 刻意不加
    反引号：它们在 temp/ 下、属 scratch、会被清理，而反引号里的 temp 路径会被存在性判据当真）：
      ① 负控 A：`README.md` 里塞回 `reviewers_total` 40（审计者点名的形态）⇒ 必须红；
      ② 负控 B：`docs/*.md` 的无日期块里塞一条"当次"读数 ⇒ 必须红（docs 那一档也有牙）；
      ③ 正控：同一句话带观测时刻 + 复算命令 ⇒ 不红；
      ④ 正控：同一句话带历史记号（`当时`）⇒ 不红；
      ⑤ 负控 C（`R11B-R6-1`）：`docs/*.md` 的带日期块里塞一条"当次"读数、块内没有任何
         时分/历史记号 ⇒ 必须红（旧口径在这里整块放行 —— 这一档是这一轮修的那个洞）；
      ⑥ 正控：同句的紧邻行带「`YYYY-MM-DD HH:MM` + 复算命令」⇒ 不红；紧邻行带历史记号 ⇒ 不红；
      ⑦ 负控 D（`R11C-R6-1`）：同句的紧邻行只带裸 `HH:MM`（无日期、无命令）⇒ 必须红；
         换成 `17:2`（不构成 `HH:MM`）⇒ 同样必须红；同一句写进 `README.md` ⇒ 同样必须红
         （两档对齐）。`FIX13` 把这一档实现成放行（裸 `HH:MM` 就算"有据"）而成绿，而那时这条
         夹具只有 ⑥ 档 —— ⑥ 的紧邻行还带着日期与命令，所以那次变宽没被自己的夹具发现；
      ⑧ 正控：带日期的块里不带现时词的历史行（有数字、带"当时"）⇒ 不红
         （口径是"行内没有现时词就放过"，不是"块里有日期就放过"；别把整本登记册判红）。
    """
    docs = ledger_docs()
    ledger = ledger_counts()
    assert not ledger_derived_claim_problems(docs, ledger), "夹具前提：当前字节上是干净的"

    stale_line = "\n台账 `reviewers_total` **40** ⇒ 欠签 **4**（两条 0 reviewer 的条目）\n"
    readme = docs["README.md"]
    stale = dict(docs, **{"README.md": readme + stale_line})
    assert stale["README.md"] != readme, "夹具前提：注入真的落到了文本上"
    assert ledger_derived_claim_problems(stale, ledger), (
        "把 `reviewers_total` **40**（不带时刻、不带历史记号）塞回 README 之后判据还是绿的 ⇒ 没牙")

    ok_ts = ("\n台账 `reviewers_total` **40** ⇒ 欠签 **4**"
             "（观测 2026-09-27 16:45:58；复跑 `python temp\\_ledger_snapshot.py`）\n")
    assert not ledger_derived_claim_problems(dict(docs, **{"README.md": readme + ok_ts}), ledger), (
        "带「观测时刻 + 复算命令」的读数不许被判红（那是本判据认的合规形态）")
    ok_hist = "\n（**当时**的读数：台账 `reviewers_total` **40** ⇒ 欠签 **4**）\n"
    assert not ledger_derived_claim_problems(dict(docs, **{"README.md": readme + ok_hist}), ledger), (
        "带历史记号的读数不许被判红（历史观测本来就该留）")

    docs_name = "docs/PROPOSALS.md"
    docs_stale = dict(docs, **{docs_name: docs[docs_name] + "\n\n台账当次 `entries` **99**。\n"})
    assert ledger_derived_claim_problems(docs_stale, ledger), (
        "`docs/*.md` 的无日期块里塞一条「当次」读数之后判据还是绿的 ⇒ docs 那一档没牙")

    # ⑤ 负控 C（`R11B-R6-1` 的原始形态）：块里带日期，但自称当次的那一行自己没有时分、
    #    也没有历史记号 ⇒ 必须红。旧口径在逐行判之前就按块里的日期 `continue` 掉了整块。
    docs_dated = dict(docs, **{docs_name: docs[docs_name] + (
        "\n\n**回写（2026-09-27）**\n"
        "台账当次 `reviewers_total` **40** ⇒ 欠签 **4**（两条 0 reviewer 的条目）。\n")})
    assert docs_dated[docs_name] != docs[docs_name], "夹具前提：注入真的落到了文本上"
    assert ledger_derived_claim_problems(docs_dated, ledger), (
        "带日期的块里塞一条「当次」读数（无时分、无历史记号）之后判据还是绿的 ⇒ "
        "`R11B-R6-1` 没修好：块里的日期不许替自称当次的行作证")

    # ⑥ 正控（`R11C-R6-1`）：同句的紧邻行带「观测时刻 + 复算命令」/ 带历史记号 ⇒ 不红
    #    （"紧邻行"这一档是新认的合规形态）。
    docs_ok_clock = dict(docs, **{docs_name: docs[docs_name] + (
        "\n\n**回写（观测 2026-09-27 17:20，复跑 `python temp\\_ledger_snapshot.py`）**\n"
        "台账当次 `reviewers_total` **40** ⇒ 欠签 **4**（两条 0 reviewer 的条目）。\n")})
    assert docs_ok_clock[docs_name] != docs[docs_name], "夹具前提：注入真的落到了文本上"
    assert not ledger_derived_claim_problems(docs_ok_clock, ledger), (
        "紧邻行带「`YYYY-MM-DD HH:MM` + 复算命令」的自称当次行不许被判红（那是本判据认的合规形态）")
    docs_ok_hist = dict(docs, **{docs_name: docs[docs_name] + (
        "\n\n**回写（2026-09-27，**当时**的读数）**\n"
        "台账当次 `reviewers_total` **40** ⇒ 欠签 **4**（两条 0 reviewer 的条目）。\n")})
    assert not ledger_derived_claim_problems(docs_ok_hist, ledger), (
        "紧邻行带历史记号的自称当次行不许被判红（历史观测本来就该留）")

    # ⑦ 负控 D（`R11C-R6-1` 的根因）：紧邻行只带裸 `HH:MM`（无日期、无命令、无历史记号）
    #    ⇒ 必须红。`FIX13` 把这一档实现成放行（_LEDGER_CLOCK_RE —— 此处刻意不加反引号：该名字已删），而这条夹具当时只有 ⑥ 档
    #    —— ⑥ 的紧邻行还带着日期与命令，所以那次变宽没被自己的夹具发现。下面这档就是补上它：
    #    与 ⑥ 只差"日期 + 命令"这半边，一红一绿必须分开断言。
    bare_clock = (
        "\n\n**回写（观测 17:20）**\n"
        "台账当次 `reviewers_total` **40** ⇒ 欠签 **4**（两条 0 reviewer 的条目）。\n")
    docs_bare_clock = dict(docs, **{docs_name: docs[docs_name] + bare_clock})
    assert docs_bare_clock[docs_name] != docs[docs_name], "夹具前提：注入真的落到了文本上"
    assert ledger_derived_claim_problems(docs_bare_clock, ledger), (
        "紧邻行只带裸 `HH:MM`（无日期、无命令）的自称当次行被判绿 ⇒ `R11C-R6-1` 没收紧："
        "裸时刻不可复算、也不唯一，不该与 ⑥ 档同判")
    # 同一句把 `17:20` 换成 `17:2`（不构成 `HH:MM`）⇒ 也必须红（判据不许只咬一种写法）。
    bare_clock2 = bare_clock.replace("17:20", "17:2")
    assert bare_clock2 != bare_clock, "夹具前提：替换真的落到了文本上"
    docs_bare_clock2 = dict(docs, **{docs_name: docs[docs_name] + bare_clock2})
    assert ledger_derived_claim_problems(docs_bare_clock2, ledger), (
        "只把裸 `17:20` 换成 `17:2` 判据就变绿 ⇒ 判据只在咬一种写法（`R11C-R6-1` 的验收："
        "两种都该红或都该绿）")
    # 两档对齐：同一句写进当前值文档 ⇒ 同样必须红（不许 docs 面绿、当前值文档面红）。
    docs_bare_clock_readme = dict(docs, **{"README.md": docs["README.md"] + bare_clock})
    assert ledger_derived_claim_problems(docs_bare_clock_readme, ledger), (
        "同一句写进 `README.md` 之后是绿的 ⇒ 同一形态两档判定相反（`R11C-R6-1` 的原始形态）")

    # ⑧ 正控：带日期的块里不带现时词的历史行 ⇒ 不红（放行的是"行内没有现时词"，
    #    不是"块里有日期" —— 这条守住"别把整本登记册变成假红"）。
    docs_hist = dict(docs, **{docs_name: docs[docs_name] + (
        "\n\n**回写（2026-09-27）**\n"
        "**当时**台账 `entries` **22** / `reviewers` 元素总数 **40**（保留供对照）。\n")})
    assert not ledger_derived_claim_problems(docs_hist, ledger), (
        "带日期的块里不带现时词的历史行不许被判红（别把整本登记册变成假红）")


#: 三处 `--json` 出口（`R6-AN-5` 点名的那三处）。
_JSON_WRITERS = ("tools/release_all.py", "scripts/release_check.py", "scripts/lint_rules.py")


def _write_text_call_lines(source: str) -> list[int]:
    """源码里真正的 `X.write_text(...)` 调用点（AST 口径，不数注释里提到的名字）。

    `R012` 的判据就是这个口径：注释里写"禁止 `Path.write_text()`"不算违规，
    真去调它才算。
    """
    import ast  # noqa: PLC0415

    out: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"):
            out.append(int(getattr(node, "lineno", 0)))
    return out


def newline_discipline_problems(readme_text: str, sources: dict[str, str]) -> list[str]:
    """换行纪律：三处 `--json` 出口都得是 `open(..., newline="")`，README 的说法要跟上。"""
    problems: list[str] = []
    for name, src in sources.items():
        if 'newline=""' not in src:
            problems.append(f"{name} 里找不到 `newline=\"\"`（产物会带上平台的换行）")
        calls = _write_text_call_lines(src)
        if calls:
            problems.append(f"{name} 里又出现了真正的 `write_text(` 调用（行 {calls}）")
    hits = 0
    for line in readme_text.splitlines():
        for n in _CRLF_RE.findall(line):
            if int(n) != 0 and not any(mark in line for mark in _HISTORICAL_MARKERS):
                problems.append(f"`README.md` 里写着 `CRLF={n}`（当次产物是 CRLF=0）："
                                f"{line.strip()[:80]}")
        if re.search(r"CR(?:LF)?\s*=\s*0", line) and not any(
                mark in line for mark in _HISTORICAL_MARKERS):
            hits += 1
    if not hits:
        problems.append("`README.md` 里读不到一处当次的 `CR=0` ⇒ 判据失去对象")
    return problems


def test_readme_newline_claims_match_the_json_writers():
    """正控（`R6-AN-5`）：README 关于 `--json` 出口的说法必须与三处实现一致。

    三处实现都是 `open(..., newline="")`，所以 README 里"`release_check` 的产物 CRLF=10"
    这句话是过期读数。这里同时钉住两边：实现侧（无 `write_text(`、有 `newline=""`）
    与文档侧（不写 `CRLF=10`、写着 `CR=0`）。
    """
    sources = {name: (REPO / name).read_text(encoding="utf-8") for name in _JSON_WRITERS}
    problems = newline_discipline_problems(README_MD.read_text(encoding="utf-8"), sources)
    assert not problems, problems


def test_the_newline_claims_criterion_is_not_vacuous():
    """负控（`R6-AN-5`）：副本里把一处改回 `write_text`、或把 README 改回 `CRLF=10` ⇒ 必须报问题。"""
    readme = README_MD.read_text(encoding="utf-8")
    sources = {name: (REPO / name).read_text(encoding="utf-8") for name in _JSON_WRITERS}
    assert not newline_discipline_problems(readme, sources), "夹具前提：当前字节上是干净的"

    name = "scripts/lint_rules.py"
    src = sources[name]
    injected = src.replace(
        'with open(args.json, "w", encoding="utf-8", newline="") as fh:',
        'with Path(args.json).write_text("") as fh:')
    assert injected != src, "夹具前提：注入点那一行必须在（不许注入到会被下一行覆盖的位置）"
    assert _write_text_call_lines(injected), "注入点的指纹：副本里必须真的出现一个 write_text 调用"
    bad_sources = dict(sources, **{name: injected})
    assert newline_discipline_problems(readme, bad_sources), (
        "副本里改回 `write_text` 之后判据还是绿的 ⇒ 这条判据没牙"
    )
    assert newline_discipline_problems(readme.replace("CR=0", "CRLF=10"), sources), (
        "把 README 改回 `CRLF=10` 之后判据必须红"
    )


#: `R6-AN-3` 点名的 5 个"注册表里不存在"的工具名（实测 0 命中）。
_GHOST_TOOL_NAMES = ("graph.hottest", "graph.paths", "graph.cold", "graph.gaps", "trace.quote")
#: 拆轴之前那句旧断言（它把 `graph.*`/`trace.*` 的第一根轴说成 `none`）。
_OLD_AXIS_SENTENCE = '**注意 `graph.*` 与 `trace.*` 都是 `side_effect="none"`（纯读）**'
#: 今天那句答案句（判据拿它当对象；改回去就必须红）。
_NEW_AXIS_SENTENCE = "**注意 `graph.*` 与 `trace.*` 的第一根轴都是 `read`（纯读），第二根轴都是 `none`**"


def graph_trace_facts() -> tuple[list[str], set[str], set[str]]:
    """实测 `graph.*` / `trace.*` 的工具名与两根轴（`R6-AN-3` 的判据依据）。"""
    from agentflow.tools import build_registry  # noqa: PLC0415

    reg = build_registry().registry
    names = sorted(n for n in reg.names() if n.startswith(("graph.", "trace.")))
    effects = {reg.get(n).side_effect for n in names}
    externals = {reg.get(n).declared_external for n in names}
    return names, effects, externals


def design_tools_problems(text: str, names: list[str], effects: set[str],
                          externals: set[str]) -> list[str]:
    """`DESIGN-TOOLS.md` 的 §1.1 表与紧随其后那句 vs 真注册表（`R6-AN-3`）。"""
    problems: list[str] = []
    ghosts = [n for n in _GHOST_TOOL_NAMES if n in text]
    if ghosts:
        problems.append(f"`DESIGN-TOOLS.md` 里仍有注册表里不存在的工具名：{ghosts}")
    missing = [n for n in names if f"`{n}`" not in text]
    if missing:
        problems.append(f"`DESIGN-TOOLS.md` 的 §1.1 表里没有这些实测工具名：{missing}")
    if effects != {"read"}:
        problems.append(f"`graph.*`/`trace.*` 的第一根轴实测是 {sorted(effects)}，不再是清一色 `read` ⇒ 文档那句话过期")
    if externals != {"none"}:
        problems.append(f"`graph.*`/`trace.*` 的第二根轴实测是 {sorted(externals)} ⇒ 文档那句话过期")
    if _OLD_AXIS_SENTENCE in text:
        problems.append(f"那句与表冲突的旧断言还在：{_OLD_AXIS_SENTENCE}")
    if _NEW_AXIS_SENTENCE not in text:
        problems.append("读不到那句答案句（`graph.*`/`trace.*` 的两根轴）⇒ 判据失去对象")
    return problems


def test_design_tools_graph_and_trace_rows_match_the_registry():
    """正控（`R6-AN-3`）：`DESIGN-TOOLS.md` 的 §1.1 表与那句注意必须与真注册表一致。

    这一条同时钉住两句事实：① 工具名逐字在注册表里（`graph.hottest`/`graph.paths`/
    `graph.cold`/`graph.gaps`/`trace.quote` 这 5 个从来不存在）；② `graph.*`/`trace.*`
    的第一根轴是 `read`、第二根是 `none`（旧句写成 `side_effect="none"`，与它上面刚
    更正过的表直接冲突）。注册表一变（例如某个工具改成写盘），这里就会红。
    """
    names, effects, externals = graph_trace_facts()
    problems = design_tools_problems(DESIGN_TOOLS_MD.read_text(encoding="utf-8"),
                                     names, effects, externals)
    assert not problems, problems


def test_the_design_tools_criterion_is_not_vacuous():
    """负控（`R6-AN-3`）：把旧那句话与 5 个幽灵工具名注回文本 ⇒ 判据必须报问题。"""
    text = DESIGN_TOOLS_MD.read_text(encoding="utf-8")
    names, effects, externals = graph_trace_facts()
    assert not design_tools_problems(text, names, effects, externals), "夹具前提：当前字节上是干净的"
    back = text.replace(_NEW_AXIS_SENTENCE, _OLD_AXIS_SENTENCE)
    assert back != text, "夹具前提：那句答案句必须在（不许注入到会被下一行覆盖的位置）"
    assert design_tools_problems(back, names, effects, externals), "改回旧句之后判据必须红"
    ghosty = text + "\n| 图分析 | `graph.hottest` / `graph.paths` | C | `read` | `none` |\n"
    assert design_tools_problems(ghosty, names, effects, externals), "幽灵工具名注回来之后判据必须红"


# ---- `R6-AN-1` 的建议③：`src/agentflow/` 顶层模块集合必须等于一份登记清单
#
# 缺陷形态（第 12 轮 `R6` 审计的 `R6-AN-1`，medium）：审计者把 `src/agentflow/providers.py`
# 的改前字节复制成 `src/agentflow/_r3_before_probe.py`（86801 B）落进包目录，把 lint 从
# `error 0 / warning 0 / info 25` 打到 `error 1 / warning 40`（error = 该文件 22 处注释星号的
# R009；warning 40 = R003「公开名与 providers.py 重复」），并作废了整个 `b84` 门窗口的读数。
# 当时没有一条判据在问"这个文件为什么在这里"：R009 只会说"注释里有装饰"，
# R003 的 40 条只是同名冲突的副产品。下面这条判据就是那个问题本身。

#: `src/agentflow/` 顶层 `*.py` 的显式登记清单（名字 -> 它为什么是一个独立的顶层模块）。
#:
#: 口径与维护：
#:   * 判据是「集合相等」（多一个报、少一个也报），不是子集：少一个同样意味着包目录的落位被动过；
#:   * 作用域只有顶层 `*.py` —— `__pycache__` 是目录、`tools/` 是子包，都不在这里判；
#:   * 「新增模块要在这里登记」，连同"它为什么必须是一个顶层模块"的一行理由；
#:     删模块要同时删掉它那一行理由（登记过期与漏登记同样危险：前者让人以为"有人看过了"）。
_AGENTFLOW_TOP_LEVEL_MODULES: dict[str, str] = {
    "__init__.py": "包入口：包级版本号与公开面（`import agentflow` 的第一落点）",
    "__main__.py": "`python -m agentflow` 的入口（只做转发）",
    # `goal-7f5116c1` M6/M7：八个角色（除主控 M）都改成了包，一个动作一个文件
    # （A 3 / B 6 / C 9 / D 14 / E 5 / F 4 / G 6 / H 4 个动作各自一个模块）+
    # `core.py`（其余成员与 mixin 组装）+ `_support.py`（模块级 helper 与常量）+
    # `__main__.py`（`python -m agentflow.<角色>` 的自检入口）。
    # 拆法是逐字搬移（一次性证明 `temp/_m6_verify_verbatim.py`：28/28），这条清单守的是
    # "拆完之后还保持这个形状"（判据 `tests/test_agent_split_is_one_action_one_file.py`）。
    "agent_a/": "智能体 A：文献搜索（拆包：3 个动作各一个文件 + core + _support + __main__）",
    "agent_b/": "智能体 B：文献整理（拆包：6 个动作各一个文件 + core + _support + __main__）",
    "agent_c/": "智能体 C：关系分析（拆包：9 个动作各一个文件 + core + _support + __main__）",
    "agent_d/": "智能体 D：研究循环（拆包：14 个动作各一个文件 + core + _support + __main__）",
    "agent_e/": "智能体 E：数值实验与形式化验证（拆包：5 个动作各一个文件 + core + _support + __main__）",
    "agent_f/": "智能体 F：多轮难题攻坚（拆包：4 个动作各一个文件 + core + _support + __main__）",
    "agent_g/": "智能体 G：论文撰写（拆包：6 个动作各一个文件 + core + _support + __main__）",
    "agent_h/": "智能体 H：审校（拆包：4 个动作各一个文件 + core + _support + __main__）",
    # B 线（F-02 / `draft/54 §1`）新建的角色 V（验证者）。登记在这里是事实登记：
    # 盘上确实多了这个包；它该不该存在由 B 线的 13 步施工单负责（`specs/v.py` 已登记
    # 进 `.noai-paths`）。A 线不改它的任何内容，只是不让"包目录里凭空多出一个模块"
    # 这条判据在合并树上误报 —— 见 `R6-AN-1` 的原始形态。
    "agent_v/": "智能体 V：验证者（F-02 接线：只读 + 写自己的 `verifications/<命题号>.jsonl`）",
    "specs/": "每个角色一份**声明真身**（`goal-7f5116c1` M3）：`ACTIONS`（动作表）与 `SPEC` —— "
              "`capabilities.py` 的四张表由它派生；它在 `.noai-paths` 里逐文件受保护",
    "agentspec.py": "一个 agent 的声明与注册表（`AgentSpec`/`AgentBrief`：职责与门面、官能轻重、只读与否、能召唤谁、写集、实现类）——`goal-7f5116c1` 的 M2，每个角色在自己模块里写一份 `SPEC`，装配面逐步改成从这里读",
    "cancellation.py": "取消语义（FC-20 的四条纪律）",
    "capabilities.py": "角色能力表 + 写集 + 允许的召唤边（主控编队的声明层）",
    "claimanatomy.py": "断言解剖学：`documents.claims` 每个元素的唯一判据来源",
    "claims.py": "原子断言拆分：把一段答复切成一堆可逐条回验的断言",
    "cli.py": "命令行入口",
    "conductor.py": "主控编队：把一次召唤做成可审计、可拒绝、可取消、可重建的台账行",
    "console.py": "把 CLI 的输出编码钉在 UTF-8 上（这件事只有一份实现）",
    "contextbudget.py": "上下文预算：压缩 / 剪枝 / spill 三件套（FC-17）",
    "dedup.py": "判重：文献 / 概念 / 关系",
    "demo.py": "离线端到端演示（不访问网络，把 A→B→校验整条链路真跑一遍）",
    "evidence.py": "证据层：先检索、再逐字回验（每条结论都落在某段真实原文上）",
    # `draft/39` §3.14（2026-10-05，用户裁定）：命题的「五元证据位」与派生等级。
    # 它不是对拍副本：位的词表/四态、派生等级、引用命题那条读法、作废四条只有这一份实现；
    # 收工门的 `reviewed_proof_rows` 与（批⑥）状态报告都调 `bits_from_row`。
    "evidencebits.py": "命题的五元证据位与派生等级（哪位角色欠哪一位 / 四态 / 等级机械派生 / "
                       "引用命题凭文献代号 / 作废四条）；纯函数层，读入口 `bits_from_row`",
    "extract.py": "文本抽取层 `extract_text` 及其 PDF 后端",
    "fetch.py": "下载层：流式下载、原子落盘、限速重试、镜像回退",
    "formalgw.py": "Lean 形式化验证后端（`evidence_kind=\"proof\"` 这句话的落点）",
    "fulltextstore.py": "抽取正文的内容寻址库：整本书的正文只存一份，产物里只留 `text_ref`（依据 `draft/30` §T0-1）",
    "gates.py": "H 的 G1–G15 门引擎（15 道独立、有名字、可单独查询的检查器）",
    "host.py": "主控接线：把 A–H 接到 `LocalBackend` 的角色登记表（依据 `draft/30` §T3-H；P10 的前置）",
    "interactions.py": "跨智能体交互的冻结契约（I1–I7）与它的闸门实现",
    "judge.py": "LLM 判定的唯一缝协议：`judge_json` 与 `judge_*` 失败词表（依据 `draft/30` §T0-8）",
    "llm.py": "抽取层：`Extractor` 协议 + 离线基线 + 可插拔 `LLMExtractor`",
    # 2026-09-28 新增的四个模块（本地书架 + 项目工作区 + 交互界面那一批）。
    # 它们都不是"对拍副本"，所以按 `R6-AN-1` 建议③的要求登记并各写一行理由。
    "locallib.py": "本地书架：把目录里的 PDF 登记进项目库，并作为 `run_topic` 的检索/取全文接缝",
    "paperbuild.py": "论文包的构建/编译/锚核对：受限地起项目脚本、读回 `REPRO_RESULT` 契约、把三态翻成工具层结论（`draft/28` §188）",
    "renderanchor.py": "渲染锚与编译回执的判据本体（纯函数）：源表/源文件/回执三维 + 三态；只读角色也能调它核包（`draft/28` §191）",
    # `draft/37` §134（2026-10-04，用户口径）：交接手稿——「交接工作前写一份手稿」。
    # 它不是对拍副本：`agent_loop._do_handoff`（循环形状）与 `tools/manuscript_tools.py`
    # 都转发到它的 `write` / `read` / `list_all`；编号分配与命名规则只有这一份实现。
    "manuscripts.py": "交接手稿的唯一实现：`manuscripts/handoffs.jsonl` 追加式账本（一行一份交接，"
                      "`to`/`summary`/`body` 必填）、编号在锁内从 0000 顺次分配、旧格式 "
                      "`<编号>-<谁>to<谁>.md` 仍读得回来 —— 「派活依据」与「溯源」此前只活在对话里"
                      "（`draft/37` §134；存储改追加式见 `draft/39` §C1）",
    "modelclient.py": "把模型网关适配成抽取层要的 `.complete()`（带 scope='extract' 记账）",
    # A 线（`draft/53` v3 / `draft/54 §2` / `draft/55`）：每个智能体自带的秘书。
    # 它不是对拍副本、也不是同级角色：四职责 + 手稿通道增改查 + 自己那份台账
    # （`out/secretary/<role>.jsonl`）；手稿的写路径从 `agent_loop` 移到这里。
    "secretary.py": "「秘书」共享模块：每智能体一名随员（四职责：格式内容优化 / 委派评估 / "
                    "闭环提醒 / 委托加工）+ 手稿通道增改查（`manuscripts.write` / 新增的 "
                    "`revise` / 只读查）+ 决定台账（`out/secretary/<role>.jsonl`，每角色一份）。"
                    "工具面为空（不进 `tools` 注册表）、库表只读（写集 ∅）、fail-open"
                    "（唯一例外：手稿执笔失败必须报错留痕）、不做任何统计"
                    "（`draft/53` v3；接口规范见 `draft/55`）",
    "modelcost.py": "模型花销入账适配器（`ModelReply` → `usage_ledger` 的一笔账）",
    "projects.py": "项目工作区：一个项目一个文件夹、默认命名 project1..N、冷启动/热启动判定",
    "tty.py": "终端呈现层：颜色开关、ASCII 回退、显示宽度对齐（框 / 表 / 徽标）",
    "modelgw.py": "模型网关：provider 无关的模型调用层，全仓唯一读 API key 的地方",
    "pipeline.py": "编排：把 A→B→C→D 串成可中断、可续跑、可审计的流水线",
    "policy.py": "策略层：允许哪些召唤，以及四类上限",
    "providers.py": "文献检索 provider 层：`SearchProvider` 协议与各数据源实现",
    "quoteverify.py": "引文校验：把\"关系描述需完全引用参考文献\"变成一道可执行的质量门",
    # `draft/37` §128（2026-10-04）：停机做成两条路 + 一个开关（优雅 / 强制），
    # 由 M 的 `conductor.stop` 与 CLI `agentflow stop` 共用同一份实现。
    "stopctl.py": "停机的唯一实现：停机开关（`.agentflow-stop`）+ 子进程登记（`runs/<role>-<sid>.pid`）"
                  "＋优雅停止与强制停止（`taskkill /T /F` 连子孙）—— 「用户叫停」这条通道此前只在"
                  "多轮路径存在：单趟 `run-agent` 里叫停之后它继续跑到第 123 步（真机读数见 §125/§127）",
    # `draft/37` §88（2026-10-04）：角色动作的「拒绝」只有一个形态。
    # 它不是对拍副本：`agent_a/ingest_local.py`、`agent_a/search_literature.py`、
    # `agent_b/register_statement.py` 都转发到它的 `refuse()`。
    "refusals.py": "角色动作的「拒绝」形态（一处定义）：`refuse(kind, error, **extra)` ⇒ "
                   "`ok=False` + 受控 `refusal_reason`。终态映射据此把拒绝落成 `refused` 而不是 `ok`"
                   "（T1 第 2 趟真机：8 次 `ok=False` 被记成 `outcome=ok`，而 `statements` 是 0 行）",
    "runflow.py": "端到端一条命令：一个主题 + 一个美元上限 → 一份可复核的运行记录",
    "scheduler.py": "调度：按写集互斥分波并发",
    "schema.py": "数据模型与校验",
    # 2026-10-07（所有者裁定"把工具链路径与模型 key 合并进一个机器级设置文件"）：
    # 它不是对拍副本：落点/键名/优先级（环境变量 > 设置文件 > 内置默认）与
    # "解析失败报真正的那个错误"只有这一份实现；判据在 `tests/test_settings.py`
    # （三条优先级各有正控与负控、示例文件与 .gitignore 的安全阀、死地址判据）。
    "settings.py": "机器级设置文件 `agentflow/settings.json`：`load_settings` + "
                   "`toolchain_settings` / `model_settings` + `env_or_setting`（取值口径"
                   "「环境变量 > 设置文件 > 内置默认/自动探测」的唯一实现；`draft/28` 体例）",
    "signatures.py": "稿件内容的规范哈希（唯一实现）：审批与内部引用都钉在它上面（依据 `draft/30` §T4-A）",
    # 2026-09-29 新增的三个模块（`draft/28` §163/§166/§169 那三批）。按 `R6-AN-1` 建议③
    # 逐条登记并写一行理由 —— 它们都不是"对拍副本"，是框架的真模块。
    # `draft/39` §3.21（2026-10-05 用户定案"新增角色 V"）：证明级验证的台账与签位。
    # 它不是对拍副本：冷启动提示词、三态结论、追加式台账、签第 3 位的条件只有这一份实现；
    # 名字带 `verification_` 前缀是刻意的 —— R003 会把 `read`/`record`/`list_all` 这类
    # 通用名在模块间判重（它们的语义各模块不同，同名会让人以为是同一件事）。
    "verifications.py": "验证者 V 的证明级审校台账：`verifications/<命题号>.jsonl` 追加式一行一次审校、"
                        "冷启动提示词（`cold_start_prompt`，签名里没有句柄）、三态结论、签五元位第 3 位"
                        "（`signs_bit3`/`bit3_payload`）—— `draft/39` §3.21",
    # `draft/39` §4（2026-10-05 用户口径）：M 的状态报告（旁路观测，谁都不停）。
    # 它不是对拍副本：四类读数怎么收集、怎么渲染成四节、怎么与复算对拍只有这一份实现；
    # 名字带 `status_report_`/`statusreport` 前缀是刻意的（R003 会把 `write_report`/
    # `render_markdown` 这类通用名在模块间判重）。
    "statusreport.py": "M 的状态报告：`collect`（只读四类读数：台账增量/交接链/在飞卡点/超时与拒绝）"
                       "＋`render_status_markdown`＋`write_status_report`（落 "
                       "`out/review/STATUS-<ts>.{md,json}`）—— `draft/39` §4",
    # `draft/39` §3.16（2026-10-05 用户裁定"批准 3、6、8；5 的表述是 F 禁止写的"）：
    # F 的"一轮真推理"形态与判据。它不是对拍副本：四种产物、策略工具箱、
    # 缝的两条合法出口、花钱前的确定性闸门、超预算的诚实阻塞只有这一份实现。
    "attackround.py": "F 一轮真推理的形态与判据：四种产物（`reduction`/`proof`/\n"
                      "`counterexample_request`/`dead_end`，**没有 `no_change`**）、策略工具箱（9 招）、\n"
                      "#5 的两条合法出口、I9 花钱前闸门、I11 缺陷继承、I16 超预算 `too_large`"
                      "（`draft/39` §3.16/§3.19）",
    # `draft/39` §3.21 五 I13（2026-10-05）：进程树治理 —— D03 的根因修法。
    # 它不是对拍副本：作业对象的建/放/收（KILL_ON_JOB_CLOSE）、后代枚举（Toolhelp 快照）、
    # 宽限后强杀只有这一份实现；`stopctl` 的强制停止优先走它。
    "jobobject.py": "进程树治理：Windows 作业对象（`KILL_ON_JOB_CLOSE`）—— assign/assign_tree/\n"
                     "grace_then_kill/reap/close；后代枚举走 Toolhelp 快照（不依赖 `wmic`）。\n"
                     "为什么需要它：受限环境里 `taskkill /T /F` 与 `os.kill` 都会被拒，\n"
                     "而\"最后一个句柄一关，OS 收掉整棵传递树\"不依赖任何外部命令",
    "sessions.py": "按项目存放的会话记录：`<项目根>/sessions/<会话号>.jsonl`（学 harness 的按工作区存放；`draft/28` §155）",
    "artifacts.py": "产物归属登记：`<工作区根>/ARTIFACTS.jsonl`，回答\"谁在哪个路径产出了什么\"（`R-52` 余；`draft/28` §166）",
    "canonical.py": "规范 JSON 字节串的唯一实现：稿件内容哈希与回执哈希共用的那一份口径（`R-33`；`draft/28` §169/§172）",
    # 2026-10-01（`draft/28` §211 / `draft/36` 的 T-6）：三处 JSONL 读法合并成一份。
    # 它是真模块（不是对拍副本）：`artifacts.read_ledger` / `signatures.read_ledger` /
    # `sessions.read_session` 都转发到它；逐对查证与合并理由见 §211。
    "jsonlfile.py": "JSONL 文件的读法唯一实现：坏行逐条报出、空行跳过、\"合法 JSON 但不是对象\"单列一档（`draft/36` T-6；`draft/28` §211）",
    # 2026-10-11（`draft/100` 的 S-A / S-E / S-B）：三批各新增一个顶层模块 ——
    # 前两个是"搬运落点"（DSH 的观测闸门与超时策略都要求一个新家），
    # 后一个是"口径换 DSH"的估值器（12-H=甲 把每 token 几字符做成配置项）。
    # 三个都不是对拍副本：分别被 `tools/fs_tools`、`agent_loop._do_tool`、
    # `contextbudget.pressure_reading` 在用。
    "fs_observation.py": "文件\"读后写\"的观测闸门：读过才许改、按 (dev,ino,size,mtime,ctime) 记版本（S-A / 裁定 9甲；DSH `fs-observation-policy` 的搬运）",
    "tool_timeout.py": "逐工具超时：协作式 ContextVar 截止 + 一张限时表 + 逐字节相同的超时结果（S-E / 裁定 13甲、12-D、12-E、12-G）",
    "tokenestimate.py": "固定密度估值器：DSH 的三个常量原样保留 + `chars_per_token` 配置项 + 三态（S-B / 裁定 12-H=甲）",
    # 2026-09-29 第二批新增的四个模块（`draft/28` §179）：把 LLM 接入规范化
    # （装配 / 提示词 / 模型缝 / 循环）。同样逐条登记并写一行理由。
    "promptkit.py": "提示词装配：有序段 + 变量 + complete + 作用域遮蔽，失败全部抛（学 DSH 的 `dsh-system-prompt`；`draft/28` §179、`draft/34`）",
    "persona.py": "身份的两个具名槽位（`deployment:persona-prefix` / `-suffix`）与它们的唯一注册入口：部署那一份无条件注册、角色那一份靠同名遮蔽、`scope` 必填（学 DSH 的 `dsh-persona`；`draft/101` §3）",
    "presets.py": "预设机制：一个预设一个目录（`preset.json` + `agent.agentflow.json`）、发现按根优先级（随包前置赢同 id）、坏预设列出来带理由、一个预设挂一次（生成键 = mtime+size）、创作面只有复制（学 DSH 的 `dsh-agent-presets`；`draft/101` §2）",
    "agent_prompts.py": "A–H 与主控的前置提示词：手写判断 + 现算事实（工具面 / 伙伴边 / 动作参数 / 失败词表；`draft/28` §178/§179）",
    "llmseam.py": "统一的模型缝：一次调用一条审计记录（版本 / 哈希 / tokens / 花销）+ 三态词表 + 预算守卫（`draft/28` §179）",
    "agent_loop.py": "LLM 驱动的角色循环：形状清单以 `agent_loop.SHAPES` 为唯一来源（八个，含手稿落行的唯一入口 `handoff`），唤起走 `Conductor.summon`、留言落会话记录（`draft/28` §179）",
    "userio.py": "用户频道：ask_user 把问题送进待答清单并等回答，超时是 `user_no_answer`（不是默许），迟到的回答照样捞得出来（`draft/28` §181）",
    "autonomy.py": "放手后的自主轮与阶段性汇报：轮次上限 + 每 N 轮一次公共汇报 + 文件/用户回答可打断（`draft/28` §181）",
    "judges.py": "语义判据的接入方式：判据注册表（每条带负控准入）+ 三态 + 引用落地过滤（`draft/28` §182）",
    "faculty_checks.py": "十项官能里可机械判的那一半：引用落地 / 猜想卫生 / 体例 / 推进与卡点（`draft/28` §182）",
    "deliver.py": "交付闸门：逐条判据 + 机械半 → pass/needs_work/unknown 三态、闸门报告与工作项，并把工作项按能力表派回去（`draft/28` §186）",
    "closing.py": "收工门（`draft/37` §16 P3）：锚 consistent / 无未裁决矛盾 / 承重结论有 T3 或已降档 / 报告九节齐全 / 没有还在等用户回答的问题，五条各自一个三态读数（`unknown` 不是通过）；工具 `conductor.closing` 与 CLI `agentflow closing` 都调它的 `check_closing`",
    "reviewaccept.py": "审稿场景的内容级验收（`draft/37` §17.3）：五条内容级判据（定理台账每条有完整假设与出处页码 / 三态分支落盘 / 成本上限 / 每跳可读输入 / 附件诚实）与五种**不许当通过**的辅助读数（sha/页数/锚/任务数/行数）分栏给出；`passed` 只看前者（条数口径：`len(reviewaccept.CRITERIA)==5`、`len(reviewaccept.AUXILIARY_SIGNALS)==5`，2026-10-07 现算复核；此前这一串的第一项写的是已被替换掉的『报告每栏有读数』）",
    "migrate_concepts.py": "`concepts` 并进 `statements` 的折叠内核（纯函数，S1r）：概念号走同一分配器重发、定义待补标记、别名带过、`relations.concept_ids` 改号逐条落账（`draft/97` §10/§14）",
    "conceptrows.py": "并表过渡期概念行的唯一读写口（S1r）：写的时候新标准先写、老表照旧镜像（两处同号），读的时候合成一个视图（新标准优先，逐行标 via），legacy_present 三态（表退役而文件还在 ⇒ stale_file 点名）+ 四个分开的计数（merged / legacy_only / definition_only_in_legacy）—— 让读侧可以一个一个搬，而两边不同步这件事永远看得见（draft/97 §10.3）",
    "paperledger.py": "S1q 正文重建：定理库取原文逐字搬（①）、论文号重写（②）、`stmt:` 引用（③）、映射落 `dependencies`（④）与五条判据（逐字 / 引用在 / 映射唯一 / 两个方向都不许多余或悬空 / 论文里不许引 `doc:`）—— 检查器是唯一实现，正文排版仍归人/模型（draft/97 §9.5 + §16.1）",
    "store.py": "共享存储：锁、原子写、事务、事件日志、ID 分配、重建",
    "textutil.py": "文本规范化、相似度、slug、页码解析",
    "tokenmeter.py": "FC-19：token / 花销预算（硬约束，重试也计入）",
    "toolchain.py": "这台机器上的证明工具链（一处定义）：显式配置（`AGENTFLOW_LEAN_BIN` 等）→ "
                    "`AGENTFLOW_PROVER_PATH` → PATH 三档查找 + 三态探测 + Mathlib 那一轴；"
                    "探测（`tools/verify_tools.detect_verifier`，禁改区）与调用（`formalgw.find_lean`）"
                    "**共用这一个答案** —— 此前两处各看一遍 PATH，于是「探测说没有、调用却能跑」"
                    "是可能的，而形式化那一条腿会静默降级成 cross_check（`draft/37` §82）",
    "verify.py": "全局不变量校验",
    # `draft/37` §72–§74（2026-10-03）：用户端。两者都是「新增」，不是对拍副本；
    # 登记它们的理由是"包目录里凭空多出一个模块"必须有人解释（`R6-AN-1` 的原始形态）。
    "webui/": "用户端网页（`draft/73` §1.2 的 R1 拆包：W0 一次拆到位）：`state.py` 的 `snapshot()` 读模型 + `views.py`（**W5 已退场**）与 `writes.py` 的写路径 + `routes.py` 的路由表 + `server.py` 的 http.server 与静态路由；`__init__.py` 保持公开面不变（四条 GET 与 `POST /answer`，唯一写路径走 `userio.answer_question`）",
    "web/": "网页的样式与令牌包：`assets.py` 把 DSH 的令牌整份照搬（MIT，来源见 `docs/USER-END-DSH-STYLE.md`），`__init__.py` 只放包说明",
}


def agentflow_module_inventory_problems(on_disk: list[str]) -> list[str]:
    """盘上顶层模块集合 vs 登记清单 ⇒ 问题清单（空 = 成立）。

    为什么收"名字集合"而不是自己去 glob：这样正控与负控可以对着同一段逻辑跑 ——
    负控在内存里往集合里加一个 `_probe_x.py`（`R6-AN-1` 的那次注入就是这个形态），
    不必往包目录写任何东西。那条前科（判据自己写仓内文件）不重演。
    """
    seen = sorted(set(on_disk))
    if not seen:
        return ["`src/agentflow/` 下一个顶层 `*.py` 都没读到 ⇒ 本判据失去对象"
                "（目录被搬走或路径写错都不能被读成\"清单是对的\"）"]
    registered = set(_AGENTFLOW_TOP_LEVEL_MODULES)
    problems: list[str] = []
    extra = [n for n in seen if n not in registered]
    missing = [n for n in _AGENTFLOW_TOP_LEVEL_MODULES if n not in set(seen)]
    if extra:
        problems.append(
            f"`src/agentflow/` 里有未登记的新顶层模块：{extra} —— 包目录里凭空多出一个模块"
            "正是 `R6-AN-1` 的原始形态（改前的 `providers.py` 被复制成 `_r3_before_probe.py`，"
            "把 lint 从 error 0 / warning 0 / info 25 打到 error 1 / warning 40，"
            "并作废了整个 b84 窗口的读数）。它若真的该在这里，请在 "
            "`_AGENTFLOW_TOP_LEVEL_MODULES` 里登记并写一行理由；若只是对拍或临时的副本，"
            "请用 `temp/` 下的整树副本，不要落进包目录")
    if missing:
        problems.append(
            f"`_AGENTFLOW_TOP_LEVEL_MODULES` 登记了但盘上不存在的模块：{missing} —— "
            "登记过期与漏登记同样危险：它会让读者以为\"有人看过了\"")
    return problems


def _agentflow_top_level_modules_on_disk() -> list[str]:
    """盘上 `src/agentflow/` 的顶层模块名（排好序；`tools/` 与 `__pycache__` 不在内）。

    收两种形态：顶层 `*.py`（名字如 `store.py`）与含 `__init__.py` 的顶层目录
    （名字带尾斜杠，如 `agent_c/`）—— `goal-7f5116c1` M6 把两个大角色拆成了包，
    而"包目录里凭空多一个目录"与"多一个 .py"是同一类事，必须同样被点名。
    """
    base = REPO / "src" / "agentflow"
    out = [p.name for p in base.glob("*.py")]
    out += [f"{p.name}/" for p in base.iterdir()
            if p.is_dir() and p.name not in {"__pycache__", "tools"}
            and (p / "__init__.py").is_file()]
    return sorted(out)


def test_agentflow_top_level_modules_match_the_registry():
    """正控（`R6-AN-1` 建议③）：包目录的顶层模块集合必须逐名等于登记清单。

    这一条把"这个文件为什么在这里"从散文变成判据。第 12 轮那次注入
    （`providers.py` 的改前字节被复制成 `_r3_before_probe.py`）放到今天会被它当场点名；
    在当时没有任何一条判据发问 —— R009 只说"注释里有装饰"，R003 只说"公开名重复"。
    """
    on_disk = _agentflow_top_level_modules_on_disk()
    problems = agentflow_module_inventory_problems(on_disk)
    assert not problems, problems
    assert len(on_disk) == len(_AGENTFLOW_TOP_LEVEL_MODULES), (
        f"盘上 {len(on_disk)} 个顶层模块、清单 {len(_AGENTFLOW_TOP_LEVEL_MODULES)} 条 —— "
        "两者必须一样多（少了会被上面的'登记了但不存在'分支点名）")


def _duplicate_inventory_keys() -> list[str]:
    """登记清单源码里重复的键（空 = 没有）。

    为什么要这条判据：Python 的字典字面量会静默丢弃重复键 ——
    清单里写两遍同一个模块名，读起来像"两条登记"，实际只有一条，
    而 `len(_AGENTFLOW_TOP_LEVEL_MODULES)` 与盘上集合的比对照样能对上
    （两条重复键只占一个名额）。2026-10-04 实测：`renderanchor.py` 那一行
    在这张表里出现了两次，谁也没发现 —— 这正是"看起来有人看过了"的形态。
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        # 带注解的赋值（`X: dict[str, str] = {...}`）是 `AnnAssign`，不带注解的是
        # `Assign` —— 两种都要认：只认一种时这条判据会以"失去对象"失败，
        # 而那是查不成，不是"没有重复"（三态纪律）。
        if isinstance(node, ast.AnnAssign):
            targets = [node.target.id] if isinstance(node.target, ast.Name) else []
        else:
            targets = [t.id for t in getattr(node, "targets", []) if isinstance(t, ast.Name)]
        if not (isinstance(node, (ast.Assign, ast.AnnAssign))
                and "_AGENTFLOW_TOP_LEVEL_MODULES" in targets):
            continue
        keys = [k.value for k in node.value.keys
                if isinstance(k, ast.Constant) and isinstance(k.value, str)]
        seen: set[str] = set()
        dups: list[str] = []
        for k in keys:
            if k in seen and k not in dups:
                dups.append(k)
            seen.add(k)
        assert len(keys) >= 40, f"只读到 {len(keys)} 个键 ⇒ 扫描器接错了（不是'没有重复'）"
        return dups
    raise AssertionError("没找到 `_AGENTFLOW_TOP_LEVEL_MODULES` 的赋值 ⇒ 判据失去对象")


def test_the_registry_has_no_duplicate_keys():
    """负控（静默丢弃）：登记清单里不许有重复键 —— 重复的那一条等于没写。"""
    assert _duplicate_inventory_keys() == []


def test_the_agentflow_module_registry_criterion_is_not_vacuous():
    """负控（`R6-AN-1` 建议③的验收）：往集合里加一个新文件 ⇒ 判据必须红。

    四档（都在内存里做，不往包目录写任何东西 —— 这条判据要防的正是"有人往包目录写文件"）：
      ① 正控：当次盘上集合 ⇒ 不红；
      ② 负控 A：集合里多一个 `_probe_x.py`（`R6-AN-1` 那次注入的形态）⇒ 必须红，且点名它；
      ③ 负控 B：把 `providers.py` 从集合里去掉 ⇒ 必须红（少一个也是包目录被动过）；
      ④ 反真空：空集合 ⇒ 必须报"失去对象"（目录搬走不许读成通过，P16）。
    """
    on_disk = _agentflow_top_level_modules_on_disk()
    assert not agentflow_module_inventory_problems(on_disk), "夹具前提：当次盘上是干净的"

    injected = [*on_disk, "_probe_x.py"]
    bad = agentflow_module_inventory_problems(injected)
    assert any("_probe_x.py" in p and "未登记" in p for p in bad), bad

    dropped = [n for n in on_disk if n != "providers.py"]
    assert dropped != on_disk, "夹具前提：`providers.py` 在盘上"
    assert any("providers.py" in p for p in agentflow_module_inventory_problems(dropped)), (
        "少一个模块也必须红（否则\"删掉之后没人发现\"）")

    assert any("失去对象" in p for p in agentflow_module_inventory_problems([])), (
        "空集合必须报失去对象（P16：判据解析出空集会无条件通过）")

