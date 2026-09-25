"""下载交接的回归测试：A 与 B 之间对"下载成功"的理解必须一致。

背景（真实缺陷，见 `realrun/RESULTS.md`）：
真实联网试跑时，一个以 `.pdf` 结尾的 URL 返回了 **12.4 MB 的 HTML**
（落地页/反爬页）。`fetch.py` **正确地**把它标成了
`content_type_mismatch`，但 AgentA 仍记 `status="ok"`，于是 AgentB 照常去
抽取那个 HTML —— 把网页导航文字当成了"概念"。

也就是说：**检测到了，但没有人消费这个结论**。本文件把"必须消费"这一点固定下来，
防止以后有人把 status 又改回 "ok"。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from abflow.agent_a import AgentA
from abflow.agent_b import AgentB
from abflow.fetch import FetchResult
from abflow.providers import Candidate

from conftest import add_literature, add_request, sync_counters, write_library_file


# --------------------------------------------------------------------------- 替身


class StubProvider:
    name = "stub"

    def __init__(self, candidates=()):
        self.candidates = list(candidates)

    def search(self, topic, mode, description, limit):
        return list(self.candidates)


class MismatchDownloader:
    """模拟"HTTP 200 但拿到的是 HTML"的真实情况。

    这是 `HttpDownloader` 在 content-type 不符时的真实返回形状：
    `ok=True`（字节确实下全了）但 `error` 里带 `content_type_mismatch`。
    """

    def download(self, url: str, dest_dir: Path, filename_hint: str) -> FetchResult:
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / f"{filename_hint}.html"
        target.write_text("<!DOCTYPE html><html><body>cookie consent</body></html>", encoding="utf-8")
        data = target.read_bytes()
        return FetchResult(
            ok=True,
            path=str(target),
            http_status=200,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            error="content_type_mismatch: text/html (URL 期望 .pdf；可能被代理/劫持或链接并非直链)",
        )


class NullExtractor:
    """抽取器替身：被调用即计数，用来断言"到底有没有去抽取"。"""

    def __init__(self):
        self.calls = 0

    def extract(self, doc, lit_id, meta):
        self.calls += 1
        return [], []


def _cand() -> Candidate:
    return Candidate(
        title="Elliptic curve cryptosystems",
        year=1987,
        doi="10.1090/s0025-5718-1987-0866109-5",
        authors=["N. Koblitz"],
        venue="Mathematics of Computation",
        type_code="J",
        summary="椭圆曲线密码系统。",
        pdf_url="http://example.invalid/koblitz.pdf",
        landing_url=None,
        language="en",
        provider="stub",
        raw={},
    )


def _agent_a(store, provider, downloader) -> AgentA:
    return AgentA(
        store,
        providers=[provider],
        downloader=downloader,
        config={"download": True, "max_downloads_per_request": 5},
    )


# --------------------------------------------------------------------------- A 侧


def test_content_type_mismatch_downgrades_status_but_keeps_evidence(store):
    """A 必须把 content_type_mismatch 降级为独立状态，同时**保留**字节作为证据。

    断言三点：① 状态不再是 "ok"；② 文件仍然落盘（path 非空，便于人工查看对方返回了什么）；
    ③ 计入 download_suspect 而不是 downloaded —— 否则统计会把"下到了网页"报成"下到了论文"。
    """
    a = _agent_a(store, StubProvider([_cand()]), MismatchDownloader())
    add_request(store, "r-0001")

    res = a.run_once()
    assert res.registered == 1
    assert res.downloaded == 0, "下到 HTML 不算成功下载"
    assert res.download_suspect == 1, "必须落在独立计数里，不能混进 downloaded"

    lit = store.rows("literature")[0]
    assert lit["download"]["status"] == "content_mismatch"
    assert lit["download"]["error"].startswith("content_type_mismatch")
    assert lit["path"], "字节要留着当证据，不能因为状态降级就丢掉文件"
    assert (store.library / lit["path"]).exists()


# --------------------------------------------------------------------------- B 侧


def test_agent_b_skips_content_mismatch_literature(store):
    """B 遇到 content_mismatch 必须**跳过且标为已处理**，并且绝不调用抽取器。

    两个都要断言到：不调用抽取器（否则网页文字会变成"概念"），
    以及标为已处理（否则这一行会永远堵在队首，每次 run 都重新领取）。
    """
    write_library_file(store, "0000/page.html", "<!DOCTYPE html><html><body>cookie consent</body></html>")
    add_literature(
        store,
        "0000",
        title="Elliptic curve cryptosystems",
        path="0000/page.html",
        processed=False,
        dedup_key="doi:10.10/x",
        download={"status": "content_mismatch", "http_status": 200, "bytes": 52,
                  "sha256": "0" * 64, "error": "content_type_mismatch: text/html"},
    )
    sync_counters(store)

    extractor = NullExtractor()
    b = AgentB(store, extractor=extractor, extract_text=lambda p: (_ for _ in ()).throw(
        AssertionError("不该对 content_mismatch 的文件调用 extract_text")))
    res = b.run_once()

    assert extractor.calls == 0, "不得对非论文内容做抽取"
    assert res.unreadable == 1
    lit = store.rows("literature")[0]
    assert lit["processed"] is True, "必须标为已处理，否则永远堵住队列"
    assert "content_type_mismatch" in (lit["last_mine_error"] or "")
    assert store.rows("concepts") == [] and store.rows("relations") == []


def test_agent_b_still_processes_normal_downloads(store):
    """回归保护：跳过逻辑不能误伤正常的 ok 下载（避免"修 A 坏 B"）。"""
    from abflow.extract import extract_text
    from abflow.llm import RuleExtractor

    write_library_file(
        store, "0000/source.txt",
        "An abelian group is a group in which the commutative law holds.",
    )
    add_literature(
        store, "0000", title="Normal paper", path="0000/source.txt", processed=False,
        dedup_key="doi:10.10/normal",
        download={"status": "ok", "http_status": 200, "bytes": 62, "sha256": "0" * 64, "error": None},
    )
    sync_counters(store)

    b = AgentB(store, extractor=RuleExtractor(), extract_text=extract_text,
               config={"seed_concepts": [{"name": "group", "definition": "a set with an operation"}]})
    res = b.run_once()

    assert res.processed == 1
    assert res.unreadable == 0
    assert store.rows("literature")[0]["processed"] is True
    assert any(c["name"] == "abelian group" for c in store.rows("concepts")), "正常路径仍应抽到概念"


# --------------------------------------------------------------------------- 受控词表


def test_typo_in_download_status_is_rejected_loudly():
    """`download.status` 拼错必须在**写入时**炸出来，而不是静默放行。

    这是缺陷 #8 的复发路径：B 靠 `status == "content_mismatch"` 这个精确字符串决定
    跳过。若写成 `content-mismatch`，比较失败 → B 照常抽取 HTML → 网页文字变"概念"，
    而**全程不会报任何错**。所以把它纳入 schema 校验，让拼错变成硬失败。
    """
    import pytest

    from abflow import schema as S

    for bad in ("content-mismatch", "contentMismatch", "html", "", "OK"):
        row = S.Literature(
            lit_id="0000", title="T", type="J", summary="", path=None,
            download={"status": bad},
        )
        with pytest.raises(ValueError, match="download.status"):
            row.validate()


def test_valid_download_statuses_are_accepted():
    """受控词表里的值都要能通过（避免"修过头"把正常值也拒了）。"""
    from abflow import schema as S

    for good in S.DOWNLOAD_STATUSES:
        S.Literature(
            lit_id="0000", title="T", type="J", summary="", path=None,
            download={"status": good},
        ).validate()
    # 空 download（未尝试下载的历史行）也必须合法
    S.Literature(lit_id="0000", title="T", type="J", summary="", path=None, download={}).validate()


# --------------------------------------------------------------------------- 校验器侧的同一约定


def test_verify_flags_content_mismatch_without_evidence(store):
    """`verify` 必须报出"标了 content_mismatch 却没留证据字节"。

    缺陷 #8 的契约有**两处**要落地：① agent_b 依据 `status` 跳过；② 证据字节必须保留。
    只做①不做②，事后就无法回答"对方到底返回了什么"。**一条约定需要两处执行**，
    所以 schema 管词表、verify 管证据留存 —— 本用例守住后者。
    """
    from abflow.verify import verify_all

    add_literature(
        store, "0000", title="T", path=None, processed=True,
        dedup_key="doi:10.1/x",
        download={"status": "content_mismatch", "http_status": 200, "bytes": 10,
                  "sha256": None, "error": "content_type_mismatch: text/html"},
    )
    codes = [i.code for i in verify_all(store).issues]
    assert "mismatch_without_evidence" in codes


def test_verify_is_quiet_when_mismatch_evidence_is_kept(store):
    """证据字节保留了（path 非空且文件在）时不该报警 —— 避免"修过头"制造噪音。"""
    from abflow.verify import verify_all

    write_library_file(store, "0000/page.html", "<!DOCTYPE html><html>landing</html>")
    add_literature(
        store, "0000", title="T", path="0000/page.html", processed=True,
        dedup_key="doi:10.1/x",
        download={"status": "content_mismatch", "http_status": 200, "bytes": 35,
                  "sha256": "0" * 64, "error": "content_type_mismatch: text/html"},
    )
    codes = [i.code for i in verify_all(store).issues]
    assert "mismatch_without_evidence" not in codes
