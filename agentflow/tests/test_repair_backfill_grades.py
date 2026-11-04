# -*- coding: utf-8 -*-
"""判据：`repair --backfill-grades` 的四栏 dry-run 与 `--apply`（业主 2026-11-04）。

## 这一份守什么

`evidence_kind` 原先只有一条升档路：同一份内容再登记一次（`Secretary._upgrade_evidence_kind`）。
于是"V 签了、之后没有人再登记"的行永远停在旧档（真机 84 的 `000000`、85 的
`000004` / `000005`）。`verifications._grade_recomputed_from_signature` 已经在签落位那一刻
按签重算；本命令只是把同一个判据搬到"事后补一遍"这个入口上。

四栏（业主定稿）：会升 / 已是最高 / 凭据不够（`state` 取 `proof_review_gap()` 原值）/
没查成（`checked=False` + 原因）。

| 判据 | 它钉的事 | 红的样子 |
|---|---|---|
| a | dry-run：有签 + sha 相符 + 停在低档 ⇒ 落"会升"，盘上零变化 | CLI 不认旗标 / dry-run 顺手写盘 |
| b | `--apply`：那一行到 `proof_review`、`_grade_recomputed` 有痕、其余三栏不动 | 写错行 / 痕丢了 / 顺手改了别的行 |
| c | 幂等：第二次 `--apply` 全部"已是最高"、`statements.json` 逐字节不变 | 再写一次 / 时间戳变 |
| d | 负控：没签 ⇒ `unsigned`、判「有毛病」⇒ `rejected`、台账读不出来 ⇒ "没查成"，都不写 | 把没凭据的行升上去 / 把"没查成"折成"不够" |
| e | 不带旗标 ⇒ 仍走 legacy 转发，且新实现没被调 | 旗标之外的路也换实现 |
| f | 四栏打印的是 `state` 原值（打桩成 `holding` ⇒ 输出里逐字出现 `holding`） | 自造枚举（把空串猜成 unsigned 之类） |

所有 `--apply` 只跑在 `tmp_path` 的临时工作区；`projects/` 下的任何文件一个字节都不碰。
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

import pytest

from agentflow import cli
from agentflow import verifications as VR
from agentflow.store import Store

#: 与 `test_fake_proof_review` 同一套造行方式（同一个门槛的判据不该有两套夹具）。
from test_fake_proof_review import _BAD, _row, _sign, _write  # noqa: E402

SID = "000000"


# ------------------------------------------------------------------ 夹具


def _ws(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _low(store: Store, sid: str, **kw: object) -> dict:
    """一条"停在低档"的行（先写行；签由用例自己落）。"""
    row = _row(sid, evidence_kind="heuristic", **kw)
    _write(store, row)
    return row


def _signed_low(store: Store, sid: str = SID) -> dict:
    """有签 + sha 相符 + 档位停在低档 —— 四栏里的"会升"那一行。"""
    _sign(store, sid)
    return _low(store, sid)


def _unsigned(store: Store, sid: str) -> dict:
    """真 `unsigned`：台账里只有*另一份证明*（#p2）的签 —— 不借光，读作没签。"""
    for _i in range(VR.SIGN_STREAK_NEED):
        VR.record_verification(store.root, statement_id=sid, proof_text=_row(sid)["proof_text"],
                               verdict={"verdict": "成立", "findings": []},
                               verifier="agent-V", proof_no=2)
    return _low(store, sid)


def _rejected(store: Store, sid: str) -> dict:
    """判过「有毛病」的那一行（签的是现行这一版，结论不是成立）。"""
    _sign(store, sid, verdict=_BAD)
    return _low(store, sid)


def _unreadable(store: Store, sid: str) -> dict:
    """台账读不出来（坏行）—— 这一栏只能是"没查成"，不许折成"凭据不够"。"""
    path = store.root / "verifications" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{这一行不是 JSON\n", encoding="utf-8")
    return _low(store, sid)


def _snapshot(root: pathlib.Path) -> dict[str, bytes]:
    """`data/` 与 `verifications/` 下每个文件的逐字节快照（dry-run 的零变化判据）。"""
    out: dict[str, bytes] = {}
    for sub in ("data", "verifications"):
        base = root / sub
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(root))] = path.read_bytes()
    return out


def _cols(out: dict) -> dict:
    return dict(out["columns"])


def _only(out: dict, column: str) -> list[dict]:
    return list(_cols(out)[column])


def _row_on_disk(store: Store, sid: str) -> dict:
    return next(dict(r) for r in store.rows("statements")
                if str(r.get("stmt_id")) == sid)


# ------------------------------------------------------------------ a dry-run


def test_a_dry_run_sees_the_upgrade_and_writes_nothing(tmp_path: pathlib.Path,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    """a：有签 + sha 相符 + 停低档 ⇒ "会升"；CLI 认识旗标；盘上一个字节不变。

    改前红：`repair` 的 parser 没有 `--backfill-grades` ⇒ argparse 以退出码 2
    （`unrecognized arguments: --backfill-grades`）拒掉，一个 handler 都进不去。
    """
    st = _ws(tmp_path)
    _signed_low(st)
    before = _snapshot(st.root)

    out = VR.recompute_grades(st.root, st)
    assert out["checked"] is True, out
    will = _only(out, "will_upgrade")
    assert [(e["statement_id"], e["from"], e["to"]) for e in will] == [
        (SID, "heuristic", "proof_review")], will
    assert _row_on_disk(st, SID)["evidence_kind"] == "heuristic"
    assert _snapshot(st.root) == before, "dry-run 动了盘"

    # CLI 这一层：旗标被认出来、四栏真打出来（改前是 argparse 的 exit 2）。
    code = cli.main(["--root", str(st.root), "repair", "--backfill-grades"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "会升 1" in text, text
    assert f"{SID}  heuristic → proof_review" in text, text
    assert "凭据不够 0" in text and "没查成 0" in text, text
    assert _snapshot(st.root) == before, "CLI dry-run 动了盘"


# ------------------------------------------------------------------ b apply


def test_b_apply_writes_only_that_row_and_leaves_a_trace(tmp_path: pathlib.Path,
                                                        capsys: pytest.CaptureFixture[str]) -> None:
    """b：`--apply` ⇒ 那一行到 `proof_review`、`_grade_recomputed` 有痕、其余三栏不动。"""
    st = _ws(tmp_path)
    _signed_low(st, "000000")            # 会升
    _unsigned(st, "000001")              # 凭据不够（unsigned）
    _rejected(st, "000002")              # 凭据不够（rejected）
    _sign(st, "000003")                  # 已是最高
    _write(st, _row("000003", evidence_kind="proof_review"))
    before = {sid: _row_on_disk(st, sid) for sid in ("000001", "000002", "000003")}
    ledgers_before = {name: (st.root / "verifications" / name).read_bytes()
                      for name in ("000001.jsonl", "000002.jsonl", "000003.jsonl")}

    out = VR.recompute_grades(st.root, st, apply=True)
    assert [e["statement_id"] for e in out["written"]] == ["000000"], out
    assert out["unmoved"] == [] and out["failed"] == [], out
    assert _only(out, "already_top") and _only(out, "already_top")[0]["statement_id"] == "000003"

    row = _row_on_disk(st, SID)
    assert row["evidence_kind"] == "proof_review", row
    trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("to") == "proof_review" and trace.get("from") == "heuristic", trace
    assert trace.get("basis") == "verifications/000000.jsonl#v-000003", trace
    assert str(trace.get("at") or ""), trace
    # 其余三栏一个字段都没动（整行逐字段比）。
    for sid, old in before.items():
        assert _row_on_disk(st, sid) == old, f"{sid} 被顺手改了"
    for name, old in ledgers_before.items():
        assert (st.root / "verifications" / name).read_bytes() == old, f"{name} 被改了"

    # CLI 的写入口：四栏 + 写后回读那一段都要真打出来。
    out2 = VR.recompute_grades(st.root, st, apply=True)
    assert out2["written"] == [] and out2["unmoved"] == [], out2
    assert sorted(e["statement_id"] for e in _only(out2, "already_top")) == [
        "000000", "000003"], out2
    assert sorted(e["statement_id"] for e in _only(out2, "not_enough")) == [
        "000001", "000002"], out2
    code = cli.main(["--root", str(st.root), "repair", "--backfill-grades", "--apply"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "写后回读：已写 0 / 未动 0 / 写失败 0" in text, text


def test_b2_apply_refuses_rows_it_could_not_check(tmp_path: pathlib.Path) -> None:
    """b 的负控：读不出来的行不写（`unchecked` 一条、盘上零变化）。"""
    st = _ws(tmp_path)
    _unreadable(st, "000000")
    before = _snapshot(st.root)
    out = VR.recompute_grades(st.root, st, apply=True)
    assert [e["statement_id"] for e in _only(out, "unchecked")] == ["000000"], out
    assert out["written"] == [] and out["unmoved"] == [], out
    assert _snapshot(st.root) == before, "读不出来的行被写了"


# ------------------------------------------------------------------ c 幂等


def test_c_second_apply_changes_no_byte(tmp_path: pathlib.Path) -> None:
    """c：第二次 `--apply` ⇒ 全部"已是最高"、`statements.json` 逐字节不变（时间戳不变）。"""
    st = _ws(tmp_path)
    _signed_low(st)
    first = VR.recompute_grades(st.root, st, apply=True)
    assert [e["statement_id"] for e in first["written"]] == [SID], first
    trace = dict(_row_on_disk(st, SID).get(VR.GRADE_RECOMPUTED_KEY) or {})
    stamp = str(trace.get("at") or "")
    assert stamp, trace
    after_first = (st.root / "data" / "statements.json").read_bytes()

    second = VR.recompute_grades(st.root, st, apply=True)
    assert _only(second, "will_upgrade") == [], second
    assert [e["statement_id"] for e in _only(second, "already_top")] == [SID], second
    assert second["written"] == [] and second["unmoved"] == [] and second["failed"] == [], second
    assert (st.root / "data" / "statements.json").read_bytes() == after_first, "第二次 apply 又写了"
    trace2 = dict(_row_on_disk(st, SID).get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert str(trace2.get("at") or "") == stamp, "时间戳变了（幂等被破坏）"


# ------------------------------------------------------------------ d 负控


def test_d_no_signature_rejected_and_unreadable_are_three_readings(
        tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]) -> None:
    """d：没签 ⇒ `unsigned`；判「有毛病」⇒ `rejected`；台账读不出来 ⇒ "没查成"；都不写。"""
    st = _ws(tmp_path)
    _unsigned(st, "000000")
    _rejected(st, "000001")
    _unreadable(st, "000002")
    _low(st, "000003")                    # 从来没送过审：gap.state 是空串（台账不在盘上）
    before = _snapshot(st.root)

    out = VR.recompute_grades(st.root, st, apply=True)
    short = {e["statement_id"]: e for e in _only(out, "not_enough")}
    assert short["000000"]["state"] == "unsigned", short
    assert short["000001"]["state"] == "rejected", short
    # 空 state 不是本命令补出来的枚举：原值就是空串，另带 gap 的台账读数说明是哪一种空。
    assert short["000003"]["state"] == "", short
    assert short["000003"]["ledger_present"] is False, short
    unknown = _only(out, "unchecked")
    assert [e["statement_id"] for e in unknown] == ["000002"], unknown
    assert "读不出来" in unknown[0]["why"] or "没查成" in unknown[0]["why"], unknown
    assert out["written"] == [] and out["unmoved"] == [], out
    assert _snapshot(st.root) == before, "负控行被写了"

    # `--apply` 的 CLI 在"有行没查成"时退出码 1（查过了、有问题），不是 0、也不是 2。
    code = cli.main(["--root", str(st.root), "repair", "--backfill-grades", "--apply"])
    text = capsys.readouterr().out
    assert code == 1, (code, text)
    assert "state=unsigned" in text and "state=rejected" in text, text
    assert "ledger_missing=true" in text, text
    assert "没查成 1" in text, text


# ------------------------------------------------------------------ e legacy


def test_e_without_the_flag_cmd_repair_still_forwards_legacy(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """e：不带旗标 ⇒ `cmd_repair` 仍走 legacy 转发；新实现一次都没被调。"""
    seen: list[object] = []

    class _Legacy:
        @staticmethod
        def main(args):  # noqa: ANN001, ANN205
            seen.append(args)
            return 7

    monkeypatch.setattr(cli, "_legacy_module", lambda name: _Legacy)

    def _boom(*a, **k):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError("带旗标的新实现被调到了")

    monkeypatch.setattr(VR, "recompute_grades", _boom)
    args = SimpleNamespace(root=str(tmp_path), related=False, apply=False,
                           backfill_grades=False)
    assert cli.cmd_repair(args) == 7
    assert seen == [args], seen

    # 分派层同一个读数：不带旗标调到的是 `cmd_repair` 本身。
    called: list[object] = []
    monkeypatch.setattr(cli, "cmd_repair", lambda a: called.append(a) or 9)
    assert cli._repair_dispatch(args) == 9
    assert called == [args], called


def test_e2_the_parser_routes_the_flag_to_the_new_command() -> None:
    """e 的另一半：旗标在 parser 层真的接上了（改前 argparse 直接不认识它）。"""
    parser = cli.build_parser()
    plain = parser.parse_args(["repair"])
    assert plain.func is cli._repair_dispatch and plain.backfill_grades is False
    flagged = parser.parse_args(["repair", "--backfill-grades", "--apply"])
    assert flagged.func is cli._repair_dispatch
    assert flagged.backfill_grades is True and flagged.apply is True


# ------------------------------------------------------------------ f state 原值


def test_f_the_state_column_prints_the_raw_gap_state(
        monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str]) -> None:
    """f：把 gap 打桩成 `holding` ⇒ 输出里逐字出现 `holding`（不是本命令自造的枚举）。"""
    st = _ws(tmp_path)
    _low(st, SID)

    def _stub(root, row, *, proof_no=None):  # noqa: ANN001, ANN202, ARG001
        return {"ok": False, "checked": True, "state": "holding", "why": "打桩：连续次数没到",
                "statement_id": str(row.get("stmt_id") or ""), "ledger": "verifications/x.jsonl",
                "verification_id": "v-000001", "checklist": []}

    monkeypatch.setattr(VR, "proof_review_gap", _stub)
    out = VR.recompute_grades(st.root, st)
    short = _only(out, "not_enough")
    assert short and short[0]["state"] == "holding", short

    code = cli.main(["--root", str(st.root), "repair", "--backfill-grades"])
    text = capsys.readouterr().out
    assert code == 0, text
    assert "state=holding" in text, text
    # 反真空：命令没有把 `holding` 改写成别的一格（例如 unsigned）。
    assert "unsigned" not in text, text
