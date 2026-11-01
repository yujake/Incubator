# -*- coding: utf-8 -*-
"""论文正文的机械扫描：H 的统一入口（`review.scan`）背后的唯一实现。

这一层是纯函数：不碰 store、不注册工具、不写盘。它只回答"盘上的正文里有什么"，
把七类读数折成同一份结构；工具层（`tools/review_tools.py::review.scan`）只做
「解析路径 → 调本模块 → `ok(...)`」。

## 为什么要有这一层（改前读数，2026-11-01 实测）

H 的工具面上"扫描/核对"类有 7 件，各回各的形状（六键 / 十一键 / 十键…），而三条
机械清单要的"数"没有一件替它数：`proof 环境数` 与 `台账定理类数` 分别落在
`specs/h.py:142` 的两列口径里，而真稿 `paper-rewrite-80` 上这两个数是 18 与 7
（同一篇论文的"有几条定理"还有 18 / 15 / 13 三个别的口径）。所以这一层的目标不是
"多一个工具"，而是同一份正文只数一遍、把口径与数字一起交出去。

## 七类与它们的口径（每一条都可复算）

| kind | 判什么 | 口径来源 |
|---|---|---|
| `text_integrity` | 六类异常字符（cjk / control / zero_width / replacement / bidi / nbsp） | 复用 `tools/review_tools.scan_text_integrity()`（唯一实现；本模块只做形状归一） |
| `cites` | 每个 `\\cite` 键都能对上一条 `\\bibitem` | `CITE_COMMANDS` × `_BIBITEM_RE` |
| `inputs` | 每个 `\\input` / `\\include` 的目标在盘上 | 解析器复用 `papermapping._input_target` |
| `refs` | 每个引用命令的键都能对上一条 `\\label` | `REF_COMMANDS`（六个，见下） |
| `proofs` | 定理类环境带 `proof`；`proof` 不悬空、要闭合 | 环境名复用 `papermapping.statement_env_names`（含印成 Lemma 的自定义宏） |
| `duplicates` | `\\label` / `\\newtheorem` 重名 | 本模块 |
| `ledger_match` | 正文 vs 台账 vs 对应表的五个数 + `statement_surplus` | 复用 `papermapping.mapping_reading` / `proposition_statement_ids` |

### `REF_COMMANDS` 为什么是六个，以及"没被引用过的标签"为什么不报（两次实测的教训）

2026-11-01 在仓内 31 篇真论文上量过两次（读数在 `temp/h_ref_family.json`）：

1. "没被引用过的 `\\label`"不是发现，是噪音：703 个标签里，只认 `\\ref` 时有 298 个
   没人引用；把 `\\ref` / `\\eqref` / `\\autoref` / `\\pageref` / `\\cref` / `\\Cref` 都算进去
   仍有 229 个。那 229 个是分节标签 —— 只被 hyperref 的书签用到，正文一个字都没引它。
   ⇒ 这一档只把条数放进 `facts.unused_labels`，一条都不当 finding 报。假阳性比漏报贵：
   H 拿着一张几百条的清单去要修法，改的人是 G，而 G 改的全是本来正确的行 —— 三轮之后
   这张清单就没人看了，真问题跟着一起被忽略。

2. 反过来，"只认 `\\ref`"会静默漏报：一条 `\\eqref{不存在的标签}` 在只认 `\\ref` 的
   扫描器眼里根本不存在 —— 悬空引用是看不见，不是报错。所以 `REF_COMMANDS` 必须是
   这六个，且每一个都要有判据（`tests/test_texaudit.py::test_every_ref_command_is_scanned`：
   把其中任何一个从词表里删掉，那条判据立刻红）。

### `ledger_match` 为什么只回数、不发明 `==`

`specs/h.py:142` 的清单①写的是「proof 环境数 == 台账里定理类命题数」。在真稿上这条
口径给出的是"18 ≠ 7，差 11 条"，而同一份稿子按 `papermapping` 的口径是"正文多出 5 个
定理类环境（`statement_surplus`）"。两个结论指向不同的事实，而后者才是要修的那件事。
所以这一档只回五个数 + `statement_surplus` 清单，不把 `==` 写成判据：等号成立与否
由人（或 H 自己）看着数字判，不由这一层替它判。

## 三态

`checked=False` 只表示"这一 kind 没查成"（路径读不出 / 没有工作区根 / 台账不在盘上 /
这一类还没接线），永远与"扫了、零命中"分开：后者是 `checked=True` + 空 `findings`。
逐类的结论在 `detail[]` 里；全局那一位是"点名的每一类都查成了"的合取。

## `findings[]` 的键集恒定（`FINDING_KEYS`，九个）

不适用时给如实空值（`0` / 空串），不许少键：`tests/test_tools_returns_declaration.py`
的 `test_every_element_of_an_array_carries_the_same_top_level_keys` 会当场红
（同一个数组里的元素顶层键不一致 ⇒ 按声明读那些键的调用方拿到 `KeyError`）。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import papermapping as PM

#: 这一层认的七类（工具层 `review.scan` 的 `kinds` 枚举唯一来源）。
SCAN_KINDS: tuple[str, ...] = (
    "text_integrity",
    "cites",
    "inputs",
    "refs",
    "proofs",
    "duplicates",
    "ledger_match",
)

#: `findings[]` 每个元素的九个键（顺序即文档顺序；恒定，见模块 docstring 末节）。
FINDING_KEYS: tuple[str, ...] = (
    "kind",
    "severity",
    "file",
    "line",
    "column",
    "text",
    "why",
    "ref",
    "codepoint",
)

#: 严重度词表（与 `schema.FINDING_LEVELS` 同集合；本模块不 import schema，只做形状）。
SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

#: 这一次最多返回多少条 `findings`（`counts` 是盘上的真总数，不受它影响）。
DEFAULT_FINDINGS_LIMIT = 200

#: 引用类命令（`\ref` 家族）。只认 `\ref` 会在真稿上造 298 个假阳性，见模块 docstring。
REF_COMMANDS: tuple[str, ...] = ("ref", "eqref", "autoref", "pageref", "cref", "Cref")

#: 文献类命令（`\cite` 家族）。`\nocite{*}` 的 `*` 不是键，跳过。
CITE_COMMANDS: tuple[str, ...] = (
    "cite", "citep", "citet", "citealp", "citeauthor", "citeyear", "nocite",
)

#: `detail[]` 每个元素的六个键（与 `review.scan_text_integrity` 的 `detail` 同形）。
DETAIL_KEYS: tuple[str, ...] = ("kind", "checked", "reason", "scanned", "counts", "returned")

#: `scan_tex()` 的八个顶层键（工具层 `returns=` 与判据都读这一份）。
RETURN_KEYS: tuple[str, ...] = (
    "checked", "kinds", "findings", "counts", "bad", "detail", "scanned", "reason",
)

_REF_RE = re.compile(
    r"\\(" + "|".join(re.escape(c) for c in REF_COMMANDS) + r")\*?\s*\{([^{}]*)\}")
_CITE_RE = re.compile(
    r"\\(" + "|".join(re.escape(c) for c in CITE_COMMANDS)
    + r")\*?\s*(?:\[[^\]]*\]\s*)*\{([^{}]*)\}")
_BIBITEM_RE = re.compile(r"\\bibitem\s*(?:\[[^\]]*\])?\s*\{([^{}]*)\}")
_LABEL_RE = re.compile(r"\\label\s*\{([^{}]*)\}")
_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^{}]*)\}")
_NEWTHEOREM_RE = re.compile(
    r"\\newtheorem\*?\s*\{(?P<name>[^{}]+)\}\s*(?:\[[^{}]*\]\s*)?\{[^{}]*\}")

#: 六类字符"为什么要改"（与 `review_tools` 那六档的处置一一对应）。
_CHAR_WHY: dict[str, str] = {
    "cjk": "英文正文里出现中文 ⇒ 这一句没被改写成目标语言（要改写，不是删）",
    "control": "控制符 ⇒ 管道污染的残留（删掉；它不是正文的一部分）",
    "zero_width": "零宽字符 ⇒ 看不见但参与匹配（删掉，否则逐字回验会误判）",
    "replacement": "替换符 U+FFFD ⇒ 上游解码已经丢了字符（回去查那一份的来源）",
    "bidi": "双向控制符 ⇒ 读到的顺序可能与实际相反（安全档，必须删）",
    "nbsp": "不换行空格 ⇒ 断行算法在那一段失效（换成普通空格）",
}


# ---------------------------------------------------------------- 形状


def _finding(
    kind: str,
    severity: str,
    *,
    file: Any = "",
    line: Any = 0,
    column: Any = 0,
    text: Any = "",
    why: Any = "",
    ref: Any = "",
    codepoint: Any = "",
) -> dict:
    """一条发现（九键恒定；缺的给如实空值，不许少键）。"""
    if severity not in SEVERITIES:  # 内部断言：分档写错是代码错，不是读数
        raise ValueError(f"severity 必须是 {SEVERITIES} 之一，收到 {severity!r}")
    return {
        "kind": str(kind),
        "severity": str(severity),
        "file": str(file or ""),
        "line": int(line or 0),
        "column": int(column or 0),
        "text": str(text or ""),
        "why": str(why or ""),
        "ref": str(ref or ""),
        "codepoint": str(codepoint or ""),
    }


def _detail(kind: str, *, checked: bool, reason: str = "", scanned: Sequence[str] = (),
            counts: Mapping[str, Any] | None = None, returned: int = 0) -> dict:
    """一类的读数（六键恒定，与 `review.scan_text_integrity` 的 `detail[]` 同形）。"""
    return {
        "kind": str(kind),
        "checked": bool(checked),
        "reason": str(reason or ""),
        "scanned": list(scanned),
        "counts": dict(counts or {}),
        "returned": int(returned),
    }


def _severity_of_char(char_kind: Any) -> str:
    """六类字符的分档（`nbsp` 只是断行，其余五类都是要改的错）。"""
    return "warning" if str(char_kind) == "nbsp" else "error"


# ---------------------------------------------------------------- 读盘


def _read_text(path: Path) -> tuple[str | None, str]:
    """读一份 UTF-8 文本；读不成返回 `(None, 理由)`（绝不返回空串冒充空文件）。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return None, f"{path.name} 读不出来（{type(exc).__name__}: {exc}）"
    if b"\x00" in raw:
        return None, f"{path.name} 是二进制文件（含 NUL 字节）⇒ 它没有可数的正文"
    try:
        return raw.decode("utf-8"), ""
    except UnicodeDecodeError as exc:
        return None, f"{path.name} 不是 UTF-8 文本（{exc}）⇒ 它没有可数的正文"


def _rel(path: Path, root: Path | None) -> str:
    """读数里的 `file` 一律是工作区相对路径（posix 分隔符，与 `fs.*` 同一条）。"""
    if root is None:
        return path.name
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return path.name


class _Corpus:
    """这一次要扫的正文：`main.tex` + 它递归 `\\input` 进来的文件（按文档顺序切片段）。

    为什么要有这样一个对象：五类里有四类（cites/refs/proofs/duplicates）都要"按文档顺序、
    带文件与行号"地看同一份展开后的正文。每类自己展开一遍 = 同一件事四处口径。
    """

    def __init__(self, root: Path | None, files: Sequence[Path]):
        self.root = root
        self.files = list(files)
        self.segments: list[tuple[str, str, int]] = []   # (相对名, 片段, 起始行偏移)
        self.problems: list[dict] = []
        self.main: Path | None = None
        self.package: Path | None = None
        self.main_text = ""

    def pkg_prefix(self) -> str:
        """论文包相对工作区根的前缀（`out/paper/`）—— 读数里的 `file` 要带它。

        `papermapping._collect_tex_segments` 给的是"相对包根"的名字（`main.tex`、
        `mapping-appendix.tex`），而 H 拿到读数之后要按那个路径去改稿 —— 所以这一层
        把它补成工作区相对（`out/paper/main.tex`）。补错的表现很隐蔽：H 会去改一个
        同名但不在包里的文件，或者干脆找不到。
        """
        if self.package is None or self.root is None:
            return ""
        prefix = _rel(self.package, self.root)
        return "" if prefix in ("", ".") else prefix.rstrip("/") + "/"

    def qualify(self, rel: str) -> str:
        """包内相对名 → 工作区相对名。"""
        prefix = self.pkg_prefix()
        if not prefix or not rel or rel.startswith(prefix):
            return rel
        return prefix + rel

    def load(self) -> None:
        """把文件展开成片段；读不成 / `\\input` 指不到都记进 `problems`（不静默丢）。"""
        self.main = next((p for p in self.files if p.name == PM.PC.TEX_NAME), None)
        if self.main is not None:
            body, why = _read_text(self.main)
            if body is None:
                self.problems.append({"file": _rel(self.main, self.root), "why": why})
                return
            self.main_text = body
            self.package = self.main.parent
            segments, _read_files, probs = PM._collect_tex_segments(  # noqa: SLF001 —— 生产实现
                self.package, self.main, body)
            self.segments = [(self.qualify(rel), seg, off) for rel, seg, off in segments]
            for prob in probs:
                self.problems.append({
                    "file": str(prob.get("where") or ""),
                    "why": str(prob.get("detail") or ""),
                })
            return
        # 没有 `main.tex`：逐份扫（不跟 `\input` —— 没有包根，跟了就是猜路径）
        for path in self.files:
            body, why = _read_text(path)
            if body is None:
                self.problems.append({"file": _rel(path, self.root), "why": why})
                continue
            self.segments.append((_rel(path, self.root), PM.strip_tex_comments(body), 0))

    @property
    def statement_names(self) -> tuple[str, ...]:
        """定理类环境名（含印成 Theorem/Lemma/… 的自定义宏）。"""
        text = self.main_text or "\n".join(seg for _r, seg, _o in self.segments)
        return PM.statement_env_names(text)

    def hits(self, pattern: re.Pattern[str]) -> list[tuple[str, int, str, str]]:
        """逐片段跑一条正则：`(文件, 行号, 命中原文, 最后一组)`。"""
        out: list[tuple[str, int, str, str]] = []
        last = pattern.groups
        for rel, seg, offset in self.segments:
            for m in pattern.finditer(seg):
                out.append((rel, offset + seg.count("\n", 0, m.start()) + 1,
                            m.group(0).strip(), m.group(last) if last else ""))
        return out


# ---------------------------------------------------------------- 七类


def _scan_cites(corpus: _Corpus, cap: int) -> tuple[list[dict], dict, str, list[str]]:
    cites = corpus.hits(_CITE_RE)
    bibs = corpus.hits(_BIBITEM_RE)
    cited: dict[str, tuple[str, int]] = {}
    for rel, line, _raw, group in cites:
        for key in (k.strip() for k in group.split(",")):
            if key and key != "*" and key not in cited:
                cited[key] = (rel, line)
    bib_keys = {k.strip() for _r, _l, _raw, k in bibs if k.strip()}
    findings = [
        _finding("cites", "error", file=rel, line=line, ref=key,
                 text=f"\\cite{{{key}}}",
                 why=(f"这条 \\cite 的键 {key!r} 在参考文献里没有对应的 \\bibitem —— "
                      f"正文引了一份不存在于参考文献表的文献（读的人点不过去）"))
        for key, (rel, line) in sorted(cited.items()) if key not in bib_keys
    ]
    facts = {
        "cite_keys": len(cited),
        "bibitem_keys": len(bib_keys),
        "uncited": len(bib_keys - set(cited)),
        "cite_commands": list(CITE_COMMANDS),
    }
    reason = "" if corpus.segments else "没有可读的正文 ⇒ 这一档没查成（不是「没有引用」）"
    return findings, facts, reason, sorted({rel for rel, _l, _r, _g in cites})


def _scan_refs(corpus: _Corpus, cap: int) -> tuple[list[dict], dict, str, list[str]]:
    refs = corpus.hits(_REF_RE)
    labels = corpus.hits(_LABEL_RE)
    label_set = {k.strip() for _r, _l, _raw, k in labels if k.strip()}
    used: dict[str, tuple[str, int, str]] = {}
    for rel, line, raw, group in refs:
        for key in (k.strip() for k in group.split(",")):
            if key and key not in used:
                used[key] = (rel, line, raw)
    findings = [
        _finding("refs", "error", file=rel, line=line, ref=key, text=raw,
                 why=(f"这条引用命令的键 {key!r} 没有对应的 \\label —— "
                      f"交叉引用悬空（读的人看到的是 ??）"))
        for key, (rel, line, raw) in sorted(used.items()) if key not in label_set
    ]
    facts = {
        "ref_keys": len(used),
        "label_keys": len(label_set),
        "unused_labels": len(label_set - set(used)),
        "ref_commands": list(REF_COMMANDS),
    }
    reason = "" if corpus.segments else "没有可读的正文 ⇒ 这一档没查成"
    return findings, facts, reason, sorted({rel for rel, _l, _r, _g in refs + labels})


def _scan_duplicates(corpus: _Corpus, cap: int) -> tuple[list[dict], dict, str, list[str]]:
    labels = corpus.hits(_LABEL_RE)
    by_key: dict[str, list[tuple[str, int]]] = {}
    for rel, line, _raw, key in labels:
        key = key.strip()
        if key:
            by_key.setdefault(key, []).append((rel, line))
    findings: list[dict] = []
    for key, spots in sorted(by_key.items()):
        for rel, line in spots[1:]:
            first_rel, first_line = spots[0]
            findings.append(_finding(
                "duplicates", "error", file=rel, line=line, ref=key,
                text=f"\\label{{{key}}}",
                why=(f"同一个 \\label 出现 {len(spots)} 次（第一次在 {first_rel}:{first_line}）"
                     f" —— 引用它的人会被指到错的那一处，而 TeX 只会给一句重复标签")))
    names = [m.group("name").strip() for m in _NEWTHEOREM_RE.finditer(
        corpus.main_text or "\n".join(seg for _r, seg, _o in corpus.segments))]
    counts: dict[str, int] = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    where = corpus.segments[0][0] if corpus.segments else ""
    for name, n in sorted(counts.items()):
        if n > 1:
            findings.append(_finding(
                "duplicates", "error", file=where, ref=name,
                text=f"\\newtheorem{{{name}}}",
                why=(f"环境名 {name!r} 被 \\newtheorem 声明了 {n} 次 —— 后一条会覆盖前一条的"
                     f"计数器/标题，正文里那两个环境的编号从此说不清")))
    facts = {
        "labels": len(by_key),
        "duplicate_labels": sum(1 for spots in by_key.values() if len(spots) > 1),
        "newtheorem_names": len(counts),
        "duplicate_newtheorem": sum(1 for n in counts.values() if n > 1),
    }
    reason = "" if corpus.segments else "没有可读的正文 ⇒ 这一档没查成"
    return findings, facts, reason, sorted({rel for rel, _l, _r, _g in labels})


def _env_events(corpus: _Corpus) -> list[dict]:
    """正文里的 begin/end 事件（定理类环境 + `proof`），按文档顺序。"""
    names = tuple(dict.fromkeys(tuple(corpus.statement_names) + ("proof",)))
    if not names:
        return []
    pattern = re.compile(
        r"\\(?P<which>begin|end)\s*\{(?P<name>" + "|".join(re.escape(n) for n in names)
        + r")\}")
    events: list[dict] = []
    for rel, seg, offset in corpus.segments:
        for m in pattern.finditer(seg):
            events.append({
                "which": m.group("which"),
                "name": m.group("name"),
                "file": rel,
                "line": offset + seg.count("\n", 0, m.start()) + 1,
            })
    return events


def _scan_proofs(corpus: _Corpus, cap: int) -> tuple[list[dict], dict, str, list[str]]:
    """定理类环境 ↔ `proof` 的配对（一条命题一份证明）。

    配对规则只有一条（刻意简单）：每个 `\\begin{proof}` 认领"它前面最近的那个、
    还没被认领过的定理类环境"。这不判"一个定理只能有一份证明"—— 真论文里
    "(1)(2) 分别证" 会写成两个 proof 环境，按"多一份就报"去拦会全是假阳性。
    报的是两种真的坏形态：证明没有归属、定理没有证明；外加 proof 环境没闭合。
    """
    statements = set(corpus.statement_names)
    events = _env_events(corpus)
    findings: list[dict] = []
    proof_opens = sum(1 for e in events if e["name"] == "proof" and e["which"] == "begin")
    proof_ends = sum(1 for e in events if e["name"] == "proof" and e["which"] == "end")
    last_stmt: dict | None = None
    paired: set[int] = set()
    stmt_events: list[dict] = []
    orphan_proofs = 0
    for e in events:
        if e["name"] in statements and e["which"] == "begin":
            last_stmt = e
            stmt_events.append(e)
            continue
        if e["name"] == "proof" and e["which"] == "begin":
            if last_stmt is None:
                orphan_proofs += 1
                findings.append(_finding(
                    "proofs", "error", file=e["file"], line=e["line"], text="\\begin{proof}",
                    why=("这一个 proof 环境前面没有任何定理类环境 —— 证明没有归属，"
                         "读者找不到它在证哪一条")))
            else:
                paired.add(id(last_stmt))
    unpaired = 0
    for e in stmt_events:
        if id(e) not in paired:
            unpaired += 1
            findings.append(_finding(
                "proofs", "error", file=e["file"], line=e["line"],
                text=f"\\begin{{{e['name']}}}",
                why=("这个定理类环境后面没有 proof 环境 —— 「一条命题一份证明」，"
                     "缺的那一份读者无法复核")))
    if proof_opens != proof_ends:
        findings.append(_finding(
            "proofs", "error", file=corpus.segments[0][0] if corpus.segments else "",
            text="\\begin{proof} / \\end{proof}",
            why=(f"proof 环境没有闭合：begin {proof_opens} 个、end {proof_ends} 个 —— "
                 f"这一份正文编不过（或者后面整段都被吃进证明里）")))
    facts = {
        "proof_envs": proof_opens,
        "statement_envs": len(stmt_events),
        "proof_without_statement": orphan_proofs,
        "statement_without_proof": unpaired,
        "proof_unclosed": proof_opens - proof_ends,
        "statement_env_names": sorted(statements),
    }
    reason = "" if corpus.segments else "没有可读的正文 ⇒ 这一档没查成"
    return findings, facts, reason, sorted({e["file"] for e in events})


def _safe_rel(package: Path, path: Path, prefix: str = "") -> str:
    """包内相对名（带工作区前缀）。"""
    try:
        rel = path.resolve().relative_to(package.resolve()).as_posix()
    except (ValueError, OSError):
        rel = path.name
    return prefix + rel if prefix else rel


def _walk_inputs(package: Path, main: Path, text: str,
                 prefix: str = "") -> tuple[list[dict], dict, list[str]]:
    """跟完 `\\input` / `\\include`（与 `papermapping._collect_tex_segments` 同规则）。

    解析器只有一个（`PM._input_target`），深度上限也用它那一份常量；这里只多做一件事：
    把"指不到"记成一条发现，而不是像对应表那一侧那样折进一串 `mapping_unresolvable`
    问题里（H 要的是"哪个文件第几行的哪一句"）。
    """
    findings: list[dict] = []
    seen: list[str] = []
    directives = [0]

    def visit(path: Path, body: str, depth: int) -> None:
        rel = _safe_rel(package, path, prefix)
        if rel not in seen:
            seen.append(rel)
        clean = PM.strip_tex_comments(body)
        for m in _INPUT_RE.finditer(clean):
            directives[0] += 1
            name = m.group(1).strip()
            line = clean.count("\n", 0, m.start()) + 1
            target = PM._input_target(path.parent, name)  # noqa: SLF001 —— 解析器唯一实现
            if target is None:
                findings.append(_finding(
                    "inputs", "error", file=rel, line=line, ref=name,
                    text=f"\\input{{{name}}}",
                    why=(f"\\input{{{name}}} 指的文件读不到（按 {path.parent} 解析，"
                         f"原名与 .tex 都试过）—— 这一支的正文根本没有进稿")))
                continue
            if depth + 1 > PM.MAX_TEX_INPUT_DEPTH:
                findings.append(_finding(
                    "inputs", "error", file=rel, line=line, ref=name,
                    text=f"\\input{{{name}}}",
                    why=(f"\\input 递归到第 {depth + 1} 层（上限 {PM.MAX_TEX_INPUT_DEPTH}）"
                         f"还没到底 —— 这一支不再展开")))
                continue
            sub, why = _read_text(target)
            if sub is None:
                findings.append(_finding("inputs", "error", file=rel, line=line, ref=name,
                                         text=f"\\input{{{name}}}", why=why))
                continue
            visit(target, sub, depth + 1)

    visit(main, text, 0)
    return findings, {"files_read": len(seen), "directives": directives[0]}, seen


def _scan_inputs(corpus: _Corpus, cap: int) -> tuple[list[dict], dict, str, list[str]]:
    if corpus.main is None or corpus.package is None:
        return [], {"files_read": 0, "directives": 0}, (
            "没有 main.tex ⇒ 无从跟 \\input（这一档没查成，不是「没有 \\input」）"), []
    findings, facts, seen = _walk_inputs(corpus.package, corpus.main, corpus.main_text,
                                         corpus.pkg_prefix())
    return findings, facts, "", seen


def _scan_text_integrity(
    root: Path | None, raw_paths: Sequence[str], cap: int,
    reader: Callable[..., dict] | None,
) -> tuple[list[dict], dict, str, list[str]]:
    """复用 `review_tools.scan_text_integrity()`（唯一实现），只把形状折成九键。"""
    if reader is None:
        return [], {}, "没有接线字符扫描器（text_integrity 这一档没查成）", []
    if root is None:
        return [], {}, "装配时没有拿到工作区根 ⇒ 相对路径无从解析（没查成，不是零命中）", []
    got = reader(root, list(raw_paths), limit=cap)
    checked = bool(got.get("checked"))
    findings = [
        _finding("text_integrity", _severity_of_char(f.get("kind")),
                 file=f.get("path"), line=f.get("line"), column=f.get("column"),
                 text=f.get("excerpt"), ref=f.get("kind"), codepoint=f.get("codepoint"),
                 why=_CHAR_WHY.get(str(f.get("kind")), ""))
        for f in (got.get("findings") or [])
    ]
    facts = dict(got.get("counts") or {})
    reason = "" if checked else str(got.get("reason") or "字符扫描没查成（没给理由）")
    return findings, facts, reason, list(got.get("scanned") or [])


def _scan_ledger(
    root: Path | None, project: Path | None, corpus: _Corpus,
    ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None,
) -> tuple[list[dict], dict, str, list[str]]:
    """五个数 + `statement_surplus`（不发明 `==`，见模块 docstring）。"""
    if project is None:
        return [], {"ledger_rows": None}, (
            "没有给 project（论文项目根）⇒ 台账与对应表这一档没查成（不是「对得上」）"), []
    if ledger is None:
        return [], {"ledger_rows": None}, "台账读不到（盘上没有 statements 表）⇒ 这一档没查成", []
    statements = ledger.get("statements")
    if statements is None:
        return [], {"ledger_rows": None}, "台账里没有 statements 这一张表 ⇒ 这一档没查成", []
    reading = PM.mapping_reading(project, workspace_root=root)
    propositions = PM.proposition_statement_ids(ledger)
    theorem_kinds = {"theorem", "lemma", "proposition", "corollary"}
    thm_rows = [r for r in statements
                if str((r or {}).get("kind") or "").strip().lower() in theorem_kinds]
    proof_envs = sum(1 for e in _env_events(corpus)
                     if e["name"] == "proof" and e["which"] == "begin")
    facts = {
        "proof_envs": proof_envs,
        "statement_envs": int(reading.get("statement_envs") or 0),
        "ledger_rows": len(statements),
        "ledger_propositions": len(propositions),
        "ledger_theorem_kinds": len(thm_rows),
        "mapping_rows": int(reading.get("rows") or 0),
        "statement_surplus": list(reading.get("statement_surplus") or []),
        "mapping_state": str(reading.get("state") or ""),
    }
    main_path = PM.package_dir(project) / PM.PC.TEX_NAME
    main_rel = _rel(main_path, root) if main_path.is_file() else (
        corpus.segments[0][0] if corpus.segments else "")
    findings = [
        _finding("ledger_match", "warning", file=main_rel, ref=str(label),
                 text=f"定理类环境 {label!r}",
                 why=("正文里有这个定理类环境，而台账/对应表里没有能与它对应的命题 —— "
                      "「一条命题对一个环境」，这是「正文多出来的」那一侧"
                      "（口径：papermapping.statement_surplus，不判 `==`）"))
        for label in facts["statement_surplus"]
    ]
    reason = "" if reading.get("checked") else str(
        reading.get("reason") or "对应表那一档没查成（没给理由）")
    return findings, facts, reason, [str(reading.get("mapping_json") or "")]


# ---------------------------------------------------------------- 入口


def _empty(*, kinds: Sequence[str], reason: str) -> dict:
    """没扫成时的那一份（八键齐全，键集与扫成时逐字相同）。"""
    return {
        "checked": False,
        "kinds": list(kinds),
        "findings": [],
        "counts": {"files": 0, "findings": 0,
                   "by_kind": {k: 0 for k in kinds},
                   "by_severity": {s: 0 for s in SEVERITIES}, "facts": {}},
        "bad": [{"kind": "kinds", "reason": reason}] if reason else [],
        "detail": [],
        "scanned": [],
        "reason": reason,
    }


def scan_tex(
    root: Any,
    *,
    kinds: Sequence[str],
    files: Sequence[Any] = (),
    path_problems: Sequence[Mapping[str, Any]] = (),
    project: Any = None,
    limit: Any = None,
    ledger: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    text_integrity: Callable[..., dict] | None = None,
    raw_paths: Sequence[str] = (),
    wired: Sequence[str] | None = None,
) -> dict:
    """扫一次：点名的那些类，折成同一份结构（纯函数，不写盘、不碰 store）。

    参数
    ----
    root : 工作区根（`Path` 或 `None`）。`None` ⇒ 相对路径无从解析 ⇒ 每一类都"没查成"。
    kinds : 要查的类（`SCAN_KINDS` 的子集；空或生词 ⇒ 拒绝，理由写清）。
    files : 已解析过的工作区文件（目录递归与路径闸在工具层，本层只读文件）。
    path_problems : 工具层解析失败的路径 `[{path, why}]`（原样进 `bad[]`）。
    project : 论文项目根（`ledger_match` 要它；不给 ⇒ 那一类"没查成"）。
    ledger : 台账三张表的行（不给 ⇒ 本层从 `root/data` 读；读不到 ⇒ 那一类"没查成"）。
    text_integrity : 字符扫描器的纯函数（`review_tools.scan_text_integrity`）。
    raw_paths : 原样路径（字符扫描器要自己解析它，所以按原样转交）。
    wired : 这一趟真的接上了的类（缺省 = 全部）。不在里面的类进 `bad[]` 并记
        "还没接线" —— 调用方（工具层）用它把"契约"与"接线"分成两步推进，
        而三态纪律要求那一步如实说"没查成"，不能悄悄跳过。
    """
    if not isinstance(kinds, (list, tuple)) or not kinds:
        return _empty(kinds=[], reason="kinds 是空的（或不是数组）⇒ 这一趟什么都没扫，"
                                      "不是「查过了、干净」")
    unknown = [k for k in kinds if k not in SCAN_KINDS]
    if unknown:
        return _empty(kinds=list(kinds), reason=(
            f"这些 kind 不认识：{unknown}（认 {list(SCAN_KINDS)}）⇒ 这一趟没扫，"
            f"不是「查过了、干净」"))

    cap = DEFAULT_FINDINGS_LIMIT if limit is None else int(limit)
    if cap < 1:
        raise ValueError(f"limit 必须是正整数，收到 {limit!r}")
    base = Path(str(root)).resolve() if root is not None else None
    project_path = Path(str(project)).resolve() if project is not None else None
    if project_path is not None and base is not None:
        try:
            project_path.relative_to(base)
        except ValueError:
            project_path = None
    files = [Path(str(p)) for p in (files or ())]
    if not files and project_path is not None:
        candidate = project_path / "out" / "paper" / PM.PC.TEX_NAME
        if candidate.is_file():
            files = [candidate]
    corpus = _Corpus(base, files)
    corpus.load()
    if ledger is None and base is not None:
        from . import schema as S

        statements_file = str((S.TABLES.get("statements") or {}).get("file") or "")
        if statements_file and (base / "data" / statements_file).is_file():
            ledger = PM.read_ledger_tables(base)

    findings: list[dict] = []
    details: list[dict] = []
    bad: list[dict] = []
    scanned: list[str] = []
    by_kind: dict[str, int] = {k: 0 for k in kinds}
    all_facts: dict[str, Any] = {}
    allowed = tuple(wired) if wired is not None else SCAN_KINDS

    for kind in kinds:
        if kind not in allowed:
            # 契约里认这一类、而这一趟还没接线 ⇒ 如实"没查成"（不是悄悄跳过）
            reason = f"这一类还没接线（这一趟允许的是 {list(allowed)}）"
            details.append(_detail(kind, checked=False, reason=reason,
                                   counts={"findings": 0}))
            bad.append({"kind": kind, "reason": reason})
            continue
        if kind == "text_integrity":
            got, facts, reason, touched = _scan_text_integrity(
                base, raw_paths, cap, text_integrity)
        elif kind == "cites":
            got, facts, reason, touched = _scan_cites(corpus, cap)
        elif kind == "refs":
            got, facts, reason, touched = _scan_refs(corpus, cap)
        elif kind == "duplicates":
            got, facts, reason, touched = _scan_duplicates(corpus, cap)
        elif kind == "proofs":
            got, facts, reason, touched = _scan_proofs(corpus, cap)
        elif kind == "inputs":
            got, facts, reason, touched = _scan_inputs(corpus, cap)
        else:  # ledger_match
            got, facts, reason, touched = _scan_ledger(base, project_path, corpus, ledger)
        details.append(_detail(kind, checked=not reason, reason=reason, scanned=touched,
                               counts={"findings": len(got)}, returned=min(len(got), cap)))
        if reason:
            bad.append({"kind": kind, "reason": reason})
        by_kind[kind] = len(got)
        findings.extend(got)
        for key, value in (facts or {}).items():
            all_facts[key] = value
        for rel in touched:
            if rel and rel not in scanned:
                scanned.append(rel)

    for item in path_problems or ():
        reason = str(item.get("why") or item.get("reason") or "")
        bad.append({"kind": "paths", "reason": reason})
        details.append(_detail("paths", checked=False, reason=reason,
                               counts={"findings": 0}))
    for item in corpus.problems:
        bad.append({"kind": "corpus",
                    "reason": f"{item.get('file')}: {item.get('why')}"})

    findings.sort(key=lambda f: (SCAN_KINDS.index(f["kind"]) if f["kind"] in SCAN_KINDS else 99,
                                 f["file"], f["line"], f["column"]))
    total = len(findings)
    kept = findings[:cap]
    by_severity = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITIES}
    counts = {
        "files": len(scanned),
        "findings": total,
        "by_kind": by_kind,
        "by_severity": by_severity,
        "facts": all_facts,
    }
    if bad:
        reason = "；".join(f"{item['kind']} 没查成：{item['reason']}" for item in bad)
    else:
        reason = "；".join(f"{k} {by_kind[k]} 条" for k in kinds) + (
            f"（findings 只给前 {cap} 条，counts 是盘上真总数）" if total > cap else "")
    return {
        "checked": not bad,
        "kinds": list(kinds),
        "findings": kept,
        "counts": counts,
        "bad": bad,
        "detail": details,
        "scanned": scanned,
        "reason": reason,
    }


__all__ = [
    "CITE_COMMANDS",
    "DEFAULT_FINDINGS_LIMIT",
    "DETAIL_KEYS",
    "FINDING_KEYS",
    "REF_COMMANDS",
    "RETURN_KEYS",
    "SCAN_KINDS",
    "SEVERITIES",
    "scan_tex",
]
