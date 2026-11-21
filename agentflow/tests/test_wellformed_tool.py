"""产物畸形统一判据（`wellformed`）的三条判据 + 反真空。

业主口径（2026-11-21）：「查各种畸形情况，尝试把可能发生畸形的环节都做成系统工具」。
本文件守四件事：

- a 每类畸形一个夹具 ⇒ 工具判 `malformed`、退出码 1（改前：没有这个工具，这类畸形
  只能靠人翻盘看）；
- b 干净仓库 ⇒ 退出码 0（正控：没有这一条，一个永远报畸形的工具也能让 a 全绿）；
- c 读不到的文件 ⇒ `unchecked` 加退出码 2（不是 0：读不出来与"没有畸形"是两件事）；
- d 反真空：把抓住这类畸形的那一条规则打桩掉 ⇒ 同一份夹具变回 `ok` ⇒ 判据红。

d 的形状值得说明：它不是"再跑一遍看它还是红的"，而是"把规则拿掉，夹具必须变绿"。
只有这样才能证明"是那一条规则在抓这一类畸形"，而不是别的规则顺手抓到的。
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from agentflow import wellformed as WF  # noqa: E402

SCRIPT = REPO / "scripts" / "check_wellformed.py"

#: 一个合法的 sha256（侧文件 / 签块 / 产物登记共用）。
SHA = "a" * 64


# ---------------------------------------------------------------- 夹具


def _dump(path: pathlib.Path, payload) -> None:
    """写一个 JSON 文件（建好父目录）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _table(root: pathlib.Path, name: str, rows: list[dict]) -> None:
    """写一张 `data/<name>.json`。"""
    _dump(root / "data" / f"{name}.json", {"schema_version": 2, "rows": rows})


def _lit_row(**over) -> dict:
    """一条合法的 literature 行。"""
    row = {
        "lit_id": "000001", "title": "t", "type": "J", "path": None,
        "download": {"status": "skipped", "http_status": None, "bytes": 0,
                     "sha256": None, "error": "no_local_path",
                     "fulltext": "no_fulltext"},
        "dedup_key": "doi:10.1/x", "_keys": ["doi:10.1/x"], "matched": "",
    }
    row.update(over)
    return row


def _rel_row(**over) -> dict:
    """一条合法的 relations 行。"""
    row = {
        "relation_id": "000001", "lit_id": "000001", "concept_ids": ["000001", "000002"],
        "description": "d", "statement": "s", "quote_verified": True,
        "quote_mode": "verbatim", "quote_span": "p1:norm[0:4]",
        "dedup_key": "000001|000002::deadbeef", "status": "active",
    }
    row.update(over)
    return row


def _stmt_row(**over) -> dict:
    """一条合法的 statements 行。"""
    row = {
        "stmt_id": "000001", "kind": "theorem", "origin": "own_result",
        "status": "active", "proof_text": "p", "proof_no": 1,
        "bits": {"grade": "pre_theorem"}, "quote_verified": None, "quote_span": "",
    }
    row.update(over)
    return row


def _cand_row(**over) -> dict:
    """一条合法的 lit_candidates 行（admitted）。"""
    row = {
        "slot": "000001", "status": "admitted", "lit_id": "000001",
        "cleared_at": "2026-11-21T00:00:00+08:00", "clear_reason": "c",
        "doi": "10.1/x", "relevance": "r",
    }
    row.update(over)
    return row


def _task_row(**over) -> dict:
    """一条合法的 tasks 行。"""
    row = {"task_id": "t-000001", "role": "M", "action": "", "kind": "",
           "status": "done", "outcome": "ok", "item_state": "", "parent_task_id": None,
           "detail": "d"}
    row.update(over)
    return row


def _usage_row(**over) -> dict:
    """一条合法的 usage_ledger 行。"""
    row = {"usage_id": "000001", "scope": "reason", "role": "M", "task_id": "t-000001",
           "tokens_in": 1, "tokens_out": 2, "tokens_total": 3, "usd": 0.1,
           "note": "call_index=0", "idem_key": "idem-0123456789ab"}
    row.update(over)
    return row


def _ret_row(**over) -> dict:
    """一条合法的销号行。"""
    row = {"name": "A1", "role": "A", "owner": "t-000001", "task_id": "t-000001",
           "reason": "交差", "seq": 1}
    row.update(over)
    return row


def clean_workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个没有任何畸形的极小工作区（六张必修表各一行合法数据）。"""
    root = tmp_path / "ws"
    _table(root, "literature", [_lit_row()])
    _table(root, "relations", [_rel_row()])
    _table(root, "statements", [_stmt_row()])
    _table(root, "lit_candidates", [_cand_row()])
    _table(root, "tasks", [_task_row()])
    _table(root, "usage_ledger", [_usage_row()])
    return root


def _sign_block(sha: str, *, manuscript_id: str = "000001") -> str:
    """一行签块（与 `vsigns.render_manuscript_sign` 的九格同形）。"""
    return (f"- V 签：已签=true；判词=成立；连续=3/3；正文sha={sha}；"
            f"时间=2026-11-21T00:00:00+08:00；签名者=secretary:F；"
            f"台账=verifications/pending/{'b' * 64}.jsonl#u-000001；手稿号={manuscript_id}")


def _write_proof(root: pathlib.Path, *, mid: str = "000001", text: str | None = None) -> None:
    """写一份合法的证明稿（标题 + 命题 + 证明）。"""
    path = root / "reports" / f"f-proof-{mid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else (
        f"# F 的证明手稿：第 {mid} 号\n\n- 命题类型：theorem\n\n"
        "## 命题\n\n一句话。\n\n## 证明\n\n第一步。\n"), encoding="utf-8")


def _write_vsign(root: pathlib.Path, sha: str = SHA, **over) -> pathlib.Path:
    """写一份合法的 V 签侧文件。"""
    side = {"schema": "vsign/1", "artifact_sha": sha,
            "artifact_path": "reports/f-proof-000001.md",
            "at": "2026-11-21T00:00:00+08:00", "count": 1, "need": 1,
            "passes": [{"verification_id": "u-000001", "at": "2026-11-21T00:00:00+08:00",
                        "proof_sha256": SHA, "why": "w"}]}
    side.update(over)
    path = root / "out" / "vsigns" / f"{sha}.json"
    _dump(path, side)
    return path


def _write_artifacts(root: pathlib.Path, rows: list[dict]) -> None:
    """写一份产物登记台账。"""
    path = root / "ARTIFACTS.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------- a：每类畸形一个夹具


def _mut_vsign_bad_sha(root: pathlib.Path) -> None:
    _write_vsign(root, artifact_sha="not-a-sha")


def _mut_lit_fulltext(root: pathlib.Path) -> None:
    row = _lit_row()
    row["download"]["fulltext"] = "metadata_only"
    _table(root, "literature", [row])


def _mut_lit_download_shape(root: pathlib.Path) -> None:
    _table(root, "literature", [_lit_row(download={})])


def _mut_rel_quote_span(root: pathlib.Path) -> None:
    _table(root, "relations", [_rel_row(quote_span="")])


def _mut_rel_dangling_lit(root: pathlib.Path) -> None:
    _table(root, "relations", [_rel_row(lit_id="999999")])


def _mut_stmt_kind(root: pathlib.Path) -> None:
    _table(root, "statements", [_stmt_row(kind="hypothesis")])


def _mut_stmt_bits(root: pathlib.Path) -> None:
    _table(root, "statements", [_stmt_row(bits="verified")])


def _mut_cand_status(root: pathlib.Path) -> None:
    _table(root, "lit_candidates", [_cand_row(status="maybe")])


def _mut_cand_admitted_no_lit(root: pathlib.Path) -> None:
    _table(root, "lit_candidates", [_cand_row(lit_id="")])


def _mut_task_role(root: pathlib.Path) -> None:
    _table(root, "tasks", [_task_row(role="Z")])


def _mut_task_item_state(root: pathlib.Path) -> None:
    _table(root, "tasks", [_task_row(item_state="flying")])


def _mut_usage_negative_usd(root: pathlib.Path) -> None:
    _table(root, "usage_ledger", [_usage_row(usd=-0.5)])


def _mut_usage_dup_idem(root: pathlib.Path) -> None:
    _table(root, "usage_ledger", [_usage_row(), _usage_row(usage_id="000002")])


def _mut_session_bad_line(root: pathlib.Path) -> None:
    path = root / "sessions" / "2026-11-21.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"kind": "agent_step", "ts": "2026-11-21T00:00:00+08:00"}\n'
                    'not json\n', encoding="utf-8")


def _mut_session_ts_desc(root: pathlib.Path) -> None:
    path = root / "sessions" / "2026-11-21.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"kind": "agent_step", "ts": "2026-11-21T01:00:00+08:00"}\n'
        '{"kind": "agent_step", "ts": "2026-11-21T00:00:00+08:00"}\n', encoding="utf-8")


def _mut_ms_title(root: pathlib.Path) -> None:
    _write_proof(root, text="# ok\n\n## 命题\n\np\n\n## 证明\n\nq\n")
    # 把标题行换成引用块（真机 dct-min3 那份副本的形态）
    path = root / "reports" / "f-proof-000001.md"
    path.write_text("> 本文件是副本\n\n## 命题\n\np\n\n## 证明\n\nq\n", encoding="utf-8")


def _mut_ms_kind(root: pathlib.Path) -> None:
    _write_proof(root, text="# ok\n\n- 命题类型：wild\n\n## 命题\n\np\n\n## 证明\n\nq\n")


def _mut_proof_no_section(root: pathlib.Path) -> None:
    _write_proof(root, text="# ok\n\n## 命题\n\np\n")


def _mut_proof_sign_without_file(root: pathlib.Path) -> None:
    _write_proof(root, text=(
        "# ok\n\n" + _sign_block(SHA) + "\n\n## 命题\n\np\n\n## 证明\n\nq\n"))


def _mut_acceptance_row(root: pathlib.Path) -> None:
    _dump(root / "out" / "paper" / "ACCEPTANCE-CHECKS.json",
          {"checks": [{"name": "少 id 的行", "kind": "statement_rows", "min": 1}]})


def _mut_artifact_missing(root: pathlib.Path) -> None:
    _write_artifacts(root, [{"path": "reports/gone.md", "sha256": SHA,
                             "at": "2026-11-21T00:00:00+08:00", "producer": "F"}])


def _mut_artifact_sha_changed(root: pathlib.Path) -> None:
    target = root / "notes" / "a.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("hello\n", encoding="utf-8")
    _write_artifacts(root, [{"path": "notes/a.md", "sha256": SHA,
                             "at": "2026-11-21T00:00:00+08:00", "producer": "M"}])


def _mut_retired_reason(root: pathlib.Path) -> None:
    path = root / "out" / "roster" / "t-000001-retired.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_ret_row(reason=""), ensure_ascii=False) + "\n",
                    encoding="utf-8")


#: (类别, 变异, 期望的 finding code, 抓它的规则名)。规则名给 d 组反真空用。
CASES: tuple[tuple[str, object, str, str], ...] = (
    ("vsigns", _mut_vsign_bad_sha, "vsign_artifact_sha", "artifact_sha"),
    ("literature", _mut_lit_fulltext, "literature_fulltext_vocab", "download_vocab"),
    ("literature", _mut_lit_download_shape, "literature_download_shape", "download_shape"),
    ("relations", _mut_rel_quote_span, "relation_quote_span_empty", "quote_span"),
    ("relations", _mut_rel_dangling_lit, "relation_lit_missing", "lit_ref"),
    ("statements", _mut_stmt_kind, "statement_kind", "kind_vocab"),
    ("statements", _mut_stmt_bits, "statement_bits_shape", "grade_vocab"),
    ("lit_candidates", _mut_cand_status, "candidate_status", "status_vocab"),
    ("lit_candidates", _mut_cand_admitted_no_lit,
     "candidate_admitted_without_lit_id", "state_fields"),
    ("tasks", _mut_task_role, "task_role", "role"),
    ("tasks", _mut_task_item_state, "task_item_state", "vocab"),
    ("usage_ledger", _mut_usage_negative_usd, "usage_usd", "money"),
    ("usage_ledger", _mut_usage_dup_idem, "usage_duplicate_idem", "idem"),
    ("sessions", _mut_session_bad_line, "session_bad_line", "lines"),
    ("sessions", _mut_session_ts_desc, "session_ts_descending", "order"),
    ("manuscripts", _mut_ms_title, "manuscript_title", "title"),
    ("manuscripts", _mut_ms_kind, "manuscript_kind_vocab", "kind"),
    ("proof_reports", _mut_proof_no_section, "proof_section_missing", "sections"),
    ("proof_reports", _mut_proof_sign_without_file, "proof_sign_file_missing", "sign_sha"),
    ("acceptance", _mut_acceptance_row, "acceptance_row_shape", "shape"),
    ("artifacts", _mut_artifact_missing, "artifact_missing", "on_disk"),
    ("artifacts", _mut_artifact_sha_changed, "artifact_sha_changed", "on_disk"),
    ("roster_retired", _mut_retired_reason, "retired_reason_absent", "fields"),
)


@pytest.mark.parametrize("kind,mutate,code,rule",
                         CASES, ids=[f"{c[0]}-{c[2]}" for c in CASES])
def test_a_each_malformed_shape_is_caught(tmp_path, kind, mutate, code, rule):
    """a：每类畸形一个夹具 ⇒ 工具判 malformed、带那条 code、整份读数退出码 1。"""
    root = clean_workspace(tmp_path)
    mutate(root)
    result = WF.check_kind(kind, root)
    assert result.state == WF.MALFORMED, (kind, result.state, result.reasons)
    assert code in {f.code for f in result.findings}, (
        kind, code, [f.code for f in result.findings])
    report = WF.check_workspace(root)
    assert report.state == WF.MALFORMED
    assert report.exit_code == WF.EXIT_MALFORMED == 1


def test_a_table_top_shape_is_malformed_not_unchecked(tmp_path):
    """a 的边界：表解析得开、但顶层形状不对 ⇒ malformed（不是"读不懂"）。

    这一条与 c 组的"读不出来"成对：`[]` 与 `{"rows": []}` 的区别是形状，不是可读性。
    把形状错读成 unchecked，一条永远写错的表会被读成"没查成"而永远不进处置。
    """
    root = clean_workspace(tmp_path)
    (root / "data" / "relations.json").write_text("[]", encoding="utf-8")
    result = WF.check_kind("relations", root)
    assert result.state == WF.MALFORMED, (result.state, result.reasons)
    assert "table_top" in {f.code for f in result.findings}


# ---------------------------------------------------------------- b：正控


def test_b_a_clean_workspace_is_ok_and_exits_zero(tmp_path):
    """b：干净工作区 ⇒ 13 类全 ok、没有任何 error/warning、退出码 0。"""
    root = clean_workspace(tmp_path)
    # 再加一份合法签 + 一份合法证明稿 + 一份被签过的侧文件（覆盖可选产物那一档）。
    _write_proof(root)
    _write_vsign(root)
    report = WF.check_workspace(root)
    assert report.state == WF.OK, [(r.kind, r.state, [f.code for f in r.findings])
                                   for r in report.results]
    assert report.exit_code == WF.EXIT_OK == 0
    assert not [f for f in report.findings if f.severity in ("error", "warning")]


def test_b_the_cli_exits_zero_on_a_clean_workspace(tmp_path):
    """b：CLI 也返回 0（判据跑的是同一个入口，不是另一份实现）。"""
    root = clean_workspace(tmp_path)
    got = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), "--json"],
                         capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 0, (got.returncode, got.stdout, got.stderr)
    payload = json.loads(got.stdout)
    assert payload["state"] == "ok" and payload["exit_code"] == 0


# ---------------------------------------------------------------- c：没查成


def test_c_unreadable_table_is_unchecked_not_ok(tmp_path):
    """c：读不出来的表 ⇒ unchecked，整份读数退出码 2（不是 0）。"""
    root = clean_workspace(tmp_path)
    (root / "data" / "statements.json").write_text("{ 这不是 JSON", encoding="utf-8")
    result = WF.check_kind("statements", root)
    assert result.state == WF.UNCHECKED, (result.state, result.findings)
    assert result.reasons
    report = WF.check_workspace(root)
    assert report.state == WF.UNCHECKED
    assert report.exit_code == WF.EXIT_UNCHECKED == 2


def test_c_a_missing_required_table_is_unchecked(tmp_path):
    """c：必修表缺文件 ⇒ unchecked（一个 init 过的工作区每张表都有空文件）。"""
    root = clean_workspace(tmp_path)
    (root / "data" / "tasks.json").unlink()
    result = WF.check_kind("tasks", root)
    assert result.state == WF.UNCHECKED
    assert WF.check_workspace(root).exit_code == 2


def test_c_the_cli_exits_two_when_it_could_not_check(tmp_path):
    """c：CLI 在没查成时返回 2，且不把它印成「全 ok」。

    用"读不懂的字节"造没查成（`{ 这不是 JSON`）；顶层形状对（`[]` 而不是
    `{"rows": []}`）不是没查成，它是畸形 —— 那一档由 `test_a_table_top_shape` 守。
    """
    root = clean_workspace(tmp_path)
    (root / "data" / "relations.json").write_text("{ 这不是 JSON", encoding="utf-8")
    got = subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)],
                         capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 2, (got.returncode, got.stdout, got.stderr)
    assert "没查成" in got.stdout


def test_c_an_absent_optional_artifact_is_ok_not_unchecked(tmp_path):
    """c 的边界：可选产物整类不存在 ⇒ ok（不是没查成，也不是畸形）。

    这条与上一条成对：把"没有这一类产物"读成 unchecked，一个刚 init 的工作区就会永远
    是 2；读成 malformed 更糟。两个方向都不许。
    """
    root = clean_workspace(tmp_path)
    for kind in ("vsigns", "sessions", "manuscripts", "proof_reports", "acceptance",
                 "artifacts", "roster_retired"):
        result = WF.check_kind(kind, root)
        assert result.state == WF.OK, (kind, result.state, result.reasons)


# ---------------------------------------------------------------- d：反真空


ANTIVACUUM: tuple[tuple[str, object, str, str], ...] = (
    ("relations", _mut_rel_quote_span, "quote_span", "relation_quote_span_empty"),
    ("literature", _mut_lit_fulltext, "download_vocab", "literature_fulltext_vocab"),
    ("tasks", _mut_task_item_state, "vocab", "task_item_state"),
    ("proof_reports", _mut_proof_sign_without_file, "sign_sha", "proof_sign_file_missing"),
)


@pytest.mark.parametrize("kind,mutate,rule,code", ANTIVACUUM,
                         ids=[f"{c[0]}-{c[2]}" for c in ANTIVACUUM])
def test_d_stubbing_the_rule_flips_the_fixture_to_ok(tmp_path, monkeypatch,
                                                     kind, mutate, rule, code):
    """d：把抓这类畸形的那一条规则打桩掉 ⇒ 同一份夹具变回 ok ⇒ 判据红。

    先断言"没打桩时是 malformed、且只有这一条 code"，再打桩，再断言 ok。第二条如果
    还是 malformed，说明抓它的不是这条规则（判据就红在这一行）；如果第一条不成立，
    说明夹具本身没造出畸形。
    """
    root = clean_workspace(tmp_path)
    mutate(root)
    before = WF.check_kind(kind, root)
    assert before.state == WF.MALFORMED
    assert {f.code for f in before.findings} == {code}, [f.code for f in before.findings]

    monkeypatch.setitem(WF.RULES[kind], rule, lambda ctx: [])
    after = WF.check_kind(kind, root)
    assert after.state == WF.OK, (
        f"把 {kind}.{rule} 打桩掉之后夹具仍是 {after.state} ⇒ 抓 {code} 的不是这条规则",
        [f.code for f in after.findings])
    assert WF.check_workspace(root).exit_code == 0


# ---------------------------------------------------------------- 接进已有的读数面


def test_the_reading_rides_an_existing_surface_and_is_not_a_gate(tmp_path):
    """读数面接线：`statusreport.collect` 里多一格 `wellformed`，`.md` 里多一行。

    它必须是读数而不是闸门：`collect()` 的既有键一个不少、也不因为畸形而抛异常；
    `render_status_markdown` 把条数印出来，处置由人定（业主口径：不许新增 blocker）。
    """
    from agentflow import statusreport as SR
    from agentflow.store import Store

    ws = tmp_path / "ws"
    (ws / "data").mkdir(parents=True, exist_ok=True)
    store = Store(ws)
    store.init()
    before = SR.collect(store, ws)
    assert before["wellformed"]["checked"] is True
    assert before["wellformed"]["state"] == WF.OK
    assert "产物畸形" in SR.render_status_markdown(before)

    # 把关系表换成一条畸形（说回验通过却给不出区间），读数面必须看见、且不抛。
    # literature 那一行照写：不写的话这条关系还会因为"lit_id 指向不存在的文献"多报一条，
    # 那条断言就测不到本意了。
    _dump(ws / "data" / "literature.json", {"schema_version": 2, "rows": [_lit_row()]})
    _dump(ws / "data" / "relations.json",
          {"schema_version": 2, "rows": [_rel_row(quote_span="")]})
    after = SR.collect(store, ws)
    assert after["wellformed"]["state"] == WF.MALFORMED
    assert after["wellformed"]["by_severity"]["error"] == 1
    assert after["wellformed"]["examples"][0]["code"] == "relation_quote_span_empty"
    md = SR.render_status_markdown(after)
    assert "产物畸形" in md and "1 条要处置" in md
    # 既有键一个不少（接线是加一格，不是换一屏）；表那一栏仍是同一批表。
    assert {"tables", "manuscripts", "in_flight", "quote_evidence",
            "statement_body", "next_steps"} <= set(after)
    assert set(after["tables"]) == set(before["tables"])
