# -*- coding: utf-8 -*-
"""L 的三件工具按名真调（`formal.formalize` / `formal.check_formal` / `formal.record`）。

## 这一份判什么

工具层：每一次调用都走 `ToolRegistry.call("<工具名>", ...)`，由工具面自己的参数校验、
角色判据、handler 转发与调用日志接住。刻意不直接调 `AgentL` 的方法 —— 动作层那一路
（action 到 handler）在 `tests/test_l_action_dispatch.py`。

| 工具 | 用例 | 正控 | 产物落盘 | 可被消费 | 可被登记 | 失败 / 拒绝路径 |
|---|---|---|---|---|---|---|
| `formal.formalize` | `test_tool_formal_formalize_writes_the_lean_and_the_steps_table` | 12 步真证明 ⇒ status / checker_status = verified、exit_code=0、coverage 12/12、b_library.found | `code/formal/<名>.lean` 与 `.steps.jsonl` 的真实路径 + 字节数 + sha256 | 两个产物读回来：每行 quote 在 proof_text 里、lean_lines 指向的行逐字是 `-- step k`；同一份产物交给 `formal.record` 真登记成一行 | 见左格（同一个工作区里那一行 experiments 真的出现） | `test_tool_formal_formalize_missing_step_and_sorry_are_unknown`、`test_tool_formal_formalize_refuses_an_unknown_statement_and_writes_nothing` |
| `formal.check_formal` | `test_tool_formal_check_formal_reverifies_the_generated_lean` | 对刚生成的 `.lean` 再核一次 ⇒ verified=True、exit_code=0、verifier_output 是真 Lean 的原话 | 只读：文件 sha256 与字节数一个都不变、也没有新文件 | 它消费的正是 `formal.formalize` 落下的那一份 .lean | 它的 `verifier_output` 就是 `formal.record` 写进 observations 的那一段（同一个字符串） | 负控 `test_tool_formal_check_formal_reports_the_checker_words_on_a_broken_line`：把 `exact` 改错一行 ⇒ failed + 检查器原话，不许折成 unknown |
| `formal.record` | `test_tool_formal_record_files_one_experiments_row` | 登记一次 ⇒ experiments 多一行：method=formal、evidence_kind=proof、claim_key=stmt:<号>、code_path、code_hash、exit_code=0、observations 里有 checker 与 tri_state | 那一行的 code_hash 是盘上 .lean 的 sha256（真实路径 + 字节数 + sha256 三样对齐） | `test_tool_formal_record_row_is_consumed_by_store_closing_and_verify`：新 `Store` 读到、`closing` 的 proof 行读数读到、`verify.verify_all` 不再把这一行判成自报 | 见左格 | `test_tool_formal_record_refuses_an_inflated_reading_and_writes_no_row`：不给读数却声称 verified ⇒ 受控拒绝、一行都不写 |

## 改前红

每条用例在报告里都有一份"把对应实现退回 %TEMP% 副本之后跑同一条"的原文；本文件
只在 docstring 里写清"退回的是哪一格"，复现步骤见报告。

## 真 Lean 与零模型

真 Lean 用本机那一版的绝对路径（PATH 上的 lean 可能是另一个东西）；文件不在或自检
不是 usable 时，需要检查器结论的那几条如实 skip 并把读数写进理由（不伪装通过）。
这一份一次模型调用都没有。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

#: 本机那一版真 Lean（绝对路径，不依赖 PATH）。
LEAN = pathlib.Path(r"D:\Incubator\_env\lean470\lean-4.7.0-windows\bin\lean.exe")
HAVE_LEAN = LEAN.is_file()

#: 被形式化的那条命题（B 登记的原文）。
CLAIM = "forall n : Nat, n + 0 = n"
#: 命题台账里那一行的编号与标题。
STMT_ID = "000001"
LABEL = "加零不改变自然数"
#: 证明链步数：空行分段口径切出 12 步（业主口径里的"真 12 步"）。
STEPS = 12
#: 盘上两个产物的名字（声明名决定文件名）。
LEAN_REL = "code/formal/add_zero_probe.lean"
STEPS_REL = "code/formal/add_zero_probe.steps.jsonl"
DECL_SHORT = "add_zero_probe"
DECL_FULL = "LProbe.add_zero_probe"


# ============================================================ 夹具与小工具


def _proof_text(steps: int = STEPS) -> str:
    """`steps` 步的证明链：一步一段（空行分段是切分口径的第一档）。"""
    return "\n\n".join(
        f"第 {k} 步：把第 {k - 1} 步的结论代入一次并化简。" for k in range(1, steps + 1))


def _source(mapped: int = STEPS, *, sorry: bool = False, exact: bool = False,
            broken: bool = False) -> str:
    """Lean 源码：前 `mapped` 步各有一个独占一行的 `-- step k` 落点。

    `broken=True` 只改一行（把 `exact rfl` 换成 `exact (Nat.zero_add n)`）：
    那一行在 Lean 里是类型不匹配，于是检查器必须说 error。判据靠"只改一行"这件事
    把失败归因钉死在那一行上。
    """
    if broken:
        body = "  exact (Nat.zero_add n)"
    elif exact:
        body = "  exact rfl"
    elif sorry:
        body = "  sorry"
    else:
        body = "  rfl"
    lines = [
        "import Init.Data.Nat.Basic",
        "",
        "namespace LProbe",
        "",
        "/-- 加零不改变自然数。 -/",
        "theorem add_zero_probe (n : Nat) : n + 0 = n := by",
        body,
    ]
    for k in range(1, mapped + 1):
        lines.append(f"-- step {k}")
    lines += ["", "end LProbe", ""]
    return "\n".join(lines)


def _lean_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """打开 Lean 开关并把检查器指到本机那一版；同时清掉两处读数缓存。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    monkeypatch.setenv("AGENTFLOW_LEAN_ENABLED", "1")
    if HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _skip_unless_usable(ws: pathlib.Path) -> None:
    """真检查器不可用时如实 skip（原因写清：文件不在 / 自检不是 usable）。"""
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=ws)
    if str(reading.get("state")) != "usable":
        pytest.skip(
            f"Lean 自检不是 usable（state={reading.get('state')}；"
            f"problems={reading.get('problems')}）⇒ 这一条要真跑检查器，跳过（不伪装通过）")


def _workspace(tmp_path: pathlib.Path) -> tuple[object, pathlib.Path]:
    """建一个工作区，并让 B 登记一条 12 步证明的命题。"""
    from agentflow.store import Store

    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    with st.tx("statements", actor="agent-B") as tx:
        tx.upsert("statements", {
            "stmt_id": STMT_ID,
            "label": LABEL,
            "statement": CLAIM,
            "statement_full": CLAIM,
            "proof_text": _proof_text(),
            "evidence_kind": "heuristic",
            "status": "active",
            "origin": "own_result",
            "quote_reason": "自产命题（这一组判据不涉及外部原文）",
        }, note="probe:statement")
    return st, ws


def _registry(st: object, ws: pathlib.Path):
    """L 的工具面（三条都在），并打开调用日志：按名调用这件事要留下机器读数。"""
    from agentflow.agent_l import install_l_tools

    reg = install_l_tools(st, workspace_root=ws)
    reg.log_calls = True
    return reg


def _call(reg: object, name: str, **params: object) -> dict:
    """按名调一次工具，返回 `data`；顺带断言这次调用真的进了调用日志。"""
    before = len(reg.call_log())
    res = reg.call(name, **params)
    log = reg.call_log()
    assert len(log) == before + 1, f"{name} 这一次没有进调用日志：{log[before:]}"
    entry = log[-1]
    assert str(entry.get("tool")) == name, entry
    assert "ok" in entry, entry
    assert res.ok is True, (name, res.ok, res.error, res.meta)
    assert isinstance(res.data, dict), (name, type(res.data))
    return dict(res.data)


def _artifact(path: pathlib.Path) -> tuple[int, str]:
    """一个真实落盘产物：路径存在、字节数、sha256（三样一起给，缺一样就不算落盘）。"""
    assert path.is_file(), f"盘上没有 {path}"
    raw = path.read_bytes()
    assert raw, f"{path} 是空文件（0 字节的文件不是产物）"
    assert len(raw) == path.stat().st_size, (path, len(raw), path.stat().st_size)
    return len(raw), hashlib.sha256(raw).hexdigest()


def _files(root: pathlib.Path) -> list[tuple[str, int, str]]:
    """整棵工作区的清单（相对路径 + 字节数 + sha256），用来判"盘上多了哪几件"。"""
    out: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            raw = path.read_bytes()
            out.append((path.relative_to(root).as_posix(), len(raw),
                        hashlib.sha256(raw).hexdigest()))
    return out


def _lean_files(ws: pathlib.Path) -> list[pathlib.Path]:
    """`code/formal/` 下的 .lean 清单（"不产生第二份"这条判据读它）。"""
    folder = ws / "code" / "formal"
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.lean"))


def _steps_rows(ws: pathlib.Path) -> list[dict]:
    """把 `.steps.jsonl` 读回来（逐行 JSON）。"""
    text = (ws / STEPS_REL).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ============================================================ 1. formal.formalize


def test_tool_formal_formalize_writes_the_lean_and_the_steps_table(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 产物 + 可消费 + 可被登记：12 步真证明经 `formal.formalize` 落成两份产物。

    改前红：把 `agent_l/formalize.py` 里逐步对照落盘那一段退回（不再写
    `.steps.jsonl`、`steps_path` 留空）⇒ 本用例第一条产物断言即红。

    三格结论各自独立断言：`status` 是这一趟算不算数、`checker_status` 是检查器原话、
    `exit_code` 是真实退出码。折叠任何一格都会被下面某一条抓到。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    data = _call(reg, "formal.formalize", claim=CLAIM, source=_source(),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)

    # ---- 正控：结论三格 + 覆盖读数 + B 的库
    assert data["status"] == "verified", (data["status"], data["reason"], data["detail"])
    assert data["checker_status"] == "verified", data["checker_status"]
    assert data["exit_code"] == 0, data["exit_code"]
    assert str(data["verifier_output"]).strip(), data["verifier_output"]
    coverage = dict(data["coverage"])
    assert coverage["steps_total"] == STEPS, coverage
    assert coverage["steps_mapped"] == coverage["steps_total"] == STEPS, coverage
    assert coverage["unmapped"] == [], coverage
    assert coverage["sorry_lines"] == [], coverage
    lib = dict(data["b_library"])
    assert lib["found"] is True, lib
    assert lib["stmt_id"] == STMT_ID, lib
    assert lib["label"] == LABEL, lib
    assert lib["dependency_steps"] == STEPS, lib

    # ---- 产物落盘：真实路径 + 字节数 + sha256（返回值里的与盘上现算的必须同一个）
    target = ws / LEAN_REL
    size, digest = _artifact(target)
    assert str(data["path"]) == LEAN_REL, data["path"]
    assert int(data["bytes"]) == size, (data["bytes"], size)
    assert str(data["sha256"]) == digest, (data["sha256"], digest)
    assert str(data["written"]) == "True", data["written"]
    raw = target.read_bytes()
    assert b"\r\n" not in raw, "落盘的行尾必须是 \\n（否则 sha256 与内容无关）"
    assert raw == _source().encode("utf-8"), "盘上那份源码与传进来的不是同一串字节"
    steps_file = ws / STEPS_REL
    steps_size, steps_digest = _artifact(steps_file)
    assert str(data["steps_path"]) == STEPS_REL, data["steps_path"]
    assert steps_size > 0 and len(steps_digest) == 64, (steps_size, steps_digest)

    # ---- 可被消费（另一条入口读回来）：每行 quote 在 proof_text 里、lean_lines 指向真标记行
    rows = _steps_rows(ws)
    assert len(rows) == STEPS, len(rows)
    assert [r["proof_step"] for r in rows] == list(range(1, STEPS + 1)), rows
    assert set(rows[0]) == {"proof_step", "quote", "lean_lines", "how"}, sorted(rows[0])
    proof_flat = " ".join(_proof_text().split())
    source_lines = target.read_text(encoding="utf-8").splitlines()
    for row in rows:
        quote = str(row["quote"])
        assert quote and quote in proof_flat, (row["proof_step"], quote)
        first, last = (int(x) for x in row["lean_lines"])
        assert 1 <= first <= last <= len(source_lines), (row["lean_lines"], len(source_lines))
        assert source_lines[first - 1] == f"-- step {row['proof_step']}", (
            row["proof_step"], source_lines[first - 1])
        assert row["how"] == "直接对应", row

    # ---- 可被登记（同一个工作区里那一行 experiments 真的出现，用的就是这份产物）
    reg_row = _call(reg, "formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                    declaration_name=DECL_SHORT)
    assert reg_row["recorded"] is True, reg_row
    assert str(reg_row["code_hash"]) == digest, (reg_row["code_hash"], digest)
    assert len(st.rows("experiments")) == 1, st.rows("experiments")


def test_tool_formal_formalize_missing_step_and_sorry_are_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """失败路径：漏一步 ⇒ unknown 且盘上仍只有那一个 .lean；say sorry ⇒ unknown 且 sorry_lines 非空。

    改前红：把 `agent_l/formalize.py::coverage_reason` 退回成"恒返回空串"（也就是
    逐步对照那条硬规则还不存在的那一版）⇒ 漏一步的那一趟会把自己读成 verified，
    `status == "unknown"` 当场红。

    漏一步那一档同时断言检查器那一格仍是 verified：机器核过了、而这一趟不算数，
    是两件事，折叠掉任何一格都会被下面某条抓到。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    full = _call(reg, "formal.formalize", claim=CLAIM, source=_source(),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)
    assert full["status"] == "verified", full["status"]
    assert [p.name for p in _lean_files(ws)] == ["add_zero_probe.lean"], _lean_files(ws)

    # ---- 漏第 12 步：盘上不许出现第二份 .lean，那一份被同名覆盖
    missed = _call(reg, "formal.formalize", claim=CLAIM, source=_source(STEPS - 1),
                   declaration_name=DECL_SHORT, statement_id=STMT_ID)
    miss_cov = dict(missed["coverage"])
    assert miss_cov["steps_total"] == STEPS, miss_cov
    assert miss_cov["steps_mapped"] == STEPS - 1, miss_cov
    assert miss_cov["unmapped"] == [STEPS], miss_cov
    assert missed["status"] == "unknown", (missed["status"], missed["reason"])
    assert missed["reason"] == "faithfulness_incomplete", missed["reason"]
    assert missed["faithfulness"] == "incomplete", missed["faithfulness"]
    assert missed["checker_status"] == "verified", missed["checker_status"]

    lean_files = _lean_files(ws)
    assert len(lean_files) == 1, f"漏一步那一趟多写了 .lean：{lean_files}"
    assert lean_files[0].name == "add_zero_probe.lean", lean_files
    miss_size, miss_digest = _artifact(ws / LEAN_REL)
    assert str(missed["sha256"]) == miss_digest, (missed["sha256"], miss_digest)
    assert int(missed["bytes"]) == miss_size, (missed["bytes"], miss_size)
    assert (ws / LEAN_REL).read_bytes() == _source(STEPS - 1).encode("utf-8"), \
        "同名覆盖之后盘上那一份不是这一趟的源码"
    # 对照表仍是 12 行（证明链是 12 步），只是第 12 步没有落点
    rows = _steps_rows(ws)
    assert len(rows) == STEPS, len(rows)
    assert rows[STEPS - 1]["how"] == "未映射", rows[STEPS - 1]
    assert rows[STEPS - 1]["lean_lines"] == [], rows[STEPS - 1]

    # ---- say sorry：含 sorry 的文件照样编译通过，那不是证明
    holes = _call(reg, "formal.formalize", claim=CLAIM, source=_source(sorry=True),
                  declaration_name=DECL_SHORT, statement_id=STMT_ID)
    hole_cov = dict(holes["coverage"])
    assert hole_cov["sorry_lines"], hole_cov
    assert holes["status"] == "unknown", (holes["status"], holes["reason"])
    assert holes["reason"] == "faithfulness_sorry", holes["reason"]
    assert holes["faithfulness"] == "holes", holes["faithfulness"]
    assert holes["status"] != "verified", "含 sorry 的源码被读成了 verified"
    assert str(holes["checker_status"]) != "", holes["checker_status"]
    assert len(_lean_files(ws)) == 1, _lean_files(ws)


def test_tool_formal_formalize_refuses_an_unknown_statement_and_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """拒绝路径：`statement_id` 不在台账里 ⇒ 受控拒绝，`code/formal` 里一个新增文件都没有。

    改前红：把 `agent_l/formalize.py::_pick_statement` 退回成"不看台账、直接认"那一版
    ⇒ 不存在的编号也会被写成一份 .lean，`refused` 与"没有新增文件"两条当场红。

    关于 `ok`：工具层这次调用本身是成功的（`ToolResult.ok=True`），"结论没通过"由
    `refused=True` 与 `written=False` 表达 —— 这是三态纪律的写法（见
    `tools/formal_tools.py` 模块 docstring 与 `_refusal` 的 docstring）。所以本用例
    断言的是 `refused` / `written` / `reason` 三格，不是 `ok=False`。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    before = _files(ws)

    res = reg.call("formal.formalize", claim=CLAIM, source=_source(),
                   declaration_name=DECL_SHORT, statement_id="999999")
    assert res.ok is True, (res.ok, res.error, res.meta)
    data = dict(res.data)
    assert data["refused"] is True, data["refused"]
    assert data["written"] is False, data["written"]
    assert data["path"] == "", data["path"]
    assert data["status"] == "unknown", data["status"]
    assert data["reason"] == "statement_not_found", data["reason"]
    assert "999999" in str(data["detail"]), data["detail"]
    assert dict(data["b_library"])["found"] is False, data["b_library"]

    after = _files(ws)
    added = [rel for rel, _size, _sha in after if rel.startswith("code/formal/")]
    assert added == [], f"被拒时 code/formal 里多了文件：{added}"
    assert _lean_files(ws) == [], _lean_files(ws)
    # 整棵树唯一允许的新落点是 B 的收件箱（裁定的第四句：失败要向 B 汇报）。
    # 会话号取的是默认的当日号，所以这里只判"落在 sessions/<sid>.jsonl 上"，
    # 不把某一天的日期写死（写死会让这条判据在跨日时变红，而它与本题无关）。
    new = [rel for rel, _s, _h in after
           if (rel, _s, _h) not in {(r, s, h) for r, s, h in before}]
    assert new and all(rel.startswith("sessions/") and rel.endswith(".jsonl")
                       for rel in new), new
    assert len(new) == 1, new


# ============================================================ 2. formal.check_formal


def test_tool_formal_check_formal_reverifies_the_generated_lean(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 可消费 + 可被登记：对刚生成的 .lean 再核一次，读数与真 Lean 原话一致。

    改前红：把 `formal.check_formal` 从 `tools/formal_tools.py::_TOOL_FUNCTIONS` 里
    摘掉（也就是 L 的工具面还没有这一件的那一版）⇒ 按名调用拿到 `unknown_tool`，
    本用例第一次调用即红。

    只读那一半也断言：检查不写盘，盘上 .lean 的字节数与 sha256 一个字都不变。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    made = _call(reg, "formal.formalize", claim=CLAIM, source=_source(),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)
    assert made["status"] == "verified", made["status"]
    before = _files(ws)

    data = _call(reg, "formal.check_formal", claim=CLAIM, script_path=LEAN_REL,
                 declaration_name=DECL_FULL)
    assert data["verified"] is True, (data["verified"], data["reason"], data["detail"])
    assert data["status"] == "verified", data["status"]
    assert data["exit_code"] == 0, data["exit_code"]
    out = str(data["verifier_output"])
    assert out.strip(), "没有检查器原话的 verified 不算数"
    assert DECL_FULL in out, out
    assert "does not depend on any axioms" in out or "depends on axioms:" in out, out
    assert data["missing_imports"] == [], data["missing_imports"]

    # ---- 只读：盘上一个字节都没动
    assert _files(ws) == before, "check_formal 改动了工作区（它必须只读）"
    size, digest = _artifact(ws / LEAN_REL)
    assert digest == str(made["sha256"]), (digest, made["sha256"])
    assert size == int(made["bytes"]), (size, made["bytes"])

    # ---- 可被登记：这段检查器原话会被 formal.record 原样写进那一行
    rec = _call(reg, "formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                declaration_name=DECL_SHORT)
    assert rec["recorded"] is True, rec
    assert str(rec["verifier_output"]) == out, (rec["verifier_output"], out)
    row = dict(st.rows("experiments")[0])
    assert str(row["verifier_output"]) == out, (row["verifier_output"], out)


def test_tool_formal_check_formal_reports_the_checker_words_on_a_broken_line(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控：把 `exact` 那一行改错 ⇒ 检查器说不行，而读数必须如实是 failed。

    改前红：把 `agent_l/_support.py::FAILED_REASONS` 退回成空元组（也就是
    `compile_error` 还没有被认成"检查器说了不通过"那一版）⇒ 这一趟的 status 变成
    unknown，`status == "failed"` 与"不许折成 unknown"两条当场红。

    "只改一行"是这一条的归因手段：好源码与坏源码逐行比，恰好一行不同。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    made = _call(reg, "formal.formalize", claim=CLAIM, source=_source(exact=True),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)
    assert made["status"] == "verified", (made["status"], made["reason"], made["detail"])
    good = _source(exact=True)
    bad = _source(broken=True)
    good_lines, bad_lines = good.splitlines(), bad.splitlines()
    assert len(good_lines) == len(bad_lines), (len(good_lines), len(bad_lines))
    changed = [i for i, (a, b) in enumerate(zip(good_lines, bad_lines)) if a != b]
    assert changed == [6], changed
    assert good_lines[6].strip() == "exact rfl", good_lines[6]
    on_disk_before = (ws / LEAN_REL).read_bytes()

    data = _call(reg, "formal.check_formal", claim=CLAIM, source=bad,
                 declaration_name=DECL_FULL)
    assert data["verified"] is False, (data["verified"], data["status"], data["reason"])
    assert data["status"] == "failed", (data["status"], data["reason"], data["detail"])
    assert data["status"] != "unknown", "检查器说了不通过，而这一趟被折成了 unknown"
    assert data["reason"] == "compile_error", data["reason"]
    assert data["exit_code"] != 0, data["exit_code"]
    out = str(data["verifier_output"])
    assert "error" in out, out
    assert "type mismatch" in out, out
    assert DECL_FULL in out, out
    assert data["problems"] == [], data["problems"]

    # 检查用的是内联源码，盘上那一份必须原样（负控不许把好文件改坏）
    assert (ws / LEAN_REL).read_bytes() == on_disk_before, "负控改动了盘上那份 .lean"


# ============================================================ 3. formal.record


def test_tool_formal_record_files_one_experiments_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 可被登记：登记一次 ⇒ experiments 表多一行，关键列逐格断言。

    改前红：把 `formal.record` 从 `_TOOL_FUNCTIONS` 里摘掉（L 还写不了 experiments
    的那一版）⇒ 按名调用拿到 `unknown_tool`，本用例第一次调用即红。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    made = _call(reg, "formal.formalize", claim=CLAIM, source=_source(),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)
    assert made["status"] == "verified", made["status"]
    size, digest = _artifact(ws / LEAN_REL)
    assert st.rows("experiments") == [], st.rows("experiments")

    data = _call(reg, "formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                 declaration_name=DECL_SHORT)
    assert data["recorded"] is True, (data["recorded"], data["reason"], data["detail"])
    assert data["statement_id"] == STMT_ID, data["statement_id"]
    assert data["claim_key"] == f"stmt:{STMT_ID}", data["claim_key"]

    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    row = dict(rows[0])
    assert str(row["experiment_id"]) == str(data["experiment_id"]), (row, data)
    assert str(row["method"]) == "formal", row["method"]
    assert str(row["evidence_kind"]) == "proof", row["evidence_kind"]
    assert str(row["result"]) == "supports", row["result"]
    assert str(row["negation_kind"]) == "not_proved", row["negation_kind"]
    assert str(row["claim_key"]) == f"stmt:{STMT_ID}", row["claim_key"]
    assert str(row["code_path"]) == LEAN_REL, row["code_path"]
    assert str(row["code_hash"]) == digest, (row["code_hash"], digest)
    assert int(row["exit_code"]) == 0, row["exit_code"]
    assert str(row["verifier_subject_key"]) == f"stmt:{STMT_ID}", row["verifier_subject_key"]
    assert str(row["verifier_output"]).strip(), row["verifier_output"]
    assert str(row["created_by"]) == "agent-L", row["created_by"]
    observations = dict(row["observations"])
    assert str(observations["checker"]).startswith("lean "), observations
    assert str(observations["tri_state"]) == "verified", observations
    assert observations["verified"] is True, observations
    assert str(observations["output_sha256"]) == str(data["output_sha256"]), observations
    assert str(observations["code_hash"]) == digest, observations
    assert data["evidence_kind"] == "proof", data["evidence_kind"]
    # 产物仍在（登记不许动盘上那一份）
    assert _artifact(ws / LEAN_REL) == (size, digest), "登记之后盘上那份 .lean 变了"


def test_tool_formal_record_row_is_consumed_by_store_closing_and_verify(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """可被消费：那一行能被三个不同的入口真读到，并且不升格命题的证据档。

    三条入口都不是"自己读自己算"：
    (a) 另开一个 `Store(ws)` 从盘上重读（不是写它的那个实例）；
    (b) `closing._leg_reading(..., "proof_experiment_rows", ...)` —— 收工门验收表里
        proof 级形式化实验行那一档的现算入口；
    (c) `verify.verify_all` 的一致性审计：它必须认得这一行不是自报的 proof。

    改前红：把 `agent_l/record.py::_formal_derived` 里的证据档钉成恒定 heuristic
    （也就是业主说的"L 的形式化产出进不了证据链"那一版）⇒ (b) 读到 0 行，(c) 那一行
    也不再是 proof，本用例红。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    made = _call(reg, "formal.formalize", claim=CLAIM, source=_source(),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)
    assert made["status"] == "verified", made["status"]
    data = _call(reg, "formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                 declaration_name=DECL_SHORT)
    assert data["recorded"] is True, data
    eid = str(data["experiment_id"])

    # ---- (a) 另一个 Store 实例从盘上读到同一行
    from agentflow.store import Store

    fresh = Store(ws)
    rows = [dict(r) for r in fresh.rows("experiments")]
    assert [str(r["experiment_id"]) for r in rows] == [eid], rows
    row = rows[0]
    assert str(row["method"]) == "formal", row
    assert str(row["evidence_kind"]) == "proof", row
    assert str(row["code_hash"]) == str(data["code_hash"]), row

    # ---- (b) 收工门那一档的现算入口读到它
    from agentflow import closing as CL

    count, detail = CL._leg_reading(fresh, "proof_experiment_rows", ws)
    assert count == 1, (count, detail)
    assert eid in (detail.get("experiments") or []), detail

    # ---- (c) 一致性审计认得它不是自报的 proof
    from agentflow import verify as V

    rep = V.verify_all(fresh)
    issues = [i for i in rep.issues if str(getattr(i, "table", "")) == "experiments"]
    assert issues == [], [getattr(i, "code", i) for i in issues]
    codes = {str(getattr(i, "code", "")) for i in rep.issues}
    assert "selfreported_proof" not in codes, codes
    assert "unhashed_experiment_code" not in codes, codes
    assert "evidence_kind_overclaim" not in codes, codes

    # ---- 同一条命题的证据档前后不变（不升档），也没有 V 的签名
    before = data["statement_evidence_kind_before"]
    after = data["statement_evidence_kind_after"]
    assert before == after == "heuristic", (before, after)
    stmt_row = next(r for r in Store(ws).rows("statements")
                    if str(r.get("stmt_id")) == STMT_ID)
    assert str(stmt_row["evidence_kind"]) == "heuristic", stmt_row
    assert bool(data["verification_required"]) is True, data
    assert not (ws / "verifications").exists() or not list(
        (ws / "verifications").glob("*.jsonl")), "这一趟不该留下任何 V 的签名"


def test_tool_formal_record_refuses_an_inflated_reading_and_writes_no_row(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """拒绝路径：不给读数（checker / verifier_output / exit_code 全空）却声称 verified ⇒ 拒绝且不写行。

    改前红：把 `agent_l/record.py::_readings_mismatch` 退回成"恒返回空串"（也就是
    直接信调用方口述那一版）⇒ 同一个调用会写进一行，`recorded is False` 与
    "experiments 一行都没有"两条当场红。

    反真空：紧接着用同一份产物、去掉那个口述读数再登记一次 —— 这一次必须成功。
    它成功了，上面那个拒绝才能被归因到"口述比现跑强"，而不是别处顺手拒的。
    """
    _lean_on(monkeypatch)
    st, ws = _workspace(tmp_path)
    reg = _registry(st, ws)
    _skip_unless_usable(ws)

    made = _call(reg, "formal.formalize", claim=CLAIM, source=_source(broken=True),
                 declaration_name=DECL_SHORT, statement_id=STMT_ID)
    assert made["status"] == "failed", (made["status"], made["reason"])
    assert made["exit_code"] != 0, made["exit_code"]
    assert str(made["path"]) == LEAN_REL, made["path"]
    assert (ws / LEAN_REL).is_file(), "failed 那一档也要留下盘上那一份源码"

    inflated = _call(reg, "formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                     declaration_name=DECL_SHORT, verified=True)
    assert inflated["recorded"] is False, inflated
    assert inflated["reason"] == "reading_mismatch", inflated["reason"]
    assert str(inflated["detail"]).strip(), inflated["detail"]
    assert st.rows("experiments") == [], st.rows("experiments")

    quiet = _call(reg, "formal.record", statement_id=STMT_ID, code_path=LEAN_REL,
                  declaration_name=DECL_SHORT)
    assert quiet["recorded"] is True, (quiet["recorded"], quiet["reason"], quiet["detail"])
    rows = st.rows("experiments")
    assert len(rows) == 1, rows
    row = dict(rows[0])
    assert str(row["method"]) == "formal", row
    assert str(row["evidence_kind"]) != "proof", row
    assert str(row["result"]) == "inconclusive", row
    assert str(dict(row["observations"])["tri_state"]) == "checked_failed", row
