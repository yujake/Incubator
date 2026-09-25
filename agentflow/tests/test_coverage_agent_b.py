"""`AgentB.resolve_structural_duplicate` 的判据测试（等级 1 写路径：I5 合并执行）。

## 为什么这个函数必须补（它是不可逆的那一类）

它是 I5 的执行端：判定 `merge` 之后会把一个概念合并进另一个，并改写关系的
`concept_ids`。docstring 逐字："错误合并不可逆（度数、路径、问题溯源全被污染），
而漏合并只是少省一点空间。"

所以本文件的核心断言不是"它写出了什么"，而是它拒绝时有没有真的什么都没写，
以及它为什么拒绝（reason 必须能被反驳）。

## 两路证据必须独立（这是本函数的全部判据）

1. 结构侧：候选恰两个概念、都不是墓碑、两者之间没有直接关系；
2. 名字侧：`name_evidence != "none"`，且用 `dedup.find_concept`（同一套规范化）
   去掉自身后双向恰好查回对方。

本文件的负控逐个打在这两条的每一处早退分支上 —— 一个"只看结构就合并"的实现
能通过"两路都齐"的正向断言，但过不了 `name_evidence="none"` 那条。
"""

from __future__ import annotations

import pytest

from agentflow import schema as S
from agentflow import textutil as T
from agentflow.agent_b import AgentB
from agentflow.store import Store

from conftest import TS, add_concept, add_literature, add_relation, sync_counters


# ============================================================ 夹具


class _NoExtractor:
    """本文件不测抽取，只需要一个满足构造签名的替身（不调用它）。"""

    def extract(self, doc, lit_id, meta):  # pragma: no cover - 不会被调用
        return [], []


@pytest.fixture
def b(store: Store) -> AgentB:
    """一个绑在空工作区上的 AgentB（本文件只测 I5 的合并决定/执行）。"""
    return AgentB(store, extractor=_NoExtractor(),
                  extract_text=lambda *a, **k: None,
                  config={"lease_seconds": 900, "max_attempts": 3})


def _two_concepts_same_name(st: Store, *, definition_a: str = "", definition_b: str = "") -> None:
    """造一对"规范化名字相同"的概念 —— 于是名字侧双向复核能通过。

    概念名与别名都从 `textutil.normalize` 走（`dedup.find_concept` 的同一套），
    不在这里另写一份小写化规则（FC-03：同一判据只有一份实现）。
    """
    add_literature(st, "0000", path="0000/s.txt")
    for cid, name, definition in (("0000", "群", definition_a), ("0001", "群", definition_b)):
        row = S.Concept(concept_id=cid, name=name, definition=definition,
                        related_concepts=[], normalized_name=T.normalize(name), aliases=[],
                        created_at=TS, updated_at=TS)
        row.validate()
        with st.tx("concepts", actor="test") as tx:
            tx.upsert("concepts", row.to_dict())
    sync_counters(st)


#: 候选的最小形状。字段名来自 `decide_structural_duplicate` 的实现（它读
#: `concept_ids` / `name_evidence` / `neighbors` / `proposal`）。
def _cand(name_evidence: str, cids: tuple[str, str] = ("0000", "0001")) -> dict:
    return {"concept_ids": list(cids), "name_evidence": name_evidence, "neighbors": ["0002"]}


# ============================================================ 正向：真的合并


def test_resolve_structural_duplicate_accepts_and_rewrites_relations(b: AgentB, store: Store):
    """正向：两路证据齐 ⇒ `applied=True`，被合并方的编号从关系的 `concept_ids` 里消失。

    断言打在判据上（§5.2）：不是"返回了 dict"，而是
    "`verdict=merge` + `applied=True` + 关系里的旧编号被恰好改写成 survivor"。

    关系刻意挂在被合并方（0001）上而不是 survivor 上：只挂在 survivor 上的
    关系根本不需要改写，那样的夹具会让一条"从不改写关系"的实现照样通过。
    """
    _two_concepts_same_name(store, definition_a="群的定义（更长，应当存活）", definition_b="短")
    add_literature(store, "0002", path="0002/s.txt")
    add_concept(store, "0002", "子群")
    add_relation(store, "0000", ["0001", "0002"], "0000", quote="q", quote_verified=True)
    sync_counters(store)

    out = b.resolve_structural_duplicate(_cand("same_normalized_name"))

    assert out["verdict"] == "merge", out
    assert out["applied"] is True, out
    survivor, merged = out["survivor_id"], out["merged_id"]
    assert (survivor, merged) == ("0000", "0001"), out
    # 判据①：合并后没有任何关系还引用被合并方的编号。
    for r in store.rows("relations"):
        assert merged not in {str(x) for x in (r.get("concept_ids") or [])}, r
    # 判据②：那条关系被改写成了 survivor 与另一个概念的组合（而不是被删掉）。
    rel = next(r for r in store.rows("relations") if r["relation_id"] == "0000")
    assert {str(x) for x in rel["concept_ids"]} == {survivor, "0002"}, rel
    # 判据③：`rewritten_relation_ids` 记的是被改写的那条关系的编号（不是概念编号）。
    assert out["rewritten_relation_ids"] == ["0000"], out


def test_resolve_structural_duplicate_survivor_is_the_longer_definition(b: AgentB, store: Store):
    """正向（判据的取值规则）：定义更长者存活；同长取 `concept_id` 较小者。

    为什么这条必须单独测：survivor 选错会静默删掉更完整的定义
    （docstring 逐字："丢掉更完整的定义等于静默删知识"）。
    只断言"合并成功"完全覆盖不到这条规则。
    """
    _two_concepts_same_name(store, definition_a="很短", definition_b="这是一个长得多、信息量更大的定义")
    out = b.resolve_structural_duplicate(_cand("same_normalized_name"))
    assert out["verdict"] == "merge", out
    assert out["survivor_id"] == "0001", out  # 0001 的定义更长
    assert out["merged_id"] == "0000", out


def test_resolve_structural_duplicate_equal_definitions_pick_smaller_id(b: AgentB, store: Store):
    """正向（tie-break 的确定性）：定义等长 ⇒ 取 `concept_id` 较小者存活。

    为什么要有这条：tie-break 若依赖表的物理顺序，同一个候选在两次运行里
    可能给出相反的结论 —— 那就不可复现、不可审计。
    """
    _two_concepts_same_name(store, definition_a="一样长", definition_b="也一样")
    out = b.resolve_structural_duplicate(_cand("same_normalized_name"))
    assert out["verdict"] == "merge", out
    assert (out["survivor_id"], out["merged_id"]) == ("0000", "0001"), out


# ============================================================ 负控：写盘


def test_resolve_structural_duplicate_rejects_without_name_evidence_and_writes_nothing(
    b: AgentB, store: Store
):
    """负控（最重要的一条）：只有一路证据 ⇒ `reject`，且两张表逐字节不变。

    这是"结构等价 ≠ 同义"这条判据的钉子。它同时证明"拒绝"与"不写盘"绑在一起 ——
    一个先写后判、判完再回滚的实现会在这里露馅（退出码相同但磁盘已变）。
    """
    _two_concepts_same_name(store)
    add_relation(store, "0000", ["0000", "0002"], "0000", quote="q", quote_verified=True)
    sync_counters(store)
    before_c = (store.data / "concepts.json").read_bytes()
    before_r = (store.data / "relations.json").read_bytes()

    out = b.resolve_structural_duplicate(_cand("none"))

    assert out["verdict"] == "reject", out
    assert out["applied"] is False, out
    assert out["rewritten_relation_ids"] == [] and out["rejected_relation_ids"] == []
    # reason 必须说清"只有一路证据"，否则人无法反驳这个拒绝。
    assert "同义" in out["reason"] or "一路" in out["reason"], out["reason"]
    assert (store.data / "concepts.json").read_bytes() == before_c, "reject 却改了概念表"
    assert (store.data / "relations.json").read_bytes() == before_r, "reject 却改了关系表"


def test_resolve_structural_duplicate_rejects_when_direct_relation_exists(b: AgentB, store: Store):
    """负控：两者之间已有直接关系 ⇒ 拒绝（它们已被声明为两个不同的东西）。

    这一路证据是结构侧的，与名字侧无关：即便名字证据齐（`same_normalized_name`），
    有直接关系也必须拒绝。只测名字侧的负控会漏掉这条。
    """
    _two_concepts_same_name(store)
    add_relation(store, "0000", ["0000", "0001"], "0000", quote="q", quote_verified=True)
    sync_counters(store)

    out = b.resolve_structural_duplicate(_cand("same_normalized_name"))

    assert out["verdict"] == "reject", out
    assert "直接关系" in out["reason"], out["reason"]
    assert out["applied"] is False


def test_resolve_structural_duplicate_rejects_when_name_recheck_fails(b: AgentB, store: Store):
    """负控：名字侧独立复核未通过（规范化名字其实不同）⇒ 拒绝。

    这是"不采信候选里的结论"这条判据的钉子：候选声称有名字证据
    （`same_normalized_name`），但 B 拿 `dedup.find_concept` 在同一套规范化下
    复算不出来 ⇒ 必须拒绝。一个直接采信 `name_evidence` 字符串的实现
    会在这里合并两个不同的概念。
    """
    add_literature(store, "0000", path="0000/s.txt")
    add_concept(store, "0000", "群", definition="长定义")
    add_concept(store, "0001", "环", definition="短")   # 名字不同
    sync_counters(store)

    out = b.resolve_structural_duplicate(_cand("same_normalized_name"))

    assert out["verdict"] == "reject", out
    assert "名字侧" in out["reason"] or "复核" in out["reason"], out["reason"]


def test_resolve_structural_duplicate_rejects_tombstone_and_bad_shape(b: AgentB, store: Store):
    """负控（三个早退分支各一条）：墓碑 / 数量不对 / 概念不存在。

    三态纪律的近亲：这三种原因的 `reason` 必须互不相同，否则人拿到
    "拒绝"以后不知道该去查什么。合成一条"非空即可"的断言会丢掉这个区分。
    """
    _two_concepts_same_name(store)
    with store.tx("concepts", actor="test") as tx:
        row = tx.find("concepts", concept_id="0001")
        row["merged_into"] = "0000"
        # `merge_reason` 是 schema 的必填配套字段（`Concept.validate`：
        # "标了 merged_into 却没有 merge_reason"直接抛）。夹具必须满足它，
        # 否则测到的是 schema 的行校验而不是本函数的墓碑分支。
        row["merge_reason"] = "测试用墓碑"
        tx.upsert("concepts", row)
    tomb = b.resolve_structural_duplicate(_cand("same_normalized_name"))
    assert tomb["verdict"] == "reject" and "墓碑" in tomb["reason"], tomb

    shape = b.resolve_structural_duplicate({"concept_ids": ["0000"], "name_evidence": "alias"})
    assert shape["verdict"] == "reject" and "恰好两个" in shape["reason"], shape

    same = b.resolve_structural_duplicate({"concept_ids": ["0000", "0000"], "name_evidence": "alias"})
    assert same["verdict"] == "reject" and "相同" in same["reason"], same

    missing = b.resolve_structural_duplicate({"concept_ids": ["0000", "9999"], "name_evidence": "alias"})
    assert missing["verdict"] == "reject" and "不存在" in missing["reason"], missing

    # `None` 候选（"没给"）也必须是一个可区分的拒绝，而不是 TypeError。
    none_cand = b.resolve_structural_duplicate(None)
    assert none_cand["verdict"] == "reject" and "恰好两个" in none_cand["reason"], none_cand
