# -*- coding: utf-8 -*-
"""F-07：文档-代码一致性元判据 —— 文档里的计数必须与实现一致。

## 为什么要有这一条（`draft/44` 的 F-07）

"文档是人的接口，它说谎的代价与代码 bug 同级"。而这条线实测过四次同族漂移：

1. `DEVELOPMENT.md` 写着"动作总数 54 / 可召唤动作数 51"，而 `capabilities` 实测是
   58 —— 判据只盯 `docs/ROLE-SPECS.md` 的标题，没人盯这两格，于是它静默漂了；
2. `capabilities.py` 的注释写着"`H` 只能召唤 `G`"，而边表实测是 `['A','E','G']`
   （`H → A`/`H → E` 是 2026-09-30 由人批准加的）；
3. `capabilities.py` 的 docstring 写着"八条断言"（这条今天是一致的：8 项、标签 `[1..8]`）；
4. `docs/` 里两处把收工门写成"五条全过 ⇒ 可交付"，而 `closing.DEFAULT_CHECKS` 是 8 格。

## 判据的形状（三层，缺一层都会变成橡皮图章）

- 对拍：文档里的那个数 == 实现的现算读数（不是"看起来差不多"）；
- 反真空：每一格都要能读出数来（读不到就抛，不许"没找到就不判"）；
- FC-27 的漂移只登记、不代改：`capabilities.py` 在禁改区（人改或人逐行走查），
  所以那一条进 `KNOWN_DOC_DRIFT`，并且带"过期登记"检查 —— 人改完之后忘了把登记删掉
  ⇒ 这里红（一张只增不减的登记表会烂成噪音）。
"""
from __future__ import annotations

import ast
import io
import pathlib
import re
import tokenize

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    path = REPO / rel
    assert path.is_file(), f"文档不在盘上：{path}"
    return path.read_text(encoding="utf-8")


def _int_of_cn(text: str) -> int | None:
    """把 `五/六/七/八/九/十` 或阿拉伯数字读成整数（读不出返回 None）。"""
    table = {"五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    text = text.strip()
    if text in table:
        return table[text]
    return int(text) if text.isdigit() else None


#: `capabilities.py` 里那条注释主张的 `H` 出边（禁改区文件：改注释必须人做）。
H_EDGES_CLAIM_RE = re.compile(r"#: - `H` 只能召唤 `G`：")

#: 已知的、待人修的文档-代码漂移。每条都必须写明"为什么不自己改"（FC-27）。
#: 过期登记检查：人改完之后盘上不再漂 ⇒ 这条必须从表里删掉，否则这里红。
#:
#: 2026-10-06：原先唯一那条 `capabilities.H_edges`（注释写「`H` 只能召唤 `G`」而边表是
#: `['A','E','G']`）已由主控在所有者授权下改好 ⇒ 登记删掉、表清空。
#: 空表是好状态（该修的修完了），不是"判据失去了对象"——另外两半
#: （未登记而真漂 ⇒ 红；登记了却已修 ⇒ 红）仍然都在。
KNOWN_DOC_DRIFT: dict[str, str] = {}


def _count_of(text: str, label: str) -> int | None:
    """从 `「<label> **N**」` 那一格读出 N（读不到返回 None）。"""
    got = re.search(rf"{label} \*\*(\d+)\*\*", text)
    return int(got.group(1)) if got else None


#: `docs/` 里"收工门 N 条/N 格"的写法。四种形态，缺一种就漏一处（R7-⑯ 的第二轮扩面）。
#:
#: ① 紧接冒号：「收工门：N 格」—— 最初的一种；
#: ② 带括号 + 冒号：「收工门（<出处>）：N 条」—— 子命令 `help=` 与测试 docstring 用的形态。
#:    这一支刻意只认 五..十 / 数字：「那一条」这种量词会被 `[一二三四五六七八九十]` 打进来
#:    （实测假阳：`tests/test_review_chain_endorse.py` 的「收工门（§22）里最贵的那一条是 …」）；
#: ③ 括号里直接写数：「跑收工门（八格）」—— 后面没有冒号（`tools/conductor_tools.py`）；
#: ④ 所有格：「收工门（`draft/37` §16 P3 的 N 条）」—— 数被「的」隔开（`docs/ROLE-SPECS.md`）。
#:
#: ②③④ 都容忍 Markdown 强调符（`**收工门**（…）`、`收工门：**八格**`、`收工门（**八格**）`）：
#: 星号夹在词与词之间是同一种事实陈述的排版变体，判据看不见它才是漏
#: （`docs/ROLE-SPECS.md` 的工具表就是"强调符夹在词与括号之间"再加"所有格"那个形态）。
_GATE_HEAD = r"收工门\**\s*"
_GATE_COUNT_RE = re.compile(_GATE_HEAD + r"[：:]\s*\**\s*([一二三四五六七八九十]|\d+)\s*[条格]")
_GATE_COUNT_BRACKET_RE = re.compile(
    _GATE_HEAD + r"[（(][^\n。；]{0,30}?\**\s*([五六七八九十]|\d+)\s*[条格]")
_GATE_COUNT_PAREN_NUMBER_RE = re.compile(
    _GATE_HEAD + r"[（(]\s*\**\s*([五六七八九十]|\d+)\s*[条格]\s*\**\s*[）)]")
_GATE_COUNT_GENITIVE_RE = re.compile(
    _GATE_HEAD + r"[（(][^）)]*的\s*\**\s*([五六七八九十]|\d+)\s*[条格]")

_GATE_COUNT_RES = (_GATE_COUNT_RE, _GATE_COUNT_BRACKET_RE, _GATE_COUNT_PAREN_NUMBER_RE,
                   _GATE_COUNT_GENITIVE_RE)


def _gate_count_matches(line: str) -> list[tuple[str, str]]:
    """这一行里每一处"收工门 N 条/N 格"⇒ `(数字原文, 命中的整段)`。

    同一条陈述会被多条正则同时命中（`收工门（八格）` 同时落在 ②③ 上），所以按
    "起点 + 数字"去重 —— 不去重的话反真空读数会把一处算成两三处。
    """
    got: dict[tuple[int, str], str] = {}
    for rex in _GATE_COUNT_RES:
        for m in rex.finditer(line):
            got.setdefault((m.start(), m.group(1)), m.group(0))
    return [(num, matched) for (_, num), matched in sorted(got.items())]


def _gate_count_sites(text: str) -> int:
    """这段文本里"收工门 N 条/N 格"的处数（含历史陈述：反真空看的是"判了几处"）。"""
    return sum(len(_gate_count_matches(line)) for line in text.splitlines())


#: 历史陈述的标记：带这些字样的行是"当时的读数"，不是"现在的事实"。
#: 判据只咬"现在时的事实陈述" —— 否则将来有人会为了过判据去改文案，
#: 那是"改判据迁就文案"的反面版本。口径与 `tests/test_capabilities_two_layer.py`
#: 的 `_HISTORICAL_MARKERS` 同形（那一处治的是同一个病：手抄数字 vs 历史留痕）。
_HISTORICAL_MARKERS: tuple[str, ...] = (
    "当时", "当次", "历史", "原写", "原值", "旧版", "改前", "观测", "S1", "S2",
)


def _is_historical(line: str) -> bool:
    """这一行是不是"带时间点的历史陈述"（历史读数允许留痕，不参与对拍）。"""
    if any(m in line for m in _HISTORICAL_MARKERS):
        return True
    return re.search(r"20\d\d-\d\d(-\d\d)?", line) is not None      # 带日期 ⇒ 历史读数


def _gate_count_problems(text: str, want: int, *, where: str,
                         first_line: int = 1) -> list[str]:
    """文本里每一处"收工门 N 条/N 格"与 `want` 不一致的地方（空列表 = 全一致）。

    只对"现在时的事实陈述"下判：带历史标记/日期的行豁免（它们说的是"当时是几条"）。
    `first_line` 让片段（docstring / 注释块）也能报出文件里的真行号。
    """
    out: list[str] = []
    for i, line in enumerate(text.splitlines(), first_line):
        if _is_historical(line):
            continue
        for num_text, matched in _gate_count_matches(line):
            if _int_of_cn(num_text) != want:
                out.append(f"{where}:{i} 写「{matched}」，实测 {want} 格")
    return out


#: 教人的文本面（R7-⑯ 的扩面）：散文（.md）加上源码里"给人读的那一半"。
#: 取的是哪一半，写清楚：
#:   · 三个根文档与 `docs/*.md` 的全文；
#:   · `src/agentflow` 与 `tests` 下每个 .py 的注释（tokenize 的 COMMENT token）、
#:     docstring（ast 的模块/类/函数文档串），以及 `help=` / `description=`
#:     这两个关键字参数的字面量（命令行帮助是给用户读的文案，f-string 的静态片段也算）。
#: 刻意不取代码里的普通字符串：`closing.ClosingReport.status_line()` 的返回串
#: 就是现算的（`收工门：{len(self.status)} 条全过`）—— 那是运行时读数，不是手抄事实，
#: 把普通字符串当散文判会造出假阳。
_TAUGHT_MD = ("README.md", "DEVELOPMENT.md", "AGENTS.md")
_TAUGHT_PY_DIRS = ("src/agentflow", "tests")


def _string_fragments(node: ast.AST) -> list[tuple[int, str]]:
    """一个字面量（含 f-string 的静态片段）⇒ (行号, 文本)；不是字面量就给空表。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [(node.lineno, node.value)]
    if isinstance(node, ast.JoinedStr):
        return [(part.lineno, part.value) for part in node.values
                if isinstance(part, ast.Constant) and isinstance(part.value, str)]
    return []


def _taught_text(path: pathlib.Path) -> tuple[list[tuple[int, str]], list[str]]:
    """(文本块清单, 读不出的原因清单)。

    读不出来不许折成"没问题"：那一份文件进不了扫描面这件事本身要报出来
    （这就是"扫不到"与"没问题"必须同形分开的那条纪律）。
    """
    src = path.read_text(encoding="utf-8", errors="replace")
    blocks: list[tuple[int, str]] = []
    problems: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                blocks.append((tok.start[0], tok.string))
    except Exception as exc:  # noqa: BLE001
        problems.append(f"注释那一面没扫到（tokenize 抛 {type(exc).__name__}）")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        problems.append(f"docstring 那一面没扫到（ast 抛 SyntaxError: {exc.msg}）")
        return blocks, problems
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc is not None and node.body and isinstance(node.body[0], ast.Expr):
                blocks.append((node.body[0].lineno, doc))
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in ("help", "description"):
                    blocks += _string_fragments(kw.value)
    return blocks, problems


def _gate_count_scan_all(want: int) -> tuple[list[str], dict[str, int]]:
    """扫整个教人文本面；返回 (问题清单, 反真空读数)。"""
    bad: list[str] = []
    reading = {"md_files": 0, "py_files": 0, "blocks": 0, "sites": 0, "unreadable": 0}
    mds = [REPO / rel for rel in _TAUGHT_MD] + sorted((REPO / "docs").glob("*.md"))
    for path in mds:
        if not path.is_file():
            bad.append(f"{path.name}: 判据要读的文档不在盘上（不许因为找不到就通过）")
            continue
        text = path.read_text(encoding="utf-8")
        reading["md_files"] += 1
        reading["sites"] += _gate_count_sites(text)
        bad += _gate_count_problems(text, want, where=path.name)
    for rel in _TAUGHT_PY_DIRS:
        for path in sorted((REPO / rel).rglob("*.py")):
            name = str(path.relative_to(REPO.parent))          # 仓库根相对（agentflow/…）
            blocks, unreadable = _taught_text(path)
            reading["py_files"] += 1
            reading["blocks"] += len(blocks)
            for why in unreadable:
                reading["unreadable"] += 1
                bad.append(f"{name}: {why}（这一份的注释/docstring 没进扫描面）")
            for lineno, block in blocks:
                reading["sites"] += _gate_count_sites(block)
                bad += _gate_count_problems(block, want, where=name, first_line=lineno)
    return bad, reading


def test_the_action_counts_in_development_md_match_the_capability_table() -> None:
    """`DEVELOPMENT.md` 的"动作总数 / 可召唤动作数"两格必须与能力表现算一致。

    这两格此前没有判据（判据只盯 `docs/ROLE-SPECS.md` 的标题），实测漂到 54/51
    （真实 58）而没有任何东西会红 —— 这正是 F-07 要治的形态。
    """
    from agentflow import capabilities as C

    total = C.two_layer_reconciliation()["total"]
    summonable = sum(len(C.actions_for(r)) for r in C.ALLOWED_EDGES["M"])
    text = _read("DEVELOPMENT.md")
    for label, want in (("动作总数", total), ("可召唤动作数", summonable)):
        got = _count_of(text, label)
        assert got is not None, (
            f"`DEVELOPMENT.md` 里再也找不到「{label} **N**」这一格（判据不许因为找不到就通过）")
        assert got == want, f"`DEVELOPMENT.md` 的「{label}」写 {got}，而能力表现算是 {want}"

    # 反负控：把那一格改成别的数 ⇒ 同一个判据必须看见（否则它是橡皮图章）
    mutated = text.replace(f"动作总数 **{total}**", f"动作总数 **{total + 1}**")
    assert mutated != text, "夹具没改到那一格 ⇒ 这条反负控是空转"
    assert _count_of(mutated, "动作总数") == total + 1 != want


def test_the_action_table_titles_match_the_capability_table() -> None:
    """`docs/ROLE-SPECS.md` 两处标题的计数（§0.7 与 §M.4.1）同样对拍。"""
    from agentflow import capabilities as C

    total = C.two_layer_reconciliation()["total"]
    summonable = sum(len(C.actions_for(r)) for r in C.ALLOWED_EDGES["M"])
    specs = _read("docs/ROLE-SPECS.md")
    p07 = re.search(r"### 0\.7 动作表（`capabilities\.CAPABILITIES`，(\d+) 个动作）", specs)
    m41 = re.search(r"#### M\.4\.1 .*?（(\d+) 个可召唤动作）", specs)
    assert p07 and m41, "两处标题的写法变了（判据不许因为找不到就通过）"
    assert int(p07.group(1)) == total, f"§0.7 写 {p07.group(1)}，实测 {total}"
    assert int(m41.group(1)) == summonable, f"§M.4.1 写 {m41.group(1)}，实测 {summonable}"


def test_the_subcommand_count_in_the_docs_matches_the_live_parser() -> None:
    """`DEVELOPMENT.md` 的"子命令数"这一格也要有判据（F-07 同族；实测曾 25 vs 真实 24）。

    `README.md` 那份读数已由 `tests/test_user_quickstart.py` 钉住；这一条管
    `DEVELOPMENT.md` 的这一格 —— 两处都是"最容易漂的手抄数字"。
    """
    from agentflow.cli import build_parser

    parser = build_parser()
    sub = next((a for a in parser._actions if getattr(a, "choices", None)), None)
    assert sub is not None, "夹具前提变了：`build_parser()` 里找不到子命令那个 action"
    live = len(sub.choices)
    text = _read("DEVELOPMENT.md")
    got = _count_of(text, "子命令数")
    assert got is not None, "`DEVELOPMENT.md` 里再也找不到「子命令数 **N**」（不许因为找不到就通过）"
    assert got == live, f"`DEVELOPMENT.md` 的子命令数写 {got}，`build_parser()` 当次给出 {live}"


def test_the_documented_assertion_count_matches_the_live_labels() -> None:
    """`capabilities.py` 的「N 条断言」必须与函数里真的有几条一致（`draft/44` 的 F-07 第 3 条）。"""
    src = _read("src/agentflow/capabilities.py")
    body = src[src.find("def assert_capabilities"):]
    doc = body[: body.find('"""', body.find('"""') + 3)]
    cn = re.search(r"([一二三四五六七八九十]+)条断言", doc)
    assert cn, "docstring 里的「N 条断言」这句话不见了（判据不许因为找不到就通过）"
    listed = [int(x) for x in re.findall(r"\n    (\d+)\. ", doc)]
    labels = {int(x) for x in re.findall(r"第 \[(\d+)[a-z]?\] 条", body)}
    assert listed == list(range(1, len(listed) + 1)), f"docstring 的编号项不连续：{listed}"
    assert labels, "函数体里一条断言标签都没读到（判据不许因为读不到就通过）"
    assert len(listed) == max(labels), (
        f"docstring 列了 {len(listed)} 条（写「{cn.group(0)}」），而函数里的条号到 [{max(labels)}]")


def test_every_documented_closing_cell_count_matches_the_live_checks() -> None:
    """凡提到"收工门 N 条/N 格"的地方，N 必须等于 `closing.DEFAULT_CHECKS` 的长度。

    "凡是…必须"这句话要能机械查，所以这里扫的是整个教人文本面（R7-⑯ 扩面）：
    三个根文档 + `docs/*.md` 的全文，加上 `src/agentflow` 与 `tests` 下每个 .py 的
    注释 / docstring / `help=` 文案 —— 改前只扫 `docs/*.md`，于是同一句话写在
    命令行的 `help=` 或测试 docstring 里时没人看得见（实测漏了 9 处）。
    """
    from agentflow import closing as CL

    want = len(CL.DEFAULT_CHECKS)
    assert want >= 8, f"收工门的格数变了（{want}）：先看这一条判据还要不要这么写"

    # ---- 反负控先跑：夹具这一层必须先证明"它真的会红、也真的会豁免"，
    # ---- 否则扫描面那一格红的时候，没人知道是文档漂了还是判据坏了。
    # 反负控①：把一处写成别的数 ⇒ 同一个扫描必须看见
    sample = _read("docs/USER-TEST.md").replace("收工门：八格全过", "收工门：五条全过")
    assert sample != _read("docs/USER-TEST.md"), "夹具没改到那一处 ⇒ 这条反负控是空转"
    assert _gate_count_problems(sample, want, where="USER-TEST.md"), "写错了却没被扫出来"
    # 反负控②（第二种写法，扩面之后两处真漂点用的就是它）：带括号的「收工门（…）：N 条」
    bracketed = "收工门（`draft/37` §16 P3）：五条各自能造红"
    assert _gate_count_problems(bracketed, want, where="（现在时·括号写法）"), \
        "带括号的现在时错数必须被抓到"
    assert _gate_count_sites(bracketed) == 1, _gate_count_sites(bracketed)
    # 反负控③（历史陈述必须豁免）：带"当时/日期"的句子不许被打成红 —— 两种写法都要成立
    historical = "（当时）收工门：五条全过 ⇒ 可交付（2026-09-24 的读数）"
    assert _gate_count_problems(historical, want, where="（历史）") == [], historical
    historical_bracket = "（当时）收工门（`draft/37` §16 P3）：五条各自能造红"
    assert _gate_count_problems(historical_bracket, want, where="（历史·括号写法）") == [], \
        historical_bracket
    assert _gate_count_problems("收工门：五条全过 ⇒ 可交付", want, where="（现在时）"), \
        "现在时的错数必须被抓到（豁免只该给历史陈述）"
    # 反负控④：量词不许被打成"格数"（「那一条」不是「收工门几条」）
    assert _gate_count_problems("收工门（§22）里最贵的那一条是 `load_bearing`", want,
                                where="（量词）") == [], "「那一条」被误判成格数 ⇒ 扫描面太松"
    # 反负控⑤（形态③④ 的负控）：括号里裸数、所有格两种写法都必须红
    assert _gate_count_problems("跑收工门（五格）", want, where="（括号裸数·现在时）"), \
        "括号里直接写数的形态漏了"
    assert _gate_count_problems("收工门（`draft/37` §16 P3 的五条）", want,
                                where="（所有格·现在时）"), "所有格形态漏了"
    # 反负控⑥（强调符形态）：星号夹在冒号与数字之间，是同一种陈述 ⇒ 必须红
    assert _gate_count_problems("收工门：**五条**全过", want, where="（强调符·现在时）"), \
        "强调符夹在冒号与数字之间就漏了"
    assert _gate_count_problems("收工门（**五格**）", want, where="（强调符·括号）"), \
        "强调符夹在括号与数字之间就漏了"
    # 反负控⑦（豁免只靠"形态"，不靠白名单）：下面这些"收工门 + 数字"的句子
    # 要么是当时的历史真身（6 格 / 7 格，那是真的历史事实），要么是量词，
    # 要么是在描述这个缺陷本身。它们一处都不许被四条正则命中 ——
    # 判的是 `_gate_count_matches` 返回空表（= 形态上够不着），而不是靠
    # `_is_historical` 放行：所以这里刻意用不做历史豁免的 `_gate_count_sites`。
    _must_not_be_caught = (
        "而收工门六格全过、`can_close=true`",          # closing.py：门当时是 6 格（史实）
        "于是收工门七格全绿、`can_close=true`",        # closing.py：当时 7 格（史实）
        "而收工门七格全过，而主稿一个字节都没改",       # closing.py：同上
        "收工门六格全过",                              # tests/test_closing_gate.py：史实
        "收工门七格全过",                              # 同上
        "收工门（§22）里最贵的那一条是 `load_bearing`",  # 量词（"那一条"）
        "缺一节那一格就红",                            # 量词（"一节"/"一格"）
        "收工门的每一格",                              # 所有格但不是计数
        "收工门写成" + '"五条全过"',                    # 在讲这个缺陷本身，不是在下断言
    )
    for sample_line in _must_not_be_caught:
        assert _gate_count_sites(sample_line) == 0, (
            "这一行被扫描面误伤了（历史读数 / 量词 / 缺陷描述都不该被当成格数）："
            f"{sample_line!r} ⇒ {_gate_count_matches(sample_line)}")

    # ---- 真面：扫整个教人文本面
    bad, reading = _gate_count_scan_all(want)
    # 反真空：扫不到与没问题必须同形分开
    assert reading["md_files"] >= 4, reading
    assert reading["py_files"] >= 100, reading
    assert reading["blocks"] >= 1000, reading
    assert reading["sites"] >= 1, (
        "整个教人文本面里一处「收工门 N 条/N 格」都没判到 ⇒ 扫描面多半是空的（不许静默通过）："
        f"{reading}")
    assert not bad, ("教人文本面里的收工门格数与 `closing.DEFAULT_CHECKS` 不一致"
                     f"（判了 {reading['sites']} 处 / 扫了 {reading['md_files']} 个 md + "
                     f"{reading['py_files']} 个 py）：" + "；".join(bad))


def test_the_registered_doc_drift_is_still_real_and_gets_cleaned_when_fixed() -> None:
    """FC-27 里的漂移只登记、不代改（人改或人逐行走查）；但登记表要能过期。

    两半（2026-10-06 之后表是空的 —— 唯一那条 `capabilities.H_edges` 已由主控在
    所有者授权下改好）：
    ① 某处真漂却没登记 ⇒ 当场红（"漂的时候没有东西会红"正是 F-07 要治的形态）；
    ② 登记了却已经修好 ⇒ 当场红（只增不减的登记表会烂成噪音）。
    空表因此是好状态，不是"判据失去了对象"。
    """
    from agentflow import capabilities as C

    drifted = H_EDGES_CLAIM_RE.search(_read("src/agentflow/capabilities.py")) is not None
    live = sorted(C.ALLOWED_EDGES["H"])
    inconsistent = drifted and live != ["G"]
    if "capabilities.H_edges" in KNOWN_DOC_DRIFT:
        assert inconsistent, (
            "`capabilities.H_edges` 已不再漂（人已经改好了）⇒ 请把这条从 `KNOWN_DOC_DRIFT` 里删掉："
            "一张只增不减的登记表会烂成噪音")
    else:
        assert not inconsistent, (
            f"`capabilities.py` 的注释说 `H` 只能召唤 `G`，而边表是 {live} —— "
            "这处漂移没有登记（登记表里没有 `capabilities.H_edges`）")
    # 登记表本身要么是空的（都修好了），要么每一条都得今天仍然漂（逐条由上面的分支守）。
    assert isinstance(KNOWN_DOC_DRIFT, dict)


@pytest.mark.parametrize("rel", ["DEVELOPMENT.md", "docs/ROLE-SPECS.md", "docs/READING-MAP.md",
                                 "docs/USER-TEST.md"])
def test_the_documents_the_judge_reads_are_still_there(rel: str) -> None:
    """反真空：上面几条判据读的文档必须在盘上（搬走/改名 ⇒ 当场红，而不是"没找到就通过"）。"""
    assert (REPO / rel).is_file(), f"判据要读的文档不在盘上：{rel}"
