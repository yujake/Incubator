# -*- coding: utf-8 -*-
"""`check_doc_refs` —— 文档与注释里的“指路”还指得到吗（只读，零模型调用）。

## 它扫什么

四类源文件（`--root` 缺省 = 本文件上一级，即 `agentflow/`）：

- `src/agentflow/**/*.py`（源码注释与 docstring 里的指路）；
- `tests/**/*.py`（判据与夹具的注释 / docstring —— 2026-11-23 纳入；
  在此之前全仓 72% 的行号引用在这里，没有任何门在看）；
- `docs/*.md`；
- 根目录 `*.md`（`README-PRODUCT.md` / `DEVELOPMENT.md` / `AGENTS.md` 等）。

`tests/fixtures/**` 里的 `.md` / `.json` / `.tsv` 是语料（各判据的输入），不扫：
它们不是“长期指路”的对象；`tests/fixtures/**` 里也没有 `.py`，所以上一条的
`tests/**/*.py` 本来就不含它。

`temp/`、`__pycache__`、`.pytest_cache` 不扫：它们不是“长期指路”的对象
（`AGENTS.md` R2：一次性探针放 `temp/`，不入库、允许被清）。

## 它认哪两种形态

1. 行号形态 `文件.py:N` / `文件.py:N-M`：报 info，并给出符号化建议
   （`文件.py::符号`，符号按 AST 现算）。行号是易失的：并行开发下实测几十分钟
   就漂一次，所以行号形态本身不算错，但“指到空处/越界/文件不在”算死。
2. 符号形态 `文件.py::符号`（符号可带点，如 `类.方法`、`SPEC.emphasis`）：
   按 AST 核符号真的存在：函数 / 类（含嵌套）/ 模块级常量 / 模块级导入名。
   这是 FC-27 清单早就在用的纪律（理由里写符号名、不写行号，由判据钉符号存在）。
   mixin 拼起来的类（`secretary.Secretary.judge_proposition_form` 一类）按同前缀
   兄弟文件兜底，不按单文件 AST 判死。

## 不判的两种形态（以及为什么）

- 裸写 `` `模块.符号` ``（反引号里、没有 `.py` 锚点）：机器不判。同一个写法
  在本仓至少三种含义 —— 模块里的 Python 符号（`schema.TABLES`）、工具/动作名
  （`conductor.ack`）、包别名（`agent_f.manuscript`）；AST 名字表只覆盖第一种。
  实测对现盘按“名字找不到就报死”去判，会报出 690 条，绝大多数是后两种 ——
  假红会把判据训练成背景噪音。要机器判就写 `文件.py::符号`。
- `.noai-paths` 那种“行首路径 + 理由里一串反引号词”的清单形态：也不在这里重复。
  那里面的反引号既可能是符号，也可能是状态值、字典键、动作名（实测 36 个“缺符号”
  里绝大多数是后者），它的正确判据是“同一句写出出处 + 清单登记的 .py 文本里找得到”，
  已在 `tests/test_noai_gate.py::test_python_manifest_referenced_symbols_exist` 里。

## 语料 / 夹具里的“假指路”（逐条登记，不放过）

`tests/` 里有一类“长得像指路、但不是指路”的串：路径解析判据的输入（`code/p1.py:12`）、
临时树里刚造出来的假文件名（`probe.py::supply`、`tests/test_a.py::test_1`）、负控靶子
（`_STALE_REFS` 里那几条改前的错引用）、历史读数原文。它们必须保持原样 —— 改成真路径
就把判据的输入改了。这类串逐条登记在 `_CORPUS_LINE_REFS` / `_CORPUS_SYMBOL_REFS`
（键 = 写它的文件 + 指针原文，值 = 为什么是语料；符号形态拆成「路径 / 符号」两段，
键里不写 `.py::` 字面量 —— 本文件自己也在「代码字符串指针」那条判据的扫描面里），
本文件只对它报 info。

为什么是“逐条登记”而不是“找不到就放过”：后者会把真死引用一起放过（同一把尺在
`tests/` 里扫出的第一条真死引用就混在这批假路径里）。登记过期（那条语料已经不在盘上）
也报死 —— 与 `tests/test_every_pointer_string_in_code_resolves.py::_FIXTURE_ONLY`
的等额纪律同源：豁免面必须是一条会过期的可见登记。

## 什么算“死引用”

- 行号形态：目标文件不在盘上（`no-file`）；起点行越界（`out-of-range`）；
  起点行是空行（`blank-line`，即“指到空处”）；区间终点越界（`out-of-range`）。
  区间终点只核越界：仓库里的区间写法大量以空行收尾（段末空行是排版习惯）。
- 符号形态：目标文件不在盘上（`no-file`）；符号在该文件的 AST 名字表里找不到
  （`no-symbol`）。

绝对路径（盘符 / 前导斜杠）不算本仓指路，只报 info：`C:/outside/p1.py:12`
是“路径解析的示例”，不是“本仓某个文件第 12 行”。带 `<...>` / `{...}` / `*`
的写法是模式而不是具体文件，也只报 info（`pattern`）。

## 退出码（三态纪律，与 `noai_gate.py` / `check_wellformed.py` 同源）

```
0 = 查过了：所有指路都指得到（行号形态可能仍是行号，但至少指得到东西）
1 = 查过了：有死引用（逐条列出；行号形态的“活引用”只报 info）
2 = 没查成：根目录 / `src/agentflow` / `docs` 不在；某个源文件读不出 / 解析不了；
   给了 `--since` 但 git 不可用或 ref 无效。2 绝不折成 0。
```

`--self-test` 是反真空：造一棵最小树，先证明干净树报 0，再放一个假符号（必须报死），
最后删掉目标文件（必须报死）。任一条不成立 ⇒ 退出码 1（判据自身坏了）；造不出树 ⇒ 2。

## 用法（在 `agentflow/` 下）

```powershell
python -B scripts/check_doc_refs.py                    # 报死引用 + info 摘要
python -B scripts/check_doc_refs.py --info             # 连每条活的行号引用与符号建议一起列
python -B scripts/check_doc_refs.py --json out.json    # 机器可读（符号 info 全量；行号 info 需配 --info）
python -B scripts/check_doc_refs.py --self-test        # 反真空自检
python -B scripts/check_doc_refs.py --since HEAD~1     # 只查 git 改动集里的文件（需要 git）
python -B scripts/check_doc_refs.py --root <另一棵树>  # 换根（自检 / 别的仓库）
```
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys
import tempfile

_SKIP_PARTS = {"__pycache__", ".pytest_cache", "node_modules", ".git", "temp"}

#: 行号指路。`(?<![A-Za-z]:[\\/])` / `(?<![/\\])` 把绝对路径（`C:/x/y.py:12`、
#: `/abs.py:3`、`C:\x\y.py:12`）挡在外面：那是“路径怎么解析”的示例，不是本仓的指路。
_LINE_REF = re.compile(
    r"(?<![A-Za-z0-9_.])(?<![A-Za-z]:[\\/])(?<![/\\])"
    r"(?P<path>(?:[A-Za-z0-9_][\w.-]*/)*[A-Za-z0-9_][\w.-]*\.py)"
    r":(?P<start>\d+)(?:\s*[-–~]\s*(?P<end>\d+))?")
#: 显式符号指路：`文件.py::符号`（符号可带点）。
_SYMBOL_REF = re.compile(
    r"(?P<path>(?:[A-Za-z0-9_][\w.-]*/)*[A-Za-z0-9_][\w.-]*\.py)"
    r"::(?P<symbol>[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)")
#: 模式而不是具体文件（`specs/<role>.py` 一类）。
_PATTERN_MARKS = ("<", ">", "{", "}", "*", "?")
#: 占位文件名（`tests/x.py::test_...` 一类）：不是要解析的真实路径。
_PLACEHOLDER_STEMS = {"x", "y", "p1", "file"}

#: 语料 / 夹具里的“假指路”：两张表，键里都不写 `.py::` 字面量。
#:
#: 这些串不是指路，是判据的输入：路径解析示例、临时树里刚造的文件名、负控靶子、
#: 历史读数原文。它们必须逐字保持原样（改成真路径 = 改判据的输入），所以只能在这里
#: 逐条登记 —— 与“找不到就放过”的区别是：只有登记过的串被放过，新写下的假路径
#: 仍然报死；登记过期（那条语料不在盘上了）也报死（`_Checker.finish`）。
#:
#: 行号形态：键 =（写它的文件, 指针原文）。
_CORPUS_LINE_REFS: dict[tuple[str, str], str] = {
    ("tests/test_claimanatomy.py", "code/p1.py:12"):
        "夹具：`proof_location` 的路径解析示例（G1 吃的是行号后缀，不是本仓文件）",
    ("tests/test_cli_upgrade_c1_c8.py", "broken.py:1"):
        "夹具：临时树里刚造的 `broken.py`，断言的是拒信逐字带出这个位置",
    ("tests/test_cli_upgrade_c1_c8.py", "broken.py:42"):
        "夹具：同上（同一份临时树的第 42 行）",
    ("tests/test_coverage_claimanatomy.py", "code/p1.py:12"):
        "夹具：同 `test_claimanatomy.py` 的那份 `proof_location` 语料",
    ("tests/test_coverage_gates.py", "code/p1.py:12"):
        "语料：G1 五档路径里“相对路径”那一档的输入 / 期望串",
    ("tests/test_coverage_gates.py", "30/p1.py:9"):
        "语料：`_strip_line_suffix` 对 `C:/out12:30/p1.py:9` 的期望串（绝对路径被截出来的子串）",
    ("tests/test_g8_receipt.py", "code/p1.py:12"):
        "夹具：G8 回执判据的 `proof_location` 语料",
    ("tests/test_gates.py", "code/p1.py:12"):
        "夹具：收工门判据的 `proof_location` 语料",
    ("tests/test_mechanical_rewrite_guards.py", "x.py:123"):
        "语料：“通用判据”的示意写法（不是具体文件）",
    ("tests/test_readonly_output_channel.py", "code/p1.py:12"):
        "夹具：只读输出通道判据的 `proof_location` 语料",
    ("tests/test_wiring_readouts.py", "b.py:2"):
        "夹具：`program_census` 的 `where` 值（假文件名 + 假行号，断言原样透传）",
    ("tests/test_r5_orchestration_cost.py", "interactions.py:1134"):
        "负控串：`_STALE_REFS` 逐字记着改前那四处错引用（判据要求它们不许再出现在"
        "被点名的文件里）—— 它本身就是历史靶子",
    ("tests/test_r5_orchestration_cost.py", "src/agentflow/webui/server.py:491"):
        "出处：`temp/pytest-all` 这个旧 run 目录的来历（历史读数位置），不是现行指路",
}

#: 符号形态：键 =（写它的文件, 路径, 符号）。
#:
#: 为什么拆成三段、不写成 `文件.py::符号` 字面量：`scripts/check_doc_refs.py` 自己也在
#: `tests/test_every_pointer_string_in_code_resolves.py` 的“代码字符串指针”扫描面里，
#: 写成字面量会被那条判据当成一条新指针（它没有真身、会红）。
_CORPUS_SYMBOL_REFS: dict[tuple[str, str, str], str] = {
    ("tests/test_clean_invariant.py", "probe.py", "Thing._helper"):
        "夹具：临时树里造的 `probe.py` 类方法名（示例形态）",
    ("tests/test_clean_invariant.py", "probe.py", "_nobody_calls_me"):
        "夹具：临时树里造的零提及私有函数（死代码判据的靶子）",
    ("tests/test_clean_invariant.py", "probe.py", "supply"):
        "夹具：临时树里的“唯一定义”（正控）",
    ("tests/test_clean_invariant.py", "probe.py", "gone_target"):
        "夹具：临时树里的“目标已经不见了”（负控）",
    ("tests/test_clean_invariant.py", "probe.py", "vanished"):
        "夹具：临时树里被删掉的定义（负控）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "probe.py", "_nobody_calls_me"):
        "夹具登记表自身的键：`_FIXTURE_ONLY` 记的那条指针是测试造的",
    ("tests/test_every_pointer_string_in_code_resolves.py", "probe.py", "supply"):
        "夹具登记表自身的键：同上（临时树里的唯一定义）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "probe.py", "gone_target"):
        "夹具登记表自身的键：同上（靶子没了）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "probe.py", "vanished"):
        "夹具登记表自身的键：同上（定义被删）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "agent_d.py", "install_d_tools"):
        "夹具登记表自身的键：`_FIXTURE_ONLY` 记的假文档行（`tools_problems` 的正控）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "tests/test_a.py", "test_1"):
        "夹具登记表自身的键：分文件跑批时拼出来的假测试文件名",
    ("tests/test_every_pointer_string_in_code_resolves.py", "tests/test_a.py", "test_2"):
        "夹具登记表自身的键：同上",
    ("tests/test_every_pointer_string_in_code_resolves.py", "tests/test_b.py", "test_3"):
        "夹具登记表自身的键：同上",
    ("tests/test_every_pointer_string_in_code_resolves.py", "demo.py", "real_symbol"):
        "夹具登记表自身的键：`check_doc_refs.self_test()` 在临时树里造的 `demo.py` 正控",
    ("tests/test_every_pointer_string_in_code_resolves.py", "demo.py", "ghost_symbol"):
        "夹具登记表自身的键：`check_doc_refs.self_test()` 的负控（临时树里没有这个符号）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "mod.py", "also_never_defined"):
        "夹具：反真空用例里 `bad.py` 的字符串（docstring 里那一条，断言它不被收）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "mod.py", "hello"):
        "夹具：反真空用例的“好指针”（临时树里造的 `mod.py`）",
    ("tests/test_every_pointer_string_in_code_resolves.py", "mod.py", "never_defined"):
        "夹具：反真空用例的“坏符号”",
    ("tests/test_every_pointer_string_in_code_resolves.py", "nowhere.py", "hello"):
        "夹具：反真空用例的“坏文件”",
    ("tests/test_sysclean_design_side_is_current.py", "agent_d.py", "install_d_tools"):
        "夹具：假文档表里那一行（喂给 `tools_problems` 的正控，不是盘上真引用）",
    ("tests/test_the_full_suite_runner_splits_deterministically.py", "tests/test_a.py", "test_1"):
        "夹具：分文件跑批的假测试文件名（只用于拼 argv）",
    ("tests/test_the_full_suite_runner_splits_deterministically.py", "tests/test_a.py", "test_2"):
        "夹具：同上",
    ("tests/test_the_full_suite_runner_splits_deterministically.py", "tests/test_b.py", "test_3"):
        "夹具：同上",
}

_EXIT_OK = 0
_EXIT_DEAD = 1
_EXIT_UNCHECKED = 2


class _Symbols:
    """一个 `.py` 文件的 AST 名字表：模块级作用域 + 任意位置的 def/class/赋值。"""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.module: dict[str, str] = {}
        self.members: dict[str, set[str]] = {}
        self.anywhere: set[str] = set()
        self.spans: list[tuple[int, int, str, str]] = []
        self.parsed = False
        self._parse()

    @staticmethod
    def _scope_statements(body: list[ast.stmt]):
        """模块级语句，并把 `if __name__ == "__main__":` / `try:` 的体摊上来。"""
        for node in body:
            yield node
            if isinstance(node, (ast.If, ast.Try)):
                yield from _Symbols._scope_statements(node.body)
                for handler in getattr(node, "handlers", []):
                    yield from _Symbols._scope_statements(handler.body)
                yield from _Symbols._scope_statements(getattr(node, "orelse", []))
                yield from _Symbols._scope_statements(getattr(node, "finalbody", []))

    @staticmethod
    def _target_names(node: ast.stmt) -> list[str]:
        """一条赋值语句绑定的模块级名字（`x = 1` / `x: T = 1` / `a = b = 1`）。"""
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            return []
        out: list[str] = []
        for t in targets:
            if isinstance(t, ast.Name):
                out.append(t.id)
        return out

    def _parse(self) -> None:
        try:
            tree = ast.parse(self.path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            return
        self.parsed = True
        for node in self._scope_statements(tree.body):
            name = getattr(node, "name", None)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.module[str(name)] = "def"
                self.members[str(name)] = self._member_names(node.body)
                self._collect_spans(node, str(name))
            elif isinstance(node, ast.ClassDef):
                self.module[str(name)] = "class"
                self.members[str(name)] = self._member_names(node.body)
                self._collect_spans(node, str(name))
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    self.module.setdefault(alias.asname or alias.name.split(".")[0], "import")
            else:
                for name in self._target_names(node):
                    self.module[name] = "const"
                    self._append_span(node, name)
        if not self.module:
            self.module = {}

    def _member_names(self, body: list[ast.stmt]) -> set[str]:
        out: set[str] = set()
        for node in self._scope_statements(body):
            name = getattr(node, "name", None)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(str(name))
                out |= self._member_names(node.body)
            else:
                out.update(self._target_names(node))
        return out

    @staticmethod
    def _end(node: ast.AST) -> int:
        return int(getattr(node, "end_lineno", 0) or getattr(node, "lineno", 0) or 0)

    def _append_span(self, node: ast.AST, qual: str, kind: str = "def") -> None:
        start = int(getattr(node, "lineno", 0) or 0)
        end = self._end(node)
        if start and end >= start:
            self.spans.append((start, end, qual, kind))

    def _collect_spans(self, node: ast.AST, prefix: str) -> None:
        """把 def/class 以及它们体内的 def/class、常量都收进 spans（带限定名）。"""
        kind = "class" if isinstance(node, ast.ClassDef) else "def"
        self._append_span(node, prefix, kind)
        body = getattr(node, "body", [])
        for child in self._scope_statements(body):
            name = getattr(child, "name", None)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.anywhere.add(str(name))
                self._collect_spans(child, f"{prefix}.{name}")
            else:
                for name in self._target_names(child):
                    self._append_span(child, f"{prefix}.{name}", "const")

    def symbol_problem(self, dotted: str) -> str:
        """空串 = 符号存在；否则返回一句“为什么找不到”。"""
        segments = [s for s in dotted.split(".") if s]
        if not segments:
            return "符号是空串"
        first = segments[0]
        if first not in self.module:
            if first in self.anywhere:
                return "" if all(s in self.anywhere for s in segments[1:]) else "找不到"
            return "找不到"
        kind = self.module[first]
        if kind in ("const", "import"):
            return ""          # 字典键 / 属性面没法用 AST 核，见到容器名即算有落点
        available = self.members.get(first, set()) | self.anywhere
        for seg in segments[1:]:
            if seg not in available:
                return "找不到"
        return ""

    def suggest(self, line: int) -> str:
        """给行号引用一个符号化建议：最内层 def/class，或最近的模块级常量。"""
        best: tuple[int, str, str] | None = None
        for start, end, qual, kind in self.spans:
            if start <= line <= end and (best is None or start >= best[0]):
                best = (start, qual, kind)
        if best is not None:
            return f"{self.path.name}::{best[1]}"
        return ""


class _Index:
    """裸文件名索引：裸名唯一时才按裸名解析（`store.py` 能解到 `src/agentflow/store.py`）。"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.by_name: dict[str, list[pathlib.Path]] = {}
        self.repo = root.parent
        for base in (root, self.repo / "draft"):
            if not base.is_dir():
                continue
            for path in base.rglob("*.py"):
                if any(part in _SKIP_PARTS for part in path.parts):
                    continue
                self.by_name.setdefault(path.name, []).append(path)

    def resolve(self, raw: str, src_file: pathlib.Path) -> pathlib.Path | None:
        candidates = (src_file.parent / raw, self.root / raw, self.root / "src" / "agentflow" / raw,
                      self.root / "docs" / raw, self.root / "src" / raw, self.repo / raw)
        for cand in candidates:
            if cand.is_file():
                return cand
        hits = self.by_name.get(pathlib.PurePosixPath(raw).name, [])
        return hits[0] if len(hits) == 1 else None


class _Checker:
    def __init__(self, root: pathlib.Path) -> None:
        self.root = root
        self.index = _Index(root)
        self._symbols: dict[pathlib.Path, _Symbols] = {}
        self._families: dict[pathlib.Path, set[str]] = {}
        self.findings: list[dict] = []
        self.unchecked: list[str] = []
        self.scanned: list[pathlib.Path] = []
        self.line_live = 0
        self.line_live_symbolized = 0
        #: 这一趟真的撞上的语料登记（用于 `finish()` 的反向等额：登记过期要报死）。
        self.corpus_hits: set[tuple[str, str]] = set()

    def symbols_of(self, path: pathlib.Path) -> _Symbols:
        got = self._symbols.get(path)
        if got is None:
            got = _Symbols(path)
            self._symbols[path] = got
        return got

    def _family_names(self, target: pathlib.Path) -> set[str]:
        """同前缀的兄弟文件里的名字（`secretary*.py` 的 mixin 方法算 `secretary.Secretary.x`）。

        为什么需要这一档：角色秘书是 mixin 拼起来的（`Secretary(JudgeMixin, ...)`），
        文档按“对外那个类”写 `secretary.Secretary.judge_proposition_form` 是对的，
        但方法真身不在 `secretary.py` 里。只按单文件 AST 判会造出假红。
        """
        got = self._families.get(target)
        if got is not None:
            return got
        names: set[str] = set()
        if not target.stem.startswith("__"):
            for sibling in target.parent.glob(f"{target.stem}*.py"):
                names |= self.symbols_of(sibling).module.keys()
                names |= self.symbols_of(sibling).anywhere
                for members in self.symbols_of(sibling).members.values():
                    names |= members
        self._families[target] = names
        return names

    def symbol_problem(self, target: pathlib.Path, dotted: str) -> str:
        """空串 = 符号有落点；否则返回“为什么找不到”（含同族文件兜底）。"""
        if not dotted:
            return ""
        problem = self.symbols_of(target).symbol_problem(dotted)
        if not problem:
            return ""
        last = [s for s in dotted.split(".") if s][-1]
        return "" if last in self._family_names(target) else problem

    def rel(self, path: pathlib.Path) -> str:
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path).replace("\\", "/")

    def add(self, severity: str, kind: str, src: pathlib.Path, line: int,
            ref: str, reason: str, detail: str, suggestion: str = "") -> None:
        self.findings.append({"severity": severity, "kind": kind, "from": self.rel(src),
                              "line": line, "ref": ref, "reason": reason,
                              "detail": detail, "suggestion": suggestion})

    # ---------------------------------------------------------------- 源文件枚举
    def source_files(self, since: str) -> list[pathlib.Path]:
        src = self.root / "src" / "agentflow"
        docs = self.root / "docs"
        if not src.is_dir() or not docs.is_dir():
            raise FileNotFoundError(f"`src/agentflow` 或 `docs` 不在：{self.root}")
        files = [p for p in sorted(src.rglob("*.py"))
                 if not any(part in _SKIP_PARTS for part in p.parts)]
        # `tests/**/*.py`：判据与夹具的注释 / docstring 也长期指路（2026-11-23 纳入）。
        # 只收 `.py`；`tests/fixtures/**` 的 `.md` / `.json` / `.tsv` 是语料，不是指路。
        tests = self.root / "tests"
        if tests.is_dir():
            files += [p for p in sorted(tests.rglob("*.py"))
                      if not any(part in _SKIP_PARTS for part in p.parts)]
        files += sorted(docs.glob("*.md"))
        files += sorted(p for p in self.root.glob("*.md") if p.is_file())
        if since:
            changed = self._changed_since(since)
            files = [p for p in files if p.resolve() in changed]
        return files

    def _changed_since(self, since: str) -> set[pathlib.Path]:
        """git 改动集（`ref..HEAD` + 未提交 + 未跟踪）；任一步失败都抛异常，
        调用方据此报 2，绝不把“没查成”折成“空改动集”。"""
        try:
            top = subprocess.run(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"],
                                 capture_output=True, text=True, timeout=60)
            if top.returncode != 0:
                raise RuntimeError(top.stderr.strip() or "git rev-parse 失败")
            diff = subprocess.run(
                ["git", "-C", str(self.root), "diff", "--name-only", f"{since}..HEAD", "--", "."],
                capture_output=True, text=True, timeout=120)
            local = subprocess.run(
                ["git", "-C", str(self.root), "diff", "--name-only", "HEAD", "--", "."],
                capture_output=True, text=True, timeout=120)
            untracked = subprocess.run(
                ["git", "-C", str(self.root), "ls-files", "--others", "--exclude-standard", "--", "."],
                capture_output=True, text=True, timeout=120)
            if any(p.returncode != 0 for p in (diff, local, untracked)):
                raise RuntimeError("git diff / ls-files 失败")
        except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
            raise RuntimeError(f"git 不可用或 ref 无效（{since}）：{exc}") from exc
        names = {line.strip() for out in (diff.stdout, local.stdout, untracked.stdout)
                 for line in out.splitlines() if line.strip()}
        out: set[pathlib.Path] = set()
        for name in names:
            for cand in (self.root / name, self.root.parent / name):
                if cand.is_file():
                    out.add(cand.resolve())
        return out

    # ---------------------------------------------------------------- 扫描
    def scan(self, files: list[pathlib.Path], show_info: bool) -> None:
        for src in files:
            try:
                text = src.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                self.unchecked.append(f"{self.rel(src)}：读不出（{type(exc).__name__}: {exc}）")
                continue
            self.scanned.append(src)
            if src.suffix == ".py":
                self._scan_source(text, src, show_info)
            else:
                self._scan_doc(text, src, show_info)

    def finish(self, since: str) -> None:
        """扫描之后的两件事：语料登记的反向等额（只在全量扫描时做）。

        `--since` 是子集扫描：没改的语料文件本来就不在面里，按“登记过期”报死会是假红。
        `--root` 换到一棵没有 `tests/` 的树（自检 / 别的仓库）同理：文件都不在，跳过。
        """
        if since:
            return
        stale: list[tuple[str, str, str]] = []
        for (rel_src, ref), why in _CORPUS_LINE_REFS.items():
            if (rel_src, ref) not in self.corpus_hits:
                stale.append((rel_src, ref, why))
        for (rel_src, raw, symbol), why in _CORPUS_SYMBOL_REFS.items():
            if (rel_src, raw, symbol) not in self.corpus_hits:
                stale.append((rel_src, f"{raw}::{symbol}", why))
        for rel_src, whole, why in stale:
            src = self.root / rel_src
            if not src.is_file():
                continue
            try:
                text = src.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            line = text[:text.find(whole)].count("\n") + 1 if whole in text else 0
            self.add("dead", "corpus", src, line, whole, "stale-corpus-entry",
                     f"语料登记过期：这处假指路已经不在盘上（{why}）")

    def _emit(self, severity: str, kind: str, src: pathlib.Path, line: int, ref: str,
              reason: str, detail: str, suggestion: str, show_info: bool) -> None:
        if severity == "info" and not show_info:
            return
        self.add(severity, kind, src, line, ref, reason, detail, suggestion)

    def _scan_source(self, text: str, src: pathlib.Path, show_info: bool) -> None:
        self._scan_line_refs(text, src, show_info)
        self._scan_symbol_refs(text, src)

    def _scan_doc(self, text: str, src: pathlib.Path, show_info: bool) -> None:
        self._scan_line_refs(text, src, show_info)
        self._scan_symbol_refs(text, src)

    @staticmethod
    def _line_of(text: str, offset: int) -> int:
        return text.count("\n", 0, offset) + 1

    def _scan_line_refs(self, text: str, src: pathlib.Path, show_info: bool) -> None:
        for match in _LINE_REF.finditer(text):
            raw = match.group("path")
            line_no = self._line_of(text, match.start())
            rec = (src, line_no, match.group(0))
            key = (self.rel(src), match.group(0))
            if key in _CORPUS_LINE_REFS:
                self.corpus_hits.add(key)
                self._emit("info", "line", *rec, "corpus", _CORPUS_LINE_REFS[key], "", show_info)
                continue
            if any(mark in raw for mark in _PATTERN_MARKS):
                self._emit("info", "line", *rec, "pattern",
                           f"{raw} 是模式写法，不是具体文件", "", show_info)
                continue
            target = self.index.resolve(raw, src)
            if target is None:
                self._emit("dead", "line", *rec, "no-file",
                           f"盘上找不到 {raw}", "", show_info)
                continue
            try:
                body = target.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                self.unchecked.append(f"{self.rel(target)}：读不出（{type(exc).__name__}: {exc}）")
                continue
            start = int(match.group("start"))
            end = int(match.group("end")) if match.group("end") else 0
            reason = detail = ""
            if start > len(body):
                reason, detail = "out-of-range", f"{self.rel(target)} 共 {len(body)} 行，第 {start} 行越界"
            elif not body[start - 1].strip():
                reason, detail = "blank-line", f"{self.rel(target)} 第 {start} 行是空行（指到空处）"
            elif end and end > len(body):
                reason, detail = "out-of-range", f"{self.rel(target)} 共 {len(body)} 行，第 {end} 行越界"
            suggestion = self.symbols_of(target).suggest(start)
            if reason:
                self._emit("dead", "line", *rec, reason, detail, suggestion, show_info)
            else:
                self.line_live += 1
                if suggestion:
                    self.line_live_symbolized += 1
                self._emit("info", "line", *rec, "ok",
                           f"指得到；符号化写法：{suggestion or '（该行不在任何符号内）'}",
                           suggestion, show_info)

    def _symbol_ref(self, raw: str, symbol: str, src: pathlib.Path, line_no: int,
                    whole: str, after: str = "") -> None:
        key = (self.rel(src), raw, symbol)
        if key in _CORPUS_SYMBOL_REFS:
            self.corpus_hits.add(key)
            self.add("info", "symbol", src, line_no, whole, "corpus",
                     _CORPUS_SYMBOL_REFS[key], "")
            return
        stem = pathlib.PurePosixPath(raw).stem
        truncated = symbol.endswith("_") and after[:1] in (".", "…", "`", "")
        if (any(mark in raw for mark in _PATTERN_MARKS) or after[:1] in ("*", "…")
                or stem in _PLACEHOLDER_STEMS or truncated):
            self.add("info", "symbol", src, line_no, whole, "pattern",
                     f"{whole} 是模式 / 占位写法，不是具体符号", "")
            return
        target = self.index.resolve(raw, src)
        if target is None:
            self.add("dead", "symbol", src, line_no, whole, "no-file", f"盘上找不到 {raw}", "")
            return
        if not self.symbols_of(target).parsed:
            self.unchecked.append(f"{self.rel(target)}：AST 解析不了，`{symbol}` 没核")
            return
        problem = self.symbol_problem(target, symbol)
        if problem:
            self.add("dead", "symbol", src, line_no, whole, "no-symbol",
                     f"{self.rel(target)} 的 AST 名字表里找不到 `{symbol}`", "")
        else:
            self.add("info", "symbol", src, line_no, whole, "ok", "符号存在", "")

    def _scan_symbol_refs(self, text: str, src: pathlib.Path) -> None:
        for match in _SYMBOL_REF.finditer(text):
            line_no = self._line_of(text, match.start())
            self._symbol_ref(match.group("path"), match.group("symbol"), src, line_no,
                             match.group(0), text[match.end():match.end() + 1])


def run(root: pathlib.Path, since: str = "", show_info: bool = False) -> _Checker:
    """跑一遍检查（不打印）；异常表示“没查成”，由入口折成退出码 2。"""
    checker = _Checker(root)
    checker.scan(checker.source_files(since), show_info)
    checker.finish(since)
    return checker


def _summary(checker: _Checker) -> dict:
    dead = [f for f in checker.findings if f["severity"] == "dead"]
    info = [f for f in checker.findings if f["severity"] == "info"]
    by_kind: dict[str, int] = {}
    for one in dead:
        key = f"{one['kind']}:{one['reason']}"
        by_kind[key] = by_kind.get(key, 0) + 1
    return {"scanned_files": len(checker.scanned), "dead": len(dead), "info": len(info),
            "line_refs_live": checker.line_live,
            "line_refs_with_symbol": checker.line_live_symbolized,
            "dead_by_kind": by_kind, "unchecked": len(checker.unchecked)}


def _render(checker: _Checker, show_info: bool) -> list[str]:
    summary = _summary(checker)
    lines = [f"扫描 {summary['scanned_files']} 个文件"
             "（src/agentflow/**/*.py + tests/**/*.py + docs/*.md + *.md）",
             f"死引用 {summary['dead']} 条；info {summary['info']} 条"
             + (f"；没查成 {summary['unchecked']} 处" if summary["unchecked"] else "")]
    dead = [f for f in checker.findings if f["severity"] == "dead"]
    if dead:
        lines.append("")
        lines.append("死引用（逐条）：")
        for one in dead:
            hint = f"；建议改 {one['suggestion']}" if one["suggestion"] else ""
            lines.append(f"  [dead] {one['from']}:{one['line']} -> {one['ref']}"
                         f"  ({one['reason']}：{one['detail']}{hint})")
    info = [f for f in checker.findings if f["severity"] == "info"]
    if checker.line_live:
        lines.append("")
        lines.append(f"行号形态 {checker.line_live} 条活引用，其中 {checker.line_live_symbolized} 条"
                     "能给出 `文件::符号` 建议（不是错，但建议改成符号形态；`--info` 列全部）")
        if show_info:
            for one in [f for f in info if f["reason"] == "ok" and f["kind"] == "line"]:
                lines.append(f"  [info] {one['from']}:{one['line']} -> {one['ref']}"
                             f"  建议 {one['suggestion'] or '（无符号可指）'}")
    if checker.unchecked:
        lines.append("")
        lines.append(f"没查成的 {len(checker.unchecked)} 处（这些不是『查过、没问题』）：")
        lines.extend(f"  {one}" for one in checker.unchecked)
    lines.append("")
    if checker.unchecked:
        lines.append("结论：没查成（2）")
    elif dead:
        lines.append("结论：有死引用（1）—— 逐条见上，处置由人定")
    else:
        lines.append("结论：全部指得到（0）")
    return lines


def self_test() -> int:
    """反真空：干净树 ⇒ 0；假符号 ⇒ 死；删掉目标文件 ⇒ 死。任一条不成立 ⇒ 1。"""
    with tempfile.TemporaryDirectory(prefix="docrefs-selftest-") as tmp:
        root = pathlib.Path(tmp)
        (root / "src" / "agentflow").mkdir(parents=True)
        (root / "docs").mkdir()
        (root / "src" / "agentflow" / "demo.py").write_text(
            "REAL_CONST = 1\n\n\ndef real_symbol() -> int:\n    return REAL_CONST\n",
            encoding="utf-8", newline="\n")
        doc = root / "docs" / "DEMO.md"
        doc.write_text("好引用 `demo.py::real_symbol`。\n", encoding="utf-8", newline="\n")
        try:
            clean = run(root)
            ok_clean = not [f for f in clean.findings if f["severity"] == "dead"]
            doc.write_text("好引用 `demo.py::real_symbol`。\n坏引用 `demo.py::ghost_symbol`。\n",
                           encoding="utf-8", newline="\n")
            first = run(root)
            fake = [f for f in first.findings if f["severity"] == "dead"]
            ok_fake = len(fake) == 1 and "ghost_symbol" in fake[0]["ref"]
            (root / "src" / "agentflow" / "demo.py").unlink()
            second = run(root)
            gone = [f for f in second.findings
                    if f["severity"] == "dead" and f["reason"] == "no-file"]
            ok_gone = len(gone) == 2
        except Exception as exc:  # noqa: BLE001 —— 自检跑不起来就是没查成
            print(f"[self-test] 没查成：{exc}", file=sys.stderr)
            return _EXIT_UNCHECKED
        print(f"[self-test] 干净树 ⇒ 死 0 条（期望 0）{'OK' if ok_clean else 'FAIL'}")
        print(f"[self-test] 假符号 ⇒ 死 {len(fake)} 条（期望 1）{'OK' if ok_fake else 'FAIL'}")
        print(f"[self-test] 删目标文件 ⇒ no-file {len(gone)} 条（期望 2）"
              f"{'OK' if ok_gone else 'FAIL'}")
        return _EXIT_OK if (ok_clean and ok_fake and ok_gone) else _EXIT_DEAD


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="检查文档与注释里的行号/符号指路是否还指得到"
                    "（0=全指得到 / 1=有死引用 / 2=没查成）")
    parser.add_argument("--root", default="", help="换一棵树（缺省 = 本文件上一级）")
    parser.add_argument("--since", default="", help="只查这个 ref 之后的 git 改动集（需要 git）")
    parser.add_argument("--info", action="store_true", help="连每条活的行号引用与符号建议一起列")
    parser.add_argument("--json", default="", help="把完整读数写成 JSON")
    parser.add_argument("--self-test", action="store_true", help="跑反真空自检后退出")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    root = pathlib.Path(args.root).resolve() if args.root else pathlib.Path(__file__).resolve().parents[1]
    try:
        checker = run(root, args.since, args.info)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"没查成：{exc}", file=sys.stderr)
        return _EXIT_UNCHECKED
    print("\n".join(_render(checker, args.info)))
    if args.json:
        payload = {"root": str(root), "summary": _summary(checker),
                   "findings": checker.findings, "unchecked": checker.unchecked}
        try:
            pathlib.Path(args.json).write_text(
                json.dumps(payload, ensure_ascii=False, indent=1),
                encoding="utf-8", newline="\n")
        except OSError as exc:
            print(f"没查成：JSON 写不出去（{exc}）", file=sys.stderr)
            return _EXIT_UNCHECKED
        print(f"[json] {args.json}")
    if checker.unchecked:
        return _EXIT_UNCHECKED
    return _EXIT_DEAD if any(f["severity"] == "dead" for f in checker.findings) else _EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
