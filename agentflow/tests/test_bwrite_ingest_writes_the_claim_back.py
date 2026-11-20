# -*- coding: utf-8 -*-
"""BWRITE：B 收录那一笔必须把命题号回写到被认领的 pending 台账行（真机 `lp-ball-10`）。

## 现场（只读取证，2026-11-20）

`projects/lp-ball-10` 的 `stmt:000015`：`verifications/pending/ef286c92….jsonl` 里有
**4 行**盖住同一份正文（u-000022..u-000025，`成立` / 未解决 error 0），而四行的
`statement_id` / `stmt_id` **全空**、没有 `claimed_at`：

| 时刻 | 事件 | 证据 |
|---|---|---|
| 13:39:19..13:42:16 | V 三转同一份正文（`review_call=b8bc9203a2d3`），13:42:16 发签 | `out/vsigns/4e418348….json` 的 `passes` 就是那三行 |
| 13:42:52 | 第 4 转（u-000025）落在同一叠 | 同一份 pending jsonl |
| 13:46:35 | `own.register_statement` 落 `stmt:000015`（`bits.reviewed=false`） | `runs/B-20261119-134835-001.json` 第 5 步 |
| 13:47:02 | `own.ingest_manuscript(mode=apply, cells=[proof_text], target=000015)` 把那一签认进第 3 位 | 同文件第 7 步：`evidence.sign_claim.claim.bound=false` |

根因不是判据该放宽，而是**认领这一拍没有写口调用**：`vsigns.bits_after_sign` 交回来的
`claim` 只在 `register_statement` 的"新建"支被交给 `vsigns.bind_pending_claim`
（那里要求 `bits.reviewed` 为真，而登记那一笔还是 false）；`ingest_manuscript`
这一支（先登记、后收录）只把 `claim` 当回执带出去，pending 行一个字节都没改。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | 在册行 + 4 行 pending 覆盖同一正文 + 收录成功 | 4 行都回写 `statement_id`；`_claimed_pending_rows` 读得到；V2FIX 那一路 `missing=[]` |
| b1 | 收录被拒（签盖的是另一版正文） | 不回写：pending 行仍空号，且没有 `claimed_at` |
| b2 | 收录没落成 / 没有命题号（直接喂 `_bind_ingested_claim`） | 一个字节都不写（不许写空号冒充认领） |
| c | 反真空：把 ③ 那一拍（`vsigns.bind_pending_claim`）打桩成不写 | a 的断言当场红 |

零模型调用；pending 走生产写口 `verifications.record_pending_sign`，签走
`vsigns.issue`（与 `_credential_fixture` 同一份发签口），不手写 jsonl。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import conftest  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.store import Store  # noqa: E402

FULL = "设 f 在 [0,1] 上连续，则 f 一致连续。"
PROOF = "取 δ=ε，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
#: 改一个字（`ε` → `ε/2`）：签盖的是旧正文，这一版认不到（负控用）。
PROOF_CHANGED = "取 δ=ε/2，逐点验证：|x-y|<δ ⇒ |f(x)-f(y)|<ε。"
REL = "reports/f-proof-000000.md"
CALL = "bwrite-b8bc9203a2d3"
LATER_CALL = "bwrite-later-1"
AT = ("2026-11-19T13:39:19+08:00", "2026-11-19T13:40:39+08:00",
      "2026-11-19T13:42:16+08:00", "2026-11-19T13:42:52+08:00")
OK = {"verdict": "成立", "findings": []}
CLEAN = {"checked": True, "axis": "clean", "decision": "没问题",
         "reason": "夹具：秘书判 clean"}


def _ws(tmp_path: pathlib.Path) -> tuple[Store, AgentB]:
    st = Store(tmp_path / "ws")
    st.init()
    return st, conftest.b_form_gate_ok(
        AgentB(st, extractor=None, extract_text=None, config={}))


def _manuscript(proof: str = PROOF) -> str:
    from agentflow import depsection as DS

    return ("# F 的证明手稿（夹具）\n\n- 计划：0000\n\n"
            "## 命题\n\n" + FULL + "\n\n"
            "## 证明\n\n" + proof + "\n\n"
            + DS.render_dependency_section([]) + "\n")


def _write(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _pending_stack(st: Store, *, body: str, later_rounds: int = 1) -> dict:
    """铺出 lp-ball-10 那一叠：三转同源 + 发签 + 之后又落几转（全空号）。

    返回 `{path, rows, credential}`；`rows` 是盘上最终的全部行（3 + `later_rounds`）。
    """
    manuscript = _write(st, REL, _manuscript(body))
    object_sha = hashlib.sha256(manuscript.read_bytes()).hexdigest()
    first = [VR.record_pending_sign(
        st.root, proof_text=body, verdict=dict(OK), object_path=REL,
        object_sha256=object_sha, secretary_judge=dict(CLEAN),
        review_call=CALL, review_pass=n, at=AT[n - 1]) for n in (1, 2, 3)]
    sha = VR.text_sha(body)
    path = VR.pending_ledger_path(st.root, object_sha)
    rel = path.relative_to(pathlib.Path(st.root)).as_posix()
    got = VS.issue(
        st.root, artifact_sha=sha, streak=3, need=3,
        ledger=f"{rel}#{first[-1]['verification_id']}",
        statement_id="", proof_no=1, artifact_path=REL,
        passes=[{"verification_id": r["verification_id"], "at": r["at"],
                 "proof_sha256": sha, "review_call": r["review_call"],
                 "review_pass": r["review_pass"]} for r in first],
        at=AT[2], by="secretary:B")
    assert got.get("written") is True or got.get("idempotent") is True, got
    for k in range(int(later_rounds or 0)):
        VR.record_pending_sign(
            st.root, proof_text=body, verdict=dict(OK), object_path=REL,
            object_sha256=object_sha, secretary_judge=dict(CLEAN),
            review_call=LATER_CALL, review_pass=k + 1, at=AT[3])
    rows, problems = VR.JF.read_jsonl(path)
    assert problems == [], problems
    return {"path": path, "rows": [dict(r) for r in rows], "credential": got}


def _register_unsigned(st: Store, *, with_body: bool = True) -> str:
    """在册、第 3 位还没翻（lp-ball-10 登记那一拍的形状：号有了、正文有了、签还没收）。

    `with_body=True` 复刻现场：登记那一笔已经把正文落在 `statements.proof_text` 上
    （`register_statement` 的 `proof_manuscript` 支），收录这一笔只认签、不重写正文
    （逐格回执是 `unchanged`）。`with_body=False` 留给负控（正文还没落 ⇒ 收录要写正文，
    签闸因此真的被走到）。
    """
    row = conftest.seed_statement_row(
        st, statement_full=FULL, kind="conjecture",
        proof_text=(PROOF if with_body else ""))
    return str(row["stmt_id"])


def _rows_now(path: pathlib.Path) -> list[dict]:
    rows, problems = VR.JF.read_jsonl(path)
    assert problems == [], problems
    return [dict(r) for r in rows]


def _unclaim(st: Store, path: pathlib.Path) -> None:
    """夹具：把这 4 行退回"还没回写"的现场（只动 tmp 工作区）。"""
    restored = []
    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        row = json.loads(line)
        row["statement_id"] = ""
        row["stmt_id"] = ""
        row.pop("claimed_at", None)
        restored.append(json.dumps(row, ensure_ascii=False) + "\n")
    path.write_text("".join(restored), encoding="utf-8")


def _missing(st: Store, sid: str) -> list[str]:
    plans = [{"plan_id": "000003", "history": [{"round": 1, "statement_id": sid}]}]
    refs = VR.unverified_statement_refs(st.root, plans)
    assert refs.get("checked") is True, refs
    return [r["statement_id"] for r in refs["refs"] if int(r.get("rows") or 0) == 0]


# ------------------------------------------------------------------ a 正控
def test_ingest_writes_the_statement_id_back_to_the_pending_rows(tmp_path):
    """a：收录成功 ⇒ 4 行 pending 全回写、读口认得到、V2FIX 那一路 `missing=[]`。"""
    st, b = _ws(tmp_path)
    sid = _register_unsigned(st)
    stack = _pending_stack(st, body=PROOF, later_rounds=1)
    assert len(stack["rows"]) == 4, stack["rows"]
    assert {str(r.get("statement_id") or "") for r in stack["rows"]} == {""}, stack["rows"]

    got = b.ingest_manuscript(manuscript=REL, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert got.get("ok") is True, got
    # 第 3 位认到的是 pending 那一签（改前就是这样；这一条不是本笔的判据）
    ev = dict(dict(got.get("evidence") or {}).get("sign_claim") or {})
    assert ev.get("applied") is True, ev
    assert str((ev.get("claim") or {}).get("ledger") or "").startswith(
        f"{VR.VERIFICATIONS_DIR}/{VR.PENDING_DIR_NAME}/"), ev

    # ---- ③ 的那一拍真的写了：4 行全回写（不是只写锚点那一行）
    after = _rows_now(stack["path"])
    assert len(after) == 4, after
    for row in after:
        assert str(row.get("statement_id") or "") == sid, row
        assert str(row.get("stmt_id") or "") == sid, row
        assert str(row.get("claimed_at") or ""), row
    # 读数透出来（回执里说同一句话）
    reading = dict(got.get("pending_claim") or {})
    assert reading.get("checked") is True, reading
    assert reading.get("bound") is True, reading
    assert reading.get("statement_id") == sid, reading
    assert len(reading.get("bound_files") or []) == 1, reading
    assert str(dict(ev.get("claim") or {}).get("bound_id") or "") == sid

    # ---- 读口（未放宽）：`_claimed_pending_rows` 认得到这 4 行
    claimed, problems = VR._claimed_pending_rows(st.root, statement_id=sid)
    assert problems == [], problems
    assert len(claimed) == 4, claimed
    # ---- V2FIX 那一路：计划 history 点名这一条 ⇒ missing=[]
    plans = [{"plan_id": "000003", "history": [{"round": 1, "statement_id": sid}]}]
    refs = VR.unverified_statement_refs(st.root, plans)
    (ref,) = refs["refs"]
    assert ref.get("statement_id") == sid, ref
    assert ref.get("rows") == 4, ref
    assert ref.get("pending_rows") == 4, ref
    assert ref.get("pending_signable") is True, ref
    assert _missing(st, sid) == []
    # 认领不搬文件：在册台账仍然没有那一份（签的锚点不许断）
    assert not (pathlib.Path(st.root) / "verifications" / f"{sid}.jsonl").exists()


def test_a_second_ingest_does_not_claim_twice(tmp_path):
    """a 的幂等面：同一笔再收录一次 ⇒ 不二次认领、行仍绑在同一个号上。"""
    st, b = _ws(tmp_path)
    sid = _register_unsigned(st)
    stack = _pending_stack(st, body=PROOF, later_rounds=1)
    first = b.ingest_manuscript(manuscript=REL, target_stmt_id=sid,
                                cells=["proof_text"], mode="apply")
    assert first.get("ok") is True, first
    second = b.ingest_manuscript(manuscript=REL, target_stmt_id=sid,
                                 cells=["proof_text"], mode="apply")
    assert second.get("ok") is True, second
    reading = dict(second.get("pending_claim") or {})
    assert reading.get("checked") is True, reading
    assert reading.get("bound") is True, reading
    assert reading.get("already") is True, reading
    after = _rows_now(stack["path"])
    assert {str(r.get("statement_id") or "") for r in after} == {sid}, after


# ------------------------------------------------------------------ b 负控
def test_a_refused_ingest_does_not_claim_the_pending_rows(tmp_path):
    """b1：收录被拒（签盖的是另一版正文）⇒ 一个字节都不回写。"""
    st, b = _ws(tmp_path)
    sid = _register_unsigned(st, with_body=False)
    stack = _pending_stack(st, body=PROOF, later_rounds=1)
    # 把稿换成"改了一个字"的那一版：pending 那一签盖的是旧正文 ⇒ 整笔受控拒
    _write(st, REL, _manuscript(PROOF_CHANGED))
    got = b.ingest_manuscript(manuscript=REL, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert got.get("ok") is False, got
    assert got.get("refused") == "proof_without_v_sign", got
    reading = dict(got.get("pending_claim") or {})
    assert reading.get("bound") is False, reading
    assert reading.get("checked") is False, reading
    after = _rows_now(stack["path"])
    assert {str(r.get("statement_id") or "") for r in after} == {""}, after
    assert {str(r.get("claimed_at") or "") for r in after} == {""}, after
    assert VR._claimed_pending_rows(st.root, statement_id=sid)[0] == []


def test_no_statement_id_never_writes_an_empty_claim(tmp_path):
    """b2：认领存在、可这一笔没落成 / 没有号 ⇒ 不写（不许写空号冒充认领）。"""
    st, b = _ws(tmp_path)
    sid = _register_unsigned(st)
    stack = _pending_stack(st, body=PROOF, later_rounds=1)
    # 先走一遍真收录，拿到那一份 claim（含 ledger 锚点）
    got = b.ingest_manuscript(manuscript=REL, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert got.get("ok") is True, got
    claim = dict(dict(dict(got.get("evidence") or {}).get("sign_claim")
                      or {}).get("claim") or {})
    assert claim.get("ledger"), claim
    # 夹具：把这 4 行退回"还没回写"的现场（只动 tmp 工作区）
    _unclaim(st, stack["path"])
    assert VR._claimed_pending_rows(st.root, statement_id=sid)[0] == []

    # (i) 这一笔没落成
    failed = {"ok": False, "target": {"stmt_id": sid},
              "evidence": {"sign_claim": {"claim": dict(claim)}}}
    out = b._bind_ingested_claim(failed)
    assert out["pending_claim"]["bound"] is False, out["pending_claim"]
    assert out["pending_claim"]["checked"] is False, out["pending_claim"]
    assert {str(r.get("statement_id") or "") for r in _rows_now(stack["path"])} == {""}

    # (ii) 落成了、可没有命题号 ⇒ 不猜（不写空号）
    anon = {"ok": True, "target": {"stmt_id": ""},
            "evidence": {"sign_claim": {"claim": dict(claim)}}}
    out = b._bind_ingested_claim(anon)
    assert out["pending_claim"]["bound"] is False, out["pending_claim"]
    assert "不猜" in str(out["pending_claim"]["why"]), out["pending_claim"]
    assert {str(r.get("statement_id") or "") for r in _rows_now(stack["path"])} == {""}
    assert {str(r.get("claimed_at") or "") for r in _rows_now(stack["path"])} == {""}


# ------------------------------------------------------------------ c 反真空
def test_stubbing_the_write_back_turns_a_red(tmp_path, monkeypatch):
    """c：把 ③ 那一拍（`vsigns.bind_pending_claim`）打桩成不写 ⇒ a 必红。

    量的是"那 4 个号真的由这一拍写上去"，不是别处凑巧又写了一份。
    """
    st, b = _ws(tmp_path)
    sid = _register_unsigned(st)
    stack = _pending_stack(st, body=PROOF, later_rounds=1)

    def _stub(*_a, **_k):
        return {"checked": True, "bound": True, "already": False,
                "statement_id": "", "ledger": "", "bound_files": [],
                "why": "夹具：打桩 —— 一个字节都不写"}

    monkeypatch.setattr(VS, "bind_pending_claim", _stub)
    got = b.ingest_manuscript(manuscript=REL, target_stmt_id=sid,
                              cells=["proof_text"], mode="apply")
    assert got.get("ok") is True, got
    assert {str(r.get("statement_id") or "") for r in _rows_now(stack["path"])} == {""}
    assert VR._claimed_pending_rows(st.root, statement_id=sid)[0] == []
    assert _missing(st, sid) == [sid]
