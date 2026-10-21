"""S2 判据：论文里的证明不许失踪（业主 2026-10-21 口径）。

## 三条口径（`draft/138` §5）

1. 所有定理的完整证明都要可查，B 侧都要有收录；
2. 产出丰盛时按档压缩：T1 可压缩、T2 把繁复工作移附录（正文留框架）——
   压缩可以，失踪不行：压了/移了，正文必须给指针；
3. T3/T4 不许整段移出正文（框架与动机必须留正文，只许技术细节进附录）。

## 这一条不判什么（都是业主否掉的）

- 不判篇幅（"T4 占 8%" 那版已否）；
- 不数"显然/易得"的出现次数（计数会逼出废话）。

## 判据

① 正文每条定理都能在台账里找到行，且那行"完整证明可查"（自有 `proof_text` 非空；
   引用 `source_lit_id` + 页码 + 逐字核验）；
② 台账里没有这条定理 ⇒ 红（"正文有、台账无"正是"证明失踪"的形态）；
③ 档位 T3/T4 且正文只剩一段指针（<400 字符且指附录）⇒ 红；
④ 反真空：T1/T2 用指针压缩 ⇒ 必须绿（防误伤——这是"压缩可以"那一半的机器证据）。
"""

from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import closing, secretary as SEC  # noqa: E402


def _workspace(tmp_path: pathlib.Path, tex: str, rows: list[dict]) -> pathlib.Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "out" / "paper").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "statements.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "out" / "paper" / "main.tex").write_text(tex, encoding="utf-8")
    return tmp_path


_OWN_PROOF = {"stmt_id": "000001", "statement_text": "自由群因子是 II_1 型因子",
              "statement_full": "自由群因子是 II_1 型因子", "proof_text": "由正则表示的迹性质直接得到。"}
_CITED = {"stmt_id": "000002", "statement_text": "自由熵维数不变",
          "statement_full": "自由熵维数不变", "proof_text": "",
          "source_lit_id": "lit-0007", "page_range": "12-14", "quote_verified": True}


def test_a_paper_with_its_proofs_on_the_ledger_passes(tmp_path: pathlib.Path) -> None:
    tex = "\\begin{theorem}自由群因子是 II_1 型因子\\end{theorem}\n"
    root = _workspace(tmp_path, tex, [_OWN_PROOF, _CITED])
    assert closing.paper_proof_scaffolding_problems(root) == []


def test_a_theorem_missing_from_the_ledger_is_red(tmp_path: pathlib.Path) -> None:
    """反真空：正文有定理、台账没有对应行 ⇒ 必须红（"证明失踪"）。"""
    tex = "\\begin{theorem}一个台账里没有的断言\\end{theorem}\n"
    root = _workspace(tmp_path, tex, [_OWN_PROOF])
    problems = closing.paper_proof_scaffolding_problems(root)
    assert problems and "没有对应行" in problems[0], problems


def test_a_cited_result_without_page_or_quote_is_red(tmp_path: pathlib.Path) -> None:
    """引用型断言缺页码/逐字核验 ⇒ 红（我们收录不了别人的全文，但必须指得到）。"""
    cited = {**_CITED, "page_range": ""}
    tex = "\\begin{theorem}自由熵维数不变\\end{theorem}\n"
    root = _workspace(tmp_path, tex, [_OWN_PROOF, cited])
    problems = closing.paper_proof_scaffolding_problems(root)
    assert problems and "页码" in problems[0], problems


def test_a_low_tier_proof_may_be_compressed_with_a_pointer(tmp_path: pathlib.Path) -> None:
    """④ 反真空（必须绿）：T1/T2 的证明被压缩、正文只留指针 ⇒ 不许红。"""
    tex = ("\\begin{theorem}自由群因子是 II_1 型因子\\end{theorem}\n"
           "标准论证，见附录 A.2。\n")
    root = _workspace(tmp_path, tex, [_OWN_PROOF, _CITED])
    SEC.append_nontriviality(root, statement_full="自由群因子是 II_1 型因子", level=2, basis="体量大")
    assert closing.paper_proof_scaffolding_problems(root) == []


def test_a_high_tier_framework_moved_to_the_appendix_is_red(tmp_path: pathlib.Path) -> None:
    """③ T3/T4 只剩一段指针（<400 字符）⇒ 红：框架与动机必须留在正文。"""
    tex = ("\\begin{theorem}自由群因子是 II_1 型因子\\end{theorem}\n"
           "见附录 A.2。\n")
    root = _workspace(tmp_path, tex, [_OWN_PROOF, _CITED])
    SEC.append_nontriviality(root, statement_full="自由群因子是 II_1 型因子", level=4, basis="洞察")
    problems = closing.paper_proof_scaffolding_problems(root)
    assert problems and "整段移进附录" in problems[0], problems


def test_no_paper_means_not_applicable_not_pass(tmp_path: pathlib.Path) -> None:
    """没有论文 ⇒ 这一族不适用（空清单），但调用方要靠 reading 区分"没有稿"。"""
    (tmp_path / "data").mkdir(parents=True)
    assert closing.paper_proof_scaffolding_problems(tmp_path) == []
    assert not (tmp_path / "out" / "paper" / "main.tex").exists()
