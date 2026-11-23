"""`check_doc_numbers` —— 全仓“文档里写死的数字 vs 现算”的一站式自检。

## 为什么需要它

并行施工时，同一批读数散在四五份文档里，每份由不同的判据各自盯着：`LIVE-READINGS`
的块、§2 第八层的散文、`READING-MAP.md` 开头那句与 §3 的行数表、`INDEX.md` 的
`MIN_DOCS`、`scripts/README.md` 的工具面。判据红的时候只能一条一条去读失败信息，
没有任何一处能回答“今天到底哪几项过期了”。

本脚本就是那一处：逐项现算（不复用文档里的值），把“项目 / 文档值 / 现算值 /
判定”打成一张表，并用三态退出码收口。

## 用法（在 `agentflow/` 下）

```
python scripts/check_doc_numbers.py                 # 只报：0 全一致 / 1 有过期 / 2 没查成
python scripts/check_doc_numbers.py --json          # 机器读数（items 逐项 + counts）
python scripts/check_doc_numbers.py --write         # 把过期项按现算值写回（先备份）
python scripts/check_doc_numbers.py --docs <副本>   # 对文档副本查/写，测量仍用 --root
python scripts/check_doc_numbers.py --selftest      # 造假文档验三态
```

退出码（三态，与 `scripts/README.md` 的共同约定同一条）：

- `0` = 查过了、全一致；
- `1` = 查过了、有过期项；
- `2` = 没查成（文档缺 / 目录缺 / 某项量不出来）。`2` 压过 `1`：只要有一项没量到，
  这一趟就不是完整结论 —— “没查到”不等于“一致”。

## 覆盖面（每一类都从盘上现算）

1. `docs/DEVELOPMENT-SPEC.md` 的 `LIVE-READINGS` 块：32 个键逐键现算
   （linter 两档走 `scripts/lint_rules.py --json-out`；`cli tools` 走子进程；
   `schema.TABLES` / `webui` 面走 import；用例数走 `pytest --collect-only`）。
2. 同文件 §2 第八层的散文：模块 / 端点 / GET / POST / 判据文件数 / 五数复跑行。
3. 静态产物三格：从 `web/static/index.html` 现读它点名的 JS / CSS，名字与字节数都比。
4. `docs/READING-MAP.md` 开头那句：文件数 / 总行数 / `>800` 文件数 / `agent_loop.py` 行数。
5. 同文件里所有 `| `模块` | 行数 |` 行（§3 与 §2 分层表都算；判据扫全文件，不只那六行）。
6. `docs/INDEX.md` 的 `MIN_DOCS`：现算值取判据文件里的常量；`tests/` 不在时退回盘上份数。
7. `scripts/README.md` 的工具面：文档点名的脚本集合 vs `scripts/*.py` 现盘集合。
8. `docs/DEVELOPMENT-SPEC.md` 里其余 `.noai-paths` 计数与 `test_noai_gate.py` 用例数
   （与第 1 类同源、分处散文/表格；同一批数在多处落位时，本脚本逐处点名）。
9. `docs/DEVELOPMENT-SPEC.md` 全文的 linter 读数三元组（`error A / warning B / info C`）：
   逐行扫，每处三元组的 `warning` / `info` 两栏各成一项。口径与权威判据
   `tests/test_release_all.py::tally_claim_problems()` 逐字对齐 —— 同一张历史记号豁免表
   （`HISTORICAL_MARKERS`）、同一条正则、同样刻意不比 `error` 栏（那一栏由发布门按
   “必须为 0” 强制，并行施工期最先变）。这一类就是 `P0` 的补丁：只扫 `LIVE-READINGS`
   块时，块外的散文三元组（`docs/DEVELOPMENT-SPEC.md:69` 那种）永远不参与对账，
   于是块绿、全文仍有过期读数。
10. 清单计数在四份「当前值」文档里的全部形态：`docs/DEVELOPMENT-SPEC.md`、根 `README.md`、
    `docs/INDEX.md`、`docs/SYSTEM-INTRO.md`。三类形态 —— 带单位（`63 条条目` /
   `60 条唯一路径` / `63 条 glob` / `7 个分组`）、加粗 + 单位（`**63** 条 glob` /
   `**63** 条条目`）、无「条」字变体（`46 条目 / 43 唯一路径 / 7 分组`）。
   第三类是实测漏口（2026-11-23 DOC-COUNT-48）：带单位的六条正则一条都接不住
   `46 条目`，于是 `docs/SYSTEM-INTRO.md:804` 写着旧值也没有任何判据会红；而
   `docs/INDEX.md:45/155` 的两处旧值不在 `tests/test_release_all.py` 的扫描面内
   （那条判据只读 `DEVELOPMENT-SPEC.md` 与 `README.md`）。引文里的数不参与对账：
   成对 ASCII 双引号包住的是归档件原话（如 INDEX 里 `"46 条唯一路径"`），改它就是
   伪造历史；同一行紧跟的当次值仍逐处核。

## 刻意不做什么

- 不重写任何判据：量法与 `tests/test_release_all.py` / `tests/test_reading_map_counts.py`
  同源，但各自独立实现 —— 判据红时本脚本是“第二双眼睛”，不是它的第二份实现。
- 不把“读不到”折成“一致”：文档锚点缺、目录缺、子进程失败，一律记文档缺项并退 2。
- `--write` 只改过期项，且只改本脚本认得的落位；锚点读不到（`文档缺项`）不猜着改。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

PROG = "check_doc_numbers"

EXIT_OK = 0
EXIT_STALE = 1
EXIT_UNKNOWN = 2

SPEC_REL = "docs/DEVELOPMENT-SPEC.md"
MAP_REL = "docs/READING-MAP.md"
INDEX_REL = "docs/INDEX.md"
SYSTEM_INTRO_REL = "docs/SYSTEM-INTRO.md"
SCRIPTS_README_REL = "scripts/README.md"
#: git 根 README（文档根再上一级）：`--root` 缺省是 `agentflow/`，而 `README.md` 在仓库根。
ROOT_README_REL = "../README.md"

#: `LIVE-READINGS` 块里本脚本认识的键（顺序照文档；缺一个或多个都算文档缺项）。
LIVE_KEYS: tuple[str, ...] = (
    "lint_rules_rules", "lint_rules_warning", "lint_rules_info",
    "lint_rules_strict_warning", "lint_rules_strict_info",
    "noai_paths_glob", "noai_paths_unique", "noai_paths_categories",
    "tools_star_tools_py", "schema_tables", "noai_gate_pytest_collected",
    "cli_tools_total", "cli_tools_modules",
    "cli_tools_role_a", "cli_tools_role_b", "cli_tools_role_c", "cli_tools_role_d",
    "cli_tools_role_e", "cli_tools_role_f", "cli_tools_role_g", "cli_tools_role_h",
    "cli_tools_role_l", "cli_tools_role_m", "cli_tools_role_v",
    "webui_modules", "webui_routes", "webui_routes_get", "webui_routes_post",
    "webui_routes_reader", "webui_routes_writer", "webui_event_kinds",
    "webui_test_files",
)

#: 人读标签（表里的“项目”一栏用；缺省回落到键名）。
LABELS: dict[str, str] = {
    "lint_rules_rules": "linter 规则条数",
    "lint_rules_warning": "linter 日常档 warning",
    "lint_rules_info": "linter 日常档 info",
    "lint_rules_strict_warning": "linter 严格档 warning",
    "lint_rules_strict_info": "linter 严格档 info",
    "noai_paths_glob": "禁改区条目行",
    "noai_paths_unique": "禁改区唯一路径",
    "noai_paths_categories": "禁改区分组",
    "tools_star_tools_py": "tools/*_tools.py 模块",
    "schema_tables": "schema 在用表",
    "noai_gate_pytest_collected": "test_noai_gate 用例数",
    "cli_tools_total": "cli tools 工具总数",
    "cli_tools_modules": "cli tools 已装模块",
    "webui_modules": "webui 模块数",
    "webui_routes": "webui 端点总数",
    "webui_routes_get": "webui GET",
    "webui_routes_post": "webui POST",
    "webui_routes_reader": "webui 只读面",
    "webui_routes_writer": "webui 写面",
    "webui_event_kinds": "webui 事件种类",
    "webui_test_files": "webui 判据文件数",
}

LABELS.update({f"cli_tools_role_{role}": f"{role.upper()} 角色工具数"
               for role in "abcdefghvlm"})

#: 文档里“当前值行”的豁免记号（带这些词的行说的是历史，不参与对账）。
HISTORICAL_MARKERS: tuple[str, ...] = ("S1", "S2", "当时", "历史", "原写", "原值", "旧版", "改前")

#: §2 第八层散文里那几个数的写法（与判据同一口径，但这里是本脚本自己的解析）。
_WEBUI_PROSE: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("webui_modules", re.compile(r"webui/`\s*——\s*\*\*(\d+)\s*个模块\*\*")),
    ("webui_routes", re.compile(r"`ROUTES`：\s*\*\*(\d+)\s*条\*\*")),
    ("webui_routes_get", re.compile(r"GET\s*\*\*(\d+)\*\*")),
    ("webui_routes_post", re.compile(r"POST\s*\*\*(\d+)\*\*")),
    ("webui_test_files", re.compile(r"判据文件共\s*\*\*(\d+)\*\*\s*个")),
)

_WEBUI_RUN = re.compile(r"⇒\s*`(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)`")
_WEBUI_RUN_KEYS: tuple[str, ...] = (
    "webui_routes", "webui_routes_get", "webui_routes_post",
    "webui_routes_reader", "webui_routes_writer",
)

_STATIC_ENTRY = re.compile(r"`static/([^`]+)`（(\d+)\s*B）")
_STATIC_REF = re.compile(r"""(?:src|href)=["'](?:[^"']*/)?assets/([^"']+)["']""")

_HEADLINE_TRIPLE = re.compile(r"\*\*(?P<files>\d+)\s*个\s*`\.py`、\s*(?P<lines>[\d,]+)\s*行\*\*")
_HEADLINE_BIG = re.compile(r"(?P<big>\d+)\s*个文件超过\s*800\s*行")
_HEADLINE_LOOP = re.compile(r"`agent_loop\.py`，\s*(?P<lines>[\d,]+)\s*行")
_HEAD_LINES = 12

_SEC3_ROW = re.compile(r"^\|\s*`([A-Za-z0-9_/]+\.py)`\s*\|\s*([0-9]+)\s*\|", re.M)

#: `error A / warning B / info C` 这种 linter 读数三元组。
#: 与 `tests/test_release_all.py::_TALLY_RE` 逐字相同 —— 这是 P0 的“同一口径”：
#: 工具与权威判据扫同一批字符，覆盖面对齐才谈得上对账。
_TALLY_RE = re.compile(r"error\s*(\d+)\s*/\s*warning\s*(\d+)\s*/\s*info\s*(\d+)")


class MeasureError(RuntimeError):
    """一项量不出来（子进程失败 / 文件不在 / 输出读不懂）—— 不是“一致”。"""


@dataclass
class Item:
    """一行对账：项目 · 文档值 · 现算值 · 判定。"""

    key: str
    label: str
    doc: str
    doc_value: object
    now_value: object
    status: str                     # ok / stale / missing
    detail: str = ""
    write: Callable[[str, object], str] | None = None

    def to_json(self) -> dict:
        """转成 JSON 里的那一格。"""
        return {"key": self.key, "label": self.label, "doc": self.doc,
                "doc_value": self.doc_value, "now_value": self.now_value,
                "status": self.status, "detail": self.detail}


@dataclass
class Context:
    """一趟对账要用的两棵树：测量根与文档根。"""

    root: Path
    docs_root: Path
    readings: dict[str, int] = field(default_factory=dict)
    unmeasured: dict[str, str] = field(default_factory=dict)


def _pin_utf8() -> None:
    """钉住 stdout/stderr 编码（GBK 重定向下打印 `⇒` 会抛，进程退 1 = 假红）。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _read(path: Path) -> str | None:
    """读一份 UTF-8 文本；读不到返回 None（不抛，由调用方记“文档缺项”）。"""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _int(value: str) -> int:
    """把 `1,234` 这类带千分位的数字读成整数。"""
    return int(str(value).replace(",", ""))


def _tail(text: str, limit: int = 600) -> str:
    """取输出尾部（报错现场在最后几行）。"""
    clean = (text or "").strip()
    return clean if len(clean) <= limit else "…" + clean[-limit:]


def _sub_first(text: str, pattern: re.Pattern[str], value: object, group: int = 1) -> str:
    """把 `pattern` 第一次命中的第 `group` 组换成 `value`；没命中原样返回。"""
    hit = pattern.search(text)
    if hit is None:
        return text
    return text[:hit.start(group)] + str(value) + text[hit.end(group):]


def _sub_all(text: str, pattern: re.Pattern[str], value: object) -> str:
    """把 `pattern` 每一处命中的数字都换成同一个值（同一口径多处落位时用）。"""
    return pattern.sub(lambda m: str(value), text)


# ---------------------------------------------------------------- 现算（不读文档）

def _python_env(root: Path) -> dict[str, str]:
    """子进程环境：UTF-8 + `src` 进 PYTHONPATH + Lean 开档（与判据同一口径）。"""
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("AGENTFLOW_LEAN_ENABLED", "1")
    src = str(root / "src")
    prior = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src + (os.pathsep + prior if prior else "")
    return env


def _run(root: Path, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    """起一个子进程；起不了 / 超时都折成 MeasureError（没查成，不是失败）。"""
    try:
        return subprocess.run([sys.executable, *args], cwd=str(root), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, env=_python_env(root))
    except subprocess.TimeoutExpired as exc:
        raise MeasureError(f"子进程超过 {timeout} 秒没结束：{args[:2]}") from exc
    except OSError as exc:
        raise MeasureError(f"起不了子进程：{type(exc).__name__}: {exc}") from exc


def measure_lint(root: Path, timeout: int) -> dict[str, int]:
    """跑 linter 两档，从它自己写的 JSON 里取 warning / info 两栏。"""
    script = root / "scripts" / "lint_rules.py"
    if not script.is_file():
        raise MeasureError(f"读不到 {script}")
    out: dict[str, int] = {}
    with tempfile.TemporaryDirectory(prefix="docnum-lint-") as tmp:
        for strict, prefix in ((False, ""), (True, "strict_")):
            dest = Path(tmp) / f"lint_{prefix or 'daily'}.json"
            args = [str(script), "--root", str(root), "--json-out", str(dest)]
            if strict:
                args.append("--strict")
            proc = _run(root, args, timeout)
            if proc.returncode == EXIT_UNKNOWN:
                raise MeasureError(f"linter{'' if not strict else ' --strict'} 自己以 2 结束"
                                   f"：{_tail(proc.stderr)}")
            if not dest.is_file():
                raise MeasureError(f"linter 没写出 {dest}（退出码 {proc.returncode}）")
            try:
                doc = json.loads(dest.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise MeasureError(f"linter 的 JSON 读不出来：{type(exc).__name__}: {exc}") from exc
            if "warning_count" not in doc or "info_count" not in doc:
                raise MeasureError("linter 的 JSON 里没有 warning_count / info_count")
            out[f"lint_rules_{prefix}warning"] = int(doc["warning_count"])
            out[f"lint_rules_{prefix}info"] = int(doc["info_count"])
            if not strict:
                out["lint_rules_rules"] = len(doc.get("rules_run") or ())
    if out.get("lint_rules_rules", 0) <= 0:
        raise MeasureError("linter 报了 0 条规则 ⇒ 扫描器失配，不是“一致”")
    return out


def measure_noai_paths(root: Path, timeout: int) -> dict[str, int]:
    """按 `.noai-paths` 现算：条目行 / 唯一路径 / 分组数。"""
    text = _read(root / ".noai-paths")
    if text is None:
        raise MeasureError("读不到 .noai-paths")
    rows = [line for line in text.splitlines() if re.match(r"^\S+\s+\[category:", line)]
    paths = {line.split()[0] for line in rows}
    cats = {m.group(1) for line in rows
            if (m := re.search(r"\[category:\s*([a-z\-]+)\]", line))}
    if not rows:
        raise MeasureError(".noai-paths 里一条条目行都没读到 ⇒ 扫描失配")
    return {"noai_paths_glob": len(rows), "noai_paths_unique": len(paths),
            "noai_paths_categories": len(cats)}


def measure_tool_modules(root: Path, timeout: int) -> dict[str, int]:
    """`src/agentflow/tools/*_tools.py` 的模块数。"""
    tools = root / "src" / "agentflow" / "tools"
    if not tools.is_dir():
        raise MeasureError(f"目录不在：{tools}")
    return {"tools_star_tools_py": len(list(tools.glob("*_tools.py")))}


def measure_schema_tables(root: Path, timeout: int) -> dict[str, int]:
    """在子进程里 import `agentflow.schema`，取 `len(TABLES)`。"""
    proc = _run(root, ["-c", "import agentflow.schema as s;print(len(s.TABLES))"], timeout)
    if proc.returncode != 0:
        raise MeasureError(f"import agentflow.schema 失败：{_tail(proc.stderr)}")
    return {"schema_tables": _parse_last_int(proc.stdout, "schema.TABLES")}


def measure_collected(root: Path, timeout: int) -> dict[str, int]:
    """`pytest --collect-only -q` 报出的 `N tests collected`（只收集、不跑）。"""
    rel = "tests/test_noai_gate.py"
    if not (root / rel).is_file():
        raise MeasureError(f"{rel} 不在盘上")
    proc = _run(root, ["-m", "pytest", rel, "--collect-only", "-q",
                       "-p", "no:cacheprovider"], timeout)
    match = re.search(r"(\d+)\s+tests?\s+collected", proc.stdout + proc.stderr)
    if not match:
        raise MeasureError(f"--collect-only 的输出里读不到用例条数：{_tail(proc.stdout + proc.stderr)}")
    return {"noai_gate_pytest_collected": int(match.group(1))}


def measure_cli_tools(root: Path, timeout: int) -> dict[str, int]:
    """跑 `python -m agentflow.cli tools`，读工具总数 / 模块数 / 逐角色格。"""
    proc = _run(root, ["-m", "agentflow.cli", "tools"], timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    total = re.search(r"工具总数：(\d+)", out)
    modules = re.search(r"已装模块 (\d+)", out)
    roles_line = re.search(r"各角色工具数：(\{[^}]*\})", out)
    if not (total and modules and roles_line):
        raise MeasureError(f"`cli tools` 的输出里读不到那三格：{_tail(out)}")
    roles = {name: int(num) for name, num in re.findall(r"'([A-Z])':\s*(\d+)", roles_line.group(1))}
    want_roles = "ABCDEFGHVLM"
    absent = [r for r in want_roles if r not in roles]
    if absent:
        raise MeasureError(f"`cli tools` 的逐角色格缺 {absent}"
                           "（Lean 开档应有 L；先查 AGENTFLOW_LEAN_ENABLED）")
    got = {"cli_tools_total": int(total.group(1)), "cli_tools_modules": int(modules.group(1))}
    got.update({f"cli_tools_role_{name.lower()}": num for name, num in roles.items()})
    return got


def _parse_last_int(text: str, what: str) -> int:
    """读输出里最后一行的整数（空输出 / 非整数都算没量到）。"""
    for line in reversed([ln.strip() for ln in text.splitlines() if ln.strip()]):
        try:
            return int(line.split()[-1])
        except (ValueError, IndexError):
            continue
    raise MeasureError(f"{what} 的输出里读不到整数：{_tail(text)}")


def measure_webui_modules(root: Path, timeout: int) -> dict[str, int]:
    """`webui/*.py` 的模块数。"""
    directory = root / "src" / "agentflow" / "webui"
    if not directory.is_dir():
        raise MeasureError(f"目录不在：{directory}")
    return {"webui_modules": len(list(directory.glob("*.py")))}


def measure_webui_files(root: Path, timeout: int) -> dict[str, int]:
    """`tests/test_webui*.py` 的判据文件数。"""
    tests = root / "tests"
    if not tests.is_dir():
        raise MeasureError(f"目录不在：{tests}")
    return {"webui_test_files": len(list(tests.glob("test_webui*.py")))}


def measure_webui_face(root: Path, timeout: int) -> dict[str, int]:
    """在子进程里 import `webui.routes` / `webui.sse`，取端点与事件那六格。"""
    code = (
        "import sys;sys.path.insert(0,'src');"
        "from agentflow.webui import routes as r, sse as s;"
        "print(len(r.ROUTES),"
        "sum(1 for x in r.ROUTES if str(x[0]).upper()=='GET'),"
        "sum(1 for x in r.ROUTES if str(x[0]).upper()=='POST'),"
        "len(r.READER_ROUTES),len(r.WRITE_ROUTES),len(s.EVENT_KINDS))"
    )
    proc = _run(root, ["-c", code], timeout)
    if proc.returncode != 0:
        raise MeasureError(f"import agentflow.webui 失败：{_tail(proc.stderr)}")
    nums = [int(x) for x in re.findall(r"\d+", proc.stdout)]
    if len(nums) < 6:
        raise MeasureError(f"webui 六个读数读不出来：{_tail(proc.stdout)}")
    return dict(zip(("webui_routes", "webui_routes_get", "webui_routes_post",
                     "webui_routes_reader", "webui_routes_writer",
                     "webui_event_kinds"), nums[:6]))


#: 每组测量失败时，把这条错误记到组内每一个键上（逐键报“没量到”）。
_MEASURE_GROUPS: tuple[tuple[str, tuple[str, ...], Callable], ...] = (
    ("lint", ("lint_rules_rules", "lint_rules_warning", "lint_rules_info",
              "lint_rules_strict_warning", "lint_rules_strict_info"), measure_lint),
    ("noai_paths", ("noai_paths_glob", "noai_paths_unique", "noai_paths_categories"),
     measure_noai_paths),
    ("tools", ("tools_star_tools_py",), measure_tool_modules),
    ("schema", ("schema_tables",), measure_schema_tables),
    ("collected", ("noai_gate_pytest_collected",), measure_collected),
    ("cli_tools", ("cli_tools_total", "cli_tools_modules", "cli_tools_role_a",
                   "cli_tools_role_b", "cli_tools_role_c", "cli_tools_role_d",
                   "cli_tools_role_e", "cli_tools_role_f", "cli_tools_role_g",
                   "cli_tools_role_h", "cli_tools_role_l", "cli_tools_role_m",
                   "cli_tools_role_v"), measure_cli_tools),
    ("webui_modules", ("webui_modules",), measure_webui_modules),
    ("webui_files", ("webui_test_files",), measure_webui_files),
    ("webui_face", ("webui_routes", "webui_routes_get", "webui_routes_post",
                    "webui_routes_reader", "webui_routes_writer", "webui_event_kinds"),
     measure_webui_face),
)


def measure(root: Path, timeout: int) -> tuple[dict[str, int], dict[str, str]]:
    """把 32 个键逐组现算；某一组没量到就逐键记原因，不让“没查到”变成 0。"""
    readings: dict[str, int] = {}
    unmeasured: dict[str, str] = {}
    for name, keys, func in _MEASURE_GROUPS:
        try:
            got = func(root, timeout)
        except (MeasureError, OSError, ValueError, TypeError) as exc:
            for key in keys:
                unmeasured[key] = f"{name} 组没量到：{exc}"
            continue
        missing = [key for key in keys if key not in got]
        if missing:
            for key in missing:
                unmeasured[key] = f"{name} 组少给了 {missing}"
        readings.update({key: value for key, value in got.items() if key in keys})
    return readings, unmeasured


def headline_now(root: Path) -> dict[str, int]:
    """现算 READING-MAP 开头那句的四格（口径：`src/` 下全部 `*.py`）。"""
    src = root / "src"
    if not src.is_dir():
        raise MeasureError(f"目录不在：{src}")
    sizes = [(path, len(path.read_text(encoding="utf-8").splitlines()))
             for path in sorted(src.rglob("*.py"))
             if "__pycache__" not in str(path)]
    if not sizes:
        raise MeasureError(f"{src} 下一个 `*.py` 都没读到 ⇒ 判据在扫空集")
    loops = [count for path, count in sizes if path.name == "agent_loop.py"]
    if not loops:
        raise MeasureError("`src/` 下没有 `agent_loop.py`")
    return {"files": len(sizes), "total": sum(count for _path, count in sizes),
            "big": sum(1 for _path, count in sizes if count > 800), "loop": loops[0]}


# ---------------------------------------------------------------- 文档 → 对账项

def _status(doc_value: object, now_value: object) -> str:
    """三态：文档缺项 / 过期 / 一致。"""
    if doc_value is None or now_value is None:
        return "missing"
    return "ok" if str(doc_value) == str(now_value) else "stale"


def _live_block(text: str) -> dict[str, int]:
    """从 `LIVE-READINGS` 块里读 `名字 = 数字`；块不在 ⇒ 空字典。"""
    begin, end = "LIVE-READINGS:BEGIN", "LIVE-READINGS:END"
    if begin not in text or end not in text:
        return {}
    body = text.split(begin, 1)[1].split(end, 1)[0]
    out: dict[str, int] = {}
    for raw in body.splitlines():
        match = re.match(r"^([a-z_]+)\s*=\s*(\d+)\s*(?:#.*)?$", raw.strip())
        if match:
            out[match.group(1)] = int(match.group(2))
    return out


def _live_write(key: str) -> Callable[[str, object], str]:
    """LIVE-READINGS 一行的写回：只换 `=` 后面的数字，行内注释不动。"""
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)(\d+)", re.M)

    def apply(text: str, value: object) -> str:
        """把该键的数字换成 `value`（锚点必须恰好一行）。"""
        if len(pattern.findall(text)) != 1:
            return text
        return _sub_first(text, pattern, value, 2)

    return apply


def build_live_items(ctx: Context, items: list[Item]) -> None:
    """第 1 类：`LIVE-READINGS` 块逐键对账。"""
    text = _read(ctx.docs_root / SPEC_REL)
    if text is None:
        items.append(Item("live-block", "LIVE-READINGS 块（文档不在）", SPEC_REL,
                          None, None, "missing", f"读不到 {SPEC_REL}"))
        return
    declared = _live_block(text)
    if not declared:
        items.append(Item("live-block", "LIVE-READINGS 块", SPEC_REL, None, None,
                          "missing", "块不在，或块里一行 `名字 = 数字` 都没有"))
        return
    for key in LIVE_KEYS:
        doc_value = declared.get(key)
        now_value = ctx.readings.get(key)
        detail = ""
        if key in ctx.unmeasured:
            detail = ctx.unmeasured[key]
        elif doc_value is None:
            detail = "块里缺这个键"
        elif now_value is None:
            detail = "没量到现算值"
        items.append(Item(f"live:{key}", LABELS.get(key, key), SPEC_REL,
                          doc_value, now_value, _status(doc_value, now_value),
                          detail, _live_write(key)))
    for extra in sorted(set(declared) - set(LIVE_KEYS)):
        items.append(Item(f"live:{extra}", f"未知键 {extra}", SPEC_REL,
                          declared[extra], None, "missing", "判据不认的键（加键要同时改判据）"))


def _webui_section(text: str) -> tuple[int, int, str]:
    """§2 第八层那一节的 `(起, 止, 原文)`；读不到返回 `(0, 0, "")`。"""
    begin = text.find("**⑧ Web / 用户端**")
    if begin < 0:
        return 0, 0, ""
    end = text.find("\n---", begin)
    end = len(text) if end < 0 else end
    return begin, end, text[begin:end]


def build_prose_items(ctx: Context, items: list[Item]) -> None:
    """第 2 类：§2 第八层散文里的 web 读数。"""
    text = _read(ctx.docs_root / SPEC_REL)
    if text is None:
        return
    _begin, _end, section = _webui_section(text)
    if not section:
        items.append(Item("prose:section", "§2 第八层（读不到）", SPEC_REL, None, None,
                          "missing", "读不到 `**⑧ Web / 用户端**` 那一节"))
        return
    for key, pattern in _WEBUI_PROSE:
        hits = pattern.findall(section)
        now_value = ctx.readings.get(key)
        if len(hits) != 1:
            items.append(Item(f"prose:{key}", LABELS.get(key, key) + "（散文）", SPEC_REL,
                              None, now_value, "missing",
                              f"散文里命中 {len(hits)} 次（要恰好 1 次）"))
            continue
        doc_value = int(hits[0])
        status = _status(doc_value, now_value)
        detail = "" if status == "ok" else f"散文与块同源；现算是 {now_value}"

        def apply(text_: str, value: object, _p: re.Pattern[str] = pattern) -> str:
            """把散文里那一处的数字换掉。"""
            return _sub_first(text_, _p, value, 1)

        items.append(Item(f"prose:{key}", LABELS.get(key, key) + "（散文）", SPEC_REL,
                          doc_value, now_value, status, detail, apply))
    runs = _WEBUI_RUN.findall(section)
    want = tuple(ctx.readings.get(key) for key in _WEBUI_RUN_KEYS)
    want_text = " ".join(str(v) for v in want) if all(v is not None for v in want) else None
    if len(runs) != 1:
        items.append(Item("prose:webui_run", "webui 五数复跑行", SPEC_REL, None, want_text,
                          "missing", f"散文里命中 {len(runs)} 次（要恰好 1 次）"))
        return
    doc_text = " ".join(runs[0])
    status = _status(doc_text, want_text)
    detail = "" if status == "ok" else f"顺序：{list(_WEBUI_RUN_KEYS)}"

    def apply_run(text_: str, value: object) -> str:
        """把五数复跑行整条换成新读数。"""
        want_ = str(value).split()
        if len(want_) != 5:
            return text_
        hit = _WEBUI_RUN.search(text_)
        if hit is None:
            return text_
        return text_[:hit.start()] + f"⇒ `{' '.join(want_)}`" + text_[hit.end():]

    items.append(Item("prose:webui_run", "webui 五数复跑行", SPEC_REL,
                      doc_text, want_text, status, detail, apply_run))


def static_want(root: Path) -> tuple[list[tuple[str, int]], str]:
    """从 `web/static/index.html` 现读它点名的三件产物：`(rel, bytes)` 与错误说明。"""
    static_dir = root / "src" / "agentflow" / "web" / "static"
    index = static_dir / "index.html"
    if not index.is_file():
        return [], f"构建产物不在盘上：{index}"
    refs = _STATIC_REF.findall(index.read_text(encoding="utf-8", errors="replace"))
    want: list[tuple[str, int]] = [("index.html", index.stat().st_size)]
    for ref in refs:
        path = static_dir / "assets" / ref
        if not path.is_file():
            return [], f"`index.html` 点名的静态产物不在盘上：{path}"
        want.append((f"assets/{ref}", path.stat().st_size))
    return want, ""


def _static_writer(want: list[tuple[str, int]]) -> Callable[[str, object], str]:
    """按现盘重写第八层那三个 `static/...`（N B）条目（位置与文件名一起换）。"""

    def apply(text: str, _value: object) -> str:
        """重写整组三格；文档条目不是恰好三个时原样返回。"""
        begin, end, section = _webui_section(text)
        hits = list(_STATIC_ENTRY.finditer(section))
        if not section or len(hits) != 3 or len(want) != 3:
            return text
        out = section
        for hit, (rel, size) in zip(reversed(hits), reversed(want)):
            out = out[:hit.start()] + f"`static/{rel}`（{size} B）" + out[hit.end():]
        return text[:begin] + out + text[end:]

    return apply


def _asset_kind(rel: str) -> str:
    """静态产物的种类（`html` / `js` / `css`）—— 重建换名时按同类配对。"""
    return rel.rsplit(".", 1)[-1].lower() if "." in rel else ""


def build_static_items(ctx: Context, items: list[Item]) -> None:
    """第 3 类：静态产物三格（名字 + 字节；同名比字节，换名按同类配对）。"""
    text = _read(ctx.docs_root / SPEC_REL)
    if text is None:
        return
    _begin, _end, section = _webui_section(text)
    if not section:
        return
    hits = _STATIC_ENTRY.findall(section)
    if len(hits) != 3:
        items.append(Item("static:set", "静态产物三格", SPEC_REL, None, None, "missing",
                          f"第八层里带字节数的条目命中 {len(hits)} 个（要恰好 3 个）"))
        return
    declared = {rel: int(size) for rel, size in hits}
    want, why = static_want(ctx.root)
    if why:
        items.append(Item("static:set", "静态产物三格（盘上读不到）", SPEC_REL,
                          None, None, "missing", why))
        return
    writer = _static_writer(want)
    want_map = dict(want)
    replaced: set[str] = set()
    for rel, size in want:
        if rel in declared:
            doc_value = declared[rel]
            status = _status(doc_value, size)
            detail = ""
        else:
            same_kind = [old for old in declared if _asset_kind(old) == _asset_kind(rel)]
            if len(same_kind) == 1:
                doc_value = declared[same_kind[0]]
                replaced.add(same_kind[0])
                status = "stale"
                detail = (f"重建换了名：`static/{same_kind[0]}` -> `static/{rel}`"
                          f"（字节 {doc_value} -> {size}）")
            else:
                doc_value = None
                status = "missing"
                detail = f"文档没列 `static/{rel}`（文件名换了，且同类条目不唯一）"
        items.append(Item(f"static:{rel}", f"静态产物 {rel}", SPEC_REL,
                          doc_value, size, status, detail, writer))
    for rel, size in declared.items():
        if rel not in want_map and rel not in replaced:
            items.append(Item(f"static:{rel}", f"静态产物 {rel}（盘上没有）", SPEC_REL,
                              size, None, "stale", "文档列了这一件，盘上已没有（重建后换名）",
                              writer))


def build_headline_items(ctx: Context, items: list[Item]) -> None:
    """第 4 类：`READING-MAP.md` 开头那句四格。"""
    text = _read(ctx.docs_root / MAP_REL)
    if text is None:
        items.append(Item("map:headline", "READING-MAP 开头（文档不在）", MAP_REL,
                          None, None, "missing", f"读不到 {MAP_REL}"))
        return
    head = "\n".join(text.splitlines()[:_HEAD_LINES])
    try:
        now = headline_now(ctx.root)
    except (MeasureError, OSError) as exc:
        items.append(Item("map:headline", "READING-MAP 开头（现算失败）", MAP_REL,
                          None, None, "missing", str(exc)))
        return
    triple = _HEADLINE_TRIPLE.search(head)
    big_hit = _HEADLINE_BIG.search(head)
    loop_hit = _HEADLINE_LOOP.search(head)
    if not triple or not big_hit or not loop_hit:
        items.append(Item("map:headline", "READING-MAP 开头三格", MAP_REL, None, None,
                          "missing", "开头那段里读不出三格读数或 agent_loop 行数"))
        return
    doc_files, doc_total = int(triple.group("files")), _int(triple.group("lines"))
    doc_big = int(big_hit.group("big"))
    doc_loop = _int(loop_hit.group("lines"))
    p_files = re.compile(r"\*\*(\d+)\s*个\s*`\.py`")
    p_total = re.compile(r"\*\*(\d+)\s*个\s*`\.py`、\s*([\d,]+)\s*行\*\*")
    p_big = _HEADLINE_BIG
    p_loop = re.compile(r"`agent_loop\.py`，\s*([\d,]+)\s*行")

    def w_files(text_: str, value: object) -> str:
        """换文件数那一格。"""
        return _sub_first(text_, p_files, value, 1)

    def w_total(text_: str, value: object) -> str:
        """换总行数那一格（带千分位）。"""
        return _sub_first(text_, p_total, f"{int(value):,}", 2)

    def w_big(text_: str, value: object) -> str:
        """换 `>800` 文件数那一格。"""
        return _sub_first(text_, p_big, value, 1)

    def w_loop(text_: str, value: object) -> str:
        """换 `agent_loop.py` 行数那一格（带千分位）。"""
        return _sub_first(text_, p_loop, f"{int(value):,}", 1)

    for key, label, doc_value, now_value, writer in (
        ("files", "READING-MAP 文件数", doc_files, now["files"], w_files),
        ("total", "READING-MAP 总行数", doc_total, now["total"], w_total),
        ("big", "READING-MAP >800 文件数", doc_big, now["big"], w_big),
        ("loop", "READING-MAP agent_loop 行数", doc_loop, now["loop"], w_loop),
    ):
        status = _status(doc_value, now_value)
        items.append(Item(f"map:headline:{key}", label, MAP_REL,
                          doc_value, now_value, status, "", writer))


def build_sec3_items(ctx: Context, items: list[Item]) -> None:
    """第 5 类：READING-MAP 里的行数表（判据口径是整份文件，不只 §3 那一节）。"""
    text = _read(ctx.docs_root / MAP_REL)
    if text is None:
        return
    rows = _SEC3_ROW.findall(text)
    if not rows:
        items.append(Item("map:rows", "READING-MAP 行数表", MAP_REL, None, None,
                          "missing", "整份文件里读不出一行 `| \\`模块\\` | 行数 |`"))
        return
    for rel, old in rows:
        path = ctx.root / "src" / "agentflow" / rel
        now_value = (len(path.read_text(encoding="utf-8").splitlines())
                     if path.is_file() else None)
        status = _status(int(old), now_value)
        detail = "" if path.is_file() else f"盘上没有 {path}"

        def apply(text_: str, value: object, _rel: str = rel, _old: str = old) -> str:
            """只换这一行第二格的行数（按模块名定位，不按行号）。"""
            pattern = re.compile(rf"^(\| `{re.escape(_rel)}` \| )({_old})( \|)", re.M)
            return _sub_first(text_, pattern, value, 2) if pattern.search(text_) else text_

        items.append(Item(f"map:row:{rel}", f"行数表 {rel}", MAP_REL,
                          int(old), now_value, status, detail, apply))


def build_index_items(ctx: Context, items: list[Item]) -> None:
    """第 6 类：`INDEX.md` 的 `MIN_DOCS`（反真空下限）。"""
    text = _read(ctx.docs_root / INDEX_REL)
    if text is None:
        items.append(Item("index:MIN_DOCS", "INDEX MIN_DOCS（文档不在）", INDEX_REL,
                          None, None, "missing", f"读不到 {INDEX_REL}"))
        return
    hit = re.search(r"MIN_DOCS\s*=\s*(\d+)", text)
    if hit is None:
        items.append(Item("index:MIN_DOCS", "INDEX MIN_DOCS", INDEX_REL, None, None,
                          "missing", "INDEX 里读不到 `MIN_DOCS = N`"))
        return
    test_file = ctx.root / "tests" / "test_docs_index_covers_every_doc.py"
    test_text = _read(test_file)
    source = "tests/test_docs_index_covers_every_doc.py 的常量"
    now_value: int | None = None
    if test_text is not None:
        const = re.search(r"^MIN_DOCS\s*=\s*(\d+)", test_text, re.M)
        if const:
            now_value = int(const.group(1))
    if now_value is None:
        docs = ctx.root / "docs"
        if docs.is_dir():
            now_value = len([p for p in docs.glob("*.md") if p.name != "INDEX.md"])
            source = "tests/ 不在，退回盘上 docs 份数"
    status = _status(int(hit.group(1)), now_value)
    detail = f"现算口径：{source}"

    def apply(text_: str, value: object) -> str:
        """把 `MIN_DOCS = N` 的 N 换掉。"""
        return _sub_first(text_, re.compile(r"(MIN_DOCS\s*=\s*)(\d+)"), value, 2)

    items.append(Item("index:MIN_DOCS", "INDEX MIN_DOCS", INDEX_REL,
                      int(hit.group(1)), now_value, status, detail, apply))


def build_scripts_readme_items(ctx: Context, items: list[Item]) -> None:
    """第 7 类：`scripts/README.md` 点名的脚本集合 vs `scripts/*.py` 现盘集合。"""
    text = _read(ctx.docs_root / SCRIPTS_README_REL)
    if text is None:
        items.append(Item("scripts:roster", "scripts/README 工具面（文档不在）",
                          SCRIPTS_README_REL, None, None, "missing",
                          f"读不到 {SCRIPTS_README_REL}"))
        return
    scripts_dir = ctx.root / "scripts"
    if not scripts_dir.is_dir():
        items.append(Item("scripts:roster", "scripts/README 工具面（目录不在）",
                          SCRIPTS_README_REL, None, None, "missing",
                          f"目录不在：{scripts_dir}"))
        return
    disk = {p.name for p in scripts_dir.glob("*.py") if p.name != "__init__.py"}
    mentioned: set[str] = set()
    for token in re.findall(r"[A-Za-z_][\w./-]*\.py", text):
        name = token.rsplit("/", 1)[-1]
        if name.startswith("test_") or "tests/" in token:
            continue
        mentioned.add(name)
    status = "ok" if mentioned == disk else "stale"
    missing = sorted(disk - mentioned)
    extra = sorted(mentioned - disk)
    detail = ""
    if status != "ok":
        detail = f"盘上有、README 没登记：{missing}；README 有、盘上没有：{extra}"
    items.append(Item("scripts:roster", "scripts/README 脚本面", SCRIPTS_README_REL,
                      len(mentioned), len(disk), status, detail))


_MANIFEST_PROSE: tuple[tuple[str, str, re.Pattern[str], str], ...] = (
    ("noai_paths_glob", "条条目", re.compile(r"(\d+)(?:\*\*)?\s*条条目"), r"(\d+)(?:\*\*)?\s*条条目"),
    ("noai_paths_glob", "条 glob", re.compile(r"(\d+)(?:\*\*)?\s*条 glob"), r"(\d+)(?:\*\*)?\s*条 glob"),
    ("noai_paths_glob", "条、", re.compile(r"(\d+)(?:\*\*)?\s*条、"), r"(\d+)(?:\*\*)?\s*条、"),
    ("noai_paths_unique", "条唯一路径", re.compile(r"(\d+)(?:\*\*)?\s*条唯一路径"),
     r"(\d+)(?:\*\*)?\s*条唯一路径"),
    ("noai_paths_categories", "个分组", re.compile(r"(\d+)(?:\*\*)?\s*个分组"),
     r"(\d+)(?:\*\*)?\s*个分组"),
    ("noai_paths_categories", "个类别", re.compile(r"(\d+)(?:\*\*)?\s*个类别"),
     r"(\d+)(?:\*\*)?\s*个类别"),
)

_MANIFEST_TABLE: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("noai_paths_glob", "清单 glob 数",
     re.compile(r"(\|\s*\*\*清单 glob 数\*\*[^|]*\|[^|]*\|\s*\*\*)(\d+)(\*\*)")),
    ("noai_paths_unique", "唯一路径数",
     re.compile(r"(\|\s*\*\*唯一路径数\*\*[^|]*\|[^|]*\|\s*\*\*)(\d+)(\*\*)")),
    ("noai_paths_categories", "禁改区类别数",
     re.compile(r"(\|\s*\*\*禁改区类别数\*\*[^|]*\|[^|]*\|\s*\*\*)(\d+)(\*\*)")),
)


def _rewrite_unique_line(text: str, anchor: str, pattern: re.Pattern[str], value: object,
                         group: int = 1) -> str:
    """按“整行原文”定位唯一一行，再换掉该行里 `pattern` 的第 `group` 组。"""
    lines = text.splitlines(keepends=True)
    same = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == anchor]
    if len(same) != 1:
        return text
    line = lines[same[0]]
    hit = pattern.search(line)
    if hit is None:
        return text
    lines[same[0]] = line[:hit.start(group)] + str(value) + line[hit.end(group):]
    return "".join(lines)


def build_manifest_items(ctx: Context, items: list[Item]) -> None:
    """第 8 类：spec 里其余 `.noai-paths` 计数与 `test_noai_gate.py` 用例数（逐处）。"""
    text = _read(ctx.docs_root / SPEC_REL)
    if text is None:
        return
    hits = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if any(mark in line for mark in HISTORICAL_MARKERS):
            continue
        plain = line.replace("**", "")
        for key, unit, read_rx, write_rx in _MANIFEST_PROSE:
            for found in read_rx.finditer(plain):
                hits += 1
                doc_value = int(found.group(1))
                now_value = ctx.readings.get(key)
                status = _status(doc_value, now_value)
                anchor = line

                def apply(text_: str, value: object, _anchor: str = anchor,
                          _rx: re.Pattern[str] = re.compile(write_rx)) -> str:
                    """按整行锚点换掉这一处计数。"""
                    return _rewrite_unique_line(text_, _anchor, _rx, value, 1)

                items.append(Item(f"spec:manifest:{lineno}:{unit}", f"spec 行{lineno} {unit}",
                                  SPEC_REL, doc_value, now_value, status, "", apply))
        for key, label, write_rx in _MANIFEST_TABLE:
            found = write_rx.search(line)
            if not found:
                continue
            hits += 1
            doc_value = int(found.group(2))
            now_value = ctx.readings.get(key)
            status = _status(doc_value, now_value)
            anchor = line

            def apply_table(text_: str, value: object, _anchor: str = anchor,
                            _rx: re.Pattern[str] = write_rx) -> str:
                """按整行锚点换掉表格里的那一格。"""
                return _rewrite_unique_line(text_, _anchor, _rx, value, 2)

            items.append(Item(f"spec:manifest:{lineno}:{label}", f"spec 行{lineno} {label}",
                              SPEC_REL, doc_value, now_value, status, "", apply_table))
        if "tests/test_noai_gate.py" in line:
            for found in re.finditer(r"(\d+)\s*passed", line):
                hits += 1
                doc_value = int(found.group(1))
                now_value = ctx.readings.get("noai_gate_pytest_collected")
                status = _status(doc_value, now_value)
                anchor = line

                def apply_passed(text_: str, value: object, _anchor: str = anchor) -> str:
                    """按整行锚点换掉用例数。"""
                    return _rewrite_unique_line(
                        text_, _anchor, re.compile(r"(\d+)(\s*passed)"), value, 1)

                items.append(Item(f"spec:pytest:{lineno}", f"spec 行{lineno} 用例数",
                                  SPEC_REL, doc_value, now_value, status, "", apply_passed))
    if not hits:
        items.append(Item("spec:manifest", "spec 里的 .noai-paths 计数", SPEC_REL,
                          None, None, "missing",
                          "一处 `.noai-paths` 计数声明都读不到 ⇒ 判据失去对象"))


#: 第 10 类的覆盖面：清单计数散落在四份「当前值」文档里（根 README 在文档根上一级）。
_MANIFEST_SPREAD_FILES: tuple[tuple[str, str], ...] = (
    (SPEC_REL, "docs/DEVELOPMENT-SPEC.md"),
    (ROOT_README_REL, "根 README.md"),
    (INDEX_REL, "docs/INDEX.md"),
    (SYSTEM_INTRO_REL, "docs/SYSTEM-INTRO.md"),
)

#: 第 10 类的三类形态。前五条与 `tests/test_release_all.py::_MANIFEST_CLAIM_RES` 同一口径
#: （带单位，`(?:\*\*)?` 让 `**63** 条 glob` 与 `63 条条目` 是同一条正则）；
#: 后三条是无「条」字变体（`46 条目 / 43 唯一路径 / 7 分组`）—— 它们刻意不带 `条`，
#: 所以前五条一条都接不住，这正是 `docs/SYSTEM-INTRO.md:804` 长期写着旧值而不红的原因。
_MANIFEST_SPREAD_RES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("noai_paths_glob", "条条目", re.compile(r"(\d+)(?:\*\*)?\s*条条目")),
    ("noai_paths_glob", "条 glob", re.compile(r"(\d+)(?:\*\*)?\s*条 glob")),
    ("noai_paths_glob", "条、", re.compile(r"(\d+)(?:\*\*)?\s*条、")),
    ("noai_paths_unique", "条唯一路径", re.compile(r"(\d+)(?:\*\*)?\s*条唯一路径")),
    ("noai_paths_categories", "个分组", re.compile(r"(\d+)(?:\*\*)?\s*个分组")),
    ("noai_paths_categories", "个类别", re.compile(r"(\d+)(?:\*\*)?\s*个类别")),
    ("noai_paths_glob", "条目（无条）", re.compile(r"(\d+)(?:\*\*)?\s*条目")),
    ("noai_paths_unique", "唯一路径（无条）", re.compile(r"(\d+)(?:\*\*)?\s*唯一路径")),
    ("noai_paths_categories", "分组（无个）", re.compile(r"(\d+)(?:\*\*)?\s*分组")),
)

#: 成对 ASCII 双引号包住的是引文（归档件原话），不是当次声明。
#: `docs/INDEX.md:45` 里 `"…清单条目 46 条唯一路径"` 引的是 2026-10-27 那版归档件，
#: 同一行紧跟的 `**47** 条条目 / **44** 条唯一路径` 才是现盘读数 —— 若把引文也拿来对账，
#: 修数字就变成伪造历史；所以这一类逐处判「这一处的数字是不是落在引文里」。
_QUOTE_SPAN = re.compile(r'"[^"\n]*"')

#: 一类里一处声明都读不到的文件（删掉计数不等于计数是对的）。
_SPREAD_LOST_OBJECT = "一处清单计数声明都读不到 ⇒ 判据失去对象"


def _quote_spans(line: str) -> list[tuple[int, int]]:
    """一行里被成对 ASCII 双引号包住的区间。"""
    return [(found.start(), found.end()) for found in _QUOTE_SPAN.finditer(line)]


def _in_quote(pos: int, spans: list[tuple[int, int]]) -> bool:
    """这个偏移是不是落在引文里。"""
    return any(begin <= pos < end for begin, end in spans)


def _manifest_spread_writer(lineno: int, read_rx: re.Pattern[str],
                            old_value: int) -> Callable[[str, object], str]:
    """按「行号 + 单位形态 + 改前值」定位那一处，只换数字（保留成对星号）。

    行号在这里是稳定锚：写回只替换数字、不增删行，所以同一份文档里多处写回时行号不变
    （`docs/SYSTEM-INTRO.md:804` 一行三处，正是靠这一点逐处写）。同一行里同值命中不止
    一处就放弃 —— 猜着写比不写更糟。
    """

    def apply(text: str, value: object) -> str:
        """换掉该行第 `lineno` 行里那一个非引文计数。"""
        lines = text.splitlines(keepends=True)
        if not 1 <= lineno <= len(lines):
            return text
        line = lines[lineno - 1]
        spans = _quote_spans(line)
        hits = [found for found in read_rx.finditer(line)
                if not _in_quote(found.start(1), spans) and int(found.group(1)) == old_value]
        if len(hits) != 1:
            return text
        hit = hits[0]
        lines[lineno - 1] = line[:hit.start(1)] + str(value) + line[hit.end(1):]
        return "".join(lines)

    return apply


def build_manifest_spread_items(ctx: Context, items: list[Item]) -> None:
    """第 10 类：四份当前值文档里的清单计数（带单位 / 加粗 + 单位 / 无「条」字变体）。

    为什么要有这一类：`manifest_claim_problems()`（权威判据）只读 `DEVELOPMENT.md` 与
    `README.md`；本脚本的第 8 类只读 `docs/DEVELOPMENT-SPEC.md`。于是
    `docs/INDEX.md:45/155` 与 `docs/SYSTEM-INTRO.md:804` 三处写着旧值也没有任何判据会红
    （2026-11-23 DOC-COUNT-48 实测残量）。这一类的覆盖面按文件补齐，并按形态补齐：
    `46 条目` 这种无「条」字的写法前五条带单位的正则一条都接不住，单列三条接住它。

    判定口径与其它类一致：逐处现算、三态；一个文件里一处声明都读不到 ⇒ 报失去对象
    （删掉这些数不等于它们是对的）。
    """
    total_hits = 0
    for rel, label in _MANIFEST_SPREAD_FILES:
        text = _read(ctx.docs_root / rel)
        if text is None:
            items.append(Item(f"spread:{rel}", f"{label}（文档不在）", rel, None, None,
                              "missing", f"读不到 {rel}"))
            continue
        file_hits = 0
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(mark in line for mark in HISTORICAL_MARKERS):
                continue
            spans = _quote_spans(line)
            for key, unit, read_rx in _MANIFEST_SPREAD_RES:
                for found in read_rx.finditer(line):
                    if _in_quote(found.start(1), spans):
                        continue
                    file_hits += 1
                    total_hits += 1
                    doc_value = int(found.group(1))
                    now_value = ctx.readings.get(key)
                    status = _status(doc_value, now_value)
                    detail = "" if status == "ok" else f"{unit} 形态；现算是 {now_value}"
                    items.append(Item(
                        f"spread:{rel}:{lineno}:{unit}",
                        f"{label} 行{lineno} {unit}", rel,
                        doc_value, now_value, status, detail,
                        _manifest_spread_writer(lineno, read_rx, doc_value)))
        if not file_hits:
            items.append(Item(f"spread:{rel}:lost-object", f"{label} 的清单计数（失去对象）",
                              rel, None, None, "missing", f"{rel} 里{_SPREAD_LOST_OBJECT}"))
    if not total_hits:
        items.append(Item("spread:lost-object", "四份当前值文档的清单计数", "",
                          None, None, "missing",
                          f"四份覆盖文件里{_SPREAD_LOST_OBJECT}"))


def _tally_writer(anchor: str, index: int, lane: str) -> Callable[[str, object], str]:
    """按整行锚点 + 该行第 `index` 处三元组 + 栏位，换掉那一栏的数字。"""
    group = 2 if lane == "warning" else 3

    def apply(text: str, value: object) -> str:
        """锚点行必须唯一；该行第 `index` 处三元组必须还在。"""
        lines = text.splitlines(keepends=True)
        same = [i for i, line in enumerate(lines) if line.rstrip("\r\n") == anchor]
        if len(same) != 1:
            return text
        line = lines[same[0]]
        matches = list(_TALLY_RE.finditer(line))
        if len(matches) < index:
            return text
        hit = matches[index - 1]
        lines[same[0]] = line[:hit.start(group)] + str(value) + line[hit.end(group):]
        return "".join(lines)

    return apply


def build_tally_items(ctx: Context, items: list[Item]) -> None:
    """第 9 类：spec 全文的 linter 读数三元组（`error A / warning B / info C`）。

    口径与权威判据 `tests/test_release_all.py::tally_claim_problems()` 对齐：

    * 扫整份 `docs/DEVELOPMENT-SPEC.md`，不是只扫 `LIVE-READINGS` 块；
    * 带 `HISTORICAL_MARKERS` 的行整行跳过（S1/S2 的当次读数要能留痕）；
    * 逐处三元组的 `warning` / `info` 两栏各对一次；`error` 栏刻意不比 ——
      那一栏由发布门按“必须为 0”强制，并行施工期最先变，钉它只会造假红；
    * 一处三元组都读不到 ⇒ 报“判据失去对象”（`missing`），不折成“一致”。

    为什么要有这一类（`P0`）：只扫 `LIVE-READINGS` 块时，块外散文里的三元组
    （如 `docs/DEVELOPMENT-SPEC.md:69`）永远不参与对账 —— 工具对这一类没有对象，
    而权威判据仍会说“这一行说 `warning 22`，当次是 24”。这是覆盖面缺口，不是数字写错。
    """
    text = _read(ctx.docs_root / SPEC_REL)
    if text is None:
        items.append(Item("tally:lost-object", "linter 三元组（文档不在）", SPEC_REL,
                          None, None, "missing", f"读不到 {SPEC_REL}"))
        return
    hits = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if any(mark in line for mark in HISTORICAL_MARKERS):
            continue
        for index, (_err, warn, info) in enumerate(_TALLY_RE.findall(line), 1):
            hits += 1
            for lane, doc_value in (("warning", int(warn)), ("info", int(info))):
                now_value = ctx.readings.get(f"lint_rules_{lane}")
                status = _status(doc_value, now_value)
                detail = ""
                if status != "ok":
                    detail = f"三元组里写 {lane} {doc_value}；{line.strip()[:80]}"
                items.append(Item(
                    f"tally:lint_rules_{lane}:{lineno}:{index}",
                    f"spec 行{lineno} 三元组 {lane}", SPEC_REL,
                    doc_value, now_value, status, detail,
                    _tally_writer(line, index, lane)))
    if not hits:
        items.append(Item("tally:lost-object", "spec 全文的 linter 三元组", SPEC_REL,
                          None, None, "missing",
                          "一处 linter 读数三元组都读不到 ⇒ 判据失去对象"))


# ---------------------------------------------------------------- 汇总 / 写回

def evaluate(root: Path, docs_root: Path, readings: dict[str, int],
             unmeasured: dict[str, str]) -> tuple[int, list[Item], dict]:
    """把十类对账项汇总，给出 `(退出码, 逐项, 计数)`。"""
    ctx = Context(root=root, docs_root=docs_root, readings=readings, unmeasured=unmeasured)
    items: list[Item] = []
    build_live_items(ctx, items)
    build_prose_items(ctx, items)
    build_static_items(ctx, items)
    build_headline_items(ctx, items)
    build_sec3_items(ctx, items)
    build_index_items(ctx, items)
    build_scripts_readme_items(ctx, items)
    build_manifest_items(ctx, items)
    build_manifest_spread_items(ctx, items)
    build_tally_items(ctx, items)
    counts = {"total": len(items),
              "ok": sum(1 for item in items if item.status == "ok"),
              "stale": sum(1 for item in items if item.status == "stale"),
              "missing": sum(1 for item in items if item.status == "missing")}
    if counts["missing"]:
        code = EXIT_UNKNOWN
    elif counts["stale"]:
        code = EXIT_STALE
    else:
        code = EXIT_OK
    return code, items, counts


def _backup_dir(root: Path, override: str | None) -> Path:
    """备份目录：缺省放 `temp/docnumbers/backups/`（不污染 docs/）。"""
    return Path(override).resolve() if override else root / "temp" / "docnumbers" / "backups"


def apply_writes(items: list[Item], docs_root: Path, backup_dir: Path) -> list[str]:
    """把过期项写回文档副本/正文；每份文档改前先备份。返回写回日志。"""
    notes: list[str] = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    groups: dict[str, list[Item]] = {}
    for item in items:
        if item.status == "stale":
            groups.setdefault(item.doc, []).append(item)
    for rel, group in groups.items():
        path = docs_root / rel
        text = _read(path)
        if text is None:
            notes.append(f"[skip] {rel} 读不到，没写")
            continue
        original = text
        for item in group:
            if item.write is None:
                notes.append(f"[manual] {rel}:{item.key} 没有自动写回，请手改")
                continue
            if item.now_value is None:
                notes.append(f"[skip] {rel}:{item.key} 现算值为空，不猜着写")
                continue
            try:
                new_text = item.write(text, item.now_value)
            except (OSError, ValueError, re.error) as exc:
                notes.append(f"[error] {rel}:{item.key} 写回抛错：{type(exc).__name__}: {exc}")
                continue
            if new_text == text:
                notes.append(f"[miss] {rel}:{item.key} 写回没命中锚点（锚点可能变了）")
                continue
            text = new_text
            notes.append(f"[write] {rel}:{item.key} {item.doc_value} -> {item.now_value}")
        if text == original:
            continue
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{rel.replace('/', '__')}.{stamp}.bak"
        try:
            shutil.copy2(path, backup)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
        except OSError as exc:
            notes.append(f"[error] {rel} 备份/写盘失败：{type(exc).__name__}: {exc}")
            continue
        notes.append(f"[backup] {backup}")
    return notes


def _width(text: str) -> int:
    """显示宽度（中日韩全角算 2；表格对齐用）。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    """按显示宽度右补空格。"""
    return text + " " * max(width - _width(text), 0)


def render(counts: dict, items: list[Item], notes: list[str]) -> str:
    """人读版：一张“项目 / 文档值 / 现算值 / 判定”表 + 结论。"""
    label_width = min(max((_width(f"{item.doc}: {item.label}") for item in items), default=20), 68)
    lines = [f"{_pad('项目', label_width)} | {'文档值':>10} | {'现算值':>10} | 判定",
             "-" * label_width + "-+-" + "-" * 10 + "-+-" + "-" * 10 + "-+------"]
    state_text = {"ok": "一致", "stale": "过期", "missing": "文档缺项"}
    for item in items:
        name = f"{item.doc}: {item.label}"
        doc_value = "-" if item.doc_value is None else str(item.doc_value)
        now_value = "-" if item.now_value is None else str(item.now_value)
        lines.append(f"{_pad(name, label_width)} | {doc_value:>10} | {now_value:>10} | "
                     f"{state_text[item.status]}")
        if item.detail and item.status != "ok":
            lines.append(f"{'':<{label_width}}   ↳ {item.detail}")
    lines.append("")
    if notes:
        lines.append("写回日志：")
        lines.extend("  " + note for note in notes)
        lines.append("")
    lines.append(f"计数：共 {counts['total']} 项 · 一致 {counts['ok']} · 过期 {counts['stale']} · "
                 f"文档缺项 {counts['missing']}")
    if counts["missing"]:
        lines.append("结论：没查成（2）—— 有项读不到/没量到，2 不是“一致”")
    elif counts["stale"]:
        lines.append(f"结论：有过期（1）—— {counts['stale']} 项与现算不一致"
                     "（加 --write 写回，或按表手改）")
    else:
        lines.append("结论：全一致（0）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 自测

def _write_lf(path: Path, text: str) -> None:
    """按 UTF-8 + LF 写文本（夹具文件不依赖平台换行）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def _pad_to(path: Path, text: str, size: int) -> None:
    """把 ASCII 文本补空格到恰好 `size` 字节（静态产物字节数要能被文档声明）。"""
    raw = text.encode("utf-8")
    if len(raw) > size:
        raise MeasureError(f"夹具文本已超过 {size} 字节：{path}")
    _write_lf(path, text + " " * (size - len(raw)))


def _fixture_spec(readings: dict[str, int], collected: int) -> str:
    """造一份带 LIVE-READINGS / §2 第八层 / §1.5 计数的夹具 spec。"""
    block = "\n".join(f"{key} = {value}" for key, value in readings.items())
    run = " ".join(str(readings[key]) for key in _WEBUI_RUN_KEYS)
    return f"""# 夹具 spec

LIVE-READINGS:BEGIN
{block}
LIVE-READINGS:END

**⑧ Web / 用户端**

`src/agentflow/webui/` —— **{readings['webui_modules']} 个模块**

`ROUTES`：**{readings['webui_routes']} 条**（GET **{readings['webui_routes_get']}** / POST **{readings['webui_routes_post']}**）

⇒ `{run}`

判据文件共 **{readings['webui_test_files']}** 个（`test_webui*.py`）

静态产物：`static/index.html`（100 B）+ `static/assets/index.abc.js`（70 B）+ `static/assets/index.def.css`（30 B）

**linter 的当次三栏（日常档）**：`error 0 / warning {readings['lint_rules_warning']} / info {readings['lint_rules_info']}`

---

## 夹具 §1.5

| **清单 glob 数** | 条目行 | **{readings['noai_paths_glob']}** |
| **唯一路径数** | 去重 | **{readings['noai_paths_unique']}** |
| **禁改区类别数** | 分组 | **{readings['noai_paths_categories']}** |

当次 **{readings['noai_paths_glob']}** 条条目 / **{readings['noai_paths_unique']}** 条唯一路径 / {readings['noai_paths_categories']} 个分组。

`tests/test_noai_gate.py` 当次 {collected} passed。
"""


def _fixture_map(files: int, total: int, big: int, loop: int) -> str:
    """造一份带开头三格与 §3 行数表的夹具 READING-MAP。"""
    return f"""# 夹具 map

> **{files} 个 `.py`、{total:,} 行**，**{big} 个文件超过 800 行**（**全仓最大的是 `agent_loop.py`，{loop:,} 行**）。

---

## §3 这些文件为什么这么大

| 文件 | 行数 | 边界 |
|---|---:|---|
| `agent_loop.py` | {loop} | 夹具 |
"""


def _fixture_readme(readings: dict[str, int]) -> str:
    """造一份带清单计数的根 README 夹具（加粗 + `条 glob` 形态）。"""
    return f"""# 夹具 README

agentflow/.noai-paths 禁改区清单（**{readings['noai_paths_glob']}** 条 glob / \
**{readings['noai_paths_unique']}** 条唯一路径，**{readings['noai_paths_categories']}** 个分组）。
"""


def _fixture_system_intro(readings: dict[str, int]) -> str:
    """造一份带无「条」字变体的 SYSTEM-INTRO 夹具（`46 条目 / 43 唯一路径` 形态）。"""
    return f"""# 夹具简介

| 读数 | 值 |
|---|---|
| `.noai-paths` | {readings['noai_paths_glob']} 条目 / \
{readings['noai_paths_unique']} 唯一路径 / {readings['noai_paths_categories']} 分组 |
"""


def _fixture_index(readings: dict[str, int]) -> str:
    """造一份带当次清单计数的 INDEX 夹具（`**N** 条条目 / **N** 条唯一路径` 形态）。"""
    return f"""# 夹具索引

现盘 **{readings['noai_paths_glob']}** 条条目 / \
**{readings['noai_paths_unique']}** 条唯一路径。

`MIN_DOCS = 1`
"""


def _build_fixture(repo: Path, readings: dict[str, int], collected: int) -> Path:
    """造一棵最小产品根：`repo/agentflow/` 是产品根，`repo/` 放 docs 与根 README。

    这与真仓库同形（`--root` = `agentflow/`，根 `README.md` 在它上一级），
    第 10 类的 `../README.md` 覆盖才测得出来。
    """
    root = repo / "agentflow"
    loop_body = "\n".join(f"x{i} = {i}" for i in range(1, 121))
    _write_lf(root / "src" / "agentflow" / "agent_loop.py", loop_body + "\n")
    _pad_to(root / "src" / "agentflow" / "web" / "static" / "index.html",
            '<script src="./assets/index.abc.js"></script>\n'
            '<link rel="stylesheet" href="./assets/index.def.css">\n', 100)
    _pad_to(root / "src" / "agentflow" / "web" / "static" / "assets" / "index.abc.js",
            "// fixture js\n", 70)
    _pad_to(root / "src" / "agentflow" / "web" / "static" / "assets" / "index.def.css",
            "/* fixture css */\n", 30)
    _write_lf(root / "tests" / "test_webui_one.py", "# fixture\n")
    _write_lf(root / "tests" / "test_noai_gate.py", "# fixture\n")
    _write_lf(root / "tests" / "test_docs_index_covers_every_doc.py", "MIN_DOCS = 1\n")
    _write_lf(root / "docs" / "DEVELOPMENT-SPEC.md", _fixture_spec(readings, collected))
    _write_lf(root / "docs" / "READING-MAP.md", _fixture_map(1, 120, 0, 120))
    _write_lf(root / "docs" / "INDEX.md", _fixture_index(readings))
    _write_lf(root / "docs" / "SYSTEM-INTRO.md", _fixture_system_intro(readings))
    _write_lf(repo / "README.md", _fixture_readme(readings))
    _write_lf(root / "scripts" / "tool_a.py", '"""夹具工具。"""\n')
    _write_lf(root / "scripts" / "README.md", "# scripts\n\n| 用途 | 脚本 |\n|---|---|\n| 门禁 | `tool_a.py` |\n")
    return root


def selftest() -> int:
    """三态自测：全一致 / 有过期 / 文档缺项（每例一棵全新夹具树）。"""
    readings = {key: 10 + index for index, key in enumerate(LIVE_KEYS)}
    collected = readings["noai_gate_pytest_collected"]
    rows: list[tuple[str, str, int, int, str]] = []
    with tempfile.TemporaryDirectory(prefix="docnum-selftest-") as tmp:
        base = Path(tmp)
        green = _build_fixture(base / "green" / "agentflow", readings, collected)
        code, _items, _counts = evaluate(green, green, readings, {})
        rows.append(("一致", "全部数字与现算相同", EXIT_OK, code, ""))

        stale = _build_fixture(base / "stale" / "agentflow", readings, collected)
        spec = stale / SPEC_REL
        bad = int(readings["webui_test_files"]) + 7
        _write_lf(spec, _read(spec).replace(
            f"webui_test_files = {readings['webui_test_files']}",
            f"webui_test_files = {bad}", 1))
        code, _items, _counts = evaluate(stale, stale, readings, {})
        rows.append(("过期", f"webui_test_files 写 {bad}（现算 {readings['webui_test_files']}）",
                     EXIT_STALE, code, ""))

        missing = _build_fixture(base / "missing" / "agentflow", readings, collected)
        spec = missing / SPEC_REL
        text = _read(spec)
        text = text.replace(f"判据文件共 **{readings['webui_test_files']}** 个", "判据文件在这里", 1)
        _write_lf(spec, text)
        code, _items, _counts = evaluate(missing, missing, readings, {})
        rows.append(("文档缺项", "第八层“判据文件共 N 个”锚点被删掉", EXIT_UNKNOWN, code, ""))

    print("自测（夹具是 tempfile 里的最小产品根；三态用同一套 build/evaluate 跑）")
    bad_count = 0
    for kind, detail, want, got, _note in rows:
        flag = "OK  " if want == got else "BAD "
        if want != got:
            bad_count += 1
        print(f"  [{flag}] {kind:4s} 期望 exit={want} 实际 exit={got}  （{detail}）")
    print(f"自测结论：{len(rows) - bad_count}/{len(rows)} 条符合期望")
    return EXIT_OK if not bad_count else EXIT_UNKNOWN


# ---------------------------------------------------------------- 入口

def main(argv: list[str] | None = None) -> int:
    """解析参数、跑对账、按三态返回退出码。"""
    _pin_utf8()
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=("文档数字 vs 现算的一站式自检：0 全一致 / 1 有过期 / 2 没查成"
                     "（文档缺 / 目录缺）"),
        allow_abbrev=False,
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="产品根（缺省 = 本脚本的上一级，即 agentflow/）")
    parser.add_argument("--docs", default=None,
                        help="文档根（含 docs/ 与 scripts/README.md；缺省 = --root；"
                             "测量始终用 --root）")
    parser.add_argument("--json", action="store_true", help="输出机器读数")
    parser.add_argument("--write", action="store_true",
                        help="把过期项按现算值写回文档（每份文档改前先备份）")
    parser.add_argument("--backup-dir", default=None,
                        help="备份目录（缺省 = <root>/temp/docnumbers/backups/）")
    parser.add_argument("--timeout", type=int, default=900,
                        help="每个子进程的超时秒数（缺省 900；超时按没查成）")
    parser.add_argument("--selftest", action="store_true",
                        help="用 tempfile 造夹具验三态（一致 / 过期 / 文档缺项）")
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    root = Path(args.root).resolve()
    docs_root = Path(args.docs).resolve() if args.docs else root
    if not root.is_dir():
        print(f"[unknown] 产品根不存在：{root} ⇒ 没查成", file=sys.stderr)
        return EXIT_UNKNOWN
    if not docs_root.is_dir():
        print(f"[unknown] 文档根不存在：{docs_root} ⇒ 没查成", file=sys.stderr)
        return EXIT_UNKNOWN

    started = time.time()
    readings, unmeasured = measure(root, max(int(args.timeout), 1))
    code, items, counts = evaluate(root, docs_root, readings, unmeasured)
    before = dict(counts)
    notes: list[str] = []
    if args.write and code != EXIT_OK:
        notes = apply_writes(items, docs_root, _backup_dir(root, args.backup_dir))
        code, items, counts = evaluate(root, docs_root, readings, unmeasured)

    if args.json:
        payload = {
            "script": PROG,
            "root": str(root),
            "docs_root": str(docs_root),
            "state": {0: "ok", 1: "stale", 2: "unknown"}[code],
            "exit_code": code,
            "counts": counts,
            "counts_before_write": before,
            "elapsed_sec": round(time.time() - started, 2),
            "unmeasured": unmeasured,
            "readings": readings,
            "wrote": notes,
            "items": [item.to_json() for item in items],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(counts, items, notes))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
