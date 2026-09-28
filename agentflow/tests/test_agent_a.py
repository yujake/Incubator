"""A 智能体：幂等、下载失败不阻塞、provider 异常、尝试次数耗尽（DESIGN.md §5）。"""

from __future__ import annotations

import hashlib
from pathlib import Path

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
