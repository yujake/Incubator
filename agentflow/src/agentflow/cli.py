"""命令行入口。

设计意图：把"能跑起来的最小操作集"固定成几个动词，避免每次都写一次性脚本 ——
一次性脚本正是这类系统后来无法复现的根源。

    python -m agentflow init / submit / run-a / run-b / status / verify / rebuild / repair / demo
    python -m agentflow start --task "..." --project p3 --mode research --dry-run   # 统一入口
    python -m agentflow run --topic "..." --budget-usd 5 --out DIR   # 端到端一条命令
    python -m agentflow doctor --selfcheck                          # 包内源码自检（不花钱）
"""

# 2026-10-22（`draft/145-CLI升级方案.md`，业主「到时候我们会花一整段时间慢慢看的，
# 务必该怎么改就怎么改」）：这一批只动 CLI 的形状 —— 一个入口（`start`）讲清
# "干什么 / 在哪干 / 花多少钱 / 开不开 Lean"，四条老命令（`run` / `run-agent` /
# `project run` / `web`）保留为别名并共用同一个执行体 `_run_spec`。
# 角色行为、工具层、读数口径都不在这一次的范围里。

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import textwrap
import time
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from pathlib import Path

from . import schema as S
from . import conceptrows as CR   # 并表过渡层：老表写完同步一份新标准（两处同号）
from . import tty
from . import __version__ as _PKG_VERSION
from .canonical import json_default
from .stop_reasons import STOP_REASONS
from .console import pin_utf8
from .store import Store, StoreError
from .verify import verify_all

#: 不给 `--root` 时的工作区根：`src/agentflow/cli.py` 的 `parents[2]` = 仓库里的 `agentflow/`。
#: （2026-09-30 更正：这一行原写 `# test/test1/` —— 那是 cli.py 还住在原型
#: `test/test1/src/agentflow/` 时的解析结果，搬到正式版之后注释没跟着改。）
DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def _non_negative_int(raw: str) -> int:
    """argparse 的 `type=`：负数在用法错阶段就被拒（退出码 2 = "没查成"）。

    为什么要这一条（`FINAL-R5-06`）：库层对负 `max_calls` 是显式拒绝（抛 `ValueError`），
    但 CLI 层不接住它 ⇒ 未捕获异常 + traceback + 退出码 1，而 1 在本项目的三态里
    是"查过了、有问题"，真相是"一次都没跑"。用法错本来就该退 2。
    """
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"必须 >= 0（收到 {raw}）")
    return value


def _non_negative_float(raw: str) -> float:
    """argparse 的 `type=`：负数上限在用法错阶段就被拒（与本文件的 `_non_negative_int` 同一个理由）。

    为什么上限不许是负数：`reviewaccept` 把上限与花销做 `>` 比较，负上限会让
    "花了零元"也判成超上限 —— 那是一个看着像"判据红"的用法错。
    用法错退 2（"没查成"），不许让它伪装成 1（"查过了、有问题"）。
    """
    value = float(raw)
    if value < 0:
        raise argparse.ArgumentTypeError(f"必须 >= 0（收到 {raw}）")
    return value


# ---------------------------------------------------------------- 配置装载


def load_config(root: Path, path: str | None = None) -> dict:
    """读配置。文件不存在 ⇒ 空配置（不是错误，这是"全用默认值"的正常形态）。

    解析失败时只报真正的那个错误。旧写法把 `import yaml` 与 `safe_load`
    放在同一个 `try` 里，于是"YAML 装上了、但这个文件语法不对"会掉进
    `except Exception` 去试 JSON，最后报出来的是JSON 的错误（`Expecting
    value: line 1 column 1 …`）—— 一次 YAML 缩进错误被伪装成"这文件根本不是
    配置格式"，排查方向被彻底带偏。报错的准确性是诊断能力的一部分。
    """
    p = Path(path) if path else (root / "config.yaml")
    if not p.exists():
        return {}
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # 环境里已装；没有则回退 JSON
    except ImportError:
        # 没有 yaml 依赖时才谈得上"按 JSON 读"，此时报的 JSON 错误才是真原因。
        try:
            return json.loads(text)
        except Exception as e:
            _config_error(f"配置解析失败（{p}；本机无 yaml 依赖，按 JSON 解析）：{e}", e)
    try:
        # YAML 是 JSON 的超集 ⇒ 这里对 .json 配置同样成立，不需要再回退。
        return yaml.safe_load(text) or {}
    except Exception as e:
        _config_error(f"配置解析失败（{p}）：YAML 语法错误：{e}", e)


def _config_error(message: str, cause: BaseException) -> None:
    """配置读不成 ⇒ 一行人话 + 退出码 2（没查成），不是 1（查过了有问题）。

    为什么要单独这一支：`SystemExit("字符串")` 会被解释器按 1 收尾，而 1 在本仓的
    三态里逐字等于"查过了、有问题" —— 一次 YAML 缩进错误会被 CI 读成"检查跑过并且
    发现了问题"。配置读不进来意味着这一次什么都没查（各命令连默认值都还没装配），
    所以是 2。消息仍然逐字给到 stderr：报错的准确性不因为换了退出码而让步。
    """
    print(message, file=sys.stderr)
    raise SystemExit(2) from cause


def make_store(root: Path | None = None) -> Store:
    """开一个工作区句柄（不做任何守卫，也不建目录）。

    为什么单独抽出来：`Store(root)` 之前那条 `.resolve()` 是所有子命令的共同约定
    （相对路径按进程当前目录解析），散在二十几处就会有一处忘了 resolve —— 于是同一个
    工作区两个句柄指向两个路径。守卫（能不能开、要不要 init）在各命令自己那一层。
    """
    root = Path(root or DEFAULT_ROOT).resolve()
    return Store(root)


# ---------------------------------------------------------------- Lean 工具链开机自检
#
# 业主 2026-10-22 的原话：「开机自检可以做，防止用户提供虚构的lean环境」。
# 自检本体在 `leantoolchain`（纯函数自检 + 一份四档读数）；这一节只做两件事：
# 把它打到第一屏，并把"自检不是 usable"变成摘要里那一格 unknown。
#
# 为什么接线集中在这一个文件里：`tools/verify_tools.py` 是 FC-27 禁改区
# （`scripts/noai_gate.py --paths` 对它是 requires_human），自检因此不往桥接层里塞，
# 而是从 `leantoolchain.lean_selfcheck_reading()` 这一个只读读数交出去。


def _lean_cell(value) -> str:
    """把读数里的一格翻成人能读的一行（空串/None 都写清楚，不留空白）。"""
    if value is None:
        return "None"
    if isinstance(value, str):
        return value if value.strip() else "（空）"
    return str(value)


def _lean_mathlib_text(sc: Mapping) -> str:
    """第 ⑤ 步（Mathlib 图论）那一格的一行摘要（版本 / 路径 / 可用与否 / 证据原文）。

    为什么这一格必须打到台面上：用户看到的"Lean 能用"与"形式化能用"是两件事 ——
    盘上那份 Mathlib 编译好了而裸 `lean.exe` 报 `unknown package 'Mathlib'` 的形态
    等于"装了没用"（2026-10-25 的现场）。这一格就是那件事的读数。
    `sc` 里没有 `mathlib` 那一格时（老读数、或调用方注入了自检替身）如实写"没读到"，
    不补一个"可用"。
    """
    m = dict(sc.get("mathlib") or {})
    if not m:
        return "（这一格没读到：自检读数里没有 mathlib）"
    state = str(m.get("state") or "")
    if state == "absent":
        return ("无 Mathlib（五档都没找到工程根）⇒ 第 ⑤ 步退回裸 lean；"
                "这一项不可用，不是『检查器坏了』")
    head = (f"{_lean_cell(state)}；工程根={_lean_cell(m.get('root'))}"
            f"（来源 {_lean_cell(m.get('source'))}）；"
            f"版本={_lean_cell(m.get('version'))}")
    if m.get("runner"):
        head += (f"；跑法={_lean_cell(m.get('runner'))}"
                 f"，退出码={_lean_cell(m.get('exit_code'))}")
    if state == "unusable" or state == "unknown":
        head += f"；理由：{_lean_cell(m.get('reason'))}"
    elif m.get("evidence"):
        head += f"；检查器原文：{_lean_cell(m.get('evidence'))}"
    return head


def _lean_reading_text(sc: Mapping) -> str:
    """自检读数的一行摘要：state + 开关值 + 来源 + 解释器路径 + Mathlib 那一格。"""
    src = _lean_cell(sc.get("source"))
    if not str(sc.get("source") or ""):
        src = "五档都没找到"
    return (f"state={_lean_cell(sc.get('state'))}；"
            f"开关={'开' if sc.get('enabled') else '关'}"
            f"（来源 {_lean_cell(sc.get('enabled_source'))}）；"
            f"来源={src}；解释器={_lean_cell(sc.get('lean_path'))}；"
            f"版本={_lean_cell(sc.get('version'))}"
            f"（{'符合期望' if sc.get('version_ok') else '不符或没读出来'}）；"
            f"Mathlib={_lean_mathlib_text(sc)}")


def _lean_first_screen(root: Path, *, stream=None) -> dict:
    """第一屏：只打"这一趟允许不允许走形式化"，自检本身不跑。返回一份未查读数。

    三件事是业主点名要露出来的：开关值 / 来源 / 解释器路径。它们读的是配置与文件面
    （`settings.lean_enabled` 与 `toolchain.resolve_checker`，后者明写着"不跑版本命令"），
    所以整段不 spawn、不写临时文件。

    ## 为什么首屏不再跑自检（2026-10-25）

    自检的第 ⑤ 步（Mathlib 图论）要真编译一次 `import Mathlib.Combinatorics.SimpleGraph.Basic`
    加 `#check SimpleGraph`：本机实测 11.3 秒（整次自检 13.3 秒），而首屏的用途只是
    "开跑之前让人看一眼开关与解释器"。把十几秒压在开工前那一下，读数是"这工具启动很慢"，
    而它想回答的那个问题（这台机器的图论库可用吗）是 `agentflow doctor` 与收工门的活 ——
    那两处照旧跑完整自检，一个格子都不少。

    所以首屏对自检那几格只写"未查"并指路：`checked` 是 `False`、`state` 是 `unknown`、
    `first_screen` 是 `True`。三态纪律在这里的落点是"没查不许长得像查过了" ——
    `formal_evidence_state` 读到 unknown，于是这一趟任何形式化结论都不会因为首屏没查
    被记成 verified（收工门那一步会再读一次真读数，并把结论写下来）。

    `stream` 只在 `--json` 那一档给 `sys.stderr`：机器读的那一份 stdout 必须保持
    可解析（一条人话混进 JSON 流里，下游拿到的是解析错误而不是结论）。
    """
    from . import leantoolchain as LT
    from . import settings as SET
    from . import toolchain as TC

    out = stream if stream is not None else sys.stdout
    enabled, enabled_src = SET.lean_enabled()
    found = TC.resolve_checker("lean")
    sc = {
        "checked": False, "ok": False, "state": "unknown",
        "enabled": bool(enabled), "enabled_source": str(enabled_src or "default"),
        "source": str(found.get("source") or ""),
        "lean_path": str(found.get("path") or ""),
        "version": "", "version_ok": False, "sha256": "",
        "positive": {"name": LT.POSITIVE_NAME, "exit_code": None, "output_head": "",
                     "elapsed_ms": 0.0, "passed": False, "problem": "",
                     "kind": "not_attempted"},
        "negative": {"name": LT.NEGATIVE_NAME, "exit_code": None, "output_head": "",
                     "elapsed_ms": 0.0, "failed": False, "control_ok": False,
                     "problem": "", "kind": "not_attempted"},
        # 第 ⑤ 步那一格用自检那一份空形状（`_empty_mathlib`），只把理由改成"未查"：
        # 空形状的 state 本来就是 unknown + checked=False，不许在这里补一个"可用"。
        "mathlib": {**LT._empty_mathlib(),  # noqa: SLF001 - 形状只有那一份定义
                    "reason": ("未查（首屏不跑自检：第 ⑤ 步要真编译一次 Mathlib，"
                               "本机实测 11.3 秒）—— 完整读数请跑 `agentflow doctor`")},
        "problems": [],
        "note": ("未查：首屏不跑自检（第 ⑤ 步那一次 Mathlib 编译本机实测 11.3 秒）。"
                 "完整读数请跑 `agentflow doctor`；收工门那一步也会跑一次"),
        "expected_version": "", "elapsed_ms": 0.0,
        #: 这一份是"首屏的未查读数"，不是自检结果。判据按这两格把两件事分开
        #: （`tests/test_first_screen_does_not_run_the_lean_selfcheck.py`）。
        "first_screen": True, "measured": False,
    }
    if found.get("problem"):
        sc["problems"].append(f"解释器那一档：{found['problem']}")

    def emit(line: str) -> None:
        """把一行打到 `out`（不是 `print` 直连 stdout）。

        为什么留这一层：首屏读数要能被判据整段收走（`out` 可注入），
        而"哪几台机器该看到哪一行"这件事只在这一处决定；散着写 `print`，
        判据就只能去截 stdout，收不到的子进程输出会把读数弄脏。
        """
        print(line, file=out)

    emit(tty.paint("[开机自检] Lean 工具链", "bold"))
    emit(tty.bullet(f"开关：{'开' if sc.get('enabled') else '关'}"
                    f"（来源 {_lean_cell(sc.get('enabled_source'))}）"))
    emit(tty.bullet(f"来源：{_lean_cell(sc.get('source'))}"
                    "（--lean > 环境变量 AGENTFLOW_LEAN_BIN > settings.json 的 "
                    "toolchain.lean_bin > config.yaml 的 lean_path > PATH）"))
    emit(tty.bullet(f"解释器：{_lean_cell(sc.get('lean_path'))}"))
    if not enabled:
        emit(tty.bullet("自检：未查（开关关着 —— 这一档本来就不起子进程、不写临时文件）"))
    else:
        emit(tty.bullet("自检：未查（首屏不跑自检：第 ⑤ 步要真编译一次 Mathlib，"
                        "本机实测 11.3 秒）—— 完整读数请跑 "
                        + tty.paint("`agentflow doctor`", "bold")))
    for problem in sc["problems"]:
        emit(tty.bullet(tty.paint(f"没通过：{problem}", "yellow")))
    # 第 ⑤ 步那一格（业主 2026-10-25：盘上有 Mathlib 而裸 lean 不知道它在哪 ⇒
    # 装了等于没装）。首屏这一格只写"未查"，不补一个"可用"。
    emit(tty.bullet(f"Mathlib（第 ⑤ 步，图论）：{_lean_mathlib_text(sc)}"))
    emit(tty.bullet("形式化证据：这一趟首屏不判定（自检未查）—— 收工门会跑一次并把结论写下来"))
    return sc


def _lean_evidence_text(lean: Mapping, reading: Mapping) -> str:
    """摘要里 Lean 那一格：自检不是 usable 时，形式化证据一律记 unknown。

    「记成 verified」这件事的前提是"我们有一个会拒绝假命题的检查器"。
    自检没给出 `usable` 的时候，这一趟声称的 proof 级证据不记成 verified ——
    它记 `unknown`，并把原因点名在这同一格里（业主口径：不许把没跑自检写成 usable）。
    """
    from . import leantoolchain as LT

    head = (f"开启={'是' if lean.get('enabled') else '否'}；"
            f"跑过={'是' if lean.get('ran') else '否'}")
    if not lean.get("enabled"):
        return head + f"；proof 级证据 {lean.get('proved', 0)} 条 —— {lean.get('reason')}"
    if (reading or {}).get("first_screen"):
        # 首屏不跑自检（第 ⑤ 步那一次 Mathlib 编译实测 11.3 秒）⇒ 这一格不判定。
        # 与"查过了、不可用"必须分开写：那会让人去修一个没坏的东西。
        return (head + f"；proof 级证据 {lean.get('proved', 0)} 条 —— 形式化证据这一格"
                "这一趟未查（首屏不跑自检：要读数请跑 `agentflow doctor`；"
                "收工门那一步会跑一次并把结论写下来）")
    evidence_state, why = LT.formal_evidence_state(reading)
    if evidence_state != "verified":
        return (head + "；形式化证据记 unknown（不是 verified）："
                f"Lean 工具链自检 {_lean_cell((reading or {}).get('state'))} —— {why}"
                f"；这一趟得到的 {lean.get('proved', 0)} 条声称的 proof 级证据不记成 verified")
    return (head + f"；proof 级证据 {lean.get('proved', 0)} 条 —— {lean.get('reason')}"
            f"（开机自检 usable：版本 {_lean_cell((reading or {}).get('version'))}，"
            "反控（假命题 1 = 2）被拒绝）")


def _print_lean_selfcheck(sc: Mapping) -> None:
    """把自检读数的每一格打到台面上（`doctor` 那一档）。

    逐键打印的理由：出问题时要能回答"是哪一步没过、那个解释器是哪个二进制"。
    只打一句"自检失败"等于把排查方向藏起来（`state` 与 `problems` 是业主点名要的）。
    """
    print(tty.rule("Lean 工具链（开机自检）"))
    print(tty.bullet(f"checked={sc.get('checked')}；ok={sc.get('ok')}；"
                     f"state={_lean_cell(sc.get('state'))}；"
                     f"开关={'开' if sc.get('enabled') else '关'}"
                     f"（来源 {_lean_cell(sc.get('enabled_source'))}）"))
    print(tty.bullet(f"source={_lean_cell(sc.get('source'))}"
                     + ("" if str(sc.get("source") or "")
                        else "（空串 = 五档都找过、都没找到）")))
    print(tty.bullet(f"lean_path={_lean_cell(sc.get('lean_path'))}"))
    print(tty.bullet(f"version={_lean_cell(sc.get('version'))}；"
                     f"version_ok={sc.get('version_ok')}；"
                     f"期望={_lean_cell(sc.get('expected_version')) or '4.x'}"))
    print(tty.bullet(f"sha256={_lean_cell(sc.get('sha256'))}"))
    for name in ("positive", "negative"):
        row = dict(sc.get(name) or {})
        head = "；".join(f"{k}={_lean_cell(v)}" for k, v in row.items()
                         if k != "output_head")
        print(tty.bullet(f"{name}：{head}"))
        print(f"    输出开头：{_lean_cell(row.get('output_head'))}")
    # 第 ⑤ 步（Mathlib 图论）逐格打出来：工程根 / 版本 / 跑法 / 退出码 / 检查器原文。
    # 只打一句"图论不可用"等于把"是哪一层断的"藏起来 —— 而"工程根没找到"与
    # "工程根找到了、`.olean` 不在"与"编过了但库不认"要改的地方完全不同。
    ml = dict(sc.get("mathlib") or {})
    if ml:
        print(tty.bullet(f"mathlib：{_lean_mathlib_text(sc)}"))
        print(tty.bullet(f"mathlib.runner={_lean_cell(ml.get('runner'))}；"
                         f"argv={' '.join(str(c) for c in (ml.get('argv') or [])) or '（空）'}"))
        print(f"    cwd={_lean_cell(ml.get('cwd'))}")
        print(f"    输出开头：{_lean_cell(ml.get('evidence') or ml.get('output_head'))}")
        for problem in ml.get("problems") or []:
            print(f"  - [mathlib] {problem}")
    problems = list(sc.get("problems") or [])
    print(tty.bullet("problems：" + ("（无）" if not problems else f"{len(problems)} 条")))
    for problem in problems:
        print(f"  - {problem}")
    print(tty.bullet(f"note：{_lean_cell(sc.get('note'))}"))


# ---------------------------------------------------------------- 工作区初始化（R-32 的第四条出路）

#: 工作区标记文件名：`store._foreign_dir_guard_should_refuse` 的白名单出口之一
#: （`projects.classify` 也认它）。
WORKSPACE_MARKER = ".agentflow-workspace"

#: 「这个目录里已经有用户的投料，仍然按工作区初始化」那条开关。
#: 拒绝文案里教的就是它（`init_workspace` 的 except 分支）。
ALLOW_FOREIGN_FLAG = "--allow-foreign-entries"


def _foreign_entries(root: Path) -> list[str]:
    """root 里不属于本框架的条目名。

    白名单从 `store._WORKSPACE_ROOT_ENTRIES` 读（唯一一份），不在这里再抄一遍 ——
    两份白名单的漂移形态是"CLI 认为可以、`Store.init()` 认为不可以"，
    而判据只会照着其中一份红。
    """
    from .store import _WORKSPACE_ROOT_ENTRIES

    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.name not in _WORKSPACE_ROOT_ENTRIES)


def _marker_text(root: Path, *, by: str) -> str:
    """标记文件的内容：谁落的、什么时候落的、认了几个外来条目。"""
    foreign = _foreign_entries(root)
    lines = ["agentflow workspace",
             f"created_at={S.now_iso()}",
             f"created_by={by}",
             f"accepted_foreign_entries={len(foreign)}"]
    if foreign:
        head = ", ".join(foreign[:10]) + (" ..." if len(foreign) > 10 else "")
        lines.append(f"accepted_entries={head}")
    return "\n".join(lines) + "\n"


def init_workspace(st: Store, root: Path, *, allow_foreign_entries: bool,
                   cmd: str, force: bool = False) -> int:
    """`Store.init()` 的 CLI 外壳：把 `R-32` 那一档的拒绝翻成「照着改」的话。

    为什么要有这一层（业主原文：「里面有 2 个不属于我们的条目」）：`R-32` 的判据本身
    是对的（它挡的是"在别人的目录里凭空建库"，`draft/28` §136.3 事故 B），缺的是一条
    「我认这个目录，里面那些文件是我自己投的料」的出口。`--force` 不是那条出口：
    它是"清空重建"。所以这里补第四条路 —— 带 `allow_foreign_entries` 时先落
    `.agentflow-workspace`（`store.init` 自己明写的白名单出口），再照常 init；
    判据本体一个字没改（它在禁改区 `schema-migration` 里）。

    返回退出码：0 = 建成了；2 = 拒绝了（文案里教那条开关）或没查成。
    两个值都有调用方（`main` 的 StoreError 那一档也是 2），所以不许折成布尔。
    """
    if allow_foreign_entries:
        marker = Path(root) / WORKSPACE_MARKER
        if not marker.exists():
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(_marker_text(Path(root), by=f"cli {cmd} {ALLOW_FOREIGN_FLAG}"),
                              encoding="utf-8", newline="\n")
    try:
        st.init(force=force)
    except StoreError as e:
        # 原样打出判据的话（它是"为什么拒"的唯一出处），再补一句"照着改"。
        # 那句只在"拒绝的理由确实是外来条目"时才打：root 是个文件、或者写者锁超时
        # 那些形态教这条开关会把人教错方向。
        print(f"[{cmd}] {e}", file=sys.stderr)
        foreign = _foreign_entries(Path(root))
        if foreign:
            print(tty.paint(
                f"[{cmd}] {Path(root)} 里那 {len(foreign)} 个条目要么是用户自己投的料"
                f"（例如一篇 PDF）、要么是这个目录本来就不干净。若它就是要用的工作区："
                f"加 {ALLOW_FOREIGN_FLAG} 再跑一次 —— 它会先落 "
                f"{WORKSPACE_MARKER}（`store` 的白名单出口），再按工作区初始化；"
                f"那些文件不删、不改，只是从此算这个工作区的条目。",
                "grey"), file=sys.stderr)
        return 2
    return 0


# ---------------------------------------------------------------- 子命令


def cmd_init(args) -> int:
    """初始化一个工作区：建目录、写下每张空表、落工作区标记。

    读写：写 `<root>/data/`（各表文件 + `events.jsonl`）与 `library/`，并在根上落
    工作区标记文件；用户的投料（例如一篇 PDF）不删不改。
    实现方式一句话：本函数只解析 `--root/--force/--allow-foreign-entries`，真正的守卫
    与建表全在 :func:`init_workspace`（外来条目那一档在那里 fail-closed）。
    退出码：`0` 建成 / `2` 没查成（目录里有外来条目而没给开关、或 `data/` 已在盘上）。
    """
    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    code = init_workspace(st, root,
                          allow_foreign_entries=bool(getattr(args, "allow_foreign_entries", False)),
                          cmd="init", force=bool(args.force))
    if code != 0:
        return code
    print(f"[init] 已初始化：{st.data}")
    return 0


def cmd_submit(args) -> int:
    """把一个或一批搜索请求登记进 `search_requests`。

    两条纪律：
    1. 取号只用 `interactions.next_prefixed_id`（全项目唯一的 `r-NNNN` 判据）。本函数原先自己数
       `len(rows) + i + 1` 并靠 `while` 撞号重试 —— 那是第二份取号判据，语义与 `next_prefixed_id`
       的 `max+1` 不同：表里只有 `r-0001`/`r-0003` 时，一个发 `r-0002`、另一个发 `r-0004`
       （`DEVELOPMENT.md` §3 纪律 2："ID 分配器只有一处；新增第二份 = 违规"）。旧写法还没有上限：
       行数过万时会静默产出 `r-10000` 这种越出 4 位空间的号。
    2. 输入不合法 ⇒ 整批不写 + 退出码 2。`row.validate()` 的 `ValueError` 原先在事务中途炸出，
       调用方拿到的是一个 traceback；而"你给的 mode/topic 不合法"是调用方错误，应当以一行说明 +
       非零退出码结束。事务本身是"异常即不提交"，所以这里 catch 之后可以如实说"整批未写入"。

    读写：写 `search_requests`（一行一个请求，取号走 `interactions.next_prefixed_id`）。
    实现方式一句话：`interactions.admit_search_request`（入队与准入在同一条链上）。
    """
    from . import interactions as X

    try:
        if args.file:
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
            items = payload["rows"] if isinstance(payload, dict) and "rows" in payload else payload
        else:
            items = [{"topic": args.topic, "mode": args.mode, "content_description": args.content or ""}]
    except (OSError, ValueError, KeyError, TypeError) as e:
        print(f"[submit] 读取提交清单失败（{args.file}）：{type(e).__name__}: {e}", file=sys.stderr)
        return 2
    if not isinstance(items, list):
        print(f"[submit] 提交清单必须是数组（或 {{\"rows\": [...]}}），收到 {type(items).__name__}", file=sys.stderr)
        return 2

    st = make_store(args.root)
    st.init()
    added: list[str] = []
    try:
        with st.tx("search_requests", actor=args.by, note="submit") as tx:
            rows = tx.rows("search_requests")
            for i, it in enumerate(items):
                if not isinstance(it, Mapping):
                    raise ValueError(f"第 {i + 1} 条不是对象：{it!r}")
                # 取号：唯一判据。`rows` 就是事务内的活列表，upsert 之后下一轮能看见新行。
                rid = X.next_prefixed_id(rows, "request_id", "r")
                row = S.SearchRequest(
                    request_id=rid,
                    timestamp=it.get("timestamp") or S.now_iso(),
                    topic=(it.get("topic") or "").strip(),
                    mode=it.get("mode") or "topical",
                    content_description=it.get("content_description") or "",
                    done=bool(it.get("done", False)),
                    submitted_by=it.get("submitted_by") or args.by,
                )
                row.validate()
                tx.upsert("search_requests", row.to_dict(), note="submitted")
                added.append(rid)
    except (ValueError, TypeError) as e:
        print(f"[submit] 请求不合法，整批未写入：{e}", file=sys.stderr)
        return 2
    print(f"[submit] 已提交 {len(added)} 条：{', '.join(added)}")
    return 0


def _build_providers(cfg: dict, names: list[str], root: Path):
    """按配置构造 provider。import 放在这里，避免无网络环境下 `agentflow status` 也去连网。"""
    from . import providers as P

    out = []
    for n in names:
        n = n.strip().lower()
        if n == "openalex":
            out.append(P.OpenAlexProvider(mailto=(cfg.get("search") or {}).get("mailto") or None,
                                          min_interval=(cfg.get("download") or {}).get("min_interval_seconds", 1.0)))
        elif n == "crossref":
            out.append(P.CrossrefProvider(min_interval=(cfg.get("download") or {}).get("min_interval_seconds", 1.0)))
        elif n == "doaj":
            out.append(P.DoajProvider())
        elif n == "europepmc":
            out.append(P.EuropePmcProvider())
        elif n == "fixture":
            out.append(P.FixtureProvider(root / "demo" / "fixtures" / "candidates.json"))
        else:
            print(f"[warn] 未知 provider：{n}（跳过）", file=sys.stderr)
    return out


def cmd_run_a(args) -> int:
    """跑一轮 A。

    退出码：0 = 这一轮正常收敛（含"队列空了"与"搜索到了但零命中"两种有效结论），
    1 = 终局失败。"搜索失败"与"超次数放弃"都不是成功：
    `AgentA.run` 把它们写成 `outcome="search_failed"` / `gave_up`，而"队列空"写成
    `skipped_reason`。原先这里恒返回 0，于是"这一轮所有请求都因为搜不到而放弃"
    在脚本看来与"一切正常"完全一样 —— 正是"未报错被读成无问题"的形态。

    读写：读 `search_requests`，写 `literature` 与候选台账（经 `AgentA.run` 那一套写口）。
    实现方式一句话：`agent_a.AgentA`（本层装配 provider 与配置）。
    """
    from .agent_a import AgentA
    from . import fetch as F

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    names = (args.provider.split(",") if args.provider else (cfg.get("agent_a") or {}).get("providers", ["openalex"]))
    providers = _build_providers(cfg, names, root)
    downloader = F.default_downloader(cfg.get("download") or {}) if (cfg.get("agent_a") or {}).get("download", True) else None
    agent = AgentA(st, providers=providers, downloader=downloader, config=dict(cfg.get("agent_a") or {}))
    out = agent.run(max_requests=args.max if args.once else None)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 1 if _run_a_failed(out) else 0


def _run_a_failed(out: Mapping) -> bool:
    """`AgentA.run()` 的返回是否表示终局失败（三态里的"失败"，不是"没做"）。"""
    return bool(out.get("gave_up")) or out.get("outcome") == "search_failed"


def _summarize_drop_reasons(reasons, *, top: int = 4) -> str:
    """把"抽取阶段被剔除的关系"的原因聚合成一行（`quote_not_found × 8`）。

    为什么不是逐条打：真跑实测 8 条剔除原因全是同一个码，于是终端上出现 8 行
    一模一样的 `quote_not_found` —— 那既占屏又读不出"到底为什么"。
    聚合成计数之后，同一份信息一行读完；`top` 之外的原因折算成"另有 N 类"，
    所以它不会因为截断而变成一句不完整的话。
    """
    counts: dict[str, int] = {}
    for raw in reasons or []:
        key = str(raw).strip() or "(空原因)"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    head = "、".join(f"{name} × {n}" for name, n in ordered[:top])
    rest = len(ordered) - len(ordered[:top])
    return head + (f"（另有 {rest} 类原因）" if rest else "")


def cmd_run_b(args) -> int:
    """跑一轮 B。

    退出码：0 = 没有抽取失败；1 = 至少一篇文献的抽取抛了异常。
    `AgentB` 刻意不把这类文献置 `processed`（留给租约到期重试，见模块 docstring
    第 4 条），也就是说"这一轮没干成"—— 那必须能从退出码上看见，
    否则定时任务会把"每轮都在重试同一篇"当成持续成功。

    读写：读 `lit_candidates`，写 `literature` / `statements` / `relations`（经秘书那几条唯一写口）。
    实现方式一句话：`agent_b.AgentB.run_once`（抽取器只有 `host.b_extractor` 一处装配）。
    """
    from . import host as _H
    from .agent_b import AgentB
    from .extract import extract_text

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    # 抽取器只有一处装配（`host.b_extractor`）：
    # 此前这里写死 `RuleExtractor()` ⇒ `B.run_once` 永远拒抽（`R-56`），
    # 于是"跑一轮 B"这条命令结构上不可能真的抽取出东西（2026-10-03，`draft/37` §83）。
    _notes: list[str] = []
    agent = AgentB(
        st,
        extractor=_H.b_extractor(st, config=cfg, notes=_notes),
        extract_text=extract_text,
        config=dict(cfg.get("agent_b") or {}),
    )
    for _n in _notes:
        print(f"[run-b] {_n}", file=sys.stderr)
    out = agent.run(max_docs=args.max if args.once else None)
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    if out.get("failed"):
        print(f"[run-b] 有 {out['failed']} 篇文献抽取失败（未置 processed，等租约到期重试）", file=sys.stderr)
        return 1
    return 0


def cmd_status(args) -> int:
    """看看这个工作区的库里有什么：每张表几行，外加事件流的追加数。

    读写：只读（`Store.stats()` 是无锁快照读）。它刻意会 `st.init()` —— 于是"对一个
    空目录跑一次 status"会把这个工作区建起来。这是历史行为，`init` 的守卫在
    `init_workspace` 里，`status` 这一档只用于"已经点了头的工作区"。
    实现方式一句话：表名清单来自 `S.TABLES`（唯一真身），本函数只排版；
    `--json` 直接印 `Store.stats()` 那一份。
    退出码：`0` 读到了 / `2` 没查成（工作区打不开，由 `main` 统一接 `StoreError`）。
    """
    st = make_store(args.root)
    st.init()
    s = st.stats()
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2, default=str))
        return 0
    print(tty.paint(f"工作区 {s['root']}", "bold"))
    print("")
    # 表名清单必须来自 `S.TABLES`，不许在这里写死。
    # 这里原先写死 `("search_requests", "literature", "concepts", "relations")`，
    # 而 `Store.stats()` 明明返回全部表（当时 15 张，加 `conjectures` 后为 16）——
    # 于是"库长什么样"的第一入口静默地不显示另外 11 张（analysis_reports / experiments /
    # documents / tasks …）。
    # 写死的第二份名单还会在表被改名/删除时以 `KeyError` 崩掉（`s[t]`），
    # 而不是如实报告。与 `cmd_tools` 里那句"角色清单必须来自 ROLES"同一个道理。
    rows = []
    for t in S.TABLES:
        info = s[t]
        extra = " ".join(f"{k}={v}" for k, v in info.items() if k != "count")
        rows.append((t, str(info["count"]), extra))
    rows.append(("events", str(s["events"]["appended"]), "追加日志"))
    for line in tty.table(("表", "行数", "其它"), rows, aligns=("left", "right", "left")):
        print(line)
    return 0


def cmd_verify(args) -> int:
    """校验全局不变量（关系、引文、台账一致性），`--deep` 会重开文献逐条复核。

    读写：只读台账与 `library/` 里的文献（`--deep` 时真的重读正文）。它同样会
    `st.init()`（与 `status` 同一个历史行为）。
    实现方式一句话：判定全在 :func:`verify.verify_all`，本函数只把旗标翻成参数、
    把 `--json` 与人读两档印出来，并把"有没有 error（`--strict` 时含 warning）"
    翻成退出码 —— 判据不在 CLI 里，改宽它等于改审计。
    退出码：`0` 没有 error / `1` 查过了、有 error（`--strict` 时 warning 也算）/
    `2` 没查成（`StoreError`，由 `main` 统一接）。
    """
    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    cfg = load_config(root, args.config)
    extract_text = None
    if args.deep:
        from .extract import extract_text as _et

        extract_text = _et
    # 关键：引文复核参数必须与 agent_b 写入时用的同一份配置，否则 --deep
    # 会用更严的规则重算，把写入时合规的引文报成 quote_not_found（假报警）。
    bcfg = cfg.get("agent_b") or {}
    rep = verify_all(
        st,
        deep=args.deep,
        extract_text=extract_text,
        quote_widen=int(bcfg.get("quote_widen_pages", 1)),
        allow_fulltext_quote_fallback=bool(bcfg.get("allow_fulltext_quote_fallback", False)),
    )
    if args.json:
        print(json.dumps(rep.to_dict(), ensure_ascii=False, indent=2, default=str))
    else:
        print(f"{tty.badge('ok' if rep.ok else 'failed')}  校验完成  "
              f"错误 {len(rep.errors)} / 警告 {len(rep.warnings)}")
        for i in rep.issues:
            tone = "red" if i.level == "error" else "yellow"
            print(tty.bullet(tty.paint(f"[{i.level}] {i.table}/{i.row_id or '-'} "
                                       f"{i.code}: {i.message}", tone)))
    # 退出码三档，与 `scripts/lint_rules.py` / `noai_gate.py` 同一口径：
    #   0 = 通过（无错误，且 --strict 下也无警告）
    #   1 = 查过了、发现问题（error 一律失败；--strict 时 warning 也算失败）
    #   2 = 没查成（StoreError，由 `main` 统一处理）
    # 原先只有 `--strict` 才返回非零 ⇒ `agentflow verify` 在库确实有 error 时
    # 退出码仍是 0。"未报错"被读成"无问题"，正是 `draft/17` §6.3 记的那条教训，
    # 也是本项目把 linter/门禁的退出码做成三档的理由。校验器的默认行为必须能当门用。
    if rep.errors:
        return 1
    return 1 if (args.strict and rep.warnings) else 0


#: 移植期工具的落点（业主 2026-10-24 批的 CLI 更新方案 C）。
#:
#: 四条命令（`repair` / `rebuild` / `demo` / `evidence migrate`）的实现搬到了
#: `tools/legacy_cli/<名字>.py`，CLI 里只留同名命令做一行转发。目的：让"下一版删掉
#: 它们"变成一次机械操作（删那个目录 + 删这几个一行函数），其余代码一行都不用动。
#:
#: 为什么按文件路径加载而不是 `import tools.legacy_cli.rebuild`：`tools/` 只在源码仓库里，
#: 不在 `src/` 下，也不是装好的包的一部分。按 `__file__` 往上两级定位仓库根，得到的
#: 行为是确定的：源码仓库里跑 ⇒ 找得到；装好的包里跑 ⇒ 那句人话（退出码 2），
#: 而不是一个 import 栈。
_LEGACY_TOOLS_DIR = "legacy_cli"


def _legacy_module(name: str):
    """加载 `tools/legacy_cli/<name>.py`（按仓库根定位，不依赖 `sys.path`）。

    缓存进 `sys.modules`：同一进程里连跑两次不会重新执行模块体（模块体里有 import，
    重复执行在多线程下会出怪相）。
    """
    key = f"_agentflow_legacy_cli_{name}"
    # 先判文件、再看缓存：反过来会让"文件已经不在了"被一个上次缓存的模块盖住，
    # 于是"装好的包里没有 tools/"那句话永远走不到（判据靠它）。
    root = Path(__file__).resolve().parents[2]
    path = root / "tools" / _LEGACY_TOOLS_DIR / f"{name}.py"
    if not path.is_file():
        raise ImportError(
            f"移植期工具不在盘上：{path}\n"
            f"  `{name}` 的实现已经搬出 CLI（tools/{_LEGACY_TOOLS_DIR}/{name}.py）。"
            "装好的包里没有 tools/ 目录 ⇒ 这条命令只能在源码仓库里跑；"
            "下一版它会连同那个目录一起被删掉。")
    cached = sys.modules.get(key)
    if cached is not None:
        return cached
    import importlib.util

    spec = importlib.util.spec_from_file_location(key, path)
    if spec is None or spec.loader is None:  # pragma: no cover - 文件刚判过存在
        raise ImportError(f"读不了这个文件：{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[key] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:  # noqa: BLE001 模块体炸了 ⇒ 不留半成品在缓存里
        sys.modules.pop(key, None)
        raise
    return module


def cmd_rebuild(args) -> int:
    """从 `events.jsonl` 重放重建全部快照（数据出事时的逃生门）。

    legacy：真实现在 `tools/legacy_cli/rebuild.py`，下一版删除，先确认行为无差异。
    转发的只是调用这一层 —— 输出、退出码、旗标与搬走前逐字节相同
    （判据 `tests/test_legacy_cli_forwards.py` 拿搬走前实测的指纹对拍）。

    读写了哪些表或文件：读 `data/events.jsonl`，覆盖 `data/*.json` 各表快照，
    缺省先在 `data/` 下留一份备份（`--no-backup` 关掉）。
    """
    return _legacy_module("rebuild").main(args)


def cmd_repair(args) -> int:
    """重算派生列 `related_concepts`（`--related` 必须显式给；写 concepts 表）。

    legacy：真实现在 `tools/legacy_cli/repair.py`，下一版删除，先确认行为无差异。
    并表之后这一列已随老表退役，所以今天它基本只会走进"受控退出 + 指路"那一支。

    读写了哪些表或文件：读 `relations` 与 concepts 表；只有在真的需要重算时才写
    concepts（缺省 fail-closed，一行都不写，退出码 2）。
    """
    return _legacy_module("repair").main(args)


def cmd_demo(args) -> int:
    """离线端到端演示（不联网、不花钱；`--keep` 保留上次的演示数据）。

    legacy：真实现在 `tools/legacy_cli/demo.py`，下一版删除，先确认行为无差异；
    执行体本身在库里（`demo.run_demo`），这里只是把两个旗标翻成两个入参。

    读写了哪些表或文件：在 `<root>/demo/run` 下建一整套演示工作区（会写盘），
    缺省先清掉上次那一份。
    """
    return _legacy_module("demo").main(args)


def cmd_tools(args) -> int:
    """列出工具层装配情况（按角色）。

    这个命令存在的意义：工具层的权限面是设计的一部分（A 拿不到 D 的工具等），
    但它默认是隐式的 —— 加一条命令把它变成可打印的事实，才好在评审时核对。

    读写：不读不写工作区文件；只现算工具面按角色的装配表。
    实现方式一句话：`tools.build_registry` / `for_role`（与运行期同一份装配）。
    """
    from agentflow.tools import ROLES, TOOL_ROLES, build_registry

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    st.init()
    # 角色清单必须来自 `TOOL_ROLES`（= 可被召唤的 A–H + 主控 M），不许在这里写死。
    # 这里原先写死 `("A","B","C","D")`，于是 E/F/G/H 落地之后，本命令会
    # 一边报告"工具总数 55"，一边只列 4 个角色的工具数 —— 而"角色即权限面"
    # 恰恰是靠这条命令变成可打印的事实的。写死名单让那句"评审时可核对"落空。
    # 现在补的是同族缺口：用 `ROLES` 会让主控的 8 件编排面工具在普查里完全不出现
    # （实测 2026-09-28：总数 63，而各角色表里没有 M）—— 那正是"主控有没有手"
    # 这个问题的答案，不能被漏掉。
    build = build_registry(store=st, workspace_root=root, roles=tuple(ROLES))
    if args.json:
        print(json.dumps(build.summary(), ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"工具总数：{len(build.registry)}（已装模块 {len(build.loaded)}：{', '.join(build.loaded) or '无'}）")
    if build.lean_off:
        # 业主 2026-10-22：按开关不装的模块要能看见（不然读者会去查"为什么少了两个工具"）。
        print(f"按 Lean 开关不装的模块（不是缺陷）：{', '.join(build.lean_off)}")
    if build.skipped:
        print("未装上的模块（并行开发中属正常）：")
        for s in build.skipped:
            print(f"  - {s['module']} [{s['stage']}] {s['error'][:80]}")
    role = args.role
    if role:
        from agentflow import leanscope as _LEANSCOPE

        if _LEANSCOPE.is_hidden(role):
            # 按名取一个"这一档下不存在"的角色：说清理由，不打印一张空清单。
            payload = _LEANSCOPE.hidden_refusal(role, surface="agentflow tools --role")
            print(payload["error"], file=sys.stderr)
            return 2
        specs = build.registry.for_role(role)
        print(f"\n角色 {role} 可用工具（{len(specs)} 个）：")
        for s in sorted(specs, key=lambda x: x.name):
            flag = " ⚠需审批" if s.needs_approval else ""
            print(f"  {s.name:28} [{s.side_effect}]{flag}  {s.summary[:60]}")
    else:
        # 只读角色的写工具泄漏必须一眼可见：它是"审校者手里有没有刀"的直接答案。
        from agentflow.tools import READ_ONLY_ROLES, SIDE_EFFECTS_WRITE

        from agentflow import leanscope as _LEANSCOPE

        # 业主 2026-10-22：`TOOL_ROLES` 是声明词表（刻意完整，见 `tools/__init__` 的
        # 注释）；这一行是读数，所以按可见性过滤 —— 开关关着时不存在的角色不许在这里
        # 留一个 "L: 0 个工具" 的格子。
        by_role = {r: len(build.registry.for_role(r))
                   for r in _LEANSCOPE.visible_roles(TOOL_ROLES)}
        print(f"\n各角色工具数：{by_role}")
        leaks = {
            r: [s.name for s in build.registry.for_role(r) if s.side_effect in SIDE_EFFECTS_WRITE]
            for r in READ_ONLY_ROLES
        }
        print(f"只读角色写工具泄漏：{leaks}（{'空 = 正常' if not any(leaks.values()) else '!! 有泄漏'}）")
        if build.registry.role_filter_notes:
            print(f"⚠️ 有工具的 roles 声明需要纠正（行为已被 for_role 拦下）：")
            for r, notes in build.registry.role_filter_notes.items():
                print(f"  [{r}] {notes[0][:140]}")
        print("（用 --role A 查看具体清单）")
    return 0


def _build_agent_c(root: Path, cfg: dict):
    from agentflow.agent_c import AgentC

    st = make_store(root)
    st.init()
    return st, AgentC(st, config=cfg.get("agent_c") or {})


def cmd_analyze(args) -> int:
    """运行 C 的关系分析（四类需求之一）。

    读写：只读 relations / statements / research_questions 与概念视图；分析结果由 `agent_c` 落 `analysis_reports`（本层不另写表）。
    实现方式一句话：`agent_c.handle` 分派到四个分析入口（hottest / cold / gaps / paths）。
    """
    """运行 C 的关系分析（四类需求之一）。"""
    root = Path(args.root or DEFAULT_ROOT).resolve()
    cfg = load_config(root, args.config)
    st, c = _build_agent_c(root, cfg)

    if args.text:
        rep = c.handle(args.text)
    elif args.kind == "paths":
        if not (args.a and args.b):
            print("[analyze] kind=paths 需要 --a 与 --b（概念代号或概念名）", file=sys.stderr)
            return 2
        a = _resolve_concept(st, args.a)
        b = _resolve_concept(st, args.b)
        if a is None or b is None:
            names = [f"{r['concept_id']}={r['name']}"
                     for r in CR.view(st, shape="legacy")["rows"]]
            print(f"[analyze] 无法解析概念：a={args.a!r} b={args.b!r}\n  现有概念：{names}", file=sys.stderr)
            return 2
        rep = c.paths(a, b, max_paths=args.max_paths, max_len=args.max_len, request=args.request or "")
    elif args.kind == "hottest":
        rep = c.hottest(top_n=args.top_n, request=args.request or "")
    elif args.kind == "cold":
        rep = c.cold(top_n=args.top_n, request=args.request or "")
    elif args.kind == "gaps":
        rep = c.gaps(limit=args.top_n, request=args.request or "")
    else:
        print(f"[analyze] 未知 kind={args.kind}", file=sys.stderr)
        return 2

    # `rep.ok is False` 表示"这次没能给出结论"（概念解析不到、关系表为空……），
    # 与"分析完成、结论是没找到"是两件事（见 `AnalysisReport.ok` 的 docstring）。
    # 必须在 `persist()` 之前分流：`persist()` 明确拒绝登记 kind 不在受控词表里的
    # 报告（`kind="unknown"` 就是分派失败），先 persist 会以 ValueError 崩出一个
    # traceback —— 而"这条需求我听不懂"是一句应当被读到的结论，不是崩溃。
    # 代价是失败报告不落表：这是 `persist()` 自己的硬规则（表外 kind 会让 D 无法处理），
    # 不是这里偷偷跳过。人读的 markdown 与机器可读的退出码照给。
    if not rep.ok:
        if rep.markdown:
            print(rep.markdown)
        # error 是受控的机器可读原因，summary 是人话结论；两条都给 ——
        # 只给 error 会把"该怎么办"丢掉（例如 error="关键词未命中"，
        # 而 summary 会列出可用的说法示例）。
        detail = str(rep.error or "")
        if rep.summary and rep.summary not in detail:
            detail = f"{detail}；{rep.summary}" if detail else rep.summary
        print(f"[analyze] 分析未给出结论（kind={rep.kind}）：{detail}", file=sys.stderr)
        return 1

    row = rep.persist()
    print(rep.markdown)
    # `persist()` 返回的是登记行（report_id / markdown_path / abs_path），
    # 不含 `kind` —— kind 是报告对象自己的属性。这里曾经误用 row['kind'] 而 KeyError。
    print(f"\n[analyze] 报告已登记：report_id={row.get('report_id')} kind={rep.kind} "
          f"markdown={row.get('markdown_path')}")
    if rep.warnings:
        print(f"[analyze] 告警 {len(rep.warnings)} 条：")
        for w in rep.warnings:
            print(f"  - {w}")
    if rep.truncated:
        print("[analyze] ⚠ 搜索被预算截断（结果可能不完整）")
    return 0


def _resolve_concept(st, token: str) -> str | None:
    """把用户给的东西解析成概念代号：既接受 4 位代号，也接受概念名（走 dedup 的规范化匹配）。

    概念行读合成视图（并表过渡期：老表 + 新标准 `kind="concept"`，同号去重）：
    只读老表会让"新标准写进来的概念"在这条命令里解析不到（用户看到一个存在的概念
    被报成"解析不了"）。
    """
    from agentflow import dedup as D

    rows = CR.view(st, shape="legacy")["rows"]
    if S.is_valid_id(token) and any(r["concept_id"] == token for r in rows):
        return token
    hit = D.find_concept(rows, token)
    return hit["concept_id"] if hit else None


def cmd_pipeline(args) -> int:
    """把 A→B→C→D 串起来跑（DESIGN-TOOLS.md §5）。

    读写：读 `search_requests` / `literature`；A/B 那一趟的写口各写自己的表，C 的报告落 `analysis_reports`。
    实现方式一句话：`pipeline.run_pipeline`（A/B 传 None 就是「不检索」，语义只在一处）。
    """
    """把 A→B→C→D 串起来跑（DESIGN-TOOLS.md §5）。"""
    from . import host as H
    from agentflow.agent_a import AgentA
    from agentflow.agent_b import AgentB
    from agentflow.extract import extract_text
    from agentflow.pipeline import run_pipeline
    from agentflow import fetch as F

    root = Path(args.root or DEFAULT_ROOT).resolve()
    cfg = load_config(root, args.config)
    st = make_store(root)
    st.init()

    # `run_pipeline` 用 agent_a/agent_b 是否为 None 来表达"这轮要不要真的去检索"，
    # 而不是另设一个布尔开关 —— 这样"不检索"就是"没接上 A/B"，语义只有一处。
    agent_a = agent_b = None
    if not args.no_search:
        names = (cfg.get("agent_a") or {}).get("providers", ["openalex"])
        agent_a = AgentA(
            st,
            providers=_build_providers(cfg, names, root),
            downloader=F.default_downloader(cfg.get("download") or {}),
            config=dict(cfg.get("agent_a") or {}),
        )
        agent_b = AgentB(
            st,
            extractor=H.b_extractor(st, config=cfg),
            extract_text=extract_text,
            config=dict(cfg.get("agent_b") or {}),
        )

    out = run_pipeline(
        st,
        request=args.request,
        gap_rounds=args.gap_rounds,
        config=cfg,
        agent_a=agent_a,
        agent_b=agent_b,
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


# ---------------------------------------------------------------- 统一执行体（RunSpec）
#
# 业主 2026-10-22 口径（`draft/145-CLI升级方案.md` §2）：一个入口讲清"干什么 / 在哪干 /
# 花多少钱 / 开不开 Lean"，其余都是它的子模式；老命令全部保留为别名，不许破坏脚本。
#
# 这一节就是那句话的落点：五条入口（`start` 与四条老命令）各自只做一件事 —— 把自己
# 那一套旗标翻成一个 `RunSpec`，然后交给同一个 `_run_spec`。旗标在那一层归一，于是
# 「同一个概念三个旗标」（`draft/145` 的 F3）不会再变成三处各自解释一遍。
#
# 为什么是"共用执行体"而不是把老命令改写成 argv 重排（把 `run --topic T` 改排成
# `start --task T`）：argv 重排会把三条老命令的用法错、`--help` 与缺省值全部换一套，
# 而 C2 的字面要求是"行为与今天逐字一致"。所以解析层一个字不动，只在执行层收口。

#: `RunSpec.mode` 的四个取值。它们回答"这一趟走哪条路"，不回答"敲的是哪个子命令"。
MODE_TOPIC = "topic"
MODE_ROLE = "role"
MODE_PROJECT = "project"
MODE_WEB = "web"

#: 各模式在"没显式给 `--budget-usd`"时的缺省额度。
#:
#: 三个数不一样是刻意的：`run` 那一趟是单次作答（1.0），`project run` 是带登记的一趟
#: （0.5），角色循环没有缺省上限（None = 不限，由墙钟与步数管）。它们现在只在这张表里
#: 写一遍 —— 老命令 parser 上的 default 由 `tests/test_cli_upgrade_c1_c8.py` 与本表对拍。
MODE_DEFAULT_BUDGET: Mapping[str, float | None] = {
    MODE_TOPIC: 1.0,
    MODE_PROJECT: 0.5,
    MODE_ROLE: None,
    MODE_WEB: None,
}

#: `--lean` 的三档（业主口径：auto 先跑自检，usable 才开）。
LEAN_CHOICES: tuple[str, ...] = ("on", "off", "auto")

#: `start --mode` 认得的值。`auto` 是"按目录状态推断"，其余是显式指定。
#: `research` 不是第五条路：它是 role 那一档的 flavor（原 `run-agent M --subagents`）。
START_MODES: tuple[str, ...] = ("auto", "topic", "role", "research",
                               "project", "cold", "warm")

#: `start --dry-run --json` 那一份的键集合。
#:
#: 写在这里是为了让它只有一个真身：判据
#: `tests/test_cli_upgrade_c1_c8.py::test_c1_dry_run_json_carries_exactly_the_documented_keys`
#: 断言当次输出的键集合逐字等于这一份 —— "口径写在 docstring 里"只有配上那条判据才是
#: 可执行的。
START_PLAN_KEYS: tuple[str, ...] = ("mode", "task", "workspace", "project", "model",
                                    "budget", "lean", "summons", "writes", "spend")

#: 新分层（F 的形状；业主 2026-10-24：「A 到 E 都是好的，且尽可能往 F 的想法上靠，
#: 至少形状上一致」）：四个动词组，每组一句话说明它管什么。
#:
#: ## 为什么要这一层，又为什么旧名一个都不删
#:
#: 二十八个平铺的动词对读 `--help` 的人不友好（"doctor 和 verify 该先跑哪个"、
#: "stats 跟 status 有什么不一样"）；但它们每一个都已经被真机上的脚本、文档与
#: 用户肌肉记忆用着。所以这一轮只做"加一层入口"：
#:
#: - 新入口：`agentflow <组> <成员> [旗标]`（本表就是它的唯一真身）；
#: - 旧入口：`agentflow <旧名> [旗标]` 照旧可用 —— 它不是别名层，它就是同一条命令
#:   （`canonical_argv` 把新路径折回旧名再交给同一个 parser，所以两者连 `args` 都是
#:   同一份，不存在"走新路少一个旗标"这种漂法）。
#:
#: ## 成员名怎么定的
#:
#: 成员名逐字沿用旧名（`inspect stats` 就是 `stats`），只有一处例外：端到端跑主题那条
#: 旧命令叫 `run`，而组也叫 `run` —— 组内再叫 `run` 会得到 `agentflow run run` 这种
#: 没人想敲的东西，所以它在组里叫 `topic`（`MEMBER_ALIASES` 里那一行）。`agentflow run`
#: 不带成员时仍然是那条旧命令，行为一个字都没变。
#:
#: ## 四组之外有没有漏的
#:
#: 旧名 28 个，这张表覆盖 28 个（判据 `tests/test_cli_grouped_entry_points.py` 断言并集
#: 相等）。其中 `verify` / `doctor` 归 `inspect`、`closing` 归 `run` 是本次归纳时补的
#: （业主给的名单里只点到 25 个）：不补它们就成了新体系里的孤儿，而"能不能交"与"这台
#: 机器行不行"显然都是查看类。要改回去就删这三行，判据会跟着红并点名。
COMMAND_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("incubate", "孵化：把一趟研究开起来、管起来", (
        "init", "start", "stop", "status", "answer", "inbox", "submit")),
    ("inspect", "查看：只读的读数与检查", (
        "status-report", "stats", "evidence", "artifacts", "analyze", "tools", "cache",
        "budget", "doctor", "verify")),
    ("run", "跑：流水线与角色循环，以及它们的维护", (
        "topic", "pipeline", "run-a", "run-b", "run-agent", "repair", "rebuild",
        "project", "closing")),
    ("serve", "服务：网页与离线演示", ("web", "demo")),
)

#: 组内成员名 → 它等价的旧命令名。只有真的换了名字的要写在这里（"同名的"不必登记）。
#:
#: 键写成 `组.成员` 而不是嵌套字典：这张表只有几行，扁平写法在 diff 里一眼能看出
#: "这一轮换了哪个名字"，嵌套写法会把理由与键隔开两屏。
MEMBER_ALIASES: dict[str, str] = {"run.topic": "run"}


def _group_members() -> dict[str, dict[str, str]]:
    """组 → {成员名: 旧命令名}（未在 `MEMBER_ALIASES` 登记的成员与旧名同名）。"""
    out: dict[str, dict[str, str]] = {}
    for group, _purpose, members in COMMAND_GROUPS:
        out[group] = {m: MEMBER_ALIASES.get(f"{group}.{m}", m) for m in members}
    return out


#: 组 → {成员名: 旧命令名}。`canonical_argv`、组页、判据都读它（一处定义）。
GROUP_MEMBERS: dict[str, dict[str, str]] = _group_members()

#: 组名（顺序即呈现顺序）。
GROUP_NAMES: tuple[str, ...] = tuple(group for group, _p, _m in COMMAND_GROUPS)

#: 组名 → 一句话用途。
GROUP_PURPOSE: dict[str, str] = {group: purpose for group, purpose, _m in COMMAND_GROUPS}


def command_paths() -> tuple[tuple[str, str], ...]:
    """旧名 → 新路径的全文对照表（`--help-legacy`、文档与判据都读这一份）。

    一个旧名只给一条新路径（`dict` 的插入序 = `COMMAND_GROUPS` 的表序）。这张表是
    "旧名一个都没删、而且每个都有一条新路径到达"这句话唯一可执行的形态：文档里的
    对照表、`--help` 末尾那句"旧名仍可用"、判据里的"并集相等"全从它生成。
    """
    pairs: dict[str, str] = {}
    for group, _purpose, members in COMMAND_GROUPS:
        for member in members:
            pairs.setdefault(GROUP_MEMBERS[group][member], f"{group} {member}")
    return tuple(pairs.items())


#: 旧名清单（28 个）。`build_parser()` 的 choices 必须与它同集：判据是集合相等
#: （`tests/test_cli_grouped_entry_points.py`），表序由 `build_parser` 的登记顺序
#: 决定，不是抄这一份的序。原先这里写"必须逐字等于它"—— 两个 28 元组顺序不同，
#: 逐字相等当场为 False，而判据从来只比 set。
LEGACY_COMMANDS: tuple[str, ...] = tuple(old for old, _path in command_paths())

#: 顶层里"带值"的那两个开关 —— 找命令位置时必须跳过它们的值，否则
#: `agentflow --root inspect stats` 会把 `inspect` 当成 `--root` 的值。
_VALUE_OPTIONS: frozenset[str] = frozenset({"--root", "--config"})


def _command_index(argv: list[str]) -> int | None:
    """argv 里第一个"命令 token"的下标（跳过顶层开关与它们的值）。找不到 ⇒ None。"""
    i = 0
    while i < len(argv):
        token = str(argv[i])
        if token in _VALUE_OPTIONS:
            i += 2
            continue
        if token.startswith("--root=") or token.startswith("--config="):
            i += 1
            continue
        if token.startswith("-"):
            i += 1
            continue
        return i
    return None


def canonical_argv(argv: list[str]) -> list[str]:
    """把 `agentflow <组> <成员> …` 折回旧名的 argv（形状见 `COMMAND_GROUPS`）。

    这是"新指令接管、旧指令不删"那条纪律的实现：新路径不是另一条执行链，它在解析之前
    就被折成旧名，于是两条路走进同一个 `parser`、同一个 `func`、同一份 `args`。
    刻意的三处"不折"（都由 `main` 在后面给人话或交给 argparse）：

    - 只有组名没有成员（`agentflow inspect`）⇒ 打组页；
    - 第二个词以 `-` 开头（`agentflow run --topic t`）⇒ 它就是旧命令本身；
    - 成员名不认识 ⇒ 不改写（`main` 会点名"这个组里没有它"）。
    """
    raw = list(argv)
    index = _command_index(raw)
    if index is None:
        return raw
    members = GROUP_MEMBERS.get(str(raw[index]))
    if members is None:
        return raw
    if index + 1 >= len(raw):
        return raw
    member = str(raw[index + 1])
    if member.startswith("-") or member not in members:
        return raw
    return raw[:index] + [members[member]] + raw[index + 2:]


@dataclass(frozen=True)
class RunSpec:
    """这一趟要做什么 —— 五条入口唯一的交汇形状。

    它只装"每条入口都说得上话"的那几格（干什么 / 在哪干 / 用什么模型 / 花多少钱 /
    开不开 Lean / 要不要盯 / 是不是试运行），剩下的旗标仍然留在 `args` 上原样透传：
    把 `--extract-rounds` 这种只属于一条路的开关也搬进来，只会让这个对象长成第二个
    `Namespace`，而"归一"就白做了。
    """

    mode: str
    task: str = ""
    role: str = ""
    root: Path | None = None
    out: Path | None = None
    project_name: str | None = None
    project_start: str = "auto"
    model: str | None = None
    budget_usd: float | None = None
    budget_usd_given: bool = False
    lean: str = "off"
    lean_given: bool = False
    research: bool = False
    watch: bool = False
    dry_run: bool = False
    as_json: bool = False
    origin: str = ""


@dataclass(frozen=True)
class _LeanPlan:
    """Lean 三档归一之后的结论：开不开、要不要动环境变量、读数里那一句话。"""

    enabled: bool
    env_value: str | None
    note: str = ""


class _BudgetUsdAction(argparse.Action):
    """`--budget-usd` 的落点：除了值，还要记下"这个数是不是用户显式给的"。

    为什么必须记：`run` 的缺省是 1.0、`project run` 是 0.5、`run-agent` 是不限 ——
    只看 `args.budget_usd` 的分不开"用户给了 1.0"与"用户什么都没给、走了缺省"。
    而这两件事在 C4 上是相反的结论：前者要把 1.0 落进寄存器，后者一个字节都不该写。
    """

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        setattr(namespace, self.dest, values)
        setattr(namespace, "budget_usd_given", True)


def _spec_from(args, *, mode: str, origin: str, task: str | None = None,
               role: str | None = None, research: bool | None = None,
               project_name: str | None = None, project_start: str | None = None,
               watch: bool | None = None, dry_run: bool | None = None) -> RunSpec:
    """把一条入口的旗标翻成 `RunSpec`；只给这条入口才知道的那几格传 `overrides`。

    所有取值都走 `getattr`：判据里有手搭 `Namespace` 的老调用方（`tests/test_agent_cli.py`
    的 `_args`），缺一格就让整条 `run-agent` 崩在属性上，是这次升级不该付的代价。
    """
    budget = getattr(args, "budget_usd", None)
    if budget is None:
        budget = MODE_DEFAULT_BUDGET.get(mode)
    raw_lean = getattr(args, "lean", None)
    if isinstance(raw_lean, bool):
        # 手搭 Namespace 的老调用方可能直接把 bool 塞进这一格：按它本来的意思读。
        lean, lean_given = ("on" if raw_lean else "off"), True
    else:
        lean = str(raw_lean or "off")
        lean_given = raw_lean is not None
    if lean not in LEAN_CHOICES:
        lean, lean_given = "off", True
    root_raw = getattr(args, "root", None)
    out_raw = getattr(args, "out", None)
    return RunSpec(
        mode=mode,
        task=str(task if task is not None
                 else (getattr(args, "task", "") or getattr(args, "topic", "") or "")),
        role=str(role if role is not None else (getattr(args, "role", "") or "")),
        # 工作区根不在这里 mkdir：`run` 的缺省落点是一个临时目录，那件事归 `_exec_topic`
        # 自己办（它在真的要走模型时才建），否则试运行会先建出一个空目录。
        root=Path(root_raw) if root_raw else None,
        out=Path(out_raw) if out_raw else None,
        project_name=project_name if project_name is not None
        else getattr(args, "name", None),
        project_start=str(project_start if project_start is not None
                          else (getattr(args, "start", "auto") or "auto")),
        model=getattr(args, "model", None),
        budget_usd=float(budget) if budget is not None else None,
        budget_usd_given=bool(getattr(args, "budget_usd_given", False)),
        lean=lean,
        lean_given=lean_given,
        research=bool(research if research is not None
                      else getattr(args, "research", False)),
        watch=bool(watch if watch is not None else getattr(args, "watch", False)),
        dry_run=bool(dry_run if dry_run is not None else getattr(args, "dry_run", False)),
        as_json=bool(getattr(args, "json", False)),
        origin=origin,
    )


def _resolve_lean(spec: RunSpec) -> _LeanPlan:
    """把 `--lean on|off|auto` 归一到"这一趟开不开"。

    - `off`：关。只有在用户显式写了 `--lean off` 时才注入
      `AGENTFLOW_LEAN_ENABLED=0`；不显式给就一个字都不动 —— "这条命令从不提 Lean"与
      "这条命令要求关掉 Lean"是两件事（改前 `run` / `project run` 都不碰这条开关，
      C2 要求逐字不变；判据 `tests/test_projects.py` 那条透传用例也钉着这一格）。
    - `on`：开，注入 `=1` 并清掉提示词侧的读数缓存。
    - `auto`：先跑一次真自检（`refresh=True`，不吃旧缓存），`usable` 才当 on；其余三档
      一律当 off，并把原因写进 `note` —— 于是形式化结论记 unknown 而不是 verified。
    """
    if spec.mode == MODE_WEB:
        return _LeanPlan(False, None)
    choice = str(spec.lean or "off")
    if choice == "on":
        return _LeanPlan(True, "1")
    if choice == "auto":
        from . import leantoolchain as LT
        from . import settings as SET

        # `auto` 问的是"如果把它打开，这台机器可用吗" —— 所以自检必须按"开着"跑一次。
        # 只改开关、不传 `lean=`：那个参数是"解释器在哪"的提示，传 `"on"` 会被当成一个
        # 文件路径去解析（实测读数逐字是 `--lean=on 不存在（解析成 D:\Incubator\on）`）。
        reading = LT.lean_selfcheck_reading(
            root=spec.root, refresh=True,
            env={**os.environ, SET.ENV_LEAN_ENABLED: "1"})
        state, why = LT.formal_evidence_state(reading)
        if state == "verified":
            return _LeanPlan(True, "1")
        return _LeanPlan(
            False, "0",
            note=("[lean] --lean auto：自检没给出 usable（"
                  f"{_lean_cell((reading or {}).get('state'))}）⇒ 这一趟照常跑，"
                  f"但一切形式化结论记 unknown。原因：{why}"))
    return _LeanPlan(False, "0" if spec.lean_given else None)


@contextmanager
def _lean_scope(plan: _LeanPlan):
    """在这一趟运行期间把 Lean 开关钉在 `plan.env_value` 上，跑完原样还原。

    为什么要还原而不是直接改：环境变量是进程级的，而 `cli.main` 在判据里只是一个函数
    调用（同一进程里会连着跑几十趟）。不还原的话，"这一趟 `--lean off`"会静默地把后面
    每一趟都关掉 —— 那种漂移在输出里完全看不见。
    """
    if plan.env_value is None:
        yield
        return
    from . import agent_prompts as AP
    from . import settings as SET

    before = os.environ.get(SET.ENV_LEAN_ENABLED)
    os.environ[SET.ENV_LEAN_ENABLED] = plan.env_value
    # 提示词侧把"开关值 + 工具链读数 + 两段文案"缓存在一起（`agent_prompts` 的那几个
    # `lru_cache`）⇒ 换了开关必须一起清，否则模型读到的还是上一档的角色面。
    AP.reset_toolchain_readings()
    try:
        yield
    finally:
        if before is None:
            os.environ.pop(SET.ENV_LEAN_ENABLED, None)
        else:
            os.environ[SET.ENV_LEAN_ENABLED] = before
        AP.reset_toolchain_readings()


def _budget_notice(before_usd, after_usd, path: str, *, stream=None) -> None:
    """预算那一行读数：把"原来多少 → 现在多少"点名出来（C4 的第二半）。

    为什么非点名不可（改前的现场）：`budget.json` 里留着 0.5 时，
    `limit_usd(fallback=10.0)` 返回 0.5 且一声不响 —— 于是"我给了 10"与"闸门按 0.5 停"
    同时成立，而输出里一个字都没提。
    """
    out = stream if stream is not None else sys.stdout
    new = float(after_usd)
    if before_usd is None:
        print(tty.bullet(f"预算：{new:g} 美元（已落盘 {path}）"), file=out)
    elif abs(float(before_usd) - new) > 1e-9:
        print(tty.bullet(
            f"预算：{float(before_usd):g} → {new:g} 美元（寄存器里原来是 {float(before_usd):g}，"
            f"命令行给了 {new:g}；已按命令行落盘，旧的那一笔留在追加史里）"), file=out)
    else:
        print(tty.bullet(f"预算：{new:g} 美元（与寄存器一致）"), file=out)


def _land_budget(spec: RunSpec, root: Path, *, stream=None) -> int:
    """显式给了 `--budget-usd` 就落盘（C4）。返回 0 = 没给或写成了，2 = 没查成。

    改前的两处错（同一批查出来的）：

    1. 三条 run 命令一次都没调 `budget.write_initial` —— 传了不写，下次查看仍是旧值，
       于是用户只能先 `budget --set 10` 绕过；
    2. 寄存器压过 flag —— `budget.json` 里留着 0.5 时，`limit_usd(fallback=10.0)`
       返回 0.5 且一声不响。

    落盘同时把第 2 条也修掉了：写完之后寄存器里就是那个显式值，闸门读到的正是它。
    写不成（只读盘 / 坏寄存器被拒）时必须停下 —— 拿旧额度接着跑，等于把第 2 条换个
    形状复现一遍。

    调用点必须在"工作区已经存在、还没花钱"这一刻：不是在这个函数里顺手 init，
    因为空目录里先落一个 `budget.json` 会让 `Store.init()` 的外来条目守卫判它不干净
    （实测：新目录上 `run --budget-usd 0.5` 直接以 store 错误退出）。
    """
    if not spec.budget_usd_given or spec.budget_usd is None:
        return 0
    from . import budget as B

    before = B.read_register(root)
    got = B.write_initial(root, spec.budget_usd, by="cli",
                          note=f"agentflow {spec.origin} --budget-usd")
    if not got.get("ok"):
        print(tty.paint(f"[budget] 没查成：{got.get('reason')}", "yellow"), file=sys.stderr)
        print(tty.paint(
            "[budget] 显式给的额度没落进寄存器 ⇒ 这一次不跑（拿旧额度接着跑，"
            "等于让寄存器静默压过 --budget-usd）", "yellow"), file=sys.stderr)
        return 2
    _budget_notice(before["total_usd"], spec.budget_usd,
                   str(got.get("path") or ""), stream=stream)
    return 0


def _has_ledger(path: Path) -> tuple[bool, str]:
    """这个项目里有没有跑过的台账（决定 `--mode auto` 该落 research 还是 warm）。

    判据刻意取"`data/tasks.jsonl` 里有几行"而不是"文件夹在不在"：一个刚 `plan` 过、
    还没跑过的项目当然没有 DAG，把它当成"有台账"会让 `--mode auto` 一上手就跑研究循环。
    """
    tasks = Path(path) / "data" / "tasks.jsonl"
    if not tasks.is_file():
        return False, "没有 data/tasks.jsonl"
    try:
        rows = sum(1 for line in tasks.read_text(encoding="utf-8").splitlines()
                   if line.strip())
    except OSError as exc:
        return False, f"data/tasks.jsonl 读不出来（{type(exc).__name__}）"
    return rows > 0, f"data/tasks.jsonl {rows} 行"


def _target_workspace(spec: RunSpec, args) -> tuple[Path, dict | None]:
    """这一趟真正的落点：项目模式给项目文件夹，其余给工作区根。

    "在哪干"这一格只在这里答一次。`web` 那一档也走它，所以 `start --watch --project P`
    开出来的网页读的正是 P 的盘 —— 而不是"用户以为的工作区"（F6 那条现场：
    `web` 不含"当前项目"，监督一次还得自己拼 `--root projects/p3-verify2`）。

    这里一律按 `start="auto"` 解析：它回答的是"落点在哪"，不回答"要不要新建" ——
    后者归 `project_start`，而试运行那一档要的正是"别替我把新建这一步办了"。
    """
    root = Path(spec.root or DEFAULT_ROOT).resolve()
    if spec.mode not in (MODE_PROJECT, MODE_WEB) or not spec.project_name:
        return root, None
    from . import projects as P

    base = P.projects_dir(getattr(args, "projects_dir", None))
    try:
        ref = P.resolve(base, spec.project_name, start="auto")
    except P.ProjectNotAWorkspace as exc:
        print(tty.paint(f"[start] {exc}", "yellow"), file=sys.stderr)
        return root, None
    return ref.path, ref.to_dict()


def _summons_text(spec: RunSpec) -> str:
    """预检里的"会召唤谁"：这一趟会不会起角色、起哪些。

    为什么这一格非有不可（`draft/145` 的 F1）：三个入口长得像、语义完全不同 ——
    `run` 是单趟作答、不召唤任何角色，`run-agent` 才是真跑某个角色的循环。今天先跑了
    `run` 的人会以为"角色都起来了"，白花一次钱才发现什么角色都没起。
    """
    if spec.mode == MODE_WEB:
        return "不起任何角色（只开网页）"
    if spec.mode == MODE_TOPIC:
        return "不召唤任何角色（端到端跑主题：检索 / 作答 / 逐字回验都不经角色循环）"
    if spec.mode == MODE_PROJECT:
        return "不召唤任何角色（项目工作区那一步是端到端主题跑）；要角色循环请 --mode research"
    from . import capabilities as _C
    from . import leanscope as _LS
    from . import schema as _S

    top = spec.role or _S.CONDUCTOR_ROLE
    kids = tuple(_C.ALLOWED_EDGES.get(top, ()))
    visible = _LS.visible_roles([top, *kids])
    if spec.research:
        return (f"{top} 起十角色循环（--subagents）：{top} 可以召唤 "
                + "、".join(r for r in visible if r != top))
    return (f"只跑 {top} 这一个循环；它按边可以召唤 "
            + ("、".join(r for r in visible if r != top) or "（没有出边）"))


def _print_plan(spec: RunSpec, args) -> int:
    """`--dry-run`：把将要发生的一切打出来，一个字节都不写、一次模型都不调（C1）。

    两处刻意的绕行：

    1. 不复用 `_lean_first_screen` —— 它会真的起一次 Lean 自检子进程（分钟级，而且
       会往临时目录写 .lean 采样）。预检要回答的是"开不开"，读数从开关那一层取，自检
       那一格如实写"没跑"。
    2. 项目那一档复用 `projects.plan`（它自己的 docstring 就是"不建目录、不写字节"），
       而不是 `projects.run_project` 再 dry-run —— 后者第一件事就是 `create_project`。
    """
    from . import projects as P
    from .modelgw import spec_from_env
    from . import settings as SET

    workspace, project = _target_workspace(spec, args)
    model_spec = spec_from_env()
    if spec.model:
        model_spec = replace(model_spec, model=spec.model)
    project_note = ""
    if spec.mode == MODE_PROJECT or (spec.mode == MODE_WEB and spec.project_name):
        base = P.projects_dir(getattr(args, "projects_dir", None))
        start = "auto" if spec.mode == MODE_WEB else spec.project_start
        try:
            # 名字不给就由 `projects.plan` 取下一个号：预检要回答"会落在哪个文件夹"。
            plan = P.plan(base, spec.project_name, start=start)
        except (P.ProjectExists, P.ProjectMissing, P.ProjectNotAWorkspace) as exc:
            # 试运行要说清"你要求的冷/热启动会撞上什么"，而不是替你把文件夹处理掉。
            print(tty.paint(f"[start] {exc}", "yellow"), file=sys.stderr)
            plan = P.plan(base, spec.project_name, start="auto")
        project = plan["project"]
        project["will_create"] = plan["will_create"]
        project["run_index"] = plan["run_index"]
        project_note = str(plan.get("note") or "")
        workspace = Path(plan["project"]["path"])
    _has_rows, ledger_why = _has_ledger(workspace)
    if project:
        note = project_note
    else:
        note = (f"这一趟的落点还没有台账（{ledger_why}）" if not _has_rows
                else f"这一趟的落点已有台账（{ledger_why}）")
    try:
        lean_on, lean_src = SET.lean_enabled()
    except (ValueError, OSError) as exc:
        lean_on, lean_src = False, f"读不懂（{type(exc).__name__}）"
    plan_out = {
        "mode": spec.mode,
        "task": spec.task,
        "workspace": str(workspace),
        "project": project or {},
        "model": {"name": model_spec.model, "base_url": model_spec.base_url},
        "budget": {"usd": spec.budget_usd, "given": spec.budget_usd_given,
                   "register": str(_register_path(workspace))},
        "lean": {"choice": spec.lean, "now_on": bool(lean_on),
                 "now_source": str(lean_src),
                 "selfcheck": "没跑（试运行不启动检查器）"},
        "summons": _summons_text(spec),
        "writes": [] if spec.mode == MODE_WEB else [
            f"工作区 {workspace}" + ("（会新建）" if project and project.get("will_create")
                                     else ""),
            "out/run-N 六件产物" if spec.mode in (MODE_TOPIC, MODE_PROJECT) else "运行记录与会话事件",
        ] + ([f"预算寄存器 budget.json（{spec.budget_usd:g}）"] if spec.budget_usd_given else []),
        "spend": "不花钱（试运行一次模型都不调）",
    }
    if spec.as_json:
        print(json.dumps(plan_out, ensure_ascii=False, default=str))
        return 0
    budget_cell = ("不限量（没给 --budget-usd，这个模式也没有缺省上限）"
                   if plan_out["budget"]["usd"] is None
                   else f"{plan_out['budget']['usd']:g} 美元"
                        + ("（命令行显式给的，会落盘）" if spec.budget_usd_given
                           else "（该模式的缺省值，不落盘）"))
    lean_cell = (f"开关现在{'开' if lean_on else '关'}（来源 {lean_src or '缺省'}）；"
                 f"这一趟 --lean {spec.lean}；自检没跑（试运行不启动检查器）")
    print("")
    for line in tty.panel(
        "试运行：将要发生的一切（一个字节都不写、一次模型都不调）",
        [("模式", ("research（十角色循环）" if spec.research else spec.mode)),
         ("模型", f"{model_spec.model}（base={model_spec.base_url}）"),
         ("预算", budget_cell),
         ("Lean", lean_cell),
         ("会召唤", plan_out["summons"]),
         ("会写这些", "；".join(plan_out["writes"]) or "（不写任何东西）")],
        body=[("任务：" + spec.task) if spec.task else "任务：（没给 —— 只起网页）",
              *([note] if note else [])],
        verbatim=[("工作区：", str(workspace))],
        tone="cyan",
    ):
        print(line)
    print(tty.bullet(tty.paint(plan_out["spend"], "bold")))
    return 0


def _register_path(workspace: Path) -> Path:
    """预算寄存器的落点（与 `budget.register_path` 同一个名字，不另造一份口径）。"""
    from . import budget as B

    return B.register_path(workspace)


def _current_round(root: Path, sid: str) -> int:
    """这一段会话现在跑到第几轮（读会话事件里的轮号；读不到就是 0）。

    为什么是 0 而不是 1：网页打开的那一刻可能什么都还没跑过，写 1 会让"还没开始"
    与"正在第 1 轮"长得一样。
    """
    try:
        from . import sessions as SS

        events, _problems = SS.read_session(root, sid=sid)
    except Exception:  # noqa: BLE001 —— 读不到轮号是"没读到"，不是 0 轮
        return 0
    best = 0
    for event in events:
        for key in ("round", "rounds", "round_index"):
            value = event.get(key)
            if isinstance(value, int) and value > best:
                best = value
    return best


def _with_watch(spec: RunSpec, args) -> int:
    """`--watch`：起网页、把 URL / 工作区 / sid / 当前轮打出来，再决定跑不跑。

    两条路（口径写在 `start` 的 help 里）：

    - 不带任务 ⇒ 只起网页（等价于 `web` 加三格读数），服务一直开着，Ctrl-C 停；
    - 带任务 ⇒ 服务在后台线程里，边跑边可监督；这一趟跑完就收工（要继续看就再 `web`）。

    为什么不用 `webui.run(argv)`：它只印 URL，而这里要印的是四格（URL / 工作区 / sid /
    当前轮）。`web` 那条老命令仍然逐字转发 `webui.run`（C2）。
    """
    import threading

    from .webui import server as _WS

    root, _project = _target_workspace(spec, args)
    root.mkdir(parents=True, exist_ok=True)
    srv = _WS.serve(
        root,
        host=str(getattr(args, "host", "127.0.0.1") or "127.0.0.1"),
        port=int(getattr(args, "port", _WS.DEFAULT_PORT) or 0),
        token=str(getattr(args, "token", "") or os.environ.get("AGENTFLOW_WEB_TOKEN", "")),
        allow_writes=bool(getattr(args, "allow_writes", False)),
        settings_write=not bool(getattr(args, "no_settings_write", False)),
    )
    host, port = srv.server_address[0], srv.server_address[1]
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{shown}:{port}/"
    sid = str(getattr(args, "sid", "") or _session_id())
    round_no = _current_round(root, sid)
    if spec.as_json:
        print(json.dumps({"url": url, "root": str(root), "sid": sid, "round": round_no},
                         ensure_ascii=False, default=str), flush=True)
    else:
        print(tty.paint(f"网页：{url}", "bold"), flush=True)
        print(tty.bullet(f"工作区：{root}"))
        print(tty.bullet(f"会话：{sid}；当前轮：{round_no}"))
        if not spec.task:
            print("Ctrl-C 停。", flush=True)
    try:
        if not spec.task or spec.mode == MODE_WEB:
            srv.serve_forever()
            return 0
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        return _dispatch(spec, args)
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            srv.shutdown()
        except Exception:  # noqa: BLE001 —— 收尾失败不该盖掉这一趟的退出码
            pass
        srv.server_close()


def _session_id() -> str:
    """这一趟的会话号（与 `run-agent` 同一口径：环境变量优先，否则当天）。"""
    from . import sessions as SS

    return SS.session_id()


def _dispatch(spec: RunSpec, args) -> int:
    """把归一后的 `RunSpec` 交给对应那条路的执行体。

    认不出的模式 ⇒ 一行人话 + 退出码 2。原文是 `raise SystemExit("<话>")`，而
    字符串形态会被解释器按 1 收尾 —— 消息里写着"没查成"、码却是"查过了有问题"，
    两者在同一句话里互相打架；今天 `START_MODES` 之外没有可达路径，但口径不许
    靠"不可达"来成立。
    """
    if spec.mode == MODE_WEB:
        return _exec_web(spec, args)
    if spec.mode == MODE_TOPIC:
        return _exec_topic(spec, args)
    if spec.mode == MODE_ROLE:
        return _exec_role(spec, args)
    if spec.mode == MODE_PROJECT:
        return _exec_project(spec, args)
    print(f"[start] 没查成：认不出的模式 {spec.mode!r}（{'/'.join(START_MODES)}）",
          file=sys.stderr)
    raise SystemExit(2)


def _announce_cache_line(spec: RunSpec) -> None:
    """起跑前打一行缓存读数（只加读数：读不到 / 不新鲜都不拦跑、不改退出码）。

    为什么在这里、而不是在三条执行体各写一遍：`_run_spec` 是五条入口（`start` /
    `run` / `run-agent` / `project run` / `web`）唯一的执行体，Lean 开关也已经归一
    好了 —— 这一行说的"这一趟用哪一档"与真正发请求时读的开关是同一个值。

    读的一方是 `cachectl.run_reading()`（它自己接住所有异常）：本函数因此只负责
    "印出来 + 选流"。`--json` 那一档走 stderr，免得一行人话把 stdout 的 JSON 弄坏。
    """
    from . import cachectl as CC

    got = CC.run_reading()
    text = str(got.get("text") or "")
    if not text:
        return
    stream = sys.stderr if spec.as_json else sys.stdout
    if str(got.get("level")) == CC.RUN_WARNING:
        print(tty.paint(text, "yellow"), file=stream, flush=True)
    else:
        print(text, file=stream, flush=True)


def _run_spec(spec: RunSpec, args) -> int:
    """唯一执行体：五条入口（`start` / `run` / `run-agent` / `project run` / `web`）都到这里。

    它按固定顺序办四件共有的关口，再分派给那条路：

    1. 试运行 ⇒ 只说、不做（连 Lean 自检都不起子进程）；
    2. Lean 三档归一（`on` / `off` / `auto`），并把结果钉在环境变量上；
    3. 显式 `--budget-usd` 落盘（C4）；
    4. `--watch` 起网页并打印四格读数（C7）；
    5. 分派。

    归一后的值会写回 `args`（`topic` / `task` / `budget_usd` / `lean_enabled`）：三条执行体
    仍然照原样读 `args`，于是"执行层收口"不会顺手改掉它们的行为（C2）。

    起跑前多了一行缓存读数（:func:`_announce_cache_line`）：它只印一行、不返回任何值，
    也不参与下面任何一个关口 —— 不新鲜照跑，退出码由执行体自己给。
    """
    args.topic = spec.task
    args.task = spec.task
    if spec.role:
        args.role = spec.role
    if spec.budget_usd is not None:
        args.budget_usd = spec.budget_usd
    if spec.dry_run:
        return _print_plan(spec, args)
    lean_plan = _resolve_lean(spec)
    if lean_plan.note:
        print(tty.paint(lean_plan.note, "yellow"),
              file=(sys.stderr if spec.as_json else sys.stdout))
    with _lean_scope(lean_plan):
        args.lean_enabled = lean_plan.enabled
        _announce_cache_line(spec)
        if spec.watch:
            return _with_watch(spec, args)
        return _dispatch(spec, args)


def _missing_task() -> str:
    """`start` 缺 `--task` 时的"人话"（C3：要说清该给哪个旗标，不许是 argparse 原文）。"""
    return ('[start] 缺一样要跑的东西：给 --task "这次要做的事"（研究 / 项目 / 主题三档都要它）。'
            "只想开网页监督就加 --watch；只想跑某一条角色的循环就 --mode role --role <角色>；"
            "想先看看会发生什么就再加 --dry-run")


def _spec_of_start(args) -> tuple[RunSpec | None, str]:
    """把 `start` 的旗标推断成 `RunSpec`；推断不出来就返回一句人话（第二格非空）。"""
    mode = str(getattr(args, "mode", "auto") or "auto")
    task = str(getattr(args, "task", "") or "").strip()
    role = str(getattr(args, "role", "") or "")
    watch = bool(getattr(args, "watch", False))
    name = getattr(args, "name", None)
    root_raw = getattr(args, "root", None)
    if root_raw and not getattr(args, "projects_dir", None):
        # `--project` 的落点跟着 `--root` 走。老命令 `project run` 这一格保持原样
        # （它从来不看 `--root`）—— C2 要求它的行为逐字不变，所以这条只写在 `start` 里。
        args.projects_dir = str(Path(root_raw).resolve() / "projects")
    if mode == "role":
        if not role:
            return None, ("[start] 缺一个要跑的角色：--mode role 要给 --role <角色>"
                          f"（可选 {'/'.join([*S.ROLES, S.CONDUCTOR_ROLE])}）。"
                          "想跑十角色循环就 --mode research（那时角色缺省 M）")
        return _spec_from(args, mode=MODE_ROLE, origin="start", role=role), ""
    if not task:
        if mode == "auto" and watch:
            return _spec_from(args, mode=MODE_WEB, origin="start", watch=True), ""
        return None, _missing_task()
    if mode == "research":
        return _spec_from(args, mode=MODE_ROLE, origin="start",
                          role=role or S.CONDUCTOR_ROLE, research=True), ""
    if mode == "topic":
        return _spec_from(args, mode=MODE_TOPIC, origin="start"), ""
    if mode in ("cold", "warm"):
        return _spec_from(args, mode=MODE_PROJECT, origin="start",
                          project_start=mode, task=task), ""
    if mode == "project":
        return _spec_from(args, mode=MODE_PROJECT, origin="start", task=task), ""
    # ---- auto：按目录状态推断（`draft/145` §3.1）
    from . import projects as P

    base = P.projects_dir(getattr(args, "projects_dir", None))
    try:
        ref = P.resolve(base, name, start="auto")
    except P.ProjectNotAWorkspace as exc:
        return None, f"[start] 没查成：{exc}"
    if name:
        # 项目给出来了 ⇒ 这一趟就在那个项目里干（研究循环也一样）。不这么做的话，
        # `--mode research --project p` 会把十角色循环跑在工作区根上、产物落在项目外面。
        args.root = str(ref.path)
    if ref.mode == "cold":
        return _spec_from(args, mode=MODE_PROJECT, origin="start",
                          project_start="cold", task=task), ""
    has_ledger, _why = _has_ledger(ref.path)
    if has_ledger:
        return _spec_from(args, mode=MODE_ROLE, origin="start",
                          project_start="warm", role=role or S.CONDUCTOR_ROLE,
                          research=True), ""
    return _spec_from(args, mode=MODE_PROJECT, origin="start",
                      project_start="warm", task=task), ""


def cmd_start(args) -> int:
    """统一入口（`draft/145` §3.1）：一个入口讲清"干什么 / 在哪干 / 花多少钱 / 开不开 Lean"。

    ## `--mode` 怎么推断（不写就是 auto）

    1. 没给 `--task`：给了 `--watch` ⇒ 只开网页（`web` 的别名）；没给 ⇒ 人话报错并点名
       `--task`（C3）；
    2. 项目文件夹不存在或为空 ⇒ cold；
    3. 项目文件夹已初始化、且 `data/tasks.jsonl` 有行 ⇒ research（十角色循环，角色缺省 M）；
    4. 项目文件夹已初始化、但没有台账 ⇒ warm。

    ## 三条"人话"

    - 缺 `--task` 且没 `--watch`：说清"要么给任务、要么只开网页"；
    - `--mode role` 少 `--role`：点名 `--role` 与可选值；
    - `--mode research` 不用给角色：角色缺省 M（`draft/145` 的 F2 正是位置参数缺失时
      argparse 那句原文 —— 用户从"缺什么"里读不出"该给哪个旗标"）。

    退出码：0 做成了 / 1 查过了、有问题 / 2 没查成（用法错或前提不满足）。

    读写：按 `--mode` 落到四条执行体之一（topic / role / project / web），读写的就是那一条自己的表；`--dry-run` 一个字节都不写、一次模型都不调。
    实现方式一句话：`_run_spec` 一个执行体（五条入口只在这一层归一旗标）。
    """
    spec, problem = _spec_of_start(args)
    if problem:
        print(tty.paint(problem, "yellow"), file=sys.stderr)
        return 2
    assert spec is not None
    return _run_spec(spec, args)


def cmd_run(args) -> int:
    """端到端跑一个主题：`run_topic` 的退出码就是这个进程的退出码。

    为什么工作区默认落在临时目录：`run` 会写 `usage_ledger`（真花钱的账），
    而默认写进演示数据目录 `test/test1/` 会让每次试跑都污染那份必须保持干净的
    数据。临时目录加"把实际路径打印出来"是这一步的诚实形态 ——
    "产物在哪"必须能从输出里读到，而不是靠人猜一个默认值。

    `--model` 只覆盖模型名：key / base_url / 超时 / 重试一律来自环境变量
    （`spec_from_env`），命令行不许传 key —— argv 会进 shell 历史与进程列表。

    这一层只剩"翻成 `RunSpec` 再交给 `_run_spec`"（`draft/145` §3.2 的别名形态：
    解析层不动、执行层收口）；真正的执行体是 :func:`_exec_topic`。

    读写：写那一趟临时工作区的各表、`usage_ledger`（真花钱的账）与六件产物目录。
    实现方式一句话：`runflow.run_topic`（本层只把旗标翻成 `RunSpec`）。
    """
    return _run_spec(_spec_from(args, mode=MODE_TOPIC, origin="run"), args)


def _exec_topic(spec: RunSpec, args) -> int:
    """原 `cmd_run` 的执行体（形状逐字保留；差异只有三处：root / out / lean 改从
    `RunSpec` 取，`budget_usd` 已经是归一后的值）。"""
    import tempfile

    from .modelgw import spec_from_env
    from .runflow import run_topic

    # 顶层参数 `--root` 必须写在子命令之前（argparse 的位置规则），
    # 缺省时给一个临时工作区（理由见 `cmd_run` 的 docstring）。
    root = Path(spec.root) if spec.root else Path(tempfile.mkdtemp(prefix="agentflow-run-"))
    out = Path(spec.out) if spec.out else Path(tempfile.mkdtemp(prefix="agentflow-run-out-"))
    model_spec = spec_from_env()
    if spec.model:
        model_spec = replace(model_spec, model=spec.model)
    st = make_store(root)
    st.init()
    # 显式额度在这里落盘：工作区已经存在、还没花一分钱（见 `_land_budget` 的注释）。
    code = _land_budget(spec, root)
    if code:
        return code
    # ---- 第一屏：Lean 工具链开机自检（业主 2026-10-22「防止用户提供虚构的lean环境」）。
    # 它回答的是"这一趟能不能信形式化证据"，所以必须在跑之前就露出来，
    # 而不是等报告里出现一条 proof 行之后才去怀疑环境。
    lean_reading = _lean_first_screen(root)
    res = run_topic(
        st,
        topic=args.topic,
        budget_usd=args.budget_usd,
        out_dir=out,
        spec=model_spec,
        max_calls=args.max_calls,
        prompt_version=args.prompt_version,
        now=args.now,
        # `--fulltext` 缺省关闭：开机就批量下载开放全文是网络与磁盘的实质开销，
        # 必须由调用方显式要。关闭时产物里会如实写"没有发起全文获取"，
        # 而不是让读者以为"取了、但没有开放全文"。
        fulltext=bool(args.fulltext),
        # `--lean` 三档（`on` / `off` / `auto`）已经在 `_run_spec` 里归一成
        # `lean_enabled` 这一格：改前这里写的是 `bool(args.lean)`，而 `--lean off`
        # 会让 `bool("off")` 为真 —— 关不掉的开关比没有开关更坏。
        lean=bool(getattr(args, "lean_enabled", False)),
        # 裸 `run` 没有项目根，所以逐页正文默认内联；要"同一本书只存一份"
        # 就显式给一个落点（依据 `draft/30` §T0-7）。
        text_store_dir=getattr(args, "text_store_dir", None),
    )
    # 两个数字、两种口径，必须分开印（`G-4`）：
    # - `spent_usd_this_run` 是本次运行花掉的（`--budget-usd` 判的就是它）；
    # - `spent_usd` 是该工作区账本累计（`usage_ledger` 跨运行求和，属于工作区）。
    # 只印累计值时，"这次运行烧光了预算"与"这个工作区历史上一共花了多少"会是
    # 同一个数字 —— 一个长期使用的工作区会让每一次 run 看起来都超预算。
    # 老版本（返回值里还没有这个键时）退回累计值：不猜，但也不隐藏它缺了。
    this_run = res.get("spent_usd_this_run", res["spent_usd"])
    # 检索三态与断言台账摘要必须打到 stdout：它们是"这次的结论有没有外部依据"
    # 的直接答案。只写在 JSON 里，等于要人先去读文件才知道该不该相信这份报告。
    counts = res["claims"]
    lean = res.get("lean") or {}
    print("")
    for line in tty.panel(
        "端到端跑一个主题",
        [("退出码", f"{_exit_badge(res['exit_code'])}（{res['reason']}）"),
         ("模型调用", f"{res['calls']} 次；本次已花 {this_run} 美元"
                      f"（本次预算 {args.budget_usd}）；该工作区账本累计 {res['spent_usd']} 美元"),
         ("检索", f"{res['retrieval_status']}；断言 {counts['total']} 条"
                  f"（逐字通过 {counts['verified']}：摘要级 {counts.get('verified_abstract', 0)}、"
                  f"全文级 {counts.get('verified_fulltext', 0)}；未验证 {counts['unverified']}）"),
         ("Lean", _lean_evidence_text(lean, lean_reading)),
         ("六件产物", "、".join(res["artifacts"]))],
        # 路径放进 `verbatim`：它是要被抄下来 `cd` 进去的，截断了就等于没打印。
        verbatim=[("工作区：", str(root)), ("产物目录：", res["out_dir"])],
        tone="green" if int(res["exit_code"]) == 0 else "yellow",
    ):
        print(line)
    # `not_wired` 必须打到 stdout：它是"这次有哪些事确定没做"的直接答案，
    # 只写在 JSON 里等于要人先去读文件才知道不该相信这份报告。
    man = json.loads((out / "run-manifest.json").read_text(encoding="utf-8"))
    for item in man["not_wired"]:
        print(tty.bullet(tty.paint(f"未接线：{item['name']} —— {item['reason']}", "yellow")))
    return int(res["exit_code"])


# ---------------------------------------------------------------- 证据面（T0-7）


def _evidence_verify(run_dir: Path) -> int:
    """核一个运行目录里的全文引用：逐条比对 `text_ref`，并重算引文命中页。

    为什么必须能独立核：`text_ref` 把"证据正文在哪"从产物内部搬到了产物外部，
    搬出去就必须有工具回答"这条引用还对不对" —— 否则搬出去等于把可复核性也搬走了。
    三态：0 = 查过、都对得上；1 = 查过了、有坏引用或页号不符；2 = 没查成。
    """
    from . import fulltextstore as FS

    ev_path = run_dir / "evidence.json"
    if not ev_path.is_file():
        print(f"[evidence] 没查成：{ev_path} 不存在", file=sys.stderr)
        return 2
    try:
        ev = json.loads(ev_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[evidence] 没查成：读不了 {ev_path}（{type(exc).__name__}: {exc}）", file=sys.stderr)
        return 2

    # 运行目录形如 <项目根>/out/run-N ⇒ 项目根是上两级；`allowed_dir` 用它把
    # "引用只许指向本项目的正文库"这条结构判据钉死。
    allowed = run_dir.parent.parent / FS.STORE_DIR_NAME
    rows: list[tuple[str, str, str]] = []
    bad = 0
    for src in ev.get("sources") or []:
        sid = str(src.get("source_id") or "?")
        ref = (src.get("fulltext") or {}).get("text_ref")
        if not isinstance(ref, dict):
            rows.append((sid, "-", "内联或没有全文（不是引用形态）"))
            continue
        rep = FS.verify_ref(ref, allowed_dir=allowed)
        if not rep["ok"]:
            bad += 1
            rows.append((sid, "坏", rep["problem"]))
        else:
            rows.append((sid, "好", f"{rep['pages']} 页 / {rep['chars']} 字"))

    rows = _verify_quotes(run_dir, ev, rows)
    bad += sum(1 for r in rows if r[1] == "页不符")
    for line in tty.table(("来源", "引用", "读数/理由"), rows, aligns=("left", "left", "left")):
        print(line)
    print(tty.bullet(f"引用 {len(rows)} 条；坏 {bad} 条。台账：{ev_path}"))
    return 1 if bad else 0


def _verify_quotes(run_dir: Path, ev: Mapping, rows: list[tuple[str, str, str]]) -> list[tuple[str, str, str]]:
    """把 `claims.json` 里登记的页号与我方独立搜出来的页号对一遍（不调用被审对象）。

    独立复核的意义：`claims.json` 的页号是被审实现给的；这里用朴素规范化
    （NFKC + 折叠空白）自己搜一遍，两处一致才算"这条引用可复核"。
    """
    import unicodedata

    from . import fulltextstore as FS

    claims_path = run_dir / "claims.json"
    if not claims_path.is_file():
        return rows
    try:
        # 2026-10-17（IO #9）：`claims.json` 顶层可能是数组（手写/半途写坏）——
        # `.get` 会抛 AttributeError，而这一支只接 OSError/ValueError。
        _doc = json.loads(claims_path.read_text(encoding="utf-8"))
        claims = (_doc.get("claims") if isinstance(_doc, dict) else None) or []
    except (OSError, ValueError):
        return rows
    pages_by_sid: dict[str, list[str]] = {}
    for src in ev.get("sources") or []:
        ref = (src.get("fulltext") or {}).get("text_ref")
        if isinstance(ref, dict):
            pages, _why = FS.load(ref)
            pages_by_sid[str(src.get("source_id") or "?")] = pages
    if not pages_by_sid:
        # 内联形态的产物：本工具不复算页号（它只复算引用形态）。
        # 这里必须如实说"没复算" —— 绝不许把"没查成"写成"页不符"：
        # 那会把一次读取能力的缺失记成产物的缺陷。
        rows.append(("（全部来源）", "未复算",
                     "产物是内联形态；要复算页号请先 `evidence migrate --apply`"))
        return rows

    def _norm(text: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", str(text or "")).casefold().split())

    for c in claims:
        quote = str(c.get("quote") or "")
        rec_page = (c.get("locator") or {}).get("page") if isinstance(c.get("locator"), dict) else None
        if not quote or rec_page is None:
            continue
        found = None
        for _sid, pages in pages_by_sid.items():
            for idx, page in enumerate(pages, start=1):
                if _norm(quote) and _norm(quote) in _norm(page):
                    found = idx
                    break
            if found:
                break
        state = "页一致" if found == rec_page else "页不符"
        rows.append((f"claims/{c.get('claim_id') or '?'}", state,
                     f"登记 {rec_page} / 我方独立搜到 {found}"))
    return rows


def _evidence_store(project_dir: Path) -> int:
    """盘一个项目的正文库：几个文件、多少字节、每个文件被几份产物引用。

    空目录与"零字节"必须分开说 —— 把空库读成"没问题"正是这一层最常见的误读。
    """
    from . import fulltextstore as FS

    store_dir = project_dir / FS.STORE_DIR_NAME
    rows = FS.inventory(store_dir)
    if not rows:
        print(tty.bullet(f"正文库：空（{store_dir} 不存在或没有任何 store 文件）"))
        return 0
    referenced: dict[str, int] = {}
    for ev_path in sorted(project_dir.glob("out/run-*/evidence.json")):
        try:
            ev = json.loads(ev_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for src in ev.get("sources") or []:
            ref = (src.get("fulltext") or {}).get("text_ref")
            if isinstance(ref, dict) and ref.get("path"):
                key = Path(str(ref["path"])).name
                referenced[key] = referenced.get(key, 0) + 1
    table = [(Path(r["path"]).name, "好" if r["ok"] else "坏",
              f"{r['bytes']} B / {r['pages']} 页 / 被 {referenced.get(Path(r['path']).name, 0)} 份产物引用",
              r["problem"]) for r in rows]
    for line in tty.table(("store 文件", "自校验", "读数", "问题"), table):
        print(line)
    print(tty.bullet(f"共 {len(rows)} 个 / {sum(int(r['bytes']) for r in rows)} 字节；落点 {store_dir}"))
    return 1 if any(not r["ok"] for r in rows) else 0


def _evidence_migrate(args) -> int:
    """把历史产物里的内联正文迁成引用形态（默认 dry-run，`--apply` 才动盘）。

    legacy：真实现在 `tools/legacy_cli/evidence_migrate.py`，下一版删除，
    先确认行为无差异（判据 `tests/test_legacy_cli_forwards.py` 拿搬走前实测的指纹对拍）。

    读写了哪些表或文件：读 `<项目根>/out/run-*/evidence.json`；`--apply` 时写
    `.fulltext/` 正文库（`fulltextstore.put`）、改写那些产物，并先在
    `<项目根>/../temp/evidence-migrate-<stamp>/` 留一份逐份备份。
    """
    return _legacy_module("evidence_migrate").main(args)


def cmd_evidence(args) -> int:
    """证据面三件事：核引用 / 盘正文库 / 迁移历史产物（依据 `draft/30` §T0-7）。

    三态（与全仓同一条纪律）：0 = 查过、都对得上；1 = 查过了、有坏引用；
    2 = 没查成（目标不在 / 读不了）。

    读写：读 `out/run-*/evidence.json` 与 `.fulltext/` 正文库；`migrate --apply` 会写正文库并改写那些产物（逐份先备份）。
    实现方式一句话：`fulltextstore` 的 `verify_ref` / `inventory` / `put`，本文件只做分派与呈现。
    """
    target = Path(args.target)
    if args.action == "verify":
        return _evidence_verify(target)
    if args.action == "store":
        if not target.is_dir():
            print(f"[evidence] 没查成：{target} 不是目录", file=sys.stderr)
            return 2
        return _evidence_store(target)
    if not target.is_dir():
        print(f"[evidence] 没查成：{target} 不是目录", file=sys.stderr)
        return 2
    return _evidence_migrate(args)


# ---------------------------------------------------------------- 入口


def cmd_artifacts(args) -> int:
    """产物归属：登记 / 列出 / 核对 / 问归属 / 找没归属的 / 渲染成表。

    三态（与全仓同一条纪律）：0 = 查过、都对得上；1 = 查过了、有变了的产物；
    2 = 没查成（路径不给 / 越界 / 文件不存在 / 核对里有读不出来的）。

    `record` 是唯一写的动作，而且先核文件后写台账 —— 一条钉不住内容的登记
    不是弱证据，是假证据（见 `agentflow.artifacts` 的模块 docstring）。

    读写：读 `artifacts` 台账与盘上文件的哈希；`record` 写一行归属，其余五个 action 只读。
    实现方式一句话：`artifacts` 模块（登记、哈希、归属查询各一处实现）。
    """
    from . import artifacts as A

    root = args.root
    action = args.action
    targets = list(args.target or [])

    if action == "record":
        if len(targets) != 1:
            print("[artifacts] 没查成：record 只收一个路径", file=sys.stderr)
            return 2
        if not args.producer.strip():
            print("[artifacts] 没查成：record 必须给 --producer（不知道是谁产的，"
                  "这条登记没有归属可言）", file=sys.stderr)
            return 2
        try:
            entry = A.record(root, path=targets[0], producer=args.producer, kind=args.kind,
                             task_id=args.task_id, exit_code=args.exit_code, note=args.note)
        except A.ArtifactError as e:
            print(f"[artifacts] 拒收：{e}", file=sys.stderr)
            return 2
        print(tty.bullet(f"已登记 {entry['path']} ← {entry['producer']}"
                         f"（{entry['kind']}，{entry['bytes']} 字节，{entry['sha256'][:16]}）"))
        return 0

    if action == "owners":
        if len(targets) != 1:
            print("[artifacts] 没查成：owners 只收一个路径", file=sys.stderr)
            return 2
        try:
            rows = A.owners_of(root, targets[0])
        except A.ArtifactError as e:
            print(f"[artifacts] 没查成：{e}", file=sys.stderr)
            return 2
        if not rows:
            print(tty.bullet(f"{targets[0]} 在台账里**没有**归属登记 —— "
                             "这不是'没人产过'，是'没人登记过'（两件事必须分开说）"))
            return 1
        for line in tty.table(("生产者", "类别", "召唤", "时刻", "sha256"),
                              [(r["producer"], r["kind"], r.get("task_id") or "—",
                                r["at"], str(r["sha256"])[:16]) for r in rows]):
            print(line)
        return 0

    if action == "unowned":
        if not targets:
            print("[artifacts] 没查成：unowned 至少要给一个路径（目录会被展开成里面的文件）",
                  file=sys.stderr)
            return 2
        files: list[Path] = []
        for t in targets:
            p = Path(t)
            if not p.is_absolute():
                p = Path(str(root)) / p
            if p.is_dir():
                files += [q for q in sorted(p.rglob("*")) if q.is_file()]
            elif p.is_file():
                files.append(p)
            else:
                print(f"[artifacts] 没查成：{t} 既不是文件也不是目录", file=sys.stderr)
                return 2
        try:
            missing = A.unowned(root, files)
        except A.ArtifactError as e:
            print(f"[artifacts] 没查成：{e}", file=sys.stderr)
            return 2
        print(tty.bullet(f"查了 {len(files)} 个文件，其中 {len(missing)} 个**没有**归属登记"))
        for m in missing:
            print(tty.bullet(m))
        return 1 if missing else 0

    if action == "list":
        rows = A.list_artifacts(root, producer=args.producer or None,
                                task_id=args.task_id or None, kind=args.kind or None)
        if not rows:
            print(tty.bullet("台账里没有匹配的记录 —— 目录里没有台账文件也是这一种"
                             "（'还没登记过'，不是'登记过、没问题'）"))
            return 0
        for line in tty.table(("路径", "生产者", "类别", "召唤", "sha256"),
                              [(r["path"], r["producer"], r["kind"], r.get("task_id") or "—",
                                str(r["sha256"])[:16]) for r in rows]):
            print(line)
        return 0

    if action == "report":
        text = A.render_markdown(root)
        if args.out:
            out_path = Path(args.out)
            if not out_path.is_absolute():
                out_path = Path(str(root)) / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text, encoding="utf-8", newline="\n")
            print(tty.bullet(f"已写 {args.out}（{len(text.encode('utf-8'))} 字节）"))
        else:
            print(text)
        return 0

    # ---- verify（默认动作）
    records, bad = A.read_ledger(root)
    checks = A.verify_entries(root, records)
    counts: dict[str, int] = {}
    for c in checks:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    bad_statuses = ("changed", "missing", "unreadable", "not_a_file")
    if not records and not bad:
        print(tty.bullet("台账里一条记录都没有 —— **没查成**，不是'都对得上'"
                         "（先 `artifacts record` 登记，别把空台账读成绿灯）"))
        return 2
    for c in checks:
        if c["status"] in bad_statuses:
            print(tty.bullet(f"{c['status']}：{c['path']}"
                             f"（台账 {c['sha256'][:16] or '—'} / 盘上 {c['sha256_now'][:16] or '—'}）"))
    for b in bad:
        print(tty.bullet(f"台账坏行：{b}"))
    print(tty.bullet(f"核对 {len(checks)} 条：{counts}；坏行 {len(bad)}"))
    if bad or any(counts.get(s) for s in bad_statuses):
        return 1
    return 0


def cmd_project(args) -> int:
    """项目式用法：一个项目一个文件夹（`projects/project1`…），冷/热启动按文件夹在不在。

    为什么把它做成一个动词而不是让人记一串 `--root`：项目工作区、本地书架、
    冷热启动这三件事是一起被用到的（"在这个项目上、用这些书、接着上次跑"），
    拆成散参数就会出现"库指到 A、产物写到 B、书来自 C"这种没人能复核的组合。

    这里是唯一把 `--projects-dir` 与 `--start` 翻译成动作的地方；
    真正的判定与执行在 `agentflow.projects`（那里有它自己的负控自检）。

    读写：读写 `projects/<名字>/` 下那一整套工作区：`list` / `plan` 只读，`run` / `create` 会建目录、写表、落报告。
    实现方式一句话：`projects` 模块（`list_projects` / `project_plan` / `run_project` / `create_project`）。
    """
    from . import projects as P

    root = P.projects_dir(args.projects_dir)
    try:
        if args.action == "list":
            rows = P.list_projects(root)
            print(tty.paint(f"projects 落点 {root}", "grey"))
            if not rows:
                print(tty.bullet("还没有任何项目；第一次跑会自动取 project1。"))
            else:
                for line in tty.table(
                    ("项目", "状态", "冷/热", "上次", "说明"),
                    [(r["name"], _state_badge(r["state"]), f"{r['cold_runs']}/{r['warm_runs']}",
                      str(r["last_mode"] or "-"), r["why"]) for r in rows],
                    aligns=("left", "left", "right", "left", "left"),
                ):
                    print(line)
            return 0

        if args.action == "create":
            if not args.paper:
                print("[project] 没查成：`create` 要 `--paper <那篇外部论文>`"
                      "（它是这个项目的输入；不给就不知道该铺什么）", file=sys.stderr)
                return 2
            res = P.create_review_project(root, paper=args.paper, name=args.name)
            seeded = res["seeded"]
            for line in tty.panel(
                f"建好项目：{res['project']['name']}",
                [("落点", res["project"]["path"]),
                 ("只读基线", ", ".join(seeded["source"])),
                 ("可改正文", seeded["manuscript"] or "(还没写：G 的活)")],
                body=[seeded["note"] or "论文已铺好：source/ 只读，out/paper/main.tex 可改。",
                      "下一步：`agentflow --root <工作区> run-agent M --task …` 派活。"],
                tone="green",
            ):
                print(line)
            return 0

        if args.action == "plan":
            info = P.plan(root, args.name, start=args.start, books_dir=args.books,
                          topic=args.topic or "")
            pj = info["project"]
            print("")
            for line in tty.panel(
                f"计划：{pj['name']}",
                [("会新建文件夹吗", "会（冷启动）" if info["will_create"] else "不会（热启动，复用）"),
                 ("判据", f"请求 {pj['requested']} ⇒ 判定 {tty.badge(pj['mode'])}（{pj['reason']}）"),
                 ("本地书架", info["books_dir"] or "(没给 --books)"),
                 ("主题", info["topic"] or "(没给 --topic ⇒ 只登记、不调模型)")],
                body=[info["note"], "这一步只说明会怎么做，不写任何字节。"],
                verbatim=[("落点：", pj["path"]), ("产物目录：", f"out/run-{info['run_index']}")],
                tone="cyan",
            ):
                print(line)
            return 0

        # ---- run 那一档走统一执行体（`draft/145` §3.2）：旗标归一、预检、预算落盘、
        # Lean 三档这几个关口都在 `_run_spec` 里，这里只剩"交给它"。
        return _run_spec(_spec_from(args, mode=MODE_PROJECT, origin="project run"), args)
    except (P.ProjectExists, P.ProjectMissing, P.ProjectNotAWorkspace) as exc:
        # 三态：这三条都是"这一步没做成"（用法/前提不满足），不是"跑过了、结论是失败"。
        print(f"[project] 没查成：{exc}", file=sys.stderr)
        return 2


def _exec_project(spec: RunSpec, args) -> int:
    """原 `cmd_project` 的 run 那一档（形状逐字保留；差异只有 `--lean` 改从
    `RunSpec` 取，以及项目落点由 `RunSpec` 归一后的 `--projects-dir` 决定）。"""
    from . import projects as P

    root = P.projects_dir(getattr(args, "projects_dir", None))
    try:
        # ---- 第一屏：Lean 工具链开机自检（与 `run-agent` / `run` 同一档，业主 2026-10-22）。
        lean_reading = _lean_first_screen(root)
        res = P.run_project(
            root, name=spec.project_name, start=spec.project_start, topic=spec.task or "",
            books_dir=getattr(args, "books", None),
            books_limit=getattr(args, "books_limit", None),
            budget_usd=getattr(args, "budget_usd", None),
            max_calls=getattr(args, "max_calls", 2),
            retrieval_limit=getattr(args, "retrieval_limit", 7),
            fulltext=not bool(getattr(args, "no_fulltext", False)),
            extract=bool(getattr(args, "extract", False)),
            extract_rounds=getattr(args, "extract_rounds", 1),
            # `--lean` 三档已经在 `_run_spec` 里归一成 `lean_enabled` 这一格：改前这里
            # 写的是 `bool(args.lean)`，而 `--lean off` 会让 `bool("off")` 为真。
            lean=bool(getattr(args, "lean_enabled", False)),
            # 显式额度这一格：`run_project` 在"建好工作区、还没花钱"那一刻把它落盘
            # （那里是唯一正确的时刻 —— 见 `_land_budget` 的注释）。
            budget_usd_explicit=spec.budget_usd_given,
            now=getattr(args, "now", None),
            # 不给就由 `run_project` 用项目根下的 `.fulltext/`（T0-6 的默认）
            text_store_dir=getattr(args, "text_store_dir", None),
        )
    except P.BudgetNotLandable as exc:
        # 显式额度没落进寄存器 ⇒ 一个字节都不往下走（拿旧额度接着跑等于让它静默压过 flag）。
        print(f"[project] 没查成：{exc}", file=sys.stderr)
        return 2
    except (P.ProjectExists, P.ProjectMissing, P.ProjectNotAWorkspace) as exc:
        # 三态：这三条都是"这一步没做成"（用法/前提不满足），不是"跑过了、结论是失败"。
        print(f"[project] 没查成：{exc}", file=sys.stderr)
        return 2

    landing = res.get("budget") or {}
    if landing.get("ok"):
        _budget_notice(landing.get("before_usd"), landing.get("after_usd"),
                       str(landing.get("path") or ""),
                       stream=(sys.stderr if bool(getattr(args, "json", False)) else None))

    pj, run, result = res["project"], res["run"], res["result"]
    emit = print
    emit("")
    for line in tty.panel(
        f"项目 {pj['name']}",
        [("本次启动", f"{tty.badge(pj['mode'])}  {pj['reason']}")],
        verbatim=[("落点：", pj["path"]),
                  ("产物目录：", run.get("out_dir") or "(本次没跑模型那一步)")],
        tone="cyan",
    ):
        emit(line)

    ing = run.get("ingest") or {}
    if ing:
        counts = ing.get("counts") or {}
        emit("")
        for line in tty.rule("本地书架"):
            emit(line)
        rows = [(k, str(v)) for k, v in counts.items() if v or k in ("ingested", "already_present")]
        for line in tty.table(("登记结局", "本数"), rows, aligns=("left", "right")):
            emit(line)
        # 这两个数只覆盖"本次真的处理过的那几本"：热启动时全部 already_present，
        # 于是它们会是 0 —— 那不是"这些书没有文本层"，所以必须写清口径。
        emit(tty.bullet(
            f"本次处理的书里：有文本层 {ing.get('text_layer_ok')} 本 / 共 {ing.get('pages_total')} 页"
            f"（已登记的 {counts.get('already_present', 0)} 本没有重抽，故不计入）"))

    ex = run.get("extraction") or {}
    if ex:
        emit("")
        for line in tty.rule("模型读书（概念 / 关系，引文逐字回验）"):
            emit(line)
        if ex.get("error"):
            emit(tty.bullet(tty.paint(f"失败：{ex['error']}", "red")))
        else:
            for line in tty.table(
                ("读数", "值"),
                [("读懂的书", ex.get("processed")),
                 ("失败的轮次", ex.get("failed")),
                 ("新建概念", ex.get("concepts_created")),
                 ("新增关系", ex.get("relations_added")),
                 ("引文过验", ex.get("quotes_verified")),
                 # 这两行是两个阶段，不是一个数的两种说法：
                 # `relations_dropped` = 模型的引文在原文里根本找不到（抽取阶段就丢了）；
                 # `quotes_failed` = 活到落库那一步、带页码窗口的回验没过。
                 # 只打后者会让"日志里剔了 7 条、框里写 0"同时出现在一份输出里。
                 ("抽取阶段剔除", ex.get("relations_dropped")),
                 ("引文未过（已剔除）", ex.get("quotes_failed")),
                 ("无法判定", ex.get("quotes_unknown"))],
                aligns=("left", "right"),
            ):
                emit(line)
            if ex.get("relations_dropped"):
                # 这里不用 Markdown 的星号强调：`tty` 那一层不做 Markdown 渲染，
                # 星号会原样打到终端上（要强调就用 `tty.paint`，或把话写进句子里）。
                emit(tty.bullet(
                    "「抽取阶段剔除」="
                    + tty.paint(str(ex.get("relations_dropped")), "bold")
                    + " 指的是：模型给的关系里有这么多条的引文在原文里逐字找不到"
                    "（详见下面的剔除原因与日志）—— 它们没有进库，所以"
                    "「新增关系 + 抽取阶段剔除」才是模型一共提了多少条关系"))
                why = _summarize_drop_reasons(ex.get("drop_reasons"))
                if why:
                    emit(tty.bullet("剔除原因：" + tty.paint(why, "yellow")))
            for err in (ex.get("errors") or [])[:5]:
                emit(tty.bullet(tty.paint(json.dumps(err, ensure_ascii=False, default=str)[:150], "yellow")))
            mdl = ex.get("model") or {}
            if mdl:
                # 这一步的花销不在 `--budget-usd` 的口径里（那个额度是主题作答那一跑的），
                # 所以必须单独打出来 —— 否则"预算没超"会被读成"这次没花多少钱"。
                emit(tty.bullet(
                    f"这一步的模型花销 {tty.paint(str(mdl.get('charged_usd')) + ' USD', 'bold')}"
                    f" / {mdl.get('calls')} 次调用 / tokens in {mdl.get('tokens_in')} "
                    f"out {mdl.get('tokens_out')}（不在 --budget-usd 的额度里："
                    "那个额度只管主题作答那一跑，这里的上界是轮数=本数）"))
                if mdl.get("uncharged_calls"):
                    emit(tty.bullet(tty.paint(
                        f"其中 {mdl['uncharged_calls']} 笔没有入账（meter 未接线或判重放）"
                        "—— 那不是 0 元，是没记上", "yellow")))
            if ex.get("store_counts"):
                emit(tty.bullet(f"库里现在：{ex['store_counts']}"))

    for n in run.get("notes") or []:
        emit(tty.bullet(tty.paint(n, "yellow")))

    if result:
        emit("")
        for line in tty.panel(
            "这一跑的结果",
            [("退出码", f"{_exit_badge(result.get('exit_code'))}（{result.get('reason')!r}）"),
             ("模型调用", f"{result.get('calls')} 次 / 本次花费 {result.get('spent_usd_this_run')} USD"),
             ("Lean", _lean_evidence_text(result.get("lean") or {}, lean_reading)),
             ("六件产物", ", ".join(result.get("artifacts") or []) or "(无)")],
            verbatim=[("产物目录：", run.get("out_dir") or "(无)")],
            tone="green" if result.get("exit_code") == 0 else "yellow",
        ):
            emit(line)
    else:
        print("[project] 本次没有跑模型那一步（没给 --topic）")
    return int(result.get("exit_code", 0)) if result else 0


# ---------------------------------------------------------------- 交互台

#: 主菜单：(按键, 说明, 处理函数名)。每一项都收 `(ask, out)` 两个口子（缺省 `input`/`print`），好让整台菜单能用
#: 脚本化输入在测试里驱动、不必真占一个终端（判据一律要能离线、确定性地跑）。
#: ---- 废案留痕（`R8`-A-1；出处 `draft/65` §2 与 `draft/65a` §A-1）----
#: 原先第 5 项是"离线自检"：`MENU` → `SHELL_ACTIONS["5"]` → `_shell_demo` → `main(["demo", "--keep"])`。
#: `draft/41-H:55` 把它写成设计；`demo.py` 由 `tests/test_demo_end_to_end.py` 6 条钉住（`draft/48-09:890` 的"唯一不需要 key 的端到端路径"），真机面零实例见 `draft/48-09:893`。
#: 淘汰与处置（`draft/44:95` L-04h、`draft/48-09:878-880`）：`demo.py` 不删、只从 `MENU` 摘掉入口，改为文档说明
#: `python -m agentflow.cli demo`。教训：新增主入口 X 时只加子命令、没加菜单格 ⇒ 同批把 X 加进 `MENU`，
#: 并写元判据断言 `"X" in MENU 文本`（判据在 `tests/test_r8_retired_entries.py`）。
MENU: tuple[tuple[str, str, str], ...] = (
    ("1", "项目：列出 / 计划 / 运行（冷启动或热启动）", "project"),
    ("2", "端到端跑一个主题（联网检索；需要模型 key）", "run"),
    ("3", "看数据状态 / 校验全局不变量", "status"),
    ("4", "看某个角色的工具面（只读角色看不到写工具）", "tools"),
)


def _ask_text(ask, prompt: str, default: str = "") -> str:
    """问一行自由文本；空输入就用缺省值（缺省值会显示在提示里）。"""
    tail = f" [{default}]" if default else ""
    got = str(ask(f"{prompt}{tail}: ") or "").strip()
    return got or default


def _ask_yes(ask, prompt: str, *, default: bool = False) -> bool:
    got = str(ask(f"{prompt} ({'Y/n' if default else 'y/N'}): ") or "").strip().lower()
    if not got:
        return default
    return got in ("y", "yes", "是", "1")


def _shell_project(ask, out) -> int:
    """菜单第 1 项：项目式用法。把用户答的几件事翻成 `project run` 的 argv。"""
    out("")
    for line in tty.rule("项目"):
        out(line)
    rows = _project_rows()
    if rows:
        for line in tty.table(("项目", "状态", "冷/热", "上次"),
                              [(r["name"], _state_badge(r["state"]),
                                f"{r['cold_runs']}/{r['warm_runs']}", str(r["last_mode"] or "-"))
                               for r in rows]):
            out(line)
        out(tty.paint("  提示：输入一个已存在的项目名 = 热启动（复用它的库与产物）", "grey"))
    else:
        out(tty.paint("  还没有任何项目；第一次跑会自动取 project1。", "grey"))

    name = _ask_text(ask, "  项目名（回车 = 自动取下一个）")
    books = _ask_text(ask, "  本地书架目录（回车 = 不用本地书，例如 D:\\books）")
    topic = _ask_text(ask, "  研究主题（回车 = 只做登记与冷/热启动，不调模型）")
    if not books and not topic:
        # 三个问题全按回车 ⇒ 这一步什么都不会做，却会新建一个项目文件夹。
        # 那正是"手滑建出一堆空项目"的来源（2026-09-28 实测：一次菜单冒烟测试
        # 就这么建出了 project2，项目卡里 run-1 的 result 是 None）。
        # 缺省必须是"不建"：新建目录是不可逆的动作，不该由三次回车触发。
        if not _ask_yes(ask, "  什么都没填 —— 这会只新建一个空项目文件夹（登记 0 本、不调模型）。"
                             "确定要建吗", default=False):
            out(tty.paint("  （没有建任何东西）", "grey"))
            return 0
    argv = ["project", "run"]
    if name:
        argv += ["--name", name]
    if books:
        argv += ["--books", books]
    if topic:
        argv += ["--topic", topic]
    if books and _ask_yes(ask, "  先让模型把书读一遍（抽概念/关系，逐字回验）", default=False):
        argv += ["--extract", "--extract-rounds",
                 _ask_text(ask, "  最多读几本（一轮一本）", "7")]
    out(tty.paint("  即将执行：agentflow " + " ".join(argv), "grey"))
    out("")
    return main(argv)


def _shell_run(ask, out) -> int:
    """菜单第 2 项：联网的端到端主题跑（`agentflow run`）。"""
    out("")
    for line in tty.rule("端到端跑一个主题（联网检索）"):
        out(line)
    topic = _ask_text(ask, "  研究主题")
    if not topic:
        out(tty.paint("  没给主题 ⇒ 什么都没做（这一步没有缺省主题，编一个会让产物对不上）", "yellow"))
        return 2
    budget = _ask_text(ask, "  预算（美元，调用前检查）", "0.5")
    calls = _ask_text(ask, "  最多调用几次模型", "2")
    out("")
    return main(["run", "--topic", topic, "--budget-usd", budget, "--max-calls", calls])


def _shell_status(ask, out) -> int:
    out("")
    for line in tty.rule("数据状态"):
        out(line)
    rc = main(["status"])
    if _ask_yes(ask, "  顺便校验全局不变量（verify）", default=True):
        out("")
        rc = max(rc, main(["verify"]))
    return rc


def _shell_tools(ask, out) -> int:
    out("")
    for line in tty.rule("角色工具面"):
        out(line)
    # 业主 2026-10-22（「在Lean开关没开时隔绝L」）：这一行是用户看得见的角色名单，
    # 开关关着时不存在的角色不许出现（它会让读者以为"这个角色今天没派活"）。
    from agentflow import leanscope as _LEANSCOPE

    out(tty.paint("  可用角色：" + " ".join(_LEANSCOPE.visible_roles(S.ROLES)), "grey"))
    role = _ask_text(ask, "  角色", "H")
    out("")
    return main(["tools", "--role", role])


# `R8`-A-1 的退场点：这里原有 `def _shell_demo(ask, out) -> int:`（删于 2026-10-07）。
# 它原先只做一件事：打三行提示，然后 `main(["demo", "--keep"])`。
# `demo` 子命令原样保留（唯一不需要模型 key 的端到端路径，`tests/test_demo_end_to_end.py`
# 6 条钉住；`draft/48-09:899` 逐字"不许删 `demo.py`"）⇒ 摘掉的只是交互台的入口，
# 命令仍然可达（`python -m agentflow.cli demo`）。四块留痕见 `MENU` 上方那一段。


#: 菜单按键 -> 处理函数。键就是 `MENU` 里那个按键。
SHELL_ACTIONS = {
    "1": _shell_project,
    "2": _shell_run,
    "3": _shell_status,
    "4": _shell_tools,
    # `R8`-A-1：这里原有 `"5": _shell_demo,`（连同 `MENU` 第 5 项一起摘掉，见上方留痕）。
}


def _state_badge(state: str) -> str:
    """把项目文件夹的四态翻成徽标（`workspace` 之外的三态都是"还不能直接用"）。"""
    mapping = {"workspace": "ok", "absent": "cold", "empty": "cold", "not_a_project": "unknown"}
    return tty.badge(mapping.get(state, state))


def _project_rows() -> list[dict]:
    from . import projects as P

    try:
        return P.list_projects(P.projects_dir(None))
    except Exception:  # noqa: BLE001 - 列表读不出来不该让菜单崩掉
        return []


def shell(ask=input, out=print) -> int:
    """不带参数运行 `agentflow` 时进的那一屏：一份菜单，而不是一串用法错误。

    两个口子（`ask` / `out`）缺省是真的终端输入输出；测试传脚本化的替身。
    退出：`q` / 回车（空输入）/ EOF / Ctrl-C 都算正常退出（0）——
    "用户不想继续了"不是错误。
    """
    out("")
    for line in tty.panel(
        "agentflow · 面向数学研究的多智能体协同框架",
        [("这是什么", "主控 M 按需唤起 A–H 八个角色；产物带可复核的证据链"),
         ("先读什么", "README.md §1–§3；规范是 DEVELOPMENT.md 与 docs/ROLE-SPECS.md"),
         ("现状", "全部代码由 AI 编写，禁改区改动未经人逐行走查（见 HANDOFF）")],
        tone="cyan",
    ):
        out(line)
    out("")
    while True:
        for key, text, _fn in MENU:
            out(f"  {tty.paint(key, 'bold', 'cyan')}) {text}")
        out(f"  {tty.paint('q', 'bold', 'cyan')}) 退出")
        try:
            choice = str(ask(tty.paint("请选择", "bold") + " > ") or "").strip().lower()
        except (EOFError, KeyboardInterrupt):
            out("")
            return 0
        if choice in ("", "q", "quit", "exit", "0"):
            out(tty.paint("（退出）", "grey"))
            return 0
        action = SHELL_ACTIONS.get(choice)
        if action is None:
            out(tty.paint(f"  没有这一项：{choice!r}（可用：{'/'.join(k for k, _t, _f in MENU)}/q）",
                          "yellow"))
            continue
        try:
            rc = action(ask, out)
        except (EOFError, KeyboardInterrupt):
            out("")
            return 0
        out("")
        out(tty.paint(f"  （上一步退出码 {rc}）", "grey"))
        out("")


def _exit_badge(code: Any) -> str:
    """退出码徽标：0/1/2 对应本项目的三态，不许把 2 折成 1。

    0 = 成功产出（绿）· 1 = 查过了、发现问题（红）· 2 = 没查成（黄）。
    第一版写成 `success if code == 0 else failed`，于是"没 key ⇒ 退出码 2"被画成了
    红色的 failed —— 那正是本项目反复强调不许折叠的那一档：
    它说的是"这一次没查成"，要做的动作是去配 key 或重试，而不是去查结论。
    """
    text = str(code)
    key = {"0": "success", "1": "failed", "2": "not_checked"}.get(text, text)
    return f"{tty.badge(key)}  {text}"


#: 产品路径上造模型缝的唯一入口。测试可以 monkeypatch 它来注入替身模型
#: （这样"CLI 这条路"能在离线单测里被真跑一遍，而不是只测库层）。
def _agent_seam_factory(role: str, *, root: Path, sid: str | None, usd_budget: float | None,
                        store: Any = None):
    """按角色造一个模型缝（key 与端点一律来自环境变量）。

    `store` 给定时，缝同时把每次调用记进 `usage_ledger`（`draft/37` §64）：
    `run-agent` 这条路此前「没有任何地方记账」，钱只活在内存与会话事件里 ——
    于是账本对一次真花了 0.289069 美元的运行报"0.000000"，而按账本判上限的
    `reviewaccept.within_cost_cap` 据此报"没超上限"（假绿）。
    不给 `store` ⇒ `meter=None` ⇒ 如实报"没有入账"（不是记一笔零）。
    """
    from . import budget as B
    from .llmseam import LlmSeam
    from .tokenmeter import TokenMeter

    # `budget_of`：每一次花钱之前现读这一趟的总预算（业主 2026-10-12：
    # 「用户可追加预算，运行消耗的钱从总预算里实时扣除」）。`usd_budget`（命令行给的）
    # 是寄存器缺席时的兜底 —— 两者都在 `budget.limit_usd` 里合一，别在这里再判一次。
    read_limit = (lambda: B.limit_usd(root, fallback=usd_budget))
    meter = TokenMeter(store, budget_usd=usd_budget) if store is not None else None
    return LlmSeam.for_role(role, session_root=root, sid=sid, usd_budget=usd_budget,
                            meter=meter, budget_of=read_limit)


def _parse_drive(items) -> tuple[dict, str]:
    """把 `--drive 角色.动作` 解析成接线表；不合法就返回 `(空表, 理由)`。"""
    table: dict[tuple[str, str], dict] = {}
    for item in items or []:
        role, _, action = str(item).partition(".")
        if not role or not action:
            return {}, f"--drive 要写成 角色.动作（收到 {item!r}）"
        table[(role, action)] = {}
    return table, ""


#: 单趟 `run-agent` 的退出码分类表（业主 2026-10-19 重排；`--help`、`cmd_run_agent` 的
#: docstring、`_run_agent_exit_code` 的 docstring 三处同口径，逐档都对得上这里）。
#:
#: 域 × 码对照见 `agentflow.stop_reasons.EXIT_CODE_DOMAINS["loop"]`，全仓统一的三条口径见
#: `stop_reasons.EXIT_CODE_UNIFIED`（`R-BE1` 的 ③-6，2026-10-27）：同一个 `1` 在四条命令里
#: 含义不同，那句话只登记在那张表里，不在这里复述。
#:
#: 表体不在这里写：它与界面徽标同源于 :data:`agentflow.stop_reasons.STOP_REASONS`
#: （Q23，2026-10-26）。改前它与 `webui.server._STOP_BADGES` 各写一份，`final_refused`
#: 只进了这一边，界面于是显示一个空徽标；反方向还多一格 `max_steps`。现在这里只投影
#: `live=True` 的那一列，新增一档时两张表不可能再漏一边。
#:
#: 为什么是一张表而不是一串 `if`：这是防漏，不是风格 —— 新增一个 `stop_reason` 时若
#: 有人忘了来这张表登记，它就落进 `EXIT_CODE_WHEN_UNKNOWN`（= 1，行为异常），一次
#: 当场可见的异常；写成 `if` 链时新取值会静默落到最后的 `return 1`（1 曾经就是"其余"
#: 这一档）。判据 `tests/test_run_agent_exit_code_table.py` 从源码里现扫 `stop_reason`
#: 的取值集合与这张表对拍，少一条就红。
#: 六档：0 正常完成（给了 `final`）· 1 行为异常 · 2 研究启动失败（连跑都没开始）· 3 等待用户
#: （`--resume` 接着跑）· 4 正常且中途停止 —— 用户叫停（强停与优雅停同档）＋ 预算耗尽 · 5
#: 正常且自行停止但没有 final。
EXIT_CODE_BY_STOP: dict[str, int] = {
    reason: row[0] for reason, row in STOP_REASONS.items() if row[3]
}

#: 没登记的 `stop_reason` 一律归这里。不许改成 0：那会把"新增了一档而没人归类"
#: 读成"做完了"—— 一次新故障变成绿灯，且没有任何地方会红。
EXIT_CODE_WHEN_UNKNOWN: int = 1

#: 已知 `stop_reason` 的清单（表里登记过的那些）。
#:
#: 刻意从表派生而不是手抄第二份：手抄一份会与表两处漂移，而"两处漂移"恰恰是这条
#: 纪律想治的病。真正独立的那一腿在判据里 —— 它从 `agent_loop.py` 的源码现扫
#: 生产点，与这里对拍（少一条就红）。
KNOWN_STOP_REASONS: frozenset[str] = frozenset(EXIT_CODE_BY_STOP)


def _run_agent_exit_code(run) -> int:
    """单趟 `run-agent` 的退出码：查 :data:`EXIT_CODE_BY_STOP` 那张表，不做 `if` 链。

    - `0` 正常完成（给了 final）；
    - `1` 行为异常（只留给"真出事"）；
    - `2` 研究启动失败（连跑都没开始）；
    - `3` 等待用户（人答完 --resume 接着跑）；
    - `4` 系统行为正常且中途停止（用户叫停 —— 强停与优雅停 —— ＋ 预算耗尽）；
    - `5` 系统行为正常且自行停止，但没有 final。
    为什么 4 与 5 必须分成两档：都不是异常，但下一步该谁动不同（4 是"有人叫停"：人 / 父 / 钱，加预算
    或人答完即可 `--resume`；5 是"它自己判定收工"：原地打转 / `escalated` 交给召唤者）。未登记的
    `stop_reason` 一律 1（安全侧）：落进 1 会当场被看见，落进 0 会把新故障读成"做完了"（`--help` 与 `cmd_run_agent` 的 docstring 必须同口径；业主 2026-10-19 重排）。
    """
    return EXIT_CODE_BY_STOP.get(str(getattr(run, "stop_reason", "") or ""),
                                 EXIT_CODE_WHEN_UNKNOWN)


#: 多轮驱动层（`--rounds N`）特有的结束形态 —— 它们刻意不进
#: :data:`EXIT_CODE_BY_STOP`：那张表说的是"一趟循环为什么停"，而这两个说的是
#: "多轮驱动为什么收"。混进去会让判据的生产点对拍（它扫的是 `agent_loop.py` 的
#: `LoopRun`）多出两条永远对不上的档，于是那张表就不再是"循环的口径"。
#:
#: 只有 `resumed_done` 能直接映射；`rounds` 还要读"最后那一轮有没有 final"，
#: 所以它由 :func:`_autonomy_exit_code` 单独判（见那里）。
AUTONOMY_ONLY_EXIT_CODE: dict[str, int] = {
    # 续跑完成：这一程要补的轮数在上一段已经跑完（`autonomy` 直接交回）
    "resumed_done": 0,
}


def _rounds_has_final(auto) -> bool:
    """轮数用完那一档要读的东西：最后那一轮到底有没有交出结论。"""
    reports = list(getattr(auto, "reports", None) or [])
    return bool(reports) and bool(str(getattr(reports[-1], "final", "") or "").strip())


def _autonomy_exit_code(auto) -> int:
    """多轮驱动层（`--rounds N`）的退出码：查同一张表，只多"轮数用完"这一档。

    业主 2026-10-19 裁定（这条是根因，不是特例）：同一件事不许在两处有两套口径。改前这一层自成一条
    `if` 链（`rounds`/`stop_file`/`resumed_done ⇒ 0`、`其余 ⇒ 1`），于是同一个 `budget` 在单趟是 4、
    在多轮是 1，`stop_file` 在单趟是 4、在多轮是 0 —— 两种口径都会漂，而且漂了没有任何东西会红。
    现在：所有 `stop_reason` 一律查 :data:`EXIT_CODE_BY_STOP`，未登记的落进 :data:`EXIT_CODE_WHEN_UNKNOWN`。
    表里没有、只有这一层有的两种形态：`rounds`（轮数用完）最后那一轮产出了 final ⇒ `0`；没有 final
    ⇒ `5`（正常且自行停止、但没有 final）—— 轮数用完不等于做完了，把它读成 0 会让"跑到上限但一句话
    没说"看起来像成功。`resumed_done`（续跑发现这一程已跑完）⇒ `0`（见 `AUTONOMY_ONLY_EXIT_CODE`）。
    判据：`tests/test_run_agent_exit_code_table.py::test_the_two_layers_read_the_same_table` 把同一组
    `stop_reason` 分别喂给两个入口、逐条断言退出码相等；负控把这一层改回写死 `budget ⇒ 1` ⇒ 当场红。
    """
    reason = str(getattr(auto, "stop_reason", "") or "")
    if reason == "rounds":
        return 0 if _rounds_has_final(auto) else 5
    if reason in AUTONOMY_ONLY_EXIT_CODE:
        return AUTONOMY_ONLY_EXIT_CODE[reason]
    return EXIT_CODE_BY_STOP.get(reason, EXIT_CODE_WHEN_UNKNOWN)


def _sid_suffix(sid: str | None) -> str:
    """`--sid <号>` 那一段（空 sid 就整段不出现）。

    为什么不写成 `--sid {sid or ''}`：没给 sid 时那样会打印出一个光秃秃的 `--sid`，
    人照抄会被 argparse 判成"缺少参数"（退出码 2）—— 与 `--root` 写错位置同族。
    打印给人敲的命令，必须是「照抄就能跑」的那一版。
    """
    return f" --sid {sid}" if sid else ""


def _waiting_notice(run, *, root: Path, sid: str | None) -> str:
    """停在等用户时那一行醒目提示：停在谁身上、下一步该敲什么。

    三件事逐条给出来（问题号 + 问题原文前 80 字 + 三条命令），因为这一刻的读者
    手里只有终端：只给"waiting_for_user"这个词，她还得自己去翻待答清单。

    三条命令一律把 `--root` 写在子命令「之前」：`--root` 是顶层参数，argparse 不许它
    出现在动词后面。此前这三条写在后面，实测照抄会得到
    `error: unrecognized arguments: --root …` 且退出码 2（看着像命令不存在）。
    判据 `tests/test_user_channel_stop_and_resume.py::
    test_the_commands_printed_in_the_hint_actually_run` 会把这里打出来的命令
    逐条真跑一遍，所以这条顺序不许再漂。
    """
    from . import userio as U

    qid = run.waiting_for or "（没有记到问题号）"
    text = ""
    for q in U.pending_questions(root, sid=sid):
        if q.qid == qid:
            text = q.text[:80]
            break
    sid_arg = _sid_suffix(sid)
    return (f"停在等待用户：{qid} {text}；下一步："
            f"`agentflow --root {root} inbox{sid_arg}` / "
            f"`agentflow --root {root} answer {qid} \"<回答>\"{sid_arg}` / "
            f"`agentflow --root {root} run-agent --resume …{sid_arg}`")


def cmd_run_agent(args) -> int:
    """真跑一次角色循环（顶层角色走它自己的循环；`--drive` 决定被召唤的子角色）。

    退出码是「六档」，逐档由 :data:`EXIT_CODE_BY_STOP` 那张表定（`--help` 与 `_run_agent_exit_code` 的 docstring 与这里同口径；业主 2026-10-19 重排）：
    - `0` 正常完成（`stop_reason="final"`，给了结论）；
    - `1` 行为异常（只留给"真出事"：没接线 / 模型没认 key / 没返回 / 连不上 / 输出吃光 / 坏 JSON
      超限 / 坏参数超限 / 没 notify，以及任何没登记的新 `stop_reason` —— 没登记一律归 1，安全侧）；
    - `2` 研究启动失败（检查点读不到 / 任务指纹不符 / 上一趟已收工 / 会话记录里重建不出那一步）；
    - `3` 等待用户（`ask_user` 问了人、还停在等回答；人答完（`agentflow answer`）之后用 `--resume`）；
    - `4` 系统行为正常且中途停止（用户叫停（强停与优雅停）与预算耗尽统一这一档；加预算或人答完即可 `--resume`）；
    - `5` 系统行为正常且自行停止，但没有 final（原地打转 / `escalated` 交给召唤者）。
    `--rounds N` 那条多轮路径查的是同一张表（`_autonomy_exit_code`），只多两档多轮特有形态：轮数
    用完且最后那轮给了 final ⇒ 0、没给 final ⇒ 5；续跑发现这一程已跑完（`resumed_done`）⇒ 0。
    ## 花钱的判断类能力开关：`--semantic-review`（H 的语义判据）/ `--experiment-reasoning`
    （E 的写脚本推理，S-10(a) 的 `author_script`）。两条同一条纪律：环境里有 key 也不改变行为。
    F 的攻坚推理不在这一列（2026-10-26 业主裁定：「没有默认开，这个就是F的工作方式，没有
    开关的说法」）：`--attack-reasoning` 已删除，F 出场就有缝（`host.wired_llm_conductor`
    无条件装配）。`--semantic-review` 不连带打开 E 的缝（两件事各自可解释：H 判"结论是否
    强于引文"、E 把判据写成一份能跑的脚本）。代价必须知道：E 没缝时，F 需要脚本的那一轮
    写不出来 ⇒ 落 `dead_end(缺工具)` 并上报 `missing_input`（缺的是 E 的缝）。改前它是静默的
    `no_change`（真机 `projects/mp4` 计划 000003 的 r1/r2 逐字："子目标 sg1 有判据但没有
    脚本，而 E 没能把它写出来（no_seam）⇒ 未推进"）——"有判据没脚本"与"跑了但没结果"
    在读数上从此分得开。

    这一层与 `run` / `project run` / `web` 一样只剩"翻成 `RunSpec` 再交给 `_run_spec`"
    （`draft/145` §3.2 的别名形态）；真正的执行体是 :func:`_exec_role`。

    读写：读任务与检查点；写 `tasks` / `usage_ledger` / `sessions/<sid>.jsonl` 与 `runs/` 下的运行记录（每一笔花销都进台账）。
    实现方式一句话：`agent_loop.run_role`（多轮走 `autonomy`，退出码由 `_run_agent_exit_code` 翻）。
    """
    return _run_spec(_spec_from(args, mode=MODE_ROLE, origin="run-agent"), args)


def _exec_role(spec: RunSpec, args) -> int:
    """原 `cmd_run_agent` 的执行体（形状逐字保留；差异只有 `--subagents` 那一处：
    `start --mode research` 归一成的 `spec.research` 与它同义）。"""
    from . import agent_loop as AL
    from . import autonomy as AU
    from . import host as H

    table, why = _parse_drive(getattr(args, "drive", None))
    if why:
        print(f"[run-agent] 用法错：{why}", file=sys.stderr)
        return 2
    # ---- 业主 2026-10-22（「在Lean开关没开时隔绝L」）：开关关着时没有这个角色。
    #
    # 为什么在这里挡而不是让它自己撞进装配：`host._build` 那一刻抛的是受控的
    # `leanscope.RoleHidden`，而 `run-agent` 是一个人手动敲的命令 —— 它该拿到的是一句
    # 能照着改的话 + 一个明确的退出码（2 = 用法错，与上面那条同档），不是一个栈。
    # 判定读 `leanscope`（唯一入口），关/开/读不出三档的话都由它的读数给。
    from . import leanscope as _LEANSCOPE
    from . import settings as _SET

    if _LEANSCOPE.is_hidden(str(getattr(args, "role", ""))):
        _rd = _LEANSCOPE.lean_reading()
        print(tty.paint(
            f"[run-agent] 角色 {args.role} 只在 Lean 形式化开关打开时存在："
            f"reason={_rd.reason}；{_rd.detail}。", "yellow"), file=sys.stderr)
        print(tty.paint(
            f"[run-agent] 要用它就把开关打开（{_SET.ENV_LEAN_ENABLED}=1 或设置文件 "
            f"toolchain.{_SET.LEAN_ENABLED_KEY} = true）；否则改派别的角色。", "grey"),
            file=sys.stderr)
        return 2
    if bool(getattr(args, "subagents", False)) or spec.research:
        # `--subagents`（2026-09-30）：把所有已声明的角色动作都交给模型驱动 ——
        # "各角色像主控的 subagent"这句话的部署开关。
        #
        # 为什么是一个显式开关而不是默认值：默认驱动一切会把"确定性代码"的活
        # （A 的检索编排、B 的按行整理、D 的图计算…）也换成模型调用，
        # 而 `host.DEFAULT_LLM_LOOPS` 的注释写着装配期纪律："不许因为环境里有 key
        # 就改变行为"。所以默认仍是"只跑确定性动作"，要 subagent 语义就明说。
        # 真机实测（`temp/live-collab-fanout-20260930-145743.txt`）：把确定性动作
        # `B.run_once` 交给 LLM 循环会替换掉那份确定性整理 —— 3 个 B 实例各烧
        # 7–8 步、以 bad_json_limit 收场、概念与关系一条没涨。批量消化这类活应当
        # 让角色跑确定性动作（并发由实例轴给），只把"判断类"动作交给模型。
        from . import capabilities as _C
        from . import leanscope as _LEANSCOPE
        from . import schema as _S

        # 业主 2026-10-22（「在Lean开关没开时隔绝L」）：这一串会变成"交给模型驱动"的
        # (角色, 动作) 清单 ⇒ 开关关着时不存在的角色不进这张表（否则模型会去派一个
        # 没有工具面、也没有提示词的角色）。
        for _role in _LEANSCOPE.visible_roles(_S.ROLES):
            for _spec in _C.actions_for(_role):
                table.setdefault((_role, _spec.action), {"max_steps": args.max_steps})
        print(tty.paint(f"[run-agent] --subagents：已把 {len(table)} 个 (角色,动作) 交给模型驱动"
                        "（含确定性动作 —— 那会被 LLM 循环替换，见 --help 的说明）", "bold"))
    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    # `D5`：这条命令也会 init，所以它带的开关与 `init` 逐字相同（同一个助手、同一个名字）。
    if init_workspace(st, root,
                      allow_foreign_entries=bool(getattr(args, "allow_foreign_entries", False)),
                      cmd="run-agent") != 0:
        return 2
    # 显式额度在这里落盘：工作区已经存在、还没花一分钱（见 `_land_budget` 的注释）。
    # `--json` 那一档把它打到 stderr，理由与下面那句第一屏相同（stdout 必须可解析）。
    _budget_code = _land_budget(spec, root,
                                stream=(sys.stderr if bool(getattr(args, "json", False)) else None))
    if _budget_code:
        return _budget_code
    # ---- 第一屏：Lean 工具链开机自检（业主 2026-10-22「防止用户提供虚构的lean环境」）。
    # `--json` 那一档把它打到 stderr：机器读的 stdout 必须保持可解析
    # （一条人话混进 JSON 流里，下游拿到的是解析错误而不是结论）。
    _lean_first_screen(root, stream=(sys.stderr if bool(getattr(args, "json", False)) else None))

    # ---- 停机开关的闩式快照（D19，业主 2026-10-22「用户摁停后仍开下一轮」）
    #
    # 为什么要在开跑之前读一次、而不是等轮间那一段自己读：开关是一次性信号 ——
    # 读到它的那一趟在收尾时把它撤走（`agent_loop._consume_stop_at_teardown`），
    # 于是"用户摁过停"这件事在盘上不留痕。多轮驱动层要是只在轮与轮之间问一句
    # "文件还在不在"，那么"第 1 轮读到并撤走、第 2 轮问了个空"就是必然的形态。
    #
    # 这里取到的是一份闩式快照（at / reason / force 原样带着）：它回答"开跑之前它就在"，
    # 与 autonomy 在轮间现读一次盘得到的读数合起来回答"这一趟见过那把开关没有"。
    # 三态：读不成不折成"没人叫停" —— 打到 stderr 并如实传 None（那一格的读数不完整）。
    stop_latch: dict[str, Any] = {}
    from . import stopctl as _STOPCTL

    try:
        _switch = _STOPCTL.read_stop(root)
    except Exception as exc:  # noqa: BLE001 —— 读不成 ≠ 没人叫停
        _switch = None
        print(tty.paint(f"[run-agent] 停机开关没读成（{type(exc).__name__}: {exc}）⇒ "
                        "这一趟不知道自己开跑前有没有被叫停（不折成「没人叫停」）", "yellow"),
              file=sys.stderr)
    if _switch:
        # 只带这几个键：负载里还有 `path` / `unreadable`，而这一层要的是
        # "谁在什么时候为什么按的"（`stop_reason_of` 只读 `force`）。
        stop_latch = {key: _switch.get(key)
                      for key in ("reason", "by", "force", "at", "path") if key in _switch}
        print(tty.paint(
            f"[run-agent] 停机开关在盘上：reason={stop_latch.get('reason')}、"
            f"by={stop_latch.get('by')}、force={stop_latch.get('force')}、"
            f"at={stop_latch.get('at')} ⇒ 这一趟按『按用户要求停』办", "yellow"))

    # ---- 会话身份在这一刻定下，之后整趟不再漂移（`draft/37` §63，修法 B）
    #
    # 为什么要在装配之前解析出来：`sessions.append(..., sid=None)` 的缺省值是
    # 「写入那一刻」的 `session_id()`（环境变量优先，否则当天日期）。此前 `run-agent`
    # 把 `sid=None` 一路传下去，于是"这一趟是哪一段会话"谁都没说清 ——
    # 运行内 `conductor.closing` 按缺省读，读到的可能不是这一趟写的那一段：
    # 实测第 11 趟（`--sid real11`）运行内报 `can_close: true`，而外部带 sid 的
    # 读数报 `failed: ['user_pending']` —— 假绿，且只在运行内出现。
    # 解析一次、之后原样带下去，工具面与写入面读的就是同一个文件；
    # 顺带把"跨零点的一趟会被劈成两个会话文件"这件事也去掉了
    # （缺省 sid 按天，而一趟可以有 3600 秒墙钟）。
    from . import sessions as SS

    if not getattr(args, "sid", None):
        args.sid = SS.session_id()

    def seam_for(role_name: str):
        """按角色名造一条接模型的缝（复用本次的 root / sid / 预算 / store）。

        为什么要闭包而不是每处各传一遍：这几个参数在一条命令里是常量，
        而参数一多，某一条召唤路径漏传一个就会静默换掉账本落点（`store`）
        或会话号 —— 症状是"跑起来了但账落在别处"，没有任何地方会报错。
        """
        return _agent_seam_factory(role_name, root=root, sid=args.sid,
                                   usd_budget=args.budget_usd, store=st)

    seam = seam_for(args.role)
    if not seam.wired:
        # 2026-10-19 口径：2 = 研究启动失败（连跑都没开始）。这句里刻意不再出现"没查成"
        # —— 同一句话里两种标签并存时，读的人会拿旧的那一种去解释 2。
        print("[run-agent] 研究启动失败：没有接模型（环境变量 AGENTFLOW_MODEL_API_KEY 与 "
              "agentflow/settings.json 的 model.api_key 都没有值）—— "
              "这是研究启动失败（退出码 2），不是「跑过了没问题」", file=sys.stderr)
        return 2

    loops = {key: {"max_steps": args.max_steps} for key in table}
    # ---- A 的检索后端（2026-09-30 修）
    #
    # 为什么必须在这里建：`wired_llm_conductor` 一直收 `providers=`，但从来没有人传 ⇒
    # `_Builder.status()` 把 A 判成 `no_provider`、A 不进登记表 ⇒ 任何角色唤起 A 都落
    # `refused/not_wired`。真机实测（`draft/28` §201）：G 明明按协议唤起了 A，
    # 拿回来的却是"A 没有接线（registry 里没有它）"—— 文献检索这条最重要的协同边
    # 在协同运行里从来就没接上过。用户口径："A 的文献检索必须要通关。"
    #
    # 口径与 `run-a` 逐字一致（`cmd_run_a` 那三行）：先看 `--provider`，再看配置里的
    # `agent_a.providers`，都没有才用 openalex。不一致的默认值本身就是"凌乱"的一种，
    # 所以这里刻意复用同一段逻辑（`_build_providers`）而不是再写一遍。
    # `args` 在测试里常是手搭的 `Namespace`（那些用例只关心循环本身），所以三个新参数
    # 一律 `getattr(..., None)` 取 —— 缺了就当"没给"，而不是让整个 `run-agent` 崩在属性上。
    cfg = load_config(root, getattr(args, "config", None))
    prov_names = (str(args.provider).split(",") if getattr(args, "provider", None)
                  else (cfg.get("agent_a") or {}).get("providers", ["openalex"]))
    providers = _build_providers(cfg, list(prov_names), root)
    # 墙钟可配（`draft/37` §16 P0）：不给 `--wall-clock-sec` 时用 `Policy` 的缺省值，
    # 于是"这次运行能给多久"从写死的 900 秒变成一个显式参数。
    from .policy import Policy

    wall = getattr(args, "wall_clock_sec", None)
    # 2026-10-18（缺陷 ⑳，业主口径「墙钟可以干脆不设」）：`--wall-clock-sec 0` ⇒ 不设上限。
    # 真机证据（`projects/t2y`，T2）：我没有传这个参数，于是用了 `default=3600.0`，
    # 1 小时整被切断 —— 而切断的那一刻 M 正要派 B 去登记命题：
    #   t-000009 E ← refused「墙钟截止已过（wall_clock_sec=3600.0）」
    #   t-000010 B ← refused 同上
    # 结果就是 `conjectures 3 / statements 0`：研究工作做完了，收尾那一步被墙钟砍掉。
    # 0（或负数）显式表示"不设上限"，与"我没传"区分开（后者仍走缺省 3600）。
    if wall is not None and float(wall) <= 0:
        wall = None
    # `Policy.usd_budget` 必须拿到同一个数（业主 2026-10-12 的预算轴；只读调查发现
    # 这一格此前从来没被灌过 —— 改前 `Policy(wall_clock_sec=wall)`，
    # 于是 `conductor` 那个全局 meter 的 `budget_usd=None`、
    # 「编排层的全局 USD 守卫实际不受 --budget-usd 约束」）。
    # 与别处同一条取值口径：命令行给的数 > 无（不限）—— 寄存器那一档由
    # `budget.limit_usd` 在每一次闸门上现读，不在这里预先合并。
    usd_cap = getattr(args, "budget_usd", None)
    pol = Policy(wall_clock_sec=wall, usd_budget=usd_cap) if wall is not None \
        else Policy(usd_budget=usd_cap)
    # `--stop-file` 接给谁（`draft/37` §125）：「单趟」那一档接进步循环（它此前根本
    # 没有停机点 —— 真机实测：用户叫停后继续跑完 60 多个任务、烧掉 $0.98，最后被强杀，
    # 台账里没有 `agent_run_end`、盘上没有步检查点）；多轮自主跑那一档照旧由
    # `autonomy._stop_before_round` 在「每轮之间」查，两处不叠加（避免"一轮跑到一半
    # 停下"把那一轮的汇报与检查点弄成半截）。
    multi_round = bool(args.rounds and args.rounds > 1)
    wiring = H.wired_llm_conductor(st, loops=loops, session_root=root, sid=args.sid,
                                   max_steps=args.max_steps, usd_budget=args.budget_usd,
                                   workspace_root=str(root), seam_factory=seam_for,
                                   providers=providers, config=cfg, policy=pol,
                                   semantic_review=bool(getattr(args, "semantic_review", False)),
                                   experiment_reasoning=bool(
                                       getattr(args, "experiment_reasoning", False)),
                                   stop_file=(None if multi_round
                                              else getattr(args, "stop_file", None)))
    if not providers:
        # 三态：A 这条路这一轮是没接线（不是"没有文献"）。说清楚，别让人去猜。
        print(tty.paint(
            "[run-agent] 注意：A 没有接任何检索后端 ⇒ 唤起 A 会如实落 refused/not_wired"
            "（想离线验证就用 --provider fixture）", "yellow"))
    if args.rounds and args.rounds > 1:
        auto = AU.run_autonomous(args.role, args.task, store=st, registry=wiring["registry"],
                                 conductor=wiring["conductor"], session_root=root,
                                 seam=seam, rounds=args.rounds, report_every=args.report_every,
                                 usd_budget=args.budget_usd, max_steps=args.max_steps,
                                 sid=args.sid, from_env=False, resume=bool(args.resume),
                                 stop_file=args.stop_file,
                                 # D19：开跑之前那一份闩式快照（开关是一次性信号，
                                 # 读到它的那一趟收尾时会把它撤走 —— 只看盘必然读漏）。
                                 stop_latch=(stop_latch or None),
                                 user_timeout_sec=getattr(args, "user_wait_sec", None))
        print(tty.paint(f"角色 {args.role} 自主跑完 {auto.rounds_done} 轮"
                        + (f"（其中 {auto.resumed_from} 轮是上一段做过的）"
                           if auto.resumed_from else ""), "bold"))
        print(f"  检查点：{auto.checkpoint}")
        for rep in auto.reports:
            print(f"  第 {rep.index} 轮：{rep.stop_reason}"
                  f"{'（汇报已发公共频道）' if not rep.report_sent else '（汇报未发出：' + rep.report_sent + '）'}")
        print(f"  停止原因：{auto.stop_reason}；用量：{auto.spend}")
        for note in auto.notes:
            print(f"  注：{note}")
        # 退出码：同一张表（业主 2026-10-19 裁定；改前这一层自成一条 if 链，
        # 于是 `budget` 单趟 4 / 多轮 1、`stop_file` 单趟 4 / 多轮 0 —— 两套口径都会漂）。
        # 只有"轮数用完"（`rounds`）要看最后那一轮有没有 final，见 `_autonomy_exit_code`。
        # `checkpoint_mismatch`（拿 A 的进度续 B）同样查表 ⇒ 2 研究启动失败，
        # 不是"跑过了有问题" —— 它不再需要一条自己的分支。
        code = _autonomy_exit_code(auto)
        # ---- 按用户要求停（D19）：这一档在改前根本走不到 —— 多轮那一层从「读盘」到
        # 「上一轮的理由码」三层都断了，于是用户摁停之后第 2 轮照开。现在它停在这里，
        # 并且这一行的三个读数就是那条判据的可见面：停在第几轮、开关上写着谁按的、
        # `runs/stop-history.jsonl` 记了没有。
        if auto.stop_reason in _STOPCTL.USER_STOP_REASONS:
            last = auto.reports[-1] if auto.reports else None
            switch = {}
            try:
                cp = json.loads(AU.checkpoint_path(root, args.role).read_text(encoding="utf-8"))
                switch = dict(cp.get("stop_switch") or {})
            except (OSError, ValueError):
                switch = {}
            print(tty.paint(
                f"[run-agent] 按用户要求停（{auto.stop_reason}）：跑完第 "
                f"{last.index if last else 0}/{args.rounds} 轮之后没有再开下一轮。"
                f"开关：reason={switch.get('reason')}、by={switch.get('by')}、"
                f"force={switch.get('force')}、at={switch.get('at')}；"
                f"审计：{root / 'runs' / 'stop-history.jsonl'}（level={auto.stop_reason}）。"
                "要继续做就 `--resume` 接着跑（那一停是上面那一趟的，不会带到下一趟）；"
                "要撤掉盘上可能残留的那把开关用 `agentflow stop --clear`。", "bold"))
            return code
        # 停在等用户（`draft/37` §72）：自主多轮那一层的停止判据现在有这一档了 ——
        # 上一轮停在等用户、而那个问题「还挂着」时，它不会开下一轮（`autonomy.py`
        # 的 `_stop_before_round`，判据在 `tests/test_resume_after_answer.py`）。
        # 退出码与单趟同档：3 = 停在等待用户（既不是完成也不是失败）。
        if auto.stop_reason == "waiting_for_user":
            pending = [r.index for r in auto.reports if r.stop_reason == "waiting_for_user"]
            print(tty.paint(
                f"[run-agent] 停在等待用户：第 {pending} 轮问了人、还停在等回答 —— "
                "后续轮次**没有**再开（不许替人把取舍定了）。"
                f"用 `agentflow --root {root} inbox{_sid_suffix(args.sid)}` 看，"
                f"答完再用 `--resume` 接着跑。", "bold"))
            return code
        # 已上报召唤者（`conductor.escalate`，业主 2026-10-19「父子天然双向」）：
        # 多轮驱动这一层的停止理由是从最后一轮抄上来的（`autonomy._stop_before_round`），
        # 所以它也会是 `escalated`。退出码从同一张表取（`EXIT_CODE_BY_STOP`），
        # 不在这里另写一个 5 —— 两处各写一个数字正是本文件已经治过的那种漂移。
        if auto.stop_reason == "escalated":
            print(tty.paint(
                "[run-agent] 已上报召唤者：最后一轮把孩子卡住的那件事写进了父的收件箱，"
                "后续轮次**没有**再开（不许替父把判断定了）。"
                "等父处理完再 `--resume` 接着跑。", "bold"))
            return code
        return code

    run = AL.run_role(args.role, args.task, store=st, registry=wiring["registry"],
                      conductor=wiring["conductor"], seam=seam, session_root=root,
                      workspace_root=str(root), sid=args.sid, max_steps=args.max_steps,
                      usd_budget=args.budget_usd, from_env=False,
                      user_timeout_sec=getattr(args, "user_wait_sec", None),
                      ask_policy=("unattended" if bool(getattr(args, "no_ask", False)) else None),
                      # `draft/37` §125：单趟这一档把停止开关接进步循环（多轮那一档
                      # 由 autonomy 在每轮之间查，两处不叠加）。
                      stop_file=(str(getattr(args, "stop_file", "") or "")
                                 if not multi_round else ""),
                      resume=bool(getattr(args, "resume", False)))
    code = _run_agent_exit_code(run)
    if args.json:
        print(json.dumps(run.to_dict(), ensure_ascii=False, indent=2, default=str))
        if code == 3:
            # JSON 那一份必须保持可解析 ⇒ 那行醒目提示走 stderr
            print(_waiting_notice(run, root=root, sid=args.sid), file=sys.stderr)
        return code
    print(tty.paint(f"角色 {args.role} 的循环：{run.stop_reason}", "bold"))
    for step in run.steps:
        print(f"  [{step.index}] {step.shape}"
              + (f"：{json.dumps(step.payload, ensure_ascii=False, default=str)[:160]}" if step.payload else "")
              + (f"  ⇒ {step.problem}" if step.problem else ""))
    if run.final:
        # 停在等用户那一档不截断：这条结论里带的是「下一步该敲什么」，
        # 而工作区路径一长，400 字就会把它切在半个命令上（实测：切在
        # `…\AppData\Lo`）—— 而人恰恰要照抄这几条命令。其余各档照旧截断。
        text = run.final if run.stop_reason == "waiting_for_user" else run.final[:400]
        print(f"  结论：{text}")
    print(f"  唤起：{run.summons}；留言：{run.messages_sent}；用量：{run.spend}")
    if code == 3:
        print(tty.paint(_waiting_notice(run, root=root, sid=args.sid), "bold"))
    if code == 2:
        print(tty.paint(f"[run-agent] 没查成：{run.final}", "yellow"), file=sys.stderr)
    return code


def _ago(stamp: str) -> str:
    """一个时间戳距现在多久（人话）；读不出来时如实说读不出来。

    为什么这个读数值得占一列：人打开 `inbox` 最想先知道的是"它等了多久" ——
    等了 3 秒与等了 3 小时，下一步的动作完全不同（再等等 vs 去答）。
    """
    from datetime import datetime

    raw = str(stamp or "").strip()
    if not raw:
        return "（没有时间戳）"
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return f"（时间戳读不出来：{raw[:20]}）"
    now = datetime.now(when.tzinfo) if when.tzinfo is not None else datetime.now()
    delta = (now - when).total_seconds()
    if delta < 0:
        return f"未来 {abs(delta):.0f} 秒（时间戳比现在晚）"
    for limit, unit, div in ((60, "秒", 1), (3600, "分钟", 60), (86400, "小时", 3600)):
        if delta < limit:
            return f"{delta / div:.0f} {unit}"
    return f"{delta / 86400:.0f} 天"


def _option_text(option: Any) -> str:
    """一个选项渲染成一栏：`label — description`（没有说明就只给 label）。"""
    label = str(getattr(option, "label", "") or "")
    description = str(getattr(option, "description", "") or "")
    return f"{label} — {description}" if description else label


def _latest_run_stop(root: Path, *, sids: list[str] | None = None) -> str:
    """最近一趟的停止理由（读最新的 `agent_run_end` 事件）；读不到就说读不到。

    为什么它跟着"没有待回答的问题"一起打印：人打开 `inbox` 最常问的两句话是
    "它在等什么"与"它跑完了吗"。前一句由待答清单回答，后一句只有
    `agent_run_end` 里的 `stop_reason` 回答得出来 —— 而"什么都没有"这个输出
    对第二句话是不回答的（读者会把它读成"没事发生"）。
    """
    from . import sessions as SS

    want = list(sids) if sids else [str(r.get("sid") or "") for r in SS.list_sessions(root)]
    best: tuple[str, str, dict] | None = None
    for sid in want:
        if not sid:
            continue
        events, _problems = SS.read_session(root, sid=sid)
        for event in events:
            if event.get("kind") != "agent_run_end":
                continue
            ts = str(event.get("ts") or "")
            if best is None or ts >= best[0]:
                best = (ts, sid, event)
    if best is None:
        return ("最近一趟的停止理由：读不到（这些会话里没有 agent_run_end 事件 —— "
                "要么还没跑过，要么会话记录被挪走了）")
    ts, sid, event = best
    waiting = str(event.get("waiting_for") or "")
    extra = f"，停在等 {waiting}" if waiting else ""
    return (f"最近一趟（会话 {sid}，角色 {event.get('role')}，{ts}）的停止理由："
            f"{event.get('stop_reason')}（步数 {event.get('steps')}）{extra}")


def cmd_inbox(args) -> int:
    """列出等着用户回答的问题（只读）。

    不给 `--sid` 时扫这个工作区的「所有」会话。为什么面板是全局的：提问正阻塞着
    某一趟运行，而那一趟的会话可能不在人当前看的地方 —— 只在某一个会话里给入口，
    就会在它正阻塞模型的时候恰好不可达（这条界面纪律抄自 DSH 的 `dsh-client-ui-user-questions`，
    而它在我们自己的结构里同样成立：`DESIGN-CONDUCTOR.md` §1.1「用户只对主控说话」，
    所以人需要一个不挑会话的入口）。而真机每一趟都有自己的 sid ⇒ 只看缺省会话
    会把"它在等什么"读成"没有待答"。
    退出码 0 = 查过了（有待答与没有待答都算查过了）。

    读写：只读 `questions` / `user_answer` 与 `sessions/*.jsonl`（一个字节都不写）。
    实现方式一句话：`userio.pending_questions`（按会话扫，缺省扫全部会话）。
    """
    from . import userio as U

    root = Path(args.root or DEFAULT_ROOT).resolve()
    sid = getattr(args, "sid", None)
    sids = [sid] if sid else U.session_ids_with_questions(root)
    rows = [(s, q) for s in sids for q in U.pending_questions(root, sid=s)]
    if args.json:
        print(json.dumps([{**q.to_dict(), "sid": s} for s, q in rows],
                         ensure_ascii=False, indent=2, default=str))
        return 0
    if not rows:
        print(tty.bullet("没有待回答的问题。"))
        print(tty.bullet(_latest_run_stop(root, sids=sids or None)))
        return 0
    for line in tty.table(("会话号", "问题号", "谁在问", "问了多久", "问题", "选项"),
                          [(s, q.qid, q.role, _ago(q.ts), q.text[:60],
                            "、".join(_option_text(o) for o in q.options) or "—")
                           for s, q in rows]):
        print(line)
    print(tty.bullet(f"用 `agentflow --root {root} answer <问题号> \"<回答>\"`"
                     f"（选选项用 `--select`，"
                     f"写正文用 `--custom`）回答；共 {len(rows)} 条"))
    print(tty.bullet(_latest_run_stop(root, sids=sids)))
    return 0


def cmd_answer(args) -> int:
    """代用户回答一个问题（写一条 `user_answer`）。

    「没查成」分三种，处置方向不同，所以分开报（折成一句"失败了"会让人不知道该改哪一个）：
    - 没有这个号：列出当前待答的号（它可能在别的会话里 ⇒ 用 `--sid` 指名）；
    - 已经有回答：谁、什么时候、答了什么（不许覆盖 —— 回答是 append-only 的审计面）；
    - 写失败：原样报出失败原因。
    回答内容三档来源（等价于 DSH 的回答形状）：`--select <label>`（可重复，可 0/n 个）、
    `--custom <正文>`、以及 `--text` 位置参数（等价于 `--custom`，老调用方照旧）。
    退出码：0 = 写成了；2 = 没查成（上面三种，或没给回答内容）。

    读写：读 `questions`（待答）与已写的 `user_answer`；写一行 `user_answer`（append-only，已有回答一律不覆盖）。
    实现方式一句话：唯一写口是 `userio.answer_question`。
    """
    from . import userio as U

    root = Path(args.root or DEFAULT_ROOT).resolve()
    sid = getattr(args, "sid", None)
    pend = {q.qid: q for q in U.pending_questions(root, sid=sid)}
    if args.qid not in pend:
        answered = [r for r in U.read_replies(root, sid=sid) if r["qid"] == args.qid]
        if answered:
            last = answered[-1]
            print(f"[answer] 没查成：{args.qid} 已经有回答了 —— {last['by']} 在 "
                  f"{last['ts']} 答的是「{str(last['answer'])[:80]}」⇒ 不许覆盖"
                  "（要改主意就让它再问一次：回答是 append-only 的审计面，"
                  "而续跑读的是最新那一条）", file=sys.stderr)
            return 2
        print(f"[answer] 没查成：没有 {args.qid} 这个问题"
              f"（当前待答：{sorted(pend) or '现在是空的'}）。"
              f"若它落在别的会话里，用 `agentflow --root {root} inbox` 看会话号，"
              "再用 `--sid` 指名",
              file=sys.stderr)
        return 2
    selected = [str(x) for x in (getattr(args, "select", None) or [])]
    custom = str(getattr(args, "custom", None) or "")
    legacy = getattr(args, "text", None)
    if not custom and legacy:
        custom = str(legacy)
    if not selected and not custom:
        print("[answer] 没查成：没给回答内容 —— 用 `--select <选项>`（可重复）、"
              "`--custom <正文>`，或位置参数 <正文>", file=sys.stderr)
        return 2
    problem = U.answer_question(root, qid=args.qid, selected=selected, custom=custom, sid=sid)
    if problem:
        print(f"[answer] 没写成：{problem}", file=sys.stderr)
        return 2
    question = pend[args.qid]
    print(tty.bullet(f"已回答 {args.qid}：{(custom or '、'.join(selected))[:80]}"))
    unknown = [x for x in selected if x not in question.option_labels]
    if unknown:
        # 不是错误（回答可以是自由的），但要说出来：label 与选项对不上时，
        # 模型下一趟读到的就是一句它认不出的选项 —— "照写"与"写得对"是两件事。
        print(tty.paint(f"  注意：{unknown} 不在这个问题的选项里"
                        f"（选项：{'、'.join(question.option_labels) or '（没有选项）'}）—— "
                        "已照写，但模型可能读不懂这个 label", "yellow"))
    print(tty.bullet(f"下一步：`agentflow --root {root} run-agent "
                     f"--role {question.role} "
                     f"--task \"<原任务原文>\" --resume{_sid_suffix(sid)}`"
                     "（它走的是自主多轮就再加 `--rounds N`）"))
    return 0


# ---------------------------------------------------------------- 启动自检（包内源码）
#
# 业主 2026-10-22 记下的 F8：一次误伤就能把整条 CLI 打掉 —— 批量替换把
# `{**q.to_dict(), …}` 变成 `{「q.to_dict(), …}`，于是所有子命令一起 SyntaxError。
#
# 两级，因为两级的代价差三个数量级：
#   1. `main()` 那一级（`_broken_source_notice`）：只捕 SyntaxError / ImportError，
#      0 ms。它接住的是"某个模块在运行时才 import"的那一类坏法 —— 真机里 `run` 的第一
#      件事就是 import `runflow`，所以坏在那一层时用户看到的是一条栈；
#   2. `doctor --selfcheck` 那一级（`selfcheck_package`）：显式全扫（实测
#      1078–1188 ms / 238 个文件），按 (路径, mtime_ns, size) 缓存。`compile()` 要读全文
#      再解析，而 stat 只是一次 syscall —— 这就是"想查就查、不想查就不查"的那一档。

#: 全扫的 stat 缓存：`(路径, mtime_ns, size) -> 该文件的问题清单（空 = 干净）`。
#:
#: 为什么放在内存里而不是盘上：`doctor` 是只读体检，一个"为了加速而写一个缓存文件"的
#: 体检会带来它自己的一类问题（缓存文件坏了 / 缓存属于另一个用户 / 缓存骗了人）。
#: 进程内已经够用：同一次体检里重复调用、以及判据里连着扫两次，都命得中。
_SELFCHECK_CACHE: dict[tuple[str, int, int], list[dict]] = {}


def selfcheck_package(package_dir: str | Path | None = None) -> dict:
    """全扫一个包里的每个 .py 文件，返回一份三态读数。

    返回 `{checked, files, scanned, reused, problems, ms, root, unreadable}`：

    - `problems` 非空 ⇒ 查过了、有坏文件（每条形如
      `{"file": 路径, "line": 行号, "column": 列号, "error": 原话}`）；
    - `checked=False` ⇒ 没查成（包目录都找不到）。它绝不是"干净"。
    """
    root = Path(package_dir) if package_dir is not None else Path(__file__).resolve().parent
    if not root.is_dir():
        return {"checked": False, "files": 0, "scanned": 0, "reused": 0,
                "problems": [], "ms": 0.0, "root": str(root), "unreadable": [],
                "reason": f"{root} 不是一个文件夹（连扫都没扫成）"}
    started = time.monotonic()
    problems: list[dict] = []
    unreadable: list[str] = []
    files = scanned = reused = 0
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files += 1
        try:
            stat = path.stat()
        except OSError as exc:
            unreadable.append(f"{path}（{type(exc).__name__}: {exc}）")
            continue
        key = (str(path), int(stat.st_mtime_ns), int(stat.st_size))
        cached = _SELFCHECK_CACHE.get(key)
        if cached is None:
            scanned += 1
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                unreadable.append(f"{path}（{type(exc).__name__}）")
                continue
            cached = []
            try:
                compile(source, str(path), "exec")
            except SyntaxError as exc:
                cached = [{"file": str(path), "line": int(exc.lineno or 0),
                           "column": int(exc.offset or 0),
                           "error": f"{type(exc).__name__}: {exc.msg}"}]
            _SELFCHECK_CACHE[key] = cached
        else:
            reused += 1
        problems.extend(cached)
    return {"checked": True, "files": files, "scanned": scanned, "reused": reused,
            "problems": problems, "ms": round((time.monotonic() - started) * 1000.0, 1),
            "root": str(root), "unreadable": unreadable}


def format_selfcheck(rep: Mapping) -> str:
    """把自检读数翻成几行：坏文件逐条报 `文件:行:列 + 错误`，干净就报扫了几个。

    格式刻意写成 `路径:行号`：那是编辑器与终端都能点开的形态，也是 C6 那句话的字面
    （"报文件:行 + 错误，而不是栈"）。
    """
    if not rep.get("checked"):
        return f"[自检] 没查成：{rep.get('reason') or '包目录不存在'}"
    lines = [f"[自检] 包内源码：{rep.get('files', 0)} 个文件"
             f"（本次真扫 {rep.get('scanned', 0)}、命中 stat 缓存 {rep.get('reused', 0)}；"
             f"{rep.get('ms', 0)} ms）"]
    for path in rep.get("unreadable") or []:
        lines.append(f"[自检] 读不了（这是没查成，不是干净）：{path}")
    for one in rep.get("problems") or []:
        lines.append(f"[自检] 语法错误（会在这一行炸，不在栈里）："
                     f"{one['file']}:{one['line']}:{one['column']}: {one['error']}")
    if rep.get("problems"):
        lines.append(f"[自检] 结论：有 {len(rep['problems'])} 个坏文件 ⇒ 退出码 1"
                     "（查过了、有问题）；修好之前任何 import 到它的子命令都会一起坏")
    else:
        lines.append("[自检] 结论：语法错误 0 个"
                     + ("（但有读不了的文件，见上面）" if rep.get("unreadable") else ""))
    return "\n".join(lines)


def _broken_source_notice(exc: BaseException) -> str:
    """把一个 SyntaxError / ImportError 翻成"文件:行 + 错误"那一句话。

    为什么这一级值得单独存在（`draft/145` 的 F8）：某个模块被写成语法错误之后，任何一条
    子命令都会在第一次 import 它时炸，而栈里那三十行对用户毫无信息量 —— 他要的是
    "哪个文件第几行"。这一句在 0 ms 内给出来；`doctor --selfcheck` 才是慢的那一档。
    """
    if isinstance(exc, SyntaxError):
        name = exc.filename or "（不知道哪个文件）"
        out = f"[自检] 语法错误：{name}:{int(exc.lineno or 0)}: {exc.msg}"
        text = (exc.text or "").strip()
        if text:
            out += f"\n[自检] 那一行：{text}"
        out += "\n[自检] 这是一次启动自检的结论（退出码 2 = 没查成），不是程序跑出来的栈。"
        return out
    name = getattr(exc, "name", None) or str(exc)
    return (f"[自检] 有模块 import 不进来：{name} —— {type(exc).__name__}: {exc}\n"
            "[自检] 这一趟没查成（退出码 2）。要逐文件点名就跑 "
            "`agentflow doctor --selfcheck`")


#: 体检里每一档"人该去做什么"的修复提示（`fix_hint` 的内容，都是能直接复制执行的原文）。
#:
#: 三条口径（业主 2026-10-24 的 E 格）：
#:
#: 1. `doctor` 只诊断、不修。所以它唯一的用处就是把"下一步敲什么"写清楚 ——
#:    一个"模型 key：没配"而不说怎么配的读数，读的人还得去翻文档。
#: 2. 提示必须是命令原文（`$env:…='…'` / `agentflow …` / `python -m …`），不是散文。
#:    散文没法复制执行，而"能不能照着做"正是这一格要解决的问题。
#: 3. 值一律用 `<尖括号占位>` 表示"这里填你的"：写死一个假的路径比不写更坏 ——
#:    有人会照抄，然后拿到一个更难查的错。
#:
#: 键是"失败项的名字"（`doctor_checks` 产出的 `name`）。判据
#: `tests/test_doctor_fix_hint.py` 断言"每个失败项都有非空提示"，并且拿一张
#: 全失败的人造读数逐项过一遍（删一条提示就红）。
DOCTOR_FIX_HINTS: dict[str, str] = {
    "model_key": "$env:AGENTFLOW_MODEL_API_KEY='<把模型 key 填在这里>'",
    "lean_enabled": "$env:AGENTFLOW_LEAN_ENABLED='1'",
    "prover": "$env:AGENTFLOW_LEAN_BIN='<lean.exe 或它所在的目录>'",
    "prover_probe": "$env:AGENTFLOW_LEAN_BIN='<lean.exe 或它所在的目录>'",
    "lean_version": "$env:AGENTFLOW_LEAN_BIN='<与 lean-toolchain 那一行同版本的 lean.exe>'",
    "lean_selfcheck": "$env:AGENTFLOW_LEAN_BIN='<那个会拒绝假命题的 lean.exe 或它所在的目录>'",
    "mathlib_root": "$env:AGENTFLOW_MATHLIB_ROOT='<Mathlib 工程的根目录>'",
    "mathlib_import": "$env:AGENTFLOW_MATHLIB_ROOT='<能 import Mathlib 的那个工程的根目录>'",
    "package_syntax": "python -m agentflow.cli doctor --selfcheck",
}

#: 体检项的三种落点（与全仓三态同一套词；`off` 是"用户自己关掉的"，不是缺陷）。
DOCTOR_ITEM_STATES: tuple[str, ...] = ("ok", "fail", "unknown", "off")


def _doctor_item(name: str, state: str, detail: str) -> dict:
    """一档体检项的读数。`fix_hint` 只在"没通过"时给（通过的东西不需要下一步）。"""
    assert state in DOCTOR_ITEM_STATES, state
    return {"name": name, "state": state, "detail": str(detail or ""),
            "fix_hint": "" if state in ("ok", "off") else DOCTOR_FIX_HINTS.get(name, "")}


def doctor_checks(rep: Mapping, *, selfcheck: Mapping | None = None,
                  only: tuple[str, ...] | None = None) -> list[dict]:
    """把一份体检读数翻成逐项 `{name, state, detail, fix_hint}`。

    为什么要有这一层（而不是在 `cmd_doctor` 里散着 print）：`--json` 与人读的两份输出
    必须是同一批判定，否则"机器看到有 3 条没通过、人看到 2 条"这种漂法迟早出现。所以
    判定只在这里做一次，人读那边只是把它排版。

    `state` 四档：`ok` / `fail`（查过了、缺东西）/ `unknown`（没查成）/ `off`（用户关掉的）。
    `off` 不算失败：把"我自己关的"和"环境缺东西"混成一档，会让关掉 Lean 的人去查环境。

    `only` 是给 `--selfcheck` 那一档用的白名单：那一档只问"包内源码能不能编译"，
    把它没探测的东西（模型 key / 证明检查器）也报成"没通过"就是另一种撒谎。
    """
    items: list[dict] = []
    model = rep.get("model") or {}
    items.append(_doctor_item(
        "model_key", "ok" if model.get("key_present") else "fail",
        f"base={model.get('base_url')}；model={model.get('model')}"
        + ("" if model.get("key_present") else "（环境变量与 agentflow/settings.json 的 "
                                              "model.api_key 两处都没有 key）")))

    enabled = bool(rep.get("lean_enabled"))
    items.append(_doctor_item(
        "lean_enabled", "ok" if enabled else "off",
        f"来源={rep.get('lean_enabled_source') or '（没记）'}；formal_mode={rep.get('formal_mode')}"))

    prov = rep.get("provers") or {}
    available = prov.get("available") or []
    items.append(_doctor_item(
        "prover", "unknown" if not prov.get("checked") else ("ok" if available else "fail"),
        ("找到：" + "、".join(f"{r.get('name')}@{r.get('path')}" for r in available))
        if available else f"一个都没找到；找过 —— {'；'.join(prov.get('looked_in') or [])}"))
    probe_errors = prov.get("probe_errors") or []
    if probe_errors:
        items.append(_doctor_item("prover_probe", "unknown", "；".join(probe_errors)))

    sc = rep.get("lean_selfcheck") or {}
    if isinstance(sc, Mapping) and sc:
        expected = str(sc.get("expected_version") or "")
        got = str(sc.get("version") or "")
        if enabled and expected:
            items.append(_doctor_item(
                "lean_version", "ok" if sc.get("version_ok") else "fail",
                f"钉住 {expected} / 实测 {got or '（没读到版本）'}"))
        state = str(sc.get("state") or "unknown")
        problems = [str(p) for p in (sc.get("problems") or [])]
        items.append(_doctor_item(
            "lean_selfcheck",
            "ok" if state == "usable" else ("off" if state == "off" else "fail"),
            f"state={state}；检查器={sc.get('lean_path') or '（没找到）'}"
            + ("；" + "；".join(problems) if problems else "")))

    ml = rep.get("mathlib") or {}
    if isinstance(ml, Mapping) and ml:
        root = str(ml.get("root") or "")
        # Lean 关着时 Mathlib 那两档是"不适用"而不是"缺东西"：把"我自己关的"读成
        # "环境缺库"，会让人去装一个这一趟根本不会用到的库。
        items.append(_doctor_item(
            "mathlib_root", "off" if not enabled else ("ok" if root else "fail"),
            (f"根={root}；与钉住的一致={bool(ml.get('pinned_match'))}"
             if root else str(ml.get("reason") or "没找到 Mathlib 工程根"))))
        if root:
            measured = ml.get("graph_import_measured")
            text = str(measured if measured is not None else ml.get("import_mathlib") or "")
            usable = text.strip().lower().startswith("usable")
            items.append(_doctor_item(
                "mathlib_import",
                "off" if not enabled else ("ok" if usable else "fail"),
                f"第 ⑤ 步真编译读数：{text}"))

    if selfcheck is not None:
        broken = list(selfcheck.get("problems") or [])
        if not selfcheck.get("checked"):
            items.append(_doctor_item(
                "package_syntax", "unknown", str(selfcheck.get("reason") or "没查成")))
        elif broken:
            where = "、".join(
                f"{Path(str(b.get('file') or '?')).name}:{b.get('line')}:{b.get('column')}"
                for b in broken[:5])
            items.append(_doctor_item(
                "package_syntax", "fail",
                f"{len(broken)} 个坏文件（{where}" +
                ("…" if len(broken) > 5 else "") + "）；修好之前任何 import 到它的子命令都会一起坏"))
        else:
            items.append(_doctor_item(
                "package_syntax", "ok", f"扫了 {selfcheck.get('files', 0)} 个 .py，语法错误 0 个"))
    if only is not None:
        items = [it for it in items if it.get("name") in only]
    return items


def _print_doctor_checks(items: list[dict]) -> None:
    """人读的"下一步"那一段：只打没通过的那几档，每条后面跟一条可直接复制的命令。

    为什么只打没通过的：全通过的机器上多打七行"下一步"等于噪音，而噪音会让真正
    该看的那一条贬值（与 `rebuild` 里"非空才打印"同一条纪律）。
    """
    bad = [it for it in items if it.get("state") in ("fail", "unknown")]
    if not bad:
        return
    print(tty.paint(f"下一步（{len(bad)} 档没通过；doctor 只诊断，不会替你改）", "bold"))
    for it in bad:
        print(tty.bullet(f"[{it['name']}] {it['detail']}"))
        print(f"    照这条改：{it['fix_hint']}")


def cmd_doctor(args) -> int:
    """体检：这台机器现在能做哪些事（「不发起任何模型调用」，不花钱）。

    为什么要有它（2026-10-03 的现场）：形式化那一条腿能不能跑，取决于两件外部事实 ——
    有没有检查器、它是不是被找得到 —— 而这两件事此前「只能通过跑一趟真机」才知道，
    并且查不出来的形态是"报告里只剩一句没核到"（用户的原话：这是坏的）。
    这一条命令把那些事实变成跑之前就能读到的三态读数。

    退出码三态：`0` 都齐（能跑，且形式化也能做）；`1` 查过了、有缺（例如没有模型 key、
    或者没找到证明检查器 —— 缺什么就少做什么，不是"跑不成"）；`2` 没查成
    （探测本身不成立：`checked=False`，例如显式配置指了一个不存在的路径）。

    `--selfcheck` 是另一个问题、也是另一档代价：它只扫包内源码（逐文件 `compile`），
    不探测工具链、不编译 Mathlib。分出来的理由见 `selfcheck_package` 的注释 —— 那一档
    实测 1 秒量级，而体检本身可能分钟级（Mathlib 那一步真的编译一次）。

    读写：不读不写工作区；只探测环境（PATH / settings.json / 模型 key 在不在）并跑一次 Lean 自检（临时 `.lean` 落在 `%TEMP%`，跑完删净）。
    实现方式一句话：`toolchain.toolchain_report` + `leantoolchain.lean_selfcheck_reading`，判定在 `doctor_checks` 一次做完。
    """
    if bool(getattr(args, "selfcheck", False)):
        rep = selfcheck_package()
        # E 格（业主 2026-10-24）：失败项带 `fix_hint`（可直接复制执行的命令原文）。
        # 自检这一档的"失败项"就是坏文件逐条 —— 所以这里把 `doctor_checks` 的同一份
        # 判定接到自检读数上，`--json` 与人读都读它，两处不会各说一套。
        # `only` 白名单：这一档没探测模型 key / 证明检查器，就不该对它们下结论。
        rep["checks"] = doctor_checks({}, selfcheck=rep, only=("package_syntax",))
        if getattr(args, "json", False):
            print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
        else:
            print(format_selfcheck(rep))
            _print_doctor_checks(rep["checks"])
        if not rep.get("checked"):
            return 2
        return 1 if (rep.get("problems") or rep.get("unreadable")) else 0

    from . import leantoolchain as LT
    from . import toolchain as TC

    # ---- 自检先跑（这一次），`toolchain_report` 再吃它 —— 整趟只编译一次。
    #
    # 这一档问的是"找到的那个检查器会不会拒绝假命题"（一个只打印版本、永远 0 退出的回显器
    # 在 `provers` 那一档里是"可用"，在这里必须是 `unusable`：反控没失败）。
    # Mathlib 那一轴只有一处探测地址：把自检读数里的 `mathlib` 那一格原样交给
    # `toolchain_report`，于是"doctor 给的 Mathlib 读数"与"收工门/首屏那一格"读的是同一份。
    sc = LT.lean_selfcheck_reading(root=Path(getattr(args, "root", None) or DEFAULT_ROOT))
    rep = TC.toolchain_report(mathlib_reading=(sc.get("mathlib") or None))
    rep["lean_selfcheck"] = sc
    # E 格：逐项读数 + `fix_hint`。`--json` 的 `checks` 与人读的"下一步"读的是同一份
    # 判定（`doctor_checks`），所以"机器看到 3 条、人看到 2 条"这种漂法不会出现。
    rep["checks"] = doctor_checks(rep)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, default=str))
    else:
        prov = rep["provers"]
        print(tty.paint("这台机器的体检", "bold"))
        print(tty.bullet(("模型 key：已配置" if rep["model"]["key_present"]
                          else "模型 key：**没配**（设 AGENTFLOW_MODEL_API_KEY，或写进 "
                               "agentflow/settings.json 的 model.api_key）")
                         + f"；base={rep['model']['base_url']}；model={rep['model']['model']}"))
        if prov["available"]:
            for row in prov["available"]:
                print(tty.bullet(f"证明检查器：{row['name']}（{row['source']}）"
                                 f" ⇒ {row['path']}；{row['version'] or '（版本读不到）'}"))
        else:
            print(tty.bullet(f"证明检查器：一个都没找到。找过 —— {'；'.join(prov['looked_in'])}"))
            print(tty.bullet("缺了它，形式化那一条腿只能如实报「没核到」；"
                             "要真做，就把它指出来："
                             "`AGENTFLOW_LEAN_BIN=<lean.exe 或它所在的目录>`"))
        if prov["probe_errors"]:
            print(tty.paint("探测没做成：" + "；".join(prov["probe_errors"]), "yellow"))
        ml = rep["mathlib"]
        print(tty.bullet("Mathlib：" + (f"{ml.get('root')}"
                                       f"（{'与钉住的一致' if ml.get('pinned_match') else '与钉住的不一致'}）"
                                       f" ⇒ import Mathlib {ml.get('import_mathlib')}"
                                       if ml.get("root") else str(ml.get("reason")))))
        if ml.get("root"):
            # D70（`draft/83` §7）：文件面读数不算数 —— 真编译过一次才算。
            # 真机读数（2026-10-08）：依赖包的 junction 在环境搬迁后悬空，
            # umbrella 在、而 `import Mathlib` 报 `unknown package 'Std'`，
            # 上面那一行照样写"可用"。
            # 2026-10-25：实测那一次编译就是自检第 ⑤ 步的那一次（图论那条 import）——
            # 两处探测合成一处之后不再另起一次 umbrella 编译，所以这一行按真实跑法写。
            print(tty.bullet("Mathlib 实测（第 ⑤ 步真编译一次 "
                             f"`import {LT.MATHLIB_GRAPH_MODULE}`）："
                             + str(ml.get("graph_import_measured"))))
        # ---- 新增的一档：Lean 工具链开机自检（业主 2026-10-22）。
        # 逐键打出来（含 state 与逐条 problems）：这一档的用途正是"把虚构环境挡在跑之前"，
        # 而"哪一步没过、那个解释器是哪个二进制"是唯一的排查线索。
        _print_lean_selfcheck(sc)
        print(tty.bullet("结论：" + ("这一趟能做形式化核验（proof 级证据可达）"
                                     if rep["can_do_formal"] else
                                     "这一趟做不了形式化核验（会如实报没核到）")))
        _print_doctor_checks(rep["checks"])
    if not rep["provers"]["checked"]:
        return 2
    return 0 if (rep["model"]["key_present"] and rep["can_do_formal"]) else 1


def cmd_web(args) -> int:
    """起用户端网页（本地小服务）。退出码 0 = 正常停止（Ctrl-C），2 = 没查成。

    它只是把 CLI 的参数翻成 `agentflow.webui.run()` 的 argv —— 实现在那一个模块里，这里不重写第二份
    （`R003` 防的正是"同一个公开名两处各有一份实现"）。`cli.main` 是命令总入口，`webui.run` 是这一个
    子命令的实现；两者的名字因此不同。
    两个开关按裁定 T1 加（`--allow-writes` 题 C2、`--no-settings-write` 题 E1）。W3/W4 之后它们真的
    改变行为，两条都在 `writes.authorize()` 的矩阵里：`--allow-writes` 是第 3 层（不开 ⇒ `/api/` 下那六条写端点
    403），`--no-settings-write` 是第 4 层（只关 `POST /api/settings`）。`getattr` 的默认值是为了让
    直接构造 `Namespace` 的老调用方（
    `tests/test_webui.py::test_the_cli_web_subcommand_forwards_to_the_module_entry`）照旧能跑：
    缺这两个字段就当"没给"。

    这一层与 `run` / `run-agent` / `project run` 一样先翻 `RunSpec`（`draft/145` §3.2）；
    区别只有一处：`web` 这条老命令仍然逐字转发给 `webui.run(argv)`，多印一个字都不行
    （C2）。要"URL / 工作区 / sid / 当前轮"那四格读数的是 `start --watch`。

    读写：只读投影（每次请求都现读盘）；唯一的写路径是答问（`userio.answer_question`）。
    实现方式一句话：`webui.run`（本层只把旗标翻成它的 argv）。
    """
    return _run_spec(_spec_from(args, mode=MODE_WEB, origin="web", watch=False), args)


def _exec_web(spec: RunSpec, args) -> int:
    """原 `cmd_web` 的执行体（逐字转发）。"""
    from . import webui

    root = Path(args.root or DEFAULT_ROOT).resolve()
    argv = ["--root", str(root), "--host", str(args.host), "--port", str(int(args.port))]
    if args.open:
        argv.append("--open")
    if args.json:
        argv.append("--json")
    if args.token:
        argv += ["--token", str(args.token)]
    if getattr(args, "allow_writes", False):
        argv.append("--allow-writes")
    if getattr(args, "no_settings_write", False):
        argv.append("--no-settings-write")
    return webui.run(argv)


def cmd_budget(args) -> int:
    """这一趟的总预算：看、设、追加（业主 2026-10-12 的预算轴）。退出码：0 做成了 / 2 没查成。

    三种用法（`budget` 模块是唯一实现，这里只做台面）：
    - `agentflow budget` / `--status`：读一格读数 —— 总额度、已花、剩余、追加历史、三态。「已花」不
      来自寄存器：唯一权威账是 `usage_ledger`（`tokenmeter.spent()`）。
    - `agentflow budget --set 5`：设一个总额度（覆盖式；第一次设预算用这个）。
    - `agentflow budget --add 2 --note "让它跑完"`：追加（运行期生效：下一次花钱之前的那个闸门就会
      现读到新上限 —— 不需要重启、不需要重跑）。
    为什么要有这一条命令：改前"跑到一半加钱"在结构上没有入口（`Policy` 是 frozen、`LlmSeam.usd_budget`
    与 `TokenMeter.budget_usd` 只在构造期注入），唯一的办法是重跑一次。

    读写：读/写 `<工作区>/budget.json` 寄存器（总额、已花、追加历史）；不碰任何表。
    实现方式一句话：`budget` 模块的寄存器读写（运行期的闸门读同一份）。
    """
    from . import budget as B
    from .tokenmeter import TokenMeter

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = make_store(root)
    try:
        meter = TokenMeter(st)
        spent = meter.spent().get("usd")
    except Exception:  # noqa: BLE001 —— 账本读不出来时"已花"记 unknown（不许折成 0）
        spent = None
    wrote = False
    if getattr(args, "set_usd", None) is not None:
        got = B.write_initial(root, float(args.set_usd), by=str(getattr(args, "by", "user") or "user"),
                              note=str(getattr(args, "note", "") or ""))
        print(f"[budget] 设总额度：{json.dumps(got, ensure_ascii=False, default=str)}")
        wrote = True
        if not got.get("ok"):
            return 2
    if getattr(args, "add_usd", None) is not None:
        got = B.add_usd(root, float(args.add_usd), by=str(getattr(args, "by", "user") or "user"),
                        note=str(getattr(args, "note", "") or ""))
        print(f"[budget] 追加：{json.dumps(got, ensure_ascii=False, default=str)}")
        wrote = True
        if not got.get("ok"):
            return 2
    snap = B.reading(root, spent_usd=spent, fallback=getattr(args, "fallback_usd", None))
    if args.json:
        print(json.dumps(snap, ensure_ascii=False, indent=2, default=str))
    else:
        total = "不限量" if snap["total_usd"] is None else f"${snap['total_usd']:.6f}"
        used = "没查成" if snap["spent_usd"] is None else f"${snap['spent_usd']:.6f}"
        left = "—" if snap["remaining_usd"] is None else f"${snap['remaining_usd']:.6f}"
        print(tty.paint(f"[budget] {root}", "bold"))
        print(f"  总预算：{total}（来源 {snap['source']}）；已花：{used}；剩余：{left}"
              + ("（**已超**）" if snap["exceeded"] else ""))
        print(f"  追加历史 {len(snap['added'])} 条；寄存器：{snap['path']}"
              + (f"；问题：{snap['problem']}" if snap["problem"] else ""))
        if not wrote and snap["total_usd"] is None:
            # 三态纪律：没设过预算 ≠ 预算充足。把"下一步怎么做"写出来，别让人猜。
            print("  （这一趟没有设过预算 ⇒ 不限量。要设：`agentflow budget --set 5`；"
                  "要追加：`agentflow budget --add 2`）")
    return 0


def cmd_stop(args) -> int:
    """停一趟正在跑的 `run-agent`（`draft/37` §128）。退出码：0 做成了 / 2 没查成。

    两种停法（用户口径："优雅停止还要提醒那些 Agent 把发起的进程一起停掉，还要写个强制停止是直接杀掉"）：
    - 「缺省（优雅）」：写停机开关 `<工作区>/.agentflow-stop`。正在跑的那一趟在「步与步之间」看到它 ⇒
      收工（写运行记录与 `final`）；E 正在跑的实验子进程也在 0.2 s 内被终止（每步都看这个开关；
      多轮自主跑则在「每轮之间」看到它）。
    - 「`--force`（强制）」：先落开关（`force=true`，留痕"谁在什么时候强杀"），再按进程登记
      `<工作区>/runs/*.pid` 把那些进程「连子孙一起」 `taskkill /T /F` —— 直接杀掉。为什么必须"连子
      孙"：Windows 上杀父进程不带子进程（实测：包装进程被杀之后 python 子进程又跑了 12 分钟）。
    `--status` 只读当前状态（开关在不在、登记里哪些进程还活着、开关文件坏了没有、最近几次叫停）。`draft/37` §140 之后：开关是一次性信号 —— 停一趟、记一笔（`runs/stop-history.jsonl`）、撤走，所以"停完接着 `--resume`"这条路不再需要人工 `--clear`。
    退出码（`draft/39` §3.11 D25，用户裁定，2026-10-05）：
    | 码 | 含义 | 驱动器该怎么办 |
    |---|---|---|
    | `0` | 这次调用新写了开关（或 `--clear` 真的撤掉了一把） | 可以清（它是我写的） |
    | `3` | 盘上已有一把别人写的开关（本次只可能追加 `force` 升级） | 不许清，只能追加升级 |
    | `4` | 没有开关（`--clear` 时无可撤；无需清） | 什么都不用做 |
    | `2` | 没做成（强制停时一个进程都没杀掉 —— 受限环境的常见形态） | 读原话，别读成"停住了" |
    为什么"别人的开关一律不许清"要写成一个码：驱动器此前只看"命令成没成功"，于是它会把用户刚落的开关顺手撤掉（"停完就清"），而那正是"用户叫停"这件事在系统里消失的形态。

    读写：写/撤 `<工作区>/.agentflow-stop` 与 `runs/stop-history.jsonl`；`--force` 按 `runs/*.pid` 杀进程（连子孙）。
    实现方式一句话：`stopctl`（开关、登记、消费历史各一处实现）。
    """
    from . import stopctl

    root = Path(args.root or DEFAULT_ROOT).resolve()
    if getattr(args, "status", False):
        state = stopctl.read_stop(root)
        live = stopctl.live_pids(root)
        print(f"[stop] 工作区：{root}")
        print(f"[stop] 开关：{stopctl.stop_path(root)}"
              f"（{'在' if state is not None else '不在'}）")
        if state is not None:
            print(f"[stop] 开关内容：{json.dumps(state, ensure_ascii=False, default=str)}")
        history = stopctl.stop_history(root, limit=5)
        if history:
            print(f"[stop] 已被消费的叫停（最近 {len(history)} 次）：")
            for h in history:
                print(f"[stop]   {h.get('at', '?')} by={h.get('by', '?')} "
                      f"reason={h.get('reason', '?')}"
                      f"{'，force' if h.get('force') else ''}"
                      f" ⇒ 由 sid={h.get('consumed_by_sid') or '（无 sid）'} 在 "
                      f"{h.get('consumed_at', '?')} 收工时用掉")
        print(f"[stop] 登记着的活进程：{len(live)} 个"
              + ("：" + "、".join(f"{p['role']}#{p['pid']}" for p in live) if live else ""))
        # D07（`draft/39` §2）：显式回答"在跑的循环：有/没有" —— 只报 pid 登记时，
        # 登记为空会让读者把"一把没人消费的开关"读成"没事"。
        loops = stopctl.running_loops(root)
        detail = "、".join(f"{r['role']}（sid={r['sid']}，起于 {r['since']}）"
                           for r in loops["running"])
        print(f"[stop] 在跑的循环：{loops['answer']}"
              + (f"：{detail}" if detail else "")
              + (f"；另有 {len(loops['live'])} 个登记着的活进程"
                 if loops["live"] and not detail else ""))
        if loops["unreadable_sessions"]:
            print(f"[stop] 有 {len(loops['unreadable_sessions'])} 段会话读不出来"
                  f"（{loops['unreadable_sessions']}）⇒ 这一路没查成，别读成「没在跑」",
                  file=sys.stderr)
        return 0

    force = bool(getattr(args, "force", False))
    if bool(getattr(args, "clear", False)):
        # 撤开关：§140 之后"接着跑"不再需要它（开关被消费时就撤走了）；这一条留给
        # "刚写完发现写错了"那种"在生效之前撤销"的用法。
        gone = stopctl.clear_stop(root)
        print(f"[stop] 停机开关{'已撤' if gone else '本来就不在'}：{stopctl.stop_path(root)}")
        return 0 if gone else 4
    state, outcome = stopctl.request_stop_detail(
        root, reason=str(getattr(args, "reason", "") or "user"),
        by="user", force=force, sid=getattr(args, "sid", None))
    mine = outcome == "created"
    print(f"[stop] 停机开关{'已落' if mine else '已在盘上'}：{state['path']}"
          f"（reason={state['reason']}{'，force' if state['force'] else ''}）")
    if not mine:
        print(f"[stop] 这把开关不是你写的（{state.get('by', '?')} 在 {state.get('at', '?')} 落的）"
              f"⇒ 退出码 3：只追加升级、**不许清**", file=sys.stderr)
    if not force:
        if mine:
            print("[stop] 优雅停止：正在跑的那一趟会在下一步之前收工"
                  "（E 的实验子进程也会被终止）；多轮自主跑在每轮之间收工")
        # G4（业主 2026-10-26「停机开关也要能杀程序」）：优雅停对程序那一半是
        # 「提醒 + 宽限」—— 逐条请它自己收尾，宽限窗口过了还在跑的只点名、不杀。
        # 有代理在跑时它自己也会做同一件事（同一份实现 `stopctl.stop_programs`），
        # 重复调用是幂等的（第二次报 `already_exited`）。
        progs = stopctl.stop_programs(root, force=False, why=str(state.get("reason") or "user"))
        print(f"[stop] {progs['notice']}")
        if not progs.get("checked"):
            print("[stop] 注意：程序状态没查成 ⇒ 别把这一步读成「没有在跑的程序」",
                  file=sys.stderr)
        return 0 if mine else 3
    killed = stopctl.kill_registered(root)
    print(f"[stop] 强制停止：按登记杀了 {killed['killed']}/{len(killed['requested'])} 个进程"
          + (f"（{killed['requested']}）" if killed["requested"] else "（登记里没有活进程）"))
    for res in killed["results"]:
        print(f"  - pid {res['pid']}：killed={res['killed']} via={res['via']} {res['detail'][:120]}")
    if killed.get("kept"):
        # `draft/37` §140：杀不成就把登记留着 —— 否则 `--status` 会报"0 个活进程"（假绿）。
        print(f"[stop] 这些进程没杀掉，登记保留（`--status` 会照实报它们在册）：{killed['kept']}")
    # G4（业主 2026-10-26）：强停对程序那一半是「强杀」—— 这棵树名下的每一条程序进程
    # 连同它的子进程一起收掉，程序行按 `killed` 收口，读数逐项点名。
    # 为什么落在这里：`agentflow stop --force` 连代理那一趟都杀了，于是"由那一趟在循环头
    # 顺手停程序"这条路过不去（杀的是同一个进程树），只剩命令行这一处能动手。
    # 顺序：排在上面的退出码 2 之前 —— "代理一个都没杀掉"不妨碍"程序照样要停"。
    progs = stopctl.stop_programs(root, force=True, why=str(state.get("reason") or "user"))
    print(f"[stop] {progs['notice']}")
    for entry in progs.get("programs") or ():
        print(f"  - {entry.get('program') or '（程序名没读到）'} pid={entry.get('pid')}"
              f" 档={entry.get('status')}"
              + (f"（{entry.get('note')}）" if entry.get("note") else ""))
    if not progs.get("checked"):
        print("[stop] 注意：程序状态没查成 ⇒ 别把这一步读成「没有在跑的程序」", file=sys.stderr)
    if killed["requested"] and not killed["killed"]:
        print("[stop] 注意：一个都没杀掉（受限环境常见：taskkill 被拒、os.kill 也被拒）——"
              "读数里给了原话，不要把它读成「停住了」。停机开关仍然有效："
              "那一趟会在下一个步检查点收工（`stop_reason=force_stop`）", file=sys.stderr)
        return 2
    return 0 if mine else 3


#: `agentflow stats` 的四个读数（名字, 一句话）。名字是 `readouts.READOUTS` 的键。
#:
#: 为什么是一张表而不是在 `build_parser` 里抄四遍 `add_parser`：help 文案、子命令名与
#: `readouts.READOUTS` 三者必须同源，抄四遍就给了它们各自漂的机会（`stats errors` 的
#: help 曾经写着"只读、零模型调用"，而另一档的文案漏了同一句）。
STATS_KINDS: tuple[tuple[str, str], ...] = (
    ("errors", "按角色 × 类目统计错误动作计数（附合计、类目释义与三态）"),
    ("flow", "按角色的动作分布：走了几步、各是什么形状、被拦下多少、转投多少"),
    ("cost", "钱与 token 的分布：按角色、按阶段（usage_ledger 的 scope）"),
    ("gates", "收工门八格三态一张表（现算；不给 --project-dir 时那几格如实记 unknown）"),
    ("all", "上面四项一起打（三态取合取：有一条没查成就整条记 unknown）"),
)


def _stats_readout(kind: str, root: Path, args, *, scanned=None):
    """按名字取一条读数（`gates` 多两个入参：项目根与报告路径）。

    唯一的分支在这里：`gates` 的读数需要"这是哪个项目"才知道论文/验收那几格查什么，
    其余三条只吃一个工作区根。把它做成一个函数而不是散在 `cmd_stats` 里，是为了让
    "哪个读数要哪些入参"只有一处说法。

    `scanned`（2026-10-27，R-BE1 的 ⑥-5）：`stats all` 读一次盘，四条读数共用 ——
    改前每条各读一遍（实测 `events.jsonl` 与 `sessions/*.jsonl` 各 4 遍）。
    """
    from . import readouts as RO

    fn = RO.READOUTS[kind]
    if kind == "gates":
        return fn(root, project_dir=str(getattr(args, "project_dir", "") or ""),
                  report_path=str(getattr(args, "report", "") or ""), scanned=scanned)
    return fn(root, scanned=scanned)


def cmd_stats(args) -> int:
    """统计量（只读测试工具）：四项读数与它们的一份合计。

    形状：`agentflow stats errors|flow|cost|gates|all [--root <工作区>] [--json]`。
    读数本身全在 `readouts`（统一五键 + 三态），CLI 只做三件事：解析 `--root`、
    选呈现（人读的小表 / 机器可读的 JSON）、把三态翻成退出码。

    读写了哪些表或文件：只读。`data/events.jsonl`、`sessions/*.jsonl`、
    `data/usage_ledger.json`，以及收工门那八格要读的表（全是只读快照读）；
    不落报告、不建目录、不加锁、零模型调用。

    实现方式一句话：`_stats_readout` 从 `readouts.READOUTS` 取实现，人读走
    `readouts.render_readout`，机器可读直接 `json.dumps` 那份 dict（同一份对象，不二次加工）。

    退出码：`0` 查过了（含"全 0"）/ `2` 没查成（JSON 里 `state="unknown"`）。
    没有 1：这一层不是判据，它不判"错误太多"。
    域 × 码对照见 `stop_reasons.EXIT_CODE_DOMAINS["readout"]`（`R-BE1` 的 ③-6，2026-10-27）。

    `errors` 那一档有一个刻意的例外：不给 `--readout` 时它按老形态打
    （`errorstats.stats_json`）。理由：那份输出的形状已经有消费者（`total` / `state`
    两个键被判据逐字钉着），而本轮的纪律是"旧指令行为不变"。`--readout` 给出与新三张表
    同一个五键形状；数值与三态在两处必须一致，判据 `tests/test_cli_stats_four_tables.py`
    拿同一夹具对拍。
    """
    from . import readouts as RO

    kind = str(getattr(args, "stats_cmd", None) or "errors")
    root = Path(getattr(args, "root", None) or DEFAULT_ROOT).resolve()
    as_json = bool(getattr(args, "json", False))

    if kind == "errors" and not getattr(args, "readout", False):
        # ---- 老形态（逐字节不变）：`errorstats` 自己的渲染与 JSON
        from . import errorstats as ES

        stats = ES.error_action_stats(root)
        if as_json:
            print(ES.stats_json(stats))
        else:
            for line in ES.render_text(stats):
                print(line)
        if not stats.checked:
            print(f"[unknown] 没查成：{stats.reason or '读不到事件流或会话记录'}"
                  "（这里的 0 不是「没有错误动作」）", file=sys.stderr)
            return 2
        return 0

    if kind == "all":
        # 四条读数共用一次扫描（2026-10-27，R-BE1 的 ⑥-5）：改前每条各读一遍盘
        # （实测 `events.jsonl` ×4、`sessions/*.jsonl` ×4）。`usage_ledger` 一并带上，
        # 于是 `cost` 也不用再读第二遍。
        scanned = RO.scan(root, tables=("usage_ledger",))
        parts = {name: _stats_readout(name, root, args, scanned=scanned)
                 for name, _help in STATS_KINDS if name != "all"}
        readout = RO.merge_readouts(parts)
        if as_json:
            # `default=json_default`：`--json` 这一档的读数由各 role 的读口给出，
            # 其中一格塞进 dataclass / Path 就会让整条命令抛 TypeError 而不是印出读数。
            print(json.dumps(readout, ensure_ascii=False, indent=2, default=json_default))
        else:
            for name in RO.ALL_DATA_KEYS:
                print("=" * 72)
                for line in RO.render_readout(name, parts[name]):
                    print(line)
            print("=" * 72)
            print(f"合计三态    checked={readout['checked']}  state={readout['state']}")
            if readout["reason"]:
                print(f"原因        {readout['reason']}")
        if not readout["checked"]:
            print(f"[unknown] 没查成：{readout['reason']}"
                  "（这里的 0 不是「没有」，是「没查成」）", file=sys.stderr)
            return 2
        return 0

    readout = _stats_readout(kind, root, args)
    if as_json:
        print(json.dumps(readout, ensure_ascii=False, indent=2, default=json_default))
    else:
        for line in RO.render_readout(kind, readout):
            print(line)
    if not readout["checked"]:
        print(f"[unknown] 没查成：{readout['reason']}"
              "（这里的 0 不是「没有」，是「没查成」）", file=sys.stderr)
        return 2
    return 0


def cmd_status_report(args) -> int:
    """项目状态报告（`draft/39` §4）：只读台账与手稿，零模型调用，不打断任何循环。

    退出码：`0` 报告已落盘 / `2` 没查成（工作区不在盘上、或收集时读不到）。

    为什么它不是"问 M 一句"：`ask_user` 那条路是反向的（让 M 停下来等人），
    而用户中途想知道情况时，正确的形态是旁路观测 —— 读盘 → 出报告，谁都不停。

    读写：只读全部台账与手稿；写 `out/review/STATUS-<ts>.{md,json}`（报告本体，不写任何表）。
    实现方式一句话：`statusreport.write_status_report`（本层只打读数与下一步）。
    """
    from . import statusreport as SR
    from .store import Store

    root = Path(getattr(args, "root", None) or DEFAULT_ROOT).resolve()
    if not root.is_dir():
        print(f"[unknown] 工作区不在盘上：{root} —— 没查成，不是「没有状态」", file=sys.stderr)
        return 2
    try:
        store = Store(root)
    except Exception as exc:  # noqa: BLE001 —— 打不开工作区 ⇒ 没查成
        print(f"[unknown] 打开工作区失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    report, md_path, json_path = SR.write_status_report(
        store, root, out_dir=getattr(args, "out", None),
        since=str(getattr(args, "since", "") or ""))
    print(f"[status-report] 报告已落盘：{md_path}")
    print(f"[status-report] 机器可读那一份：{json_path}")
    print("[status-report] 产出：" + "、".join(
        f"{k} {v['count']}" for k, v in report["tables"].items() if v["count"]))
    print(f"[status-report] 交接账本：{report['manuscripts']['rows']} 行"
          f"（模型填 {report['manuscripts']['model_authored']} / 派生 "
          f"{report['manuscripts']['derived']}）")
    infl = report["in_flight"]
    print(f"[status-report] 在飞任务：{infl['running_tasks']}；在跑的循环："
          f"{'有' if infl['running_loops'] else '没有'}；停机开关："
          f"{'在' if infl['stop_switch'] else '不在'}")
    print("[status-report] 下一步（从读数派生）：")
    for line in report["next_steps"]:
        print(f"  - {line}")
    return 0


def cmd_closing(args) -> int:
    """跑收工门（`draft/37` §16 P3）。退出码：0 可交付 / 1 被拦住 / 2 没查成。

    三态（与 `noai_gate` 同一套口径）：`unknown` 那一档绝不是通过 —— "没查成"（没给项目根、报告还没写）与"查过了有问题"必须给不同的退出码，否则 CI 会把两者读成同一件事。
    ## 收工门之后再接一段内容级验收（`draft/37` §17.3，题 6 选 A = 接线）：这一层此前在生产面上一次
    都没被调用过；现在它的唯一生产调用者是这里（只读、零模型调用、不落任何台账）。为什么挑这个出
    口：收工门问的正是"这份交付能不能交"，而 `reviewaccept` 问的是同一份交付的同一个问题（只是判据
    在内容层）；两者的入参（`project_dir` / `report_path` / `session_root` / `sid`）本来就是同一批，
    而那批入参在这里已经收齐了 ⇒ 不新开面、不新开子命令（子命令数被 `test_user_quickstart` /
    `test_doc_code_consistency` 逐字钉着）。
    两件事刻意分开、读数分栏打：退出码仍只由收工门定（`tri_state_exit_code`）—— 把内容级验收并进
    退出码等于偷偷改门的强度（那是裁定题）；`unknown` 不折平：六条各自打"通过/不通过/没查成"，
    辅助读数照原样打出，并逐字说明"它们不构成通过"。
    `--acceptance-sid` 缺省传 `closing.NO_SESSION`（"这次调用没有会话身份"），于是「三态分支」那一格
    是"没查成" —— 不折进 `sid=None` 的"读缺省会话"，那正是 §58/§63 记过两次的假绿形态。
    ## 退出码由 M 的判据定（业主 2026-10-09）：「是否收工不要用机械判据，由 M 制定的目标是否达成
    为准」⇒ 退出码（0 可交付 / 1 被拦住 / 2 没查成）跟着 M 的判据走：运行内 M 交判据那一次已经把它
    落到 `out/review/m-verdicts.jsonl`，这里缺省读那一份；`--goal-met` / `--goal-not-met` 是"人/CI
    代述 M 的说法"的显式入口。没有判据 ⇒ 2（"没人判过"既不是"可以交"也不是"被拦住"）。八格照旧
    逐格现算并打出来，但它们是读数。

    读写：只读台账（statements / relations / experiments / documents / review_findings …）与 `out/paper/`、`out/review/` 下的产物；不写任何表、不改任何文件。
    实现方式一句话：`closing.check_closing` 现算八格，本层只排版与翻退出码。
    """
    from . import closing as CL
    from . import leantoolchain as LT
    from .store import Store

    root = Path(args.root or DEFAULT_ROOT).resolve()
    st = Store(root)
    project = args.project_dir or ""
    report = args.report or (str(Path(project) / "out" / "review" / "REPORT.md")
                             if project else "")
    rep = CL.check_closing(st, project_dir=project, report_path=report,
                           goal=str(getattr(args, "goal", "") or ""),
                           goal_met=getattr(args, "goal_met", None),
                           basis=str(getattr(args, "basis", "") or ""))
    for name in CL.DEFAULT_CHECKS:
        state = rep.status.get(name, "?")
        mark = {"pass": "通过", "fail": "拦住", "unknown": "没查成"}.get(state, state)
        print(tty.bullet(f"{name}：{mark}"))
    for f in rep.findings:
        print(f"  [{f.level}] {f.code}：{f.detail}")
    # 非平凡性那一格（S3/S4）：读数必须在人看得见的地方露面 —— 只塞进 readings 字典
    # 等于"接了一半的线"（业主 2026-10-21 追问"请确认真的接线了"时暴露的缺口）。
    _nt = (rep.readings or {}).get("nontriviality") or {}
    if _nt:
        if _nt.get("checked"):
            _counts = _nt.get("counts") or {}
            print(tty.bullet(
                "非平凡性："
                + " / ".join(f"T{level} {_counts.get(f'T{level}', 0)}" for level in (1, 2, 3, 4))
                + f" / 未判 {_counts.get('unjudged', 0)}"
                + f"（共 {_nt.get('statements_total', 0)} 条命题；T3/T4 {_nt.get('high_tier_total', 0)} 条）"))
        else:
            print(tty.bullet(f"非平凡性：没读到（{_nt.get('reason') or '台账为空'}）"))
        for _label, _key in (("论文侧缺铺垫", "paper_scaffolding_problems"),
                             ("T4 缺造梯子记录", "t4_ladder_problems")):
            for _problem in (_nt.get(_key) or []):
                print(f"  [warning] nontriviality：{_label} —— {_problem}")
    print(rep.summary())
    # ---- Lean 工具链那一格（业主 2026-10-22「防止用户提供虚构的lean环境」）。
    # 收工门问的是"这份交付能不能交"，而"这一趟的 proof 级证据可不可信"是同一个问题的前提：
    # 自检没给出 usable 时，本格把形式化证据的档位明写成 unknown，
    # 不让一份靠回显器撑起来的 proof 行混过"可交付"。
    _lean_sc = LT.lean_selfcheck_reading(root=root)
    print(tty.bullet("Lean 工具链自检：" + _lean_reading_text(_lean_sc)))
    _lean_problem = LT.evidence_state_problem(_lean_sc)
    if _lean_problem:
        print(tty.bullet(tty.paint(_lean_problem, "yellow")))
    if getattr(args, "no_review_acceptance", False):
        # 关掉是显式的：它让"零调用的那段历史"仍可复现，也方便对拍接线前后的读数。
        print("[review-acceptance] 这一次没跑（`--no-review-acceptance`）—— "
              "这一格是「没查成」，不是「内容级验收通过了」")
        return CL.tri_state_exit_code(rep)
    _print_review_acceptance(st, project=project, report=report,
                             cap_usd=getattr(args, "cap_usd", None),
                             sid=(getattr(args, "acceptance_sid", None)
                                  or CL.NO_SESSION))
    return CL.tri_state_exit_code(rep)


def _print_review_acceptance(store, *, project: str, report: str,
                             cap_usd: float | None, sid: str) -> None:
    """把内容级验收（`draft/37` §17.3 的六条）打到人能读的地方（只读）。

    `reviewaccept` 读的是同一批入参：`project_dir` / `report_path` / `session_root`（不给就用
    `store.root`，与 `check_closing` 同一条口径）/ `sid`。
    为什么六条要逐条打而不是只打一个 `passed`：这一层的三态纪律就写在判据本身里（"没查成"与"查过
    了没问题"必须分得开，`unknown` 会挡住 `passed`）；只打一个布尔值，等于把这条纪律在出口上又折平。
    为什么辅助读数也要逐条打（哪怕一个都不参与判定）：§17.3 逐字禁止拿它们当通过 —— 而"禁止"要能
    被读的人看见才有意义；它们与判据分栏给出，末尾再写一句它们不构成通过。
    这一段只读盘：`check_review` 走 `store.rows` / `sessions.read_session` / `userio` 的读口 /
    `papercompile.receipt_matches_tex`，一处都不写。
    """
    from . import reviewaccept as RX

    acc = RX.check_review(store, project_dir=project, report_path=report,
                          cost_cap_usd=cap_usd, sid=sid)
    readings = acc.to_dict()
    mark = {"pass": "通过", "fail": "不通过", "unknown": "没查成"}
    print("")
    print(tty.paint("[review-acceptance] 内容级验收（§17.3；只读，零模型调用）", "bold"))
    for key, name in RX.CRITERIA:
        state = readings["criteria"].get(key, "?")
        print(tty.bullet(f"{name}：{mark.get(state, state)}"))
        note = readings["details"].get(key) or ""
        if note:
            print(f"    {note}")
    print(f"  passed（只看上面这几条）＝{readings['passed']}")
    if readings["failed"]:
        print(f"  没通过的：{'、'.join(readings['failed'])}")
    print("  ── 辅助读数（§17.3 逐字禁止拿来当通过：它们都很容易变，证明不了内容）")
    for key, label in RX.AUXILIARY_SIGNALS:
        print(f"    {label}＝{readings['auxiliary'].get(key)}")
    for key, value in readings["readings"].items():
        print(f"    （判据读数）{key}＝{value}")
    print(f"  {acc.summary()}")


def _subparsers_action(parser: argparse.ArgumentParser):
    """顶层唯一的那个 subparsers action（三处判据靠它取 `choices`）。"""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _subcommand_helps(parser: argparse.ArgumentParser) -> dict[str, str]:
    """子命令名 → 它那一句 help（从 parser 里现读，不在别处抄第二份）。"""
    action = _subparsers_action(parser)
    helps: dict[str, str] = {}
    for choice in (getattr(action, "_choices_actions", None) or []) if action else []:
        helps[str(getattr(choice, "dest", ""))] = str(getattr(choice, "help", "") or "")
    return helps


#: 组页里"组名"那一列占多宽（够放 `incubate` 再加两格）。
_GROUP_COL = 12

#: 组页与首屏里"成员"那一行缩进多少格。
_MEMBER_INDENT = 4 + _GROUP_COL


def _wrap(text: str, *, indent: int, width: int = 100) -> list[str]:
    """折行并把续行缩进到 `indent` 格（空串 ⇒ 一行空）。"""
    parts = textwrap.wrap(str(text or ""), width=max(20, width - indent)) or [""]
    return [" " * indent + parts[0], *(" " * indent + p for p in parts[1:])]


def _render_group_help(group: str, parser: argparse.ArgumentParser) -> str:
    """组页（`agentflow inspect` / `agentflow inspect --help`）。

    只讲三件事：这个组管什么、组里有哪些成员（每个一句）、以及"旧名仍然直接用"。
    为什么要有这一页：新入口的第一跳是组名，而 argparse 没有"组"这个东西 —— 它只认
    `choices` 里的 28 个旧名。不给人这一页，用户敲 `agentflow inspect` 会拿到
    `invalid choice: 'inspect'`，那等于把"分层"这件事藏进文档里。
    """
    members = GROUP_MEMBERS[group]
    helps = _subcommand_helps(parser)
    lines = [f"agentflow {group} —— {GROUP_PURPOSE[group]}", ""]
    lines.append(f"用法：agentflow {group} <成员> [旗标]")
    example_old, example_path = command_paths()[0]
    for old, path in command_paths():
        if path.startswith(f"{group} "):
            example_old, example_path = old, path
            break
    lines.append(f"      例：agentflow {example_path}        "
                 f"（与 agentflow {example_old} 是同一条命令）")
    lines.append("")
    lines.append("成员（成员名就是旧名；旧名本身也仍然可以直接敲）：")
    column = max(len(m) for m in members) + 2
    for member, old in members.items():
        note = "" if old == member else f"（旧名 `{old}`）"
        head = f"    {member:<{column}}"
        body = textwrap.wrap(f"{helps.get(old, '')}{note}",
                             width=max(30, 100 - len(head))) or [""]
        lines.append(head + body[0])
        lines.extend(" " * len(head) + extra for extra in body[1:])
    lines.append("")
    lines.append("看某一条的旗标：`agentflow {0} <成员> --help`。".format(group))
    lines.append("旧名 → 新路径的全文对照表：`agentflow --help-legacy`。")
    return "\n".join(lines)


def _render_legacy_help() -> str:
    """旧名 → 新路径的全文对照表（`agentflow --help-legacy`）。

    单独一页的理由：`--help` 首屏要能一眼读完（`draft/145` 的 F5 说的是"二十多个子命令
    分两页才看全"），而 28 行对照表塞进去就又是两页。这张表与 `command_paths()` 同源，
    所以改分层只改那一处。
    """
    lines = ["旧名 → 新路径（本轮一个旧名都没删；两边行为逐字相同）", ""]
    width = max(len(old) for old, _path in command_paths())
    for old, path in command_paths():
        lines.append(f"  {old:<{width}}  →  agentflow {path}")
    lines.append("")
    lines.append("分组的用途：")
    for group, purpose, _members in COMMAND_GROUPS:
        lines.append(f"  {group:<{_GROUP_COL}}{purpose}")
    lines.append("")
    lines.append("旧名不带组前缀（`agentflow stats`）与新路径（`agentflow inspect stats`）"
                 "等价：新路径在解析之前就折回旧名，所以旗标、缺省、退出码一个字都不差。")
    return "\n".join(lines)


class _GroupedHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """首屏按 `COMMAND_GROUPS` 印四个入口，并把 28 个旧名的一句话说明收进"旧名仍可用"。

    为什么只能在这一层做（`draft/145` 的 F5）：argparse 没有给 subparsers 分组的能力
    （`_SubParsersAction` 只认一张 `choices` 字典），而三处既有判据正是靠"唯一一个
    subparsers action"读 `choices` 的 —— 拆成多个会一起红。所以呈现只发生在这里：
    这里只拦 subparsers 那一种 action，其余一律照 argparse 原样走，于是每个子命令自己的
    `--help` 一个字都不变（C2 要求老命令的输出逐字一致）。
    """

    #: 子命令名那一列占多宽（够放 `status-report` 这种最长的名字再加两格）。
    _NAME_COL = 18

    def _format_action(self, action):
        if not isinstance(action, argparse._SubParsersAction):
            return super()._format_action(action)
        helps = {str(getattr(choice, "dest", "")): str(getattr(choice, "help", "") or "")
                 for choice in (getattr(action, "_choices_actions", None) or [])}
        names = list(action.choices)
        lines: list[str] = []
        placed: set[str] = set()
        lines.append("  组内地名就是旧名；旧名本身也仍然可以直接敲")
        for group, purpose, members in COMMAND_GROUPS:
            rows = [m for m in members if GROUP_MEMBERS[group][m] in names]
            if not rows:
                continue
            lines.append(f"    {group:<{_GROUP_COL}}{purpose}")
            member_text = "  ".join(rows)
            lines.extend(_wrap(member_text, indent=_MEMBER_INDENT,
                               width=max(60, self._width)))
            placed |= {GROUP_MEMBERS[group][m] for m in rows}
        rest = [name for name in names if name not in placed]
        if rest:
            # 漏登记不静默消失：落在这一栏里，判据也断言并集等于全部子命令。
            lines.append("  未分组（COMMAND_GROUPS 漏登记了，请补进去）")
            for name in rest:
                lines.extend(self._command_lines(name, helps.get(name, "")))
        lines.append("")
        lines.append("  例：`agentflow inspect stats cost --json`；"
                     "某一条的旗标看 `agentflow inspect stats --help`。")
        lines.append("")
        lines.append("  旧名仍可用（一个都没删，与新路径逐字等价）：")
        lines.extend(_wrap(" ".join(LEGACY_COMMANDS), indent=4,
                           width=max(60, self._width)))
        lines.append("  全文对照表与四组的用途：`agentflow --help-legacy`"
                     "（也在 docs/USER-GUIDE.md 的 CLI 一节）。")
        return "\n".join(lines) + "\n\n"

    def _command_lines(self, name: str, help_text: str) -> list[str]:
        """一行 `名字 + 一小句`（太长就折行，续行与那一列对齐）。"""
        indent = " " * (self._NAME_COL + 4)
        width = max(40, self._width - self._NAME_COL - 4)
        parts = textwrap.wrap(help_text, width=width) or [""]
        return [f"    {name:<{self._NAME_COL}}{parts[0]}",
                *(indent + part for part in parts[1:])]


def build_parser() -> argparse.ArgumentParser:
    """建整张命令行表：28 个旧命令 + 顶层开关（四个组由 `canonical_argv` 折回这里）。

    读写：不读不写任何文件（`--help` 之所以能在 0 毫秒内给出来，就是因为这一层只装表）。
    实现方式一句话：每个子命令一个 `add_parser` + 一句 `set_defaults(func=cmd_xxx)`；
    首屏的分组只发生在呈现层（`_GroupedHelpFormatter`），`choices` 仍然是那 28 个名字
    —— 三处判据（子命令数、分组覆盖、`--json` 契约）都靠这个唯一的 subparsers action。

    加一条命令时要一起改的地方（顺序即"漏了会红"的顺序）：
    `COMMAND_GROUPS` 里给它一个组 → 这里 `add_parser` + `set_defaults` → 那个 handler
    写清"干什么 / 读写哪些表 / 实现方式" → `docs/USER-GUIDE.md` 与 `docs/CLI-CONTRACT.md`
    各补一行/一节 → 子命令数那两处读数（`README.md` 与 `docs/DEVELOPMENT-SPEC.md`）。
    """
    p = argparse.ArgumentParser(prog="agentflow",
                                description="面向数学研究的多智能体协同框架（正式版；A–H + 主控 M）",
                                formatter_class=_GroupedHelpFormatter)
    p.add_argument("--root", default=None,
                   help="工作区根（不给就用 DEFAULT_ROOT = 本仓库的 `agentflow/`）")
    p.add_argument("--config", default=None, help="配置文件路径（默认 <root>/config.yaml）")
    # 呈现层的两个开关。为什么做成顶层开关而不是每条命令各带一个：
    # "这次输出别带颜色"是终端的事，不是某个子命令的事；散在各处就会出现
    # "project 支持而 run 不支持"这种随命令而变的怪现象。
    p.add_argument("--no-color", action="store_true",
                   help="关掉颜色（管道里本来就会自动关；这个开关是给『想强制关』的人）")
    p.add_argument("--plain", action="store_true",
                   help="纯 ASCII 输出（制表符/勾号都不画；老终端或想粘到邮件里时用）")
    p.add_argument("--compact", action="store_true", help="少画框、少空行")
    # 版本号出口。为什么要这一格：`agentflow/__init__.py` 的 `__version__` 与
    # `pyproject.toml` 的 `version` 是两个各自写死的字面量，而在此之前 CLI 里
    # 一条命令都读不到它们 —— "发出去的东西有版本号、用的人只能在 `pip show` 里查"
    # 是一种把版本号交给别人保管的形态（装成脚本、或从源码树跑时连 `pip show` 都没有）。
    # 只读常量，不 import 任何子模块（`agentflow/__init__` 本来就只放版本号）。
    p.add_argument("--version", action="version",
                   version=f"agentflow {_PKG_VERSION}",
                   help="印版本号并以 0 结束")
    # 旧名 → 新路径的全文对照表（28 行）。单独一页而不是塞进 `--help`：首屏要能一眼读完，
    # 而这张表与 `command_paths()` 同源，改分层只改那一处。
    p.add_argument("--help-legacy", action="store_true",
                   help="打印旧名 → 新路径的全文对照表（本轮一个旧名都没删，两边逐字等价）")
    #: `metavar` 是"首屏能读"的一半：二十多个名字全塞进 usage 行会折成三行，
    #: 而真正想让人看的是下面那四组。子命令清单仍在 `choices` 里（判据读的就是它）。
    #:
    #: 抬头改的是 argparse 的 positionals 组那一节的 `title`（默认 `positional arguments`）：
    #: 顶层没有别的位置参数，那一组里只有这个 subparsers action，所以改它就是改那一节的
    #: 抬头。为什么不给 `add_subparsers` 传 `title=`：那会新建一个组并把它追加到
    #: "options" 之后，于是最重要的那一节会被挤到 `--help` 的最下面。
    #: `parser._actions` 与 `choices` 一个字都不变 —— 三处判据靠的仍然是
    #: "唯一一个 subparsers action"。
    p._positionals.title = "命令（四个入口）"
    sub = p.add_subparsers(dest="cmd", metavar="<命令>")

    sp = sub.add_parser("init", help="初始化数据目录与空表")
    sp.add_argument("--force", action="store_true", help="覆盖已有数据（危险）")
    sp.add_argument(ALLOW_FOREIGN_FLAG, action="store_true",
                    help="这个目录里已经有用户的投料（例如一篇 PDF），仍然按工作区初始化："
                         f"先落 {WORKSPACE_MARKER}（`store` 的白名单出口）再 init；"
                         "用户的文件不删不改。不给这个开关时，'有外来条目'那一档照旧拒绝")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("submit", help="提交搜索请求")
    sp.add_argument("--topic", required=False)
    sp.add_argument("--mode", default="topical", choices=list(S.SEARCH_MODES))
    sp.add_argument("--content", default="")
    sp.add_argument("--by", default="cli")
    sp.add_argument("--file", default=None, help="从 JSON 文件批量提交（{rows:[...]} 或 [...]）")
    sp.set_defaults(func=cmd_submit)

    sp = sub.add_parser("run-a", help="运行 A 智能体")
    sp.add_argument("--once", action="store_true", help="只处理一条请求")
    sp.add_argument("--max", type=int, default=1)
    sp.add_argument("--provider", default=None, help="逗号分隔，如 fixture 或 openalex,crossref")
    sp.set_defaults(func=cmd_run_a)

    sp = sub.add_parser("run-b", help="运行 B 智能体")
    sp.add_argument("--once", action="store_true", help="只整理一篇文献")
    sp.add_argument("--max", type=int, default=1)
    sp.set_defaults(func=cmd_run_b)

    sp = sub.add_parser("status", help="查看各表统计")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("verify", help="校验全局不变量（error ⇒ 退出码 1）")
    sp.add_argument("--deep", action="store_true", help="重新打开文献复核引文（慢）")
    sp.add_argument("--strict", action="store_true", help="警告也算失败（error 一律失败）")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("rebuild", help="从 events.jsonl 重建快照")
    sp.add_argument("--no-backup", action="store_true")
    sp.set_defaults(func=cmd_rebuild)

    sp = sub.add_parser("repair", help="重算派生字段")
    sp.add_argument("--related", action="store_true", help="重算 related_concepts")
    sp.set_defaults(func=cmd_repair)

    sp = sub.add_parser("demo", help="离线端到端演示（不访问网络）")
    sp.add_argument("--keep", action="store_true", help="保留上次演示数据")
    sp.set_defaults(func=cmd_demo)

    # ---- 工具层与新智能体（DESIGN-TOOLS.md）
    sp = sub.add_parser("tools", help="列出工具层按角色的装配情况")
    # 角色清单必须来自 `S.ROLES`，不许在这里写死（与 `cmd_tools` 函数体同一条纪律）。
    # 这里原先写死 `choices=["A", "B", "C", "D"]`：函数体修了、参数层没修，于是
    # E/F/G/H 落地之后 `tools --role E` 被 argparse 以退出码 2 拒掉
    # （实测 `invalid choice: 'E'`）——"角色即权限面"的可打印事实只覆盖 A–D。
    # 用 `S.ROLES`（schema 是角色名单的唯一来源，`tools.ROLES` 就是它）而不是
    # 在这里 import `tools`：这样 `cli --help` / 其它子命令不必为了一张词表去装配工具层。
    sp.add_argument("--role", default=None, choices=list(S.ROLES), help="只看某个角色的工具")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_tools)

    sp = sub.add_parser("analyze", help="C：关系分析（四类需求）")
    sp.add_argument("--kind", default="hottest", choices=list(S.REPORT_KINDS))
    sp.add_argument("--a", default=None, help="kind=paths：起点概念（代号或名字）")
    sp.add_argument("--b", default=None, help="kind=paths：终点概念（代号或名字）")
    sp.add_argument("--top-n", type=int, default=5, help="hottest/cold 取前几名；gaps 的 limit")
    sp.add_argument("--max-paths", type=int, default=5)
    sp.add_argument("--max-len", type=int, default=4, help="路径最大跳数")
    sp.add_argument("--request", default="", help="原始需求原文（登记在报告里便于审计）")
    sp.add_argument("--text", default=None, help="直接用自然语言需求，走 C.handle() 分派")
    # B 格：`--json` 是这一轮新加的开关（此前没有），所以它给的是外层四格
    # （ok / state / data / problems，见 `_envelope_payload`）。`data.text` 是这条命令
    # 原本打印的那份报告原文 —— 本命令还没有结构化输出，这一格不假装有。
    sp.add_argument("--json", action="store_true",
                    help="机器可读：外层四格（ok/state/data/problems），data.text 是报告原文")
    sp.set_defaults(func=cmd_analyze)

    sp = sub.add_parser("pipeline", help="编排：C→D→(A→B→D 复查) 循环")
    sp.add_argument("--request", required=True, help="自然语言分析需求")
    sp.add_argument("--gap-rounds", type=int, default=2)
    sp.add_argument("--no-search", action="store_true", help="不跑 A/B（只做静态分析）")
    sp.set_defaults(func=cmd_pipeline)

    # ---- 统一入口（`draft/145` §3.1）：一个入口讲清"干什么 / 在哪干 / 花多少钱 /
    # 开不开 Lean"。四条老命令（run / run-agent / project run / web）都是它的别名：
    # 解析层一个字不动、执行层收口（见 `_run_spec`）。
    sp = sub.add_parser(
        "start",
        help="统一入口：给一句话就开始干（研究循环 / 端到端主题 / 项目工作区 / 只开网页）",
        description=(
            "统一入口。`--mode` 不写就按目录状态推断：没给 --task 且给了 --watch ⇒ 只开网页；"
            "项目文件夹不存在或为空 ⇒ cold；已有台账（data/tasks.jsonl 有行）⇒ research；"
            "存在但没有台账 ⇒ warm。`--mode research` 时角色缺省 M，不再要位置参数。\n\n"
            "缺参数时报的是人话并点名该给哪个旗标（不是 argparse 那句 "
            "the following arguments are required）。\n\n"
            "--dry-run 只打印将要发生的一切：不建目录、不写字节、一次模型都不调、"
            "也不起 Lean 自检子进程。\n\n"
            "--watch 起网页并打印 URL / 工作区 / sid / 当前轮；不带 --task 时只开网页"
            "（一直开着，Ctrl-C 停），带 --task 时边跑边可监督、跑完收工。\n\n"
            "--json 的键集合：--dry-run 那一档逐字等于 cli.START_PLAN_KEYS"
            "（mode / task / workspace / project / model / budget / lean / summons / "
            "writes / spend）；--watch 不带任务那一档是 {url, root, sid, round}；"
            "其余档透传给对应那条路自己的 JSON（run 的运行记录 / run-agent 的运行记录）。"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    _what = sp.add_argument_group("要跑什么")
    _what.add_argument("--task", default=None,
                       help="这次要做的事（一句话）。不给就得给 --watch（只开网页）")
    _what.add_argument("--mode", default="auto", choices=list(START_MODES),
                       help="auto（缺省，按目录状态推断）/ research（十角色循环，角色缺省 M）"
                            "/ topic（端到端主题跑）/ role（只跑一个角色循环）"
                            "/ project / cold / warm（项目工作区）")
    _what.add_argument("--role", default="",
                       choices=[*S.ROLES, S.CONDUCTOR_ROLE],
                       help="角色（--mode role 必填；--mode research 缺省 M）")
    _what.add_argument("--project", dest="name", default=None,
                       help="项目名（落在 <projects-dir>/<名字>；不给就自动取下一个 projectN）")
    _where = sp.add_argument_group("在哪干")
    # 顶层已经有 `--root`：这里再给一次，`default=SUPPRESS` 是关键 —— 否则子 parser 的
    # 缺省 None 会把用户写在子命令前面的 `--root` 覆盖掉（argparse 的已知形态）。
    _where.add_argument("--root", default=argparse.SUPPRESS, help="工作区根（与顶层 --root 同义）")
    _where.add_argument("--projects-dir", default=None,
                        help="projects 落点（缺省：<root>/projects）")
    _where.add_argument("--start", default="auto", choices=["auto", "cold", "warm"],
                        help="项目冷/热启动（--mode cold/warm 也表达同一件事）")
    _where.add_argument("--out", default=None, help="产物目录（只对 topic 那一档有意义）")
    _where.add_argument("--books", default=None, help="本地书架目录（项目那一档：里面的 PDF 会被登记）")
    _where.add_argument("--books-limit", type=_non_negative_int, default=None,
                        help="本次最多登记几本")
    _where.add_argument("--text-store-dir", default=None,
                        help="逐页正文的内容寻址落点（不给就按各模式的缺省）")
    _cost = sp.add_argument_group("花多少钱 / 开不开 Lean / 要不要盯")
    _cost.add_argument("--budget-usd", type=float, default=None, action=_BudgetUsdAction,
                       help="美元上限。显式给了就落盘到 <工作区>/budget.json（C4）；"
                            "不给就按各模式的缺省（topic 1.0 / project 0.5 / role 不限）")
    _cost.add_argument("--lean", nargs="?", const="on", default=None,
                       choices=list(LEAN_CHOICES),
                       help="on / off / auto（裸写 --lean 等于 --lean on）。"
                            "auto = 先跑一次自检，usable 才开；不是 usable 就照常跑，"
                            "但一切形式化结论记 unknown 并在读数里点名原因")
    _cost.add_argument("--watch", action="store_true",
                       help="起网页并打印 URL / 工作区 / sid / 当前轮")
    _cost.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="只说、不做：打印将要发生的一切，不写字节、不调模型")
    _cost.add_argument("--json", action="store_true", help="机器可读的那一份（见 description）")
    _cost.add_argument("--host", default="127.0.0.1", help="--watch 的监听地址")
    _cost.add_argument("--port", type=int, default=8788, help="--watch 的端口（0 = 让系统挑）")
    _cost.add_argument("--open", action="store_true", help="--watch 起来之后用浏览器打开")
    _cost.add_argument("--token", default="", help="--watch 的访问口令")
    _cost.add_argument("--allow-writes", action="store_true",
                       help="--watch 允许写面（起一趟 / 插话 / 答问 / 叫停 / 改设置 / 改预算）")
    _cost.add_argument("--no-settings-write", action="store_true",
                       help="--watch 关掉设置写面（只关 POST /api/settings）")
    _more = sp.add_argument_group("透传下去的老旗标（与同名子命令同义）")
    _more.add_argument("--max-calls", type=_non_negative_int, default=3,
                       help="最多调用几次模型（topic / project 两档用）")
    # 与 `run` 那个动词同一个缺省与同一份 choices：`None` 穿到 `run_topic` 会抛
    # "未知 prompt 版本"，那是用法错却以退出码 1 的形式出现（本项目的三态里 1 = 查过了有问题）。
    from .runflow import PROMPT_VERSIONS as _START_PROMPT_VERSIONS

    _more.add_argument("--prompt-version", default="v1",
                       choices=list(_START_PROMPT_VERSIONS),
                       help="prompt 模板版本（缺省 v1，与 run 同口径）")
    _more.add_argument("--fulltext", action="store_true", help="取开放全文（topic 那一档）")
    _more.add_argument("--no-fulltext", action="store_true", help="不取全文（project 那一档）")
    _more.add_argument("--retrieval-limit", type=_non_negative_int, default=7,
                       help="最多取几条本地来源进材料段（project 那一档）")
    _more.add_argument("--extract", action="store_true", help="先让模型把库里没抽过的书读一遍")
    _more.add_argument("--extract-rounds", type=_non_negative_int, default=1,
                       help="模型抽取最多跑几轮（一轮至多一本书）")
    _more.add_argument("--model", default=None, help="只覆盖模型名（key/base_url 一律来自环境变量）")
    _more.add_argument("--drive", action="append", default=[],
                       help="把某个 (角色.动作) 交给模型驱动（role 那一档，可重复）")
    _more.add_argument("--subagents", action="store_true",
                       help="把所有已声明的角色动作都交给模型驱动（research 缺省就是它）")
    _more.add_argument("--semantic-review", action="store_true", help="给 H 接上语义判据")
    _more.add_argument("--experiment-reasoning", action="store_true", help="给 E 接上写脚本的推理")
    _more.add_argument(ALLOW_FOREIGN_FLAG, action="store_true",
                       help="这个目录里已经有用户的投料也照样按工作区初始化")
    _more.add_argument("--provider", default=None, help="A 的检索后端（逗号分隔）")
    _more.add_argument("--max-steps", type=_non_negative_int, default=30,
                       help="每满几步向父代理报一次步数账（不是闸）")
    _more.add_argument("--wall-clock-sec", type=float, default=None,
                       help="墙钟上限（秒）；不给 = 不设上限")
    _more.add_argument("--rounds", type=_non_negative_int, default=1, help="跑几轮")
    _more.add_argument("--report-every", type=_non_negative_int, default=1,
                       help="每几轮汇报一次")
    _more.add_argument("--sid", default=None, help="会话号（缺省当天）")
    _more.add_argument("--resume", action="store_true", help="从检查点续跑")
    _more.add_argument("--user-wait-sec", type=float, default=None, help="问用户时等多久（秒）")
    _more.add_argument("--no-ask", action="store_true", help="无人值守档：问用户被确定性拒绝")
    _more.add_argument("--stop-file", default=None, help="停止开关文件")
    _more.add_argument("--now", default=None, help=argparse.SUPPRESS)
    sp.set_defaults(func=cmd_start, budget_usd_given=False)

    # 端到端一条命令。退出码即 `run_topic` 的三态：0 / 1 / 2。
    sp = sub.add_parser("run", help="端到端跑一个主题（检索→作答→逐字回验→记账→熔断→六件产物）")
    sp.add_argument("--topic", required=True, help="研究主题")
    sp.add_argument("--budget-usd", type=float, default=1.0, action=_BudgetUsdAction,
                    help="美元上限（每次调用之前检查，达线即停 —— 单跑可能超出至多一次调用，"
                         "超出量写在 cost.json 的 budget_overshoot_usd 里）；"
                         "显式给了就同时落盘到 <工作区>/budget.json")
    sp.add_argument("--out", default=None, help="产物目录（默认新建临时目录并打印路径）")
    sp.add_argument("--max-calls", type=_non_negative_int, default=3,
                    help="最多调用几次模型（库层拒绝负数；这里让它在用法错阶段就以退出码 2 结束）")
    sp.add_argument("--model", default=None, help="只覆盖模型名（key/base_url 一律来自环境变量）")
    # `choices` 让非法版本走 argparse 的用法错（退出码 2 = "没查成"），而不是穿到库层抛
    # ValueError + traceback ⇒ 退出码 1（那在本项目的三态里是"查过了、有问题"）。
    # 延迟 import：`agentflow.cli` 的顶层不许拉起 runflow（它依赖一长串模块）。
    from .runflow import PROMPT_VERSIONS as _PROMPT_VERSIONS

    sp.add_argument("--prompt-version", default="v1", choices=list(_PROMPT_VERSIONS),
                    help="prompt 模板版本（写进清单）")
    sp.add_argument("--fulltext", action="store_true",
                    help="获取开放全文（逐条下载；回验因此可能到达全文级）")
    sp.add_argument("--lean", nargs="?", const="on", default=None, choices=list(LEAN_CHOICES),
                    help="on / off / auto（裸写 --lean 等于 --lean on；缺省 off）。"
                         "对答复里的 Lean 代码块真跑证明检查器（需要环境里已装 Lean；"
                         "只有 verified 才算 proof 级证据）。"
                         "auto = 先跑一次自检，usable 才开")
    # `--now` 只为自动化测试注入固定时间戳：产物里的时间戳可复现，断言才稳得住。
    sp.add_argument("--now", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--text-store-dir", default=None,
                    help="逐页正文的内容寻址落点（不给就内联在产物里；给了同一本书只存一份，"
                         "依据 draft/30 §T0-7）")
    sp.set_defaults(func=cmd_run, budget_usd_given=False)

    # 项目式用法：`projects/<名字>` 一个项目一个文件夹，冷/热启动按文件夹在不在。
    sp = sub.add_parser(
        "project",
        help="项目工作区：list / plan / run / create（一个项目一个文件夹，冷启动还是热启动看文件夹在不在）",
    )
    sp.add_argument("action", choices=["list", "plan", "run", "create"],
                    help="list 列出现有项目；plan 只说明这次会怎么跑（不写字节）；"
                         "run 真跑；create 正常地建一个审阅型项目（--paper 给那篇外部论文）")
    sp.add_argument("--name", default=None,
                    help="项目名（缺省=自动取下一个 projectN；run 时也接受已有名字=热启动）")
    sp.add_argument("--projects-dir", default=None,
                    help="projects 落点（缺省：由本包位置推出的工作区根下的 projects/；"
                         "也可用环境变量 AGENTFLOW_PROJECTS_DIR 或设置文件的 "
                         "workspace.projects_dir 覆盖）")
    sp.add_argument("--start", default="auto", choices=["auto", "cold", "warm"],
                    help="auto=看文件夹在不在（缺省）；cold=必须不存在；warm=必须已存在且初始化过")
    sp.add_argument("--books", default=None,
                    help=r"本地书架目录（例如 D:\books）：里面的 PDF 会被登记进项目库")
    sp.add_argument("--books-limit", type=_non_negative_int, default=None,
                    help="本次最多登记几本（超出的一本都不登记，清单里写明理由）")
    sp.add_argument("--paper", default=None,
                    help="审阅型项目要铺进去的那篇外部论文（.pdf；同目录有同名 .tex 就一并铺成"
                         "只读基线与可改正文）—— 只对 `project create` 有意义")
    sp.add_argument("--topic", default=None, help="研究主题（给了才会调模型；缺省只做登记）")
    sp.add_argument("--budget-usd", type=float, default=0.5, action=_BudgetUsdAction,
                    help="这一次运行的美元额度（每次调用之前检查）；"
                         "显式给了就同时落盘到 <项目根>/budget.json")
    sp.add_argument("--max-calls", type=_non_negative_int, default=2, help="最多调用几次模型")
    sp.add_argument("--retrieval-limit", type=_non_negative_int, default=7,
                    help="最多取几条本地来源进材料段（一本书算一条）")
    sp.add_argument("--no-fulltext", action="store_true",
                    help="不取全文（引文只会在 1200 字符的摘要窗口里比对，回验强度更低）")
    # `--lean` 与 `run` 那个动词同一口径：默认关；关着时"没有任何形式化验证证据"
    # 照样写进未接线清单。没有这个开关时，本地书架这条主路径上永远拿不到 proof 级证据。
    # 2026-10-22 起是三档（`on` / `off` / `auto`）：裸写 `--lean` 仍等于 `--lean on`，
    # 而 `--lean off` 真的关 —— 改前 `bool("off")` 为真，关不掉的开关比没有开关更坏。
    sp.add_argument("--lean", nargs="?", const="on", default=None, choices=list(LEAN_CHOICES),
                    help="on / off / auto（裸写 --lean 等于 --lean on；缺省 off）。"
                         "对答复里的 Lean 代码块真跑证明检查器（需要环境里已装 Lean；"
                         "只有 verified 才算 proof 级证据）。"
                         "auto = 先跑一次自检，usable 才开")
    sp.add_argument("--extract", action="store_true",
                    help="先让模型把库里还没抽过的书读一遍（概念/关系；每条关系的引文"
                         "逐字回验，找不到的当场剔除并计数）")
    sp.add_argument("--extract-rounds", type=_non_negative_int, default=1,
                    help="模型抽取最多跑几轮 —— 一轮只处理至多一本书（agent_b.run_once 的契约），"
                         "所以 7 本书要 --extract-rounds 7")
    sp.add_argument("--now", default=None, help=argparse.SUPPRESS)
    sp.add_argument("--text-store-dir", default=None,
                    help="覆盖逐页正文的落点（不给就用 <项目根>/.fulltext，见 T0-6 的默认）")
    sp.set_defaults(func=cmd_project, budget_usd_given=False)

    # 证据面工具：核引用、盘 store、把历史内联产物迁成引用形态（依据 draft/30 §T0-7）。
    sp = sub.add_parser(
        "evidence",
        help="证据面：verify 核一个运行的全文引用 / store 盘一个项目的正文库 / migrate 迁移历史产物",
    )
    sp.add_argument("action", choices=["verify", "store", "migrate"],
                    help="verify <run_dir>；store <project_dir>；migrate <project_dir> [--apply]")
    sp.add_argument("target", help="verify 给运行目录；store/migrate 给项目目录")
    sp.add_argument("--apply", action="store_true",
                    help="migrate 真的改写产物（缺省只 dry-run：这一步改的是历史证据本体）")
    # B 格：这一轮新加的开关 ⇒ 外层四格（`data.text` 是它打印的那份读数）。
    sp.add_argument("--json", action="store_true",
                    help="机器可读：外层四格（ok/state/data/problems），data.text 是读数原文")
    sp.set_defaults(func=cmd_evidence)

    # 产物归属登记（依据 draft/28 §153 的 A3/A4 与 R-52）：谁在哪个路径产出了什么。
    sp = sub.add_parser(
        "artifacts",
        help="产物归属：record 登记 / list 列出 / verify 核对哈希 / owners 问这个路径归谁 / "
             "unowned 找出**没有**归属的路径 / report 渲染成表",
    )
    sp.add_argument("action",
                    choices=["record", "list", "verify", "owners", "unowned", "report"],
                    help="record <路径>；owners <路径>；unowned <目录或文件…>；"
                         "report 把台账渲染成 markdown（--out 给文件，否则打到 stdout）")
    sp.add_argument("target", nargs="*", default=[],
                    help="record/owners 给一个路径；unowned 给一个或多个路径（目录会被展开成文件）")
    sp.add_argument("--producer", default="", help="record：谁产的（角色名 / 工具名 / M）")
    sp.add_argument("--kind", default="file", help="record：产物类别（script / report / paper / …）")
    sp.add_argument("--task-id", default="", help="record：这次产出属于哪一次召唤")
    sp.add_argument("--exit-code", type=int, default=None,
                    help="record：产生它的那次执行的退出码（没跑过就别给，不许拿 0 冒充）")
    sp.add_argument("--note", default="", help="record：人读的补充")
    sp.add_argument("--out", default=None, help="report：写到这个文件（缺省打到 stdout）")
    # B 格：这一轮新加的开关 ⇒ 外层四格（`data.text` 是台账渲染出来的原文）。
    sp.add_argument("--json", action="store_true",
                    help="机器可读：外层四格（ok/state/data/problems），data.text 是读数原文")
    sp.set_defaults(func=cmd_artifacts)

    sp = sub.add_parser(
        "run-agent", help="真跑一次角色循环（模型驱动；退出码六档：0 正常完成 / 1 行为异常 / "
                          "2 研究启动失败 / 3 等待用户 / 4 正常且中途停止 / "
                          "5 正常且自行停止但没有 final）",
        description="真跑一次角色循环。退出码六档："
                    "0 = 正常完成（这一趟给了 final）；"
                    "1 = 行为异常（只留给「真出事」：没接线 / 模型没认 key / 没返回 / "
                    "连不上 / 输出吃光 / 坏 JSON 超限 / 坏参数超限 / 没 notify，以及任何"
                    "没登记的新 stop_reason —— 没登记一律归 1）；"
                    "2 = 研究启动失败（连跑都没开始：检查点读不到 / 任务指纹不符 / "
                    "上一趟已收工 / 会话记录里重建不出那一步）；"
                    "3 = 等待用户（问了人、还停在等回答 —— 既不是完成也不是失败，"
                    "人答完用 --resume 接着跑那一步之后）；"
                    "4 = 系统行为正常且中途停止（用户叫停 —— 强停与优雅停 —— 与预算耗尽"
                    "统一这一档，可 --resume）；"
                    "5 = 系统行为正常且自行停止，但没有 final（原地打转 / "
                    "escalated 交给召唤者）。")
    sp.add_argument("role", choices=list(S.ROLES) + [S.CONDUCTOR_ROLE],
                    help="顶层角色（M = 主控，其余 = A–H）")
    sp.add_argument("--task", required=True, help="这次要做的事（给角色的任务描述）")
    sp.add_argument("--drive", action="append", default=[],
                    help="把某个 (角色.动作) 交给模型驱动，可重复；不写则不改变确定性行为")
    sp.add_argument("--subagents", action="store_true",
                    help="把**所有已声明的角色动作**都交给模型驱动（=「各角色像 subagent」）；"
                         "注意它会替换掉确定性动作（例如 B 的按行整理），批量消化这类活建议"
                         "改用「确定性动作 + 同角色多实例并发」（`conductor.summon_many`）")
    sp.add_argument("--semantic-review", action="store_true",
                    help="给 H 接上语义判据（「结论是否强于引文」）；不写则那一格如实报「没查」")
    sp.add_argument("--experiment-reasoning", action="store_true",
                    help="给 E 接上写脚本的推理（`author_script`：按子目标带来的判据写一份核验"
                         "脚本，例如一个能在 N<=8 上手算核对的玩具例子，然后照常真跑一次）；"
                         "不写则 E 只回 `no_seam`（没接线），"
                         "F 那一轮落 `dead_end(缺工具)` 并向召唤者上报 `missing_input`"
                         "（缺的是 E 的缝，不是脚本）。"
                         "F 的攻坚推理不是开关（2026-10-26 业主裁定：那本来就是 F 的工作方式），"
                         "所以这里没有给 F 的那一条：F 出场就有缝，而 E 这一条默认关"
                         "（与 `--semantic-review` 同一条纪律）")
    sp.add_argument(ALLOW_FOREIGN_FLAG, action="store_true",
                    help="这个目录里已经有用户的投料（例如一篇 PDF），仍然按工作区初始化："
                         f"先落 {WORKSPACE_MARKER} 再 init（与 `init` 的开关逐字同一个）；"
                         "不给这个开关时，'有外来条目'那一档照旧拒绝")
    sp.add_argument("--provider", default=None,
                    help="A 的检索后端，逗号分隔（openalex/crossref/doaj/europepmc/fixture）；"
                         "缺省按配置 `agent_a.providers`，再缺省 openalex —— 与 `run-a` 同口径。"
                         "A 没有后端就不会进登记表：那时任何角色唤起 A 都会如实落 "
                         "`refused/not_wired`（没查成，不是「这个主题没有文献」）。"
                         "想离线验证这条链路就写 `--provider fixture`")
    #: 默认 30（`draft/37` §16 P0）：默认 6 的时候，一个被驱动的动作连"读完一段正文"都不够
    #: —— 真机实测 G 拿了 151 步、89 次在读，最后还是没能落盘一处改动，而框架默认只给 6 步。
    #: 它是报告阈值、不是闸（裁定 12-K）：超过它只会向上报一次账，不强制收工。
    sp.add_argument("--max-steps", type=_non_negative_int, default=30,
                    help="每满几步向父代理报一次步数账（不设步数闸：超了不强制收工）")
    #: 墙钟（`policy.wall_clock_sec`）默认 900 秒：真机里第 8 次派活就是被它挡下的（`deadline_exceeded`）。
    #: 放成可配而不是写死：长任务（审一篇论文）该给一小时量级，短任务仍可以压到几分钟。
    # 2026-10-18（业主口径，逐字）：「不传就是无限制，传多少时间就是多少」。
    # 所以 default 从 3600.0 改成 None（不设上限）。真机代价（`projects/t2y`）：
    # 我没传这个参数 ⇒ 用了缺省 3600 ⇒ 1 小时整切断，而那一刻 M 正要派 B 登记命题
    # （`t-000010 B refused：墙钟截止已过（wall_clock_sec=3600.0）`）⇒ `conjectures 3 / statements 0`。
    sp.add_argument("--wall-clock-sec", type=float, default=None,
                    help="这次运行的墙钟上限（秒）。**不给 = 不设上限**；给了多少就是多少"
                         "（到点后新召唤一律被拒，已在跑的走协作式取消；<=0 同样视为不设）")
    sp.add_argument("--rounds", type=_non_negative_int, default=1,
                    help="跑几轮（>1 走自主轮：按 --report-every 向公共频道汇报）")
    sp.add_argument("--report-every", type=_non_negative_int, default=1, help="每几轮汇报一次")
    sp.add_argument("--budget-usd", type=float, default=None, action=_BudgetUsdAction,
                    help="美元上限（在每次请求之前检查）；"
                         "显式给了就同时落盘到 <工作区>/budget.json")
    sp.add_argument("--sid", default=None, help="会话号（默认当天）")
    sp.add_argument("--resume", action="store_true",
                    help="从检查点续跑：`--rounds >1` 时只跑没做过的轮（任务指纹不一致会被拒）；"
                         "单趟时接着上一趟停下的那一步之后（上一趟停在等用户或步数用尽都能接）。"
                         "指纹不一致 ⇒ 退出码 2")
    sp.add_argument("--user-wait-sec", type=float, default=None,
                    help="问用户时等多久（秒）：缺省 = 一直等到有人答（等待期间不产生 token "
                         "开销，等的是磁盘上的回答事件）；`0` = 登记问题后立刻停下来等"
                         "（退出码 3）。用户裁定「问了就停」，所以不再有 30 秒那一档默认值")
    sp.add_argument("--no-ask", action="store_true",
                    help="无人值守档：问用户被确定性拒绝（不落问题、不停循环，按最保守的做法"
                         "继续并把这件事写进结论）。三态口径：没人在场是「没查成」，"
                         "不是「通过」，更不许降级成「问一下试试」")
    sp.add_argument("--stop-file", default=None,
                    help="停止开关（人可随时按停）：这个文件一出现就停 —— 单趟运行时在"
                         "**步与步之间**查（做完当前这一步再收工，留步检查点与运行记录）；"
                         "`--rounds > 1` 时在**每轮之间**查（当前这一轮跑完再停）")
    sp.add_argument("--json", action="store_true", help="把运行记录打成 JSON")
    sp.set_defaults(func=cmd_run_agent, budget_usd_given=False)

    sp = sub.add_parser("budget",
                        help="这一趟的总预算：看 / 设 / 追加（业主 2026-10-12：不限制步数只限预算，"
                             "运行消耗实时从总预算里扣除，扣完自动优雅停）")
    sp.add_argument("--status", action="store_true", help="只读：总额度 / 已花 / 剩余 / 追加历史")
    sp.add_argument("--set", dest="set_usd", type=float, default=None,
                    help="设一个总额度（覆盖式；第一次设预算用它）")
    sp.add_argument("--add", dest="add_usd", type=float, default=None,
                    help="追加一笔额度（运行期生效：下一个闸门就受新上限约束）")
    sp.add_argument("--by", default="user", help="谁加的（写进追加历史，默认 user）")
    sp.add_argument("--note", default="", help="一句话说明（写进追加历史）")
    sp.add_argument("--fallback-usd", type=float, default=None,
                    help="寄存器缺席时按这个数显示（不给就是不限量）")
    sp.add_argument("--json", action="store_true", help="打成 JSON（给网页/脚本读）")
    sp.set_defaults(func=cmd_budget)

    sp = sub.add_parser("stop",
                        help="停一趟正在跑的 run-agent（`draft/37` §128）：缺省优雅停，"
                             "`--force` 直接杀掉（连子进程）")
    sp.add_argument("--reason", default="user", help="停机理由码（默认 user）")
    sp.add_argument("--force", action="store_true",
                    help="强制停止：不等待收尾，并按进程登记把子进程连子孙一起杀掉")
    sp.add_argument("--sid", default=None, help="这一趟的会话号（写进停机开关，便于核对）")
    sp.add_argument("--status", action="store_true",
                    help="只看状态：开关在不在、登记里哪些进程还活着")
    sp.add_argument("--clear", action="store_true",
                    help="撤掉停机开关（接着跑之前要先撤，否则下一趟第 0 步就收工）")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("inbox", help="列出等着用户回答的问题（只读；不给 --sid 就扫全部会话）")
    sp.add_argument("--sid", default=None,
                    help="只查这一个会话；不给则扫该工作区所有会话（真机每一趟都有自己的 "
                         "sid，只看缺省会话会把「它在等什么」读成「没有待答」）")
    sp.add_argument("--json", action="store_true", help="打成 JSON")
    sp.set_defaults(func=cmd_inbox)

    sp = sub.add_parser("answer", help="代用户回答一个问题（写 user_answer；回答是 append-only 的）")
    sp.add_argument("qid", help="问题号（见 `agentflow inbox`）")
    sp.add_argument("text", nargs="?", default=None,
                    help="回答正文（等价于 --custom；与 --select 可以同时给）")
    sp.add_argument("--select", action="append", default=None,
                    help="选中的选项 label，可重复（DSH 的 selected：0/1/n 个）")
    sp.add_argument("--custom", default=None,
                    help="补充或覆盖的正文（DSH 的 custom：对多选是补充、对单选是覆盖）")
    sp.add_argument("--sid", default=None, help="问题所在会话号（见 `agentflow inbox`）")
    sp.set_defaults(func=cmd_answer)

    # 格数不手抄：判据真身是 `closing.DEFAULT_CHECKS`，这里现读它的长度
    # （`draft/63` §3 #3 的口径：这类定值随代码变，手抄一份就是给自己留一个会过期的数 ——
    # 真机读数里它已经漂过一次：手抄"五条"而真身是 8 格）。
    from . import closing as _CL

    sp = sub.add_parser(
        "closing",
        help=f"跑收工门（draft/37 §16 P3 的 {len(_CL.DEFAULT_CHECKS)} 格；退出码 0/1/2）")
    sp.add_argument("--project-dir", default="",
                    help="项目根目录（正文与编译回执在 <它>/out/paper/；不给 ⇒ 论文那一格是「没查成」）")
    sp.add_argument("--report", default="",
                    help="报告路径（不给且没给 --project-dir ⇒ 报告形状那一格是「没查成」）")
    # 内容级验收（`draft/37` §17.3）那一段的入参：只影响那一段的读数，
    # 不影响退出码（退出码仍然只由收工门定）。三个都给缺省值 ——
    # 缺省时那几格记「没查成」，不折成通过。
    sp.add_argument("--cap-usd", type=_non_negative_float, default=None,
                    help="这一趟的成本上限（美元）—— 内容级验收的「在成本上限内」用；"
                         "不给 ⇒ 那一格是「没查成」")
    sp.add_argument("--acceptance-sid", default=None,
                    help="这一趟的会话号（内容级验收的「三态分支」那一格用；"
                         "不给 ⇒ 那一格是「没查成」，不按缺省会话读）")
    sp.add_argument("--no-review-acceptance", action="store_true",
                    help="不跑收工门之后的那个内容级验收读数（缺省就跑）")
    # M 的判据（业主 2026-10-09：「是否收工不要用机械判据，由 M 制定的目标是否达成为准」）：
    # 缺省 = 读运行内落盘的那一份（`out/review/m-verdicts.jsonl`）；显式给这里三个
    # 开关就按命令行这一份判（人/CI 代述 M 的说法时用）。都不给又没有落盘的那一份
    # ⇒ 退出码 2（「没人判过」），不是 0 也不是 1。
    sp.add_argument("--goal", default="", help="（M 的判据）这一趟的目标，一句话")
    sp.add_argument("--basis", default="", help="（M 的判据）凭什么这么判：读数/交付物路径")
    _met = sp.add_mutually_exclusive_group()
    _met.add_argument("--goal-met", dest="goal_met", action="store_true", default=None,
                      help="（M 的判据）目标达成了 ⇒ 收工（退出码 0）")
    _met.add_argument("--goal-not-met", dest="goal_met", action="store_false",
                      help="（M 的判据）没达成 ⇒ 不退（退出码 1）")
    sp.set_defaults(func=cmd_closing)

    # 项目状态报告（`draft/39` §4）：只读 + 零模型调用 —— 用户中途想知道情况时用它，
    # 而不是去问 M 一句（那条路会让 M 停下来等人，正好与"不打断协作"相反）。
    sp = sub.add_parser("status-report",
                        help="项目状态报告（只读台账与手稿；落 out/review/STATUS-<ts>.{md,json}）")
    sp.add_argument("--since", default="", help="只统计这个 ISO 时间前缀之后的读数（如 2026-10-05）")
    sp.add_argument("--out", default="", help="报告落哪个目录（缺省 <工作区>/out/review）")
    # B 格：这一轮新加的开关 ⇒ 外层四格。这条命令真正的机器可读那一份一直是它落盘的
    # `STATUS-<ts>.json`（路径就在 data.text 的读数里），`--json` 给的是外层四格 +
    # 那段人读的原文，免得脚本去猜文件名的通配符。
    sp.add_argument("--json", action="store_true",
                    help="机器可读：外层四格（ok/state/data/problems），data.text 是报告原文")
    sp.set_defaults(func=cmd_status_report)

    # 统计量（测试工具，业主 2026-10-24）：先只有"按角色 × 类目数错误动作"，本轮扩成
    # 四张读数（errors / flow / cost / gates）＋ 一条 `all`。读数本身全在 `readouts`
    # （统一五键 + 三态），这里只挂子命令与开关 —— 于是"同一个数两份实现"不会从这里回来。
    # `--root` 用 `default=argparse.SUPPRESS`：子 parser 的缺省 None 会把用户写在子命令
    # 前面的顶层 `--root` 覆盖掉（与 `start` 那一组同一个理由）。
    sp = sub.add_parser("stats", help="统计量（只读测试工具）：错误动作 / 动作流 / 花费 / 收工门")
    _ssub = sp.add_subparsers(dest="stats_cmd", metavar="<统计量>")
    for _name, _kind_help in STATS_KINDS:
        _sp = _ssub.add_parser(_name, help=_kind_help)
        _sp.add_argument("--root", default=argparse.SUPPRESS, help="工作区根（与顶层 --root 同义）")
        _sp.add_argument("--json", action="store_true", help="机器可读（JSON）")
        if _name in ("gates", "all"):
            # 只对 gates 有意义的两格：不给 ⇒ 依赖它们的那几格如实记 unknown（不是 pass）。
            _sp.add_argument("--project-dir", default="",
                             help="（gates/all）项目根：论文 / 验收 / 产物台账那几格要它")
            _sp.add_argument("--report", default="",
                             help="（gates/all）报告路径：报告形状那一格要它")
        if _name == "errors":
            # 老形态的兼容出口：不给这个开关时按 `errorstats` 的原样打（逐字节不变）。
            _sp.add_argument("--readout", action="store_true",
                             help="按新的五键读数形状打（checked/state/reason/data/problems），"
                                  "与 flow/cost/gates 同一个外层；不给则保持老形态")
        _sp.set_defaults(func=cmd_stats, stats_cmd=_name)
    sp.set_defaults(func=cmd_stats, stats_cmd="errors")

    # 用户端网页：给人看"它在等什么、跑到哪了、上一趟干了什么"，并让人在那里回答问题。
    # 它是「只读投影」（每次请求都从盘上现读），唯一的写路径是 `POST /answer` → `userio.answer_question`。
    sp = sub.add_parser("web", help="起用户端网页（本地小服务：待回答面板 / 运行态 / 事件回放）")
    sp.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认只监听本机；给 0.0.0.0 才会被别的机器访问）")
    sp.add_argument("--port", type=int, default=8788, help="端口（0 = 让系统给一个空闲端口）")
    sp.add_argument("--open", action="store_true", help="起来之后用默认浏览器打开")
    sp.add_argument("--json", action="store_true",
                    help="只打印一行 URL 的 JSON（起后台任务时用它拿确切地址）")
    sp.add_argument("--token", default="",
                    help="访问口令（也可用环境变量 AGENTFLOW_WEB_TOKEN；给了就必须带上）")
    # 裁定 T1：只加这两个开关。W3/W4 之后它们真的接线（`writes.authorize()` 的第 3/4 层），
    # 下面两句 help 逐字说明它们各管哪一面 —— 免得读 help 的人以为"缺省只读"是"还没接线"。
    sp.add_argument("--allow-writes", action="store_true",
                    help="允许写面（起一趟 / 插话 / 答问 / 叫停 / 改设置 / 改预算）；"
                         "缺省只读，不开这一档时写端点一律 403")
    sp.add_argument("--no-settings-write", action="store_true",
                    help="关掉设置写面（只关 POST /api/settings，其余写面照旧）")
    sp.set_defaults(func=cmd_web)

    # 体检：跑之前先知道这台机器能做哪些事（有没有 key / 有没有证明检查器 / Mathlib 对不对得上）。
    # 它不发起任何模型调用 —— 于是"形式化能不能做"这件事在花钱之前就有一个可读的三态读数。
    sp = sub.add_parser("doctor", help="体检：这台机器能做哪些事（不花钱；0 齐 / 1 有缺 / 2 没查成）")
    sp.add_argument("--json", action="store_true", help="把体检结果打成 JSON")
    sp.add_argument("--selfcheck", action="store_true",
                    help="只做包内源码自检：逐文件 compile，坏文件报『文件:行:列 + 错误』"
                         "（不探测工具链、不编译 Mathlib、不花钱；0 干净 / 1 有坏文件 / 2 没查成）")
    sp.set_defaults(func=cmd_doctor)

    # 两档提示词缓存（业主 2026-10-23：「把两档缓存落地为用户使用系统时可调用的工具」）。
    # 两条子命令的形状（`status` 只读 / `warm --lean on|off|both [--dry-run]` 会花钱）
    # 定在 `cachectl.add_subcommands` 里，本文件只负责把它挂到这一张子命令表上 —— 于是
    # "缓存怎么读"只有一个真身，命令行与网页按钮读的是同一份实现。
    from .cachectl import add_subcommands as _add_cache_subcommands

    _add_cache_subcommands(sub)
    return p


def _print_subcommand_help(parser: argparse.ArgumentParser, name: str) -> None:
    """把某个旧命令自己的 `--help` 原样打出来（组页要接在它前面时用）。

    为什么读现成那一份 parser 的子命令表（`choices`）而不是再 `build_parser()` 一次：那会造出第二份 parser，
    而"组页后面接的真是那条命令的 help"这件事必须拿同一份对象才算数。
    """
    action = _subparsers_action(parser)
    child = (getattr(action, "choices", None) or {}).get(name) if action else None
    if child is not None:
        child.print_help()


#: `--json` 的外层四格（业主 2026-10-24 批的 B 格）。`inspect` 那一组的机器可读输出
#: 一律是这一层，里面才是各命令自己那一份 `data`。
#:
#: 为什么还要一层外壳：三态是这套框架的硬纪律，而"每条命令各拿一个字段表示三态"
#: （`ok` / `checked` / `state` / 出没出问题）必然会漂。外壳把这件事收成一处，
#: 于是脚本可以只写一次 `if not doc["ok"]`。
JSON_ENVELOPE_KEYS: tuple[str, ...] = ("ok", "state", "data", "problems")

#: 三态取值（`state` 那一格）：`checked` 查过了 / `failed` 查过了有问题 / `unknown` 没查成。
JSON_ENVELOPE_STATES: tuple[str, ...] = ("checked", "failed", "unknown")

#: 这四条命令的 `--json` 是本轮新加的（它们此前没有这个开关），所以外层四格
#: 在两条路上都生效。另外六条（stats / tools / cache / budget / doctor / verify）
#: 早就有自己的 `--json`，那些输出已有消费者：旧路径一个字节都不许变，只有从
#: `inspect` 那一组走时才套外层（见 `_wants_json_envelope` 的注释）。
ENVELOPE_ONLY_COMMANDS: frozenset[str] = frozenset({
    "status-report", "evidence", "artifacts", "analyze"})


def _envelope_state(code: int) -> str:
    """退出码 → 三态词（与全仓 0/1/2 的口径逐字对应）。"""
    if code == 0:
        return "checked"
    if code == 1:
        return "failed"
    return "unknown"


def _envelope_payload(raw_text: str, code: int, problems: list[str]) -> dict:
    """把一条命令打印的原文装进外层四格（幂等：已经是外层就原样放行）。

    认得四种输入：

    1. 已经是四格外层（`ok`/`state`/`data`/`problems` 齐）⇒ 原样返回（幂等点）。
    2. 是读数层那五格（`checked`/`state`/`reason`/`data`/`problems`，见 `readouts`）
       ⇒ 翻成外层四格：`ok` 由退出码给，`problems` 里补上那条 `reason`。
       为什么要有这一支：`agentflow inspect stats flow --json` 走的正是这里，而它的
       `data` 已经是"这一类读数自己的表" —— 再套一层会得到 `data.data` 那种读不下去的形状。
    3. 是一个 JSON 对象（各命令自己那一份）⇒ 放进 `data`。
    4. 不是 JSON（`analyze` / `evidence` / `artifacts` / `status-report` 这几条还没有
       结构化输出）⇒ `data = {"text": 原文}`。这一格是诚实的占位：它不假装有结构，
       也没把原文丢掉。
    """
    state = _envelope_state(code)
    body = str(raw_text or "")
    parsed: object = None
    if body.strip():
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            parsed = None
    if isinstance(parsed, dict):
        if set(JSON_ENVELOPE_KEYS) <= set(parsed):
            extra = [str(p) for p in (parsed.get("problems") or [])]
            return {"ok": bool(parsed.get("ok")) and code == 0,
                    "state": str(parsed.get("state") or state),
                    "data": parsed.get("data") if isinstance(parsed.get("data"), dict) else {},
                    "problems": extra + list(problems)}
        if {"checked", "state", "data"} <= set(parsed):
            notes = [_problem_line(p) for p in (parsed.get("problems") or [])]
            reason = str(parsed.get("reason") or "")
            if reason and not parsed.get("checked"):
                notes.insert(0, reason)
            return {"ok": bool(parsed.get("checked")) and code == 0,
                    "state": str(parsed.get("state") or state),
                    "data": parsed.get("data") if isinstance(parsed.get("data"), dict) else {},
                    "problems": notes + list(problems)}
        return {"ok": code == 0, "state": state, "data": parsed,
                "problems": list(problems)}
    data: dict = {"text": body}
    return {"ok": code == 0, "state": state, "data": data, "problems": list(problems)}


def _problem_line(item: object) -> str:
    """把一条 `problems` 条目折成一行文本（外壳里的 `problems` 一律是字符串数组）。

    读数层给的是 `{"code", "detail"}`（结构化），stderr 给的是原话（字符串）。外壳里
    两者同形，脚本才能只写一次 `for line in doc["problems"]`。
    """
    if isinstance(item, Mapping):
        code = str(item.get("code") or "")
        detail = str(item.get("detail") or "")
        return f"[{code}] {detail}" if code else detail
    return str(item)


def _wants_json_envelope(request: tuple[str, str, str] | None, args) -> bool:
    """这一趟要不要套 `--json` 的外层四格。

    两条路各有一条理由（缺一条就会有一半的消费者拿到旧形状）：

    - 从 `inspect` 那一组走（`agentflow inspect <成员> …`）：外层一律套上 ——
      那一组是新入口，它的机器可读输出就是"契约"本身；
    - 旧路径 + 本轮新加 `--json` 的那四条（`status-report` / `evidence` /
      `artifacts` / `analyze`）：它们此前根本没有这个开关，所以没有旧形状可破坏。

    为什么另外六条旧路径不套：`tools --json` 的输出有一份冻结快照判据逐字钉着
    （`tests/golden/tool_surface_snapshot.json`），`budget` / `verify` / `doctor` /
    `stats errors` / `cache` 各有消费者；把它们的字节改掉就不是"旧指令行为不变"了。
    """
    if not getattr(args, "json", False):
        return False
    if request is not None and request[0] == "inspect":
        return True
    return str(getattr(args, "cmd", "")) in ENVELOPE_ONLY_COMMANDS


def _run_enveloped(args) -> int:
    """跑一次命令，把它打印的东西收起来，打一份外层四格的 JSON。

    为什么要"收起来再打"：这四条命令（与那六条）都是自己 `print` 的，它们不该为了
    JSON 长出第二套渲染（那正是"同一个数两份实现"）。收 stdout、把 stderr 的每一行
    记进 `problems`，是唯一不碰它们内部的做法。

    退出码原样返回：外层四格是给人/脚本读的，进程退出码才是 CI 的判据 —— 两处不许
    分家，所以这里不打折也不升级。
    """
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = int(args.func(args) or 0)
    problems = [line for line in str(err.getvalue()).splitlines() if line.strip()]
    doc = _envelope_payload(str(out.getvalue()), code, problems)
    if code != 0 and not doc["problems"]:
        # 没通过却一条原因都没打给 stderr 的命令（`doctor` / `cache` 是这一档：它们的
        # 逐条原因在 `data` 里）。外壳不许在这种时候给一个空 `problems` —— 读脚本的人
        # 会以为"失败了但没原因"。所以补一句指路，指到 `data` 里那一份。
        doc["problems"] = [f"退出码 {code}（{doc['state']}）：这一条没把原因打到 stderr，"
                           "逐条原因在 data 里那份读数（doctor 看 data.checks）"]
    print(json.dumps(doc, ensure_ascii=False, indent=2, default=str))
    for line in problems:
        print(line, file=sys.stderr)
    return code


def _group_request(argv: list[str]) -> tuple[str, str, str] | None:
    """argv 是不是一个"组"的请求：返回 `(组名, 成员名或空串, 原样的那个词)`，否则 None。

    四组之外一律 None（照旧走 argparse）。三档形态都从这里出去，`main` 只需要看
    `member` 是空串（打组页）、`-h/--help`（打组页 + 旧命令自己的 help）还是别的词
    （不认识 ⇒ 人话点名）。`run` 那一组特殊：它的组名同时是旧命令名，所以"裸 `agentflow
    run`"与"`agentflow run <不是成员>`"都原样交回 argparse —— 那条命令一个字节都不许动。
    """
    index = _command_index(argv)
    if index is None:
        return None
    group = str(argv[index])
    if group not in GROUP_MEMBERS:
        return None
    member = str(argv[index + 1]) if index + 1 < len(argv) else ""
    return (group, member, str(argv[index]))


def main(argv: list[str] | None = None) -> int:
    """命令总入口：钉编码 → 认组页 → 折回旧名 → 解析 → 交给 handler（必要时套 `--json` 外壳）。

    读写：这一层自己不读写任何工作区文件；它只钉输出编码（`pin_utf8`）、认 `--help-legacy`、
    把 `agentflow <组> <成员>` 折回旧名（`canonical_argv`），并把三类"没跑成"翻成退出码
    2：源码/import 坏了（C6 那一级，报 `文件:行`）、`StoreError`、以及 Ctrl-C。
    实现方式一句话：解析层一个字不动，分层与外壳都发生在"进 handler 之前"那几行 ——
    于是 28 个旧命令的 `args`、旗标、输出与退出码全部保持原样。
    退出码：handler 返回什么就是什么（0 / 1 / 2 的三态口径在各命令自己的 docstring 里）。
    """
    # 先把输出编码钉住再做任何事：GBK 控制台编不出摘要里的 `⇒` ⇒ print 抛异常 ⇒ 进程以 1
    # 结束，而 1 是"查过了、发现问题"。那会把 `run` 无 key 的受控码 2（没跑成）反转成 1。
    pin_utf8()
    raw = list(sys.argv[1:] if argv is None else argv)
    # 不带任何参数 ⇒ 进交互台。理由：这套工具的动词与开关多到"不看文档就用不起来"，
    # 而它的主要用户是研究者，不是每天敲这串命令的人。给一个菜单不是为了炫技，
    # 是为了让"能用"这件事不依赖记忆。
    if not raw:
        return shell()
    # ---- 新分层（`COMMAND_GROUPS`）的两个入口：组页与"这个组里没有它"的人话。
    # 为什么必须在 `parse_args` 之前：argparse 不认识组名（`choices` 里只有 28 个旧名），
    # 让它先看到 `inspect` 只会得到 `invalid choice: 'inspect'` —— 分层就被藏进文档里了。
    request = _group_request(raw)
    if request is not None:
        group, member, word = request
        members = GROUP_MEMBERS[group]
        wants_page = member in ("", "-h", "--help")
        if wants_page and not (group == "run" and member == ""):
            # `run` 那一组的裸组名不归这里：`agentflow run` 是旧命令本身（缺 --topic 的
            # 那句人话由 argparse 给），组页走 `agentflow run --help`。
            parser = build_parser()
            print(_render_group_help(group, parser))
            if group == "run":
                # 组名与旧命令同名：把旧命令自己的 help 接在同一页后面，于是
                # `agentflow run --help` 既讲清了组，也没有丢掉任何一格旗标。
                print()
                _print_subcommand_help(parser, "run")
            if member in ("-h", "--help"):
                # 与 argparse 的 `--help` 同一条契约：先打印、再以 SystemExit(0) 结束
                # （`agentflow run --help` 这一档改前就走 argparse，进程内调用方
                # 一直靠 `except SystemExit` 接它）。
                raise SystemExit(0)
            return 0
        if (not wants_page and not member.startswith("-")
                and member not in members and group != "run"):
            # `run` 那一组不接这一档：它的组名同时是旧命令名，不认识的第二个词照旧交给
            # argparse（`unrecognized arguments`），那条命令的行为一个字节都不改。
            print(f"[用法错误] `{group}` 这一组里没有 `{member}`。\n"
                  f"  组内成员：{'  '.join(members)}\n"
                  f"  看这一页：`agentflow {group} --help`；"
                  f"看某一条的旗标：`agentflow {group} <成员> --help`", file=sys.stderr)
            return 2
    raw = canonical_argv(raw)
    parser = build_parser()
    args = parser.parse_args(raw)
    tty.set_style(color=False if (args.no_color or args.plain) else None,
                  charset="ascii" if args.plain else None)
    if getattr(args, "help_legacy", False):
        print(_render_legacy_help())
        return 0
    if args.cmd is None:
        return shell()
    envelope = _wants_json_envelope(request, args)
    try:
        if envelope:
            return _run_enveloped(args)
        return args.func(args)
    except (SyntaxError, ImportError) as e:
        # 启动自检的第一级（`draft/145` 的 C6）：某个模块在运行时才 import 到它时坏了 ⇒
        # 报"文件:行 + 错误"，不许把三十行栈甩给用户。`IndentationError` 是
        # `SyntaxError` 的子类，所以它也在这一档里。
        print(_broken_source_notice(e), file=sys.stderr)
        return 2
    except StoreError as e:
        print(f"[store 错误] {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        # `FINAL-R5-02`：`agentflow run` 的取消此前是不可达的，而且被中断的那一跑在磁盘上
        # 与"从来没跑过"同形（`KeyboardInterrupt` 是 `BaseException`，穿出 `except Exception`）。
        # 这里按三态纪律把它记成"没查成"（退出码 2），并逐字说清"产物可能不完整" ——
        # 不假装六件产物已经写齐（那要靠真正的取消面才能做到，见 run_topic 的 docstring）。
        print("[已中断] 本次没有跑完（Ctrl-C）⇒ 退出码 2 = 没查成；"
              "产物目录里可能只有部分文件，不许当成一次正常运行的读数。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
