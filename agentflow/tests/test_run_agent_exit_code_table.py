"""判据：`run-agent` 的退出码分类表（业主 2026-10-19 重排成六档）。
## 为什么这条判据比"再补一条 if"重要
新增一档 `stop_reason` 等于新增一种"这一趟为什么停"。忘了归类时，最坏的形态不是"多一个码"，而是它静默落进某一档、看起来一切正常：落进 `0` 会被读成"做完了"，落进 `4` 会被读成"有人叫停、可以续跑"。写成
`if` 链时，新取值会落到最后那个`return 1`，而 1 曾经就叫"其余"——没人会去看它。
所以这里的核心判据不是"表里有没有 `budget`"，而是「代码里能产生的每一个 `stop_reason` 是不是都在表里登记过」：少一条就红，且红的是"有东西没归类"，不是"某个字面量对不上"。
## 五条判据（每条都带负控 —— 负控证明这条判据真的在守它）
1. 覆盖（最重要）：从 `src/agentflow/agent_loop.py` 源码现扫生产点（`run.stop_reason = "…"` / `stop_reason="…"` 构造参数 /
`_user_stop_reason` 里的 `reason = "…"` 与 `else "…"` / `stopctl.INTERRUPT_REASON`），与`cli.EXIT_CODE_BY_STOP` 对拍；少一条 ⇒
红。负控：往源码文本里塞一条没登记的新取值 ⇒ 同一个扫描必须看见。2. 分类：业主逐字口径的正控（0/2/3/4/5/1 各档代表值）逐个读退出码；负控：把 `stop_file` 挪回 1 ⇒ 红。3. 未登记默认异常：
任何没登记的字符串 ⇒ `1`（安全侧，不是 0）。负控：把兜底改成 0 ⇒ 红。4. 文案一致：`run-agent --help`、`cmd_run_agent` 的
docstring、`_run_agent_exit_code` 的 docstring 三处都写全六档的编号与标题，且都不含"四档/五档"这种旧说法。负控：把 help 里某一档的标题改掉 / 塞回"四档" ⇒ 红。5. 反真空：
扫描面本身要读得出东西来（号码齐、表不空、三处文案非空）——不许"什么都没扫到"于是静默通过。
## 这张表可能比代码宽一点，是刻意的
`no_notify`（L-05e 之后循环不再产生它）今天在 `agent_loop.py` 里没有生产点。表里先登记它不是"多写"，而是「这一档已经被归过类了」（留给旧会话记录）。判据因此分成两半：生产点 ⊆ 表（硬），
以及「表里有、代码里没有」的那几条必须在`_TABLE_ONLY_TODAY` 里逐条写明理由（这样「表里悄悄多一条死档」也会被看见）。
`escalated` 曾经也在这份"预登记"名单上 —— 它由另一条线落地，落地那一刻它就变成真生产点（`run.stop_reason = "escalated"`），于是自动从「表里有、代码里没有」那一栏消失，
表一个字都不用改。这正是"表比代码宽是安全的、只有漏登记才危险"的实例。
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agentflow import cli as CLI  # noqa: E402

LOOP_SRC_REL = "src/agentflow/agent_loop.py"


# ============================================================ 生产点扫描（判据 1）
def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """按名字找函数节点；找不到 ⇒ 直接抛（判据不许因为「找不到」就当成「没有」）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"`agent_loop.py` 里找不到 `def {name}(`（扫描面塌了）")


def _branch_strings(node: ast.AST) -> set[str]:
    """`reason = "<A>" if … else "<B>"` 这一族里真正赋进去的那几个字符串。

    只看「结果位置」（常量本身 / `IfExp` 的两支），不看条件里嵌的东西：
    条件里那个 `state.get("force")` 的 `"force"` 是开关字段名，不是停止原因 ——
    把它算成生产点会造出一条假的"未登记档"。
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _branch_strings(node.body) | _branch_strings(node.orelse)
    return set()


def stop_reasons_in_source(src: str) -> set[str]:
    """从源码现扫「这一趟可能落成哪些 `stop_reason`」（只认生产点，不认散文）。

    走 AST 而不是正则：正则会把注释与 docstring 里举例的取值也算成生产点，于是「新档没登记」和「注释里多写一句 `stop_reason="…"`」分不开 —— 那种假阳会逼着后来的人绕开这条判据。AST
    只看得见真的会执行的那几处赋值 / 传参。四类生产点逐类扫：`run.stop_reason = "<取值>"`（循环里各个 `break` 之前那一步）；
    2. `…(stop_reason="<取值>")`（`LoopRun(...)` 的构造参数 —— 续跑被拒那四档走这条；
    必须扫它，否则那四档会被误判成"没人产生"）；
    3. `_user_stop_reason` 里 `reason = "<取值>" if … else "<取值>"`（`stop_file` /
    `force_stop` 是这一族 —— 它们不是字面量赋给 `run.stop_reason` 的，而是作为返回值交上去；只扫第 1 类会漏掉用户叫停这一整族）；
    4. `stopctl.INTERRUPT_REASON`（父叫停的默认理由码：它从常量读，不在本文件里写死，
    所以显式把那个常量补进来）。
    """
    tree = ast.parse(src)
    got: set[str] = set()
    for node in ast.walk(tree):
        # ---- 第 1 类：run.stop_reason = "<取值>"
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr == "stop_reason":
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        got.add(node.value.value)
                # ---- 第 3 类：`_user_stop_reason` 里 `reason = …`
                elif isinstance(target, ast.Name) and target.id == "reason":
                    got |= _branch_strings(node.value)
        # ---- 第 2 类：stop_reason="<取值>" 作为关键字实参
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if (kw.arg == "stop_reason" and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)):
                    got.add(kw.value.value)

    # 第 3 类的形状守卫：`reason` 这个局部名只该出现在 `_user_stop_reason` 里。
    # 它今天只在那一处（两行 `reason = "…" if … else "…"`）；若哪天别处也用了
    # 同名的局部变量，上面那条 `target.id == "reason"` 会把别人的字符串算进来 ——
    # 这条断言让那种漂当场可见，而不是静默多出几个"生产点"。
    body = _function_node(tree, "_user_stop_reason")
    in_user_stop = {s for node in ast.walk(body) if isinstance(node, ast.Assign)
                    for t in node.targets if isinstance(t, ast.Name) and t.id == "reason"
                    for s in _branch_strings(node.value)}
    assert in_user_stop, "`_user_stop_reason` 里读不到 `reason = \"…\"`（用户叫停那一族漏扫了）"

    from agentflow import stopctl as SC

    got.add(str(SC.INTERRUPT_REASON))
    return got


#: 表里有、但今天在 `agent_loop.py` 里扫不到生产点的那些档 —— 每条都要写明理由
#: （「理由」这一列就是它们的登记：没有理由的死档会被下一半判据看见）。
_TABLE_ONLY_TODAY: dict[str, str] = {
    "no_notify": "L-05e 之后循环不再产生它（已降级成读数）；留给旧会话记录，"
                 "取值本身仍是「收工没按格式填表」⇒ 异常",
    # `escalated` 的那条线已经落地（`agent_loop.py` 里确有
    # `run.stop_reason = "escalated"`），所以它今天不在「表里有、代码里没有」那一栏里
    # —— 这一行是预登记时的理由留痕，删不删都不改变任何判定（不放宽、也不收紧）。
    "escalated": "预登记：交给召唤者、本趟自行收工 ⇒ 归「它自己决定停」那一族（5）",
}


def coverage_problems(table: dict[str, int], src: str) -> list[str]:
    """判据 1：生产点 ⊆ 表；表 − 生产点 ⊆ 已写明理由的预登记档。"""
    produced = stop_reasons_in_source(src)
    out = [f"代码里能产生 `{r}`，但退出码表 `EXIT_CODE_BY_STOP` 里没有登记"
           f"（新档必须来这张表登记，否则它只会落进兜底的异常档）"
           for r in sorted(produced - set(table))]
    out += [f"表里登记了 `{r}`，但代码里扫不到生产点，也没有在 `_TABLE_ONLY_TODAY` 里"
            f"写明理由（「表里悄悄多一条死档」也是一种漂）"
            for r in sorted(set(table) - produced) if r not in _TABLE_ONLY_TODAY]
    return out


# ============================================================ 三处文案（判据 4）
#: 六档各自必须出现在文案里的标题词（码 → 那一档的名字）。
_CODE_LABELS: dict[int, str] = {
    0: "正常完成",
    1: "行为异常",
    2: "研究启动失败",
    3: "等待用户",
    4: "中途停止",
    5: "自行停止",
}

#: 码后面多远之内必须出现它那一档的标题（够「`0` 正常完成」与「0 = 正常完成」两种
#: 写法，又不够跨到下一档去 —— 跨过去就说明这个码根本没写标题）。
_LABEL_WINDOW = 40


def _has_code_label(text: str, code: int, label: str) -> bool:
    """`code` 的某个独立出现之后 40 字内有没有 `label`（有 ⇒ 这一档写全了）。"""
    for m in re.finditer(rf"(?<!\d){code}(?!\d)", text):
        if label in text[m.start():m.start() + _LABEL_WINDOW]:
            return True
    return False


def help_text() -> str:
    """`run-agent --help` 的运行时文本（用户读的是它，不是源码里的字面量）。

    两处都要取：`add_parser(help=…)` 那一句不挂在子 parser 上，而是挂在父 action 的
    那张内部结构上（`choices` 列表里那一行摘要，只能按私有属性名 `getattr` 取）——
    只看子 parser 的 `description` 会漏掉摘要那一份，而那正是最常被读到的一份。
    """
    parser = CLI.build_parser()
    sub = next(a for a in parser._actions if getattr(a, "choices", None))
    sp = sub.choices["run-agent"]
    listed = ""
    for choice in getattr(sub, "_choices_actions", None) or []:
        if str(getattr(choice, "dest", "")) == "run-agent":
            listed = str(getattr(choice, "help", "") or "")
            break
    return f"{listed}\n{sp.description or ''}"


def three_texts() -> dict[str, str]:
    """判据 4 的三处文案（要求同口径的那三处）。"""
    return {
        "run-agent --help": help_text(),
        "cmd_run_agent 的 docstring": CLI.cmd_run_agent.__doc__ or "",
        "_run_agent_exit_code 的 docstring": CLI._run_agent_exit_code.__doc__ or "",
    }


def doc_problems(texts: dict[str, str]) -> list[str]:
    """判据 4：三处都写全六档，且都没有旧说法。"""
    out: list[str] = []
    for where, text in texts.items():
        if not text.strip():
            out.append(f"{where}：读到的文案是空的（判据不许因为读不到就通过）")
            continue
        out += [f"{where}：找不到「{code} ⇒ {label}」这一档（六档必须逐档写全）"
                for code, label in _CODE_LABELS.items()
                if not _has_code_label(text, code, label)]
        if "final" not in text:
            out.append(f"{where}：整段里没有 `final` —— 0 档的含义是「给了 final」，"
                       f"不写它这一档就说不清")
        out += [f"{where}：还留着旧说法「{stale}」（现在是六档）"
                for stale in ("四档", "五档") if stale in text]
    return out


# ============================================================ 分类与兜底（判据 2/3）
class _Run:
    """最小替身：`_run_agent_exit_code` 只读 `stop_reason`。"""

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason


#: 业主口述的正控（表是实现，这里是口径；两者对不上就红 —— 表自己说自己
#: 对是没有意义的）。
_EXPECTED: dict[str, int] = {
    "final": 0,
    "waiting_for_user": 3,
    "no_checkpoint": 2,
    "checkpoint_mismatch": 2,
    "budget": 4,
    "stop_file": 4,
    "force_stop": 4,
    "no_progress_limit": 5,
    "escalated": 5,
    "model_timeout": 1,
    "not_wired": 1,
    "bad_json_limit": 1,
}

#: 判据 3 用的探针：一个谁都没登记的取值（它不在表里 —— 上面有断言守着）。
UNREGISTERED_PROBE = "a_stop_reason_nobody_registered"

#: 判据 3 期望的兜底码（业主：任何没登记的新 stop_reason 默认归 1 = 异常，安全侧）。
_EXPECTED_UNKNOWN = 1


def mapping_problems() -> list[str]:
    """判据 2：正控逐个读真实函数（不是读表 —— 读表证明不了查表那一行没写错）。"""
    out: list[str] = []
    for reason, want in _EXPECTED.items():
        got = CLI._run_agent_exit_code(_Run(reason))
        if got != want:
            out.append(f"`{reason}` 读成 {got}，业主口径是 {want}")
    return out


def unknown_problems() -> list[str]:
    """判据 3：没登记的取值 ⇒ 1；兜底常量本身也必须是 1。"""
    out: list[str] = []
    if UNREGISTERED_PROBE in CLI.EXIT_CODE_BY_STOP:
        out.append(f"夹具有问题：探针 {UNREGISTERED_PROBE!r} 竟然在表里注册过")
    got = CLI._run_agent_exit_code(_Run(UNREGISTERED_PROBE))
    if got != _EXPECTED_UNKNOWN:
        out.append(f"没登记的 stop_reason 兜底成 {got}，必须是 {_EXPECTED_UNKNOWN}"
                   f"（行为异常）—— 兜成 0 会把「新增了一档而没人归类」读成「做完了」")
    if int(CLI.EXIT_CODE_WHEN_UNKNOWN) != _EXPECTED_UNKNOWN:
        out.append(f"`EXIT_CODE_WHEN_UNKNOWN` 是 {CLI.EXIT_CODE_WHEN_UNKNOWN}，"
                   f"必须是 {_EXPECTED_UNKNOWN}")
    return out


def _src() -> str:
    return (REPO / LOOP_SRC_REL).read_text(encoding="utf-8")


# ============================================================ 判据 1：覆盖
def test_every_stop_reason_the_loop_can_produce_is_registered() -> None:
    """判据 1（最重要）：代码里能产生的每一个 `stop_reason` 都在这张表里。

    少一条就红 —— 它防的正是「新增一档忘了归类」，而那种漏在运行时的表现是
    「静默落进兜底档、看起来正常」。
    """
    problems = coverage_problems(CLI.EXIT_CODE_BY_STOP, _src())
    assert not problems, "退出码表与代码的生产点对不上：\n" + "\n".join(problems)


def test_the_scan_is_not_vacuous() -> None:
    """反真空：扫描面真的读到了东西（号码齐、四类生产点都够得着）。

    没有这一条，`stop_reasons_in_source` 哪天正则失效会返回空表，于是判据 1
    永远绿 —— 那是「没查成」冒充「没问题」。
    """
    produced = stop_reasons_in_source(_src())
    # 四类生产点各举一个代表：漏掉任何一类正则都说明扫描面塌了。
    for must in ("final", "no_checkpoint", "stop_file", "force_stop",
                 "interrupted_by_parent"):
        assert must in produced, (f"扫描面读不到 `{must}` 这个生产点 —— 那条正则失效了，"
                                  f"判据 1 会因此变成橡皮图章：{sorted(produced)}")
    assert len(produced) >= 15, f"只扫到 {len(produced)} 个 stop_reason，太少了：{sorted(produced)}"
    # 表这一侧也要有量：六档一个都不许空。
    assert set(CLI.EXIT_CODE_BY_STOP.values()) == {0, 1, 2, 3, 4, 5}, (
        f"六档必须每一档都有登记的取值，实测 {sorted(set(CLI.EXIT_CODE_BY_STOP.values()))}")
    assert CLI.KNOWN_STOP_REASONS == frozenset(CLI.EXIT_CODE_BY_STOP), (
        "`KNOWN_STOP_REASONS` 与表漂了（它必须从表派生）")


def test_negative_control_a_new_unregistered_stop_reason_goes_red() -> None:
    """负控（判据 1）：源码里多出一条没登记的取值 ⇒ 同一个扫描必须当场看见。

    这就是「防新增一档忘了归类」那半条的真实形态：有人加了一行
    `run.stop_reason = "…"` 却没来表里登记。
    """
    mutated = _src() + ('\n\ndef _probe_a_new_stop_reason(run) -> None:\n'
                        '    run.stop_reason = "brand_new_stop_reason"\n')
    assert mutated != _src(), "夹具没改到源码 ⇒ 这条负控是空转"
    assert "brand_new_stop_reason" not in _src(), "夹具把源码当真了（原位就有这个取值？）"
    problems = coverage_problems(CLI.EXIT_CODE_BY_STOP, mutated)
    assert problems, "新加了一条没登记的 stop_reason，判据却没红"
    assert any("brand_new_stop_reason" in p for p in problems), problems


def test_negative_control_removing_a_registration_goes_red() -> None:
    """负控（判据 1 的另一半）：从表里删掉一条 ⇒ 同一个对拍必须看见（少一条就红）。"""
    table = dict(CLI.EXIT_CODE_BY_STOP)
    del table["no_progress_limit"]
    problems = coverage_problems(table, _src())
    assert any("no_progress_limit" in p for p in problems), problems


# ============================================================ 判据 2：分类
def test_the_owner_categories_are_read_off_the_real_function() -> None:
    """判据 2：业主逐字口径的正控（0/2/3/4/5/1 各档都点到）。"""
    problems = mapping_problems()
    assert not problems, "退出码与业主口径对不上：\n" + "\n".join(problems)


@pytest.mark.parametrize("reason,want", [
    ("final", 0),
    ("stop_file", 4),          # 用户叫停（优雅停）⇒ 4，不是 1
    ("force_stop", 4),         # 用户叫停（强停）⇒ 4
    ("budget", 4),             # 预算耗尽 ⇒ 4（与叫停同一档）
    ("waiting_for_user", 3),
    ("no_checkpoint", 2),
    ("no_progress_limit", 5),  # 正常且自行停止、没有 final ⇒ 5，不是 1
    ("escalated", 5),          # 交给召唤者 ⇒ 5
    ("model_timeout", 1),      # 真出事 ⇒ 1
    (UNREGISTERED_PROBE, 1),   # 没登记 ⇒ 1（安全侧）
])
def test_each_category_reading(reason: str, want: int) -> None:
    """判据 2/3 的逐条读数（失败时 pytest 报的是「哪一档读成了几」）。"""
    got = CLI._run_agent_exit_code(_Run(reason))
    assert got == want, f"`{reason}` 读成 {got}，业主口径是 {want}"


def test_negative_control_moving_stop_file_back_to_one_goes_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（判据 2）：把 `stop_file` 挪回 1 ⇒ 判据当场红。

    「挪回 1」就是重排之前的行为（用户叫停被读成「这趟坏了」）。
    """
    monkeypatch.setitem(CLI.EXIT_CODE_BY_STOP, "stop_file", 1)
    problems = mapping_problems()
    assert any("stop_file" in p for p in problems), (
        f"把 stop_file 挪回 1 之后判据竟然没红：{problems}")


# ============================================================ 判据 3：兜底
def test_an_unregistered_stop_reason_falls_back_to_abnormal() -> None:
    """判据 3：没登记的 `stop_reason` ⇒ 1（异常），不是 0。"""
    problems = unknown_problems()
    assert not problems, "\n".join(problems)


def test_negative_control_defaulting_unknown_to_zero_goes_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（判据 3）：把兜底改成 0 ⇒ 判据当场红。

    0 是「做完了」：那会把一次新故障读成绿灯，而没有任何地方会红 —— 这正是
    这半条判据存在的理由。
    """
    monkeypatch.setattr(CLI, "EXIT_CODE_WHEN_UNKNOWN", 0)
    assert CLI._run_agent_exit_code(_Run(UNREGISTERED_PROBE)) == 0, "夹具没生效"
    problems = unknown_problems()
    assert problems, "兜底改成 0 之后判据竟然没红"


# ============================================================ 判据 4：三处文案
def test_the_three_texts_tell_the_same_six_codes() -> None:
    """判据 4：`--help` / 两个 docstring 三处逐档一致，且没有「四档/五档」旧说法。

    为什么咬三处而不是一处：用户从 `--help` 读、维护者从 docstring 读、改代码的人
    从 `_run_agent_exit_code` 读 —— 三处读者不同，任何一处漂了都会让人按错的语义
    去解释退出码，而没有一处会红。
    """
    problems = doc_problems(three_texts())
    assert not problems, "三处退出码文案不一致：\n" + "\n".join(problems)


def test_the_three_texts_are_the_three_places() -> None:
    """反真空：三处都读得到字，且 `--help` 里确实有 `run-agent` 的说明。"""
    texts = three_texts()
    assert len(texts) == 3, texts.keys()
    for where, text in texts.items():
        assert len(text.strip()) >= 200, f"{where} 的文案只有 {len(text)} 字，太短了"
    assert "角色循环" in texts["run-agent --help"]


def test_negative_control_a_drifted_help_text_goes_red() -> None:
    """负控（判据 4）：把 `--help` 里某一档的标题改掉 ⇒ 判据红（那一档读不到标题）。

    要把这一屏里那一档的标题全部换掉：判据咬的是「这一档在这屏里有没有标题」，
    不是「标题出现几次」—— `--help` 的摘要与 `description` 会把同一档各写一遍，
    只改一处仍然读得到，那是判据该放行的情形。
    """
    texts = dict(three_texts())
    before = texts["run-agent --help"]
    texts["run-agent --help"] = before.replace("行为异常", "其它毛病")
    assert texts["run-agent --help"] != before, "夹具没改到文案 ⇒ 这条负控是空转"
    problems = doc_problems(texts)
    assert any("行为异常" in p for p in problems), problems


def test_negative_control_the_old_four_step_wording_goes_red() -> None:
    """负控（判据 4）：文案里塞回「四档」这种旧说法 ⇒ 判据红。"""
    texts = dict(three_texts())
    texts["cmd_run_agent 的 docstring"] += "\n（退出码四档。）"
    problems = doc_problems(texts)
    assert any("四档" in p for p in problems), problems


# ============================== 判据 5：多轮层与单趟层用同一张表（业主 2026-10-19 裁定）
class _Auto:
    """最小替身：`_autonomy_exit_code` 只读 `stop_reason`（`rounds` 还要读最后一轮的 final）。"""

    def __init__(self, stop_reason: str, final: str = "") -> None:
        self.stop_reason = stop_reason
        # `rounds` 那一档要读"最后那一轮有没有交出结论"；其余档不看 reports。
        self.reports = [type("_Rep", (), {"index": 1, "stop_reason": "final",
                                          "final": final})()] if final else []


def two_layer_problems(multi_of) -> list[str]:
    """把同一组 `stop_reason` 分别喂给两个入口，逐条断言退出码相等。

    「相等」而不是"各自符合各自的表"：这条判据要抓的正是两套口径本身 ——
    改前 `budget` 单趟 4 / 多轮 1、`stop_file` 单趟 4 / 多轮 0，两边单看都"有理由"，
    合起来才看出是同一件事被写了两遍。
    """
    out: list[str] = []
    for reason in sorted(CLI.EXIT_CODE_BY_STOP):
        single = CLI._run_agent_exit_code(_Run(reason))
        multi = multi_of(_Auto(reason, final="交出了结论"))
        if single != multi:
            out.append(f"`{reason}`：单趟 ⇒ {single}，多轮 ⇒ {multi}（同一件事两套口径）")

    probe = CLI._run_agent_exit_code(_Run(UNREGISTERED_PROBE))
    probe_multi = multi_of(_Auto(UNREGISTERED_PROBE))
    if probe != probe_multi:
        out.append(f"未登记的 stop_reason：单趟 ⇒ {probe}，多轮 ⇒ {probe_multi}")
    return out


def test_the_two_layers_read_the_same_table() -> None:
    """判据 5（2026-10-19 业主裁定，根因）：`--rounds` 那层不许自成一条 if 链。

    改前 `cmd_run_agent` 里那条 if 链是
    `0 if stop_reason in ("rounds","stop_file","resumed_done") else 1`，
    于是 `stop_file`（用户叫停）在多轮层被读成 0「做完了」、`budget` 被读成 1「异常」，
    而单趟层分别是 4 和 4 —— 同一张表在两处各写一遍，两处都可能漂，且漂了没人会红。
    """
    problems = two_layer_problems(CLI._autonomy_exit_code)
    assert not problems, ("多轮层的退出码与单趟层不是同一张表：\n" + "\n".join(problems))


def _legacy_multi_round_exit_code(auto) -> int:
    """改前那一层的样子（自成 if 链：`budget ⇒ 1`、`stop_file ⇒ 0`）—— 负控夹具。"""
    if auto.stop_reason == "checkpoint_mismatch":
        return 2
    if auto.stop_reason == "waiting_for_user":
        return 3
    return 0 if auto.stop_reason in ("rounds", "stop_file", "resumed_done") else 1


def test_negative_control_the_old_multi_round_ladder_goes_red() -> None:
    """负控（判据 5）：把多轮层改回写死的老样子 ⇒ 判据当场红。

    逐条点名 `budget`（1 vs 4）与 `stop_file`（0 vs 4）：这两格正是"同一件事两套
    口径"在真机上最会误导人的地方 —— 一个是"钱花完了"被读成坏，一个是"人叫停了"
    被读成做完了。
    """
    problems = two_layer_problems(_legacy_multi_round_exit_code)
    assert any("budget" in p for p in problems), problems
    assert any("stop_file" in p for p in problems), problems


@pytest.mark.parametrize("reason,want", [
    ("resumed_done", 0),        # 多轮特有：续跑发现这一程已经跑完
    ("budget", 4),              # 以下全是"同一张表"的读数（业主 2026-10-19 逐档给出）
    ("stop_file", 4),
    ("force_stop", 4),
    ("ask_cancelled", 4),
    ("interrupted_by_parent", 4),
    ("waiting_for_user", 3),
    ("checkpoint_mismatch", 2),
    ("no_checkpoint", 2),
    ("already_finished", 2),
    ("resume_no_transcript", 2),
    ("escalated", 5),
    ("no_progress_limit", 5),
    (UNREGISTERED_PROBE, 1),
])
def test_the_owner_multi_round_readings(reason: str, want: int) -> None:
    """业主给多轮层的逐档读数（多轮特有那两档 + 与单趟同表的那几族）。"""
    got = CLI._autonomy_exit_code(_Auto(reason, final="交出了结论"))
    assert got == want, f"多轮层 `{reason}` 读成 {got}，业主口径是 {want}"


def test_rounds_exhausted_without_a_final_is_five_not_zero() -> None:
    """轮数用完那一档：产出了 final ⇒ 0；没有 final ⇒ 5（不是 0）。

    为什么这条要单独钉：`rounds` 是唯一"退出码取决于内容"的档 —— 只看 stop_reason
    的话，把它一律读成 0（改前的行为）会让"跑到轮数上限、一句话没说"看起来像成功。
    """
    assert CLI._autonomy_exit_code(_Auto("rounds", final="结论：做完了")) == 0
    assert CLI._autonomy_exit_code(_Auto("rounds")) == 5, "没有 reports 就是没有 final"
    assert CLI._autonomy_exit_code(_Auto("rounds", final="   ")) == 5, "只有空白的 final 不算 final"


def test_the_multi_round_only_forms_stay_out_of_the_loop_table() -> None:
    """反污染：`rounds` / `resumed_done` 不许混进 `EXIT_CODE_BY_STOP`。

    混进去会让判据 1 的生产点对拍（它扫 `agent_loop.py` 的 `LoopRun`）多出两条永远
    对不上的档，那张表就不再是"一趟循环的口径"。它们只活在多轮层。
    """
    assert not (set(CLI.AUTONOMY_ONLY_EXIT_CODE) & set(CLI.EXIT_CODE_BY_STOP)), (
        f"多轮特有的形态混进了循环退出码表：{sorted(set(CLI.AUTONOMY_ONLY_EXIT_CODE) & set(CLI.EXIT_CODE_BY_STOP))}")
    assert "rounds" not in CLI.EXIT_CODE_BY_STOP
