# -*- coding: utf-8 -*-
"""F 的推理是它的工作方式，不是一个开关（业主 2026-10-26 晚的裁定）。

业主原话（唯一权威，逐字）：
```
「？？？F怎么还默认不搞推理？F的职责是什么？D到B没有路吗？加」
「没有默认开，这个就是F的工作方式，没有开关的说法。」
```

## 改前是什么形态（逐条查实的死结）

`--attack-reasoning` 默认关 ⇒ `agent_f.default_llm()` 返回 None ⇒ `_deploy` 落到
`UNWIRED_OWNERS` 那一支 ⇒ 真机 10 个计划全是 `rounds=1`、`product="dead_end"`、
`reason="缺工具"`、detail 逐字「本框架尚未接线自动推理」⇒ F 从来没做过一次推理、
从没交过 proof、盘上 0 份 `reports/f-proof-*.md`。

## 判据

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a 默认有缝 | 不传任何开关 ⇒ `default_llm()` 非 None，且它是带记账（`meter`）的真缝 | 改前默认 None |
| a2 不再落未接线 | `_deploy` 在运行形态里不再产出"未接线"的 `dead_end` | 改前每一轮都是它 |
| b 缺缝要明说 | 把缝打桩成 None（只允许出现在负控里）⇒ 明确报"缺缝"，不是静默 `no_change` | 改前那一支说的是"未接线"且带一个不存在的开关 |
| c 反真空 | 打桩一个假缝 ⇒ 真机路径真发一次调用（打桩计数） | 改前缝根本到不了 F 手上 |
| 守卫 1 | `UNWIRED_OWNERS` 里没有 F（连"F 可能未接线"这条路都不存在） | 改前是 `("C", "D", "F")` |
| 守卫 2 | 全仓字面量清零：那个开关的标识符与 flag 只允许出现在带裁定日期的文档串里；再给一条负控（注入一行 ⇒ 守卫必红） | 改前 `if attack_reasoning:` 就是那道闸 |

零模型钱：全部用假缝 / 真缝但不配 key（真缝不配 key 时 `ask_json` 自己报"没接线"，
不发网络请求）。
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import agent_f as AF
from agentflow import host
from agentflow.store import Store

#: 那个被删掉的开关的字面量（拼出来而不是写死：这一份判据自己也要通过它自己的扫描
#: —— 源码里出现一次就红，而判据本体不能给自己开后门）。
_NAME = "attack" + "_reasoning"
_OLD_FLAG = "--" + _NAME.replace("_", "-")
#: 裁定日期。守卫只允许"带这个日期的文档串"提到那个开关（解释它为什么被删）。
_RULING_DATE = "2026-10-26"


class CountingSeam:
    """假缝（`judge_json` 认 `complete(prompt) -> str`）：记录被问了几次。"""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


def _plan(f, *, key: str = "PK-F-WORKING") -> str:
    got = f.create_plan("难题：证明某个小结论", key, subgoals=[
        {"sid": "s1", "text": "把这个结论一步步证出来", "owner": "F",
         "testable": "手稿的依赖段每条引用一行"}])
    assert got.get("created") is True, got
    return str(got["plan_id"])


def _proof_payload() -> dict:
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "把子目标直接写成两步：一步前提、一步由前提得结论",
            "steps": [{"n": 1, "text": "设 n 是正整数（这一轮的前提）。", "cites": [],
                       "assumption": True},
                      {"n": 2, "text": "由前提，n 的阶乘为正（前提）。", "cites": [],
                       "assumption": True}]}


def _wired(tmp_path: pathlib.Path, store: Store, **kw):
    return host.wired_llm_conductor(
        store, session_root=tmp_path, sid="f-working", max_steps=1,
        workspace_root=tmp_path, **kw)


# ------------------------------------------------------------------ a 默认有缝


def test_no_switch_at_all_still_gives_f_a_seam(tmp_path: pathlib.Path, store: Store) -> None:
    """a 不传任何开关 ⇒ `default_llm()` 非 None，而且它带记账（花销照常进 usage 台账）。

    改前红：默认档下 `default_llm()` 是 None（当年那个开关是唯一让它得到
    缝的东西；它已于 2026-10-26 删除）。
    """
    from agentflow.llmseam import LlmSeam

    AF.set_default_llm(None)
    _wired(tmp_path, store)          # 不传那个开关（它已经不存在），也不传 seam_factory
    seam = AF.default_llm()
    assert seam is not None, "不传任何开关时 F 仍然没有推理缝（改前那一支还在）"
    assert isinstance(seam, LlmSeam), (
        f"F 拿到的不该是别的东西：{type(seam).__name__}")
    assert getattr(seam, "meter", None) is not None, (
        "F 的缝没有挂 TokenMeter ⇒ 攻击轮推理的花销不会进 usage 台账（不许绕过记账）")


def test_the_old_flag_is_gone_and_f_gets_its_seam_without_it(tmp_path: pathlib.Path,
                                                            store: Store) -> None:
    """守卫 2：那个命令行开关已被删除，而 F 的缝照旧无条件装起来。

    改前红：那个开关的 `False` 分支是唯一让 `f_llm` 保持 None 的地方
    （所以改前"不传开关"与"传 False"都会让 F 没有缝）。
    """
    from agentflow.cli import build_parser

    seen: list[str] = []

    def _factory(role: str):
        seen.append(role)
        return CountingSeam({"product": "reduction", "strategy": "归约",
                             "why_strategy": "拆小",
                             "new_subgoals": [{"goal": "证 n<=3", "testable": "枚举"}]})

    AF.set_default_llm(None)
    _wired(tmp_path, store, seam_factory=_factory)
    assert "F" in seen, "不传任何开关时 F 的缝没有被造出来"
    assert AF.default_llm() is not None
    # 那个 flag 已经不存在：传它会被 argparse 当场拒（不是"解析了但没用"）。
    with pytest.raises(SystemExit):
        build_parser().parse_args(["run-agent", "M", "--task", "x", _OLD_FLAG])


def _literal_hits(root: pathlib.Path) -> list[tuple[str, int, str]]:
    """扫一遍 `root` 下的 `.py`：那个开关的字面量出现在哪里。

    允许出现的唯一形态：带裁定日期的文档串（模块 / 类 / 函数的第一条语句）——
    它解释"曾经有过这个开关、为什么删掉"。注释、普通字符串、标识符、argparse
    参数一律算命中（返回 `(文件, 行号, 原文)`）。
    """
    hits: list[tuple[str, int, str]] = []
    for path in sorted(pathlib.Path(root).rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if _NAME not in text and _OLD_FLAG not in text:
            continue
        allowed: set[int] = set()
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                continue
            body = getattr(node, "body", None) or []
            if not body:
                continue
            first = body[0]
            if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                continue
            if _RULING_DATE in str(first.value.value):
                for line_no in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                    allowed.add(line_no)
        for line_no, line in enumerate(text.splitlines(), 1):
            if _NAME in line or _OLD_FLAG in line:
                if line_no not in allowed:
                    hits.append((str(path), line_no, line.strip()))
    return hits


def test_the_old_switch_literal_is_gone_from_source_and_tests() -> None:
    """守卫 2（全仓字面量清零）：`src/` 与 `tests/` 里不再出现那个开关的标识符或 flag。

    为什么连标识符一起扫：只删命令行 flag 时，配置项 / 参数表 / 分支还留着同一个名字
    —— 那件事没有任何读数会报，而它正是"开关又以另一个名字回来了"的入口。
    唯一豁免是带裁定日期的文档串（它就是本文件的说明与历史记录）。
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    hits = _literal_hits(root / "src") + _literal_hits(root / "tests")
    assert not hits, (
        f"那个开关的字面量还在 {len(hits)} 处（只允许出现在带 {_RULING_DATE} 的文档串里）："
        + "；".join(f"{p}:{ln} {text[:60]}" for p, ln, text in hits[:8]))


def test_the_scanner_really_scans(tmp_path: pathlib.Path) -> None:
    """守卫 2 的负控：在任意位置注入一行赋值 ⇒ 扫描器必须报出来（证明它真扫）。

    业主的原话是"在 src 任意位置注入一行那个标识符的赋值 ⇒ 守卫必红"。
    这一条在临时目录里做同一件事：不碰真树，但走的是同一个扫描器。
    """
    probe = tmp_path / "probe.py"
    probe.write_text(f"{_NAME} = True\n", encoding="utf-8")
    hits = _literal_hits(tmp_path)
    assert hits, "扫描器没抓到注入的那一行 ⇒ 守卫是空的"
    assert hits[0][0].endswith("probe.py") and hits[0][1] == 1, hits


def test_unwired_owners_does_not_contain_f() -> None:
    """守卫 1：`UNWIRED_OWNERS` 里没有 F（连"F 可能未接线"这条路都不能存在）。"""
    assert "F" not in AF.UNWIRED_OWNERS, AF.UNWIRED_OWNERS
    assert AF.UNWIRED_OWNERS == ("C", "D"), AF.UNWIRED_OWNERS


# ------------------------------------------------------------------ a2 不再落未接线


def test_a_f_round_never_lands_the_not_wired_dead_end(tmp_path: pathlib.Path,
                                                      store: Store) -> None:
    """a2 运行形态：F 出场就有缝 ⇒ 这一轮不再产出"未接线"的 `dead_end`。

    真缝不配 key 时 `ask_json` 自己报"没查成"（不发网络请求）：那一档是
    `no_change` + `judge_*`，不是"本框架尚未接线自动推理"。
    改前红：这一轮落 `dead_end(缺工具)` + detail 逐字"本框架尚未接线自动推理"。
    """
    AF.set_default_llm(None)
    _wired(tmp_path, store)
    seam = AF.default_llm()
    f = AF.AgentF(store, config={"workspace_root": str(store.root)}, llm=seam)
    out = f.step(_plan(f))

    rec = store.rows("attack_plans")[0]["history"][-1]
    detail = str(rec.get("detail") or "")
    assert "本框架尚未接线自动推理" not in detail, detail
    assert "未接线" not in detail, detail
    assert not (rec.get("product") == "dead_end"
                and rec.get("dead_end_reason") == "缺工具"), rec
    assert out.get("outcome") == "no_change", out


# ------------------------------------------------------------------ b 缺缝要明说


def test_a_stubbed_none_seam_says_the_seam_is_missing(tmp_path: pathlib.Path,
                                                      store: Store) -> None:
    """b 负控（只允许出现在测试打桩里）：缝被置 None ⇒ 明确报"缺缝"。

    为什么这一条必须有：把"F 默认有缝"改完之后，最容易出的错是"没有缝时静默地
    什么都不做"（`no_change` 一句、没有产物、没有理由）—— 那正是改前真机 10 个
    计划的形态。这里钉三件：有产物（`dead_end`）、点名缺的是缝、返回值里有
    `missing_seam=True` 可机械判读。
    """
    f = AF.AgentF(store, config={"workspace_root": str(store.root)}, llm=None)
    out = f.step(_plan(f))

    rec = store.rows("attack_plans")[0]["history"][-1]
    assert rec.get("product") == "dead_end", rec
    assert rec.get("dead_end_reason") == AF.AgentF.SEAM_MISSING_REASON, rec
    assert "缺缝" in str(rec.get("detail") or ""), rec
    assert out.get("missing_seam") is True, out
    assert out.get("outcome") == "no_change", out


# ------------------------------------------------------------------ c 反真空


def test_a_stub_seam_really_receives_one_call(tmp_path: pathlib.Path, store: Store) -> None:
    """c 反真空：装配层打桩一个假缝 ⇒ 真机路径（工具层 `attack.step`）真发一次调用。

    走的是 M 派 `F.step` 的那条路（`attack_tools._agent_for` → `AgentF(store)` ←
    `agent_f.default_llm()`）：改前不传任何开关时 `default_llm()` 是 None ⇒
    这一轮一次调用都不会发生（dead_end"未接线"）；现在它拿到装配期登记的缝、真问一次。
    """
    AF.set_default_llm(None)
    seam = CountingSeam(_proof_payload())
    _wired(tmp_path, store, seam_factory=lambda role: seam)
    reg = AF.install_f_tools(store)
    plan = AF.AgentF(store).create_plan("难题", "PK-TOOL", subgoals=[
        {"sid": "s1", "text": "把这个结论一步步证出来", "owner": "F",
         "testable": "手稿的依赖段每条引用一行"}])
    out = reg.call("attack.step", plan_id=str(plan["plan_id"]))
    assert out.ok, out

    assert len(seam.prompts) == 1, (
        f"工具层那条路没有真的问过一次（{len(seam.prompts)} 次）—— 缝没到 F 手上")
    row = store.rows("attack_plans")[0]
    rec = row["history"][-1]
    assert rec.get("product") == "proof", rec
    assert str(rec.get("statement_id") or ""), rec


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))

