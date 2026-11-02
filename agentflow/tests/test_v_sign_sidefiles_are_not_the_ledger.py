# -*- coding: utf-8 -*-
"""V 签的侧文件与「有毛病」回执：两个对象严格分开（业主 2026-11-01）。

## 口径（逐字，别改解释）

```text
「有毛病」是给提供证明的一方看的，具体信息是叫它们优化证明，只有连续三次审核通过这才叫 V 签。
「V 签不直接进台账，进手稿，随 B 侧将手稿中的定理或命题收录时读到。B 侧自己写的证明想要 V
签时一样是拿到 V 签，B 再录入。」
```

## 两个对象与一条从属关系

| 对象 | 落点 | 它是什么 | 谁能拿它下结论 |
|---|---|---|---|
| 回执 | 「不落文件」：`vsigns.receipt_of` 从台账现算 | V 判「有毛病」的那一次（逐条缺陷） | 读的人（F / M） |
| 送达 | 「不落文件」：`vsigns.delivery_of` 从 `tasks` + `agent_mailbox` 现算 | 这条意见交给了谁、谁读了、什么时候 | 读的人 |
| 签 | `out/vsigns/<artifact_sha>.json` | 连续 `need` 次「成立」那一刻留的档 | B 收录时认它；门核它 |
| 归档 | `out/vsigns/issued.json` | 「派生索引」（只给人看） | 「谁都不许拿它下结论」 |

> 回执从来不是签；归档从来不是判定依据；判定只读逐份 `<sha>.json` 与台账。

## 判据表（每条都带"它能怎么红"）

| 编号 | 它要证明的事 | 它能怎么红 |
|---|---|---|
| r1 | 判「有毛病」⇒ 有一份回执（现算），逐条缺陷，且 `bits.reviewed` 仍是假 | 把回执当签（写 true）⇒ 红 |
| r2 | 回执不改任何判定读数（`state` 仍 `rejected`、位仍假）；签过的那一条则 `found=False` | 读口退化成"什么都算有" ⇒ 红 |
| r3 | 连续次数未到门槛 ⇒ 一个签文件都不许有（`write_sign` 自己也拒） | 一次成立就写签 ⇒ 红 |
| r4 | 连续次数到门槛 ⇒ 「恰好一份」签文件，名字 = 正文 sha，`passes` 三转逐字，`written_by=secretary/direct` 如实 | 写两份 / 名字错 / passes 只有 1 条 ⇒ 红 |
| r4b | 签过之后再判第 4 转：签文件不被重写（一稿一签），且整笔不失败 | 覆盖旧签 ⇒ 红 |
| r5 | 写签不改被签正文的 sha（不自指），且签文件不在稿内 | 把签写进稿内 ⇒ 红 |
| r6 | 送达三档（`delivered` / `dispatched_only` / `not_dispatched`）从盘上现算，`delivered_at` 取自 `agent_mailbox` | 没送却读成送到 ⇒ 红 |
| r7 | `issued.json` == 从 `out/vsigns/*.json` 重建的结果（逐格相等），重建两次字节相同 | 手改归档 ⇒ 红 |
| r8 | 漏记（签文件在、归档没有）⇒ 红 | 归档失败静默 ⇒ 红 |
| r9 | 虚记（归档有、签文件不在）⇒ 红 | 手工补一条 ⇒ 红 |
| r10 | 伪造痕迹：`archived_by` 不是工具标识，或 `archived_at` 不是派生值 ⇒ 红 | 手写一条 ⇒ 红 |
| r11 | 没有 `out/vsigns/` ⇒ `not_applicable`，「不建目录」 | 凭空造空归档 ⇒ 红 |
| r12 | 81 只读复制品上读得出「8 条打回 / 4 条送达 / 4 条未送达」 | 读口把"没送到"吞掉 ⇒ 红 |

改动前读数（2026-11-01 81 只读复制品 `temp/161_replica_81`）：台账 8 行全是「有毛病」、
0 行「成立」、`bits.reviewed=True` 0 行、板项 4 条、`agent_mailbox` 2 条、后 4 条判定
（04:05–04:14）全在 F 最后一趟起跑（03:54:03）之后 ⇒ 一条都没送到。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import evidencebits as EB
from agentflow import verifications as VR
from agentflow import vsigns as VSP
from agentflow.store import Store

TS = "2026-11-01T00:00:00+08:00"
SID = "000081"
PROOF = "1. 取 G = C_n（n ≥ 3）：它是 2-正则、围长为 n。\n2. 由第 1 步直接得到结论。"
FULL = "设 G 是 3-正则群；则弦长函数不是常值。"
_OK = {"verdict": "成立", "findings": []}
_BAD = {"verdict": "有毛病", "defect_step": 2, "why": "第 2 步没有依据",
        "findings": [
            {"level": "error", "step": 2, "kind": "无依据的步骤",
             "detail": "第 2 步直接用了结论"},
            {"level": "error", "step": 3, "kind": "记号没定义",
             "detail": "第 3 步的 d1 没有定义"},
        ]}
#: 81 那份只读复制品（本机证据物；不在仓里就跳过 r12 —— 它验的是读数，不是夹具行为）。
REPLICA_81 = pathlib.Path(__file__).resolve().parents[1] / "temp" / "161_replica_81"


# ------------------------------------------------------------------ 夹具

def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _put(store: Store, *, proof: str = PROOF) -> dict:
    row = {
        "stmt_id": SID, "origin": "own_result", "kind": "theorem",
        "label": "弦长函数非常值", "statement_full": FULL,
        "statement_text": "弦长函数不是常值", "proof_text": proof,
        "evidence_kind": "heuristic", "status": "active",
        "quote_verified": None, "quote_reason": "自产命题",
        "created_at": TS, "created_by": "test",
        "bits": EB.bits_of(proof=True, proof_process=proof, kind="theorem"),
    }
    with store.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)
    return row


def _row(store: Store) -> dict:
    return dict(store.rows("statements")[0])


def _fault(store: Store, *, verdict: dict | None = None, proof: str = PROOF) -> dict:
    """一条「有毛病」的审校（秘书判了 fault、洗稿洗出了转达文本 —— 与 81 的落盘形状一致）。"""
    return VR.record_verification(
        store.root, statement_id=SID, proof_text=proof, verdict=verdict or _BAD,
        verifier="agent-V", store=store, proof_no=1,
        secretary_judge={"checked": True, "axis": "fault", "decision": "有缺陷要指出"},
        washed_relay={"washed": True,
                      "text": "第 2 步缺依据、第 3 步记号没定义；补完再送 V。"})


def _clean(store: Store, *, proof: str = PROOF) -> dict:
    return VR.record_verification(
        store.root, statement_id=SID, proof_text=proof, verdict=_OK,
        verifier="agent-V", store=store, proof_no=1,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题"})


def _signs(store: Store) -> list[str]:
    """签目录里的「签文件」（`issued.json` 是归档，不是签）。"""
    d = VSP.signs_dir(store.root)
    return sorted(p.name for p in d.glob("*.json") if p.name != VSP.INDEX_NAME) \
        if d.is_dir() else []


def _sign_doc(store: Store, sha: str) -> dict:
    return json.loads(VSP.sign_path(store.root, sha).read_text(encoding="utf-8"))


def _board_item(store: Store, *, item: str = "t-000001", key: str,
                acked: bool = True, seen_by: str = "t-000002") -> None:
    """造一条 V 判决板项（`deliver_v_verdicts` 的落点形状）。

    `acked=False` 那一档是"开了项、还没被读"：`item_state` 停在 `pending` 且「不写」
    `seen_by` —— `schema.Task.validate` 的判据是「`item_state='seen'` 必须写 `seen_by`」
    （空口 ack 的判据靠它配对，业主 A3），所以"没读"不能拿 `seen` 去凑。
    """
    with store.tx("tasks", actor="test") as tx:
        tx.upsert("tasks", {
            "task_id": item, "role": "F", "action": "notice", "called_by": "V",
            "depth": 4, "input_key": key, "kind": "notice", "expects": "ack",
            "item_state": "done" if acked else "queued",
            "item_close": "acked" if acked else "",
            "seen_by": seen_by if acked else "", "seen_step": 0 if acked else None,
            "status": "pending", "detail": "夹具",
        })


def _mailbox(store: Store, *, item: str, at: str = "2026-11-01T03:14:35+08:00") -> None:
    """造一条 `agent_mailbox` 事件（`record_mailbox_delivery` 的落盘形状）。"""
    base = pathlib.Path(store.root) / "sessions"
    base.mkdir(parents=True, exist_ok=True)
    with (base / "20261101.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"kind": "agent_mailbox", "at": at, "role": "F",
                             "step": 0, "item_ids": [item]},
                            ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- r1 / r2：回执不是签

def test_r1_a_fault_leaves_a_receipt_with_every_defect(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    _fault(st)
    sha = VR.proof_sha(PROOF)
    got = VSP.receipt_of(st.root, sha)
    assert got["checked"] and got["found"], (
        "判了「有毛病」而回执读口说没有 ⇒ 缺陷没有任何逐条落点"
        "（业主：『有毛病』是给提供证明的一方看的，具体信息是叫它们优化证明）")
    assert [d["step"] for d in got["defects"]] == [2, 3], got["defects"]
    assert all(str(d["text"]).strip() for d in got["defects"]), "每一条缺陷都要带正文"
    assert got["verdict"] == "有毛病"
    # 回执不是签：位仍是假。
    assert _row(st)["bits"].get("reviewed") is False
    assert _signs(st) == [], "一张「有毛病」的回执不许变成签文件"


def test_r2_a_receipt_changes_no_verdict_reading(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    _fault(st)
    reading = VR.statement_review_reading(st.root, _row(st))
    assert reading["state"] == "rejected", reading
    assert not reading["reviewed"], (
        "回执把第 3 位读成了真 ⇒ 一张『有毛病』的纸条被当成了签")
    assert EB.bits_from_row(_row(st)).get("reviewed") is False
    # 反真空：换一份「签过」的正文，同一个读口必须说 found=False（回执读口不是"什么都算有"）。
    other = VSP.receipt_of(st.root, VR.proof_sha(PROOF + "\n3. 另一版。"))
    assert other["checked"] and not other["found"], other


# ---------------------------------------------------------------- r3 / r4：门槛与签文件

def test_r3_below_the_bound_no_sign_file_is_written(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    _clean(st)
    _clean(st)
    got = VR.consecutive_holds(st.root, SID, proof_no=1)
    assert (got["streak"], got["need"]) == (2, 3), got
    assert _signs(st) == [], f"连续 2/3 次就出现了签文件 {_signs(st)} ⇒ 门槛被绕过"
    # 门槛那一层自己也拒（唯一写口不许只看调用方说的 written=True）。
    # 2026-11-02 起写口分成 `issue` / `land` 两步，这里量的是"颁发"那一半。
    refused = VSP.issue(st.root, artifact_sha=VR.proof_sha(PROOF), streak=2, need=3,
                        by="secretary:F")
    assert not refused["written"] and "未达门槛" in refused["reason"], refused
    assert _signs(st) == []


def test_r4_the_third_hold_writes_exactly_one_sign_file(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    _clean(st)
    _clean(st)
    third = _clean(st)
    wb = third.get("statement_writeback") or {}
    assert wb.get("written") is True, wb
    sha = VR.proof_sha(PROOF)
    assert _signs(st) == [f"{sha}.json"], (
        f"连续 3/3 次成立、第 3 位已经翻了，盘上却是 {_signs(st)} ⇒ "
        "签只活在 statements 那一格里（业主：签要进手稿，随 B 收录时读到）")
    doc = _sign_doc(st, sha)
    assert doc["artifact_sha"] == sha and doc["verdict"] == "成立"
    assert (doc["streak"], doc["need"]) == (3, 3)
    assert [p["verification_id"] for p in doc["passes"]] == \
        ["v-000001", "v-000002", "v-000003"], (
            "passes 要逐转留（三元读数，逐字 why）；只剩 1 条就等于把前两转丢了")
    assert all(str(p["why"]) == "" or True for p in doc["passes"])
    assert doc["written_by"] == VSP.WRITTEN_BY_DIRECT, (
        "这一条是直调写入口（`record_verification(flip=True)`）⇒ 不许冒充 secretary")
    assert "verifications/000081.jsonl#v-000003" == doc["ledger"]
    assert doc["source_note"] == VSP.PASSES_SOURCE_NOTE, (
        "签里必须写清「passes 不是全文、全文在台账」—— 别让后来人误会")


def test_r4b_a_fourth_pass_does_not_rewrite_the_sign(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    for _ in range(3):
        _clean(st)
    sha = VR.proof_sha(PROOF)
    before = _sign_doc(st, sha)
    fourth = _clean(st)
    wb = (fourth.get("statement_writeback") or {})
    assert wb.get("written") is True, (
        "第 4 转把整笔弄失败了 ⇒ 一稿一签的判据变成了'签过就不许再判'")
    after = _sign_doc(st, sha)
    assert after == before, (
        "第 4 转把签文件重写了（at/passes 变了）⇒ 一稿一签被破坏；"
        "签是'第 3 转那一刻'的档，后面的转只进台账")
    assert _signs(st) == [f"{sha}.json"]


def test_r4c_the_secretary_path_marks_the_sign_as_hers(tmp_path):
    """落签者是收方秘书（业主 2026-11-02）：签文件里的 `written_by` 必须点名是哪一位。

    为什么这一格要单独钉：`sign_statement` 有两条调用者（秘书落地 / 直调写入口），
    而"签该由谁落"只能从权威上下文读（`conductor.current_parent()` 的父角色，
    见 `Secretary.sign_recipient`）—— 不许从 `self.role`（那是 V 自己的角色）凑一个。
    两档写成同一个值，读的人就分不出"收方秘书落的签"与"夹具/直调发的签"。
    """
    from agentflow import conductor as CND
    from agentflow import secretary as SEC

    class _Seam:
        """离线替身缝：`sign_issuance` 一律答「签发」。"""

        wired = True

        def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                     note: str = "") -> tuple[dict, object]:
            class _Call:
                ok = True
                problem = ""
                detail = ""
                text = ""
                model = "fake"
                prompt_version = "t"
                prompt_sha256 = "0" * 64

            return {"decision": SEC.SIGN_ISSUE, "reason": "夹具：三轮都干净",
                    "basis": ["夹具"]}, _Call()

    st = _ws(tmp_path)
    _put(st)
    for _ in range(2):
        _clean(st)
    # 第 3 转走"V 只落台账、秘书翻位"那条生产路（`flip=False` + `decide_sign_issuance`）。
    third = VR.record_verification(
        st.root, statement_id=SID, proof_text=PROOF, verdict=_OK,
        verifier="agent-V", store=st, proof_no=1, flip=False,
        secretary_judge={"checked": True, "axis": "clean", "decision": "没问题"})
    sec = SEC.Secretary("V", root=st.root, store=st, seam=_Seam(), enable_model=True)
    # V 这一趟是 F 派出来的（收方 = F 的秘书）—— 身份只从 `calling_as` 读，不由模型给。
    with CND.calling_as("t-v-000001", "V", parent_task_id="t-f-000001",
                        parent_role="F"):
        got = sec.decide_sign_issuance(statement_id=SID, proof_text=PROOF, proof_no=1,
                                       verdict=_OK, row=third)
    assert got["issue"] is True and got["issued"] is True, got
    sha = VR.proof_sha(PROOF)
    doc = _sign_doc(st, sha)
    assert doc["written_by"] == "secretary:F", (
        f"收方秘书那条路写出来的签记成了 {doc['written_by']!r} ⇒ "
        "「谁该落这一签」这一格读不出业主口径里的那个答案（只许 secretary:F / secretary:B）")
    assert doc["envelope"]["to"] == "secretary:F", doc.get("envelope")
    assert [p["verification_id"] for p in doc["passes"]] == \
        ["v-000001", "v-000002", "v-000003"], doc["passes"]
    assert VSP.index_drift(st.root)["drift"] == []

def test_r5_writing_the_sign_does_not_move_the_artifact_sha(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    want = VR.proof_sha(PROOF)
    for _ in range(3):
        _clean(st)
    got = VR.proof_sha(str(_row(st).get("proof_text") or ""))
    assert got == want, (
        f"签写完之后被签的那份正文的 sha 变了（{want[:12]}… → {got[:12]}…）⇒ 自指矛盾")
    sign_path = VSP.sign_path(st.root, want)
    assert sign_path.is_file()
    doc = _sign_doc(st, want)
    # `artifact_path` 是稿的位置（这里没有手稿 ⇒ 空串），但无论它是什么都不许是签自己。
    assert str(doc.get("artifact_path") or "") != VSP.rel(sign_path, st.root)
    assert not str(doc.get("artifact_path") or "").startswith(VSP.SIGNS_DIR), (
        "签被写进了签目录以外的地方 / 或把签自己当成了稿")


# ---------------------------------------------------------------- r6：送达三档

def test_r6_delivery_states_are_read_from_the_board(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    _fault(st)
    key = f"v-verdict@{SID}#p1@v-000001"
    # ① 只判了、没人开项 ⇒ not_dispatched（81 的后 4 条就是这一档）。
    one = VSP.receipt_digest(st.root, st)
    assert (one["receipts"], one["delivered"], one["undelivered"]) == (1, 0, 1), one
    assert one["rows"][0]["state"] == "not_dispatched", one["rows"]
    # ② 开了项但没读 ⇒ dispatched_only。
    _board_item(st, key=key, acked=False)
    two = VSP.receipt_digest(st.root, st)
    assert two["rows"][0]["state"] == "dispatched_only", two["rows"]
    assert (two["delivered"], two["undelivered"]) == (0, 1), two
    # ③ 读了并 ack ⇒ delivered，且收件人与时刻都从盘上现算。
    _board_item(st, key=key, acked=True)
    _mailbox(st, item="t-000001")
    three = VSP.receipt_digest(st.root, st)
    row = three["rows"][0]
    assert row["state"] == "delivered", row
    assert row["delivered_to"] == "F", row
    assert row["delivered_at"] == "2026-11-01T03:14:35+08:00", row
    assert row["read_step"] == 0
    assert (three["delivered"], three["undelivered"]) == (1, 0), three
    # ④ 反真空：把 ack 撤掉 ⇒ 读数必须翻回去（不是"读到过就永远是 delivered"）。
    _board_item(st, key=key, acked=False)
    assert VSP.receipt_digest(st.root, st)["rows"][0]["state"] == "dispatched_only"


# ---------------------------------------------------------------- r7–r11：派生归档

def _three_and_sign(st: Store) -> str:
    _put(st)
    for _ in range(3):
        _clean(st)
    return VR.proof_sha(PROOF)


def test_r7_the_archive_equals_a_full_rebuild(tmp_path):
    st = _ws(tmp_path)
    sha = _three_and_sign(st)
    path = VSP.index_path(st.root)
    assert path.is_file(), f"发过一次签而 `{path.name}` 不在盘上"
    on_disk = VSP.load_index(st.root)[0]
    computed = VSP.compute_index(st.root)
    assert VSP.index_body(on_disk) == VSP.index_body(computed), (
        "`issued.json` 与『从 out/vsigns/*.json 全量重建』的结果不是逐格相等 ⇒ "
        "归档已经不是派生物了（顺序规则：按 at 升序、同 at 再按 artifact_sha）")
    assert [e["artifact_sha"] for e in on_disk["signs"]] == [sha]
    first = path.read_bytes()
    VSP.rebuild_index(st.root)
    second = path.read_bytes()
    assert first == second, "重建两次字节不同 ⇒ 顺序规则或派生字段不稳定（判据①失效）"
    assert VSP.index_drift(st.root)["drift"] == []


def test_r8_a_missing_archive_entry_is_red(tmp_path):
    st = _ws(tmp_path)
    _three_and_sign(st)
    path = VSP.index_path(st.root)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["signs"] = []
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    got = VSP.index_drift(st.root)
    assert got["checked"] is True, got
    assert any("漏记" in d for d in got["drift"]), (
        f"签文件在、归档里一条都没有，而 drift 没报漏记：{got['drift']}")


def test_r9_a_fake_archive_entry_is_red(tmp_path):
    st = _ws(tmp_path)
    _three_and_sign(st)
    path = VSP.index_path(st.root)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["signs"].append({"artifact_sha": "f" * 64, "artifact_path": "reports/x.md",
                         "verdict": "成立", "at": TS, "streak": 3, "need": 3,
                         "statement_id": SID,
                         "archived_by": VSP.ARCHIVED_BY, "archived_at": TS})
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    got = VSP.index_drift(st.root)
    assert any("虚记" in d for d in got["drift"]), (
        f"归档里有、盘上没有对应签文件，而 drift 没报虚记：{got['drift']}")


def test_r10_a_hand_edited_archive_entry_is_red(tmp_path):
    st = _ws(tmp_path)
    _three_and_sign(st)
    path = VSP.index_path(st.root)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["signs"][0]["archived_by"] = "someone-with-editor"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    got = VSP.index_drift(st.root)
    assert any("archived_by" in d for d in got["drift"]), (
        f"归档项的 archived_by 不是发签工具写的，而 drift 没点名：{got['drift']}")
    # `archived_at` 也要是派生值（= 签文件的 at）：改成墙钟就是伪造痕迹。
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["signs"][0]["archived_by"] = VSP.ARCHIVED_BY
    doc["signs"][0]["archived_at"] = "2020-01-01T00:00:00+08:00"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    got = VSP.index_drift(st.root)
    assert any("archived_at" in d for d in got["drift"]), got["drift"]


def test_r11_an_old_workspace_sees_no_new_files(tmp_path):
    st = _ws(tmp_path)
    _put(st)
    _fault(st, proof=PROOF + "\n3. 改稿之后。")
    got = VSP.index_drift(st.root)
    assert got["tri"] == "not_applicable" and got["drift"] == [], (
        f"没有 out/vsigns/ 的工作区要如实报 not_applicable（不是『一致』、也不是红）：{got}")
    assert not VSP.signs_dir(st.root).exists(), "不许为了『有东西可读』凭空建目录"
    backed = VSP.backed_reading(st.root, st.rows("statements"), store=st)
    assert backed["tri"] == "not_applicable" and backed["signed"] == [], backed


# ---------------------------------------------------------------- r12：81 的读数

@pytest.mark.skipif(not REPLICA_81.is_dir(),
                    reason="81 的只读复制品不在本机（temp/161_replica_81 是证据物，不入仓）")
def test_r12_the_81_replica_reads_eight_receipts_four_delivered():
    st = Store(REPLICA_81)
    got = VSP.receipt_digest(REPLICA_81, st)
    assert got["checked"] and got["delivery_checked"], got
    assert (got["receipts"], got["statements"]) == (8, 7), got["reason"]
    assert (got["delivered"], got["undelivered"]) == (4, 4), (
        f"81 的真机读数是 8 条打回 / 4 条送达 / 4 条未送达，读到的是 {got['reason']}")
    assert sorted(got["undelivered_ids"]) == [
        "000019#p1@v-000001", "000020#p1@v-000001",
        "000021#p1@v-000001", "000048#p1@v-000001"], got["undelivered_ids"]
    # 没有 out/vsigns/ 的历史工作区：签那一族不适用（不红、也不假装通过）。
    assert VSP.index_drift(REPLICA_81)["tri"] == "not_applicable"
