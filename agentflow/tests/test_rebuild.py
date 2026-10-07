"""`rebuild` 的无损性。

背景（真实缺陷）：`rebuild()` 的事件折叠原本走 `S.row_from_dict()`，而它只保留
dataclass 字段 —— 于是带下划线前缀的诊断/扩展字段（`_keys`、`_quote_check`）
在重建后全部消失。功能上判重还能靠 `doi`/`dedup_key` 兜底，但
"能重建"不应该意味着"重建出更少的信息"：一旦丢字段，事后就无法回答
"当初这条文献是从哪些键命中/被判定为重复的"。

本文件把"无损"固定下来。
"""

from __future__ import annotations

import json

from agentflow.store import Store


def _seed(store: Store) -> None:
    """写一行带诊断字段的文献 + 一行带校验明细的关系。"""
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "0000", "title": "Probe paper", "type": "J", "summary": "",
            "path": None, "processed": True, "source_request_ids": [],
            "dedup_key": "doi:10.1/probe", "doi": "10.1/probe", "year": 2000,
            "authors": [], "venue": None, "language": None,
            "added_at": "2026-01-01T00:00:00+00:00", "download": {},
            "claimed_by": None, "lease_until": None, "mine_attempts": 0,
            "last_mine_error": None,
            "_keys": ["doi:10.1/probe", "title:probe paper|2000", "title:probe paper|*"],
        })
    with store.tx("concepts", "relations", actor="test") as tx:
        for cid, name, rel in (("0000", "group", ["0001"]), ("0001", "abelian group", ["0000"])):
            tx.upsert("concepts", {
                "concept_id": cid, "name": name, "definition": "d",
                "related_concepts": rel, "normalized_name": name, "aliases": [],
                "definition_source_lit_id": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
            })
        tx.upsert("relations", {
            "relation_id": "0000", "concept_ids": ["0000", "0001"], "description": "d",
            "lit_id": "0000", "page_range": {"start": 1, "end": 1, "label": "p. 1"},
            "quote": "An abelian group is a group.",
            "quote_normalized": "an abelian group is a group",
            "quote_verified": True, "statement": "d",
            "concept_group_key": "0000|0001", "dedup_key": "0000|0001::x",
            "status": "active", "duplicate_of": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "_quote_check": {"verified": True, "reason": "substring_match"},
        })


def _row(store: Store, table: str) -> dict:
    return json.loads((store.data / f"{table}.json").read_text(encoding="utf-8"))["rows"][0]


def test_rebuild_preserves_diagnostic_fields(store):
    """重建后诊断字段不得丢失（否则无从追溯"当初为什么判成重复"）。

    同时断言 schema 字段仍然被规范化 —— 无损不等于"原样抄回"，
    校验后的规范值必须覆盖原始值。
    """
    _seed(store)
    before_keys = _row(store, "literature")["_keys"]
    before_qc = _row(store, "relations")["_quote_check"]

    out = store.rebuild(backup=False)
    assert out["applied"] == 4 and out["skipped"] == 0

    assert _row(store, "literature")["_keys"] == before_keys
    assert _row(store, "relations")["_quote_check"] == before_qc


def test_rebuild_is_idempotent_and_keeps_tables_valid(store):
    """连做两次 rebuild 结果必须逐字节一致（幂等），且不变量仍成立。"""
    _seed(store)

    store.rebuild(backup=False)
    first = {t: (store.data / f"{t}.json").read_bytes() for t in
             ("literature", "concepts", "relations", "search_requests")}
    store.rebuild(backup=False)
    second = {t: (store.data / f"{t}.json").read_bytes() for t in
              ("literature", "concepts", "relations", "search_requests")}

    assert first == second, "rebuild 必须幂等，否则反复重建会漂移"


def test_rebuild_ignores_corrupt_events_without_dying(store):
    """事件日志里混入坏行时应跳过并计数，而不是整次重建失败。

    崩溃时可能留下半行 JSON —— 那不应该让数据库变得不可恢复。
    """
    _seed(store)
    with open(store.events_path, "a", encoding="utf-8") as f:
        f.write('{"op":"upsert","table":"literature","row":{"lit_id":"0001"')  # 截断的坏行
        f.write("\n")
        f.write("这不是 JSON\n")

    out = store.rebuild(backup=False)
    # `I-5`（登记在 `draft/28`）：旧断言是 `out["skipped"] >= 0` —— 恒真
    # （`skipped` 在 `rebuild` 里只增不减），于是"日志里有坏行"这件事
    # 在被测判据里完全看不见，"没抛异常"就被读成"日志是好的"。
    # 现在返回值里有 `corrupt_events`（坏行条数），本用例钉住它。
    assert out["corrupt_events"] == 2, out  # 上面写进去的正是 2 行坏行
    assert len(store.rows("literature")) == 1, "好数据仍应重建出来"


def _append_event(store: Store, event: dict) -> None:
    """往事件日志尾部直接追加一条事件（模拟"日志里有这一行、而它是坏的"）。"""
    with open(store.events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def test_rebuild_reports_schema_rejected_rows_by_reason_and_detail(store):
    """R-06：`skipped` 只说"跳了几行"。这一条钉住"为什么跳"的两份明细。

    改前必红：返回值里没有 `skipped_details` / `skipped_by_reason` ⇒
    `KeyError`（"静默丢行"这件事当时只有一个整数，读它的人不知道去查什么）。

    `reason="schema_rejected"` 的语义是"这一行本来就不合法"（形状对、值不合法）
    —— 与"事件行坏了"（`shape_broken`）必须分得开：前者改数据、后者查是谁写坏的。
    """
    _seed(store)
    _append_event(store, {"op": "upsert", "table": "review_findings", "row": {
        "finding_id": "0002", "doc_id": None, "round_no": 1, "level": "bogus",
        "kind": "体例", "target": "第 3 节", "evidence": "原文", "message": "d",
        "axis": "体例", "criterion": "c", "verdict": "not_applicable", "detail": "d",
        "created_at": "2026-01-01T00:00:00+00:00", "created_by": "agent-H"}})

    out = store.rebuild(backup=False)
    assert out["skipped"] == 1, out
    assert out["skipped_by_reason"] == {"schema_rejected": 1}, out["skipped_by_reason"]
    assert [d["reason"] for d in out["skipped_details"]] == ["schema_rejected"]
    first = out["skipped_details"][0]
    assert first["table"] == "review_findings" and first["id"] == "0002", first
    assert first["error"].startswith("ValueError:"), first
    assert isinstance(first["event_index"], int), first


def _rebuild_args(root) -> list[str]:
    # `--root` 是全局开关（在子命令之前）—— 放后面会被 argparse 判成"不认识的参数"。
    return ["--root", str(root), "rebuild", "--no-backup"]


def test_rebuild_cli_prints_the_skip_breakdown_when_there_is_one(store, capsys) -> None:
    """判据（`46-01 §2.2(b)` STEP-3 逐字：明细没有人看得见就等于没做）：CLI 要把它打出来。

    改前必红：`cmd_rebuild` 只打印"应用 N 条，跳过 M 条"—— `M` 是个整数，
    读的人不知道跳过了什么（`store.rebuild` 那时也确实没有明细；R-06 补上两键之后，
    若 CLI 不打印，那两键仍然只有测试看得见）。
    """
    from agentflow import cli

    _seed(store)
    _append_event(store, {"op": "upsert", "table": "concepts",
                          "row": {"concept_id": "0003"}})  # 缺 name/definition
    out = store.rebuild(backup=False)
    assert out["skipped"] == 1, out

    # 直接调 cmd_rebuild 会再重建一次（幂等，但事件日志里的坏行仍在）⇒ 打印里必须有分类
    rc = cli.cmd_rebuild(cli.build_parser().parse_args(_rebuild_args(store.root)))
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "跳过的分类计数" in text, text
    assert "shape_broken=1" in text, text
    assert "跳过明细" in text, text


def test_rebuild_cli_stays_quiet_on_a_clean_rebuild(store, capsys) -> None:
    """反负控（别把噪音当读数）：没有跳过 ⇒ 不打印分类与明细。"""
    from agentflow import cli

    _seed(store)
    rc = cli.cmd_rebuild(cli.build_parser().parse_args(_rebuild_args(store.root)))
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "跳过的分类计数" not in text, text
    assert "跳过明细" not in text, text
    assert "已从事件日志重建" in text, text


def test_rebuild_reports_shape_broken_rows_and_does_not_narrow_the_except(store):
    """R-06 的另一半：缺必填字段的行抛的是 `TypeError`，不许把它并进 schema 拒绝。

    取证：`row_from_dict` 对缺参行抛 `TypeError`（dataclass 的形态）——
    若把 `except` 收窄成 `except ValueError`，这一类行会炸穿重建（比静默跳过更坏）。
    这一条同时钉住分类：`shape_broken` 与 `schema_rejected` 各占一格、不许合并
    （合并之后"这一行不合法"与"事件行坏了"就再也分不出来了）。
    """
    _seed(store)
    _append_event(store, {"op": "upsert", "table": "concepts",
                          "row": {"concept_id": "0003"}})  # 缺 name/definition

    out = store.rebuild(backup=False)
    assert out["skipped"] == 1, out
    assert out["skipped_by_reason"] == {"shape_broken": 1}, out["skipped_by_reason"]
    detail = out["skipped_details"][0]
    assert detail["reason"] == "shape_broken" and detail["id"] == "0003", detail
    assert detail["error"].startswith("TypeError:"), detail


def test_rebuild_skip_detail_keys_are_the_documented_ones(store):
    """反真空：明细是空的时候也在（"0 静默丢行"从"一个数"变成"一个可核的空明细"）。

    为什么单列：只在"有跳过"的用例里断言键存在，会让"键被删掉"这件事
    在正常路径上无人管 —— 而正常路径恰恰是最长的那条。
    """
    _seed(store)
    out = store.rebuild(backup=False)
    assert out["skipped"] == 0, out
    assert out["skipped_by_reason"] == {} and out["skipped_details"] == [], out
