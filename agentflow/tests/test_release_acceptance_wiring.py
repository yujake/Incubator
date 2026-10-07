# -*- coding: utf-8 -*-
"""接线判据：内容级验收（`draft/37` §17.3）真的在生产路径上跑一次，读数落到人能读的地方。

## 这一组守什么（题 6 选 A = 接线）

`reviewaccept` 此前是"判据齐、测试齐、而真机上永远没人跑它"：`src/`/`tools/`/`scripts/`
里一条 import 都到不了它，五条测试文件各自 `import reviewaccept` 直接调 ——
测试全绿与"这条判据在生产面上存在"是两件事，而只有前者成立时，读的人会把它读成后者。

所以这一组的前两条是反真空，不是对拍副本：

1. `test_the_only_production_caller_is_the_readonly_closing_exit`：把生产面的调用者
   一个个数出来（`ast` 扫 `src/`），并逐条登记它们为什么在那儿 ——
   零个调用者 ⇒ 红（接线没接上）；多出一个没登记的 ⇒ 红（多了一条没人解释的面）。
   这一条不满足于"CLI 里有一行 import"：`import` 与 `真的调它"是两件事。
2. `test_every_criterion_really_runs_through_the_cli_exit`：把六条判据的每一个
   隐藏入口逐个换成"一调就炸"，从 CLI 出口进去 ⇒ 必须炸。
   "没有真的跑到六条判据 ⇒ 不许算通过"就是这一条的字面实现。

后两条守"读数落到人能读到的地方"与三态不折平：

3. `test_the_six_criteria_and_the_five_auxiliary_readings_reach_the_human_output`
   —— 六条判据 + 五种辅助读数的名字与值必须出现在 CLI 的原始输出里，
   并且辅助读数带着"不构成通过"的那句话。
4. `test_the_readings_are_recomputed_not_hand_copied` —— 改盘上的东西 ⇒
   输出里的数跟着变（防"把六条判据的结论手抄成一句通过"）。

## 反真空那一条（辅助读数漂亮也不许通过）

`test_pretty_auxiliary_readings_cannot_print_a_pass`：把五种辅助读数全部造得漂亮
（正文改过 sha 变了 / PDF 在盘上 / 锚 consistent / 任务行与台账行都增加），
而内容级判据不合格 ⇒ CLI 输出里的 `passed` 必须是假。
这一条要的是"分栏在出口上也是真的"，不只是 `ReviewAcceptance` 里分了栏。

## 接线不许动的东西（都在这里钉住）

- 抄一遍判据：`test_the_wiring_does_not_restate_the_criteria` —— 输出里的
  判据名与顺序必须来自 `reviewaccept.CRITERIA`，不许在 `cli.py` 里另写一份
  （另写一份就等于"同一件事两个落位"，而两处会各自漂）。
- 动退出码：`test_the_exit_code_still_comes_only_from_the_closing_gate` ——
  摘掉接线 / 让内容级验收"没查成"都不许改退出码。把内容级验收并进退出码
  等于偷偷改门的强度，那是裁定题不是接线题。
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from agentflow import cli
from agentflow import closing as CL
from agentflow import reviewaccept as RX
from agentflow import sessions as SS
from agentflow import userio as U
from test_review_acceptance import _good, _report, _seal, _stmt, _task, _usage

REPO = pathlib.Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "agentflow"

#: 六条判据的实现入口（`check_review` 逐个调它们）。判据名不由这里定：
#: 名字与顺序一律读 `RX.CRITERIA`，免得判据表改了而这份判据守的是旧名字。
_CRITERION_IMPLS: tuple[str, ...] = (
    "_c_statements", "_c_triage", "_c_cost", "_c_hops", "_c_attachment", "_auxiliary",
)

#: 三态的中文标记（出口上打的字）。`unknown` 与 `fail` 的标记必须不同 ——
#: 折平这两个是本项目最忌的形态。
_MARKS: dict[str, str] = {"pass": "通过", "fail": "不通过", "unknown": "没查成"}


# ============================================================ 夹具 / 工具

def _cli_closing(store, report_path, out_lines: int = 200, *extra: str) -> tuple[int, str]:
    """从 CLI 出口进（不是直接 import `reviewaccept` 调它），返回 `(退出码, 输出)`。

    `--plain` 是为了不受终端能力影响（勾号/制表符不画）；输出重定向到 capsys，
    颜色本来就会自动关。
    """
    code = cli.main(["--plain", "--root", str(store.root), "closing",
                     "--project-dir", str(store.root), "--report", str(report_path),
                     *extra])
    return code, ""


def _run(store, report_path, *extra: str) -> tuple[int, str]:
    """跑一次 CLI 出口并把 stdout/stderr 收成一段文本。"""
    import io
    from contextlib import redirect_stderr, redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        code = cli.main(["--plain", "--root", str(store.root), "closing",
                         "--project-dir", str(store.root), "--report", str(report_path),
                         *extra])
    return int(code), buf.getvalue()


def _good_and_sid(tmp_path):
    """五条全过的那个工作区 + 它的会话号（夹具的提问落在"缺省会话"里）。

    会话号从 `sessions.session_id()` 现读，不手抄一个日期（手抄的会过期）。
    """
    st, report = _good(tmp_path)
    return st, report, SS.session_id()


def _calls_in(path: pathlib.Path) -> dict[str, list[str]]:
    """一个文件里"函数 -> 它调到的名字列表"（`ast`，不按行号断言）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            got: list[str] = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    if isinstance(f, ast.Attribute):
                        got.append(f.attr)
                    elif isinstance(f, ast.Name):
                        got.append(f.id)
            out[node.name] = got
    return out


def _check_review_callers() -> dict[str, list[int]]:
    """全 `src/` 里真调 `RX.check_review` 的落点（`ast`，不是字符串搜索）。

    为什么必须是 `ast`：`cli.py` 里有大段注释写着一个不存在的符号名时，
    字符串搜索会把注释读成调用点 —— 那正是本项目记过的"引用一个不存在的行"。
    """
    found: dict[str, list[int]] = {}
    for path in sorted(SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover —— 语法都不对的话别的判据先红
            continue
        hits: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else "")
            if name == "check_review":
                hits.append(int(getattr(node, "lineno", 0)))
        if hits:
            found[path.relative_to(SRC).as_posix()] = hits
    return found


# ============================================================ 1. 反真空：生产面调用者逐个登记

#: 生产面的调用者登记表（这就是接线本身）。键是相对 `src/agentflow/` 的路径，
#: 值是"这个文件里的哪个函数调它、为什么在那儿"。
#:
#: 漏登记 ⇒ 红（多了一条没人解释的面）；一个都没有 ⇒ 红（接线没接上）。
_PRODUCTION_CALLERS: dict[str, tuple[str, str]] = {
    "cli.py": (
        "_print_review_acceptance",
        "CLI 的只读出口 `agentflow closing`：收工门读数之后接一段内容级验收读数。"
        "为什么在 `_print_review_acceptance` 而不是 `cmd_closing` 里：那个函数是"
        "「只读、只打印」这一段的唯一实现，`cmd_closing` 只负责决定跑不跑它。",
    ),
}


def _print_review_acceptance_calls() -> list[str]:
    """`_print_review_acceptance` 这个函数体里调到的名字（`ast`）。"""
    got = _calls_in(SRC / "cli.py")
    return got.get("_print_review_acceptance", [])


def test_the_only_production_caller_is_the_readonly_closing_exit():
    """接线判据（正控 + 逐条登记）：生产面的调用者恰好是登记的那一个。

    改前必红：这一层此前在生产面上 0 个调用者（`src/`/`tools/`/`scripts/`
    都到不了它），于是"五条内容级判据"在真机上从来没跑过一次。

    为什么不是"CLI 里有一行 `from . import reviewaccept`"就算接线：
    那只是声明面（import 了不等于调了）。这一条数的是调用点（`ast` 里的
    `check_review(...)`），并且要求每个调用点都在登记表里有一行理由。
    """
    callers = _check_review_callers()
    assert callers, ("生产面一个 `check_review` 调用点都没有 ⇒ 接线没接上："
                     "这一层在真机上永远不会跑（测试里的那些 import 不算生产面）")
    assert set(callers) == set(_PRODUCTION_CALLERS), (
        f"生产面的调用者与登记表不一致：盘上 {sorted(callers)}，"
        f"登记 {sorted(_PRODUCTION_CALLERS)} —— 多出来的那一条是一条没有理由的面，"
        "少了的那一条说明登记过期了")
    # 登记表说的"在哪个函数里"必须是真的（不是一句好听话）
    for rel, (func, _why) in _PRODUCTION_CALLERS.items():
        got = _calls_in(SRC / rel)
        assert func in got, f"登记说调它在 {func} 里，而 {rel} 里没有这个函数"
        assert "check_review" in got[func], (
            f"登记说 {func} 调 `check_review`，而它当次调的是 "
            f"{[c for c in got[func] if 'review' in c]} ⇒ 登记已经过期")


def test_the_wiring_runs_by_default_not_only_behind_an_optin_flag():
    """接线必须缺省就跑（正控）：否则"接上了"只是"接了一个没人按的开关"。

    改前必红：没有接线时输出里根本没有这一段。
    """
    assert "check_review" in _print_review_acceptance_calls(), (
        "`_print_review_acceptance` 里没有 `check_review` 调用 ⇒ 它没在跑判据")
    got = _calls_in(SRC / "cli.py")
    assert "_print_review_acceptance" in got.get("cmd_closing", []), (
        "`cmd_closing` 不再调 `_print_review_acceptance` ⇒ 接线被摘掉了"
        "（那正是本题要防的形态：判据还在、测试还绿、而真机上没人跑它）")
    # 缺省跑：没有 `--no-review-acceptance` 时不许走"没跑"那一支
    args = cli.build_parser().parse_args(["closing"])
    assert getattr(args, "no_review_acceptance", None) is False, (
        "`--no-review-acceptance` 的缺省值不是假 ⇒ 接线退化成了「要显式打开」")
    assert getattr(args, "cap_usd", "缺失") is None
    assert getattr(args, "acceptance_sid", "缺失") is None
    # 负控的正控面：给了 `--no-review-acceptance` 才是"没跑"
    args2 = cli.build_parser().parse_args(["closing", "--no-review-acceptance"])
    assert args2.no_review_acceptance is True


# ============================================================ 2. 反真空：六条判据真的跑到

@pytest.mark.parametrize("impl", _CRITERION_IMPLS)
def test_every_criterion_really_runs_through_the_cli_exit(tmp_path, monkeypatch, impl):
    """反真空（每一个判据各一条）：从 CLI 出口进去，六条判据必须真的被执行。

    做法：把这个隐藏入口换成"一调就炸"，然后跑 CLI。
    夹具是五条全过的工作区 ⇒ 不走出口的话不会有任何东西去碰它们。

    为什么必须从 CLI 进、不许 `import reviewaccept` 直接调：本题要证的正是
    "这条调用链在生产面上存在"。直接调判据只能证明判据自己是对的
    —— 而那件事已经有五条测试在守了（它们此前全绿，而生产面是 0 条 import）。
    """
    st, report, sid = _good_and_sid(tmp_path)

    def boom(*_a, **_kw):
        raise AssertionError(f"判据 {impl} 被调到了（这正是要证的：调用链活着）")

    monkeypatch.setattr(RX, impl, boom)
    with pytest.raises(AssertionError, match=impl):
        _run(st, report, "--cap-usd", "1.0", "--acceptance-sid", sid)


def test_unwiring_makes_that_control_dark(tmp_path, monkeypatch):
    """上面那条负控的对照：接线摘掉之后，那些隐藏入口一次都不许被调到。

    没有这一条，上面那条可能只是"碰巧炸了"（例如某个夹具路径顺手调了它们）：
    这里让同一个工作区、同一个炸点，只把接线摘掉 ⇒ 必须安静地跑完，
    且输出里必须明说"这一格是没查成"。

    这一对合起来才等于"把接线摘掉 ⇒ 必须红"：摘掉之后
    `test_every_criterion_really_runs_through_the_cli_exit` 六条全部不炸（红），
    而这一条转而变绿。
    """
    st, report, sid = _good_and_sid(tmp_path)

    def boom(*_a, **_kw):
        raise AssertionError("接线摘掉了，判据不该被调到")

    monkeypatch.setattr(RX, "_c_statements", boom)
    monkeypatch.setattr(RX, "_auxiliary", boom)
    code, out = _run(st, report, "--cap-usd", "1.0", "--acceptance-sid", sid,
                     "--no-review-acceptance")
    assert code == 0, out
    assert "没查成" in out and "内容级验收" in out, out
    assert RX.CRITERIA[0][1] not in out, ("摘掉接线之后判据名不该出现 —— "
                                          "出现了说明它还在跑（那这条对照就失效了）")


# ============================================================ 3. 读数落到人能读的地方

def test_the_six_criteria_and_the_five_auxiliary_readings_reach_the_human_output(tmp_path):
    """交付要求：六条判据的结论（三态逐条）+ 五种辅助读数必须打到人能读的地方。

    这一条不满足于"函数被调过"：它读的是 CLI 的原始输出，
    逐条核判据名、逐条核三态标记、逐条核辅助读数的值，并核那句
    "辅助读数不构成通过"。
    """
    st, report, sid = _good_and_sid(tmp_path)
    code, out = _run(st, report, "--cap-usd", "1.0", "--acceptance-sid", sid)
    assert code == 0, out

    # 六条判据：名字与顺序都来自 `reviewaccept.CRITERIA`（改写一份就会在这里红）
    for key, name in RX.CRITERIA:
        assert name in out, f"判据 {key} 的名字没打到出口上：{name!r}"
        state = "pass"  # 五条全过的工作区
        assert f"{name}：{_MARKS[state]}" in out, f"判据 {key} 的三态标记没打对"
    # 三态不折平：三种标记里 `unknown`/`fail` 与 `pass` 必须长得不一样
    assert len(set(_MARKS.values())) == 3
    assert "passed（只看上面这几条）＝True" in out, out
    # 辅助读数：五种各自的名字与值
    for key, label in RX.AUXILIARY_SIGNALS:
        assert label in out, f"辅助读数 {key} 的标签没打到出口上"
        assert f"{label}＝" in out, f"辅助读数 {key} 的值没打到出口上"
    assert "逐字禁止拿来当通过" in out, (
        "出口上没有那句『辅助读数逐字禁止拿来当通过』"
        " —— §17.3 的禁令要能被读的人看见才有意义")
    assert "证明不了内容" in out, "出口上没有『它们证明不了内容』这句口径"
    # 辅助读数确实有值（不是打了一排空）
    assert "＝b20cb2" in out or RX.AUXILIARY_SIGNALS[0][1] + "＝" in out, out
    assert f"{RX.AUXILIARY_SIGNALS[2][1]}＝consistent" in out, out


def test_the_readings_are_recomputed_not_hand_copied(tmp_path):
    """反真空（防手抄）：改盘上的东西 ⇒ 出口上的数跟着变。

    做法：同一个工作区先跑一次（那一格 `pass`），再把一条命题弄坏，重跑 ⇒
    出口上那一格必须变 `不通过`，且 `passed` 跟着变假、`没通过的` 里点名它。

    没有这一条，接线可以写成"打一句固定的『五条全过』"而所有别的判据全绿
    —— 那正是本项目反复踩的"算了不判 = 假读数"。
    """
    st, report, sid = _good_and_sid(tmp_path)
    from agentflow import schema as _S

    code, out = _run(st, report, "--cap-usd", "1.0", "--acceptance-sid", sid)
    assert code == 0
    assert "passed（只看上面这几条）＝True" in out, out

    key, name = RX.CRITERIA[0]
    _stmt(st, "0002", page_range=_S.PageRange())          # 缺页码 ⇒ 这一条必须红
    code2, out2 = _run(st, report, "--cap-usd", "1.0", "--acceptance-sid", sid)
    assert code2 == 0, out2                                # 退出码仍由收工门定
    assert f"{name}：{_MARKS['fail']}" in out2, out2
    assert "passed（只看上面这几条）＝False" in out2, out2
    assert f"没通过的：{key}" in out2, out2

# ============================================================ 4. 辅助读数漂亮也不许通过

def test_pretty_auxiliary_readings_cannot_print_a_pass(tmp_path):
    """§17.3 逐字禁止的五种读数一起变漂亮，出口上也不许出现 `passed=True`。

    造法（照 `test_review_acceptance.test_pretty_auxiliary_signals_cannot_fake_a_pass`
    的同一批动作，只是这一次从 CLI 出口读）：内容级判据弄坏（一条命题缺页码 +
    有未答问题），同时五种辅助信号全部造得漂亮 —— 正文改过（sha 变了）、
    PDF 在盘上、锚 `consistent`、任务行与台账行都增加。
    """
    st, report, sid = _good_and_sid(tmp_path)
    _report(tmp_path, empty_section="七")
    from agentflow import schema as _S

    _stmt(st, "0002", page_range=_S.PageRange())
    U.ask_user(st.root, role="M", question="要不要重取?", timeout_sec=0.0, qid="q0009")
    _task(st, "t-0003")
    _task(st, "t-0004")
    with st.tx("concepts", actor="test") as tx:
        tx.upsert("concepts", _S.Concept(concept_id="0000", name="室图", definition="d",
                                         created_at="2026-01-01T00:00:00+00:00").to_dict())
    (tmp_path / "out" / "paper" / "main.tex").write_text("改过了\n", encoding="utf-8")
    _seal(tmp_path, st)                                   # 重封锚 ⇒ 锚 consistent

    code, out = _run(st, report, "--cap-usd", "10.0", "--acceptance-sid", sid)
    # 退出码由收工门定：这一场里有一条没答的问题，所以收工门的 `user_pending` 也红
    # （那正是"正确的分支是停在等待用户"的读数）⇒ 1。内容级验收读数的出现与它无关。
    assert code == 1, out
    # 辅助读数确实漂亮
    assert f"{RX.AUXILIARY_SIGNALS[2][1]}＝consistent" in out, out
    assert f"{RX.AUXILIARY_SIGNALS[3][1]}＝3" in out, out       # 一条原有召唤 + 两条新增
    assert f"{RX.AUXILIARY_SIGNALS[4][1]}＝2" in out, out       # literature + concepts
    assert RX.AUXILIARY_SIGNALS[0][1] + "＝" in out, out        # sha 有值
    # 而内容级判据不合格 ⇒ 出口上的 passed 必须是假
    assert "passed（只看上面这几条）＝True" not in out, (
        "辅助读数漂亮而内容不合格时出口报了通过 —— 分栏只在模块里分了，出口上又折平了")
    assert "passed（只看上面这几条）＝False" in out, out
    assert "没通过的：" in out, out
    # 未通过时那句明说：辅助读数不构成通过（`summary()` 的原话，出口整句打出来）
    assert "不构成通过" in out, (
        "出口上没有『辅助读数不构成通过』那句 —— 那是这一层最要紧的一句话")


# ============================================================ 5. 接线不许动的东西

def test_the_wiring_does_not_restate_the_criteria():
    """接线只加"谁调用它、读数落到哪"：判据名与顺序不许在 `cli.py` 里另写一份。

    判法：出口上的每一个判据名都能在 `cli.py` 里找不到成对的字面量
    （名字来自 `RX.CRITERIA`，不是从别处抄的）。判据表的唯一落点仍是
    `reviewaccept.CRITERIA` —— 抄一份就等着它漂。
    """
    src = (SRC / "cli.py").read_text(encoding="utf-8")
    for key, name in RX.CRITERIA:
        assert f'"{key}"' not in src, (
            f"`cli.py` 里写死了判据键 {key!r} ⇒ 判据表被抄了第二份")
        assert f'"{name}"' not in src, (
            f"`cli.py` 里写死了判据名（{name[:12]}…）⇒ 判据表被抄了第二份")
    for key, label in RX.AUXILIARY_SIGNALS:
        assert f'"{key}"' not in src, f"`cli.py` 里写死了辅助读数键 {key!r}"
        assert f'"{label}"' not in src, f"`cli.py` 里写死了辅助读数标签 {label!r}"


def test_the_exit_code_still_comes_only_from_the_closing_gate(tmp_path):
    """接线不许动门的强度：退出码仍然只由收工门定。

    三个方向各跑一次同一个工作区：

    ① 接线跑着、五条全过 ⇒ 收工门 8 格全过 ⇒ 0；
    ② 接线摘掉 ⇒ 必须还是 0（接线不参与退出码）；
    ③ 接线跑着、而内容级验收"没查成"（没给 `--acceptance-sid`）⇒ 必须还是 0
       —— "内容级验收没查成"绝不许把退出码从 0 变成 2 或 1。
    """
    st, report, sid = _good_and_sid(tmp_path)
    code_wired, _ = _run(st, report, "--cap-usd", "1.0", "--acceptance-sid", sid)
    code_unwired, out_unwired = _run(st, report, "--cap-usd", "1.0",
                                     "--acceptance-sid", sid, "--no-review-acceptance")
    code_no_sid, out_no_sid = _run(st, report, "--cap-usd", "1.0")
    assert code_wired == code_unwired == code_no_sid == 0, (
        code_wired, code_unwired, code_no_sid, out_unwired, out_no_sid)
    # 三态不许折平：没给会话身份 ⇒ 那一格必须"没查成"，而收工门那 8 格仍是"通过"
    assert f"{RX.CRITERIA[1][1]}：{_MARKS['unknown']}" in out_no_sid, out_no_sid
    assert f"{RX.CRITERIA[1][1]}：{_MARKS['unknown']}" not in out_unwired, out_unwired
    assert CL.NO_SESSION == "", (
        "`closing.NO_SESSION` 不再是空串 ⇒ 出口传下去的那个『没有会话身份』"
        "会被读成缺省会话（那正是 §58/§63 记过两次的假绿）")


def test_a_negative_cost_cap_is_a_usage_error_not_a_verdict(tmp_path):
    """兜底判据：负数上限是用法错（退出码 2），不许伪装成"判据红"（退出码 1）。

    为什么值得一条判据：`cli.py` 里另一个 `_non_negative_int` 就是为同一件事写的
    （`FINAL-R5-06`），而新加的上限开关很容易漏掉这一条 ——
    漏掉之后负上限会让"花了零元"判成超上限，退出码给 1
    （读的人会去查台账，而真相是命令行写错了）。
    """
    st, report, sid = _good_and_sid(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--plain", "--root", str(st.root), "closing",
                  "--project-dir", str(st.root), "--report", str(report),
                  "--cap-usd", "-1"])
    assert exc.value.code == 2, ("负数上限必须退 2（没查成 / 用法错），"
                                 f"而它退了 {exc.value.code}")
