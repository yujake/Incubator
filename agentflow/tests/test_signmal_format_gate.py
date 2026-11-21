# -*- coding: utf-8 -*-
"""判据：签文件的格式闸（SIGNMAL，2026-11-21）——「写侧受控拒」而不是「事后对账抓」。

## 现场（逐字，只读取证）

真机 `projects/lp-ball-15` 的 `out/vsigns/` 里有四份签（`temp/reconB` 对账：合格 3 /
不合格 1）。不合格的那一份是
`2f77e321f1ea40ef7513a449801b3499dbf589322059724c79678d232508dd44.json`：

```text
pass#1/#2/#3 的 object_sha256 不是 64 位 hex
```

三票的 `object_sha256` 都是空串 —— 在册那一支的台账行从来没有这一格
（`v_ledger_write.record_verification` 只在调用方给了才写，V 的在册写口没给），
`sign_counting.ticket` 原样抄过来，`vsigns.issue` 原样落盘。写侧此前只判
「这一签该不该发」，不判「这一份签的读数字段能不能用」⇒ 坏形状只能等事后对账抓。

## 这一份量什么

| # | 造什么 | 期望 |
|---|---|---|
| a | 台账行的 `object_sha256` 是非空但不是 64 位 hex | `issue` 受控拒 `malformed_sign_file`，`out/vsigns/` 一个文件都没有 |
| a2 | 台账行没有 `object_sha256`（真机那一份的形状）、`artifact_path` 在盘上 | 照常落盘，且三票的 `object_sha256` 都是 64 位 hex、等于那份稿的字节 sha |
| b | 三票都带合法的 `object_sha256` / `review_call` / `review_pass` | 照常落盘（正控） |
| c1 | `passes` 是空的（0 票） | 受控拒 |
| c2 | 非 legacy 的票没有 `review_call` | 受控拒 |
| d | 把 `sign_file_problems` 打桩成恒放行 | a 必红（坏值照常落盘） |

夹具全部 tmp 工作区、零模型调用；不读写 `projects/`（真机那一段只作取证引用）。

## 为什么 a2 是「补」不是「拒」

`object_sha256` 为空有两种来路：「点了名一份稿而没记它的字节 sha」（真机这一份）与
「这一签根本没有对象文件」。前者能现算（那份稿的字节 sha，与未在册那一支记的值
同一把尺）⇒ 写侧补上；补不上的那一档（点了名、文件在盘上而读不出来）才拒。
详见 `vsigns.complete_object_identity` / `vsigns.sign_file_problems`。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import sign_counting as SC  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402

SID = "000003"
CALL = "63d3444b63bb"
REL = "reports/f-proof-000003.md"
PROOF = ("1. 由定义直接得到 V_p(2) 的两段表达式。\n"
         "2. 由第 1 步与 ψ 严格递增得左支严格递增。\n"
         "3. 由第 2 步与 π^2/4−2<log2 得右支严格递减。")
TS = "2026-11-21T16:58:56+08:00"
GOOD_OBJ = "a" * 64


def _sha() -> str:
    """这一份正文的签尺（唯一实现 `_sign_sha`，与 `issue` 同一把）。"""
    return VS._sign_sha(PROOF)


def _ws(root: pathlib.Path) -> str:
    """一个最小工作区：一份手稿 + 一本在册台账 ⇒ 返回正文 sha。"""
    (root / "verifications").mkdir(parents=True, exist_ok=True)
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / REL).write_text(
        "# F 的证明手稿：夹具\n\n## 命题\n\n夹具命题。\n\n"
        f"## 证明\n\n{PROOF}\n\n## 依赖\n\n| 引用 | 命题号 | 用在哪一步 |\n"
        "|---|---|---|\n", encoding="utf-8")
    return _sha()


def _row(pass_no: int, *, object_sha: str | None = None) -> dict:
    """一条台账行（同一 `review_call`、`review_pass=pass_no`、clean、成立）。

    `object_sha=None` ⇒ 这一行没有 `object_sha256` 这一格（真机在册行的形状）。
    """
    row = {
        "verification_id": f"v-{pass_no:06d}", "statement_id": SID, "stmt_id": SID,
        "proof_no": 1, "proof_sha256": _sha(), "verdict": "成立",
        "secretary_judge": {"checked": True, "axis": "clean"},
        "findings": [], "defect_step": None, "unresolved_errors": 0,
        "at": f"2026-11-21T16:5{pass_no}:00+08:00", "round": pass_no,
        "review_call": CALL, "review_pass": pass_no, "manuscript": REL,
        "why": f"第 {pass_no} 转：逐条核对，未发现缺陷。",
    }
    if object_sha is not None:
        row["object_sha256"] = object_sha
    return row


def _write_ledger(root: pathlib.Path, rows: list[dict]) -> None:
    path = root / "verifications" / f"{SID}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def _passes(sha: str, rows: list[dict]) -> list[dict]:
    """调用方那一份 `passes`（只有 legacy 那一档会用到；三票逐行取）。"""
    return [{"verification_id": r["verification_id"], "at": r["at"],
             "proof_sha256": sha, "review_call": r["review_call"],
             "review_pass": r["review_pass"]} for r in rows]


def _issue(root: pathlib.Path, rows: list[dict], **kw) -> dict:
    sha = _sha()
    return VS.issue(root, artifact_sha=sha, streak=3, need=3, artifact_path=REL,
                    ledger=f"verifications/{SID}.jsonl#{rows[-1]['verification_id']}",
                    statement_id=SID, proof_no=1, passes=_passes(sha, rows),
                    at=TS, by="secretary:F", **kw)


def _sign_files(root: pathlib.Path) -> list[pathlib.Path]:
    d = VS.signs_dir(root)
    return sorted(p for p in d.glob("*.json") if p.name != VS.INDEX_NAME) \
        if d.is_dir() else []


def _sign_doc(root: pathlib.Path) -> dict:
    files = _sign_files(root)
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _unplug_shape_gates(monkeypatch) -> None:
    """把「这一签凭什么成立」的几道闸打桩成恒放行（只给 c 组造"坏形状"用）。

    与 `test_sign_integrity_gates._unplug_sign_gate` 同一做法：不摘掉它们，坏形状会先
    被「对象 / 背书 / 系统计数」那几道闸挡住，量到的就不是格式闸的牙。
    """
    monkeypatch.setattr(VS, "sign_object_gate",
                        lambda **_kw: {"ok": True, "code": "", "reason": "",
                                       "ledger_kind": "registered"})
    monkeypatch.setattr(VS, "sign_ledger_backing",
                        lambda root, ledger, *, proof_sha256: {
                            "checked": True, "ok": True, "code": "", "row": {},
                            "path": "", "verification_id": "", "why": "夹具：摘掉背书闸"})


# ============================================================ a：非空而形状坏 ⇒ 拒

def test_a_a_malformed_object_sha_is_refused_before_anything_lands(tmp_path):
    """a：台账行的 `object_sha256` 不是 64 位 hex ⇒ 受控拒，`out/vsigns/` 零文件。

    改前这一份会原样落盘（`issue` 把 `sign_counting.ticket` 抄来的值直接写文件）——
    真机 lp-ball-15 的 `2f77e321…` 就是那么来的。
    """
    root = tmp_path / "ws"
    sha = _ws(root)
    rows = [_row(1, object_sha=GOOD_OBJ), _row(2, object_sha="deadbeef"),
            _row(3, object_sha=GOOD_OBJ)]
    _write_ledger(root, rows)
    got = _issue(root, rows)
    assert got["written"] is False, got
    assert got["code"] == VS.MALFORMED_SIGN_FILE, got
    assert "object_sha256" in got["reason"], got["reason"]
    assert "第 2 票" in got["reason"], got["reason"]
    assert got["how_to_fix"] == VS.HOW_TO_FIX_MALFORMED_SIGN, got
    assert _sign_files(root) == [], "被拒的签落了盘"
    assert not VS.sign_path(root, sha).is_file(), "被拒的签落了盘"


def test_a2_the_real_machine_shape_is_completed_not_refused(tmp_path):
    """a2：台账行没有 `object_sha256`（真机那一份的形状）⇒ 落盘时补成 64 位 hex。

    补的值是「被审那份稿的字节 sha」—— 与未在册那一支记的是同一把尺
    （`agent_v/core.py::_manuscript_bytes_sha`），不是另发明一个数。
    """
    root = tmp_path / "ws"
    sha = _ws(root)
    rows = [_row(i) for i in (1, 2, 3)]  # 三行都没有 object_sha256
    assert all("object_sha256" not in r for r in rows), rows
    _write_ledger(root, rows)
    got = _issue(root, rows)
    assert got["written"] is True, got
    doc = _sign_doc(root)
    want = hashlib.sha256((root / REL).read_bytes()).hexdigest()
    assert [p["object_sha256"] for p in doc["passes"]] == [want] * 3, doc["passes"]
    assert [p["object_path"] for p in doc["passes"]] == [REL] * 3, doc["passes"]
    assert all(len(str(p["proof_sha256"])) == 64 for p in doc["passes"]), doc["passes"]


# ============================================================ b：合法签照常落盘

def test_b_a_well_formed_sign_still_lands(tmp_path):
    """b（正控）：三票都带合法的对象 sha / 同趟轮号 ⇒ 照常落盘。"""
    root = tmp_path / "ws"
    sha = _ws(root)
    rows = [_row(i, object_sha=GOOD_OBJ) for i in (1, 2, 3)]
    _write_ledger(root, rows)
    got = _issue(root, rows)
    assert got["written"] is True, got
    assert got["code"] == "" and got["how_to_fix"] == "", got
    doc = _sign_doc(root)
    assert [p["object_sha256"] for p in doc["passes"]] == [GOOD_OBJ] * 3, doc["passes"]
    assert [p["review_call"] for p in doc["passes"]] == [CALL] * 3, doc["passes"]
    assert [p["review_pass"] for p in doc["passes"]] == [1, 2, 3], doc["passes"]


# ============================================================ c：0 票 / 没有 review_call

def test_c1_zero_passes_is_refused(tmp_path, monkeypatch):
    """c1：`passes` 是空的（0 票）⇒ 受控拒（`passes` 必须是正整数张票）。"""
    root = tmp_path / "ws"
    _ws(root)
    _unplug_shape_gates(monkeypatch)
    monkeypatch.setattr(SC, "count_ledger_file",
                        lambda path, *, anchor_vid, proof_sha256, need: {
                            "checked": True, "ok": True, "count": int(need),
                            "need": int(need), "passes": [], "legacy": True,
                            "counted_by": "fixture:unplugged", "review_call": ""})
    got = VS.issue(root, artifact_sha=_sha(), streak=3, need=3, artifact_path=REL,
                   ledger=f"verifications/{SID}.jsonl#v-000003", statement_id=SID,
                   proof_no=1, passes=[], at=TS, by="secretary:F")
    assert got["written"] is False, got
    assert got["code"] == VS.MALFORMED_SIGN_FILE, got
    assert "passes" in got["reason"], got["reason"]
    assert _sign_files(root) == [], "0 票的签落了盘"


def test_c2_a_non_legacy_pass_without_review_call_is_refused(tmp_path, monkeypatch):
    """c2：非 legacy 的票没有 `review_call` ⇒ 受控拒（跨趟不拼票，得先说清哪一趟）。"""
    root = tmp_path / "ws"
    sha = _ws(root)
    _unplug_shape_gates(monkeypatch)
    #: 造一个「新形态计数、而票上没有 review_call」的形状：正常计数路径产生不出来
    #: （`count_rows` 只取同一 `review_call` 的行），所以这里把计数的返回值打桩成
    #: 那个形状 —— 量的是 `issue` 的格式闸，不是计数层。
    monkeypatch.setattr(SC, "count_ledger_file",
                        lambda path, *, anchor_vid, proof_sha256, need: {
                            "checked": True, "ok": True, "count": int(need),
                            "need": int(need), "legacy": False,
                            "counted_by": SC.COUNTED_BY, "review_call": CALL,
                            "anchor_pass": int(need), "anchor_call": CALL,
                            "passes": [{"verification_id": f"v-{i:06d}",
                                        "at": f"2026-11-21T16:5{i}:00+08:00",
                                        "proof_sha256": sha,
                                        "object_sha256": GOOD_OBJ,
                                        "review_call": "", "review_pass": i}
                                       for i in (1, 2, 3)]})
    got = VS.issue(root, artifact_sha=sha, streak=3, need=3, artifact_path=REL,
                   ledger=f"verifications/{SID}.jsonl#v-000003", statement_id=SID,
                   proof_no=1, passes=[], at=TS, by="secretary:F")
    assert got["written"] is False, got
    assert got["code"] == VS.MALFORMED_SIGN_FILE, got
    assert "review_call" in got["reason"], got["reason"]
    assert _sign_files(root) == [], "没有 review_call 的签落了盘"


# ============================================================ d：反真空

def test_d_without_the_format_gate_a_malformed_value_lands(tmp_path, monkeypatch):
    """d（反真空）：把 `sign_file_problems` 打桩成恒放行 ⇒ a 当场红（坏值落了盘）。"""
    monkeypatch.setattr(VS, "sign_file_problems", lambda doc: [])
    root = tmp_path / "ws"
    _ws(root)
    rows = [_row(1, object_sha=GOOD_OBJ), _row(2, object_sha="deadbeef"),
            _row(3, object_sha=GOOD_OBJ)]
    _write_ledger(root, rows)
    got = _issue(root, rows)
    assert got["written"] is True, got
    doc = _sign_doc(root)
    assert [p["object_sha256"] for p in doc["passes"]][1] == "deadbeef", doc["passes"]


# ============================================================ e：写口把值记进台账

def test_e_the_registered_writer_records_the_object_sha_in_the_ledger(tmp_path):
    """e：在册那一支的写口（`AgentV.verify_proof`）落台账时带上 `object_sha256`。

    改前 `_review_pass` 的 `record_verification(...)` 不传这一格 ⇒ 台账行没有它 ⇒
    签文件三票空串（真机 lp-ball-15 的畸形签）。这一条钉的是"值从哪来"：补全只是
    旧行的兜底，新行的正本在台账上。
    """
    from test_v_reviews_three_times_before_signing import (  # noqa: PLC0415
        CLEAN_REPLY, PROOF as V_PROOF, REL as V_REL, SID as V_SID,
        _ReviewSeam, _Seam, _as_submitter, _axis, _put, _secretary, _ws as _vws)
    from agentflow import secretary as SEC  # noqa: PLC0415
    from agentflow.agent_v import AgentV  # noqa: PLC0415

    st = _vws(tmp_path)
    _put(st, proof_text=V_PROOF)
    review = _ReviewSeam([CLEAN_REPLY])
    sec_seam = _Seam({"v_reply_defect": [_axis(SEC.V_REPLY_CLEAN)],
                      "sign_issuance": [_axis(SEC.SIGN_ISSUE)]})
    agent = AgentV(st, workspace_root=st.root, llm=review,
                   secretary=_secretary(st, sec_seam))
    #: 对象 sha 是「V 读到的、盖章之前的那一份文件」的字节 sha —— 盖章会在稿头插一行
    #: `- V 签：`，字节因此变；所以期望值必须在 `verify_proof` 之前算。
    want = hashlib.sha256((pathlib.Path(st.root) / V_REL).read_bytes()).hexdigest()
    with _as_submitter():
        agent.verify_proof(V_SID, proof_text=V_PROOF, proof_manuscript=V_REL)

    rows, bad = VR.list_verifications(st.root, statement_id=V_SID, limit=None)
    assert not bad, bad
    assert [str(r.get("object_sha256") or "") for r in rows] == [want] * 3, rows
    assert [str(r.get("object_path") or "") for r in rows] == [V_REL] * 3, rows
    doc = _sign_doc(pathlib.Path(st.root))
    assert [str(p.get("object_sha256") or "") for p in doc["passes"]] == [want] * 3, (
        doc["passes"])
