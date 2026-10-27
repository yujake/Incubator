"""A 智能体：幂等、下载失败不阻塞、provider 异常、尝试次数耗尽（DESIGN.md §5）。

2026-10-26（Q16）之后本文件有一个共同的形状变化，逐条写在用例的 docstring 里：
`run_once` 走 `admission_plan(require_judged=True)`，所以自动链路一条都不入库，
候选停在待裁（`lit_candidates` 的 `pending`）；入库只有一条路 —— A 逐条判收
（`lit.stage_add` 把 relevance 补进原槽，再 `lit.admit`）。于是"跑一遍就进库 N 条"
这类断言全部改成"入库 0 + 待裁 N"，或改在判收之后量。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentflow import schema as S
from agentflow.agent_a import AgentA
from agentflow.fetch import FetchResult
from agentflow.providers import Candidate

from conftest import add_request, set_request_done


# --------------------------------------------------------------------------- 替身


class StubProvider:
    """确定性 provider 替身：返回固定候选，或按需抛异常。"""

    name = "stub"

    def __init__(self, candidates=(), error: Exception | None = None):
        self.candidates = list(candidates)
        self.error = error
        self.calls: list[tuple] = []

    def search(self, topic, mode, description, limit):
        self.calls.append((topic, mode, description, limit))
        if self.error is not None:
            raise self.error
        return list(self.candidates)


class OkDownloader:
    """总是成功的下载器替身：落一个真实文件，返回真实 sha256（不联网）。"""

    def __init__(self):
        self.calls: list[str] = []

    def download(self, url: str, dest_dir: Path, filename_hint: str) -> FetchResult:
        self.calls.append(url)
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{filename_hint or 'file'}.txt"
        target.write_text("An abelian group is a group in which the commutative law holds.", encoding="utf-8")
        data = target.read_bytes()
        return FetchResult(
            ok=True,
            path=str(target),
            http_status=200,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            error=None,
        )


class FailingDownloader:
    """总是失败的下载器替身（不联网）。"""

    def download(self, url: str, dest_dir: Path, filename_hint: str) -> FetchResult:
        # 失败档必须是受控词表里的一档（`F-6`，`FetchResult.__post_init__` 守）。
        return FetchResult(ok=False, kind="http_500", path=None, http_status=500,
                           bytes=0, sha256=None, error="boom")


def _cand(**kw) -> Candidate:
    base = dict(
        title="Commutativity in abelian groups",
        year=1930,
        doi="10.1000/demo.abelian",
        authors=["A. Author"],
        venue="Demonstration Journal of Algebra",
        type_code="J",
        summary="满足交换律的群。",
        pdf_url="http://example.invalid/abelian.pdf",
        landing_url=None,
        language="en",
        provider="stub",
        raw={"provider": "stub"},
    )
    base.update(kw)
    return Candidate(**base)


def _agent_a(store, provider, downloader=None, **cfg) -> AgentA:
    config = {"download": True, "lease_seconds": 900, "max_attempts": 3}
    config.update(cfg)
    return AgentA(store, providers=[provider], downloader=downloader, config=config)


# --------------------------------------------------------------------------- 判收那两步


def _pending_slots(store, request_id: str) -> list[str]:
    """本委托还停在待裁（pending）的槽位号，升序。

    Q16 之后"跑一遍登记了几条"这个问题的落点是这一格：自动链路不再写 literature 行，
    它写的是候选行。所以"候选真的进了列表"与"一条都没查到"要靠它分开。
    """
    return sorted(str(r.get("slot")) for r in store.rows("lit_candidates")
                  if str(r.get("request_id")) == request_id
                  and str(r.get("status")) == "pending")


def _a_tools(store):
    """A 的工具面（判收那两步走真注册表，不是绕到 `litstage` 的内部函数上）。"""
    from agentflow.tools import build_for_role

    reg = build_for_role("A", store=store, workspace_root=store.root).registry
    reg.bound_role = "A"
    return reg


def _judge_and_admit(store, request_id: str, slot: str,
                     relevance: str = "与本次检索直接相关") -> dict:
    """Q16 的入库入口：先给原槽补一句 relevance，再逐条入库。

    两步都是 A 自己的活：`lit.stage_add` 带 relevance 重进同一篇 ⇒ 按 G9 补进原槽
    （不发新号、不先撤再进）；`lit.admit` 逐条过 `admission_plan` 再走既有登记路径。
    返回 `lit.admit` 的读数（判据要读 `registered` / `admitted[].lit_id`）。
    """
    reg = _a_tools(store)
    row = next(r for r in store.rows("lit_candidates") if str(r.get("slot")) == str(slot))
    entry: dict = {"title": str(row["title"]), "relevance": relevance}
    if row.get("doi"):
        entry["doi"] = str(row["doi"])
    topped = reg.call("lit.stage_add", request_id=request_id, entries=[entry])
    assert topped.ok, topped.error
    assert [u["slot"] for u in topped.unwrap()["updated"]] == [str(slot)], (
        f"补 relevance 必须落在原槽（G9：「补进原槽，不发新号」），实得 {topped.unwrap()}")
    got = reg.call("lit.admit", request_id=request_id, slots=[str(slot)])
    assert got.ok, got.error
    return got.unwrap()


def _mark_processed(store, lit_id: str, value: bool) -> None:
    """模拟 B 已经消化过这一篇（`processed` 只有 B 会置真）。"""
    with store.tx("literature", actor="test") as tx:
        row = tx.find("literature", lit_id=lit_id)
        assert row is not None, lit_id
        row["processed"] = bool(value)
        tx.upsert("literature", row)


# --------------------------------------------------------------------------- 幂等


def test_run_once_is_idempotent_and_accumulates_source_requests(store):
    """重跑同一请求不产生第二行文献；另一请求命中同一 DOI 时只累积 source_request_ids。

    改前红（Q16 落地后）：`first.registered == 1` 实得 0 —— 自动链路不再整批入库
    （`admission_plan(require_judged=True)`：候选没有 relevance，整批拒，一行都不结算）。
    定性：判据过时。裁定出处（业主 2026-10-26 Q16）：「如果 A 没全读过（数没全更新为
    入库和拒收），禁止提交待新增列表入库」⇒ 从 Q16 起 `run_once` 一条都不入库。

    改后仍守原来那件事（三段，逐段对应原判据的一句话）：
    ① 重跑同一请求不产生第二行（原来靠 `registered=1` 证明"第一行真的在"，
       现在靠"第一行在待裁列表里且只有一个槽"证明）；
    ② 崩溃后重跑不堆行（原来是 `duplicated=1`，现在是 pending 不翻倍）；
    ③ 另一条请求命中同一篇只累积来源、不新建行（这一条原样保留，只是行是判收造出来的）。
    下载成功时 path 必须落库那一条保留在第三段：字节是在"已在库、来补文件"那一趟落的
    （`run_once` 的补下载分支，Q16 刻意留着的那一个例外）。

    一处读数缺口（B1）已修：`lit.admit` 的登记路径现在把候选行的 `request_id` 带给
    `search.register`（2026-10-27），所以判收造出来的行一开始就带 `['r-0001']`、
    另一条请求命中同一篇之后是 `['r-0001', 'r-0002']` —— 这里因此钉字面值（改前那一格
    是空的，只敢钉"只增不减"）。请求行的 `result_lit_ids` 也跟着回填了，但它这一轮的
    `outcome` 仍是 `no_results`（那是这一轮自己的结论，只有下一次跑同一条请求才会
    自愈成 `ok`），所以来源那一侧钉 `result_lit_ids`，不钉 `outcome`。
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())
    add_request(store, "r-0001")

    # ---- 第一段：自动链路只暂存，不入库
    first = a.run_once()
    assert first.processed == 1, first.to_dict()
    assert first.registered == 0 and first.duplicated == 0, first.to_dict()
    assert store.rows("literature") == [], "自动链路一条都不许入库（Q16 的提交闸）"
    assert _pending_slots(store, "r-0001") == ["000000"], "命中的那一条必须进待裁列表"
    assert "待裁 1 条" in str(store.rows("search_requests")[0]["last_error"]), (
        "入库 0 条必须与「一条都没检索到」分得开")

    # 模拟"崩溃后重跑"：done 置回 False，再跑一次
    set_request_done(store, "r-0001", False)
    second = a.run_once()
    assert second.registered == 0 and second.duplicated == 0, second.to_dict()
    assert store.rows("literature") == [], "同一 DOI 不得重复登记文献行"
    assert _pending_slots(store, "r-0001") == ["000000"], "重跑不许把待裁行堆成两行"

    # ---- 第二段：A 逐条判收之后才有那一行
    got = _judge_and_admit(store, "r-0001", "000000")
    rows = store.rows("literature")
    assert len(rows) == 1, rows
    lit_id = rows[0]["lit_id"]
    assert got["registered"] == 1 and got["admitted"][0]["lit_id"] == lit_id, got
    assert rows[0]["processed"] is False, "processed 只能由 B 置真"
    # B1 的上半：判收造的行从第一次就带来源（改前这里是空的）
    assert rows[0]["source_request_ids"] == ["r-0001"], rows[0]["source_request_ids"]
    # B1 的下半：请求行的 `result_lit_ids` 也回填了（改前永不回填）
    assert store.rows("search_requests")[0]["result_lit_ids"] == [lit_id], (
        store.rows("search_requests")[0])

    # ---- 第三段：另一条请求命中同一篇文献：只追加来源，不新建行（顺带把字节补上）
    add_request(store, "r-0002", topic="阿贝尔群")
    third = a.run_once()
    assert third.duplicated == 1 and third.registered == 0, third.to_dict()
    rows = store.rows("literature")
    assert len(rows) == 1, "同一 DOI 不得重复登记文献行"
    assert rows[0]["lit_id"] == lit_id
    # B1（2026-10-27）修好之后这里可以钉字面值了（改前只敢钉"只增不减 + 升序去重"）。
    assert rows[0]["source_request_ids"] == ["r-0001", "r-0002"], (
        f"来源必须累积且升序，实得 {rows[0]['source_request_ids']}")
    assert rows[0]["path"] is not None, "下载成功时 path 必须落库（补下载那一趟）"


def test_existing_literature_row_is_not_overwritten_by_duplicate(store):
    """判重命中时只能追加来源，不能覆盖既有行的 path/processed（丢失更新）。

    改前红（Q16 落地后）：`store.rows("literature")[0]` 抛 `IndexError` —— 第一趟
    `run_once` 已经不入库了，库里一行都没有。定性：判据过时（裁定同 Q16：自动链路
    不入库，入库只能逐条判收之后）。

    改后仍守原来那件事：判重命中那一支（读数 `duplicated=1` 证明它真的跑到了）
    不许改动既有行的 path / download / lit_id / processed，只能追加来源。
    输入要三步才齐（暂存 → 判收 → 补下载），第四步才是原来那条判据量的那一趟。
    """
    a = _agent_a(store, StubProvider([_cand()]), OkDownloader())
    add_request(store, "r-0001")
    a.run_once()
    _judge_and_admit(store, "r-0001", "000000")
    # 补下载那一趟：字节落进既有行（Q16 刻意留的那个例外："已在库、缺文件"仍可下载）
    set_request_done(store, "r-0001", False)
    backfill = a.run_once()
    assert backfill.duplicated == 1, ("补下载必须走判重那一支，实得 "
                                      f"{backfill.to_dict()}")
    row = store.rows("literature")[0]
    assert row["path"], "夹具前提：补下载之后 path 必须非空"
    assert str(row["download"].get("status")) == "ok", row["download"]
    # 模拟 B 已经消化过这一篇：判重命中时不许把它翻回 False
    _mark_processed(store, row["lit_id"], True)
    before = dict(next(r for r in store.rows("literature") if r["lit_id"] == row["lit_id"]))

    add_request(store, "r-0002", topic="阿贝尔群")
    res = a.run_once()
    assert res.duplicated == 1, ("夹具前提：这一趟必须走到判重命中那一支，实得 "
                                 f"{res.to_dict()}")
    after = next(r for r in store.rows("literature") if r["lit_id"] == before["lit_id"])
    assert after["path"] == before["path"]
    assert after["download"] == before["download"]
    assert after["lit_id"] == before["lit_id"]
    assert after["processed"] is True, "判重命中把 B 的处理标记翻回去了（丢失更新）"
    assert set(before["source_request_ids"] or []) <= set(after["source_request_ids"] or []), (
        f"来源只许追加，实得 {before['source_request_ids']} -> "
        f"{after['source_request_ids']}")


# --------------------------------------------------------------------------- 按主题现查
#
# `A.search_literature`（2026-09-30）：用户口径是"A 的文献检索必须要通关"。
# 下面四条把"通关"拆成四个可判定的面：入队成功、真查到并登记、三态分得开、
# 走的是同一条准入闸门（不是绕过它开的后门）。


def test_search_literature_enqueues_and_returns_the_registered_rows(store):
    """正控：一次 `search_literature(topic)` 之后，文献真的在库里，来源也在请求行上。

    改前红（Q16 落地后）：`out["outcome"] == "ok"` 实得 `no_results` —— 自动链路一条
    都不入库，于是没有 `result_lit_ids`，请求行只能落 `no_results`（`schema` 的
    `SEARCH_OUTCOMES` 是禁改区契约，里面没有"找到了但待裁"这一档，区别只写在
    `last_error` 的读数里）。定性：判据过时（Q16 原话：没全读过就禁止入库）。

    改后仍守原来那件事，拆成两拍：第一拍"入队 + 真查到 + 进待裁列表"，
    第二拍"A 逐条判收之后文献真的在库里"。两拍之间那个读数（`待裁 1 条`）是
    原来 `outcome=ok` 承担的那句话："这一问查到了，不是没查到"。
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())

    out = a.search_literature(topic="abelian group", mode="topical")

    # ---- 第一拍：入队、查到、进列表（还没入库）
    assert out["ok"] is True and out["admitted"] is True, out
    assert out["request_id"] and out["request_id"].startswith("r-"), out
    assert out["done"] is True, out
    assert out["outcome"] == "no_results", out
    assert out["registered"] == 0, out
    assert "待裁 1 条" in str(out["last_error"]), out["last_error"]
    rows = store.rows("search_requests")
    assert len(rows) == 1, "只该入队一条"
    assert rows[0]["topic"] == "abelian group" and rows[0]["mode"] == "topical"
    assert rows[0]["submitted_by"] == "agent-A", "出处必须留在行上（谁提的）"
    assert store.rows("literature") == [], "这一拍一条都不许入库"
    cands = store.rows("lit_candidates")
    assert len(cands) == 1 and cands[0]["title"] == _cand().title, cands
    assert out["result_lit_ids"] == [] and out["literature"] == [], out
    # provider 真的被问过（"入队了但没人查"必须与"查到了"分得开）
    assert provider.calls and provider.calls[0][0] == "abelian group"

    # ---- 第二拍：逐条判收之后，文献真的在库里
    got = _judge_and_admit(store, out["request_id"], cands[0]["slot"])
    lit = store.rows("literature")
    assert len(lit) == 1 and lit[0]["title"] == _cand().title, lit
    assert got["admitted"][0]["lit_id"] == lit[0]["lit_id"]


def test_search_literature_reports_no_results_as_an_outcome_not_an_error(store):
    """查了但零命中 ⇒ `no_results`（有效结论），而不是错误、也不是异常。"""
    a = _agent_a(store, StubProvider([]), OkDownloader())
    out = a.search_literature(topic="there is no such paper anywhere")
    assert out["ok"] is True and out["outcome"] == "no_results", out
    assert out["result_lit_ids"] == [] and store.rows("literature") == []


def test_search_literature_without_a_provider_writes_nothing(store):
    """三态：「A 没接检索后端」⇒ 零写入 + 单独的理由码（不是"这个主题没有文献"）。"""
    a = AgentA(store, providers=[], downloader=OkDownloader(), config={"download": True})
    out = a.search_literature(topic="abelian group")
    assert out["ok"] is False and out["kind"] == "no_provider", out
    assert store.rows("search_requests") == [], "没接线时不许留下一条查不动的请求"


def test_search_literature_bad_topic_and_mode_are_refused_before_any_write(store):
    """参数门：空主题 / 未知 mode 都在入队之前被拒（负控：零写入）。"""
    a = _agent_a(store, StubProvider([_cand()]), OkDownloader())
    assert a.search_literature(topic="   ")["kind"] == "bad_topic"
    assert a.search_literature(topic="x", mode="没有这个模式")["kind"] == "bad_mode"
    assert store.rows("search_requests") == []


def test_search_literature_goes_through_the_inflight_gate(store, monkeypatch):
    """它必须过闸门：在途请求已达上限 ⇒ 如实拒绝且零写入（不许绕过 I7）。

    为什么单钉这一条：`search_literature` 是"生产队列"的动作，而队列有在途上限
    （`interactions.admit_search_request`）—— 绕过它，"角色一缺证据就提问"会退化成
    "每轮都问"，把所有请求一起拖慢。判据用 `max_inflight_requests=1` 制造满员。
    """
    from agentflow import interactions as X

    a = _agent_a(store, StubProvider([_cand()]), OkDownloader())
    monkeypatch.setitem(X.DEFAULTS, "max_inflight_requests", 1)
    add_request(store, "r-0001", topic="already queued")     # 占住在途额度

    out = a.search_literature(topic="abelian group")
    assert out["ok"] is True and out["admitted"] is False, out
    assert out["outcome"] == "rejected_by_gate" and "上限" in str(out["reason"]), out
    assert len(store.rows("search_requests")) == 1, "被拒时一条都不许写"


def test_search_literature_does_not_pretend_someone_elses_request_is_its_own(store):
    """队列里有更早的请求时，如实报出"这一轮领到的是它"，不冒充成本次的结果。

    三态纪律在这里的落点：`claimed_request_id != request_id` 是一个必须能被看见的
    区别 —— 否则调用方会把"别人那条的结果"当成"我要的文献"。

    改前红（Q16 落地后）：`len(store.rows("literature")) == 1` 实得 0 —— 两条请求
    都只走到"暂存"，谁也没入库。定性：判据过时（Q16：没逐条判过就不许入库）。

    改后仍守原来那件事：那个"同一个替身候选被两条请求各查了一次 ⇒ 判重合成同一行
    （不是两行）"改在它今天真正发生的地方量 —— 逐条判收时。先判早那条 ⇒ 库里一行；
    再判自己那条 ⇒ 撞 DOI 被拒（`duplicate_doi`），库里仍然只有一行。

    来源那一格（B1 修好之后钉字面值）：它只记"真正登记了这一篇的那次委托" ——
    也就是早那条。被 `duplicate_doi` 拒的那一次不进来源，这是判收的语义
    （那一条根本没有成为一次登记）。所以这里钉 `[早那条]` 而不是两条：
    改前两条都在来源里，是因为两次都走了登记/判重分支。第二洞（已报业主，不在本文件
    修）：被拒那次委托在 literature 上不留痕，它今天只活在候选行的 `request_id` 上，
    所以下面单独钉那一格。
    """
    a = _agent_a(store, StubProvider([_cand()]), OkDownloader())
    add_request(store, f"r-{S.format_id(1)}", topic="older request")      # 先来一条（同为 low 优先级）
    out = a.search_literature(topic="mine", mode="topical")
    assert out["request_id"] != f"r-{S.format_id(1)}"
    # 它先替更早那条跑完、再跑自己那条 —— 两条都要如实报出来。
    assert out["claimed_request_ids"] == [f"r-{S.format_id(1)}", out["request_id"]], out
    assert out["claimed_own"] is True, out
    # 两条都在库里，各自都完成了（用的是同一个替身 provider，各暂存一条）
    by_id = {r["request_id"]: r for r in store.rows("search_requests")}
    assert by_id[f"r-{S.format_id(1)}"]["done"] is True
    assert by_id[out["request_id"]]["done"] is True
    # Q16：两条各占自己的槽（列表按委托重置），谁也没入库
    assert store.rows("literature") == []
    by_slot = {r["request_id"]: str(r["slot"]) for r in store.rows("lit_candidates")}
    assert sorted(by_slot) == sorted([f"r-{S.format_id(1)}", out["request_id"]]), by_slot

    # 判早那条 ⇒ 一行入库
    first = _judge_and_admit(store, f"r-{S.format_id(1)}", by_slot[f"r-{S.format_id(1)}"])
    assert first["registered"] == 1, first
    lit = store.rows("literature")
    assert len(lit) == 1, (
        "同一个替身候选被两条请求各查了一次 ⇒ 判重合成同一行（不是两行）")
    # 判自己那条 ⇒ 撞 DOI 被拒，仍然只有一行
    reg = _a_tools(store)
    row = next(r for r in store.rows("lit_candidates")
               if str(r["slot"]) == by_slot[out["request_id"]])
    topped = reg.call("lit.stage_add", request_id=out["request_id"],
                      entries=[{"title": str(row["title"]), "doi": str(row["doi"]),
                                "relevance": "与本次检索直接相关"}])
    assert topped.ok, topped.error
    second = reg.call("lit.admit", request_id=out["request_id"],
                      slots=[by_slot[out["request_id"]]])
    assert second.ok, second.error
    got = second.unwrap()
    assert got["registered"] == 0, got
    assert [r["code"] for r in got["refused"]] == ["duplicate_doi"], got
    lit = store.rows("literature")
    assert len(lit) == 1, "同一篇不许变成两行文献"
    # B1（2026-10-27）修好之后这里可以钉字面值了：来源只记真正登记它的那次委托。
    assert lit[0]["source_request_ids"] == [f"r-{S.format_id(1)}"], lit[0]["source_request_ids"]
    # 被拒那次委托的溯源落在候选行上（哪天有人给 literature 补这条链，这里可以改宽）
    rejected = next(r for r in store.rows("lit_candidates")
                    if str(r["slot"]) == by_slot[out["request_id"]])
    assert str(rejected["request_id"]) == out["request_id"], rejected
    assert rejected["status"] == "pending", rejected


def test_a_non_ascii_description_is_kept_for_audit_but_not_used_as_the_query(store):
    """中文 description 不许进查询串（真机会把结果清零），但请求行上要原样留着。

    真机现场（2026-09-30）：G 写了一段中文 description，`precise` 把它拼进查询串
    ⇒ `论文包引言 … 分支布朗运动极值过程的 Poisson 点过程 OR <英文词>` ⇒ OpenAlex 0 条；
    同一句 topic、description 换成英文短语 ⇒ 8 条里 7 条对题。中文描述不是"信息少"，
    而是把检索带偏（它在英文库里成了主导词），而两层闸门都不拦它
    （题面+中文描述混排走的是 `applicable_as_is`）—— 这正是"没报错、也没结果"的形态。

    判据两条：① provider 收到的 description 是空串（查询只用题面）；
    ② 请求行上的 `content_description` 仍是原样中文（审计留痕不许被"修好"掉）。

    改前红（Q16 落地后）：`out["outcome"] == "ok"` 实得 `no_results` —— 自动链路不入库，
    所以请求行落 `no_results`。定性：判据过时（Q16）。改后那一格换成"入库 0 条 +
    待裁 1 条"：这一问确实查到了，只是还没被逐条判过（与 Q16 之前 `outcome=ok`
    承担的是同一句话）。
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())
    cn = "论文包引言 used_by=main.tex:introduction 需要一条外部文献支撑"

    out = a.search_literature(topic="abelian group", mode="precise", description=cn)

    assert out["registered"] == 0 and "待裁 1 条" in str(out["last_error"]), out
    assert provider.calls, "provider 一次都没被问到"
    assert provider.calls[0][2] == "", (
        f"查询串里不该出现非 ASCII 描述，实得 {provider.calls[0][2]!r}")
    row = store.rows("search_requests")[0]
    assert row["content_description"] == cn, "请求行上的描述必须原样保留（审计留痕）"

    # 正控：英文描述照旧进查询串（只过滤非 ASCII，不是把描述一律丢掉）
    provider.calls.clear()
    a.search_literature(topic="abelian group", mode="precise",
                        description="extremal process of BBM")
    assert provider.calls[0][2] == "extremal process of BBM", provider.calls[0][2]


def test_search_literature_refuses_a_cjk_only_topic_before_any_write(store):
    """纯中文题面：入队之前就如实拒，且零写入（不是"入队后查失败"）。

    为什么必须在这一层拦：`providers` 对抽不出英文关键词的题面是 fail-closed
    （抛 `query_not_applicable_cjk`，第三态"这一问没发出去"）。若让它入队，
    `run_once` 会把它当搜索失败处理 —— 试满 `max_attempts` 次、每次留退避租约，
    最后落 `search_failed`，而调用方读到的是"检索出问题了"。
    真相是"这一问根本没发出去"，两件事必须分开（三态纪律）。

    判据取自 providers 的公开判据（`query_applicability`）—— 这条也顺带钉住
    "A 用的就是那一份判据"，不是在 `agent_a` 里又写了一份。
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())

    out = a.search_literature(topic="分支布朗运动的极值过程", mode="precise")

    assert out["ok"] is True and out["admitted"] is False, out
    assert out["outcome"] == "query_not_applicable", out
    assert out["kind"] == "query_not_applicable_cjk", out
    assert "英文" in str(out.get("note")), out
    assert provider.calls == [], "这一问根本不该发给 provider"
    assert store.rows("search_requests") == [], "零写入：不许留一条注定查不动的请求"
    assert store.rows("literature") == []


def test_search_literature_accepts_a_cjk_topic_when_the_description_carries_english(store):
    """逃生门：中文题面 + 英文描述 ⇒ 这一问发得出去（判据同样取自 providers）。

    为什么要有这条正控：上面那条只证明"拒得对"，没有证明"该怎么救"。
    真机里角色既可能给中文题面、也可能给英文题面；把它逼到"只能给英文题面"
    是没必要的严 —— `query_applicability` 明确把"题面 + 描述"一起看。

    改前红（Q16 落地后）：`out["outcome"] == "ok"` 实得 `no_results`、库里一行都没有。
    定性：判据过时（Q16：自动链路不入库）。改后"这一问真的查到了"由"待裁列表里有
    那一条"来证明（同一件事，换到 Q16 之后它真正落的那一格）。
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())

    out = a.search_literature(topic="分支布朗运动的极值过程", mode="precise",
                              description="branching Brownian motion extremal process")

    assert out["admitted"] is True, out
    assert out["registered"] == 0 and "待裁 1 条" in str(out["last_error"]), out
    assert provider.calls[0][0] == "分支布朗运动的极值过程", "题面原样交给 provider"
    assert provider.calls[0][2] == "branching Brownian motion extremal process", (
        f"英文描述要原样进查询，实得 {provider.calls[0][2]!r}")
    assert len(store.rows("lit_candidates")) == 1, "命中的那一条必须进待裁列表"
    assert store.rows("literature") == [], "还没逐条判过 ⇒ 一条都不该入库"


def test_a_query_that_cannot_be_sent_is_not_retried(store):
    """第三态（这一问没发出去）必须当场终结，不许按"网络抖动"重试三次。

    现场（`draft/28` §204/§205）：`providers` 对抽不出英文关键词的题面 fail-closed，
    而这条 `ProviderError` 落在 `run_once` 里原来与"网络抖动"同一档 ⇒ 试满
    `max_attempts`、每次留退避租约、最后落 `search_failed`。
    两件事必须分得开：网络抖动可能下次就好，"没发出去"不可能靠重试变好。

    这条判据绕开 `search_literature` 的入队前预检，直接把一条注定发不出去的请求塞进队列 ——
    因为别的入队口（CLI `submit` / `research.submit_gap` / C 的 gap 分支）没有那道预检，
    它们今天走的就是这条路。
    """
    from agentflow import providers as P

    a = _agent_a(store, StubProvider(error=P.ProviderError(
        f"stub: {P.QUERY_NOT_APPLICABLE_CJK}：查询串里抽不出任何英文关键词 ⇒ 这一问不发")),
        OkDownloader())
    add_request(store, "r-0001", topic="分支布朗运动的极值过程", mode="topical")

    first = a.run_once()
    assert first.processed == 1, first.to_dict()
    row = store.rows("search_requests")[0]
    assert row["done"] is True, f"第三态必须当场终结，实得 done={row['done']} lease={row['lease_until']}"
    assert row["outcome"] == "search_failed", row
    assert row["lease_until"] is None, "终结了就不该再留退避租约"
    assert P.QUERY_NOT_APPLICABLE_CJK in str(row["last_error"]), row["last_error"]
    assert "重试不会变" in str(row["last_error"]), row["last_error"]
    assert int(row["attempts"]) == 1, f"只该试一次，实得 {row['attempts']}"

    # 再跑一轮：它已经终结，不该被重复领取（attempts 不涨）
    second = a.run_once()
    assert second.request_id is None, second.to_dict()
    assert int(store.rows("search_requests")[0]["attempts"]) == 1


def test_a_transient_provider_failure_still_gets_the_backoff_retry(store):
    """负控（反真空）：网络抖动那一档的重试语义一个字没动。

    没有这条，上面那条判据可能只是"我把所有失败都当场终结了" —— 而那会让
    "一次网络抖动把请求永久判死"（DESIGN.md §5.3 明确要避免的形态）重新回来。
    """
    a = _agent_a(store, StubProvider(error=RuntimeError("connection reset by peer")),
                 OkDownloader())
    add_request(store, "r-0001", topic="abelian group", mode="topical")

    res = a.run_once()
    assert res.processed == 1, res.to_dict()
    row = store.rows("search_requests")[0]
    assert row["done"] is False, "网络抖动不许被当场判死"
    assert row["outcome"] is None, row
    assert row["lease_until"], "可重试的失败必须留退避租约"
    assert int(row["attempts"]) == 1
    assert "connection reset" in str(row["last_error"]), row["last_error"]


# --------------------------------------------------------------------------- 下载失败


def test_download_failure_still_registers_and_completes_request(store):
    """下载失败不阻塞请求：文献行照常登记（path=null），请求仍置 done。

    改前红（Q16 落地后）：`res.registered == 1` 实得 0、`download_failed == 1` 实得 0 ——
    第一趟既不登记也不下载：没通过入库判断的候选不下载（Q16 之后那就是全部候选）。
    定性：判据过时（Q16：入库只能逐条判收）。改后这条判据量的是同一件事的两拍：
    ① 判收之后那一行照样在（`path=null`），请求照样 `done`；
    ② 再跑一趟时的补下载真的试过并如实记失败（`download_failed=1`），而失败
       不把那一行判死、也不把请求打回未完成。
    """
    a = _agent_a(store, StubProvider([_cand()]), FailingDownloader())
    add_request(store, "r-0001")

    # ---- 第一拍：自动链路不入库、也不下载失败（它根本没下载）
    first = a.run_once()
    assert first.registered == 0 and first.download_failed == 0, first.to_dict()
    assert first.processed == 1, first.to_dict()
    assert store.rows("literature") == []

    # ---- 第二拍：逐条判收 ⇒ 行在、path 空
    _judge_and_admit(store, "r-0001", "000000")
    lit = store.rows("literature")
    assert len(lit) == 1 and lit[0]["path"] is None, lit
    assert lit[0]["processed"] is False

    # ---- 第三拍：补下载失败 ⇒ 如实记账，行与请求都不许被这个失败改坏
    set_request_done(store, "r-0001", False)
    res = a.run_once()
    assert res.registered == 0 and res.download_failed == 1 and res.processed == 1, (
        res.to_dict())
    lit = store.rows("literature")[0]
    assert lit["path"] is None
    assert lit["download"]["status"] == "failed"
    assert lit["download"]["error"] == "boom"
    assert lit["processed"] is False
    req = store.rows("search_requests")[0]
    assert req["done"] is True


def test_download_failure_leaves_no_staging_or_partial_files(store):
    """下载失败时不得在 library/ 留下 staging 目录或半成品文件（慢操作不留残渣）。"""
    a = _agent_a(store, StubProvider([_cand()]), FailingDownloader())
    add_request(store, "r-0001")
    a.run_once()
    assert [p.name for p in store.library.iterdir() if p.name.startswith("agentflow-stage-")] == []
    assert [p for p in store.library.rglob("*") if p.is_file()] == []


# --------------------------------------------------------------------------- provider 失败


def test_provider_exception_is_recorded_not_raised(store):
    """provider 抛异常不得冒泡；按 DESIGN §5.3 请求应保持未完成，留待重试。

    注：本条原先断言"抛异常后仍标 done=true"，与 DESIGN.md §5.3 冲突。
    经裁决以 DESIGN 为准（一次网络抖动不该把请求永久判死），故改为断言
    "异常被吞掉、原因入 last_error、done 仍为 false"。attempts 用尽后的终局
    由下一条用例覆盖。
    """
    provider = StubProvider(error=RuntimeError("network down"))
    a = _agent_a(store, provider, None, max_attempts=3)
    add_request(store, "r-0001")

    res = a.run_once()  # 不应抛异常
    assert res.processed == 1
    req = store.rows("search_requests")[0]
    assert req["done"] is False, "首次失败应留待重试（§5.3）"
    assert req["outcome"] is None
    assert "network down" in (req["last_error"] or "")
    assert store.rows("literature") == []


def test_provider_exception_marks_done_after_attempts_exhausted(store):
    """DESIGN §5.3：attempts 达到上限时才把失败固化为终局（outcome=search_failed）。"""
    provider = StubProvider(error=RuntimeError("network down"))
    a = _agent_a(store, provider, None, max_attempts=1)
    add_request(store, "r-0001")

    a.run_once()
    req = store.rows("search_requests")[0]
    assert req["done"] is True
    assert req["outcome"] == "search_failed"
    assert "network down" in (req["last_error"] or "")


def test_gives_up_after_max_attempts(store):
    """尝试次数用尽后必须显式放弃：done=true 且 last_error 含"超过最大尝试次数"。"""
    provider = StubProvider(error=RuntimeError("boom"))
    a = _agent_a(store, provider, None, max_attempts=2)
    # 模拟"前 2 次尝试已失败但没提交完成标志"（崩溃恢复路径）
    add_request(store, "r-0001", attempts=2)

    a.run_once()
    req = store.rows("search_requests")[0]
    assert req["done"] is True
    assert "超过最大尝试次数" in (req["last_error"] or "")
    assert req["claimed_by"] is None and req["lease_until"] is None
    assert provider.calls == [], "放弃时不应再去调 provider"


def test_give_up_path_is_also_reached_by_extra_attempts(store):
    """max_attempts+1 次调用后也必须是"显式放弃"状态（不能再无限重试）。"""
    provider = StubProvider(error=RuntimeError("boom"))
    a = _agent_a(store, provider, None, max_attempts=1)
    add_request(store, "r-0001", attempts=1)
    for _ in range(2):
        a.run_once()
    req = store.rows("search_requests")[0]
    assert req["done"] is True
    assert "超过最大尝试次数" in (req["last_error"] or "")


# --------------------------------------------------------------------------- 终局语义（§1.1 / §5.3）


def test_empty_search_result_marks_done_without_crashing(store):
    """provider 返回空结果是合法常态：应记 done=true + outcome=no_results，而不是抛异常卡死。

    原先实现（无结果且无报错）把 done 置真却不给任何原因，触发 schema 不变量
    的 ValueError；异常抛出后请求仍保留租约与 done=false，队列被堵到租约过期。
    修复后由 `outcome` 字段显式表达"搜索过了，确实没有命中"。
    """
    a = _agent_a(store, StubProvider([]), None, download=False)
    add_request(store, "r-0001")

    res = a.run_once()  # ← 不应抛异常
    assert res.processed == 1
    req = store.rows("search_requests")[0]
    assert req["done"] is True, "空结果也应显式完成，否则队列被堵"
    assert req["outcome"] == "no_results"
    assert req["last_error"] is None, "零命中不是错误，不应写进 last_error"
    assert req["claimed_by"] is None
    assert req["lease_until"] is None


def test_search_failure_should_stay_pending_for_retry(store):
    """DESIGN.md §5.3：搜索失败保持 done=false 以便重试，只有 attempts≥max 才放弃。

    原实现无条件把 done 置真，于是第一次搜索失败就"完成"，
    §5.3 的"重试"与"超过最大尝试次数才放弃"两条语义都失效。
    """
    provider = StubProvider(error=RuntimeError("transient 503"))
    a = _agent_a(store, provider, None, max_attempts=3)
    add_request(store, "r-0001")

    a.run_once()
    req = store.rows("search_requests")[0]
    assert req["done"] is False, "第一次失败不应直接判完成（§5.3）"
    assert "transient 503" in (req["last_error"] or "")
    assert req["attempts"] == 1
    # 退避租约：允许重试，但不会在同一进程里立刻重打同一个 API
    assert req["lease_until"] is not None, "应设置退避租约，避免打爆上游"
