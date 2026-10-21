"""`rebuild` 的无损性。

背景（真实缺陷）：`rebuild()` 的事件折叠原本走 `S.row_from_dict()`，而它只保留
dataclass 字段 —— 于是带下划线前缀的诊断/扩展字段（`_keys`、`_quote_check`）
在重建后全部消失。功能上判重还能靠 `doi`/`dedup_key` 兜底，但
"能重建"不应该意味着"重建出更少的信息"：一旦丢字段，事后就无法回答
"当初这条文献是从哪些键命中/被判定为重复的"。

本文件把"无损"固定下来。

## S1r 并表那一笔给这一份加的第二件事（2026-10-10）

`SCHEMA_VERSION=2` 起 `concepts` 不在 `TABLES` 里了，而老盘的事件日志里
`{"table": "concepts"}` 到处都是 ⇒ `rebuild` 必须把它们折进新家
（`statements` + `kind="concept"`，折叠内核 `migrate_concepts`），不是拒掉、
也不是记成"认不出的表"。这一份因此多两部分判据：

- 折叠本身与它的读数（`migrated_concepts` / `migrated_v1_events` /
  `migrated_relations_renumbered` / `migrated_pending_search` /
  `migration_ledger_lines` / `out/migrate-map.jsonl`）；
- 版本容忍的边界：只有 `SCHEMA_VERSION-1` 被容忍，别的版本照旧 fail-closed。

样本本身（`_seed`）里的概念行落新标准 —— `concepts` 已经不是一张能写的表了
（`store.tx(CR.LEGACY_TABLE, …)` 会以"未知表"受控失败），拿它当"通用被测表"的地方
一律换 `statements`。纯函数的折叠规则由
`test_the_concepts_table_folds_into_statements.py` 单独守。
"""

from __future__ import annotations

import json

from agentflow import conceptrows as CR
from agentflow import schema as S
from agentflow import textutil as T
from agentflow.store import Store, StoreError

#: 固定时间戳（与 `conftest` 同一口径：判据不依赖"当前时间"）。
TS = "2026-01-01T00:00:00+00:00"


def _relation_row(cids: list[str], *, rid: str = "0000", lit_id: str = "0000") -> dict:
    """一条合法关系行（`concept_ids` 由调用方给：折叠那一格要拿老概念号喂它）。"""
    return {
        "relation_id": rid, "concept_ids": list(cids), "description": "d",
        "lit_id": lit_id, "page_range": {"start": 1, "end": 1, "label": "p. 1"},
        "quote": "An abelian group is a group.",
        "quote_normalized": "an abelian group is a group",
        "quote_verified": True, "statement": "d",
        "concept_group_key": T.concept_group_key(cids),
        "dedup_key": f"{T.concept_group_key(cids)}::x",
        "status": "active", "duplicate_of": None,
        "created_at": TS, "_quote_check": {"verified": True, "reason": "substring_match"},
    }


def _seed(store: Store) -> None:
    """写一行带诊断字段的文献 + 两行 `kind="concept"` 的命题 + 一行带校验明细的关系。

    S1r 并表那一笔之后 `concepts` 不再是 `TABLES` 里的一张表 ⇒ 这一份样本里的概念行
    按新标准落（`statements` + `kind="concept"`，构造口 `CR.concept_statement`）。
    老表那些行（v1 事件）怎么被折进新家，由
    `test_rebuild_folds_v1_concept_events_into_the_new_standard` 单独钉 ——
    那是另一条路，样本里混进去会让"这次重建重放了几条事件"这件事变糊。
    """
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {
            "lit_id": "0000", "title": "Probe paper", "type": "J", "summary": "",
            "path": None, "processed": True, "source_request_ids": [],
            "dedup_key": "doi:10.1/probe", "doi": "10.1/probe", "year": 2000,
            "authors": [], "venue": None, "language": None,
            "added_at": TS, "download": {},
            "claimed_by": None, "lease_until": None, "mine_attempts": 0,
            "last_mine_error": None,
            "_keys": ["doi:10.1/probe", "title:probe paper|2000", "title:probe paper|*"],
        })
    with store.tx("relations", "statements", actor="test") as tx:
        for sid, label in (("0000", "group"), ("0001", "abelian group")):
            row = CR.concept_statement(stmt_id=sid, label=label, definition="d")
            row.validate()
            tx.upsert("statements", row.to_dict())
        tx.upsert("relations", _relation_row(["0000", "0001"]))


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
             ("literature", "statements", "relations", "search_requests")}
    store.rebuild(backup=False)
    second = {t: (store.data / f"{t}.json").read_bytes() for t in
              ("literature", "statements", "relations", "search_requests")}

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


def _concept_event(cid: str, name: str, definition: str = "", **kw) -> dict:
    """一条 v1 事件里的 `concepts` 行（`schema_version = SCHEMA_VERSION - 1`）。

    为什么需要这一格：`SCHEMA_VERSION=2` 起 `concepts` 不在 `TABLES` 里，而
    真实老盘的事件日志里这种行到处都是 ⇒ 它必须被折进新家。用
    `SCHEMA_VERSION - 1` 而不是写死 `1`：这一份判据要跟着版本号走，
    下一版并表时它自动指"上一版"（写死等于把"容忍哪一版"钉在历史的某一刻）。
    """
    row = {"concept_id": cid, "name": name, "definition": definition,
           "related_concepts": [], "normalized_name": name, "aliases": [],
           "definition_source_lit_id": None, "created_at": TS, "updated_at": TS}
    row.update(kw)
    return {"op": "upsert", "table": "concepts", "row": row,
            "schema_version": S.SCHEMA_VERSION - 1}


def test_rebuild_folds_v1_concept_events_into_the_new_standard(store):
    """S1r：v1 事件里的 `concepts` 行被折进 `statements`，五份读数必须齐全。

    改前必红：表名不在 `TABLES` 里的 upsert 落进 `unrecognized_table` ⇒ 那一行进
    `skipped`，而返回值看起来完全正常（`applied` / `skipped` 都是普通读数）——
    "旧库里的概念"于是以"跳过了 N 行"的形式静默消失，没有人看得出少了东西。
    这一条钉住折叠本身（折出来的行长什么样）与"折了多少"的每一格读数，
    以及逐条改号账真的落到了 `out/migrate-map.jsonl`（账本的意义是"逐条可复算"）。
    """
    with store.tx("relations", actor="test") as tx:
        tx.upsert("relations", _relation_row(["0007", "0008"]))
    _append_event(store, _concept_event("0007", "Moore bound", "Moore 界……",
                                        aliases=["M(k,g)"]))
    _append_event(store, _concept_event("0008", "diameter"))

    out = store.rebuild(backup=False)

    assert out["migrated_v1_events"] == 2, out["migrated_v1_events"]
    assert out["migrated_concepts"] == 2, out
    assert out["migrated_pending_search"] == 1, out
    assert out["migrated_relations_renumbered"] == 2, out
    # 折叠不是跳过：老表那些行一条都不许落进 `skipped`
    assert out["skipped_by_reason"] == {} and out["skipped"] == 0, out["skipped_details"]
    assert any("pending_search" in n for n in out["migrated_notes"]), out["migrated_notes"]

    by_label = {r["label"]: r for r in store.rows("statements")}
    assert set(by_label) == {"Moore bound", "diameter"}, by_label
    assert all(r["kind"] == "concept" for r in by_label.values())
    assert all(r["proof_text"] == "concept:primitive" for r in by_label.values())
    assert by_label["Moore bound"]["statement_full"] == "Moore 界……"
    assert by_label["Moore bound"]["aliases"] == ["M(k,g)"]
    assert by_label["Moore bound"]["status"] == "active"
    # 定义空着的老行 ⇒ 待补标记，不是"定义就是空的"
    assert by_label["diameter"]["status"] == "pending_definition"
    assert "concept:pending_search" in by_label["diameter"]["quote_reason"]

    # 关系表里的老概念号被改写成新号，派生键一并重算
    # （只改 `concept_ids` 的话，迁移出来的库自己就带着一条 `stale_group_key`）
    (rel,) = store.rows("relations")
    new_ids = sorted(r["stmt_id"] for r in by_label.values())
    assert rel["concept_ids"] == new_ids, rel["concept_ids"]
    assert rel["concept_group_key"] == T.concept_group_key(new_ids), rel["concept_group_key"]

    # 折出来的行必须过当前 schema（不是"先折了再说"）
    S.validate_table("statements", {"schema_version": S.SCHEMA_VERSION,
                                    "rows": store.rows("statements")})

    # ---- 逐条改号账（append-only，一行一件事）
    lines = [json.loads(x) for x in
             store.migration_ledger_path.read_text(encoding="utf-8").splitlines()]
    assert out["migration_ledger_lines"] == len(lines), (out["migration_ledger_lines"], lines)
    maps = [x for x in lines
            if x["op"] == "migrate_map" and x.get("kind") == "concept→statement"]
    assert sorted((m["old_id"], m["new_id"]) for m in maps) == [
        ("0007", new_ids[0]), ("0008", new_ids[1])], maps
    summary = [x for x in lines if x.get("kind") == "summary"]
    assert summary and summary[-1]["concepts"] == 2, summary
    assert summary[-1]["relations_changed"] == 2 and summary[-1]["pending_search"] == 1, summary
    renumbered = [x for x in lines if x["op"] == "relation_renumbered"]
    assert len(renumbered) == 2 and all(x["rel_id"] == "0000" for x in renumbered), (
        "改号账指不出是哪一条关系 ⇒ 账本失去'逐条可复算'的意义", renumbered)


def _stale_concept_doc(cid: str = "0007", name: str = "老概念") -> dict:
    """一份迁移前的老文件（`data/concepts.json`）的内容。"""
    return {"schema_version": S.SCHEMA_VERSION - 1, "rows": [
        {"concept_id": cid, "name": name, "definition": "老定义",
         "related_concepts": [], "normalized_name": name, "aliases": [],
         "created_at": TS, "updated_at": TS}]}


def test_rebuild_keeps_the_stale_file_when_the_log_does_not_cover_it(store):
    """三态（老文件）：`backup=False` 不删；日志没覆盖到的行在时，`backup=True` 也不删。

    两条都是"不许不可逆销毁"：

    - `backup=False` 那一支没有备份 ⇒ 删掉就是销毁（返回值里必须如实报 `kept`，
      而不是假装干净）；
    - 老文件里有事件日志里从来没有过的概念号（`F-9` 的已知边界：`rebuild` 的唯一输入
      是日志）⇒ 那些行的唯一副本就在这份文件里，删掉等于把"日志漏掉的那一段"销毁。
      宁可留一个"看起来还是数据库"的文件（它会被 `conceptrows.legacy_present` 点名成
      `stale_file`），也不做不可逆的事。`moved_snapshot_ahead` 是这件事的读数 ——
      不报的话，"老文件为什么没删"就查不出来。
    """
    (store.data / "concepts.json").write_text(
        json.dumps(_stale_concept_doc(), ensure_ascii=False), encoding="utf-8")

    out = store.rebuild(backup=False)
    assert out["moved_stale_files_kept"] == ["concepts.json"], out
    assert out["moved_stale_files_removed"] == [], out
    assert (store.data / "concepts.json").is_file(), "没有备份的那一支不许删数据"

    out2 = store.rebuild(backup=True)
    assert out2["moved_snapshot_ahead"] == {"concepts": ["0007"]}, out2
    assert out2["moved_stale_files_removed"] == [], out2
    assert out2["moved_stale_files_kept"] == ["concepts.json"], out2
    assert (store.data / "concepts.json").is_file(), (
        "日志没覆盖到的那一行只在这份文件里 ⇒ 删它就是不可逆销毁")


def test_rebuild_removes_the_stale_file_once_the_log_covers_it(store):
    """另一半：老文件的行都在事件日志里（v1 事件）⇒ `backup=True` 时删掉它。

    留着一份"看起来还是数据库"的老文件，下一次有人直接读它就拿到迁移前的旧值，
    而这件事没有任何自动判据看得见。删之前必须先抄进 `.backup-*`（否则那是一次
    不可逆的销毁）；而"删掉"不等于"搬完了"，所以顺带钉住那一行真的折进了新家。
    """
    _append_event(store, _concept_event("0007", "老概念", "老定义"))
    (store.data / "concepts.json").write_text(
        json.dumps(_stale_concept_doc(), ensure_ascii=False), encoding="utf-8")

    out = store.rebuild(backup=False)
    assert out["moved_snapshot_ahead"] == {}, out
    assert out["moved_stale_files_kept"] == ["concepts.json"], out
    assert (store.data / "concepts.json").is_file()

    out2 = store.rebuild(backup=True)
    assert out2["moved_stale_files_removed"] == ["concepts.json"], out2
    assert out2["moved_stale_files_kept"] == [], out2
    assert not (store.data / "concepts.json").exists()
    backups = sorted(p for p in store.data.glob(".backup-*") if p.is_dir())
    assert backups and (backups[-1] / "concepts.json").is_file(), (
        "删之前那一份必须已经进了备份目录，否则'删'= 不可逆销毁", backups)
    assert [r["stmt_id"] for r in store.rows("statements")] == ["0000"]
    assert store.rows("statements")[0]["label"] == "老概念"


def test_rebuild_refuses_a_schema_version_other_than_the_previous_one(store):
    """三态（版本）：只有 `SCHEMA_VERSION-1` 被容忍，别的版本照旧 fail-closed。

    `known_old` 那一档（S1r 为 v1 事件开的兼容口）最容易被放宽成"版本号不等于当前
    就折叠"。放宽之后，一个未来版本写的事件会被按当前语义重放并静默改写快照，
    而 `rebuild` 正是灾难恢复的唯一手段 —— 那正是 `F-7`（读期 fail-closed）要挡的事。
    容忍那一半由 `test_rebuild_folds_v1_concept_events_into_the_new_standard` 钉
    （它断言 `migrated_v1_events == 2`：上一版的事件是被折的，不是被拒的）。
    """
    _append_event(store, {"op": "upsert", "table": "literature",
                          "row": {"lit_id": "0000", "title": "T", "type": "J"},
                          "schema_version": S.SCHEMA_VERSION + 1})
    try:
        store.rebuild(backup=False)
    except StoreError as exc:
        text = str(exc)
        assert str(S.SCHEMA_VERSION + 1) in text and str(S.SCHEMA_VERSION) in text, text
        assert "拒绝重建" in text, text
    else:
        raise AssertionError(
            f"schema_version={S.SCHEMA_VERSION + 1} 的事件被照常重放 ⇒ "
            "'拿旧语义解释新数据'没有任何守卫")


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
    # 缺 `stmt_id`（`Statement` 唯一的必填字段）⇒ `row_from_dict` 抛 `TypeError`。
    # 换表说明：`concepts` 已不是 `TABLES` 里的一张表，拿它当"通用被测表"会走
    # `_MOVED_TABLES` 那条折叠路径而不是"形状坏了"这一支 ⇒ 通用重放机制的样本换
    # `statements`（概念行的新家）。
    _append_event(store, {"op": "upsert", "table": "statements",
                          "row": {"origin": "own_result", "label": "没有号"}})
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

    样本换表：`concepts` 已不在 `TABLES` 里（并表那一笔），而"形状坏了"这一支要的是
    当前 schema 的表；`statements` 里唯一没有默认值的字段是 `stmt_id`
    ⇒ 形状坏的那一行必然没有号，`detail["id"]` 因此是空串（不猜一个号出来）。
    "明细点名是哪一行"那一半由上面 `schema_rejected` 那一条钉（它的样本有主键）。
    """
    _seed(store)
    _append_event(store, {"op": "upsert", "table": "statements",
                          "row": {"origin": "own_result", "label": "没有号"}})

    out = store.rebuild(backup=False)
    assert out["skipped"] == 1, out
    assert out["skipped_by_reason"] == {"shape_broken": 1}, out["skipped_by_reason"]
    detail = out["skipped_details"][0]
    assert detail["reason"] == "shape_broken" and detail["table"] == "statements", detail
    assert detail["id"] == "", detail
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
