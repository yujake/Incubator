"""在**不改包目录**的前提下先验证"覆盖率优先"的打分改法（离线原型）。

现状（`locallib.excerpt_for`）：`score = Σ weight[t]`，`weight[t] = 1/df(t)`。
后果：命中**一个稀有词**（weight 大）的页，压过命中**三个常见词**的页。
实测代价：题目 `cosets and quotient groups` 下，`univ-algebra` 选中的页只命中
`cosets` 一个词（该页 unrelated 的机率就高），而书里明明有同时讲 quotient 与 groups 的页。

本原型对比三种打分（都不改包，只在这里算）：
  A 现状：Σ weight
  B 覆盖率优先：命中**不同主题词个数**为主键，稀有度和为次键
  C 折中：Σ weight × (1 + 命中个数)

判据：8 个题目里"最强来源的摘录含 ≥2 个主题词"的题目数（越多越好），
并且**导航页必须仍然为 0**。

跑法：python temp\\_score_prototype.py
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, r"D:\Incubator\agentflow\src")
from agentflow.extract import extract_text  # noqa: E402
from agentflow.locallib import (  # noqa: E402
    _looks_like_navigation,
    _tokens,
    _window_on_tokens,
)

LIB = pathlib.Path(r"D:\Incubator\projects\project1\library")
BOOKS = {
    "bv cvxbook": "bv_cvxbook.pdf",
    "complex": "complex.pdf",
    "mml-book": "mml-book.pdf",
    "probability": "Math--Bertsekas_Tsitsiklis_Introduction_to_probability.pdf",
    "CTCL": "CTCL.pdf",
    "univ-algebra": "univ-algebra2012.pdf",
    "411notes": "411notes.pdf",
}
TOPICS = [
    "convex optimization duality and Lagrange multipliers",
    "the argument principle and the residue theorem",
    "singular value decomposition and low-rank approximation",
    "maximum likelihood estimation and unbiased estimators",
    "the Yoneda lemma and natural transformations",
    "cosets and quotient groups",
    "holomorphic functions and power series expansions",
    "Markov chains and limiting probabilities",
]
CACHE: dict[str, list[str]] = {}


def pages_of(name: str) -> list[str]:
    if name not in CACHE:
        doc = extract_text(str(LIB / BOOKS[name]))
        CACHE[name] = [str(p) for p in (doc.pages or [])]
    return CACHE[name]


def pick(pages: list[str], topic: str, mode: str, max_chars: int = 1200):
    toks = _tokens(topic)
    df: dict[str, int] = {t: 0 for t in set(toks)}
    for page in pages:
        low = page.lower()
        for t in df:
            if t in low:
                df[t] += 1
    weight = {t: 1.0 / max(1, n) for t, n in df.items()}
    best = (0.0, 0)
    for i, page in enumerate(pages):
        low = page.lower()
        present = {t for t in weight if t in low}
        if not present:
            continue
        if mode == "A":
            score = sum(weight[t] for t in present)
        elif mode == "B":
            score = len(present) * 1000.0 + sum(weight[t] for t in present)
        else:
            score = sum(weight[t] for t in present) * (1 + len(present))
        if _looks_like_navigation(page):
            score *= 0.15
        if score > best[0]:
            best = (score, i)
    page = pages[best[1]]
    _, exc = best[1] + 1, _window_on_tokens(page, toks, weight, max_chars)
    return best[1] + 1, exc, toks, page


for mode, label in (("A", "现状 Σweight"), ("B", "覆盖率优先"), ("C", "Σweight×(1+命中数)")):
    weak, nav = [], 0
    for topic in TOPICS:
        best_rare, best_name, best_page = 0, "", 0
        for name in BOOKS:
            page, exc, toks, raw = pick(pages_of(name), topic, mode)
            rare = sum(1 for t in set(toks) if t in exc.lower())
            if _looks_like_navigation(raw):
                nav += 1
            if rare > best_rare:
                best_rare, best_name, best_page = rare, name, page
        if best_rare < 2:
            weak.append(f"{topic[:34]}（最强 {best_name} 第 {best_page} 页，{best_rare} 词）")
    print(f"{label:24s} 弱题目 {len(weak)}/{len(TOPICS)}  导航页 {nav}")
    for w in weak:
        print(f"      - {w}")
