# -*- coding: utf-8 -*-
"""判据：秘书要能认出"表述几乎相同的两条命题是同一个"，并把截然不同的证明并列记录。

业主 2026-10-24 的原话（唯一权威）：

    我怕B的秘书看到对表述几乎相同的定理，不会有种意识它们是同一个，然后把截然不同的
    证明并列记录（如果证明方式几乎相同，视为同种证明，可选：各取所长混合表述，重拿V签）。

## 这一份钉的六条

| 条 | 它要证明的事 | 改前（这一笔之前）为什么是红的 |
|---|---|---|
| ① | 两条表述不同、同一命题的登记 ⇒ 落成一条 `stmt` + `proof_no=2` | 改前 `_record_statement_tx` 只按 `textutil.normalize(statement_full)` 查重：换一种写法就是新的一条命题 ⇒ 两条 `stmt`、`proof_no` 恒为 1 |
| ② | 两条证明几乎相同的 ⇒ 不新增 `proof_no`、`refused="proof_same_kind"`、拒信点名 `#k` | 改前没有"同种证明"这道判断：第二份照收成 `#p2`（"并列记录"正是业主担心的那件事） |
| ③ | 两条截然不同的证明 ⇒ `proof_no=2`，且两条路径的依赖面 `groups_of` 按证明号分开 | 改前第二条登记落成新命题 ⇒ `groups_of` 里只有一条命题、没有第 2 份证明这一维 |
| ④ | `merge=true` ⇒ 覆盖 canonical、旧正文进 `proof_history`、未重签前不算成立（负控） | 改前 `merge` 这个键不被任何判据读（白名单原样留着、`record_statement` 不看它）⇒ 换写法的合并稿落成新命题；同写法的合并稿只走 canonical 覆盖那一支（有 `proof_history`、没有"要求重签"这一档） |
| ⑤ | 反真空：`proposition_key` 打桩成"恒不等" ⇒ ① 必红；打桩成"恒等" ⇒ 一条无关命题也被并进去 ⇒ 必红 | 这一条不靠改前代码：它证明 ①③④ 的绿有对象（判据真的在判，不是恒真） |
| ⑥ | 三态：文本过短 / 纯符号 ⇒ `unknown` 且不并（不猜） | 改前没有这道判断，短文本与长文本走同一条查重路（只能判"同/不同"）；"判不了"这一档在改前不存在 |

## "改前红"怎么在本文件里可复现

改前的行为可以用一次 monkeypatch 精确复现：把 `propositionkey.proposition_key` 打桩成
"每条文本一个自己的键"就等于"没有同一性判断"（题面差异不再被规范化掉）；把
`propositionkey.same_kind_proof` 打桩成"永远不同"就等于"没有同种证明这道判断"。
`test_reverting_one_judge_turns_its_criterion_red` 就是这么做的：它把 ① 与 ② 分别
打回改前行为，并断言同一组读数当场变红。这不是"另写一份假代码"，注入点就是判据本体
（`_judge` / `_same_kind_hits` 都只经这两个模块级函数）。

## 两处边界（读的人要知道；它们让上面六条不至于被读成"所有重复登记都会并"）

1. 只在命题性的 kind 之间判（`secretary.PROPOSITION_KINDS`：theorem / lemma /
   proposition / corollary / conjecture）。`definition` / `concept` 不是命题 ——
   "表述几乎相同的两条命题是同一个"这句话对它们不成立（本仓的
   `test_agent_b_concept_registration_carries_kind.py` 就用"同一条正文、只换
   theorem / definition"核对五个位，那两条本来就该是两行）。
2. 没有证明正文的登记不进合并支：它不产生"第 N 份证明"，而把它的载荷（bits / kind /
   引文三态）静默并进另一行，等于丢一次登记。这一支保留老口径（按规范化正文精确查重）。

## 边界

全部 tmp 工作区、零模型调用（V 的签名走 `verifications.record_verification`）。
不写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式（这一份也要能在一棵临时源码树上单独跑）。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import evidencebits as EB
from agentflow import propositionkey as PK
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_c.proof_chain import _DepGraph
from agentflow.secretary import Secretary
from agentflow.store import Store

#: 第一条命题（登记工作区里的第一行，号由 store 发，实得 `000000`）。
SID = S.format_id(0)
#: 两条依赖的根（③ 要用它们把"两条证明的依赖面分得开"落到 `groups_of` 上）。
LIT_A = S.format_id(9)
LIT_B = S.format_id(8)

#: 命题的两种写法：引导词（设/若/则 vs 假设/为/于是）不同，内容相同。
#: 这一对的键相同（`proposition_key` 命中），词面相似度 0.7986 < 0.85 —— 所以它是
#: "键那一档"的样本（不是相似度兜底那一档）。
FULL_A = "设 G 是 3-正则群；则弦长函数不是常值。"
FULL_A_KEY = "假设 G 为 3-正则群，于是弦长函数不是常值。"
#: 同一个句子的词形变体（`常值` -> `常数值`）：键不同（二元组多了 `数值`），
#: 词面相似度 0.9118 >= 0.85 ⇒ 这是"相似度兜底那一档"的样本。
FULL_A_MORPH = "设 G 是 3-正则群；则弦长函数不是常数值。"
#: 一条与上面无关的命题（反真空用：打桩成"恒等"时它会被并进去）。
FULL_B = "设 H 是有限群；则 H 的阶有限。"

#: 证明 #p1（定义直算路线；引 `lit:000009` 好让依赖边落得下来）。
PROOF_A = ("证明：把弦长函数记为 f，设 G 是 3-正则群。由定义直接计算每个顶点的邻域大小，"
           "弦长只依赖邻域结构，故 f 在正则性下取常值，与假设矛盾。见 lit:000009。")
#: 与 `PROOF_A` 几乎同一种证法（换了两处措辞）：相似度 0.8538 >= 0.80。
PROOF_A_NEAR = ("证明：把弦长函数记为 f，设 G 为 3-正则群。由定义直接算出每个顶点的邻域大小，"
                "弦长只依赖于邻域结构，因此 f 在正则性下取常值，与假设矛盾。见 lit:000009。")
#: 与 `PROOF_A` 截然不同的证法（归纳路线；引 `lit:000008`）。
PROOF_B = ("证明：对顶点数作强归纳。取一条最长路径，用 3-正则性把端点邻域配对，"
           "再以诱导子图归结到更小的图，最终得到弦长随基图变化的递推，导出非常值。"
           "见 lit:000008。")
#: 又一条不相干的证法（相似度兜底那一档的样本用它，免得撞上"同种证明"）。
PROOF_C = ("证明：用对偶图的度数公式。常值弦长会逼出所有顶点同构，而 3-正则图里"
           "存在反例（Petersen 图），故弦长函数不是常值。")
#: 合并稿（各取所长：定义直算 + 归纳配对）。它与两份原稿都不像（0.67 / 0.59）——
#: 那正是"合并"的必然结果，所以 `merge=true` 不靠"合并稿与谁同种"来判。
MERGED = (PROOF_A + "\n"
          "另：也可对顶点数作归纳（配对步骤见 lit:000008），两条路线在这里合并为一份。")

_OK = {"verdict": "成立", "findings": []}


# ------------------------------------------------------------------ 小工具

def _ws(path: pathlib.Path) -> Store:
    st = Store(path / "ws")
    st.init()
    return st


def _agent(st: Store) -> AgentB:
    """B 的真实现（零模型调用：这条路只碰秘书与 store）。"""
    return AgentB(st, extractor=None, extract_text=None, config={})


def _own(full: str) -> dict:
    """自产命题的必填件（`doc_id` + `quote_reason`；B-2 之后首登按猜想）。"""
    return {"statement_full": full, "statement_text": full[:24],
            "origin": "own_result", "kind": "conjecture",
            "doc_id": S.format_id(0), "quote_reason": "我方自产命题，没有外部引文要比对"}


def _put_lit(st: Store, lit_id: str) -> None:
    row = S.Literature(lit_id=lit_id, title=f"文献 {lit_id}", type="J", summary="夹具",
                       path=None, added_at=S.now_iso())
    row.validate()
    with st.tx("literature", actor="test") as tx:
        tx.upsert("literature", row.to_dict())


def _rows(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("statements")]


def _row(st: Store, stmt_id: str = SID) -> dict:
    hit = [r for r in _rows(st) if str(r.get("stmt_id")) == stmt_id]
    assert hit, f"盘上读不到命题 {stmt_id}（在册：{[r.get('stmt_id') for r in _rows(st)]}）"
    return hit[0]


def _sign(st: Store, *, text: str, proof_no: int = 1, stmt_id: str = SID) -> dict:
    """V 的签名写入口（`verify_proof` 走的就是它；这里不经模型）。"""
    return VR.record_verification(st.root, statement_id=stmt_id, proof_text=text,
                                  verdict=dict(_OK), verifier="agent-V", store=st,
                                  proof_no=proof_no)


def _reading(st: Store, stmt_id: str = SID) -> dict:
    return VR.statement_review_reading(st.root, _row(st, stmt_id))


def _proof_nos(row: dict) -> list[int]:
    return [int(no) for no, _ in VR.proof_list(row)]


def _deps(st: Store) -> list[dict]:
    return [dict(r) for r in st.rows("dependencies")]


def _groups(st: Store, stmt_id: str = SID) -> dict:
    """依赖的二维读数（`{证明号: {路径组: [边]}}`）——读侧唯一口径。"""
    graph = _DepGraph(stmts=_rows(st), deps=_deps(st), exps=[], lits=[])
    return graph.groups_of(stmt_id)


def _criterion_one_problems(base: pathlib.Path, *,
                            first: tuple[str, str] = (FULL_A, PROOF_A),
                            second: tuple[str, str] = (FULL_A_KEY, PROOF_B)) -> list[str]:
    """① 的读数：两条表述不同的同一条命题是不是落成"一条 + 第 2 份证明"。

    收在一处是为了让反真空那一条拿同一份读数打红（判据不经两套口径）。
    """
    st = _ws(base)
    b = _agent(st)
    problems: list[str] = []
    got_first = b.register_statement(**_own(first[0]), proof_text=first[1])
    if not (got_first.get("ok") and got_first.get("stmt_id") == SID):
        problems.append(f"首登没落成 {SID}：{got_first}")
        return problems
    got_second = b.register_statement(**_own(second[0]), proof_text=second[1])
    rows = _rows(st)
    if len(rows) != 1:
        problems.append(f"两条表述不同的同一条命题落成了 {len(rows)} 条命题行（应 1 条）")
    if not got_second.get("ok"):
        problems.append(f"第二条登记被拒：{got_second.get('kind')} / {got_second.get('error')}")
        return problems
    if int(got_second.get("proof_no") or 0) != 2:
        problems.append(f"第二条登记没被读成第 2 份证明（proof_no={got_second.get('proof_no')!r}）")
    if rows and _proof_nos(rows[0]) != [1, 2]:
        problems.append(f"证明号不是 [1, 2]：{_proof_nos(rows[0])}")
    if rows and VR.proof_text_of(rows[0], 1) != first[1]:
        problems.append("canonical 那一格被第二份证明顶掉了")
    if rows and VR.proof_text_of(rows[0], 2) != second[1]:
        problems.append("第 2 份证明的正文不是交来的那一份")
    return problems


def _unrelated_merge_problems(base: pathlib.Path) -> list[str]:
    """反真空（恒等那一档）的读数：一条无关命题是不是被并进了既有命题。"""
    st = _ws(base)
    b = _agent(st)
    problems: list[str] = []
    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    if not first.get("ok"):
        return [f"首登失败：{first}"]
    other = b.register_statement(**_own(FULL_B), proof_text=PROOF_C)
    rows = _rows(st)
    if len(rows) != 2:
        problems.append(f"无关命题 {FULL_B!r} 被并进去了：在册 {len(rows)} 条（应 2 条）")
    if other.get("merged"):
        problems.append(f"无关命题被读成 merged（proof_no={other.get('proof_no')!r}）")
    return problems


def _same_kind_refusal_problems(base: pathlib.Path) -> list[str]:
    """② 的读数：几乎相同的第二份证明是不是被拒、且没新增证明号。"""
    st = _ws(base)
    b = _agent(st)
    problems: list[str] = []
    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    if not first.get("ok"):
        return [f"首登失败：{first}"]
    near = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_A_NEAR)
    rows = _rows(st)
    if near.get("ok") is not False:
        problems.append(f"几乎相同的第二份证明被照收了（ok={near.get('ok')!r}）")
    if str(near.get("kind") or "") != "proof_same_kind":
        problems.append(f"拒绝码不是 proof_same_kind：{near.get('kind')!r}")
    if "#1" not in str(near.get("error") or ""):
        problems.append(f"拒信没点名与第几份同种：{str(near.get('error') or '')[:80]!r}")
    if rows and _proof_nos(rows[0]) != [1]:
        problems.append(f"被拒之后证明号仍变成了 {_proof_nos(rows[0])}")
    if len(rows) != 1:
        problems.append(f"被拒之后在册 {len(rows)} 条命题（应 1 条）")
    return problems


# ============================================================ 边界：非命题 kind 不并

def test_non_propositional_kinds_do_not_merge(tmp_path: pathlib.Path) -> None:
    """边界：`definition` 不是命题 ⇒ 与同一条正文的 `theorem` 各占一行，不并。

    这一条守的是"同一命题"这句话的射程：`Statement.kind` 是自由文本（不参与任何判据
    分支），所以判据必须自己说清它管哪几档。并错方向的代价不对称 —— 把一条定理并进
    一条定义，台账上就少掉一整类条目，而盘上看起来完全合法。
    """
    st = _ws(tmp_path)
    sec = Secretary("B", root=st.root, store=st)
    definition = sec.record_statement({**_own(FULL_A + "（本行是定义）"), "kind": "definition",
                                       "proof_text": PROOF_A}, role="B")
    assert definition.get("checked") is True and definition.get("created") is True, definition
    theorem = sec.record_statement({**_own(FULL_A), "kind": "theorem",
                                    "proof_text": PROOF_C}, role="B")
    assert theorem.get("checked") is True and theorem.get("created") is True, theorem
    assert theorem.get("merged") is False, theorem
    rows = _rows(st)
    assert len(rows) == 2, f"definition 与 theorem 被并成了一条：{len(rows)} 行"
    assert [str(r.get("kind")) for r in rows] == ["definition", "theorem"], rows


# ============================================================ ① 的六步规范化

def test_the_key_is_stable_under_the_six_normalizations() -> None:
    """键的规范化各核一次（业主列的那五类差异 + 排序无关的集合化）。

    这不是"再测一遍同一个函数"，而是把"同一条定理的不同写法应该得到同一个键"这句话
    拆成可以各自失败的几件事：编号/标签前缀、记号（`p^a` / `|G|` / 上标、Unicode
    变体）、引导词、分句顺序。任意一条退回去，对应那对样本的键就不再相等。
    """
    base = "设 p 是素数，G 是群，则 p^a 整除 |G|。"
    key = PK.proposition_key(base)
    assert key, "基准样本自己就判不了（键是空的）"
    plain = "设 p <= |G|，则 p^a 整除 |G|。"
    variants = {
        "去编号/标签前缀": ("定理 2.1：设 p 是素数，G 是群，则 p^a 整除 |G|。", base),
        "去引导词（设/若/则/那么）": ("若 p 为素数、G 为群，那么 p^a 整除 |G|。", base),
        "统一记号（p^{a} 与 ∣G∣）": ("设 p 是素数，G 是群，则 p^{a} 整除 ∣G∣。", base),
        "统一 Unicode（≤ 与 <=）": ("设 p ≤ |G|，则 p^a 整除 |G|。", plain),
        "上标字符（pᵃ 与 p^a）": ("设 p <= |G|，则 pᵃ 整除 |G|。", plain),
        "分句换序（排序无关的集合化）": ("p^a 整除 |G|，p 是素数，G 是群。", base),
    }
    for label, (left, right) in variants.items():
        assert PK.proposition_key(left) == PK.proposition_key(right), (
            f"{label} 之后键不相等：{PK.proposition_key(left)!r} != {PK.proposition_key(right)!r}")
    # 反真空：改一个内容词（素 -> 奇）键必须变（否则上面那几条可能只是因为"键恒等"）。
    assert PK.proposition_key("设 p 是奇数，G 是群，则 p^a 整除 |G|。") != key, (
        "换了一个内容词键还是同一个 ⇒ 判据太松（那是恒等的另一种形态）")


# ============================================================ ① 同一命题 ⇒ 一条 + 第 2 份证明

def test_two_phrasings_of_one_proposition_become_one_row_with_proof_two(
        tmp_path: pathlib.Path) -> None:
    """① 两条表述不同但同一命题的登记 ⇒ 落成一条 `stmt` + `proof_no=2`。

    两档依据各核一次：键相同（引导词/记号/编号的差异被规范化掉）与词面相似度兜底
    （键不同、表述高度重合）。返回值必须如实说明"并入了哪一条、作为第几份、凭什么"。
    """
    st = _ws(tmp_path)
    b = _agent(st)

    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    assert first.get("ok") is True and first.get("stmt_id") == SID, first
    second = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_B)
    assert second.get("ok") is True, second
    assert second.get("new_row") is False, second
    assert second.get("merged") is True, second
    assert int(second.get("proof_no") or 0) == 2, second
    assert second.get("matched_by") == PK.BASIS_KEY, second
    assert "并入已有命题" in second.get("note", "") and "第 2 份证明" in second.get("note", ""), (
        second.get("note"))
    assert "proposition_key 相同" in second.get("note", ""), second.get("note")

    rows = _rows(st)
    assert len(rows) == 1, f"两条表述不同的同一条命题落成了 {len(rows)} 条命题行"
    row = rows[0]
    assert _proof_nos(row) == [1, 2], _proof_nos(row)
    assert VR.proof_text_of(row, 1) == PROOF_A, "canonical 那一格被第二份证明顶掉了"
    assert VR.proof_text_of(row, 2) == PROOF_B, VR.proof_text_of(row, 2)
    # 变体留痕：盘上要读得出"这一笔是那一条命题的另一种写法"（凭空并进来是不许的）。
    variants = list(row.get("_proposition_matches") or [])
    assert variants and variants[-1].get("statement_full") == FULL_A_KEY, variants
    assert variants[-1].get("proof_no") == 2, variants

    # 相似度兜底那一档：键不同（常值 / 常数值），词面相似度 0.9118 >= 0.85。
    st2 = _ws(tmp_path / "morph")
    b2 = _agent(st2)
    assert b2.register_statement(**_own(FULL_A), proof_text=PROOF_A).get("ok") is True
    morph = b2.register_statement(**_own(FULL_A_MORPH), proof_text=PROOF_C)
    assert morph.get("ok") is True and morph.get("merged") is True, morph
    assert morph.get("matched_by") == PK.BASIS_SIMILARITY, morph
    assert float(morph.get("similarity") or 0) >= PK.SAME_PROPOSITION_JACCARD, morph
    assert f"{float(morph.get('similarity')):.4f}" in morph.get("note", "") or \
        "prose_similarity" in morph.get("note", ""), morph.get("note")
    assert len(_rows(st2)) == 1 and _proof_nos(_rows(st2)[0]) == [1, 2], _rows(st2)


# ============================================================ ② 同种证明 ⇒ 拒，不新增号

def test_two_nearly_identical_proofs_are_refused_as_the_same_kind(
        tmp_path: pathlib.Path) -> None:
    """② 两条证明几乎相同 ⇒ 不新增 `proof_no`、`proof_same_kind`、拒信点名与 `#k` 同种。

    判据读数与拒信读数各核一次：前者来自 `propositionkey.same_kind_proof`（0.8538 ≥ 0.80），
    后者是秘书交回给调用方的那句话（点名第几份 + 两条处置）。负控：拒了这一笔之后
    盘上仍只有 #p1，且那一条命题还在（不是"整条丢掉"）。
    """
    st = _ws(tmp_path)
    b = _agent(st)
    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    assert first.get("ok") is True, first

    verdict = PK.same_kind_proof(PROOF_A_NEAR, PROOF_A)
    assert verdict["state"] == PK.STATE_SAME, verdict
    assert float(verdict["similarity"]) >= PK.PROOF_SAME_JACCARD, verdict

    near = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_A_NEAR)
    assert near.get("ok") is False, near
    assert near.get("kind") == "proof_same_kind", near
    assert "#1" in near.get("error", ""), near.get("error")
    assert "同种" in near.get("error", ""), near.get("error")
    assert "merge=true" in near.get("error", ""), "拒信没给出合并那一条正路"

    rows = _rows(st)
    assert len(rows) == 1, f"被拒之后在册 {len(rows)} 条命题"
    assert _proof_nos(rows[0]) == [1], f"被拒之后证明号变成了 {_proof_nos(rows[0])}"
    assert VR.proof_text_of(rows[0], 1) == PROOF_A, "被拒的这一笔改动了既有正文"
    # 反真空：换一条真正不同的证法 ⇒ 同一组读数里它能进（否则"拒"可能只是"谁都进不来"）。
    allowed = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_B)
    assert allowed.get("ok") is True and allowed.get("proof_no") == 2, allowed


# ============================================================ ③ 截然不同的证明 ⇒ #p2，依赖面分开

def test_two_different_proofs_are_recorded_side_by_side_with_separate_dependencies(
        tmp_path: pathlib.Path) -> None:
    """③ 两条截然不同的证明 ⇒ `proof_no=2`，两条路径的依赖面按证明号分开。

    依赖读侧是既有的二维展开（`_DepGraph.groups_of`）：第一层是证明号、第二层是路径组。
    这一条要钉的是"第 2 份证明的依赖落在 `used_by='stmt:X#p2'` 上，没有串进 #p1"。
    """
    st = _ws(tmp_path)
    _put_lit(st, LIT_A)
    _put_lit(st, LIT_B)
    b = _agent(st)
    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    assert first.get("ok") is True, first
    second = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_B)
    assert second.get("ok") is True and second.get("proof_no") == 2, second
    assert PK.same_kind_proof(PROOF_A, PROOF_B)["state"] == PK.STATE_DIFFERENT

    tails = sorted(str(d.get("used_by")) for d in _deps(st))
    assert tails == [f"stmt:{SID}", f"stmt:{SID}#p2"], tails
    two_d = _groups(st)
    assert sorted(two_d) == [1, 2], (
        f"`groups_of` 第一层不是证明号：{sorted(two_d)}（第 2 份证明的依赖没落进自己的证明号）")
    assert sorted(two_d[2]) == [1], sorted(two_d[2])
    labels_p1 = [str(d.get("label")) for d in two_d[1][1]]
    labels_p2 = [str(d.get("label")) for d in two_d[2][1]]
    assert labels_p1 == ["lit:000009"], labels_p1
    assert labels_p2 == ["lit:000008"], labels_p2
    assert not (set(labels_p1) & set(labels_p2)), "两条证明的依赖面混在了一起"
    # 路径组仍是"第几条路径"那一维：组内 AND / 组间 OR，不因多一份证明而折平。
    assert all(int(d.get("path_group") or 0) == 1 for d in _deps(st)), _deps(st)

    # V 的签按 proof_no 各签一份（既有 `reviewed_by_proof` 已经支持多维）：
    # 两份证明各签一次，台账两行、逐条表两张都为 true —— 一份的签不许顶替另一份。
    signed1 = _sign(st, text=PROOF_A, proof_no=1)
    signed2 = _sign(st, text=PROOF_B, proof_no=2)
    assert signed1.get("proof_sha256") == VR.proof_sha(PROOF_A), signed1
    assert signed2.get("proof_sha256") == VR.proof_sha(PROOF_B), signed2
    ledger = [r for r in VR.list_verifications(st.root, statement_id=SID, limit=None)[0]]
    assert sorted((int(r.get("proof_no") or 0) for r in ledger)) == [1, 2], ledger
    assert EB.reviewed_by_proof(_row(st)) == {1: True, 2: True}, EB.reviewed_by_proof(_row(st))
    per = {int(p["proof_no"]): p for p in _reading(st).get("proofs") or []}
    assert per[1]["state"] == "signed" and per[2]["state"] == "signed", per


# ============================================================ ④ merge=true ⇒ 覆盖 + 要重签

def test_merge_true_overwrites_canonical_and_requires_a_fresh_v_signature(
        tmp_path: pathlib.Path) -> None:
    """④ `merge=true` ⇒ 覆盖 canonical、旧正文进 `proof_history`、未重签前不算成立。

    负控（同一条判据里就地核两回）：
    1. 不给 `merge` 的同种证明被拒（`proof_same_kind`）—— 合并是可选项，不是默认；
    2. 合并之后 V 那一签盖的是旧稿 ⇒ `statement_review_reading.reviewed` 是 False、
       等级不是 `pre_theorem`；重签之后才回到 signed。这就是"没有 V 重签不许算成立"。
    """
    st = _ws(tmp_path)
    b = _agent(st)
    first = b.register_statement(**_own(FULL_A), proof_text=PROOF_A)
    assert first.get("ok") is True, first
    signed = _sign(st, text=PROOF_A, proof_no=1)
    assert signed.get("statement_writeback", {}).get("written") is True, signed
    assert _reading(st).get("reviewed") is True, _reading(st)

    refused = b.register_statement(**_own(FULL_A_KEY), proof_text=PROOF_A_NEAR)
    assert refused.get("ok") is False and refused.get("kind") == "proof_same_kind", refused

    sec = Secretary("B", root=st.root, store=st)
    merged = sec.record_statement({**_own(FULL_A_KEY), "proof_text": MERGED,
                                   "merge": True}, role="B")
    assert merged.get("checked") is True, merged
    assert merged.get("merged") is True and merged.get("merged_same_kind") is True, merged
    assert merged.get("resign_required") is True, merged
    assert int(merged.get("proof_no") or 0) == 1, merged
    assert merged.get("proof_standing", {}).get("state") == "stale", merged.get("proof_standing")

    row = _row(st)
    assert row.get("proof_text") == MERGED, "合并稿没有覆盖 canonical 那一格"
    history = list(row.get("proof_history") or [])
    assert len(history) == 1, history
    assert history[0].get("text") == PROOF_A, history
    assert history[0].get("sha") == VR.proof_sha(PROOF_A), history
    assert history[0].get("replaced_by") == VR.proof_sha(MERGED), history
    assert int(history[0].get("proof_no") or 0) == 1, "旧正文没记清是哪一份证明的旧稿"
    # 合并与"直接覆盖"的区别：盘上有合并痕迹这一笔（谁合并、合并了哪几份）。
    traces = list(row.get("_proof_merge") or [])
    assert traces and traces[-1].get("resign_required") is True, traces
    assert traces[-1].get("proof_no") == 1, traces

    # 未重签之前不算成立：读侧现算（三处读数都必须是 False / 非 pre_theorem）。
    reading = _reading(st)
    assert reading.get("reviewed") is False, reading
    assert reading.get("grade") != "pre_theorem", reading
    assert EB.bits_from_row(row).get("reviewed") is False, EB.bits_from_row(row)
    assert merged.get("reviewed") is False, merged

    # 重签之后才算成立（正控：否则上面那几条可能只是因为"这一格永远是红的"）。
    resigned = _sign(st, text=MERGED, proof_no=1)
    assert resigned.get("statement_writeback", {}).get("written") is True, resigned
    reading2 = _reading(st)
    assert reading2.get("reviewed") is True, reading2
    assert reading2.get("grade") == "pre_theorem", reading2
    assert row.get("proof_text") == MERGED, "重签不该改动正文"


# ============================================================ ⑤ 反真空：判据有对象

def test_the_same_proposition_verdict_is_not_a_vacuum(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """⑤ 反真空：把 `proposition_key` 打桩成恒不等 ⇒ ① 必红；恒等 ⇒ 无关命题被并 ⇒ 必红。

    打桩点是判据本体（`propositionkey.proposition_key`）：`_judge` 与秘书都只经它取键，
    所以这两种注错正好复现"没有同一性判断"与"同一性判断恒真"两种极端。
    """
    assert _criterion_one_problems(tmp_path / "baseline") == [], (
        "夹具前提：注入之前 ① 应当是绿的")

    # 恒不等 = 改前的行为（每条文本一个自己的键，题面差异不再被规范化掉）。
    monkeypatch.setattr(PK, "proposition_key", lambda text: f"k:{text}", raising=True)
    problems = _criterion_one_problems(tmp_path / "always-different")
    assert problems, "把 proposition_key 打桩成恒不等之后 ① 仍然全绿 ⇒ 那组断言没有对象"
    assert any("条命题行" in p or "第 2 份" in p for p in problems), problems
    assert len(_rows(Store(tmp_path / "always-different" / "ws"))) == 2, (
        "恒不等之后应当退回改前的形态：两条命题行")

    # 恒等 = 判据恒真（一条无关命题也会被并进去）。
    monkeypatch.setattr(PK, "proposition_key", lambda text: "same", raising=True)
    vacuous = _unrelated_merge_problems(tmp_path / "always-same")
    assert vacuous, "把 proposition_key 打桩成恒等之后，无关命题没有被并进去 ⇒ 判据没有对象"
    assert any("被并进去" in p for p in vacuous), vacuous


def test_reverting_one_judge_turns_its_criterion_red(
        tmp_path: pathlib.Path, monkeypatch) -> None:
    """⑤ 的同族：把"同种证明"那道判断打回改前（永远不同）⇒ ② 必红。

    改前没有这道判断：几乎相同的第二份证明照收成 `#p2`。打桩 `same_kind_proof` 回到
    "永远不同"就是那个行为，② 的那组读数必须当场变红（证明它钉的是这道判断本身）。
    """
    assert _same_kind_refusal_problems(tmp_path / "baseline") == [], (
        "夹具前提：注入之前 ② 应当是绿的")
    monkeypatch.setattr(
        PK, "same_kind_proof",
        lambda a, b, threshold=PK.PROOF_SAME_JACCARD: {
            "state": PK.STATE_DIFFERENT, "basis": "", "similarity": 0.0,
            "threshold": float(threshold), "what": "证明",
            "reason": "打桩：永远不同（改前的行为）"},
        raising=True)
    problems = _same_kind_refusal_problems(tmp_path / "no-same-kind-judge")
    assert problems, "去掉同种证明的判断之后 ② 仍然全绿 ⇒ 那组断言没有对象"
    assert any("照收" in p or "证明号" in p for p in problems), problems


# ============================================================ ⑥ 三态：判不了不并

def test_unjudgeable_texts_are_unknown_and_never_merged(tmp_path: pathlib.Path) -> None:
    """⑥ 文本过短 / 纯符号 ⇒ `unknown` 且不并（不猜）。

    三态纪律：`unknown` 既不是 `same` 也不是 `different`。两档判不了的 `reason` 不同
    （太短 / 全是符号）：处置不同 —— 前者可以补上下文，后者要补文字。
    """
    for left, right in (("x = 1", "y = 1"), ("显然。", "由定义。"),
                        ("≤ ≥ ≠", "≠ ∤ ∝"), ("∀x∈G", "∀y∈H")):
        got = PK.same_proposition(left, right)
        assert got["state"] == PK.STATE_UNKNOWN, (left, right, got)
        assert got["basis"] == "" and got["similarity"] == 0.0, got
        assert got["reason"], (left, right, got)
    assert "全是符号" in PK.same_proposition("≤ ≥ ≠", "≠ ∤ ∝")["reason"]
    assert "太短" in PK.same_proposition("x = 1", "y = 1")["reason"]
    assert PK.same_kind_proof("显然。", "由定义。")["state"] == PK.STATE_UNKNOWN

    # 登记路径：两条都判不了的短命题各落各的行（不许因为"判不了"就把它们并成一条）。
    st = _ws(tmp_path)
    b = _agent(st)
    one = b.register_statement(**_own("显然。"), proof_text="显然。")
    two = b.register_statement(**_own("由定义。"), proof_text="由定义。")
    assert one.get("ok") is True and two.get("ok") is True, (one, two)
    rows = _rows(st)
    assert len(rows) == 2, f"判不了的两条短命题被并成了 {len(rows)} 条"
    assert all(_proof_nos(r) == [1] for r in rows), [_proof_nos(r) for r in rows]
    assert [str(r.get("stmt_id")) for r in rows] == [S.format_id(0), S.format_id(1)], rows
    assert not any(r.get("_proposition_matches") for r in rows), "判不了的文本被留了'并进来'的痕"

    # 秘书那一层要能把"判不了"如实交回（改前没有这一格：`record_statement` 的返回值
    # 里没有任何"这一笔被判成什么"的读数，所以这条断言在改前是 NameError 式的红）。
    st2 = _ws(tmp_path / "reading")
    sec = Secretary("B", root=st2.root, store=st2)
    got = sec.record_statement({**_own("显然。"), "proof_text": "显然。"}, role="B")
    assert got.get("checked") is True and got.get("created") is True, got
    assert got.get("proposition_state") == PK.STATE_UNKNOWN, got.get("proposition_state")
    assert "判不了" in got.get("proposition_reason", ""), got.get("proposition_reason")
    assert got.get("merged") is False, got


# ============================================================ 阈值可注入

def test_the_thresholds_are_injectable(tmp_path: pathlib.Path) -> None:
    """阈值是构造参数（口径可调，判据不变）。

    把命题轴的阈值调到 0.99 ⇒ 那对 0.9118 的词形变体不再被并（两条命题行）；
    默认阈值下它并成一条（同一份读数里核正反两档）。
    """
    st = _ws(tmp_path / "default")
    b = _agent(st)
    assert b.register_statement(**_own(FULL_A), proof_text=PROOF_A).get("ok") is True
    assert b.register_statement(**_own(FULL_A_MORPH), proof_text=PROOF_C).get("ok") is True
    assert len(_rows(st)) == 1, "默认阈值下词形变体应当并成一条"

    st2 = _ws(tmp_path / "strict")
    b2 = _agent(st2)
    assert b2.register_statement(**_own(FULL_A), proof_text=PROOF_A).get("ok") is True
    strict = Secretary("B", root=st2.root, store=st2, same_proposition_jaccard=0.99)
    got = strict.record_statement({**_own(FULL_A_MORPH), "proof_text": PROOF_C}, role="B")
    assert got.get("checked") is True and got.get("created") is True, got
    assert len(_rows(st2)) == 2, "阈值调到 0.99 之后那一对不该再并（键本来就不同）"
