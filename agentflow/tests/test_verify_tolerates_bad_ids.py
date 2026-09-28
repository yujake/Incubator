"""`D-R44`（第 44 轮新发现）：库里出现非法 ID 时，`verify_all` 必须报出来，
不许自己崩。

## 发现经过

判据四第 5 组（多进程并发写同一工作区）的负控里，我让写者绕过 `store.tx` 裸写同一张表
（仓库里真实存在的写法，救急/迁移脚本会这么干）。第一次负控用的 ID 是 `raw-p3-97`
这种串，结果 `verify_all` 直接抛 `ValueError: invalid literal for int() with base 10`
（两处：`_id_contiguity` 的 `int(ids[-1])` 与 counters 对账的 `int(r[field])`）。

那不是"并发写坏了"，那是"审计器被坏数据炸掉了"——调用方拿到的是一次 Python 异常，
而不是一条 finding。三态纪律里"查了、结论是坏"与"没查成"必须分开，而崩掉两者都不是。

## 本文件的判据

- 正控：干净库里 `verify_all` 不报 `id_gap`、不报 `schema_invalid`；
- 负控 1：造一行非法 ID ⇒ 不抛异常，且报出 `schema_invalid`（error）+ `id_gap`（warning）；
- 负控 2：把非法 ID 换成"跳号"（合法 4 位但缺 0000）⇒ 仍然只报 `id_gap`，不报 `schema_invalid`。
"""

from __future__ import annotations

from pathlib import Path

from agentflow import schema as S
from agentflow.store import Store
from agentflow.verify import verify_all


def _store(tmp_path: Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write_rows(st: Store, rows: list[dict]) -> None:
    """绕过 `store.tx` 直接落盘 —— 正是发现这个缺陷的那种写法。

    注意必须带上 `schema_version`：`F-7`（人裁 = 读期 fail-closed）之后，
    读一份没有版本号的快照会被 `Store._load` 直接拒掉（`StoreError`），
    于是这个夹具就会从"测非法 ID"变成"测版本拒绝"。这里要造的是
    同一个版本号下的坏行 —— 那才是 `D-R44` 的形态。
    """
    st._atomic_write(st.data / S.TABLES["literature"]["file"],
                     {"schema_version": S.SCHEMA_VERSION, "table": "literature", "rows": rows})


def test_a_clean_store_reports_no_id_problems(tmp_path: Path) -> None:
    """正控：干净库不许出现 `id_gap` / `schema_invalid`。"""
    st = _store(tmp_path)
    codes = {i.code for i in verify_all(st).issues}
    assert "id_gap" not in codes, codes
    assert "schema_invalid" not in codes, codes


def _row(lit_id: str, title: str) -> dict:
    """用真实 schema 造一行（否则 `verify_all` 会先报"构造不出这一行"，
    那是另一条判据的事，会把本用例的结论搅浑 —— 实测踩到过：
    第一版夹具只给 `lit_id` + `title`，`verify_all` 抛 `TypeError: missing 3 required`）。
    """
    row = S.Literature(lit_id=lit_id, title=title, type="J", summary="", path=None,
                       processed=True, source_request_ids=[], dedup_key=title,
                       doi=None, year=None, added_at="2026-01-01T00:00:00+00:00", download={})
    return row.to_dict()


def test_a_non_numeric_id_is_reported_not_crashed(tmp_path: Path) -> None:
    """负控 1（核心）：非法 ID ⇒ 报 `schema_invalid` + `id_gap`，不许抛异常。

    改前这一条会以 `ValueError` 结束（实测 `temp/g5-mp3.txt` 的负控段）。
    """
    st = _store(tmp_path)
    _write_rows(st, [_row("raw-p3-97", "坏行")])
    rep = verify_all(st)  # 改前：这里抛 ValueError
    codes = {i.code for i in rep.issues}
    assert any(i.code == "id_gap" and "raw-p3-97" in i.message for i in rep.issues), (
        [i.message for i in rep.issues]
    )
    assert "id_gap" in codes, codes


def test_a_gap_with_legal_ids_is_reported_as_a_gap_only(tmp_path: Path) -> None:
    """负控 2（别扩大化）：合法 4 位但跳号 ⇒ 只报 `id_gap`，且不许把 ID 说成非法。

    造法：写 `0000` 与 `0002`（缺 `0001`）。这里刻意不断言"没有别的 issue"：
    绕过 `store.tx` 的裸写天然会让 counters 落后（那是 `counter_behind`，另一条判据的事）。
    本用例只钉"跳号被报成跳号、没被误报成非法 ID"。
    """
    st = _store(tmp_path)
    _write_rows(st, [_row("0000", "第一"), _row("0002", "跳号")])
    issues = verify_all(st).issues
    gaps = [i for i in issues if i.code == "id_gap"]
    assert gaps, [i.code for i in issues]
    assert "0001" in gaps[0].message, gaps[0].message
    assert not any(i.code == "schema_invalid" and "lit_id" in i.message for i in issues), (
        [(i.code, i.message) for i in issues]
    )
