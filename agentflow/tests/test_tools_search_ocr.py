"""A 的检索工具（`tools/search_tools.py`）与 B 的 OCR 工具（`tools/ocr_tools.py`）的性质测试。

全部离线、确定性：检索用注入的假 provider，OCR 用注入的测试桩后端，
provider 探测用 `ABFLOW_SKIP_NETWORK=1` 把网络源标成"未探测"。

两条贯穿的性质（DESIGN-TOOLS §7 与 §6.3 同源）：
- "没做" ≠ "做了没结果"：没有可用 OCR 后端时 `ocr.run` 必须 fail 并说明没产出，
  绝不返回空文本假装识别成功；后端真跑了但返回空串才是"做了但没结果"（记 warning）。
- "没查" ≠ "是新的"：没有 store 时判重结论是 `None`（未知）而不是 `False`（新）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentflow import providers as P
from agentflow.tools import ocr_tools, search_tools
from agentflow.tools.base import ToolRegistry

# ============================================================ 假 provider / OCR 桩


class _StubProvider:
    """注入用的假检索源：不联网、结果确定。"""

    def __init__(self, candidates: list[P.Candidate], name: str = "stub") -> None:
        self.name = name
        self._candidates = candidates
        self.last_query_text = "stub query"

    def search(self, topic: str, mode: str = "topical", description: str = "", limit: int = 10):  # noqa: ARG002
        return list(self._candidates[: int(limit)])


class _StubBackend:
    """OCR 测试桩后端（不是真 OCR）：可以控制可用性与返回值。"""

    produces_text = True

    def __init__(self, name: str, text: str = "", *, available: bool = True, reason: str = "测试桩") -> None:
        self.name = name
        self._text = text
        self._available = available
        self._reason = reason
        self.checks = {"role": "测试桩（不是真 OCR）"}
        self.calls: list = []

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:  # noqa: ARG002
        return self._available, self._reason

    def ocr_image(self, image, languages) -> str:
        self.calls.append(tuple(languages))
        return self._text


def _cand(title: str, *, doi: str | None = None, year: int | None = 2020, summary: str = "摘要") -> P.Candidate:
    return P.Candidate(title=title, year=year, doi=doi, type_code="J", summary=summary, provider="stub")


# ============================================================ search.*


def test_search_providers_marks_network_sources_unverified_when_offline(store, monkeypatch):
    """ABFLOW_SKIP_NETWORK=1 时网络源必须标成「未探测」（available=None），不是"可用"也不是"不可用"。"""
    monkeypatch.setenv("ABFLOW_SKIP_NETWORK", "1")
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, store=store, workspace=store.root)

    res = reg.call("search.providers")
    assert res.ok, res.error
    data = res.data
    rows = {r["name"]: r for r in data["providers"]}
    for name in search_tools.NETWORK_PROVIDERS:
        assert name in rows, f"{name} 没有被探测"
        assert rows[name]["available"] is None, f"{name} 被猜成了可用/不可用"
        assert rows[name]["status"] == "unverified"
        assert "未探测" in rows[name]["reason"]
        assert name in data["unverified"]
    # fixture 是本地文件源，不联网，必须给出真实的可用性结论
    assert rows["fixture"]["available"] is not None
    assert rows["fixture"]["status"] in ("probed_ok", "probed_fail")
    assert data["skip_network"] is True


def test_search_literature_rejects_precise_mode_without_description(store):
    """mode=precise 缺 description 时必须 fail（与 schema.SearchRequest 的约束一致）。"""
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, store=store, workspace=store.root)
    res = reg.call("search.literature", topic="群", mode="precise")
    assert res.ok is False
    assert res.meta.get("kind") == "param_constraint"
    assert "description" in res.error


def test_search_literature_flags_new_and_existing_candidates(store):
    """候选必须自带判重结论：哪条是新的、哪条命中了表里的哪一行。"""
    from conftest import add_literature

    add_literature(store, "0000", title="Duplicate paper", doi="10.1000/dup", dedup_key="doi:10.1000/dup")

    stub = _StubProvider([_cand("Duplicate paper", doi="10.1000/dup"), _cand("Brand new paper", doi="10.1000/new")])
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, store=store, providers=[stub], workspace=store.root)

    res = reg.call("search.literature", topic="群", mode="topical", limit=5, provider="stub")
    assert res.ok, res.error
    data = res.data
    assert data["store_checked"] is True
    assert data["count"] == 2
    assert data["existing_count"] == 1 and data["new_count"] == 1
    dup, new = data["candidates"]
    assert dup["existing"] is True and dup["existing_lit_id"] == "0000" and dup["is_new"] is False
    assert new["existing"] is False and new["is_new"] is True
    assert data["warnings"] == [], "有 store 时不该出现「无法判重」的警告"


def test_search_literature_without_store_reports_unknown_instead_of_new(store):
    """没有 store 时，判重结论必须是 None（未知）—— 把"没查"写成"新的"会让 A 重复登记。"""
    stub = _StubProvider([_cand("Some paper", doi="10.1000/x")])
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, providers=[stub], workspace=store.root)

    data = reg.call("search.literature", topic="群", mode="topical", provider="stub").data
    assert data["store_checked"] is False
    assert data["candidates"][0]["existing"] is None
    assert data["candidates"][0]["is_new"] is None
    assert data["unknown_count"] == 1
    assert any("未配置 store" in w for w in data["warnings"])


def test_search_literature_empty_result_is_a_conclusion_not_a_failure(store):
    """检索正常执行但零命中是有效结论（ok + 空列表 + 说明），不是故障。"""
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, store=store, providers=[_StubProvider([])], workspace=store.root)
    res = reg.call("search.literature", topic="没人写过的东西", mode="topical", provider="stub")
    assert res.ok is True
    assert res.data["count"] == 0
    assert any("零命中" in w for w in res.data["warnings"])


def test_search_dedup_check_requires_store(store):
    """search.dedup_check 没有 store 时必须 fail（返回"看起来新的"就是假阴性）。"""
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, workspace=store.root)
    res = reg.call("search.dedup_check", title="任意标题", year=2020)
    assert res.ok is False
    assert res.meta.get("kind") == "no_store"
    assert "假阴性" in res.error


def test_search_dedup_check_matches_existing_doi(store):
    """判重按三级硬键执行：同 DOI 必须命中既有行，并给出命中的键。"""
    from conftest import add_literature

    add_literature(store, "0000", title="On abelian groups", doi="10.1000/dup", year=1930, dedup_key="doi:10.1000/dup")
    reg = ToolRegistry(name="search")
    reg.bound_role = "A"  # P-14：search.* 只有 A
    search_tools.register(reg, store=store, workspace=store.root)

    hit = reg.call("search.dedup_check", title="Completely different title", doi="10.1000/dup").data
    assert hit["would_be_duplicate"] is True
    assert hit["existing"]["lit_id"] == "0000"
    assert "doi" in str(hit["matched_key"]).lower()

    miss = reg.call("search.dedup_check", title="A wholly unrelated topic nobody wrote about", year=2099).data
    assert miss["would_be_duplicate"] is False
    assert miss["existing"] is None
    assert "near_misses" in miss


# ============================================================ ocr.*


def test_ocr_backends_probe_is_injectable_and_reported_truthfully(store, tmp_path):
    """ocr.backends 必须如实报告探测结论：可用 / 不可用 + 逐条理由。"""
    down = _StubBackend("stub-down", available=False, reason="桩：故意不可用")
    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[down])

    res = reg.call("ocr.backends")
    assert res.ok, res.error
    data = res.data
    assert data["any_ocr_backend_available"] is False
    assert data["selected_for_auto"] is None
    assert data["backends"][0]["available"] is False
    assert "故意不可用" in data["backends"][0]["reason"]
    assert "不会" in data["verdict"] or "无任何可用" in data["verdict"]


def test_ocr_run_fails_instead_of_faking_success_when_no_backend(store, tmp_path):
    """没有可用后端时 ocr.run 必须 fail 并说明"一个字符都没产出"，绝不假装识别成功。"""
    png = tmp_path / "page.png"
    _write_png(png)
    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[_StubBackend("stub-down", available=False)])

    res = reg.call("ocr.run", path=str(png))
    assert res.ok is False
    assert res.meta.get("kind") == "no_backend"
    assert res.data is None, "失败时不该返回任何「识别结果」"
    assert "没有" in res.error and "假装" in res.error


def test_ocr_run_marks_empty_backend_output_as_ran_but_empty(store, tmp_path):
    """后端真跑了但返回空串 ⇒ ok=True + empty=True + warning「做了但没结果」。"""
    png = tmp_path / "page.png"
    _write_png(png)
    stub = _StubBackend("stub-empty", "")
    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[stub])

    res = reg.call("ocr.run", path=str(png))
    assert res.ok is True, res.error
    data = res.data
    assert data["backend"] == "stub-empty"
    assert data["total_chars"] == 0
    assert data["pages"][0]["ok"] is True
    assert data["pages"][0]["empty"] is True
    assert any("做了但没结果" in w for w in data["warnings"])
    assert "做了但没结果" in data["note"]
    assert stub.calls, "桩后端没有被真的调用过"


def test_ocr_run_reports_max_pages_truncation(store, tmp_path):
    """max_pages 截断必须留痕：静默截断会让"我没看到那几页"伪装成"那几页没有内容"。"""
    fitz = pytest.importorskip("fitz", reason="栅格化 PDF 需要 PyMuPDF")
    pdf = tmp_path / "three.pdf"
    doc = fitz.open()
    for _ in range(3):
        doc.new_page()
    doc.save(str(pdf))
    doc.close()

    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[_StubBackend("stub-text", "STUB-TEXT")])

    res = reg.call("ocr.run", path=str(pdf), max_pages=1)
    assert res.ok, res.error
    data = res.data
    assert data["pages_requested"] == [1, 2, 3]
    assert data["pages_processed"] == [1]
    assert data["truncated_pages"] == 2
    assert any("截断" in w for w in data["warnings"])
    assert data["text"] == "STUB-TEXT"


def test_ocr_run_rejects_the_none_backend_via_schema(store, tmp_path):
    """`none` 不是 OCR 后端而是"明确的退路"，参数词表里就不该有它。"""
    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[ocr_tools.NullBackend()])
    res = reg.call("ocr.run", path=str(tmp_path / "x.pdf"), backend="none")
    assert res.ok is False
    assert res.meta.get("kind") == "param_error"


def test_ocr_null_backend_is_never_selected_for_auto_and_produces_nothing(store, tmp_path):
    """NullBackend 永远"可用"却产不出文本：auto 必须跳过它，run 必须 fail。"""
    null = ocr_tools.NullBackend()
    assert isinstance(null, ocr_tools.OcrBackend)
    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[null])

    data = reg.call("ocr.backends").data
    assert data["backends"][0]["produces_text"] is False
    assert data["selected_for_auto"] is None
    assert data["any_ocr_backend_available"] is False

    png = tmp_path / "page.png"
    _write_png(png)
    res = reg.call("ocr.run", path=str(png))
    assert res.ok is False and res.meta.get("kind") == "no_backend"


def test_ocr_detect_text_layer_fails_clearly_for_missing_file(store, tmp_path):
    """文本层探测：文件不存在时给出明确的 file_missing，而不是"没有文本层"。"""
    reg = ToolRegistry(name="ocr")
    reg.bound_role = "B"  # P-14：ocr.* 只有 B
    ocr_tools.register(reg, store=store, workspace=tmp_path, backends=[_StubBackend("stub-text", "x")])
    res = reg.call("ocr.detect_text_layer", path=str(tmp_path / "nope.pdf"))
    assert res.ok is False
    assert res.meta.get("kind") == "file_missing"


def _write_png(path: Path) -> Path:
    from PIL import Image

    Image.new("RGB", (12, 12), "white").save(path)
    return path
