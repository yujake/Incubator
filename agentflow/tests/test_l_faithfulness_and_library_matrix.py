# -*- coding: utf-8 -*-
"""L 消费 B 的定理证明库、并把"忠实复述"变成机器读数（五条判据 B4–B6、C7、C8）。

## 这一份判什么

裁定里的第三句是"消费 B 的定理证明库"。它落在两件事上：一是 L 真的按
`statement_id` 读到 B 登记的 `statement_full` 与 `proof_text`（读不到就受控拒绝、
一个字节都不写）；二是"形式化的到底是不是 B 那一条"必须是读数而不是自述 ——
`coverage` / `steps.jsonl` 是那个读数的两个落点。

| 编号 | 判据 | 改前红（本文件加进来之前的那棵树） |
|---|---|---|
| B4 | 真命题（12 步 proof）⇒ `b_library` 五格齐全，且与 `coverage.b_library` 逐键相同；盘上真有那一份 `.lean`（sha256 与返回值一致）；真 Lean 退出 0 | 改前树里没有 `agent_l`（`AgentL` 不存在 ⇒ ImportError）；形式化那一格是 E 的 `run_experiment(method='formal')` + `check_formal`，它的源码里 `b_library` / `coverage` / `steps` / `faithfulness` 一个都没有（HEAD 实测四个都 False） |
| B5 | 不存在的 `statement_id` ⇒ 受控 `statement_not_found`、`written=False`、盘上一个新文件都没有、也不起检查器 | 同上；且改前的 `AgentE.check_formal` 形参是 `(claim, script_path, source, name, imports, timeout_sec)` —— 没有 `statement_id`，传它 TypeError |
| B6 | 转述过的 claim（与库不逐字相同）⇒ `statement_not_found`；逐字那一句（不给编号）⇒ `claim_match`；给了编号却转述 ⇒ `claim_mismatch`（两条不折平） | 同上 |
| C7 | 12/12 覆盖 ⇒ `verified`；漏一步 ⇒ `unknown` 且 `unmapped` 点名第 12 步（检查器那一格仍是 verified，两件事不折叠）；出现 sorry ⇒ `unknown` | 改前没有 `coverage` / `faithfulness` 这两格，也没有 `steps.jsonl` ⇒ 逐键断言全红 |
| C8 | `steps.jsonl` 每一行的 `quote` 都能在 `proof_text` 里逐字找到；`lean_lines` 指向真的 `-- step k` 行 | 改前没有任何逐步对照产物 ⇒ 文件不存在，红 |

## 真 Lean

C7 要真跑检查器：用本机那一版（绝对路径，不依赖 PATH）。跑不动时（文件不在或自检
不是 `usable`）用例如实 `skip` 并把读数写进理由，不伪装通过 —— 而 B4/B5/B6/C8 判的
是"库与对照表"，与检查器在不在无关，所以它们在任何一档下都照样断言。

## 临时文件

工作区全部在 `tmp_path` 下自建；`.lean` / `.steps.jsonl` 随 tmp 一起清掉。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from agentflow import schema as S
from agentflow import settings as SET
from agentflow.agent_l.formalize import (
    B_LIBRARY_KEYS,
    FAITHFULNESS_KEYS,
    HOW_VALUES,
    L_STATEMENT_AND_FAITHFULNESS_REASONS,
    PROOF_PATH_REASONS,
    STATEMENT_REASONS,
    STEP_ROW_KEYS,
)
from agentflow.store import Store

#: 被形式化的那条命题（B 登记的原文；Lean 里那条定理与它逐字同义）。
CLAIM = "forall n : Nat, n + 0 = n"
#: 转述过的那一句：意思一样，一个字符都不同。
PARAPHRASE = "对任意自然数 n，n 加零还是 n。"
#: 命题台账里那一行的编号与标题。
STMT_ID = "000001"
LABEL = "加零不改变自然数"
#: 会话号（递送落点用它；不由环境变量决定，判据才可复现）。
SID = "t"

#: 证明链的步数（空行分段 ⇒ `split_proof_steps` 切出 12 步）。
STEPS = 12

#: 本机那一版真 Lean（绝对路径；PATH 上的 lean 可能是另一个东西）。
#: 真 Lean 的落点：`AGENTFLOW_LEAN_BIN` 优先、没设才退回本机那一版 —— 取值点只有一处
#: （`tests/conftest.py` 的 `lean_path()`；本文件不再写第二份绝对路径）。
from conftest import lean_path

LEAN = lean_path()
HAVE_LEAN = LEAN.is_file()


# ============================================================ 夹具


def _reset_readings() -> None:
    """清掉 `leantoolchain` 的自检缓存与提示词那个 lru_cache（配置重载口）。"""
    from agentflow import agent_prompts as AP
    from agentflow import leantoolchain as LT

    LT.reset_reading_cache()
    AP.reset_toolchain_readings()


def _lean_env(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    """把 Lean 开关钉到某一档；开着时同时把检查器指到本机那一版（绝对路径）。"""
    monkeypatch.setenv(SET.ENV_LEAN_ENABLED, "1" if on else "0")
    if on and HAVE_LEAN:
        monkeypatch.setenv("AGENTFLOW_LEAN_BIN", str(LEAN))
    _reset_readings()


def _skip_unless_usable(ws: pathlib.Path) -> None:
    """真检查器不可用时如实 skip（原因写清：文件不在 / 自检不是 usable）。

    为什么不把这一档写成"断言通过"：`unusable` 是"这台机器上的 lean 不构成检查器"，
    它与"形式化对了"是两件事。把它读成通过，正好是本项目反复登记的那一种折叠。
    """
    from agentflow import leantoolchain as LT

    if not HAVE_LEAN:
        pytest.skip(f"本机没有 {LEAN} ⇒ 这一条要真跑检查器，跳过（不伪装通过）")
    reading = LT.lean_selfcheck_reading(root=ws)
    if str(reading.get("state")) != "usable":
        pytest.skip(
            f"Lean 自检不是 usable（state={reading.get('state')}；"
            f"problems={reading.get('problems')}）⇒ 这一条要真跑检查器，跳过（不伪装通过）")


def _proof_text(steps: int = STEPS) -> str:
    """`steps` 步的证明链：一步一段（空行分段是切分口径的第一档）。"""
    parts = []
    for k in range(1, steps + 1):
        parts.append(f"第 {k} 步：把第 {k - 1} 步的结论代入一次并化简。")
    return "\n\n".join(parts)


def _source(mapped: int = STEPS, *, sorry: bool = False) -> str:
    """Lean 源码：`-- step k` 标出前 `mapped` 步的落点（其后的步没有落点）。"""
    body = "  sorry" if sorry else "  rfl"
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


def _workspace(tmp_path: pathlib.Path, *, steps: int = STEPS) -> tuple[Store, pathlib.Path]:
    """建一个工作区，并让 B 登记一条命题（`proof_text` 是 `steps` 步的证明链）。"""
    ws = tmp_path / "ws"
    st = Store(ws)
    st.init()
    with st.tx("statements", actor="agent-B") as tx:
        tx.upsert("statements", {
            "stmt_id": STMT_ID,
            "label": LABEL,
            "statement": CLAIM,
            "statement_full": CLAIM,
            "proof_text": _proof_text(steps),
            "evidence_kind": "heuristic",
            "status": "active",
            "origin": "own_result",
            "quote_reason": "自产命题（这一组判据不涉及外部原文）",
        }, note="probe:statement")
    return st, ws


def _agent_l(st: Store, ws: pathlib.Path):
    """L 的真实现（零模型；会话落点显式给，递送判据才可复现）。"""
    from agentflow.agent_l import AgentL

    return AgentL(st, workspace_root=ws, config={"session_root": str(ws), "sid": SID})


def _disk_snapshot(root: pathlib.Path) -> list[tuple[str, int]]:
    """工作区的完整文件清单（相对路径 + 字节数），用来判"盘上只多了哪几件"。"""
    out: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out.append((path.relative_to(root).as_posix(), path.stat().st_size))
    return out


def _formal_artifacts(root: pathlib.Path) -> list[str]:
    """工作区里的形式化产物（`.lean` / `.steps.jsonl`）清单。

    "被拒时一个字节都不许写"这条纪律的对象是这两种产物（以及它们所在的
    `code/formal/` 目录）。B 的收件箱（`sessions/<sid>.jsonl`）是另一条通道：
    受控拒绝之后 L 仍会把"这一条与台账对不上"汇报给 B —— 那是裁定的第四句，不是
    形式化产物。两者必须分开读，否则"盘上多了东西"会把一次正确的汇报也算成违约。
    """
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*")
                  if path.is_file()
                  and (path.suffix == ".lean" or path.name.endswith(".steps.jsonl")))


def _new_files(before: list[tuple[str, int]],
               after: list[tuple[str, int]]) -> set[str]:
    """两次快照之间新出现的文件（相对路径）。"""
    return {rel for rel, _size in after} - {rel for rel, _size in before}


# ============================================================ B4 读 B 的库


def test_b4_a_real_statement_gives_a_complete_b_library_reading(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B4：真命题（12 步 proof）⇒ `b_library` 五格齐全，且真的跑过检查器。

    改前红：改前树里没有 `agent_l`（`AgentL` 不存在 ⇒ ImportError）。退一步按源码看，
    改前形式化那一格是 E 的 `run_experiment(method='formal')` + `check_formal`，
    `b_library` / `coverage` / `steps` / `faithfulness` 在那份实现里一个都没有
    （HEAD 实测：`inspect.getsource` 里四个记号全是 False）。

    反真空：`proof_chars` 对着真证明链的字数比、`dependency_steps` 对着真步数比；
    `sha256` 对着盘上那份字节现算 —— 三格都不许是常量。
    """
    _lean_env(monkeypatch, True)
    st, ws = _workspace(tmp_path)
    agent = _agent_l(st, ws)
    data = agent.formalize(CLAIM, source=_source(), statement_id=STMT_ID)

    lib = dict(data.get("b_library") or {})
    assert sorted(lib) == sorted(B_LIBRARY_KEYS), sorted(lib)
    assert lib["stmt_id"] == STMT_ID, lib
    assert lib["label"] == LABEL, lib
    assert lib["found"] is True, lib
    assert lib["proof_chars"] == len(_proof_text()), (lib, len(_proof_text()))
    assert lib["dependency_steps"] == STEPS, lib

    # 同一个读数也进 coverage（汇总那一格），且逐键相同
    coverage = dict(data.get("coverage") or {})
    assert dict(coverage.get("b_library") or {}) == lib, coverage.get("b_library")
    assert data.get("statement_source") == "explicit", data.get("statement_source")
    assert data.get("statement_id") == STMT_ID, data.get("statement_id")

    # 盘上真有那一份 .lean，返回值里的 sha256 与字节一致（不是"我写过了"的自述）
    rel = str(data.get("path") or "")
    assert rel.endswith(".lean"), rel
    on_disk = (ws / rel).read_bytes()
    assert hashlib.sha256(on_disk).hexdigest() == data.get("sha256"), rel
    assert int(data.get("bytes") or 0) == len(on_disk), data.get("bytes")

    # 真的跑过检查器：退出码 0、检查器原话非空、结论 verified
    _skip_unless_usable(ws)
    assert data.get("status") == "verified", (data.get("status"), data.get("reason"),
                                              data.get("detail"))
    assert data.get("checker_status") == "verified", data.get("checker_status")
    assert data.get("exit_code") == 0, data.get("exit_code")
    assert str(data.get("verifier_output") or "").strip(), data.get("verifier_output")
    assert data.get("faithfulness") == "complete", data.get("faithfulness")


# ============================================================ B5 编号不在册


def test_b5_an_unknown_statement_id_is_refused_and_writes_nothing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B5：不存在的 `statement_id` ⇒ `statement_not_found`、不写盘、不起检查器。

    改前红：改前 `AgentL` 不存在（ImportError）；改前的 `AgentE.check_formal` 形参是
    `(claim, script_path, source, name, imports, timeout_sec)` —— 没有 `statement_id`，
    传它直接 TypeError。"按编号读库"这件事整条不存在。

    反真空：`written=False` 与整棵目录树的清单相等是两件事，两件都断言；
    再加一道"起检查器就算违约"的替身（`check_formal` 换成会抛的实现）。
    """
    _lean_env(monkeypatch, False)
    st, ws = _workspace(tmp_path)
    agent = _agent_l(st, ws)

    def _boom(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("取不到 B 的库时不许可起检查器")

    monkeypatch.setattr(type(agent), "check_formal", _boom)
    before = _disk_snapshot(ws)
    artifacts_before = _formal_artifacts(ws)
    data = agent.formalize(CLAIM, source=_source(), statement_id="999999")

    assert data.get("refused") is True, data.get("refused")
    assert data.get("reason") == "statement_not_found", data.get("reason")
    assert data.get("reason") in STATEMENT_REASONS, STATEMENT_REASONS
    assert data.get("written") is False, data.get("written")
    assert data.get("path") == "", data.get("path")
    assert data.get("status") == "unknown", data.get("status")
    assert str(data.get("detail") or "").strip(), data.get("detail")

    # 取不到库那一支上 b_library 仍然在（键集合处处成立），只是 found=False
    lib = dict(data.get("b_library") or {})
    assert sorted(lib) == sorted(B_LIBRARY_KEYS), sorted(lib)
    assert lib["found"] is False, lib
    assert lib["stmt_id"] == "999999", lib
    # 忠实复述那八格在拒绝分支上也在（键集合不许随分支变）
    for key in FAITHFULNESS_KEYS:
        assert key in data, f"被拒分支上少了 {key} 这一格"

    after = _disk_snapshot(ws)
    assert _formal_artifacts(ws) == artifacts_before == [], (
        f"被拒时盘上多了形式化产物：{_formal_artifacts(ws)}")
    assert not (ws / "code" / "formal").exists(), "被拒时还建了 code/formal 目录"
    # 唯一允许的新落点是 B 的收件箱：那条汇报是裁定的第四句，不是形式化产物
    assert _new_files(before, after) <= {"sessions/t.jsonl"}, _new_files(before, after)
    assert dict(data.get("report") or {}).get("state") == "reported", data.get("report")


# ============================================================ B6 转述的 claim


def test_b6_a_paraphrased_claim_does_not_match_the_library(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B6：转述过的 claim ⇒ `statement_not_found`；逐字那一句才认得出源。

    改前红：改前没有这条路 —— 形式化那一格是 E 的 `run_experiment(method='formal')`，
    `claim` 是一段自由文本，转述与原文在它眼里毫无区别（也就没有理由码可断言）；
    而 `AgentL` 在那棵树上不存在（ImportError）。

    三条来源各判一次，且两条拒绝理由不许折平：
    - 不给编号 + 转述 ⇒ `statement_not_found`（认不出来源）；
    - 不给编号 + 逐字 ⇒ `statement_source="claim_match"`（正控：证明上面那条不是
      "任何不给编号的调用都被拒"）；
    - 给了编号 + 转述 ⇒ `claim_mismatch`（"认不出来源"与"认出来了但不是这一条"
      是两件事，处置不同）。
    """
    _lean_env(monkeypatch, False)
    st, ws = _workspace(tmp_path)
    agent = _agent_l(st, ws)

    before = _disk_snapshot(ws)
    artifacts_before = _formal_artifacts(ws)
    lost = agent.formalize(PARAPHRASE, source=_source(), statement_id=None)
    assert lost.get("refused") is True, lost.get("refused")
    assert lost.get("reason") == "statement_not_found", lost.get("reason")
    assert lost.get("reason") in STATEMENT_REASONS, lost.get("reason")
    assert lost.get("written") is False, lost.get("written")
    assert _formal_artifacts(ws) == artifacts_before == [], (
        f"认不出来源时还写了形式化产物：{_formal_artifacts(ws)}")
    assert _new_files(before, _disk_snapshot(ws)) <= {"sessions/t.jsonl"}, (
        "认不出来源时盘上多出来的不只是 B 的收件箱")

    # 正控：逐字那一句（不给编号）必须认得出源
    ok = agent.formalize(CLAIM, source=_source(), statement_id=None)
    assert ok.get("refused") is False, (ok.get("refused"), ok.get("reason"))
    assert ok.get("statement_source") == "claim_match", ok.get("statement_source")
    assert ok.get("statement_id") == STMT_ID, ok.get("statement_id")

    # 给了编号却转述：另一条受控拒绝，与上面那条不折平
    wrong = agent.formalize(PARAPHRASE, source=_source(), statement_id=STMT_ID)
    assert wrong.get("refused") is True, wrong.get("refused")
    assert wrong.get("reason") == "claim_mismatch", wrong.get("reason")
    assert wrong.get("reason") != lost.get("reason"), (
        "「认不出来源」与「认出来了但不是这一条」被折成同一个理由码")
    assert set(STATEMENT_REASONS) >= {"statement_not_found", "claim_mismatch"}, (
        sorted(set(STATEMENT_REASONS)))


# ============================================================ C7 忠实复述三档


def test_c7_twelve_of_twelve_is_verified_missing_step_and_sorry_are_unknown(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C7：12/12 ⇒ verified；漏一步 ⇒ unknown 且点名；sorry ⇒ unknown。

    改前红：改前没有 `coverage` / `faithfulness` / `checker_status` 这几格
    （`KeyError`），也没有 `steps.jsonl`；"逐步对照"那时只是一句文字义务。

    三档各自与"检查器说了什么"分开读：漏一步那一档的 `checker_status` 仍然是
    verified（机器核过了），而综合结论是 unknown（这一趟不算数）—— 这两件事在
    返回值里各有一格，折叠掉任何一格都会被下面某条断言抓到。
    """
    _lean_env(monkeypatch, True)
    st, ws = _workspace(tmp_path)
    _skip_unless_usable(ws)
    agent = _agent_l(st, ws)

    full = agent.formalize(CLAIM, source=_source(), statement_id=STMT_ID)
    cov = dict(full.get("coverage") or {})
    assert cov.get("steps_total") == STEPS, cov
    assert cov.get("steps_mapped") == STEPS, cov
    assert cov.get("unmapped") == [], cov
    assert full.get("status") == "verified", (full.get("status"), full.get("reason"),
                                              full.get("detail"))
    assert full.get("checker_status") == "verified", full.get("checker_status")
    assert full.get("faithfulness") == "complete", full.get("faithfulness")

    missed = agent.formalize(CLAIM, source=_source(STEPS - 1), statement_id=STMT_ID)
    miss_cov = dict(missed.get("coverage") or {})
    assert miss_cov.get("steps_mapped") == STEPS - 1, miss_cov
    assert miss_cov.get("unmapped") == [STEPS], miss_cov
    assert missed.get("status") == "unknown", (missed.get("status"), missed.get("reason"))
    assert missed.get("reason") == "faithfulness_incomplete", missed.get("reason")
    assert missed.get("faithfulness") == "incomplete", missed.get("faithfulness")
    assert str(STEPS) in str(missed.get("detail") or ""), missed.get("detail")
    # 机器说通过、而逐步对照不过：两格各留各的读数（不许折叠）
    assert missed.get("checker_status") == "verified", missed.get("checker_status")

    holes = agent.formalize(CLAIM, source=_source(sorry=True), statement_id=STMT_ID)
    hole_cov = dict(holes.get("coverage") or {})
    assert hole_cov.get("sorry_lines"), hole_cov
    assert holes.get("status") == "unknown", (holes.get("status"), holes.get("reason"))
    assert holes.get("reason") == "faithfulness_sorry", holes.get("reason")
    assert holes.get("faithfulness") == "holes", holes.get("faithfulness")
    # 检查器那一档的原话仍在（含 sorry 的文件会编译通过，所以它可能说 verified）
    assert str(holes.get("checker_status") or "") != "", holes.get("checker_status")
    assert holes.get("status") != "verified", "含 sorry 的源码被读成了 verified"


# ============================================================ C8 steps.jsonl


def test_c8_every_steps_row_quotes_the_proof_text_verbatim(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """C8：`steps.jsonl` 每一行都能在 `proof_text` 里逐字找到（逐行）。

    改前红：改前没有任何逐步对照产物（`steps_path` 这一格都不存在，文件更不在），
    所以第一句"文件存在"就红。

    这一条与检查器无关：`steps.jsonl` 在自检闸之前就落盘了，所以开关关着也照样断言
    （零 Lean、零子进程）。反真空有两层：行数必须等于真步数；每行的 `lean_lines`
    起止行必须真的落在源码里那一行 `-- step k` 上（只断言"有两行号"是真空的）。
    """
    _lean_env(monkeypatch, False)
    st, ws = _workspace(tmp_path)
    agent = _agent_l(st, ws)
    data = agent.formalize(CLAIM, source=_source(), statement_id=STMT_ID)

    steps_rel = str(data.get("steps_path") or "")
    assert steps_rel.endswith(".steps.jsonl"), steps_rel
    steps_file = ws / steps_rel
    assert steps_file.is_file(), f"盘上没有 {steps_rel}"

    rows = [json.loads(line) for line in
            steps_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == STEPS, len(rows)
    assert [row.get("proof_step") for row in rows] == list(range(1, STEPS + 1)), (
        [row.get("proof_step") for row in rows])

    proof_flat = " ".join(_proof_text().split())
    source_lines = (ws / str(data.get("path") or "")).read_text(encoding="utf-8").splitlines()
    for row in rows:
        assert sorted(row) == sorted(STEP_ROW_KEYS), sorted(row)
        quote = str(row.get("quote") or "")
        assert quote, row
        assert quote in proof_flat, (row.get("proof_step"), quote)
        how = str(row.get("how") or "")
        assert how in HOW_VALUES, how
        lines = list(row.get("lean_lines") or [])
        assert len(lines) == 2, lines
        first, last = int(lines[0]), int(lines[1])
        assert 1 <= first <= last <= len(source_lines), (lines, len(source_lines))
        marker = source_lines[first - 1].strip().lower()
        assert marker.startswith("-- step"), (row.get("proof_step"), marker)
        assert int(marker.split()[-1]) == int(row.get("proof_step")), (row, marker)

    coverage = dict(data.get("coverage") or {})
    assert coverage.get("steps_mapped") == STEPS, coverage
    assert coverage.get("how", {}).get("直接对应") == STEPS, coverage.get("how")

    # 受控理由词表里确实有上面用到的那两个码（FC-03：不在测试里手抄一份）。
    # L 的理由表今天是两张：`_support.FORMAL_REASONS_L`（桥接 + 自检 + record）与
    # `formalize.L_STATEMENT_AND_FAITHFULNESS_REASONS`（台账 + 路径 + 忠实复述），两个都要读。
    assert "faithfulness_incomplete" in L_STATEMENT_AND_FAITHFULNESS_REASONS
    assert "faithfulness_sorry" in L_STATEMENT_AND_FAITHFULNESS_REASONS
    assert "statement_not_found" in L_STATEMENT_AND_FAITHFULNESS_REASONS
    assert set(L_STATEMENT_AND_FAITHFULNESS_REASONS) <= \
        set(STATEMENT_REASONS) | set(PROOF_PATH_REASONS) | {
            "faithfulness_incomplete", "faithfulness_sorry", "faithfulness_extra_steps"}
    # 路径那两个码是 2026-10-22 晚加的（业主裁定「要指明对哪个路径做了形式化验证」）：
    # 它们必须在受控词表里，而不是只活在 `_path_choice` 的字符串里。
    assert set(PROOF_PATH_REASONS) == {"proof_path_not_found", "proof_path_unspecified"}, (
        sorted(PROOF_PATH_REASONS))
    assert "L" in S.ROLES, "L 不在角色词表里 ⇒ 这一整份判据的前提不成立"
