# -*- coding: utf-8 -*-
"""接线判据：内容级验收（`draft/37` §17.3）真的在生产路径上跑一次，读数落到人能读的地方。`reviewaccept` 此前是"判据齐、测试齐、而真机上永远没人跑它"：`src/`/`tools/`/`scripts/`里一条 import 都到不了它，
五条测试文件各自 `import reviewaccept` 直接调 ——测试全绿与"这条判据在生产面上存在"是两件事，而只有前者成立时，读的人会把它读成后者。生产面今天有两个只读出口，读数同形（判据名与顺序都现取自 `reviewaccept`）：CLI
`agentflow closing`（`cli._print_review_acceptance`，题 6 选 A）；2. 主控的收工工具 `conductor.closing`（`tools/conductor_tools.py`，题 13 选 B）——决定收工的人是主控，
它做收工决定时手里不能只有收工门那八格。所以这一组的前两条是反真空，不是对拍副本：`test_the_production_callers_are_exactly_the_registered_readonly_exits`：把生产面的调用者一个个数出来（`ast` 扫
`src/`），并逐条登记它们为什么在那儿 ——零个调用者 ⇒ 红（接线没接上）；多出一个没登记的 ⇒ 红（多了一条没人解释的面）。这一条不满足于"CLI 里有一行 import"：`import` 与"真的调它"是两件事。（它改名前叫
`test_the_only_production_caller_is_the_readonly_closing_exit`：当时只有 CLI 那一条，题 13 选 B 之后不再"只有一条"，名字跟着口径一起改，判据本身（逐条登记 + 相等）一个字没放宽。）2.
`test_every_criterion_really_runs_through_the_cli_exit` 与`test_every_criterion_really_runs_through_the_conductor_tool_exit`：
把五条内容级判据的每一个隐藏入口逐个换成"一调就炸"，分别从 CLI 出口与工具出口进去 ⇒ 必须炸。"没有真的跑到判据 ⇒ 不许算通过"就是这两条的字面实现。
中间几条守"读数落到人能读到的地方"与三态不折平（两个出口各一组）：`test_the_six_criteria_and_the_five_auxiliary_readings_reach_the_human_output`—— 六条判据 + 五种辅助读数的名字与值必须出现在
CLI 的原始输出里，并且辅助读数带着"不构成通过"的那句话；`test_the_tool_exit_reports_the_criteria_and_the_auxiliary_readings` ——同一份读数必须出现在工具体的返回里（判据名/顺序/辅助标签逐条对上
`reviewaccept`）。4. `test_the_readings_are_recomputed_not_hand_copied` 与`test_the_tool_readings_are_recomputed_not_hand_copied` —— 改盘上的东西
⇒输出里的数跟着变（防"把六条判据的结论手抄成一句通过"）。`test_pretty_auxiliary_readings_cannot_print_a_pass`：把五种辅助读数全部造得漂亮（正文改过 sha 变了 / PDF 在盘上 / 锚 consistent /
任务行与台账行都增加），而内容级判据不合格 ⇒ CLI 输出里的 `passed` 必须是假。这一条要的是"分栏在出口上也是真的"，不只是 `ReviewAcceptance` 里分了栏。
抄一遍判据：`test_the_wiring_does_not_restate_the_criteria` 与`test_the_tool_wiring_does_not_restate_the_criteria` —— 两个出口上的判据名、判据顺序、辅助读数标签必须来自
`reviewaccept.CRITERIA` /`AUXILIARY_SIGNALS`，不许在 `cli.py` 或 `conductor_tools.py` 里另写一份（另写一份就等于"同一件事两个落位"，而两处会各自漂）。- 动退出码 / 动
`can_close`：`test_the_exit_code_still_comes_only_from_the_closing_gate`与
`test_the_tool_readings_are_recomputed_not_hand_copied`（后者的下半段钉住"内容级判据红了，而收工门那八格的 `can_close` 一个字都不变"）—— 摘掉接线 /让内容级验收"没查成"都不许改退出码；
把内容级验收并进退出码或 `can_close`等于偷偷改门的强度，那是裁定题不是接线题。- `cap_usd` 的三态：`test_cap_usd_absent_is_unknown_and_over_cap_is_fail`与
`test_a_negative_cost_cap_is_a_usage_error_not_a_verdict` ——不给上限 ⇒ 那一格"没查成"（绝不是通过）；负数上限是用法错（受控拒绝），不许伪装成"判据红"。"""
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

    另加一笔 M 的收工判据（业主 2026-10-09：「是否收工不要用机械判据，由 M
    制定的目标是否达成为准」）：这个夹具代表"一趟好好的交付"，而按新口径，
    "交付好"本身不再等于"可以收工" —— 还要 M 说一句达成了。判据落在
    `out/review/m-verdicts.jsonl`（运行内 `conductor.closing` 给判据时的同一处落点），
    于是这些用例走的正是"运行外出口读运行内落盘的那一份"这条路。
    要改这一份（例如造"没达成"的场）就在后面再追加一行 —— 读侧取最后一行。
    """
    st, report = _good(tmp_path)
    _m_verdict(tmp_path, met=True, basis="五条全过的交付 + 八格读数")
    return st, report, SS.session_id()


def _m_verdict(root, *, met: bool, goal: str = "把这份交付做到能交",
               basis: str = "", tasks=()) -> None:
    """往 `out/review/m-verdicts.jsonl` 追加一笔 M 的判据（append-only）。"""
    from agentflow import closing as _CL

    okw, why = _CL.write_m_verdict(
        root, goal=goal, met=met, basis=basis, sid=SS.session_id(),
        tasks=tasks or ({"what": goal, "state": "done" if met else "not_done"},))
    assert okw, why


def _tool_closing(store, *, project_dir: str = "", report_path: str = "",
                  cap_usd: float | None = None, sid: str | None = None,
                  session_root=None, **extra):
    """从工具体出口进（不是 CLI、也不直接 import `reviewaccept` 调它）。

    为什么必须走 `build_registry` + `registry.call`：要证的正是"这条调用链在
    生产面上存在"。直接调 `check_review` 只能证明判据自己是对的 —— 那件事已经
    有五条测试在守了，而生产面此前是 0 条 import。

    `cap_usd` 缺省是"不给这个参数"（不是传 `None`）：参数都不给与给了个空值
    在读的人眼里必须是两件事，这里让它们逐字分成两条路。

    `**extra` 原样透传给工具（M 的判据那三格 `goal` / `goal_met` / `basis` /
    `task_list` 就是这样传的）—— 本函数不替它们编缺省值。
    """
    from agentflow.tools import build_registry

    built = build_registry(store=store, workspace_root=store.root,
                           session_root=(store.root if session_root is None else session_root),
                           sid=(SS.session_id() if sid is None else sid),
                           roles=("M",))
    kw: dict = {"project_dir": project_dir, "report_path": report_path, **extra}
    if cap_usd is not None:
        kw["cap_usd"] = cap_usd
    return built.registry.call("conductor.closing", role="M", **kw)


def _criterion_row(payload: dict, key: str) -> dict:
    """取某一格判据的行；键不在 `RX.CRITERIA` 里就当场红（判据名改了要跟着改）。"""
    keys = [k for k, _ in RX.CRITERIA]
    assert key in keys, f"判据键 {key!r} 不在 `RX.CRITERIA` 里（{keys}）⇒ 本判据要跟着改"
    return next(r for r in payload["criteria"] if r["key"] == key)


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
    "tools/conductor_tools.py": (
        "conductor_closing",
        "主控的收工工具 `conductor.closing`（题 13 选 B）：主控是决定收工的人，"
        "它调这个工具时手里不能只有收工门那八格 —— 同一次只读调用里把内容级验收的"
        "读数一并给出（判据名/顺序/辅助标签现取自 `reviewaccept`）。"
        "为什么在工具体里而不是另开一个工具：两者读的是同一批入参"
        "（`project_dir` / `report_path` / `session_root` / `sid` / 成本上限），"
        "而那批入参在 `conductor_closing` 里已经收齐了；开第二个面只会让"
        "「收工」与「内容级验收」在模型眼里变成两件可以只做一件的事。",
    ),
    "webui/readers.py": (
        "acceptance_face",
        "Web 端的只读面 `GET /api/acceptance`（Web 批 W1，B 线的 `readers.acceptance_face`）："
        "`Acceptance.tsx` 那一页要的就是这五条内容级判据 + 五条辅助信号的逐条读数，"
        "而它的唯一来源就是 `reviewaccept.check_review`。这一条是**只读出口**："
        "`acceptance_face` 只读盘、只返回 `{tri, reason, ...}`，三态里 "
        "`unreadable` / `not_applicable` 照实回报（页面不许把读不到渲染成 0）；"
        "它不改盘、不起子进程、不出网。为什么值得单列一条：这是这一层第一次被"
        "**用户端**直接消费 —— 在此之前它只有 CLI 与主控工具两个出口，"
        "网页端要用它就得先在这里留一条可审的登记。",
    ),
}


def _print_review_acceptance_calls() -> list[str]:
    """`_print_review_acceptance` 这个函数体里调到的名字（`ast`）。"""
    got = _calls_in(SRC / "cli.py")
    return got.get("_print_review_acceptance", [])


def test_the_production_callers_are_exactly_the_registered_readonly_exits():
    """接线判据（正控 + 逐条登记）：生产面的调用者恰好是登记的那几个。

    改前必红：这一层此前在生产面上 0 个调用者（`src/`/`tools/`/`scripts/`都到不了它），于是"五条内容级判据"在真机上从来没跑过一次。

    为什么不是"CLI 里有一行 `from . import reviewaccept`"就算接线：那只是声明面（import 了不等于调了）。这一条数的是调用点（`ast` 里的`check_review(...)`），
    并且要求每个调用点都在登记表里有一行理由。

    为什么名字从"`the_only_production_caller`"改过来：题 13 选 B 之后生产面不再是"只有 CLI 那一条"。改的是名字与口径（登记表可以有多条），判据本身（盘上调用点集合 == 登记表，
    且登记的每个函数真的调了它）没放宽。
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
    # 反真空（口径）：登记表里"只读出口"这条性质必须仍然成立 ——
    # 工具体声明成写工具的话，这条接线就不再是"只读出口"（收工那一步会改盘）。
    from agentflow.tools import conductor_tools as CT

    assert CT.conductor_closing.__tool_spec__.side_effect == "read", (
        "`conductor.closing` 不再是只读工具 ⇒ 这条接线不再是「只读出口」")


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


# ============================================================ 2b. 反真空：工具体出口那条链

@pytest.mark.parametrize("impl", _CRITERION_IMPLS)
def test_every_criterion_really_runs_through_the_conductor_tool_exit(tmp_path, monkeypatch, impl):
    """反真空（题 13 选 B，每一个判据入口各一条）：从主控的工具体出口进去，判据必须真的被执行。

    做法与 CLI 那条同形：把这个隐藏入口换成"一调就炸"，然后调
    `conductor.closing`（走 `build_registry` + `registry.call` 这条真装配路径）。

    为什么"炸"也算证据：`ToolRegistry.call` 会把异常收成
    `ok=False / kind='unexpected'`，所以断言打在"这次调用没成功、报的是那个炸点"上 ——
    "没有真的跑到判据"与"跑到了、判据炸了"在这里是两件分得开的事。

    为什么必须从工具出口进：本条要证的是"运行内的主控手里真的拿到这份读数"。
    直接 `import reviewaccept` 调它只能证明判据自己是对的（那有五条测试在守）。
    """
    from agentflow.store import Store

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()

    def boom(*_a, **_kw):
        raise AssertionError(f"判据 {impl} 被调到了（这正是要证的：工具出口那条链活着）")

    monkeypatch.setattr(RX, impl, boom)
    res = _tool_closing(st)
    assert res.ok is False, (f"判据 {impl} 换成炸点之后工具体居然成功了 ⇒ "
                             "内容级验收没从工具出口跑到")
    assert str((res.meta or {}).get("kind")) == "unexpected", (res.meta, res.data)
    assert impl in str(res.error), (res.error, res.meta)


def test_unwiring_the_tool_control_makes_it_dark(tmp_path, monkeypatch):
    """上面那条负控的对照：接线摘掉之后，那些隐藏入口一次都不许被工具体调到。

    摘法是把 `check_review` 整个换掉（它不再逐个调判据），同时把所有判据入口
    都换成炸点：工具体必须安静地返回，且那个替身必须被调到恰好一次 ——
    这证明上面的"炸"确实来自「工具体 → check_review → 判据」这条链，
    而不是某个夹具路径顺手碰了它们。
    """
    from agentflow.store import Store

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    hits: list[str] = []

    def stub(*_a, **_kw):
        hits.append("check_review")
        return RX.ReviewAcceptance()

    def boom(*_a, **_kw):
        raise AssertionError("接线摘掉了，判据不该被调到")

    monkeypatch.setattr(RX, "check_review", stub)
    for impl in _CRITERION_IMPLS:
        monkeypatch.setattr(RX, impl, boom)
    res = _tool_closing(st)
    assert res.ok is True, (res.error, res.meta)
    assert hits == ["check_review"], ("工具体没有经由 `check_review` 读内容级验收"
                                      f"（替身被调到 {len(hits)} 次）⇒ 上面那条负控证明不了任何事")


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
    assert code2 == 0, out2                                # 退出码仍由 M 的判据定
    assert f"{name}：{_MARKS['fail']}" in out2, out2
    assert "passed（只看上面这几条）＝False" in out2, out2
    assert f"没通过的：{key}" in out2, out2


# ------------------------------------------- 3b. 同一份读数从工具体出口给主控

def test_the_tool_exit_reports_the_criteria_and_the_auxiliary_readings(tmp_path):
    """题 13 选 B：主控在收工那一步必须看得见逐条判据（三态 + detail）与五种辅助读数。

    这一条读的是工具体的返回（不是 CLI 输出）：判据名、判据顺序、辅助读数的标签
    必须与 `reviewaccept.CRITERIA` / `AUXILIARY_SIGNALS` 逐条对上 ——
    它们只能从那个模块取，工具体里抄一份就会在这里红。

    三态不折平：每一格都必须是 `pass`/`fail`/`unknown` 之一，且 `unknown` 与
    `fail` 各有自己的字面（出口上的三种标记在 CLI 那边还各有一条判据）。
    """
    st, report, sid = _good_and_sid(tmp_path)
    res = _tool_closing(st, project_dir=str(st.root), report_path=str(report),
                        cap_usd=1.0, sid=sid)
    assert res.ok, (res.error, res.meta)
    ra = res.data["review_acceptance"]

    # 判据：键、名字、顺序都来自 `RX.CRITERIA`（不是这里手抄的一份）
    assert [r["key"] for r in ra["criteria"]] == [k for k, _ in RX.CRITERIA]
    assert [r["name"] for r in ra["criteria"]] == [n for _, n in RX.CRITERIA]
    for row in ra["criteria"]:
        assert row["state"] in _MARKS, f"判据 {row['key']} 的三态值不在词表里：{row['state']!r}"
        assert isinstance(row["detail"], str), row
    # 五条全过的工作区 ⇒ 逐条 pass，`passed` 为真，没通过的那一栏是空的
    assert all(r["state"] == "pass" for r in ra["criteria"]), ra["criteria"]
    assert ra["passed"] is True and ra["failed"] == [], ra

    # 辅助读数：标签与顺序来自 `RX.AUXILIARY_SIGNALS`，五种都带值（值可以是空/null）
    assert [r["key"] for r in ra["auxiliary"]] == [k for k, _ in RX.AUXILIARY_SIGNALS]
    assert [r["label"] for r in ra["auxiliary"]] == [l for _, l in RX.AUXILIARY_SIGNALS]
    for row in ra["auxiliary"]:
        assert "value" in row, row
    # 那句"逐字禁止拿来当通过"必须是模块自己的原话（不是这里另写一句近义句）
    assert ra["auxiliary_note"] == RX.ReviewAcceptance().to_dict()["auxiliary_note"], ra
    assert "逐字禁止" in ra["auxiliary_note"], ra
    # 逐条读数（判据各自的原始读数）也一并给出，分栏在出口上仍然是真的
    assert ra["readings"], "工具体没有把逐条判据读数给出来"
    assert "内容级判据全过" in ra["summary"], ra


def test_the_tool_readings_are_recomputed_not_hand_copied(tmp_path):
    """反真空（防手抄，工具体这一侧）：改盘上的东西 ⇒ 返回里的数跟着变。

    做法与 CLI 那条同形：同一个工作区先调一次（那一格 `pass`），
    再把一条命题弄坏，重调 ⇒ 那一格必须变 `fail`、`passed` 跟着变假、
    `failed` 里点名它。

    同时钉住"两层不折平"：内容级判据红了，而收工门那八格的 `can_close`
    一个字都不许跟着变（那是裁定题，不是接线题）。
    """
    st, report, sid = _good_and_sid(tmp_path)
    from agentflow import schema as _S

    before = _tool_closing(st, project_dir=str(st.root), report_path=str(report),
                           cap_usd=1.0, sid=sid)
    assert before.ok and before.data["review_acceptance"]["passed"] is True, before.data
    assert before.data["can_close"] is True, before.data

    key, _name = RX.CRITERIA[0]
    _stmt(st, "0002", page_range=_S.PageRange())          # 缺页码 ⇒ 这一条必须红
    after = _tool_closing(st, project_dir=str(st.root), report_path=str(report),
                          cap_usd=1.0, sid=sid)
    assert after.ok, (after.error, after.meta)
    ra = after.data["review_acceptance"]
    assert _criterion_row(ra, key)["state"] == "fail", ra["criteria"]
    assert ra["passed"] is False and key in ra["failed"], ra
    # 两层刻意不折平：内容级判据红了，收工门那八格照旧（can_close 由 M 的判据定）
    assert after.data["can_close"] is True, after.data["status"]
    assert after.data["status"] == before.data["status"], (
        "内容级验收把收工门的读数带偏了 —— 两层的入参同源，但判定必须各管各的")


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
    # 概念行并表之后住 `statements`（`kind="concept"`）：辅助读数 `ledger_rows` 数的
    # 正是 `conceptrows.view` 里那些行 ⇒ 这一格必须落一条真概念行（别的 kind 不会让
    # 这个读数动，那样这条用例就白跑了）。
    _stmt(st, "0000", kind="concept", label="室图", statement_text="室图", statement_full="d")
    (tmp_path / "out" / "paper" / "main.tex").write_text("改过了\n", encoding="utf-8")
    _seal(tmp_path, st)                                   # 重封锚 ⇒ 锚 consistent
    # 这一场里有一条没人回答的问题 ⇒ M 的判据是"没达成"（正确分支是停在等待用户）：
    # 取最后一行，于是这一条把上面夹具那一笔 met=True 顶掉。
    _m_verdict(tmp_path, met=False, basis="有一条问题还没人回答 ⇒ 停在这里等用户",
               tasks=({"what": "把这份交付做到能交", "state": "not_done",
                       "why": "等用户回答 q0009"},

                      ))

    code, out = _run(st, report, "--cap-usd", "10.0", "--acceptance-sid", sid)
    # 退出码由 M 的判据定：M 判"没达成" ⇒ 1（内容级验收读数的出现与它无关）
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


def test_the_tool_wiring_does_not_restate_the_criteria():
    """同一个口径的工具体那一半：`conductor_tools.py` 里不许抄判据名/辅助读数标签。

    判法与 `cli.py` 那条逐字同形。为什么两个文件各有一条：抄一份的成本很低
    （对着出口的输出复制粘贴），而抄出来的那份会与 `reviewaccept` 各自漂 ——
    到时候"哪一份是真的"没人说得清。名字与顺序的唯一落点是 `RX.CRITERIA`。
    """
    src = (SRC / "tools" / "conductor_tools.py").read_text(encoding="utf-8")
    for key, name in RX.CRITERIA:
        assert f'"{key}"' not in src, (
            f"`conductor_tools.py` 里写死了判据键 {key!r} ⇒ 判据表被抄了第二份")
        assert f'"{name}"' not in src, (
            f"`conductor_tools.py` 里写死了判据名（{name[:12]}…）⇒ 判据表被抄了第二份")
    for key, label in RX.AUXILIARY_SIGNALS:
        assert f'"{key}"' not in src, f"`conductor_tools.py` 里写死了辅助读数键 {key!r}"
        assert f'"{label}"' not in src, f"`conductor_tools.py` 里写死了辅助读数标签 {label!r}"


def test_cap_usd_absent_is_unknown_and_over_cap_is_fail(tmp_path):
    """成本那一格的三态（工具体这一侧）：不给上限 ⇒ 没查成；给了且真的超 ⇒ 不通过。

    为什么必须分开判：`cap_usd` 不给时把那一格写成"通过"是本项目最忌的折平
    （"没查"读成"查过了没问题"）。所以三条一起判：
    不给 ⇒ `unknown`（detail 里明说"没查成"）；给一个够大的 ⇒ `pass`；
    账上真超了 ⇒ `fail`。三条都从工具出口读，不是直接调 `check_review`。
    """
    st, report, sid = _good_and_sid(tmp_path)
    _usage(st, "0002", 5.0)                       # 夹具原有 0.25 + 这一笔 5.0

    def state(cap: float | None) -> dict:
        # `cap=None` 走的是"连 `cap_usd` 这个参数都不给"那条路（见 `_tool_closing`）
        res = _tool_closing(st, project_dir=str(st.root), report_path=str(report),
                            cap_usd=cap, sid=sid)
        assert res.ok, (res.error, res.meta)
        return _criterion_row(res.data["review_acceptance"], "within_cost_cap")

    row = state(None)
    assert row["state"] == "unknown", row
    assert "没查成" in row["detail"], row
    assert state(10.0)["state"] == "pass"
    over = state(1.0)
    assert over["state"] == "fail", over
    assert "5.25" in over["detail"], over


def test_a_negative_cost_cap_is_a_param_error_not_a_verdict(tmp_path):
    """兜底判据（工具体那一侧）：负数上限是受控的用法错，不许伪装成"判据红"。

    与 CLI 那条同一条纪律（`FINAL-R5-06`）：负数上限要么被参数校验拒成
    `param_error`，要么会在"花了零元"上判成超上限 —— 后者让读的人去查台账，
    而真相是调用方把参数写错了。这里钉住前一种（`cap_usd` 的 `minimum: 0`）。
    """
    from agentflow.store import Store

    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    res = _tool_closing(st, cap_usd=-1.0)
    assert res.ok is False, res.data
    assert str((res.meta or {}).get("kind")) == "param_error", (res.meta, res.error)


def test_the_exit_code_still_comes_only_from_the_closing_gate(tmp_path):
    """接线不许动门的强度：退出码仍然只由收工门定。

    三个方向各跑一次同一个工作区：

    ① 接线跑着、五条全过、M 的判据说"达成" ⇒ 0；
    ② 接线摘掉 ⇒ 必须还是 0（接线不参与退出码）；
    ③ 接线跑着、而内容级验收"没查成"（没给 `--acceptance-sid`）⇒ 必须还是 0
       —— "内容级验收没查成"绝不许把退出码从 0 变成 2 或 1。

    新口径（业主 2026-10-09）只改了"谁定退出码"：由 M 的判据定（不再是"八格全过"），
    "内容级验收不参与退出码"这一条一个字没变。
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


# ============================================================ 6. M 的判据：落盘 + 三态退出码

def test_the_exit_code_follows_ms_verdict_three_ways(tmp_path):
    """退出码跟着 M 的判据 走（业主 2026-10-09：「是否收工不要用机械判据，
    由 M 制定的目标是否达成为准」）—— 三态各一条：

    - 运行内落过判据、说"达成" ⇒ 0（运行外那一趟读的是运行内那一份：这条路
      正是 `draft/37` §63 记过的"两个出口读数必须一致"）；
    - 落过的判据说"没达成" ⇒ 1；
    - 一行都没落 ⇒ 2（"没人判过"既不是"可以交"也不是"被拦住"）。

    为什么"没人判过"必须是 2 而不是 0：0 的含义是"M 判过、可以交"。
    把"没判过"折成 0 就是本项目最忌的那一类折平（`draft/37` §58/§63 的假绿）。
    """
    from agentflow import closing as _CL

    st, report = _good(tmp_path)
    st2, report2 = _good(tmp_path / "b")
    st3, report3 = _good(tmp_path / "c")
    _m_verdict(tmp_path, met=True, basis="M 说达成了")
    _m_verdict(tmp_path / "b", met=False, basis="M 说还差一件")
    code_yes, _ = _run(st, report)
    code_no, out_no = _run(st2, report2)
    code_none, out_none = _run(st3, report3)
    assert (code_yes, code_no, code_none) == (0, 1, 2), (code_yes, code_no, code_none)
    assert "没有提交自己的判据" in out_none, out_none
    assert "没有提交自己的判据" not in out_no, out_no
    # 显式入口（人/CI 代述 M 的说法）压过落盘那一份
    code_flag, _ = _run(st2, report2, "--goal-met")
    assert code_flag == 0, code_flag
    assert _CL.read_m_verdict(tmp_path / "b")["count"] == 1, (
        "命令行那一次不该改写落盘的判据（它只是代述，不是运行内那一次）")


def test_ms_verdict_survives_the_run_through_the_tool_exit(tmp_path):
    """运行内给判据的那一次调用把它落盘 ⇒ 运行外的出口读得到同一份（两个出口一致）。

    这一条钉的是"同一处口径"：判据由 M 在运行内给（`conductor.closing`），
    落的盘由运行外那趟读（`agentflow closing` 不给显式入参时的回退）。
    """
    from agentflow import closing as _CL

    st, report = _good(tmp_path)
    res = _tool_closing(st, project_dir=str(st.root), report_path=str(report),
                        cap_usd=1.0, sid="s-verdict", goal="把这份交付做到能交",
                        goal_met=True, basis="八格与内容级读数都在",
                        task_list=[{"what": "把交付做完", "state": "done"}])
    assert res.ok, (res.error, res.meta)
    assert res.data["can_close"] is True, res.data
    assert res.data["verdict_written"]["ok"] is True, res.data["verdict_written"]
    got = _CL.read_m_verdict(st.root)
    assert got["checked"] and got["count"] == 1, got
    assert got["verdict"]["met"] is True and got["verdict"]["sid"] == "s-verdict", got
    # 运行外：不给任何判据开关 ⇒ 读到的就是上面那一份 ⇒ 退出码 0（一致）
    code, out = _run(st, report)
    assert code == 0, out
    assert "M 判" in out, out


def test_the_verdict_lands_in_the_workspace_not_the_process_cwd(tmp_path, monkeypatch):
    """真机 t1v 抓到的缺陷：`project_dir="."` 时判据落到了跑批的工作目录里。

    工具契约写的是"相对工作区"，而 `Path(".")` 是按进程当前目录解析的 ——
    真机那一趟：M 在步 99 交了判据（`goal_met` 给了）、工具报落盘成功，而判据
    实际写在 `agentflow/out/review/`（跑批的工作目录）而不是
    `projects/p5-review-t18/out/review/`（工作区）⇒ 运行外的出口读工作区，
    得出"没人判过"（退出码 2），而运行内 M 明明判过 —— 正是这一格要治的分家。

    判据：从工具体出口给相对 `project_dir`（`"."`），判据必须落在工作区里，
    且进程目录里不许出现 `out/`。修法是两侧共用 `resolve_under_workspace`
    （写侧 `conductor.closing`、读侧 `check_closing` 的回退）。
    """
    st, report = _good(tmp_path)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)                      # 进程当前目录 ≠ 工作区（真机形状）
    res = _tool_closing(st, project_dir=".", report_path=str(report),
                        goal="把这份交付做到能交", goal_met=True)
    assert res.ok, (res.error, res.meta)
    landed = st.root / "out" / "review" / "m-verdicts.jsonl"
    assert landed.is_file(), ("判据没落在工作区里 ⇒ 运行外的出口读不到它"
                              f"（工具报的落点：{res.data['verdict_written']}）")
    assert not (cwd / "out").exists(), (
        "判据落到了进程当前目录里（`project_dir='.'` 没按工作区解析）——"
        "这正是真机 t1v 的形态")


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
