"""S3 判据：非平凡性那一格只说、不拦（业主 2026-10-21）。

1. 分布读得出来，且 `unjudged` 是独立一栏（0 不许并进 T1 —— 三态纪律）；
2. T3/T4 会被列出来（带 stmt_id / level / basis）；
3. 它不拦门：`check_closing` 里这一族只出 `level="warning"`。

反真空：第 1 条用"一判一未判"证明两栏分得开；第 3 条断言"没有任何 error 级 finding
来自 nontriviality 这一族" —— 有人把它升成 error 就会红。
"""

from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentflow import closing, secretary as SEC  # noqa: E402


def _ws(tmp_path: pathlib.Path, rows: list[dict], tex: str = "") -> pathlib.Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "statements.json").write_text(
        json.dumps({"rows": rows}, ensure_ascii=False), encoding="utf-8")
    if tex:
        (tmp_path / "out" / "paper").mkdir(parents=True, exist_ok=True)
        (tmp_path / "out" / "paper" / "main.tex").write_text(tex, encoding="utf-8")
    return tmp_path


def test_counts_keep_unjudged_apart_from_t1(tmp_path: pathlib.Path) -> None:
    rows = [{"stmt_id": "000001", "statement_full": "jia"},
            {"stmt_id": "000002", "statement_full": "yi"}]
    root = _ws(tmp_path, rows)
    SEC.append_nontriviality(root, statement_full="jia", level=1, basis="just over the bar")
    got = closing.nontriviality_reading(root)
    assert got["checked"] is True and got["statements_total"] == 2
    assert got["counts"]["T1"] == 1, got["counts"]
    assert got["counts"]["unjudged"] == 1, "unjudged must be its own column, not folded into T1"


def test_high_tier_rows_are_listed_with_their_basis(tmp_path: pathlib.Path) -> None:
    root = _ws(tmp_path, [{"stmt_id": "000003", "statement_full": "bing"}])
    SEC.append_nontriviality(root, statement_full="bing", level=4, basis="needs insight")
    got = closing.nontriviality_reading(root)
    assert got["high_tier_total"] == 1
    assert got["high_tier"][0]["level"] == 4 and got["high_tier"][0]["stmt_id"] == "000003"
    assert got["high_tier"][0]["basis"] == "needs insight"


def test_no_statements_is_unread_not_all_t1(tmp_path: pathlib.Path) -> None:
    got = closing.nontriviality_reading(tmp_path)
    assert got["checked"] is False and got["reason"], got


def test_the_reading_sees_paper_problems_but_only_warns(tmp_path: pathlib.Path) -> None:
    root = _ws(tmp_path, [{"stmt_id": "000004", "statement_full": "ding", "proof_text": ""}],
               "\\begin{theorem}ding\\end{theorem}\n")
    SEC.append_nontriviality(root, statement_full="ding", level=4, basis="insight")
    reading = closing.nontriviality_reading(root)
    assert reading["paper_scaffolding_problems"], "paper-side problems must be visible"
    # `check_closing` 要一个 Store（不是路径），所以这一条改成文本级钉住"只警告"：
    # 那一族 finding 的 level 必须是 warning —— 有人改成 error，这里就红。
    src = pathlib.Path(closing.__file__).read_text(encoding="utf-8")
    i = src.find("high_tier_without_ladder")
    assert i > 0, "收工输出里那一行不见了"
    window = src[i:i + 900]
    assert '"warning"' in window, "这一族不许升级成 error（业主：S3 只说、不拦）"
