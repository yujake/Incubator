# -*- coding: utf-8 -*-
"""L（Lean 形式化者）的七条判据：它真的存在、真的能跑、真的写得出 Lean、真的会拒绝假命题。

## 这一组为什么存在（业主 2026-10-22 的施工单，逐字）

「照着 E 的方式新设角色 L（Lean 形式化者）—— 把 E 里所有与 Lean 开关/形式化有关的东西
复制过去，E 的内容先不删，协作面（边/召唤）暂不搭。业主要看见『L 真的能写 Lean 代码、
真的能干活』。」再加一条反控：「把命题改成一个假命题（1 = 2）⇒ Lean 必须拒绝，L 的结论
必须是 failed（不许『看起来 verified』）。这一条是『能干活』与『会瞎报』的分界线。」

七条判据（每条都写明"改前红"是什么形态）：

| # | 判据 | 改前红（没有 L 这一套时它怎么红） |
|---|---|---|
| 1 | L 存在且可跑 | `S.ROLES` 里没有 L ⇒ 断言当场红；`run-agent L` 连角色都解析不到 |
| 2 | 协作面没搭 | 反过来：如果有人给 L 加了边或让它可召唤，这一条红 |
| 3 | 真写盘 | 没有 `formalize` 这一格（E 那条路只有内联源码）⇒ 盘上不会出现 `code/formal/` 下的 .lean |
| 4 | 真检查 | 自检不是 usable 时若还报 verified（或不起检查器却报 exit_code=0）⇒ 红 |
| 5 | 反控 | 假命题被报成 verified ⇒ 红（这是"会瞎报"的唯一机械分界） |
| 6 | E 未被削弱 | E 的动作表 / 工具面 / Lean 开关改写在 L 落地后少一条 ⇒ 红 |
| 7 | 反真空 | 把"读自检结论"那一步钉成恒 usable ⇒ 判据 4 的 unknown 档必须变红 |

## 零模型

全程 `ScriptedGateway`（照剧本回答的替身模型：与真模型同接口，不发一次请求、不花一分钱）。
真 Lean 用本机装的那一版（绝对路径，不依赖 PATH）；本机没有它时，需要它的那两条判据
断言"结论是 unknown 且说清了原因"，而不是悄悄跳过（跳过等于把"没查成"折叠成"通过"）。

## 临时文件

所有工作区都建在 pytest 的 `tmp_path` 下，`code/formal/*.lean` 随 tmp 一起被清掉。
判据自己不往仓库里写任何东西（`git status -- projects/` 不受影响）。
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow import schema as S

#: 本机那一版真 Lean（业主已加 360 信任）。用绝对路径：PATH 上的 lean 可能是另一个东西
#: （`toolchain` 的四档梯子把 PATH 放在最后一档，正是因为它最不可信）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()

#: 正面样例：一条真命题，带 import 与 namespace（业主口径："内容要像样"）。
GOOD_SOURCE = """import Init.Data.Nat.Basic

namespace LProbe

/-- 一条具体命题：对所有自然数 n，n + 0 = n。 -/
theorem add_zero_probe (n : Nat) : n + 0 = n := rfl

end LProbe
"""
#: 反控：假命题（`rfl` 一定证不出 `1 = 2`）。
BAD_SOURCE = """import Init.Data.Nat.Basic

namespace LProbe

/-- 反控用的假命题：1 = 2。 -/
theorem one_eq_two : 1 = 2 := rfl

end LProbe
"""

GOOD_CLAIM = "forall n : Nat, n + 0 = n"
BAD_CLAIM = "1 = 2"

#: 判据 4 的那五档自检理由码（不是 failed、不是 verified）。
SELFCHECK_REASON_HINTS = ("lean_selfcheck_off", "lean_selfcheck_unusable",
                          "lean_selfcheck_unknown")


class ScriptedGateway:
    """照剧本回答的替身模型（与真模型同接口；价 0.0，一次请求都不发）。"""

    spec = type("Spec", (), {"model": "scripted", "api_key": "fake"})()

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 **kw: object) -> object:
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return type("Reply", (), {"ok": True, "text": text, "tokens_in": 5, "tokens_out": 5,
                                  "error_detail": "", "error_kind": ""})()


def _drive_run_agent(ws: pathlib.Path, replies: list[str], task: str,
                     monkeypatch: pytest.MonkeyPatch) -> dict:
    """用 `run-agent L` 跑一趟（零模型）。返回退出码、工作区与逐步骤结果。"""
    from argparse import Namespace

    from agentflow import cli
    from agentflow import sessions as SS
    from agentflow.llmseam import LlmSeam
    from agentflow.tools.conductor_tools import reset_cache

    script = {"L": list(replies)}

    def factory(role: str, *, root: pathlib.Path, sid: str, usd_budget: float | None,
                store: object = None) -> LlmSeam:
        gw = ScriptedGateway(script.get(role, ['{"final": "（没有剧本）", "evidence": []}']))
        return LlmSeam(role=role, session_root=root, gateway=gw, price=(0.0, 0.0),
                       sid=sid, usd_budget=usd_budget)

    monkeypatch.setattr(cli, "_agent_seam_factory", factory)
    reset_cache()
    args = Namespace(root=str(ws), sid="t", json=False, budget_usd=None, dispatch=False,
                     role="L", task=task, drive=[], max_steps=4, rounds=1,
                     report_every=1, resume=False, stop_file=None)
    rc = cli.cmd_run_agent(args)
    events, problems = SS.read_session(ws, sid="t")
    steps = [e for e in events if e.get("kind") == "agent_step"]
    ends = [e for e in events if e.get("kind") == "agent_run_end"]
    return {"rc": int(rc), "ws": ws, "steps": steps, "ends": ends,
            "events": events, "problems": problems}


def _formalize_result(run: dict) -> dict:
    """那一趟里 `formal.formalize` 的那一次工具调用的结果（没有就报清楚）。"""
    for ev in run["steps"]:
        result = ev.get("result") or {}
        if str(result.get("tool") or "") == "formal.formalize":
            return dict(result.get("data") or {})
    raise AssertionError(
        f"这一趟没有调到 formal.formalize ⇒ 后面的判据没东西可看（步骤：{run['steps']}）")


def _provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """把这一趟的 Lean 落在本机那一版上（绝对路径），并清掉自检读数缓存。"""
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


@pytest.fixture(scope="module")
def good_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """判据 1/3/4 共用的那一趟（`run-agent L` + 真命题 + 真 Lean）。"""
    ws = tmp_path_factory.mktemp("l-good") / "ws"
    with pytest.MonkeyPatch.context() as mp:
        _provider(mp)
        replies = [
            json.dumps({"tool": "formal.formalize",
                        "args": {"claim": GOOD_CLAIM, "source": GOOD_SOURCE}},
                       ensure_ascii=False),
            json.dumps({"final": "已形式化并检查", "evidence": []}, ensure_ascii=False),
        ]
        run = _drive_run_agent(ws, replies, f"把 {GOOD_CLAIM} 形式化并检查", mp)
    from agentflow import leantoolchain as LT

    LT.reset_reading_cache()
    return run


@pytest.fixture(scope="module")
def bad_run(tmp_path_factory: pytest.TempPathFactory) -> dict:
    """判据 5 的那一趟（反控：假命题）。"""
    ws = tmp_path_factory.mktemp("l-bad") / "ws"
    with pytest.MonkeyPatch.context() as mp:
        _provider(mp)
        replies = [
            json.dumps({"tool": "formal.formalize",
                        "args": {"claim": BAD_CLAIM, "source": BAD_SOURCE}},
                       ensure_ascii=False),
            json.dumps({"final": "跑完了", "evidence": []}, ensure_ascii=False),
        ]
        run = _drive_run_agent(ws, replies, f"把 {BAD_CLAIM} 形式化并检查", mp)
    from agentflow import leantoolchain as LT

    LT.reset_reading_cache()
    return run


# ============================================================ 1. L 存在且可跑
def test_l_exists_as_a_role_and_runs_a_scripted_round(good_run: dict) -> None:
    """L 真的是一个角色：名单里有它、spec 读得出来、`run-agent L` 真的起得来。

    改前红：`S.ROLES` 里没有 "L"（第一行就红）；`specs/l.py` 不存在（import 直接抛）；
    `run-agent L` 解析不到角色 ⇒ 退出码不是 0。

    为什么"能起"要判：一个只在注册表里的角色与一个真的能被派活跑完一圈的角色，
    在台账上长得一样（前者连一行 `agent_run_end` 都不会有）。
    """
    assert "L" in S.ROLES, f"schema.ROLES 里没有 L：{S.ROLES}"
    from agentflow.agent_l import AgentL
    from agentflow.specs import l as LSPEC

    assert LSPEC.SPEC.role == "L"
    assert LSPEC.ACTIONS, "L 的动作表是空的 ⇒ 它没有任何可以做的事"
    assert {a.action for a in LSPEC.ACTIONS} == {"formalize", "check_formal", "record"}, LSPEC.ACTIONS
    for spec in LSPEC.ACTIONS:
        assert callable(getattr(AgentL, spec.handler_name, None)), (
            f"L 的动作 {spec.action} 声明的 handler {spec.handler_name!r} 不存在")
    assert good_run["rc"] == 0, f"run-agent L 的退出码是 {good_run['rc']}"
    ends = good_run["ends"]
    assert ends and str(ends[-1].get("role")) == "L", ends
    assert str(ends[-1].get("stop_reason")) == "final", ends[-1]
    assert good_run["problems"] == [], good_run["problems"]


# ============================================================ 2. 协作面：入口只有 B
def test_the_collaboration_surface_is_b_to_l_and_l_to_c(tmp_path: pathlib.Path) -> None:
    """协作面就是业主 2026-10-22 晚裁定的那一个面：入边只有 `B`、出边只有 `C`。

    裁定逐字（记在 `specs/l.py` 的模块 docstring）：「只有 B 可以派 L，L 允许派 C
    来梳理证明链，消费 B 的定理证明库，可向 B 汇报形式化过程中遇到的困难、要求 B
    完善证明并重新得到 V 签，若缺陷严重，B 应通知 D 开展研究处理证明难点」。

    这一条随当天几次改口径变过（第一版空边集 + 不可召唤；第二版 `F → L`；第三版
    撤回；最终裁定把入口给 B、给 L 一条 `L → C`）。它守的是"谁能让 L 干活"：
    入边集合多一个或少一个、L 多派一个人，这里当场点名。

    改前红（反过来读）：把 `specs/b.py` 的 `edges` 里去掉 'L'、或把 `specs/l.py`
    的 `summonable` 改回 False ⇒ 下面"B → L 在闸门上通"那一条红；给别的角色加
    一条到 L 的边 ⇒ 入边集合那一条红；把 `specs/m.py` 的边表清空则"反真空"红。

    反真空：先断言边表本身不是空的、并证明 F→E 这条无关的真边仍然通 —— 否则
    "入边恰好是 B"在一个空表或一个坏掉的读数上恒真。
    """
    from agentflow import policy as P
    from agentflow.agentspec import builtin_registry
    from agentflow.host import wired_conductor
    from agentflow.store import Store

    edges = C.ALLOWED_EDGES
    assert sum(len(v) for v in edges.values()) >= 30, (
        f"边表几乎是空的 ⇒ 下面的断言会变成真空：{ {k: len(v) for k, v in edges.items()} }")
    inbound = sorted(role for role, targets in edges.items() if "L" in targets)
    assert inbound == ["B"], f"能召唤 L 的角色是 {inbound}（最终裁定：只有 B）"
    assert edges.get("L") == frozenset({"C"}), (
        f"L 的出边是 {sorted(edges.get('L') or [])}（最终裁定：只有 C）")
    assert "L" not in C.NON_SUMMONABLE, (
        f"L 在不可召唤名单里 ⇒ B 也派不动它（裁定要 B 是唯一入口）：{sorted(C.NON_SUMMONABLE)}")
    reg = builtin_registry()
    assert "L" in reg.summonable_roles(), reg.summonable_roles()
    pol = P.Policy()
    assert P.check(pol, P.Decision(frm="F", to="E", action="", depth=2)) is None, (
        "F → E 这条既有边都不通了 ⇒ 这一条判据读的不是边表")
    assert P.check(pol, P.Decision(frm="B", to="L", action="", depth=2)) is None, (
        "B → L 在闸门上不通 ⇒ 最终裁定的唯一入口没有接上")

    # 读数的第二条来源：主控真的召唤不动它（不是"名单里有它"这么一句话）。
    # `status` 是"这次召唤跑完了没有"（被拒也是跑完了），"有没有做"看 `outcome` ——
    # 两个格子在本仓是刻意分开的，判据不许把它们折成一个。
    st = Store(tmp_path / "ws")
    st.init()
    cond = wired_conductor(st, workspace_root=str(st.root))
    res = cond.summon("L", "check_formal", {"claim": "1 = 1"}, by="M")
    assert str(getattr(res, "outcome", "")) == "refused", (
        f"主控居然把 L 召唤成功了：{res}")
    assert str(getattr(res, "refusal_reason", "")) == "forbidden_edge", res
    assert "L" in str(getattr(res, "detail", "") or ""), res
    # 父代理也一样（F 曾经开过这条边，最终裁定把它给了 B）
    res_f = cond.summon("L", "check_formal", {"claim": "1 = 1"}, by="F")
    assert str(getattr(res_f, "outcome", "")) == "refused", res_f
    assert str(getattr(res_f, "refusal_reason", "")) == "forbidden_edge", res_f


# ============================================================ 3. 真写盘
def test_l_writes_a_real_lean_file_to_the_workspace(good_run: dict) -> None:
    """那一趟真的在 `code/formal/` 落了一个 .lean，内容像样（import + namespace + theorem）。

    改前红：没有 `formalize` 这一格时盘上不会出现这个文件（E 那条路把内联源码放在
    临时目录里跑完就删）；`sha256` 与盘上字节不一致时也红 —— 它证明返回值里那份哈希
    描述的是盘上这份文件，而不是内存里那段字符串。
    """
    data = _formalize_result(good_run)
    assert data.get("written") is True, data
    rel = str(data.get("path") or "")
    assert rel.startswith("code/formal/") and rel.endswith(".lean"), rel
    path = good_run["ws"] / rel
    assert path.is_file(), f"返回值说有文件，盘上没有：{path}"
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    assert "theorem" in text, text
    assert text.lstrip().startswith("import "), "源码要有 import（这条定理用的是 Lean 核心库）"
    assert "namespace " in text and "end " in text, text
    assert "theorem add_zero_probe" in text, text
    assert b"\r\n" not in raw, "落盘的行尾必须是 \\n（write_bytes；\\r\\n 会让 sha256 与内容无关）"
    assert data.get("sha256") == hashlib.sha256(raw).hexdigest(), (
        f"返回值里的 sha256 与盘上字节不一致：{data.get('sha256')} vs "
        f"{hashlib.sha256(raw).hexdigest()}")
    assert int(data.get("bytes") or 0) == len(raw) == len(text.encode("utf-8"))


# ============================================================ 4. 真检查
def test_the_run_really_spawned_lean(good_run: dict) -> None:
    """那一趟真的把 Lean 跑起来了（绝对路径 + 真实退出码），结论是三态里的 verified。

    改前红：自检不是 usable 却报 verified ⇒ 红；没起检查器却给 `exit_code=0` ⇒ 红
    （`exit_code` 的真实值来自进程，不是"跑完了就写 0"）。

    本机没有那一版 lean 时，这一条断言的是另一档：结论必须是 unknown、必须带原因，
    且不允许出现 exit_code（不 spawn 就没有退出码）。"跳过"不在选项里 ——
    跳过会把"没查成"读成"通过"。
    """
    data = _formalize_result(good_run)
    if not HAVE_LEAN:
        assert data.get("status") == "unknown", data
        assert data.get("reason") in SELFCHECK_REASON_HINTS, data
        assert data.get("problems"), data
        assert data.get("exit_code") is None, data
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条只在 unknown 档上成立（已断言）")
    assert data.get("status") == "verified", data
    assert data.get("verified") is True and data.get("checked") is True, data
    assert data.get("exit_code") == 0, data
    assert pathlib.Path(str(data.get("lean_path"))).resolve() == LEAN.resolve(), (
        f"跑的不是本机那一版 lean：{data.get('lean_path')}")
    assert str(data.get("lean", {}).get("state")) == "usable", data.get("lean")
    output = str(data.get("verifier_output") or "")
    assert "does not depend on any axioms" in output or "axioms" in output, (
        f"检查器原话里没有公理审计那一行：{output!r}")

    # 独立复核：判据自己再用绝对路径跑一次同一个文件（不经过 L 的任何代码）。
    proc = subprocess.run([str(LEAN), str(good_run["ws"] / str(data["path"]))],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120, cwd=str(good_run["ws"]))
    assert proc.returncode == 0, (
        f"判据自己跑 lean 也没过（退出码 {proc.returncode}）：{proc.stdout}\n{proc.stderr}")


# ============================================================ 5. 反控
def test_a_false_proposition_must_be_failed_not_verified(bad_run: dict) -> None:
    """反控（这是"能干活"与"会瞎报"的分界线）：`1 = 2` 必须被 Lean 拒，L 记 failed。

    改前红：假命题被记成 verified（或 checked=True 但 reason=verified）⇒ 红。

    本机没有 lean 时同样不许"看起来 verified"：结论只能是 unknown（假命题在这种机器上
    既没被证明也没被反驳），这一条仍然守着"会瞎报"那条线。
    """
    data = _formalize_result(bad_run)
    assert data.get("written") is True, data
    path = bad_run["ws"] / str(data.get("path") or "")
    assert path.is_file() and "1 = 2" in path.read_text(encoding="utf-8")
    if not HAVE_LEAN:
        assert data.get("status") == "unknown", data
        assert data.get("verified") is not True, data
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条只在 unknown 档上成立（已断言）")
    assert data.get("status") == "failed", (
        f"假命题没有被记成 failed ⇒ 这就是『会瞎报』：{json.dumps(data, ensure_ascii=False)}")
    assert data.get("verified") is False, data
    assert data.get("reason") == "compile_error", data
    assert int(data.get("exit_code") or 0) != 0, data
    output = str(data.get("verifier_output") or "")
    assert "type mismatch" in output or "error" in output, (
        f"检查器原话里没有任何一处拒绝的痕迹：{output!r}")
    # 独立复核：判据自己跑一次同一个文件，退出码必须非 0（否则是判据自己看错了）。
    proc = subprocess.run([str(LEAN), str(path)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120,
                          cwd=str(bad_run["ws"]))
    assert proc.returncode != 0, f"判据自己跑 lean 居然过了：{proc.stdout}"


# ============================================================ 6. E 未被削弱
def test_e_is_not_weakened_by_the_copy(tmp_path: pathlib.Path) -> None:
    """E 的实验面原样，而它的 Lean 侧已经整条退场（2026-10-23 晚裁定）。

    这一条改过一次口径（改前断言 E 的动作表五格 + `verify.check_formal` 的 `roles=()`）。
    裁定（逐字「E 侧与 Lean 相关的工具和动作都该清干净」）之后那个中间态也没了：

    - 桥接层真身仍在：`VT.check_formal` 这个函数实体还在（L 的 `_CheckFormalL` 经
      `agent_e/check_formal.py::_CheckFormal` 调到它）；
    - 但工具那一件整条删除了（不是 `roles=()`）：注册表里没有 `verify.check_formal`；
    - E 的动作表四格（`check_formal` 不在其中），`AgentE` 上没有 `check_formal` 方法；
    - E 的实验面一件不少（`run_experiment` / `run_script_experiment` / `evidence_for` /
      `list_experiments`），`verify.run_experiment` 仍在它工具面上。

    改前红（两个方向都要能说话）：多回一格动作、把 `verify.check_formal` 装回注册表、
    或者把 `formal.*` 漏进 E 的工具面 ⇒ 任一条红；反过来，谁把 E 的实验面削掉一格，
    "E 没被削弱"那几条也会红。
    """
    from agentflow.agent_e import AgentE
    from agentflow.specs import e as ESPEC
    from agentflow.store import Store
    from agentflow.tools import build_registry
    from agentflow.tools import verify_tools as VT

    # ---- E 的声明面：四格动作，没有 check_formal
    e_actions = tuple(s.action for s in C.CAPABILITIES["E"])
    assert e_actions == ("run_experiment", "evidence_for",
                         "list_experiments", "run_script_experiment"), e_actions
    assert not hasattr(AgentE, "check_formal"), "AgentE 上还有 check_formal 方法"
    assert ESPEC.SPEC.summonable is True and tuple(ESPEC.SPEC.edges) == ("B", "D", "V"), ESPEC.SPEC

    # ---- 桥接层真身仍在（函数实体），而工具那一件整条删除
    assert callable(VT.check_formal), "VT.check_formal 的函数实体不见了（那是桥接层真身）"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    reg = build_registry(store=st, workspace_root=str(ws)).registry
    assert "verify.check_formal" not in set(reg.names()), (
        "`verify.check_formal` 又装回注册表了（裁定要的是整条删掉，不是 roles=()）")
    assert "formal.check_formal" in set(reg.names()), "L 的形式化入口不见了"

    # ---- E 的实验面一件不少
    face = {spec.name for spec in reg.for_role("E")}
    for want in ("verify.run_experiment", "verify.code_hash", "verify.evidence_for"):
        assert want in face, f"E 的工具面少了 {want}：{sorted(face)}"
    assert not any(n.startswith("formal.") for n in face), f"formal.* 漏进了 E 的工具面：{sorted(face)}"

    here = pathlib.Path(__file__).resolve().parent
    proc = subprocess.run([sys.executable, "-m", "pytest", str(here / "test_lean_switch.py"),
                           "-q", "--no-header", "-p", "no:cacheprovider"],
                          cwd=str(here.parent), capture_output=True, text=True,
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8",
                               "PYTHONUTF8": "1"})
    tail = "\n".join((proc.stdout or proc.stderr or "").splitlines()[-12:])
    assert proc.returncode == 0, f"test_lean_switch.py 红了（退出码 {proc.returncode}）：\n{tail}"


def _unknown_from_the_gate(data: dict) -> bool:
    """这一份结论是不是"自检闸拦下来"的那一档（判据 4 的 unknown 档）。

    三件事必须同时成立：状态 unknown、理由码是自检那三个之一、且带一行原因。
    只有"理由码来自自检闸"才算 —— 否则桥接层自己的 `no_backend` 也会让
    "unknown"这三个字成立，而那时闸门根本没起作用（判据 7 打的就是这一格）。
    """
    return (str(data.get("status")) == "unknown"
            and str(data.get("reason")) in SELFCHECK_REASON_HINTS
            and bool(data.get("problems")))


def test_the_unknown_branch_is_not_vacuous(tmp_path: pathlib.Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """反真空：把"读自检结论"那一步钉成恒 usable ⇒ 判据 4 的 unknown 档必须红。

    做法（两个方向都打）：
    ① 造一个确定不可用的工具链（`AGENTFLOW_LEAN_BIN` 指向不存在的文件、PATH 清空）
       ⇒ L 的结论必须是"自检闸拦下来的 unknown"，且桥接层一次都没被调用；
    ② 只把 `AgentL._lean_selfcheck` 换成恒 usable（工具链仍然是那个不存在的）
       ⇒ 桥接层被调用了、理由码变成了 `no_backend`（不再是自检那三个之一）
       ⇒ ① 的那条断言必须变红。它红了才说明"unknown 档"真的在读自检结论，
       而不是恒真的一句话。
    """
    from agentflow import leantoolchain as LT
    from agentflow.agent_l import AgentL
    from agentflow.store import Store
    from agentflow.tools import verify_tools as VT

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()

    # ---- ① 确定不可用：显式给一个不存在的解释器 + 清空 PATH（不让它落到第四/五档）
    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(tmp_path / "no-such-lean.exe"))
    monkeypatch.setenv("PATH", "")
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()

    calls: list[int] = []
    real_check = VT.check_formal

    def spy(*a: object, **kw: object) -> object:
        calls.append(1)
        return real_check(*a, **kw)

    monkeypatch.setattr(VT, "check_formal", spy)
    agent = AgentL(st, workspace_root=ws)
    first = agent.formalize(GOOD_CLAIM, source=GOOD_SOURCE)
    assert _unknown_from_the_gate(first) is True, (
        f"自检不可用时结论不是『闸门拦下来的 unknown』：{json.dumps(first, ensure_ascii=False)}")
    assert calls == [], "自检不可用却还是去问检查器了（那正是『连撞同一条错误』）"
    assert first.get("exit_code") is None, first

    # ---- ② 只把自检结论换成恒 usable ⇒ ① 的判据必须红
    monkeypatch.setattr(AgentL, "_lean_selfcheck", lambda self: ("usable", ""))
    LT.reset_reading_cache()
    agent2 = AgentL(st, workspace_root=ws)
    second = agent2.formalize(GOOD_CLAIM, source=GOOD_SOURCE)
    assert calls, "把自检钉成 usable 之后桥接层仍然一次都没被调用 ⇒ 闸门的位置不对"
    assert _unknown_from_the_gate(second) is False, (
        "把自检钉成恒 usable，判据 4 的 unknown 档居然还是绿的 ⇒ 那条判据没有在读自检结论："
        + json.dumps(second, ensure_ascii=False))
    assert str(second.get("reason")) not in SELFCHECK_REASON_HINTS, second


# ============================================================ 附加：三态词表
def test_the_three_states_and_reasons_are_one_vocabulary() -> None:
    """L 的三态与理由码是 E 那份词表的超集（同一个桥接层状态不许有两个名字）。

    改前红：L 自己抄一份理由表 ⇒ 两边一漂就红（这条判据就是那份漂移的探针）。
    """
    from agentflow import agent_l
    from agentflow.agent_e import FORMAL_REASONS

    assert agent_l.THREE_STATES == ("verified", "failed", "unknown")
    assert set(FORMAL_REASONS) <= set(agent_l.FORMAL_REASONS_L), (
        set(FORMAL_REASONS) - set(agent_l.FORMAL_REASONS_L))
    assert agent_l.FAILED_REASONS == ("compile_error", "uses_sorry", "extra_axioms",
                                      "decl_mismatch"), agent_l.FAILED_REASONS
    assert set(agent_l.SELFCHECK_REASONS.values()) <= set(agent_l.FORMAL_REASONS_L)
    # 三态互斥：failed 那一族与自检那一族没有交集（否则同一个理由码会有两个含义）
    assert not (set(agent_l.FAILED_REASONS) & set(agent_l.SELFCHECK_REASONS.values()))
