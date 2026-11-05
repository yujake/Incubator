# -*- coding: utf-8 -*-
"""判据：V 的「只读」边界是「不能改别人的东西」，它可以写「自己维护的那张表」。

## 这条判据补的是哪一道裂缝（2026-11-05）

`verify.verify_proof` 改前声明 `side_effect="read"`，而它实际写：
`verifications/<命题号>.jsonl`（`verifications.record_verification`）、未在册档的签信封
`out/vsigns/<正文 sha>.json`（`vsigns.issue`），并让收方秘书把签块盖回送审的那份手稿
（`vsigns.land`）。三者都是「工作区写」，所以真值是 `write_local`。
仓库此前用一句「V 不写表，只产出一份文件」把这件事解释过去 —— 那句话与
`tools/base.py::EFFECT` 对轴的定义（数据表 / 工作区）打架。

## 这一批的口径（业主 2026-11-05）

- 只读角色 = 「不能改别人的东西」（别人的数据表 / 别人的稿）；
- 它可以写「自己维护的那张表」（`verifications` 凭据台账）与自己的产物（签的侧文件/签块）；
- 所以 `verify.verify_proof` 声明 `write_local` 是对的，V 拿到它是
  `tools.base.READONLY_CALL_EXCEPTIONS["V"]` 的「逐条登记例外」，不是放宽权限。

## 判据（a / b / c / d / g / h）

- 「a」 声明与行为一致：V 的三件声明工具里，声明 `write_local` 的集合 == 真跑后
  真的写盘的集合（源码扫 + 一次真实调用）；V 面上其余写工具必须全是通用能力，
  非通用的写工具只有 `verify.verify_proof` 一件。
- 「b」 正控：V 仍拿得到 `verify.verify_proof`；真跑一次在册送审，落到
  `verifications/<号>.jsonl`（且那一行的 `stmt_id` / `verdict` 对得上）。
- 「c」 C / H 仍然一个字节都写不了：工具面没有未登记的 `write_local`、没有
  `verify.verify_proof`；调写工具 ⇒ 受控拒（`kind='role_denied'`）。
- 「d」 例外表逐条可解释：每条都写清它写的是自己的什么（关键词逐个对；
  V 那条还必须写明「不改别人的」）。
- 「g」 V 只能写自己那张表：对 `statements` / `experiments` 的写尝试、对别人的稿的
  `fs.write` 尝试 ⇒ 受控拒；真跑一次 `verify.verify_proof` 之后，手稿与 statements
  的字节不变，只有 `verifications/` 多了一行。
- 「h」 反真空：摘掉 V 的例外 ⇒ b 红（V 拿不到工具）；把声明改回 `read` ⇒ a 红
  （同一份判据函数对"声明 read、实际写盘"的那一份必须报差异）。

零模型钱：模型缝是本地替身（`_ScriptedSeam`），不起任何外部进程、不碰 `projects/`。
"""
from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import pathlib
from types import SimpleNamespace
from typing import Any

import pytest

from agentflow import agent_v
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.store import Store
from agentflow.tools import (READ_ONLY_ROLES, SIDE_EFFECTS_WRITE, UNIVERSAL_TOOLS,
                             build_for_role, build_registry)
from agentflow.tools import base as TB

from conftest import TS, add_literature

#: 盘上那一份证明的正文（与 `test_verify_proof_takes_text_from_the_shelf.py` 同一形状）。
PROOF = "1. 由定义直接得到。2. 代入上一行即得。"
PROOF_EMPTY = ""

#: 夹具命题（按正文取号，不按行序猜）。
S_WITH_PROOF = "设 G 是有限群；则这条命题有一个可逐行走查的证明。"
S_NO_PROOF = "设 G 是有限群；则这条命题的正文还没写上来。"

#: 替身缝回的那份结论（与 `agent_v` 自检用的那一份同形）。
_VERDICT = '{"verdict": "成立", "findings": []}'

#: V 的「声明工具」（`roles=("V",)` 的那三件，不含通用能力）。
V_DECLARED_TOOLS: frozenset[str] = frozenset({
    "verify.verify_proof",
    "verify.list_verifications",
    "verify.read_proof",
})

#: V 工具面上「登记在案的通用写工具」（9 件）。它们是通用能力，不是 V 的私有写入面；
#: 这一行是人写下来的读数，不由实现反推（多一件/少一件都要人看过）。
V_UNIVERSAL_WRITE_TOOLS: frozenset[str] = frozenset({
    "clock.timer_start",
    "clock.alarm_start",
    "clock.periodic_start",
    "clock.periodic_stop",
    "clock.timer_purpose",
    "clock.timer_cancel",
    "clock.wait_any",
    "conductor.ack",
    "conductor.post_task",
})

#: V 的完整工具面（2026-11-05 实测）。为什么钉死：`for_role("V")` 少一件/多一件如果是
#: 静默发生的，下面"声明 == 行为"就可能在缩小的面上成立（真空通过）。
V_FACE: frozenset[str] = frozenset({
    "table.list", "table.get", "table.count", "table.schema", "table.search",
    "clock.now", "clock.timer_start", "clock.alarm_start", "clock.periodic_start",
    "clock.periodic_stop", "clock.timer_purpose", "clock.timer_list",
    "clock.timer_cancel", "clock.wait_any",
    "program.list",
    "fs.list", "fs.read", "fs.stat", "fs.search",
    "trace.children",
    "verify.verify_proof", "verify.list_verifications", "verify.read_proof",
    "conductor.escalate", "conductor.ack", "conductor.post_task",
    "manuscripts.read", "manuscripts.list",
}) | V_UNIVERSAL_WRITE_TOOLS

#: 例外表里每条登记"它写的是自己的什么"的「逐条关键词」（d 的判据输入）。
#: 人写下这张表，不由实现反推：改例外表必须在这里补一行。
EXCEPTION_OWN_PRODUCT: dict[tuple[str, str], str] = {
    ("C", "analysis.register_report"): "analysis_reports",
    ("H", "review.review_document"): "review_findings",
    ("H", "review.verify_fixes"): "review_findings",
    ("H", "review.report"): "报告文件",
    ("H", "review.record_finding"): "review_findings",
    ("V", "verify.verify_proof"): "verifications",
}


# ------------------------------------------------------------------ 夹具


class _ScriptedSeam:
    """最小的模型缝替身：`ask()` 回同一份结论（不碰网络、不花钱）。"""

    def __init__(self, text: str = _VERDICT) -> None:
        self.text = text
        self.prompts: list[str] = []

    def ask(self, prompt: str, **_kw: Any) -> Any:
        self.prompts.append(prompt)
        return SimpleNamespace(text=self.text, problem="")


def _ws(tmp_path: pathlib.Path) -> Store:
    """一个工作区：一篇在册文献 + 一条带证明正文的命题 + 一条正文为空的命题。"""
    st = Store(tmp_path / "ws")
    st.init()
    add_literature(st, "0000", title="夹具文献")
    with st.tx("statements", "counters", actor="fixture", note="fixture") as tx:
        for full, proof in ((S_WITH_PROOF, PROOF), (S_NO_PROOF, PROOF_EMPTY)):
            row = S.Statement(
                stmt_id=str(tx.alloc_id("stmt")), origin="external_lit",
                kind="theorem", label="夹具", statement_full=full,
                proof_text=proof, source_lit_id="0000",
                page_range=S.PageRange(start=1, end=1), quote_verified=None,
                quote_reason="夹具：这一格不参与本轮判据",
                evidence_kind="heuristic", created_at=TS,
            )
            row.validate()
            tx.upsert("statements", row.to_dict(), note="fixture")
    return st


def _ids(st: Store) -> str:
    """带正文那条命题的命题号（按正文取，不按行序猜）。"""
    rows = {str(r.get("statement_full") or ""): str(r.get("stmt_id") or "")
            for r in st.rows("statements")}
    return rows[S_WITH_PROOF]


def _manuscript(st: Store, sid: str, body: str = PROOF) -> str:
    """落一份按号命名的手稿（空依赖表也是声明）。"""
    from agentflow import depsection as DS

    rel = f"reports/f-proof-{sid}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 证明手稿\n\n- 命题号：stmt:{sid}\n\n"
        f"## 命题\n\n{S_WITH_PROOF}\n\n"
        f"## 证明\n\n{body}\n\n" + DS.render_dependency_section([]),
        encoding="utf-8")
    return rel


def _call_v(st: Store, **kw: Any):
    """过一次工具层的参数门再调 `verify.verify_proof`（两层口径一起量）。"""
    reg = build_for_role("V", store=st, workspace_root=str(st.root)).registry
    saved = agent_v.default_llm()
    agent_v.set_default_llm(_ScriptedSeam())
    try:
        return reg.call("verify.verify_proof", role="V", **kw)
    finally:
        agent_v.set_default_llm(saved)


def _v_face(st: Store) -> dict[str, Any]:
    reg = build_registry(store=st, workspace_root=st.root).registry
    return {s.name: s for s in reg.for_role("V")}


def _digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _workspace_files(root: pathlib.Path) -> dict[str, str]:
    """工作区里每一份文件的 sha256（相对路径 -> 摘要）。"""
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root)).replace("\\", "/")] = _digest(p)
    return out


# ------------------------------------------------------------------ a：声明 == 行为


def _declared_side_effect_in_source(tool: str) -> str:
    """从 `tools/verify_tools.py` 的源码里读这条工具声明的 `side_effect`（AST，不读运行期对象）。"""
    import agentflow.tools.verify_tools as VT

    tree = ast.parse(pathlib.Path(VT.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name)
                    and dec.func.id == "tool"):
                continue
            if not (dec.args and isinstance(dec.args[0], ast.Constant)
                    and dec.args[0].value == tool):
                continue
            for kw in dec.keywords:
                if kw.arg == "side_effect" and isinstance(kw.value, ast.Constant):
                    return str(kw.value.value)
    raise AssertionError(f"`tools/verify_tools.py` 里找不到 @tool({tool!r}) 的 side_effect 声明")


def _attribute_calls(path: pathlib.Path, attrs: set[str]) -> set[str]:
    """源码里 `X.<attr>(...)` 形态的调用（只看属性名；用来证明"它真的会写"）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in attrs:
            found.add(node.func.attr)
    return found


def _mismatches(declared: set[str], actual: set[str]) -> dict[str, list[str]]:
    """a 的判据本体：声明写 vs 真写。两侧都空也算"对上"（那是空集对空集）。"""
    return {
        "声明了却不写": sorted(declared - actual),
        "写了却没声明": sorted(actual - declared),
    }


def test_a_the_declaration_matches_the_write_behaviour(tmp_path: pathlib.Path) -> None:
    """a：V 的三件声明工具里，声明 `write_local` 的 == 真跑后真的写盘的。

    证据两半：
      1. 「源码扫」：`tools/verify_tools.py` 里 `verify.verify_proof` 的声明就是
         `write_local`；`agent_v/core.py` 里真的调了 `record_verification` /
         `record_pending_sign` / `vsigns.issue`（属性名扫）。
      2. 「一次真实调用」：`verify.verify_proof` 真跑一次（b 的同一条路）⇒ 台账文件出现；
         `verify.list_verifications` / `verify.read_proof` 真跑一次 ⇒ 工作区一个字节都没变。
    """
    st = _ws(tmp_path)
    face = _v_face(st)
    assert set(face) == set(V_FACE), (
        f"V 的工具面与钉住的那一份不一致：多了 {sorted(set(face) - V_FACE)}、"
        f"少了 {sorted(V_FACE - set(face))}")

    # ---- ① 源码扫：三件工具里只有 verify_proof 声明 write_local
    source_declared = {name: _declared_side_effect_in_source(name)
                       for name in V_DECLARED_TOOLS}
    assert source_declared == {
        "verify.verify_proof": "write_local",
        "verify.list_verifications": "read",
        "verify.read_proof": "read",
    }, source_declared
    # 写在 handler 链上的那几处：没有它们，"write_local"就只是声明
    core = pathlib.Path(agent_v.__file__).resolve().parent / "core.py"
    writes = _attribute_calls(core, {"record_verification", "record_pending_sign",
                                     "issue", "write_manuscript_sign"})
    assert {"record_verification", "record_pending_sign", "issue"} <= writes, (
        f"`agent_v/core.py` 里找不到那几处写调用：{sorted(writes)} —— "
        "那意味着 `write_local` 没有对应的实现证据")

    # ---- ② 一次真实调用：verify_proof 真写台账；另两件真读、一个字节不写
    sid = _ids(st)
    rel = _manuscript(st, sid)
    before = _workspace_files(pathlib.Path(st.root))
    got = _call_v(st, statement_id=sid, proof_manuscript=rel)
    assert got.ok is True, (got.error, got.meta)
    assert dict(got.data or {}).get("checked") is True, got.data
    after = _workspace_files(pathlib.Path(st.root))
    created = sorted(set(after) - set(before))
    changed = sorted(k for k in set(before) & set(after) if before[k] != after[k])
    assert f"verifications/{sid}.jsonl" in created, (
        f"`verify.verify_proof` 没有落台账（新建文件：{created}）")
    assert set(changed) <= {f"verifications/{sid}.jsonl"}, (
        f"它改了自己的台账之外的东西：{changed}")

    reg = build_for_role("V", store=st, workspace_root=str(st.root)).registry
    before_read = _workspace_files(pathlib.Path(st.root))
    for name, kw in (("verify.list_verifications", {}),
                     ("verify.read_proof", {"statement_id": sid})):
        res = reg.call(name, role="V", **kw)
        assert res.ok is True, (name, res.error, res.meta)
    after_read = _workspace_files(pathlib.Path(st.root))
    changed_by_read = sorted(k for k in set(before_read) | set(after_read)
                             if before_read.get(k) != after_read.get(k))
    assert after_read == before_read, (
        f"声明为 `read` 的 V 工具真跑一次却改了工作区：{changed_by_read}")

    # ---- ③ 集合相等：三件声明工具里"声明写"与"真写"逐个对得上
    declared = {n for n in V_DECLARED_TOOLS if face[n].side_effect in SIDE_EFFECTS_WRITE}
    actual = {"verify.verify_proof"}  # 上面那一次真跑 + 另两件的"文件未变"
    assert _mismatches(declared, actual) == {"声明了却不写": [], "写了却没声明": []}, (
        _mismatches(declared, actual))

    # ---- ④ V 面上其余写工具必须全是通用能力（非通用的写工具只有这一件）
    all_declared_write = {n for n, s in face.items() if s.side_effect in SIDE_EFFECTS_WRITE}
    assert all_declared_write == set(V_UNIVERSAL_WRITE_TOOLS) | {"verify.verify_proof"}, (
        f"V 的写面上出现了别的写工具：{sorted(all_declared_write)}")
    assert V_UNIVERSAL_WRITE_TOOLS <= set(UNIVERSAL_TOOLS), sorted(
        V_UNIVERSAL_WRITE_TOOLS - set(UNIVERSAL_TOOLS))


# ------------------------------------------------------------------ b：V 仍拿得到


def test_b_v_still_gets_the_tool_and_a_real_review_lands_the_ledger(
        tmp_path: pathlib.Path) -> None:
    """b 正控：V 的工具面上有 `verify.verify_proof`；真跑一次在册送审 ⇒ 台账那一行落地。

    反真空在 h：摘掉例外 ⇒ 这件的正控立刻拿不到工具。
    """
    st = _ws(tmp_path)
    sid = _ids(st)
    rel = _manuscript(st, sid)

    face = _v_face(st)
    assert "verify.verify_proof" in face, "V 的工具面上没有 verify.verify_proof"
    assert face["verify.verify_proof"].side_effect == "write_local", (
        "声明不是 write_local ⇒ a 与这条正控会用两套口径说话")

    got = _call_v(st, statement_id=sid, proof_manuscript=rel)
    assert got.ok is True, (got.error, got.meta)
    data = dict(got.data or {})
    assert data.get("checked") is True, data
    assert data.get("verdict") == "成立", data

    ledger = pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl"
    assert ledger.is_file(), "审过了却没有落 verifications/<命题号>.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    assert rows, "台账是空的"
    row = rows[-1]
    assert row.get("stmt_id") == sid, (row.get("stmt_id"), sid)
    assert row.get("verdict") == "成立", row.get("verdict")
    assert row.get("proof_sha256") == VR.proof_sha(PROOF), row.get("proof_sha256")


# ------------------------------------------------------------------ c：C / H 一个字节都写不了


def test_c_and_h_still_cannot_write_a_byte(tmp_path: pathlib.Path) -> None:
    """c 正控：C / H 的工具面没有未登记的写工具、也没有 `verify.verify_proof`；
    调写工具 ⇒ 受控拒（`kind='role_denied'`）。"""
    st = _ws(tmp_path)
    sid = _ids(st)
    reg = build_registry(store=st, workspace_root=st.root).registry
    for role in ("C", "H"):
        face = {s.name for s in reg.for_role(role)}
        assert "verify.verify_proof" not in face, (
            f"{role} 拿到了 V 的凭据写入面 —— 那正是「只读角色不能改别人的东西」要拦住的事")
        # C/H 的 `write_local` 只许是两类登记过的：自己的落库代理 + 通用能力
        allowed = {n for n, _w in TB.READONLY_CALL_EXCEPTIONS.get(role, ())}
        allowed |= set(UNIVERSAL_TOOLS)
        leaked = {s.name for s in reg.for_role(role)
                  if s.side_effect in SIDE_EFFECTS_WRITE and s.name not in allowed}
        assert leaked == set(), f"{role} 的面上出现未登记的写工具：{sorted(leaked)}"
        assert "fs.write" not in face and "table.update" not in face, (
            f"{role} 的面上出现了写文件 / 改表的工具")

        # 真调一次写工具：受控拒，且拒绝码是"角色面"那一档（不是参数错）
        for name, kw in (("fs.write", {"path": "notes/x.md", "content": "x"}),
                         ("table.update", {"table": "statements",
                                           "id": sid, "patch": {}})):
            got = reg.call(name, role=role, **kw)
            assert got.ok is False, (role, name, got.data)
            assert got.meta.get("kind") == "role_denied", (
                role, name, got.meta)


# ------------------------------------------------------------------ d：例外表逐条可解释


def test_d_every_read_only_exception_says_what_it_writes(store: Store) -> None:
    """d：每条例外都写清"为什么需要它、它写的是自己的什么"。

    "逐条可解释"不靠嘴说：每条理由必须点名它写的那张表 / 那份产物（关键词逐条对，
    见 `EXCEPTION_OWN_PRODUCT`），长度足够说清问题，且 V 那条必须写明
    「「不改别人的」」 —— 那是这条裂缝的边界本身。
    """
    assert set(TB.READONLY_CALL_EXCEPTIONS) == {"C", "H", "V"}, (
        sorted(TB.READONLY_CALL_EXCEPTIONS))
    seen: set[tuple[str, str]] = set()
    for role, entries in TB.READONLY_CALL_EXCEPTIONS.items():
        assert entries, f"{role} 的例外表是空的 —— 空条目不能算「登记过」"
        for tool, why in entries:
            key = (role, tool)
            assert key not in seen, f"{key} 登记了两次"
            seen.add(key)
            text = str(why or "").strip()
            assert len(text) >= 40, f"{key} 的理由太短，说不清「为什么需要它」：{text!r}"
            expected = EXCEPTION_OWN_PRODUCT.get(key)
            assert expected is not None, (
                f"{key} 不在 `EXCEPTION_OWN_PRODUCT` 里 —— 新加的例外必须在这里"
                "写下「它写的是自己的什么」")
            assert expected in text, (
                f"{key} 的理由没有点名它写的东西 {expected!r}：{text!r}")
    assert seen == set(EXCEPTION_OWN_PRODUCT), (
        f"例外表与逐条关键词表对不上：{sorted(seen ^ set(EXCEPTION_OWN_PRODUCT))}")

    v_why = dict(TB.READONLY_CALL_EXCEPTIONS["V"])["verify.verify_proof"]
    assert "不改别人的" in v_why, f"V 那条例外没写边界：{v_why!r}"
    assert ("自己的" in v_why) or ("自己维护" in v_why), (
        f"V 那条例外没写「它写的是自己的」：{v_why!r}")

    # 工具面那一侧：V 的例外真的生效（不是只在表里躺着）
    face = _v_face(store)
    assert "verify.verify_proof" in face, "例外登记了，但工具面上没有它"
    assert "verify.verify_proof" in TB.READONLY_CALL_EXCEPTIONS["V"][0][0], v_why


# ------------------------------------------------------------------ g：V 只能写自己那张表


def test_g_v_cannot_write_someone_elses_table_or_manuscript(tmp_path: pathlib.Path) -> None:
    """g：V 对 `statements` / `experiments` / 别人的稿的写尝试 ⇒ 受控拒。

    "受控拒"的判据是工具层/角色面真的说话（`ok=False` + `kind='role_denied'`），
    不是"碰巧没调"。
    """
    st = _ws(tmp_path)
    reg = build_registry(store=st, workspace_root=st.root).registry
    sid = _ids(st)
    attempts = (
        ("table.update", {"table": "statements", "id": sid,
                          "patch": {"statement_full": "被别人改了"}}),
        ("table.create", {"table": "experiments", "row": {"claim_key": "x"}}),
        ("fs.write", {"path": f"reports/f-proof-{sid}.md", "content": "伪造的稿"}),
        ("fs.edit", {"path": f"reports/f-proof-{sid}.md",
                     "old_string": "由定义", "new_string": "被别人改了"}),
    )
    for name, kw in attempts:
        got = reg.call(name, role="V", **kw)
        assert got.ok is False, (name, got.data)
        assert got.meta.get("kind") == "role_denied", (name, got.meta)
        assert name not in {s.name for s in reg.for_role("V")}, (
            f"{name} 出现在 V 的工具面上 ⇒ 这次拒绝只是碰巧")


def test_g_a_real_review_leaves_someone_elses_bytes_alone(tmp_path: pathlib.Path) -> None:
    """g 的行为那一半：真跑一次 `verify.verify_proof` 之后，别人的东西一个字节不变。

    允许变的只有 V 自己维护的 `verifications/<号>.jsonl`；手稿与 `statements` 的字节
    必须与跑之前逐字相同（这一趟没有秘书 ⇒ 第 3 位不翻、签块不落）。
    """
    st = _ws(tmp_path)
    sid = _ids(st)
    rel = _manuscript(st, sid)
    root = pathlib.Path(st.root)
    manuscript = root / rel
    statements = root / "data" / "statements.json"
    assert manuscript.is_file() and statements.is_file(), (rel, statements)
    before_ms, before_st = _digest(manuscript), _digest(statements)
    before_experiments = len(st.rows("experiments"))

    got = _call_v(st, statement_id=sid, proof_manuscript=rel)
    assert got.ok is True, (got.error, got.meta)
    assert dict(got.data or {}).get("checked") is True, got.data

    assert _digest(manuscript) == before_ms, "V 改了别人的稿（手稿字节变了）"
    assert _digest(statements) == before_st, "V 改了 statements 的字节"
    assert len(st.rows("experiments")) == before_experiments, "V 写了 experiments"
    assert (root / "verifications" / f"{sid}.jsonl").is_file(), "自己的台账没落地"


# ------------------------------------------------------------------ h：反真空


def test_h_removing_the_exception_takes_the_tool_away(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """h 反真空①：摘掉 V 的例外 ⇒ V 立刻拿不到 `verify.verify_proof`（b 的判据红）。"""
    face = _v_face(store)
    assert "verify.verify_proof" in face, "夹具前提：摘之前它在面上"

    stripped = dict(TB.READONLY_CALL_EXCEPTIONS)
    stripped["V"] = ()
    monkeypatch.setattr(TB, "READONLY_CALL_EXCEPTIONS", stripped, raising=True)

    face_without = _v_face(store)
    assert "verify.verify_proof" not in face_without, (
        "摘掉例外之后 V 仍拿得到它 ⇒ 例外机制没有承重（b 恒绿）")
    # 另一件 V 工具不受影响（红不是从别处来的）
    assert "verify.read_proof" in face_without, "摘例外误伤了只读那两件"


def test_h_declaring_it_read_again_makes_a_red(store: Store) -> None:
    """h 反真空②：把声明改回 `read` ⇒ a 的判据函数必须报差异。

    造法：拿真 face 复制一份、只把 `verify.verify_proof` 的 `side_effect` 改成 `read`，
    再喂给同一个 `_mismatches`（真写的那一件仍算在"写了"那一侧）。
    """
    face = _v_face(store)
    actual = {"verify.verify_proof"}
    bad_face = dict(face)
    bad_face["verify.verify_proof"] = dataclasses.replace(
        face["verify.verify_proof"], side_effect="read")
    declared = {n for n in V_DECLARED_TOOLS
                if bad_face[n].side_effect in SIDE_EFFECTS_WRITE}
    assert _mismatches(declared, actual)["写了却没声明"] == ["verify.verify_proof"], (
        "把声明改回 read 之后 a 没红 ⇒ 那条判据不是在看声明")
    # 正控：真 face 上同一份判据必须干净（红不是写死的）
    good_declared = {n for n in V_DECLARED_TOOLS
                     if face[n].side_effect in SIDE_EFFECTS_WRITE}
    assert _mismatches(good_declared, actual) == {"声明了却不写": [], "写了却没声明": []}
