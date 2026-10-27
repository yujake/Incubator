# -*- coding: utf-8 -*-
"""废案判据：已废口径的原话、以及被删掉的旧符号，都不许还有存活的落点。

## 这份判据为什么必须存在

今晚换过一批口径（三态取代"在飞 = 活跃"、销号闸改成"只可针对静默"、
`ALL` 取代 `#public`、力气档位 T0–T4 取代"非平凡度两问"、消息只到链尾……）。
换口径那一刻，没有任何既有判据会变红：

- 代码里旧符号的定义删掉之后，`import` 会报错，但注释 / docstring / 文档
  里的旧名字删不删，Python 一个字都不会说；
- 旧口径的原话（"在飞就是活跃"）留在注释里，lint 不管注释的语义；
- 于是下一个人读到那句话，会照着它做 —— 这正是这一本要防的事。

所以这里把四件事各做成一条两向判据（多一处红，少一处也红）：

1. `DEPRECATED_PHRASES`：每一族的旧口径原话，扫描范围内的命中文件集合
   必须与台账 `PHRASE_ALLOWED` 逐条相等；
2. `REMOVED_SYMBOLS`：今晚被删掉的旧符号（定义已不在树里），它们的字面提及
   也必须与台账 `SYMBOL_ALLOWED` 逐条相等；
3. `COMMENTED_CODE_ALLOWED`：被注释掉的代码块一律删（默认动作就是删）。
   全库今天一块都没有；真需要墓碑就压成一行 `# 已撤：<符号>（别再把它加回来）`，
   那一行是"这个符号撤过"，不是"这份实现留着"；
4. `DANGLING_ALLOWED`：注释 / docstring 里点名的模块符号必须真的还在
   （`` `模块.符号` ``，右半边是常量 / 私有名 / 类名）。名字已经不在树里的，
   那句话要么改指路、要么整句删。

第 3、4 条是"清废案"那一单加的（业主 2026-10-26：默认删，只有「判据依赖」
与「活陷阱」两种理由能留）。第 3 条的判据手段是 `ast.parse`：把连续几行注释
剥掉 `#` 之后喂给解释器 —— 中文散文里一个全角括号就解析不过去，而
`def _f():` / `return 1` 这类会老老实实解析成功，于是"像代码"不靠人看。

两向的红都是有用的：
- 实测有、台账没写 ⇒ 又长出一个旧口径的落点（删掉它，或写清为什么留）；
- 台账写了、实测没有 ⇒ 登记过期（放着不管，这张表会烂成"反正都得登记"）。

## 白名单的口径（写得越短越不会被借用）

一条登记只有三种理由站得住：

- 判据读它：某条判据必须把旧口径的原文写出来才能守它（"提示词里不许出现这句话"
  的负控、读旧数据的兼容面正控）。删掉那条判据就失去守的对象。
- 活陷阱：删掉之后，下一个人立刻会做错事（不是"读起来不顺"，
  是"照它做就是错的"）。
- 该删，已转持有方：这一处在热文件 / FC-27 禁改区里，本轮只读改不了。
  这条是欠账不是豁免 —— 持有方一改完，实测就不会再命中，台账那一行必须跟着删
  （删不掉就红，这正是两向比对要的效果）。

"只是考古"（读起来像在讲历史）不是理由 —— 那类一律删。审查留痕（FC-27 走查
记录那种）按"活陷阱"记，理由要写明"删掉丢的是什么原话"。

## 已知盲区（写清，否则这条判据会被读成比它实际更强）

- 只数字面。同一句话换个说法（"飞着"、"处于飞行态"）不进来；那一类靠
  评审，不靠这里。
- 只扫 `*.md` / `*.py`。UI 的 `.tsx` 与非文本产物不在这里。
- 台账按 `(族, 文件)` 记账，不按行号：行号在本仓库并行开发下实测几十分钟就漂了，
  而按行号记账会让每一次无关改动都要求重登记。
"""

from __future__ import annotations

import ast
import functools
import io
import pathlib
import re
import textwrap
import tokenize
import warnings

PROJ = pathlib.Path(__file__).resolve().parents[1]
_SKIP_PARTS = {"__pycache__", "node_modules", "golden", "static", "fixtures"}
_EXTRA_MD = ("AGENTS.md", "DEVELOPMENT.md", "DESIGN.md", "DESIGN-CONDUCTOR.md",
             "DESIGN-INTERACTIONS.md", "DESIGN-ROLES.md", "DESIGN-TOOLS.md")

#: 族 -> (正则, 换成了什么)。正则只咬旧口径的原话，不咬概念词：
#:
#: 咬概念词（例如单独一个"在飞"）会把 549 行正当用法一起判红 —— `docs/` 里的
#: "在飞"绝大多数是页面名（Live 页）与进程义（"此刻在飞的直接子"，
#: 与 `conductor.py` 的 `_in_flight_children_of` 一致）。那两类不是废案。
DEPRECATED_PHRASES: dict[str, tuple[str, str]] = {
    "F1_legacy_public_literal": (
        r"#public[^\n]{0,14}(?:与|和|=)[^\n]{0,14}ALL"
        r"|ALL[^\n]{0,14}(?:与|和)[^\n]{0,14}#public"
        r"|两套写法",
        "`ALL` 一个新写法（`#public` 只许出现在读旧数据那一处：`agent_loop._legacy_all`）"),
    "F2_flying_equals_active": (
        r"在飞\s*(?:就是|=|即|等同)\s*活跃|活跃\s*(?:就是|=|即)\s*在飞",
        "三态（`conductor.AGENT_STATES`）：活跃 = 非静默 = 在飞 + 待机"),
    "F3_old_retire_gate": (
        r"还在飞\s*/\s*名下还有未消|名下还有未消的板项\s*⇒",
        "销号闸（`conductor.retire_blocking`）：只可针对静默，"
        "拒信码 `target_not_silent` + `blocking`"),
    "F4_every_parent_must_know": (
        r"每一级父代理都要知道|每一级父[^\n]{0,6}都要知道"
        r"|各级父[^\n]{0,6}(?:知道|知情)|每级父[^\n]{0,6}(?:知道|知情)"
        r"|各级父[^\n]{0,6}各一条|各级父各开一条",
        "消息只到链尾（`conductor.CHAIN_DELIVERY_STATES` / `CHAIN_HOP_ROSTER`）"),
    "F5_two_nontrivial_questions": (
        r"非平凡度[^\n]{0,4}两问|那两问|非平凡性[^\n]{0,4}两问",
        "按证明花的力气分档 T0–T4（`secretary.nontriviality_from_effort`）"),
    "F6a_f_lands_statements": (
        r"F\s*自己落\s*statements|自己落\s*statements|F\s*直写\s*statements"
        r"|F\s*把[^\n。]{0,12}落成\s*`?statements",
        "`statements` 由 B 的秘书登记（`B.register_statement`）"),
    "F6c_sleep_then_poll": (
        r"(?<!不)睡[^\n]{0,3}轮询|(?<!不)轮询[^\n]{0,3}睡",
        "挂在时钟上（`clock.wait_any` / `clock.periodic_start`），不自己睡、不轮询"),
    "F7_second_type_decls": (
        r"两份\s*`?type_decls|两处\s*`?type_decls|type_decls[^\n]{0,6}两份",
        "`webui/state.type_decls` 是唯一实现（`readers` / `writes` 只转发）"),
    "F8_role_code_recipient": (
        r"to\s*=\s*`?<角色代号>`?|to=A[–-]H|按角色代号发|to=<单个角色字母>",
        "寻址按名册名 / 绝对编号（`agent_loop._decode_roster_recipient`）；"
        "角色代号只剩读侧的兼容档，读数 `addressed_by=role_fallback`"),
    "F9_force_new_in_a_refusal": (
        r"(?:请给|才走|请显式给)\s*`?force_new",
        "拒信指的必须是这条动作上真有的做法（`proofs=[...]` / `statement_full`）；"
        "`force_new` 只住在 `conjecture.register_conjecture` 那件工具上"),
}

#: 今晚被删掉、且没有同名重加的旧符号 —— 判据是"当前树里已经没有它的定义"。
#:
#: 候选由 `agentflow/temp/_find_replaced_symbols.py` 从 `git diff b83362c~1..HEAD -- agentflow/src`
#: 抽（定义行被删的 39 个），再逐个在当前树里核 `def` / `NAME =` / `class`：
#: `NO_LEAN_DROP_BLOCKS` / `NO_LEAN_DROP_LINE_MARKERS` / `NO_LEAN_REPLACEMENTS` 三个
#: 虽然从 `specs/l.py` 退役了，但 `specs/e.py` / `b.py` / `g.py` 里仍有活定义 ⇒ 不是废案，
#: 不许进这张表（进了就会把正当引用判成废案）。剩下 10 个定义确已不在树里。
REMOVED_SYMBOLS: tuple[str, ...] = (
    "_action_summary",
    "_all_computed",
    "_can_take",
    "_check_citations_needs_kind",
    "_concept_statement",
    "_escalate_missing_seam",
    "_load_document_text_cls",
    "_roster_landing_order",
    "_tool_summary",
    "_write_row",
)

#: 族 -> {文件（相对 `agentflow/`）: 为什么它还在}。空表本身也是有内容的读数。
PHRASE_ALLOWED: dict[str, dict[str, str]] = {
    "F1_legacy_public_literal": {
        "tests/test_agent_loop.py":
            "判据读它：`_recipient_for_channel('#public') == 'ALL'` 是读旧数据那一处的正控",
        "tests/test_agent_prompts.py":
            "判据读它：这一行判的是兼容面还在不在（两种写法都收）",
        "tests/test_shape_vs_value_errors.py":
            "判据读它：`ALL` 与 legacy 字面量归一是这一组守的对象",
    },
    "F3_old_retire_gate": {
        "src/agentflow/agent_prompts.py":
            "该删，已转持有方：提示词摘要冻结。其中一处是负控 `for stale in (...)`（判据读它），"
            "另两处是变更记录",
    },
    "F5_two_nontrivial_questions": {
        "src/agentflow/agent_loop.py": "该删，已转持有方（热文件，本轮只读）",
        "src/agentflow/secretary.py":
            "该删，已转持有方（当时正被另一条 lane 改，行号在动）",
        "src/agentflow/specs/b.py": "该删，已转持有方（FC-27 禁改区）",
        "tests/test_filing_tier_carries_the_proof.py":
            "判据读它：断言 note 里不再出现旧那两问（负控）",
        "tests/test_nontriviality_is_judged_by_effort.py":
            "判据读它：断言档位不归因到旧那两问（负控）",
        "tests/test_secretary.py":
            "判据读它：注释说明升档只补力气读数（旧那两问不作判据）",
    },
    "F6a_f_lands_statements": {
        "tests/test_f_hands_propositions_to_b.py":
            "判据读它：逐句扫「F 自己落 statements」三种改前写法（负控）",
    },
    "F4_every_parent_must_know": {
        "src/agentflow/agent_prompts.py":
            "该删，已转持有方：提示词摘要冻结。两处是变更记录，一处是负控 `for stale in (...)`（判据读它）",
        "src/agentflow/tools/conductor_tools.py": "该删，已转持有方（热文件，本轮只读）",
        "docs/ROLE-SPECS.md": "该删，已转持有方（docs 与 draft 另有一单在管）",
        "tests/test_guide_goes_down_the_secretary_chain.py":
            "活陷阱：业主 2026-10-26 那段原话的唯一全文引用（含取消那一句）。"
            "删掉就没有『这条链依据哪句话』的出处，下一个人会照着旧口径把各级父加回来",
        "tests/test_prompt_stability.py":
            "活陷阱：抬版本台账的 note 是逐版本的历史读数（p199 当时确实那么换过）。"
            "删词等于伪造那一版换了什么；现行口径由 p204 那一行覆盖",
        "tests/test_skill_staleness.py":
            "判据读它：`_STALE_MESSAGE` 里必须留着这句旧说法，否则那条判据没有守的对象",
    },
    "F8_role_code_recipient": {
        "src/agentflow/agent_loop.py": "该删，已转持有方（热文件，本轮只读）",
        "tests/test_addressing_is_by_roster_name_not_by_role.py":
            "判据读它：这个文件就是守这条口径的判据 —— 正则在注释里写出三种旧写法，"
            "判据 f 的断言描述与反真空样例也必须逐字带着旧写法",
        "tests/test_agent_prompts.py":
            "判据读它：`old = (...)` 是改前那一版提示词原文，负控拿它判『新提示词不等于旧的那一句』",
    },
    "F9_force_new_in_a_refusal": {
        "src/agentflow/secretary.py":
            "该删，已转持有方（secretary lane 持有该文件）：那一句是 force_new 的考古",
        "tests/test_duplicate_refusal_names_a_real_parameter.py":
            "判据读它：逐字引用旧拒信原话，断言新拒信里不再出现它（负控）",
    },
}

#: 旧符号 -> {文件: 为什么它还在}。
SYMBOL_ALLOWED: dict[str, dict[str, str]] = {
    "_action_summary": {
        "src/agentflow/specs/l.py": "该删，已转持有方（FC-27 禁改区的墓碑句）",
        "docs/FC27-PENDING-2026-10-21.md":
            "活陷阱：FC-27 走查记录。删掉即丢失「当时批准的是哪几行」的原话",
    },
    "_tool_summary": {
        "src/agentflow/specs/l.py": "该删，已转持有方（FC-27 禁改区的墓碑句）",
        "docs/FC27-PENDING-2026-10-21.md":
            "活陷阱：FC-27 走查记录。删掉即丢失「当时批准的是哪几行」的原话",
    },
}


def _scan_files() -> list[pathlib.Path]:
    """会被读者当成真的那些面（判据文件自己排除在外）。"""
    me = pathlib.Path(__file__).resolve()
    out: list[pathlib.Path] = []
    for sub in ("src", "tests", "scripts", "tools", "docs"):
        root = PROJ / sub
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix not in {".py", ".md"}:
                continue
            if _SKIP_PARTS & set(p.parts) or p.resolve() == me:
                continue
            out.append(p)
    for name in _EXTRA_MD:
        p = PROJ / name
        if p.is_file():
            out.append(p)
    return out


def _rel(p: pathlib.Path) -> str:
    """相对 `agentflow/` 的 posix 路径；树外的（反真空用的 `tmp_path`）给它的基名。"""
    try:
        return p.resolve().relative_to(PROJ).as_posix()
    except ValueError:
        return p.name


def measured_phrase_hits(files: list[pathlib.Path]) -> dict[str, set[str]]:
    """族 -> 命中文件集合（相对 `agentflow/`，posix）。"""
    got: dict[str, set[str]] = {name: set() for name in DEPRECATED_PHRASES}
    pats = {name: re.compile(pat) for name, (pat, _) in DEPRECATED_PHRASES.items()}
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for name, pat in pats.items():
            if pat.search(text):
                got[name].add(_rel(p))
    return got


def measured_symbol_hits(files: list[pathlib.Path]) -> dict[str, set[str]]:
    """旧符号 -> 命中文件集合。"""
    got: dict[str, set[str]] = {name: set() for name in REMOVED_SYMBOLS}
    pats = {n: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])")
            for n in REMOVED_SYMBOLS}
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        for name, pat in pats.items():
            if pat.search(text):
                got[name].add(_rel(p))
    return got


def diff_two_way(measured: dict[str, set[str]],
                 ledger: dict[str, dict[str, str]]) -> list[str]:
    """两向比对：多一处、少一处都各是一条。"""
    problems: list[str] = []
    for name in sorted(measured):
        allowed = set(ledger.get(name, {}))
        extra = sorted(measured[name] - allowed)
        stale = sorted(allowed - measured[name])
        if extra:
            problems.append(f"{name}：多出 {extra}（删掉，或登记为什么留）")
        if stale:
            problems.append(f"{name}：台账过期 {stale}（实测已经没有它了，删掉那一行）")
    return problems


# ============================================================ 第 1 条：旧口径原话

def test_no_deprecated_wording_survives_unregistered() -> None:
    """旧口径的原话，命中面必须与台账逐条相等。"""
    problems = diff_two_way(measured_phrase_hits(_scan_files()), PHRASE_ALLOWED)
    assert not problems, (
        "这些族命中了台账之外的落点（或台账过期了）：\n  " + "\n  ".join(problems)
        + "\n旧口径一律删；只有「判据读它」与「活陷阱」两种理由可以登记。")


# ============================================================ 第 2 条：旧符号

def test_no_removed_symbol_is_still_mentioned_unregistered() -> None:
    """被删掉的旧符号，字面提及必须与台账逐条相等。"""
    problems = diff_two_way(measured_symbol_hits(_scan_files()), SYMBOL_ALLOWED)
    assert not problems, (
        "这些已删的旧符号还有落点（或台账过期了）：\n  " + "\n  ".join(problems)
        + "\n定义已经不在树里 ⇒ 任何提及都是死的；仍被代码引用的那是活性缺陷，"
          "要么接上要么连代码一起改，不许只在注释里留着。")


# ============================================================ 反真空

def test_the_scanner_sees_the_old_wording() -> None:
    """反真空：同一套扫描，喂旧原话必须读到，喂新口径必须读不到。

    没有这一条，`measured_phrase_hits` 可以因为正则永远不匹配而恒返回空集 ——
    那时上面两条相等判据在"台账也是空表"的情况下仍然是绿的，而绿的原因是
    "什么都没扫到"，不是"没有废案"。这是最便宜的假绿。
    """
    old = "在飞就是活跃，所以 #public 与 ALL 是两套写法"
    new = "三态：在飞 / 待机 / 静默；活跃 = 非静默；`ALL` 一个写法"
    pats = {n: re.compile(p) for n, (p, _) in DEPRECATED_PHRASES.items()}
    hit_old = {n for n, pat in pats.items() if pat.search(old)}
    hit_new = {n for n, pat in pats.items() if pat.search(new)}
    assert hit_old == {"F1_legacy_public_literal", "F2_flying_equals_active"}, hit_old
    assert hit_new == set(), f"新口径被读成了废案：{hit_new}"


def test_the_symbol_scanner_sees_a_positive_reference(tmp_path: pathlib.Path) -> None:
    """反真空（第 2 条）：往一份文件里塞一句对已删旧符号的正面引用 ⇒ 必须读到它。

    用 `tmp_path` 而不是往 `src/` 真的写一个文件：判据自己往被扫的树里写东西，
    会让"跑判据"变成"改仓库"（`tests/test_demo_selftest_leaves_the_repo_clean.py`
    记的正是这类事故）。被量的那一步（`measured_symbol_hits`）真跑一遍。
    """
    probe = tmp_path / "probe.py"
    probe.write_text("# _roster_landing_order 那份排法是旧口径\nX = 1\n", encoding="utf-8")
    got = measured_symbol_hits([probe])
    assert "_roster_landing_order" in {n for n, files in got.items() if files}, got


def test_the_two_way_diff_reports_both_directions() -> None:
    """两向都要有牙：多一处、少一处各报一条，不许只报一个方向。"""
    problems = diff_two_way({"A": {"x.py", "y.py"}}, {"A": {"x.py": "判据读它"}})
    assert any("多出" in p for p in problems), problems
    issues = diff_two_way({"A": {"x.py"}}, {"A": {"x.py": "判据读它", "z.py": "过期"}})
    assert any("过期" in p for p in issues), issues
    assert diff_two_way({"A": {"x.py"}}, {"A": {"x.py": "理由"}}) == []

# ============================================================ 第 3 条：注释掉的代码块
#
# 口径（业主 2026-10-26）：默认动作是删。被注释掉的实现一行都不留 —— 它今天既不被
# 执行、也不被任何判据读，留在库里只有一个作用：让人以为"那是备用的做法"。
# 唯一允许的形态是一行墓碑：`# 已撤：<符号>（别再把它加回来）`，
# 它说的是"这个符号撤过"，不是"这份实现留着"。多行注释代码一律删。

#: 文件 -> 为什么这一段注释代码还留着。空表本身是读数（今天一块都没有）。
COMMENTED_CODE_ALLOWED: dict[str, str] = {}

#: 注释里长得像代码的行：有 Python 关键字，或有赋值 / 调用。
_CODE_HINT = re.compile(
    r"(?:^|\s)(?:def|class|return|if|elif|else|for|while|try|except|finally|with|import"
    r"|from|yield|raise|assert|lambda|global|nonlocal|del|pass|break|continue)\b"
    r"|\w\s*=\s*[^\s=]"
    r"|^\s*[\w.\[\]'\"]+\s*\(",
)


def _comment_lines(text: str) -> list[tuple[int, str]]:
    """整行注释（行首是 `#` 的那些）：`[(行号, 注释原文)]`。"""
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and lines[tok.start[0] - 1].strip().startswith("#"):
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []
    return out


def _parses_as_python(body: list[str]) -> bool:
    """这几行（已经剥掉 `#`）拼起来是不是一段合法的 Python。"""
    src = textwrap.dedent("\n".join(body)).strip()
    if not src:
        return False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ast.parse(src)
    except SyntaxError:
        return False
    return True


def commented_code_blocks(text: str) -> list[tuple[int, int, str]]:
    """注释掉的代码块：连续 >= 2 行整行注释，剥掉 `#` 之后能 `ast.parse` 成 Python。

    `ast.parse` 是这里的分界线：中文散文里一个全角括号、一个顿号就解析不过去，
    而 `def _x():` / `return 1` / `self.n = 0` 这类会老老实实解析成功。
    因此"像代码"不靠人看，靠解释器说了算。

    按"像代码的、且行行相邻的那几行"切片再判，不要求整段注释都像代码：
    真实形态是一个散文小标题下面挂着三行注释掉的实现（
    `# 旧实现留着备用` + `# def _f():` + `#     return 1`），整段拼起来解析不过，
    而实现那两行自己是合法的 —— 只判整段就会把这种最典型的残骸漏掉。
    """
    blocks: list[tuple[int, int, str]] = []
    comments = _comment_lines(text)
    i = 0
    while i < len(comments):
        j = i
        while j + 1 < len(comments) and comments[j + 1][0] == comments[j][0] + 1:
            j += 1
        run = comments[i:j + 1]
        if len(run) >= 2:
            for start in range(len(run)):
                group: list[str] = []
                for k in range(start, len(run)):
                    raw = run[k][1]
                    piece = raw.lstrip("#")
                    if piece.startswith(" "):
                        piece = piece[1:]
                    if not piece.strip():
                        continue
                    if not _CODE_HINT.search(piece):
                        break
                    group.append(piece)
                if len(group) >= 2 and _parses_as_python(group):
                    blocks.append((run[start][0], run[start][0] + len(group) - 1,
                                   group[0].strip()[:80]))
                    break
        i = j + 1
    return blocks


def measured_commented_code(files: list[pathlib.Path]) -> dict[str, list[str]]:
    """文件 -> 该文件里的注释代码块（`起-止: 首行`）。"""
    got: dict[str, list[str]] = {}
    for p in files:
        if p.suffix != ".py":
            continue
        found = commented_code_blocks(p.read_text(encoding="utf-8", errors="replace"))
        if found:
            got[_rel(p)] = [f"{a}-{b}: {head}" for a, b, head in found]
    return got


def test_no_commented_out_code_block_survives() -> None:
    """注释掉的代码块：命中面必须与台账逐条相等（今天两向都是空）。"""
    measured = measured_commented_code(_scan_files())
    extra = sorted(set(measured) - set(COMMENTED_CODE_ALLOWED))
    stale = sorted(set(COMMENTED_CODE_ALLOWED) - set(measured))
    problems = []
    if extra:
        problems.append("多出：" + "；".join(f"{f} -> {measured[f]}" for f in extra))
    if stale:
        problems.append(f"台账过期：{stale}（这几份文件里已经没有注释代码了）")
    assert not problems, (
        "注释掉的代码块只允许删；真需要墓碑就压成一行 `# 已撤：<符号>（别再把它加回来）`：\n  "
        + "\n  ".join(problems))


def test_the_commented_code_scanner_sees_a_dead_def() -> None:
    """反真空：塞一段注释掉的 `def _dead_probe()` ⇒ 扫描器必须读出来。

    没有这一条，上面那条在"扫描器恒定返回空"时也是绿的 —— 而绿的原因会是
    "什么都没扫到"，不是"库里没有注释代码"。
    """
    probe = (
        "# 旧实现留着备用\n"
        "# def _dead_probe():\n"
        "#     return 1\n"
        "X = 1\n"
    )
    found = commented_code_blocks(probe)
    assert found, "注释掉的 def 没被认出来"
    assert "def _dead_probe():" in found[0][2], found


def test_the_commented_code_scanner_ignores_prose(tmp_path: pathlib.Path) -> None:
    """负控：中文散文块不许被当成注释代码（否则这条判据会把整库判红）。"""
    prose = (
        "# 这一档问的是「找到的那个检查器会不会拒绝假命题」。\n"
        "# 一个只打印版本、永远 0 退出的回显器在这里必须是 unusable。\n"
        "# 理由：反控没失败就说明它没真编过。\n"
        "X = 1\n"
    )
    assert commented_code_blocks(prose) == []


# ============================================================ 第 4 条：docstring 指的符号得在
#
# 这一条只能做到"点名的符号存在"这一档，做法是：把 `` `模块.符号` `` 里的
# 模块名当文件干名（`src/agentflow//*.py` 的 stem），符号名当那一格里的定义
# （def / class / 赋值 / 注解 / import 进来的名字）。名字已经不在树里的，
# 那句话要么改指路、要么删 —— 它是死的，读者照着它去找只会找到空气。
#
# 只咬"像个符号"的右半边（全大写常量 / `_私有` / `ClassName`）：
# 小写右半边多是工具名（`conductor.summon`）、表名与字段名，那些不是模块符号。

#: 文件 -> 为什么那句话里的旧名字还留着。
DANGLING_ALLOWED: dict[str, str] = {
    "src/agentflow/autonomy.py":
        "活陷阱：`STOP_TOKEN` 撤掉之后，任何还引用它的代码会立刻 NameError —— "
        "这一句是「旁路没了、别再把它加回来」的唯一说明，删掉下一个人会重新加一个字面匹配",
    "src/agentflow/agent_prompts.py":
        "该删，已转持有方（提示词 lane 持有该文件）：两处指路名已经不在树里"
        "（一处现名 `_receipt_for`、一处现名 `FACULTY_LOCAL`）",
    "src/agentflow/secretary.py":
        "该删，已转持有方（secretary lane 持有该文件）：那一句的旧名已经不在树里，现名 `_statement_filing_tier`",
    "src/agentflow/specs/h.py": "该删，已转持有方（FC-27 禁改区）",
    "src/agentflow/tools/__init__.py": "该删，已转持有方（FC-27 禁改区）",
    "scripts/lint_rules.py": "该删，已转持有方（FC-27 禁改区）",
    "tests/test_conductor_stop_is_a_tool_not_a_word.py":
        "判据读它：这一条判「源码里没有对 STOP_TOKEN 的活引用」，名字必须写出来才有守的对象",
    "tests/test_review_acceptance.py":
        "判据读它：这一条判「`REPORT_SECTIONS` / `SPLIT_MARKERS` 已经不在 closing 里」，"
        "名字必须写出来才有守的对象",
}

#: 各种文件后缀：`` `conductor.py` `` 这种不是"模块.符号"。
_DOTTED_SUFFIXES = {
    "py", "md", "json", "jsonl", "tsx", "ts", "yaml", "yml", "txt", "sh", "toml",
    "cfg", "ini", "rst", "csv", "lean", "owl", "xml", "html", "css",
}
#: 右半边像个符号：常量 / 私有名 / 类名。
_SYMBOL_SHAPE = re.compile(r"^(?:[A-Z_][A-Z0-9_]*|_[a-z]\w*|[A-Z][A-Za-z0-9]*)$")
_DOTTED_REF = re.compile(r"`([a-z_]\w*)\.([A-Za-z_]\w*)`")


@functools.lru_cache(maxsize=1)
def _module_names() -> dict[str, set[str]]:
    """干名 -> 那一格里的名字（任何深度的定义 + import 进来的名字）。

    深度不限：这个仓库大量真身住在类里（`AgentLoop._park_gate` 这种），只收顶层的
    话，一条完全正确的引用会被判成"符号不存在"—— 那会把这条判据变成噪音源。
    """
    table: dict[str, set[str]] = {}
    root = PROJ / "src" / "agentflow"
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add(alias.asname or alias.name.split(".")[-1])
        table.setdefault(p.stem, set()).update(names)
    return table


def _docstring_lines(text: str) -> list[tuple[int, str]]:
    """docstring 的每一行：`[(行号, 文本)]`（行号按它在文件里的位置给）。"""
    out: list[tuple[int, str]] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            tree = ast.parse(text)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None) or []
        if not (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            continue
        first = body[0].lineno
        for offset, line in enumerate(body[0].value.value.splitlines()):
            out.append((first + offset, line))
    return out


def measured_dangling_refs(files: list[pathlib.Path],
                           modules: dict[str, set[str]] | None = None) -> dict[str, list[str]]:
    """文件 -> 点名了一个不存在的模块符号的那些行。"""
    table = _module_names() if modules is None else modules
    got: dict[str, list[str]] = {}
    for p in files:
        if p.suffix != ".py":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        faces = [(no, raw) for no, raw in _comment_lines(text)]
        faces.extend(_docstring_lines(text))
        for lineno, line in faces:
            for match in _DOTTED_REF.finditer(line):
                stem, name = match.group(1), match.group(2)
                if stem not in table or name in _DOTTED_SUFFIXES:
                    continue
                if not _SYMBOL_SHAPE.match(name):
                    continue
                if name not in table[stem]:
                    got.setdefault(_rel(p), []).append(f"{lineno}: {stem}.{name}")
    return got


def test_every_symbol_a_comment_points_at_still_exists() -> None:
    """docstring / 注释里点名的模块符号必须还在树里；不在的删掉或改指路。"""
    measured = measured_dangling_refs(_scan_files())
    extra = sorted(set(measured) - set(DANGLING_ALLOWED))
    stale = sorted(set(DANGLING_ALLOWED) - set(measured))
    problems = []
    if extra:
        problems.append("多出：" + "；".join(f"{f} -> {measured[f]}" for f in extra))
    if stale:
        problems.append(f"台账过期：{stale}")
    assert not problems, (
        "这些句子点名了一个已经不存在的符号（名字要么改指路、要么整句删）：\n  "
        + "\n  ".join(problems))


def test_the_dangling_scanner_sees_a_removed_symbol(tmp_path: pathlib.Path) -> None:
    """反真空：点名一个不存在的符号 ⇒ 必须读到；点名一个存在的 ⇒ 不许读到。"""
    modules = {"schema": {"SCHEMA_VERSION"}}
    bad = tmp_path / "bad.py"
    bad.write_text("# 词表见 `schema.KINDS` 那一格\nX = 1\n", encoding="utf-8")
    good = tmp_path / "good.py"
    good.write_text('"""版本号在 `schema.SCHEMA_VERSION` 里。"""\nX = 1\n', encoding="utf-8")
    got = measured_dangling_refs([bad], modules)
    assert any("schema.KINDS" in hit for hits in got.values() for hit in hits), got
    assert measured_dangling_refs([good], modules) == {}
