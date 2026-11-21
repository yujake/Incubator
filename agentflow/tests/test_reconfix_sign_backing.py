# -*- coding: utf-8 -*-
"""RECONFIX 判据：recon 的「签→台账回指」那一格必须按签的类型分流。

## 现场（为什么有这份判据）

`temp/reconB/recon.py` 的 ④ 项只认一本台账：`verifications/pending/<object_sha256>.jsonl`。
可盘上有两本：

- 在册签（号 `v-…`）住 `verifications/<命题号>.jsonl`
  （`v_paths.verification_ledger_path` / `v_ledger_write.next_verification_id`）；
- 未在册签（号 `u-…`）才落 `verifications/pending/<object_sha256>.jsonl`
  （`v_pending_write.record_pending_sign` / `v_vocab.PENDING_PREFIX`）。

只认一本 ⇒ 在册签一旦带上 `object_sha256`（SIGNMAL 2026-11-21 之后写侧的形态：
`agent_v/core.py` 的在册写口补上了这一格），recon 就去 pending 目录找它，
结构上永远找不到，于是把「在册签」读成「回指缺失」—— 口径混同，不是产物缺陷。

## 判据（先红后绿；红的那一版是 `temp/reconB/recon.py` 的旧实现）

| # | 判据 |
|---|---|
| a | 在册签夹具（`v-…` + 非空 object_sha256 + `verifications/000042.jsonl` 在盘）⇒ 不再判「回指缺失」，且回指对象是 `verifications/<命题号>.jsonl` |
| b | 未在册签夹具（`u-…` + `verifications/pending/<object_sha256>.jsonl` 在盘）⇒ 仍按 pending 回指（正控） |
| c | 两种都不在盘 ⇒ 仍判缺失（闸没关掉）；只对上 2/3 票也判缺失 |
| d | 反真空：把分流打桩回旧口径（`sign_kind_of` 恒 `pending`）⇒ a 必红 |
| e | 分不清类型（号既不是 v- 也不是 u- / 3 票不同形态）⇒ `unchecked`：不算合格、不算缺失，state 记 unknown |
| f | 不许跨本串读：在册签旁边摆一份 pending 干扰本（同一个 object sha），回指仍只认在册那一本 |
| g | 另一侧的口径陷阱：命题已在册、签是未在册时发的（`u-…`）⇒ 仍按 pending 回指（认领不搬家） |
| h | 反真空（另一侧）：把分流打桩成「按命题在不在册」⇒ g 必红 |

判据只读夹具、零模型、零真机；夹具全在 `tmp_path` 下。
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
RECON_PATH = REPO / "scripts" / "recon_b.py"

#: 三把 sha 各司其职：签盖的那把（正文 sha）/ 被审那份稿的字节 sha / 另一份 pending 的键。
ART_REG = "a1" * 32
ART_PEND = "b2" * 32
OBJ_REG = "c3" * 32
OBJ_PEND = "d4" * 32

_AT = ("2026-11-21T10:00:00+08:00", "2026-11-21T10:01:00+08:00",
       "2026-11-21T10:02:00+08:00")


def _load_recon():
    """按文件路径加载被判的脚本（`scripts/` 不是包，也不许从 `temp/` 载）。"""
    spec = importlib.util.spec_from_file_location("reconfix_recon_b", RECON_PATH)
    assert spec and spec.loader, f"加载不了 {RECON_PATH} ⇒ 判据失去对象（不是通过）"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_json(path: pathlib.Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def _passes(vids: list[str], *, proof_sha: str, object_sha: str, object_path: str) -> list[dict]:
    return [{"verification_id": vid, "review_call": "c0ffee1", "review_pass": i,
             "at": _AT[i - 1], "verdict": "成立", "axis": "clean",
             "proof_sha256": proof_sha, "object_sha256": object_sha,
             "object_path": object_path, "round": i}
            for i, vid in enumerate(vids, 1)]


def _registered_sign(vids: list[str] | None = None) -> dict:
    vids = vids or ["v-000001", "v-000002", "v-000003"]
    return {"schema": "vsign/1", "artifact_sha": ART_REG,
            "artifact_path": "reports/f-proof-000042.md",
            "statement_id": "000042",
            "ledger": f"verifications/000042.jsonl#{vids[-1]}",
            "need": 3, "count": 3, "streak": 3, "verdict": "成立", "legacy": False,
            "at": _AT[-1],
            "passes": _passes(vids, proof_sha=ART_REG, object_sha=OBJ_REG,
                              object_path="reports/f-proof-000042.md")}


def _pending_sign(vids: list[str] | None = None) -> dict:
    vids = vids or ["u-000001", "u-000002", "u-000003"]
    return {"schema": "vsign/1", "artifact_sha": ART_PEND,
            "artifact_path": "reports/f-proof-000043.md",
            "statement_id": "",
            "ledger": f"verifications/pending/{OBJ_PEND}.jsonl#{vids[-1]}",
            "need": 3, "count": 3, "streak": 3, "verdict": "成立", "legacy": False,
            "at": _AT[-1],
            "passes": _passes(vids, proof_sha=ART_PEND, object_sha=OBJ_PEND,
                              object_path="reports/f-proof-000043.md")}


def _rows(vids: list[str], *, proof_sha: str, stmt: str = "") -> list[dict]:
    return [{"verification_id": vid, "stmt_id": stmt, "statement_id": stmt,
             "proof_sha256": proof_sha, "review_pass": i, "verdict": "成立",
             "at": _AT[i - 1], "object_sha256": ""} for i, vid in enumerate(vids, 1)]


def _workspace(tmp_path: pathlib.Path, *, sign: dict, ledger: pathlib.Path | None,
               ledger_rows: list[dict] | None, statement_id: str = "",
               statement_proof: str = "") -> pathlib.Path:
    """造一个最小工作区：`out/vsigns/<sha>.json` + 可选的一本台账 + 一行 statements。"""
    root = tmp_path / "ws"
    sha = sign["artifact_sha"]
    _write_json(root / "out" / "vsigns" / f"{sha}.json", sign)
    _write_json(root / "out" / "vsigns" / "issued.json",
                {"signs": [{"artifact_sha": sha, "at": sign["at"]}]})
    if ledger is not None and ledger_rows is not None:
        _write_jsonl(root / ledger, ledger_rows)
    rows = []
    if statement_id:
        rows.append({"stmt_id": statement_id, "proof_sha256": statement_proof})
    _write_json(root / "data" / "statements.json", {"rows": rows})
    return root


def _item4(root: pathlib.Path, mod) -> dict:
    """跑 ④ 项：只喂它真正用到的那一格（statements 行）。"""
    rows = json.loads((root / "data" / "statements.json").read_text(encoding="utf-8"))["rows"]
    ctx = {"root": root, "T": lambda name: rows if name == "statements" else []}
    return mod.item4_signs(ctx)


def _only(item: dict) -> dict:
    return item["metrics"]["signs"][0]


# ------------------------------------------------------------------ a


def test_a_a_registered_sign_points_at_its_statement_ledger(tmp_path):
    """在册签（v-…，object_sha256 非空）⇒ 回指 `verifications/<命题号>.jsonl`，不判缺失。"""
    mod = _load_recon()
    sign = _registered_sign()
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path("verifications/000042.jsonl"),
                      ledger_rows=_rows(["v-000001", "v-000002", "v-000003"], proof_sha=ART_REG),
                      statement_id="000042", statement_proof=ART_REG)
    item = _item4(root, mod)
    rec = _only(item)
    assert rec["problems"] == [], rec["problems"]
    assert item["metrics"]["valid"] == 1 and item["metrics"]["invalid"] == 0
    assert item["metrics"]["unchecked"] == 0
    # 正控：它现在按 `verifications/<命题号>.jsonl` 核（不是 pending）
    assert rec["backing"]["kind"] == "registered"
    assert rec["backing"]["path"] == "verifications/000042.jsonl", rec["backing"]
    assert rec["backing"]["rows_for_this_sign"] == 3, rec["backing"]
    rendered = "\n".join(item["lines"])
    assert "回指在册签 → verifications/000042.jsonl" in rendered, rendered
    assert "不在盘上" not in rendered, rendered


# ------------------------------------------------------------------ b


def test_b_an_unregistered_sign_still_points_at_its_pending_ledger(tmp_path):
    """未在册签（u-…）⇒ 仍按 `verifications/pending/<object_sha256>.jsonl` 回指（正控）。"""
    mod = _load_recon()
    sign = _pending_sign()
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path(f"verifications/pending/{OBJ_PEND}.jsonl"),
                      ledger_rows=_rows(["u-000001", "u-000002", "u-000003"], proof_sha=ART_PEND))
    item = _item4(root, mod)
    rec = _only(item)
    assert rec["problems"] == [], rec["problems"]
    assert item["metrics"]["valid"] == 1 and item["metrics"]["invalid"] == 0
    assert rec["backing"]["kind"] == "pending"
    assert rec["backing"]["path"] == f"verifications/pending/{OBJ_PEND}.jsonl", rec["backing"]
    assert rec["backing"]["rows_for_this_sign"] == 3, rec["backing"]


# ------------------------------------------------------------------ c


def test_c1_a_missing_registered_ledger_is_still_a_defect(tmp_path):
    """在册签的台账不在盘上 ⇒ 仍判缺失（分流没有把闸关掉）。"""
    mod = _load_recon()
    root = _workspace(tmp_path, sign=_registered_sign(), ledger=None, ledger_rows=None,
                      statement_id="000042", statement_proof=ART_REG)
    item = _item4(root, mod)
    rec = _only(item)
    assert item["metrics"]["invalid"] == 1 and item["metrics"]["valid"] == 0
    text = "；".join(rec["problems"])
    assert "verifications/000042.jsonl" in text and "不在盘上" in text, text


def test_c2_a_missing_pending_ledger_is_still_a_defect(tmp_path):
    """未在册签的台账不在盘上 ⇒ 仍判缺失（这一支的正控没有丢）。"""
    mod = _load_recon()
    root = _workspace(tmp_path, sign=_pending_sign(), ledger=None, ledger_rows=None)
    item = _item4(root, mod)
    rec = _only(item)
    assert item["metrics"]["invalid"] == 1 and item["metrics"]["valid"] == 0
    text = "；".join(rec["problems"])
    assert f"verifications/pending/{OBJ_PEND}.jsonl" in text and "不在盘上" in text, text


def test_c3_only_two_of_three_passes_backed_is_a_defect(tmp_path):
    """台账在盘上但只回指得上 2/3 票 ⇒ 仍判缺失（「行数对」这一核没有松）。"""
    mod = _load_recon()
    root = _workspace(tmp_path, sign=_registered_sign(),
                      ledger=pathlib.Path("verifications/000042.jsonl"),
                      ledger_rows=_rows(["v-000001", "v-000002"], proof_sha=ART_REG),
                      statement_id="000042", statement_proof=ART_REG)
    item = _item4(root, mod)
    rec = _only(item)
    assert item["metrics"]["invalid"] == 1 and item["metrics"]["valid"] == 0
    text = "；".join(rec["problems"])
    assert "只对上 2/3 票" in text, text
    assert "v-000003 不在 verifications/000042.jsonl 的行里" in text, text


# ------------------------------------------------------------------ d


def test_d_without_the_split_a_registered_sign_is_read_as_missing(tmp_path, monkeypatch):
    """反真空：把分流打桩回旧口径（恒 pending）⇒ a 必红，且红成「回指缺失」。"""
    mod = _load_recon()
    # 旧的判据就是「无论哪种签，都去 pending/<object_sha256>.jsonl 找」。
    monkeypatch.setattr(mod, "sign_kind_of", lambda _vid: mod.PENDING)
    sign = _registered_sign()
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path("verifications/000042.jsonl"),
                      ledger_rows=_rows(["v-000001", "v-000002", "v-000003"], proof_sha=ART_REG),
                      statement_id="000042", statement_proof=ART_REG)
    item = _item4(root, mod)
    rec = _only(item)
    assert item["metrics"]["invalid"] == 1, "打桩回旧口径之后 a 仍然绿 ⇒ a 的绿不是分流给的"
    text = "；".join(rec["problems"])
    assert f"verifications/pending/{OBJ_REG}.jsonl" in text, text
    assert "不在盘上" in text, text


# ------------------------------------------------------------------ e


def test_e_an_undecidable_type_is_unchecked_not_ok_and_not_missing(tmp_path):
    """分不清类型（号不是 v-/u-）⇒ unchecked：不算合格、不算缺失、state 记 unknown。"""
    mod = _load_recon()
    sign = _registered_sign(vids=["x-000001", "x-000002", "x-000003"])
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path("verifications/000042.jsonl"),
                      ledger_rows=_rows(["v-000001", "v-000002", "v-000003"], proof_sha=ART_REG),
                      statement_id="000042", statement_proof=ART_REG)
    item = _item4(root, mod)
    assert item["metrics"]["valid"] == 0 and item["metrics"]["invalid"] == 0
    assert item["metrics"]["unchecked"] == 1, item["metrics"]
    assert item["state"] == "unknown", item["state"]
    rec = _only(item)
    assert rec["problems"] == [], "分不清类型不许折成「缺失」"
    assert rec["backing"]["unchecked"], rec["backing"]
    assert "unchecked" in rec["backing"]["unchecked"], rec["backing"]
    assert "不在盘上" not in "\n".join(item["lines"])


def test_e2_mixed_namespaces_in_one_sign_are_undecidable(tmp_path):
    """同一签的 3 票分属两本台账（形态混装）⇒ 也落 unchecked（不猜其中一本）。"""
    mod = _load_recon()
    sign = _registered_sign(vids=["v-000001", "u-000002", "v-000003"])
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path("verifications/000042.jsonl"),
                      ledger_rows=_rows(["v-000001", "v-000002", "v-000003"], proof_sha=ART_REG),
                      statement_id="000042", statement_proof=ART_REG)
    item = _item4(root, mod)
    assert item["metrics"]["unchecked"] == 1, item["metrics"]
    assert item["metrics"]["invalid"] == 0 and item["metrics"]["valid"] == 0


# ------------------------------------------------------------------ f


def test_f_a_decoy_pending_ledger_does_not_capture_a_registered_sign(tmp_path):
    """在册签旁边摆一份 pending 干扰本 ⇒ 回指仍只认在册那一本（不跨本串读）。"""
    mod = _load_recon()
    sign = _registered_sign()
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path("verifications/000042.jsonl"),
                      ledger_rows=_rows(["v-000001", "v-000002", "v-000003"], proof_sha=ART_REG),
                      statement_id="000042", statement_proof=ART_REG)
    # 干扰本：同名 object sha 的 pending 台账，行上 proof_sha256 全不对（串过去就会红）。
    _write_jsonl(root / "verifications" / "pending" / f"{OBJ_REG}.jsonl",
                 _rows(["v-000001", "v-000002", "v-000003"], proof_sha="9" * 64))
    item = _item4(root, mod)
    rec = _only(item)
    assert rec["problems"] == [], rec["problems"]
    assert rec["backing"]["path"] == "verifications/000042.jsonl", rec["backing"]


# ------------------------------------------------------------------ g


def test_g_a_claimed_pending_sign_is_not_rerouted_to_the_statement_ledger(tmp_path):
    """命题已在册、签却是未在册时发的（u-…）⇒ 仍按 pending 回指（真机 lp-ball-15 的形态）。

    这一条是另一侧的口径陷阱：若按「命题现在在不在册」分流，就会去
    `verifications/000043.jsonl` 找，而那份台账根本不存在（认领不搬家，见
    `verifications._claimed_pending_rows`）⇒ 3 个合格签会被整批读成「回指缺失」。
    """
    mod = _load_recon()
    sign = _pending_sign()
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path(f"verifications/pending/{OBJ_PEND}.jsonl"),
                      ledger_rows=_rows(["u-000001", "u-000002", "u-000003"], proof_sha=ART_PEND),
                      statement_id="000043", statement_proof=ART_PEND)
    # 故意不造 verifications/000043.jsonl：它本就不该存在（这一签是 pending 发的）。
    assert not (root / "verifications" / "000043.jsonl").exists()
    item = _item4(root, mod)
    rec = _only(item)
    assert rec["problems"] == [], rec["problems"]
    assert item["metrics"]["valid"] == 1 and item["metrics"]["invalid"] == 0
    assert rec["backing"]["kind"] == "pending", rec["backing"]
    assert rec["backing"]["path"] == f"verifications/pending/{OBJ_PEND}.jsonl", rec["backing"]


def test_h_routing_by_statement_registration_would_break_g(tmp_path, monkeypatch):
    """反真空（另一侧）：把分流打桩成「按命题在不在册」⇒ g 必红成「回指缺失」。"""
    mod = _load_recon()
    monkeypatch.setattr(mod, "sign_backing_target",
                        lambda _sign, _passes, _by_proof, _kind: ("verifications/000043.jsonl", ""))
    sign = _pending_sign()
    root = _workspace(tmp_path, sign=sign,
                      ledger=pathlib.Path(f"verifications/pending/{OBJ_PEND}.jsonl"),
                      ledger_rows=_rows(["u-000001", "u-000002", "u-000003"], proof_sha=ART_PEND),
                      statement_id="000043", statement_proof=ART_PEND)
    item = _item4(root, mod)
    rec = _only(item)
    assert item["metrics"]["invalid"] == 1, "按命题在册与否分流也绿 ⇒ g 的绿不区分口径"
    assert "不在盘上" in "；".join(rec["problems"]), rec["problems"]
