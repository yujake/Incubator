"""工具层审计修复的性质测试（每一条修复都有正/负两个方向）。

对应 `temp/inventory/INVENTORY.md` 第 4 节「可疑清单」里被点名、并且在本轮修掉的条目。
本文件刻意不复述实现细节：每一条断言都打在"新的、正确的判据"上 ——
也就是"修之前这一条会失败"的那个判据。凡是能造出"好数据/坏数据"两面的，
都成对写（只有绿灯证明不了闸门在工作）。

条目对照（缺陷 → 本文件的用例）：

| 缺陷 | 用例 |
|---|---|
| P0-1 `review.scan_document` 依赖没查却判 accepted | `test_scan_document_*` |
| P0-2 `doc.build_document` 允许假引用落库 | `test_build_document_*` / `test_check_citations_*` |
| P1-3/4 `search.providers` / `ocr.run` / `ocr.backends` 的 side_effect 说假话 | `test_side_effect_*` |
| P1-5 `r-NNNN` 三份分配器语义冲突 | `test_request_id_*` |
| P1-6 `search.dedup_check` 读表失败静默报「不是重复」 | `test_dedup_check_*` / `test_literature_*` |
| P1-7 `trace.chain` 无图可查却报 ok | `test_trace_*` |
| P2-8/9 `verify.detect_verifier` / `check_formal` 声明与实现不一致 | `test_detect_verifier_*` / `test_check_formal_*` |
| P2-10 非 `ToolError` 逃逸成无声的 `unexpected` | `test_no_unexpected_escape_*` |
| 4.5 docstring 与实现不一致（trace L3 词表、returns= 漂移、H/G 判据漂移） | `test_l3_status_*` / `test_declared_returns_*` / `test_scan_document_matches_scan_claim_*` |
"""

from __future__ import annotations

import ast
import json
import re
import shutil
from pathlib import Path

import pytest

from agentflow import formalgw as FG
from agentflow import interactions as IX
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import doc_tools as DT
from agentflow.tools import ocr_tools as OT
from agentflow.tools import research_tools as RT
from agentflow.tools import review_tools as RV
from agentflow.tools import search_tools as ST
from agentflow.tools import table_tools as TT
from agentflow.tools import trace_tools as TR
from agentflow.tools import verify_tools as VT
from agentflow.tools.base import ToolError, ToolRegistry

from conftest import add_literature, add_request, write_library_file

TS = "2026-01-01T00:00:00+00:00"


# ============================================================ 小工具


def clean_claim(**over: object) -> dict:
    """一条完全合规的断言（与 test_agent_h 的同类夹具同形，但本文件自带一份，
    避免测试文件之间互相 import 造成的隐式耦合）。

     与 `test_agent_h.clean_claim` 同办：`evidence_kind` 是 `cross_check`。
    这条断言的引文只有一条关系与一页文献，没有形式化检查器参与，
    标成 `proof` 是误标（`D-1` 的写入期判据会拒它）。
    随之而来的一处必须一起改：`cross_check` 的「不构成证明」声明是结构强制的
    （少它就报 `overclaim`），所以 `disclaimer` 必须填上 —— 否则"合规夹具"变成坏样本。
    """
    claim = {
        "claim_id": "claim-1",
        "section": "主要结果",
        "text": "谱落在区间内。",
        "evidence_kind": "cross_check",
        "citations": ["rel:0000", "lit:0000#p.12-13"],
        "is_negative": False,
        "negation_kind": None,
        "disclaimer": DT.CROSS_CHECK_DISCLAIMER,
    }
    claim.update(over)
    return claim


def doc_row(doc_id: str = "0000", claims: list[dict] | None = None, *, status: str = "draft") -> dict:
    return S.Document(
        doc_id=doc_id,
        kind="paper",
        title=f"稿件 {doc_id}",
        markdown_path=None,
        claims=[dict(c) for c in (claims or [clean_claim()])],
        status=status,
        review_rounds=0,
        created_at=TS,
        updated_at=TS,
    ).to_dict()


def seed_document(store: Store, row: dict) -> None:
    """经 store 写一行合法稿件（schema 会把关 —— 坏样本另用直接改盘的方式造）。"""
    S.row_from_dict("documents", row).validate()
    with store.tx("documents", actor="test", note="fixture") as tx:
        tx.upsert("documents", row)


def parse_declared_keys(returns: str) -> tuple[set[str], str]:
    """三态入口：从 `ToolSpec.returns` 里抽键名，并把"抽的结果"如实分类。

    返回值是 ``(键集合, 状态)``，状态取三个值之一：

    ======================  ==========================================================
    状态                     含义
    ======================  ==========================================================
    ``"parsed"``            抽到了至少一个键 —— 声明是机器可读的
    ``"empty_declaration"`` 声明本身是空串/全空白 —— 这个工具没有声明返回形状
    ``"unparseable"``       声明非空，但一个键都抽不出来 —— 说明它不是键列表写法
    ======================  ==========================================================

    ## 为什么要有这个函数（三态纪律）

    旧的 `declared_keys` 返回空集表达"没抽到"，而空集在下游是真空通过 ——
    "我没抽到键"与"它没有键"是两件事，必须分开（三态纪律）。

    这条纪律在本仓库里已经付过代价：下游断言是 ``declared - actual == set()``，
    而空集永远是任何集合的子集 ⇒ 一个 ``returns="data={src, dst}"`` 这样不带引号
    的声明会让"声明 vs 实现一致"这条判据静默地什么都不检查。本轮实测：
    55 个工具里有 36 个（65%）的 `returns=` 属于这种写法，也就是说这条判据
    在三分之二的工具上从来没有真正执行过（改声明不会红、改实现也不会红）。

    所以：判据必须建立在非空键集合上，而"抽不到"必须是一个可判定的事实、
    而不是一个恰好能被当成"通过"的空集。谁要放行 `unparseable`，必须显式
    在豁免清单里写出理由（见 `tests/test_tools_returns_declaration.py`）。

    解析规则刻意保持与旧实现逐字一致（只认单引号包裹的
    ``'[a-z_][a-z0-9_]*'``）：本轮不改判据的"严格程度"，只把"没抽到"从不合格
    的空集提升为一个会被检查的状态。
    """
    if not (returns or "").strip():
        return set(), "empty_declaration"
    keys = set(re.findall(r"'([a-z_][a-z0-9_]*)'", returns))
    return (keys, "parsed") if keys else (set(), "unparseable")


def declared_keys(returns: str) -> set[str]:
    """从 `ToolSpec.returns` 里抽出它承诺的键名（只取键的薄封装）。

    这是本文件里"声明与实现一致"这条判据的机器可读入口：声明写成
    ``{'a','b'}`` 这样的键列表，测试逐字解析它去和实际返回的键集合比对 ——
    于是"声明一套、返回另一套"不可能再悄悄发生（改声明就会红，改实现也会红）。

    它只回答"键是什么"，不回答"抽到没有" —— 抽不到时它返回空集，
    而空集在下游是真空通过。要判"这份声明到底能不能机器读"，请用
    :func:`parse_declared_keys`（三态：parsed / empty_declaration / unparseable）。
    本函数保留（签名与返回值逐字不变）只是为了不连累既有的调用方，
    实现上转发给三态入口，避免同一判据长出两份实现（linter R003 会抓）。
    """
    return parse_declared_keys(returns)[0]


def registry_for(module: object, store: Store, **kw: object) -> ToolRegistry:
    """注册一个模块的工具，并按模块绑定角色（`P-14`）。

    `P-14` 之后 `call` 需要"这次是谁在调"：角色面是模块级知识（见
    `_MODULE_ROLE`），测试只是把它写下来，不是自己发明一个角色。
    """
    reg = ToolRegistry(name="audit")
    module.register(reg, store=store, **kw)  # type: ignore[attr-defined]
    reg.bound_role = _role_for_module(module, reg)
    return reg


#: `registry_for` 的模块 -> 该表代表的角色。写错会被 `_role_for_module` 的断言抓住
#: （它要求该角色在这张表里真的拿得到工具）。
_MODULE_ROLE: dict[str, str] = {
    "doc_tools": "G",        # `doc.*` 的写侧主人是 G
    "ocr_tools": "B",        # `ocr.*` 只有 B
    "research_tools": "D",   # `research.*` 只有 D
    "review_tools": "H",     # 审校工具（含 H 的落库代理）
    "search_tools": "A",     # `search.*` 只有 A
    "table_tools": "A",      # `table.*` 的角色含 A/B/C/D/E/F/G —— 取非只读的 A
    "trace_tools": "C",      # C/D 共用，取只读的 C
    "verify_tools": "E",     # `verify.*` 的角色含 E/F/G/H，写侧含 E
}


def _role_for_module(module: object, reg: ToolRegistry) -> str:
    """按模块名查 `_MODULE_ROLE`，并断言该角色在这张表里真的拿得到工具。"""
    mod_name = getattr(module, "__name__", "").rsplit(".", 1)[-1]
    role = _MODULE_ROLE.get(mod_name)
    assert role, f"模块 {mod_name!r} 没有在 `_MODULE_ROLE` 里登记角色 —— 夹具不知道该代表谁"
    assert reg.for_role(role), f"{mod_name}: 绑的角色 {role!r} 在这张表里拿不到任何工具"
    return role


def corrupt(store: Store, filename: str) -> None:
    """把一张表写成不是合法 JSON 的文件（模拟"快照损坏"这类真实故障）。

    为什么用这种造法而不是打桩：`Store._load` 对坏 JSON 抛 `StoreError`
    （`store.py:297-302`），这正是"表读不出来"在生产里的形态。
    """
    (store.data / filename).write_text("{ 这不是 JSON", encoding="utf-8")


# ============================================================ P0-1 review.scan_document


def test_scan_document_without_dependencies_is_unverified_not_accepted():
    """核心：`dependencies=None` ⇒ `checked=False` ⇒ verdict 不得是 accepted。

    修之前的判据是 `"rejected" if errors else ("accepted_with_warnings" if warnings else "accepted")`
    —— 它完全不读 `dep_check["checked"]`，于是同一个返回值里
    `dep_check` 说"没查依赖闭合"、`verdict` 说"accepted"。
    """
    doc = doc_row()
    unchecked = RV.scan_document(doc)

    assert unchecked["dep_check"]["checked"] is False
    assert unchecked["error_count"] == 0, "这份稿件本身是干净的 —— 问题在于依赖没查"
    assert unchecked["verdict"] not in ("accepted", "accepted_with_warnings"), (
        "依赖闭合没查时不许判通过：那会把'从未检查'读成'检查通过'"
    )
    assert unchecked["verdict"] == "unverified"
    assert "没查" in unchecked["reason"] and "不能判 accepted" in unchecked["reason"], (
        "verdict 必须配一句可读的 reason，否则调用方无从知道 unverified 指的是什么"
    )


def test_scan_document_with_checked_dependencies_may_be_accepted():
    """负控：查了、确实没有未闭合依赖 ⇒ 才可以判 accepted（闸门不能永远关着）。"""
    doc = doc_row()
    # 2026-10-17（业主「通过标准和 V 一样」）：**通过**要求语义层也判过 —— 这里接一个
    # "判过且一致"的替身，于是这条正控仍然是"闸门能开"，而不是把断言降级成 unverified。
    _judge = lambda claim, document: {"verdict": "consistent"}
    checked = RV.scan_document(doc, dependencies=[], semantic_judge=_judge)
    assert checked["dep_check"]["checked"] is True
    assert checked["verdict"] == "accepted"

    warned = RV.scan_document(
        doc,
        semantic_judge=_judge,
        dependencies=[
            {
                "dep_id": "0000",
                "status": "external_unavailable",
                "label": "companion book",
                "status_reason": "不在可得范围内",
            }
        ],
    )
    assert warned["dep_check"]["checked"] is True
    assert warned["verdict"] == "accepted_with_warnings", "已知边界是 warning，不该升级成'没查'"


def test_scan_document_error_dominates_but_never_becomes_accepted():
    """有 error 时是 rejected（无论依赖查没查），但任何时候都不许 accepted*。"""
    bad = clean_claim(citations=[])
    doc = doc_row(claims=[bad])
    unchecked = RV.scan_document(doc)
    assert unchecked["error_count"] == 1
    assert unchecked["verdict"] == "rejected"
    assert unchecked["verdict"] not in ("accepted", "accepted_with_warnings")


def test_scan_document_tool_path_omitted_dependencies_is_unverified(store: Store):
    """工具层：`review.scan_document` 省略 `dependencies` ⇒ unverified（不是 accepted）。

    工具没接 store（`side_effect="none"`），所以"省略"只能等价于"没查"。
    修之前 handler 把省略映射成 `None`，而 verdict 根本不看这个位。
    """
    reg = registry_for(RV, store)
    res = reg.call("review.scan_document", doc=doc_row())
    assert res.ok, res.error
    assert res.data["dep_check"]["checked"] is False
    assert res.data["verdict"] == "unverified"
    # 显式给空清单是"查了" ⇒ 才可能通过
    res2 = reg.call("review.scan_document", doc=doc_row(), dependencies=[])
    # 2026-10-17（业主「通过标准和 V 一样」）：依赖闭合查过还不够 —— **语义层没接线**
    # （工具面接不了 `semantic_judge`）⇒ 这一档只能到 `unverified`，**不许**判通过。
    # 想看到"通过"，得走 `scan_document(..., semantic_judge=…)` 那条入口（见上一条正控）。
    assert res2.data["dep_check"]["checked"] is True
    assert res2.data["verdict"] == "unverified"


def test_scan_document_and_review_document_agree_on_verdict(store: Store):
    """两条入口必须同口径：只读的 `scan_document` 与写库的 `review_document`。

    写入路径早就有 `elif not dep_checked: verdict = "unverified"` 这条纪律
    （`review_tools.py` 的注释写着"不许在这个前提下判 accepted"）；
    这次修的是只读路径与它对齐。若只改一处，"读一遍"与"审一遍"会对同一份稿件
    给出两个都不报错的相反结论。
    """
    seed_document(store, doc_row())
    reader = RV.scan_document(store.rows("documents")[0], dependencies=None)
    writer = RV.review_document(store, "0000", dependencies=None)
    assert writer["dep_check"]["checked"] is False
    assert writer["verdict"] == "unverified"
    assert reader["verdict"] == writer["verdict"], "只读路径与写入路径的 verdict 必须一致"
    assert store.rows("documents")[0]["status"] != "accepted"


@pytest.mark.parametrize(
    ("sample", "expected_kind"),
    [
        (clean_claim(evidence_kind="prooof"), "garbled"),
        (clean_claim(negation_kind="not_proved"), "garbled"),
        (clean_claim(is_negative=True, negation_kind="maybe"), "missing_negation_kind"),
        (clean_claim(citations=["", "  "]), "garbled"),
    ],
    ids=["bad-evidence-kind", "negation-kind-on-positive-claim", "bad-negation-kind", "empty-citation-element"],
)
def test_scan_document_flags_the_checks_it_used_to_miss(sample: dict, expected_kind: str):
    """4.5#10：H 侧曾经漏掉的四条检查，现在必须由 H 自己判出来（不依赖 G）。

    这四条是 H 与 G 漂移的实证：修之前它们只在 G 侧有，H 会把同一份稿件读成干净的。
    这里不经过 G，直接打在 H 上 —— 于是"另一路的判据层怎么演进"都不会让本用例
    变得没有意义。
    """
    h = RV.scan_document(doc_row(claims=[sample]), dependencies=[])
    kinds = {f["kind"] for f in h["findings"] if f["level"] == "error"}
    assert expected_kind in kinds, f"H 没判出 {expected_kind}：{h['findings']}"
    assert h["error_count"] >= 1
    assert h["verdict"] == "rejected"
    # 负控：合规样本不许被这些新检查误伤
    assert RV.scan_document(doc_row(), dependencies=[])["error_count"] == 0


def test_scan_document_never_passes_a_document_that_g_rejects():
    """4.5#10 的危险方向：G 判 error ⇒ H 也必须判 error（H 可以更严，不许更松）。

    "G 认为违规、H 认为通过"是没有任何报错的静默分裂 —— 它会让审校环节
    变成 G 的橡皮图章。反向（H 更严）是安全的：H 面对的是盘上可能绕过 schema
    写进来的历史行，fail-closed 是它的本分。

    # 待修：G 侧的判据层正在被迁移到 `agentflow.claimanatomy`（本轮实测到它在
    # 十几分钟内改了两次 code→kind 映射：`unknown_status_axis` 先映射成
    # `missing_negation_kind`、后映射成 `scope_drift`；`negation_kind='maybe'`
    # 一度在 G 侧不产生 error）。因此当 G 对某个样本当前没有 error 时，
    # 本用例跳过该样本（无法断言"G 判 error"这件事），只把它记进这段话里。
    # 彻底消除漂移的正解是让 `scan_document` 也转发 `claimanatomy`
    # （同一份判据 + 同一份 code→kind 映射）—— 那要等 claimanatomy 稳定后再做，
    # 已上报主控。
    """
    samples = [
        clean_claim(evidence_kind="prooof"),
        clean_claim(negation_kind="not_proved"),
        clean_claim(is_negative=True, negation_kind="maybe"),
        clean_claim(citations=["", "  "]),
        clean_claim(text="因此我们已证明 X。", evidence_kind="cross_check"),
    ]
    checked = 0
    for sample in samples:
        g = DT.scan_claim(sample)
        assert g["findings"], f"夹具本身应当被 G 判出问题：{sample}"
        g_errors = {f["kind"] for f in g["findings"] if f["level"] == "error"}
        if not g_errors:
            continue  # 见 docstring 的"待修"：G 侧当前没判 error，无从断言
        checked += 1
        h = RV.scan_document(doc_row(claims=[sample]), dependencies=[])
        assert h["error_count"] >= 1, (
            f"H 放过了 G 判为 error 的稿件（G 拒绝、H 通过 = 静默分裂）："
            f"{sample} → G={sorted(g_errors)} H={[f['kind'] for f in h['findings']]}"
        )
    assert checked >= 1, "一个能断言的样本都没有 —— 闸门实际上没被验证过"

    # 负控：干净样本两侧都不许报 error
    assert DT.scan_claim(clean_claim())["error_count"] == 0
    assert RV.scan_document(doc_row(), dependencies=[])["error_count"] == 0
    # 负控：干净样本两侧都不许报 error
    assert DT.scan_claim(clean_claim())["error_count"] == 0
    assert RV.scan_document(doc_row(), dependencies=[])["error_count"] == 0


# ============================================================ P0-2 doc.build_document


def _build(reg: ToolRegistry, claims: list[dict], **kw: object):
    params = {"kind": "note", "title": "带引用的稿件", "claims": claims}
    params.update(kw)
    return reg.call("doc.build_document", **params)


def test_build_document_refuses_dangling_citation_and_writes_nothing(store: Store, tmp_path: Path):
    """核心：`citations=["lit:9999"]` ⇒ 不写库（逐字节比对）+ 逐条列出坏引用。

    修之前 `scan_claim` 只查"citations 非空"，假引用照样写库 + 渲染。
    """
    reg = registry_for(DT, store, workspace_root=store.root)
    before = (store.data / "documents.json").read_bytes()

    claims = [DT.compose_claim("一个引用了不存在文献的断言。", citations=["lit:9999"], evidence_kind="heuristic", section="s")]
    res = _build(reg, claims)

    assert res.ok is False
    assert res.meta.get("kind") == "dangling_citation"
    assert res.meta.get("created") is False
    assert [m["citation"] for m in res.meta["missing"]] == ["lit:9999"]
    # 必须指出是哪一条断言的引用（compose_claim 会派生 claim_id，不假定它叫 claim-1）
    # `claim_id` 由脚本按顺序发（`draft/39` §3.11 四 D10）：调用方写的那一个会被丢掉，
    # 于是"哪条断言出的问题"按本脚本分配的代号报回来。
    assert res.meta["missing"][0]["claim_id"] == "claim-1"
    assert res.meta["missing"][0]["claim_id"]
    assert "literature" in res.meta["missing"][0]["why"]
    # ---- 逐字节比对：一个字都没写
    assert (store.data / "documents.json").read_bytes() == before
    assert store.rows("documents") == []
    docs_dir = store.root / "documents"
    assert not docs_dir.exists() or list(docs_dir.glob("*.md")) == [], "坏引用不许留下 markdown"


@pytest.mark.parametrize(
    ("citation", "table_word"),
    [
        ("rel:9999", "relations"),
        ("lit:9999", "literature"),
        ("exp:9999", "experiments"),
        ("eval:9999", "eval_results"),
    ],
)
def test_build_document_checks_every_citation_kind(store: Store, citation: str, table_word: str):
    """四张表都要核（"代号不存在"这一档 fail-closed）。"""
    reg = registry_for(DT, store, workspace_root=store.root)
    claims = [DT.compose_claim("x", citations=[citation], evidence_kind="heuristic", section="s")]
    res = _build(reg, claims)
    assert res.ok is False and res.meta.get("kind") == "dangling_citation"
    assert table_word in res.meta["missing"][0]["why"]
    assert store.rows("documents") == []


def test_an_unknown_citation_prefix_is_refused_at_construction_time(store: Store):
    """前缀不认识这一档：拒的落点从 `check_citations` 前移到构造期（仍然是 fail-closed）。

    改前这一档只有 `check_citations` 报（`missing[0]["why"]` 里写"无法识别"），
    而 `claimanatomy` 对 citations 只查"非空 / 非空串" ⇒ H 那一侧（它不经
    `check_citations`，因为没有 store 可读）看不见"这个前缀根本没法核"。
    `draft/68` 题 1（2026-10-07 所有者裁定 A，本次改动由所有者授权、主控代改）
    把前缀判据落进 `claimanatomy`（唯一入口，G 与 H 共用）⇒ `compose_claim` 当场抛。

    所以这条判据的口径跟着改（改的理由就是上面这一段，不是为了让红灯变绿）：
    从「`_build` 回 `dangling_citation`」改成「构造期就抛，且拒信点名那个前缀」。
    要守的东西一个字没变：前缀不认识不许静默放过，且盘上什么都不许写。
    """
    with pytest.raises(ValueError, match="bad_citation_prefix"):
        DT.compose_claim("x", citations=["谁也不知道:1"], evidence_kind="heuristic", section="s")
    assert store.rows("documents") == []


def test_a_bare_number_citation_is_refused_at_construction_time(store: Store):
    """裸号（`0004`）同理：构造期拒，且拒信教作者写成带前缀的形态。

    改前裸号由 `check_citations` 报（它刻意与"未知前缀"分开报，`R-03` 的三态），
    现在两档都在构造期被拦，但拒信仍然要分开（未知前缀要人确认词表、
    裸号只要写对形态），所以这里逐字钉住裸号那一句里给出的两种写法。
    """
    with pytest.raises(ValueError) as exc:
        DT.compose_claim("x", citations=["0004"], evidence_kind="heuristic", section="s")
    msg = str(exc.value)
    assert "是裸号" in msg and "stmt:0004" in msg and "lit:0004" in msg, msg
    assert store.rows("documents") == []


def test_build_document_accepts_real_citations_and_writes(store: Store):
    """负控：引用真的存在 ⇒ 正常落库 + 渲染（闸门不能把好数据一起拦掉）。"""
    add_literature(store, S.format_id(0), title="真实文献", processed=True)
    reg = registry_for(DT, store, workspace_root=store.root)

    claims = [
        DT.compose_claim("引用真实文献的断言。",
                         citations=[f"lit:{S.format_id(0)}", f"lit:{S.format_id(0)}#p.3"],
                         evidence_kind="heuristic", section="s")
    ]
    res = _build(reg, claims)
    assert res.ok, res.error
    doc = res.data
    assert doc["doc_id"] == S.format_id(0)
    assert store.rows("documents")[0]["doc_id"] == S.format_id(0)
    md = store.root / str(doc["markdown_path"])
    assert md.is_file() and f"lit:{S.format_id(0)}" in md.read_text(encoding="utf-8")
    # 同一次调用里的另一条断言带上假引用 ⇒ 整笔回滚（不许"部分成功"）
    before = (store.data / "documents.json").read_bytes()
    mixed = claims + [DT.compose_claim("y", citations=["exp:9999"], evidence_kind="heuristic", section="s")]
    res2 = _build(reg, mixed)
    assert res2.ok is False and (store.data / "documents.json").read_bytes() == before
    assert len(store.rows("documents")) == 1, "坏引用那次不该新增行"


def test_check_citations_separates_not_checked_from_checked(store: Store):
    """三态：`rows_of=None`（没法查）不等于"引用都存在"。"""
    claims = [clean_claim()]
    no_store = DT.check_citations(None, claims)
    assert no_store["checked"] is False
    assert "没法核对" in no_store["reason"]
    assert no_store["missing"] == []

    def rows_of(table: str):
        return store.rows(table)

    checked = DT.check_citations(rows_of, [clean_claim(citations=["lit:9999"])])
    assert checked["checked"] is True
    assert [m["ref"] for m in checked["missing"]] == ["9999"]
    # 负控：真的有 ⇒ 无 missing
    add_literature(store, "0000", title="真实文献", processed=True)
    ok_res = DT.check_citations(rows_of, [clean_claim(citations=["lit:0000"])])
    assert ok_res["checked"] is True and ok_res["missing"] == [] and ok_res["resolved"] == 1


# ============================================================ P1-3/4 side_effect 如实


def test_side_effect_search_providers_declares_read_plus_egress(store: Store):
    """`search.providers` 真的发 HTTP ⇒ 第二根轴必须是 `egress`（需要审批）。

    B3 收官把它从遗留取值 `network` 迁到两根轴上的确定值：效果轴 `read`
    （它不写我们的东西）、外部轴 `egress`（它真的对外发请求）。
    审批面在当前环境下不变（沙箱未声明 ⇒ `external != "none"` 仍要审批）。
    """
    reg = registry_for(ST, store, workspace=store.root)
    spec = reg.get("search.providers")
    assert spec.side_effect == "read", "真实探测只读我们的表，效果轴是 read"
    assert spec.declared_external == "egress", "真的对外发 HTTP ⇒ 外部轴必须是 egress"
    assert spec.needs_approval is True


def test_side_effect_ocr_tools_are_declared_individually(store: Store, tmp_path: Path):
    """`ocr.run`（下载模型）/`ocr.backends`（工作区外 mkdir）/`ocr.detect_text_layer` 分级如实。"""
    reg = registry_for(OT, store, workspace=tmp_path, backends=[OT.NullBackend()])
    run = reg.get("ocr.run")
    # B3 收官：`network` -> `write_local`（它会下模型并 mkdir 模型目录）+ `egress`（真的下）
    assert run.side_effect == "write_local"
    assert run.declared_external == "egress"
    assert run.needs_approval is True
    assert reg.get("ocr.backends").side_effect == "write_local"
    assert reg.get("ocr.backends").needs_approval is True
    # ---- 负控：真的只读的那个不许被顺手改成写（否则审批会变成噪音）
    assert reg.get("ocr.detect_text_layer").side_effect == "read"
    assert reg.get("ocr.detect_text_layer").needs_approval is False


def test_side_effect_check_formal_declares_exec_and_needs_approval(store: Store):
    """`verify.check_formal` 起的是调用方给内容的检查器 ⇒ `read` + `exec`，且需要审批。

    B3 收官的行为变化（P-15/P-19）：它此前声明 `read` 且 `external="none"`，
    于是"起检查器进程"这个事实只在注释里。现在第二根轴如实为 `exec`：

    - `needs_approval` 从 `False` 变 `True`（沙箱未声明 ⇒ 起进程要签字）；
    - `sandbox_required` 从 `False` 变 `True`；
    - `roles` 从 `_ROLES`（含 H）改成 `_ROLES_WRITE` ⇒ H 的工具面少一个。
    """
    reg = registry_for(VT, store, root=store.root)
    spec = reg.get("verify.check_formal")
    assert spec.side_effect == "read", "它读的是检查器的输出，不改我们的东西"
    assert spec.declared_external == "exec"
    assert spec.needs_approval is True
    assert spec.sandbox_required is True
    assert "H" not in spec.roles, "声明必须正确：它现在需要审批，H 只读 ⇒ 不能拥有它"
    # 负控：同一族的 `detect_verifier` 跑的是工具自己写死的 `--version` 探测，
    # 调用方决定不了跑什么 ⇒ 它保持 `read` + `none`（R010 已逐条登记为例外）。
    probe = reg.get("verify.detect_verifier")
    assert (probe.side_effect, probe.declared_external) == ("read", "none")
    assert probe.needs_approval is False


def test_side_effect_declarations_do_not_leak_write_tools_to_read_only_roles(store: Store):
    """防误伤：改成 network/write_local 之后，只读角色 C/H 的工具面仍然没有任何写工具。"""
    from agentflow.tools import READ_ONLY_ROLES, build_registry

    build = build_registry(store=store, workspace_root=store.root)
    assert build.registry.role_filter_notes == {}, "声明错了才会留痕；这里应当为空"
    for role in READ_ONLY_ROLES:
        leaks = [s.name for s in build.registry.for_role(role) if s.needs_approval]
        # 2026-10-17（业主裁定「方案 1」）：例外表里登记的落库代理不算漏
        from agentflow.tools.base import READONLY_CALL_EXCEPTIONS as _EXC
        _ex = {n for _ns in _EXC.values() for n, _w in _ns}
        leaks = [n for n in leaks if n not in _ex]
        assert leaks == [], f"{role} 拿到了需要审批的工具：{leaks}"


# ============================================================ P1-5 r-NNNN 分配器


def test_research_tools_request_id_is_the_interactions_implementation():
    """`research_tools` 的那份副本已被删除：它现在就是 `interactions` 的实现本身。"""
    assert RT.next_prefixed_id is IX.next_prefixed_id
    assert RT._next_request_id.__module__ == "agentflow.tools.research_tools"

    rows = [{"request_id": "r-0001"}, {"request_id": "r-0003"}, {"request_id": "not-an-id"}]
    assert RT._next_request_id(list(rows)) == IX.next_prefixed_id(rows, "request_id", "r") == f"r-{S.format_id(4)}"
    # 负控：旧副本没有前缀守卫（`interactions` 有）⇒ 现在的转发必须同样拒绝
    with pytest.raises(ValueError):
        IX.next_prefixed_id([], "request_id", "r-")
    assert RT.next_prefixed_id is IX.next_prefixed_id


def test_table_tools_and_research_tools_share_the_one_request_id_implementation():
    """`table_tools` 与 `research_tools` 的取号必须与权威实现逐个一致（FC-11）。

    历史：全项目曾有三份 `r-NNNN` 分配器（`table_tools` 取最小可用号、
    `research_tools` 取 max+1 且无守卫、`interactions.next_prefixed_id` 取 max+1
    且带前缀守卫）。同一张 `search_requests` 表因此有三个取号器，语义互相冲突：
    表里只有 `r-0001`、`r-0003` 时，一个给 `r-0000`、另一个给 `r-0004`。

    这里曾经有一条"记录分歧"的断言（断言 `table_tools` 给 `r-0000`）。
    它属于"这里本该一致"的那一类 —— 最小可用号会复用已删行的号，而
    `literature.source_request_ids` / `research_questions.waiting_request_ids`
    长期引用 `r-NNNN`，号被复用会让溯源静默指向另一条请求。
    所以它被改成了一致性断言（连同 `tests/test_tools_table_fs.py` 里
    断言 `f"r-{S.format_id(0)}"` 的那一行），并保留了"曾经分歧"这个事实作为注释。
    """
    rows = [{"request_id": f"r-{S.format_id(1)}"}, {"request_id": f"r-{S.format_id(3)}"}, {"request_id": "not-an-id"}]
    expected = IX.next_prefixed_id(rows, "request_id", "r")
    assert expected == f"r-{S.format_id(4)}"
    assert TT._next_request_id(rows) == expected, "table_tools 必须与权威实现同号"
    assert RT._next_request_id(list(rows)) == expected, "research_tools 必须与权威实现同号"
    # 同一份实现（不是副本）：两个模块都只是转发
    assert RT.next_prefixed_id is IX.next_prefixed_id
    assert TT.next_prefixed_id is IX.next_prefixed_id

    # 空表：两处都必须给 r-0001（旧语义 r-0000 已废弃）
    assert TT._next_request_id([]) == RT._next_request_id([]) == IX.next_prefixed_id([], "request_id", "r") == f"r-{S.format_id(1)}"
    # 负控：任何输入下都必须与权威实现一致，且绝不发出已占用的号
    for probe in (
        [{"request_id": f"r-{S.format_id(0)}"}],
        [{"request_id": f"r-{S.format_id(0)}"}, {"request_id": f"r-{S.format_id(2)}"}],
        [{"request_id": f"r-{S.format_id(9)}"}, {"request_id": f"r-{S.format_id(1)}"}],
    ):
        want = IX.next_prefixed_id(probe, "request_id", "r")
        assert TT._next_request_id(probe) == want == RT._next_request_id(list(probe))
        assert want not in {r["request_id"] for r in probe}


def test_table_tools_request_id_fails_closed_when_the_space_is_exhausted():
    """编号用尽必须显式失败：`next_prefixed_id` 自己不设上限，会静默给 5 位号。

    `"r-10000"` 违反 `r-NNNN` 的 4 位契约（`store.py:52-53` 的"用满即 fail-closed"，
    以及 `tests/test_agent_c_service.py:637` 对 `S.is_valid_id(...)` 的断言），
    因此 `assert_request_id_in_space` 把这道守卫放在两处转发之后 ——
    取号只有一份实现，空间判据也只有一份。

    # 待修：按 FC-03，这道上限最终应下沉进 `interactions.next_prefixed_id` 本身：
    # agent_c / agent_d / agent_f / cli / demo 都直接调它，因此那些路径现在
    # 仍会产出 `r-10000`。`interactions.py` 是 FC-27 禁改区（auth-audit），
    # 我不改它 —— 已上报主控。本用例只覆盖工具层的两个入口。
    """
    top = 10 ** S.ID_DIGITS - 1
    rows = [{"request_id": f"r-{S.format_id(i)}"} for i in range(0, top + 1)]
    with pytest.raises(ToolError):
        TT._next_request_id(rows)
    with pytest.raises(ToolError):
        RT._next_request_id(list(rows))
    # 负控：还没用满时不许炸（否则守卫会变成"永远拒绝"）
    assert TT._next_request_id(rows[:-1]) == f"r-{S.format_id(top)}"


def test_research_submit_gap_uses_the_authority_for_new_request_ids(store: Store):
    """端到端：`research.submit_gap` 发出的号 == 权威实现按同一批行算出的号。"""
    reg = ToolRegistry(name="d")
    RT.install(reg, store)
    reg.bound_role = "D"  # `P-14`：`research.*` 只有 D
    with store.tx("research_questions", actor="test", note="seed") as tx:
        tx.upsert(
            "research_questions",
            S.ResearchQuestion(
                question_id=S.format_id(0),
                question="q",
                origin="C:paths:0000->0001",
                related_concept_ids=[S.format_id(0)],
                priority="high",
                created_at=TS,
                updated_at=TS,
            ).to_dict(),
        )
    add_request(store, f"r-{S.format_id(1)}", done=True, last_error="no_results")
    add_request(store, f"r-{S.format_id(3)}", done=True, last_error="no_results")

    expected = IX.next_prefixed_id(store.rows("search_requests"), "request_id", "r")
    res = reg.call("research.submit_gap", question_id=S.format_id(0), topic="非交换环", mode="topical")
    assert res.ok, res.error
    assert res.data["request_id"] == expected == f"r-{S.format_id(4)}"
    assert {r["request_id"] for r in store.rows("search_requests")} == {f"r-{S.format_id(1)}", f"r-{S.format_id(3)}", f"r-{S.format_id(4)}"}


# ============================================================ P1-6 search.dedup_check


def test_dedup_check_does_not_claim_new_when_the_table_cannot_be_read(store: Store):
    """核心：读表失败 ⇒ 结构化失败，绝不给出 `would_be_duplicate=False`。"""
    reg = registry_for(ST, store, workspace=store.root)

    # ---- 负控 1：健康的空表 ⇒ 这是一个有效结论（查了、不是重复）
    healthy = reg.call("search.dedup_check", title="Nobody wrote about this", year=2020)
    assert healthy.ok and healthy.data["checked"] is True
    assert healthy.data["would_be_duplicate"] is False
    assert healthy.data["existing_table_size"] == 0
    assert healthy.data["store_read_error"] is None

    # ---- 负控 2：没有 store ⇒ 早就是 fail-closed（对照用）
    no_store = ToolRegistry(name="no-store")
    ST.register(no_store, workspace=store.root)
    no_store.bound_role = "A"  # `P-14`：`search.*` 只有 A
    miss = no_store.call("search.dedup_check", title="x", year=2020)
    assert miss.ok is False and miss.meta["kind"] == "no_store" and miss.meta["checked"] is False

    # ---- 正例：表坏了 ⇒ 不许退化成"没有重复"
    corrupt(store, "literature.json")
    broken = reg.call("search.dedup_check", title="Nobody wrote about this", year=2020)
    assert broken.ok is False
    assert broken.meta["kind"] == "table_unreadable"
    assert broken.meta["checked"] is False
    assert broken.data is None, "失败时不许返回任何形如判重结论的字典"
    assert "假阴性" in broken.error


def test_literature_search_marks_candidates_unknown_when_the_table_is_broken(store: Store):
    """同一根因的第二处：`search.literature` 也不许把"没查成"写成 `is_new=True`。"""

    class _StubProvider:
        name = "stub"

        def search(self, topic, mode="topical", description="", limit=10):  # noqa: ARG002
            from agentflow import providers as P

            return [P.Candidate(title="Some paper", year=2020, doi="10.1000/x", type_code="J", provider="stub")]

    reg = registry_for(ST, store, workspace=store.root, providers=[_StubProvider()])

    good = reg.call("search.literature", topic="群", mode="topical", provider="stub").data
    assert good["store_checked"] is True and good["candidates"][0]["is_new"] is True

    corrupt(store, "literature.json")
    bad = reg.call("search.literature", topic="群", mode="topical", provider="stub").data
    assert bad["store_checked"] is False
    assert bad["candidates"][0]["is_new"] is None, "表读不出来 ⇒ 判重结论必须是 None（未知）"
    assert bad["existing_table_size"] is None
    assert bad["store_read_error"], "必须留下读表失败的原因"
    assert any("没查" in w for w in bad["warnings"])


# ============================================================ P1-7 trace.* 三态


def test_trace_chain_without_any_graph_is_not_checked_not_ok():
    """核心：无 store 无 graph ⇒ `checked=False` + ok=False（不是 ok=True + step_count=0）。"""
    reg = ToolRegistry(name="trace-none")
    TR.register(reg)  # 既不给 store 也不给 graph
    reg.bound_role = "C"  # `P-14`：`trace.*` 的声明角色是 C/D，这里代表只读的 C
    res = reg.call("trace.chain", relation_ids=["0000"])
    assert res.ok is False
    assert res.meta.get("kind") == "no_graph"
    assert res.meta.get("checked") is False
    assert res.data is None, "不许返回 ok=True + step_count=0 —— 那会被读成'这些代号都不存在'"
    assert "没查" in res.error


def test_trace_chain_with_a_graph_distinguishes_broken_chain_from_no_lookup(store: Store):
    """有图时：链条确实断裂 ⇒ ok=True + checked=True + missing 非空（"查了、没有"）。"""
    reg = registry_for(TR, store)
    res = reg.call("trace.chain", relation_ids=["9999"])
    assert res.ok is True, res.error
    assert res.data["checked"] is True
    assert res.data["missing"] == ["9999"]
    assert res.data["step_count"] == 0
    assert "9999" in res.data["chain_text"]


def test_trace_lookups_without_graph_say_not_checked_not_not_found(store: Store):
    """4.3(a)⑤⑥：L1/L2/L3 在"没有图可查"时也必须说"没查"，不许说"查了、没有"。"""
    reg = ToolRegistry(name="trace-none")
    TR.register(reg)
    reg.bound_role = "C"  # `P-14`：同上
    cases = (
        ("trace.relation", {"relation_id": "0000"}),
        ("trace.concept", {"concept_id": "0000"}),
        ("trace.literature", {"lit_id": "0000"}),
        ("trace.chain", {"relation_ids": ["0000"]}),
    )
    for name, params in cases:
        res = reg.call(name, **params)
        assert res.ok is False, name
        assert res.meta.get("kind") == "no_graph", (name, res.meta)
        assert res.meta.get("checked") is False, name

    # ---- 负控：有图、代号确实不存在 ⇒ 是"查了、没有"（kind=not_found + checked=True）
    reg2 = registry_for(TR, store)
    for name, params, key in (
        ("trace.relation", {"relation_id": "9999"}, "known_relations"),
        ("trace.concept", {"concept_id": "9999"}, "known_concepts"),
        ("trace.literature", {"lit_id": "9999"}, "known_literature"),
    ):
        res = reg2.call(name, **params)
        assert res.ok is False and res.meta.get("kind") == "not_found", (name, res.meta)
        assert res.meta.get("checked") is True, name
        assert key in res.meta, name


def test_trace_literature_every_branch_carries_pages_returned_and_truncated(store: Store):
    """4.5 #4：`pages_returned`/`truncated` 在每一条返回分支上都必须存在。

    修之前它们只在成功分支上给 —— 恰恰在"读不到"的场景缺席，而那种场景下
    "我请求了哪些页、实际给了哪些页"才是调用方最需要的信息。
    """
    add_literature(store, "0000", title="有正文", path="0000/source.txt", processed=True)
    add_literature(store, "0001", title="没下载", path=None, processed=False)
    add_literature(store, "0002", title="文件丢了", path="0002/gone.txt", processed=False)
    write_library_file(store, "0000/source.txt", "An abelian group is a group.\n")

    reg = registry_for(TR, store)
    seen_status = set()
    for lit_id, expected in (("0000", "ok"), ("0001", "no_path"), ("0002", "file_missing")):
        data = reg.call("trace.literature", lit_id=lit_id).data
        assert data["status"] == expected
        assert "pages_returned" in data and "truncated" in data, (lit_id, sorted(data))
        assert data["status"] in TR.L3_STATUSES
        seen_status.add(data["status"])
    assert seen_status == {"ok", "no_path", "file_missing"}


def test_l3_status_vocabulary_is_actually_enforced():
    """4.5 #9：`L3_STATUSES` 不能只是一句注释 —— 编外的 status 必须当场炸。"""
    assert TR._status("file_missing") == "file_missing"
    with pytest.raises(ToolError):
        TR._status("file_mising")  # 拼错一个字母：以前会照原样返回给下游


# ============================================================ P2-8/9 verify.*


def test_detect_verifier_side_effect_is_read_and_checked_is_honest(store: Store, monkeypatch: pytest.MonkeyPatch):
    """`checked` 必须真有 False 路径；`side_effect` 必须是 read（它起子进程）。"""
    reg = registry_for(VT, store, root=store.root)
    spec = reg.get("verify.detect_verifier")
    assert spec.side_effect == "read", "它 `shutil.which` + `subprocess.run` 外部二进制，不是'无副作用'"
    assert spec.needs_approval is False

    # ---- 路径 1：探测本身失败 ⇒ checked=False（旧实现硬编码 True，没有这条路）
    def boom(_name):
        raise OSError("PATH 读不了")

    monkeypatch.setattr(shutil, "which", boom)
    failed = VT.detect_verifier()
    assert failed["checked"] is False
    assert failed["probe_errors"], "失败原因必须逐条可见"
    assert "没做成" in failed["reason"]

    # ---- 路径 2：探测完成、环境里确实没有 ⇒ checked=True + available=[]
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    done = VT.detect_verifier()
    assert done["checked"] is True
    assert done["available"] == [] and done["available_names"] == []
    assert done["probe_errors"] == []
    assert "没有" in done["reason"]


def test_detect_verifier_checked_false_when_the_version_probe_fails(store: Store, monkeypatch: pytest.MonkeyPatch):
    """二进制在、但版本探测起不来 ⇒ 仍记入 available，同时 `checked=False`（部分探测）。"""
    import subprocess

    monkeypatch.setattr(shutil, "which", lambda name: rf"C:\fake\{name}.exe")

    def boom(*_a, **_kw):
        raise OSError("起不来")

    monkeypatch.setattr(subprocess, "run", boom)
    det = VT.detect_verifier()
    assert det["checked"] is False
    assert det["available"], "它确实在 PATH 上 —— 这个事实不该被抹掉"
    assert det["probe_errors"]


def test_check_formal_return_shape_matches_its_declaration(store: Store, monkeypatch: pytest.MonkeyPatch):
    """声明与实现不许再分裂：`returns=` 里承诺的键 == 每一条 ok 分支实际返回的键。

    本用例在 P1 接线（`check_formal` 转发到 `formalgw.check_lean`）之后被改过两处，
    两处都是旧断言的收敛，而不是判据放宽：

    - `summary` 过去必须含"未接线"（那时它确实没接线）；现在必须说清它会真跑一次；
    - 第三条路径过去断言 `reason == "not_implemented"`。那条路径给的是
      `script_path="proofs/x.lean"`，而工作区里没有这个文件：接线之后它读不到源码。
      `E-3` 之前这里报的是 `decl_mismatch`（"文件里没有你要证的东西"，`checked=True`），
      那是"错的旧形态" —— 读不到源码是"没查成"，不是"查了、命题不成立"。
      现在 `formalgw` 给出 `source_unreadable`，于是 `checked=False`、
      `verified=None`（不是 `False`）。改这条断言不是为了让测试变绿，
      而是断言本身断的就是那个错的旧形态（`E-3` 的现状读数与 `draft/28` §26.2
      的授权都在）。四条 ok 分支的键集合仍必须逐字相同。
    - `missing_imports`（B8a/G-18）是新加的第 7 个键：`import_unavailable` 要能回答
      "哪个库不可得"，而六键形态里没有位置放它。它四条路径都在（历史形态"要么都有、
      要么都没有"保持不变），空列表只表示"检查器没有抱怨找不到包"。
    - `verifier_status`（B5b/B8b 的 `G-24①`）是第 8 个键：`reason` 收口进
      `agent_e.FORMAL_REASONS`/本层受控词表之后，检查器原样报的那个状态必须有
      一个透传栏（收口与透传成对存在，否则收口就是删信息）。四条路径都在，
      拒绝路径上是空串（"没有检查器状态可透传"）。
    - `exit_code`（`E-12(a)`，`draft/44`）是第 9 个键：真机 50 条 formal 里 41 条
      `exit_code=None`，而那一格改前同时表示"没查成"与"检查器跑完了"两件事 ——
      检查器进程的真实退出码必须有自己的位置（上游读数是 `agent_e/core.py`
      的 `_record_formal`，它把"跑到哪一步"与"结论是什么"分开记）。
      四条 ok 分支都在：三条"没起检查器"的分支给 `None`（"没有退出码"是诚实的值，
      不是 `0` —— `0` 会被读成"检查器跑完了、退出码 0"），主分支给检查器原样报的那个值。
      口径是「契约对每一条分支都成立」（主控 2026-10-07 裁 (a)）：key 集合不随分支变，
      所以 `set(返回) == 声明` 这条判据在每条分支上都仍然有效。同口径的另两处是
      `tests/test_check_formal_wiring.py`（桩 + 注释键数 + `N-4` 的例外表）
      与 agent 侧 `agent_e/core.py::_formal_refusal`（拒绝分支补 `exit_code: None`）。
    - 第 4 条 ok 分支 `tool_crashed`（`E-4`：探测本身没做成）此前没有被采样
      （`B-R7` 登记过这件事），现在补上。

    这里采的是 ok 分支。失败那一侧是「2 个 `return fail(...)` 调用点，覆盖 3 类情形」
    —— 本文件与 `tools/verify_tools.py` 的旧措辞都写成"三条 `return fail(...)` 分支"，
    那是把「情形数」当成了「调用点数」（`R0-B2` 实测：AST 数出 2 个调用点）：
    ①拿不到声明名、②声明名参数不合法 —— 这两类汇进同一个调用点
    （`except ValueError` ⇒ `kind="param_error"`，`verify_tools.py:436-443`）；
    ③桥接层抛异常走另一个调用点（`except Exception` ⇒ `kind="check_failed"`，
    `:444-450`）。两个调用点给的都是 `ok=False` + `data=None`（一个键都不给），
    由本文件里逐条 `return` 比对声明的用例与运行期那条
    `test_every_fail_branch_of_check_formal_gives_no_keys_and_a_declared_kind` 钉住
    （`I-4`/`T3`/`C2`）。
    上面这个数字有机械判据守着（`test_the_fail_call_site_count_in_this_docstring_is_live`）：
    改了调用点数而没改这句话，它会红。
    """
    reg = registry_for(VT, store, root=store.root)
    spec = reg.get("verify.check_formal")
    declared = declared_keys(spec.returns)
    assert declared == {"checked", "verified", "claim", "reason", "detail",
                        "verifier_output", "missing_imports", "verifier_status",
                        "exit_code"}
    assert "真跑" in spec.summary, "summary 必须如实说明它会真的跑一次检查器"
    assert "未接线" not in spec.summary, "它已经接线了，声明里不许再写未接线"

    # ---- 路径 1：无后端
    monkeypatch.setattr(
        VT, "detect_verifier", lambda: {"checked": True, "available": [], "available_names": [], "reason": "无", "probe_errors": []}
    )
    d1 = reg.call("verify.check_formal", claim="1+1=2").data
    # ---- 路径 2：有后端、没给脚本
    monkeypatch.setattr(
        VT,
        "detect_verifier",
        lambda: {
            "checked": True,
            "available": [{"name": "lean", "path": "lean", "version": "4"}],
            "available_names": ["lean"],
            "reason": "有",
            "probe_errors": [],
        },
    )
    d2 = reg.call("verify.check_formal", claim="1+1=2").data
    # ---- 路径 3：有后端 + 给了脚本路径，但盘上没有这个文件
    # （`E-3`：这是"没查成"`source_unreadable`，不是 `decl_mismatch`）
    d3 = reg.call("verify.check_formal", claim="1+1=2", script_path="proofs/x.lean").data
    # ---- 路径 4（`E-4`，`B-R7` 之前没采）：探测本身没做成 ⇒ tool_crashed。
    # `available=[]` 与 `checked=False` 是两条独立的事实：这一支说的不是
    # "环境里没有检查器"，而是"我们不知道环境里有没有"。
    monkeypatch.setattr(
        VT,
        "detect_verifier",
        lambda: {
            "checked": False,
            "available": [],
            "available_names": [],
            "reason": "探测本身没做成（桩）",
            "probe_errors": ["PATH 读不了（桩）"],
        },
    )
    d4 = reg.call("verify.check_formal", claim="1+1=2").data

    for branch in (d1, d2, d3, d4):
        assert set(branch) == declared, f"返回的键与 returns= 不一致：{sorted(branch)}"
        assert branch["verifier_output"] == ""
    # 三条是"没查成"：checked=False 且没有验证结论。
    for branch in (d1, d2, d3, d4):
        assert branch["checked"] is False
        assert branch["verified"] is None, "没跑过 ⇒ verified 必须是 None，不许写成 False"
    # 第三条路径（`E-3` 之后）：盘上没有那个脚本 ⇒ 没查成（`source_unreadable`）。
    # 它过去被折成 `decl_mismatch`（"声明名对不上"，`checked=True`/`verified=False`），
    # 那是把"路径写错了"报成"你证的东西不在文件里" —— 调用方会去改数学而不是改路径。
    assert [d["reason"] for d in (d1, d2, d3, d4)] == [
        "no_backend", "no_script", "source_unreadable", "tool_crashed",
    ]
    # `verifier_status`（`G-24①`）：检查器原样报的那个状态。工具层这一栏与 `reason`
    # 逐字相同（收口发生在 E 那一层，见 tests/test_agent_e_formal_reasons.py）。
    # `d1` / `d2` 是"没起检查器"（无后端 / 调用方没给源码）⇒ 空串
    # （"没有检查器状态可透传"）；`d4` 是探测本身没做成，也没有检查器状态。
    # `d3` 例外：`source_unreadable` 是 `formalgw` 报出来的状态，所以它照样透传
    # —— 它同时是 `reason` 与 `verifier_status`，因为这一档说的就是"这次检查没发生"。
    assert [d["verifier_status"] for d in (d1, d2, d4)] == ["", "", ""]
    assert d3["verifier_status"] == "source_unreadable"
    # 负控：任何分支都不许声称验证过
    assert all(b["verified"] is not True for b in (d1, d2, d3, d4))


# ----------------------------------------------------- `R0-B2`：措辞里的调用点数要现算

#: 本文件里写调用点数的那句话的形状。为什么要"可解析"：数字散在散文里时，
#: 改代码的人没有理由去改它 —— 同族先例是 `tests/test_check_formal_wiring.py`
#: 的 `f"{len(CONTRACT_KEYS)} 个键"`（`N-4`）。
#: 数字位写 `\d+`，所以 docstring 里引这个形状时必须用 `N` 之类的非数字占位
#: （否则判据会把自己举的例子也当成"写了一个数"）。
_FAIL_CALL_SITE_CLAIM = re.compile(r"(\d+)\s*个\s*`return fail\(\.\.\.\)`\s*调用点")


def _claim_docstring(text: str) -> str:
    """取断言契约那个用例自己的 docstring（不是全文件的 docstring）。

    为什么把落点收窄到一处（第一版是全文件扫，被自己咬了）：全文件扫时，
    任何一段「引用」这个形状的文字都会命中它 —— 包括本判据下面那段解释
    "坏样本长什么样"的说明。约束于是变成"谁都不许把形状写出来"，
    而写在帮助函数里的解释恰恰最需要写出形状。
    收窄到"那句话必须住在这个用例的 docstring 里"之后，别处的引用与解释随便写。
    """
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "test_check_formal_return_shape_matches_its_declaration"):
            doc = ast.get_docstring(node, clean=False)
            assert doc, "那个断言契约的用例没有 docstring ⇒ 这句措辞没有落点"
            return doc
    raise AssertionError(
        "找不到 `test_check_formal_return_shape_matches_its_declaration` "
        "⇒ 这条判据没查成（不是「措辞没问题」）")


def _fail_call_sites(source: str) -> list[tuple[int, str]]:
    """AST 现算 `check_formal` 体内 `return fail(...)` 的调用点 ⇒ `[(行号, kind)]`。

    只数「调用点」，不数情形：`except ValueError` 那一支同时覆盖"拿不到声明名"与
    "声明名参数不合法"两类情形 ⇒ 情形数（3）与调用点数（2）本来就不同。
    找不到 `check_formal` 时抛断言，而不是返回空列表 —— "没查成"不是"没有调用点"。
    """
    tree = ast.parse(source)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "check_formal"), None)
    assert fn is not None, "找不到 `check_formal` ⇒ 这条判据没查成（不是「它没有失败分支」）"
    out: list[tuple[int, str]] = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "fail":
            kind = next((str(k.value.value) for k in node.keywords
                         if k.arg == "kind" and isinstance(k.value, ast.Constant)), "")
            out.append((node.lineno, kind))
    return sorted(out)


def _claim_problem(doc_text: str, source: str) -> str:
    """docstring 里写的调用点数 vs 现算调用点数（空串 = 一致）。"""
    live = len(_fail_call_sites(source))
    stated = sorted({int(m.group(1)) for m in _FAIL_CALL_SITE_CLAIM.finditer(doc_text)})
    if not stated:
        return ("本文件的 docstring 里读不到那句「N 个 `return fail(...)` 调用点」"
                "⇒ 判据没有落脚点（这不是「一致」）")
    if stated != [live]:
        return (f"docstring 里写的是 {stated} 个调用点，而 AST 现算是 {live} 个"
                f"（`R0-B2` 的原始形态正是这样：写着「三条」而实测 2 个 —— "
                "把情形数当成了调用点数）")
    return ""


def test_the_fail_call_site_count_in_this_docstring_is_live() -> None:
    """反回流：上面那句"2 个调用点"必须与 AST 现算一致，改代码忘了改话就红。

    为什么值得一条用例：这句措辞已经错过一次（`B-R5` 起就写着"三条"），
    而它不是笔误 —— 它把"3 类情形"说成了"3 个调用点"，下一个人照着它推理就会
    以为有三个失败出口。数字能机械核，所以就让机器核。

    边界（刻意不扫）：`src/agentflow/tools/verify_tools.py` 里同样的计数
    （`:439` / `:779` / `:785` / `:787`）在 FC-27 禁改区（`prover-bridge` 类），
    原文同样把情形数写成调用点数、且 `:785`/`:787` 那两句已被后来的用例推翻
    （实测采样 4 条 ok 分支、且失败分支有逐分支采样用例）。那几处已登记人审队列，
    本判据故意只看本文件 —— 否则它会因为一条我无权改的注释而长红，那是判据替人做决定。
    """
    source = Path(VT.__file__).read_text(encoding="utf-8")
    docs = _claim_docstring(Path(__file__).read_text(encoding="utf-8"))

    live = _fail_call_sites(source)
    assert len(live) == 2, (
        f"`check_formal` 的 `return fail(...)` 调用点数变了（现算 {len(live)} 个：{live}）"
        "⇒ 先确认是不是真的加/删了失败出口，再同时改那句措辞与这里的锚")

    problem = _claim_problem(docs, source)
    assert not problem, problem

    # 反负控：把那个数字改回旧值（`B-R5` 起写的"三条"）⇒ 同一读法必须报出来。
    doctored = _FAIL_CALL_SITE_CLAIM.sub("3 个 `return fail(...)` 调用点", docs, count=1)
    assert doctored != docs, "反负控没改到那句话 —— 这条负控自己失效了"
    assert _claim_problem(doctored, source), (
        "数字被改回旧值，判据却一声不吭 ⇒ 它是真空的")
    # 反向的负控：连"没有落脚点"这一态也要报出来（删掉那句话 ⇒ 不是"一致"）
    assert _claim_problem("这里没有任何计数句", source), "删掉那句话之后判据仍判绿 ⇒ 它没有接点"


def test_every_fail_branch_of_check_formal_gives_no_keys_and_a_declared_kind(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """`I-4`/`T3`/`C2`：三条拒绝分支逐条采样 —— 失败时 `ok=False`、`data=None`、kind 在声明里。

    拒绝分支没有键集合可谈（`base.fail` 逐字 `data=None`），所以声明用分号把
    "失败：ok=False + kind(...) + data=None"写成了另一节。此前没有任何用例采过
    这三条分支（`D2` 登记过），于是把它们改成猜测/放行在套件里看不出来。
    """
    reg = registry_for(VT, store, root=store.root)
    spec = reg.get("verify.check_formal")
    declared_kinds = _declared_failure_kinds(spec.returns)
    assert declared_kinds, f"声明里没有可解析的失败 kind 词表：{spec.returns!r}"

    monkeypatch.setattr(
        VT, "detect_verifier",
        lambda: {"checked": True, "available": [{"name": "lean", "path": "lean", "version": "4"}],
                 "available_names": ["lean"], "reason": "有", "probe_errors": []},
    )

    # ---- 拒绝 1：给了源码但源码里没有具名声明，调用方也没给 checker_name
    # ⇒ 不回退成文件名词干（猜一个名字等于把"声明名核对"这条判据悄悄关掉）。
    r1 = reg.call("verify.check_formal", claim="c", source="example : True := trivial")
    # ---- 拒绝 2：`formalgw.check_lean` 对非法参数抛 ValueError ⇒ param_error
    def raise_value_error(*_a, **_kw):
        raise ValueError("（桩）声明名不合法")

    monkeypatch.setattr(FG, "check_lean", raise_value_error)
    r2 = reg.call("verify.check_formal", claim="c", source="theorem t : True := trivial",
                  checker_name="t")
    # ---- 拒绝 3：桥接层抛别的异常 ⇒ check_failed（"没查成"，既不是通过也不是证伪）
    def raise_runtime_error(*_a, **_kw):
        raise RuntimeError("（桩）桥接层崩了")

    monkeypatch.setattr(FG, "check_lean", raise_runtime_error)
    r3 = reg.call("verify.check_formal", claim="c", source="theorem t : True := trivial",
                  checker_name="t")

    got = [r1, r2, r3]
    assert [r.ok for r in got] == [False, False, False], [r.error for r in got]
    assert [r.data for r in got] == [None, None, None], (
        "拒绝分支不许给键集合（`base.fail` 逐字 `data=None`）—— 给了键就等于"
        "声明里那节'失败分支不承诺上面那套键'是假的"
    )
    kinds = [r.meta.get("kind") for r in got]
    assert kinds == ["param_error", "param_error", "check_failed"], kinds
    for kind in kinds:
        assert kind in declared_kinds, (
            f"实测 kind={kind!r} 不在声明的失败词表 {sorted(declared_kinds)} 里 —— "
            "调用方按声明写错误处理就会漏掉这一档（`C1` 是同一个形态）"
        )


def test_code_hash_failure_kinds_match_its_declaration_every_branch(
    store: Store, monkeypatch: pytest.MonkeyPatch
):
    """`C1`：`verify.code_hash` 的 `returns=` 失败词表与各分支实测 kind 集合逐值相同。

    现状（`C1` 登记）：声明写 ``kind(io_error/param_error)``，而两条最可能的失败
    ——脚本路径越界、工作区内文件不存在——都抛 `ParamError`（`ToolError` 的子类），
    被 `base.ToolRegistry.call` 的 `except ToolError` 兜成泛化的 `kind="tool_error"`：
    声明的取值集合里少了一个真实取值，而承诺的那两个一个都不出现。
    修法选的是"让实现产出声明承诺的 kind"，所以这条断言是双向的：
    每个分支的实测 kind 都要在声明的词表里，且词表里每个 kind 都真的被某个分支产出
    （只测一个方向时，"声明里多写一个永远不出现的 kind"照样能绿）。

    负控（见 `temp/batchL-probe.py`）：把 `_hash_of` 的两支收口撤掉（回到
    `except ToolError: raise`）⇒ 越界与文件不存在两支变回 `tool_error`，本条必红。
    """
    reg = registry_for(VT, store, root=store.root)
    spec = reg.get("verify.code_hash")
    declared_kinds = _declared_failure_kinds(spec.returns)
    assert declared_kinds == {"io_error", "param_error"}, (
        f"声明里的失败词表变了：{spec.returns!r} ⇒ 抽到 {sorted(declared_kinds)}"
    )

    (store.root / "probe.py").write_text("print(1)\n", encoding="utf-8")

    # ---- ok 分支：工作区内的真实文件
    good = reg.call("verify.code_hash", path="probe.py")
    assert good.ok, good.error
    assert set(good.data) == declared_keys(spec.returns)

    # ---- 失败 1：路径越界（`_resolve` 的守卫拒绝）
    out_of_bounds = reg.call("verify.code_hash", path="../outside.py")
    # ---- 失败 2：工作区内、但盘上没有这个文件（`code_hash` 的 ParamError）
    missing = reg.call("verify.code_hash", path="probes/not_here.py")
    # ---- 失败 3：`open()` 抛 OSError（文件被占用 / ACL 拒绝）
    (store.root / "locked.py").write_text("print(1)\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(VT, "open", boom, raising=False)
    unreadable = reg.call("verify.code_hash", path="locked.py")
    # ---- 失败 4：通用参数校验（框架那一层拒的，与工具自身无关）
    bad_param = reg.call("verify.code_hash", path=5)
    monkeypatch.undo()

    got = [out_of_bounds, missing, unreadable, bad_param]
    assert [r.ok for r in got] == [False, False, False, False], [r.error for r in got]
    assert [r.data for r in got] == [None, None, None, None], (
        "拒绝分支不许给键集合（`base.fail` 逐字 `data=None`）"
    )
    kinds = [r.meta.get("kind") for r in got]
    assert kinds == ["param_error", "io_error", "io_error", "param_error"], kinds
    assert "tool_error" not in kinds, (
        "泛化的 tool_error 意味着有一条失败路径逃出了本工具自己的收口 ⇒ "
        "声明里承诺的 kind 一个都没被产出（`C1` 的现状形态）"
    )
    for kind in kinds:
        assert kind in declared_kinds, (
            f"实测 kind={kind!r} 不在声明的失败词表 {sorted(declared_kinds)} 里"
        )
    # 反向：声明里每个 kind 都必须被至少一个分支真的产出（否则是空承诺）
    assert set(kinds) == declared_kinds, (
        f"声明承诺 {sorted(declared_kinds)}，而实测只产出 {sorted(set(kinds))} —— "
        "声明里写了永远不出现的取值时，按声明写错误处理的调用方会白写一档"
    )
    # 削掉桩之后同一条路径照旧可用（负控的反面：失败不是因为桩一直在）
    ok_again = reg.call("verify.code_hash", path="locked.py")
    assert ok_again.ok and len(ok_again.data["code_hash"]) == 16


# ------------------------------------------------------------ 分支级契约（`I-4`/`T3`）


def _declared_failure_kinds(returns: str) -> set[str]:
    """从 `returns=` 的失败节里抽出 kind 词表（形如 `kind(io_error/param_error)`）。

    只认括号里用 `/` 分隔的写法 —— 那是本仓库 `verify.*` 的既有写法
    （`verify.code_hash` 与 `verify.check_formal` 都是这样写的）。抽不到就返回空集，
    调用方必须把"空集"读成"没抽到"（三态纪律：抽不到不是通过）。
    """
    out: set[str] = set()
    for group in re.findall(r"kind\(([^()]*)\)", returns or ""):
        out |= {x.strip() for x in group.split("/") if x.strip()}
    return out


def _function_segment(source: str, func: str) -> str:
    """从模块源码里取出某个顶层函数的源码片段（用来做逐分支的语法级检查）。"""
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            seg = ast.get_source_segment(source, node)
            assert seg, f"取不出 {func} 的源码片段"
            return seg
    raise AssertionError(f"{func} 不在这个模块的源码里")


def _branch_shapes(source: str, func: str):
    """逐条 `return` 抽形状，返回 `(ok 分支键集合, fail 分支键集合, fail 分支 kind, 其它)`。

    规则（与 `base.ok` / `base.fail` 的签名一致）：

    - `return ok({...})` ⇒ ok 分支，键集合 = 那个字典字面量的键。第一个位置参数
      不是字典字面量时记 `None`（读不出 —— 由调用方判红，读不出不是通过）；
    - `return fail(...)` ⇒ fail 分支，键集合记它第一个位置参数（不是字典时 `None`），
      kind 取 `kind=` 那个关键字；
    - 其它形态（返回变量、三元表达式……）进"其它"，调用方必须断言它是空的，
      否则一条"把字典挪到别处再 return"的重构会让判据静默失效。
    """
    seg = _function_segment(source, func)
    fn = ast.parse(seg).body[0]
    assert isinstance(fn, ast.FunctionDef)
    ok_keys: list[frozenset[str] | None] = []
    fail_keys: list[frozenset[str] | None] = []
    fail_kinds: list[str | None] = []
    other: list[str] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        call = node.value
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
            other.append(ast.dump(call)[:80])
            continue
        name = call.func.id
        if name not in ("ok", "fail"):
            other.append(name)
            continue
        first = call.args[0] if call.args else None
        keys: frozenset[str] | None = None
        if isinstance(first, ast.Dict):
            keys = frozenset(
                str(k.value) for k in first.keys if isinstance(k, ast.Constant)
            )
        if name == "ok":
            ok_keys.append(keys)
        else:
            kind = None
            for kw in call.keywords:
                if kw.arg == "kind" and isinstance(kw.value, ast.Constant):
                    kind = str(kw.value.value)
            fail_keys.append(keys)
            fail_kinds.append(kind)
    return ok_keys, fail_keys, fail_kinds, other


def test_every_return_of_check_formal_matches_its_declaration(store: Store):
    """`I-4`/`T3`：逐条 `return` 与声明比对 —— 覆盖全部 ok 分支与全部 fail 分支。

    旧判据只采 3 条 ok 分支，于是「分支间键集合不一致」与「失败分支被改成放行」
    在套件里结构性看不见（`I-4` 的注入实验：把拒绝分支改成猜一个名字，104 条
    相关用例照样全绿）。这里改成语法级判据：从 `verify_tools` 的源码里把
    `check_formal` 的每一条 `return` 抽出来，逐条与声明比对。

    三条硬要求：

    1. 每一条 ok 分支的键集合必须与声明的键集合逐字相同（不是子集）；
    2. 每一条 fail 分支都不许给键集合（`data=None`）；
    3. 每条 fail 分支的 `kind` 必须在声明的失败词表里；
    4. 没有"读不出形状"的 `return` —— 读不出不许算通过。
    """
    reg = registry_for(VT, store, root=store.root)
    spec = reg.get("verify.check_formal")
    declared = declared_keys(spec.returns)
    declared_kinds = _declared_failure_kinds(spec.returns)
    src = Path(VT.__file__).read_text(encoding="utf-8")
    ok_keys, fail_keys, fail_kinds, other = _branch_shapes(src, "check_formal")

    assert not other, f"check_formal 里有读不出形状的 return：{other}"
    assert len(ok_keys) >= 4, (
        f"只抽到 {len(ok_keys)} 条 ok 分支 —— 判据没覆盖到该覆盖的分支"
        "（今天有：探测没做成 / 无后端 / 无脚本 / 跑完一次）"
    )
    for keys in ok_keys:
        assert keys is not None, (
            "有一条 ok 分支的返回不是字典字面量 ⇒ 键集合读不出来。"
            "把字典挪到别处构造会让这条判据静默失效，请把它写成字面量或显式登记例外"
        )
        assert keys == declared, (
            f"ok 分支的键与 `returns=` 不一致：多 {sorted(keys - declared)}，"
            f"少 {sorted(declared - keys)}"
        )
    assert fail_keys, "一条 fail 分支都没抽到 —— 这条判据其实没在检查拒绝路径"
    for keys in fail_keys:
        assert keys is None, (
            f"fail 分支居然给了键集合 {sorted(keys)}，而声明写的是 `data=None`（一个键都不给）"
        )
    assert declared_kinds, f"声明里没有可解析的失败 kind 词表：{spec.returns!r}"
    assert len(fail_kinds) == len(fail_keys)
    for kind in fail_kinds:
        assert kind in declared_kinds, (
            f"fail 分支的 kind={kind!r} 不在声明的失败词表 {sorted(declared_kinds)} 里"
        )


def test_negative_control_the_branch_checker_catches_an_extra_key_in_an_ok_branch(store: Store):
    """负控（`I-4`）：给一条 ok 分支多塞一个键 ⇒ 逐分支判据必须发现。

    注入打在真实源码片段的文本上（把 `return ok(` 的第一个位置参数换成一个
    多带一个键的字典）。第一句断言"注入确实改了源码片段"：锚点哪天失效，
    这条会红，而不是静默地什么都没注入（空转的负控与没有负控是一回事）。
    """
    reg = registry_for(VT, store, root=store.root)
    declared = declared_keys(reg.get("verify.check_formal").returns)
    src = Path(VT.__file__).read_text(encoding="utf-8")
    seg = _function_segment(src, "check_formal")
    mutated = seg.replace("return ok(", 'return ok({"leaked_key": 1}, ', 1)
    assert mutated != seg, "注入锚点失效（`return ok(` 的写法变了）—— 重新对准锚点"
    ok_keys, _, _, _ = _branch_shapes(mutated, "check_formal")
    assert any(keys is not None and keys != declared for keys in ok_keys), (
        "给一条 ok 分支多塞一个键，逐分支判据居然没发现"
    )


def test_negative_control_the_branch_checker_catches_a_keyed_fail_branch(store: Store):
    """负控（`I-4`/`C2`）：让一条 fail 分支返回字典 ⇒ 逐分支判据必须发现。

    这正是 `I-4` 注入实验的形态：把拒绝分支改成"给一套键 / 猜一个名字"，
    旧判据全绿。现在它必须响。
    """
    src = Path(VT.__file__).read_text(encoding="utf-8")
    seg = _function_segment(src, "check_formal")
    mutated = seg.replace("return fail(", 'return fail({"leaked_key": 1}, ', 1)
    assert mutated != seg, "注入锚点失效（`return fail(` 的写法变了）—— 重新对准锚点"
    _, fail_keys, _, _ = _branch_shapes(mutated, "check_formal")
    assert any(keys is not None for keys in fail_keys), (
        "fail 分支返回了字典，逐分支判据居然没发现"
    )


def test_negative_control_the_branch_checker_catches_an_unreadable_return():
    """负控（`I-4`）：把返回的构造器换成一个不认识的函数 ⇒ 必须落进"读不出"而不是静默通过。

    这模拟的是"把字典挪到别处再 return"那类重构：形状读不出来时判据必须响，
    否则一条判据会在重构之后静默地什么都不检查。
    """
    seg = _function_segment(Path(VT.__file__).read_text(encoding="utf-8"), "check_formal")
    mutated = seg.replace("return ok(", "return _payload(", 1)
    assert mutated != seg, "注入锚点失效（`return ok(` 的写法变了）—— 重新对准锚点"
    _, _, _, other = _branch_shapes(mutated, "check_formal")
    assert other, "把返回的构造器换成不认识的函数之后，逐分支判据居然什么都没报"


def test_declared_returns_are_a_subset_of_what_the_tools_actually_return(store: Store):
    """通用防漂移：`returns=` 承诺的键必须在实际 payload 里都存在（4.5 #4/#7/#8）。"""
    from conftest import add_concept, add_relation

    add_concept(store, "0000", "群")
    add_concept(store, "0001", "阿贝尔群")
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="An abelian group is a group.")
    add_literature(store, "0000", title="有正文", path="0000/source.txt", processed=True)
    write_library_file(store, "0000/source.txt", "An abelian group is a group.\n")

    trace_reg = registry_for(TR, store)
    cases = (
        ("trace.relation", {"relation_id": "0000"}),
        ("trace.concept", {"concept_id": "0000"}),
        ("trace.literature", {"lit_id": "0000", "max_chars": 200}),
        ("trace.chain", {"relation_ids": ["0000"]}),
    )
    for name, params in cases:
        res = trace_reg.call(name, **params)
        assert res.ok, (name, res.error)
        missing = declared_keys(trace_reg.get(name).returns) - set(res.data)
        assert not missing, f"{name} 的 returns= 承诺了但没给：{sorted(missing)}"

    verify_reg = registry_for(VT, store, root=store.root)
    for name, params in (
        ("verify.evidence_for", {"claim_key": "k"}),
        ("verify.evidence_for", {}),
        ("verify.list_experiments", {}),
    ):
        res = verify_reg.call(name, **params)
        assert res.ok, (name, res.error)
        missing = declared_keys(verify_reg.get(name).returns) - set(res.data)
        assert not missing, f"{name} 的 returns= 承诺了但没给：{sorted(missing)}"
    det = verify_reg.call("verify.detect_verifier").data
    assert not declared_keys(verify_reg.get("verify.detect_verifier").returns) - set(det)


# ============================================================ P2-10 非 ToolError 逃逸


def _assert_not_unexpected(res: object, expected_kind: str) -> None:
    assert res.ok is False  # type: ignore[attr-defined]
    kind = res.meta.get("kind")  # type: ignore[attr-defined]
    assert kind == expected_kind, (kind, res.error)  # type: ignore[attr-defined]
    assert kind != "unexpected", "修之前它会逃出工具层，被 base.py 兜成无声的 kind='unexpected'"


def test_no_unexpected_escape_doc_and_review_store_failure(store: Store):
    """`doc.*` / `review.*`：`StoreError`（RuntimeError）不再逃逸成 `unexpected`。"""
    doc_reg = registry_for(DT, store, workspace_root=store.root)
    rev_reg = registry_for(RV, store)
    assert doc_reg.call("doc.list_documents").ok is True
    assert rev_reg.call("review.list_findings").ok is True

    # `documents` 表坏了 ⇒ 读侧（list_documents）与写侧（build_document）都要结构化失败。
    # 这里让 citation 核对先通过（否则会先撞上 dangling_citation，测不到 StoreError）：
    # 把 documents 表弄坏、但 literature 表是好的。
    add_literature(store, "0000", title="真实文献", processed=True)
    corrupt(store, "documents.json")
    _assert_not_unexpected(doc_reg.call("doc.list_documents"), "store_error")
    _assert_not_unexpected(
        doc_reg.call(
            "doc.build_document",
            kind="note",
            title="t",
            claims=[DT.compose_claim("x", citations=["lit:0000"], evidence_kind="heuristic", section="s")],
        ),
        "store_error",
    )

    # `review_findings` 表坏了 ⇒ 同一个 guard_result 也要把它变成 store_error
    store2 = Store(store.root)
    corrupt(store2, "review_findings.json")
    _assert_not_unexpected(registry_for(RV, store2).call("review.list_findings"), "store_error")


def test_no_unexpected_escape_trace_store_failure(store: Store):
    corrupt(store, "relations.json")
    res = registry_for(TR, store).call("trace.chain", relation_ids=["0000"])
    _assert_not_unexpected(res, "store_error")
    assert res.meta.get("checked") is False


def test_no_unexpected_escape_verify_store_reads(store: Store):
    corrupt(store, "experiments.json")
    reg = registry_for(VT, store, root=store.root)
    _assert_not_unexpected(reg.call("verify.evidence_for", claim_key="k"), "store_error")
    _assert_not_unexpected(reg.call("verify.list_experiments"), "store_error")


def test_no_unexpected_escape_verify_code_hash_io(store: Store, monkeypatch: pytest.MonkeyPatch):
    """`verify.code_hash`：`open()` 的 OSError（文件被占用/ACL 拒绝）不再逃逸。

    桩打在 `open` 上，不打在被测的 `code_hash` 上。这一点是本用例的关键：
    把桩打在 `code_hash` 上等于把整个函数体换掉 —— 于是"逃逸已修好"这件事
    根本没有被执行过（实测：改成打 `open` 之后，`code_hash` 的真实函数体
    确实收到了那个路径并抛出 `PermissionError`，见 `temp/_probe_g35_patch_target.py`）。
    `raising=False` 只为容忍"某天实现把 `open` 显式导进了本模块 globals"这种改写。
    """
    reg = registry_for(VT, store, root=store.root)
    (store.root / "probe.py").write_text("print(1)\n", encoding="utf-8")

    def boom(*_a, **_k):
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(VT, "open", boom, raising=False)
    _assert_not_unexpected(reg.call("verify.code_hash", path="probe.py"), "io_error")
    # 负控：正常的哈希路径照旧可用（撤掉桩，同一个文件、同一条路径）
    monkeypatch.undo()
    ok_res = reg.call("verify.code_hash", path="probe.py")
    assert ok_res.ok and len(ok_res.data["code_hash"]) == 16


def test_no_unexpected_escape_verify_run_experiment_out_of_workspace(store: Store):
    """`verify.run_experiment`：脚本越界抛的是 `ExperimentError(RuntimeError)`，不再逃逸。"""
    reg = registry_for(VT, store, root=store.root)
    before = (store.data / "experiments.json").read_bytes()
    res = reg.call(
        "verify.run_experiment",
        claim="c",
        claim_key="k",
        script_path="../../../outside.py",
    )
    assert res.ok is False
    assert res.meta.get("kind") in ("experiment_error", "validation_error", "param_error"), res.meta
    assert res.meta.get("kind") != "unexpected"
    assert (store.data / "experiments.json").read_bytes() == before, "失败不许留下实验行"


def test_no_unexpected_escape_ocr_page_count_and_pdf_pages(store: Store, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """`ocr.detect_text_layer` / `ocr.run`：页数探测与逐页读取的异常都要结构化。"""
    reg = registry_for(OT, store, workspace=tmp_path, backends=[_StubBackend("stub", "TEXT")])
    # ---- detect_text_layer：page_count 抛
    txt = tmp_path / "a.txt"
    txt.write_text("hello", encoding="utf-8")

    def boom(_p):
        raise RuntimeError("没有 fitz")

    monkeypatch.setattr(OT, "page_count", boom)
    _assert_not_unexpected(reg.call("ocr.detect_text_layer", path="a.txt"), "page_count_failed")

    # ---- ocr.run：逐页 load_page 抛（所有页都失败 ⇒ all_pages_failed，且逐页留痕）
    fitz = pytest.importorskip("fitz", reason="栅格化 PDF 需要 PyMuPDF")
    pdf = tmp_path / "two.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    class _BoomDoc:
        page_count = 2

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def load_page(self, _i):
            raise RuntimeError("页坏了")

    monkeypatch.setattr(fitz, "open", lambda *_a, **_kw: _BoomDoc())
    res = reg.call("ocr.run", path="two.pdf")
    assert res.ok is False
    assert res.meta.get("kind") == "all_pages_failed", res.meta
    assert res.meta.get("kind") != "unexpected"
    assert all("读取第" in p["error"] for p in res.meta["pages"]), res.meta["pages"]


def test_no_unexpected_escape_search_register_schema_failure(store: Store, monkeypatch: pytest.MonkeyPatch):
    """`search.register` 的 `row.validate()` 不再无声逃逸（同一调用类型 42 行后被显式 guard 过）。"""
    reg = registry_for(ST, store, workspace=store.root)

    def boom(_self):
        raise ValueError("title 超过 600 字符（夹具故意）")

    monkeypatch.setattr(S.Literature, "validate", boom)
    res = reg.call("search.register", title="T", type_code="J", summary="s")
    _assert_not_unexpected(res, "validation_error")
    assert res.meta.get("lit_id")
    assert store.rows("literature") == [], "校验失败的行不许落盘"

    # 负控：取消打桩后，正常的登记照旧成功
    monkeypatch.undo()
    ok_res = reg.call("search.register", title="正常的文献", type_code="J", summary="s")
    assert ok_res.ok and ok_res.data["created"] is True
    assert store.rows("literature")[0]["title"] == "正常的文献"


# ============================================================ 4.1 零断言工具的契约


def test_table_list_total_is_the_filtered_total_not_the_page_size(store: Store):
    """4.1：`table.list` 的 `total` 是过滤后总数 —— 分页逻辑唯一的依据，此前零断言。"""
    reg = registry_for(TT, store)
    for i in range(5):
        reg.call("table.create", table="statements",
                 row={"origin": "own_result", "kind": "theorem", "label": f"c{i}",
                      "statement_full": "d", "quote_reason": "尚未逐字校验"})

    page1 = reg.call("table.list", table="statements", limit=2)
    assert page1.ok, page1.error
    assert page1.data["total"] == 5, "total 必须是过滤后的总数，不是本页条数"
    assert page1.data["returned"] == 2 and len(page1.data["rows"]) == 2

    page3 = reg.call("table.list", table="statements", limit=2, offset=4)
    assert page3.data["total"] == 5 and page3.data["returned"] == 1, "最后一页只有 1 条，但 total 仍是 5"

    filtered = reg.call("table.list", table="statements", limit=10, filter={"label": "c1"})
    assert filtered.data["total"] == 1, "total 说的是**过滤后**的总数"


def test_table_count_is_not_affected_by_limit(store: Store):
    """4.1：`table.count` 的 docstring 明说"计数不该受 limit 影响" —— 这条不变量此前没被测。"""
    reg = registry_for(TT, store)
    for i in range(4):
        reg.call("table.create", table="statements",
                 row={"origin": "own_result", "kind": "theorem", "label": f"c{i}",
                      "statement_full": "d", "quote_reason": "尚未逐字校验"})
    assert reg.call("table.count", table="statements").data == 4
    # count 没有 limit 参数，但被列表的 limit 影响才是真正的缺陷：连开两次 list 后 count 不变
    reg.call("table.list", table="statements", limit=1)
    assert reg.call("table.count", table="statements").data == 4
    # 负控：过滤时总数按过滤后的口径
    assert reg.call("table.count", table="statements", filter={"label": "c2"}).data == 1


# ---------------------------------------------------------------- 测试用 OCR 桩


class _StubBackend:
    """本文件自带的 OCR 测试桩（不是真 OCR，只回一个固定字符串）。"""

    produces_text = True

    def __init__(self, name: str, text: str = "") -> None:
        self.name = name
        self._text = text
        self.checks: dict = {"role": "测试桩"}

    def available(self, *, refresh: bool = False) -> tuple[bool, str]:  # noqa: ARG002
        return True, "桩"

    def ocr_image(self, _image, _languages) -> str:
        return self._text
