"""FC-17（上下文预算：压缩 / 剪枝 / spill 三件套）的性质测试。

这些用例锁的是约束本身，不是实现细节。三条纪律各有对应的用例：

- 三态纪律：`pruned=True, spilled=False, reason="未提供 spill_root"` 与
  `pruned=True, spilled=True` 是两件不同的事，而它们与"没超阈值"又是第三件事。
  所以"reason 非空"要逐个态去断言 —— 空 reason 会让"没剪"与"忘了剪"无法区分。
- 不许静默兜底：配置里写 `"8000"`（字符串）必须抛，而不是被悄悄转成 8000；
  注入的 `summarize` 返回空摘要必须抛，而不是把这段历史悄悄扔掉。
- 判据② 要落到盘上：超大工具结果必须被剪枝/落盘，而且要逐项核对
  （内联长度 ≤ 上限、文件存在、文件大小 == 内联里记录的字节数、
  sha256 前 16 位 == 文件名前缀 == 盘上内容的哈希）—— "看着像"不算验证。

为什么每条都配负控：本项目最忌讳的失败形态是"没做"与"做了没效果"长得一样。
一个只断言 `pruned is True` 的用例，在"其实什么都没剪、只是标记了一下"的实现下
照样全绿。
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from agentflow.contextbudget import (
    CompactResult,
    ContextBudget,
    PrunedText,
    compact,
    prune,
    prune_tool_result,
)
from agentflow.tools import build_registry
from agentflow.tools.base import ToolRegistry, ToolResult, ToolSpec, ok

_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- 靶子与预算


def _make_big(lines: int = 13_000) -> str:
    """构造一个"超大工具结果"。

    刻意混了中文与 ASCII：这样"字符数"与"UTF-8 字节数"不相等，
    能抓出"拿字符数去比 `max_inline_bytes`"这类口径错误 ——
    拿错口径的实现会在纯 ASCII 用例上全绿，一遇中文就漏。
    """
    return "".join(
        f"第{i:06d}行：这是一段用于验证剪枝与落盘的中文内容，含 ASCII marker {i}。\n"
        for i in range(lines)
    )


#: 判据②的靶子：> 500 KB。
BIG = _make_big()


def _spill_budget() -> ContextBudget:
    """让"落盘"分支可达的预算：`head_chars + tail_chars (102000) > max_inline_bytes (64000)`。

    为什么不直接用默认数值：默认 head+tail=4000 远小于 64000，剪枝后的文本
    永远进不了落盘分支（见 `test_default_numbers_make_spill_unreachable_from_prune`）。
    这不是实现 bug，是"数值表里两组数各自独立"的直接后果，
    但必须显式构造一个能触发的预算，否则"落盘"这条路径永远不会被验证。
    """
    return ContextBudget(
        threshold_chars=200_000,
        head_chars=100_000,
        tail_chars=2_000,
        spill_dir="spill",
        max_inline_bytes=64_000,
        compaction_threshold_chars=200_000,
        compaction_keep_recent=8,
    )


def _items(n: int = 20, size: int = 12_000) -> list[str]:
    """compaction 的靶子：20 条 × ~12008 字符 ≈ 240,160 > 200,000。"""
    return [f"第{i:03d}条：" + "x" * size for i in range(n)]


# ============================================================ 判据①：配置


def test_config_yaml_carries_the_fc17_block_and_it_loads():
    """判据①：`config.yaml` 里必须真的有 compaction 行、剪枝行、spill 上限。

    两遍核对，缺一不可：

    1. 按原始文本核对键名存在（防止"块还在、行被注释掉了"）；
    2. 按 `ContextBudget.from_mapping` 核对数值能被真正装载并校验通过
       （防止"键名对了但类型/取值非法，一装载就炸"）。
    """
    yaml = pytest.importorskip("yaml")
    raw = (_ROOT / "config.yaml").read_text(encoding="utf-8")
    for key in (
        "threshold_chars",
        "head_chars",
        "tail_chars",
        "spill_dir",
        "max_inline_bytes",
        "compaction_threshold_chars",
        "compaction_keep_recent",
    ):
        assert re.search(rf"^\s*{key}\s*:", raw, re.M), f"config.yaml 里没有 {key} 这一行"

    doc = yaml.safe_load(raw)
    assert isinstance(doc, dict) and "context_budget" in doc, "config.yaml 里没有 context_budget 块"
    b = ContextBudget.from_mapping(doc)  # 内含 validate()：三件套必须都开着
    assert (b.threshold_chars, b.head_chars, b.tail_chars) == (8000, 3000, 1000)
    assert b.spill_dir == "spill"
    assert b.max_inline_bytes == 64_000
    assert b.compaction_threshold_chars == 200_000
    assert b.compaction_keep_recent == 8


def test_budget_defaults_are_all_on():
    """默认值必须都开着（FC-17："三件套必须开"）。

    若默认关着，这条约束就只在"有人主动去配"的时候存在 ——
    而 FC-17 的存在理由恰恰是"没人会主动去配它，直到任务撞上墙"。
    """
    b = ContextBudget()
    assert b.threshold_chars > 0
    assert b.max_inline_bytes > 0
    assert b.compaction_threshold_chars > 0
    b.validate()  # 不抛
    assert b.to_mapping()["head_chars"] == 3000


def test_from_mapping_accepts_block_or_whole_document():
    """两种入参都要能用：整份配置（含块）与块本身。缺键用默认。"""
    whole = {"store": {"root": "."}, "context_budget": {"threshold_chars": 9000}}
    block = {"threshold_chars": 9000}
    for cfg in (whole, block):
        b = ContextBudget.from_mapping(cfg)
        assert b.threshold_chars == 9000
        assert b.head_chars == 3000, "缺的键必须回落到默认值"
    assert ContextBudget.from_mapping(None) == ContextBudget()


def test_from_mapping_rejects_unknown_key():
    """负控：拼错的键必须抛。

    把 `threshold_char`（少个 s）静默忽略，等于"用户以为改了阈值、实际没改" ——
    这正是"不许静默兜底"要拦的那类失败。
    """
    with pytest.raises(ValueError, match="未知配置键"):
        ContextBudget.from_mapping({"threshold_char": 9000})


# ============================================================ 剪枝：三态与边界


def test_prune_state_1_not_over_threshold(tmp_path: Path):
    """三态①：没超阈值 ⇒ 原样返回，且 `reason` 非空并说明"未超阈值"。"""
    r = prune("短文本", budget=ContextBudget(), spill_root=tmp_path)
    assert isinstance(r, PrunedText)
    assert (r.pruned, r.spilled, r.spill_path) == (False, False, None)
    assert r.text == "短文本"
    assert r.original_chars == r.kept_chars == len("短文本")
    assert r.reason.strip(), "空 reason 会让'没剪'与'忘了剪'无法区分"
    assert "未超阈值" in r.reason
    assert not list(tmp_path.rglob("*")), "没剪就不该在盘上留下任何东西"


def test_prune_boundary_is_inclusive(tmp_path: Path):
    """边界：恰好等于阈值 ⇒ 不剪；多一个字符 ⇒ 剪。"""
    b = ContextBudget()
    exactly = "a" * b.threshold_chars
    r0 = prune(exactly, budget=b, spill_root=tmp_path)
    assert r0.pruned is False and "未超阈值" in r0.reason
    r1 = prune(exactly + "a", budget=b, spill_root=tmp_path)
    assert r1.pruned is True and "剪枝" in r1.reason


def test_prune_keeps_head_and_tail_and_states_how_much_was_dropped(tmp_path: Path):
    """剪枝的形状：head + "省略 N 字符" + tail。

    尾部必须留：长输出的尾部往往是错误信息 / 退出码 / UNSAT core
    （DSH 的 `tailChars: 1024` 就是为这个留的），只砍尾巴会把最该看的东西砍掉。
    """
    b = ContextBudget()
    text = "".join(f"L{i:06d}\n" for i in range(5000))
    r = prune(text, budget=b, spill_root=tmp_path)
    removed = len(text) - b.head_chars - b.tail_chars
    assert r.pruned is True
    assert r.text.startswith(text[: b.head_chars])
    assert r.text.endswith(text[-b.tail_chars :])
    assert f"省略 {removed} 字符" in r.text and f"原 {len(text)} 字符" in r.text
    assert r.kept_chars == len(r.text) < r.original_chars == len(text)


def test_prune_state_2_no_spill_root_is_reported_honestly():
    """三态②：超阈值 + 没给 `spill_root` ⇒ `pruned=True, spilled=False`，
    且 `reason` 必须说清"没提供 spill_root / 未能落盘"。

    这一态与"已落盘"不是同一件事：前者意味着被省略的中间部分
    目前没有保存在任何地方。把它们折叠成一个 `pruned=True` 就是把
    "数据丢了"伪装成"数据落盘了"。
    """
    b = _spill_budget()
    r = prune(BIG, budget=b, spill_root=None)
    assert (r.pruned, r.spilled, r.spill_path) == (True, False, None)
    assert "未提供 spill_root" in r.reason and "未能落盘" in r.reason
    # 它确实需要落盘：剪枝后的内联仍超上限（否则这一态无从谈起）
    assert len(r.text.encode("utf-8")) > b.max_inline_bytes


def test_prune_state_3_with_spill_root_writes_a_file(tmp_path: Path):
    """三态③：超阈值 + 给了 `spill_root` ⇒ `spilled=True` 且路径真的存在。"""
    b = _spill_budget()
    r = prune(BIG, budget=b, spill_root=tmp_path)
    assert (r.pruned, r.spilled) == (True, True)
    assert r.spill_path is not None
    p = Path(r.spill_path)
    assert p.is_file() and p.parent == tmp_path / b.spill_dir
    assert p.read_bytes() == BIG.encode("utf-8")


def test_prune_reports_spill_failure_instead_of_pretending(tmp_path: Path):
    """负控：落盘路径被占住（那是个文件，不是目录）⇒ 必须如实报"落盘失败"。

    不许静默兜底成"已落盘"，也不许把异常抛出去打断智能体的循环：
    退回"已剪枝但未落盘"这一态，并在 reason 里说明中间部分没保存。
    """
    blocker = tmp_path / "spill"
    blocker.write_text("占位", encoding="utf-8")
    r = prune(BIG, budget=_spill_budget(), spill_root=tmp_path)
    assert r.pruned is True and r.spilled is False and r.spill_path is None
    assert "落盘失败" in r.reason


def test_prune_rejects_non_str_and_bad_budget():
    """负控：类型不对就抛，不做 `str()` 这种静默转换。"""
    with pytest.raises(ValueError, match="只接受 str"):
        prune(b"bytes is not str", budget=ContextBudget())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ContextBudget"):
        prune("x", budget={"threshold_chars": 8000})  # type: ignore[arg-type]


# ============================================================ 判据②：超大结果 → 剪枝/落盘


def test_oversized_tool_result_is_pruned_and_spilled_item_by_item(tmp_path: Path):
    """判据②：> 500 KB 的工具结果必须被剪枝/落盘，而不是撑爆上下文。

    逐项核对，不是"看着像"：

    1. 靶子确实 > 500 KB；
    2. 内联长度 ≤ `max_inline_bytes`（按字节，与字段名同口径）；
    3. 落盘文件真的存在；
    4. 文件名 = `<sha256 前 16 位>-result.txt`；
    5. 盘上内容的 sha256 == 文件名的前 16 位 == 原文的 sha256；
    6. 内联里记录的字节数 == 文件实际大小；
    7. 内联里带 sha256 前 16 位 —— 否则读者无法判断"落盘的到底是不是我以为的那份"；
    8. 内联里带相对路径与"怎么读"的指示；
    9. 信息守恒：原文能从盘上逐字节取回；
    10. 原子写不留临时文件残渣。
    """
    assert len(BIG) > 500_000, f"靶子只有 {len(BIG)} 字符，够不上'超大'"
    b = _spill_budget()
    r = prune(BIG, budget=b, spill_root=tmp_path)

    # 1) 剪枝后的内联必须在上限之内（这才是"没撑爆上下文"）
    assert r.pruned is True
    assert len(r.text.encode("utf-8")) <= b.max_inline_bytes

    # 2) 确实需要落盘（否则这个用例没在验证落盘）
    assert r.spilled is True and r.spill_path
    p = Path(r.spill_path)
    assert p.is_file(), f"落盘文件不存在：{p}"

    digest = hashlib.sha256(BIG.encode("utf-8")).hexdigest()
    assert p.name == f"{digest[:16]}-result.txt", "文件名必须是 <sha256 前 16 位>-result.txt"
    file_bytes = p.read_bytes()
    assert hashlib.sha256(file_bytes).hexdigest() == digest, "盘上内容必须与原文逐字节一致"
    assert p.name.split("-")[0] == hashlib.sha256(file_bytes).hexdigest()[:16]

    m = re.search(r"（(\d+) 字节", r.text)
    assert m, f"内联里没有记录字节数：{r.text!r}"
    recorded = int(m.group(1))
    assert recorded == p.stat().st_size == len(BIG.encode("utf-8"))
    assert f"sha256:{digest[:16]}" in r.text
    assert f"spill/{p.name}" in r.text, "内联里必须给相对路径，否则读者找不到文件"
    assert "read" in r.text and "offset" in r.text, "内联里必须说清'怎么读'"
    assert f"sha256:{digest[:16]}" in r.reason, "reason 也要能自证'落的是这一份'"

    # 信息守恒 + 不留残渣
    assert file_bytes == BIG.encode("utf-8")
    assert list((tmp_path / b.spill_dir).glob("*.tmp-*")) == [], "落盘后不该留下临时文件"
    assert r.original_chars == len(BIG)
    assert r.kept_chars == len(r.text)


def test_default_numbers_make_spill_unreachable_from_prune(tmp_path: Path):
    """把默认数值的几何事实写进测试：默认配置下"落盘"分支不可达。

    `head_chars + tail_chars = 4000` 远小于 `max_inline_bytes = 64000`，
    剪枝后的文本永远进不了落盘分支 ⇒ 只靠 `prune()`，"spill 开着"这件事
    在默认数值下是看不出来的。这条用例把这个事实钉住：
    一旦有人调大了 head/tail（或调小了上限），它会立刻变红，逼人重新核对。
    """
    b = ContextBudget()
    r = prune(BIG, budget=b, spill_root=tmp_path)
    assert r.pruned is True and r.spilled is False
    assert len(r.text.encode("utf-8")) <= b.max_inline_bytes
    assert b.head_chars + b.tail_chars < b.max_inline_bytes, "默认数值的几何关系变了，请重新读这条用例"
    assert not (tmp_path / b.spill_dir).exists()


# ============================================================ prune_tool_result：不改结论


def test_prune_tool_result_never_changes_the_conclusion(tmp_path: Path):
    """负控：剪枝不该让失败变成成功，也不该反过来。

    `ok` / `error` 必须逐字段保留：剪枝是"少看点内容"，不是"改判"。
    """
    b = _spill_budget()
    good = ToolResult(ok=True, data={"body": BIG, "n": 3}, error=None, meta={"tool": "demo.huge"})
    bad = ToolResult(ok=False, data=None, error="读取失败：文件不存在", meta={"kind": "tool_error"})
    for src in (good, bad):
        out = prune_tool_result(src, budget=b, spill_root=tmp_path)
        assert isinstance(out, ToolResult) and out is not src, "必须返回**新**结果，不改调用方手上那个"
        assert out.ok is src.ok, "剪枝改变了结论"
        assert out.error == src.error, "剪枝改了 error"
        assert src.meta == ({"tool": "demo.huge"} if src is good else {"kind": "tool_error"}), "入参被就地改动了"
    assert prune_tool_result(good, budget=b, spill_root=tmp_path).ok is True
    assert prune_tool_result(bad, budget=b, spill_root=tmp_path).ok is False


def test_prune_tool_result_records_audit_meta(tmp_path: Path):
    """`meta` 必须记清"剪了几个、落没落盘、落在哪、原来多少字符"。"""
    b = _spill_budget()
    out = prune_tool_result(
        ToolResult(ok=True, data={"big": BIG, "small": "短"}, error=None, meta={"tool": "x"}),
        budget=b,
        spill_root=tmp_path,
    )
    assert out.meta["tool"] == "x", "既有 meta 不许被丢掉"
    assert out.meta["pruned"] is True
    assert out.meta["spilled"] is True
    assert isinstance(out.meta["spill_path"], str) and Path(out.meta["spill_path"]).is_file()
    assert out.meta["spill_paths"] == [out.meta["spill_path"]]
    assert out.meta["prune_count"] == 1
    assert out.meta["original_chars"] == len(BIG) + len("短")
    assert out.meta["kept_chars"] < out.meta["original_chars"]
    assert out.meta["prune_reasons"] and "剪枝" in out.meta["prune_reasons"][0]
    assert "落盘" in out.meta["prune_note"]


def test_prune_tool_result_on_small_data_says_so(tmp_path: Path):
    """没有大字符串时：`pruned=False`，且 note 非空说明"没剪"（而不是留白）。"""
    out = prune_tool_result(ToolResult(ok=True, data={"a": "短"}, error=None, meta={}), budget=ContextBudget())
    assert out.meta["pruned"] is False and out.meta["spilled"] is False
    assert out.meta["spill_path"] is None and out.meta["spill_paths"] == []
    assert "没有任何字符串超过" in out.meta["prune_note"]


def test_prune_tool_result_walks_nested_containers_and_keeps_keys(tmp_path: Path):
    """嵌套结构要走到；dict 的键不动（改键是改 schema，不是剪枝）。"""
    b = _spill_budget()
    data = {"rows": [{"quote": BIG}], "note": ("a", "b")}
    out = prune_tool_result(ToolResult(ok=True, data=data, error=None, meta={}), budget=b, spill_root=tmp_path)
    assert list(out.data) == ["rows", "note"]
    assert out.data["rows"][0]["quote"] != BIG and "已落盘" in out.data["rows"][0]["quote"]
    assert out.data["note"] == ("a", "b"), "元组要保持元组"
    assert data["rows"][0]["quote"] == BIG, "入参 data 被就地改动了"


def test_prune_tool_result_leaves_error_text_alone(tmp_path: Path):
    """记录在案的边界：本层只剪 `data`，不碰 `error`（error 是结论的一部分）。

    即使 error 很长也不剪 —— 这是刻意的：把失败原因剪掉，等于让"失败"变得不可诊断。
    """
    long_error = "E" * 20_000
    out = prune_tool_result(ToolResult(ok=False, data=None, error=long_error, meta={}), budget=ContextBudget())
    assert out.error == long_error
    assert out.meta["pruned"] is False
    assert "没有任何字符串超过" in out.meta["prune_note"]


def test_prune_tool_result_rejects_non_toolresult():
    """负控：鸭子类型判定也要响 —— 不是"有 data 就行"。"""
    with pytest.raises(ValueError, match="dataclass"):
        prune_tool_result({"ok": True, "data": "x", "error": None, "meta": {}}, budget=ContextBudget())


# ============================================================ compact：确定性 / 保留策略 / 三态


def test_compact_is_deterministic_without_summarize():
    """不给 `summarize` ⇒ 确定性的机械摘要：跑两次逐字节相同。

    FC-16：确定性的部分绝不交给 LLM。机械摘要只报计数，不含正文、不调模型、
    不含时间戳/随机数 —— 否则"同一份历史两次压缩结果不同"会让一切回放失效。
    """
    items = _items()
    b = ContextBudget()
    r1 = compact(items, budget=b)
    r2 = compact(items, budget=b)
    assert isinstance(r1, CompactResult)
    assert r1.text.encode("utf-8") == r2.text.encode("utf-8")
    assert r1 == r2
    assert r1.summarizer == "mechanical" and r1.compacted is True
    early_chars = sum(len(t) for t in items[:12])
    assert f"早期 12 条，共 {early_chars} 字符" in r1.text


def test_compact_keeps_the_most_recent_n_verbatim():
    """保留策略：20 条 ⇒ 最后 8 条原文保留，更早的 12 条被折进摘要。"""
    items = _items()
    b = ContextBudget()  # compaction_keep_recent=8
    r = compact(items, budget=b)
    assert (r.dropped_count, r.kept_count) == (12, 8)
    for t in items[12:]:
        assert t in r.text, "最近的条目必须**逐字**保留（摘要不能替代原文）"
    for t in items[:12]:
        assert t not in r.text, "早期条目不该以原文形式出现在压缩结果里"
    assert r.original_chars == sum(len(t) for t in items)
    assert r.kept_chars == len(r.text)


def test_compact_uses_injected_summarizer_and_says_so():
    """给了 `summarize` ⇒ `summarizer="injected"`，且它收到的是被折掉的那批条目。"""
    items = _items()
    got: list[list[str]] = []

    def summarize(early: list[str]) -> str:
        got.append(list(early))
        return f"[注入摘要] {len(early)} 条"

    r = compact(items, budget=ContextBudget(), summarize=summarize)
    assert r.summarizer == "injected" and r.compacted is True
    assert got == [items[:12]]
    assert "[注入摘要] 12 条" in r.text
    assert r.text != compact(items, budget=ContextBudget()).text, "注入摘要必须真的被用上"


def test_compact_state_3_over_threshold_but_nothing_to_drop():
    """三态③：超阈值，但条目数 ≤ `compaction_keep_recent` ⇒ 没有压缩。

    这一态必须与"压缩过了"分开：`compacted=False, summarizer="none"`，
    且 reason 说清"没有更早的条目可折"。注入的 `summarize` 不会被调用 ——
    调了却不采用，比不调更坏。
    """
    called: list[int] = []

    def never_call_me(early: list[str]) -> str:
        called.append(len(early))
        return "不该被调用"

    r = compact(
        ["x" * 600, "y" * 600],
        budget=ContextBudget(compaction_threshold_chars=1000, compaction_keep_recent=8),
        summarize=never_call_me,
    )
    assert (r.compacted, r.summarizer, r.dropped_count) == (False, "none", 0)
    assert called == [], "没有可折的条目时不该调用注入的 summarize"
    assert "没有被调用" in r.reason
    assert "x" * 600 in r.text and "y" * 600 in r.text


def test_compact_below_threshold_does_nothing_and_says_so():
    """三态①：没超阈值 ⇒ 全部原样保留，`summarizer="none"` 且 reason 非空。"""
    items = ["a" * 100, "b" * 100]
    r = compact(items, budget=ContextBudget())
    assert (r.compacted, r.summarizer, r.dropped_count, r.kept_count) == (False, "none", 0, 2)
    assert "未超阈值" in r.reason and r.reason.strip()
    assert all(t in r.text for t in items)
    # kept_chars 的口径 = 实际渲染出来的文本的字符数（与 PrunedText.kept_chars 一致）
    assert r.kept_chars == len(r.text) == 200 + len("[1] ") + len("\n[2] ")


def test_compact_rejects_empty_summary_and_bad_items():
    """负控：注入的摘要返回非 str / 空串必须抛；非法条目同样抛。"""
    items = _items()
    b = ContextBudget()
    with pytest.raises(ValueError, match="非空 str"):
        compact(items, budget=b, summarize=lambda early: None)  # type: ignore[arg-type,return-value]
    with pytest.raises(ValueError, match="非空 str"):
        compact(items, budget=b, summarize=lambda early: "   ")
    with pytest.raises(ValueError, match="有序序列"):
        compact("这是一个字符串，不是条目列表", budget=b)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="有序序列"):
        compact({"a", "b"}, budget=b)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="缺 'text' 键"):
        compact([{"content": "x"}] * 20, budget=b)  # type: ignore[list-item]
    with pytest.raises(ValueError, match="必须是 str"):
        compact([{"text": 1}] * 20, budget=b)  # type: ignore[list-item]


def test_compact_accepts_mapping_items():
    """mapping 条目：只看 `text` 键，其它键留给调用方。"""
    items = [{"text": f"第{i:03d}条：" + "x" * 12_000, "role": "C"} for i in range(20)]
    r = compact(items, budget=ContextBudget())
    assert r.compacted is True and r.dropped_count == 12
    assert items[19]["text"] in r.text


# ============================================================ 配置校验负控


def test_validate_rejects_head_plus_tail_not_shorter_than_threshold():
    """负控：`head + tail >= threshold` ⇒ 抛。

    头 + 尾已经不比原文短，再加省略标记就是把内容变长 ——
    这种配置下"剪枝"是净增长，必须拒绝。
    """
    with pytest.raises(ValueError, match="自相矛盾"):
        ContextBudget(head_chars=7000, tail_chars=1000, threshold_chars=8000).validate()
    with pytest.raises(ValueError, match="自相矛盾"):
        ContextBudget(head_chars=4000, tail_chars=4000, threshold_chars=8000).validate()


def test_validate_rejects_zeroed_triple():
    """负控：三件套里任何一件被关掉（= 0）⇒ validate() 抛。"""
    for kw in (
        {"threshold_chars": 0},
        {"max_inline_bytes": 0},
        {"compaction_threshold_chars": 0},
    ):
        with pytest.raises(ValueError, match="三件套"):
            ContextBudget(**kw).validate()


def test_validate_rejects_bad_shapes():
    """负控：负数、空目录、绝对路径、`..` 逃逸全部拒绝。"""
    with pytest.raises(ValueError, match=">= 0"):
        ContextBudget(head_chars=-1).validate()
    with pytest.raises(ValueError, match=">= 0"):
        ContextBudget(compaction_keep_recent=-1).validate()
    with pytest.raises(ValueError, match="非空字符串"):
        ContextBudget(spill_dir="").validate()
    with pytest.raises(ValueError, match="相对目录"):
        ContextBudget(spill_dir=str(_ROOT)).validate()
    with pytest.raises(ValueError, match="相对目录"):
        ContextBudget(spill_dir="../escape").validate()


def test_from_mapping_rejects_stringly_typed_numbers():
    """负控：字符串型数字 ⇒ 抛（不许静默转）。"""
    for bad in ({"threshold_chars": "8000"}, {"max_inline_bytes": "64000"}):
        with pytest.raises(ValueError, match="必须是整数"):
            ContextBudget.from_mapping(bad)
    with pytest.raises(ValueError, match="必须是整数"):
        ContextBudget.from_mapping({"head_chars": 3000.0})
    with pytest.raises(ValueError, match="必须是整数"):
        ContextBudget.from_mapping({"tail_chars": True})


def test_from_mapping_propagates_validate_failures():
    """负控：装载即校验（fail-closed）——"三件套没开"在读配置时就炸，
    而不是等某个工具返回 500 KB 文本时才炸。"""
    with pytest.raises(ValueError, match="三件套"):
        ContextBudget.from_mapping({"compaction_threshold_chars": 0})
    with pytest.raises(ValueError, match="自相矛盾"):
        ContextBudget.from_mapping({"threshold_chars": 100, "head_chars": 90, "tail_chars": 10})


# ============================================================ 既有行为零变化 + 无循环依赖


def test_registry_call_without_budget_returns_exactly_what_it_used_to(store):
    """既有行为零变化：`call` 不传 `budget` 时，返回值与加 FC-17 之前一致。

    这里的期望值是改动前手抄下来的（`{"data": 0, "error": null, "meta": {...}, "ok": true}`）——
    写成"结构性断言"（只查键存在）会漏掉"多塞了一个 meta 键"这种静默变化。

    并表（`SCHEMA_VERSION=2`）之后这张表换成了 `statements`：本条钉的是
    `table.count` 的返回值逐字段不变（含 `meta.table` 回显），
    与表名无关；`concepts` 已经不在 `schema.TABLES` 里，拿它做标本会让这条
    变成"参数错误"的断言 —— 那是另一件事。
    """
    reg = build_registry(store=store, workspace_root=store.root).registry
    # `P-14`：完整注册表默认不绑定角色 ⇒ `call` 一律被拒。本用例测的是"不传 budget
    # 时返回值逐字段不变"，所以先绑定一个合法角色（`table.count` 的角色含 A）。
    reg.bound_role = "A"
    res = reg.call("table.count", table="statements")
    assert res.to_dict() == {
        "ok": True,
        "data": 0,
        "error": None,
        "meta": {"filtered": False, "table": "statements", "total": 0},
    }
    assert "pruned" not in res.meta and "spilled" not in res.meta, "不传 budget 就不该出现剪枝痕迹"


def test_registry_call_does_not_prune_automatically(store):
    """负控（最关键的一条）：不传 `budget` 时，>500 KB 的返回值逐字符不变。

    若哪天有人"顺手"把剪枝接进 `ToolRegistry.call` 的默认路径，
    所有既有调用方拿到的数据都会悄悄变短 —— 这条用例会立刻变红。
    """
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"  # `P-14`：见 test_registry_call_without_budget_… 的同一条注释
    reg.register(
        ToolSpec(
            name="demo.huge",
            summary="返回一个超大字符串",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok({"body": BIG}),
            returns="{'body'}（超长字符串）",
            roles=("A",),
        )
    )
    res = reg.call("demo.huge")
    assert res.ok is True and res.data == {"body": BIG}
    assert len(res.data["body"]) == len(BIG) and res.meta == {}


def test_registry_call_with_budget_prunes_and_spills(tmp_path: Path):
    """显式传 `budget` 时才剪枝；且 `ok` 不变、内联在上限内、文件在盘上。"""
    b = _spill_budget()
    reg = ToolRegistry(name="t")
    reg.bound_role = "A"  # `P-14`：见 test_registry_call_without_budget_… 的同一条注释
    reg.register(
        ToolSpec(
            name="demo.huge",
            summary="返回一个超大字符串",
            params={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda: ok({"body": BIG}),
            returns="{'body'}（超长字符串）",
            roles=("A",),
        )
    )
    res = reg.call("demo.huge", budget=b, spill_root=tmp_path)
    assert res.ok is True and res.error is None
    assert res.meta["pruned"] is True and res.meta["spilled"] is True
    assert Path(res.meta["spill_path"]).is_file()
    assert len(res.data["body"].encode("utf-8")) <= b.max_inline_bytes


def test_budget_keyword_is_not_stolen_from_tools_that_declare_it(store):
    """`budget` 的名字冲突：工具自己声明了 `budget` 参数时，它属于工具。

    这不是假想：`attack.check_budget` / `attack.create_plan` 真的有一个 `budget`
    参数（FC-18 的四维预算）。消歧规则读注册表即可判断，没有隐藏状态。
    """
    real = build_registry(store=store, workspace_root=store.root).registry.get("attack.create_plan")
    assert "budget" in (real.params.get("properties") or {}), "前提变了：这个工具不再声明 budget 参数"

    reg = ToolRegistry(name="t")
    reg.bound_role = "A"  # `P-14`：见 test_registry_call_without_budget_… 的同一条注释
    reg.register(
        ToolSpec(
            name="demo.own_budget",
            summary="我自己就有 budget 参数",
            params={
                "type": "object",
                "properties": {"budget": {"type": "object"}},
                "required": ["budget"],
                "additionalProperties": False,
            },
            handler=lambda budget: ok({"got": budget}),
            returns="{'got'}（回显传进来的 budget）",
            roles=("A",),
        )
    )
    res = reg.call("demo.own_budget", budget={"max_rounds": 3})
    assert res.ok is True and res.data == {"got": {"max_rounds": 3}}
    assert "pruned" not in res.meta, "工具自己的 budget 不该触发上下文剪枝"


def test_contextbudget_import_does_not_pull_in_tools_base():
    """无循环依赖：`import agentflow.contextbudget` 成功，且不会拉起 `tools.base`。

    为什么这条必须是子进程：pytest 是一个进程跑完所有用例，
    `sys.modules` 里早就装满了别人的模块 —— 在同进程里断言"没被 import"
    是测不出东西的（那正是"看着像验证"）。
    """
    root = _ROOT
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    code = (
        "import sys; import agentflow.contextbudget as C;"
        " assert 'agentflow.tools' not in sys.modules, sorted(sys.modules);"
        " assert 'agentflow.tools.base' not in sys.modules;"
        " print(C.ContextBudget().threshold_chars)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(root)
    )
    assert proc.returncode == 0, f"import 失败：{proc.stdout}\n{proc.stderr}"
    assert proc.stdout.strip() == "8000"


def test_contextbudget_has_no_module_level_tools_import():
    """同一件事的静态版本：源码的模块级 import 里不许出现 `tools`。

    与子进程用例互补：子进程证明"现在没循环"，AST 检查说明"为什么不可能循环"
    （局部导入是唯一的入口，见 `ToolResult.pruned`）。
    """
    import agentflow.contextbudget as C

    tree = ast.parse(Path(C.__file__).read_text(encoding="utf-8"))
    for node in tree.body:  # 只看模块层，函数内的局部导入不算
        if isinstance(node, ast.Import):
            assert all("tools" not in a.name for a in node.names), ast.dump(node)
        elif isinstance(node, ast.ImportFrom):
            assert "tools" not in (node.module or ""), ast.dump(node)
