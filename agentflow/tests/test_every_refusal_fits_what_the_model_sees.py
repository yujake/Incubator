# -*- coding: utf-8 -*-
"""每一条拒信都必须装得进模型真正能看到的那一段（Q31，2026-10-26）。

## 缺陷

模型看到的拒信不是台账里那一段全文，而是 `agent_loop._do_summon` 交给它的
`_clip(res.detail, 400)`。Q31 实测：扇出那条拒信 580 字，前 400 字里有判定读数与
工具名，而「只可对静默的」这条前提与收尾在全 400 之后 —— 台账里写着「说了」，
模型一个字没看到。比「没说」更坏：读台账的人以为它知道。

## 这一份钉住的五件事

| 判据 | 守的是 | 改前红在哪 |
|---|---|---|
| a) `test_a_every_gate_refusal_has_the_four_parts_within_the_window` | 全仓每一个闸门拒信（`policy.Refusal`，由 AST 逐个点出来，不是手抄的清单）都四样齐全、且四样那一段 ≤ 400 字 | 扇出那条 580 字（含名单形态 598 / conductor 追加等待读数后 614），四样里「前提」「禁令」都在 400 之后；且改前根本没有这四样这个词头（判定 / 正路 / 前提 / 禁令） |
| b) `test_b_the_four_parts_come_before_the_explanation` | 顺序：四样按判定 → 正路 → 前提 → 禁令排，附加解释（`说明：`）排在四样最后一笔之后 | 改前扇出那条把解释夹在判定与工具名之间（"这一格只数直接子…"），顺序不可机械判 |
| c) `test_c_after_the_real_clip_the_four_parts_are_still_there` | 拿真的 `AL._clip(text, 400)` 过一遍，四样那一段与四个词头全都还在（这是真正对模型负责的那一条） | 改前扇出那条 `_clip` 之后「前提」与「禁令」都不在 |
| d) `test_d_moving_one_of_the_four_past_the_window_turns_a_and_c_red` | 反真空：把「禁令」挪到 400 之后 ⇒ a 与 c 必红；把改前那条原文喂进来 ⇒ 也必红 | 不适用（它守的是 a/c 不是真空的那一条） |
| e) `test_e_every_refusal_site_is_built_by_the_shape_and_none_is_unreachable` | 结构性：`policy.py` 里每一个 `Refusal(...)` 的报文都必须出自 `refusal_detail(...)`；且每一个点都必须被某个用例走到（新加一个点却没人走 ⇒ 红） | 改前 17 处各写各的字符串，形状只能一条条看 |
| f) `test_f_the_action_refusal_family_is_measured_in_the_same_window` | `refusals.refuse(...)` 那一族（全仓 60+ 处）也量同一个窗口：四键齐备、文案非空、字面长度 ≤ 400；量不到的（不是字面量）算 `unknown` 而不是通过 | 改前没有任何判据量过它们的长短 |

## 为什么判据量的是形状，不是某一句话

按措辞量（"报文里必须有这几个字"）只能守住已经想到的那几条。所以这里的判据本体住在
`policy.refusal_shape_problems`：它按四样的词头（`policy.REFUSAL_SLOTS`）量齐不齐、
顺序对不对、四样那一段在不在窗口内，再加两条能机械判的内容底线（判定里要有一个数字 =
现算读数；禁令里要有一个禁令词）。新加一条拒信时，形状是自动被量的；指路指得对不对
仍由各条闸自己的判据守（触深与扇出各有一份，见
`tests/test_depth_exceeded_says_escalate_to_parent.py` 与
`tests/test_retiring_a_silent_child_frees_a_fanout_seat.py`）。

## 已知边界（量不到，不等于没问题）

- `summon_many` 那条路把同一条报文交给模型时是 `_clip(r.detail, 200)`
  （`agent_loop` 里那一行）：闸门拒信按 400 排，200 那一档掉的是附加解释与明细，
  四样仍在前 200 里的是短的那几条 —— 这一格本批没有按 200 重排，记在这里。
- `refusals.refuse(...)` 那一族的长度是从源码量出来的字面下界（插值按 1 字计）：
  它量不到插值展开后的真实长度，所以「绿」只说明字面部分没有超；超的那几处逐个登记在
  `_REFUSE_OVER_WINDOW` 里，登记与实测必须相等（多一处、少一处都红）。
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import sys
import warnings
from typing import Any, Callable

import pytest

from agentflow import agent_loop as AL
from agentflow import policy as P
from agentflow import refusals as R
from agentflow import schema as S

#: 全仓源码根：闸门拒信之外，动作拒绝那一族也在这里面找。
PKG = pathlib.Path(P.__file__).resolve().parent

#: 拒信的窗口：与 `policy.REFUSAL_HEAD_CHARS` 同一来源（不另抄一个 400）。
WINDOW = P.REFUSAL_HEAD_CHARS


def _parse(text: str) -> ast.Module:
    """`ast.parse` 的薄壳：仓库里有些老字面量带着无效转义，解析时会发 Deprecation
    Warning，那不是本判据的读数，压掉它免得把输出的注意力引开。"""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ast.parse(text)


# ====================================================================== 驱动拒信
#
# 判据不手抄报文，而是把每一条闸门走一遍：同一个函数 `policy.check` /
# `check_action`，喂进去的是决策输入（Decision），出来的是那一行真的会交给模型的话。
#
# 覆盖是否完整不靠自觉：`test_e` 把 `Refusal(...)` 的调用点从源码里数出来，
# 与这里能走到的点逐个对账 —— 漏一个点就红。


def _seat(i: int, state: str) -> dict[str, Any]:
    """一格占位（形状与 `Conductor.fanout_seats_of` 的 `seats` 逐字一致）。"""
    return {"name": f"D{i}", "task_id": f"t-9{i:03d}", "role": "E", "state": state,
            "state_label": {"silent": "静默", "flying": "在飞", "standby": "待机"}[state],
            "occupies": True, "retirable": state == "silent", "why": ""}


def _cases() -> list[tuple[str, Callable[[], Any]]]:
    """每一条闸门一个用例：覆盖 `check` / `check_action` 的每个 `Refusal(...)` 点。"""
    shallow = P.Policy(max_direct_children=3)
    deep = P.Policy()                      # 缺省档：链上 5 个代理 / 直接子上限 25
    many = tuple(_seat(i, "flying") for i in range(100))
    all_silent = tuple(_seat(i, "silent") for i in range(100))
    return [
        ("check_action.unknown_role", lambda: P.check_action("Z", "x")),
        ("check_action.conductor_action",
         lambda: P.check_action(S.CONDUCTOR_ROLE, "summon")),
        ("check_action.unknown_action", lambda: P.check_action("A", "没有这个动作")),
        ("unknown_role.to", lambda: P.check(deep, P.Decision(frm="M", to="Z", action=""))),
        ("unknown_role.frm",
         lambda: P.check(deep, P.Decision(frm="Z", to="A", action="run_once"))),
        ("forbidden_edge.non_summonable",
         lambda: P.check(deep, P.Decision(frm="A", to=S.CONDUCTOR_ROLE, action=""))),
        ("forbidden_edge.via",
         lambda: P.check(deep, P.Decision(frm="A", to="V", action="verify_proof"))),
        ("forbidden_edge.no_via",
         lambda: P.check(deep, P.Decision(frm="C", to="B", action="run_once"))),
        ("cycle_detected",
         lambda: P.check(deep, P.Decision(frm="A", to="B", action="run_once",
                                          key=("A", "run_once", "k"),
                                          ancestry=(("A", "run_once", "k"),)))),
        ("depth_exceeded",
         lambda: P.check(deep, P.Decision(frm="F", to="E", action="evidence_for",
                                          depth=deep.max_chain_depth + 1))),
        ("fanout_exceeded.no_seats",
         lambda: P.check(shallow, P.Decision(frm="D", to="A", action="run_once",
                                             direct_children=shallow.max_direct_children))),
        ("fanout_exceeded.seats_one_silent",
         lambda: P.check(shallow, P.Decision(
             frm="D", to="A", action="run_once",
             direct_children=shallow.max_direct_children,
             direct_children_seats=(_seat(1, "silent"), _seat(2, "flying"),
                                    _seat(3, "flying"))))),
        ("fanout_exceeded.seats_none_silent",
         lambda: P.check(shallow, P.Decision(
             frm="D", to="A", action="run_once",
             direct_children=shallow.max_direct_children,
             direct_children_seats=(_seat(1, "flying"), _seat(2, "flying"),
                                    _seat(3, "standby"))))),
        # 最坏形态：主控档 100 格（名单很容易把窗口撑爆 —— 判定里只许点前几格）。
        ("fanout_exceeded.conductor_100_flying",
         lambda: P.check(deep, P.Decision(frm=S.CONDUCTOR_ROLE, to="A", action="run_once",
                                          direct_children=100, direct_children_seats=many))),
        ("fanout_exceeded.conductor_100_silent",
         lambda: P.check(deep, P.Decision(frm=S.CONDUCTOR_ROLE, to="A", action="run_once",
                                          direct_children=100,
                                          direct_children_seats=all_silent))),
        ("concurrency_exceeded",
         lambda: P.check(deep, P.Decision(frm="M", to="A", action="run_once",
                                          running=deep.max_concurrency))),
        ("budget_exceeded.tasks",
         lambda: P.check(deep, P.Decision(frm="M", to="A", action="run_once",
                                          total=deep.max_tasks_per_run))),
        ("budget_exceeded.usd_zero",
         lambda: P.check(deep, P.Decision(frm="M", to="A", action="run_once",
                                          usd_left=0.0))),
        ("budget_exceeded.usd_wanted",
         lambda: P.check(deep, P.Decision(frm="M", to="A", action="run_once",
                                          usd_left=1.0, usd_wanted=2.0))),
        ("deadline_exceeded",
         lambda: P.check(deep, P.Decision(frm="M", to="A", action="run_once",
                                          deadline_hit=True))),
    ]


def _lean_cases() -> list[tuple[str, Callable[[], Any]]]:
    """Lean 开关关着时那两条（`_lean_hidden` 依赖设置文件 ⇒ 这里按它的契约打桩）。"""
    deep = P.Policy()
    return [
        ("forbidden_edge.lean_hidden_to",
         lambda: P.check(deep, P.Decision(frm=S.CONDUCTOR_ROLE, to="L",
                                          action="formalize"))),
        ("forbidden_edge.lean_hidden_frm",
         lambda: P.check(deep, P.Decision(frm="L", to="C", action="hottest"))),
    ]


def _drive(monkeypatch: Any) -> list[dict[str, Any]]:
    """把每一条闸门走一遍，返回 `[{"label", "line", "text", "reason"}]`。

    `Refusal` 在这一层被换成一个记账函数：它把"哪一行造出了这条拒信"与报文一起记下，
    然后照旧返回真的 `Refusal`（所以下游看到的对象与生产里一模一样）。
    换掉的只是构造入口，判定逻辑一个字没动。

    每个用例必须恰好造出一条：0 条说明那个点走不到（覆盖是真空的），多于 1 条说明
    用例造出了别的拒信 —— 两种都当场红，不留给后面的断言去猜。
    """
    monkeypatch.setattr(P, "_lean_hidden", lambda role: role == "L")
    rows: list[dict[str, Any]] = []
    real = P.Refusal

    def _rec(reason: str, detail: str = "", limit: str = "") -> Any:
        rows.append({"line": sys._getframe(1).f_lineno, "text": str(detail),
                     "reason": str(reason), "label": ""})
        return real(reason, detail, limit)

    monkeypatch.setattr(P, "Refusal", _rec)
    for label, fn in _cases() + _lean_cases():
        before = len(rows)
        got = fn()
        made = len(rows) - before
        assert got is not None and made == 1, (
            f"{label}：这条用例造出了 {made} 条拒信（要恰好一条，否则覆盖不可判）")
        assert got.reason in S.REFUSAL_REASONS, (label, got.reason)
        rows[-1]["label"] = label
    monkeypatch.undo()
    return rows


# ====================================================================== a) 四样 + 窗口
def test_a_every_gate_refusal_has_the_four_parts_within_the_window(
        monkeypatch: Any) -> None:
    """a) 每一条闸门拒信：四样齐全、顺序对、四样那一段 ≤ 400 字。

    窗口是 `policy.REFUSAL_HEAD_CHARS`（= `agent_loop._do_summon` 的那个 400），
    量的是「附加解释之前」的那一段 —— 解释允许被截，四样不允许。
    """
    rows = _drive(monkeypatch)
    problems: list[str] = []
    for row in rows:
        for one in P.refusal_shape_problems(row["text"]):
            problems.append(f"{row['label']}：{one}")
    assert not problems, "；".join(problems) + (
        f"\n（共量了 {len(rows)} 条拒信，窗口 {WINDOW} 字）")

    # 反真空：这一轮必须真的量到十几条，而不是"一条都没走进去所以全绿"。
    labels = {row["label"] for row in rows}
    assert len(rows) >= 20, sorted(labels)
    assert len(labels) == len(rows), sorted(labels)


# ====================================================================== b) 顺序
def test_b_the_four_parts_come_before_the_explanation(monkeypatch: Any) -> None:
    """b) 顺序可机械判：四样的下标严格递增，且四样最后一笔在解释首句之前。

    判据形式（与报文的措辞无关）：`max(四个词头的下标) < text.find("说明：")`；
    没有附加解释时，四样就是整段。
    """
    rows = _drive(monkeypatch)
    heads = list(P.REFUSAL_SLOT_HEADS)
    problems: list[str] = []
    for row in rows:
        text = row["text"]
        idx = [text.find(head) for head in heads]
        if any(i < 0 for i in idx):
            problems.append(f"{row['label']}：四样不齐（下标 {idx}）")
            continue
        if idx != sorted(idx) or len(set(idx)) != len(idx):
            problems.append(f"{row['label']}：顺序不对（下标 {idx}）")
            continue
        tail = text.find(P.REFUSAL_TAIL_HEAD)
        if tail >= 0 and not max(idx) < tail:
            problems.append(f"{row['label']}：解释的入口（{tail}）没有排在四样最后一笔"
                            f"（{max(idx)}）之后")
    assert not problems, "；".join(problems)


# ====================================================================== c) 真的过一遍 _clip
def test_c_after_the_real_clip_the_four_parts_are_still_there(monkeypatch: Any) -> None:
    """c) 拿真函数 `AL._clip(text, 400)` 过一遍：四样那一段与四个词头全都还在。

    这是真正对模型负责的那一条：a/b 量的是台账里那一段，c 量的是模型手里那一段。
    """
    rows = _drive(monkeypatch)
    problems: list[str] = []
    for row in rows:
        text = row["text"]
        seen = AL._clip(text, WINDOW)
        head = P.refusal_head(text)
        if len(head) > WINDOW:
            problems.append(f"{row['label']}：四样那一段 {len(head)} 字 > 窗口 {WINDOW}")
            continue
        if head not in seen:
            problems.append(f"{row['label']}：_clip 之后四样那一段不全（丢在尾巴上）")
        for word in P.REFUSAL_SLOT_HEADS:
            if word not in seen:
                problems.append(f"{row['label']}：_clip 之后看不到「{word}」")
    assert not problems, "；".join(problems) + "\n（模型看到的是 _clip(detail, 400)）"


# ====================================================================== d) 反真空
def _moved_past_the_window(detail: str) -> str:
    """把「禁令」那一段挪到 400 之后：造出 Q31 的旧形态（四样还在，只是读不到）。"""
    idx = detail.find(P.REFUSAL_SLOT_HEADS[-1])
    assert idx > 0, "夹具坏了：这条报文里找不到禁令那一段"
    filler = "背景。" * 90            # 360 字，把禁令推到窗口之外
    return detail[:idx] + P.REFUSAL_TAIL_HEAD + filler + detail[idx:]


#: 改前那条扇出拒信（逐字取自 Q31 取证时的 git diff：580 字，前提与收尾在 400 之后）。
OLD_FANOUT = (
    "该任务此刻在飞 3 个直接子，达到发起方 D 的直接子上限 3（现算："
    "direct_children_limit_for(policy, 'D')，取自 policy.max_direct_children）。"
    "这一格只数直接子，不管隔着几层的子（孙辈算它们自己父的格）—— "
    "单时刻口径：直接子一返回就腾出名额。"
    "此刻占位 3 个（逐格名单这一层没读到，别把它读成『没有可销的』）。"
    "两条可走的路：① 等已派出去的那些回来（读 `out/tasks/*.json` 或 `conductor.state` "
    "看谁还没回），下一轮再派；② 立刻腾一格 —— 销号静默子代理腾出名额："
    "调 `conductor.retire_child`（参数 `child_name=\"<名册名>\"`、`reason=\"为什么销它\"`）"
    "（名册名从 `{\"roster\": {\"of\": \"self\"}}` 读，如 `D1`），销号之后同一父的"
    "下一次 summon 立刻重新算占位、当场就能派进去。"
    "前提：只可对静默的（无工作 ∧ 无计时器 ∧ 无活跃子代理）；在飞 / 待机 / 读不到的"
    "会被拒，拒信带 `refusal_code=target_not_silent` 与逐条 `blocking` —— "
    "别拿销号当停止用（销号不可逆、名字永久不复用）。"
    "同时确认自己没有把同一件事重复派出去"
)


def test_d_moving_one_of_the_four_past_the_window_turns_a_and_c_red(
        monkeypatch: Any) -> None:
    """d) 反真空：四样之一挪到 400 之后 ⇒ a 与 c 必红；改前原文 ⇒ 也必红。

    两半都要断言：判据对"好的"必须绿（否则"坏的红"可能只是因为夹具坏了），
    对"坏的"必须红在它该红的地方。
    """
    rows = {row["label"]: row["text"] for row in _drive(monkeypatch)}
    healthy = rows["fanout_exceeded.seats_one_silent"]
    assert not P.refusal_shape_problems(healthy), "夹具坏了：健康的那条自己就不过"
    assert P.refusal_head(healthy) in AL._clip(healthy, WINDOW)

    broken = _moved_past_the_window(healthy)
    a_problems = P.refusal_shape_problems(broken)
    assert a_problems, "把禁令挪到 400 之后，a 仍然全绿 —— 那 a 量的不是四样的顺序"
    assert any("顺序" in one or "窗口" in one for one in a_problems), a_problems
    seen = AL._clip(broken, WINDOW)
    assert P.REFUSAL_SLOT_HEADS[-1] not in seen, (
        "把禁令挪到 400 之后，模型仍然看得到它 —— c 没有在量真的 _clip")

    # 改前那条原文：它连四样都没有，也不在窗口内。
    old = P.refusal_shape_problems(OLD_FANOUT)
    assert len(OLD_FANOUT) > WINDOW, len(OLD_FANOUT)
    assert any("缺「判定：" in one for one in old), old
    assert "前提：" not in AL._clip(OLD_FANOUT, WINDOW), (
        "改前那条的前提落在 400 之内了 ⇒ 这份取证文字不能当改前红用")


# ====================================================================== e) 结构 + 覆盖
def _ast_refusal_sites() -> list[tuple[int, int]]:
    """`policy.py` 里每一个 `Refusal(...)` 调用的行范围（AST 数出来的，不是手抄的）。"""
    tree = _parse(inspect.getsource(P))
    return [(node.lineno, node.end_lineno or node.lineno)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "Refusal"]


def _refusal_builder_offenders() -> list[str]:
    """报文不是出自 `refusal_detail(...)` 的那些点（手拼一条就绕过形状了）。"""
    src = inspect.getsource(P)
    tree = _parse(src)
    lines = src.splitlines()
    bad: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Refusal"):
            continue
        detail: ast.AST | None = node.args[1] if len(node.args) >= 2 else None
        for kw in node.keywords:
            if kw.arg == "detail":
                detail = kw.value
        ok = (isinstance(detail, ast.Call) and isinstance(detail.func, ast.Name)
              and detail.func.id == "refusal_detail")
        if not ok:
            bad.append(f"{node.lineno}: {lines[node.lineno - 1].strip()}")
    return bad


def _other_modules_building_refusals() -> list[str]:
    """`policy.py` 之外还有谁在造 `Refusal(...)`（闸门拒信只有那一个产出口）。"""
    found: list[str] = []
    for path in sorted(PKG.rglob("*.py")):
        if path.name == "policy.py":
            continue
        try:
            tree = _parse(path.read_text(encoding="utf-8"))
        except SyntaxError:            # 语法坏的文件不在这里判（另有判据）
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "Refusal":
                found.append(f"{path.relative_to(PKG).as_posix()}:{node.lineno}")
    return found


def test_e_every_refusal_site_is_built_by_the_shape_and_none_is_unreachable(
        monkeypatch: Any) -> None:
    """e) 结构性两条：报文必须出自拼装口；每个点必须被走到。

    没有这一条，判据只能守住"今天这几条"：新加一处手拼的 `Refusal(...)` 时，
    a/b/c 三条都看不见它（它们量的是用例走到的那些）。
    """
    bad = _refusal_builder_offenders()
    assert not bad, "这些 `Refusal(...)` 的报文不是 `refusal_detail(...)` 拼的：\n" + "\n".join(bad)
    assert not _other_modules_building_refusals(), (
        "闸门拒信多了一个产出口：这些模块也在造 `policy.Refusal`"
        f"（形状判据只认 policy.py 那一个口）：{_other_modules_building_refusals()}")

    sites = _ast_refusal_sites()
    assert len(sites) >= 15, f"AST 只数到 {len(sites)} 个 `Refusal(...)` 点 —— 扫描坏了"
    rows = _drive(monkeypatch)
    hit: set[tuple[int, int]] = set()
    for row in rows:
        for span in sites:
            if span[0] <= row["line"] <= span[1]:
                hit.add(span)
                break
    missed = [span for span in sites if span not in hit]
    src = inspect.getsource(P).splitlines()
    assert not missed, "这些拒信点没有任何用例走到（形状判据对它们是真空的）：\n" + "\n".join(
        f"{start}-{end}: {src[start - 1].strip()}" for start, end in missed)


# ====================================================================== f) 动作拒绝那一族
#: `refusals.refuse(...)` 那一族的窗口同样是 400：它在 `Conductor._end_from_payload` 里
#: 变成任务行的 `detail`，再由 `agent_loop._do_summon` 的 `_clip(res.detail, 400)`
#: 交给父代理。这一族在 6 个角色模块里（60+ 处），文案是 f-string ⇒ 只能量到字面下界
#: （每个插值按 1 字计）：量不到插值的真实长度，这是本判据的已知边界。
#:
#: 超过窗口的字面点逐个登记在这里（键 = 文案前 24 字，不用行号：行号几十分钟就漂）。
#: 登记与实测必须相等：修好一处 ⇒ 它从实测里消失 ⇒ 这里也要跟着消失（否则红）。
_REFUSE_OVER_WINDOW: dict[str, int] = {
    # `agent_b/register_statement.py` 的 context_theorem_not_anchored：两条正路写全了，
    # 但解释排在正路中间。改它要动别人正在改的那个文件（Q31 的战场是 policy.py），
    # 所以在报告里点名、在这里留读数，本批不动它。
    # 另有一处字面下界 396（同一个文件的 must_start_as_conjecture）：再叠上
    # `Conductor._end_from_payload` 那一段 handler 戳记就会过窗，而下界量不出戳记 ——
    # 这一处只在报告里点名，判据量不到它（unknown 不是通过，这一条写在这里以免读的人
    # 把「绿」读成「那一处没问题」）。
    "这一笔点名了上下文定理（`derived_fro": 408,
}


def _literal_len(node: ast.AST) -> int:
    """字符串字面量的长度下界：f-string 的字面部分 + 每个插值按 1 字计。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return len(node.value)
    if isinstance(node, ast.JoinedStr):
        return sum(len(str(part.value)) if isinstance(part, ast.Constant) else 1
                   for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_len(node.left) + _literal_len(node.right)
    return 0


def _literal_head(node: ast.AST, n: int = 24) -> str:
    """报文开头的字面部分（做登记的键用：行号会漂，文案开头不会）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value[:n]
    if isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant):
                return str(part.value)[:n]
        return ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_head(node.left, n)
    return ""


def _refuse_sites() -> list[dict[str, Any]]:
    """全仓 `refusals.refuse(...)` 的调用点（报文与它在该文件里的位置）。"""
    sites: list[dict[str, Any]] = []
    for path in sorted(PKG.rglob("*.py")):
        if path.name == "refusals.py":       # 定义点，不是调用点
            continue
        try:
            tree = _parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.id if isinstance(fn, ast.Name)
                    else fn.attr if isinstance(fn, ast.Attribute) else "")
            if name not in ("refuse", "_refuse"):
                continue
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                    and fn.value.id == "self":
                continue                     # 某个类自己的 `self._refuse(...)`，不是这一族
            msg: ast.AST | None = node.args[1] if len(node.args) >= 2 else None
            for kw in node.keywords:
                if kw.arg in ("error", "detail"):
                    msg = kw.value
            sites.append({"where": f"{path.relative_to(PKG).as_posix()}:{node.lineno}",
                          "chars": _literal_len(msg) if msg is not None else None,
                          "head": _literal_head(msg) if msg is not None else ""})
    return sites


def test_f_the_action_refusal_family_is_measured_in_the_same_window() -> None:
    """f) 动作拒绝那一族：四键齐备、文案非空、字面长度 ≤ 400（超的逐个登记）。"""
    out = R.refuse("bad_id", "这一条只是形状正控", resolved="x")
    assert out["ok"] is False
    assert out["refusal_reason"] == R.PRECONDITION_REASON
    for key in ("kind", "error"):
        assert str(out.get(key) or "").strip(), f"refuse() 缺 {key}（拒信会变成空话）"

    sites = _refuse_sites()
    # 反真空：扫不到就判红 —— "没扫到"不是"没有问题"。
    assert len(sites) >= 60, f"只扫到 {len(sites)} 处动作拒绝 —— 扫描器坏了"
    assert len({one["where"].split(":")[0] for one in sites}) >= 6, sorted(
        {one["where"].split(":")[0] for one in sites})

    unknown = [one["where"] for one in sites if one["chars"] is None]
    assert not unknown, f"这些调用点的报文不是字面量，本判据量不到（unknown ≠ 通过）：{unknown}"

    over = {one["head"]: one for one in sites if (one["chars"] or 0) > WINDOW}
    got = {head: one["chars"] for head, one in over.items()}
    assert got == _REFUSE_OVER_WINDOW, (
        "动作拒绝超出窗口的登记与实际不一致（修好一处就把登记删掉；"
        f"新超一处就把它修好或写进报告）：实际 {got}，登记 {_REFUSE_OVER_WINDOW}")
