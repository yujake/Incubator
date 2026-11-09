# -*- coding: utf-8 -*-
"""缺陷 A：签块里的 `台账=` / `时间=` 停在旧那一签（2026-11-05，真机 87）。

## 现场（`projects/paper-rewrite-87/reports/f-proof-000000.md:5` 逐字）

```text
- V 签：已签=true；判词=成立；连续=3/3；正文sha=43a2b34…685e；时间=2026-11-05T02:50:58+08:00；
  签名者=secretary:F；台账=verifications/000000.jsonl#v-000008；命题号=000000；手稿号=000000
```

同一 sha 之后还有：`v-000009`（02:53:31，判词=有毛病，defect_step=6）→ `v-000010`（成立）
→ `v-000011`（成立）。签块说"最新一签是 v-000008"，账上说最新是 v-000011 ——
签本身有效，不一致的是记录。

## 病根（两处，都在 `vsigns`）

1. `land()` 把签文件里的 `at` / `ledger` 原样抄进块，而 `issue()` 是"一稿一签"：
   同一份正文重签时它 `idempotent`、签文件一个字都不重写 ⇒ 那两格永远是第一次发签那一行；
2. 重判（同 sha 的新台账行）没有任何写者去碰块（`record_verification` 只追加台账）。

## 修法（业主 2026-11-05 择 a）

块是给人读的「这一份现在凭什么算签过」，指旧签会让人以为没重判过。所以每次重判都刷
`台账=` / `时间=` 两格；判成「有毛病」则整块降为未签；`land()` 的那两格改成从台账现锚。

## 六条判据（先红后绿）

| # | 造什么 | 期望 |
|---|---|---|
| a | 签过 → 同 sha 再判一次成立（新 v 号） | 块里 `台账=` 指到新那一签、`时间=` 跟着变成它的 `at`；其余格不动 |
| b | 签过 → 同 sha 再判「有毛病」 | 块变成未签（`已签=false`、`判词=有毛病`、`连续=0/need`），两格指到那一行 |
| c | 反真空：把"重判后刷新块"那一步摘掉 | a 红（块仍停在旧那一签） |
| d | 降为未签之后再来「成立」 | 不翻回来（单行成立不足以重签），读数是 `unsigned_until_resigned` |
| e | 重判的 sha 与块盖的不是同一份 | 不拿这一行去刷别人的块（`not_this_sha`） |
| f | 同一份正文重签（`issue` 幂等） | `land` 从台账现锚：块两格= 完成新一轮连续的那一行，不是签文件里的旧值 |

反真空的做法（c）与仓库既有判据同形：把唯一的写口 `vsigns.refresh_manuscript_sign`
换成一个什么都不做的替身，再看 a 那两条断言是不是立刻红 —— 绿的那一半不靠"恰好没跑"。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.store import Store

SID = "000000"
REL = f"reports/f-proof-{SID}.md"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
#: 87 那一签的 `时间`（刻意不等于任何一次 `record_verification` 的 `at`）。
OLD_AT = "2026-11-05T02:50:58+08:00"


@pytest.fixture
def clock(monkeypatch):
    """让每一行台账的 `at` 都不一样（真机那种"同一秒两行"会让断言变成恒真）。

    只打桩 `verifications._now_iso`（`record_verification` 写 `at` 的唯一来源）：
    每一行比上一行晚一分钟，于是"时间格跟没跟着变"是一个可复现的读数。
    """
    state = {"n": 0}

    def _now() -> str:
        state["n"] += 1
        return f"2026-11-05T02:{40 + state['n']:02d}:00+08:00"

    monkeypatch.setattr(VR, "_now_iso", _now)
    return state


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    path = pathlib.Path(st.root) / REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# F 的证明手稿\n\n"
                    f"- 命题号：stmt:{SID}\n"
                    f"- 计划：{SID} · 子目标：S3\n\n"
                    f"## 命题\n\n{FULL}\n\n## 证明\n\n{PROOF}\n\n"
                    + _DS.render_dependency_section([]), encoding="utf-8")
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", {
            "stmt_id": SID, "origin": "own_result", "kind": "theorem",
            "label": "一致连续", "statement_full": FULL, "statement_text": FULL,
            "proof_text": PROOF, "evidence_kind": "heuristic", "status": "active",
            "quote_verified": None, "quote_reason": "夹具：自产命题",
            "created_at": OLD_AT, "created_by": "test", "bits": {}})
    return st


def _verify(st: Store, *, verdict: str = "成立", step=None, judge: str = "clean") -> dict:
    """落一行台账（走真写口；`flip=False` = V 那一侧只落台账）。"""
    findings = ([{"detail": "夹具：第 6 步的直接计算不成立", "level": "error", "step": step}]
                if verdict == "有毛病" else [])
    return VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF,
        verdict={"verdict": verdict, "defect_step": step, "findings": findings},
        secretary_judge={"axis": judge, "checked": True, "reason": "夹具：秘书判定"},
        manuscript=REL, flip=False)


def _sign(st: Store, *, streak: int = 3, need: int = 3, at: str = OLD_AT,
          ledger: str = "") -> dict:
    """走真写口发签 + 落签（收方秘书 = F 的秘书）。"""
    rows, _bad = VR.list_verifications(st.root, statement_id=SID, limit=None)
    sha = str(rows[-1].get("proof_sha256") or "")
    # 2026-11-05：签的三道必填闸要求 `passes` 逐转带读数（verification_id / at /
    # proof_sha256），最后一转就是 `ledger` 指的那一行。夹具从真台账取这三条，
    # 不手编 id —— 手编的 id 正是"三格全空的占位"那一档要堵的形态。
    passes = [{"verification_id": str(r.get("verification_id") or ""),
               "at": str(r.get("at") or ""),
               "proof_sha256": str(r.get("proof_sha256") or ""),
               "why": str(r.get("why") or "")}
              for r in rows[-int(need):]]
    issued = VS.issue(
        st.root, artifact_sha=sha, streak=streak, need=need, artifact_path=REL,
        ledger=(ledger or f"verifications/{SID}.jsonl#{rows[-1]['verification_id']}"),
        statement_id=SID, proof_no=1, passes=passes, at=at, by="secretary:F")
    landed = VS.land(st.root, artifact_sha=sha, by="secretary:F",
                     manuscript_path=REL, store=None, statement_id=SID, proof_no=1)
    return {"issued": issued, "landed": landed, "sha": sha}


def _block(st: Store) -> dict:
    text = (pathlib.Path(st.root) / REL).read_text(encoding="utf-8")
    return VS.manuscript_sign_reading(text, manuscript_path=REL)


def _ledger_rows(st: Store) -> list[dict]:
    rows, problems = VR.list_verifications(st.root, statement_id=SID, limit=None)
    assert not problems, problems
    return [dict(r) for r in rows]


# ====================================================================== a 成立
def test_a_a_clean_rejudgement_moves_the_block_to_the_newest_row(tmp_path, clock):
    """签过 → 同 sha 再判一次成立 ⇒ 块里 `台账=` 指到新那一签、`时间=` 跟着变。"""
    st = _ws(tmp_path)
    for _ in range(3):
        _verify(st)
    _sign(st)
    signed_row = _ledger_rows(st)[-1]
    first = _block(st)
    assert first["found"] and first["signed"] is True, first
    assert first["ledger"] == f"verifications/{SID}.jsonl#v-000003", first
    # 落签那一刻，块上那两格已经指着台账上那一行（`land` 现锚，不是抄签文件）。
    assert first["at"] == str(signed_row["at"]), first
    # 而签文件里那一格仍是发签那一刻的 at（一稿一签：它不重写）—— 这正是"抄签文件"
    # 会把块抄成旧那一签的原因（见 f）。
    sign_doc = VS.sign_of(st.root, first["proof_sha256"])["sign"]
    assert sign_doc["at"] == OLD_AT, sign_doc.get("at")

    row = _verify(st)
    vid = str(row["verification_id"])
    assert vid == "v-000004", row
    after = _block(st)
    assert after["ledger"] == f"verifications/{SID}.jsonl#{vid}", (
        f"签块还停在 {after['ledger']!r}：账上最新是 {vid}（缺陷 A 的现场）")
    assert after["at"] == str(row["at"]), (
        f"`时间=` 没跟着变成新那一行的 at：块上 {after['at']!r}，账上 {row['at']!r}")
    assert after["at"] != first["at"], "时间格没变 ⇒ 这一条断言会变成恒真"
    # 刷的只有那两格：签本身（sha / 连续 / 签名者 / 命题号）一个字不动。
    assert after["proof_sha256"] == first["proof_sha256"], after
    assert (after["streak"], after["need"]) == (3, 3), after
    assert after["signer"] == "secretary:F", after
    assert after["statement_id"] == SID, after
    assert after["identity_state"] == "resolved", after
    # 读数：刷块那一笔自己也要说清它落在哪一档。
    assert str(row.get("sign_block_refresh", {}).get("state")) == "refreshed", row


# ====================================================================== b 有毛病
def test_b_a_fault_on_the_same_sha_demotes_the_block(tmp_path, clock):
    """签过 → 同 sha 再判「有毛病」⇒ 块变成未签，不许还挂着旧签。"""
    st = _ws(tmp_path)
    for _ in range(3):
        _verify(st)
    _sign(st)
    assert _block(st)["signed"] is True

    row = _verify(st, verdict="有毛病", step=6, judge="fault")
    after = _block(st)
    assert after["signed"] is False, f"负判之后块还写着签：{after}"
    assert after["verdict"] == "有毛病", after
    assert (after["streak"], after["need"]) == (0, 3), after
    assert after["ledger"] == f"verifications/{SID}.jsonl#{row['verification_id']}", after
    assert after["at"] == str(row["at"]), after
    standing = VS.manuscript_sign_standing(
        (pathlib.Path(st.root) / REL).read_text(encoding="utf-8"),
        proof_sha=after["proof_sha256"], manuscript_path=REL)
    assert standing["state"] == "rejected", standing


# ====================================================================== c 反真空
def test_c_without_the_refresh_step_the_clean_case_goes_red(tmp_path, monkeypatch):
    """反真空：把"重判后刷新块"那一步摘掉 ⇒ a 红（块仍停在旧那一签）。"""

    def _no_refresh(*_a, **_kw):
        return {"checked": True, "state": "skipped", "why": "反真空：刷新那一步被摘掉了"}

    monkeypatch.setattr(VS, "refresh_manuscript_sign", _no_refresh)
    st = _ws(tmp_path)
    for _ in range(3):
        _verify(st)
    _sign(st)
    first = _block(st)
    row = _verify(st)
    after = _block(st)
    assert after["ledger"] == first["ledger"], (
        "摘掉刷新那一步之后块还动了 ⇒ 这份判据测的不是那个写口")
    assert after["ledger"] != f"verifications/{SID}.jsonl#{row['verification_id']}", (
        "摘掉刷新之后 a 那一条断言仍然绿 ⇒ a 是空的")
    # 台账那一行照样落了（刷块失败不许带走这一签）。
    assert str(row.get("sign_block_refresh", {}).get("state")) == "skipped", row


# ====================================================================== d 不翻回来
def test_d_a_later_clean_row_does_not_re_sign_a_demoted_block(tmp_path, clock):
    """降为未签之后再来「成立」⇒ 不翻回来（单行成立不足以重签），读数说清为什么。"""
    st = _ws(tmp_path)
    for _ in range(3):
        _verify(st)
    _sign(st)
    fault = _verify(st, verdict="有毛病", step=6, judge="fault")
    demoted = _block(st)
    assert demoted["signed"] is False

    row = _verify(st)
    after = _block(st)
    assert after["signed"] is False, (
        "单行「成立」把块翻回了签 ⇒ 那等于绕过「同一趟连续 need 次」的发签门槛")
    assert after["ledger"] == demoted["ledger"], after
    assert after["ledger"] == f"verifications/{SID}.jsonl#{fault['verification_id']}", after
    assert str(row.get("sign_block_refresh", {}).get("state")) == "unsigned_until_resigned", row


# ====================================================================== e 别人的块
def test_e_a_row_of_another_sha_never_touches_this_block(tmp_path, clock):
    """重判的 sha 与块盖的不是同一份 ⇒ 不拿这一行去刷别人的块。"""
    st = _ws(tmp_path)
    for _ in range(3):
        _verify(st)
    _sign(st)
    before = _block(st)
    other = PROOF.replace("δ=ε", "δ=2ε")
    row = VR.record_verification(
        st.root, statement_id=SID, proof_text=other,
        verdict={"verdict": "成立", "why": "夹具：另一份正文也判成立"},
        secretary_judge={"axis": "clean", "checked": True, "reason": "夹具"},
        manuscript=REL, flip=False)
    after = _block(st)
    assert after["proof_sha256"] == before["proof_sha256"], after
    assert after["ledger"] == before["ledger"], after
    assert str(row.get("sign_block_refresh", {}).get("state")) == "not_this_sha", row


# ====================================================================== f 重签现锚
def test_f_a_resign_of_the_same_text_anchors_to_the_newest_clean_row(tmp_path, clock):
    """同一份正文重签（`issue` 幂等不动签文件）⇒ `land` 从台账现锚，不抄旧那一行。"""
    st = _ws(tmp_path)
    for _ in range(3):
        _verify(st)
    _sign(st)
    old_ledger = _block(st)["ledger"]
    assert old_ledger.endswith("#v-000003"), old_ledger
    _verify(st, verdict="有毛病", step=6, judge="fault")
    assert _block(st)["signed"] is False

    newest = _verify(st)
    again = _sign(st, at=OLD_AT)
    assert again["issued"]["idempotent"] is True, (
        "一稿一签：同一份正文重签必须是 idempotent（这一条判据假设它不重写签文件）")
    assert again["landed"]["landed"] is True, again["landed"]
    after = _block(st)
    assert after["signed"] is True, after
    assert after["ledger"] == f"verifications/{SID}.jsonl#{newest['verification_id']}", (
        f"重签把块锚回了旧那一签（{after['ledger']!r}）—— 这正是缺陷 A 的第二条病根")
    assert after["at"] == str(newest["at"]), after
    assert after["at"] != OLD_AT, after
    assert again["landed"]["anchor_source"] == "ledger", again["landed"]


# ====================================================================== 三态
def test_the_ledger_anchor_separates_unreadable_from_empty(tmp_path):
    """`ledger_anchor` 的三态：没号/没行是"查过了、没有"，读不出来是"没查成"。"""
    st = _ws(tmp_path)
    sha = VR.text_sha(PROOF)
    no_statement = VS.ledger_anchor(st.root, statement_id="", artifact_sha=sha)
    assert no_statement["checked"] is True and no_statement["found"] is False, no_statement
    empty = VS.ledger_anchor(st.root, statement_id=SID, artifact_sha=sha)
    assert empty["checked"] is True and empty["found"] is False, empty
    bad_sha = VS.ledger_anchor(st.root, statement_id=SID, artifact_sha="zz")
    assert bad_sha["checked"] is False, bad_sha
    bad_ledger = VS.ledger_anchor(st.root, statement_id="not-an-id", artifact_sha=sha)
    assert bad_ledger["checked"] is False, bad_ledger
    # 写一行之后：锚就是它，`clean` 按 conclusion + 秘书轴两档判。
    row = _verify(st)
    got = VS.ledger_anchor(st.root, statement_id=SID, artifact_sha=sha)
    assert got["found"] is True and got["clean"] is True, got
    assert got["ledger"] == f"verifications/{SID}.jsonl#{row['verification_id']}", got
    stored = pathlib.Path(st.root) / f"verifications/{SID}.jsonl"
    assert stored.is_file(), "夹具没落出台账 —— 上面那条断言会变成恒真"
