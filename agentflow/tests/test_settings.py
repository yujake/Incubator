# -*- coding: utf-8 -*-
"""机器级设置文件与它的安全阀：判据本体（`agentflow/settings.py`，2026-10-07）。

## 这一组守四件事

1. 「落点与错误」：默认落点是 `agentflow/settings.json`；文件不存在是"全用默认值"
   的正常形态（空 dict），不是错误；而解析失败要报真正的那一个错误 ——
   JSON 语法错（带行列号）与"合法 JSON 但不是对象"是两种错，不许折成一句"格式不对"
   （`cli.load_config` 踩过的坑：YAML 缩进错误被报成 JSON 的错，排查方向全歪）。
2. 「三条优先级的正控与负控」：环境变量 > 设置文件 > 内置默认。
   每一条都成对写：正控证明"上一档真的赢"，负控证明"去掉那一档之后确实落到下一档"
   —— 只写正控的话，一个"永远返回环境变量"的实现也能通过。
3. 「死地址判据」：源码与工具链文档里不许再出现那台机器的绝对路径
   （形如 `D:\\...\\temp\\lean470\\...` / `D:\\...\\_env\\lean...`，以及
   `_env/lean470` 这种工作区根相对写法）。判据是文本级 + AST 级的并集：
   文本级接注释，AST 级接字符串常量与 docstring。配负控：把一句这样的路径
   塞进一个文件 ⇒ 必红。
4. 「安全阀」：`settings.json` 不在 `git ls-files` 里且被 ignore（配"被 `git add -f`
   强行入库就必红"的负控）；示例文件里 `api_key` 是空串；`settings.py`/`modelgw.py`
   里任何打印/日志都不回显 key（配"把 key 打进日志 ⇒ 必红"的负控）。

## 判据的扫描面（为什么不是"全仓每一个字节"）

第 3 条里"不许出现"的面是源码加工具链文档：`agentflow/src`、
`agentflow/tools`、`agentflow/scripts` 与所有者点名的那两份文档
（`docs/FORMAL-TOOLCHAIN.md`、`DEVELOPMENT.md`）。
`docs/` 下三份历史登记/归档（一次真机运行的证据块、一份暂停公告、一份问题登记册）
里仍留着那些路径 —— 它们是"当时这台机器的读数"的逐字记录，
改写它们等于改历史证据。这一残渣不是"看不见"：`_RESIDUE_REGISTER` 把
（文件, 次数）逐条钉住，任何新增都会红。
（`draft/` 与 `temp/` 下原本也逐条钉着十来份；2026-10 业主裁定把它们移出索引
⇒ 这一面按 `git ls-files` 取、取不到它们，登记随之减掉 —— 理由与留档见
`_RESIDUE_REGISTER` 上方那段注释。判据强度没变：扫描面一个字没动。）
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from agentflow import formalgw as FG
from agentflow import modelgw as MG
from agentflow import projects as P
from agentflow import settings as SET
from agentflow import toolchain as TC

PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parent

#: 第 3 条判据的扫描面：源码三个目录（`src` / `tools` / `scripts`）的「工作树」文件，
#: 加上所有者点名的两份文档。为什么是工作树而不是索引：新写的文件在提交之前
#: 也该被判据看见（它恰恰是最可能顺手带上一句绝对路径的地方）。
ZERO_HIT_FILES = ("agentflow/docs/FORMAL-TOOLCHAIN.md", "agentflow/DEVELOPMENT.md")

#: 判据文件自己（仓库根相对）。它必须写出那种路径才能当负控夹具，
#: 所以它被明确排除在残渣统计之外 —— 排除是有意的、写在明面上的，
#: 且由 `test_the_criterion_file_still_needs_its_fixtures` 守着"这一条还有用"。
_CRITERION_FILE = "agentflow/tests/test_settings.py"

#: 那台机器的环境地址的形状：`<盘>:\...\{temp|_env}\{lean470|mathlib-pinned*|elantool}`，
#: 加上工作区根相对的那种写法（`_env/lean470`）。
#:
#: 分隔符写成 `[\\/]+`（一个或多个）而不是一个：Python 源码里的 docstring 与字符串
#: 把路径写成 `D:\\Incubator\\temp\\...`，而判据扫的是「文件文本」 ——
#: 那一串双反斜杠是最常见的形态，只认单个反斜杠会把最该抓的那一类漏掉
#: （第一版就是这样：`\\temp\\lean470` 一个都扫不出来）。
#:
#: 刻意不匹配 `_env/lean470/...`（没有盘符、前面也不是 `temp`）：那种写法正是
#: 文档里该有的"工作区根相对落点"，它不指向任何一台具体机器。
#:
#: ## 为什么分隔符要用「原子组」（`(?>...)`）—— 这是一次真事故留下的形态
#:
#: 改前这里写的是 `(?:[^\\/\s`"'<>|]*[\\/]+)*?`：一个"可以匹配空"的内层量词套在
#: 一个 `*?` 里。这在连续多个反斜杠的文本上是指数级回溯 —— 2026-10-07 实测：
#: 判据在 `temp/g5-mp3.txt`（5,161 字符、576 个反斜杠，内容是
#: `\\\\Local\\\\\\\\Temp\\\\\\\\…` 这种多反斜杠路径）上单条判据跑 >45 s 不返回，
#: 而它在子代理那份干净工作树里只要 10 s（那棵树里同样有这个文件 —— 差别只在
#: 文件是不是真的被扫到）。形态是"判据把整条全量门钉死"，不是"慢一点"。
#:
#: 修法：把分隔符串做成原子组（吃进去就不回吐），并把段数上限写成 `{0,10}`。
#: 正则引擎于是只有"有界"的回溯：每个起点最多十来步。守卫是
#: `test_the_machine_path_scanner_survives_a_backslash_storm`（它同时钉住
#: "变快了"与"还认得出来"两件事 —— 只钉速度的话，把正则改废也能变快）。
_MACHINE_ENV_PATH = re.compile(
    r"[A-Za-z]:(?>[\\/]+)(?:[^\\/\s`\"'<>|]+(?>[\\/]+)){0,10}?"
    r"(?:_env|temp)(?>[\\/]+)(?:lean470|mathlib-pinned\d*|elantool)"
    r"|(?<![A-Za-z0-9_])temp(?>[\\/]+)(?:lean470|mathlib-pinned\d*|elantool)",
    re.I)

#: 允许留在历史登记/归档里的那一份残渣：(仓库根相对路径, 命中次数)。
#: 逐条钉住的理由见模块 docstring —— 它们是"当时那台机器的读数"的逐字记录。
#: 这一张表的作用是「只许减不许增」：任何新增（包括文档里随手再写一句绝对路径）都会红。
#:
#: 2026-10 缩表（业主裁定的直接后果，不是判据放宽）：这一面按 `git ls-files` 取
#: （只认入库的文档），而 `draft/`、`temp/`、`test/` 已从索引移除并写进 `.gitignore`
#: （**不许恢复跟踪**）—— 于是登记表里那两类落位**不再可能命中**。
#: 一条永不生效的登记与一张永不生效的豁免是同一种腐烂（R004 的 `R004_ALLOWED_SITES`
#: 就是这样退场的），所以它们随裁定一起从表里减掉。为什么这不是"放过它们"：
#: 扫描面一个字没动（`_scan_set` / `_tracked_files` 都是现算的），
#: 这一面能看见的仍然只是"入库的东西"；"看不见"与"没问题"的分界由
#: `test_the_scanned_set_is_scanned_at_all` 与模块 docstring 各自承担。
#:
#: 减掉的 16 条（原样留档，免得下一个人以为它们被静默放过）：
#:   · `agentflow/docs/INDEX.md`（1）：2026-10 重写成权威地图，里面的逐字路径
#:     改成了"命令 + 观测时刻"口径 ⇒ 命中归零（文件还在，只是不再命中）；
#:   · `draft/` 下 11 份（22/23/24/25/26/27/28/31/35/37/38）：移出索引 ⇒ 这一面取不到；
#:   · `temp/` 下 4 份（`B8a-evidence.md` / `auditE-lean-probe.json` / `run_gates.py` /
#:     `w5_p1_probe.py`）：同上。
#: 保留下来的三条都仍被跟踪，且命中处是"历史证据 / 实验输入"（理由见模块 docstring）。
_RESIDUE_REGISTER: dict[str, int] = {
    "agentflow/docs/NOAI-SUSPENSION-2026-09-25.md": 1,
    "agentflow/docs/PROPOSALS.md": 3,
    "agentflow/docs/USER-TEST-TASK-QUOTE-FORMAL.txt": 1,
}


# --------------------------------------------------------------------------- #
# 判据的公共部分（正控与负控共用同一段逻辑 —— 分别写两份就等于没在判同一件事）
# --------------------------------------------------------------------------- #


def _dead_env_path_hits(text: str) -> list[str]:
    """一段文本里那台机器环境地址的命中（去重、保序）。"""
    return list(dict.fromkeys(m.group(0) for m in _MACHINE_ENV_PATH.finditer(text)))


def _hits_in_python(source: str) -> dict[str, list[str]]:
    """一份 Python 源码的命中，分两档：`text`（连注释一起扫）与 `ast`（字符串常量/docstring）。

    为什么两档都要（缺一档就有盲区）：注释只出现在源码文本里（AST 里没有注释），
    而 docstring 与普通字符串常量在 AST 里是 `ast.Constant`，比正则扫文本更贴
    "这是给人读的一句话，不是一段被拼出来的路径"。两档取并集，
    报出来的位置也更准（AST 能给出行号）。
    """
    out: dict[str, list[str]] = {}
    text_hits = _dead_env_path_hits(source)
    if text_hits:
        out["text"] = text_hits
    tree = ast.parse(source)
    ast_hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for hit in _dead_env_path_hits(node.value):
                ast_hits.append(f"第 {node.lineno} 行：{hit}")
    if ast_hits:
        out["ast"] = list(dict.fromkeys(ast_hits))
    return out


def _scan_files(paths: list[Path]) -> dict[str, list[str]]:
    """一批文件 → `{相对路径: 命中}`（只留非空的）。

    路径的显示名：能相对仓库根就相对（可读），不能（判据自造的临时文件）就用绝对路径。
    """
    found: dict[str, list[str]] = {}
    for p in paths:
        try:
            rel = p.resolve().relative_to(REPO.resolve()).as_posix()
        except ValueError:
            rel = p.as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        if p.suffix == ".py":
            hits = [f"{k}: {v}" for k, v in _hits_in_python(text).items()]
        else:
            hits = _dead_env_path_hits(text)
        if hits:
            found[rel] = hits
    return found


def _tracked_files() -> list[str]:
    """仓库里被跟踪的文件（仓库根相对、正斜杠）。读不到 git ⇒ 空列表（调用方判它）。"""
    proc = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"],
                          capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        return []
    return [one for one in proc.stdout.split("\0") if one]


def _text_files(root: Path) -> list[Path]:
    """一个目录下的文本文件（按后缀过滤；跳过 `.git` 与字节码）。"""
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if p.suffix in (".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".cfg",
                        ".ini", ".ps1", ".sh", ".lean"):
            out.append(p)
    return out


def _scan_set() -> list[Path]:
    """第 3 条判据扫哪些文件：源码三个目录（「工作树上的」，连未跟踪的新文件一起）
    加所有者点名的两份文档。

    为什么按工作树而不是按 `git ls-files`：判据要在「提交之前」就有牙
    （新写的文件还没入库，按索引扫会漏掉它们 —— 而新写的文件恰恰是最可能
    顺手带上一句绝对路径的地方）。按索引扫那一份留给下面的残渣登记表。
    """
    out: list[Path] = []
    for sub in ("src", "tools", "scripts"):
        base = PROJECT / sub
        if base.is_dir():
            out.extend(_text_files(base))
    for rel in ZERO_HIT_FILES:
        p = REPO / rel
        if p.is_file():
            out.append(p)
    return sorted(set(out))


def _residue_hits() -> dict[str, int]:
    """扫描面之外（`draft/**` 与其余文档）还留着多少条命中：`{相对路径: 次数}`。

    这一面按 `git ls-files` 取（只认入库的文档）：历史登记/归档是入库的东西，
    而工作树上的临时物（`temp/`、`out/`）不在"文档"的范围里。

    本文件自己排除在外（`_CRITERION_FILE`）—— 有意的、写在明面上的排除，
    不是漏掉：判据要能证明"注入一句这样的路径必红"，就得先写出那样一句。
    它的另一半在下面 `test_the_criterion_file_still_needs_its_fixtures` 里：
    排除一旦不再需要（夹具没了）就会被判红，免得它腐烂成"一张永不生效的豁免"。
    """
    scanned = {p.resolve() for p in _scan_set()}
    out: dict[str, int] = {}
    for rel in _tracked_files():
        if rel == _CRITERION_FILE:
            continue
        p = REPO / rel
        if not p.is_file() or p.resolve() in scanned:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue          # 二进制/读不了的文件不是"没有命中"，但它也不是源码或文档
        n = len(_dead_env_path_hits(text))
        if n:
            out[rel] = n
    return out


def _key_echo_problems(source: str, name: str) -> list[str]:
    """一份模块源码里"把 key 打出去"的地方（打印/日志/写流）。

    判据是 AST：任一 `print` / `logging.*` / `*.write` 调用的实参（含子表达式）里
    出现 `api_key` 这个名字（或 `ENV_KEY` 指向的那个常量名）就报一条。
    为什么按"打印/日志"这一面而不管别处：key 落到「文件」上另有第 4 条的
    `settings.json` 忽略规则管，而"回显"这件事唯一会发生的形态就是往台面/日志里写。

    例外只有一类，且是结构判据：那处 key 被包在 `bool(...)` / `len(...)` 里，
    或参与了一次比较（`spec.api_key == ""`、`is not None`）—— 那是"配没配"这个
    布尔位，不是 key 本体。`toolchain_report` 的 `key_present` 正是这种形态，
    把它算成回显会让真判据被一个假阳性长期点亮（然后被忽略）。
    """
    tree = ast.parse(source)
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        fn_name = ""
        if isinstance(fn, ast.Name):
            fn_name = fn.id
        elif isinstance(fn, ast.Attribute):
            fn_name = fn.attr
        if fn_name not in ("print", "write", "debug", "info", "warning", "error", "log"):
            continue
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if _mentions_the_key(arg):
                problems.append(f"{name}:{node.lineno}: {fn_name}(...) 里出现了 key")
    return problems


def _mentions_the_key(node: ast.AST) -> bool:
    """这个表达式里有没有"key 本体"（`api_key` / `ENV_KEY`）。

    排除两类"配没配"的判位：`bool(x.api_key)` / `len(x.api_key)`（真值测试），
    以及任何比较表达式（`x.api_key == ""`、`is not None`）。
    排除是「剪枝」（命中这两类就整棵子树不再往下走）：只 `continue` 的话，
    `bool(spec.api_key)` 里的那个 `spec.api_key` 仍会被 `ast.walk` 走到而误报。
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in ("bool", "len"):
        return False
    if isinstance(node, ast.Compare):
        return False
    if isinstance(node, ast.Name) and node.id in ("api_key", "ENV_KEY"):
        return True
    if isinstance(node, ast.Attribute) and node.attr == "api_key":
        return True
    return any(_mentions_the_key(child) for child in ast.iter_child_nodes(node))


def _settings_tracked_problems(tracked: list[str]) -> list[str]:
    """`settings.json` 出现在"被跟踪文件"里就是问题（它必须永远不在里面）。

    做成一个函数是因为「负控要对着同一段逻辑跑」（在临时仓库里 `git add -f`
    之后，同一段逻辑必须报出问题）—— 两份实现的话，负控证明的是另一件事。
    """
    return [name for name in tracked
            if name == "agentflow/settings.json" or name.endswith("/agentflow/settings.json")]


# --------------------------------------------------------------------------- #
# 一、落点、缺失与解析失败
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例都从一个"确定没有设置文件、也没配环境变量"的状态开始。

    没有这一层，判据会随本机是否恰好写了 `settings.json` 而红或绿 ——
    那正是"环境事实渗进判据"的形态。
    """
    for var in (TC.ENV_LEAN_BIN, TC.ENV_COQ_BIN, TC.ENV_ISABELLE_BIN, TC.ENV_PROVER_PATH,
                FG.ENV_MATHLIB_ROOT, "LEAN_PATH",
                MG.ENV_KEY, MG.ENV_BASE, MG.ENV_NAME):
        monkeypatch.delenv(var, raising=False)
    absent = PROJECT / "_no_settings_for_this_test.json"
    assert not absent.exists(), f"这个文件是判据的占位物，不该存在：{absent}"
    monkeypatch.setenv(SET.ENV_SETTINGS, str(absent))


def test_the_default_landing_spot_is_the_project_settings_json(monkeypatch) -> None:
    """落点：默认是 `agentflow/settings.json`（工程根 = `src/` 的上一级）。"""
    monkeypatch.delenv(SET.ENV_SETTINGS)
    assert SET.settings_path() == PROJECT / "settings.json", SET.settings_path()
    assert SET.PROJECT_ROOT == PROJECT
    # 负控：给了 AGENTFLOW_SETTINGS 就不再是默认落点（否则"指到别处"没有意义）。
    monkeypatch.setenv(SET.ENV_SETTINGS, "X:/elsewhere/settings.json")
    assert SET.settings_path() == Path("X:/elsewhere/settings.json")


def test_an_injected_env_does_not_probe_the_default_path() -> None:
    """注入环境（`env=`）且没给 `AGENTFLOW_SETTINGS` ⇒ 本次不读文件（返回 None）。

    判据要能在确定的环境里跑：本机的 `settings.json` 不许渗进注入环境。
    """
    assert SET.settings_path(env={}) is None
    assert SET.load_settings(env={}) == {}
    assert SET.settings_path(env={SET.ENV_SETTINGS: "Y:/x.json"}) == Path("Y:/x.json")


def test_a_missing_file_is_an_empty_dict_not_an_error(tmp_path: Path) -> None:
    """正控：文件不存在 ⇒ 空 dict；负控：同一路径写上一个真文件 ⇒ 读到它的内容。

    成对写的理由：只断言"不存在时是空 dict"的话，一个永远返回 `{}` 的实现也能过。
    """
    p = tmp_path / "settings.json"
    assert SET.load_settings(p) == {}
    assert SET.toolchain_settings(p)["lean_bin"] == ""
    p.write_text(json.dumps({"toolchain": {"lean_bin": "X:/lean/bin"}}), encoding="utf-8")
    assert SET.load_settings(p) == {"toolchain": {"lean_bin": "X:/lean/bin"}}
    assert SET.toolchain_settings(p)["lean_bin"] == "X:/lean/bin"


def test_a_syntax_error_is_reported_as_a_syntax_error(tmp_path: Path) -> None:
    """语法错 ⇒ `json.JSONDecodeError`（带行列号，消息里有文件路径），不是"格式不对"。

    负控：同一份文件形状合法但不是对象（数组）⇒ 抛 `ValueError`，
    且「两种错是两种类型」（折叠成一句话就会把排查方向带偏）。
    """
    bad = tmp_path / "bad.json"
    bad.write_text('{"toolchain": {"lean_bin": "X:/x",}}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError) as ei:
        SET.load_settings(bad)
    assert str(bad) in str(ei.value), ei.value
    assert ei.value.lineno >= 1 and ei.value.colno >= 1, ei.value

    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2, 3]\n", encoding="utf-8")
    with pytest.raises(ValueError) as ei2:
        SET.load_settings(arr)
    assert "JSON 对象" in str(ei2.value) and "list" in str(ei2.value), ei2.value
    assert not isinstance(ei2.value, json.JSONDecodeError), "形状错与语法错不许折成同一类"


def test_unknown_and_non_string_values_count_as_unset(tmp_path: Path) -> None:
    """键集合固定：没写的键与"值不是字符串"的键都算未设置（都是空串）。

    为什么非字符串算未设置而不是 `str(value)`：把一个 `123` 悄悄当路径用，
    比"当作没配"更难查 —— 报出来的会是一句"路径不存在"。
    """
    p = tmp_path / "settings.json"
    p.write_text(json.dumps({
        "toolchain": {"lean_bin": 123, "coq_bin": "  X:/coqc  ", "typo_key": "X:/nope"},
        "model": {"name": None},
    }), encoding="utf-8")
    ts = SET.toolchain_settings(p)
    assert set(ts) == set(SET.TOOLCHAIN_KEYS), ts
    assert ts["lean_bin"] == "" and ts["coq_bin"] == "X:/coqc"
    assert "typo_key" not in ts, "未登记的键不许渗进返回值"
    ms = SET.model_settings(p)
    assert set(ms) == set(SET.MODEL_KEYS) and ms["name"] == ""


# --------------------------------------------------------------------------- #
# 二、三条优先级的正控与负控（环境变量 > 设置文件 > 内置默认）
# --------------------------------------------------------------------------- #


def _write(tmp_path: Path, name: str, body: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def test_env_beats_the_settings_file_and_the_file_is_really_beaten(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 负控（第一档压第二档）：两档各指一个真实存在的文件，环境变量赢。

    负控那半句是这条判据的关键：去掉环境变量之后，来源必须「变成设置文件那一档」
    且路径变成设置文件里那个（不是空、也不是默认）—— 否则"环境变量赢"可能只是
    因为设置文件根本没被读。两个桩各自建在真目录里，就是为了让"哪一档赢"
    由 `source` 与 `path` 两件事同时说话。
    """
    env_exe = tmp_path / "from-env" / "lean.exe"
    env_exe.parent.mkdir(parents=True)
    env_exe.write_text("", encoding="utf-8")
    set_exe = tmp_path / "from-settings" / "lean.exe"
    set_exe.parent.mkdir(parents=True)
    set_exe.write_text("", encoding="utf-8")
    stub = _write(tmp_path, "s.json", {"toolchain": {"lean_bin": str(set_exe)}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    monkeypatch.setenv(TC.ENV_LEAN_BIN, str(env_exe))
    got = TC.resolve_checker("lean")
    assert (got["source"], got["path"]) == ("explicit", str(env_exe)), got
    assert got["looked"].startswith(TC.ENV_LEAN_BIN), got
    monkeypatch.delenv(TC.ENV_LEAN_BIN)
    beaten = TC.resolve_checker("lean")
    assert (beaten["source"], beaten["path"]) == ("settings", str(set_exe)), beaten


def test_the_settings_file_beats_the_builtin_default(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 负控（第二档压第三档）：模型三键在设置文件里时按它读，删掉就回默认。

    用模型那一轴做这条（它的"内置默认"是一个可逐字比对的常量）。
    """
    stub = _write(tmp_path, "s.json", {"model": {
        "api_key": "key-from-settings", "base_url": "https://example.invalid/v1/",
        "name": "from-settings"}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    spec = MG.spec_from_env()
    assert spec.api_key == "key-from-settings"
    assert spec.base_url == "https://example.invalid/v1", "末尾斜杠要归一（否则拼出双斜杠）"
    assert spec.model == "from-settings"

    # 负控：把文件挪走 ⇒ 三键全部回内置默认（key 为空、端点与模型名是常量）。
    monkeypatch.setenv(SET.ENV_SETTINGS, str(tmp_path / "gone.json"))
    empty = MG.spec_from_env()
    assert empty.api_key == "" and empty.configured is False
    assert empty.base_url == MG.DEFAULT_BASE_URL and empty.model == MG.DEFAULT_MODEL


def test_env_beats_the_settings_file_for_the_model_key(tmp_path: Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 负控（模型那一轴的第一档）：环境变量里的 key 压过设置文件里的 key。"""
    stub = _write(tmp_path, "s.json", {"model": {"api_key": "key-from-settings"}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    monkeypatch.setenv(MG.ENV_KEY, " key-from-env ")
    assert MG.spec_from_env().api_key == "key-from-env", "环境变量必须压过设置文件"
    monkeypatch.delenv(MG.ENV_KEY)
    assert MG.spec_from_env().api_key == "key-from-settings", "去掉环境变量后该轮到文件"


def test_the_written_order_is_env_then_file_then_autodetect(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控 + 负控（第三档＝自动探测，以及三档的「次序」）：

    没有环境变量、没有设置文件时落到 `AGENTFLOW_PROVER_PATH` 那一档；
    一旦设置文件给了目录，返回的来源必须是设置文件那一档（不是 `prover_path`）
    —— 这一条才是"次序"的判据：桩按收到的 `path=` 回不同的路径，
    次序反了就会拿到 `prover_path` 的那个答案。
    """
    def fake_which(_name: str, path: str | None = None) -> str | None:
        """按 `path=` 回一个可辨识的答案（`which` 只被当成"某一档指给我的目录"用）。"""
        return f"./in-{Path(path).name}" if path else None

    monkeypatch.setattr(TC.shutil, "which", fake_which)
    monkeypatch.setenv(SET.ENV_SETTINGS, str(tmp_path / "gone.json"))
    monkeypatch.setenv(TC.ENV_PROVER_PATH, str(tmp_path / "generic"))
    auto = TC.resolve_checker("lean")
    assert auto["source"] == "prover_path", auto
    assert auto["path"].endswith("in-generic"), auto

    settings_dir = tmp_path / "from-settings"
    settings_dir.mkdir()
    stub = _write(tmp_path, "s.json", {"toolchain": {"lean_bin": str(settings_dir)}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    got = TC.resolve_checker("lean")
    assert got["source"] == "settings_dir", got
    assert got["path"].endswith("in-from-settings"), got
    assert "settings" in got["looked"], got["looked"]

    # 负控（第一档压第三档）：环境变量在 ⇒ 走 explicit 那一档，设置文件不再被采用。
    exe_dir = tmp_path / "from-env"
    exe_dir.mkdir()
    monkeypatch.setenv(TC.ENV_LEAN_BIN, str(exe_dir))
    top = TC.resolve_checker("lean")
    assert top["source"] == "explicit_dir" and top["path"].endswith("in-from-env"), top


def test_a_configured_but_missing_setting_is_a_problem_not_an_absence(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """负控（fail-closed）：设置文件里配了一个不存在的路径 ⇒ 记成配置问题，不是"没有"。

    为什么这条必须有牙：把"配置错"读成"环境里没有检查器"，正是 `toolchain` 模块
    docstring 里那个静默降级（形式化悄悄退成 cross_check，报告里只剩"没核到"）。
    """
    stub = _write(tmp_path, "s.json", {"toolchain": {"lean_bin": "X:/definitely/not/here"}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    monkeypatch.setattr(TC.shutil, "which", lambda *_a, **_k: None)
    got = TC.resolve_checker("lean")
    assert got["path"] == "" and got["problem"], got
    assert "不存在" in got["problem"], got
    probe = TC.probe_checkers()
    assert probe["checked"] is False, probe
    assert any("不存在" in one for one in probe["probe_errors"]), probe


def test_mathlib_root_can_come_from_the_settings_file(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """Mathlib 那一轴同一条口径：文件里的 `toolchain.mathlib_root` 认，环境变量压过它。"""
    root = tmp_path / "mathlib4"
    root.mkdir()
    (root / "lakefile.lean").write_text("-- lakefile\n", encoding="utf-8")
    (root / "lean-toolchain").write_text("leanprover/lean4:v4.7.0\n", encoding="utf-8")
    other = tmp_path / "env-mathlib"
    other.mkdir()
    (other / "lakefile.lean").write_text("-- lakefile\n", encoding="utf-8")
    (other / "lean-toolchain").write_text("leanprover/lean4:v4.7.0\n", encoding="utf-8")

    stub = _write(tmp_path, "s.json", {"toolchain": {"mathlib_root": str(root)}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    assert FG.find_mathlib_root() == str(root)
    # 负控：环境变量在 ⇒ 环境变量赢（文件里那个不再被采用）。
    monkeypatch.setenv(FG.ENV_MATHLIB_ROOT, str(other))
    assert FG.find_mathlib_root() == str(other)
    # 负控：文件缺失且没有环境变量 ⇒ 找不到（那一档不生效，不是我行我素地猜一个）。
    monkeypatch.delenv(FG.ENV_MATHLIB_ROOT)
    monkeypatch.setenv(SET.ENV_SETTINGS, str(tmp_path / "gone.json"))
    assert FG.find_mathlib_root() == ""


def test_a_relative_setting_path_is_resolved_against_the_workspace_root() -> None:
    """相对路径相对「工作区根」解析（不相对进程 cwd）—— 否则同一个设置文件两处两种解释。"""
    assert SET.resolve_setting_path("_env/lean470/lean-4.7.0-windows/bin") == \
        SET.WORKSPACE_ROOT / "_env" / "lean470" / "lean-4.7.0-windows" / "bin"
    absolute = Path("X:/somewhere/lean.exe")
    assert SET.resolve_setting_path(str(absolute)) == absolute


# --------------------------------------------------------------------------- #
# 三、死地址判据（那台机器的绝对路径不许再出现在源码与工具链文档里）
# --------------------------------------------------------------------------- #


def test_the_scanner_has_teeth_on_every_form_of_the_dead_path(tmp_path: Path) -> None:
    """负控（判据自己的正控）：四种形态都必须被扫出来。

    这四种是这次改动要扒掉的全部形态：模块 docstring 里的绝对路径、
    注释里的绝对路径、命令块里的绝对路径、工作区根相对的 `temp/...`。
    没有这一条，"扫出来 0 条"可能只是正则根本没接上。
    """
    samples = {
        "docstring": '# -*- coding: utf-8 -*-\n"""装在这台机器上的 '
                     'D:\\\\Incubator\\\\temp\\\\lean470\\\\lean-4.7.0-windows\\\\bin。"""\n',
        "comment": "# 实测：Lean 装在 D:/Incubator/temp/lean470/lean-4.7.0-windows/bin\n",
        "command": 'CMD = "$env:PATH=\\"D:\\\\Incubator\\\\_env\\\\lean470\\\\bin;$env:PATH"'
                   '  # noqa: E501\n',
        "relative": "ROOT = 'temp/mathlib-pinned2/mathlib4-4.7.0'\n",
    }
    for label, text in samples.items():
        hits = _dead_env_path_hits(text)
        assert hits, f"这一形态没被扫出来：{label}（{text!r}）"
    # 注入到文件上也要红（文本级 + AST 级两档各来一份）
    py = tmp_path / "injected.py"
    py.write_text("LEAN = r\"D:\\\\Incubator\\\\temp\\\\lean470\\\\lean-4.7.0-windows\\\\bin\"\n",
                  encoding="utf-8")
    got = _scan_files([py])
    assert got, "把一句这样的路径塞回某个 Python 文件 ⇒ 判据必须红"
    assert any("ast:" in one for one in got[next(iter(got))]), got
    md = tmp_path / "injected.md"
    md.write_text("本机 Lean 在 D:\\Incubator\\_env\\mathlib-pinned2\\mathlib4-4.7.0 里\n",
                  encoding="utf-8")
    assert _scan_files([md]), "把一句这样的路径塞回某个文档 ⇒ 判据必须红"


def test_the_machine_path_scanner_survives_a_backslash_storm() -> None:
    """守卫（2026-10-07 的真事故）：连续多反斜杠不许让这条判据回溯到卡死。

    改前的正则里有一个"能匹配空的内层量词套在外层量词里"（`(?:[^\\/…]*[\\/]+)*?`）。
    形态：在 `temp/g5-mp3.txt`（5,161 字符 / 576 个反斜杠，内容是
    `\\\\Local\\\\\\\\Temp\\\\\\\\…` 这种多反斜杠路径）上，单条判据 >45 s 不返回
    —— 而全量门会跑这条判据，所以那等于"把门钉死"。

    两件事一起钉，缺一条都会被"把正则改废"骗过去：
      ① 一串多反斜杠必须在有界时间内扫完（上限写得很宽松：这不是性能基准，
         它要抓的是"指数级"这一档，不是"慢 20%"）；
      ② 同一段文本里那句真路径仍然要被抓出来 —— 只钉速度的话，
         "不认了"也能让上面那条变绿。
    """
    storm = ("X:" + "\\" * 8 + "Local" + "\\" * 8 + "Temp" + "\\" * 8) * 300
    text = storm + "\n真路径在这里：D:\\\\Incubator\\\\temp\\\\lean470\\\\bin\n"
    t0 = time.time()
    hits = _dead_env_path_hits(text)
    took = time.time() - t0
    assert took < 2.0, (
        f"扫一串多反斜杠用了 {took:.1f}s ⇒ 正则又在指数回溯了"
        "（分隔符串要用原子组 `(?>[\\\\/]+)`，见 `_MACHINE_ENV_PATH` 的注释）")
    assert any("lean470" in one for one in hits), (
        f"这场反斜杠风暴里那句真路径没被抓出来 ⇒ 正则被改窄了，不只是变快：{hits}")


def test_the_scanned_set_is_scanned_at_all() -> None:
    """反真空：扫描面必须真的扫到了东西（否则"0 条"什么也不证明）。"""
    tracked = _tracked_files()
    assert len(tracked) > 500, f"git ls-files 只给了 {len(tracked)} 个文件 ⇒ 扫描面塌了"
    scan = {p.resolve() for p in _scan_set()}
    assert len(scan) > 100, f"扫描面只有 {len(scan)} 个文件"
    for must in ("src/agentflow/toolchain.py", "src/agentflow/formalgw.py",
                 "src/agentflow/modelgw.py", "src/agentflow/settings.py",
                 "src/agentflow/tools/verify_tools.py", "tools/release_all.py",
                 "scripts/lint_rules.py", "docs/FORMAL-TOOLCHAIN.md", "DEVELOPMENT.md"):
        assert (PROJECT / must).resolve() in scan, f"扫描面里少了 {must}"


def test_no_dead_machine_path_in_the_source_or_the_toolchain_docs() -> None:
    """正控（本件的主判据）：源码与工具链文档里 0 条那台机器的环境地址。"""
    found = _scan_files(_scan_set())
    assert found == {}, (
        "源码或工具链文档里还写着那台机器的环境地址 —— 本机路径该写在 "
        "settings.json 的 toolchain 段里（见 settings.example.json）：\n"
        + "\n".join(f"  {k}: {v}" for k, v in found.items())
    )


def test_the_remaining_occurrences_are_registered_and_cannot_grow() -> None:
    """残渣只许减不许增：扫描面之外的命中必须与登记表逐条一致。

    这一条是"没扫到"与"扫过、结论是不能动"之间的分界：`draft/**` 与几份历史
    归档里那些路径是当时这台机器的读数记录（改写它们等于改历史证据），
    所以它们被逐条登记而不是被静默放过 —— 新增一条就红，
    减掉一条也红（提醒把登记表一起更新）。
    """
    assert _residue_hits() == _RESIDUE_REGISTER, (
        "扫描面之外的命中变了。新增：请把路径改成 settings.json 的口径；"
        "确实是历史记录：请更新本文件的 `_RESIDUE_REGISTER` 并写清理由。\n"
        f"实际：{json.dumps(_residue_hits(), ensure_ascii=False, indent=2)}"
    )


def test_the_criterion_file_still_needs_its_fixtures() -> None:
    """本文件被排除在残渣统计之外，是因为它「必须」写出那种路径当负控夹具。

    这一条守着那个排除还有用：夹具被删掉之后，排除就该一起删
    （一张永不生效的豁免表会腐烂成"看起来还在挡着什么" —— R010 的同一句纪律）。
    """
    src = (REPO / _CRITERION_FILE).read_text(encoding="utf-8")
    hits = _dead_env_path_hits(src)
    assert hits, ("本文件的负控夹具不见了 ⇒ 上面那条排除已经没用了，请把它一起删掉"
                  f"（并把 `_RESIDUE_REGISTER` 里的说明同步）")
    assert len(hits) >= 2, f"夹具只剩一条 {hits} ⇒ 覆盖面可能已经被删窄了"


# --------------------------------------------------------------------------- #
# 四、安全阀：settings.json 不入库、示例没有真 key、key 不回显
# --------------------------------------------------------------------------- #


def test_the_real_settings_json_is_neither_tracked_nor_unignored() -> None:
    """正控：`agentflow/settings.json` 不在 `git ls-files` 里，且被 ignore 规则罩着。"""
    tracked = _tracked_files()
    assert tracked, "读不到 git 的跟踪清单 ⇒ 这条判据没查成（不是「干净」）"
    assert _settings_tracked_problems(tracked) == [], (
        "真正的设置文件进了索引 —— 它里面要填 API key，绝不能入库")
    proc = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q",
                           "agentflow/settings.json"], capture_output=True)
    assert proc.returncode == 0, "settings.json 没有被忽略规则罩住（.gitignore 第 13 节）"
    proc2 = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-v",
                            "agentflow/settings.json"], capture_output=True, text=True)
    assert ".gitignore" in proc2.stdout, proc2.stdout


def test_a_force_added_settings_json_would_be_reported(tmp_path: Path) -> None:
    """负控（安全阀的牙）：在一个一次性仓库里 `git add -f` 它 ⇒ 同一段判据必红。

    为什么用一次性仓库而不是本仓的索引：本仓的索引是「共享状态」，
    判据自己往里写东西是"判据动仓内文件"那一类前科（`R6-AN-1`）。
    这里 `git init` 到 `tmp_path`，忽略规则抄自本仓的真实 `.gitignore`，
    于是"忽略着也能被强推进去"这个形态被真跑了一遍。
    """
    repo = tmp_path / "mini"
    (repo / "agentflow").mkdir(parents=True)
    real_ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "/agentflow/settings.json" in real_ignore, "本仓的忽略规则里没有这一条"
    (repo / ".gitignore").write_text(real_ignore, encoding="utf-8")
    (repo / "agentflow" / "settings.json").write_text(
        json.dumps({"model": {"api_key": "this-is-a-negative-control-key"}}), encoding="utf-8")

    def _git(*args: str) -> str:
        proc = subprocess.run(["git", "-C", str(repo), *args],
                              capture_output=True, text=True, encoding="utf-8")
        return proc.stdout

    _git("init", "-q")
    # 前半：忽略规则生效 ⇒ 普通 `git add -A` 进不去索引（与正控同一段逻辑判"干净"）。
    _git("add", "-A")
    assert _settings_tracked_problems(_tracked_names(repo)) == [], "忽略规则没生效"
    # 后半：`git add -f` 强行入库 ⇒ 同一段逻辑必须报出问题。
    _git("add", "-f", "agentflow/settings.json")
    names = _tracked_names(repo)
    assert _settings_tracked_problems(names), (
        "被 `git add -f` 推进索引之后判据没红 —— 这条安全阀没有牙")


def _tracked_names(repo: Path) -> list[str]:
    """某个仓库的跟踪清单（负控用；与 `_tracked_files` 分开只为把仓库根参数化）。"""
    proc = subprocess.run(["git", "-C", str(repo), "ls-files"],
                          capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return [one for one in proc.stdout.splitlines() if one]


def test_the_example_settings_file_has_no_key_in_it() -> None:
    """正控：示例文件在，`api_key` 是空串；负控：示例里不许出现任何像 key 的东西。"""
    p = PROJECT / "settings.example.json"
    assert p.is_file(), "示例文件不在 ⇒ 用户无从知道该写什么"
    raw = p.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert data["model"]["api_key"] == "", "示例里的 api_key 必须是空串"
    assert data["toolchain"]["lean_bin"] == "", "示例里不许写死任何一台机器的路径"
    assert "sk-" not in raw and "sk-" not in json.dumps(data), "示例里不许有任何真 key"
    # 负控那半句：把 key 塞进一份同样的文件 ⇒ 同一段判据必须红。
    assert _example_problems({**data, "model": {"api_key": "real-looking-key"}}), \
        "示例里出现非空 key 时判据必须红"


def _example_problems(data: dict) -> list[str]:
    """一份"示例设置"的问题清单（正控与负控共用）。"""
    problems: list[str] = []
    model = data.get("model") if isinstance(data.get("model"), dict) else {}
    toolchain = data.get("toolchain") if isinstance(data.get("toolchain"), dict) else {}
    if str(model.get("api_key") or ""):
        problems.append("示例文件里 model.api_key 非空")
    for key, value in toolchain.items():
        if _dead_env_path_hits(str(value)):
            problems.append(f"示例文件里 toolchain.{key} 写着一台机器的环境地址")
    return problems


def test_no_module_echoes_the_api_key() -> None:
    """正控：`settings.py` 与 `modelgw.py` 里没有把 key 打出去的地方；负控见下一条。"""
    for name in ("settings.py", "modelgw.py"):
        src = (PROJECT / "src" / "agentflow" / name).read_text(encoding="utf-8")
        assert _key_echo_problems(src, name) == [], _key_echo_problems(src, name)


def test_printing_the_key_would_be_reported() -> None:
    """负控（回显 key 的牙）：把 key 打进日志/台面 ⇒ 必红。

    这是"照 `ModelSpec.redacted` 的先例"那句话的判据形态：先例本身也要能被判。
    """
    assert _key_echo_problems("print(spec.api_key)\n", "x.py"), "print(key) 没被扫出来"
    assert _key_echo_problems("import logging\n"
                              "logging.info('key=%s', self.spec.api_key)\n", "x.py"), \
        "日志里回显 key 没被扫出来"
    assert _key_echo_problems("sys.stdout.write(ENV_KEY + '=' + key)\n", "x.py"), \
        "把环境变量名与值一起写出去没被扫出来"
    # 反向：只打印"配没配"这一格与脱敏之后的快照，不算回显。
    assert _key_echo_problems("print('key_present:', bool(spec.api_key))\n", "x.py") == [], \
        "只报『配没配』不该被算成回显"
    assert _key_echo_problems("print(spec.redacted())\n", "x.py") == [], \
        "redacted() 就是给日志用的，不该被算成回显"


def test_a_key_from_the_settings_file_never_shows_up_in_the_redacted_snapshot(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """正控（端到端）：从设置文件读到的 key，进 `redacted()` 之后只剩 `***`。"""
    secret = "this-value-must-never-be-printed"
    stub = _write(tmp_path, "s.json", {"model": {"api_key": secret}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    spec = MG.spec_from_env()
    assert spec.api_key == secret
    blob = json.dumps(spec.redacted(), ensure_ascii=False)
    assert secret not in blob and spec.redacted()["api_key"] == "***", blob
    # 负控：不加脱敏地 dump 整份 spec 就能看见它 —— 这就是"必须走 redacted"的理由。
    assert secret in json.dumps({"api_key": spec.api_key}, ensure_ascii=False)


# --------------------------------------------------------------------------- #
# 五、数据面落点（`workspace.projects_dir`）走同一条口径
# --------------------------------------------------------------------------- #


def test_the_projects_dir_default_is_derived_not_written() -> None:
    """正控：`projects/` 的默认落点是算出来的，不是写死的一台机器的路径。

    改前这里是一句字面量（那台机器的绝对路径），换一台机器就是一句假话 ——
    而症状不是报错，是"项目建到了别处"。改后它由本包位置推出的工作区根算出来：
    本机读数与改前逐字相同（这一点由第一条断言钉住：它就是"工作区根 + projects/"）。
    """
    assert P.DEFAULT_PROJECTS_DIR == SET.WORKSPACE_ROOT / "projects", P.DEFAULT_PROJECTS_DIR
    assert P.DEFAULT_PROJECTS_DIR.is_absolute(), P.DEFAULT_PROJECTS_DIR
    # 它在受审树外面（`agentflow/` 之外）—— 这是 projects.py 里那条设计意图，
    # 与"来源写在哪儿"无关，所以改来源不该把它搬进受审树。
    assert SET.PROJECT_ROOT not in P.DEFAULT_PROJECTS_DIR.parents, P.DEFAULT_PROJECTS_DIR


def test_the_projects_dir_follows_explicit_then_env_then_file_then_derived(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """四档顺序（显式 > 环境变量 > 设置文件 > 推导默认），正控与负控成对。"""
    env_dir = tmp_path / "from-env"
    file_dir = tmp_path / "from-file"
    explicit = tmp_path / "explicit"
    stub = _write(tmp_path, "ws.json", {"workspace": {"projects_dir": str(file_dir)}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    monkeypatch.setenv(P.ENV_PROJECTS_DIR, str(env_dir))

    # 正控第一档：显式参数最硬（它在设置文件与环境变量都在时也赢）。
    assert P.projects_dir(str(explicit)) == explicit
    # 正控第二档：环境变量赢过设置文件。
    assert P.projects_dir(None) == env_dir
    # 负控第一档：把环境变量拿掉 ⇒ 落到设置文件（这一档真的被读到了）。
    monkeypatch.delenv(P.ENV_PROJECTS_DIR)
    assert P.projects_dir(None) == file_dir
    # 负控第二档：把设置文件也拿走 ⇒ 落到推导出的默认值，而不是我行我素地猜。
    monkeypatch.setenv(SET.ENV_SETTINGS, str(tmp_path / "gone.json"))
    assert P.projects_dir(None) == P.DEFAULT_PROJECTS_DIR


def test_the_projects_dir_setting_is_strict_about_shapes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """形状纪律：非字符串（数字/列表）当"没配"，不当路径；相对路径相对工作区根。

    与 `settings._section` 的既有口径同一个理由：把一个 `123` 悄悄当路径用，
    比"当作没配"更难查；而相对路径若相对进程 cwd 解析，同一个设置文件
    在 CLI 与判据里会变成两个落点（那是静默的错）。
    """
    stub = _write(tmp_path, "shape.json", {"workspace": {"projects_dir": 123}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub))
    monkeypatch.delenv(P.ENV_PROJECTS_DIR, raising=False)
    assert P.projects_dir(None) == P.DEFAULT_PROJECTS_DIR, "非字符串的值被当成路径用了"

    stub2 = _write(tmp_path, "rel.json", {"workspace": {"projects_dir": "somewhere/projects"}})
    monkeypatch.setenv(SET.ENV_SETTINGS, str(stub2))
    assert P.projects_dir(None) == SET.WORKSPACE_ROOT / "somewhere" / "projects"


# --------------------------------------------------------------------------- #
# 六、密封性：判据必须跑在"这台机器什么都没配"的环境里
# --------------------------------------------------------------------------- #


def test_the_suite_pins_the_lean_switch_on() -> None:
    """守卫（业主 2026-10-12 翻缺省之后）：整趟套件跑在「Lean 形式化开着」那一档。

    两件事必须分开、各自有判据：

      - 产品缺省是关的（「默认设置中 Lean 关闭帮用户在无严苛要求时省钱」）——
        由 `tests/test_lean_switch.py::test_the_product_default_is_lean_off` 钉住；
      - 套件跑的是开着那一档 —— 这一套判据守的是形式化那条路的接线（桥接层、
        E 的动作与受控理由、提示词里的"怎么写"、收工门的承重格、`runflow` 的 Lean 段、
        两份冻结快照），缺省关掉只是"默认不烧那笔钱"，不是"这条路没了"。
        实测：翻缺省那一刻 98 条判据变红，全部落在这一档。

    为什么这条守卫必要：`conftest.py` 那一行是手写的环境钉，它一旦被删/被改，
    那几百条判据会静默跑在"这条路不存在"的档上 —— 它们照样绿（关掉时那些分支
    根本不发生），而"开着时逐字不变"这条性质就没人看着了。
    """
    import os
    assert os.environ.get("AGENTFLOW_LEAN_ENABLED") == "1", (
        "套件没有钉在 Lean 开着那一档（见 tests/conftest.py）⇒ 这一批判据会跑错档")
    assert SET.DEFAULT_LEAN_ENABLED is False, (
        "产品缺省必须是关的；它与「套件跑在开着那一档」是两件事，不许混")


def test_the_suite_pins_the_machine_settings_away() -> None:
    """守卫（2026-10-07 的全量门真事故）：判据不许读到本机那份设置文件。

    事实：设置层落地之后，本机真有 `agentflow/settings.json`（里面有真的 API key 与
    这台机器的 Lean / Mathlib 落点）。而一批判据断言的恰恰是"没配的时候"的分支
    —— `run` 没 key ⇒ 退出码 2 且报 `no_key`、`detect_verifier` 报"没装"、
    "build 期不碰模型" —— 它们在本机那份文件面前全部变红（实测那趟门 12 条红）。
    另外，按老习惯 `export AGENTFLOW_MODEL_API_KEY=...` 之后再跑判据，会得到同样的红。

    所以 `tests/conftest.py` 在导入期把 `AGENTFLOW_SETTINGS` 钉到一个不存在的路径、
    并清掉本机事实类的环境变量。这条守卫钉住"那一手真的生效"，四档缺一档就退化成空转：

      ① 套件级的钉真的在（`conftest.PINNED_SETTINGS_PATH` 非空）；
      ② 本用例生效的那个落点在盘上没有文件 —— 注意本文件自己的 autouse 夹具
         （它会把落点再指到 `PROJECT/_no_settings_for_this_test.json`），
         所以这里断的是"生效落点不存在"，不是"等于 conftest 钉的那一个"；
      ③ 生效落点不是本机那份 `agentflow/settings.json`，且读出来是空的；
      ④ 反向：往生效落点写一份真设置 ⇒ 产品立刻读得到 —— 这一档证明钉的是一个
         "真会被读的落点"，而不是"一个被忽略的字符串"。跑完自己删掉。
    """
    import conftest

    assert conftest.PINNED_SETTINGS_PATH, \
        "conftest 没钉设置路径（是不是设了 AGENTFLOW_NO_SETTINGS_PIN？）"
    effective = SET.settings_path()
    assert effective is not None, "生效落点是 None ⇒ 本次不读文件，这条守卫没落脚点"
    assert not effective.exists(), f"生效落点上居然有文件：{effective}"
    assert effective != PROJECT / "settings.json", "生效落点就是本机那份设置文件 — 没解耦"
    assert SET.load_settings() == {}, "钉住之后仍读到了设置 ⇒ 与本机解耦没生效"
    for name in ("AGENTFLOW_MODEL_API_KEY", "AGENTFLOW_LEAN_BIN",
                 "AGENTFLOW_MATHLIB_ROOT", "AGENTFLOW_PROVER_PATH"):
        assert not os.environ.get(name), f"{name} 还在环境里 ⇒ 判据会随本机 shell 变形"

    p = Path(effective)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('{"model": {"name": "pinned-probe"}}', encoding="utf-8")
    try:
        assert SET.model_settings()["name"] == "pinned-probe", (
            "往生效落点写设置却读不到 ⇒ 这一手是空转（它钉的字符串根本没进产品代码）")
    finally:
        p.unlink()


if __name__ == "__main__":  # pragma: no cover - 手动跑这一组时的入口
    raise SystemExit(pytest.main([__file__, "-q"]))
