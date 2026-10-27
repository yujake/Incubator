# -*- coding: utf-8 -*-
"""业主裁定：父代理必须处理子代理的产出 —— 判据（效应证据口径）与五条读数。
## 真机证据（已核实，本判据的由来）
`projects/mp4/data/tasks.json`：F 的所有任务 `called_by=D`（`t-000006/26/75/83`）。而 D 的派活任务只写"读 C 的报告立猜想"—— D 派完 F、拿到 F 的结果、就 `final` 了；F 的产出只留在台账、由
M 在下一轮读。于是"父拿到了结果却不处理"，整条链的推进责任被真空地转给了最上层。
## 判据口径：效应证据，不是白名单（业主 2026-10 的修正）
在这一次 summon 之后，父只要在任何一步留下可查的效应、且这一步指到了那条子产出（`task_id` / 产物路径 / 台账 id），就算处理了。业主点名的形态只是举例：写台账、改计划、立/改猜想、写报告、再派活、交给 H 审、用它做判断、折进 final ……
"可查的效应"由 `agent_loop._is_effect_evidence` 用负表判：只排除只读侦察（`fs.list` / `status_report` 这类）与 `invalid` 步。于是列举只活在文档里。
## 这一组守什么（红/绿逐条）+ 为什么每条都要有负控
| # | 场景 | 期望 |
|---|---|---|
| ① | 父派子 → 子回结果 → 父读它写的那份报告 | 绿：`unconsumed=0`、`consumed=1` |
| ② | 父派子 → 父写受控的 `not_consumed` | 绿：`waived=1`、`unconsumed=0` |
| ③ | 父派子 → 拿到结果 → 直接 final（无具体产物指涉） | 红：`unconsumed=1` |
| ④ | ③ 的变体：把 `not_consumed` 的理由码换成空串 / 自造码 | 红：`unconsumed=1` + 不成立的理由被念出来 |
| ⑤ | 反真空：没派过子的 run | 不红（`n/a`），但报 `summons_total=0` |
| ⑥ | 反窄化正控：两种"不在原来三条里"的形态（立猜想 / 写报告） | 都必须绿 |
| ⑦ | 反窄化负控：把判据改回"只认那三条"（白名单） | ⑥ 那两条必须红 |
⑥⑦ 是同一批场景的两套判据（真判据 vs 白名单判据）：只有两套读数不同，才能证明判据读的是"效应证据"而不是"它属不属于我列举的那几类"。
"""
from __future__ import annotations

import json
import pathlib
import re
from typing import Any

import pytest

from agentflow import agent_loop as AL
from agentflow import closing as CL
from agentflow import sessions as SS
from agentflow.agent_loop import LlmBackend, run_role
from agentflow.conductor import Conductor, LocalBackend
from agentflow.llmseam import LlmSeam
from agentflow.store import Store
from agentflow.tools import build_registry

SID = "test-run"

#: 父 = D，子 = F —— 与真机证据里那条链同形（`t-000006` 等四条的 `called_by=D`）。
#:  动作一栏是空串：S2 口径之后派活不点动作，`LlmBackend` 对空动作一律走循环
#: （见 `LlmBackend.call` 的第一支），所以这里只需要把两个角色登记成"有人接"。
LOOPS: dict[tuple[str, str], dict[str, Any]] = {("D", ""): {}, ("F", ""): {}}

#: 子代理写出来的产物路径（判据要能在父的后续动作里认出它）。
REPORT = "reports/attack-1.md"

CHILD_SCRIPT: list[str] = [
    json.dumps({"tool": "fs.write",
                "args": {"path": REPORT,
                         "content": "# 攻击路线\n据 C 的报告，主猜想可攻：n=3 的检查已过。\n"},
                "why": "把攻击路线写成报告"}, ensure_ascii=False),
    json.dumps({"final": f"攻击路线写在 {REPORT}：conj-0001 有反例风险，建议父据此改猜想状态。",
                "evidence": []}, ensure_ascii=False),
]

#: 父的观测里那条子任务的编号（`"task_id": "t-000002"`）：模型据它指称子产出。
_TID_IN_PROMPT = re.compile(r'"task_id":\s*"(t-\d{4,8})"')


def _child_tid(prompt: str) -> str:
    """从父自己的观测里读子任务的编号（照替身模型的做法：它看得见就写得出来）。"""
    found = _TID_IN_PROMPT.findall(prompt)
    assert found, ("父的观测里看不见子任务的 `task_id` ⇒ 这条指称它写不出来，"
                   f"演示不了『指到子产出』；提示词尾部：{prompt[-1200:]}")
    return found[-1]


class _Scripted:
    """照剧本回答的替身模型：每条可以是字符串，也可以是 `prompt -> 字符串` 的函数。

    为什么允许函数：有些步必须指到上一步的产物（`task_id`），而它只有模型在
    自己的观测里看得到 —— 真模型是这么做的，替身模型不该被喂一个写死的编号
    （那会变成"测试知道答案"，而判据要证明的是"模型能据此指称"）。
    """

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[Any]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: Any) -> Any:
        self.prompts.append(prompt)
        item = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        text = item(prompt) if callable(item) else str(item)
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 10,
                                  "tokens_out": 10, "error_detail": "",
                                  "error_kind": ""})()


def _parent_summon() -> str:
    return json.dumps({"summon": {"role": "F", "task": "读完 C 的报告，把主猜想的攻击路线写出来",
                                  "why": "这条路线只有 F 能跑"}},
                      ensure_ascii=False)


def _world(tmp_path: pathlib.Path, parent_replies: list[Any],
           *, child_replies: list[Any] | None = None):
    """造一个工作区 + 主控 + 工具层，父 D 与子 F 各有一个替身模型。"""
    st = Store(tmp_path / "ws")
    st.init()
    replies_by_role: dict[str, list[Any]] = {"D": parent_replies,
                                             "F": list(child_replies or CHILD_SCRIPT)}
    gateways = {role: _Scripted(rows) for role, rows in replies_by_role.items()}

    def seam_factory(role: str) -> LlmSeam:
        return LlmSeam(role=role, session_root=st.root, gateway=gateways.get(role),
                       price=(0.0, 0.0), sid=SID)

    backend = LlmBackend(inner=LocalBackend({}), loops=LOOPS, session_root=st.root,
                         seam_factory=seam_factory, max_steps=8, store=st, sid=SID,
                         workspace_root=str(st.root))
    cond = Conductor(st, policy=None, backend=backend)
    backend.conductor = cond
    built = build_registry(store=st, conductor=cond, workspace_root=str(st.root))
    backend.registry = built.registry
    return st, cond, built.registry, gateways


def _parent_run(st, cond, registry, gateways) -> Any:
    seam = LlmSeam(role="D", session_root=st.root, gateway=gateways["D"],
                   price=(0.0, 0.0), sid=SID)
    return run_role("D", "按你的职责把这件事做掉", store=st, registry=registry,
                    conductor=cond, seam=seam, workspace_root=str(st.root),
                    sid=SID, from_env=False, max_steps=8)


def _ends(st) -> list[dict[str, Any]]:
    events, problems = SS.read_session(st.root, sid=SID)
    assert not problems, problems
    return [e for e in events if str(e.get("kind") or "") == "agent_run_end"]


def _line(run: Any) -> str:
    """这条判据在这一趟上的那一行（与收工那一行同一份读数）。"""
    got = run.summon_consumption
    return str(AL.summon_consumption_verdict(got)["line"])


# ============================================================ ① 正控：效应证据（消费）

def test_green_when_the_parent_uses_the_child_output(tmp_path: pathlib.Path):
    """① 正控：父派子 → 子回结果 → 父读子写的那份报告 ⇒ `unconsumed == 0`。"""
    parent = [
        _parent_summon(),
        json.dumps({"tool": "fs.read", "args": {"path": REPORT},
                    "why": "照子代理的路线看一遍再决定"}, ensure_ascii=False),
        json.dumps({"final": "读过攻击路线，结论已收敛", "evidence": []}, ensure_ascii=False),
    ]
    st, cond, registry, gateways = _world(tmp_path, parent)
    run = _parent_run(st, cond, registry, gateways)

    assert run.stop_reason == "final", run.to_dict()
    assert (st.root / REPORT).is_file(), "子代理那份报告没落到盘上（判据就没有指称对象）"
    assert run.summons_total == 1, run.summon_consumption
    assert run.summons_consumed == 1, run.summon_consumption
    assert run.summons_unconsumed == 0, run.summon_consumption
    verdict = AL.summon_consumption_verdict(run.summon_consumption)
    assert verdict["status"] == "green", verdict
    # 证据落在"哪一步、什么效应、指到了哪个字面量"上（不只是"算它处理了"）
    ev = run.summon_consumption["productions"][0]["evidence"]
    # 步号不再写死成 1：它是这一趟的步计数器给的读数，而派活那一回合之后计数器
    # 会为被召唤的一支多走一格（实测：父的 steps 是 0=summon / 2=fs.read / 3=final）。
    # 判据要钉的是"证据指到的就是我读那份报告的那一步"，所以拿那一步自己的 index 比 ——
    # 写死 1 会在任何编号口径变化时假红，而它守的那件事一个字都没变。
    read_step = next(s for s in run.steps if s.result.get("tool") == "fs.read")
    assert ev["step"] == read_step.index, (ev, read_step.index)
    assert ev["shape"] == "tool", ev
    assert REPORT in ev["refs"], ev
    # 收工那一行（`agent_run_end`）读得到这四个数
    end = [e for e in _ends(st) if str(e.get("role")) == "D"][-1]
    assert int(end["summon_consumption"]["summons_unconsumed"]) == 0, end["summon_consumption"]
    assert any("summons_total=1" in str(n) for n in (end.get("notes") or [])), end["notes"]


# ============================================================ ② 正控：waiver 通路

def test_green_through_the_waiver_channel(tmp_path: pathlib.Path):
    """② 正控：父显式写 `not_consumed`（受控码 + 一句话）⇒ `waived == 1`、不红。"""
    def closing_with_waiver(prompt: str) -> str:
        return json.dumps({"final": "这条子产出的结论被更早的一条覆盖了，不再采用",
                           "evidence": [],
                           "not_consumed": [{"task_id": _child_tid(prompt),
                                             "code": "superseded",
                                             "why": "同一条路线 F 在上一轮已经给过结论"}]},
                          ensure_ascii=False)

    st, cond, registry, gateways = _world(tmp_path, [_parent_summon(), closing_with_waiver])
    run = _parent_run(st, cond, registry, gateways)

    assert run.summons_total == 1, run.summon_consumption
    assert run.summons_waived == 1, run.summon_consumption
    assert run.summons_consumed == 0, run.summon_consumption
    assert run.summons_unconsumed == 0, run.summon_consumption
    assert AL.summon_consumption_verdict(run.summon_consumption)["status"] == "green"
    assert not run.summon_consumption["waiver_problems"], run.summon_consumption
    # final 里那一格进了落档的收工载荷（`not_consumed` 不许只活在内存里）
    assert str(run.final_payload.get("not_consumed") or "").strip(), run.final_payload


# ============================================================ ③ 负控：直接 final

def test_negative_the_parent_finals_right_after_the_result(tmp_path: pathlib.Path):
    """③ 负控（最要紧）：父派子 → 拿到结果 → 直接 final（没有具体产物指涉）⇒ 红。

    这就是真机里 D 的形态：把结果拿到手，然后收工。判据必须在这一格上红，
    否则"父必须处理子产出"这句话在读数上什么都不约束。
    """
    parent = [
        _parent_summon(),
        # 只说到"F 交给了什么"，没有任何 `task_id` / 产物路径 / 台账 id ——
        # 那正是业主说的"final 里没有具体产物指涉"。
        json.dumps({"final": "F 已经把攻击路线交上来了，收工。", "evidence": []},
                   ensure_ascii=False),
    ]
    st, cond, registry, gateways = _world(tmp_path, parent)
    run = _parent_run(st, cond, registry, gateways)

    assert run.summons_total == 1, run.summon_consumption
    assert run.summons_unconsumed == 1, run.summon_consumption
    assert run.summons_consumed == 0 and run.summons_waived == 0, run.summon_consumption
    verdict = AL.summon_consumption_verdict(run.summon_consumption)
    assert verdict["status"] == "red", verdict
    # 红的那一行必须说得清：是哪一条、为什么红
    assert f"unconsumed=1" in verdict["line"], verdict["line"]
    assert "没有处理" in verdict["why"], verdict


def test_the_criterion_shows_a_red_line_and_a_green_line(tmp_path: pathlib.Path):
    """红/绿两行可演示（业主点名要的形式）：同一份判据，两趟运行各打一行。

    红行来自"派了子就收工"，绿行来自"读了子代理的报告再收工" —— 两行都是
    `summon_consumption_verdict()` 现算的，不是手写的文案。
    """
    red_parent = [_parent_summon(),
                  json.dumps({"final": "F 已经交上来了，收工。", "evidence": []},
                             ensure_ascii=False)]
    st, cond, registry, gateways = _world(tmp_path / "red", red_parent)
    red = _parent_run(st, cond, registry, gateways)

    green_parent = [_parent_summon(),
                    json.dumps({"tool": "fs.read", "args": {"path": REPORT},
                                "why": "照子代理的路线看一遍再决定"}, ensure_ascii=False),
                    json.dumps({"final": "读过攻击路线了", "evidence": []},
                               ensure_ascii=False)]
    st2, cond2, registry2, gateways2 = _world(tmp_path / "green", green_parent)
    green = _parent_run(st2, cond2, registry2, gateways2)

    red_line, green_line = _line(red), _line(green)
    print(red_line)
    print(green_line)
    assert "RED" in red_line and "unconsumed=1" in red_line, red_line
    assert "GREEN" in green_line and "unconsumed=0" in green_line, green_line


# ============================================================ ④ 负控：受控理由码

@pytest.mark.parametrize("code,label", [("", "空串"), ("because_i_said_so", "自造码")])
def test_negative_a_bad_waiver_code_does_not_waive(tmp_path: pathlib.Path, code: str,
                                                   label: str):
    """④ 负控：`not_consumed` 的理由码是空串 / 自造码 ⇒ 不算 waive，判据红。

    为什么必须逐条造红：理由码是这条通路唯一的闸门。它一放宽，"我不处理它"
    就退化成一句自我声明 —— 而声明写得漂亮与真的处理过，在读数上会变成同一件事。
    """
    def closing_with_bad_code(prompt: str) -> str:
        return json.dumps({"final": "我就不处理这条子产出了",
                           "evidence": [],
                           "not_consumed": [{"task_id": _child_tid(prompt),
                                             "code": code,
                                             "why": "一句话理由：先放着"}]},
                          ensure_ascii=False)

    st, cond, registry, gateways = _world(tmp_path, [_parent_summon(), closing_with_bad_code])
    run = _parent_run(st, cond, registry, gateways)

    assert run.summons_waived == 0, (label, run.summon_consumption)
    assert run.summons_unconsumed == 1, (label, run.summon_consumption)
    verdict = AL.summon_consumption_verdict(run.summon_consumption)
    assert verdict["status"] == "red", (label, verdict)
    problems = " ".join(run.summon_consumption["waiver_problems"])
    assert "受控表" in problems, (label, problems)   # 不成立的声明必须被念出来，不许静默丢
    # 收工那一行也念到了它（"我写了拒绝说明但框架不认"必须看得见）
    end = [e for e in _ends(st) if str(e.get("role")) == "D"][-1]
    assert any("不成立的拒绝说明" in str(n) for n in (end.get("notes") or [])), \
        end.get("notes")


# ============================================================ ⑤ 反真空：没有对象

def test_n_a_when_the_run_never_summoned_anything(tmp_path: pathlib.Path):
    """⑤ 反真空：`summons_total == 0` 的 run ⇒ 判据不红（它没有对象），但要报 0。

    没有这一条，"这一趟没派过子"与"派了没处理"会共用同一个读数 —— 反真空要的
    正好是把它俩分开：前者 `n/a`、后者 `red`，而两者都不许被折成"通过"。
    """
    parent = [json.dumps({"final": "这一趟自己干完了，没有派子", "evidence": []},
                         ensure_ascii=False)]
    st, cond, registry, gateways = _world(tmp_path, parent)
    run = _parent_run(st, cond, registry, gateways)

    assert run.summons_total == 0, run.summon_consumption
    assert run.summons_unconsumed == 0, run.summon_consumption
    verdict = AL.summon_consumption_verdict(run.summon_consumption)
    assert verdict["status"] == "n/a", verdict
    assert "summons_total=0" in verdict["line"], verdict["line"]
    # 收工那一行也报了 0（"没派过"不是"不用报"）
    end = [e for e in _ends(st) if str(e.get("role")) == "D"][-1]
    assert int(end["summon_consumption"]["summons_total"]) == 0, end["summon_consumption"]
    assert any("summons_total=0" in str(n) for n in (end.get("notes") or [])), end["notes"]


# ================================================== ⑥⑦ 反窄化：不是白名单

def _form_a_replies() -> list[Any]:
    """形态 A：立一条猜想（业主点名的"立/改猜想"），statement 里指到子产物。"""
    def register(prompt: str) -> str:
        tid = _child_tid(prompt)
        return json.dumps({"tool": "conjecture.register_conjecture",
                           "args": {"statement": "在 n≥3 的随机图模型下，投影度量的二阶项"
                                                 f"由 {REPORT} 给出的下界成立",
                                    "origin": f"D 据 F 的产出（{REPORT} / {tid}）立的一条猜想",
                                    "notes": f"来源任务 {tid}"},
                           "why": "据子产出立一条可检验的猜想"}, ensure_ascii=False)
    return [_parent_summon(), register,
            json.dumps({"final": "已据 F 的路线立了一条猜想", "evidence": []},
                       ensure_ascii=False)]


def _form_b_replies() -> list[Any]:
    """形态 B：写报告（`fs.write`），正文里指到子产物。"""
    def write(prompt: str) -> str:
        tid = _child_tid(prompt)
        return json.dumps({"tool": "fs.write",
                           "args": {"path": "reports/verdict.md",
                                    "content": f"# 裁决\n据 F 的 {REPORT}（{tid}）：可攻。\n"},
                           "why": "把子产出的读数写进自己的报告"}, ensure_ascii=False)
    return [_parent_summon(), write,
            json.dumps({"final": "裁决报告已写", "evidence": []}, ensure_ascii=False)]


@pytest.mark.parametrize("builder,label,effect_tool", [
    (_form_a_replies, "立猜想（conjecture.register_conjecture）", "conjecture.register_conjecture"),
    (_form_b_replies, "写报告（fs.write）", "fs.write"),
])
def test_green_for_forms_outside_the_three_routes(tmp_path: pathlib.Path, builder,
                                                  label: str, effect_tool: str):
    """⑥ 反窄化正控：两种"不在原来三条里"的合法处理形态 ⇒ 都必须绿。

    原来那三条（消费 / 拒绝并说明 / 继续派）是举例。这一条证明判据认的是
    "效应证据"：`conjecture.register_conjecture` 与 `fs.write` 都不属于"读产物/再派活"，
    但它们留下了指到子产出的效应。
    """
    st, cond, registry, gateways = _world(tmp_path, builder())
    run = _parent_run(st, cond, registry, gateways)

    assert run.summons_unconsumed == 0, (label, run.summon_consumption)
    assert run.summons_consumed == 1, (label, run.summon_consumption)
    ev = run.summon_consumption["productions"][0]["evidence"]
    assert ev["shape"] == "tool" and effect_tool in ev["effect"], (label, ev)
    assert AL.summon_consumption_verdict(run.summon_consumption)["status"] == "green", label


def _whitelist_effect(shape: str, payload: Any) -> bool:
    """"只认那三条"的白名单版判据（负控专用，不进生产代码）。

    它只认两条通路：① 读产物（`fs.read`）算消费；② 再派活（summon）算继续派。
    ③ waiver 由 `_waiver_declarations` 独立判，这里不涉及 —— 于是两种"不在三条里"
    的形态（立猜想 / 写报告）在这个白名单下必然红。这正是拐杖要证明的事：
    判据不是白名单。
    """
    if shape in ("summon", "summon_many"):
        return True
    return shape == "tool" and str(payload.get("name") or "") == "fs.read"


@pytest.mark.parametrize("builder,label", [
    (_form_a_replies, "立猜想"),
    (_form_b_replies, "写报告"),
])
def test_negative_a_whitelist_criterion_would_turn_those_two_red(
        tmp_path: pathlib.Path, builder, label: str, monkeypatch):
    """⑦ 反窄化负控：把判据改回"只认那三条" ⇒ ⑥ 那两条必须红。

    注入点是 `_is_effect_evidence`（判"这一步算不算效应"的唯一谓词）：
    换成白名单版之后，同样两趟运行必须红。若这里仍然绿，说明判据里还藏着
    别的"不看谓词也放行"的旁路 —— 那才是真正的窄化。
    """
    monkeypatch.setattr(AL, "_is_effect_evidence", _whitelist_effect, raising=True)
    st, cond, registry, gateways = _world(tmp_path, builder())
    run = _parent_run(st, cond, registry, gateways)

    assert run.summons_unconsumed == 1, (label, run.summon_consumption)
    assert AL.summon_consumption_verdict(run.summon_consumption)["status"] == "red", label


# ================================================== 落点：批量与手稿（三种形状各一条）

def test_a_batch_lands_one_reading_per_target_and_drops_refusals():
    """`summon_many`：每个 target 各一条产出读数；被拒的那一项不进 `summons_total`。

    为什么单钉这一条：批量结果是"一次调用、多个子任务"，如果只记第一条（或只记
    整批一条），"这一批里哪一条没被处理"在读数上就消失了 —— 而真机里 D 派 F 的
    四行（`t-000006/26/75/83`）正是分批派出去的。
    """
    res = {"ok": True, "results": [
        {"role": "F", "task_id": "t-000010", "status": "done", "outcome": "ok"},
        {"role": "F", "task_id": "t-000011", "status": "failed", "outcome": "refused"},
        {"role": "F", "task_id": "t-000012", "status": "done", "outcome": "ok"},
    ]}
    items = AL._call_productions("summon_many", {}, res, step=3)
    assert [i["task_id"] for i in items] == ["t-000010", "t-000012"], items
    assert all(i["counted"] and i["kind"] == "summon" for i in items), items
    # 批量结果里没有逐项 `final`/路径 ⇒ 指称只有 `task_id`（业主逐字允许的那一类）
    assert items[0]["outputs"] == ["t-000010"], items[0]


def test_a_handoff_lands_in_productions_but_is_not_counted():
    """`handoff`：记一条（业主点名要含它），但 `counted=False` —— 不进 `summons_*`。

    为什么不计：手稿是对等通道（写给同伴/M 的一份交接），没有 `task_id`、
    也没有"子结果"可以消费；把它算成"下级产出"会让 `summons_total` 混进一类
    根本没有"处理"这个问题的东西。它进 `productions` 只是让"这次调用产生了什么"
    在一处读得到。
    """
    items = AL._call_productions("handoff", {"to": "F"},
                                 {"handoff": "0007", "ok": True, "id": "0007"}, step=2)
    assert len(items) == 1, items
    assert items[0]["counted"] is False and items[0]["handoff_id"] == "0007", items[0]
    assert items[0]["task_id"] == "", items[0]
    run = AL.LoopRun(role="D", task="x")
    run.productions = items
    got = AL.summon_consumption(run)
    assert got["summons_total"] == 0, got
    assert AL.summon_consumption_verdict(got)["status"] == "n/a", got


# ================================================== 收工门那一格：可见但不拦门

def test_the_closing_gate_reads_the_reading_without_failing(tmp_path: pathlib.Path):
    """收工门那一格：`summons_unconsumed > 0` 时读得到，但它不拦门（warning，不 fail）。

    业主逐字：「`summons_unconsumed > 0` 时收工门的相应格要能读到（不一定 fail，
    但必须可见）」⇒ 这一格落 `readings["summon_consumption"]` + 一条 `warning`：
    `machine_pass` 只看 `blocker`，所以门的强度一点没变，而"没处理"再也不会
    从收工门的输出里消失。
    """
    parent = [_parent_summon(),
              json.dumps({"final": "F 已经交上来了，收工。", "evidence": []},
                         ensure_ascii=False)]
    st, cond, registry, gateways = _world(tmp_path, parent)
    _parent_run(st, cond, registry, gateways)

    got = CL.summon_consumption_reading(st.root, sid=SID)
    assert got["checked"], got
    assert got["summons_total"] == 1 and got["summons_unconsumed"] == 1, got
    assert [x["task_id"] for x in got["unconsumed"]], got["unconsumed"]

    rep = CL.check_closing(st, session_root=st.root, sid=SID, checks=())
    assert int(rep.summon_consumption["summons_unconsumed"]) == 1, rep.to_dict()
    warns = [f for f in rep.findings if f.code == "child_output_not_processed"]
    assert warns and warns[0].level == "warning", [f.to_dict() for f in rep.findings]
    assert not rep.blockers, "这一格不许拦门（业主：不一定要 fail）"
    assert "子产出没处理" in rep.summary(), rep.summary()


def test_the_closing_gate_says_unknown_for_an_old_session(tmp_path: pathlib.Path):
    """三态：老会话（没有任何一趟报过这一格）⇒ `checked=False`，不是 0。

    把"没有这一格"折成 0 等于给老工作区发一张"全都处理过"的假绿 ——
    这正是本仓反复登记的那条形态（"没查成"与"查过了没问题"必须分得开）。
    """
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_end", "role": "D", "stop_reason": "final"}, sid=SID)

    got = CL.summon_consumption_reading(root, sid=SID)
    assert got["checked"] is False, got
    assert "没有任何一趟" in got["reason"], got["reason"]
    assert got["summons_total"] == 0, got
