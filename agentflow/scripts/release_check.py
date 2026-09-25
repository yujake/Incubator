"""发布前的一键检查（`python scripts/release_check.py`）。

## ⚠️ 本文件落在**禁 AI 区**里

`.noai-paths` 的 `[category: release-deploy]` 登记了 `scripts/release_check.py`。
按 FC-27，**改这个文件需要「人编写或人逐行走查 + 2 名 reviewer 批准」**。

本文件当前的作者状态必须如实登记：

    authored_by: AI agent（本框架的构建者），**尚未经人逐行走查**
    required_approvals: 2（尚未取得）

也就是说：**这个门现在是"未批准"状态**，它跑出来的绿灯**不构成发布许可**。
把这句话写进 docstring 而不是写进某个聊天记录里，是因为它是这个文件**最重要的属性** ——
一个"看起来在把关、其实自己还没被审过"的发布脚本，正是 FC-27 说的那种
"测试全绿、上线即越权"的形态。

## 它做什么

按固定顺序跑**八项**，每项给**三档**结论（`pass` / `fail` / `unknown`），
最后给一个总判定与**退出码**：

    0 = 全部 pass
    1 = 有 fail
    2 = 有 unknown（**没跑成 ≠ 通过**），或检查器自身出错

⭐ **`unknown` 与 `fail` 分开，且都不等于 `pass`。** 这是三态纪律在发布门上的落地：
"pytest 因为收集错误没跑起来"既不是"测试通过"，也不是"测试失败"，
把它算成任何一档都会掩盖真相。

## 八项

| # | 项 | 判据 | 为什么它在发布门里 |
|---|---|---|---|
| 1 | 全量测试 | `pytest -q` 退出码 0，且 **0 failed** | 最基础的一层；但它单独**不构成**发布许可（见下） |
| 2 | 模块自检 | 8 个 agent + pipeline 自检全部退出码 0 | 自检覆盖的是"端到端能不能跑通"，而单测覆盖的是"判据对不对" —— 两者不重叠 |
| 3 | 工具普查 | 工具数与角色工具数**可复现**；只读角色（C/H）的写工具泄漏 **= 0** | 权限面是设计的一部分，且它**默认是隐式的** —— 只有普查才让它成为事实 |
| 4 | 全库校验 | `verify_all` 的 **error = 0** | 跨表不变量（悬空引用、依赖闭合、三态一致性）只有它查 |
| 5 | linter | `scripts/lint_rules.py` 的 **error = 0** | 形态类规则（第二份名单、静默失败、脚本无退出码） |
| 6 | 禁 AI 区门 | `scripts/noai_gate.py --check-consistency` 一致，且**本次改动集**判定明确 | FC-27；`unknown` 必须显式暴露 |
| 7 | 契约版本 | `agentflow.CONTRACT_VERSION` 与 `interactions.CONTRACT_VERSION` 一致，且 `schema.SCHEMA_VERSION` 与 `__schema_version__` 一致 | "两份契约各按各的理解跑"是**没有任何报错**的分裂 |
| 8 | 源码树可导入 | 每个模块都能被单独 import（**循环依赖**会在这里炸） | `python -m agentflow.X` 是接口的一部分 |

## 为什么"测试全绿"进不了这一项

第 1 项全绿**不能**推出可以发布，理由是本项目自己的一手教训：
9 条已交付缺陷里 **0 条**能被 happy-path 抓到（`10-…md` §10.10 结论①）。
所以发布门不只看"测试过没过"，还看**门本身有没有被校准过**（第 3/4/5/6 项）
与**契约版本有没有对齐**（第 7 项）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# ------------------------------------------------------------------ 常量

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"

#: 三档结论。**`unknown` 必须与 `fail` 分开** —— 见模块 docstring。
VERDICTS = ("pass", "fail", "unknown")

#: 需要跑自检的模块（`python -m agentflow.<x>`，在 `src/` 下跑）。
SELFTEST_MODULES = (
    "agent_a", "agent_b", "agent_c", "agent_d",
    "agent_e", "agent_f", "agent_g", "agent_h", "pipeline",
)

#: 每个角色**期望**的工具数下界。写成下界而不是等值：
#: 新增工具是正常的演进，而**静默少工具**才是要抓的（所以下界 + 泄漏必须为 0）。
#: ⚠️ 这些数字是**观测值**（`cli tools`/普查脚本），不是设计目标 ——
#: 把它们写在这里的价值是"变化时必须有人看一眼"，而不是"必须恰好这么多"。
ROLE_TOOL_FLOOR: dict[str, int] = {"A": 18, "B": 16, "C": 15, "D": 30, "E": 18, "F": 28, "G": 28, "H": 20}

READ_ONLY_ROLES = ("C", "H")


@dataclass
class Item:
    key: str
    title: str
    verdict: str = "unknown"
    detail: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"key": self.key, "title": self.title, "verdict": self.verdict,
                "detail": self.detail, "notes": self.notes}


@dataclass
class Report:
    items: list[Item] = field(default_factory=list)

    def add(self, item: Item) -> Item:
        self.items.append(item)
        return item

    def counts(self) -> dict[str, int]:
        return {v: sum(1 for i in self.items if i.verdict == v) for v in VERDICTS}

    def overall(self) -> str:
        c = self.counts()
        if c["fail"]:
            return "fail"
        if c["unknown"]:
            return "unknown"
        return "pass"

    def to_dict(self) -> dict:
        return {
            "overall": self.overall(),
            "counts": self.counts(),
            "items": [i.to_dict() for i in self.items],
            "authored_by": "AI agent（尚未经人逐行走查；本文件在禁 AI 区内）",
            "note": (
                "overall=pass 只表示**这八项检查都通过了**，不构成发布许可："
                "本脚本自身位于禁 AI 区（`.noai-paths` 的 release-deploy 类），"
                "按 FC-27 仍需人逐行走查 + 2 名 reviewer 批准"
            ),
        }


def _ensure_utf8_console() -> None:
    """把本进程的 stdout/stderr 显式钉在 UTF-8 上（输出不依赖调用方的 locale）。

    为什么发布门必须自己管这件事：本脚本会打印中文与 `⚠` 这类符号，而
    cp936(GBK) 控制台下 Python 的默认编码会让 `print` 直接抛 `UnicodeEncodeError`
    —— 那不是"发现了问题"的退出码 1，而是**发布门自己没跑成**，而"没跑成"
    与"通过"在调用方眼里极易混淆（三态纪律）。口径与编排层 `tools/release_all.py`
    上一轮采用的写法相同：`reconfigure(encoding="utf-8", errors="replace")`。
    """
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            # 被重定向或被测试替换过的流可能没有 reconfigure（或已关闭）。
            # 此时不能因此崩掉发布门：这一句是**加固**，不是判据本身。
            pass


def _run(cmd: Sequence[str], *, cwd: Path, timeout: float = 1800.0, env_extra: dict | None = None) -> dict:
    """跑一个子进程，三态返回。

    ⚠️ **超时 / 起不来 / 非零退出码是三件不同的事**，这里必须分开报：
    - `started=False` ⇒ 它**根本没跑成**（`unknown`）
    - `timed_out=True` ⇒ 它跑到一半被砍（`unknown`，且**不是** fail —— 我们没有证据说它错）
    - 否则按 `exit_code` 判

    ⚠️ 解码也必须显式 `encoding="utf-8"`：子进程的输出里有中文，默认走
    locale 编码时 `text=True` 会在**读回**那一侧抛 `UnicodeDecodeError`，
    于是一个正常结束的子进程被判成"没跑成"—— 判据没变，错的是读它的方式。

    ⚠️ 同理，子进程的**输出编码**必须被显式覆盖，不能用 `setdefault`。
    实测（cp936 控制台）：父进程被调用方设成 `PYTHONIOENCODING=cp936` 时，
    `setdefault` 会把这一个值原样传给子进程 —— 于是 `lint_rules.py` 在打印
    含 `⇒` 的行时自己抛 `UnicodeEncodeError` 并以退出码 1 结束。而本脚本第 5 项
    把退出码 1 读成"linter 发现问题"，于是一次**投递问题**被报成"代码有问题"，
    方向完全反了。覆盖成 utf-8 之后，子进程打印什么都不会因此崩。
    """
    env = dict(os.environ)
    # 覆盖而不是补默认值：理由见上面那一段（这与 `tools/release_all.py` 里
    # `{**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", **extra}` 同一写法）。
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if env_extra:
        env.update(env_extra)
    try:
        p = subprocess.run(list(cmd), cwd=str(cwd), capture_output=True, text=True,
                           timeout=timeout, env=env, errors="replace", encoding="utf-8")
    except subprocess.TimeoutExpired as e:
        return {"started": True, "timed_out": True, "exit_code": None,
                "stdout": (e.stdout or ""), "stderr": (e.stderr or ""),
                "cmd": " ".join(cmd)}
    except OSError as e:
        return {"started": False, "timed_out": False, "exit_code": None,
                "stdout": "", "stderr": f"{type(e).__name__}: {e}", "cmd": " ".join(cmd)}
    return {"started": True, "timed_out": False, "exit_code": p.returncode,
            "stdout": p.stdout, "stderr": p.stderr, "cmd": " ".join(cmd)}


def _tail(text: str, n: int = 12) -> list[str]:
    lines = [x for x in (text or "").splitlines() if x.strip()]
    return lines[-n:]


# ------------------------------------------------------------------ 八项检查


def item_test_suite(rep: Report) -> Item:
    it = rep.add(Item("tests", "全量测试（pytest -q）"))
    r = _run([sys.executable, "-m", "pytest", "-q"], cwd=REPO_ROOT)
    if not r["started"]:
        it.verdict = "unknown"
        it.notes.append(f"**根本没跑起来**：{r['stderr'][:200]}")
        return it
    if r["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("超时被砍 —— **没有证据说它错**，所以是 unknown 而不是 fail")
        return it
    out = r["stdout"] + r["stderr"]
    it.detail = {"exit_code": r["exit_code"], "tail": _tail(out)}
    # 解析 "N passed, M failed, K deselected" 这类摘要。
    import re

    passed = re.search(r"(\d+) passed", out)
    failed = re.search(r"(\d+) failed", out)
    errors = re.search(r"(\d+) error", out)
    it.detail["passed"] = int(passed.group(1)) if passed else None
    it.detail["failed"] = int(failed.group(1)) if failed else 0
    it.detail["errors"] = int(errors.group(1)) if errors else 0
    if it.detail["passed"] is None:
        it.verdict = "unknown"
        it.notes.append("**解析不出 passed 计数** ⇒ 可能没跑到收集完成（收集错误）⇒ unknown，不是 pass")
        return it
    if r["exit_code"] != 0 or it.detail["failed"] or it.detail["errors"]:
        it.verdict = "fail"
    else:
        it.verdict = "pass"
    it.notes.append("⚠️ 这一项全绿**不构成**发布许可：9 条已交付缺陷里 0 条能被 happy-path 抓到")
    return it


def item_selftests(rep: Report) -> Item:
    it = rep.add(Item("selftests", "模块自检（8 个 agent + pipeline）"))
    results: dict[str, dict] = {}
    for mod in SELFTEST_MODULES:
        src = SRC / "agentflow" / f"{mod}.py"
        text = src.read_text(encoding="utf-8") if src.exists() else ""
        # ⚠️ **"没有自检块"不是"自检通过"**（三态纪律）。
        # 实测（`DEVELOPMENT.md` §10 的 D5）：`agent_a` / `agent_b` **没有** `__main__` 块，
        # 于是 `python -m agentflow.agent_a` 退出码 0 且输出 0 行 —— 旧判据会把它记成 PASS，
        # 而它其实**什么都没检查**。这正是本项目最忌讳的"把没做读成通过"。
        # 现在：没有自检块 ⇒ `unknown`，并把这件事**报出来**（它是待补的缺口，不是通过）。
        has_selftest = "__main__" in text
        r = _run([sys.executable, "-m", f"agentflow.{mod}"], cwd=SRC, timeout=900.0)
        entry = {"started": r["started"], "timed_out": r["timed_out"],
                 "exit_code": r["exit_code"], "has_selftest": has_selftest,
                 "tail": _tail(r["stdout"] + r["stderr"], 3)}
        if not has_selftest:
            entry["verdict"] = "unknown"
            entry["why"] = "该模块没有自检块（`__main__`）⇒ **没自检**，不是'自检通过'"
        elif not r["started"] or r["timed_out"]:
            entry["verdict"] = "unknown"
        elif r["exit_code"] != 0:
            entry["verdict"] = "fail"
        else:
            entry["verdict"] = "pass"
        results[mod] = entry
    it.detail = results
    bad = [m for m, v in results.items() if v["verdict"] == "fail"]
    unknown = [m for m, v in results.items() if v["verdict"] == "unknown"]
    if bad:
        it.verdict = "fail"
        it.notes.append(f"这些自检**没通过**：{bad}")
    elif unknown:
        it.verdict = "unknown"
        it.notes.append(
            f"这些模块**没有自检块**（不是'通过'）：{unknown} ⇒ "
            "要么给它们补一个 `__main__` 自检，要么在 `SELFTEST_MODULES` 里说明为什么不需要"
        )
    else:
        it.verdict = "pass"
    return it


def item_tool_census(rep: Report) -> Item:
    it = rep.add(Item("tools", "工具普查（数量可复现 + 只读角色 0 泄漏）"))
    code = (
        "import json, tempfile, pathlib\n"
        "from agentflow.tools import build_registry, ROLES, READ_ONLY_ROLES, SIDE_EFFECTS_WRITE\n"
        "from agentflow.store import Store\n"
        "d = pathlib.Path(tempfile.mkdtemp()); s = Store(d); s.init()\n"
        "b = build_registry(store=s, workspace_root=d, strict=True)\n"
        "by_role = {r: len(b.registry.for_role(r)) for r in ROLES}\n"
        "leaks = {r: [x.name for x in b.registry.for_role(r) if x.side_effect in SIDE_EFFECTS_WRITE]\n"
        "         for r in READ_ONLY_ROLES}\n"
        "se = {}\n"
        "for x in b.registry._specs.values(): se[x.side_effect] = se.get(x.side_effect, 0) + 1\n"
        "print(json.dumps({'total': len(b.registry), 'by_role': by_role, 'leaks': leaks,\n"
        "                  'side_effects': se, 'skipped': b.skipped,\n"
        "                  'role_filter_notes': b.registry.role_filter_notes}, ensure_ascii=False))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=300.0)
    if not r["started"] or r["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("普查脚本没跑成")
        return it
    if r["exit_code"] != 0:
        it.verdict = "fail"
        it.detail = {"stderr": _tail(r["stderr"], 6)}
        return it
    try:
        data = json.loads(r["stdout"].strip().splitlines()[-1])
    except (ValueError, IndexError) as e:
        it.verdict = "unknown"
        it.notes.append(f"普查输出解析失败：{e}")
        return it
    it.detail = data
    problems: list[str] = []
    if data["skipped"]:
        problems.append(f"有模块被跳过：{data['skipped']}")
    for role, leaks in data["leaks"].items():
        if leaks:
            problems.append(f"**只读角色 {role} 有写工具泄漏**：{leaks}")
    for role, floor in ROLE_TOOL_FLOOR.items():
        got = data["by_role"].get(role, 0)
        if got < floor:
            problems.append(f"角色 {role} 只有 {got} 个工具（下界 {floor}）⇒ 可能有工具静默没装上")
    if data["role_filter_notes"]:
        problems.append(f"有工具的 roles 声明把写工具给了只读角色（行为已被拦下，但声明要改）：{data['role_filter_notes']}")
    it.verdict = "pass" if not problems else "fail"
    it.notes.extend(problems)
    return it


def item_verify(rep: Report) -> Item:
    it = rep.add(Item("verify", "全库校验（verify_all error = 0）"))
    code = (
        "import json, tempfile, pathlib\n"
        "from agentflow.verify import verify_all\n"
        "from agentflow.store import Store\n"
        "d = pathlib.Path(tempfile.mkdtemp()); s = Store(d); s.init()\n"
        "r = verify_all(s).to_dict()\n"
        "print(json.dumps({'error_count': r['error_count'], 'warning_count': r['warning_count'],\n"
        "                  'errors': [i['code'] for i in r['errors']], 'checked': r['checked']},\n"
        "                 ensure_ascii=False))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=300.0)
    if not r["started"] or r["timed_out"] or r["exit_code"] != 0:
        it.verdict = "unknown"
        it.notes.append(f"**校验器自身没跑成**（不是'库有问题'）：{_tail(r['stderr'], 4)}")
        return it
    data = json.loads(r["stdout"].strip().splitlines()[-1])
    it.detail = data
    it.verdict = "pass" if data["error_count"] == 0 else "fail"
    it.notes.append(
        "注意：这里查的是**空库**。空库 0 error 只说明'校验器能跑'，"
        "不说明真实库干净 —— 真实库的校验在验收测试里（`test/test2/run_acceptance.py` 的 P8）"
    )
    return it


def item_linter(rep: Report) -> Item:
    it = rep.add(Item("lint", "linter（error = 0）"))
    r = _run([sys.executable, str(REPO_ROOT / "scripts" / "lint_rules.py"), "--json",
              str(REPO_ROOT / ".release-lint.json")], cwd=REPO_ROOT, timeout=600.0)
    if not r["started"] or r["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("linter 没跑成")
        return it
    # 退出码 0/1 都是"跑成了"；2 是 linter 自身失败
    if r["exit_code"] == 2:
        it.verdict = "unknown"
        it.notes.append("linter 自身失败（退出码 2）——**这是检查器的问题，不是被检对象的**")
        return it
    it.detail = {"exit_code": r["exit_code"], "tail": _tail(r["stdout"] + r["stderr"], 6)}
    it.verdict = "pass" if r["exit_code"] == 0 else "fail"
    return it


def item_noai(rep: Report, changed: Sequence[str]) -> Item:
    it = rep.add(Item("noai", "禁 AI 区门（清单一致 + 改动集判定）"))
    gate = REPO_ROOT / "scripts" / "noai_gate.py"
    if not gate.exists():
        it.verdict = "unknown"
        it.notes.append("`scripts/noai_gate.py` 不存在 ⇒ **门还没接线**（不是'没有禁改区'）")
        return it
    r1 = _run([sys.executable, str(gate), "--check-consistency"], cwd=REPO_ROOT, timeout=120.0)
    if not r1["started"] or r1["timed_out"]:
        it.verdict = "unknown"
        it.notes.append("一致性检查没跑成")
        return it
    it.detail["consistency_exit"] = r1["exit_code"]
    it.notes.extend(_tail(r1["stdout"] + r1["stderr"], 4))
    if r1["exit_code"] != 0:
        it.verdict = "fail"
        it.notes.append("`.noai-paths` 与 `AGENTS.md` 的清单**不一致** ⇒ 两处会按不同清单行事")
        return it
    if not changed:
        it.verdict = "unknown"
        it.notes.append(
            "没给改动集（`--changed`）⇒ **没查成**。三态纪律：`unknown` 绝不是 `clean`。"
            "用法：`python scripts/release_check.py --changed src/agentflow/dedup.py`"
        )
        return it
    r2 = _run([sys.executable, str(gate), "--paths", *changed], cwd=REPO_ROOT, timeout=120.0)
    it.detail["gate_exit"] = r2["exit_code"]
    it.notes.extend(_tail(r2["stdout"] + r2["stderr"], 4))
    if r2["exit_code"] == 0:
        it.verdict = "pass"
    elif r2["exit_code"] == 1:
        it.verdict = "fail"
        it.notes.append("命中禁改区 ⇒ 需人编写或人逐行走查 + **2 名 reviewer 批准**（FC-27）")
    else:
        it.verdict = "unknown"
    return it


def item_contract(rep: Report) -> Item:
    it = rep.add(Item("contract", "契约版本与 schema 版本一致"))
    code = (
        "import json, agentflow\n"
        "from agentflow import interactions as I, schema as S\n"
        "print(json.dumps({'pkg_version': agentflow.__version__,\n"
        "                  'schema_version_pkg': agentflow.__schema_version__,\n"
        "                  'schema_version_mod': S.SCHEMA_VERSION,\n"
        "                  'contract_pkg': agentflow.CONTRACT_VERSION,\n"
        "                  'contract_mod': I.CONTRACT_VERSION}))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=120.0)
    if not r["started"] or r["timed_out"] or r["exit_code"] != 0:
        it.verdict = "unknown"
        it.notes.append(f"读版本号失败：{_tail(r['stderr'], 4)}")
        return it
    d = json.loads(r["stdout"].strip().splitlines()[-1])
    it.detail = d
    problems = []
    if d["schema_version_pkg"] != d["schema_version_mod"]:
        problems.append("`__schema_version__` 与 `schema.SCHEMA_VERSION` 不一致")
    if d["contract_pkg"] != d["contract_mod"]:
        problems.append("`CONTRACT_VERSION` 的两处定义不一致")
    it.verdict = "pass" if not problems else "fail"
    it.notes.extend(problems)
    it.notes.append("数据格式版本与函数契约版本是**两件事**，必须能分别升（本项目真的发生过：判据语义变了而格式没变）")
    return it


def item_imports(rep: Report) -> Item:
    it = rep.add(Item("imports", "源码树可导入（无循环依赖）"))
    code = (
        "import importlib, json, pkgutil, agentflow\n"
        "bad = {}\n"
        "mods = [m.name for m in pkgutil.walk_packages(agentflow.__path__, 'agentflow.')]\n"
        "for name in mods:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception as e:\n"
        "        bad[name] = f'{type(e).__name__}: {e}'\n"
        "print(json.dumps({'total': len(mods), 'bad': bad}, ensure_ascii=False))\n"
    )
    r = _run([sys.executable, "-c", code], cwd=SRC, timeout=300.0)
    if not r["started"] or r["timed_out"] or r["exit_code"] != 0:
        it.verdict = "unknown"
        it.notes.append(f"导入普查没跑成：{_tail(r['stderr'], 4)}")
        return it
    d = json.loads(r["stdout"].strip().splitlines()[-1])
    it.detail = d
    it.verdict = "pass" if not d["bad"] else "fail"
    if d["bad"]:
        it.notes.append(f"这些模块导入失败（**循环依赖会在这里炸**）：{sorted(d['bad'])}")
    return it


# ------------------------------------------------------------------ main


def main(argv: Sequence[str] | None = None) -> int:
    # 先把输出编码钉在 UTF-8 上再做任何事：总判定的那几行是本脚本的最终产物，
    # 而它们在 cp936 控制台上会抛 UnicodeEncodeError（见 `_ensure_utf8_console`）。
    _ensure_utf8_console()
    ap = argparse.ArgumentParser(description="agentflow 发布前检查（八项，三档判定）")
    ap.add_argument("--changed", nargs="*", default=[], help="本次改动的文件（给禁 AI 区门用）")
    ap.add_argument("--json", default="", help="把结果写到该 JSON 路径")
    ap.add_argument("--skip", nargs="*", default=[], help="跳过某些项（key），调试用")
    args = ap.parse_args(argv)

    if not (SRC / "agentflow").exists():
        print(f"[release] 读不到源码树 {SRC / 'agentflow'} —— **检查器自身失败**（退出码 2）", file=sys.stderr)
        return 2

    rep = Report()
    runners = (
        ("tests", lambda: item_test_suite(rep)),
        ("selftests", lambda: item_selftests(rep)),
        ("tools", lambda: item_tool_census(rep)),
        ("verify", lambda: item_verify(rep)),
        ("lint", lambda: item_linter(rep)),
        ("noai", lambda: item_noai(rep, args.changed)),
        ("contract", lambda: item_contract(rep)),
        ("imports", lambda: item_imports(rep)),
    )
    for key, fn in runners:
        if key in args.skip:
            continue
        print(f"\n===== [{key}] =====", flush=True)
        try:
            item = fn()
        except Exception as e:  # noqa: BLE001
            item = Item(key, key, "unknown", {}, [f"检查项自身抛异常：{type(e).__name__}: {e}"])
            rep.add(item)
        mark = {"pass": "PASS", "fail": "FAIL", "unknown": "????"}[item.verdict]
        print(f"  [{mark}] {item.title}")
        for n in item.notes:
            print(f"        · {n}")

    d = rep.to_dict()
    if args.json:
        Path(args.json).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    c = rep.counts()
    overall = rep.overall()
    print("\n" + "=" * 72)
    print(f"发布检查总判定：{overall.upper()}    pass={c['pass']} fail={c['fail']} unknown={c['unknown']}")
    print("⚠️ overall=pass 只说明这八项都通过了，**不构成发布许可**：")
    print("   本脚本自身在禁 AI 区（`.noai-paths` 的 release-deploy 类），按 FC-27 仍需人逐行走查 + 2 名 reviewer 批准。")
    if args.json:
        print(f"结果 JSON: {args.json}")

    if overall == "fail":
        return 1
    if overall == "unknown":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
