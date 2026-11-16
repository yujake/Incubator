# -*- coding: utf-8 -*-
"""彩排契约：唯一一份打桩白名单 + 入口表 + 链外登记（数据 + 纯函数，无断言）。

## 这份文件回答什么

业主 2026-11-15 的硬要求逐字：

> 「要保证彩排路径与真机路径用的东西实际上是一致的」

`temp/sp/REPORT-SP.md` 的审计读数：14 份 `test_rehearsal_*.py` 里「真同路径」0 条
（`LlmSeam.ask` 只被调用 2 次、`AgentLoop.run` 0 次、11 份账本 0 行的假零）。
本文件把「什么算同一条路」落成可机核的三张表，判据本体在
`tests/test_rehearsal_same_path.py`：

1. 入口表（:data:`CLI_ARGV0`）：真机的入口是 `cli.main([...])`（或
   `python -m agentflow`）；从 `Conductor.summon` / 直接调 `AgentX` 进去都低一层
   —— 那条路没有 `_run_spec` / `LlmBackend` / `AgentLoop.run` / 收工门。
2. 打桩白名单（:data:`WHITELIST`，五类 + env）：只许替换
   `llm_seam` / `time` / `random` / `subprocess` / `external_io`（网络出口）。
   其余一律是「把被测的那一段换掉」——绿了说明不了真机。
3. 链外登记（:data:`CHAIN_ONLY`）：改不成 CLI 入口的旧彩排逐条登记
   名称 + 理由 + 它证明了什么 / 没证明什么，并断言它们不得被文档/报告
   引用为「彩排已走通」。它们不再是「真机前置证据」。

## 为什么 `complete` 的替身可以，`ask` 的不可以

`temp/sp/REPORT-SP.md` §1.8 把唯一的缝说得很准：

- 十角色链的审计缝唯一：`llmseam.LlmSeam.ask`（`ask_json` / `ask_step` 是它的包装）；
- 出网唯一：`modelgw.ModelGateway.complete`。

所以「换掉 `ask`」= 换掉了预算闸 / 账本行 / `llm_call` 事件 / ambient 解析 ——
三格必然测不到；而「换掉 `complete`」正是任务书要求的替换点
（真 `LlmSeam` + 真 `TokenMeter`，只让网关返回预置 JSON）。
:func:`scripted_seam` 就是那一种替身的唯一构造入口。

## 两个刻意的边界

- 本文件不是判据：这里不 `assert`。判据在 `test_rehearsal_same_path.py`，
  一处定义、一处报红，免得「表在这儿、判在那儿」漂成两份。
- `CHAIN_ONLY` 不是豁免面：登记之后判据仍要求「它确实不是同一条路」
  （`test_chain_only_files_really_are_not_same_path`）—— 谁把它改成了 CLI 入口，
  那条判据会红，逼他把它从这张表里摘出去。
"""
from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Mapping, Sequence

#: 测试目录（本文件所在）。`PROJECT_ROOT` 是 `agentflow/`。
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent
SRC_DIR = PROJECT_ROOT / "src" / "agentflow"

#: 彩排文件的命名口径（业主与既有 14 份都按它认）。
REHEARSAL_PREFIX = "test_rehearsal_"

#: 判据本体（本文件 + `test_rehearsal_same_path.py`）也匹配 `test_rehearsal_*`，
#: 必须显式排除：否则「扫彩排文件」会把判据本体当成彩排去判它
#: （实测：不排除时它会以「入口不是 CLI / 自造 `_DuckSeam`」被判红 —— 判据自伤）。
CONTRACT_FILE = Path(__file__).name
CONTRACT_TEST_FILE = "test_rehearsal_same_path.py"
#: WF 判据（2026-11-16）：这两份也是"判据"，不是彩排 —— 它们复用
#: `test_rehearsal_c13_wake.py` / `test_rehearsal_c4_revision_loop.py` 的真入口 `_run`，
#: 只加正控 / 反真空 / 负控。反真空必须把产品那一格（接线 / 洗稿）摘掉才能证明
#: 正控不是真空的；那与「打桩只许五类」的静态判据天然冲突，而把判据文件当彩排扫
#: 只会自伤。真机同路径的证据仍由那两份彩排提供（它们仍在这张名单里、三格照跑）。
WF_CRITERIA_FILES = (
    "test_rehearsal_c13_wake_chain.py",
    "test_rehearsal_c4_revision_chain.py",
)

#: A 侧文献全流程的判据文件（2026-11-16 RA1）：与上面两份 WF 判据同形。
#:
#: 它复用 `test_rehearsal_a_literature_flow.py` 的真入口 `_run`（CLI + 真 `LlmSeam`），
#: 只在旁边加反真空 / 负控 / 产品就绪判据。反真空必须打桩「产品那一格」
#: （`litstage._decisions_from` 回填空 / `_rejected_entry` 去号 / `_numbered_entry` 定稿的号 /
#: `judged_state` 收工门那一格的读数）—— 这与「打桩只许五类」的静态判据天然冲突，
#: 而把判据文件当彩排扫只会自伤。真机同路径的证据仍由那份彩排提供（它仍在这张
#: 名单里、三格照跑）；本文件不提供同路径证据，只回答"那几条闸承不承重"。
FLOW_CRITERIA_FILES = (
    "test_rehearsal_a_literature_flow_criteria.py",
)

#: 「真机前置证据」的正面登记：这些彩排走的是 CLI 入口 + 真 `LlmSeam` + 真账本 + 三格探针。
#:
#: 为什么要有它：`CHAIN_ONLY` 是一张「不是同一条路」的黑名单，单靠它回答不了
#: 「那到底哪几条算证据」。本表逐条登记正面证据，并由判据钉住三件事：它不在
#: `CHAIN_ONLY` 里、`is_rehearsal_module` 认它（三格照跑）、它确实从 CLI 入口进。
#:
#: 本表只登记 2026-11-16 之后新增的那几条；更早的彩排各自另有判据（它们没登记在这里
#: 不等于它们不是证据，也不等于本表是全集）。
SAME_PATH_EVIDENCE: tuple[str, ...] = (
    "test_rehearsal_a_literature_flow.py",
)

_EXCLUDED = frozenset({CONTRACT_FILE, CONTRACT_TEST_FILE,
                       *WF_CRITERIA_FILES, *FLOW_CRITERIA_FILES})

# ============================================================ 一 入口表

#: 合法入口：`cli.main([...])`。模块别名解析回 `agentflow.cli` 之后按末段比对。
CLI_MODULE = "cli"
CLI_MAIN = "main"

#: 允许的首个位置参数（真命令）。`incubate start` 在解析前折回 `start`，
#: 不是第二条执行链（`cli.canonical_argv`），所以这里只登记这三个。
CLI_ARGV0 = frozenset({"start", "run", "run-agent"})

#: 另一种同样合法的入口：真进程 `[sys.executable, "-m", "agentflow", ...]`。
MODULE_ENTRY = "agentflow"

# ============================================================ 二 打桩白名单

#: 键 = `(模块末段, 属性)`；值 = 归类。五类之外一律不许打桩。
#:
#: 模块名取末段（`agentflow.tools.verify_tools` → `verify_tools`）：彩排文件
#: 用 `from agentflow.tools import verify_tools as VT` 之后，AST 只看得到 `VT`，
#: 归一化到末段是唯一能跨写法对齐的口径。
WHITELIST: dict[tuple[str, str], str] = {
    # ---- llm_seam：模型缝 / 缝工厂 / 出网传输
    ("modelgw", "ModelGateway"): "llm_seam",
    ("modelgw", "urllib_transport"): "llm_seam",
    ("modelgw", "spec_for"): "llm_seam",
    ("modelgw", "spec_from_env"): "llm_seam",
    ("llmseam", "LlmSeam"): "llm_seam",
    ("llmseam", "set_role_seam"): "llm_seam",
    ("llmseam", "set_role_config"): "llm_seam",
    ("llmseam", "assert_real_seam"): "llm_seam",
    ("cli", "_agent_seam_factory"): "llm_seam",
    ("host", "_seam"): "llm_seam",
    ("agent_f", "set_default_llm"): "llm_seam",
    # ---- time：时钟 / 日期
    ("clock", "*"): "time",
    ("schema", "now_iso"): "time",
    ("time", "*"): "time",
    ("datetime", "datetime"): "time",
    ("datetime", "now"): "time",
    # ---- random：种子
    ("random", "*"): "random",
    ("uuid", "uuid4"): "random",
    ("secrets", "*"): "random",
    # ---- subprocess：外部进程
    ("subprocess", "*"): "subprocess",
    ("os", "system"): "subprocess",
    # ---- external_io：网络出口（含检索 provider）
    ("providers", "*"): "external_io",
    ("urllib", "*"): "external_io",
    ("urllib.request", "*"): "external_io",
    ("httpx", "*"): "external_io",
    ("requests", "*"): "external_io",
}

#: 整模块可打桩的那些（键 `(模块, "*")` 的书写糖）。
WILDCARD_MODULES = frozenset({"clock", "time", "random", "subprocess", "secrets",
                              "providers", "urllib", "urllib.request", "httpx",
                              "requests"})

#: `monkeypatch.setenv` / `delenv` 单列一档：它改的是「这台机器上装了什么」，
#: 不是行为桩。业主的硬要求里没有这一档，但它与五类同族（外部条件）。
ENV_METHODS = frozenset({"setenv", "delenv"})

#: 打桩命中白名单外时的归类提示（报红信息里点名「这是哪一层」）。
FORBIDDEN_HINT: dict[str, str] = {
    "agent_loop": "步循环 / 工具分发",
    "secretary": "秘书语义判断",
    "tools": "工具分发",
    "base": "工具分发",
    "closing": "收工门",
    "manuscriptclosing": "收工门",
    "policy": "策略",
    "interactions": "准入闸",
    "vsigns": "签发",
    "verifications": "签发 / 准入",
    "tokenmeter": "台账写口",
    "store": "存储写口",
    "agent_b": "角色实现 / 形态闸",
    "agent_c": "角色实现",
    "agent_e": "角色实现 / 数值通道",
    "agent_f": "角色实现",
    "agent_l": "角色实现",
    "review_tools": "工具层实现",
    "verify_tools": "证明检查器桥接层",
    "locallib": "本地文献解析",
    "extract": "文本抽取主通道",
    "modelcost": "计价口径",
}

#: 缝的接口面（`LlmSeam`）：彩排文件里自造这几个方法 = 换掉了缝本身。
SEAM_METHODS = frozenset({"ask", "ask_json", "ask_step"})

#: 网关的接口面（`ModelGateway`）：这正是允许替身的那一层（只它一个方法）。
GATEWAY_METHODS = frozenset({"complete"})

#: 把模型对象塞进产品构造器的形参名（静态判定「构造期直接替换」用）。
SEAM_KWARGS = ("seam", "llm", "extractor", "seam_factory", "reviewer", "reader")

#: 私有直调：从产品源码里现扫出来的类私有方法名（见 :func:`product_private_names`）。
_SRC_CACHE: dict[str, Any] = {}


# ============================================================ 三 链外登记

#: 改不成 CLI 入口的旧彩排：名称 → 理由 + 它证明了什么 / 没证明什么。
#:
#: 字段：
#: - ``chain``：这条彩排覆盖的是哪条协作链；
#: - ``reason``：为什么它不能作为「真机同一条路」的证据（逐条具体，不写「覆盖不足」）；
#: - ``proves``：它仍然证明了什么（这些读数仍然有用，只是不能当前置）；
#: - ``does_not_prove``：它没有证明什么（真机上因此仍然未知的那一段）；
#: - ``superseded_by``：改用 CLI 入口 + 真 `LlmSeam` 的那份新彩排（没有就空串）。
CHAIN_ONLY: dict[str, dict[str, str]] = {
    "test_rehearsal_b_intake_exits.py": {
        "chain": "C5 · B 收编的形态闸 / 同一性门出口",
        "reason": "直调 `AgentB.register_statement` / `AgentF.rewrite_manuscript_proposition`，"
                  "秘书是手工造的 `_Seam(ask_json)`；还打桩 `proofregistry.replace_section` 与 "
                  "`AgentB._proposition_form_gate`。入口比 CLI 低两层，缝是自造替身。",
        "proves": "形态闸对引文侧/手稿侧的放行与受控拒各自的分支，以及同一性门的三态读数。",
        "does_not_prove": "这些判断在真机 CLI 的步循环里被调用时会拿到同一个号、落进同一本账；"
                          "三格的格②（caller_role）与格③（账本行）都没有对象。",
        "superseded_by": "test_rehearsal_cli_proof_main_chain.py",
    },
    "test_rehearsal_b_multi_path.py": {
        "chain": "C6 · 同命题多条证明路径",
        "reason": "直调 `AgentB.ingest_manuscript` + 手工 `Secretary`，并用 conftest 的 "
                  "`b_form_gate_ok` 换掉秘书的形态判定方法。",
        "proves": "`path_group` 的逐路径记账与命题级取 min 的规则。",
        "does_not_prove": "真机从 CLI 走进来时它仍然成立（判定面被换掉了）。",
        "superseded_by": "",
    },
    "test_rehearsal_c11_formal.py": {
        "chain": "C11 · 形式化链（B → L → C）",
        "reason": "走工具层 `build_registry().call(\"formal.*\")`（比 CLI 低两层）；打桩 "
                  "`verify_tools.check_formal` / `detect_verifier` / `AgentL.check_formal`。",
        "proves": "L 的三件工具面与 Lean 桥接层在开档下的读数口径。",
        "does_not_prove": "真机从 `run-agent L` / `start --mode research` 走进来时的装配与账本。",
        "superseded_by": "",
    },
    "test_rehearsal_c2_proof_chain.py": {
        "chain": "C2 · 证明主链（登记 → 送审 → 三签 → 收录 → 依赖）",
        "reason": "三个角色都是直调（`v.verify_proof` / `b.ingest_manuscript`），缝是自造 "
                  "`_Seam(ask_json)` + `_Review(ask)` + `_FakeF(complete)`；另打桩 `vsigns.issue`。",
        "proves": "主链各段的终态读数与「V 没签 ⇒ 链红」的反真空。",
        "does_not_prove": "真机 CLI → `_exec_role` → `LlmBackend` → `AgentLoop.run` 这条路上，"
                          "三签与收录是否仍按同一顺序发生；三格没有对象。",
        "superseded_by": "test_rehearsal_cli_proof_main_chain.py",
    },
    "test_rehearsal_two_f_independent_proofs.py": {
        "chain": "双 F · 同命题独立第二份证明",
        "reason": "直调 `AgentB` + 手工 `Secretary`；打桩 `manuscript_id_for_path`、"
                  "`AgentB._optimization_replace_enabled`，并用 `b_form_gate_ok` / "
                  "`signed_v_handoffs` 换掉判定与签名。",
        "proves": "两条路径的编号、签名与命题级取 min 的规则。",
        "does_not_prove": "真机里第二份证明由 F 自己交、由 B 的循环收（入口与判定面都不是产品那条）。",
        "superseded_by": "",
    },
}


# ============================================================ 数据结构


@dataclass(frozen=True)
class Source:
    """一行 AST 的可读定位（报红信息用它，别让读者自己去数行）。"""

    file: str
    line: int
    text: str


@dataclass(frozen=True)
class StubTarget:
    """一次打桩：解析后的目标 + 白名单判定。"""

    where: Source
    module: str
    attr: str
    category: str          # 白名单归类（空串 = 不在白名单里）
    env: bool              # `monkeypatch.setenv/delenv` 那一档


@dataclass(frozen=True)
class EntryCall:
    """一次合法入口调用（`cli.main([...])` 或 `python -m agentflow`）。"""

    where: Source
    argv0: str
    how: str               # "cli.main" / "module"


@dataclass(frozen=True)
class StubClass:
    """彩排文件里自定义的模型替身类。"""

    where: Source
    name: str
    methods: tuple[str, ...]
    seam_surface: bool     # True = 定义了 ask/ask_json/ask_step（换掉缝）


# ============================================================ 一 文件与语法树


def rehearsal_files() -> list[Path]:
    """全部彩排文件（按名字排序；排除判据本体与两份契约文件）。"""
    return sorted(p for p in TESTS_DIR.glob(f"{REHEARSAL_PREFIX}*.py")
                  if p.name not in _EXCLUDED)


def is_rehearsal_module(path: str | Path) -> bool:
    """这个模块是不是「声称自己走真机同一条路」的彩排（运行期三格只对它生效）。

    `CHAIN_ONLY` 里的文件不是：它们已登记为「不是同一条路」，
    对它们再跑三格断言只会让套件永远红，而不会多出任何信息。
    它们的实测读数在 `temp/rc2/` 的探针里单独记（见交付报告）。
    """
    name = Path(path).name
    return (name.startswith(REHEARSAL_PREFIX) and name not in _EXCLUDED
            and name not in CHAIN_ONLY)


def parse(path: str | Path) -> ast.Module:
    """读一个文件并解析成语法树（编码固定 UTF-8：本仓全部源文件都是 LF + UTF-8）。"""
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def _source_line(tree: ast.Module, path: Path, node: ast.AST) -> Source:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    line = int(getattr(node, "lineno", 0) or 0)
    text = lines[line - 1].strip() if 0 < line <= len(lines) else ""
    return Source(file=Path(path).name, line=line, text=text)


# ============================================================ 二 导入别名


def import_aliases(tree: ast.Module) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """解析导入：`(模块别名 → 模块末段, 符号别名 → (模块末段, 原符号))`。

    `from agentflow import locallib as LL` 与 `from agentflow.tools import verify_tools`
    都归到末段：彩排文件里的写法五花八门，只有末段是跨写法稳定的那一格。
    `import agentflow.cli as cli` 也归到 `cli`。
    """
    modules: dict[str, str] = {}
    symbols: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                last = alias.name.split(".")[-1]
                modules[alias.asname or last] = last
                if alias.asname:
                    modules[alias.asname] = last
        elif isinstance(node, ast.ImportFrom):
            base = (node.module or "").split(".")[-1]
            for alias in node.names:
                local = alias.asname or alias.name
                if alias.name == "*":
                    continue
                symbols[local] = (base, alias.name)
    return modules, symbols


# ============================================================ 三 打桩扫描


def _chain_of(node: ast.AST) -> tuple[str, list[str]] | None:
    """把 `A.b.c` 拆成 `("A", ["b", "c"])`；不是属性链就返回 None。"""
    attrs: list[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        attrs.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        attrs.reverse()
        return cur.id, attrs
    return None


def _stub_call(node: ast.Call) -> bool:
    """这次调用是不是 `monkeypatch.setattr` / `mock.patch[...]` 这一类打桩。"""
    func = node.func
    name = func.attr if isinstance(func, ast.Attribute) else (
        func.id if isinstance(func, ast.Name) else "")
    if name in ENV_METHODS:
        return False
    return name in {"setattr", "patch", "object", "patch.object"}


def stub_targets(tree: ast.Module, path: Path) -> list[StubTarget]:
    """扫出全部打桩点，并把目标解析回 `(模块末段, 属性)`。

    认三种写法（本仓常见的三种都覆盖）：
    - `monkeypatch.setattr(target, "attr", ...)`
    - `mock.patch.object(target, "attr", ...)` / `patch.object(...)`
    - `monkeypatch.setenv/delenv(...)` → 单列 `env` 档（不算行为桩）
    """
    modules, symbols = import_aliases(tree)
    out: list[StubTarget] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        fname = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        where = _source_line(tree, path, node)
        if fname in ENV_METHODS:
            out.append(StubTarget(where=where, module="env", attr=fname, category="env", env=True))
            continue
        if not _stub_call(node):
            continue
        # `mock.patch.object(X, "attr")` 的第一个实参是目标；第二个是属性名。
        args = list(node.args)
        if fname == "object" and isinstance(func, ast.Attribute):
            args = args  # patch.object(target, name, ...)
        if len(args) < 2:
            continue
        target, attr_node = args[0], args[1]
        attr = ""
        if isinstance(attr_node, ast.Constant) and isinstance(attr_node.value, str):
            attr = attr_node.value
        elif isinstance(attr_node, ast.Attribute):
            attr = attr_node.attr
        chain = _chain_of(target)
        if chain is None:
            out.append(StubTarget(where=where, module="?", attr=attr, category="", env=False))
            continue
        base, attrs = chain
        if base in modules:
            module = modules[base]
            full = ".".join(attrs + ([attr] if attr else []))
            out.append(StubTarget(where=where, module=module, attr=full,
                                  category="", env=False))
        elif base in symbols:
            mod, symbol = symbols[base]
            if symbol in _src_module_names():
                # `from agentflow import proofregistry as PR`：`PR` 是模块别名，
                # 不是符号别名 —— 目标要落到 `proofregistry.replace_section`。
                module = symbol
                full = ".".join(attrs + ([attr] if attr else []))
            else:
                module = mod
                full = ".".join([symbol] + attrs + ([attr] if attr else []))
            out.append(StubTarget(where=where, module=module, attr=full,
                                  category="", env=False))
        else:
            # 裸名字（`setattr(Store, "tx")` 里的 Store）：用属性名反查白名单。
            out.append(StubTarget(where=where, module="", attr=".".join(attrs + ([attr] if attr else [])),
                                  category="", env=False))
    return out


def _src_module_names() -> frozenset[str]:
    """`src/agentflow` 下全部模块的末段名（判「这个别名是模块还是符号」用）。"""
    if "modules" not in _SRC_CACHE:
        _SRC_CACHE["modules"] = frozenset(p.stem for p in SRC_DIR.rglob("*.py"))
    return _SRC_CACHE["modules"]


def whitelist_category(module: str, attr: str) -> str:
    """这次打桩落在白名单的哪一类（空串 = 白名单外）。"""
    if module and (module, "*") in WHITELIST:
        return WHITELIST[(module, "*")]
    first = attr.split(".")[0] if attr else ""
    for key in ((module, attr), (module, first)):
        if key in WHITELIST:
            return WHITELIST[key]
    if not module:
        # 裸名字那一档：按属性名在整张表里反查（`Store` 不在白名单，`uuid4` 在）。
        for (_mod, known), category in WHITELIST.items():
            if known == first:
                return category
    return ""


def classify_stubs(tree: ast.Module, path: Path) -> list[StubTarget]:
    """把打桩点补上归类（白名单内的也返回，判据只看 `category == ""` 的那些）。"""
    out = []
    for got in stub_targets(tree, path):
        category = got.category or whitelist_category(got.module, got.attr)
        out.append(StubTarget(where=got.where, module=got.module, attr=got.attr,
                              category=category, env=got.env))
    return out


def hint_for(module: str, attr: str) -> str:
    """白名单外的打桩点，说清它大概是哪一层（报红信息里的「归类提示」）。"""
    if module == "?":
        return "动态目标（`type(x)` / 下标一类，静态解析不到具体模块）"
    if not module:
        return "产品实现（无法从导入别名解析到模块）"
    return FORBIDDEN_HINT.get(module, f"{module} 的实现")


# ============================================================ 四 入口扫描


def cli_entry_calls(tree: ast.Module, path: Path) -> list[EntryCall]:
    """扫出合法入口调用。

    1. `cli.main(["start", ...])` / `main([...])`（后者要求 `main` 是从 `agentflow.cli` 导入的）；
    2. `subprocess.run([sys.executable, "-m", "agentflow", ...])`（真进程，更真）。
    """
    modules, symbols = import_aliases(tree)
    out: list[EntryCall] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        where = _source_line(tree, path, node)
        # ---- 1 cli.main / main
        if isinstance(func, ast.Attribute) and func.attr == CLI_MAIN:
            base = func.value
            base_name = base.id if isinstance(base, ast.Name) else ""
            got = modules.get(base_name, "")
            if not got and base_name in symbols:
                # `from agentflow import cli`：别名在符号表里，模块是 `cli`。
                mod, sym = symbols[base_name]
                if sym == CLI_MODULE:
                    got = CLI_MODULE
            if got == CLI_MODULE:
                argv0 = _argv0_of(node)
                if argv0:
                    out.append(EntryCall(where=where, argv0=argv0, how="cli.main"))
        elif isinstance(func, ast.Name) and func.id == CLI_MAIN \
                and symbols.get(CLI_MAIN, ("", ""))[0] == CLI_MODULE:
            argv0 = _argv0_of(node)
            if argv0:
                out.append(EntryCall(where=where, argv0=argv0, how="cli.main"))
        # ---- 2 python -m agentflow
        if isinstance(func, ast.Attribute) and func.attr == "run" and node.args:
            argv = node.args[0]
            if isinstance(argv, (ast.List, ast.Tuple)) and len(argv.elts) >= 3:
                words = [e.value for e in argv.elts
                         if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if "-m" in words:
                    idx = words.index("-m")
                    if idx + 1 < len(words) and words[idx + 1] == MODULE_ENTRY:
                        tail = words[idx + 2:]
                        if tail and tail[0] in CLI_ARGV0:
                            out.append(EntryCall(where=where, argv0=tail[0], how="module"))
    return out


def _argv0_of(call: ast.Call) -> str:
    """`cli.main([...])` 的第一个实参列表里的首个字符串（不是列表 ⇒ 空串）。"""
    if not call.args:
        return ""
    argv = call.args[0]
    if not isinstance(argv, (ast.List, ast.Tuple)):
        return ""
    for elt in argv.elts:
        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
            return elt.value
        return ""      # 第一个位置是变量/表达式：入口不可静态核对
    return ""


# ============================================================ 五 自造替身扫描


def stub_classes(tree: ast.Module, path: Path) -> list[StubClass]:
    """彩排文件里自定义的模型替身类（带 `ask/ask_json/ask_step/complete` 的类）。"""
    out: list[StubClass] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = {m.name for m in node.body
                   if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))}
        hit = tuple(sorted(methods & (SEAM_METHODS | GATEWAY_METHODS)))
        if not hit:
            continue
        out.append(StubClass(where=_source_line(tree, path, node), name=node.name,
                             methods=hit, seam_surface=bool(methods & SEAM_METHODS)))
    return out


def seam_kwarg_uses(tree: ast.Module, path: Path, class_names: Sequence[str]) -> list[Source]:
    """这些替身类有没有被当成「缝 / 模型对象」塞进产品构造器（`seam=` / `llm=` …）。

    `gateway=` 不在这一档：那是允许的替换点（真 `LlmSeam` + 预置网关）。
    """
    names = set(class_names)
    out: list[Source] = []

    def _refers(expr: ast.AST) -> bool:
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and n.id in names:
                return True
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in SEAM_KWARGS and _refers(kw.value):
                    out.append(_source_line(tree, path, node))
                    break
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Attribute) and target.attr in {"llm", "seam"} \
                        and _refers(node.value):
                    out.append(_source_line(tree, path, node))
    return out


# ============================================================ 六 私有直调扫描


def _scan_src() -> tuple[frozenset[str], frozenset[str]]:
    """从 `src/agentflow` 现扫：类私有方法名 + 模块私有函数名。

    为什么不写死一张名单：私有方法会改名、会新增。现扫的口径是「产品里真实存在的
    私有名字」，判据因此跟着源码走，而不是跟着上一批彩排文件的形态走。
    """
    if "names" in _SRC_CACHE:
        return _SRC_CACHE["names"]
    class_names: set[str] = set()
    func_names: set[str] = set()
    for path in sorted(SRC_DIR.rglob("*.py")):
        try:
            # 产品源码里有几处故意写的非转义字符串（如 `"\d"`），`ast.parse` 会发
            # `SyntaxWarning`；它不影响这一次的读数，但会把每一个彩排用例的警告栏淹掉。
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and item.name.startswith("_") and not item.name.startswith("__"):
                        class_names.add(item.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name.startswith("_") and not node.name.startswith("__"):
                func_names.add(node.name)
    got = (frozenset(class_names), frozenset(func_names))
    _SRC_CACHE["names"] = got
    return got


def private_product_calls(tree: ast.Module, path: Path) -> list[Source]:
    """彩排文件里对产品私有方法的直调（`f._hand_proof()` / `loop._v_...()` …）。"""
    class_private, module_private = _scan_src()
    modules, _symbols = import_aliases(tree)
    out: list[Source] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        attr = func.attr
        if not attr.startswith("_") or attr.startswith("__"):
            continue
        receiver = func.value
        receiver_name = receiver.id if isinstance(receiver, ast.Name) else ""
        hit = attr in class_private
        if not hit and attr in module_private and receiver_name in modules:
            hit = True
        if hit:
            out.append(_source_line(tree, path, node))
    return out


# ============================================================ 七 文档引用扫描


#: 「彩排已走通」的机器口径：表格里一格只有「通」，或这几句原话。
_AFFIRMATIVE_CELL = re.compile(r"\|\s*通\s*(?:\||$)")
_AFFIRMATIVE_PHRASES = ("彩排已走通", "彩排走通", "已走通", "可当真机前置", "真机前置证据")
_NEGATIONS = ("不通", "未通", "没走通", "没通过", "不合格", "不是同一条", "非真机前置",
              "不算", "证明不了", "不能当")

#: 扫哪些文档：仓内 `docs/`、`temp/` 与根目录的 `*.md`（都是「报告 / 文档」的落点）。
DOC_GLOBS = ("docs/**/*.md", "temp/**/*.md", "*.md")


def doc_files() -> list[Path]:
    """全部会被检查引用口径的文档（去重、排序）。"""
    seen: dict[Path, None] = {}
    for pattern in DOC_GLOBS:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_file() and "temp/rc2" not in str(path).replace("\\", "/"):
                seen[path] = None
    return sorted(seen)


def chain_only_citations() -> list[dict[str, str]]:
    """在文档里找「把 CHAIN_ONLY 里的文件说成彩排已走通」的那些行。"""
    out: list[dict[str, str]] = []
    for doc in doc_files():
        try:
            text = doc.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            hit = [name for name in CHAIN_ONLY if name in line]
            if not hit:
                continue
            affirmative = bool(_AFFIRMATIVE_CELL.search(line)) or any(
                phrase in line for phrase in _AFFIRMATIVE_PHRASES)
            if not affirmative:
                continue
            if any(neg in line for neg in _NEGATIONS):
                continue
            out.append({"doc": str(doc.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                        "line": str(lineno), "file": hit[0], "text": line.strip()[:200]})
    return out


# ============================================================ 八 替身构造（唯一入口）


class ScriptedModel:
    """照剧本回答的网关替身（与 `modelgw.ModelGateway.complete` 同接口）。

    它不是缝：没有预算闸、账本、`llm_call` 事件、ambient 解析 —— 那些全在真
    `LlmSeam` 上。:func:`scripted_seam` 把它挂在真 `LlmSeam` 上，三格因此有对象。
    """

    spec = SimpleNamespace(model="scripted", api_key="fake", temperature=0.2,
                           reasoning_effort="")

    def __init__(self, replies: Sequence[str] | Callable[..., str],
                 *, price: tuple[float, float] = (0.0, 0.0)) -> None:
        self.replies = replies
        self.price = price
        self.prompts: list[str] = []
        self.systems: list[str] = []
        self.tool_names: list[tuple[str, ...]] = []

    def complete(self, prompt: str, *, scope: str = "", system: str | None = None,
                 tools: Any = None, **kw: Any) -> Any:
        """回一段预置文本（剧本是列表就按序取、取完停在最后一条；是函数就现算）。"""
        self.prompts.append(str(prompt))
        self.systems.append(str(system or ""))
        self.tool_names.append(tuple(
            str(getattr(t, "name", getattr(t, "get", lambda *_: "")("name")) or "")
            for t in (tools or ())))
        if callable(self.replies):
            text = self.replies(prompt=str(prompt), system=str(system or ""),
                                tools=tools, index=len(self.prompts) - 1)
        else:
            seq = list(self.replies) or ['{"final": "（没有剧本）", "evidence": []}']
            text = seq[min(len(self.prompts) - 1, len(seq) - 1)]
        if not isinstance(text, str):
            text = _json_text(text)
        return SimpleNamespace(ok=True, text=text, tokens_in=8, tokens_out=8,
                               scope=scope, attempts=1, error_kind="", error_detail="",
                               cache_hit_tokens=None, cache_miss_tokens=None,
                               tool_calls=(), reasoning="")


def _json_text(obj: Any) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def scripted_seam(role: str, replies: Sequence[str] | Callable[..., str], store: Any = None,
                  *, root: str | Path | None = None, price: tuple[float, float] = (0.0, 0.0),
                  sid: str | None = None, usd_budget: float | None = None,
                  budget_of: Any = None) -> Any:
    """唯一允许的模型替身构造：真 `LlmSeam` + 真 `TokenMeter` + 预置网关。

    返回的缝上挂着 `.gateway`（剧本网关），于是「问了几次、问的什么」可读；
    `store` 给定时账本行照落（三格③因此有对象，不是零行假绿）。
    """
    from agentflow.llmseam import LlmSeam
    from agentflow.tokenmeter import TokenMeter

    session_root = Path(root) if root is not None else Path(str(getattr(store, "root", "")))
    meter = TokenMeter(store, budget_usd=usd_budget) if store is not None else None
    return LlmSeam(role=role, session_root=session_root, gateway=ScriptedModel(replies, price=price),
                   price=price, sid=sid, usd_budget=usd_budget, meter=meter, budget_of=budget_of)


def scripted_seam_factory(scripts: Mapping[str, Any], *, price: tuple[float, float] = (0.0, 0.0)
                          ) -> Callable[..., Any]:
    """造一个与 `cli._agent_seam_factory` 同签名的工厂（按角色取剧本）。

    用法（彩排文件里唯一允许的替换）::

        monkeypatch.setattr(cli, "_agent_seam_factory",
                            rehearsal_contract.scripted_seam_factory(SCRIPT))
        rc = cli.main(["start", "--mode", "research", ...])
    """
    def factory(role: str, *, root: Path, sid: str | None, usd_budget: float | None,
                store: Any = None) -> Any:
        script = scripts.get(role)
        if script is None:
            script = scripts.get("*") or ['{"final": "（没有剧本）", "evidence": []}']
        return scripted_seam(role, script, store, root=root, price=price,
                             sid=sid, usd_budget=usd_budget, budget_of=None)

    return factory


def iter_rehearsal_trees() -> Iterator[tuple[Path, ast.Module]]:
    """把彩排文件逐个交给调用方（判据用；这里不做任何断言）。"""
    for path in rehearsal_files():
        yield path, parse(path)


# ============================================================ 九 读数（判据 ①/② 的本体）

#: 账本里「模型调用级」那一行的机器标记（`llmseam._charge_ledger` 的 `note` 开头）。
#: 召唤级结算行（`note` 是 `settle-…`）不是一次真调用，判「一行账」时不数它们。
LLM_ROW_PREFIX = "source=llmseam;"

#: 下面几个是「每笔真调用有且只有一行账」与「所有 `llm_call` 落在本趟会话」两条判据的
#: 本体。RC2 把它们写在 `test_rehearsal_cli_proof_main_chain.py` 里；CC3 的四条链也要用
#: 同一份，所以搬到契约文件（本文件仍然不 `assert`：这里只给读数，报红在判据文件里）。
#: 两份实现各写一次「什么叫不对」正是本仓反复踩过的坑（见 RC2 报告 §五）。


def session_calls(ws: Path | str) -> list[dict[str, Any]]:
    """这一趟的每一次 `llm_call` 事件，连同它落在哪个会话文件上。

    为什么把文件名一起带出来：`llm_call` 只落在「缝当时的 `sid`」那个文件里，而账本行
    不带会话号 —— 「这条调用是不是本趟的」只能从文件这一侧读。缺了这一格，「缝没有
    sid ⇒ 落在缺省会话」在读数上与「账本有一行」长得一样（那一笔钱确实记了，只是记在
    了另一份会话的审计面上）。

    逐格：`session`（文件名去掉 `.jsonl`）、`role`、`task_id`、`reason`（`charged` /
    `duplicate` / `no_meter` / …）、`usage_id`（入账时指向 `usage_ledger` 那一行）。
    """
    import json

    out: list[dict[str, Any]] = []
    for path in sorted((Path(ws) / "sessions").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind") != "llm_call":
                continue
            ledger = dict(event.get("ledger") or {})
            out.append({
                "session": path.stem,
                "role": str(event.get("role") or ""),
                "task_id": str(event.get("task_id") or ""),
                "reason": str(ledger.get("reason") or ""),
                "usage_id": str(ledger.get("usage_id") or ""),
            })
    return out


def ledger_identity(ws: Path | str, store: Any) -> dict[str, Any]:
    """「每笔真调用有且只有一行账」的逐笔读数（判据①的本体）。

    三个集合必须一一对上：

    - `calls`：`llm_call` 事件（真缝落的那条审计记录）—— 每一次真调用恰好一条；
    - `rows`：`usage_ledger` 里 `note` 以 :data:`LLM_ROW_PREFIX` 开头的行；
    - `pairs`：事件 → 行的一一映射。配对键同时验两件事：`usage_id` 指到的那一行，
      以及行上的 `(role, task_id, call_index)` 与事件这一侧的
      `(role, task_id, 会话)` 逐字一致。

    `duplicates` 是这条判据的承重点：`duplicate` 的语义是「这次真调用被判成已记过了
    ⇒ 静默不记」。账本行数于是小于真调用次数，而三格（有行、无主 0、悬空 0）仍然全绿
    —— 那正是「另一条路上复发的无主花销」。
    """
    import re

    calls = session_calls(ws)
    rows = [dict(r) for r in store.rows("usage_ledger")
            if str(r.get("note") or "").startswith(LLM_ROW_PREFIX)]
    by_id = {str(r.get("usage_id") or ""): r for r in rows}
    pairs: list[dict[str, Any]] = []
    unpaired: list[dict[str, Any]] = []
    for call in calls:
        if call["reason"] != "charged":
            continue
        row = by_id.get(call["usage_id"])
        if row is None:
            unpaired.append(dict(call, why="charged 但账本里没有这一行"))
            continue
        note = str(row.get("note") or "")
        m = re.search(r"call_index=(\d+)", note)
        pairs.append({
            "session": call["session"], "role": call["role"],
            "task_id": call["task_id"],
            "call_index": int(m.group(1)) if m else -1,
            "usage_id": call["usage_id"],
            "row_role": str(row.get("role") or ""),
            "row_task_id": str(row.get("task_id") or ""),
        })
    claimed = {p["usage_id"] for p in pairs}
    keys = [(p["session"], p["role"], p["task_id"], p["call_index"]) for p in pairs]
    return {
        "calls": len(calls),
        "rows": len(rows),
        "pairs": pairs,
        "duplicates": [c for c in calls if c["reason"] != "charged"],
        "unpaired": unpaired,
        "unclaimed": sorted(set(by_id) - claimed),
        "keys": keys,
        "wrong_owner": [p for p in pairs
                        if p["row_role"] != p["role"] or p["row_task_id"] != p["task_id"]],
    }


def one_row_per_call_problems(reading: Mapping[str, Any]) -> list[str]:
    """判据①：每笔真调用有且只有一行账（返回问题清单；空 = 绿）。纯函数。"""
    problems: list[str] = []
    if int(reading.get("calls") or 0) <= 0:
        problems.append("没有对象：这一趟 0 次真调用（不是干净，是没走那条路）")
    duplicates = list(reading.get("duplicates") or [])
    if duplicates:
        problems.append(
            f"{len(duplicates)} 笔真调用被判 duplicate、静默不记账："
            f"{[(c.get('session'), c.get('role'), c.get('task_id')) for c in duplicates]}")
    calls, rows = int(reading.get("calls") or 0), int(reading.get("rows") or 0)
    if rows != calls:
        problems.append(f"真调用 {calls} 次，账本只落了 {rows} 行")
    if reading.get("unpaired") or reading.get("unclaimed"):
        problems.append(f"事件与账本行没有一一对应：未配对 {reading.get('unpaired')} / "
                        f"未被认领 {reading.get('unclaimed')}")
    if reading.get("wrong_owner"):
        problems.append(f"账本行的归口与事件不一致：{reading.get('wrong_owner')}")
    keys = list(reading.get("keys") or [])
    if len(set(keys)) != len(keys):
        problems.append(f"同一 `(sid, role, task, 序号)` 上出现两次真调用：{keys}")
    return problems


def session_split(ws: Path | str, sid: str) -> dict[str, Any]:
    """`llm_call` 事件按会话文件分组，并点名「不在本趟 `sid` 上」的那些。

    为什么它是独立的一条判据：三格按 ambient task 归口（账本 `task_id`），不按会话
    文件归口 ⇒ 一条没有 `sid` 的缝照样能把账记对、把三格判绿，而它的 `llm_call` 事件
    全落在缺省会话（`sessions/<当天日期>.jsonl`）上。那一份会话是「这一趟的审计面」吗？
    不是。
    """
    calls = session_calls(ws)
    by_session: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_session.setdefault(call["session"], []).append(call)
    elsewhere = [c for c in calls if c["session"] != sid]
    return {"sid": str(sid), "calls": calls, "by_session": by_session,
            "elsewhere": elsewhere,
            "in_run": [c for c in calls if c["session"] == sid]}


def session_problems(split: Mapping[str, Any]) -> list[str]:
    """判据②：全部 `llm_call` 落在本趟 `sid`（返回问题清单；空 = 绿）。纯函数。"""
    problems: list[str] = []
    if not split.get("calls"):
        problems.append("没有对象：这一趟 0 条 `llm_call` 事件（不是干净，是没走那条路）")
    elsewhere = list(split.get("elsewhere") or [])
    if elsewhere:
        problems.append(
            f"{len(elsewhere)} 条 `llm_call` 落在本趟 `sid={split.get('sid')}` 之外："
            f"{[(c.get('session'), c.get('role'), c.get('task_id')) for c in elsewhere]}")
    return problems
