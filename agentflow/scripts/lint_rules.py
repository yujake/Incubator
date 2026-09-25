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

`0` = 无 error；`1` = 有 error；`2` = linter 自己没跑成（读不到源码树）。

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


def _enclosing_def(lines: Sequence[str], lineno: int) -> str:
    """该行所在的最内层 `def`/`class` 名（缩进比较，够用即可）。

    为什么需要它：R004 的第一版在真实代码上命中 17 处，其中大多数落在
    `_selftest()` 里 —— 自检故意构造一个局部 `ToolRegistry` 来测工具，
    那是测试脚手架而不是装配点。把脚手架报成"绕过角色校验"是假报警，
    而假报警会让这条门失去可信度。闸门要在真实样本上校准（本项目通用纪律）。
    """
    chain = _enclosing_defs(lines, lineno)
    return chain[-1] if chain else ""


def _enclosing_defs(lines: Sequence[str], lineno: int) -> list[str]:
    """该行所在的整个嵌套链（最外层 → 最内层）。

    为什么需要"整条链"而不只是最内层：`tools/fs_tools.py` 的自检写成

    ```python
    def _selftest():
        def check(label, cond, detail=""):   # ← 嵌套小工具
            ...
        reg = ToolRegistry(name="selftest")  # ← 命中点在最外层函数体里
    ```

    命中点所属的最内层 def 是 `check` —— 它不以 `_self` 开头，于是
    "自检脚手架"的豁免判错了对象，产生两个纯粹的假阳性。
    判据应当是"这条语句在哪个函数链里"，任何一个祖先函数是自检入口就够了。
    """
    cur_indent = len(lines[lineno - 1]) - len(lines[lineno - 1].lstrip())
    pat = re.compile(r"^(\s*)(?:async\s+)?(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)")
    chain: list[str] = []
    for i in range(lineno - 2, -1, -1):
        m = pat.match(lines[i])
        if not m:
            continue
        indent = len(m.group(1))
        if indent < cur_indent:
            chain.append(m.group(2))
            cur_indent = indent
    chain.reverse()
    return chain


def _is_scaffolding(chain: Sequence[str]) -> bool:
    """函数链里任一祖先是不是自检/演示脚手架？

    判据：名字以 `_self` 开头，或名字里含 `selftest` / `self_check` / `demo`
    （大小写不敏感）。为什么是名字而不是结构：本项目的自检入口有一个写下来的约定
    （`python -m agentflow.agent_x`，见 `DEVELOPMENT.md`），约定就是判据；
    而"从 `__main__` 块被调用"这条结构判据覆盖不到"自检函数被测试直接 import 调用"的形态。
    两种判据都保留：任一成立即算脚手架。
    """
    for name in chain:
        low = name.lower()
        if name.startswith("_self") or "selftest" in low or "self_check" in low or "demo" in low:
            return True
    return False


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
                    "**为什么可以忽略**（带 ≥4 字的注释，或 `# noqa: <规则>`）—— "
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


#: 被认可为"装配期角色校验器"的调用名。函数体里调用了其中任何一个，
#: 就不算"绕过装配期的 roles 校验" —— 这正是 R004 那句提示里的
#: "或显式调用同一份校验函数（不要复制它的判据）"的可判定形式。
#:
#: 为什么是"一份写下来的名单"而不是"猜"：判据是 `ROLES` 这一个常量，
#: 校验动作可以发生在多个装配入口上；linter 不可能从名字推断某函数是不是在
#: 执行同一条断言。所以它要求人显式登记：把名字加进本表 = 声明
#: "这个函数执行的确实是同一份判据"。加名字是一个刻意的动作，会被 code review 看到。
#: 每个名字都要在测试里断言它真的存在（否则名单会腐烂成空话）。
ROLE_VALIDATOR_CALLS: dict[str, str] = {
    "validate_tool_roles": (
        "`agent_d` 的装配入口（`install_d_tools` 的 `registry=` 注入路径也走它）—— "
        "用同一份 `ROLES` 常量在第二个装配入口上执行 `build_registry` 的那条断言"
    ),
    # 刻意不放进来的：`capabilities.assert_capabilities`。它核的是能力表
    # 与 `schema.ROLES` 是否一致，不核注册表里的 spec。把它放进来，就等于允许
    # "构造一个角色名写错的注册表，然后调一次与它无关的自检"来消掉这条 warning ——
    # 那是一个看起来合规的假阴性，比没有豁免更坏。
    # 这份名单宁可短：每加一个名字都要能回答"它真的核了注册表的 roles 吗"。
}

#: 工具层的正规装配入口。同一函数体里调用了它们，就说明 roles 校验已经跑过，
#: 于是"绕过"这个前提不成立。与 `ROLE_VALIDATOR_CALLS` 分开列，因为它们是
#: 构造器（做校验 + 返回注册表），不是单纯的校验器 —— 混在一张表里会让
#: "调一次校验"与"用正规入口造表"看起来是同一件事。
REGISTRY_BUILDERS: tuple[str, ...] = ("build_registry", "build_for_role")

#: R004 的逐点例外：键是 `(仓库相对路径, 最内层函数名)`，值必须写清理由。
#:
#: 为什么要有它，而不只靠"调用某个函数"来判：有些装配点用内联的 fail-closed 断言
#: 执行了同一条判据（判据取自同一份常量），但没有把它包成一个具名函数。
#: 那种代码不是绕过，linter 也看不出它在断言 —— 所以要求人显式登记。
#:
#: 两条纪律，与 `SAME_NAME_ALLOWED` 同族：
#:   1. 每条都必须写理由；写不出理由的，就是该改代码而不是该加例外。
#:   2. `tests/test_lint_rules.py::test_r004_allowed_sites_still_exist` 会断言
#:      每个键指向的文件与函数真的存在 —— 否则改名/删函数之后例外静默腐烂，
#:      门还在，只是再也不生效。
R004_ALLOWED_SITES: dict[tuple[str, str], str] = {
    ("src/agentflow/agent_h.py", "__init__"): (
        "H 的 `writers`（落库代理）注册表：紧接着有一处内联 fail-closed 断言 —— "
        "遍历 `self.writers.describe()`，凡是 `side_effect in SIDE_EFFECTS_WRITE` 且不在 "
        "`_H_WRITABLE_TOOLS` 里的工具就 `raise ReviewError`。判据**取自工具层的同一份 "
        "`SIDE_EFFECTS_WRITE`**（没有另写一份'哪些算写'）。"
        "所以这一处不是绕过角色校验，而是把'H 只能写 review_findings 与 documents.status'"
        "这条约束用另一条更强的断言（按副作用等级）钉住。"
        "⚠️ 注意：它没有核 spec 里声明的 `roles` 字面量 —— 那条由 `install_h_tools` "
        "走 `build_registry` 覆盖。"
    ),
}


def _calls_named(tree: ast.AST, lineno: int, names: Sequence[str]) -> str:
    """`lineno` 所在的最内层函数体里是否调用了 `names` 里的任一函数？

    返回命中的函数名（空串 = 没命中）。为什么按"最内层函数体"而不是整个文件：
    文件里别处调过一次校验器，不能为这一处构造注册表背书 ——
    那样这条豁免就退化成"文件级忽略"，而文件级忽略正是本项目最反对的形态。
    """
    best: tuple[int, ast.AST] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        lo = node.lineno
        hi = max((getattr(n, "lineno", lo) for n in ast.walk(node)), default=lo)
        if lo <= lineno <= hi:
            # 取最内层（起点最大）的那个函数
            if best is None or lo > best[0]:
                best = (lo, node)
    if best is None:
        return ""
    wanted = set(names)
    for node in ast.walk(best[1]):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        nm = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
        if nm in wanted:
            return nm
    return ""


def rule_R004_registry_outside_tools(root: Path) -> list[Finding]:
    """在工具层之外直接构造 `ToolRegistry` —— 绕过装配期的角色校验。

    `agent_d.install_d_tools` 正是这样绕过了 `build_registry` 的 `roles` 校验，
    于是 `roles=("agent-C",)` 这种拼错从来没被发现，D 静默少了 3 个工具。

    ## 四次校准（逐次记录，因为它们共同决定了这条规则现在长什么样）

    校准一（豁免脚手架）：落在 `_selftest()` / `__main__` 里的局部注册表是
    测试脚手架，不是装配点。第一版不豁免时在真实代码上命中 17 处，大多数是自检。

    校准二（改为 AST 匹配）：第二版仍是逐行正则，于是在真实代码上产生一个
    纯粹的假阳性：`agent_d.validate_tool_roles` 的 docstring 里写着一句
    ```text
    ``ToolRegistry(name="agent-D")`` + ``register_function``
    ```
    —— 那是在解释这个缺陷，却被当成了缺陷本身。
    "在注释里描述一个反模式"不该被报成"采用了这个反模式"。

    校准三（豁免整条函数链）：判"是不是脚手架"要按嵌套链而不是最内层 def
    （见 `_enclosing_defs`）—— `tools/fs_tools.py` 的命中点在最内层是嵌套小工具
    `check`，在链上才看得到 `_selftest`。

    校准四（豁免正规装配入口与已登记例外）：
    - 同一函数体里调用了 `REGISTRY_BUILDERS`（`build_registry`/`build_for_role`）
      ⇒ roles 校验已经跑过，"绕过"这个前提不成立；
    - 同一函数体里调用了 `ROLE_VALIDATOR_CALLS` 里已登记的校验器 ⇒ 同上；
    - `R004_ALLOWED_SITES` 里逐点登记并写了理由的 ⇒ `info`（不是 `warning`）。

    仍然作为 warning 保留的：`agent_e.install_e_tools` 与 `agent_f.install_f_tools`
    —— 这两条装配路径确实没有任何 roles 校验（`VT.register`/`AT.register` 各自
    按模块级 `_ROLES` 声明角色，注册表本身不再核一次）。它们不是假阳性，
    是已知的、被接受的缺口（`docs/PROPOSALS.md` 的 G-1）；正确的关法是
    P-1（把断言下沉到 `ToolRegistry.register*`，而那在禁 AI 区，须人审），
    不是在这两个入口各补一次断言 —— 那会变成同一判据的第三、第四份实现。
    保留它们为 warning 是刻意的：一个被接受的缺口必须继续出现在报告里，
    否则"接受"会伪装成"已修复"。
    """
    out: list[Finding] = []
    authorities = {str(x).replace("\\", "/") for x in REGISTRY_AUTHORITIES}
    for p in _iter_py(root, SRC_REL):
        rel = p.relative_to(root)
        if str(rel).replace("\\", "/") in authorities:
            continue
        try:
            text = p.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (SyntaxError, OSError):
            continue
        lines = text.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            nm = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else "")
            if nm != "ToolRegistry":
                continue
            lineno = node.lineno
            chain = _enclosing_defs(lines, lineno)
            enc = chain[-1] if chain else ""
            snippet = lines[lineno - 1].strip() if lineno <= len(lines) else ""
            if _is_scaffolding(chain) or _is_in_main_block(lines, lineno):
                continue
            site = (str(rel).replace("\\", "/"), enc)
            if site in R004_ALLOWED_SITES:
                out.append(Finding(
                    "R004", "info", str(rel), lineno,
                    f"{site[0]}:{lineno}（函数 `{enc}`）构造 `ToolRegistry`，但该装配点"
                    f"已逐点登记为例外：{R004_ALLOWED_SITES[site]}",
                    snippet,
                ))
                continue
            satisfied = _calls_named(tree, lineno, (*ROLE_VALIDATOR_CALLS, *REGISTRY_BUILDERS))
            if satisfied:
                out.append(Finding(
                    "R004", "info", str(rel), lineno,
                    f"{site[0]}:{lineno} 在工具层之外构造 `ToolRegistry`，但同一函数体里调用了 "
                    f"`{satisfied}` ⇒ 不算绕过（roles 校验已经跑过）",
                    snippet,
                ))
                continue
            out.append(Finding(
                "R004", "warning", str(rel), lineno,
                "在工具层之外直接构造 `ToolRegistry` ⇒ 绕过了装配期的 roles 校验。"
                "请改用 `tools.build_registry`/`build_for_role`，"
                "或显式调用同一份校验函数（不要复制它的判据）；"
                "若该装配点确实用别的方式执行了同一条断言，请把函数名加进 "
                "`ROLE_VALIDATOR_CALLS`，或把 `(文件, 函数)` 加进 `R004_ALLOWED_SITES` 并写清理由",
                snippet,
            ))
    return out


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
    """
    markers = ("urllib", "http.client", "socket", "subprocess", "requests.", "httpx", "easyocr.Reader")
    out: list[Finding] = []
    for p in _iter_py(root, SRC_REL):
        lines = p.read_text(encoding="utf-8").splitlines()
        text = "\n".join(lines)
        if 'side_effect="read"' not in text and "side_effect='read'" not in text:
            continue
        hits = [i + 1 for i, raw in enumerate(lines)
                if any(m in raw for m in markers) and not raw.lstrip().startswith("#")]
        if not hits:
            continue
        out.append(Finding(
            "R006", "info", str(p.relative_to(root)), hits[0],
            f"本文件既有 `side_effect=\"read\"` 的工具声明，又有 {len(hits)} 处网络/子进程/模型调用"
            f"（行 {hits[:5]}{'…' if len(hits) > 5 else ''}）⇒ 请核对具体那个工具的副作用声明"
            "。文件级共现不是缺陷证据：声明 read 的工具无需审批，而它若真的联网，"
            "权限面就在说假话（`search.providers`、`ocr.run` 都曾如此）",
        ))
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
_R010_ALLOWED_SITES: dict[str, str] = {
    "verify.detect_verifier": (
        "按定义不是 exec：它跑的命令是工具自己写死的 `_VERIFIER_CANDIDATES`"
        "（`lean --version` / `coqc --version` / `isabelle version`），"
        "调用方决定不了跑什么（P-13 §10 第 1 条逐字登记了这处歧义）。"
        "它仍是 `subprocess.run` ⇒ 字面判据命中，所以在此登记而不是改声明。"
    ),
    "verify.check_formal": (
        "按定义是 exec（执行由调用方给内容的检查器），但本轮的硬约束是"
        "「55 个既有工具的行为逐字不变」：把它改成 external='exec' 会让它立刻需要"
        "人工审批，而 `tests/test_tools_audit_fixes.py` 断言了它当前不需要。"
        "⇒ 先在 B3 的迁移清单里认领（P-13 §4.2 第 6 条：`E.check_formal` 的"
        "能力层新值就是 read + exec），本轮只登记。"
    ),
}

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
            external = _r010_literal(_r010_kw(dec, "external"), "")
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
        external = _r010_literal(_r010_kw(node, "external"), "")
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


def _r010_read_legacy_table(root: Path) -> tuple[dict[str, tuple[str, str]], int] | None:
    """读 `tools/base.py` 里那张逐工具遗留翻译表 ⇒ `(表, 行号)`；读不到返回 `None`。

    为什么必须去读它而不是在 lint 里再写一份：那张表是"遗留取值到底写不写
    我们的东西"的唯一来源。在 lint 里复述一份，两处必然漂移，而漂移的形态是
    "工具层翻译成 write_local、规则以为它没登记" —— 一个没有任何报错的错误结论。
    读不到时返回 `None`，由调用方报 unknown（三态纪律：读不到 ≠ 没问题）。
    """
    path = root / _R010_TOOLS_REL / "base.py"
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "LEGACY_EFFECTS_BY_TOOL":
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            return None
        table: dict[str, tuple[str, str]] = {}
        for key, val in zip(value.keys, value.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if not (isinstance(val, ast.Tuple) and len(val.elts) == 2):
                continue
            parts = [e.value for e in val.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(parts) == 2:
                table[key.value] = (parts[0], parts[1])
        return (table, node.lineno)
    return None


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

    ## `external` 从哪里来（遗留取值的处理）

    - 工具自己写了 `external=` ⇒ 用它的值；
    - 写了 `side_effect="network"`（遗留取值）⇒ 按 `base.LEGACY_EFFECTS_BY_TOOL`
      翻译成 `egress`，于是 R010-b 会在迁移期命中这些工具 —— 这是刻意的：
      "声明出网却查不到网络调用"正是本规则要数出来的那件事，
      而"当前声明是遗留取值"不是免检理由（保守的假话仍然是假话）；
    - 两者都没写 ⇒ `none`（与 `ToolSpec.external` 的默认值同一口径）。
      于是 `subprocess` 出现在 handler 链里、却没人声明 `external` 的工具
      会被 R010-a 命中 —— 这正是 P-13 §10 第 1 条那处歧义的落点，
      由 `_R010_ALLOWED_SITES` 逐条登记并写明理由。

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
        # `LEGACY_EFFECTS_BY_TOOL` 读不到（error）或文件解析不了（warning）报出来。
        return [Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            f"没有工具层源码目录 {base} ⇒ 本次核对了 0 条工具声明"
            "（没有工具声明，不是'声明都对'）",
        )]

    out: list[Finding] = []
    checked = 0
    legacy: list[str] = []
    fired_gaps: list[str] = []
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
            if spec["side_effect"] == "network":
                legacy.append(name)
                external = "egress"
            else:
                external = spec["external"] or "none"
            procs = _r010_markers_reachable(spec["roots"], defs, _R010_PROCESS_MARKERS)
            nets = _r010_markers_reachable(spec["roots"], defs, _R010_NETWORK_MARKERS)
            if procs and external != "exec":
                reason = _R010_ALLOWED_SITES.get(name)
                if reason is not None:
                    out.append(Finding(
                        "R010", "info", rel, spec["line"],
                        f"{name} 的 handler 链里出现了起子进程的调用（{procs}），而它声明 "
                        f"external={external!r} ⇒ 按**字面判据**会报 error，但本工具"
                        f"**已逐条登记为例外**：{reason}",
                    ))
                else:
                    out.append(Finding(
                        "R010", "error", rel, spec["line"],
                        f"{name} 声明 external={external!r}（即'我不在宿主上执行程序'），"
                        f"而它的 handler 链里出现了起子进程的调用（{procs}）⇒ "
                        "**声明与代码不符**。这一根轴直接决定审批与沙箱是否生效："
                        "改了代码就要改声明，改了声明就要重算审批面。"
                        "若它按轴的**定义**确实不是 exec（命令内容由工具自己写死），"
                        "请把工具名与理由加进 `_R010_ALLOWED_SITES`（那是共享轴定义的一部分，"
                        "不是给规则开后门：它会以 info 继续出现在报告里）",
                    ))
            elif procs and name in _R010_KNOWN_GAPS:
                fired_gaps.append(name)
            if external == "egress" and not nets:
                out.append(Finding(
                    "R010", "warning", rel, spec["line"],
                    f"{name} 声明 external='egress'，但它的 handler 链里**没有任何**网络调用"
                    "（标记见 `_R010_NETWORK_MARKERS`）⇒ 要么声明写错了，要么代码走了一条"
                    "本规则看不出来的路径。保守的假话仍然是假话：审计问'哪些工具会出网'时"
                    "会把不联网的工具列进去（P-13 §9③ 与 DEVELOPMENT.md 的 P7）",
                ))

    if legacy:
        out.append(Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            f"遗留计数：全仓还有 {len(legacy)} 处 `side_effect=\"network\"`"
            f"（{', '.join(sorted(legacy))}）。它们由 `base.LEGACY_SIDE_EFFECTS` 与 "
            "`base.LEGACY_EFFECTS_BY_TOOL` 两张显式翻译表承接，**行为不变**"
            "（继续需要审批、继续被只读角色剥离）。这个数字必须单调降到 0，"
            "然后翻译表本身也要删掉（P-13 §3.2：只增不减的迁移不是迁移）",
        ))
    else:
        out.append(Finding(
            "R010", "info", str(_R010_TOOLS_REL), 0,
            "遗留计数：0 处 `side_effect=\"network\"`（词表里已无该遗留取值，"
            "或本规则一条声明都没读到 —— 结合下面那条'核对了 N 条'的 info 一起读）",
        ))

    # ---- 逐工具翻译表的完整性：这张表与"实际还有几处遗留"必须同步收敛
    table = _r010_read_legacy_table(root)
    if table is None:
        out.append(Finding(
            "R010", "error", str(_R010_TOOLS_REL / "base.py"), 0,
            "读不到 `LEGACY_EFFECTS_BY_TOOL`（逐工具遗留翻译表）⇒ 本次无法判断"
            "'还剩几处遗留、各自是什么原意' —— 这是**没查成**，不是没问题",
        ))
    else:
        entries, lineno = table
        missing = sorted(set(legacy) - set(entries))
        extra = sorted(set(entries) - set(legacy))
        if missing:
            out.append(Finding(
                "R010", "error", str(_R010_TOOLS_REL / "base.py"), lineno,
                f"这些工具声明了遗留取值 `network`，但 `LEGACY_EFFECTS_BY_TOOL` 里没有"
                f"它们的原意：{missing} ⇒ 翻译结果会退回默认值，于是'它其实会写我们的东西'"
                "这个事实被丢掉（P-13 §3.2：遗留取值必须被**显式**翻译）",
            ))
        if extra:
            out.append(Finding(
                "R010", "warning", str(_R010_TOOLS_REL / "base.py"), lineno,
                f"`LEGACY_EFFECTS_BY_TOOL` 里有翻不出来的条目（对应的工具已经不再声明"
                f"`network`）：{extra} ⇒ 翻译表该删了。只增不减的迁移不是迁移"
                "（P-13 §3.2）",
            ))
        if not missing and not extra:
            out.append(Finding(
                "R010", "info", str(_R010_TOOLS_REL / "base.py"), lineno,
                f"逐工具遗留翻译表与实际遗留声明逐条一致（{len(entries)} 条）",
            ))
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        f"本规则逐工具核对了 {checked} 条工具声明（转发链深度上限 4；"
        "handler 是取不到的名字或链更深时那一条**没核对**）。"
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
    out.append(Finding(
        "R010", "info", str(_R010_TOOLS_REL), 0,
        "本规则的**已知漏检**（转发链断在工具层之外，本规则看不见，不等于没问题）："
        + "；".join(f"{n} —— {why}" for n, why in sorted(_R010_KNOWN_GAPS.items())),
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


RULES: tuple[tuple[str, object], ...] = (
    ("R001 except-pass", rule_R001_bare_except_pass),
    ("R002 None→空容器", rule_R002_none_folds_to_empty),
    ("R003 同名公开定义", rule_R003_duplicate_public_defs),
    ("R004 工具层外构造注册表", rule_R004_registry_outside_tools),
    ("R005 写死角色名单", rule_R005_hardcoded_role_list),
    ("R006 read 工具碰网络", rule_R006_read_tool_touches_network),
    ("R007 缺 docstring", rule_R007_missing_docstring),
    ("R008 脚本无退出码", rule_R008_scripts_without_exit_code),
    ("R009 注释里的装饰", rule_R009_decoration_in_comments),
    ("R010 装置轴与代码不符", rule_R010_external_axis_mismatch),
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


def main(argv: Sequence[str] | None = None) -> int:
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
        Path(args.json).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    mode = "严格（发布级）" if args.strict else "日常"
    print(f"[linter] 扫描 {d['scanned']}；规则 {len(d['rules_run'])} 条；模式 {mode}")
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
