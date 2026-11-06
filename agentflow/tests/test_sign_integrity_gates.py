# -*- coding: utf-8 -*-
"""「签的完整性」与「签了不升档」两族缺陷的判据（业主 2026-11-05）。

现场：`temp/rmk90-audit/REPORT-R-mk-infinite-90-20261105.md`（只读巡检）。

## 这一组守什么

| # | 缺陷（真机读数） | 判据 | 反真空（摘掉闸 ⇒ 红） |
|---|---|---|---|
| a | 8 条 3/3 签里 4 条 `statement_id=""` | 没有号不是拒签理由（业主 2026-11-05 晚：`命题号=未在册` 合法）；拒的是"连 pending 台账都没有" | 打桩 `sign_object_gate` 恒放行 ⇒ 签文件出现 |
| b | 4 条 `ledger` 是稿头自引（`reports/<稿>#V签`） | 台账只认 `verifications/<号>.jsonl#v-…` 与 `verifications/pending/<正文sha>.jsonl#u-…` | 同上（同一道闸） |
| c | 那 4 条的 `passes` 是三个空占位 | 每一转都要 `verification_id`/`at`/`proof_sha256` | 同上 |
| d | `f-proof-plan-000011.md` 拿到 3/3 签、`identity_state=resolved` | 计划稿是合法落稿名、但不是签的载体；身份不得 `resolved` | 打桩 `sign_carrier_reading` 恒 ok ⇒ 身份又 `resolved` |
| e | 000014/000016 只跑了第一步，`evidence_kind` 停在 `heuristic` | 签成之后同一笔里重算 `evidence_kind`（不必第二条命令） | 打桩 `_grade_recomputed_from_signature` ⇒ 停在旧档 |
| g | 000013/000017 两步都跑 ⇒ `proof_review` | 在册那一支（正控）仍然升档 | —— |
| 丙 | `b-register@` 是 `expects=work` 的义务 | `ack`/`completed` 关不掉它（收口只认证据或明确放弃） | 打桩前缀表为空 ⇒ 被 ack 关掉 |

零模型调用、全部 tmp 工作区；不读写 `projects/`。
"""
from __future__ import annotations

import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB   # noqa: E402
from agentflow import manuscriptform as MF  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.conductor import Conductor, LocalBackend, calling_as  # noqa: E402
from agentflow.store import Store  # noqa: E402

from conftest import seed_statement_row  # noqa: E402

FULL = "设 G 是 3-正则简单图，且每条边至少落在两个三角形里；则 G ≅ K4。"
PROOF = ("1. 取边 uv，它落在两个三角形 uvw 与 uvx 里。\n"
         "2. 由 3-正则，w 与 x 都只能再连一个点 ⇒ w~x。\n"
         "3. 四点两两相邻 ⇒ K4；K4 每点度数 3，不能再向外连边。\n")
SID = "000013"
OK = {"verdict": "成立", "findings": []}
CLEAN_JUDGE = {"checked": True, "axis": "clean", "decision": "没问题"}


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _seed(st: Store, *, proof_text: str = PROOF) -> str:
    # 等级是唯一的轴：给这一行预置五元位（正文非空 ⇒ 第 2 位为真），
    # V 的三次「成立」翻第 3 位之后等级现算 `pre_theorem`；历史列照等级反算。
    bits = EB.bits_of(origin="own_result", proof=bool(str(proof_text or "").strip()),
                      proof_process=str(proof_text or ""), kind="conjecture")
    seeded = seed_statement_row(
        st, proof_text=proof_text, statement_full=FULL, statement_text="K4 的刻画",
        kind="conjecture", label="k4-characterisation", origin="own_result",
        evidence_kind=EB.kind_from_bits(bits, kind="conjecture"), bits=bits)
    return str(seeded["stmt_id"])


def _manuscript(st: Store, sid: str, *, plan: bool = False) -> str:
    name = f"f-proof-plan-{sid}" if plan else f"f-proof-{sid}"
    rel = f"reports/{name}.md"
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# F 的证明手稿：K4 的刻画\n\n- 命题号：stmt:{sid}\n\n## 命题\n\n{FULL}\n\n"
        f"## 证明\n\n{PROOF}\n\n## 依赖\n\n"
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
        "|---|---|---|---|\n（空表就是声明。）\n",
        encoding="utf-8")
    return rel


def _passes(sha: str, n: int = 3) -> list[dict]:
    return [{"verification_id": f"v-{i:06d}", "at": f"2026-11-05T00:00:0{i}+08:00",
             "proof_sha256": sha, "why": "这一转判「成立」"} for i in range(1, n + 1)]


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements") if str(r.get("stmt_id")) == sid)


def _sign_three(st: Store, sid: str, rel: str) -> dict:
    """连判三转（真台账；第 3 转发签）。返回第 3 转的写回读数。"""
    last: dict = {}
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        last = VR.record_verification(
            str(st.root), statement_id=sid, proof_text=PROOF, verdict=dict(OK),
            verifier="agent-V", store=st, proof_no=1, manuscript=rel, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})
    return last


# ====================================================================== a / b / c

def test_a_a_sign_without_a_statement_id_is_refused(tmp_path: pathlib.Path) -> None:
    """a：连台账都不给（`statement_id=""` + `ledger=""`）⇒ 受控拒绝，签文件一个都不许出现。

    2026-11-05 晚（业主）改口径后这一条拒的不是"没有命题号"（`命题号=未在册` 是
    合法形态），而是"这一签没有任何独立台账背书"：没号要落
    `verifications/pending/<正文sha>.jsonl#u-<号>`，那才是这一档的落点。
    """
    st = _ws(tmp_path)
    sha = VR.proof_sha(PROOF)
    got = VS.issue(st.root, artifact_sha=sha, streak=3, need=3,
                   artifact_path="reports/f-proof-000013.md", ledger="",
                   statement_id="", passes=_passes(sha), by="secretary:F")
    assert got["written"] is False, got
    assert got["code"] == VS.STATEMENT_ID_MISSING, got
    assert "没有可签的对象" in got["reason"], got["reason"]
    assert "没有号不是拒签理由" in got["reason"], got["reason"]
    assert not VS.signs_dir(st.root).exists(), "被拒的颁发建了签目录"


def test_b_a_self_referential_ledger_is_not_a_ledger(tmp_path: pathlib.Path) -> None:
    """b：稿头自述（`reports/<稿>#V签`）不是台账 ⇒ 受控拒绝。"""
    st = _ws(tmp_path)
    sha = VR.proof_sha(PROOF)
    rel = _manuscript(st, SID)
    got = VS.issue(st.root, artifact_sha=sha, streak=3, need=3, artifact_path=rel,
                   ledger=f"{rel}#V签", statement_id=SID, passes=_passes(sha),
                   by="secretary:F")
    assert got["written"] is False, got
    assert got["code"] == VS.LEDGER_NOT_VERIFICATION, got
    assert "不是 V 自己那本台账" in got["reason"], got["reason"]
    assert not [p for p in VS.signs_dir(st.root).glob("*.json")] \
        if VS.signs_dir(st.root).is_dir() else True


def test_c_three_empty_passes_are_not_a_streak(tmp_path: pathlib.Path) -> None:
    """c：`passes=[{},{},{}]` 不许被数成「连续 3/3」⇒ 受控拒绝。"""
    st = _ws(tmp_path)
    sha = VR.proof_sha(PROOF)
    got = VS.issue(st.root, artifact_sha=sha, streak=3, need=3,
                   artifact_path="reports/f-proof-000013.md",
                   ledger=f"verifications/{SID}.jsonl#v-000003", statement_id=SID,
                   passes=[{}, {}, {}], by="secretary:F")
    assert got["written"] is False, got
    assert got["code"] == VS.PASSES_INCOMPLETE, got
    assert "三格全空" in got["reason"], got["reason"]


# ====================================================================== d 计划稿

def test_d_a_plan_manuscript_is_not_a_sign_carrier(tmp_path: pathlib.Path) -> None:
    """d：计划稿是合法落稿名，但不是签的载体（身份不得 `resolved`）。"""
    st = _ws(tmp_path)
    rel = _manuscript(st, SID, plan=True)
    assert VS.is_sign_carrier(rel) is False, rel
    assert VS.sign_carrier_reading(rel)["code"] == VS.MANUSCRIPT_NAME_PLAN

    # 落稿名这一半必须照旧成立（F 的「先落计划名、拿到号再改名」工作流）。
    named = MF.name_reading("F", plan_id=SID)
    assert named["ok"] is True and named["path"] == rel, named
    assert VS.parse_manuscript_name(rel)["family"] is True, VS.parse_manuscript_name(rel)

    # 一块「已签 3/3」盖在计划稿上 ⇒ 身份不许 resolved（真机 883c3097）。
    sha = VR.proof_sha(PROOF)
    mark = VS.render_manuscript_sign(
        proof_sha=sha, streak=3, need=3, at="2026-11-05T00:00:00+08:00",
        ledger=f"verifications/{SID}.jsonl#v-000003", statement_id=SID,
        manuscript_id=f"plan-{SID}", signer="secretary:F")
    text = pathlib.Path(st.root, rel).read_text(encoding="utf-8")
    pathlib.Path(st.root, rel).write_text(text + "\n" + mark + "\n", encoding="utf-8")
    reading = VS.manuscript_sign_reading(
        pathlib.Path(st.root, rel).read_text(encoding="utf-8"),
        manuscript_path=rel)
    assert reading["found"] is True and reading["signed"] is True, reading
    assert reading["identity_state"] == "unmatched", reading
    assert "不是签的载体" in str(reading.get("identity_why") or ""), reading


# ====================================================================== e 签成即升档

def test_e_signing_then_registering_the_body_upgrades_the_grade(tmp_path: pathlib.Path) -> None:
    """e：两阶段现场（先发签、后回填正文）⇒ 正文落进那一行时同一笔升到 `pre_theorem`。"""
    st = _ws(tmp_path)
    sid = _seed(st, proof_text="")
    rel = _manuscript(st, sid)
    third = _sign_three(st, sid, rel)
    wb = dict(third.get("statement_writeback") or {})
    assert wb.get("written") is False, wb   # 正文还没进那一行 ⇒ 第 3 位不翻
    assert EB.bits_from_row(_row(st, sid))["grade"] == "conjecture", _row(st, sid)
    sha = VR.proof_sha(PROOF)
    assert VS.sign_path(st.root, sha).is_file(), "三转成立却没有签文件"

    # B 回填正文（第一步：`register_statement:proofs`）。不再跑第二条升级命令。
    b = AgentB(st, extractor=None, extract_text=None)
    bits = EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                      kind="conjecture")
    wrote = b._attach_proofs(sid, [], canonical=PROOF, bits=bits)
    assert wrote.get("written") is True, wrote
    # 等级是唯一的轴：同一笔把等级算到 `pre_theorem`（历史档位反算是 `proof_review`）。
    assert (wrote.get("grade_recomputed") or {}).get("to") == "pre_theorem", wrote
    row = _row(st, sid)
    assert EB.bits_from_row(row)["grade"] == "pre_theorem", row.get("bits")
    assert EB.kind_from_bits(row.get("bits") or {},
                             kind=row.get("kind") or "") == "proof_review", row
    assert row["proof_text"] == PROOF, row


# ====================================================================== g 正控

def test_g_the_registered_path_still_upgrades_like_the_good_现场(tmp_path: pathlib.Path) -> None:
    """g：000013/000017 那种"两步都跑"的正控仍在 —— 签一到，`pre_theorem` 就到位。"""
    st = _ws(tmp_path)
    sid = _seed(st, proof_text=PROOF)
    rel = _manuscript(st, sid)
    third = _sign_three(st, sid, rel)
    assert (third.get("statement_writeback") or {}).get("written") is True, third
    row = _row(st, sid)
    assert EB.bits_from_row(row)["grade"] == "pre_theorem", row.get("bits")
    assert EB.kind_from_bits(row.get("bits") or {},
                             kind=row.get("kind") or "") == "proof_review", row
    assert (row.get(VR.GRADE_RECOMPUTED_KEY) or {}).get("to") == "pre_theorem", row


# ====================================================================== 丙 义务项

def _board(tmp_path: pathlib.Path) -> tuple[Store, Conductor, str, str]:
    st = _ws(tmp_path)
    cond = Conductor(st, registry={}, backend=LocalBackend({}))
    owner = str(cond.open_top_level_run("M", "义务项收口"))
    sha = VR.proof_sha(PROOF)
    with calling_as(owner, "M"):
        opened = cond.open_item(kind="notice", role="B", expects="work", action="notice",
                                summary="必须收录：签已落、statement 行还空",
                                called_by="V", parent_task_id=owner, depth=2,
                                input_key=f"b-register@{SID}@{sha}")
    item = str(opened)
    cond.mark_item_seen(item, by_task_id=owner, step=1)
    return st, cond, owner, item


def test_the_registration_obligation_cannot_be_closed_by_ack(tmp_path: pathlib.Path) -> None:
    """丙：`b-register@` 是 `expects=work` 的义务 —— `ack`/`completed` 都关不掉它。"""
    st, cond, owner, item = _board(tmp_path)
    before = next(dict(r) for r in cond._tasks() if r["task_id"] == item)
    for close in ("acked", "completed"):
        out = cond.ack_items([item], close=close, by_task_id=owner)
        assert out["state"] == "refused", out
        assert "obligation_needs_evidence" in (out.get("refusal_codes") or []) \
            or "bad_close" in (out.get("refusal_codes") or []), out
    after = next(dict(r) for r in cond._tasks() if r["task_id"] == item)
    assert after["item_state"] == before["item_state"], after
    assert after["item_close"] == "", after

    # 框架凭证据收口那一条路仍然在（摘掉义务闸不许把正路也堵了）。
    state, why = cond.close_item_by_evidence(item, close="expired", why="明确放弃：夹具")
    assert state == "done" and not why, (state, why)


# ====================================================================== f 反真空

def _unplug_sign_gate(monkeypatch) -> None:
    """把必填闸打桩成恒放行（"改前"的现场：唯一写口不再核这些事）。

    2026-11-05 晚这一批是两道：形状闸（`sign_object_gate`：对象 / 台账形状 / 三票）
    与背书闸（`sign_ledger_backing`：那一行在不在盘上、是不是这一份正文、签不签得住）。
    反真空要摘的是"这一签凭什么成立"的全部判据，所以两道一起摘。
    """
    monkeypatch.setattr(VS, "sign_object_gate",
                        lambda **_kw: {"ok": True, "code": "", "reason": "",
                                       "ledger_kind": ""})
    monkeypatch.setattr(VS, "sign_ledger_backing",
                        lambda root, ledger, *, proof_sha256: {
                            "checked": True, "ok": True, "code": "", "row": {},
                            "path": "", "verification_id": "", "why": "夹具：摘掉背书闸"})


def test_f_a_without_the_gate_an_empty_ledger_anchor_writes_a_sign(
        tmp_path, monkeypatch) -> None:
    """f-a：摘掉闸 ⇒ a 当场红（连台账都没有也写出了签文件）。"""
    _unplug_sign_gate(monkeypatch)
    st = _ws(tmp_path)
    sha = VR.proof_sha(PROOF)
    wrote = VS.issue(st.root, artifact_sha=sha, streak=3, need=3,
                     artifact_path="reports/f-proof-000013.md", ledger="",
                     statement_id="", passes=_passes(sha), by="secretary:F")
    assert wrote["written"] is True, wrote
    assert VS.sign_path(st.root, sha).is_file()


def test_f_b_without_the_gate_a_self_referential_ledger_writes_a_sign(
        tmp_path, monkeypatch) -> None:
    """f-b：摘掉闸 ⇒ b 当场红（稿头自述被当成了台账）。"""
    _unplug_sign_gate(monkeypatch)
    st = _ws(tmp_path)
    sha = VR.proof_sha(PROOF)
    rel = _manuscript(st, SID)
    wrote = VS.issue(st.root, artifact_sha=sha, streak=3, need=3, artifact_path=rel,
                     ledger=f"{rel}#V签", statement_id=SID, passes=_passes(sha),
                     by="secretary:F")
    assert wrote["written"] is True, wrote
    assert VS.sign_path(st.root, sha).is_file()


def test_f_c_without_the_gate_three_empty_passes_write_a_sign(tmp_path, monkeypatch) -> None:
    """f-c：摘掉闸 ⇒ c 当场红（三个空对象被数成连续 3/3）。"""
    _unplug_sign_gate(monkeypatch)
    st = _ws(tmp_path)
    sha = VR.proof_sha(PROOF)
    wrote = VS.issue(st.root, artifact_sha=sha, streak=3, need=3,
                     artifact_path="reports/f-proof-000013.md",
                     ledger=f"verifications/{SID}.jsonl#v-000003", statement_id=SID,
                     passes=[{}, {}, {}], by="secretary:F")
    assert wrote["written"] is True, wrote
    assert VS.sign_path(st.root, sha).is_file()


def test_f_d_without_the_carrier_gate_a_plan_block_is_resolved(tmp_path, monkeypatch) -> None:
    """f-d：把载体判定摘掉 ⇒ d 当场红（计划稿的签块又读成 `identity_state=resolved`）。"""
    monkeypatch.setattr(VS, "sign_carrier_reading",
                        lambda path: {"ok": True, "code": "", "reason": "",
                                      "name": str(path)})
    st = _ws(tmp_path)
    rel = _manuscript(st, SID, plan=True)
    mark = VS.render_manuscript_sign(
        proof_sha=VR.proof_sha(PROOF), streak=3, need=3,
        ledger=f"verifications/{SID}.jsonl#v-000003", statement_id=SID,
        manuscript_id=f"plan-{SID}", signer="secretary:F")
    text = pathlib.Path(st.root, rel).read_text(encoding="utf-8") + "\n" + mark + "\n"
    reading = VS.manuscript_sign_reading(text, manuscript_path=rel)
    assert reading["identity_state"] == "resolved", reading


def test_f_e_without_the_backfill_the_grade_stays_heuristic(tmp_path, monkeypatch) -> None:
    """f-e：把回填打桩成"什么都不做" ⇒ 正文落进去之后档位仍停在 `heuristic`。"""
    monkeypatch.setattr(VR, "_grade_recomputed_from_signature",
                        lambda row, *, root, proof_no=None: {
                            "row": dict(row), "reading": {}})
    st = _ws(tmp_path)
    sid = _seed(st, proof_text="")
    rel = _manuscript(st, sid)
    _sign_three(st, sid, rel)
    b = AgentB(st, extractor=None, extract_text=None)
    bits = EB.bits_of(origin="own_result", proof=True, proof_process=PROOF,
                      kind="conjecture")
    b._attach_proofs(sid, [], canonical=PROOF, bits=bits)
    assert _row(st, sid)["evidence_kind"] == "heuristic", _row(st, sid)


def test_f_obligation_without_the_prefix_table_a_work_item_is_acked_closed(
        tmp_path, monkeypatch) -> None:
    """f-丙：把"义务项"前缀表打桩成空 ⇒ 同一条 `b-register@` 会被 `completed` 关掉。"""
    monkeypatch.setattr(Conductor, "_evidence_closed_item_prefixes",
                        staticmethod(lambda: ()))
    _st, cond, owner, item = _board(tmp_path)
    out = cond.ack_items([item], close="completed", by_task_id=owner)
    assert out["state"] == "acked", out
    row = next(dict(r) for r in cond._tasks() if r["task_id"] == item)
    assert row["item_close"] == "completed", row


#: 防"夹具从不走正路"：本文件里那两条正控（g / 丙的 evidence 收口）用的就是生产口。
assert S.ID_DIGITS >= 4
