# -*- coding: utf-8 -*-
"""文献库那一面的判据（D-57：UI 侧的文献库页从来没有读数端）。

## 改前的现场

`webui/readers.py` 里没有任何文献读数函数，`GET /api/literature` 不在路由表里；
前端「文献库」那格挂着一句 reason「今天也没有别的端点给它」。所以页面读不出不是
坏了，是从来没有接 —— 这一份判据就是那条从未存在过的接线的判据。

## 这一面唯一的业务口径（业主逐字）

「文献库按照正式入库的算，显示时可以显示被哪些定理证明使用，如果分不清哪些真入库、
哪些待入库（这个没读的必要），这是A侧实现问题」。

2026-10-24 追裁（原话「老工作区就是读不出来」）：判据只有候选台账那一格
（`lit_candidates.status == "admitted"`），不退回 `literature.matched`；没有候选台账的
工作区整面记「读不出来」（`count` 是 null，不是 0）。

三句话落成三条硬约束，本文件的 `c` / `d` / `e` 各守一条：

1. 只显示正式入库的（判不出的不显示，但要在 `problems` 里留一条 `admission_undecidable`）；
2. 每条显示出来的都要能读出「被哪些命题／哪一份证明用过」；
3. 「读不出来」与「台账里 0 条」与「没有这个端点」是三档，不许折成一档。

## 六条判据与「改前红」

| 判据 | 它守的是 | 改前红的样子 |
|---|---|---|
| a `test_a_the_five_admitted_rows_carry_every_declared_field` | 5 条入库夹具：每条都给全 `LibraryWork` 声明的键；外壳是五键；端点真的只挂在只读面上 | 没有 `library_face` ⇒ AttributeError |
| b `test_b_a_readable_ledger_with_zero_admitted_is_zero_not_unknown` | 台账与候选表都在用、这一档 0 条入库 ⇒ `computed` + 计数 0（正控：不是 unknown） | 同上 |
| c `test_c_a_missing_or_broken_table_is_unknown_and_never_zero` | 表不在盘上 / 坏 JSON ⇒ `unknown` + reason，计数是 `None`（负控：反「折成 0」） | 同上 |
| d `test_d_two_dependencies_pointing_at_a_work_list_the_stmt_and_proof_no` | 被引反查：2 条 dependencies 指向某一篇 ⇒ 列出 stmt 号与 proof_no | 同上 |
| e `test_e_only_admitted_candidates_are_listed_and_no_ledger_is_not_zero` | 只认 admitted（3 admitted + 2 pending ⇒ 只显示 3 条）；无候选台账 ⇒ `count is None` + reason 写「候选台账」；判不出的那篇留 `admission_undecidable` | 同上 |
| f `test_f_the_two_judgments_are_not_vacuous` | 反真空：把反查打桩成空 ⇒ d 必红；把「只算入库」打桩成全收 ⇒ e 必红 | 同上 |

## 为什么把 d / e 的断言抽成 `_x_problems` 纯函数

f 那两条反真空不能靠"把判据文件抄一份改一改"来实现：那样注射的是另一条判据。
所以 d / e 各自只有一行 `assert _x_problems(view) == []`，而 f 拿同一批纯函数跑
被注射过的读数 —— 打桩生效时它们必须吐出问题。这就是「这条判据不是在真空里绿」。

## 为什么字段名一律从 `readers.ts_fields()` 取

键名只有一个来源：`readers._TS_TYPES`（生成物 `ui/src/types.ts` 也从它出）。判据里
再抄一份字段表，等于给"声明与读数一致"这件事造第二个口径 —— 那正是契约判据 C
要防的形态。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Mapping

import pytest

from agentflow import schema as S
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]

#: 本模块声明的字段表（唯一来源；见文件头最后一段）。
FIELDS = R.ts_fields()

#: 夹具里的固定时间戳。
TS = "2026-10-24T00:00:00+08:00"

#: 这一条端点在路由表里的那一行（改前它不存在）。
ROUTE = ("GET", "/api/literature", "handle_library")


# ====================================================================== 夹具
def _workspace(tmp: pathlib.Path, name: str = "ws") -> tuple[pathlib.Path, Store]:
    """一份表都在盘上的空工作区（`Store.init` 建表，不手写 JSON）。"""
    root = tmp / name
    root.mkdir()
    store = Store(root)
    store.init()
    return root, store


def _lit(store: Store, lit_id: str, *, title: str, **kw: Any) -> dict:
    """写一条合法的 `literature` 行（走 schema 的 `validate`，防夹具本身不合法）。"""
    download = kw.pop("download", None) or {"status": "skipped"}
    row = S.Literature(
        lit_id=lit_id, title=title, type=str(kw.pop("type", "J")), summary="夹具：一句话摘要",
        path=kw.pop("path", None), processed=True,
        dedup_key=str(kw.pop("dedup_key", f"title:{title.lower()}|*")),
        doi=kw.pop("doi", None), year=kw.pop("year", 2020),
        authors=list(kw.pop("authors", ())), added_at=TS, download=download,
        pages=str(kw.pop("pages", "")), matched=str(kw.pop("matched", "")),
        claimed_by=kw.pop("claimed_by", None),
        mine_attempts=int(kw.pop("mine_attempts", 0)),
        last_mine_error=kw.pop("last_mine_error", None),
    )
    assert not kw, f"夹具给了 Literature 没有的字段：{sorted(kw)}"
    row.validate()
    with store.tx("literature", actor="test", note="library face fixture") as tx:
        tx.upsert("literature", row.to_dict(), note="library face fixture")
    return row.to_dict()


def _candidate(store: Store, slot: str, lit_id: str | None, *,
               status: str = "admitted") -> None:
    """给某一篇补一条候选行（`lit_candidates` 那五档状态之一）。"""
    row = S.LitCandidate(slot=slot, batch=1, status=status, title=f"夹具候选 {slot}",
                         request_id="r-000001", lit_id=lit_id,
                         admitted_at=(TS if status == "admitted" else ""))
    row.validate()
    with store.tx("lit_candidates", actor="test", note="library face fixture") as tx:
        tx.upsert("lit_candidates", row.to_dict(), note="library face fixture")


def _empty_candidates_table(root: pathlib.Path) -> None:
    """把候选表写成"在盘上、但一行都没有"（业主口径的「有表但一行候选都没有」）。"""
    (root / "data" / "lit_candidates.json").write_text(
        json.dumps({"schema_version": S.SCHEMA_VERSION, "rows": []}, ensure_ascii=False) + "\n",
        encoding="utf-8")


def _stmt(store: Store, stmt_id: str, *, lit_id: str = "", label: str = "") -> dict:
    """写一条合法命题行；`lit_id` 非空就是「这一篇文献里的命题」（引用侧）。"""
    row = S.Statement(
        stmt_id=stmt_id, origin=("external_lit" if lit_id else "own_result"), kind="theorem",
        label=label or f"夹具命题 {stmt_id}", statement_text="短版命题",
        statement_full="若假设成立，则结论成立（夹具：含完整假设）",
        proof_text="Proof. 夹具里的一段逐字证明。",
        source_lit_id=(lit_id or None), quote_verified=None,
        quote_reason="夹具：还没有做逐字回验", evidence_kind="heuristic",
        status="active", created_at=TS)
    row.validate()
    with store.tx("statements", actor="test", note="library face fixture") as tx:
        tx.upsert("statements", row.to_dict(), note="library face fixture")
    return row.to_dict()


def _dep(store: Store, dep_id: str, *, used_by: str, lit_id: str, label: str = "") -> dict:
    """写一条合法依赖行：`used_by` 指的是一条命题（`#pN` 可选），来源是某一篇文献。"""
    row = S.Dependency(dep_id=dep_id, used_by=used_by, kind="theorem",
                       label=label or f"夹具依赖 {dep_id}", status="closed",
                       source_lit_id=lit_id, created_at=TS, created_by="agent-G")
    row.validate()
    with store.tx("dependencies", actor="test", note="library face fixture") as tx:
        tx.upsert("dependencies", row.to_dict(), note="library face fixture")
    return row.to_dict()


def _write_library_file(root: pathlib.Path, rel: str, text: str = "夹具全文\n") -> None:
    """在 `library/` 下落一份文件（下载落地那一格要去盘上核对它）。

    按字节写：`write_text` 在 Windows 上会把 "\\n" 翻成 "\\r\\n"，而字节数是判据
    （与 `conftest.write_paper` 同一条口径：夹具自己先把字节定死）。
    """
    path = root / "library" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


# ====================================================================== 五条入库夹具
def _five_admitted(tmp: pathlib.Path) -> pathlib.Path:
    """5 条都算正式入库的文献，覆盖「下载落地」的三档与两种被引形态。

    - `000000`：下载 ok 且文件真的在盘上；被 1 条命题引用（via statement）；
    - `000001`：`download.status=ok` 而盘上没有那份文件（→ 落地=absent，且进 problems）；
    - `000002`：`download.status=skipped`、没有 path（→ 落地=absent，但没有"声称 ok"的问题）；
    - `000003`：`path` 指的是 `library/` 下的一个目录（→ 落地=unreadable：读不到字节）；
    - `000004`：下载失败（→ 落地=absent）；被 1 条第 2 号证明的依赖引用（via dependency）。
    """
    root, store = _workspace(tmp, "five")
    _write_library_file(root, "000000/paper.pdf")
    (root / "library" / "000003").mkdir(parents=True, exist_ok=True)
    _lit(store, "000000", title="The Sylow Theorems", authors=("甲", "乙"),
         doi="10.2478/v10037-007-0018-3", path="000000/paper.pdf",
         download={"status": "ok", "bytes": 11, "url": "https://example.org/a"},
         mine_attempts=2, claimed_by="agent-B")
    _lit(store, "000001", title="A Reordering of the Sylow Theorems",
         path="000001/missing.pdf", download={"status": "ok", "bytes": 7},
         last_mine_error="no_fulltext_this_time")
    _lit(store, "000002", title="Sylow subgroups of index 2 in their normalizers",
         download={"status": "skipped", "error": "no_local_path"})
    _lit(store, "000003", title="Sylow Theorems", path="000003",
         download={"status": "ok", "bytes": 0}, pages="45-46")
    _lit(store, "000004", title="Group actions and Sylow", path=None,
         download={"status": "failed", "error": "HTTP 404"})
    for slot, lid in (("000000", "000000"), ("000001", "000001"), ("000002", "000002"),
                      ("000003", "000003"), ("000004", "000004")):
        _candidate(store, slot, lid)
    _stmt(store, "000001", lit_id="000000", label="Theorem 1 (§0)")
    _dep(store, "000000", used_by="stmt:000002#p2", lit_id="000004",
         label="第二条证明路径用到这一篇")
    return root


# ====================================================================== a
def test_a_the_five_admitted_rows_carry_every_declared_field(tmp_path: pathlib.Path) -> None:
    """a：5 条入库夹具的每个字段都在，且与 `_TS_TYPES` 的声明逐键相同。

    三件事一起钉：
    1. 外壳恰好是那五键（`checked` / `state` / `reason` / `data` / `problems`）；
    2. `data`、每条 `LibraryWork`、每条 `LibraryUse`、每条 problem 的键集合 == 声明；
    3. 端点真的挂在只读面上（路由表里那一行在、处理器在、没有配对的 POST）。
    """
    root = _five_admitted(tmp_path)
    view = R.library_face(root)

    # 1. 五键外壳（不多不少）。
    assert set(view) == set(FIELDS["LibraryView"]), (sorted(view), FIELDS["LibraryView"])
    assert sorted(FIELDS["LibraryView"]) == ["checked", "data", "problems", "reason", "state"]
    assert view["checked"] is True
    assert view["state"] == "computed", view["state"]
    assert view["reason"] == "", view["reason"]

    # 2. data 与每一条行的键集合。
    data = view["data"]
    assert isinstance(data, Mapping), data
    assert set(data) == set(FIELDS["LibraryData"]), (
        "data 的键与声明不同：", sorted(set(data) ^ set(FIELDS["LibraryData"])))
    assert data["rows_total"] == 5, data["rows_total"]
    assert data["count"] == 5, data["count"]
    works = data["works"]
    assert len(works) == 5, [w.get("lit_id") for w in works]
    for work in works:
        assert set(work) == set(FIELDS["LibraryWork"]), (
            work.get("lit_id"), sorted(set(work) ^ set(FIELDS["LibraryWork"])))
        assert work["admitted"] is True, work
        assert isinstance(work["authors"], list), work["authors"]
        assert isinstance(work["uses"], list), work["uses"]
        assert work["uses_count"] == len(work["uses"]), work
        for use in work["uses"]:
            assert set(use) == set(FIELDS["LibraryUse"]), sorted(use)
    # 作者与 DOI 是逐字透传的（不是自己拼的字符串）。
    by_id = {w["lit_id"]: w for w in works}
    assert by_id["000000"]["authors"] == ["甲", "乙"], by_id["000000"]["authors"]
    assert by_id["000000"]["doi"] == "10.2478/v10037-007-0018-3"
    assert by_id["000000"]["claimed_by"] == "agent-B"
    assert by_id["000000"]["mine_attempts"] == 2
    assert by_id["000001"]["last_mine_error"] == "no_fulltext_this_time"
    assert by_id["000003"]["pages"] == "45-46"

    # 3. 下载落地三态全都在（在 / 不在 / 读不到），且不是一个布尔。
    states = {w["download_state"] for w in works}
    assert states == {"present", "absent", "unreadable"}, states
    assert by_id["000000"]["download_state"] == "present"
    assert by_id["000000"]["download_bytes"] == len("夹具全文\n".encode("utf-8"))
    assert by_id["000001"]["download_state"] == "absent"
    assert by_id["000003"]["download_state"] == "unreadable"
    assert by_id["000003"]["download_bytes"] is None

    # 4. problems 的每条也是声明过的形状；"声称 ok 而盘上没有"必须留痕。
    assert view["problems"], "000001 声称 download.status=ok 而盘上没有那份文件 ⇒ 必须留一条"
    for problem in view["problems"]:
        assert set(problem) == set(FIELDS["LibraryProblem"]), sorted(problem)
    codes = {p["code"] for p in view["problems"]}
    assert "download_claimed_but_absent" in codes, codes

    # 5. 端点：只读面里真有那一行，处理器真的登记过，而且没有配对的 POST。
    assert ROUTE in R.ROUTES, [row for row in R.ROUTES if "literature" in row[1]]
    assert R.HANDLERS.get("handle_library") is R.handle_library
    from agentflow.webui import routes as RT

    assert RT.match("GET", "/api/literature") is not None
    assert RT.match("POST", "/api/literature") is None, "这条端点必须是只读的"
    assert "POST" not in {m for m, p, _h in R.ROUTES if p == "/api/literature"}


# ====================================================================== b
def test_b_a_readable_ledger_with_zero_admitted_is_zero_not_unknown(
        tmp_path: pathlib.Path) -> None:
    """b（正控）：候选台账在用、但这一档里 0 条入库 ⇒ 查过了 + 计数 0，不是 unknown。

    改后（业主 2026-10-24 追裁「老工作区就是读不出来」）这一条的落点换了：
    「空表 + 空候选表」不再是「0 条」，而是读不出来（见 e 的 b 段）。所以正控必须建在
    "判据真的能用"的工作区上 —— 否则 0 与 unknown 就分不开了。夹具还故意把 `matched`
    写成 `exact` / `partial`：改前那一版会因此把它们算成入库，改后必须一条都不显示。
    """
    # b1：文献台账 0 行，候选表在用（1 条 pending）⇒ 读到了，里面 0 条。
    root, store = _workspace(tmp_path, "zero-rows")
    _candidate(store, "000000", None, status="pending")
    view = R.library_face(root)
    assert view["checked"] is True, view["reason"]
    assert view["state"] == "computed", view["state"]
    assert view["reason"] == "", view["reason"]
    data = view["data"]
    assert data["rows_total"] == 0, data["rows_total"]
    assert data["count"] == 0, "0 条入库是数字 0，不是 None，也不是 unknown"
    assert data["works"] == [], data["works"]
    assert data["undecidable"] == 0, data["undecidable"]
    assert view["problems"] == [], view["problems"]

    # b2：文献台账 2 行、两篇的候选都还在 pending（判得出来：没入库）⇒ 显示 0 条。
    root2, store2 = _workspace(tmp_path, "zero-admitted")
    _lit(store2, "000000", title="命中校验通过、候选还在 pending", matched="exact")
    _lit(store2, "000001", title="同上（partial）", matched="partial")
    _candidate(store2, "000000", "000000", status="pending")
    _candidate(store2, "000001", "000001", status="pending")
    view2 = R.library_face(root2)
    assert view2["state"] == "computed", view2["state"]
    assert view2["data"]["rows_total"] == 2, view2["data"]["rows_total"]
    assert view2["data"]["count"] == 0, "pending 不是入库，一条都不该显示"
    assert view2["data"]["undecidable"] == 0, "pending 是判得出来的，不算判不出"
    assert [p["code"] for p in view2["problems"]] == [], view2["problems"]


# ====================================================================== c
def test_c_a_missing_or_broken_table_is_unknown_and_never_zero(tmp_path: pathlib.Path) -> None:
    """c（负控）：表不在盘上 / 表是坏 JSON ⇒ `state="unknown"` + reason，计数 `None`。

    反的就是"折成 0"那一档：`count=0` 会让页面说"库里一篇文献都没有"，而真相是
    "这一面根本没读成"。两档在读数上必须一眼分得开。
    """
    missing, _st1 = _workspace(tmp_path, "missing")
    (missing / "data" / "literature.json").unlink()
    broken, _st2 = _workspace(tmp_path, "broken")
    (broken / "data" / "literature.json").write_text("{ 这不是 JSON\n", encoding="utf-8")

    for name, root in (("表不在盘上", missing), ("坏 JSON", broken)):
        view = R.library_face(root)
        assert view["checked"] is False, (name, view)
        assert view["state"] == "unknown", (name, view["state"])
        assert view["reason"] != "", (name, "unknown 必须给 reason")
        data = view["data"]
        assert data["count"] is None, (name, "不许折成 0")
        assert data["rows_total"] is None, (name, data["rows_total"])
        assert data["works"] == [], (name, data["works"])
        codes = {p["code"] for p in view["problems"]}
        assert "literature_unreadable" in codes, (name, codes)
        # 负控的负控：这条读数不许是"读到了 0 行"。
        assert data["count"] != 0, name


# ====================================================================== d
def _d_workspace(tmp: pathlib.Path, name: str = "cited") -> pathlib.Path:
    """一篇入库文献被 2 条 dependencies 用（一条 canonical、一条第 2 号证明）。"""
    root, store = _workspace(tmp, name)
    _lit(store, "000000", title="被两条依赖引用的那一篇", doi="10.1000/cited")
    _candidate(store, "000000", "000000")
    _stmt(store, "000001", label="用了这一篇的定理")
    _dep(store, "000000", used_by="stmt:000001", lit_id="000000",
         label="第一条证明路径用到这一篇")
    _dep(store, "000001", used_by="stmt:000001#p2", lit_id="000000",
         label="第二条证明路径用到这一篇")
    return root


def _d_problems(view: Mapping[str, Any]) -> list[str]:
    """d 的断言（纯函数：f 会拿被注射过的读数再来问它一次）。"""
    problems: list[str] = []
    works = list((view.get("data") or {}).get("works") or [])
    if len(works) != 1:
        return [f"该只有 1 条入库文献，实际 {[w.get('lit_id') for w in works]}"]
    work = works[0]
    uses = list(work.get("uses") or [])
    got = {(str(u.get("stmt_id")), int(u.get("proof_no") or 0), str(u.get("via")))
           for u in uses}
    for want in (("000001", 1, "dependency"), ("000001", 2, "dependency")):
        if want not in got:
            problems.append(f"被引反查少了一条：{want}（读到 {sorted(got)}）")
    if work.get("uses_count") != len(uses):
        problems.append(f"uses_count={work.get('uses_count')} 与 uses 的长度 {len(uses)} 不符")
    if any(str(u.get("via")) != "dependency" for u in uses):
        problems.append(f"这两条依赖该全记成 dependency：{sorted(got)}")
    return problems


def test_d_two_dependencies_pointing_at_a_work_list_the_stmt_and_proof_no(
        tmp_path: pathlib.Path) -> None:
    """d：2 条 dependencies 指向某一篇 ⇒ 那一条列出 stmt 号与 proof_no（1 与 2 各一条）。

    `proof_no` 不许折成一个数：多证明模型下 `stmt:000001` 与 `stmt:000001#p2` 是
    两条不同的证明路径，界面要能让读的人看出"两条路径都用了这一篇"。
    """
    view = R.library_face(_d_workspace(tmp_path))
    assert _d_problems(view) == [], _d_problems(view)
    works = view["data"]["works"]
    assert works[0]["uses"][0]["used_by"] in {"stmt:000001", "stmt:000001#p2"}, works[0]["uses"]
    assert view["data"]["uses_tri"] == R.TRI_COMPUTED, view["data"]["uses_tri"]


# ====================================================================== e
def _e_mixed(tmp: pathlib.Path, name: str = "mixed") -> pathlib.Path:
    """3 条 admitted + 2 条 pending：只有前者算正式入库。

    两条 pending 的文献刻意写成 `matched="exact"`：改前那一版（有 matched 退回分支）
    会把它们算进来 —— 这一格就是「只认候选台账」那条裁定的注射点。
    """
    root, store = _workspace(tmp, name)
    for lid in ("000000", "000001", "000002"):
        _lit(store, lid, title=f"入库的 {lid}")
        _candidate(store, lid, lid, status="admitted")
    for lid in ("000003", "000004"):
        _lit(store, lid, title=f"还在 pending 的 {lid}", matched="exact")
        _candidate(store, lid, lid, status="pending")
    return root


def _e_mixed_problems(view: Mapping[str, Any]) -> list[str]:
    """e-a 的断言（纯函数：f 会拿被注射过的读数再来问它一次）。"""
    problems: list[str] = []
    data = view.get("data") or {}
    ids = [str(w.get("lit_id")) for w in (data.get("works") or [])]
    if ids != ["000000", "000001", "000002"]:
        problems.append(f"只该显示 3 条 admitted，实际 {ids}（pending 不算入库）")
    if data.get("count") != 3:
        problems.append(f"count 该是 3，实际 {data.get('count')!r}")
    if any(w.get("admitted") is not True for w in (data.get("works") or [])):
        problems.append("显示出来的每一条都必须 admitted=true")
    codes = [str(p.get("code")) for p in (view.get("problems") or [])]
    if "admission_undecidable" in codes:
        problems.append("pending 是判得出来的（没入库），不该记 admission_undecidable")
    if data.get("undecidable") != 0:
        problems.append(f"undecidable 该是 0（没有一个判不出），实际 {data.get('undecidable')!r}")
    return problems


def _e_orphan(tmp: pathlib.Path, name: str = "orphan") -> pathlib.Path:
    """候选表在用，但有一篇文献在候选台账里根本没有行 ⇒ 判不出 ⇒ 不显示 + 留痕。"""
    root, store = _workspace(tmp, name)
    for lid in ("000000", "000001"):
        _lit(store, lid, title=f"有候选行的 {lid}")
        _candidate(store, lid, lid, status="admitted")
    _lit(store, "000002", title="候选台账里没有它（但 matched 是 exact）", matched="exact")
    return root


def _e_orphan_problems(view: Mapping[str, Any]) -> list[str]:
    """e-a2 的断言：判不出的那一条不显示，但要有一条 admission_undecidable 点名它。"""
    problems: list[str] = []
    data = view.get("data") or {}
    ids = [str(w.get("lit_id")) for w in (data.get("works") or [])]
    if ids != ["000000", "000001"]:
        problems.append(f"只该显示有候选行的两条，实际 {ids}")
    entries = [p for p in (view.get("problems") or [])
               if str(p.get("code")) == "admission_undecidable"]
    if len(entries) != 1:
        problems.append(f"problems 该有且只有一条 admission_undecidable，实际 {len(entries)}")
    elif "000002" not in str(entries[0].get("detail") or ""):
        problems.append("那条 admission_undecidable 没点名判不出的那一篇（000002）")
    if data.get("undecidable") != 1:
        problems.append(f"undecidable 该是 1，实际 {data.get('undecidable')!r}")
    return problems


def _e_no_ledger(tmp: pathlib.Path, name: str, *, mode: str) -> pathlib.Path:
    """候选台账缺失 / 空表：两种形态都得记「读不出来」。

    两条文献刻意写成 `matched=exact/partial` —— 业主 2026-10-24 的裁定是"那一格不再是
    判据"，所以这一档必须是读不出来，而不是"退回 matched 算出 2 条"。
    """
    root, store = _workspace(tmp, name)
    _lit(store, "000000", title="甲（matched=exact）", matched="exact")
    _lit(store, "000001", title="乙（matched=partial）", matched="partial")
    if mode == "absent":
        (root / "data" / "lit_candidates.json").unlink()
    elif mode == "empty":
        _empty_candidates_table(root)
    else:  # pragma: no cover - 夹具写错时当场炸，而不是静默测了个别的
        raise AssertionError(f"未知的 mode：{mode!r}")
    return root


def _e_no_ledger_problems(view: Mapping[str, Any]) -> list[str]:
    """e-b 的断言：没有候选台账 ⇒ 读不出来（count 是 null，不是 0）。"""
    problems: list[str] = []
    data = view.get("data") or {}
    if view.get("checked") is not True:
        problems.append(f"台账本身读到了 ⇒ checked 该是 true，实际 {view.get('checked')!r}")
    if view.get("state") == "computed":
        problems.append("没有候选台账却记成了 computed ⇒ 把读不出来折成了 0 条")
    if data.get("count") is not None:
        problems.append(f"这一档 count 必须是 null，实际 {data.get('count')!r}")
    if data.get("count") == 0:
        problems.append("这一档不许用 0 条冒充读不出来")
    if "候选台账" not in str(view.get("reason") or ""):
        problems.append(f"reason 没写「候选台账」那一句：{view.get('reason')!r}")
    if list(data.get("works") or []):
        problems.append("读不出来的那一档不许显示任何一条")
    if data.get("rows_total") != 2:
        problems.append(f"台账本身读到了 ⇒ rows_total 该是 2，实际 {data.get('rows_total')!r}")
    return problems


def test_e_only_admitted_candidates_are_listed_and_no_ledger_is_not_zero(
        tmp_path: pathlib.Path) -> None:
    """e：只认候选台账那一格 —— 三件事一起钉。

    a) 有候选表、其中 3 条 admitted、2 条 pending ⇒ 只显示那 3 条（改前那一版会把
       pending 也算进来，或在没有候选行时退回 `matched`）；
    b) 没有候选台账（表不在盘上 / 表在但一行都没有）⇒ `count is None`、`state` 不是
       computed、`reason` 写清「候选台账」 —— 负控：反"折成 0 条"；
    a2) 候选表在用、但某篇在台账里没有行 ⇒ 不显示，且 `problems` 点名它
       （业主口径：判不出是 A 侧的实现问题，留痕不拦门）。
    """
    view = R.library_face(_e_mixed(tmp_path))
    assert _e_mixed_problems(view) == [], _e_mixed_problems(view)
    # 显示出来的每一条都带得来"凭什么算入库"（唯一那一格）。
    bases = {str(w["admission_basis"]) for w in view["data"]["works"]}
    assert bases == {R.ADMISSION_BASIS_CANDIDATE}, bases

    orphan = R.library_face(_e_orphan(tmp_path))
    assert _e_orphan_problems(orphan) == [], _e_orphan_problems(orphan)

    for mode in ("absent", "empty"):
        root = _e_no_ledger(tmp_path, f"no-ledger-{mode}", mode=mode)
        got = R.library_face(root)
        assert _e_no_ledger_problems(got) == [], (mode, _e_no_ledger_problems(got))
        # 业主那句原话逐字在 reason 里（读的人不必猜这一档为什么不算 0）。
        assert R.LIBRARY_NO_LEDGER_REASON in str(got["reason"]), (mode, got["reason"])


# ====================================================================== f
def _no_uses(**_kw: Any) -> dict[str, list[dict]]:
    """桩：反查一律返回空（"这一篇谁都没用过"）。"""
    return {}


def _accept_everything(_row: Mapping[str, Any], **_kw: Any) -> tuple[bool, str]:
    """桩：入库判据一律说 True（"全收"）。"""
    return True, "stub"


def test_f_the_two_judgments_are_not_vacuous(tmp_path: pathlib.Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """f（反真空）：两条判据不是摆设 —— 打桩之后 d / e 必须当场红。

    注射点就是 `library_face` 用的那两个模块级函数（它们是这一面唯一的两个判断）：
    `_library_uses`（被引反查）与 `_library_admission`（入库判据）。
    """
    # 正控：没打桩时两条都绿（否则下面那两条"红了"说明不了任何事）。
    view_d = R.library_face(_d_workspace(tmp_path, "d-clean"))
    view_e = R.library_face(_e_mixed(tmp_path, "e-clean"))
    assert _d_problems(view_d) == [], _d_problems(view_d)
    assert _e_mixed_problems(view_e) == [], _e_mixed_problems(view_e)

    # ① 把反查打桩成空 ⇒ d 必红。
    with monkeypatch.context() as mp:
        mp.setattr(R, "_library_uses", _no_uses)
        injected = R.library_face(_d_workspace(tmp_path, "d-stubbed"))
    assert _d_problems(injected), "把反查打桩成空，d 还绿着 ⇒ 那条判据在真空里"

    # ② 把"只算入库"打桩成全收 ⇒ e 必红（pending 那两条会冒出来）。
    with monkeypatch.context() as mp:
        mp.setattr(R, "_library_admission", _accept_everything)
        injected = R.library_face(_e_mixed(tmp_path, "e-stubbed"))
    assert _e_mixed_problems(injected), "把『只算入库』打桩成全收，e 还绿着 ⇒ 那条判据在真空里"
