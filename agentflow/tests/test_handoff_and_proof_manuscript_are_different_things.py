# -*- coding: utf-8 -*-
"""判据：交接手稿（handoff）与证明稿（proof manuscript）是两个东西，名字不许混。

## 裁定（业主 2026-11-04，逐字）

> `manuscripts/handoffs.jsonl` 那一路 ⇒ 对外名字改成「交接手稿（handoff）」，
> 凡叫 `manuscript` 的地方，说明文字一律写"交接单"，与"证明稿（proof manuscript）"区分；
> `proof_manuscript` 保持原名（它是稿的路径）。
> 加一条判据：两个名字不许在同一句里混用（扫 `agent_skills.py` / `specs/*.py` /
> `agent_prompts.py` 的模型可见面：出现 `manuscripts.read` 的段落里不许出现
> `proof_manuscript`，反之亦然）。

来路是草案 `temp/probe_handoff_vs_proof_naming.py`（当前读数：模型可见面 4860 段、
混用 0 段、交接族 6 段、证明族 32 段）。本文件把它的 a/b/c 三档落成正式判据，
并把草案里"咨询·不判红"的那一格收紧成 d：六处首提必须点族名
（`temp/NAMING-HANDOFF-VS-PROOF.patch` 改的就是这六处；改前 6/6 缺词）。

## 四档（+ 一格自测）

| # | 判据 | 造什么 | 期望 |
|---|---|---|---|
| a | 同一段里既有 `manuscripts.` 又有 `proof_manuscript` | 真身 | 0 段；有则红并点名 `file:line` |
| b | 两个名字分开写 | 合成段落 | 绿（不误报） |
| c | 样本不足（任一族 < 3 段） | 空表 / 一族独有 | 2 = 没查成（不是绿） |
| d | 六处首提各点自己的族名 | 真身 | 改前 6/6 红 → 改后 6/6 绿 |
| e | 自测：扫描器对合成混用段落必须判红、对分开段落不许误报 | 合成段落 | 否则 2 |

退出码（直接跑本文件时）：0 = 分得开；1 = 查过了、有缺陷（混用或首提缺词）；
2 = 没查成（样本不足 / 自测不过 / 源码读不动）。

为什么"样本不足"必须是 2 而不是 0：扫描器读不到模型可见面时，"0 段混用"与
"没读到东西"读数完全同形 —— 把后者读成"分得开"就是本项目反复踩的折叠。
"""
from __future__ import annotations

import ast
import pathlib
import re

PROJECT = pathlib.Path(__file__).resolve().parents[1]
SOURCES = (
    PROJECT / "src/agentflow/agent_skills.py",
    PROJECT / "src/agentflow/agent_prompts.py",
    *sorted((PROJECT / "src/agentflow/specs").glob("*.py")),
)

HANDOFF_TOKEN = "manuscripts."
PROOF_TOKEN = "proof_manuscript"
HANDOFF_WORDS = ("交接手稿", "交接单", "handoff")
PROOF_WORDS = ("证明稿", "证明手稿", "proof manuscript")

#: 反真空：少于这个段数就判"没查成"（数不是一个规格，是"扫描器确实读到了"的下限）。
MIN_PER_FAMILY = 3

#: 六处首提：(族, 落点说明, 文件, 锚点, 该段必须出现的族名)。
#: 锚点取改前改后都在的那一小句 —— 判据守的是"这一段"，不是"这一行号"（行号会漂）。
FIRST_MENTIONS = (
    ("交接", "agent_skills 的「原文这一层」（`manuscripts.read` 只有 id）",
     "src/agentflow/agent_skills.py", "按编号读全文", HANDOFF_WORDS),
    ("交接", "HANDOFF_PROTOCOL 的开头（协议第一句）",
     "src/agentflow/agent_prompts.py", "交接工作前的标准动作", ("handoff",)),
    ("交接", "M 的交接段（`handoff` 形状那份手稿）",
     "src/agentflow/specs/m.py", "交接工作前先写一份", ("交接手稿",)),
    ("证明", "B 的注册动作（`proof_manuscript` 是证明正文的载体）",
     "src/agentflow/specs/b.py", "是证明正文的载体", PROOF_WORDS),
    ("证明", "V 的核验动作（在册命题必须带 `proof_manuscript`）",
     "src/agentflow/specs/v.py", "在册命题必须带", ("证明稿",)),
    ("证明", "F 的派审段（由你派 V 审这一份稿）",
     "src/agentflow/specs/f.py", "由你派 V 审这一份", ("证明稿",)),
)

#: 自测：a 混用必须被抓住；b 分开写不许误报。判据自己的红/绿能力由它证明。
_SELF_TEST = (
    ("mixed", "用 `manuscripts.read` 读全文，再把 `proof_manuscript` 交给 V", True),
    ("handoff", "用 `manuscripts.read` 读这一份交接手稿（handoff）", False),
    ("proof", "把证明稿（`proof_manuscript`）交给 V", False),
)


def _rel(path: pathlib.Path) -> str:
    return str(path.relative_to(PROJECT)).replace("\\", "/")


def paragraphs() -> list[tuple[str, int, str]]:
    """模型可见面里的段落 ⇒ `[(相对路径, 行号, 段落原文)]`（解码后的字符串内容）。

    按空行切段落是在解码后的字符串值上切，不是源码行 —— 提示词/工具声明是
    隐式拼接与三引号，源码行切不出"一句话"。
    """
    rows: list[tuple[str, int, str]] = []
    for path in SOURCES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # 读不动 ⇒ 没查成，不许当成"没有混用"
            raise AssertionError(f"{_rel(path)}: 解析失败（{exc}）⇒ 没查成") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for para in re.split(r"\n\s*\n", node.value):
                    if para.strip():
                        rows.append((_rel(path), int(node.lineno), para))
    return sorted(rows, key=lambda r: (r[0], r[1]))


def scan(rows: list[tuple[str, int, str]]) -> list[dict]:
    """同一段里两个名字都出现 ⇒ 混用。返回 `[{file, line, text}]`。"""
    mixed: list[dict] = []
    for rel, line, para in rows:
        if HANDOFF_TOKEN in para and PROOF_TOKEN in para:
            mixed.append({"file": rel, "line": line, "text": " ".join(para.split())[:240]})
    return mixed


def counts(rows: list[tuple[str, int, str]]) -> tuple[int, int]:
    """`(交接族段数, 证明族段数)`。"""
    return (sum(1 for _f, _l, p in rows if HANDOFF_TOKEN in p),
            sum(1 for _f, _l, p in rows if PROOF_TOKEN in p))


def verdict(rows: list[tuple[str, int, str]]) -> tuple[int, list[dict], int, int]:
    """三态：`0` 分得开 / `1` 有混用 / `2` 没查成。样本不足先于混用判。"""
    mixed = scan(rows)
    handoff_n, proof_n = counts(rows)
    if handoff_n < MIN_PER_FAMILY or proof_n < MIN_PER_FAMILY:
        return 2, mixed, handoff_n, proof_n
    return (1 if mixed else 0), mixed, handoff_n, proof_n


def _fmt(one: dict) -> str:
    return f"{one['file']}:{one['line']}  {one['text']}"


def first_mention_problems(rows: list[tuple[str, int, str]]) -> list[str]:
    """六处首提各点自己的族名；锚点漂了就直说找不到落点（那是判据要修，不是通过）。"""
    problems: list[str] = []
    for family, site, rel, anchor, words in FIRST_MENTIONS:
        hits = [r for r in rows if r[0] == rel and anchor in r[2]]
        if len(hits) != 1:
            problems.append(f"{family}族首提找不到唯一落点：{rel} 里锚点 {anchor!r} "
                            f"命中 {len(hits)} 段（{site}）")
            continue
        found_rel, line, text = hits[0]
        if not any(w in text for w in words):
            problems.append(f"{family}族首提没点族名：{found_rel}:{line}（{site}）"
                            f"—— 这一段要出现 {' / '.join(words)}")
    return problems


# ============================================================ a 同段混用 ⇒ 红
def test_a_no_paragraph_mixes_the_two_names() -> None:
    """a：真身上 0 段混用；有则红，并逐段点名 `file:line`。"""
    mixed = scan(paragraphs())
    assert mixed == [], ("这几段把两个名字混在一起（同一段里既有 `manuscripts.` 又有 "
                         "`proof_manuscript`）：\n  - " + "\n  - ".join(_fmt(m) for m in mixed))


# ============================================================ b 分开写 ⇒ 绿
def test_b_paragraphs_that_keep_the_two_apart_are_green() -> None:
    """b：两个名字各说各的 ⇒ 不误报（用合成段落，不依赖真身恰好干净）。"""
    rows = [
        ("selftest/handoff.md", 7, "用 `manuscripts.read` 读这一份交接手稿（handoff）"),
        ("selftest/proof.md", 9, "把证明稿（`proof_manuscript`）交给 V"),
    ] * MIN_PER_FAMILY
    code, mixed, handoff_n, proof_n = verdict(rows)
    assert (handoff_n, proof_n) == (MIN_PER_FAMILY, MIN_PER_FAMILY), (handoff_n, proof_n)
    assert mixed == [], [ _fmt(m) for m in mixed]
    assert code == 0, f"分开写的段落被判成 {code}"


# ============================================================ c 样本不足 ⇒ 2
def test_c_an_insufficient_sample_is_exit_2_not_green() -> None:
    """c：任一族 < 3 段 ⇒ `2`（没查成），绝不许读成"分得开"。"""
    cases = {
        "空表": [],
        "只有交接族": [("selftest/a.md", 1, "`manuscripts.read` 读交接手稿")],
        "只有证明族": [("selftest/b.md", 1, "`proof_manuscript` 是证明稿")],
    }
    for why, rows in cases.items():
        code, _mixed, handoff_n, proof_n = verdict(rows)
        assert code == 2, (f"{why}：只扫到交接族 {handoff_n} 段 / 证明族 {proof_n} 段，"
                           f"判成 {code} ⇒ 「没查成」被折成了「分得开」")
    # 正控：真身样本够（否则 a 那一条的绿是真空的）。
    code, _mixed, handoff_n, proof_n = verdict(paragraphs())
    assert handoff_n >= MIN_PER_FAMILY and proof_n >= MIN_PER_FAMILY, (handoff_n, proof_n)
    assert code in (0, 1), code


# ============================================================ d 六处首提
def test_d_the_six_first_mentions_name_their_family() -> None:
    """d：六处首提各点族名 —— 改前这一条 6/6 红，应用 patch 后 6/6 绿。"""
    problems = first_mention_problems(paragraphs())
    assert problems == [], "首提没有把两个名字分开：\n  - " + "\n  - ".join(problems)


# ============================================================ e 自测（有牙）
def test_e_the_scanner_catches_a_mixed_paragraph_and_names_where() -> None:
    """e：扫描器真的会红，且红的时候说得出 `file:line` —— 否则 a 的绿是真空的。"""
    for name, text, want in _SELF_TEST:
        got = scan([("selftest/synthetic.md", 12, text)])
        assert bool(got) is want, f"自测 {name!r}：期望混用={want}，实得 {bool(got)} ⇒ 扫描器坏了"
    caught = scan([("selftest/synthetic.md", 12, _SELF_TEST[0][1])])
    assert "selftest/synthetic.md:12" in _fmt(caught[0]), _fmt(caught[0])


def main() -> int:
    for name, text, want in _SELF_TEST:
        got = scan([("selftest", 0, text)])
        if bool(got) is not want:
            print(f"[没查成] 自测 {name!r} 期望混用={want}，实得 {bool(got)} ⇒ 扫描器坏了")
            return 2
    rows = paragraphs()
    code, mixed, handoff_n, proof_n = verdict(rows)
    print(f"[读数] 模型可见面段落 {len(rows)} 段；交接族 {handoff_n} 段、证明族 {proof_n} 段")
    if code == 2:
        print(f"[没查成] 只扫到交接族 {handoff_n} 段 / 证明族 {proof_n} 段"
              f"（各要 ≥{MIN_PER_FAMILY}）")
        return 2
    if mixed:
        print(f"[红] {len(mixed)} 段把两个名字混在一起：")
        for one in mixed:
            print("  - " + _fmt(one))
        return 1
    problems = first_mention_problems(rows)
    if problems:
        print(f"[红] 六处首提里 {len(problems)} 处没点族名：")
        for problem in problems:
            print("  - " + problem)
        return 1
    print("[绿] 两个名字分得开：0 段混用，六处首提都点了族名")
    return 0


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(main())
