# -*- coding: utf-8 -*-
"""B 收录的第二条入口：逐份 inline 登记也要分配路径号（业主 2026-11-11 追加裁定）。

## 缺陷（收尾批实测）

B 收录有两条入口：

| # | 入口 | 改后 |
|---|---|---|
| ① | 按手稿收录（`ingest_manuscript` / D→B 指针支） | 号由秘书在收录事务里分（`assign_path_group`），`path_group` 1/2 正确 |
| ② | 逐份 inline 登记（`register_statement` 里那一支把 `proofs` 逐条挂上） | 同上：B 不再自己算，回执里的 `path_group` 一路用到底 |

这一份钉的是"同一个「第几条证明」在两条入口上是同一个号"：`dependencies.path_group` /
`used_by` 的 `#pN` / `verifications.path_group` 三者同号。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | ② 逐份 inline 登记第二份不同正文 | 依赖行 `used_by="stmt:<号>#p2"` 且 `path_group=2`；覆盖这份正文的 `verifications` 行 `path_group=2`（三者同号） |
| b | ② 登记第一份 | 依赖行 `used_by="stmt:<号>"`（无 `#p1`，沿既有口径）且 `path_group=1`；`verifications.path_group=1` |
| c | 同 sha 重复逐份登记 | 仍 2 条路径、号不变（幂等）：证明号仍 `[1, 2]`、依赖组仍 `{1, 2}`，不说成第 3 条 |
| d | 同一份证明分别走 ① 与 ② | 两条入口拿到的 `path_group` 相同（都 = 2） |
| e | 反真空：把唯一的分配实现打成"永远第 1 条" | a 必须红 —— 第二份证明的依赖面回落成「`#p2` 的痕迹顶着第 1 条路径」/ 整条丢失，`verifications` 也没有号 |

全部 tmp 工作区、零模型调用（V 的签走 conftest 的真写口）。第一份证明也走 ②（`proofs=[{1,…}]`），
于是两条入口的起点逐字相同 —— d 比的是"同一份证明、同一个盘面"，不是两个不同的盘面。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
_TESTS = pathlib.Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import conftest  # noqa: E402

from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import manuscriptsubmission as MS  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

#: 被引的那条在册命题（要够可引档：`pre_theorem` 及以上）。
DEP_SID = "000000"
PROPOSITION = "对任意有限群 G，若 p 整除 |G|，则 G 有 p 阶元。"
OWN = {"statement_full": PROPOSITION, "statement_text": "p 阶元",
       "origin": "own_result", "kind": "conjecture", "doc_id": S.format_id(0),
       "quote_reason": "我方自产命题，没有外部引文要比对"}
P1 = f"1. 由 stmt:{DEP_SID} 直接推出。"
P2 = f"另一条路线：由 stmt:{DEP_SID} 与双陪集计数推出。"
#: 第二份证明的稿（F 的稿号段；只当签的载体与依赖段的来处）。
MS2_REL = "reports/f-proof-000777.md"


# ------------------------------------------------------------------ 工作区

def _ws(tmp_path: pathlib.Path, name: str = "ws") -> tuple[Store, AgentB]:
    st = Store(tmp_path / name)
    st.init()
    return st, AgentB(st, extractor=None, extract_text=None, config={})


def _citable(st: Store) -> None:
    """一条够档的在册命题（手稿依赖段的引用门槛：`proof_review` 及以上）。"""
    conftest.seed_statement_row(st, stmt_id=DEP_SID, statement_full="引理：p 阶元",
                                kind="lemma", proof_text="引理：p 阶元")
    conftest.sign_for_the_gate(st.root, statement_id=DEP_SID,
                               proof_text="引理：p 阶元", store=st)
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == DEP_SID)
    bits = dict(row.get("bits") or {})
    bits["proof"] = True
    ev = dict(bits.get("evidence") or {})
    ev.setdefault("proof_process", str(row.get("proof_text") or ""))
    bits["evidence"] = ev
    bits["grade"] = EB.derive_grade(bits, kind="lemma")
    with st.tx("statements", actor="夹具") as tx:
        tx.upsert("statements", dict(row, bits=bits))


def _manuscript(sid: str, proof: str) -> str:
    """一份三节稿：`## 命题` / `## 证明` / `## 依赖`（依赖段只写三列）。

    产出侧不写「证明号」、也不写依赖表的「路径号」列 —— 路径号由秘书收录时分配。
    """
    rows = [{"stmt_id": DEP_SID, "quote": "引理：p 阶元", "step": "1",
             "path_group": 1}]
    head = "# F 的证明手稿\n\n"
    head += f"- 命题号：stmt:{sid}\n"
    # 三列（引用 / 命题号 / 步）：手写一张新形式表，不借 renderer 的四列。
    deps = ("| 引用 | 命题号 | 步 |\n|---|---|---|\n"
            f"| 引理：p 阶元 | stmt:{DEP_SID} | 1 |\n")
    return (head + "\n## 命题\n\n" + PROPOSITION + "\n\n## 证明\n\n" + proof
            + "\n\n## 依赖\n\n" + deps)


def _write(st: Store, rel: str, text: str) -> None:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _first_proof(st: Store, b: AgentB) -> str:
    """登记命题 + 第一份证明（走 ②：`proofs=[{1, …}]`）⇒ 返回命题号。"""
    _citable(st)
    made = b.register_statement(**OWN)
    assert made.get("ok") is True, made
    sid = str(made["stmt_id"])
    rel = f"reports/f-proof-{sid}.md"
    ms1 = _manuscript(sid, P1)
    _write(st, rel, ms1)
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=P1, store=st,
                               manuscript=rel)
    first = b.register_statement(**OWN, proofs=[{"proof_no": 1, "text": P1}],
                                 proof_manuscript=rel)
    assert first.get("ok") is True, first
    return sid


def _second_proof(st: Store, b: AgentB, sid: str) -> dict:
    """逐份 inline 登记第二份证明（正文 + 手稿路径；稿头不写「证明号」）。"""
    ms2 = _manuscript(sid, P2)
    _write(st, MS2_REL, ms2)
    conftest.sign_for_the_gate(st.root, statement_id=sid, proof_text=P2, store=st,
                               manuscript=MS2_REL)
    return b.register_statement(**OWN, proof_text=P2, proof_manuscript=MS2_REL)


# ------------------------------------------------------------------ 读数

def _deps(st: Store, sid: str) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")
            if str(r.get("used_by") or "").split("#", 1)[0] == f"stmt:{sid}"]


def _verifications(st: Store, sid: str, text: str) -> list[dict]:
    rows, bad = VR.list_verifications(st.root, statement_id=sid, limit=None)
    assert bad == [], bad
    sha = VR.text_sha(text)
    return [dict(r) for r in rows if str(r.get("proof_sha256") or "") == sha]


def _proof_nos(st: Store, sid: str) -> list[int]:
    row = next(dict(r) for r in st.rows("statements")
               if str(r.get("stmt_id")) == sid)
    return [int(no) for no, _text in VR.proof_list(row)]


def _path_problems(st: Store, sid: str) -> list[str]:
    """判据 a 的本体（正控与反真空共用同一份读数）：空列表 = 三者同号。

    三条一起看，缺一条都不算：
    - 依赖行：`used_by="stmt:<号>#p2"` 的那一行 `path_group` 必须是 2；
    - `verifications`：覆盖第二份正文的行必须都是 `path_group=2`；
    - 不允许"#p2 的痕迹顶着第 1 条路径"（依赖行的号与路径号分家）。
    """
    problems: list[str] = []
    deps = _deps(st, sid)
    p2_rows = [d for d in deps if str(d.get("used_by")) == f"stmt:{sid}#p2"]
    if not p2_rows:
        problems.append(
            "依赖表里没有 `used_by=stmt:<号>#p2` 那一行（第二份证明的依赖面没建起来）"
            f"：{[ (d.get('used_by'), d.get('path_group')) for d in deps ]!r}")
    else:
        bad = [(d.get("used_by"), d.get("path_group")) for d in p2_rows
               if int(d.get("path_group") or 1) != 2]
        if bad:
            problems.append(f"`#p2` 那一行的 `path_group` 不是 2：{bad!r}")
    ver = _verifications(st, sid, P2)
    if not ver:
        problems.append("`verifications` 里没有覆盖第二份正文的行")
    else:
        bad_ver = [r.get("path_group") for r in ver
                   if int(r.get("path_group") or 0) != 2]
        if bad_ver:
            problems.append(
                f"覆盖第二份正文的 verification 行里 `path_group` 不是 2：{bad_ver!r}"
                f"（三条读数：{[ (d.get('used_by'), d.get('path_group')) for d in deps ]!r}"
                f" / {[r.get('path_group') for r in ver]!r}）")
    return problems


def _first_path_problems(st: Store, sid: str) -> list[str]:
    """判据 b 的本体：第一份证明的三处号都是 1（`used_by` 不带 `#p1`）。"""
    problems: list[str] = []
    deps = _deps(st, sid)
    canon = [d for d in deps if str(d.get("used_by")) == f"stmt:{sid}"]
    if not canon:
        problems.append(
            "依赖表里没有 `used_by=stmt:<号>` 那一行（第 1 份证明的依赖面）"
            f"：{[ (d.get('used_by'), d.get('path_group')) for d in deps ]!r}")
    else:
        bad = [(d.get("used_by"), d.get("path_group")) for d in canon
               if int(d.get("path_group") or 0) != 1]
        if bad:
            problems.append(f"第 1 份证明的依赖行 `path_group` 不是 1：{bad!r}")
    if any("#p1" in str(d.get("used_by") or "") for d in deps):
        problems.append("第一份证明的 `used_by` 里出现了 `#p1` 尾巴（既有口径不带它）")
    ver = _verifications(st, sid, P1)
    if not ver:
        problems.append("`verifications` 里没有覆盖第一份正文的行")
    else:
        bad_ver = [r.get("path_group") for r in ver
                   if int(r.get("path_group") or 0) != 1]
        if bad_ver:
            problems.append(f"第一份证明的 verification 行 `path_group` 不是 1：{bad_ver!r}")
    return problems


# ============================================================ a：第二份 = 2
def test_a_the_second_inline_proof_is_path_two(tmp_path):
    st, b = _ws(tmp_path)
    sid = _first_proof(st, b)
    got = _second_proof(st, b, sid)
    assert got.get("ok") is True, got
    problems = _path_problems(st, sid)
    assert problems == [], problems
    # 读数原样带出来（红的时候能直接看出三处分家的样子）。
    deps = [(str(d.get("used_by")), int(d.get("path_group") or 0))
            for d in _deps(st, sid)]
    ver = [r.get("path_group") for r in _verifications(st, sid, P2)]
    assert f"stmt:{sid}#p2" in {u for u, _ in deps}, deps
    assert all(pg == 2 for u, pg in deps if u == f"stmt:{sid}#p2"), deps
    assert ver and all(int(g or 0) == 2 for g in ver), ver


# ============================================================ b：第一份 = 1
def test_b_the_first_inline_proof_is_path_one(tmp_path):
    st, b = _ws(tmp_path)
    sid = _first_proof(st, b)
    problems = _first_path_problems(st, sid)
    assert problems == [], problems
    deps = [(str(d.get("used_by")), int(d.get("path_group") or 0))
            for d in _deps(st, sid)]
    ver = [r.get("path_group") for r in _verifications(st, sid, P1)]
    assert deps == [(f"stmt:{sid}", 1)], deps
    assert ver and all(int(g or 0) == 1 for g in ver), ver


# ============================================================ c：幂等
def test_c_repeating_the_same_proof_keeps_the_same_path(tmp_path):
    st, b = _ws(tmp_path)
    sid = _first_proof(st, b)
    first = _second_proof(st, b, sid)
    assert first.get("ok") is True, first
    before = MS.path_reading(st, st.root, statement_id=sid)
    assert before["count"] == 2, before
    # 同一份正文（同 sha / 同一份稿）再逐份登记一次。同一条记录再交一次是一次重复
    # 读数（`duplicate_statement`），不是"第 3 条证明"—— 这里要钉的是路径面没动。
    again = _second_proof(st, b, sid)
    assert again.get("ok") is True or again.get("kind") == "duplicate_statement", again
    after = MS.path_reading(st, st.root, statement_id=sid)
    assert after["count"] == before["count"] == 2, (before, after)
    assert _proof_nos(st, sid) == [1, 2], _proof_nos(st, sid)
    groups = sorted({int(d.get("path_group") or 0) for d in _deps(st, sid)})
    assert groups == [1, 2], groups
    ver = [r.get("path_group") for r in _verifications(st, sid, P2)]
    assert ver and all(int(g or 0) == 2 for g in ver), ver
    assert not any("#p3" in str(d.get("used_by") or "") for d in _deps(st, sid)), (
        "重复登记把同一份证明记成了第 3 条路径")


# ============================================================ d：两条入口同号
def test_d_both_entrances_pick_the_same_path_number(tmp_path):
    # ②：逐份 inline 登记
    st_inline, b_inline = _ws(tmp_path, "inline")
    sid_inline = _first_proof(st_inline, b_inline)
    inline = _second_proof(st_inline, b_inline, sid_inline)
    assert inline.get("ok") is True, inline
    inline_pg = dict(inline.get("path_group") or {})
    # ①：按手稿收录（`ingest_manuscript(mode="apply")`，与 D→B 指针支同一个分配口）
    st_ingest, b_ingest = _ws(tmp_path, "ingest")
    sid_ingest = _first_proof(st_ingest, b_ingest)
    ms2 = _manuscript(sid_ingest, P2)
    _write(st_ingest, MS2_REL, ms2)
    conftest.sign_for_the_gate(st_ingest.root, statement_id=sid_ingest, proof_text=P2,
                               store=st_ingest, manuscript=MS2_REL)
    from agentflow import conductor as CND

    task = S.Task(task_id="t-000001", role="B", action="ingest_manuscript",
                  called_by="D", depth=1, status="running", started_at=S.now_iso(),
                  input_key="inline-path-group")
    with st_ingest.tx("tasks", actor="夹具") as tx:
        tx.upsert("tasks", task.to_dict())
    with CND.calling_as("t-000001", "B", parent_task_id="t-000009", parent_role="D"):
        ingest = b_ingest.ingest_manuscript(
            manuscript=MS2_REL, target_stmt_id=sid_ingest,
            cells=["proof_text", "dependencies"], mode="apply")
    assert ingest.get("ok") is True, ingest
    ingest_pg = dict(ingest.get("path_group") or {})
    assert ingest_pg.get("path_group") == 2, ingest_pg
    assert inline_pg.get("path_group") == 2, inline_pg
    assert int(ingest_pg["path_group"]) == int(inline_pg["path_group"]), (
        ingest_pg, inline_pg)
    # 两条入口落出的依赖面也同形（不只是回执里的一个数）。
    for st, sid in ((st_inline, sid_inline), (st_ingest, sid_ingest)):
        deps = _deps(st, sid)
        assert [(str(d.get("used_by")), int(d.get("path_group") or 0)) for d in deps] == [
            (f"stmt:{sid}", 1), (f"stmt:{sid}#p2", 2)], deps


# ============================================================ e：反真空
def test_e_removing_the_allocation_turns_a_red(tmp_path, monkeypatch):
    """把路径号分配摘掉（永远第 1 条）⇒ a 必须红（回到"第 2 条顶着第 1 条路径"那一边）。

    打桩点取分配的唯一实现（`manuscriptsubmission.assign_path_group`，实现
    `manuscriptpaths`）：秘书那一笔事务里调的就是它。它一旦恒返回 1，第二份证明的
    依赖面要么整条不落（`#p2` 那一行读不到），要么回落成 `path_group=1`，而
    `verifications` 那一份也没有 2 —— 正控（不打桩）是同一条判据全绿。
    """
    # 正控：不打桩 ⇒ a 的判据全绿（否则这条反真空测的是桩本身）
    st_ok, b_ok = _ws(tmp_path, "control")
    sid_ok = _first_proof(st_ok, b_ok)
    assert _second_proof(st_ok, b_ok, sid_ok).get("ok") is True
    assert _path_problems(st_ok, sid_ok) == [], _path_problems(st_ok, sid_ok)

    # 打桩：唯一实现永远给第 1 条
    real = MS.assign_path_group

    def _always_one(**_kw):
        return {"checked": True, "path_group": 1, "existing": False, "count": 1,
                "paths": [], "why": "打桩：永远第 1 条"}

    monkeypatch.setattr(MS, "assign_path_group", _always_one)
    st, b = _ws(tmp_path, "stubbed")
    sid = _first_proof(st, b)
    got = _second_proof(st, b, sid)
    assert got.get("ok") is True, got
    problems = _path_problems(st, sid)
    assert problems, "摘掉分配之后判据 a 仍然全绿 ⇒ 那不是这一笔写对的"
    deps = [(str(d.get("used_by")), int(d.get("path_group") or 0))
            for d in _deps(st, sid)]
    ver = [r.get("path_group") for r in _verifications(st, sid, P2)]
    # 旧形状：`#p2` 的痕迹没有落在第 2 条路径上（要么那一行整条没落，要么顶着 1）。
    assert (not any(u == f"stmt:{sid}#p2" and pg == 2 for u, pg in deps)), (
        f"分配被摘掉之后 `#p2` 仍落在第 2 条路径上（旧形状没有复现）：{deps!r}")
    assert (not ver) or any(int(g or 0) != 2 for g in ver), (
        f"分配被摘掉之后 verification 行仍带 2：{ver!r}")
    monkeypatch.setattr(MS, "assign_path_group", real)

# ============================================================ 同种证明那一问的默认回答
import pytest as _pytest  # noqa: E402


@_pytest.fixture(autouse=True)
def _proof_kind_default(monkeypatch):
    """这一组量的是路径号 / 收录，不是同种证明的语义判别 ⇒ 默认回 different。

    2026-11-12 起"同种证明"改由秘书的语义判定给（禁机械闸）；没有判定面时按
    fail-closed 拒收，会把这里的第二份证明全部拒掉。语义判别本身的判据在
    `tests/test_rehearsal_two_f_independent_proofs.py`。
    """
    import agentflow.secretary as _SEC

    real = _SEC.Secretary.judge

    def _judge(self, kind, context, **kw):
        if kind == "proof_kind":
            return {"checked": True, "decision": "different", "same_path": 0,
                    "reason": "夹具：不同种", "basis": [], "cost": {}}
        return real(self, kind, context, **kw)

    monkeypatch.setattr(_SEC.Secretary, "judge", _judge)
