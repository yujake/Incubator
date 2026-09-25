"""把 `D:\\Incubator\\test\\main.pdf` 作为**真实文献**灌进框架（验收测试的输入层）。

## 这一步在整条流水线里的位置

```
人提交检索请求（r-NNNN, submitted_by="human", priority="high"）
      ↓
A 的角色：把 PDF 落到 library/ 并登记一行 literature
      ↓
B：抽取概念/关系 → concepts/relations（引文逐字回验 + 判重 + I6 冲突闸门）
      ↓
C（只读分析）→ D（研究）→ F/E/G/H
```

## 关于 `SeedExtractor`：它是什么，不是什么

**是**：抽取器接口（`llm.Extractor`：`extract(doc, lit_id, meta) -> (concepts, relations)`）
的一个**人工/规则辅助实现**。本环境没有可用的 LLM API key，所以"自动抽取"
这一步由**人读论文后写下的概念-关系清单**代替。

**不是**：绕过 B 的验证门的旁路。关键点在于：

- 概念与关系的**写入仍然全部走 `AgentB.run_once()`** —— 判重、代号分配、
  引文逐字回验、I6 写入期冲突检查，一个都不少；
- 每条关系的 `quote` 都是**论文 PDF 文本的逐字子串**，由**同一个**
  `quoteverify.check_quote` 核验（`--check` 模式会先跑一遍，任何一条定位不到就
  fail-closed 退出）；
- 因此"引文忠于原文"这件事是**被验证的**，而不是被声称的。

⚠️ 诚实的边界：**概念与关系的"选择"是人给的**，不是系统自己读出来的。
所以在验收报告里必须写明：本轮的自动化程度到"抽取器的**选择**由人提供，
但抽取结果的**正确性由框架验证**"为止。把它说成"系统自动读懂了论文"是过度声称。

## 为什么引文校验必须 fail-closed

这是全项目唯一能自动发现"编造引文"的地方。若 `--check` 允许"大部分引文能定位"
就放行，那么这条门在验收里就等于不存在 —— 而它恰恰是我们要演示的那条门。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
import importlib
import os

# ---------------------------------------------------------------- 目标实现切换
#
# 两个目标：
#   prototype —— `test/test1/src`，包名 `abflow`（第三阶段的原型）
#   formal    —— `agentflow/src`，包名 `agentflow`（正式版）
#
# 用环境变量选：`$env:AGENTFLOW_TARGET='formal'`
#
# 为什么用动态导入而不是 `if TARGET == ...: from abflow import X else: from agentflow import X`：
# 后者要求**两个包同时可导入**，而 prototype/formal 的 `schema.py` 版本并不相同
# （formal 多了 tasks/usage_ledger/eval_results 三张表）—— 同时导入会在 sys.modules 里
# 留下两个不同的 `schema` 模块，那种"同名不同版本共存"是最难查的一类错。
_AGENTFLOW_TARGET = os.environ.get("AGENTFLOW_TARGET", "prototype").strip().lower()
if _AGENTFLOW_TARGET not in ("prototype", "formal"):
    raise SystemExit(
        f"AGENTFLOW_TARGET 必须是 'prototype' 或 'formal'，收到 {_AGENTFLOW_TARGET!r}"
        "（拼错就**静默**跑在原型上，是那种最该炸的错）"
    )

if _AGENTFLOW_TARGET == "formal":
    _SRC = _HERE.parent.parent / "agentflow" / "src"
    PKG = "agentflow"
else:
    _SRC = _HERE.parent / "test1" / "src"
    PKG = "abflow"

if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _imp(mod: str):
    """按当前目标导入子模块。**包名只在这里出现一次。**"""
    return importlib.import_module(f"{PKG}.{mod}")


S = _imp("schema")
extract_text = _imp("extract").extract_text
ConceptDraft = _imp("llm").ConceptDraft
RelationDraft = _imp("llm").RelationDraft
make_page_range = _imp("llm").make_page_range
check_quote = _imp("quoteverify").check_quote
Store = _imp("store").Store

PAPER_PDF = _HERE.parent / "main.pdf"

# ---------------------------------------------------------------- 概念清单

#: ``(概念名, 定义, 别名)``。
#:
#: 挑选原则：**只看论文自己命名/定义的对象**，不发明论文没说的东西。
#: 因此这里没有"根系统""Coxeter 群"之类只是背景的条目 —— 它们出现在论文里，
#: 但不是这篇论文研究的**对象**。把背景知识当研究对象会让 C 的"最热概念"统计
#: 变成"论文里最常出现的词"，那是词频统计，不是知识图谱。
CONCEPTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("K(m)", "论文 Definition 1.1 定义的折叠图：顶点集 V_K = {x ∈ Z^m : Σ_i x_i ∈ {0,1}}，x 与 y 相邻当且仅当 y = x ± e_i。", ("the folded graph", "折叠图")),
    ("S̃_m", "论文 Definition 1.2 定义的腔图：仿射 Weyl 群 W_a(Ã_{m-1}) 关于生成元 {s_0, s_1, …, s_{m-1}} 的 Cayley 图。", ("the chamber graph", "chamber graph", "腔图")),
    ("Q^∨", "coroot lattice（余根格）：{x ∈ Z^m : Σ_i x_i = 0} ≅ Z^{m-1}。", ("coroot lattice", "余根格")),
    ("W_a(Ã_{m-1})", "仿射 Weyl 群：Q^∨ ⋊ S_m，作用为 x ↦ w(x) + λ，w ∈ S_m，λ ∈ Q^∨。", ("affine Weyl group", "W_a", "仿射 Weyl 群")),
    ("periodic graph", "周期图：局部有限连通简单图 X 连同在 V(X) 上自由作用、轨道有限的自由阿贝尔群 Γ ≤ Aut(X)；rank Γ 称为周期秩。", ("周期图",)),
    ("spectrum of a periodic graph", "周期图的谱：Floquet（Bloch）矩阵的谱在对偶环面上的并的闭包（式 (2)）。", ("Spec", "周期图的谱")),
    ("Floquet matrix", "Floquet 矩阵 A_χ：以 X/Γ 的类为指标，从 x 的类到 y 的类的元素是 χ(λ) 对实现该转移的全部平移 λ 之和。", ("Floquet 矩阵", "Bloch matrix")),
    ("cospectral", "同谱：两个图的谱（作为集合）相等。", ("同谱", "cospectrality")),
    ("girth", "围长：图中最短环的长度。", ("围长",)),
    ("vertex-transitive", "顶点传递：自同构群在顶点集上传递。", ("顶点传递",)),
    ("periodic rank", "周期秩：周期群 Γ 的秩（rank Γ）。", ("周期秩",)),
    ("spectral invariant", "谱不变量：只由谱（作为集合）决定的量，例如 λ_max、λ_min、'谱是区间'这一陈述。", ("谱不变量",)),
    ("density of states", "态密度：比谱（作为集合）更细的谱数据，Rem. 1.7 明确说它**也许**能区分这一对图，而本文的计算并未解决该问题。", ("态密度",)),
    ("companion book [6]", "论文引用的配套书（Companion book on quotient lattices, tori and periodic graphs, vol. 11, Theorem 6.5）。论文的 Spec S̃_m 结果**取自**该书，本文未重证。", ("companion book", "[6]")),
)

# ---------------------------------------------------------------- 关系清单

#: 每条：``(概念名组, 关系描述, 逐字引文, 期望页码)``。
#:
#: ⚠️ `quote` 必须是 PDF 提取文本的**逐字子串**。`--check` 会逐条核验；
#: 期望页码只是提示，真正的页由 `resolve_pages()` 找出来并写回 ——
#: 然后**再用 B 的引文门以该页码为声明窗口核验一次**，必须命中
#: `reason == "substring_match"`（若命中 `substring_match_outside_declared_range`，
#: 说明我们记的页码是错的，那是缺陷而不是可接受的结果）。
RELATIONS: tuple[tuple[tuple[str, ...], str, str, int], ...] = (
    (
        ("K(m)", "periodic graph"),
        "K(m) 是 Q^∨-周期的且周期秩为 m−1，且 Q^∨ 在 V_K 上恰有两个轨道（Σx_i = 0 与 Σx_i = 1）。",
        "K(m) is Q∨-periodic of rank m−1 with exactly two orbits on VK, namely {P",
        3,
    ),
    (
        ("S̃_m", "periodic graph"),
        "S̃_m 是 Q^∨-周期的且周期秩为 m−1，且 |W_a/Q^∨| = m!。",
        "and eSm is Q∨-periodic of rank m −1 with |Wa/Q∨| = m!. Both graphs are m-",
        3,
    ),
    (
        ("K(m)", "S̃_m", "vertex-transitive"),
        "两个图都是 m-正则、无限、局部有限、顶点传递的，并且都带一个秩 m−1 的自由阿贝尔群作用、商有限。",
        "Both graphs are m-regular, infinite, locally finite and vertex-transitive, and both carry a free",
        2,
    ),
    (
        ("K(m)", "spectrum of a periodic graph"),
        "Theorem 1.3：对 m ≥ 3，Spec K(m) = [−m, m]（周期图的谱定义为 Floquet 矩阵谱在对偶环面上的并的闭包）。",
        "Theorem 1.3 (spectrum of K(m)). Let m ≥3. Then Spec K(m) = [−m, m], where the spectrum",
        2,
    ),
    (
        ("S̃_m", "spectrum of a periodic graph", "companion book [6]"),
        "Spec S̃_m = [−m, m]（3 ≤ m ≤ 5）**取自配套书 [6, Thm. 6.5]**，本文未重证。",
        "the companion book that Spec eSm = [−m, m] for 3 ≤m ≤5.",
        1,
    ),
    (
        ("K(m)", "girth"),
        "Theorem 1.4：对 m ≥ 3，girth K(m) = 6。",
        "Theorem 1.4 (girths). Let m ≥3. Then girth K(m) = 6. For the chamber graph, girth eSm = 6",
        2,
    ),
    (
        ("S̃_m", "girth"),
        "Theorem 1.4：girth S̃_m = 6（m = 3），girth S̃_m = 4（一切 m ≥ 4）。",
        "when m = 3 and girth eSm = 4 for every m ≥4.",
        2,
    ),
    (
        ("K(m)", "S̃_m", "cospectral", "spectrum of a periodic graph"),
        "Theorem 1.5：对 m ∈ {4,5}，Spec K(m) = [−m, m] = Spec S̃_m，即两者同谱。",
        "Spec K(m) = [−m, m] = Spec eSm,",
        2,
    ),
    (
        ("K(m)", "S̃_m", "girth"),
        "Theorem 1.5：girth K(m) = 6 ≠ 4 = girth S̃_m，故 K(m) ≇ S̃_m —— **谱不决定图**。",
        "but girth K(m) = 6̸ = 4 = girth eSm. In particular K(m)̸ ∼= eSm: the spectrum does not determine",
        2,
    ),
    (
        ("spectrum of a periodic graph", "spectral invariant"),
        "Theorem 1.5 是关于**一个特定程序**的否定结果：任何只用谱（作为集合）的识别都会给 K(m) 与 S̃_m 相同的值，因而无法区分它们。",
        "read as a set, can decide the identity of a periodic graph within this family.",
        1,
    ),
    (
        ("spectral invariant", "density of states"),
        "Rem. 1.7：论文**不声称**没有谱不变量能区分这一对 —— 更细的数据（如谱测度或态密度）也许能，而 §5 的计算并未解决该问题。",
        "data, such as the spectral measure or the density of states, may well distinguish the pair, and the",
        2,
    ),
    (
        ("girth", "spectral invariant", "K(m)", "S̃_m"),
        "Rem. 1.7：本文中区分这一对的是**围长**，一个初等的度量不变量。",
        "girth, an elementary metric invariant.",
        2,
    ),
    (
        ("companion book [6]", "S̃_m", "spectrum of a periodic graph"),
        "Rem. 1.6：Spec S̃_m = [−m, m] 对该书而言只对 3 ≤ m ≤ 5 已证；对 m ≥ 6 只证明了包含关系 Spec S̃_m ⊆ [−m, m] 与两个端点 ±m，**等号是公开问题**。",
        "matching the known range; the case of eSm for m ≥6 is an open problem that would extend it. The",
        2,
    ),
    (
        ("S̃_m", "spectrum of a periodic graph"),
        "§6：m ≥ 6 的障碍是 S̃_m 的 cell 有 m! 个顶点，而 K(m) 的只有两个；对 K(m) 只需证 |S(χ)| 取到 0（有显式见证），对 S̃_m 则必须证明两个分支相交，而**没有显式见证可用**。",
        "one must show that two branches meet, with no explicit witness available.",
        8,
    ),
    (
        ("Floquet matrix", "K(m)"),
        "Lemma 3.1(iii)：K(m) 的 cell 是两个顶点、m 条平行边，电压为 0, e_1, …, e_{m−1}。",
        "are m parallel edges A–B with these voltages.",
        5,
    ),
    (
        ("Floquet matrix", "spectrum of a periodic graph", "K(m)"),
        "Lemma 3.1(iii)：Floquet 矩阵的非对角元是这 m 条边的 χ-权之和 S(χ) = χ(0) + Σ_{i<m} χ(e_i) = 1 + Σ_{i<m} z_i。",
        "i<m zi, and the conjugate in the opposite direction; so Aχ is as",
        5,
    ),
    (
        ("K(m)", "spectrum of a periodic graph"),
        "Theorem 1.3 的证明 (a)：S(χ) 是 m 个单位复数之和，故 |S(χ)| ≤ m（三角不等式）；0 也被取到（m = 2 取 z_1 = −1；m = 3 取两个本原三次单位根；m ≥ 4 取 z_1 = −1 与全部 (m−2) 次单位根）。",
        "|S| = 0 is attained: for m = 2 take z1 = −1; for m = 3 take z1 = e2πi/3, z2 = e4πi/3, the two",
        5,
    ),
    (
        ("K(m)", "spectrum of a periodic graph"),
        "Theorem 1.3 的证明 (a)：χ ↦ |S(χ)| 连续且 T^{m−1} 连通，故 |S(T^{m−1})| 是 [0,m] 的连通子集且含 0 与 m，从而等于 [0,m] —— **这是唯一用到环面拓扑的地方**。",
        "Finally χ 7→|S(χ)| is continuous and Tm−1 is connected, so |S(Tm−1)| is a connected subset of",
        5,
    ),
    (
        ("K(m)", "Floquet matrix"),
        "Rem. 3.5（陷阱）：把 2m 个有向步 ±e_i 各算一项会得到 S(1) = 2m−1 与 λ_max = 2m−1 —— **错的**；cell 里每个方向只有一条边，故 S(1) = m。m = 4 时错答案 7，而真正的度数是 4。",
        "term χ(±ei) to S(χ) gives S(1) = 2(m −1) + 1 = 2m −1 and λmax = 2m −1. That is also wrong:",
        6,
    ),
    (
        ("K(m)", "spectrum of a periodic graph"),
        "Rem. 3.3（陷阱）：|S| = 0 的见证是显式的，所以端点 0 **不必**用数值搜索 —— 粗网格会漏掉它（论文称每角 60 点的网格上 m = 4 的 min|S| 约为 0.04 而非 0）。",
        "for m = 4 is about 0.04 rather than 0).",
        6,
    ),
    (
        ("K(m)", "girth"),
        "§5：K(m) 的 girth 由盒子里的 BFS 得到 6（m = 3,4,5）。",
        "Girth (Theorem 1.4). K(m): BFS in a box gives girth 6 for m = 3, 4, 5. eSm: the affine",
        7,
    ),
    (
        ("S̃_m", "girth"),
        "§5：把仿射 Weyl 群实现为 {(w,λ)}、群律 (w,λ)(v,μ) = (wv, λ + w(μ))，从 Coxeter 表现构造半径 6 的球，在球内算得 girth 为 6（m = 3）、4（m = 4,5）。",
        "Weyl group is realised as {(w, λ)} with the group law (w, λ)(v, µ) = (wv, λ + w(µ)), the ball",
        7,
    ),
    (
        ("spectrum of a periodic graph", "K(m)"),
        "§5：数值校验**不作为证明** —— 论文明确写出 'No numerical output is used as a proof'。",
        "No numerical output is used as a proof: every statement is proved in the text.",
        7,
    ),
    (
        ("K(m)", "girth"),
        "Example 1.8：K(4) 中的一个 6-环，(0,0,0,0) → (0,0,0,1) → (−1,0,0,1) → (−1,0,1,1) → (−1,0,1,0) → (0,0,1,0) → 回到起点，差向量 e_4, −e_1, e_3, −e_4, e_1, −e_3。",
        "returning to (0, 0, 0, 0). The successive differences e4, −e1, e3, −e4, e1, −e3 are signed standard",
        2,
    ),
    (
        ("S̃_m", "girth"),
        "Example 1.8：S̃_4 中的一个 4-环是 1, s_1, s_1s_3, s_3 —— 在 Ã_3 的 Coxeter 圈里节点 1 与 3 不相邻，故 s_1 与 s_3 可交换、walk 闭合。",
        "A 4-cycle in eS4 is the square 1, s1, s1s3, s3: the nodes 1 and 3 are not adjacent in the Coxeter",
        3,
    ),
)

#: **负控引文**：每一对是 ``(名称, 被篡改的引文, 原引文)``。
#: 每一对必须：原引文定位成功、篡改引文定位失败。若篡改引文也"成功"，
#: 说明这条门是假的（例如它做的是相似度匹配而不是逐字匹配）。
NEGATIVE_CONTROL_QUOTES: tuple[tuple[str, str, str], ...] = (
    (
        "改一个词（the → a）",
        "a companion book that Spec eSm = [−m, m] for 3 ≤m ≤5.",
        "the companion book that Spec eSm = [−m, m] for 3 ≤m ≤5.",
    ),
    (
        "改一个数字（6 → 5）",
        "Theorem 1.4 (girths). Let m ≥3. Then girth K(m) = 5. For the chamber graph, girth eSm = 6",
        "Theorem 1.4 (girths). Let m ≥3. Then girth K(m) = 6. For the chamber graph, girth eSm = 6",
    ),
    (
        "把否定去掉（not determine → determine）",
        "but girth K(m) = 6̸ = 4 = girth eSm. In particular K(m)̸ ∼= eSm: the spectrum does determine",
        "but girth K(m) = 6̸ = 4 = girth eSm. In particular K(m)̸ ∼= eSm: the spectrum does not determine",
    ),
)


# ---------------------------------------------------------------- 抽取器


class SeedExtractor:
    """`llm.Extractor` 契约的人工清单实现。见模块 docstring 的边界说明。"""

    def __init__(self, pages: dict[str, int] | None = None) -> None:
        #: 概念名组 -> 该关系引文所在的真实页码（由 :func:`resolve_pages` 预先算好）。
        self.pages = pages or {}

    def extract(self, doc, lit_id: str, meta: dict) -> tuple[list[Any], list[Any]]:
        concepts = [
            ConceptDraft(name=name, definition=definition, aliases=list(aliases), source_lit_id=lit_id)
            for name, definition, aliases in CONCEPTS
        ]
        relations = []
        for names, description, quote, _hint in RELATIONS:
            page = self.pages.get(_rel_key(names, quote))
            if page is None:
                raise RuntimeError(
                    f"SeedExtractor 没有 {_rel_key(names, quote)!r} 的页码 —— "
                    "必须先跑 resolve_pages()。**不要猜页码**：猜出来的页码会让引文门退化成'全文搜索后就算过'"
                )
            relations.append(
                RelationDraft(
                    concept_names=list(names),
                    description=description,
                    quote=quote,
                    page_range=make_page_range(page, page, f"p. {page}"),
                )
            )
        return concepts, relations


def _rel_key(names: tuple[str, ...], quote: str) -> str:
    return "|".join(names) + "::" + quote[:40]


# ---------------------------------------------------------------- 引文定位与核验


def _load_doc(pdf_path: Path = PAPER_PDF):
    return extract_text(str(pdf_path))


def resolve_pages(doc=None, pdf_path: Path = PAPER_PDF) -> dict[str, int]:
    """找出每条关系引文**真实所在**的 PDF 页码（1-based）。

    为什么"找出来"而不是"信手写的提示"：页码写错会让引文门以
    `substring_match_outside_declared_range` 命中 —— 那说明我们记录的
    出处是错的。真正的做法是**先定位、再回验**，而不是先声明一个数再让它
    被 ±widen 兜住。
    """
    doc = doc or _load_doc(pdf_path)
    out: dict[str, int] = {}
    for names, _desc, quote, _hint in RELATIONS:
        chk = check_quote(doc, quote, S.PageRange(None, None, ""), allow_fulltext_fallback=True)
        if chk.verified is not True or chk.matched_page is None:
            raise AssertionError(
                f"引文定位失败：{_rel_key(names, quote)!r}\n  quote={quote!r}\n  reason={chk.reason}"
            )
        out[_rel_key(names, quote)] = int(chk.matched_page)
    return out


def check_quotes(pdf_path: Path = PAPER_PDF, *, verbose: bool = True) -> dict:
    """对全部引文做**逐字可达性**核验 + **负控**。

    返回 ``{"checked", "total", "verified", "failed", "unknown", "negative_controls": [...]}``。

    ⚠️ **三分档计数**（FC-10）：`failed`（定位不到）与 `unknown`（无文本层/空引文）
    必须分开报 —— 前者要改引文，后者要 OCR。合并成一个"通过率"数字，
    就再也看不出该做什么了。
    """
    doc = _load_doc(pdf_path)
    pages = resolve_pages(doc, pdf_path)

    verified = failed = unknown = 0
    details: list[dict] = []
    for names, _desc, quote, hint in RELATIONS:
        page = pages[_rel_key(names, quote)]
        chk = check_quote(doc, quote, S.PageRange(page, page, f"p. {page}"))
        if chk.verified is True:
            verified += 1
        elif chk.verified is False:
            failed += 1
        else:
            unknown += 1
        details.append(
            {
                "key": _rel_key(names, quote),
                "declared_page": page,
                "hint_page": hint,
                "verified": chk.verified,
                "matched_page": chk.matched_page,
                "reason": chk.reason,
                "window": chk.window,
            }
        )

    neg: list[dict] = []
    for label, tampered, original in NEGATIVE_CONTROL_QUOTES:
        # 负控的"原引文"可能并不在 RELATIONS 里，单独定位一次
        orig_chk = check_quote(doc, original, S.PageRange(None, None, ""), allow_fulltext_fallback=True)
        tam_chk = check_quote(
            doc, tampered,
            S.PageRange(orig_chk.matched_page, orig_chk.matched_page, "") if orig_chk.matched_page else None,
            widen=1,
        )
        neg.append(
            {
                "label": label,
                "original_verified": orig_chk.verified,
                "original_page": orig_chk.matched_page,
                "tampered_verified": tam_chk.verified,
                "tampered_reason": tam_chk.reason,
                "gate_works": orig_chk.verified is True and tam_chk.verified is False,
            }
        )

    result = {
        "checked": True,
        "total": len(RELATIONS),
        "verified": verified,
        "failed": failed,
        "unknown": unknown,
        "details": details,
        "negative_controls": neg,
        "gates_ok": all(x["gate_works"] for x in neg),
        "pdf_pages": len(getattr(doc, "pages", []) or []),
        "has_text_layer": bool(getattr(doc, "has_text_layer", False)),
    }
    if verbose:
        print(f"引文核验：共 {result['total']} 条 → verified={verified} failed={failed} unknown={unknown}")
        for d in details:
            flag = "OK " if d["verified"] is True else "!! "
            print(f"  {flag}p{d['declared_page']}(提示 p{d['hint_page']}) {d['reason']:38s} {d['key'][:70]}")
        print(f"负控：{len(neg)} 条")
        for n in neg:
            flag = "OK " if n["gate_works"] else "!! "
            print(
                f"  {flag}{n['label']}: 原文 verified={n['original_verified']} / "
                f"篡改 verified={n['tampered_verified']} ({n['tampered_reason']})"
            )
    if failed or unknown or not result["gates_ok"]:
        raise AssertionError(
            f"引文门失败：failed={failed} unknown={unknown} 负控未生效={[n['label'] for n in neg if not n['gate_works']]}"
        )
    return result


# ---------------------------------------------------------------- 灌库


def ingest_paper(
    store: Store,
    *,
    pdf_path: Path = PAPER_PDF,
    run_b: bool = True,
    extractor: Any = None,
) -> dict:
    """把论文灌进一个已初始化的 workspace。

    1. 拷贝 PDF 到 `library/`；
    2. 登记一条**人的**检索请求（`submitted_by="human"`, `priority="high"`, `done=True`,
       `outcome="ok"`）—— 因为这份文献不是 A 检索来的，而是人直接给的。
       把它伪装成 A 的搜索结果，会让"文献来源"这条追溯链说假话；
    3. 登记一行 `literature`，`source_request_ids` 指向那条请求（双向链成立）；
    4. 用 `AgentB` + `SeedExtractor` 走**真实的 B 流程**抽概念/关系。
    """
    store.init()
    doc = _load_doc(pdf_path)
    pages = resolve_pages(doc, pdf_path)

    dest_name = "main-yu-2026-cospectral-periodic-graphs.pdf"
    dest = store.library / dest_name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists():
        shutil.copy2(pdf_path, dest)

    AgentB = _imp("agent_b").AgentB
    _et = _imp("extract").extract_text
    I = _imp("interactions")

    with store.tx("search_requests", "literature", "counters", actor="human", note="ingest paper") as tx:
        # ⚠️ **ID 必须从分配器拿，不许写死。**
        #
        # 最初的实现把 `lit_id` 硬编码成 `"0000"`、`request_id` 硬编码成 `"r-0001"`，
        # 于是 `counters.json` 里的 `lit` 还是 0，而表里已经有 0000 ——
        # `verify` 会报 `counter_behind`，下一次真实分配还会**撞号**
        # （撞号的表现是按主键 upsert 静默覆盖，一声不响）。
        # 这是"手工造数据时图省事"的典型代价，而它只在**跑一次 verify** 时才暴露。
        lit_id = tx.alloc_id("lit")
        req_id = I.next_prefixed_id(tx.rows("search_requests"), "request_id", "r")
        title = "Cospectral periodic graphs: the spectrum does not determine the graph"
        tx.upsert(
            "search_requests",
            S.SearchRequest(
                request_id=req_id,
                timestamp=S.now_iso(),
                topic=title,
                mode="precise",
                content_description=(
                    "人直接提供的一篇未发表论文（PDF，8 页，有文本层）。"
                    "不是 A 检索来的 —— 这一点必须如实记录，否则'文献从哪来'这条链会说假话。"
                ),
                done=True,
                submitted_by="human",
                priority="high",
                outcome="ok",
                result_lit_ids=[lit_id],
                submit_note="验收测试输入：独立推导复现该论文的研究成果",
            ).to_dict(),
        )
        tx.upsert(
            "literature",
            S.Literature(
                lit_id=lit_id,
                title=title,
                type="P",
                summary=(
                    "未发表预印本（Tongji University, Jiaqi Yu, 2026-09-21）。证明 Spec K(m) = [−m,m]，"
                    "并引用配套书得到 Spec S̃_m = [−m,m]（3≤m≤5）；两图对 m=4,5 同谱但围长 6≠4，故不同构 ——"
                    "**谱不决定周期图**。m ≥ 6 的等号是论文自己的公开问题。"
                ),
                path=dest_name,
                processed=False,
                source_request_ids=[req_id],
                year=2026,
                authors=["Jiaqi Yu"],
                language="en",
                added_at=S.now_iso(),
                download={
                    "status": "ok",
                    "note": "人直接提供（不是网络下载）；内容类型经人工确认为 PDF",
                    "pages": len(getattr(doc, "pages", []) or []),
                    "has_text_layer": bool(getattr(doc, "has_text_layer", False)),
                },
            ).to_dict(),
        )

    out: dict = {
        "request_id": req_id,
        "lit_id": lit_id,
        "pdf_copied_to": dest_name,
        "quote_pages": pages,
        "b_result": None,
    }
    if run_b:
        b = AgentB(
            store,
            extractor=extractor or SeedExtractor(pages),
            extract_text=_et,
            config={"quote_widen_pages": 0, "allow_fulltext_quote_fallback": False},
        )
        res = b.run_once()
        out["b_result"] = res.to_dict() if hasattr(res, "to_dict") else res
    return out


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="把 main.pdf 灌进框架 / 核验引文门")
    ap.add_argument("--check", action="store_true", help="只核验引文逐字可达性 + 负控，不写任何东西")
    ap.add_argument("--root", default=str(_HERE / "workspace"), help="workspace 根目录")
    ap.add_argument("--json", default="", help="把结果写到该 JSON 路径")
    ap.add_argument("--pdf", default=str(PAPER_PDF))
    args = ap.parse_args(argv)

    if args.check:
        res = check_quotes(Path(args.pdf))
    else:
        st = Store(args.root)
        res = ingest_paper(st, pdf_path=Path(args.pdf))
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    if args.json:
        Path(args.json).write_text(json.dumps(res, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
