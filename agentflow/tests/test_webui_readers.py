# -- coding: utf-8 --
"""六个只读面的判据（`draft/78 §2.1` 的 B 线判据；`draft/73` §2.3）。

## 每一面两半（`draft/73` §2.3 的判据口径）

- 正控：夹具造出真数据（`tests/conftest.py` 的 `make_artifacts_sample`，
  裁定 J2/K2 的样本）⇒ 读数出现在结果里，且字段名逐字对得上；
- 负控（这一组最重要）：数据源不可读 ⇒ 该面 `tri="unreadable"` + `reason` 非空；
  空工作区 ⇒ `tri="not_applicable"` + 一句"还没写过"。不许折成 `0` / `[]` / `false`
  （"没查成 vs 查到 0"这条线是本仓库最贵的纪律）。

## 三态词表

`computed` / `unreadable` / `not_applicable`（裁定 N1：与「交付说明」那一格的
`ok`/`missing`/`unknown` 不许互相顶替）。本文件同时钉住"哪一栏用哪一套"。

## 注册表

`readers.CHECKED_TYPES` / `UNCHECKED_TYPES` 是契约判据 C 的两份登记，它们必须与
`type_decls()` 自洽：一个接口要么在受核对名单里、要么在欠账名单里（且欠账那一边
不许真读出键来）。这一半在本文件里自己先核一遍，别等 A 线的判据来报。
"""

from __future__ import annotations

import json
import pathlib
import re

import conftest
import pytest

from agentflow import sessions as SS
from agentflow import userio as U
from agentflow.webui import readers as R
from agentflow.webui import routes
from agentflow.webui.state import _read_report

#: 夹具工作区里那一段会话的号（与 `conftest.make_artifacts_sample` 的默认值一致）。
SID = "fix-sid"

#: 每个接口的字段名（来自 `readers.type_decls()` 那一份声明 —— 不在这里另抄一遍）。
FIELDS = R.ts_fields()


# ====================================================================== 1 快照面
def test_the_state_face_keeps_the_snapshot_keys_verbatim(
        artifacts_ws: pathlib.Path) -> None:
    """正控（快照）：`state_face()` 的 `snapshot` 就是 `snapshot()` 的返回值，键一字不改。

    为什么钉这个：`StateSnapshot` 的键是旧壳渲染与 `tests/test_webui.py` 共用的公开面，
    外挂一层三态头不许顺手把里面的键改名或包一层。
    """
    from agentflow.webui import snapshot

    got = R.state_face(artifacts_ws)
    live = snapshot(artifacts_ws)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["snapshot"] == live, "外挂一层不许改快照本身"
    assert set(got["snapshot"]) == set(live)
    assert "pending_questions" in got["snapshot"]


def test_the_state_face_reports_unreadable_when_it_could_not_read(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话文件读不出来 ⇒ `unreadable`（不是"没有会话"）。

    做法：把这个会话文件换成一个同名的目录（`read_session` 会以 `OSError` 一族
    报出"读不出来"）⇒ 快照把它收进 `problems`，这一面必须跟着变红。
    """
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="t")
    real = (root / "sessions" / "t.jsonl").read_bytes()
    (root / "sessions" / "t.jsonl").unlink()
    (root / "sessions" / "t.jsonl").mkdir()                # 同名目录 ⇒ 读不出来
    got = R.state_face(root)
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert got["reason"], "变红了却没说为什么"
    # 撤回去 ⇒ 又绿（证明红的成因就是那一处）
    (root / "sessions" / "t.jsonl").rmdir()
    (root / "sessions" / "t.jsonl").write_bytes(real)
    assert R.state_face(root)["tri"] == R.TRI_COMPUTED


# ====================================================================== 2 一趟详情
def test_run_view_reads_runs_report_and_checkpoint(artifacts_ws: pathlib.Path) -> None:
    """正控（一趟详情）：`runs` / `report` / `checkpoint` 三栏都有真读数。

    检查点的 9 个键与 `spend` 的 5 个键逐字钉住（`agent_loop.save_run_checkpoint` +
    `llmseam.SeamSpend.to_dict`）。
    """
    got = R.run_view(artifacts_ws, SID)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["sid"] == SID and got["path"].endswith(f"{SID}.jsonl")
    assert len(got["runs"]) == 1, got["runs"]
    run = got["runs"][0]
    assert set(run) == set(R.RUN_ROW_KEYS), (sorted(run), sorted(R.RUN_ROW_KEYS))
    assert run["stop_reason"] == "final" and run["steps"] == 1
    assert got["report"]["status"] == "ok", got["report"]
    assert "夹具样本交付说明" in got["report"]["text"]
    ck = got["checkpoint"]
    assert ck is not None, got["checkpoint_reason"]
    assert set(ck) == {"role", "sid", "task", "fingerprint", "step", "stop_reason",
                       "waiting_for", "spend", "at"}, sorted(ck)
    assert set(ck["spend"]) == {"calls", "tokens_in", "tokens_out", "usd",
                                "unknown_usd_calls"}, sorted(ck["spend"])
    assert ck["step"] == 3 and ck["stop_reason"] == "waiting_for_user"
    assert ck["spend"]["usd"] == 0.25
    assert SID in got["checkpoint_reason"]


def test_run_view_says_missing_session_is_unreadable(tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话文件不在盘上 ⇒ `unreadable`，而不是"这一趟 0 条事件"。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.run_view(root, "nope")
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert "不在盘上" in got["reason"], got
    assert got["runs"] == [] and got["checkpoint"] is None


def test_run_view_says_missing_checkpoint_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：会话在、但这一趟还没落检查点 ⇒ `checkpoint` 是 `None` + 一句理由。

    "还没落检查点"不是"检查点是空的"：读数里必须看得出是哪一档。
    """
    root = tmp_path / "ws"
    root.mkdir()
    SS.append(root, {"kind": "agent_run_start", "role": "M", "task": "x"}, sid="t")
    got = R.run_view(root, "t")
    assert got["tri"] == R.TRI_COMPUTED, got
    assert got["checkpoint"] is None
    assert "还没落过检查点" in got["checkpoint_reason"], got["checkpoint_reason"]


def test_run_view_reports_a_corrupt_checkpoint_as_unreadable(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：检查点文件在、但内容不是 JSON ⇒ `unreadable` 并点名它。"""
    p = artifacts_ws / "runs" / f"agent-M-{SID}.json"
    good = p.read_text(encoding="utf-8")
    p.write_text("{这不是 JSON\n", encoding="utf-8")
    try:
        got = R.run_view(artifacts_ws, SID)
        assert got["tri"] == R.TRI_UNREADABLE, got
        assert "检查点" in got["reason"], got["reason"]
    finally:
        p.write_text(good, encoding="utf-8")
    assert R.run_view(artifacts_ws, SID)["tri"] == R.TRI_COMPUTED


# ====================================================================== 3 证据链
def test_evidence_chain_reads_every_column(artifacts_ws: pathlib.Path) -> None:
    """正控（证据链）：七栏都在，且验证台账那一栏读到了夹具造的那一行（裁定 K2）。"""
    got = R.evidence_chain(artifacts_ws)
    assert got["tri"] == R.TRI_COMPUTED, got
    for key in ("statements", "conjectures", "experiments", "review_findings",
                "relations", "verifications", "secretary"):
        assert key in got, key
        assert f"{key}_tri" in got, key
    assert len(got["verifications"]) == 1, got["verifications"]
    row = got["verifications"][0]
    assert row["verdict"] == "成立", row
    assert row["proof_sha256"] and row["statement_id"] == "0001"
    assert set(row) == set(FIELDS["VerificationRow"]), sorted(row)
    assert got["secretary"], "秘书台账那一栏没读到夹具造的两条"
    assert got["secretary"][0]["role"] == "M"


def test_evidence_chain_reports_unreadable_when_a_table_is_broken(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：一张表读不出来 ⇒ 整面 `unreadable`，且那一栏也标红。

    "少了一栏"与"那一栏是空的"在界面上必须分得开：所以整面变红之外，那一栏自己的
    `<栏>_tri` 也要是 `unreadable`。
    """
    from agentflow.schema import TABLES

    rel = str(TABLES["statements"]["file"])
    p = artifacts_ws / "data" / rel
    good = p.read_bytes()
    p.write_text("{这不是 JSON\n", encoding="utf-8")
    got = R.evidence_chain(artifacts_ws)
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert got["statements_tri"] == R.TRI_UNREADABLE, got["statements_tri"]
    assert got["statements"] == []
    assert "statements" in got["reason"], got["reason"]
    # 别的栏照常给行（局部坏掉不该把整份读数清空）
    assert got["verifications"], "一栏坏了不该把别的栏也清空"
    p.write_bytes(good)
    assert R.evidence_chain(artifacts_ws)["tri"] == R.TRI_COMPUTED


def test_evidence_chain_on_an_empty_workspace_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：空工作区 ⇒ `not_applicable` + "一张表都没落过盘"，不是 0。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.evidence_chain(root)
    assert got["tri"] == R.TRI_NOT_APPLICABLE, got
    assert got["statements"] == [] and got["statements_tri"] == R.TRI_NOT_APPLICABLE
    assert "一张都没落过盘" in got["reason"], got["reason"]


# ====================================================================== 4 产物面
def test_artifacts_face_reads_ledger_handoffs_checks_style_products_tasks(
        artifacts_ws: pathlib.Path) -> None:
    """正控（产物面）：七栏都读到夹具造的东西，且台账逐行核对是 `ok`。"""
    got = R.artifacts_face(artifacts_ws)
    assert got["tri"] == R.TRI_COMPUTED, got
    assert len(got["ledger"]) == 5, got["ledger"]
    assert set(got["ledger"][0]) == set(FIELDS["ArtifactRow"]), sorted(got["ledger"][0])
    assert [r["status"] for r in got["ledger_verify"]] == ["ok"] * 5, got["ledger_verify"]
    assert set(got["ledger_verify"][0]) == set(FIELDS["LedgerVerifyRow"])
    assert len(got["handoffs"]) == 1, got["handoffs"]
    # 交接行的必填 14 栏都在（`revises`/`kind`/`ref_problems` 是"有就带上"的三栏）
    required = tuple(f for f in FIELDS["HandoffRow"]
                     if f not in ("revises", "kind", "ref_problems"))
    assert set(got["handoffs"][0]) >= set(required), sorted(got["handoffs"][0])
    assert [c["id"] for c in got["checks"]] == ["C1", "C2", "C3"], got["checks"]
    assert got["style"]["sections"] == list(conftest.REPORT_STYLE_SECTIONS)
    assert len(got["secretary"]) == 2, got["secretary"]
    assert got["run_dir"].endswith("run-1"), got["run_dir"]
    assert len(got["products"]) == 6, got["products"]
    assert all(p["exists"] for p in got["products"]), got["products"]
    assert got["tasks"] and got["tasks"][0]["task_id"] == "t-0001"


def test_the_ledger_verify_notices_a_changed_file(artifacts_ws: pathlib.Path) -> None:
    """负控（台账核对）：台账钉的文件被改过 ⇒ 那一行的 `status` 是 `changed`（不是 `ok`）。"""
    got = R.artifacts_face(artifacts_ws)
    assert all(r["status"] == "ok" for r in got["ledger_verify"])
    target = artifacts_ws / "out" / "experiments" / "e-0001.log"
    target.write_text("夹具样本：这一行是后来改的。\n", encoding="utf-8")
    got2 = R.artifacts_face(artifacts_ws)
    statuses = {r["path"]: r["status"] for r in got2["ledger_verify"]}
    assert statuses["out/experiments/e-0001.log"] == "changed", statuses
    # 删掉 ⇒ `missing`（三档不同处置，不许折成一个"不 ok"）
    target.unlink()
    got3 = R.artifacts_face(artifacts_ws)
    statuses3 = {r["path"]: r["status"] for r in got3["ledger_verify"]}
    assert statuses3["out/experiments/e-0001.log"] == "missing", statuses3


def test_artifacts_face_on_an_empty_workspace_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """负控（三态）：空工作区 ⇒ `not_applicable`，七栏各带自己的 `tri`，不是 0。"""
    root = tmp_path / "ws"
    root.mkdir()
    got = R.artifacts_face(root)
    assert got["tri"] == R.TRI_NOT_APPLICABLE, got
    for key in ("ledger_tri", "handoffs_tri", "checks_tri", "style_tri",
                "secretary_tri", "products_tri", "tasks_tri"):
        assert got[key] == R.TRI_NOT_APPLICABLE, (key, got[key])
    assert got["ledger"] == [] and got["products"] and not any(
        p["exists"] for p in got["products"])
    assert "本机还没有跑过" in got["products_reason"], got["products_reason"]


def test_artifacts_face_on_a_broken_ledger_is_unreadable(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：台账有一行读不出来 ⇒ 整面 `unreadable` + 点名那一栏。"""
    p = artifacts_ws / "ARTIFACTS.jsonl"
    good = p.read_text(encoding="utf-8")
    p.write_text(good + "{这不是 JSON\n", encoding="utf-8")
    try:
        got = R.artifacts_face(artifacts_ws)
        assert got["tri"] == R.TRI_UNREADABLE, got
        assert got["ledger_tri"] == R.TRI_UNREADABLE
        assert "读不出来" in got["reason"], got["reason"]
    finally:
        p.write_text(good, encoding="utf-8")
    assert R.artifacts_face(artifacts_ws)["tri"] == R.TRI_COMPUTED


def test_run_products_marks_a_missing_product_not_zero(
        artifacts_ws: pathlib.Path) -> None:
    """负控（六件产物）：少一件 ⇒ 那一件 `exists=false` + `tri=not_applicable`，
    `bytes`/`lines` 是 `None`（不是 0 —— 那是"没读到"，不是"读到了 0 字节"）。"""
    (artifacts_ws / "out" / "run-1" / "claims.json").unlink()
    got = R.run_products(artifacts_ws)
    claims = next(p for p in got["products"] if p["name"] == "claims.json")
    assert claims["exists"] is False and claims["tri"] == R.TRI_NOT_APPLICABLE
    assert claims["bytes"] is None and claims["lines"] is None
    # `.json` 的 lines 按设计是 None（只有 .jsonl 能数行），那不是"0 行"
    report = next(p for p in got["products"] if p["name"] == "report.md")
    assert report["exists"] and report["lines"] is None and report["bytes"]
    # jsonl 那一件数得出真行数
    tr = next(p for p in got["products"] if p["name"] == "model-transcript.jsonl")
    assert tr["lines"] == 2, tr


# ====================================================================== 5 收工门
def test_acceptance_face_reads_the_five_criteria_and_five_aux(
        artifacts_ws: pathlib.Path) -> None:
    """正控（收工门）：5 条判据 + 5 条辅助读数的键名逐字来自 `reviewaccept`。"""
    from agentflow.reviewaccept import AUXILIARY_SIGNALS, CRITERIA

    got = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws))
    assert got["tri"] == R.TRI_COMPUTED, got
    assert set(got["criteria"]) == {k for k, _d in CRITERIA}, got["criteria"]
    assert set(got["auxiliary"]) == {k for k, _d in AUXILIARY_SIGNALS}, got["auxiliary"]
    assert set(got["details"]) == {k for k, _d in CRITERIA}
    assert got["failed"] == sorted(k for k, v in got["criteria"].items() if v != "pass")
    assert got["auxiliary_note"], "辅助读数那句『只供人看』必须带回来"


def test_acceptance_face_leaves_the_cost_gate_unknown_without_a_cap(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：不给我 `cap_usd` ⇒「在成本上限内」那一格是 `unknown`。

    这一档是 `draft/75 §2.10` 第③行点名要的：没给上限时那一格是"没查成"，
    不是"在预算内"。判据同时要求 `reason` 把它点名。
    """
    got = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=None)
    assert got["criteria"]["within_cost_cap"] == "unknown", got["criteria"]
    assert "within_cost_cap" in got["reason"], got["reason"]
    # 给了上限 ⇒ 那一格不再因为"没给上限"而 unknown（它可能 fail/pass，那是另一回事）
    got2 = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=1.0)
    assert got2["criteria"]["within_cost_cap"] != "unknown", got2["criteria"]


def test_acceptance_face_says_unknown_branch_without_a_sid(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：不给我 `sid` ⇒ `triage_branch_recorded` 是 `unknown`。

    这条与 `tests/test_sid_scoped_questions.py` 是同一件事的两端：那边钉的是
    "带 sid 就看得见"，这边钉的是"不带 sid 时是没查成，不是通过"。
    """
    got = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=1.0)
    assert got["criteria"]["triage_branch_recorded"] == "unknown", got["criteria"]
    assert "triage_branch_recorded" in got["reason"], got["reason"]
    got2 = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws), cap_usd=1.0,
                             sid=SID)
    assert got2["criteria"]["triage_branch_recorded"] == "fail", got2["criteria"]
    assert "没被回答" in got2["details"]["triage_branch_recorded"], got2["details"]


# ====================================================================== 6 本机
def test_machine_face_keeps_the_toolchain_keys_and_never_shows_a_key(
        artifacts_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch,
        tmp_path: pathlib.Path) -> None:
    """正控（本机）：工具链那些键逐字保留；设置里的 key 只给"配没配"与掩码。

    判据逐字符断言一个真 key 不在读数里（裁定 E1：key 只写不读）。
    """
    secret = "sk-真key-绝不许出现在读数里-0123456789"
    settings_file = tmp_path / "settings-real.json"
    settings_file.write_text(json.dumps({
        "toolchain": {"lean_bin": "/opt/lean", "mathlib_root": "/opt/mathlib"},
        "model": {"api_key": secret, "base_url": "http://127.0.0.1:9", "name": "m1"},
        "workspace": {"projects_dir": "/tmp/projects"},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("AGENTFLOW_SETTINGS", str(settings_file))
    got = R.machine_face(artifacts_ws)
    from agentflow.toolchain import toolchain_report

    assert set(got) >= set(toolchain_report()), (sorted(got), sorted(toolchain_report()))
    assert set(got["provers"]) == {"checked", "available", "available_names",
                                   "probe_errors", "reason", "looked_in", "sources"}
    assert got["settings_tri"] == R.TRI_COMPUTED, got
    assert got["settings"]["exists"] is True
    assert got["settings"]["model"]["api_key"] == "***", got["settings"]["model"]
    assert got["settings"]["model"]["configured"] is True
    assert got["settings"]["model"]["base_url"] == "http://127.0.0.1:9"
    assert got["settings"]["toolchain"]["lean_bin"] == "/opt/lean"
    assert secret not in json.dumps(got, ensure_ascii=False), \
        "真 key 出现在读数里了（裁定 E1：key 只写不读）"


def test_machine_face_without_a_settings_file_says_not_applicable(
        artifacts_ws: pathlib.Path) -> None:
    """负控（三态）：设置文件不在盘上 ⇒ 那一段 `not_applicable` + 理由。

    注意它不让整面变红：工具链读得出来就是读得出来；"一部分没配"不等于"整面没查成"。
    """
    got = R.machine_face(artifacts_ws)
    assert got["settings_tri"] == R.TRI_NOT_APPLICABLE, got
    assert "不在盘上" in got["settings_reason"], got["settings_reason"]
    assert got["settings"]["exists"] is False
    assert got["settings"]["model"]["api_key"] == "", got["settings"]["model"]
    assert got["settings"]["model"]["configured"] is False
    assert got["tri"] == R.TRI_COMPUTED, got


def test_machine_face_reports_an_unfinished_probe_as_unreadable(
        artifacts_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（三态）：探测没跑完（`provers.checked=false`）⇒ 整面 `unreadable`。

    这一档与 `available == []`（探过了、一个都没找到）必须分得开：前者是"没查成"。
    """
    from agentflow import toolchain as TC

    real = TC.toolchain_report

    def fake(env=None):  # noqa: ANN001 - 与真签名同形
        got = dict(real(env))
        got["provers"] = {"checked": False, "available": [], "available_names": [],
                          "probe_errors": {"lean": "探针超时"}, "reason": "探针没跑完",
                          "looked_in": [], "sources": {}}
        return got

    monkeypatch.setattr(TC, "toolchain_report", fake)
    got = R.machine_face(artifacts_ws)
    assert got["tri"] == R.TRI_UNREADABLE, got
    assert "checked=false" in got["reason"], got["reason"]


# ====================================================================== 注册表与接缝
def test_the_two_registries_agree_with_type_decls() -> None:
    """正控（注册表）：`CHECKED_TYPES` / `UNCHECKED_TYPES` 与 `type_decls()` 自洽。

    三条：受核对名单里的接口真的被声明了；欠账名单里的接口也被声明了；两份名单不相交。
    A 线的契约判据 C 拿这两份名单去比对键集合，所以它们自己先不许自相矛盾。
    """
    declared = set(re.findall(r"^export interface ([A-Za-z_][A-Za-z0-9_]*)",
                              R.type_decls(), re.M))
    assert declared, "type_decls() 一个接口都没吐 ⇒ 生成器那一段是空的"
    missing = [n for n in R.CHECKED_TYPES if n not in declared]
    assert not missing, f"受核对名单里有没声明的接口：{missing}"
    missing2 = [n for n in R.UNCHECKED_TYPES if n not in declared]
    assert not missing2, f"欠账名单里有没声明的接口：{missing2}"
    both = sorted(set(R.CHECKED_TYPES) & set(R.UNCHECKED_TYPES))
    assert not both, f"同一个接口不许同时在两份登记里：{both}"
    for name, why in R.UNCHECKED_TYPES.items():
        assert why.strip(), f"{name} 的欠账没有写理由"


def test_the_checked_types_really_have_readings(artifacts_ws: pathlib.Path) -> None:
    """正控（受核对名单不是空的）：名单里每个接口都能在夹具上读出键集合。

    这条是给 A 线的契约判据 C 打前站的：它失败时说明"登记了一件读不出来的事"，
    而那种失败在 A 那边会以"夹具没造出这些读数"的形态出现 —— 在这里先说清楚。
    """
    got: dict[str, set[str]] = {}
    run = R.run_view(artifacts_ws, SID)
    got["RunView"] = set(run)
    got["ReportReadingView"] = set(run["report"])
    if run["checkpoint"]:
        got["CheckpointView"] = set(run["checkpoint"])
        got["CheckpointSpendView"] = set(run["checkpoint"]["spend"])
    art = R.artifacts_face(artifacts_ws)
    got["ArtifactsView"] = set(art)
    for name, rows in (("ArtifactRow", art["ledger"]),
                       ("LedgerVerifyRow", art["ledger_verify"]),
                       ("HandoffRow", art["handoffs"]),
                       ("SecretaryDecision", art["secretary"]),
                       ("AcceptanceCheck", art["checks"]),
                       ("TaskRow", art["tasks"]),
                       ("RunProduct", art["products"])):
        assert rows, f"夹具没造出 {name} 的行"
        got[name] = set(rows[0])
    got["ReportStyle"] = set(art["style"])
    ev = R.evidence_chain(artifacts_ws)
    got["EvidenceView"] = set(ev)
    got["VerificationRow"] = set(ev["verifications"][0])
    acc = R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws))
    got["AcceptanceView"] = set(acc)
    mach = R.machine_face(artifacts_ws)
    got["MachineView"] = set(mach)
    got["SettingsReading"] = set(mach["settings"])
    missing = [n for n in R.CHECKED_TYPES if n not in got]
    assert not missing, f"受核对名单里这些接口在夹具上没有读数：{missing}（登记该改）"


def test_the_route_table_hands_our_endpoints_to_our_handlers() -> None:
    """正控（接缝）：六个面的表项真的进了总表，且 `handler_for` 取得到处理器。

    绑定/猴补丁都不需要：`routes.handler_for(name)` 直接读子表模块的 `HANDLERS`
    字典（A 线落的那条接缝）。这条是"我这一半接没接上"的机器读数。
    """
    ours = {name for _m, _p, name in R.ROUTES}
    assert ours == {"handle_run_view", "handle_evidence", "handle_artifacts",
                    "handle_acceptance", "handle_machine", "handle_stream"}, ours
    for _m, path, name in R.ROUTES:
        assert path in routes.patterns(), f"{path} 没进总表"
        assert routes.handler_for(name) is not None, f"{name} 没有实现"
        assert callable(routes.handler_for(name)), name
    assert ("GET", "/api/stream", "handle_stream") in routes.ROUTES
    assert R.PENDING_ENDPOINTS == {}, "B1/B3 之后不该还有 PENDING 的端点"


def test_the_run_row_keys_match_what_sessions_computes(artifacts_ws: pathlib.Path) -> None:
    """反真空（两份实现的护栏）：`readers` 与 `sessions` 的趟次键集合逐字相同。

    `readers.run_view` 走 `sessions.runs_in_session`；而 `webui.state._scan` 另有一份
    同形实现（A 线）。这条断言钉住"我这一份与 `RunRow` 的 20 个键一致"——哪天
    `_scan` 改了键而我这边的（或 `RunRow` 的）没跟上，契约判据 C 会红，而这里
    先说清是"两份实现漂移"还是"夹具没造出来"。
    """
    run = R.run_view(artifacts_ws, SID)["runs"][0]
    assert set(run) == set(R.RUN_ROW_KEYS), (sorted(run), sorted(R.RUN_ROW_KEYS))
    live = SS.runs_in_session(
        SS.read_session(artifacts_ws, sid=SID)[0], sid=SID)
    assert set(live[0]) == set(run), (sorted(live[0]), sorted(run))


def test_the_report_reading_uses_the_other_tri_vocabulary(
        artifacts_ws: pathlib.Path) -> None:
    """正控（裁定 N1）：交付说明那一格用 `ok`/`missing`/`unknown`，不许与 `Tri` 互顶。"""
    got = R.run_view(artifacts_ws, SID)["report"]
    assert got["status"] in ("ok", "missing", "unknown"), got
    assert got["status"] == _read_report(artifacts_ws)[0]
    assert got["status"] not in ("computed", "unreadable", "not_applicable"), \
        "两套词表不许互相顶替（裁定 N1）"


def test_every_face_carries_tri_and_reason(artifacts_ws: pathlib.Path) -> None:
    """反真空（三态头）：六个面每一个都给 `tri` 与 `reason`，取值在词表里。"""
    faces = {
        "state": R.state_face(artifacts_ws),
        "run": R.run_view(artifacts_ws, SID),
        "evidence": R.evidence_chain(artifacts_ws),
        "artifacts": R.artifacts_face(artifacts_ws),
        "acceptance": R.acceptance_face(artifacts_ws, project_dir=str(artifacts_ws)),
        "machine": R.machine_face(artifacts_ws),
        "products": R.run_products(artifacts_ws),
    }
    for name, got in faces.items():
        assert got["tri"] in (R.TRI_COMPUTED, R.TRI_UNREADABLE, R.TRI_NOT_APPLICABLE), \
            (name, got["tri"])
        assert isinstance(got.get("reason"), str), name
        if got["tri"] != R.TRI_COMPUTED:
            assert got["reason"], f"{name} 不是 computed 却没给理由"


def test_userio_view_shapes_are_reachable_from_readers() -> None:
    """反真空（L1 收敛的入口）：`userio` 的视图与 `readers` 用到的是同一套形状。

    B4 把"待答/选项"的读取收敛到了 `userio`（那三个 `*_view`）；`readers` 不另写
    第二份选项视图 —— 这条断言两边给出的键集合相同。
    """
    from agentflow.userio import coerce_option, option_view, question_view, reply_view
    from agentflow.webui.state import option_view as state_option_view

    raw = {"label": "甲", "description": "第一档"}
    assert set(option_view(raw)) == {"label", "description", "multi"}
    assert option_view(raw) == state_option_view(raw), "两处选项视图必须同形"
    q = U.Question(qid="q0001", role="M", text="问一句",
                   options=(coerce_option(raw),), multi_select=True)
    qv = question_view(q)
    assert set(qv) == {"qid", "sid", "role", "ts", "timeout_sec", "text", "options",
                       "multi", "index"}, sorted(qv)
    assert qv["multi"] is True and qv["options"][0]["label"] == "甲"
    rv = reply_view({"qid": "q0001", "selected": ["甲"], "custom": ""})
    assert set(rv) == {"qid", "answer", "selected", "custom", "by", "late"}, sorted(rv)
    assert rv["answer"] == "甲"


def test_userio_pending_views_are_the_global_panel_source(
        artifacts_ws: pathlib.Path) -> None:
    """正控（L1 收敛的落点）：全部会话的待答读数是"待答面板"那一份数据。

    `workspace_pending_view` 是界面上"待答必须全局可达"那条纪律的机器形态：
    它按 `(sid, index)` 排序、逐条带会话号与事件下标（`index` 是它在事件流里的位置）。
    """
    from agentflow import userio as U

    allp = U.workspace_pending_view(artifacts_ws)
    assert len(allp) == 1, allp
    one = allp[0]
    assert one["sid"] == SID and one["qid"] == "q0001"
    assert one["role"] == "M" and one["index"] == 3, one
    assert one["options"][0]["label"] == "保留", one["options"]
    assert one["options"][0]["description"] == "第一档", one["options"]
    assert set(one) == {"qid", "sid", "role", "ts", "timeout_sec", "text", "options",
                        "multi", "index"}, sorted(one)
    assert U.pending_view(artifacts_ws, sid=SID) == allp
    assert U.pending_view(artifacts_ws, sid="别的会话") == []


def test_userio_pending_view_drops_answered_questions(tmp_path: pathlib.Path) -> None:
    """负控（L1 收敛）：答过的不再出现在待答里；两段会话各有各的 qid，互不串味。"""
    from agentflow import userio as U

    root = tmp_path / "ws"
    root.mkdir()
    a = U.ask_user(root, role="M", question="甲问", timeout_sec=0, sid="s-one")
    b = U.ask_user(root, role="A", question="乙问", timeout_sec=0, sid="s-two")
    got = U.workspace_pending_view(root)
    assert [(q["sid"], q["qid"]) for q in got] == [("s-one", a.qid),
                                                   ("s-two", b.qid)], got
    U.answer_question(root, qid=a.qid, selected=("好",), sid="s-one")
    left = U.workspace_pending_view(root)
    assert [q["qid"] for q in left] == [b.qid], left
    assert [q["sid"] for q in left] == ["s-two"], left
