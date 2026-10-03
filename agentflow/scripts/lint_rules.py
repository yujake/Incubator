"""`agentflow` 的机械可查规则（linter）。

## 为什么要有它

`DEVELOPMENT.md` 里的规范分两类：能被机器判定的与只能靠人判的。
只有前者值得写成规则；把后者也塞进来，结果是一堆"看起来在检查、实际靠人读"的条目，
而它们会训练人忽略输出（这正是本项目反复吃过的亏：假报警比不校验更糟）。

所以本文件的每一条规则都满足三个条件：
1. 可判定 —— 输入是源码文本，输出是"命中/未命中"，不需要理解语义；
2. 给出行号与上下文 —— 命中不等于缺陷，交付的是线索；
3. 分级 —— `error`（确定是违规）/ `warning`（很可能是）/ `info`（只是数字）。

## 与 `tests/` 的分工

linter 管全仓库的形态（"有没有第二份名单"、"有没有静默失败"），
测试管行为。两者不重叠：linter 不做断言，测试不做全仓扫描。
所以 linter 的命中不阻塞测试，它只在 `scripts/release_check.py` 里参与判定。

## 退出码

`0` = 无 error（且非严格档）；`1` = 有 error，或 `--strict` 档下仍有 warning；
`2` = linter 自己没跑成（读不到源码树）。`warning` 只在 `--strict` 档升级成失败 ——
把"很可能是违规"与"确定违规"分开，是为了不让日常档的退出码失去信息量。

退出码是刻意的。参考体例（`draft/17-…md` §6）记录了一套成熟项目的教训：
"多数脚本不设退出码，于是『未报错』被误读为『无问题』"。
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import io
import json
import re
import sys
import tokenize
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

#: 源码根（相对仓库根）。
SRC_REL = Path("src") / "agentflow"
TESTS_REL = Path("tests")
SCRIPTS_REL = Path("scripts")

#: 这些文件允许出现"角色名清单"（它们是那份清单的权威定义处）。
ROLE_LIST_AUTHORITIES = {Path("src/agentflow/schema.py"), Path("src/agentflow/tools/__init__.py")}

#: 这些文件允许直接构造 `ToolRegistry`（它们就是工具层的装配点）。
REGISTRY_AUTHORITIES = {Path("src/agentflow/tools/__init__.py"), Path("src/agentflow/tools/base.py")}


@dataclass(frozen=True)
class Finding:
    rule: str
    level: str  # error | warning | info
    path: str
    line: int
    message: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {
            "rule": self.rule, "level": self.level, "path": self.path,
            "line": self.line, "message": self.message, "snippet": self.snippet,
        }


@dataclass
class LintReport:
    findings: list[Finding] = field(default_factory=list)
    scanned: dict[str, int] = field(default_factory=dict)
    rules_run: list[str] = field(default_factory=list)

    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def to_dict(self) -> dict:
        return {
            "errors": [f.to_dict() for f in self.errors()],
            "warnings": [f.to_dict() for f in self.warnings()],
            "infos": [f.to_dict() for f in self.findings if f.level == "info"],
            "error_count": len(self.errors()),
            "warning_count": len(self.warnings()),
            "info_count": len(self.findings) - len(self.errors()) - len(self.warnings()),
            "rules_run": list(self.rules_run),
            "scanned": dict(self.scanned),
        }


# ---------------------------------------------------------------- 规则实现


def _iter_py(root: Path, rel: Path) -> Iterator[Path]:
    base = root / rel
    if not base.exists():
        return
    for p in sorted(base.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def _is_in_main_block(lines: Sequence[str], lineno: int) -> bool:
    """该行是否位于某个 `if __name__ == \"__main__\"` 块之内（缩进比较，够用即可）。"""
    for i in range(lineno - 1, -1, -1):
        raw = lines[i]
        if not raw.strip():
            continue
        if raw.lstrip().startswith("if __name__") and "__main__" in raw:
            indent = len(raw) - len(raw.lstrip())
            cur = lines[lineno - 1]
            return len(cur) - len(cur.lstrip()) > indent
        # 遇到一个缩进更浅的顶层语句就说明不在块里了
        if raw[:1].strip() and not raw.startswith((" ", "\t")):
            return False
    return False


def _explained(lines: Sequence[str], i: int, j: int) -> str:
    """`lines[i..j]` 之间有没有解释性注释（含 `# noqa`）。

    为什么这条判据是必要的："有理由地忽略一个异常"与"静默吞掉一个异常"
    是两件事，而前者是正确的工程实践（例如"日志钩子坏了不该打断主流程"）。
    把两者一起报成 error，结果是 29 个 error 里有 22 个是故意的设计决定 ——
    那正是"假报警会训练人忽略告警"。

    所以判据收紧成：没有解释的吞掉才是违规。解释的载体是注释，
    且注释至少要有 4 个非空白字符（`#` 或 `# noqa` 这种不算解释）。
    """
    for k in range(i, min(j + 1, len(lines))):
        raw = lines[k]
        pos = raw.find("#")
        if pos < 0:
            continue
        body = raw[pos + 1 :].strip()
        # `noqa`/`type: ignore` 这类抑制标记本身也是"我知道这里有问题"的证据
        if len(body) >= 4:
            return body
    return ""


def rule_R001_bare_except_pass(root: Path) -> list[Finding]:
    """没有解释的 `except ...: pass` —— 静默吞掉异常。

    判定：`except` 行之后紧接着只有 `pass`（允许中间有空行与注释），
    且从 `except` 到 `pass` 之间没有任何解释性注释。

    这条规则本身经历过一次校准：第一版把所有 `except: pass` 都报成 error，
    在真实代码上产生 29 个 error，其中 22 个是故意且带注释的设计决定
    （"日志钩子坏了不该打断实验/攻坚/写稿/审校"）。那会让这条门在第一次运行时就
    失去可信度。现在只有没解释的才算违规 —— 这与本项目的通用纪律一致：
    闸门必须在真实样本上量过假阳性率才能上。
    """
    out: list[Finding] = []
    pat = re.compile(r"^\s*except\b")
    for p in _iter_py(root, SRC_REL):
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, raw in enumerate(lines):
            if not pat.match(raw):
                continue
            j = i + 1
            while j < len(lines) and (not lines[j].strip() or lines[j].strip().startswith("#")):
                j += 1
            if j < len(lines) and lines[j].strip() == "pass" and not _explained(lines, i, j):
                out.append(Finding(
                    "R001", "error", str(p.relative_to(root)), i + 1,
                    "**没有解释**地吞掉异常。若确实可以忽略，请在 `except` 行或 `pass` 前写明"
                    "为什么可以忽略（带 ≥4 字的注释，或 `# noqa: <规则>`）—— "
                    "'我知道这里会抛，且知道为什么可以不管'与'我没注意'必须能区分",
                    raw.strip(),
                ))
    return out


def rule_R002_none_folds_to_empty(root: Path) -> list[Finding]:
    """`if <x> is None:` 之后两行内 `return []` / `return {}` —— 把"没做"折叠成"没有"。

    这是本项目最贵的那个缺陷形态（`DESIGN-INTERACTIONS.md` §3.4）。
    允许例外：分支里同时出现 `checked`/`reason`/`raise` 的（说明它显式表达了"没做"）。

    ## 一次校准：带伴生原因的返回不算折叠

    真实假阳性：`tools/search_tools._literature_rows` 写成

    ```python
    if ctx.store is None:
        return [], "未配置 store（不是表坏了）"
    try:
        return ctx.store.rows("literature"), None
    except Exception as exc:
        return [], f"读 literature 表失败：{type(exc).__name__}: {exc}"
    ```

    这不是折叠 —— 它恰恰是三态纪律的正确形态：空容器 + 一个受控的 reason，
    "读到了 / 读了但表坏了 / 根本没配 store"三者分得开（该函数的 docstring 逐字解释了这件事）。
    旧的例外判据靠关键词（`reason`/`checked`）匹配，这个函数用的是中文理由字符串，
    于是被判为违规。校准后判据加上结构一条：`return []`/`{}` 后面跟着逗号
    （即返回的是一个 ≥2 元组）⇒ 它在带回一个伴生值 ⇒ 不算折叠。

    为什么结构判据比关键词更可靠：关键词列表永远列不全（中文/英文/别的字段名），
    而"有没有带回第二个东西"是写法本身，与命名无关。
    """
    out: list[Finding] = []
    pat = re.compile(r"^\s*if\s+.*\bis\s+None\s*:")
    for p in _iter_py(root, SRC_REL):
        lines = p.read_text(encoding="utf-8").splitlines()
        for i, raw in enumerate(lines):
            if not pat.match(raw):
                continue
            window = "\n".join(lines[i : i + 4])
            if not re.search(r"return\s+(\[\]|\{\})", window):
                continue
            if re.search(r"checked|reason|raise\b|fail\(", window):
                continue
            # 结构判据：`return [], <伴生值>` 且伴生值不是 `None` ⇒ 带回了一个 reason。
            #
            # 为什么必须把伴生值取出来判，而不是只判"有没有逗号"：
            # `return [], None` 也有逗号，但它在三态纪律上仍然是错的 ——
            # 调用方拿到 `None` 依然分不出"没做"与"做了没有"。
            # 只判逗号会把这条收紧边界一起放行，而那条边界正是"不许随便多返回一个东西就免检"。
            m = re.search(r"return\s+(?:\[\]|\{\})\s*,\s*([^\n,]*)", window)
            if m and m.group(1).strip() and m.group(1).strip() != "None":
                continue
            out.append(Finding(
                "R002", "warning", str(p.relative_to(root)), i + 1,
                "`is None` 之后直接返回空容器，看起来像把'没做'折叠成'没有结果'。"
                "如果是，请返回 `checked=False` + `reason`（或 `return [], \"<为什么>\"` 这种"
                "带回伴生原因的形态）；如果不是（例如'空输入理应得空输出'），"
                "请在紧邻的注释里写明理由",
                raw.strip(),
            ))
    return out


#: 允许"同名"的例外，每条都必须写清理由。
#:
#: 为什么需要例外清单而不是"删掉这条规则"：同名有时是刻意的
#: （工具模块的 `register` 是文档化的装配约定；`AnalysisReport` 是一对
#: "返回值对象 vs 登记行"的刻意区分）。但"刻意"必须是写下来的，
#: 这样新增的同名才会浮出来。清单本身可审阅、可反驳。
SAME_NAME_ALLOWED: dict[str, str] = {
    "register": "工具模块的装配约定：`_call_register` 明确支持 `register`/`install`/`ALL_TOOLS` 三种入口（tools/__init__.py）",
    "AnalysisReport": "刻意的两个类：`schema.AnalysisReport` 是登记行，`agent_c.AnalysisReport` 是返回对象（带 markdown 全文）——投影关系写在 persist() 里",
    "DEFAULT_BUDGET": "常量而非函数；`attack_tools.DEFAULT_BUDGET` 与各 agent 的引用是同一份的import，不是两份实现",
    "selftest": "每个模块各有自己的自检是这个项目的约定（`python -m agentflow.agent_x`）——它们检查的东西不同，同名是自然的",
    "tool_specs": "每个工具模块各自导出『未绑定 store 的清单』（审计/文档生成用）——同名同义，实现各自列自己的函数",
    "install": "与 `register` 同族的装配入口别名（`_call_register` 支持它）",
}


def _is_forwarder(path: Path, name: str) -> bool:
    """该模块里的 `name` 定义是不是一个转发（而不是一份独立实现）？

    判定（AST，够用即可）：
    - 函数体在剥掉 docstring 与前导的 `import` 之后，只剩一条语句，
      且该语句是 `return <something>.name(...)` 或 `return name(...)`；
    - 或者函数体只有一条 `return <导入自别处的同名对象>`。

    为什么要自动识别转发：`agent_d.detect_contradictions` 是刻意的转发
    （"唯一权威实现已移到 interactions.py"）。把它报成"两份实现"是假报警，
    而假报警会训练人忽略整条规则。

    为什么"前导 import"必须放行（一次真实的假阳性，记录在案）：
    `fetch.slugify` 与 `providers.normalize_doi` 合并时，转发体写成

    ```python
    def slugify(text, limit=60, fallback="untitled"):
        from .textutil import slugify as _impl   # 惰性 import：避免模块级循环依赖
        return _impl(text, limit=limit, fallback=fallback)
    ```

    函数体于是有两条语句，旧判据（"只有一条 return"）判它不是转发 ⇒
    报出"两份独立实现"的假 warning，而真实现其实只有一份。
    两条更宽松也更正确的口径：
      - 惰性 import 是实现细节，不是"第二份判据" —— 它没有重述任何规则；
      - 判据应当是"这个函数体除了取到别处的对象并原样调用之外什么都没做"，
        而不是"字面上只有一行"。

    仍然不放行在 return 之前有赋值/分支/`try` 的写法：那些能在转发之外
    悄悄改变语义（例如把异常吞掉、给参数补默认值、改返回值），
    而那正是"同名两份实现"要抓的东西。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, OSError):
        return False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            body = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            # 剥掉前导的 import（惰性 import 是转发体里唯一允许的"额外"语句）。
            # 只剥前导：`return ...` 之后再出现 import 是不可达代码，不算转发。
            #
            # 同时把 import 的别名记下来：转发体通常写成
            # `from .textutil import slugify as _impl` + `return _impl(...)`，
            # 于是 `return` 里出现的名字（`_impl`）不等于被转发的名字（`slugify`）。
            # 要求"别名解析回同名"而不是"随便调一个别处来的函数"：
            # 前者是"我引的是唯一权威实现"，后者无法证明它同义。
            aliases: dict[str, str] = {}
            while body and isinstance(body[0], (ast.Import, ast.ImportFrom)):
                for al in body.pop(0).names:
                    aliases[al.asname or al.name.split(".")[0]] = al.name
            if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
                return False
            # `return X.name(...)` / `return name(...)` / `return X.name`
            v = body[0].value
            if isinstance(v, ast.Call):
                v = v.func
            if isinstance(v, ast.Attribute):
                return v.attr == name
            if isinstance(v, ast.Name):
                return v.id == name or aliases.get(v.id) == name
            return False
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            tgt = node.targets[0]
            if isinstance(tgt, ast.Name) and tgt.id == name:
                return True  # `name = <导入的对象>`
    return False


def rule_R003_duplicate_public_defs(root: Path) -> list[Finding]:
    """同名公开函数/类在两个以上模块里各有一份（`slugify` / `normalize_doi` 的形态）。

    判定：模块级 `def <name>` / `class <name>`，名字不以 `_` 开头，
    且在两个以上不同模块里出现，且至少两个不是转发，且不在例外清单里。

    为什么要排掉转发与例外：
    - `agent_d.detect_contradictions` 是刻意的转发（"唯一权威实现已移到
      `interactions.py`"）—— 把它报成两份实现是假报警；
    - 工具模块的 `register` 是文档化的装配约定。
    两种都排掉之后，剩下的同名才值得人看一眼。
    """
    defs: dict[str, list[tuple[str, Path]]] = {}
    for p in _iter_py(root, SRC_REL):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not node.name.startswith("_"):
                    defs.setdefault(node.name, []).append((str(p.relative_to(root)), p))

    out: list[Finding] = []
    for name, entries in sorted(defs.items()):
        paths = {e[0] for e in entries}
        if len(paths) < 2:
            continue
        if name in SAME_NAME_ALLOWED:
            out.append(Finding(
                "R003", "info", sorted(paths)[0], 0,
                f"同名 `{name}` 在 {len(paths)} 个模块里出现，但它在例外清单里："
                f"{SAME_NAME_ALLOWED[name]}",
            ))
            continue
        real = [e for e in entries if not _is_forwarder(e[1], name)]
        if len({e[0] for e in real}) < 2:
            continue  # 只剩一份真实现，其余都是转发 ⇒ 已经合并过了
        for path in sorted({e[0] for e in real}):
            out.append(Finding(
                "R003", "warning", path, 0,
                f"公开名 `{name}` 在 {len({e[0] for e in real})} 个模块里有独立实现："
                f"{sorted({e[0] for e in real})}。若是同一判据的两份实现，必须合并成一份并让另一份转发"
                "（`textutil.slugify` vs `fetch.slugify`、`dedup.normalize_doi` vs "
                "`providers.normalize_doi` 都曾因此静默分歧）；若确实该分开，请加进 "
                "`SAME_NAME_ALLOWED` 并写清理由",
            ))
    return out


def rule_R004_registry_outside_tools(root: Path) -> list[Finding]:
    """在工具层之外直接构造 `ToolRegistry` —— 绕过装配期的角色校验。

    ## 已退休（`P-1`，本函数不再产生 findings）

    这条规则的存在理由只有一条：`build_registry` 之外构造的注册表没有核过
    `roles ⊆ schema.ROLES`（`agent_d.install_d_tools` 因此静默少过 3 个工具，
    `agent_e` / `agent_f` 的装配路径也一直带着这个缺口）。`P-1` 把判据下沉到
    `ToolRegistry.register*` 之后，"构造一张没核过角色的注册表"在结构上不可能 ——
    判据跑在注册那一刻，覆盖所有入口。于是这条规则的判据面变成真空：
    它还能报的每一处都已经是合规代码。

    与其让它继续以 warning 的形式报"已知的、被接受的缺口"（`agent_e.py` /
    `agent_f.py` 那两条），不如按 `R006` 的既有形态退休、不删号：
    编号保留（删号会让历史报告里的 "R004" 变成悬空引用），退休记录见
    `RETIRED_RULES`，`DEVELOPMENT.md` §6 的规则表同步。

    为什么"返回空列表"而不是删掉函数：见 `R006` 的同一条理由 ——
    删函数会连带改 `RULES` 的编号。

    ## 历史判据（保留在下面这段描述里，供读旧报告的人对照）

    命中判据曾经是：某个非脚手架函数的函数体里出现了 `ToolRegistry(...)` 调用，
    且同一函数体里既没有调 `REGISTRY_BUILDERS`（`build_registry`/`build_for_role`）
    也没有调 `ROLE_VALIDATOR_CALLS` 里登记的校验器，也不在 `R004_ALLOWED_SITES`
    的逐点例外里。四次校准（豁免脚手架 / 改 AST 匹配 / 豁免整条函数链 /
    豁免正规装配入口）的过程留在 git 历史里；四次校准的共同教训正是"这类规则
    只能在判据没有更好的落点时存在"—— 而 `P-1` 给了它一个更好的落点。
    """
    # 不产生 findings 是刻意的：判据面已由注册期校验承担（`P-1`，见 docstring）。
    return []


def rule_R005_hardcoded_role_list(root: Path) -> list[Finding]:
    """写死完整角色名单的第二份副本（FC-03）。

    ## 判据的校准（这条规则被改过一次）

    第一版的判据是"一行里出现 ≥4 个角色字母的字面量"，在真实代码上命中
    `cli.py`、`attack_tools.py`、`doc_tools.py` 等 6 处 —— 而它们全都是合法的：
    工具模块各自声明 `_ROLES = ("E","F","G")` 是刻意的（"哪几个角色该拿到本模块的工具"
    是模块级知识，不该集中到 schema）。把它们报成"第二份名单"是假报警。

    真正的缺陷形态是 `cli.cmd_tools` 里那种枚举全部角色的写法：
    `roles=("A","B","C","D")` —— 它看起来在"列出所有角色"，而实际上漏掉了 E–H，
    于是命令一边说"工具总数 55"、一边只列 4 个角色。

    所以判据收紧为：字面量里出现 ≥6 个不同角色字母（即它是在试图枚举"全部角色"）。
    子集声明（≤4）不报。
    """
    out: list[Finding] = []
    pat = re.compile(r"""['"]([A-H])['"](\s*,\s*['"]([A-H])['"]){5,}""")
    for p in _iter_py(root, SRC_REL):
        rel = p.relative_to(root)
        if str(rel).replace("\\", "/") in {str(x).replace("\\", "/") for x in ROLE_LIST_AUTHORITIES}:
            continue
        for i, raw in enumerate(p.read_text(encoding="utf-8").splitlines()):
            if pat.search(raw) and not raw.lstrip().startswith("#"):
                out.append(Finding(
                    "R005", "warning", str(rel), i + 1,
                    "出现了写死的**完整**角色名单字面量。角色名单的**唯一来源**是 `schema.ROLES`"
                    "（`tools.ROLES` 就是它）。枚举全部角色的第二份副本一旦漏掉新角色就会静默漂移"
                    "（`cli.cmd_tools` 曾因此只列出 A–D）",
                    raw.strip(),
                ))
    return out


def rule_R006_read_tool_touches_network(root: Path) -> list[Finding]:
    """`side_effect="read"` 的文件里出现网络/子进程/模型下载调用。

    ## 这条规则的校准（被改过一次）

    第一版是逐行报 warning，在真实代码上产生 19 条 warning，散落在
    `search_tools` / `ocr_tools` / `verify_tools` / `table_tools` / `agent_c` 里。
    问题在于判据是文件级共现：一个文件里只要既有 `side_effect="read"` 又有
    `subprocess`（哪怕那个 `read` 工具跟网络毫无关系），就会命中。
    19 条 warning 里绝大多数是这种无关共现 —— 而噪音会让整条规则被忽略。

    所以改成每个文件一条、级别 `info`：它交付的是"去这个文件里核一下
    具体那个工具"这个指针，而不是一个缺陷判定。真正的缺陷判定由人看过之后写进
    `DEVELOPMENT.md` 的清单，或者由工具层自己的测试断言（`test_tools_search_ocr.py`
    里对 `search.providers` 的 `side_effect` 断言就是那种形态）。

    为什么还留着它：INVENTORY 里 `search.providers`（声明 read 却发 HTTP）与
    `ocr.run`（声明 read 却下 100MB 模型）正是这样被发现的 —— 一个指向
    "值得看一眼的地方"的指针有真实价值，只要它不冒充缺陷。

    ## 已退休（`G-14`，本函数不再产生 findings）

    它交付的是"去这个文件里核一下具体那个工具"这个指针，而 R010 已经把同一件事
    逐工具做了（沿 handler 链做 AST 解析，点名到工具）。同一件事留两份的结果是：
    文件级那份在最该抓的文件上给不出是哪一个工具（一个文件里 55 个工具），
    而它的 info 行还会与 R010 的结论混在一起。所以 R006 停报，编号保留
    （删号会让历史报告里的 "R006" 变成悬空引用），退休记录见 `RETIRED_RULES`。

    ## 退休时的口径缺口（`R7-R6-1`，已补）

    退休声明写的是"判据移入 R010"，但 R010 此前只有两条子规则：
    "非 exec 而起子进程"（R010-a）与"声明 egress 而看不到网络"（R010-b）。
    于是 R006 问的那个方向 —— `side_effect="read"` / `external="none"` 的工具
    **实际联网** —— 在门里没有任何判据看得见（实测：人造树上改前的 R006 报 1 条、
    而 R010 报 0 条）。那正是"门被悄悄改松"的形态：退休声明说判据还在，其实少了半边。
    现在由 R010-c 接住（同一个函数、同一张 `_R010_NETWORK_MARKERS`、逐工具点名）。
    """
    # 不产生 findings 是刻意的：判据面已由 R010 逐工具承担（见 docstring 末节）。
    # 留这个函数体而不是删函数，是为了让 `RULES` 的编号与文档表不用改 —— 改编号
    # 会让历史报告与 DEVELOPMENT.md §6 的规则表对不上。
    return []


#: 已退休的规则：编号保留，但不再产生 findings。
#:
#: 为什么必须显式打印而不是悄悄不报：规则数从 10 变 9 会被读者当成"少了一条"，
#: 而"10 条里有一条不干活"如果不写出来，就会变成看起来没变、其实少了一条判据面——
#: 那正是本项目最忌讳的静默失效形态。`run_all` 的摘要行会把这张表一并打印。
#:
#: `R004` 进这张表的理由（`P-1`，与 `R006` 同族）：判据有了更好的落点
#: （注册期校验），于是这条替身规则只会报出合规代码。退休 ≠ 判据消失 ——
#: 判据现在跑在 `ToolRegistry.register` 里，覆盖全部入口。
RETIRED_RULES: dict[str, str] = {
    "R004": (
        "工具层外构造注册表 → 判据移到**注册期**（`P-1`：`ToolRegistry.register*` 各核一次 "
        "`roles ⊆ schema.ROLES`）；见 rule_R004_registry_outside_tools 的 docstring 末节"
    ),
    "R006": (
        "文件级共现 → 判据移入 R010（逐工具 AST，点名到工具）；"
        "两个方向都在 R010 里：非 exec 而起子进程（R010-a）、声明 `none` 而链里联网（R010-c）、"
        "声明 `egress` 而看不到网络（R010-b）；见 rule_R006 与 rule_R010 的 docstring"
    ),
}


def _load_vocab_census():
    """加载 `tools/vocab_census.py`（独立脚本，不 import agentflow，可对任意 root 跑）。"""
    p = Path(__file__).resolve().parents[1] / "tools" / "vocab_census.py"
    if not p.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_vocab_census_for_lint", p)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def rule_R011_dead_vocab(root: Path) -> list[Finding]:
    """受控词表里的死取值：登记了、而 `src/` 里找不到产出点（`G-26` 第二步）。

    ## 两栏分开、级别不同（`P-22` / `P-23` 的裁定）

    登记表只有一处（`tools/vocab_census.py` 的 `RESERVED_VALUES`），而普查把它读成两栏：

    | 栏 | 含义 | 级别 | 为什么这个级别 |
    |---|---|---|---|
    | 栏一 `reserved` | 无产出、但已登记为预留（每条都写了理由与将来谁接线） | info | 这是人的口径裁定，不是缺陷：用红灯逼一个"未经裁决的改法"是本项目明确否掉的形态 |
    | 栏二 `unclaimed` | 无产出、且无人认领 | error | 它没有任何理由留在词表里：要么补产出、要么登记为预留、要么删值 —— 三选一之前它就是一条静默的谎（审计看到"有这个取值"而代码永远给不出） |

    两栏永不合并：`reserved` 不是"通过"，它必须照样打印出来（含理由）——
    静默豁免是本项目最忌的形态。`reserved + unclaimed == dead` 这条恒等式
    在这里机械核对：它不成立说明普查那一侧漏了值，那时报 error 而不是"看起来干净"。

    ## 另外两种必须出现在输出里的东西

    - 栏一附（`registered_not_dead`）：登记为预留、而机械普查今天看不见它是死取值的
      那些（同形不同义，或登记已过期）。它们必须打印 —— 否则那几条登记在输出里
      查无此条，等于登记表自己骗自己；
    - 已知缺口：反向（漏词表：代码产出了不在词表里的字面量）本版未实现。
      把"没查"与"查过没问题"折叠成同一个沉默，正是本项目最忌讳的形态。

    ## 扫描器自己失效时也必须说话，而且不许与"查过了、干净"同形（`H-7`）

    普查工具的反真空下限（词表数 / 产出点数）不满足时 `checked=False`。
    这一档与"读不到普查工具"一起构成两条"没查成"退路：它们报 `warning`，
    不报 `info`。理由是三态纪律在本仓库里的统一口径 —— `unknown`（没查成）绝不
    等于 `clean`（查过了、没问题），而 `info` 在发布门上恰好是"看不见"的那一档
    （`item_linter` 只看 `error`），于是"探测器坏了"与"词表很干净"会印成同一个样子。

    为什么不是 `error`（登记册里 `H-7` 的另一种口径）：这两条是常驻的仪器状态，
    不是任何一次改动造成的缺口；把它们升成 `error` 会让发布门在任何一次
    `vocab_census` 读不到时立刻红，而那时该做的是修仪器（或如实在报告里
    声明缺了这一项），不是让一条永远红的灯常驻。`warning` 让它在 `--strict`
    档与 `item_linter` 的严格档里都可见，又不会把"没查成"说成"被检对象有缺陷"。

    第三条"没查成"是反向的已知缺口（漏词表：代码产出了不在词表里的字面量）
    —— 它是本版明确未实现的能力，与上面两条仪器状态不同：它今天结构上
    不可能变绿，钉成 `warning` 就是造一条永远红的灯。所以它保持 `info`，
    但必须逐字打印（静默豁免才是本仓库最忌的形态）。
    """
    mod = _load_vocab_census()
    if mod is None:
        return [Finding(
            "R011", "warning", "tools/vocab_census.py", 1,
            "读不到词表普查工具 ⇒ 这一条没查成（不是『没有死取值』）—— "
            "按三态纪律，『没查成』不许与『查过了、干净』同形，所以这里是 warning 而不是 info",
        )]
    result = mod.census(root)
    if not result["checked"]:
        return [Finding(
            "R011", "warning", "src/agentflow/schema.py", 1,
            f"词表普查没查成：{result['reason']} ⇒ 没查到不等于没有死取值"
            "（`checked=False` 是仪器状态，不是被检对象的缺口；但它也绝不是『干净』）",
        )]
    out: list[Finding] = []
    reserved = result["reserved"]
    unclaimed = result["unclaimed"]
    registered_not_dead = result["registered_not_dead"]
    reasons = result.get("reserved_reasons") or {}

    # ---- 恒等式先核：reserved + unclaimed 必须恰好等于全部死取值。
    # 不成立 ⇒ 普查那一侧漏了值（口径漂了），这时"两栏都干净"是个假象。
    if result["reserved_total"] + result["unclaimed_total"] != result["dead_total"]:
        out.append(Finding(
            "R011", "error", "tools/vocab_census.py", 1,
            "普查的两栏之和对不上死取值总数："
            f"reserved {result['reserved_total']} + unclaimed {result['unclaimed_total']} "
            f"!= dead {result['dead_total']} ⇒ 有死取值没有落进任何一栏，"
            "本次的『两栏干净』不可信（这道判据本身漏了东西）",
        ))

    # ---- 栏二（error）：无产出且无人认领
    for name, values in sorted(unclaimed.items()):
        out.append(Finding(
            "R011", "error", "src/agentflow/schema.py", 1,
            f"[栏二 unclaimed] {name} 里有 {len(values)} 个取值在 src/ 里找不到产出点：{values}"
            "（无产出且无人认领 ⇒ 它没有任何理由留在词表里：补产出 / 登记为预留 / 删值，"
            "`tools/vocab_census.py` 的 `RESERVED_VALUES` 是预留登记的唯一落点）",
        ))

    # ---- 栏一（info）：无产出但已登记为预留（不是"通过"，照样逐条打印）
    for name, values in sorted(reserved.items()):
        for v in values:
            why = reasons.get(f"{name}.{v}", "（未写理由：登记表要求写）")
            out.append(Finding(
                "R011", "info", "src/agentflow/schema.py", 1,
                f"[栏一 reserved] {name}.{v}：无产出但已登记为预留 —— {why}",
            ))

    # ---- 栏一附（info）：登记了、而今天普查不认为它是死取值
    for name, values in sorted(registered_not_dead.items()):
        for v in values:
            why = reasons.get(f"{name}.{v}", "（未写理由：登记表要求写）")
            out.append(Finding(
                "R011", "info", "tools/vocab_census.py", 1,
                f"[栏一附] {name}.{v}：登记为预留，而本次普查看不见它是死取值"
                f"（同形不同义，或登记已过期）—— {why}",
            ))

    out.append(Finding(
        "R011", "info", "tools/vocab_census.py", 1,
        f"两栏计数（分开给，不许用合计代替分栏）：reserved {result['reserved_total']} / "
        f"unclaimed {result['unclaimed_total']} / 栏一附 {result['registered_not_dead_total']}；"
        f"死取值合计 {result['dead_total']}（诊断值）",
    ))
    out.append(Finding("R011", "info", "tools/vocab_census.py", 1, result["known_gap"]))
    return out


def rule_R007_missing_docstring(root: Path, *, strict: bool = False) -> list[Finding]:
    """公开函数/方法缺 docstring。

    ## 这个"数"为什么不能是一个全局数字（校准）

    第一版只打印 `公开函数 497 个，其中 188 个没有 docstring` —— 一个不可行动的数字：
    它既没说是哪些文件，也没说"新写的函数该不该补"。而 `DEVELOPMENT.md` §2.4
    是一条成文的规则（"每个公开函数必须有 docstring 且含'为什么'段落"）。
    一条成文的规则配一个不可行动的数字，等于这条规则没有门。

    ## 校准后的形态：按模块给数字 + `--strict` 时升级为 warning

    - 默认（日常 `python scripts/lint_rules.py`）：一条 `info`，消息里带
      按缺失数排序的前 5 个模块（让人一眼看到该从哪下手）+ 全量数字。
      为什么不逐条报 `warning`：188 条会把整份报告淹掉，而噪音会让整条规则被忽略
      （R001/R006 都栽在这上面）。
    - `--strict`（发布级）：逐模块一条 `warning`。这样"发布"与"日常"
      对同一条规则的强度不同，而这个差别是显式写下来的，不是靠人记得。

    为什么不直接把日常级别升成 warning：那会让 188 条警告常驻输出，
    而 `release_check.py` 的第 5 项只看 `error` —— 于是"升级"实际上什么也没挡住，
    只制造了噪音。"更严"必须体现在判据上，不是体现在级别上。
    """
    per_file: dict[str, tuple[int, int]] = {}
    for p in _iter_py(root, SRC_REL):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        total = missing = 0
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name.startswith("_"):
                    continue
                total += 1
                if not ast.get_docstring(node):
                    missing += 1
        if total:
            per_file[str(p.relative_to(root)).replace("\\", "/")] = (total, missing)

    grand_total = sum(t for t, _ in per_file.values())
    grand_missing = sum(m for _, m in per_file.values())
    if not grand_total:
        return []

    offenders = sorted(
        ((rel, t, m) for rel, (t, m) in per_file.items() if m),
        key=lambda x: (-x[2], x[0]),
    )
    if strict:
        return [
            Finding("R007", "warning", rel, 0,
                    f"{rel}：公开函数 {t} 个，{m} 个没有 docstring。"
                    "发布级判据（`--strict`）要求每个公开函数都有 docstring —— "
                    "`DEVELOPMENT.md` §2.4 是成文规则，成文规则必须配得上一条门")
            for rel, t, m in offenders
        ]
    head = "、".join(f"{rel}={m}/{t}" for rel, t, m in offenders[:5])
    return [Finding(
        "R007", "info", str(SRC_REL), 0,
        f"公开函数 {grand_total} 个，其中 {grand_missing} 个没有 docstring"
        f"；缺失最多的 5 个模块：{head or '（无）'}"
        "（用 `--strict` 可把本项升为逐模块 warning；日常不逐条报是为了不让输出被淹掉）",
    )]


def rule_R008_scripts_without_exit_code(root: Path) -> list[Finding]:
    """`scripts/` 下的脚本没有 `sys.exit` / `raise SystemExit`。

    参考体例的教训："未报错"被误读为"无问题"（多数脚本不设退出码，
    于是 5 行 ~5100 字的假阴性没人发现）。检查脚本必须有退出码。

    ## 为什么分两级（`scripts/` 是 error，仓库根的 `tools/` 是 warning）

    - `scripts/` 里放的是发布门（`lint_rules` / `noai_gate` / `release_check`）。
      它们没有退出码，"没报错"就等于"通过" —— 那是不可接受的，所以是 error。
    - 仓库根的 `tools/`（注意：不是 `src/agentflow/tools/`）放的是开发期探测脚本
      （`probe_*.py` / `inspect_*.py` / `smoke_*.py`）。它们是人手工跑来看一眼的，
      没有退出码不影响任何自动化判据 ⇒ warning，提醒而不阻塞。

    这个区分是刻意的：把开发期草稿与发布门混成同一级，会让这条规则在第一次运行时
    就产生一堆"其实没关系"的红灯 —— 而红灯被训练成背景噪音之后，真正的缺陷也会被忽略。
    """
    out: list[Finding] = []
    roots = (
        (root / SCRIPTS_REL, "error", "发布门"),
        (root / "tools", "warning", "开发期探测脚本"),
    )
    for base, level, why in roots:
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if p.name == "__init__.py":
                continue
            if "__pycache__" in p.parts:
                continue
            text = p.read_text(encoding="utf-8")
            if "sys.exit" in text or "SystemExit" in text:
                continue
            out.append(Finding(
                "R008", level, str(p.relative_to(root)), 0,
                f"这{why}没有退出码 ⇒ 无法区分'检查通过'与'脚本根本没跑成'。"
                "自动化的判据必须是 0=通过 / 1=发现问题 / 2=检查器自身失败 的三档退出码",
            ))
    return out


# ------------------------------------------------------------------- R010 用到的表

#: 工具层源码的位置（相对仓库根）。R010 只扫这里 —— 工具实现在 `src/agentflow/tools/`。
_R010_TOOLS_REL = SRC_REL / "tools"

#: 起子进程的标记（按工具判，不按文件判）。
#:
#: 为什么 `shutil.which` 不算：它只查 PATH、不起进程。`verify.detect_verifier`
#: 的注释把两者并列写过，但轴的定义是"在宿主上执行一个程序"，
#: which 不满足它 —— 判据贴着定义走，而不是贴着注释里的词走。
_R010_PROCESS_MARKERS: tuple[tuple[str, str], ...] = (
    ("subprocess", "起子进程"),
    ("os.system", "起 shell 命令"),
    ("os.popen", "起 shell 管道"),
    ("pty.spawn", "起伪终端进程"),
)

#: 网络调用的标记。与 R006 的标记各有各的一份是刻意的：
#: R006 的级别与命中集合在 B2 里不许变（改宽它就是制造噪音，见 P15），
#: 所以新增的标记只加在这一份里，R006 一个字符都不动。
#:
#: 判据是"点号路径以标记为尾，或标记是不带点的单段且与路径的首段相等"。
#: 两条纪律都是被实测的假阳性换来的：
#:   - 用"任一段相等"时，`os.walk` 会被 `os.system` 命中（首段都是 `os`）
#:     ⇒ `fs.list` / `fs.write` / `fs.stat` / `fs.search` 四个根本不起进程的工具
#:     被判成"起 shell 命令"；
#:   - 用子串包含时，`os.walk` 同样被 `os.system` 命中（末段的字符比较）。
#: 假阳性会让整条规则被忽略（P15），所以判据贴着点号段走。
_R010_NETWORK_MARKERS: tuple[tuple[str, str], ...] = (
    ("urllib", "urllib（R006 同款标记）"),
    ("http.client", "http.client（R006 同款标记）"),
    ("socket", "原始 socket（R006 同款标记）"),
    ("subprocess", "R006 把 subprocess 也算进网络标记，这里沿用（见 R006）"),
    ("requests", "requests（R006 同款标记）"),
    ("httpx", "httpx（R006 同款标记）"),
    ("easyocr", "easyocr 首次构造 Reader 要下模型（R006 同款标记）"),
    ("urlopen", "HTTP 入口"),
    ("urlretrieve", "HTTP 入口"),
    ("http_get_json", "provider 层的 HTTP 入口（`search.providers` 走 `P.http_get_json`）"),
    ("http_post", "provider 层的 HTTP 入口"),
    ("download", "下载器入口（`search.download` 走 `downloader.download`）"),
    ("search", "provider 对象的检索入口（`search.literature` 走 `prov.search`）"),
)

#: R010-a 的例外清单：声明 `external != "exec"` 而 handler 链里起子进程的工具。
#:
#: 每一条都必须写理由，且理由要回答同一个问题：它起进程这件事，
#: 满不满足轴的定义 —— "在宿主上执行一个由调用方决定内容的程序"。
#: 不满足 ⇒ 它按定义不是 `exec`，而 lint 的字面判据（"出现起子进程的调用"）
#: 仍然会命中它。把两者一起读才是 P-13 §10 第 1 条要的人裁。
#:
#: `tests/test_lint_rules.py::test_r010_allowed_sites_still_exist` 会断言
#: 每个键都真的指向一个"确实起进程、且确实没声明 exec"的工具 ——
#: 否则例外清单会静默腐烂成一张"永不生效的豁免"。
_R010_ALLOWED_SITES: dict[str, str] = {}
#: 2026-10-03（`draft/37` §82）删掉了这里唯一的一条：`verify.detect_verifier`。
#: 它此前"按定义不是 exec、却仍被 `subprocess` 标记命中"，所以登记为例外；
#: 探测现在只是转发 `agentflow.toolchain.probe_checkers`（查找口径与三态都搬到那一处定义），
#: 本工具不再自己起子进程 ⇒ 例外不再命中，而本文件末尾的判据
#: （`tests/test_lint_rules.py::test_r010_allowed_sites_still_exist`）要求
#: 例外清单里的每一条都必须在真实树上命中 —— 所以是删掉它，而不是留着一条永不生效的豁免。

#: R010-a 的已知漏检（这条规则看不见、但按定义/按事实确实会起进程的工具）。
#:
#: 为什么要把漏检写下来：三态纪律要求"没查成"与"查过了没问题"分开。
#: 这三个工具没有被 R010-a 命中，原因是转发链断在工具层之外：
#:
#: - `verify.run_experiment` 的 handler 调 `_run_experiment_tool`，后者在本文件里
#:   只是转发到 `agent_e.AgentE.run_experiment`（`agent_e.py` 的 `subprocess.run`）——
#:   工具层里没有任何一行叫 subprocess 的代码；
#: - `ocr.backends` 的 handler 调 `_h_backends` → `PytesseractBackend.available()`
#:   → `pytesseract.get_tesseract_version()`，而起进程的是那个第三方库内部，
#:   源码里没有 `subprocess` 这个字。
#:
#: 两个都是"起进程在工具层之外"，所以本规则的字面判据看不到它们 ——
#: 这不是"它们没问题"，而是"这条规则查不到"。用户/下一个执行者必须知道这件事，
#: 所以它是报告里的正常条目，不是注释里的一句话。
_R010_KNOWN_GAPS: dict[str, str] = {
    "verify.run_experiment": "起进程发生在 `agent_e.AgentE.run_experiment`（工具层之外的文件），工具层里没有 subprocess 字面",
    "ocr.backends": (
        "按定义不是 exec（它起的是写死的 `tesseract --version`，调用方只选后端名），"
        "而起进程发生在第三方库 `pytesseract.get_tesseract_version()` 内部 —— "
        "工具层源码里没有 subprocess 字面，所以本规则看不见它。"
        "P-13 §4.3 第 9 条把它列在 B3 的迁移清单里（新值 `write_local + exec`）"
    ),
}

#: R010-b（声明 `egress` 而看不到网络调用）的已知盲区。
#:
#: 为什么需要这张表而不是改声明或加 `noqa`：这一条的特征是
#: "声明是对的、瞎的是检测器" —— 出网发生在第三方库内部，工具层源码里没有
#: 任何网络字面量，所以 R010-b 的字面判据结构上看不见它。三种处置里：
#:
#: - 改声明（把 `ocr.run` 降成 `none`）：那是制造假话，直接违反 `P-13` 里
#:   "声明必须正确"这一条；
#: - `noqa` 静默：本项目的成文教训是"静默豁免是最难查的形态"（`P15` 同族）；
#: - 登记 + 照旧打印 info（本表）：warning 归零，而"这一段我核不了"仍然可见。
#:
#: 每一条都必须写清"哪一段核不了"。`test_r010_egress_blind_spots_still_exist`
#: 会断言每个键都真的还命中 R010-b（否则这张表会腐烂成"永不生效的豁免"，
#: 与 `R004_ALLOWED_SITES` 退场时的形态一样）。
_R010_EGRESS_BLIND_SPOTS: dict[str, str] = {
    "ocr.run": (
        "它声明 `external='egress'` 是**对的**：首次构造 easyocr 的 Reader 时会"
        "下载约 100MB 的识别模型。而那个下载发生在第三方库 `easyocr` 内部，"
        "工具层源码里没有任何网络字面量（没有 urllib/requests/httpx/socket 这些标记）"
        "⇒ R010-b 的判据结构上到不了那一段。"
        "它与已登记的 `ocr.backends` 那条同族（都是「事情发生在库内部」）。"
        "本机补充实测：那个模型源的域名 TLS 证书链验证失败 ⇒ 「下不来」是可复现的，"
        "但这不改变「声明是对的」这个结论。"
    ),
}


#: R010-c（声明 `none` 而链里有网络标记）的**假阳性登记表**。
#:
#: 为什么需要它：R010-c 的判据是"`_R010_NETWORK_MARKERS` 里的标记在 handler 链里可达"，
#: 而那张标记表里有两条是按**末段相等**匹配的（`search` / `download`）——
#: 它们是为"provider 对象的检索入口"加的（`prov.search` / `downloader.download`），
#: 代价是 `re.search` / `rx.search` 这种**正则方法**也会被算成网络入口。
#: 实测（补回这个方向的那一刻，真实树 58 条声明）：4 个候选里 2 个是这种正则假阳性
#: （`doc.build_document` 的 `re.search`、`fs.search` 的 `rx.search`）。
#:
#: 三种处置里选哪一种（与 `_R010_EGRESS_BLIND_SPOTS` 同一套取舍）：
#: - 改标记表：`search` 是**两条方向共用**的（R010-b 靠它认 `prov.search`），
#:   动它就是动既有判据 —— 本批的硬约束是不许放宽任何既有规则；
#: - `noqa` 静默：本项目的成文教训是"静默豁免是最难查的形态"（`P15` 同族）；
#: - 登记 + 照旧打印 info（本表）：warning 归零，而"这一条我判不了"仍然可见。
#:
#: 每一条都必须写清"这个标记命中的到底是什么"。它与 `_R010_KNOWN_GAPS`（链断了看不见）、
#: `_R010_EGRESS_BLIND_SPOTS`（出网在库内部）是三张不同的表：本表说的是
#: "**标记命中了，但那个东西不是网络**"——把三张表合并会让"哪一段我核不了"失去答案。
_R010_NETWORK_FALSE_POSITIVES: dict[str, str] = {
    "doc.build_document": (
        "命中的是 `re.search`（标准库正则，`import re` 在文件顶部）—— "
        "`_R010_NETWORK_MARKERS` 的 `search` 那一条按末段相等匹配（它要认的是 "
        "`prov.search` 这个 provider 检索入口），于是任何 `X.search(...)` 都会命中它。"
        "这个工具本身不出网：它的 handler 链里只有正则匹配与文本处理"
    ),
    "fs.search": (
        "命中的是 `rx.search`（`rx = re.compile(pattern)` 之后的匹配调用，同 `re.search` 的形态）"
        "—— 同一条末段相等的 `search` 标记。这个工具本身不出网：它在本地目录里做模式匹配"
    ),
    "verify.detect_verifier": (
        "命中的是 `subprocess` —— 它是 `subprocess.run(['lean', '--version'])` 这一类"
        "起子进程的调用。`subprocess` 出现在 `_R010_NETWORK_MARKERS` 里是 R006 当年的口径"
        "（那一张表按『网络 / 子进程 / 模型下载』三类共用），所以按这张表它算网络标记；"
        "但 R010-c 这一档问的是『会不会出网』，而起进程不出网。"
        "它按 R010-a 已经逐条登记在 `_R010_ALLOWED_SITES` 里（按轴的定义不是 exec），"
        "在 R010-c 这里属于标记表的已知串味 ⇒ 登记为假阳性，以 info 继续可见"
    ),
}


def _r010_name_of(node: ast.AST) -> str:
    """`Name` / `Attribute` 的文本形式（`subprocess.run` / `_h_run`）；其余返回空串。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _r010_name_of(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _r010_calls(node: ast.AST) -> list[str]:
    """一个表达式里出现的全部被调用/被引用的名字（含 `X.y` 的两种写法）。"""
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            nm = _r010_name_of(sub.func)
            if nm:
                out.append(nm)
                out.append(nm.split(".")[-1])
    return out


def _r010_kw(call: ast.Call, name: str) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _r010_external_literal(node: ast.Call) -> str:
    """一条声明的 `external` 字面量 ⇒ 字符串；两个真实写法都认，都没写则给空串。

    为什么是两个名字：`ToolSpec` 的字段叫 `declared_external`
    （`external` 是属性名，写进构造器会 `TypeError`），而 `@tool` 装饰器的
    关键字参数就叫 `external`。只认一个的后果不是报错，是把声明读成默认值
    `none`，于是声明 `exec` 的工具会以 `none` 参与 R010-a 判定 ——
    "声明错了"与"声明没被读见"在报告里长得一模一样（三态纪律要防的正是它）。
    """
    for name in ("declared_external", "external"):
        got = _r010_kw(node, name)
        if got is not None:
            return _r010_literal(got, "")
    return ""


def _r010_literal(node: ast.AST | None, default: str) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else default


def _r010_specs(tree: ast.Module, defs: Mapping[str, ast.AST]) -> list[dict]:
    """读出模块里每条工具声明：`{name, side_effect, external, roots, line}`。

    `defs` 是模块级函数/类的名字表，用来把 handler 里出现的名字解析成
    同文件内的实现（`lambda: ok(detect_verifier())` 的 handler 因此能
    查到 `detect_verifier` 里去 —— 转发型 handler 不算"没核对"）。

    只认字面量（名字与两个受控取值）。`name=` 是变量时跳过该条 ——
    于是那条工具本次"没核对"（由"扫到了几条"这条 info 如实报出），
    而不是被当成"核对通过"（三态纪律）。
    """
    out: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            if _r010_name_of(dec.func) != "tool":
                continue
            # `@tool(name, summary, params, *, side_effect=..., external=...)`：
            # 名字与 summary 都是位置参数（见 `tools.base.tool` 的签名）。
            name = _r010_literal(dec.args[0] if dec.args else None, "")
            if not name:
                continue
            side = _r010_literal(_r010_kw(dec, "side_effect"), "none")
            external = _r010_external_literal(dec)
            out.append({
                "name": name, "side_effect": side, "external": external,
                "roots": [node.name], "line": node.lineno,
            })
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _r010_name_of(node.func) != "ToolSpec":
            continue
        name = _r010_literal(_r010_kw(node, "name"), "")
        if not name:
            continue
        side = _r010_literal(_r010_kw(node, "side_effect"), "none")
        external = _r010_external_literal(node)
        handler = _r010_kw(node, "handler")
        if handler is None and len(node.args) > 3:
            handler = node.args[3]  # ToolSpec(name, summary, params, handler, ...)
        roots: list[str] = []
        if handler is not None:
            for called in _r010_calls(handler):
                if called in defs:
                    roots.append(called)
        out.append({"name": name, "side_effect": side, "external": external,
                    "roots": roots, "line": node.lineno})
    return out


def _r010_markers_reachable(
    roots: Sequence[str],
    defs: dict[str, ast.AST],
    markers: Sequence[tuple[str, str]],
    *,
    max_depth: int = 4,
) -> list[str]:
    """从 `roots` 出发（按名字解析一层转发）能到达哪些标记。

    深度上限 4 是刻意写下来的：`P.locator_rule` 那种"任意深度地猜"
    与本仓库的取向相反。超过上限 ⇒ 本次没核对到，由"扫到了几条工具"
    这条 info 与例外清单共同兜住，不折叠成"没问题"。
    """
    found: list[str] = []
    seen: set[str] = set()

    def visit(fn: ast.AST, depth: int) -> None:
        if depth > max_depth:
            return
        for sub in ast.walk(fn):
            if not isinstance(sub, (ast.Call, ast.Attribute, ast.Name)):
                continue
            text = _r010_name_of(sub.func) if isinstance(sub, ast.Call) else _r010_name_of(sub)
            if not text:
                continue
            parts = text.split(".")
            # 判据（两条，都贴着点号段）：
            #   1. 带点的标记要求路径以它结尾（`subprocess.run` 以 `subprocess` 结尾，
            #      于是 `subprocess.run` 命中；`P.http_get_json` 以 `http_get_json` 结尾）；
            #   2. 不带点的标记要求路径的首段或末段与它相等（`urllib.parse.quote`
            #      的首段是 `urllib`；`downloader.download` 的末段是 `download`）——
            #      但 `os.walk` 的首段 `os` 与末段 `walk` 都不是任何标记，
            #      所以它不会被 `os.system` 这一类误抓。
            # 这两条替代了早先的"任一段相等"与"子串包含"：它们在真实树上都产生过
            # 假阳性（四个 fs 工具被判成起 shell），而假阳性会让整条规则被忽略（P15）。
            for nm, why in markers:
                if nm in found:
                    continue
                if "." in nm:
                    hit = text == nm or text.endswith("." + nm)
                else:
                    hit = text == nm or parts[0] == nm or parts[-1] == nm
                if hit:
                    found.append(nm)
        for called in _r010_calls(fn):
            if called.endswith("__init__") or called.endswith("__call__"):
                continue
            if called in seen:
                continue
            if called == "self":
                continue
            seen.add(called)
            sub_def = defs.get(called)
            if sub_def is not None:
                visit(sub_def, depth + 1)

    for root in roots:
        seen.add(root)
        fn = defs.get(root)
        if fn is not None:
            visit(fn, 1)
    return [why for nm, why in markers if nm in found]


def rule_R010_external_axis_mismatch(root: Path) -> list[Finding]:
    """声明与代码在 `external` 这根轴上不符（R006 的对偶）。

    ## 为什么必须有这条规则，以及它为什么与 R006 不同

    R006 问的是一个方向："声明 `read`，实际联网/起进程"。它有两个实测出来的
    结构缺陷（P-13 §10 第 5 条）：判据是文件级共现，而且要求同一文件里
    恰好有 `side_effect="read"` 的声明 —— 于是
    `src/agentflow/tools/search_tools.py`（三个 `network` 工具、真的发 HTTP）
    一次都不出现。一个真会出网的文件，因为"没有读工具"而完全不在输出里。

    R010 因此按工具判：先把每个 `ToolSpec` / `@tool` 的声明读出来，
    再从它的 handler 出发按名字解析转发（深度上限 4），
    看这条工具能不能到达起进程 / 网络调用。两条子规则：

    | 子规则 | 判据 | 级别 | 为什么 |
    |---|---|---|---|
    | R010-a | 声明的 `external != "exec"` 而 handler 链里出现起子进程的调用 | error | 这是"声明与代码不符"的确定形态：它直接决定审批与沙箱是否生效 |
    | R010-b | 声明的 `external == "egress"` 而 handler 链里没有任何网络调用 | warning | 可能只是保守或临时标注；本仓库有成文教训（P15）：假报警会训练人忽略告警 |
    | R010-b 的已登记盲区 | 同上，但工具在 `_R010_EGRESS_BLIND_SPOTS` 里 | info | 声明是对的、瞎的是检测器（出网在第三方库内部）；登记后不再计 warning，但仍以 info 出现 —— 静默豁免是最难查的形态 |
    | R010-c | 声明的 `external == "none"` 而 handler 链里出现网络调用的标记 | warning | 这是 R006 原来问的那个方向（`R7-R6-1`：退休声明说"移入 R010"，但此前没人接它）。级别沿用 R006 的取向：判据是**字面标记可达**，而标记表里 `search` / `download` 按末段相等匹配 ⇒ 真实树上会命中 `re.search` / `rx.search` 这类正则方法（已逐条登记在 `_R010_NETWORK_FALSE_POSITIVES`）。假阳性一多，error 会把门常驻点亮然后被忽略（P15） |

    ## `_R010_NETWORK_FALSE_POSITIVES`：R010-c 的"标记命中了、但那不是网络"

    判据用的是 R006 留下的那张标记表，所以它继承了那张表的两种串味（实测，真实树
    58 条声明里命中 3 条，三条都登记在这张表里）：

    - `search` / `download` 是按**末段相等**匹配的（它们要认的是 `prov.search` /
      `downloader.download` 这两个入口）⇒ `re.search` / `rx.search` 这种正则方法会被命中；
    - `subprocess` 在 R006 的口径里算"网络/子进程/模型调用"三类共用的一张表 ⇒
      只起进程、不出网的工具也会被命中。（2026-10-03，`draft/37` §82：此前命中的
      唯一一个是 `verify.detect_verifier`，它已随"探测搬到 `agentflow.toolchain`"而不再
      自己起子进程 —— 那条例外登记也已从 `_R010_ALLOWED_SITES` 删掉。）

    为什么登记而不是改标记表或加 `noqa`：`search` / `download` 那两条是 R010-b 也要用的
    （同一张表管两个方向），动它就是动既有判据；而静默豁免是本项目最忌的形态。
    登记后它们以 info 继续出现在报告里，并且报告里有一条"这一档核对了 N 条声明、
    其中 M 条登记为假阳性"的反真空读数 —— 它变成 0 时"没有命中"不等于"没有问题"。

    ## 为什么 R010-c 只判 `external == "none"`

    不是 `!= "egress"`：声明 `exec` 的工具起进程是如实的（它比 `egress` 更外），
    把它也算进这一档会让如实声明变成缺陷；而且 `subprocess` 同时是网络标记表的一员，
    那样每个 `exec` 工具都会被重复报两次。三个方向的判据必须各问各的：
    a 问"起进程却没说 exec"、b 问"说出网却看不到网络"、c 问"说什么都不做却联网"。

    ## `_R010_EGRESS_BLIND_SPOTS`：什么时候该登记、什么时候不该

    它是"检测器看不见"的登记表，不是"我不想被报"的开关。判据只有一条：
    出网这件事确实发生，而工具层源码里结构上没有网络字面量
    （例如 `ocr.run` 首次构造 easyocr Reader 时由第三方库下载模型）。
    声明写错（其实不出网）不适用这张表 —— 那要改声明；
    本规则判据能覆盖的情形也不适用 —— 那要改代码。

    它必须与"已知漏检"（`_R010_KNOWN_GAPS`，那是 R010-a 那一侧的）分开：
    两张表管的是两根不同的轴、两个不同的失败方向，合并会让
    "哪一段我核不了"这个问题失去答案。

    ## `external` 从哪里来

    - 工具写了 `declared_external=`（`ToolSpec` 的字段）或 `external=`（`@tool`
      装饰器的关键字）⇒ 用它的值。两个名字都要认：只认一个会让另一群工具
      按默认值 `none` 参与判定，而"声明被读成默认值"与"没声明"在报告里长得一样；
    - 两者都没写 ⇒ `none`（与 `ToolSpec.declared_external` 的默认值同一口径）。
      于是 `subprocess` 出现在 handler 链里、却没人声明 `external` 的工具
      会被 R010-a 命中 —— 这正是 P-13 §10 第 1 条那处歧义的落点，
      由 `_R010_ALLOWED_SITES` 逐条登记并写明理由。

    注意：B3 收官删掉了遗留取值 `network`，这条规则不再读任何翻译表。
    在此之前它要把 `side_effect="network"` 按 `base.LEGACY_EFFECTS_BY_TOOL`
    翻译成 `egress`（否则 `search.*` 那几条会带着默认的 `none` 参与判定），
    并逐条核对那张表与真实声明是否一致。那个取值现在会在 `ToolSpec.__post_init__`
    就以 `ValueError` 被拒 ⇒ 规则里不再需要为它开任何分支。

    ## 判据的强形态（B3 收官之后）

    现在只有 `declared_external="exec"` 能承接子进程：凡 handler 链里出现
    起进程调用、而声明不是 `exec` 的，除 `_R010_ALLOWED_SITES` 登记的例外以外
    一律是 `error`。这比迁移期更强 —— 那时"遗留取值"是一条免报的旁路。

    ## 例外清单与"只核对，不推断"

    例外清单（`_R010_ALLOWED_SITES`）登记的是"按轴的定义不是 exec、
    但字面判据会命中"的工具，每条都写了理由。这不是在给规则开后门：
    没有任何一条例外能把 R010-a 的 error 变成"不报" —— 它变成 `info`，
    仍然出现在报告里，且 `test_r010_allowed_sites_still_exist` 会断言
    它确实指着一个"真的起进程、真的没声明 exec"的工具。

    本规则不从 handler 推断声明：声明必须由人写（P-13 §9①：N-4 已否决
    AST 推断 —— 22/55 取不到 handler 源码、9 个转发型 handler 是假阳性）。
    AST 在这里的作用只有一个：核对人写的声明与代码是否一致。
    转发链深度上限 4；超过上限或 handler 是取不到的名字时，该条没核对，
    由下方那条"扫到了几条工具"的 `info` 如实报出。
    """
    base = root / _R010_TOOLS_REL
    if not base.exists():
        # 合成小树（测试夹具）与"还没落地工具层的树"都会走到这里。
        # 报 info 而不是 error：没有工具声明 ⇒ 这条规则没有对象可查，
        # 而不是"查了发现违规"（三态：这两个必须分开）。
        # 注意"声明读不到"与"目录不存在"是两件事：前者会以
        # "这个文件解析不了"（warning）报出来。
        return [Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            f"没有工具层源码目录 {base} ⇒ 本次核对了 0 条工具声明"
            "（没有工具声明，不是'声明都对'）",
        )]

    out: list[Finding] = []
    checked = 0
    none_checked_nets = 0
    fired_gaps: list[str] = []
    fired_egress_blind: list[str] = []
    fired_net_fp: list[str] = []
    for p in _iter_py(root, _R010_TOOLS_REL):
        rel = p.relative_to(root).as_posix()
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, OSError) as e:
            out.append(Finding(
                "R010", "warning", rel, 0,
                f"这个文件解析不了（{type(e).__name__}）⇒ 里面的工具声明本次没有核对",
            ))
            continue
        defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        tool_level_defs = {
            n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        for spec in _r010_specs(tree, tool_level_defs):
            checked += 1
            name = spec["name"]
            external = spec["external"] or "none"
            if external == "none":
                none_checked_nets += 1
            procs = _r010_markers_reachable(spec["roots"], defs, _R010_PROCESS_MARKERS)
            nets = _r010_markers_reachable(spec["roots"], defs, _R010_NETWORK_MARKERS)
            if procs and external != "exec":
                reason = _R010_ALLOWED_SITES.get(name)
                if reason is not None:
                    out.append(Finding(
                        "R010", "info", rel, spec["line"],
                        f"{name} 的 handler 链里出现了起子进程的调用（{procs}），而它声明 "
                        f"external={external!r} ⇒ 按字面判据会报 error，但本工具"
                        f"已逐条登记为例外：{reason}",
                    ))
                else:
                    out.append(Finding(
                        "R010", "error", rel, spec["line"],
                        f"{name} 声明 external={external!r}（即'我不在宿主上执行程序'），"
                        f"而它的 handler 链里出现了起子进程的调用（{procs}）⇒ "
                        "声明与代码不符。这一根轴直接决定审批与沙箱是否生效："
                        "改了代码就要改声明，改了声明就要重算审批面。"
                        "若它按轴的定义确实不是 exec（命令内容由工具自己写死），"
                        "请把工具名与理由加进 `_R010_ALLOWED_SITES`（那是共享轴定义的一部分，"
                        "不是给规则开后门：它会以 info 继续出现在报告里）",
                    ))
            elif procs and name in _R010_KNOWN_GAPS:
                fired_gaps.append(name)
            # ---- R010-c：声明 `none`（两根轴上的"我什么都不对外做"）而链里真的联网
            #
            # 这是 R006 原来问的那个方向（"声明 read、实际联网"）在逐工具口径下的落地。
            # 为什么它是补回来的一条而不是新判据：R006 退休时 `RETIRED_RULES` 写的是
            # "判据移入 R010（逐工具 AST）"，但 R010 此前只有"非 exec 而起子进程"与
            # "声明 egress 而看不到网络"两条 —— 于是 `side_effect="read"` / `external="none"`
            # 的工具**真的联网**这件事在今天的门里没有任何一条判据看得见（`lint_rules.py`
            # 的 R009 那条 info 也自认"静默豁免是本项目最忌的形态"）。
            # 级别是 warning 而不是 error，理由与 R006 当年一致、并写进 DEVELOPMENT.md：
            # 判据是"字面标记可达"，`_R010_NETWORK_MARKERS` 里 `search` / `download`
            # 这两条是按**末段相等**匹配的 ⇒ 真实树上 `re.search` / `rx.search` 这类
            # 正则方法会被算成"网络入口"（实测 4 个候选里 2 个是这种假阳性）。
            # 假阳性一多，error 会把门常驻点亮、然后被忽略（P15）；warning 让它进
            # `--strict` 档与发布门的可见面，同时不冒充缺陷判定。
            if external == "none" and nets:
                fp = _R010_NETWORK_FALSE_POSITIVES.get(name)
                if fp is not None:
                    fired_net_fp.append(name)
                    out.append(Finding(
                        "R010", "info", rel, spec["line"],
                        f"{name} 声明 external='none' 而链里有网络标记（{nets}），"
                        f"但这一条已逐条登记为本规则字面判据的假阳性：{fp}"
                        "它不再计 warning（'声明与代码不符'这个结论不成立），"
                        "但仍然以 info 出现在报告里 —— 静默豁免是本项目最忌的形态",
                    ))
                else:
                    out.append(Finding(
                        "R010", "warning", rel, spec["line"],
                        f"{name} 声明 external='none'（即'我对外什么都不做'），"
                        f"而它的 handler 链里出现了网络调用的标记（{nets}）⇒ "
                        "这是 R006 原来问的那个方向（声明读、实际联网），现在按工具点名报出来。"
                        "声明 read/none 的工具不需要审批，所以它若真的联网，权限面就在说假话 —— "
                        "`search.providers` 与 `ocr.run` 当年正是这样被发现的。"
                        "处理：核一下那个网络入口是不是真的会出网 —— 是 ⇒ 改声明（`egress`）；"
                        "不是（例如 `re.search` 这种正则方法被标记命中）⇒ 它属于本规则字面判据的"
                        "已知假阳性，请把工具名与理由加进 `_R010_NETWORK_FALSE_POSITIVES`，"
                        "登记后会以 info 继续出现在报告里",
                    ))
            if external == "egress" and not nets:
                blind = _R010_EGRESS_BLIND_SPOTS.get(name)
                if blind is not None:
                    fired_egress_blind.append(name)
                    out.append(Finding(
                        "R010", "info", rel, spec["line"],
                        f"{name} 声明 external='egress'，而本规则的字面判据在它的 handler 链里"
                        f"看不到任何网络调用。这一条**不是**误报，是检测器的已知盲区，"
                        f"已逐条登记：{blind}"
                        "它不再计为 warning（「声明与代码不符」这个结论不成立），"
                        "但仍然以 info 出现在报告里 —— 静默豁免是本项目最忌的形态",
                    ))
                else:
                    out.append(Finding(
                        "R010", "warning", rel, spec["line"],
                        f"{name} 声明 external='egress'，但它的 handler 链里**没有任何**网络调用"
                        "（标记见 `_R010_NETWORK_MARKERS`）⇒ 要么声明写错了，要么代码走了一条"
                        "本规则看不出来的路径。保守的假话仍然是假话：审计问'哪些工具会出网'时"
                        "会把不联网的工具列进去（P-13 §9③ 与 DEVELOPMENT.md 的 P7）。"
                        "若出网确实发生在第三方库内部（工具层没有网络字面量），"
                        "请把工具名与理由加进 `_R010_EGRESS_BLIND_SPOTS`："
                        "它是**已知盲区登记**，不是给规则开后门（登记后会以 info 继续出现）",
                    ))

    # ---- 遗留取值 `network` 的计数与翻译表核对：B3 收官后整段删掉
    #
    # 它曾经在这里报告"全仓还有 N 处 `side_effect=\"network\"`"，并逐条核对
    # `base.LEGACY_EFFECTS_BY_TOOL` 与那些声明是否一一对应（两个方向都报）。
    # 那个取值已从 `SIDE_EFFECTS` 里删掉 ⇒ 任何声明它的 `ToolSpec` 在构造期
    # 就以 `ValueError` 被拒，于是"还剩几处遗留"这个数字恒定是 0、
    # 翻译表也不再存在。留一条恒为 0 的计数会让报告多一行没有人能行动的信息，
    # 但"遗留已清零"这个事实仍值得留在报告里（下一条 info）。
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        "遗留取值：0 处 `side_effect=\"network\"` —— 该取值已从 "
        "`tools/base.SIDE_EFFECTS` 与 `capabilities.SIDE_EFFECTS` 里删除，"
        "两张翻译表（`LEGACY_SIDE_EFFECTS` / `LEGACY_EFFECTS_BY_TOOL`）"
        "连同全部下游分支一起消失。声明它的工具在 `ToolSpec.__post_init__` "
        "就会抛 `ValueError`（负控见 `tests/test_tools_base.py`）",
    ))
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        f"本规则逐工具核对了 {checked} 条工具声明（转发链深度上限 4；"
        "handler 是取不到的名字或链更深时那一条没核对）。"
        "这条 info 是 R010 的'判据接上了没有'的证据：若它变成 0，"
        "说明扫描器没读到任何声明 —— 那时'没有命中'不等于'没有问题'（P16）",
    ))
    if fired_gaps:
        out.append(Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            "以下工具原先登记在**已知漏检**清单里，但本次真的被这条规则看见了："
            + "、".join(f"{n}（{_R010_KNOWN_GAPS[n]}）" for n in sorted(fired_gaps))
            + " ⇒ 请把它移进 `_R010_ALLOWED_SITES` 并写清'按轴的**定义**它到底算不算 exec'，"
            "否则它会以 error 出现在报告里（而它可能只是漏检清单过期了）",
        ))
    # ---- R010-c 的"判据接上了没有"：这条 info 是那一档的反真空下限。
    #
    # 为什么必须打印：R010-c 的判据是"声明 none 的工具里，链里出现网络标记的有几个"。
    # 若扫描器哪天不再产出 `external == 'none'` 的声明（字段名改了、或全部工具都改成
    # 了别的取值），这一档会静默变成 0 条 —— 那时"没有命中"与"没有对象可查"在报告里
    # 长得一模一样（三态纪律要防的正是它）。
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        f"R010-c（声明 external='none' 而链里有网络标记）核对了 {none_checked_nets} 条声明，"
        f"其中以 info 登记为字面假阳性的 {len(_R010_NETWORK_FALSE_POSITIVES)} 条"
        f"（本次命中 {len(fired_net_fp)} 条）；还有 {none_checked_nets - len(fired_net_fp)} 条"
        "声明 `none` 的工具**没有任何网络标记可达**（那是这一档的'查过了、干净'）。"
        "若这个数字变成 0，说明扫描器没读到任何 `external='none'` 的声明 —— "
        "那时'没有命中'不等于'没有问题'（P16）",
    ))
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        "R010-c 的**已知字面假阳性**（标记命中了、但那个调用不是网络）："
        + "；".join(f"{n} —— {why}" for n, why in sorted(_R010_NETWORK_FALSE_POSITIVES.items())),
    ))
    stale_net_fp = sorted(set(_R010_NETWORK_FALSE_POSITIVES) - set(fired_net_fp))
    if stale_net_fp:
        out.append(Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            f"这些工具登记在 R010-c 的假阳性表里，但本次它们没有命中 R010-c：{stale_net_fp}"
            " ⇒ 要么声明改了、要么标记表变了（那是好事，请把它们从表里摘掉 —— "
            "一张永不生效的豁免表会腐烂成'看起来还在挡着什么'）",
        ))
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        "本规则的**已知漏检**（转发链断在工具层之外，本规则看不见，不等于没问题）："
        + "；".join(f"{n} —— {why}" for n, why in sorted(_R010_KNOWN_GAPS.items())),
    ))
    # ---- R010-b 的已知盲区：登记表本身必须出现在报告里（否则它是注释，不是判据）。
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        "R010-b 的**已知盲区**（声明 `egress` 是对的、而出网发生在第三方库内部，"
        "本规则的字面判据结构上看不见）："
        + "；".join(f"{n} —— {why}" for n, why in sorted(_R010_EGRESS_BLIND_SPOTS.items())),
    ))
    stale_blind = sorted(set(_R010_EGRESS_BLIND_SPOTS) - set(fired_egress_blind))
    if stale_blind:
        out.append(Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            f"这些工具登记在 R010-b 的已知盲区里，但本次它们没有命中 R010-b：{stale_blind}"
            " ⇒ 要么声明改了、要么规则变强了（那是好事）—— 请把过期条目从 "
            "`_R010_EGRESS_BLIND_SPOTS` 删掉，否则登记表会腐烂成一张永不生效的豁免",
        ))
    return out


# ------------------------------------------------------------------- R009 用到的表
#
# 代码跨度先摘出来：`` `` `` 这样的示例是合法内容（本文档字符串里就有），
# 判据要贴着"这串字符是不是给人看的装饰"，而不是"字符里有没有星号"。
# 摘除方式与清洗脚本 `temp/_clean_deco.py` 同构，但两者互不依赖：
# 清洗脚本是一次性工具，本规则是长期门；门不许依赖一个临时脚本。

#: 代码跨度：``...`` 与 `...`（先长后短，避免两个单反引号被误当一对）。
_R009_CODE_SPAN = re.compile(r"``.+?``|`[^`\n]+`", re.S)
#: emoji / 杂项符号 / 变体选择符。
#:
#: 范围刻意不含 `U+2190–U+21FF`（箭头 ← → ⇒）与 `U+2300–U+25FF`（技术符号、
#: 制表符 ─ │）：本仓库的注释大量使用 `A → B` 表示流程、用 `⇒` 表示推论，
#: 它们是正常标点而不是装饰。第一版把箭头也算了进去，在真实树上得到 915 处
#: 命中 —— 其中绝大多数是 `→`，这类假阳性会让整条规则被忽略（校准纪律）。
_R009_EMOJI_CLS = (
    "\U0001F000-\U0001FAFF"
    "\u2600-\u27BF\u2B00-\u2BFF\uFE0F"
)
_R009_EMOJI = re.compile(f"[{_R009_EMOJI_CLS}]")
#: 成对的星号强调。上限 400 字符：超长的"强调"不是强调，多半是没配对的星号
#: （那种由下面的"残留星号"判据接住）。
_R009_BOLD = re.compile(r"\*\*(?=\S)([^*]{1,400}?)(?<=\S)\*\*", re.S)
#: 残留的星号（上面清掉成对之后剩下的），只在没有被代码跨度遮住时才报。
_R009_STRAY = re.compile(r"\*\*")
#: 判据自检样本：一段必然含 1 个 docstring + 1 个注释的最短源码。
#:
#: 为什么要自检：本规则的输出是"某文件有 N 处装饰"。若区间计算整体失灵
#: （返回空集），输出会变成"哪儿都没有装饰" —— 而"干净"与"没查成"在输出里
#: 长得一模一样。所以在扫真树之前，先让判据在一个人造样本上证明自己接上了。
_R009_SELFTEST = '"""自检。"""\n\n# 自检注释。\n'
_R009_SELFTEST_REGIONS = 2


def _r009_load_gate():
    """按路径加载同目录的 `noai_gate.py`。

    为什么不写 `import noai_gate`：本模块在两种方式下被加载 ——
    `python scripts/lint_rules.py`（`scripts/` 在 `sys.path` 上）与
    `importlib` 按文件路径加载（测试里的做法，`sys.path` 上没有 `scripts/`）。
    按 `__file__` 定位对两者都成立，也不需要动 `sys.path`（动它会影响整个进程）。
    """
    spec = importlib.util.spec_from_file_location(
        "_noai_gate_for_lint", Path(__file__).resolve().parent / "noai_gate.py"
    )
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _r009_mask_code(text: str) -> str:
    """把代码跨度换成等长空格（等长是为了让行号/列号仍然对得上）。"""
    return _R009_CODE_SPAN.sub(lambda m: " " * len(m.group(0)), text)


def _r009_scan(text: str) -> tuple[list[tuple[int, str]], int]:
    """扫一个源文件 ⇒ `([(行号, 装饰种类)], 扫到的注释/文档串个数)`。

    ## 第二个返回值为什么必须返回

    它是这道门的"接上了没有"的证据：如果区间计算整体失灵（返回 0 个文档串），
    本规则会一条都不报 —— 而"一条都不报"与"干净"在输出里长得一样。
    这正是本项目记过的 P16 形态，所以规则要求这个数字大于 0。

    ## 列号为什么有两种算法

    `tokenize` 给的列号是字符下标，而 `ast` 的 `col_offset` 是 UTF-8 字节偏移。
    源码里四处是中文，两者的差值就是中文的字节数 —— 混用会让区间滑进代码里
    （清洗脚本第一版就是这样去改动 `min(2.0**attempt, 30.0)` 的）。
    """
    text = text.replace("\r\n", "\n")
    lines = text.splitlines()
    found: list[tuple[int, str]] = []
    regions = 0

    def char_col(lineno: int, byte_col: int) -> int:
        if not 1 <= lineno <= len(lines):
            return byte_col
        return len(lines[lineno - 1].encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

    def inspect_region(lineno: int, region: str, kind: str) -> None:
        nonlocal regions
        regions += 1
        masked = _r009_mask_code(region)
        if _R009_BOLD.search(masked) or _R009_STRAY.search(masked):
            found.append((lineno, f"{kind}里的星号强调"))
        if _R009_EMOJI.search(masked):
            found.append((lineno, f"{kind}里的 emoji"))

    # tokenize 失败不在这里吞掉：调用方把它记成"这个文件没查成"，
    # 而不是"查了、没命中"（三态纪律：没做不等于做了没结果）。
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.COMMENT:
            inspect_region(tok.start[0], tok.string, "注释")

    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            continue
        const = first.value
        start = char_col(const.lineno, const.col_offset)
        end = char_col(const.end_lineno, const.end_col_offset)
        if const.lineno == const.end_lineno:
            region = lines[const.lineno - 1][start:end]
        else:
            region = "\n".join(
                [lines[const.lineno - 1][start:]]
                + lines[const.lineno:const.end_lineno - 1]
                + [lines[const.end_lineno - 1][:end]]
            )
        inspect_region(const.lineno, region, "docstring")
    return found, regions


def rule_R009_decoration_in_comments(root: Path) -> list[Finding]:
    """注释与 docstring 里出现 Markdown 强调标记或 emoji。

    ## 为什么这是一条规则，而不是一句"注意风格"

    源码注释不会经过渲染器。写在里面的成对星号与 emoji，
    到了读者眼里就是一堆符号 —— 它表达的不是强调，而是"这段文字是被生成出来的"。
    这类标记一旦出现就会扩散：下一段注释照抄上一段的写法，
    几十个文件之后就成了默认风格。所以它值得一条机器可查的规则，
    而不是依赖每次 code review 都有人提。

    ## 判据的两级：禁改区外是 error，禁改区内只报 info

    禁改区（FC-27）之外的文件，AI 可以改，这条规则必须挡住回归，所以是 `error`。
    禁改区之内的文件（`dedup.py` / `store.py` / `release_check.py` 等）
    按 FC-27 只能由人编写或人逐行走查 —— 对它们报 `error` 会造出一条永远红的灯：
    它只能靠人去改那些人专属文件才能变绿，而每个文件的改动各需要 2 名 reviewer。
    一条永远红的门与一条永远绿的门一样没有信息量（本项目 R001/R006 都栽在噪音上），
    所以区内只报一条汇总 `info`：能看见、不阻塞，并列出要清哪几个文件。

    ## 这道门自身的假阳性（立项前实测过）

    在真实树上试过四类候选，命中量与误报如下（131 个 `.py`，8167 个注释/文档串）：

    - 成对星号强调：禁改区外 12 处 —— 采用；
    - 未配对的残留星号：禁改区外 12 处 —— 采用（它是"清了一半"的形态）；
    - emoji：禁改区外 1 处 —— 采用；
    - 单个星号强调：区外 7 处，其中 6 处是假阳性 ——
      放弃。它们分别是 `# -*- coding: utf-8 -*-`（文件编码声明）与
      `search.*`（glob 写法）。真命中里混着同形态的 glob 写法，
      单靠字符没法区分；假阳性会让这条规则被忽略。
    - Markdown 链接 `[文字](url)` 与删除线：全仓 0 处 —— 不立项。
      一条没有真实正样本的规则无法校准，它只是"看起来更严"。

    emoji 的字符范围也要贴着这个仓库：第一版把箭头 `→` `⇒` 也算成 emoji，
    于是在真实树上得到 915 处命中，绝大多数是流程写法 `A → B`。
    范围因此收窄成"emoji 平面 + 杂项符号 + 变体选择符"。

    ## 为什么必须显式处理"查不了"

    三态纪律：判据失败要报出来，不能折叠成"通过"。本规则有三处可能查不了 ——
    禁改区清单读不到（那就无法区分区内区外，⇒ error）、
    文件读不出/解析不了（⇒ 汇总 warning）、
    判据自检不过或一个源文件都没扫到（⇒ error）。

    最后一条是本项目 P16"判据真空通过"的通用形态：判据解析出空集时无条件通过。
    本规则的自检形态是"先在人造样本上证明扫描器接上了" ——
    不这样做就得靠"整棵树有没有解析出注释"来判断，而一棵真的没有注释的树
    与一个坏掉的扫描器在输出上完全一样（第一版就是这么写的，被
    `test_linter_runs_all_rules_and_reports_counts` 的合成树当场抓住：
    那棵树里的文件确实没有注释，于是被判成"扫描器坏了"）。
    """
    out: list[Finding] = []

    gate = None
    try:
        gate = _r009_load_gate()
    except Exception as e:  # noqa: BLE001
        out.append(Finding(
            "R009", "error", "scripts/noai_gate.py", 0,
            f"读不到禁改区判定模块（{type(e).__name__}: {e}）⇒ 无法区分禁改区内外，"
            "本次没有真正检查（不是没问题）",
        ))
        return out

    rules = None
    try:
        rules = gate.load_manifest(root / ".noai-paths")
    except Exception as e:  # noqa: BLE001
        out.append(Finding(
            "R009", "error", ".noai-paths", 0,
            f"禁改区清单读不到或解析失败（{type(e).__name__}: {e}）⇒ "
            "无法判定哪些文件属于禁改区，本次没有真正检查（不是没问题）",
        ))
        return out

    selftest = _r009_scan(_R009_SELFTEST)
    if selftest[1] < _R009_SELFTEST_REGIONS:
        out.append(Finding(
            "R009", "error", "<linter>", 0,
            f"判据自检失败：在自检样本上只解析出 {selftest[1]} 个注释/docstring"
            f"（应为 {_R009_SELFTEST_REGIONS}）⇒ 扫描器没接上，本次结果不可信 —— "
            "判据解析出空集会无条件通过（P16），所以这里失败而不是通过",
        ))
        return out

    scan_roots = (SRC_REL, TESTS_REL, SCRIPTS_REL, Path("tools"))
    scanned = 0
    unreadable: list[str] = []
    outside: list[tuple[str, int, int, str]] = []
    inside: list[tuple[str, int]] = []

    for base in scan_roots:
        for p in _iter_py(root, base):
            rel = p.relative_to(root).as_posix()
            scanned += 1
            try:
                text = p.read_text(encoding="utf-8")
                hits, _ = _r009_scan(text)
            except (OSError, SyntaxError, tokenize.TokenError, ValueError) as e:
                unreadable.append(f"{rel}（{type(e).__name__}）")
                continue
            if not hits:
                continue
            in_zone = bool(gate.check_paths([rel], manifest=rules, root=root).violations)
            if in_zone:
                inside.append((rel, len(hits)))
            else:
                outside.append((rel, len(hits), hits[0][0], hits[0][1]))

    if not scanned:
        out.append(Finding(
            "R009", "error", "<linter>", 0,
            f"一个源文件都没扫到（根 {root}）⇒ 本次没有真正检查（根写错了不能被读成'干净'）",
        ))
        return out
    if unreadable:
        out.append(Finding(
            "R009", "warning", "<linter>", 0,
            f"{len(unreadable)} 个文件没查成（读不出或解析不了）："
            f"{'、'.join(unreadable[:5])}"
            + ("…" if len(unreadable) > 5 else "")
            + " —— 这些文件的注释里有没有装饰，本次是未知，不是干净",
        ))

    for rel, n, lineno, kind in sorted(outside, key=lambda x: (-x[1], x[0]))[:5]:
        out.append(Finding(
            "R009", "error", rel, lineno,
            f"{n} 处注释/docstring 里有 Markdown 强调标记或 emoji（首个在第 {lineno} 行，{kind}）。"
            "源码不会被渲染成网页：成对的星号到了读者眼里只是星号，emoji 只是符号。"
            "要强调就把它写进句子，要插图就写进 `docs/` 或 `draft/`",
        ))
    if len(outside) > 5:
        rest = sum(n for _, n, _, _ in outside[5:])
        out.append(Finding(
            "R009", "error", "<linter>", 0,
            f"另有 {len(outside) - 5} 个文件、合计 {rest} 处同类问题（上面只列了最多的 5 个）",
        ))

    if inside:
        head = "、".join(f"{rel}={n}" for rel, n in sorted(inside, key=lambda x: (-x[1], x[0]))[:5])
        out.append(Finding(
            "R009", "info", "<禁改区>", 0,
            f"禁改区 {len(inside)} 个文件里仍有 {sum(n for _, n in inside)} 处装饰（{head}"
            + ("…" if len(inside) > 5 else "")
            + "）—— 这些文件按 FC-27 只能由人改，本项不计入判据；"
            "列在此处是为了让人知道要清哪几个文件，而不是让门一直亮着红灯",
        ))
    else:
        out.append(Finding(
            "R009", "info", "<禁改区>", 0,
            "禁改区里没有装饰待清（区内与区外都干净）",
        ))
    return out


# ---------------------------------------------------------------- R012 行尾纪律


#: 编排层（`scripts/` 与 `tools/`）—— R012 的扫描范围。
#:
#: 为什么口径落在这里而不是全仓：`G-42` 说的是产物（发布门上落下的证据文件），
#: 而产物只有编排层会写。`src/` 里的 `write_text` 写的是工作区内的载荷，
#: `tests/` 里的写的是 `tmp_path`（怎么换行都不影响任何门）。
ORCHESTRATOR_FILES_REL = (SCRIPTS_REL, Path("tools"))

#: 逐条登记的豁免（相对仓库根）。只有登记了才不报，且每条必须能被反查：
#: 文件不在盘上、或已经不再出现 `write_text` ⇒ 本规则报一条 `info` 提醒删登记
#: （登记过期与漏登记同样危险：前者让人以为"有人看过了"，后者让人以为"没问题"）。
R012_NEWLINE_EXEMPTIONS: dict[str, str] = {
    "tools/make_demo_dataset.py": (
        "演示数据生成器：它写的是 `demo/run/data/*`（工作区载荷，不是发布门的产物），"
        "内容有测试钉死；`G-42` 的适用面是门落下的证据文件，不是这一类"
    ),
}

#: `write_bytes` 自己给字节 ⇒ 天然不经过平台的换行转换；`write_text` 要走它就必须
#: 显式给 `newline=` —— 见 `_r012_violations`。
_BYTES_WRITERS = frozenset({"write_bytes"})


def _r012_takes_newline(node: ast.Call) -> bool:
    """这次调用有没有显式控住行尾（`newline=` 关键字，任何值都算）。"""
    return any(kw.arg == "newline" for kw in node.keywords)


def _r012_violations(tree: ast.Module) -> list[ast.Call]:
    """`write_text(...)` 而没有 `newline=` 的调用点。

    `open(..., newline=...)` 与 `write_bytes(...)` 不在判据里：前者显式控住了行尾，
    后者根本不经过文本层。
    """
    bad: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        name = node.func.attr
        if name in _BYTES_WRITERS:
            continue
        if name != "write_text":
            continue
        if _r012_takes_newline(node):
            continue
        bad.append(node)
    return bad


def rule_R012_write_text_newline(root: Path) -> list[Finding]:
    """编排层里"不做行尾控制就写文本"的调用点（`G-42` 的机器判据，`c-12`）。

    ## 这条规则为什么存在（而不是一条注释）

    `tools/release_all.py` 的注释引用了一条禁令 —— `G-42：禁止 Path.write_text()` ——
    而全仓 grep 显示 `RULES` 里当时只有 R001–R011，没有任何一条叫 G-42。
    也就是说：那条"被引用的禁令"在门里查不到，读者以为有机器防线，实际只有一段散文。
    散文不是判据 —— 它随文件一起漂，而漂的方向永远是"没人再记得它"。

    真正的事故形态（`draft/22` §12.15.2 记过）：`Path.write_text()` 在 Windows 上
    把每个 `\\n` 刷成 `\\r\\n`，于是"跑一次门"就把被 git 跟踪的产物改脏 ——
    改行尾会改 `sha256`，而禁改区批准台账钉住的对象正是 `sha256`。

    ## 判据

    对 `scripts/` 与 `tools/` 下的每个 `.py`：AST 里出现
    `X.write_text(...)` 而没有 `newline=` ⇒ `warning`。
    两种写法算合规：显式传 `newline=`，或改用 `write_bytes`（自己给字节）。

    ## 为什么是 `warning` 而不是 `error`

    放 `error` 会让发布门在任何一次漏改时立刻红 —— 与本文件 R009 对禁改区的处置
    同一条理由："CI 里一条永远红的灯会被忽略"。`warning` 在 `--strict` 档可见
    （`scripts/release_check.py::item_linter` 现在走严格档），且会被逐条打印出来。

    ## 豁免不是"静默"

    逐条登记的豁免见 `R012_NEWLINE_EXEMPTIONS`；登记一旦指向不存在的文件或
    该文件不再出现 `write_text`，本规则报一条 `info` 提醒把它删掉 ——
    登记过期与漏登记同样危险。
    """
    out: list[Finding] = []
    for rel_dir in ORCHESTRATOR_FILES_REL:
        if not (root / rel_dir).exists():
            # 目录不存在 = 这一半没查成。报出来，不静默跳过。
            out.append(Finding(
                "R012", "info", rel_dir.as_posix(), 0,
                f"读不到 {rel_dir.as_posix()}/ ⇒ 这一半的行尾纪律本次没查成（不是『干净』）",
            ))
            continue
        for path in _iter_py(root, rel_dir):
            rel = path.relative_to(root).as_posix()
            if rel in R012_NEWLINE_EXEMPTIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, SyntaxError, UnicodeDecodeError) as exc:
                # 解析不了 = 这一条没查成。不许静默跳过：静默跳过会让
                # "我没读出来"与"这里没问题"在报告里同形（三态纪律）。
                out.append(Finding(
                    "R012", "warning", rel, 0,
                    f"读不出或解析不了（{type(exc).__name__}: {exc}）⇒ 这个文件的行尾纪律本次没查成",
                ))
                continue
            lines = text.splitlines()
            for node in _r012_violations(tree):
                snippet = lines[node.lineno - 1].strip()[:150] if 0 < node.lineno <= len(lines) else ""
                out.append(Finding(
                    "R012", "warning", rel, node.lineno,
                    "`write_text(...)` 没有 `newline=` ⇒ Windows 上会把 `\\n` 刷成 `\\r\\n`，"
                    "产物的 `sha256` 会跟着变（`G-42`，`draft/22` §12.15.2）；"
                    "改用 `open(..., newline=\"\")` 或 `write_bytes`",
                    snippet=snippet,
                ))
    # 登记不许过期（过期登记会让人以为"这一条有人看着"）
    for rel, why in sorted(R012_NEWLINE_EXEMPTIONS.items()):
        p = root / rel
        if not p.is_file():
            out.append(Finding(
                "R012", "info", rel, 0,
                f"豁免登记指向一个不存在的文件 ⇒ 请删掉这条登记（登记理由：{why}）",
            ))
        elif "write_text" not in p.read_text(encoding="utf-8", errors="replace"):
            out.append(Finding(
                "R012", "info", rel, 0,
                f"豁免登记已过期：该文件不再出现 `write_text` ⇒ 请删掉这条登记（登记理由：{why}）",
            ))
    return out


RULES: tuple[tuple[str, object], ...] = (
    ("R001 except-pass", rule_R001_bare_except_pass),
    ("R002 None→空容器", rule_R002_none_folds_to_empty),
    ("R003 同名公开定义", rule_R003_duplicate_public_defs),
    ("R004 工具层外构造注册表", rule_R004_registry_outside_tools),
    ("R005 写死角色名单", rule_R005_hardcoded_role_list),
    ("R006 read 工具碰网络", rule_R006_read_tool_touches_network),
    ("R011 受控词表的死取值", rule_R011_dead_vocab),
    ("R007 缺 docstring", rule_R007_missing_docstring),
    ("R008 脚本无退出码", rule_R008_scripts_without_exit_code),
    ("R009 注释里的装饰", rule_R009_decoration_in_comments),
    ("R010 装置轴与代码不符", rule_R010_external_axis_mismatch),
    ("R012 编排层写产物不控行尾", rule_R012_write_text_newline),
)


def run_all(root: Path, *, strict: bool = False) -> LintReport:
    """跑全部规则。

    `strict=True`（发布级）会把支持它的规则切换到更严的判据 ——
    目前只有 R007（缺 docstring：日常给一个带分布的 `info`，发布级逐模块报 `warning`）。
    用 `inspect.signature` 探测而不是给每条规则都加一个忽略掉的参数：
    后者会让"哪些规则真的支持严格模式"变成一件要读实现才知道的事。
    """
    rep = LintReport()
    for name, fn in RULES:
        rep.rules_run.append(name)
        try:
            if "strict" in inspect.signature(fn).parameters:  # type: ignore[arg-type]
                rep.findings.extend(fn(root, strict=strict))  # type: ignore[operator]
            else:
                rep.findings.extend(fn(root))  # type: ignore[operator]
        except Exception as e:  # noqa: BLE001
            rep.findings.append(Finding(
                "LINT", "error", "<linter>", 0,
                f"规则 {name} 自身失败：{type(e).__name__}: {e}（**这是检查器的问题，不是被检对象的**）",
            ))
    rep.scanned["src_py"] = sum(1 for _ in _iter_py(root, SRC_REL))
    rep.scanned["tests_py"] = sum(1 for _ in _iter_py(root, TESTS_REL))
    return rep


def _pin_utf8() -> None:
    """钉住 stdout/stderr 的编码。

    为什么这个门脚本内联一份而不是 import `agentflow.console`：门必须在本包
    import 不了的时候也能跑（它是治理门，不是应用代码）。规范实现见
    `src/agentflow/console.py::pin_utf8`，两处的行为由
    `tests/test_cli_console_encoding.py` 的普查用例统一守着，所以不会静默漂移。

    不钉的后果（实测）：GBK 重定向下打印含 `⇒` 的行会抛 UnicodeEncodeError，
    进程以 1 结束 —— 而那正是"发现问题"的码；于是"打印不出来"被读成"代码有问题"，
    而且 `0 error + ≥1 warning` 的干净树在重定向下也会退 1。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 可以忽略：被重定向或被替换过的流可能没有 reconfigure，不该让门崩掉。
            pass


def main(argv: Sequence[str] | None = None) -> int:
    _pin_utf8()
    ap = argparse.ArgumentParser(description="agentflow 机械可查规则（linter）")
    ap.add_argument("--root", default=".", help="仓库根（默认当前目录）")
    ap.add_argument("--json", default="", help="把结果写到该 JSON 路径")
    ap.add_argument("--strict", action="store_true", help="把 warning 也算失败")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / SRC_REL).exists():
        print(f"[linter] 读不到源码树 {root / SRC_REL} —— **这是检查器自身失败**（退出码 2）",
              file=sys.stderr)
        return 2

    rep = run_all(root, strict=args.strict)
    d = rep.to_dict()
    if args.json:
        # `G-42`（`c-12`）的落地形态：产物必须是纯 LF，与平台无关。
        # `Path.write_text` 在 Windows 上会把每个 `\n` 刷成 `\r\n` ⇒ 产物的 `sha256`
        # 与"盘上那一版"对不上（`draft/22` §12.15.2 记过那次事故），
        # 而禁改区批准台账钉住的正是 `sha256`。`newline=""` 关掉平台的换行转换。
        # 这条纪律本身也有机器判据：本文件的 `rule_R012_write_text_newline`。
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        with open(args.json, "w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(d, ensure_ascii=False, indent=2))

    mode = "严格（发布级）" if args.strict else "日常"
    print(f"[linter] 扫描 {d['scanned']}；规则 {len(d['rules_run'])} 条；模式 {mode}")
    # 退休的规则必须显式打印：否则"10 条里有一条不干活"会变成
    # "看起来规则数没变、其实少了一条判据面"（G-14 的 retire 形态）。
    for rid, why in sorted(RETIRED_RULES.items()):
        print(f"[linter] 已退休 {rid}：{why}")
    print(f"[linter] error {d['error_count']} / warning {d['warning_count']} / info {d['info_count']}")
    for f in rep.errors():
        print(f"  ERROR {f.rule} {f.path}:{f.line}  {f.message[:150]}")
        if f.snippet:
            print(f"        > {f.snippet[:150]}")
    for f in rep.warnings():
        print(f"  warn  {f.rule} {f.path}:{f.line}  {f.message[:150]}")
    for f in rep.findings:
        if f.level == "info":
            print(f"  info  {f.rule}  {f.message}")

    if rep.errors():
        return 1
    if args.strict and rep.warnings():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
