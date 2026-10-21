"""A 智能体：幂等、下载失败不阻塞、provider 异常、尝试次数耗尽（DESIGN.md §5）。"""

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


# --------------------------------------------------------------------------- 幂等


def test_run_once_is_idempotent_and_accumulates_source_requests(store):
    """重跑同一请求不产生第二行文献；另一请求命中同一 DOI 时只累积 source_request_ids。"""
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())
    add_request(store, "r-0001")

    first = a.run_once()
    assert first.registered == 1 and first.duplicated == 0 and first.processed == 1
    rows = store.rows("literature")
    assert len(rows) == 1
    lit_id = rows[0]["lit_id"]
    assert rows[0]["source_request_ids"] == ["r-0001"]
    assert rows[0]["path"] is not None, "下载成功时 path 必须落库"
    assert rows[0]["processed"] is False, "processed 只能由 B 置真"
    req = store.rows("search_requests")[0]
    assert req["done"] is True and req["result_lit_ids"] == [lit_id]

    # 模拟"崩溃后重跑"：done 置回 False，再跑一次
    set_request_done(store, "r-0001", False)
    second = a.run_once()
    assert second.registered == 0, "同一 DOI 不得重复登记文献行"
    assert second.duplicated == 1, "第二次必须走 duplicated 分支"
    assert len(store.rows("literature")) == 1

    # 另一个请求命中同一篇文献：只追加来源，不新建行
    add_request(store, "r-0002", topic="阿贝尔群")
    third = a.run_once()
    assert third.duplicated == 1 and third.registered == 0
    rows = store.rows("literature")
    assert len(rows) == 1
    assert rows[0]["source_request_ids"] == ["r-0001", "r-0002"], "来源必须累积且升序"


def test_existing_literature_row_is_not_overwritten_by_duplicate(store):
    """判重命中时只能追加来源，不能覆盖既有行的 path/processed（丢失更新）。"""
    a = _agent_a(store, StubProvider([_cand()]), OkDownloader())
    add_request(store, "r-0001")
    a.run_once()
    before = dict(store.rows("literature")[0])
    set_request_done(store, "r-0001", False)
    a.run_once()
    after = store.rows("literature")[0]
    assert after["path"] == before["path"]
    assert after["download"] == before["download"]
    assert after["lit_id"] == before["lit_id"]


# --------------------------------------------------------------------------- 按主题现查
#
# `A.search_literature`（2026-09-30）：用户口径是"A 的文献检索必须要通关"。
# 下面四条把"通关"拆成四个可判定的面：入队成功、真查到并登记、三态分得开、
# 走的是同一条准入闸门（不是绕过它开的后门）。


def test_search_literature_enqueues_and_returns_the_registered_rows(store):
    """正控：一次 `search_literature(topic)` 之后，文献真的在库里，来源也在请求行上。"""
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())

    out = a.search_literature(topic="abelian group", mode="topical")

    assert out["ok"] is True and out["admitted"] is True, out
    assert out["request_id"] and out["request_id"].startswith("r-"), out
    assert out["outcome"] == "ok" and out["done"] is True, out
    rows = store.rows("search_requests")
    assert len(rows) == 1, "只该入队一条"
    assert rows[0]["topic"] == "abelian group" and rows[0]["mode"] == "topical"
    assert rows[0]["submitted_by"] == "agent-A", "出处必须留在行上（谁提的）"
    lit = store.rows("literature")
    assert len(lit) == 1 and lit[0]["title"] == _cand().title
    assert out["result_lit_ids"] == [lit[0]["lit_id"]]
    assert [x["lit_id"] for x in out["literature"]] == [lit[0]["lit_id"]]
    assert out["literature"][0]["title"] == lit[0]["title"]
    # provider 真的被问过（"入队了但没人查"必须与"查到了"分得开）
    assert provider.calls and provider.calls[0][0] == "abelian group"


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
    """
    a = _agent_a(store, StubProvider([_cand()]), OkDownloader())
    add_request(store, f"r-{S.format_id(1)}", topic="older request")      # 先来一条（同为 low 优先级）
    out = a.search_literature(topic="mine", mode="topical")
    assert out["request_id"] != f"r-{S.format_id(1)}"
    # 它先替更早那条跑完、再跑自己那条 —— 两条都要如实报出来。
    assert out["claimed_request_ids"] == [f"r-{S.format_id(1)}", out["request_id"]], out
    assert out["claimed_own"] is True, out
    # 两条都在库里，各自都完成了（用的是同一个替身 provider，各登记一篇）
    by_id = {r["request_id"]: r for r in store.rows("search_requests")}
    assert by_id[f"r-{S.format_id(1)}"]["done"] is True
    assert by_id[out["request_id"]]["done"] is True
    assert len(store.rows("literature")) == 1, (
        "同一个替身候选被两条请求各查了一次 ⇒ 判重合成同一行（不是两行）")
    lit = store.rows("literature")[0]
    assert lit["source_request_ids"] == [f"r-{S.format_id(1)}", out["request_id"]], lit["source_request_ids"]


def test_a_non_ascii_description_is_kept_for_audit_but_not_used_as_the_query(store):
    """中文 description 不许进查询串（真机会把结果清零），但请求行上要原样留着。

    真机现场（2026-09-30）：G 写了一段中文 description，`precise` 把它拼进查询串
    ⇒ `论文包引言 … 分支布朗运动极值过程的 Poisson 点过程 OR <英文词>` ⇒ OpenAlex 0 条；
    同一句 topic、description 换成英文短语 ⇒ 8 条里 7 条对题。中文描述不是"信息少"，
    而是把检索带偏（它在英文库里成了主导词），而两层闸门都不拦它
    （题面+中文描述混排走的是 `applicable_as_is`）—— 这正是"没报错、也没结果"的形态。

    判据两条：① provider 收到的 description 是空串（查询只用题面）；
    ② 请求行上的 `content_description` 仍是原样中文（审计留痕不许被"修好"掉）。
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())
    cn = "论文包引言 used_by=main.tex:introduction 需要一条外部文献支撑"

    out = a.search_literature(topic="abelian group", mode="precise", description=cn)

    assert out["outcome"] == "ok", out
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
    """
    provider = StubProvider([_cand()])
    a = _agent_a(store, provider, OkDownloader())

    out = a.search_literature(topic="分支布朗运动的极值过程", mode="precise",
                              description="branching Brownian motion extremal process")

    assert out["admitted"] is True and out["outcome"] == "ok", out
    assert provider.calls[0][0] == "分支布朗运动的极值过程", "题面原样交给 provider"
    assert provider.calls[0][2] == "branching Brownian motion extremal process", (
        f"英文描述要原样进查询，实得 {provider.calls[0][2]!r}")
    assert len(store.rows("literature")) == 1


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
    """下载失败不阻塞请求：文献行照常登记（path=null），请求仍置 done。"""
    a = _agent_a(store, StubProvider([_cand()]), FailingDownloader())
    add_request(store, "r-0001")
    res = a.run_once()

    assert res.registered == 1 and res.download_failed == 1 and res.processed == 1
    lit = store.rows("literature")[0]
    assert lit["path"] is None
    assert lit["download"]["status"] == "failed"
    assert lit["download"]["error"] == "boom"
    assert lit["processed"] is False
    req = store.rows("search_requests")[0]
    assert req["done"] is True and req["result_lit_ids"] == [lit["lit_id"]]


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
