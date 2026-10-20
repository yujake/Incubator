# -*- coding: utf-8 -*-
"""F 与 E 的接缝：`--experiment-reasoning` ＋ 以「玩具例子」验收这条接线。

## 业主口径（这一批的验收词）

**玩具例子** = 在一个小到能手工核对的情形上，把断言跑成**可复现的读数** ——
一条最小脚本 ＋ 一次真实执行 ＋ 一个读得出的数（例如某个量在 `N <= 8` 的档位上与
预期相符/不符）。它**不是**"再跑一遍原脚本"，也**不是**"把界从 n≤8 推到 n≤12"那种
扫描清单（后者留下的是"扫到哪儿"，前者要的是"这一个数对不对"）。

## 根因（真机读数，`projects/mp4/data/attack_plans.json` 计划 000003 的 r1/r2）

每一轮逐字都是 `no_change`：

    子目标 sg1 有判据但没有脚本，而 E 没能把它写出来（no_seam）⇒ 未推进
    （没有脚本就没有实验可跑；这不是"跑了但没结果"）

而 E 的缝从来没接过：`--attack-reasoning` 只给 F 接、`--semantic-review` 只给 H 接。
两个入口（`host.wired_llm_conductor` 的 `role_llm` 与 `llmseam` 的按角色表）都没登记过
`"E"` ⇒ `AgentE.llm is None` ⇒ `author_script` 受控拒绝 `no_seam` ⇒ F 永远卡在
"有判据没脚本"。

## 这一组判据（四条，含两处负控）

| # | 判的是 | 位置 |
|---|---|---|
| ① 正控 | 缝接上 ⇒ F 建计划 → 子目标带 `testable` → E 用缝写脚本 → 脚本真跑 → `experiments` 落一行，`method`/`exit_code`/`result`/`evidence_kind` 与玩具例子标记都对 | `test_positive_control_*` |
| ② 负控 | 同样的输入、缝关着 ⇒ E 报 `no_seam`、F 那一轮落 `dead_end` 并上报 `missing_input`（**不是**静默 `no_change`），读数里看得出缺的是缝 | `test_negative_control_*`（另含"没有主控 ⇒ 不假装上报过"） |
| ③ 反真空 | 玩具例子**真被执行过**：脚本文件在盘上 + 执行结果行在 + 两者 sha256/路径对得上 | `_assert_toy_chain`（① 与 ④ 共用同一把尺子） |
| ④ 第二负控 | 缝接上但模型回**空脚本** ⇒ 有缝但没产出，不许当成功；同一把尺子必须红 | `test_second_negative_control_*` |

另有一条"把 ① 的形态改回静默 `no_change` ⇒ 判据红"的反向判据
（`test_the_criterion_turns_red_*`）：它用 `monkeypatch` 把这一轮换回**改前那个返回值**
（逐字），然后要求同一把尺子报红 —— 否则"判据能红"这句话本身没法被检验。

## 离线

桩一律在测试里：`_StubSeam.complete(prompt)` 返回写死的 JSON（F 的判据 / E 的脚本），
一次真模型都不调、一分钱都不花。判据不由模型决定。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentflow import host
from agentflow import llmseam
from agentflow import schema as S
from agentflow import sessions as SS
from agentflow.agent_e.run_experiment import TOY_EXAMPLE_KEY, TOY_EXAMPLE_MAX_N
from agentflow.agent_f import AgentF
from agentflow.store import Store
from agentflow.tools import verify_tools as VT
from agentflow.tools.conductor_tools import reset_cache

# ---------------------------------------------------------------- 桩（一律在测试里）

#: 一份**玩具例子**脚本：n <= 6 的错排数 D(n) 逐项枚举，再与手算表对比。
#:
#: 为什么它是玩具例子（而不是"扫描清单"）：`D(1..6) = [0, 1, 2, 9, 44, 265]` 这六个
#: 数一个人拿纸就能核；脚本给出的读数 `D(6)=265` 是**一个可以手算核对的数**，
#: 不是"我把界推到 12 了"。规模 `n=6 <= 8`（`TOY_EXAMPLE_MAX_N`）。
TOY_SCRIPT = (
    "import itertools\n"
    "import json\n"
    "\n"
    "# 手算表（外部给定，不由本脚本推出）：错排数 D(1..6)\n"
    "EXPECT = {1: 0, 2: 1, 3: 2, 4: 9, 5: 44, 6: 265}\n"
    "N = 6\n"
    "\n"
    "\n"
    "def derangements(n):\n"
    "    return sum(1 for p in itertools.permutations(range(n))\n"
    "               if all(p[i] != i for i in range(n)))\n"
    "\n"
    "\n"
    "got = {n: derangements(n) for n in range(1, N + 1)}\n"
    "ok = all(got[n] == EXPECT[n] for n in got)\n"
    "print('REPRO_RESULT: ' + json.dumps({\n"
    "    'result': 'supports' if ok else 'refutes',\n"
    "    'observations': {'n': N, 'D': got[N], 'expect_D6': EXPECT[N], 'matched': ok},\n"
    "    'counterexample': None if ok else {'n': N, 'why': 'D(6) 与手算表不符'},\n"
    "    'negation_kind': 'not_proved',\n"
    "    'bound': {'n': N},\n"
    "    'strategy': 'brute force',\n"
    "    'scaling': [{'n': N, 'sec': 0.01, 'objects': 720}],\n"
    "}))\n"
)

#: 子目标带上来的「这是一个玩具例子」声明（F 原样带进 `run_experiment(params=…)`）。
TOY_PARAMS = {"toy_example": {"n": 6, "expect": 265, "quantity": "D(6)"}}

#: F 的缝这一轮要交的产物：一次 `counterexample_request`（判据三件套）。
#:
#: 它走的是 `_spec_from_testable`（子目标只有 `testable` 时由 F 把那一句变成判据）——
#: 于是这条正控覆盖的是**整条链**：`testable` → 判据 → 脚本 → 实验行。
F_ROUND = json.dumps({
    "product": "counterexample_request",
    "strategy": "小情形搜索找模式",
    "why_strategy": "n<=6 的错排数可以手算核对：先在这个玩具例子上把断言跑成读数",
    "script_spec": {
        "criterion": "对 n<=6，枚举出的错排数 D(n) 与手算表 [0,1,2,9,44,265] 逐项相等",
        "params": "n=1..6，逐项枚举全排列",
        "expected_bound": "D(6)=265",
    },
    "why_it_decides": "手算表是外部给定的：逐项相等就能判这条断言在这个小情形上成不成立",
}, ensure_ascii=False)


class _StubSeam:
    """最小模型缝（`judge.judge_json` 的调用约定：`complete(prompt) -> str`）。

    记下每次提问（判据要能断言"提示词里真的念了判据"），回复由剧本给；
    剧本用尽时**炸**（多问一次都不许静默通过）。
    """

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(str(prompt))
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


class _NoCall:
    """没被接线的角色的缝替身：谁调它谁红（"这一趟不该问它"本身就是判据）。"""

    def __init__(self, role: str) -> None:
        self.role = role
        self.calls = 0

    def complete(self, prompt: str) -> str:  # pragma: no cover - 只在接线错了时走到
        self.calls += 1
        raise AssertionError(f"角色 {self.role} 的缝被调用了 —— 这一趟它不该被接线")


@pytest.fixture(autouse=True)
def _no_model_key(monkeypatch: pytest.MonkeyPatch):
    """把模型 key 清掉：这一组判的是**开关**，不是"这台机器上有没有 key"。"""
    monkeypatch.delenv("AGENTFLOW_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("AGENTFLOW_MODEL_BASE_URL", raising=False)


def _store(tmp_path: Path, name: str = "ws") -> Store:
    st = Store(tmp_path / name)
    st.init()
    return st


def _wiring(st: Store, *, experiment_reasoning: bool, attack_reasoning: bool = True,
            e_stub=None, f_stub=None, sid: str = "toy"):
    """装配一个接了线的会话（`run-agent` 那条路的最小形状）。"""
    seams = {"F": f_stub, "E": e_stub}
    reset_cache()

    def factory(role: str):
        return seams.get(role) or _NoCall(role)

    return host.wired_llm_conductor(
        st, session_root=st.root, sid=sid, max_steps=3,
        workspace_root=str(st.root), seam_factory=factory, providers=None,
        attack_reasoning=attack_reasoning, experiment_reasoning=experiment_reasoning)


def _f_of(wiring) -> AgentF:
    """从接了线的主控里取 F 那个实例（走 `_Builder` 的同一份装配，不另建一个）。"""
    return wiring["conductor"].backend.resolve("F")


def _toy_plan(f: AgentF, *, key: str = "PK-TOY") -> str:
    """建一张只有一个 E 子目标的计划（子目标带 `testable` 与玩具例子声明）。"""
    return f.create_plan(
        "难题：错排数在 n<=6 上与手算表是否逐项相等", key,
        subgoals=[{
            "sid": "s1",
            "text": "用错排数的小情形判这条断言",
            "owner": "E",
            "testable": "对 n<=6，枚举出的 D(n) 与手算表 [0,1,2,9,44,265] 逐项相等",
            "params": dict(TOY_PARAMS),
        }])["plan_id"]


def _codes_on_disk(root: Path) -> list[str]:
    """工作区 `code/` 下的脚本（没有就空列表）。"""
    d = Path(root) / "code"
    return sorted(p.name for p in d.glob("*.py")) if d.is_dir() else []


# ---------------------------------------------------------------- ① ③：正控 + 反真空

def _assert_toy_chain(store: Store, *, expect_d6: int = 265) -> dict:
    """玩具例子那条链的判据（①③ 的尺子；④ 与"改回静默"那两条负控也用它判红）。

    它断言的是**链路和读数**，不是"表里有一行"：脚本在盘上且 sha256 对得上、
    执行结果行在、玩具例子那一格成形且规模够小、那个数与预期相符。
    少任何一条，这条链就只是"写了一份脚本"或"跑了一次没读数"。
    """
    rows = list(store.rows("experiments"))
    assert len(rows) == 1, f"玩具例子应当只落一行 experiments，实得 {len(rows)} 行"
    row = dict(rows[0])
    # ---- ③ 反真空：脚本文件存在 ＋ 执行结果行存在 ＋ sha256/路径对得上
    path = Path(store.root) / str(row.get("code_path") or "")
    assert str(row.get("code_path") or ""), f"行上没有 code_path：{row}"
    assert path.is_file(), f"脚本不在盘上：{path}"
    assert VT.code_hash(path) == row.get("code_hash"), (
        f"盘上那份脚本与行上的 code_hash 不是同一份：{path}")
    logs = [Path(store.root) / str(p) for p in (row.get("artifact_paths") or [])]
    assert logs and logs[0].is_file(), f"没有执行结果文件（只写了脚本？）：{logs}"
    text = logs[0].read_text(encoding="utf-8")
    assert "exit_code=0" in text, f"执行结果文件里没有退出码：{text[:400]}"
    assert "REPRO_RESULT" in text, f"执行结果文件里没有结论行（脚本没真跑）：{text[:400]}"
    # ---- ① 行上的四个字段
    assert row["method"] == "numeric", row
    assert row["exit_code"] == 0, row
    assert row["result"] == "supports", row
    assert row["evidence_kind"] == "cross_check", row  # 数值支持不是证明（FC-22）
    assert row["negation_kind"] == "not_proved", row
    # ---- ① 玩具例子标记（落点：`observations["toy_example"]`）
    obs = dict(row.get("observations") or {})
    toy = obs.get(TOY_EXAMPLE_KEY)
    assert isinstance(toy, dict), f"行上没有玩具例子标记：{obs}"
    assert toy.get("checked") is True, toy
    assert toy.get("within_limit") is True, toy
    assert toy.get("n") == 6 and toy.get("limit") == TOY_EXAMPLE_MAX_N, toy
    assert toy.get("executed") is True and toy.get("exit_code") == 0, toy
    assert toy.get("script_path") == row["code_path"], toy
    assert toy.get("script_sha256") == row["code_hash"], toy
    assert (row.get("params") or {}).get(TOY_EXAMPLE_KEY), (
        f"调用方的玩具例子声明没进 params：{row.get('params')}")
    # ---- 那个数：与手算相符
    assert obs.get("D") == expect_d6, f"读数里的 D(6) 与手算不符：{obs}"
    return row


def test_positive_control_e_writes_the_toy_script_runs_it_and_the_row_is_readable(
        tmp_path: Path):
    """① 正控：缝接上之后，「testable → 判据 → 脚本 → 真跑 → 实验行」整条通。

    若这条破了：F 又落回 `no_change`，`experiments` 一行都没有 —— 那正是真机
    `projects/mp4` 计划 000003 的形态（有判据没脚本，永远差一步）。
    """
    st = _store(tmp_path)
    e_stub = _StubSeam(json.dumps({"source": TOY_SCRIPT,
                                   "why": "枚举 n<=6 的错排数，与手算表逐项对比"}))
    f_stub = _StubSeam(F_ROUND)
    wiring = _wiring(st, experiment_reasoning=True, e_stub=e_stub, f_stub=f_stub)

    # ---- 缝真的到了 E 手上（两条路都要接：角色工厂 + `llmseam` 的按角色表）
    f = _f_of(wiring)
    assert f.llm is f_stub, "F 的缝没接上（这一条是正控的前置）"
    assert f.e.llm is e_stub, "角色工厂那条路上 E 没拿到缝"
    assert llmseam.role_seam("E") is e_stub, "工具路径（`attack.step`）上 E 没拿到缝"

    pid = _toy_plan(f)
    out = f.step(pid)

    assert out["action"] == "run_experiment", out
    assert out["outcome"] == "progress", out
    # 两个缝各被问了一次：F 造判据、E 写脚本（多问就是不正常，少问就是没走到）
    assert f_stub.calls == 1, f_stub.prompts
    assert e_stub.calls == 1, e_stub.prompts
    assert "错排数" in e_stub.prompts[0], "写脚本的提示词里没念判据"
    assert "D(6)=265" in e_stub.prompts[0], e_stub.prompts[0]

    # ---- ③：链在盘上、读数在行上
    _assert_toy_chain(st)
    # 子目标把脚本落点与实验号写回去了（下一轮复核时知道跑的是哪一份）
    sg = next(s for s in st.rows("attack_plans")[0]["subgoals"] if s["sid"] == "s1")
    assert sg["script_path"] == "code/attack_s1.py", sg
    assert sg["experiment_ids"], sg
    assert sg["status"] == "supported_not_proved", sg  # 数值支持不许关子目标（FC-22）


# ---------------------------------------------------------------- ② 负控：缝关着

def _missing_seam_reading(store: Store, out: dict) -> dict:
    """把「缝关着那一轮」抽成一份可判的形态（② 与"改回静默"负控共用同一份读法）。

    只读台账与返回值里**已经有**的东西，不另造读数：
    `out["reason"]`（= 这一轮的 detail）、`attack_plans.history` 的最后一条、
    子目标的 `blocked_reason` / `status`、以及"盘上有没有脚本/实验行"。
    """
    plan_rows = list(store.rows("attack_plans"))
    assert plan_rows, "没有攻坚计划"
    plan = dict(plan_rows[-1])
    rec = dict((plan.get("history") or [])[-1])
    sg = next(s for s in (plan.get("subgoals") or []) if s["sid"] == "s1")
    detail = str(out.get("reason") or "")
    blocked = str(sg.get("blocked_reason") or "")
    product = rec.get("product_detail") or {}
    return {
        "action": out.get("action"),
        "outcome": out.get("outcome"),
        # 「静默」的定义：这一轮**没有产物**（改前那个形态）
        "silent": not rec.get("product") and not product,
        "dead_end": rec.get("product") == "dead_end",
        "dead_end_reason": rec.get("dead_end_reason"),
        "mentions_seam": ("no_seam" in detail) or ("no_seam" in blocked),
        "names_the_missing_switch": ("experiment-reasoning" in detail),
        "blocked": str(sg.get("status") or "") == "blocked",
        "experiments": len(store.rows("experiments")),
        "scripts": _codes_on_disk(store.root),
        "detail": detail,
    }


def _assert_missing_seam_is_loud(reading: dict) -> None:
    """② 的尺子：缝关着时那一轮必须是**说得清**的失败，而不是静默 `no_change`。

    三条缺一不可：① 有产物且是 `dead_end`（受控理由 `缺工具`）；② 读数里点名
    `no_seam`；③ 说出缺的那个开关（`--experiment-reasoning`）—— 只说"未推进"的
    读数在下一轮会被同样地猜一遍。
    """
    assert reading["silent"] is False, f"缝关着时那一轮又回到静默 no_change 了：{reading}"
    assert reading["dead_end"] is True, f"那一轮没有落 dead_end：{reading}"
    assert reading["dead_end_reason"] == AgentF.SEAM_MISSING_REASON, reading
    assert reading["mentions_seam"] is True, f"读数里看不出缺的是 `no_seam`：{reading}"
    assert reading["names_the_missing_switch"] is True, (
        f"读数里没点名要打开的那个开关：{reading}")
    assert reading["blocked"] is True, f"子目标没有标 blocked（会静默重试）：{reading}"
    assert reading["experiments"] == 0 and not reading["scripts"], (
        f"缝关着的时候不许有脚本或实验行：{reading}")


def test_negative_control_without_the_seam_f_lays_a_dead_end_and_escalates(tmp_path: Path):
    """② 负控：同样的输入、缝关着 ⇒ `no_seam` ＋ 落 `dead_end` ＋ 上报 `missing_input`。

    两个方向都钉：
    - 只开 `--attack-reasoning` 时 E 仍然没有缝（**F 的开关不连带打开 E 的缝**）；
    - 那一轮不是静默 `no_change`，而是 `dead_end(缺工具)` 且把"缺 E 的缝"上报给召唤者
      （收件箱里那条 `agent_message` 的 `escalation.kind == "missing_input"`，`evidence`
      带子目标名）。
    """
    from agentflow.conductor import calling_as

    st = _store(tmp_path)
    f_stub = _StubSeam(F_ROUND)
    wiring = _wiring(st, experiment_reasoning=False, e_stub=None, f_stub=f_stub,
                     sid="toy-off")
    notes = " ".join(str(n) for n in wiring["notes"])
    assert "E 的写脚本推理：未接线" in notes, notes
    f = _f_of(wiring)
    assert f.e.llm is None, "只开 F 的开关时 E 不许拿到缝（两个开关各自可解释）"

    pid = _toy_plan(f, key="PK-TOY-OFF")
    # 这一趟以 F 被召唤者的身份跑（父 = M）：`conductor.escalate` 要的三件事都挂上。
    with calling_as("t-0002", "F", parent_task_id="t-0001", parent_role="M",
                    session_root=str(st.root), sid="toy-off"):
        out = f.step(pid)

    reading = _missing_seam_reading(st, out)
    _assert_missing_seam_is_loud(reading)          # ← ② 的判据
    assert "no_seam" in reading["detail"], reading["detail"]

    # ---- 上报真的发生了（不是"写了一句'已上报'"）
    events, problems = SS.read_session(st.root, sid="toy-off")
    assert not problems, problems
    messages = [e for e in events if e.get("kind") == "agent_message"]
    assert len(messages) == 1, messages
    msg = messages[0]
    assert msg["to"] == "M", msg
    esc = msg.get("escalation") or {}
    assert esc.get("kind") == "missing_input", esc
    assert "子目标 s1" in (esc.get("evidence") or []), esc
    assert "模型缝" in str(esc.get("need") or ""), esc
    assert "experiment-reasoning" in str(esc.get("need") or ""), esc
    assert "experiment-reasoning" in str(msg.get("body") or ""), msg.get("body")
    assert [e for e in events if e.get("kind") == "agent_escalation"], events


def test_negative_control_without_a_conductor_it_says_it_did_not_report(tmp_path: Path):
    """② 的第二半（三态）：这一层没有主控 ⇒ 如实说"没上报"，不许写成"已上报"。

    为什么单钉这一条：`escalate` 只有三种结局（已上报 / 被受控拒绝 / 没有可用的主控），
    而中间那一种最容易被写成一句"已上报"—— 那会让父代理永远等一条不会来的留言。
    """
    st = _store(tmp_path)
    f_stub = _StubSeam(F_ROUND)
    llmseam.set_role_seam("E", None)
    reset_cache()                                   # 没有已装配的主控
    f = AgentF(st, config={"workspace_root": str(st.root)}, llm=f_stub)

    out = f.step(_toy_plan(f, key="PK-TOY-NOCO"))
    reading = _missing_seam_reading(st, out)
    _assert_missing_seam_is_loud(reading)           # 产物与读数照样要说清
    assert "没有可用的主控" in reading["detail"], reading["detail"]
    assert "已用 `conductor.escalate" not in reading["detail"], reading["detail"]


# ------------------------------------------------- 「改回静默 no_change ⇒ 判据红」

#: 改前那一轮的返回值（逐字照抄 `_deploy_e` 的旧分支，只有这一处改了才叫"改回"）。
def _old_silent_round(self, sg, *, plan, note: str, spec_line: str) -> dict:  # noqa: ANN001
    """注入负控：把 `no_seam` 那一轮退回到改前的形态（无产物、无上行）。"""
    sid = str(sg.get("sid") or "")
    return {
        "action": "script_not_authored",
        "outcome": "no_change",
        "detail": (
            f"子目标 {sid} 有判据但没有脚本，而 E 没能把它写出来"
            f"（no_seam）⇒ **未推进**（没有脚本就没有实验可跑；"
            f"这不是'跑了但没结果'）。{note}{spec_line}"
        ),
        "evidence": [],
        "status": "todo",
        "blocked_reason": f"E 写不出脚本：no_seam｜{note}",
        "count_attempt": False,
    }


def test_the_criterion_turns_red_if_the_no_seam_round_goes_back_to_a_silent_no_change(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """反向判据：把这一轮改回**静默 `no_change`** ⇒ 同一把尺子必须红。

    为什么要有它：否则"② 的判据能红"这句话本身没人检验过 —— 一条永远绿的判据
    与"这条链是通的"在读数上长得一样。
    """
    st = _store(tmp_path)
    monkeypatch.setattr(AgentF, "_missing_seam_round", _old_silent_round)
    wiring = _wiring(st, experiment_reasoning=False, f_stub=_StubSeam(F_ROUND),
                     sid="toy-red")
    f = _f_of(wiring)
    out = f.step(_toy_plan(f, key="PK-TOY-RED"))

    reading = _missing_seam_reading(st, out)
    assert reading["silent"] is True, f"注入没生效（这一轮还有产物）：{reading}"
    with pytest.raises(AssertionError):
        _assert_missing_seam_is_loud(reading)


# ---------------------------------------------------------------- ④ 第二负控：空脚本

def test_second_negative_control_an_empty_script_is_not_a_success(tmp_path: Path):
    """④ 负控：缝接上、模型只回空脚本 ⇒ "有缝但没产出"绝不当成功。

    两条一起断言：① 这一轮如实落 `bad_source`（与 `no_seam` 是两个码：前者要改脚本、
    后者要去接线）；② 玩具例子那把尺子**红** —— 没有实验行、盘上没有脚本。
    """
    st = _store(tmp_path)
    e_stub = _StubSeam(json.dumps({"source": "   ", "why": "我先想了想"}))
    wiring = _wiring(st, experiment_reasoning=True, e_stub=e_stub,
                     f_stub=_StubSeam(F_ROUND), sid="toy-empty")
    f = _f_of(wiring)
    assert f.e.llm is e_stub, "这一条要的是'有缝'那一档（与 ② 的分界）"
    out = f.step(_toy_plan(f, key="PK-TOY-EMPTY"))

    assert out["outcome"] == "no_change", out
    assert out["action"] == "script_not_authored", out
    assert "bad_source" in out["reason"], out
    assert "no_seam" not in out["reason"], out
    assert st.rows("experiments") == [], st.rows("experiments")
    assert _codes_on_disk(st.root) == [], _codes_on_disk(st.root)

    # 判据必须红（同一把尺子）
    with pytest.raises(AssertionError):
        _assert_toy_chain(st)
    # 也不许上报：缺的是产出，不是缝（上报只会让父代理去查一个不存在的开关）
    events, _problems = SS.read_session(st.root, sid="toy-empty")
    assert not [e for e in events if e.get("kind") == "agent_escalation"], events


# ---------------------------------------------------------------- 开关本身的形态

def test_the_switch_is_opt_in_and_does_not_ride_on_attack_reasoning(tmp_path: Path):
    """`--experiment-reasoning` 的形态：可解析、默认关、且**不被** `--attack-reasoning` 连带。

    三条各自钉一件事：
    ① argparse 认得这个开关，且默认是 False（与 `--semantic-review` 同一条纪律）；
    ② 只开 `attack_reasoning` ⇒ 装配出来的 E 仍然 `llm is None`，notes 如实说"未接线"；
    ③ 开 `experiment_reasoning` ⇒ E 拿到那个缝，notes 说"接线"。
    """
    from agentflow.cli import build_parser

    off_args = build_parser().parse_args(["run-agent", "M", "--task", "x"])
    assert getattr(off_args, "experiment_reasoning", False) is False
    on_args = build_parser().parse_args(
        ["run-agent", "M", "--task", "x", "--experiment-reasoning"])
    assert on_args.experiment_reasoning is True
    # 与 `--attack-reasoning` 是两个独立开关（同时给、单独给都要能解析）
    both = build_parser().parse_args(
        ["run-agent", "M", "--task", "x", "--attack-reasoning", "--experiment-reasoning"])
    assert both.attack_reasoning is True and both.experiment_reasoning is True

    seam = _StubSeam()

    def factory(role: str):
        return seam if role in ("E", "F") else _NoCall(role)

    st_off = _store(tmp_path, "off")
    w_off = host.wired_llm_conductor(
        st_off, session_root=st_off.root, sid="off", max_steps=1,
        workspace_root=str(st_off.root), seam_factory=factory, providers=None,
        attack_reasoning=True, experiment_reasoning=False)
    notes_off = " ".join(str(n) for n in w_off["notes"])
    assert "E 的写脚本推理：未接线" in notes_off, notes_off
    assert w_off["conductor"].backend.resolve("E").llm is None, (
        "只开 --attack-reasoning 时 E 不许拿到缝")

    st_on = _store(tmp_path, "on")
    w_on = host.wired_llm_conductor(
        st_on, session_root=st_on.root, sid="on", max_steps=1,
        workspace_root=str(st_on.root), seam_factory=factory, providers=None,
        attack_reasoning=False, experiment_reasoning=True)
    notes_on = " ".join(str(n) for n in w_on["notes"])
    assert "E 的写脚本推理：接线" in notes_on, notes_on
    assert w_on["conductor"].backend.resolve("E").llm is seam, (
        "打开 --experiment-reasoning 之后 E 必须真的拿到那个缝")
    # 没开 `--attack-reasoning` ⇒ F 仍然没有缝（两个方向都不连带）
    assert w_on["conductor"].backend.resolve("F").llm is None
    # 工具路径那一份登记同样要在位（`attack.step` 走的是 `role_seam("E")`）
    assert llmseam.role_seam("E") is seam


def test_the_toy_example_switch_is_not_a_new_declaration_surface():
    """反发明：玩具例子的落点必须是 `experiments` 的**既有**字段，不是新列/新动作。

    判据：`experiments` 的 schema 字段里没有 `toy*`（所以它不是一次声明面改动），
    而我们的落点 `observations` 本来就在那张表的字段里。
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(S.Experiment)}
    assert "observations" in fields, fields
    assert not [f for f in fields if "toy" in f.lower()], (
        f"`experiments` 多了玩具例子的列（那是改声明面）：{fields}")


# ============================================================================
# 缺陷二（2026-10-21 真机）：`experiments.observations.toy_example` 从未出现
#
# 真机读数（`projects/mp3/data/experiments.json`）：2 条实验、**`toy_example` 0 条**。
# 根因写在 `_toy_example_reading` 的 docstring 里：此前只有经 `F→E` 且父把
# `params["toy_example"]` 带下来才会标，而模型不一定会带 —— 于是 E 自己写出来的
# "玩具读数"（mp3 第二条的 claim 逐字这么写的，`bound` 是 `D<=6 / M<=8 / n<=3`、
# `exit_code=0`）在台账上一条标记都没有。
#
# 下面这一组判据钉的是"E 自己判"：① 小规模真跑 ⇒ 自动标；② 大规模 ⇒ 不标且 why
# 写明超限；③ 负控：把自动判定关掉 ⇒ ① 红；④ 负控：让"没真跑"的也标 ⇒ 红。
# ============================================================================

#: 小规模脚本：n=4 的错排数，与手算表逐项对比（`n=4 <= 8`，人拿纸能核）。
SMALL_AUTO_SCRIPT = (
    "import itertools, json\n"
    "EXPECT = {1: 0, 2: 1, 3: 2, 4: 9}\n"
    "N = 4\n"
    "def derangements(n):\n"
    "    return sum(1 for p in itertools.permutations(range(n))\n"
    "               if all(p[i] != i for i in range(n)))\n"
    "got = {n: derangements(n) for n in range(1, N + 1)}\n"
    "ok = all(got[n] == EXPECT[n] for n in got)\n"
    "print('REPRO_RESULT: ' + json.dumps({\n"
    "    'result': 'supports' if ok else 'refutes',\n"
    "    'observations': {'n': N, 'D': got[N], 'matched': ok},\n"
    "    'counterexample': None if ok else {'n': N, 'why': 'D(4) 与手算表不符'},\n"
    "    'negation_kind': 'not_proved', 'bound': {'n': N},\n"
    "    'strategy': 'brute force',\n"
    "}))\n"
)

#: 大规模脚本：n=20 的全排列错排数（扫到 n=20 —— 这不是能手算的一个数）。
BIG_AUTO_SCRIPT = (
    "import json\n"
    "N = 20\n"
    "print('REPRO_RESULT: ' + json.dumps({\n"
    "    'result': 'supports', 'evidence_kind': 'cross_check',\n"
    "    'observations': {'n': N}, 'counterexample': None,\n"
    "    'negation_kind': 'not_proved', 'bound': {'n': N},\n"
    "}))\n"
)

#: 跑完了但**没按协议打结论行**的脚本（"执行过"≠"跑成了一个读得出的数"）。
NO_RESULT_SCRIPT = "print('I ran, but I printed nothing usable')\n"


def _auto_ws(tmp_path: Path) -> Store:
    st = Store(tmp_path / "auto")
    st.init()
    return st


def _write(st: Store, rel: str, text: str) -> None:
    p = Path(st.root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _run(st: Store, rel: str, *, params: dict | None = None, key: str = "auto") -> dict:
    """用**生产的 `run_experiment`** 跑一遍（不带任何 `toy_example` 声明 —— 真机形态）。"""
    from agentflow.agent_e import AgentE

    e = AgentE(st, config={"lease_seconds": 60}, workspace_root=st.root)
    e.run_experiment("一个能手算的小情形：错排数", key, rel, params=params or {})
    return dict(st.rows("experiments")[-1])


def _auto_reading(row: dict) -> dict:
    obs = dict(row.get("observations") or {})
    got = obs.get(TOY_EXAMPLE_KEY)
    assert isinstance(got, dict), (
        f"行上没有玩具例子读数（`observations[{TOY_EXAMPLE_KEY!r}]`）：{obs}")
    return got


def _assert_auto_toy(row: dict, *, expect_n) -> None:
    """① 的尺子：小规模 + 真跑 ⇒ 自动标成玩具例子，且每一格都成形。

    七格逐条判（少一格就只是"看起来像"）：`declared`（自动填的、带出处）、
    `checked` / `within_limit` / `limit` / `n` / `executed` / `exit_code` /
    `script_path` / `script_sha256` / `why`（"由规模自动判定"）。
    """
    from agentflow.agent_e.run_experiment import is_toy_example

    toy = _auto_reading(row)
    assert is_toy_example(toy) is True, f"小规模真跑的实验没有被自动标成玩具例子：{toy}"
    declared = toy.get("declared")
    assert isinstance(declared, dict) and declared.get("auto") is True, declared
    assert declared.get("source"), f"自动判定没说读出处在哪个键上：{declared}"
    assert toy.get("checked") is True and toy.get("within_limit") is True, toy
    assert toy.get("limit") == TOY_EXAMPLE_MAX_N, toy
    assert toy.get("n") is not None and int(toy["n"]) <= TOY_EXAMPLE_MAX_N, toy
    if expect_n is not None:
        assert _as_int(toy.get("n")) == expect_n, toy
    assert toy.get("executed") is True and toy.get("exit_code") == 0, toy
    assert toy.get("script_path") == row.get("code_path"), (toy, row.get("code_path"))
    assert toy.get("script_sha256") == row.get("code_hash"), (toy, row.get("code_hash"))
    why = str(toy.get("why") or "")
    assert "由规模自动判定" in why, f"why 里没写“由规模自动判定”：{why!r}"
    # 反真空：那个数真的在行上（玩具例子的读数是"一个数"，不是"扫到哪儿"）
    assert _as_int(dict(row.get("observations") or {}).get("D")) == 9, row.get("observations")


def _as_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _assert_not_a_toy(row: dict, *, want_in_why: str) -> None:
    """② 的尺子：**不**标成玩具例子，且 `why` 里写明为什么（超限 / 没真跑）。"""
    from agentflow.agent_e.run_experiment import is_toy_example

    toy = _auto_reading(row)
    assert is_toy_example(toy) is False, f"这一条被标成了玩具例子：{toy}"
    why = str(toy.get("why") or "")
    assert want_in_why in why, f"why 里没写 {want_in_why!r}：{why!r}"
    return toy


def test_auto_control_a_small_script_that_really_ran_is_marked_a_toy_example(tmp_path: Path):
    """① 小规模真跑 ⇒ 自动标 `toy_example`（`executed=true`），不需要调用方声明。

    真机对照：mp3 的第二条实验 `params={}`，claim 自己写着"玩具读数"，
    而 `observations.toy_example` 一条都没有 —— 这一条就是补那条断掉的接缝。
    """
    st = _auto_ws(tmp_path)
    _write(st, "code/small.py", SMALL_AUTO_SCRIPT)
    row = _run(st, "code/small.py")
    assert row["exit_code"] == 0 and row["result"] == "supports", row
    _assert_auto_toy(row, expect_n=4)
    # 声明面没动：这一格仍然落在 `observations` 里（不是新列）
    assert TOY_EXAMPLE_KEY in dict(row.get("observations") or {}), row


def test_a_big_scan_is_not_marked_a_toy_example_and_the_reason_names_the_limit(
        tmp_path: Path):
    """② 大规模（n=20 超上限）⇒ **不标**，`why` 写明超限（"大扫描不许当玩具例子"）。"""
    st = _auto_ws(tmp_path)
    _write(st, "code/big.py", BIG_AUTO_SCRIPT)
    row = _run(st, "code/big.py", key="big")
    toy = _assert_not_a_toy(row, want_in_why="超过玩具例子的上限")
    assert toy.get("within_limit") is False, toy
    assert toy.get("limit") == TOY_EXAMPLE_MAX_N, toy
    assert _as_int(toy.get("n")) == 20, toy


def test_no_result_line_is_not_marked_a_toy_example(tmp_path: Path):
    """② 的第二半：跑完了但没打出结论行 ⇒ `executed=false`，不标（"执行过"≠"跑成读数"）。"""
    st = _auto_ws(tmp_path)
    _write(st, "code/silent.py", NO_RESULT_SCRIPT)
    # 没有结论行 ⇒ 脚本自报的规模读不到；为了把"没真跑"这一档单独钉住，
    # 由 `params` 给一个够小的 `n`（"规模看着够小、但没跑出结论"正是这一档的形态）。
    row = _run(st, "code/silent.py", params={"n": 4}, key="silent")
    toy = _assert_not_a_toy(row, want_in_why="没有真的跑出结论行")
    assert toy.get("executed") is False, toy
    assert toy.get("within_limit") is True, (
        f"规模确实够小（params n=4），不标的原因必须落在“没真跑”上：{toy}")


def test_negative_control_with_the_auto_judgement_off_the_first_criterion_turns_red(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """③ 负控：把自动判定关掉（声明缺席 ⇒ 什么都不写）⇒ ① 的尺子必须红。

    这一格就是**改前**的行为（`params` 里没有声明就返回 `None`）：真机 mp3 的
    `toy_example` 0 条正是它造成的。判据必须能咬住"回到改前"。
    """
    from agentflow.agent_e import run_experiment as RX

    monkeypatch.setattr(RX, "_auto_toy_example_reading",
                        lambda **_: None)
    st = _auto_ws(tmp_path)
    _write(st, "code/small.py", SMALL_AUTO_SCRIPT)
    row = _run(st, "code/small.py")
    assert TOY_EXAMPLE_KEY not in dict(row.get("observations") or {}), row
    with pytest.raises(AssertionError):
        _assert_auto_toy(row, expect_n=4)


def test_negative_control_marking_a_run_that_never_produced_a_result_turns_red(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """④ 负控：让"没真跑"的也算真跑（`executed` 恒 True）⇒ 不标的尺子必须红。"""
    from agentflow.agent_e import run_experiment as RX

    monkeypatch.setattr(RX, "_toy_example_executed", lambda **_: True)
    st = _auto_ws(tmp_path)
    _write(st, "code/silent.py", NO_RESULT_SCRIPT)
    row = _run(st, "code/silent.py", params={"n": 4}, key="silent")
    with pytest.raises(AssertionError):
        _assert_not_a_toy(row, want_in_why="没有真的跑出结论行")


def test_the_auto_judgement_does_not_override_an_explicit_declaration(tmp_path: Path):
    """声明优先：调用方给了 `toy_example` ⇒ 自动判定不许覆盖它（一个字都不改）。"""
    st = _auto_ws(tmp_path)
    _write(st, "code/small.py", SMALL_AUTO_SCRIPT)
    declared = {"n": 4, "expect": 9, "quantity": "D(4)"}
    row = _run(st, "code/small.py", params={TOY_EXAMPLE_KEY: dict(declared)}, key="decl")
    toy = _auto_reading(row)
    assert toy.get("declared") == declared, toy
    assert "auto" not in (toy.get("declared") or {}), toy
    assert toy.get("why") == "", f"声明那一档的 why 不许被自动判定改写：{toy}"
