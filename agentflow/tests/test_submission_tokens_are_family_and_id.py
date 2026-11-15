# -*- coding: utf-8 -*-
"""EC3：`mss:` 提交记号带族 —— 稿的身份是 (族, 稿号)，不是单号。

## 根因（EC2 在携带单那一侧发现、这是第三个落点）

四族各有自己的号段、都从 `000000` 起（`manuscriptids` 的四条计数器）⇒ 同一号跨族
是常态。`mss:` 提交记号原来写单号头（`mss:<稿号>`），`submissions_of` 又按单号建
字典（`out.setdefault(mid, rec)`）⇒ `e-proof-000000` 与 `e-num-000000` 各一枚记号时
只留一个键：

- `submission_reading(manuscript="reports/e-proof-000000.md")` 报 `state=submitted`
  却带着 另一族那一枚 记号的 `token` / `via`（读数串了）；
- E 收工会把另一族那份读成 `already_submitted` ⇒ 不再写自己的记号。

## 这一份钉什么

| # | 造什么 | 期望 |
|---|---|---|
| a | 同号两族各一枚带族记号（`e-proof-000000` / `e-num-000000`） | `submissions_of` 两个键；`submission_reading` 各读各的（token/via 不串） |
| a2 | e-num 已有自己的记号，e-proof 已签 | E 收工仍给 e-proof 写自己的记号（另一族不压住本族）；第二趟幂等 |
| a2b | e-proof 已提交、e-num 未签 | e-num 读 `unsigned`（不是 `already_submitted`） |
| a3 | `_select` 喂一个已签的 e-num 候选、e-proof 已提交 | 仍给 e-num 写自己的记号（幂等键是 (族, 号)） |
| b | 单族单号的老形态（`mss:<号>`） | `submissions_of` 的键与读数与改前逐字相同（对照表见 `_assert_b`） |
| c | 只有老记号 `mss:<号>` | 仍读得到：族由载体路径 / 盘上唯一稿唯一确定 |
| d | 老记号 + 没写族 + 该号两族都在盘上 | 不许猜：读数 `checked=False` + 点名「跨族同号」；E 收工不拿它当「已提交」 |
| e | 反真空：把 `submission_key` 退回单号 | a 必红（e-proof 的读数带出 e-num 那一枚的 token/via —— 改前那一幕重现） |

## 实测口径（与缺陷报告的一处出入，以盘上为准）

`e-num` 走绿色通道、不收签（`manuscriptfamily.sign_carrier` 回
`numeric_manuscript_is_not_a_sign_carrier`）⇒ `signed_candidates` 对 e-num 永远读成
`unsigned`，E 收工在盘上写不出 e-num 的记号（这不是本批引入的：签的载体表如此）。
所以 ⑤ 的"两向"分开钉：a2/a2b 用真签钉端到端（另一族已有的记号不压住本族、本族
的记号也不把另一族读成已提交），a3 直接在 `_select` 那一层喂一个已签的 e-num 候选，
钉 (族, 号) 这个幂等键本身。

零模型调用：签用 `verifications.record_pending_sign` + `vsigns.issue` 直接造（与
`test_e_auto_submits_signed_manuscripts.py` 同一套夹具形状）。全部 tmp 工作区，
不读写 `projects/`（真机工作区只读），不跑全量。
"""
from __future__ import annotations

import pathlib

import pytest
from agentflow import manuscriptclosing as MC
from agentflow import manuscriptfamily as MFAM
from agentflow import manuscriptsubmission as MS
from agentflow import proofregistry as PR
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_f import submission as SUB
from agentflow.store import Store

TS = "2026-11-16T00:00:00+08:00"
FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
BODY = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
        "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")


# ============================================================ 夹具
def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _task(st: Store, *, task_id: str = "t-000001", role: str = "E") -> dict:
    row = S.Task(task_id=task_id, role=role,
                 action="prove" if role == "F" else "run_experiment",
                 called_by="D", depth=1, status="running", started_at=S.now_iso(),
                 input_key="ec3-mss-family-fixture")
    row.validate()
    with st.tx("tasks", actor="fixture") as tx:
        tx.upsert("tasks", row.to_dict())
    return row.to_dict()


def _body(family: str, mid: str) -> str:
    """每一份稿的正文都不一样（签按正文 sha 认；两族同号不能共用一份签）。"""
    return BODY + f"\n3. 稿 {family}-{mid} 的收尾标记。"


def _text(family: str, mid: str) -> str:
    return ("# 手稿\n\n- 实验号：exp:000001\n\n"
            f"## 命题\n\n{FULL}\n\n## 证明\n\n{_body(family, mid)}\n\n"
            + "## 依赖\n\n| 引用 | 命题号 | 用在哪一步 |\n|---|---|---|\n")


def _write(st: Store, rel: str, family: str, mid: str) -> str:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    text = _text(family, mid)
    path.write_text(text, encoding="utf-8")
    return text


def _signed(st: Store, family: str, mid: str) -> str:
    """盘上写一份 `reports/<族>-<号>.md` 并真颁一份签；返回相对路径。"""
    rel = f"reports/{family}-{mid}.md"
    text = _write(st, rel, family, mid)
    body = _body(family, mid)
    rows = [VR.record_pending_sign(
        st.root, proof_text=body, verdict={"verdict": "成立", "findings": []},
        verifier="agent-V", object_path=rel,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                         "reason": "夹具：clean"}) for _ in range(3)]
    key = str(rows[0].get("object_sha256") or rows[0].get("proof_sha256") or "")
    passes = [{"verification_id": r["verification_id"], "at": r["at"],
               "proof_sha256": r["proof_sha256"]} for r in rows]
    wrote = VS.issue(st.root, artifact_sha=PR.proof_sha(text), streak=3, need=3,
                     artifact_path=rel,
                     ledger=f"verifications/pending/{key}.jsonl"
                            f"#{rows[-1]['verification_id']}",
                     statement_id="", passes=passes, by="secretary:E")
    assert wrote.get("written") is True, wrote
    return rel


def _artifacts(st: Store, task_id: str = "t-000001") -> list[str]:
    row = next(dict(r) for r in st.rows("tasks")
               if str(r.get("task_id")) == task_id)
    return [str(x) for x in (row.get("artifacts") or [])]


def _put_artifacts(st: Store, tokens: list[str], *, task_id: str = "t-000001") -> None:
    with st.tx("tasks", actor="fixture") as tx:
        row = dict(tx.find("tasks", task_id=task_id))
        row["artifacts"] = S.sorted_unique(list(row.get("artifacts") or ()) + tokens)
        tx.upsert("tasks", row)


def _token(*, family: str, mid: str = "000000", via: str,
           body_sha: str = "a" * 64) -> str:
    return SUB.submission_token(
        manuscript_id=mid, family=family, path=f"reports/{family}-{mid}.md",
        body_sha=body_sha, sign_sha="b" * 64, file_sha="c" * 64,
        statement_id="", at=TS, submitted_at=TS, via=via)


# ============================================================ a：同号两族 ⇒ 两个键、各读各的
def _assert_a(st: Store, tokens: list[str]) -> None:
    """a 的断言（e 的反真空也走它）。"""
    got, problems = SUB.submissions_of(tokens)
    assert problems == [], problems
    assert set(got) == {"e-proof:000000", "e-num:000000"}, sorted(got)
    assert got["e-proof:000000"]["family"] == "e-proof", got
    assert got["e-num:000000"]["family"] == "e-num", got
    proof = MS.submission_reading(st, st.root, manuscript="reports/e-proof-000000.md")
    num = MS.submission_reading(st, st.root, manuscript="reports/e-num-000000.md")
    assert proof["state"] == "submitted", proof
    assert proof["via"] == SUB.VIA_CLOSING, proof
    assert MS.parse_submission(proof["token"])["family"] == "e-proof", proof
    assert proof["token"] == got["e-proof:000000"]["token"], proof
    assert num["state"] == "submitted", num
    assert num["via"] == MS.VIA_INGEST, num
    assert MS.parse_submission(num["token"])["family"] == "e-num", num
    assert num["token"] == got["e-num:000000"]["token"], num
    assert proof["token"] != num["token"], (proof["token"], num["token"])


def test_a_two_families_with_the_same_number_are_two_keys(tmp_path):
    st = _ws(tmp_path)
    _task(st, role="E")
    tokens = [
        _token(family="e-proof", via=SUB.VIA_CLOSING),
        _token(family="e-num", via=MS.VIA_INGEST),
    ]
    _put_artifacts(st, tokens)
    _assert_a(st, tokens)


# ============================================================ a2：E 收工按 (族, 号) 幂等
#
# 实测口径（`manuscriptfamily.sign_carrier`）：`e-num` 走绿色通道，不收签
# （`numeric_manuscript_is_not_a_sign_carrier`）⇒ `signed_candidates` 对 e-num 永远
# 读成 `unsigned`，E 收工在盘上写不出 e-num 的记号。所以 ⑤ 的两半分开钉：
#   a2（端到端、真签）：另一族已有的记号不压住本族 —— e-num 的记号在 artifacts 里，
#       不意味着已签的 e-proof 已提交 ⇒ E 收工仍写 e-proof 自己的记号；反过来，e-proof
#       的记号也不把 e-num 读成 `already_submitted`（它是 `unsigned`）。
#   a3（选人那一层）：直接喂给 `_select` 一个"已签的 e-num 候选"，证明 (族, 号) 的
#       幂等键本身是对的 —— e-proof 已提交不意味着 e-num 已提交（那一层与签的闸无关）。
def test_a2_another_familys_token_does_not_suppress_the_signed_family(tmp_path):
    st = _ws(tmp_path)
    _task(st, role="E")
    proof_rel = _signed(st, "e-proof", "000000")
    num_rel = f"reports/e-num-000000.md"
    _write(st, num_rel, "e-num", "000000")
    # 盘上先有 e-num 那一枚（带族）记号：改前 `mid in submitted` 会把它读成 e-proof 也
    # 已提交（EC2 探针那一幕：另一族的记号把本族压住）。
    _put_artifacts(st, [_token(family="e-num", via=MS.VIA_INGEST)])
    assert MFAM.sign_carrier(num_rel)["ok"] is False, "夹具前提：e-num 不是签的载体"
    out = MC.auto_submit_for(store=st, root=st.root, role="E",
                             families=("e-proof", "e-num"),
                             task_id="t-000001", stamp=TS)
    assert out.get("checked") is True, out
    assert [str(x.get("family")) for x in out.get("auto_submitted") or []] == ["e-proof"], out
    assert [str(x.get("manuscript")) for x in out.get("auto_submitted") or []] == [proof_rel], out
    assert str(out["auto_submitted"][0]["token"]).startswith("mss:e-proof-000000"), out
    still = {str(x.get("manuscript")): dict(x) for x in out.get("still_unsubmitted") or []}
    # e-num 那一枚读成已提交是对的（它自己那枚带族记号）；关键在 e-proof 没被它压住。
    assert str(still[num_rel].get("state")) == "already_submitted", still
    assert "e-num 稿号 000000" in str(still[num_rel].get("why") or ""), still
    # 两族各一枚带族记号 ⇒ 两个键。
    artifacts = _artifacts(st)
    got, problems = MS.submissions_of(artifacts)
    assert problems == [], problems
    assert set(got) == {"e-proof:000000", "e-num:000000"}, sorted(got)
    # 第二趟收工：本族幂等，一个字节都不再写。
    before = list(artifacts)
    again = MC.auto_submit_for(store=st, root=st.root, role="E",
                               families=("e-proof", "e-num"),
                               task_id="t-000001", stamp=TS)
    assert again.get("auto_submitted") == [], again
    assert _artifacts(st) == before, "第二趟收工又写了一遍 artifacts"


def test_a2b_e_proofs_token_does_not_make_e_num_already_submitted(tmp_path):
    """反方向端到端：e-proof 已提交不把 e-num 读成 `already_submitted`。

    e-num 未签（绿色通道不收签）⇒ 它自己的结局是 `unsigned`；改前 `mid in submitted`
    会把它读成 `already_submitted`（两族折在同一个裸号键上）。
    """
    st = _ws(tmp_path)
    _task(st, role="E")
    proof_rel = _signed(st, "e-proof", "000000")
    num_rel = "reports/e-num-000000.md"
    _write(st, num_rel, "e-num", "000000")
    first = MC.auto_submit_for(store=st, root=st.root, role="E",
                               families=("e-proof", "e-num"),
                               task_id="t-000001", stamp=TS)
    assert [str(x.get("manuscript")) for x in first.get("auto_submitted") or []] == [
        proof_rel], first
    second = MC.auto_submit_for(store=st, root=st.root, role="E",
                                families=("e-proof", "e-num"),
                                task_id="t-000001", stamp=TS)
    assert second.get("auto_submitted") == [], second
    still = {str(x.get("manuscript")): dict(x) for x in second.get("still_unsubmitted") or []}
    assert str(still[proof_rel].get("state")) == "already_submitted", still
    assert str(still[num_rel].get("state")) == "unsigned", still
    assert "e-proof 稿号 000000" in str(still[proof_rel].get("why") or ""), still


def test_a3_e_proof_submitted_does_not_mean_e_num_is_submitted():
    """选人那一层：`e-proof-000000` 已提交，已签的 `e-num-000000` 仍要写自己的记号。"""
    proof = _token(family="e-proof", via=SUB.VIA_CLOSING)
    submitted, problems = MS.submissions_of([proof])
    assert problems == [], problems
    roww = {"task_id": "t-000001", "role": "E"}
    out = {"checked": True, "auto_submitted": [], "auto_submitted_count": 0,
           "still_unsubmitted": [], "problems": [], "why": ""}
    pending = MC._select(
        [{"family": "e-num", "manuscript_id": "000000",
          "manuscript": "reports/e-num-000000.md", "signed": True,
          "signed_sha": "a" * 64, "current_sha": "a" * 64, "state": "signed",
          "why": "夹具：已签", "file_sha": "b" * 64, "sign_sha": "c" * 64,
          "statement_id": "", "proof_no": 1, "at": TS}],
        submitted=submitted, families_by_mid={"000000": ["e-proof", "e-num"]},
        row=roww, row_why="", stamp=TS, out=out)
    assert len(pending) == 1, (pending, out)
    assert pending[0][1].startswith("mss:e-num-000000"), pending
    assert out["still_unsubmitted"] == [], out


# ============================================================ b：单族单号老形态（对照读数）
def _legacy_token(rel: str, *, mid: str = "000000") -> str:
    """改前 `submission_token` 写出来的形状（`mss:<号>`，没有族那一格）。"""
    return (f"mss:{mid}#path={rel}#body_sha={'d' * 64}#sign_sha={'e' * 64}"
            f"#file_sha={'f' * 64}#statement_id=#at={TS}#submitted_at={TS}"
            f"#via={SUB.VIA_CLOSING}")


def _assert_b(st: Store, rel: str, legacy: str) -> None:
    """b 的对照断言（改前逐字相同的那些读数，逐格列在这里）。"""
    parsed = SUB.parse_submission(legacy)
    assert parsed["manuscript_id"] == "000000", parsed
    assert parsed["family"] == "", parsed          # 老记号头里没有族
    assert parsed["carrier_family"] == "f-proof", parsed  # 族从载体路径补
    got, problems = SUB.submissions_of([legacy])
    assert problems == [], problems
    # 键与改前逐字相同：单族时沿用裸稿号（F 的读侧因此不必改）。
    assert list(got) == ["000000"], sorted(got)
    read = MS.submission_reading(st, st.root, manuscript=rel)
    # 改前那 16 格读数，逐格给对照值（键集一个字没加）。
    assert read["checked"] is True, read
    assert read["state"] == "submitted", read
    assert read["via"] == SUB.VIA_CLOSING, read
    assert read["submitted_at"] == TS, read
    assert read["manuscript"] == rel, read
    assert read["manuscript_id"] == "000000", read
    assert read["producer_role"] == "F", read
    assert read["token"] == legacy, read
    assert "f-proof" in read["why"], read   # 族由载体补出来（读数里点名）
    assert "跨族" not in read["why"], read
    by_mid = MS.submission_reading(st, st.root, manuscript_id="000000")
    assert by_mid["state"] == "submitted", by_mid
    assert by_mid["token"] == legacy, by_mid


def test_b_a_single_family_legacy_token_reads_as_before(tmp_path):
    st = _ws(tmp_path)
    _task(st, role="F")
    rel = "reports/f-proof-000000.md"
    _write(st, rel, "f-proof", "000000")
    legacy = _legacy_token(rel)
    _put_artifacts(st, [legacy])
    _assert_b(st, rel, legacy)


# ============================================================ c：只有老记号仍读得到
def test_c_a_legacy_token_is_still_readable_when_the_family_is_unique(tmp_path):
    st = _ws(tmp_path)
    _task(st, role="E")
    rel = "reports/e-proof-000000.md"
    _write(st, rel, "e-proof", "000000")
    # c1：老记号自己带着载体路径 ⇒ 族由路径唯一确定。
    legacy = _legacy_token(rel)
    _put_artifacts(st, [legacy])
    read = MS.submission_reading(st, st.root, manuscript=rel)
    assert read["state"] == "submitted", read
    assert "e-proof" in read["why"], read
    assert read["token"] == legacy, read
    # c2：老记号没写 path，但盘上该号只有一族 ⇒ 族由上下文唯一确定，照读。
    st2 = _ws(tmp_path / "c2")
    _task(st2, role="E")
    rel2 = "reports/e-proof-000000.md"
    _write(st2, rel2, "e-proof", "000000")
    bare = f"mss:000000#body_sha={'d' * 64}#submitted_at={TS}#via={SUB.VIA_CLOSING}"
    _put_artifacts(st2, [bare])
    got, problems = MS.submissions_of([bare])
    assert problems == [], problems
    assert list(got) == ["000000"], sorted(got)
    read2 = MS.submission_reading(st2, st2.root, manuscript=rel2)
    assert read2["state"] == "submitted", read2
    assert read2["token"] == bare, read2
    assert "跨族" not in read2["why"], read2


# ============================================================ d：老记号 + 跨族同号 ⇒ 不猜
def test_d_a_legacy_token_on_a_cross_family_number_is_not_guessed(tmp_path):
    st = _ws(tmp_path)
    _task(st, role="E")
    proof_rel = _signed(st, "e-proof", "000000")
    num_rel = "reports/e-num-000000.md"
    _write(st, num_rel, "e-num", "000000")  # e-num 只落稿（绿色通道不收签）
    # 老记号：没有族、也没有载体路径（族真的定不下来）；而盘上这一号两族都有。
    legacy = (f"mss:000000#body_sha={'d' * 64}#at={TS}"
              f"#submitted_at={TS}#via={SUB.VIA_CLOSING}")
    _put_artifacts(st, [legacy])
    got, problems = MS.submissions_of([legacy])
    assert problems == [], problems
    assert list(got) == ["000000"], sorted(got)
    assert got["000000"]["family"] == "", got
    read = MS.submission_reading(st, st.root, manuscript_id="000000")
    assert read["checked"] is False, read
    assert read["state"] != "submitted", read
    assert "跨族同号" in str(read["why"]), read
    assert "e-num" in str(read["why"]) and "e-proof" in str(read["why"]), read
    assert "跨族同号" in "；".join(read["problems"]), read
    # 每一族按自己的路径读：都不许把这枚老记号当成自己的（不许猜）。
    for rel in (proof_rel, num_rel):
        one = MS.submission_reading(st, st.root, manuscript=rel)
        assert one["checked"] is False, one
        assert one["state"] != "submitted", one
        assert "跨族同号" in str(one["why"]), one
        assert "e-num" in str(one["why"]) and "e-proof" in str(one["why"]), one
    # E 收工不拿它当已提交：已签的 e-proof 照常写自己的明确记号（append-only，不猜
    # 老记号属于谁），并把「跨族同号、无法唯一定位」点名在 problems 里。e-num 未签
    # 走 `unsigned`（绿色通道不收签），不被读成 `already_submitted`。
    out = MC.auto_submit_for(store=st, root=st.root, role="E",
                             families=("e-proof", "e-num"),
                             task_id="t-000001", stamp=TS)
    assert [str(x.get("family")) for x in out.get("auto_submitted") or []] == ["e-proof"], out
    assert any("跨族同号" in str(x) for x in out.get("problems") or []), out
    still = {str(x.get("manuscript")): dict(x) for x in out.get("still_unsubmitted") or []}
    assert str(still[num_rel].get("state")) == "unsigned", still
    # e-proof 现在有自己的明确记号，读得出来；e-num 仍是「族定不下来」（不猜 —— 老
    # 记号可能属于它，也可能属于 e-proof）。
    proof = MS.submission_reading(st, st.root, manuscript=proof_rel)
    num = MS.submission_reading(st, st.root, manuscript=num_rel)
    assert proof["state"] == "submitted" and "e-proof" in proof["why"], proof
    assert num["checked"] is False and num["state"] != "submitted", num


# ============================================================ e：反真空
def test_e_reverting_the_key_to_a_bare_number_turns_a_red(tmp_path, monkeypatch):
    st = _ws(tmp_path)
    _task(st, role="E")
    tokens = [
        _token(family="e-proof", via=SUB.VIA_CLOSING),
        _token(family="e-num", via=MS.VIA_INGEST),
    ]
    _put_artifacts(st, tokens)
    # 反真空：把身份键退回单号 ⇒ a 那一组断言必须红（改前那一幕：两族折成一行、
    # 读数带着另一族那一枚记号的 token/via）。
    monkeypatch.setattr(SUB, "submission_key",
                        lambda family, manuscript_id: str(manuscript_id))
    got, _problems = SUB.submissions_of(_artifacts(st))
    assert list(got) == ["000000"], sorted(got)
    proof = MS.submission_reading(st, st.root, manuscript="reports/e-proof-000000.md")
    # ← 改前那一幕：e-proof 的读数带着 e-num 那一枚记号的 token/via（读数串了）。
    assert proof["token"] == got["000000"]["token"], proof
    assert proof["token"].startswith("mss:e-num-"), proof
    assert proof["via"] == MS.VIA_INGEST, proof
    with pytest.raises(AssertionError):
        _assert_a(st, _artifacts(st))
