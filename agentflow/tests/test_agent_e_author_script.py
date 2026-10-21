# -*- coding: utf-8 -*-
"""S-10(a)：E 从判据写一份核验脚本（`author_script`）—— 补齐"造出的子目标必然停住"那一跳。

## 它补的是什么

`draft/44` S-10：F 的 `counterexample_request` 造出的 E 子目标带着判据（`script_spec` = criterion/params/expected_bound）
却没有 `script_path` ⇒ `_deploy_e` 只能回一句"没有给 script_path ⇒ 未推进"，那条子目标原地打转直到计划 `stalled`。补法是让 E
按判据把脚本写出来（`author_script`），落进工作区，然后照常跑它。

## 五条硬条件（本文件逐条钉）

1. 只做生成，判读一个字不改（FC-16）：`run_experiment` / `_derive` / `_parse_conclusion` 那一侧不许出现任何缝调用 —— 判据是"跑一次判读，缝的调用计数为
0"；
2. 脚本必须落进工作区（`code/`），不是临时目录：落点要能被 `run_experiment(script_path=…)` 与 `proof_location` 认出来（`check_formal`
把源码放临时目录那次踩过这个坑）；
3. 三态不许折成"原地打转"：`no_seam` / `bad_spec` / `bad_source` / `write_failed` / `judge_*` 各自出现在 `blocked_reason` 里，
且都不返回 `script_path`；
4. 反负控："没判据 ⇒ 不写脚本"：没有 `script_spec` 的 E 子目标不许被凭空生成一份脚本（否则"写脚本"这件事会掩盖"根本不知道该判什么"）；
5. 端到端：判据在、脚本不在 ⇒ 改前红（no_change、盘上无脚本、无实验行）；改后：盘上有脚本 + `experiments` 有条目 + 子目标里看得见 `script_path`。

离线：缝是假模型（返回写死的 JSON），判据不由真模型决定。"""
from __future__ import annotations

import json
from pathlib import Path

from agentflow import llmseam
from agentflow.agent_e import AgentE
from agentflow.agent_f import AgentF
from agentflow.store import Store

#: 一份最小的合格核验脚本（必须自己打印 `REPRO_RESULT:` 那一行）。
SCRIPT = (
    "import json\n"
    "print('REPRO_RESULT: ' + json.dumps({\n"
    "    'result': 'supports',\n"
    "    'observations': {'n': 18, 'm': 3, 'k': 6},\n"
    "    'counterexample': None,\n"
    "    'negation_kind': 'not_proved',\n"
    "    'bound': {'n': 18},\n"
    "    'strategy': 'brute force',\n"
    "    'scaling': [{'n': 18, 'sec': 0.01, 'objects': 5}]}))\n"
)

#: 一份"不会说结论"的脚本（没有 `REPRO_RESULT`）—— `bad_source` 那一档。
SCRIPT_NO_VERDICT = "print('我算完了')\n"

SPEC = {"criterion": "每条边的 k-圈数 >= 2", "params": "m=3, k=6, n<=18",
        "expected_bound": "n_max=18"}


def _reply(source: str) -> str:
    return json.dumps({"source": source, "why": "这份脚本枚举小情形并打印结论"})


class FakeLLM:
    """最小模型缝（`judge.judge_json` 的调用约定：`complete(prompt) -> str`）。"""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if not self.replies:
            raise AssertionError("模型被调用的次数比剧本多")
        return self.replies.pop(0)


class BrokenLLM:
    """每次调用都炸（走 `judge_failed:<类名>` 那一档）。"""

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        raise RuntimeError("网关炸了")


def _e(store: Store, llm=None) -> AgentE:
    return AgentE(store, config={"workspace_root": store.root}, llm=llm)


def _f(store: Store, llm=None) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root}, llm=llm)


def _codes_on_disk(root: Path) -> list[str]:
    """工作区里 `code/` 下的脚本（没有就空列表）。"""
    d = Path(root) / "code"
    return sorted(p.name for p in d.glob("*.py")) if d.is_dir() else []


# --------------------------------------------------------------- 条件 2 + 5：落点与可跑

def test_author_script_lands_under_code_and_the_reading_path_can_run_it(store: Store):
    """E 按判据写出的脚本落在 `code/` 下，并且 `run_experiment` 能直接跑它。

    若这条破了：脚本落在临时目录里 ⇒ `check_formal` 认不出它、`run_experiment` 也接不上，
    于是"写了脚本"与"有实验读数"之间永远差一步（这一步就是 S-10(a) 要补的那一步）。
    """
    llm = FakeLLM(_reply(SCRIPT))
    e = _e(store, llm=llm)
    out = e.author_script(SPEC, sid="s2")

    assert out["ok"] is True, out
    assert out["script_path"] == "code/attack_s2.py", out
    assert (Path(store.root) / "code" / "attack_s2.py").is_file()
    assert out["sha256"], out
    # 缝用了一次（生成），且提示词里念了判据（"照着判据写"这件事必须真的发生）
    assert llm.calls == 1, llm.calls
    assert "每条边的 k-圈数 >= 2" in llm.prompts[0], llm.prompts[0]

    # 判读路径接得上：同一条 `script_path` 真跑一次，落一行实验
    res = e.run_experiment("每条边的 k-圈数 >= 2", "PK-S10A#s2", out["script_path"],
                           method="numeric")
    assert res["recorded"] is True, res
    assert res["result"] == "supports", res
    row = next(r for r in store.rows("experiments") if r["experiment_id"] == res["experiment_id"])
    assert row["code_path"] == "code/attack_s2.py", row["code_path"]


# --------------------------------------------------------------- 条件 1：判读路径无缝调用

def test_the_reading_path_never_calls_the_seam(store: Store):
    """FC-16：判读（跑脚本 → 推导结论）一次模型都不叫。

    做法：把缝换成一个"一叫就记一笔"的假模型，然后跑一次已经存在的脚本 ——
    判读若偷偷问了模型（哪怕只是为了"解释一下这个读数"），计数就不再是 0。
    若这条破了：数值实验的判读过模型 ⇒ 同一条脚本两次跑出两个结论，而"确定性"这句话
    只是注释里的一句话（FC-16 的全部内容）。
    """
    llm = FakeLLM()  # 没有任何剧本：被调用就会炸
    e = _e(store, llm=llm)
    d = Path(store.root) / "code"
    d.mkdir(parents=True, exist_ok=True)
    (d / "given.py").write_text(SCRIPT, encoding="utf-8")

    res = e.run_experiment("判据", "PK-FC16#s1", "code/given.py", method="numeric")
    assert res["result"] == "supports", res
    assert llm.calls == 0, f"判读路径叫了模型 {llm.calls} 次（FC-16）"


# --------------------------------------------------------------- 条件 3：三态

def test_author_script_is_three_state_and_never_returns_a_path(store: Store):
    """五种"没写成"各归各的码，且一个都不许返回 `script_path`。

    若这条破了：`no_seam` 与 `bad_source` 折成同一句"没写成" ⇒ 前者要去接线、后者要改脚本，
    两件完全不同的事在读数上长得一样（真机里 F 就是据此把子目标原地转圈）。
    """
    # (a) 没接缝
    out = _e(store, llm=None).author_script(SPEC, sid="s1")
    assert (out["ok"], out["reason"], out["script_path"]) == (False, "no_seam", ""), out
    # (b) 判据不完整（缺 expected_bound）
    out = _e(store, llm=FakeLLM()).author_script({"criterion": "x"}, sid="s1")
    assert (out["ok"], out["reason"], out["script_path"]) == (False, "bad_spec", ""), out
    # (c) 模型给的脚本不合格（不会说结论）
    out = _e(store, llm=FakeLLM(_reply(SCRIPT_NO_VERDICT))).author_script(SPEC, sid="s1")
    assert (out["ok"], out["reason"], out["script_path"]) == (False, "bad_source", ""), out
    assert "REPRO_RESULT" in out["note"], out
    # (d) 缝炸了 ⇒ `judge_failed:*`（不是"没有结论"）
    out = _e(store, llm=BrokenLLM()).author_script(SPEC, sid="s1")
    assert out["ok"] is False and out["reason"].startswith("judge_failed"), out
    assert out["script_path"] == "", out
    # (e) 坏 JSON ⇒ `judge_bad_json`
    out = _e(store, llm=FakeLLM("这不是 JSON")).author_script(SPEC, sid="s1")
    assert out["ok"] is False and out["reason"] == "judge_bad_json", out
    # 五档跑完，工作区里一个脚本都不该多出来（"没写成"不许留下半成品）
    assert _codes_on_disk(store.root) == [], _codes_on_disk(store.root)


# --------------------------------------------------------------- 条件 4 + 5：端到端

def _plan_for_e(f: AgentF, *, with_spec: bool) -> str:
    sg: dict = {"sid": "s1", "text": "按判据跑实验", "owner": "E", "testable": "n<=18"}
    if with_spec:
        sg["script_spec"] = dict(SPEC)
    return f.create_plan("难题：判据写脚本", f"PK-S10A-{int(with_spec)}", subgoals=[sg])["plan_id"]


def test_deploy_e_authors_the_script_from_the_spec_then_runs_it(store: Store):
    """端到端：判据在、脚本不在 ⇒ E 写脚本 → 跑出实验 → 子目标里看得见 `script_path`。

    改前的读数（本条的第一个断言就是它）：`outcome == "no_change"`、盘上没有脚本、
    `experiments` 表里没有行 —— 子目标只剩"没有给 script_path ⇒ 未推进"这一句。
    """
    llmseam.set_role_seam("E", FakeLLM(_reply(SCRIPT)))
    try:
        f = _f(store)
        pid = _plan_for_e(f, with_spec=True)
        out = f.step(pid)
    finally:
        llmseam.set_role_seam("E", None)

    assert out["outcome"] == "progress", out
    assert _codes_on_disk(store.root), "盘上没有脚本 ⇒ 这一跳没落地"
    rows = store.rows("experiments")
    assert len(rows) == 1, rows
    assert rows[0]["result"] == "supports", rows[0]
    sg = next(s for s in store.rows("attack_plans")[0]["subgoals"] if s["sid"] == "s1")
    assert sg["script_path"] == "code/attack_s1.py", sg
    assert sg.get("experiment_ids"), sg


def test_deploy_e_writes_nothing_without_a_spec(store: Store):
    """反负控：没有判据的 E 子目标 ⇒ 一份脚本都不许写。

    若这条破了：框架会替"不知道该判什么"的子目标凭空生成一个脚本 ——
    那比原地不动更坏：它会把"没有判据"伪装成"有实验在跑"。
    """
    llmseam.set_role_seam("E", FakeLLM(_reply(SCRIPT)))
    try:
        f = _f(store)
        out = f.step(_plan_for_e(f, with_spec=False))
    finally:
        llmseam.set_role_seam("E", None)

    assert _codes_on_disk(store.root) == [], _codes_on_disk(store.root)
    assert store.rows("experiments") == [], store.rows("experiments")
    assert out["outcome"] == "no_change", out
    assert "script_path" in out["reason"], out
    assert "criterion=" not in out["reason"], out


def test_deploy_e_surfaces_the_authorship_reason_when_the_seam_is_missing(store: Store):
    """条件 3 的端到端那一半：没接缝时 `blocked_reason` 里要看得见 `no_seam`。

    若这条破了：读数仍是一句"缺 script_path"，没人知道这一条缺的是模型缝而不是脚本 ——
    那正是 S-10 记的"原地打转"（每一轮都撞同一句话、而那句话指不到要动的地方）。
    """
    llmseam.set_role_seam("E", None)
    f = _f(store, llm=FakeLLM())  # F 自己有缝，E 没有 —— 两条缝互不借用
    out = f.step(_plan_for_e(f, with_spec=True))

    assert out["outcome"] == "no_change", out
    assert "no_seam" in out["reason"], out
    sg = next(s for s in store.rows("attack_plans")[0]["subgoals"] if s["sid"] == "s1")
    assert "no_seam" in str(sg.get("blocked_reason") or ""), sg
    assert _codes_on_disk(store.root) == [], _codes_on_disk(store.root)
