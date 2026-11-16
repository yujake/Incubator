# -*- coding: utf-8 -*-
"""判据：彩排路径与真机路径「用的东西实际上是一致的」（业主 2026-11-15 硬要求）。

审计（`temp/sp/REPORT-SP.md`）的读数：现有 14 份 `test_rehearsal_*.py` 里
「真同路径」0 条。这份判据把「一致」拆成五条可机核的判据 + 一条运行期三格，
全部落在 `tests/rehearsal_contract.py` 那张唯一的数据表上：

| # | 判据 | 打红的是什么 |
|---|---|---|
| 1 | 打桩白名单 | `monkeypatch.setattr` / `mock.patch` 的目标不在五类（LLM 缝 / 时间 / 随机 / 子进程 / 网络出口）里 |
| 2 | 入口一致性 | 彩排没有从 `cli.main([...])`（或 `python -m agentflow`）进 |
| 3 | 替身判 | 彩排自造了带 `ask/ask_json/ask_step` 的类，或把 `complete` 替身塞进 `seam=` / `llm=` |
| 4 | 私有调用判 | 直调产品私有方法（`AgentX._y` / `loop._z`） |
| 5 | 三格上下文探针 | 这一趟没有真模型调用 / 钱没有归属 / 不在 `calling_as` 里 |
| 6 | 类型闸（反真空） | `AGENTFLOW_STRICT_SEAM=1` 时把 `_Seam` 塞进装配点 |

## 为什么这五条合起来才等于「同一条路」

单看任何一条都能被绕过：只换缝不换入口（c1 那样）仍然逃掉步循环与收工门；
入口对但自造替身（把 `Secretary` 塞一个 `_Seam`）三格直接没有对象；
三格有对象但账本 0 行时 `unattributed==0` 是第零态假绿。

## `CHAIN_ONLY` 不是豁免

改不成 CLI 入口的旧彩排逐条登记在 `rehearsal_contract.CHAIN_ONLY`（名称 + 理由 +
证明了什么 / 没证明什么），并被两条判据钉住：

- `test_chain_only_files_really_are_not_same_path`：登记的必须确实不是同一条路
  —— 谁把它改好了，这条会红，逼他把它摘出来；
- `test_chain_only_files_are_not_cited_as_rehearsed`：它们不得在文档/报告里被引用为
  「彩排已走通」—— 也就是说，它们不再是「可以拿去当真机前置证据」的名单。
"""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any, Iterator, Mapping

import pytest

import rehearsal_contract as RC

#: 本文件自己也匹配 `test_rehearsal_*.py`；契约数据表里已把它排除，这里只留一个
#: 断言口径（任何静态判据都不该把它自己当成彩排）。
SELF = Path(__file__).name


# ============================================================ 一 静态判据


def _active_files() -> list[Path]:
    """声称「走真机同一条路」的彩排（`CHAIN_ONLY` 之外的）。"""
    return [p for p in RC.rehearsal_files() if p.name not in RC.CHAIN_ONLY]


@pytest.mark.parametrize("path", _active_files(), ids=lambda p: p.name)
def test_no_stub_outside_the_whitelist(path: Path) -> None:
    """1：打桩只许落在五类（LLM 缝 / 时间 / 随机 / 子进程 / 网络出口）+ env 上。

    打桩清单是 `rehearsal_contract.WHITELIST` —— 唯一一份。命中白名单外的第一条
    就红，报 `file:line` + `module.attr` + 「这一层是什么」。
    """
    bad = [t for t in RC.classify_stubs(RC.parse(path), path) if not t.category]
    assert not bad, "\n".join(
        [f"{path.name}：有 {len(bad)} 处打桩落在白名单外 —— 打它等于把被测的那一段换掉，"
         f"绿了也说明不了真机。允许的五类只有：LLM 缝 / 时间源 / 随机源 / 子进程 / 网络出口"
         f"（+ env）。"]
        + [f"  {t.where.file}:{t.where.line}  打桩了 `{t.module or '?'}.{t.attr}` ——"
           f"这一层是「{RC.hint_for(t.module, t.attr)}」；原文：{t.where.text}"
           for t in bad]
        + ["改法：只替换网关（`rehearsal_contract.scripted_seam` 内部是真 LlmSeam + 真 TokenMeter），"
           "别替换产品实现本身。"])


@pytest.mark.parametrize("path", _active_files(), ids=lambda p: p.name)
def test_the_entry_is_the_cli(path: Path) -> None:
    """2：入口必须是 `cli.main(["start"|"run"|"run-agent", ...])`（或 `python -m agentflow`）。

    从 `Conductor.summon` / 直接调 `AgentX` 进去都低一层：那条路没有 `_run_spec` /
    `LlmBackend` / `AgentLoop.run` / 收工门，也没有 `calling_as` 那一格身份。
    """
    tree = RC.parse(path)
    calls = RC.cli_entry_calls(tree, path)
    assert calls, (
        f"{path.name}：这份彩排没有从 CLI 入口进（`cli.main([...])` 一次都没有）。"
        "它直接调了内部函数 ⇒ 它证明的是「那段函数单独能跑」，不是「真机那条路能跑」。"
        "入口必须是 `cli.main([\"start\", \"--mode\", \"research\", \"--root\", <tmp>, "
        "\"--task\", …, \"--max-steps\", N])`（或 `run` / `run-agent`），"
        "只把 `cli._agent_seam_factory` 换成 `rehearsal_contract.scripted_seam_factory(...)`。")
    assert all(c.argv0 in RC.CLI_ARGV0 for c in calls), (
        f"{path.name}：`cli.main` 的第一个词不是真命令（只认 {sorted(RC.CLI_ARGV0)}）："
        f"{[(c.where.line, c.argv0) for c in calls]}")


@pytest.mark.parametrize("path", _active_files(), ids=lambda p: p.name)
def test_no_self_made_model_stub(path: Path) -> None:
    """3：不许自造模型替身（`ask/ask_json/ask_step` 是缝的接口面，`complete` 是网关面）。

    - 定义了 `ask/ask_json/ask_step` 的类 = 换掉了缝（没有 meter / 不落账 /
      不读 ambient / 不查预算）⇒ 一律红；
    - 只有 `complete` 的类是网关替身（允许的那一层），但若它被塞进
      `seam=` / `llm=` 这类「模型对象」的位置 ⇒ 也红 —— 那是把网关当缝用。
    """
    tree = RC.parse(path)
    classes = RC.stub_classes(tree, path)
    seam_stubs = [c for c in classes if c.seam_surface]
    injected = RC.seam_kwarg_uses(tree, path, [c.name for c in classes])
    problems: list[str] = []
    problems += [f"  {c.where.file}:{c.where.line}  自造了缝替身类 `{c.name}"
                 f"({', '.join(c.methods)})` —— 它没有 meter、不落 llm_call、读不到 ambient，"
                 f"三格必然测不到。" for c in seam_stubs]
    problems += [f"  {w.file}:{w.line}  把模型替身塞进了 `seam=` / `llm=` 的位置（构造期直接替换）："
                 f"{w.text}" for w in injected]
    assert not problems, "\n".join(
        [f"{path.name}：模型这一层的替身必须挂在网关上（真 LlmSeam + 预置 JSON）。"]
        + problems
        + ["改法：`rehearsal_contract.scripted_seam(role, replies, store)` 或 "
           "`rehearsal_contract.scripted_seam_factory({...})`。"])


@pytest.mark.parametrize("path", _active_files(), ids=lambda p: p.name)
def test_no_private_product_calls(path: Path) -> None:
    """4：不许直调产品私有方法（`AgentX._y()` / `loop._z()`）—— 那是绕过公开入口。"""
    bad = RC.private_product_calls(RC.parse(path), path)
    assert not bad, "\n".join(
        [f"{path.name}：直调了 {len(bad)} 处产品私有方法。私有方法不是入口："
         "它随时会改名/改语义，而「彩排走通」这句话会继续挂着。"]
        + [f"  {w.file}:{w.line}  {w.text}" for w in bad])


# ============================================================ 二 链外登记


def test_every_chain_only_entry_is_complete() -> None:
    """`CHAIN_ONLY` 每一条都要有名称 + 理由 + 证明了什么 / 没证明什么。"""
    names = {p.name for p in RC.rehearsal_files()}
    missing = sorted(set(RC.CHAIN_ONLY) - names)
    assert not missing, f"CHAIN_ONLY 登记了不存在的彩排文件：{missing}"
    bad: list[str] = []
    for name, item in sorted(RC.CHAIN_ONLY.items()):
        for key in ("chain", "reason", "proves", "does_not_prove"):
            if not str(item.get(key) or "").strip():
                bad.append(f"  {name}: 缺 `{key}`")
        if len(str(item.get("reason") or "")) < 20:
            bad.append(f"  {name}: `reason` 太短（要写清为什么它不是同一条路）")
    assert not bad, "CHAIN_ONLY 有登记不完整的条目：\n" + "\n".join(bad)


@pytest.mark.parametrize("name", sorted(RC.CHAIN_ONLY), ids=lambda n: n)
def test_chain_only_files_really_are_not_same_path(name: str) -> None:
    """反真空：登记进 `CHAIN_ONLY` 的文件必须确实不是同一条路。

    这不是在羞辱旧文件 —— 它在防「登记表腐烂成一句借口」：谁把这些文件改成了
    CLI 入口 + 真缝，这条判据就红，逼他把它从 `CHAIN_ONLY` 里摘出去、重新算证据。
    """
    path = RC.TESTS_DIR / name
    assert path.is_file(), f"CHAIN_ONLY 里的文件不见了：{path}"
    tree = RC.parse(path)
    forms: list[str] = []
    if [t for t in RC.classify_stubs(tree, path) if not t.category]:
        forms.append("白名单外打桩")
    if not RC.cli_entry_calls(tree, path):
        forms.append("入口不是 CLI")
    classes = RC.stub_classes(tree, path)
    if any(c.seam_surface for c in classes) or RC.seam_kwarg_uses(
            tree, path, [c.name for c in classes]):
        forms.append("自造模型替身")
    if RC.private_product_calls(tree, path):
        forms.append("私有直调")
    assert forms, (
        f"{name}：它现在不走任何一条「不是同一条路」的形态 —— 也就是说它可能已经是"
        "CLI 入口 + 真缝了。请把它从 `rehearsal_contract.CHAIN_ONLY` 里摘出去，"
        "它才有资格重新出现在「彩排已走通」的名单里。")


def test_chain_only_files_are_not_cited_as_rehearsed() -> None:
    """它们不得被文档/报告引用为「彩排已走通」（否则红：那份名单是骗人的）。"""
    bad = RC.chain_only_citations()
    assert not bad, "\n".join(
        [f"有 {len(bad)} 处文档/报告把 CHAIN_ONLY 里的文件引用为「彩排已走通」："]
        + [f"  {b['doc']}:{b['line']}  {b['file']}  —— {b['text']}" for b in bad]
        + ["这些文件已登记为「不是真机同一条路」（见 rehearsal_contract.CHAIN_ONLY）："
           "把它们从「可当真机前置证据」的名单里剔除，或者把它们改成 CLI 入口 + 真缝。"])


def test_the_contract_applies_to_files_that_claim_same_path() -> None:
    """口径自检：`is_rehearsal_module` 与静态判据用的是同一张表（否则两条判据会漂）。"""
    for path in RC.rehearsal_files():
        claimed = RC.is_rehearsal_module(path)
        assert claimed == (path.name not in RC.CHAIN_ONLY), path.name
    assert not RC.is_rehearsal_module(RC.TESTS_DIR / SELF), "判据本体不许把自己当彩排"


# ============================================================ 二·五 正面登记


@pytest.mark.parametrize("name", sorted(RC.SAME_PATH_EVIDENCE), ids=lambda n: n)
def test_registered_same_path_evidence_is_really_same_path(name: str) -> None:
    """⑥ 正面登记：真机前置证据必须不是 CHAIN_ONLY，且四条静态判据全过。

    这是 `CHAIN_ONLY` 的补集里被显式点过名的那一批：谁把它塞进 `CHAIN_ONLY`
    （"改不成 CLI 入口"的黑名单），这一条先红；谁把它的入口/缝换掉，四条静态判据红。
    它同时要求 `is_rehearsal_module` 认它 —— 那是三格探针生效的唯一开关
    （不认识它 = 三格没有对象，等于把运行期那一格静默摘掉）。
    """
    path = RC.TESTS_DIR / name
    assert path.is_file(), f"登记为真机前置证据的文件不见了：{path}"
    assert name not in RC.CHAIN_ONLY, (
        f"{name} 同时出现在 CHAIN_ONLY 里 —— 一份彩排不能既是「不是同一条路」"
        "又是「真机前置证据」")
    assert RC.is_rehearsal_module(path), (
        f"{name} 没被 `is_rehearsal_module` 认 ⇒ 三格探针不会对它生效"
        "（那等于把它最要紧的那一格静默摘掉了）")
    tree = RC.parse(path)
    assert RC.cli_entry_calls(tree, path), f"{name}：登记为证据，却没有 CLI 入口"
    bad = [t for t in RC.classify_stubs(tree, path) if not t.category]
    assert not bad, f"{name}：打桩落在白名单外：{[(t.where.line, t.attr) for t in bad]}"
    classes = RC.stub_classes(tree, path)
    assert not any(c.seam_surface for c in classes), f"{name}：自造了缝替身"
    assert not RC.seam_kwarg_uses(tree, path, [c.name for c in classes]), (
        f"{name}：把模型替身塞进了 `seam=` / `llm=` 的位置")
    assert not RC.private_product_calls(tree, path), f"{name}：直调了产品私有方法"


# ============================================================ 三 类型闸（反真空）


class _DuckSeam:
    """刻意的假缝（只有 `ask_json`）：类型闸必须拒它。"""

    def ask_json(self, prompt: str, **_kw: Any) -> tuple[dict[str, Any], Any]:
        return {"well_formed": True, "decision": "T2"}, _DuckCall()


class _DuckCall:
    ok = True
    problem = ""
    detail = ""


def _workspace(tmp_path: Path) -> Any:
    from agentflow.store import Store

    st = Store(tmp_path / "ws")
    st.init()
    return st


def test_the_type_gate_refuses_a_duck_typed_seam(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """6：`AGENTFLOW_STRICT_SEAM=1` 时，`_Seam` 塞进装配点 ⇒ `TypeError`（反真空）。

    这一条同时证明三件事：闸默认关（历史用法不变）、开了之后真的拒、
    真 `LlmSeam` 照常通过。它把 §3.3 那 22 处「构造期直接替换」一次判红 ——
    静态扫描抓不到那些，只有类型闸抓得到。
    """
    from agentflow import cli, llmseam as LS
    from agentflow.agent_f import AgentF
    from agentflow.agent_loop import LlmBackend
    from agentflow.agent_v import AgentV
    from agentflow.secretary import Secretary

    st = _workspace(tmp_path)
    monkeypatch.delenv("AGENTFLOW_STRICT_SEAM", raising=False)
    # 默认关：旧用法不炸（否则套件里几百处历史替身会一起红 —— 那不是本判据要的）
    Secretary("B", root=st.root, store=st, seam=_DuckSeam(), enable_model=True)
    monkeypatch.setenv("AGENTFLOW_STRICT_SEAM", "1")
    for label, make in (
        ("Secretary.__init__", lambda: Secretary("B", root=st.root, store=st,
                                                seam=_DuckSeam(), enable_model=True)),
        ("AgentV.__init__", lambda: AgentV(st, workspace_root=st.root, llm=_DuckSeam())),
        ("AgentF.__init__", lambda: AgentF(st, llm=_DuckSeam(),
                                          config={"workspace_root": st.root})),
        ("LlmBackend.seam_factory", lambda: LlmBackend(
            inner=object(), loops={}, session_root=Path(str(st.root)),
            seam_factory=lambda role: _DuckSeam())._seam("D")),
        ("cli._agent_seam_factory", lambda: _cli_factory_with_duck(monkeypatch, st)),
    ):
        with pytest.raises(TypeError, match="不是产品那个"):
            make()
    # 正控：真 LlmSeam 在严格档下照常装配（闸不是"一律拒"）
    real = RC.scripted_seam("secretary:B", ['{"decision": "T2"}'], st)
    Secretary("B", root=st.root, store=st, seam=real, enable_model=True)
    assert type(real) is LS.LlmSeam
    # 子类同样是「另一个对象」（刻意 `type(...) is`，不是 `isinstance`）：它会覆盖
    # `ask`，于是预算闸/账本/事件可以被换掉而类型看起来"还是 LlmSeam"。
    class _SubSeam(LS.LlmSeam):
        pass

    with pytest.raises(TypeError, match="不是产品那个"):
        LS.assert_real_seam(_SubSeam(role="M", session_root=Path(str(st.root))),
                            where="判据：子类")


def _cli_factory_with_duck(monkeypatch: pytest.MonkeyPatch, st: Any) -> Any:
    """在严格档下让 `cli._agent_seam_factory` 拿到一个 duck-type（模拟被替换的工厂）。"""
    from agentflow import cli, llmseam as LS

    monkeypatch.setattr(LS.LlmSeam, "for_role", classmethod(lambda cls, *a, **k: _DuckSeam()))
    return cli._agent_seam_factory("M", root=Path(str(st.root)), sid=None,
                                   usd_budget=None, store=st)


# ============================================================ 四 运行期三格


def _reconcile_of(roots: list[str]) -> dict[str, Any]:
    """把这一趟碰过的每个工作区根的账本读数合成一份（读不出 ⇒ 记 `unreadable`）。"""
    from agentflow.store import Store
    from agentflow.modelcost import reconcile_usage

    agg: dict[str, Any] = {"ledger_rows": 0, "task_rows": 0, "unattributed": 0,
                           "unattributed_usd": 0.0, "dangling": [], "problems": []}
    for root in sorted(set(roots)):
        try:
            got = reconcile_usage(Store(Path(root)))
        except Exception as exc:  # noqa: BLE001 —— 读不出是一条读数，不是"没有账"
            agg["problems"].append(f"{root}: 账本读不出（{type(exc).__name__}: {exc}）")
            continue
        agg["ledger_rows"] += int(got.get("ledger_rows") or 0)
        agg["task_rows"] += int(got.get("task_rows") or 0)
        agg["unattributed"] += int((got.get("unattributed") or {}).get("count") or 0)
        agg["unattributed_usd"] += float((got.get("unattributed") or {}).get("usd") or 0.0)
        agg["dangling"] += list(got.get("dangling") or [])
    return agg


@contextlib.contextmanager
def triplet_probe(request: pytest.FixtureRequest) -> Iterator[dict[str, Any]]:
    """包住 `LlmSeam.ask`（包装后照常调用），收尾断言三格。

    每次调用记 `(explicit, ambient, current_caller_role(), wired, has_meter)`；
    收尾先判「有没有对象」（`live` 空 ⇒ 这一趟根本没走那条路），再断言三格：

    ① `resolved = explicit or ambient` 全部非空
       —— 注意不要求 ambient 非空：真机顶趟走显式号（`open_top_level_run`），
       写成"ambient 必须非空"会把真机判红、把彩排判绿。
    ② 至少一次 `current_caller_role() != ""`（`⇔` 在 `calling_as` 里）
       —— 挂点是 `agent_loop.py:13575`（循环本体）/ `:11659`（工具分发）；
       从 `LocalBackend.call` 进只有 ambient 没有 caller_role，那不是同一条路。
    ③ `ledger_rows > 0` 且 `unattributed.count == 0` 且 `dangling` 空
       —— 0 行时 0 是「第零态假绿」，不是「干净」。
    """
    from agentflow import conductor as CND
    from agentflow import llmseam as LS

    seen: list[dict[str, Any]] = []
    orig = LS.LlmSeam.ask

    def ask(self: Any, prompt: str, **kw: Any) -> Any:
        explicit = str(kw.get("task_id") or "").strip()
        seen.append({
            "role": str(getattr(self, "role", "") or ""),
            "explicit": explicit,
            "ambient": LS.ambient_task_id(),
            "caller_role": CND.current_caller_role(),
            "wired": bool(getattr(self, "wired", False)),
            "has_meter": getattr(self, "meter", None) is not None,
            "root": str(getattr(self, "session_root", "") or ""),
        })
        return orig(self, prompt, **kw)

    LS.LlmSeam.ask = ask
    try:
        yield {"seen": seen}
    finally:
        LS.LlmSeam.ask = orig

    node = request.node
    live = [r for r in seen if r["wired"]]
    print(f"[三格] {node.nodeid}  ask 次数={len(seen)}  live={len(live)}")
    assert live, (
        f"{node.name}：这一趟一次真模型调用都没有（`LlmSeam.ask` 0 次 / 全是没接线的缝）"
        " ⇒ 三格没有对象。这是「没走那条路」，不是「走了且干净」。")
    resolved = [r["explicit"] or r["ambient"] for r in live]
    assert all(resolved), (
        "格①失败：有模型调用既没有显式 task_id、`ambient_task_id()` 也是空串 ⇒ 这一笔钱无处归属。"
        f"逐次读数（explicit/ambient）：{[(r['explicit'], r['ambient']) for r in live if not (r['explicit'] or r['ambient'])]}")
    inside = [r for r in live if r["caller_role"]]
    assert inside, (
        "格②失败：没有任何一次模型调用发生在 `calling_as` 上下文里"
        f"（current_caller_role() 全为空：{sorted({r['caller_role'] for r in live})}）。"
        "真机的挂点是 `LlmBackend.call`（agent_loop.py:13575）与 `_do_tool`（:11659）；"
        "若你从 `LocalBackend.call` 进，只有 ambient 没有 caller_role —— 那不是同一条路。")
    got = _reconcile_of([r["root"] for r in live])
    print(f"[三格] {node.nodeid}  ①resolved={len(resolved)}/{len(live)}  "
          f"②caller_role={sorted({r['caller_role'] for r in inside})}  "
          f"live_meter={sum(1 for r in live if r['has_meter'])}  "
          f"③ledger_rows={got['ledger_rows']} unattributed={got['unattributed']} "
          f"dangling={len(got['dangling'])}")
    assert got["ledger_rows"] > 0, (
        "格③失败：这一趟 usage_ledger 一行都没有 ⇒ `unattributed==0` 是第零态（假绿）。"
        f"说明调用没接 meter，或走的是不落账的替身缝。读数：{got}")
    assert got["unattributed"] == 0, (
        f"格③失败：{got['unattributed']} 笔账无主（${got['unattributed_usd']}）—— "
        "判据要求 0 笔无主（要么 0 笔、要么全部点名，这里要求 0 笔）。")
    assert not got["dangling"], (
        f"格③失败：账本挂着 tasks 里不存在的号 {got['dangling']}（那些钱没有一行台账号可回写）。")
    # 这里刻意不断言每条账都有 meter：`has_meter=False` 的缝在格③的 0 行上已经
    # 被抓住（没有 meter 就没有账本行）—— 两处断言同一件事会让失败信息分不清该修哪一处。
    json.dumps(got)      # 读数必须可序列化（进报告/日志时不炸）
