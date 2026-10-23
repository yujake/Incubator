"""`docs/ROLE-SPECS.md` 的结构完整性门 + 与实时工具普查的对账。

## 这个文件在测什么，为什么它值得存在

用户对正式版的要求里有两条是文档要求："为 A–H 八个角色各写详细规格说明书"，并逐字点名了小节
（职责 / 明确不负责 / 逐个工具的契约 / 状态机 / 预算与终止 / 三态与失败模式 / 不变式 / 接口）；
2. 审计判据里有 "docstring 与实现一致"。

一份 2000+ 行的规格最容易的坏法不是写错，而是写漏 —— 少写一节，没有任何东西会变红，而读者会以为"这一节大概没有那些内容"。本文件把"写漏"变成红点。

## 三态（本文件的负控重点）

`tools/verify_role_specs.py` 有三个结论，本文件对三个都有断言：

- `ok`（结构完整）/ `incomplete`（查过、有缺失）/ `unknown`（没查成：文档不存在、
读不到、或一个角色节都没匹配到）。

`unknown` 绝不能等于 `ok` —— 文档被改名或格式被改坏时，"什么都没读到"必须报"没查成"，而不是"通过"。这是本项目反复踩过的坑（`DEVELOPMENT.md` §3 纪律 1）。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DOC = REPO / "docs" / "ROLE-SPECS.md"
#: N/O/Q 三角色的草稿（登记前不进 `docs/ROLE-SPECS.md`，由 `--roles` 单独查）。
DRAFT_NOQ = REPO / "docs" / "ROLE-SPECS-DRAFT-N-O-Q.md"

#: 门口径的 stdio 编码（`X-91.5-2`）：判据不许依赖控制台代码页。
#:
#: `tools/verify_role_specs.py` 的输出里有非 ASCII（`⇒`、"对账没做"、"`--roles` 非法"、
#: `[OK ] …` 的中文小节名）。子进程往管道写时 `sys.stdout.encoding` 取的是
#: `locale.getpreferredencoding(False)` —— 在 GBK 控制台（本机 `chcp` = 936）上是 `cp936`：
#: 轻则父进程按 `utf-8` 解码成乱码（那 4 条断言红），重则子进程自己
#: `UnicodeEncodeError` 崩掉、退出码从 2 变成 1（`--no-live` 那一档实测如此）。
#: 把子进程的 stdio 显式钉成 utf-8 ⇒ 读数是"判据要判的那件事"，与跑它的终端代码页无关；
#: 这两个变量也正是四道门跑本门时用的环境（`temp/run_gates.py` 显式设了它们）。
_GATE_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
#: 与 `_GATE_ENV` 同源，但摘掉 `PYTHONPATH`：`test_the_cli_reports_unknown_when_the_package_cannot_be_imported`
#: 要靠"子进程 import 不到 `agentflow`"来造 `unknown`（父进程的 `PYTHONPATH=src` 会被继承）。
_GATE_ENV_NO_PYTHONPATH = {k: v for k, v in _GATE_ENV.items() if k != "PYTHONPATH"}


def _load_gate():
    """按路径导入 `tools/verify_role_specs.py`（`tools/` 不是包）。"""
    spec = importlib.util.spec_from_file_location(
        "_verify_role_specs_under_test", REPO / "tools" / "verify_role_specs.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


G = _load_gate()


# ============================================================ 正向：真实文档


def test_real_role_specs_are_structurally_complete():
    """正向：真实文档里 9 个角色节（A–H + M）各 8 个必备子节齐全，顺序也对。"""
    result = G.check(DOC)
    assert result["verdict"] == "ok", result["reason"]
    assert [s["role"] for s in result["sections"]] == list(G.EXPECTED_ROLES)


def test_every_role_section_has_ten_numbered_subsections():
    """正向：每节 10 个编号子节（8 个必备 + 「一句话定位」+「自检入口」）。"""
    result = G.check(DOC)
    bad = {s["role"]: s["subsections"] for s in result["sections"] if s["subsections"] < 10}
    assert not bad, f"这些角色节的编号子节少于 10 个：{bad}"


def test_cli_gate_exits_zero_on_the_real_document():
    """端到端：门脚本本身以退出码 0 结束（不是只有函数返回对）。"""
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py")],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert p.returncode == 0, p.stdout + p.stderr


# ============================================ `H-8`：与现场装配的逐角色对账


def test_the_live_reconciliation_agrees_on_the_real_document():
    """正控：真文档的逐角色工具条数必须与现场装配一致（`H-8` 的核心判据）。"""
    live, reason = G.live_tool_counts(root=REPO)
    assert live is not None, reason
    result = G.check(DOC, live_counts=live, live_reason=reason)
    assert result["verdict"] == "ok", result["reason"]
    assert result["live_counts"] == live


def test_negative_control_a_wrong_tool_count_is_caught(tmp_path):
    """负控（`H-8`）：把 §H 的标题数字改成 `1` ⇒ 必须报 `incomplete` 并点名是哪一节。

    改前这一条全绿：旧门只检查"标题里能不能读出一个数字"，不比对现场实测值
    （审计者 H 的原始负控：把 `37` 改成 `999`、`22` 改成 `1`，门照报 `[OK]`、退出码 0）。
    """
    live, reason = G.live_tool_counts(root=REPO)
    assert live is not None, reason

    def tamper(lines: list[str]) -> list[str]:
        return [ln.replace(f"### H.4 工具面（{live['H']} 个，实测）", "### H.4 工具面（1 个，实测）")
                for ln in lines]

    assert _mutate(tmp_path, tamper).read_text(encoding="utf-8") != DOC.read_text(encoding="utf-8"), \
        "夹具前提：§H.4 的标题里能读到当次的条数"
    result = G.check(_mutate(tmp_path, tamper), live_counts=live, live_reason=reason)
    assert result["verdict"] == "incomplete", result["reason"]
    assert "§H" in result["reason"] and "不符" in result["reason"], result["reason"]


def test_negative_control_999_is_also_caught(tmp_path):
    """负控 2：换成 `999` 同样必须红（判据不是对着数字 `1` 特判）。"""
    live, reason = G.live_tool_counts(root=REPO)
    assert live is not None, reason

    def tamper(lines: list[str]) -> list[str]:
        return [ln.replace(f"### H.4 工具面（{live['H']} 个，实测）", "### H.4 工具面（999 个，实测）")
                for ln in lines]

    result = G.check(_mutate(tmp_path, tamper), live_counts=live, live_reason=reason)
    assert result["verdict"] == "incomplete", result["reason"]


def test_negative_control_a_correct_number_elsewhere_does_not_excuse_the_bad_one(tmp_path):
    """`R6-3` 负控：对账必须锚定那一格，别处出现正确数字不算。

    改前判据是 `want not in got`，而 `got` 取的是该角色所有子节标题里的数字
    ⇒ 只要 §H 下任意别处标题里出现过 `25 个`，§H.4 写成 `999 个` 也照样 `ok`，
    还会打印"逐角色工具条数与现场装配一致"（重审实测的那个形态）。
    这里把两件事同时做出来：工具面写 `999`、别处补一个当次的正确数字 ⇒ 必须红。

    那两个数从当次普查读出来（不写死）：写死会让夹具先过期而红，
    红的理由变成"夹具过期"，而这条用例问的是"判据会不会咬人"。
    """
    live, reason = G.live_tool_counts(root=REPO)
    assert live is not None, reason
    hit = live["H"]

    def tamper(lines: list[str]) -> list[str]:
        out: list[str] = []
        injected = False
        for ln in lines:
            ln = ln.replace(f"### H.4 工具面（{hit} 个，实测）", "### H.4 工具面（999 个，实测）")
            out.append(ln)
            # 在 §H 的另一个子节标题后面塞一个正确数字（"别处有 22"）
            if (not injected and re.match(r"^###\s+H\.\d+\s+", ln)
                    and "999" not in ln and "工具面" not in ln):
                out[-1] = ln.rstrip() + f"（{hit} 个，实测）"
                injected = True
        assert injected, f"夹具前提：在 §H 里塞一个『{hit} 个』的别处标题"
        return out

    live, reason = G.live_tool_counts(root=REPO)
    result = G.check(_mutate(tmp_path, tamper), live_counts=live, live_reason=reason)
    assert result["verdict"] == "incomplete", result["reason"]
    assert "999" in result["reason"], result["reason"]
    assert "不符" in result["reason"], result["reason"]


def test_without_a_live_census_the_check_is_silent_about_the_numbers() -> None:
    """边界：不注入 `live_counts` ⇒ 只判结构（这样"包 import 不进来"时本门仍能跑）。

    但调用方不许把它读成"数字对上了" —— `main()` 在"要做的对账没做成"时
    把 verdict 降成 `unknown`（见下一条）。
    """
    result = G.check(DOC)
    assert result["verdict"] == "ok"
    assert result["live_counts"] is None
    assert "未与现场装配对账" in result["reason"], result["reason"]


def test_the_cli_reports_unknown_when_the_package_cannot_be_imported(tmp_path):
    """负控 3（三态）：装配不了工具层 ⇒ 退出码 2（没查成），不是 0。

    这条与 `H-8` 的"要不要让门依赖包可导入"那个取舍直接相关：选的是"依赖它、但依赖不上时如实报未知"——不静默退回"只判结构"。

    实测（第一版写错）：`--root <空的 tmp>` 不足以让装配失败 ——`live_tool_counts` 会 `sys.path.insert(0, root/"src")`，
    而父进程的`PYTHONPATH=src` 会被子进程继承（`agentflow` 于是仍然 import 得到）。判据要按事实造：必须把 `PYTHONPATH` 从子进程环境里摘掉。

    `X-91.5-2`：摘掉 `PYTHONPATH` 的同时必须把 stdio 编码钉回来 ——这条断言读的是子进程打印的中文（"对账没做"），不钉的话在 GBK 控制台下父进程按 utf-8 解码得到乱码、断言红，
    而它与"包装配不上"这件事无关⇒ 这里用 `_GATE_ENV_NO_PYTHONPATH`（同源、只少 `PYTHONPATH`）。
    """
    root = tmp_path / "nowhere"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "ROLE-SPECS.md").write_text(DOC.read_text(encoding="utf-8"),
                                                 encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--root", str(root)],
        cwd=str(root), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=120, env=_GATE_ENV_NO_PYTHONPATH,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    assert "[unknown]" in p.stdout, p.stdout
    assert "对账没做" in p.stdout, p.stdout


def test_every_capturing_subprocess_pins_the_stdio_encoding() -> None:
    """`X-91.5-2` 的回归判据：本文件里每一个捕获输出的子进程都必须显式钉住 stdio 编码。

    为什么值得一条判据（而不是"这一次改完就算"）：`X-91.5-2` 的形态是只在某些环境里红—— 门口径环境（`PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`）下全绿，GBK 控制台（本机
    `chcp` = 936）下 4 条红。一次性修法挡不住下一个人新加一条 `subprocess.run(...)`：新调用不带 `env=` 时，乱码 / 子进程
    `UnicodeEncodeError` 那一档就静默回来了，而它在门口径环境下照样绿。

    判据落在本文件自己的源码上（不靠人记得）：`capture_output=True` 的`subprocess.run(...)` 必须在同一个调用里出现
    `_GATE_ENV`（`_GATE_ENV_NO_PYTHONPATH`是同一份约定的派生，名字里含它）或逐字写了 `PYTHONIOENCODING`。扫不到任何这样的调用 ⇒
    报"失去对象"（删掉子进程不等于编码被钉住了）。
    """
    src = Path(__file__).read_text(encoding="utf-8")
    capturing: list[int] = []
    unpinned: list[int] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "run"):
            continue
        segment = ast.get_source_segment(src, node) or ""
        if "capture_output=True" not in segment:
            continue
        capturing.append(node.lineno)
        if "_GATE_ENV" not in segment and "PYTHONIOENCODING" not in segment:
            unpinned.append(node.lineno)
    assert capturing, (
        "一条 `capture_output=True` 的 `subprocess.run` 都没扫到 —— 判据失去对象"
        "（删掉那些子进程、或改掉 `run` 的写法，都不等于编码已经被钉住）"
    )
    assert not unpinned, (
        f"这些捕获输出的子进程没有钉住 stdio 编码（`X-91.5-2` 会在 GBK 控制台下复发）："
        f"行 {unpinned}"
    )


def test_no_test_module_pollutes_the_parent_env_with_a_stdio_encoding() -> None:
    """`X-91.5-2` 的根因判据（2026-10-15 加）：父进程的编码变量不许被会话级改写。为什么上面那条不够：它扫的是 `Path(__file__)` —— 只管得住本文件。实测就漏了
    `tests/test_temp_root_pin.py`：全量跑里它是唯一那条"只在全量跑里红、单独跑是绿的"用例。机制（已复现到字节，3.25 秒）：本文件此前在三处用
    `os.environ.setdefault("PYTHONIOENCODING", "utf-8")`改了父进程的环境 ⇒ 按目录字母序跑在 `test_temp_root_pin.py` 之前 ⇒
    那个文件起子进程时把变量继承下去 ⇒ 子进程吐 UTF-8、父进程按 GBK 解 ⇒ `_readerthread`
    抛`UnicodeDecodeError: 'gbk' codec can't decode byte 0xa2 in position 584`。为什么判"根因"而不是去把 `tests/` 里那 15 处没钉编码的
    `subprocess.run` 逐个改掉：编码的唯一正确钉法是"在起子进程那一处钉"（`subprocess.run(..., env=)` 或 `encoding=`）。在会话级改
    `os.environ` 是跨测试的隐式耦合 —— 它让"哪个文件先跑"变成另一个文件红绿的条件，而那正是这条缺陷的形态。所以这里禁掉的是那种写法本身：要传编码就拼一份 env
    传下去（`{**os.environ, "PYTHONIOENCODING": ...}`），不要改进程自己的环境。判据用 AST 而不是文本扫描：第一版按行找那几个字面量，
    结果是它把本文件里解释这件事的注释也当成了违规（注释里逐字引用了被禁的写法）——文本扫描分不清"代码"与"在讨论这段代码的话"。AST 只认真正会执行的那两种形态：`os.environ.setdefault(...)` /
    `os.environ[...] = ...`。
    """
    banned_vars = ("PYTHONIOENCODING", "PYTHONUTF8")
    mutating_attrs = {"setdefault", "update", "pop"}
    bad: list[str] = []
    saw_correct_pattern = False
    for p in sorted((REPO / "tests").rglob("*.py")):
        src = p.read_text(encoding="utf-8")
        if "{**os.environ" in src and any(v in src for v in banned_vars):
            saw_correct_pattern = True
        for node in ast.walk(ast.parse(src)):
            target = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                    and node.func.attr in mutating_attrs:
                base = node.func.value
                if isinstance(base, ast.Attribute) and base.attr == "environ":
                    target = node
            elif isinstance(node, (ast.Assign, ast.AugAssign)):
                subs = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in subs:
                    if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute) \
                            and t.value.attr == "environ":
                        target = node
            if target is None:
                continue
            seg = ast.get_source_segment(src, target) or ""
            if any(v in seg for v in banned_vars):
                bad.append(f"{p.name}:{target.lineno}  {' '.join(seg.split())[:90]}")
    assert saw_correct_pattern, (
        "扫不到任何「`{**os.environ, \"PYTHONIOENCODING\": …}`」的正确写法 —— "
        "判据疑似失去对象（`tests/` 里应当有多处这样的子进程环境）")
    assert not bad, (
        "这些地方在**会话级**改父进程的 stdio 编码变量 —— 它会跨测试泄漏，"
        "让后跑的文件起子进程时编码对不上（改成拼一份 env 传下去，"
        "或在起子进程那一处传 `encoding=`）：\n" + "\n".join(bad)
    )


# ============================================================ 负控：三态都必须可达


def _mutate(tmp_path: Path, transform) -> Path:
    lines = DOC.read_text(encoding="utf-8").splitlines()
    out = tmp_path / "ROLE-SPECS.md"
    out.write_text("\n".join(transform(lines)), encoding="utf-8")
    return out


def test_negative_control_missing_subsection_is_incomplete(tmp_path):
    """负控（最关键的一条）：删掉某角色的「明确不负责」子节 ⇒ 必须报 `incomplete`。

    没有这一条，这道门就可能是"永远通过"的橡皮图章 —— 而永远通过的文档门
    比没有文档门更糟（它把"没人检查"伪装成"检查过了"）。
    """
    def drop(lines: list[str]) -> list[str]:
        return [ln for ln in lines if not ln.startswith("### D.3 明确不负责")]

    result = G.check(_mutate(tmp_path, drop))
    assert result["verdict"] == "incomplete"
    assert any("D" in p and "不负责" in p for p in result["reason"].split("；")), result["reason"]


def test_negative_control_dropped_role_is_incomplete(tmp_path):
    """负控：整个角色节被删掉 ⇒ `incomplete`（且原因里点名集合不符）。"""
    def drop(lines: list[str]) -> list[str]:
        out, skipping = [], False
        for ln in lines:
            if ln.startswith("## G "):
                skipping = True
            elif ln.startswith("## ") and skipping:
                skipping = False
            if not skipping:
                out.append(ln)
        return out

    result = G.check(_mutate(tmp_path, drop))
    assert result["verdict"] == "incomplete"
    assert "期望" in result["reason"]


def test_negative_control_doc_without_role_headings_is_unknown_not_ok(tmp_path):
    """负控（三态的核心）：一个角色节都匹配不到 ⇒ `unknown`，不是 `ok`。

    这是"文档被改名 / 格式被改坏"的形态。把它报成 `ok` 就是把"没查成"
    读成"结构完整" —— 本项目最贵的那类静默兜底。
    """
    bad = tmp_path / "ROLE-SPECS.md"
    bad.write_text("# 一份别的东西\n\n没有任何角色节标题。\n", encoding="utf-8")
    result = G.check(bad)
    assert result["verdict"] == "unknown"


def test_negative_control_missing_document_is_unknown_not_ok(tmp_path):
    """负控：文档不存在 ⇒ `unknown`（路径写错时必须报"没查成"）。"""
    result = G.check(tmp_path / "does-not-exist.md")
    assert result["verdict"] == "unknown"


def test_gate_exit_codes_are_three_valued(tmp_path):
    """端到端：三个结论对应三个不同的退出码（`ok`=0 / `incomplete`=1 / `unknown`=2）。"""
    ok = subprocess.run([sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--json"],
                        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8",
                        errors="replace", timeout=120, env=_GATE_ENV)
    assert ok.returncode == 0
    assert json.loads(ok.stdout)["verdict"] == "ok"

    root = tmp_path / "empty"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "ROLE-SPECS.md").write_text("# 空\n", encoding="utf-8")
    unknown = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--root", str(root)],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert unknown.returncode == 2, unknown.stdout + unknown.stderr


# ============================================================ --roles / --doc（可选参数）


def test_default_role_set_is_unchanged_and_blind_to_n_o_q():
    """默认行为一字不变：不传 `--roles` 时判据是 A–H（+V,L）+ M。

    这条同时是缺口本身的记录：草稿里的 N/O/Q 节在默认判据下一个都匹配不到，
    于是门报 `unknown`（"没查成"）而不是"发现三个新角色缺规格"。
    新角色登记后若没有人显式传 `--roles`，这道门就看不见它们。

    2026-10-06（F-02）：`EXPECTED_ROLES` 多了 `V`（真角色，进 `schema.ROLES`）——
    它是登记进默认集合的新角色，与 N/O/Q 那种"草稿通道里的角色"不是一回事：
    本用例守的仍然是"默认判据看不见 N/O/Q"（下面那条 `default["sections"] == []`）。
    """
    # 2026-10-23：`L`（Lean 形式化者）立项后，默认角色集合是 A–H + V + L + M。
    # 这一行原先漏了 `L`，那份字面量记录的是 L 立项前的角色数 —— 补上不是放宽，
    # 而是让这条字面量与 `verify_role_specs.EXPECTED_ROLES`（= 现场名单 + 主控）同源。
    assert G.EXPECTED_ROLES == ("A", "B", "C", "D", "E", "F", "G", "H", "V", "L", "M")
    assert G.DEFAULT_ROLES is None
    default = G.check(DRAFT_NOQ)
    assert default["verdict"] == "unknown"
    assert default["sections"] == [], "默认判据不该看见 N/O/Q"
    assert G.check(DOC)["roles"] == list(G.EXPECTED_ROLES)


# ============================================================ `R6-6`：默认角色集合的来源


def _assert_default_roles_match_live(expected, live_roles, conductor_role) -> None:
    """默认角色集合必须与现场角色名单逐字相等（正控与负控共用同一段断言，负控才有意义）。"""
    want = tuple(live_roles) + (conductor_role,)
    assert tuple(expected) == want, (
        "`verify_role_specs.EXPECTED_ROLES` 与现场角色名单不一致："
        f"表里 {tuple(expected)}，现场 {want}。现场加了角色而这张表没跟上时，"
        "这道门会继续对一个已经不存在的角色集合报 ok（`R6-6`）。"
    )


def test_default_roles_are_cross_asserted_against_the_live_role_list():
    """正控（`R6-6`）：`EXPECTED_ROLES` 与现场 `tools.ROLES` + `CONDUCTOR_ROLE` 一致。

    改前这条缺口是：`EXPECTED_ROLES` 只与测试里另写的一份字面量比对
    （上面那条用例的 `== ("A", ..., "M")`），于是"现场多/少一个角色"与
    "这道门看不见它"可以同时成立，而没有东西会红。这里把两边直接对上 ——
    现场是 `tools.ROLES`（`ROLES` 的单一来源）加 `schema.CONDUCTOR_ROLE`。
    """
    from agentflow import schema as S
    from agentflow import tools as T

    _assert_default_roles_match_live(G.EXPECTED_ROLES, T.ROLES, S.CONDUCTOR_ROLE)


def test_negative_control_a_role_divergence_between_the_gate_and_the_live_list_is_caught():
    """负控（`R6-6`）：表与现场分家 ⇒ 上面那条交叉断言必须红。

    两个方向都注入：现场多一个角色（表没跟上）、现场少一个角色（表多写了）。
    没有这条，"两边一致"就无法与"这条断言恒真"区分开。
    """
    from agentflow import schema as S
    from agentflow import tools as T

    with pytest.raises(AssertionError):
        _assert_default_roles_match_live(
            tuple(G.EXPECTED_ROLES) + ("N",), T.ROLES, S.CONDUCTOR_ROLE
        )
    with pytest.raises(AssertionError):
        _assert_default_roles_match_live(
            tuple(G.EXPECTED_ROLES)[:-1], T.ROLES, S.CONDUCTOR_ROLE
        )


def test_cli_roles_flag_checks_the_n_o_q_draft():
    """正向：`--roles N,O,Q --doc <草稿>` ⇒ 三个角色节各 8 个必备子节齐全，退出码 0。"""
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N,O,Q", "--doc", "docs/ROLE-SPECS-DRAFT-N-O-Q.md", "--json"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["verdict"] == "ok", data["reason"]
    assert [s["role"] for s in data["sections"]] == ["N", "O", "Q"]


def test_cli_roles_flag_can_report_the_draft_as_incomplete(tmp_path):
    """负控（有牙）：在草稿的副本上删掉 `O.3 明确不负责` ⇒ 传了 `--roles` 门必须报 `incomplete`。

    没有这一条，"`--roles` 能检查那份草稿"就只是"门退 0"——而退 0 也可能因为
    它其实把整份文档跳过了（`unknown` 与 `ok` 混淆是同一族的假绿）。
    """
    body = DRAFT_NOQ.read_text(encoding="utf-8").replace("### O.3 明确不负责", "### O.3 别的")
    doc = tmp_path / "draft.md"
    doc.write_text(body, encoding="utf-8")
    result = G.check(doc, roles=("N", "O", "Q"))
    assert result["verdict"] == "incomplete", result["reason"]
    assert any("O" in p and "不负责" in p for p in result["reason"].split("；")), result["reason"]


def test_cli_roles_flag_rejects_a_malformed_role_set(tmp_path):
    """负控：`--roles` 写法非法时不许静默回落到默认集合，必须明确报错并退非零。

    否则 `--roles N;O;Q`（打错分隔符）会变成"用默认集合查了另一份东西"的假绿。
    """
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N;O;Q", "--doc", "docs/ROLE-SPECS-DRAFT-N-O-Q.md"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert p.returncode == 2, p.stdout + p.stderr
    assert "--roles 非法" in (p.stdout + p.stderr)

    missing_doc = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N,O,Q", "--doc", "docs/no-such-draft.md"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert missing_doc.returncode == 2, "文档不存在必须是 unknown(2)，不是通过"
    assert G.check(tmp_path / "gone.md", roles=("N",))["verdict"] == "unknown"


# ============================================ `R6-5`：`--no-live` 不许让门报绿


def test_no_live_makes_the_gate_unknown_not_green():
    """负控（`R6-5` 核心）：`--no-live` 跳过对账 ⇒ 退出码非 0、首行 `[unknown]`。

    改前这一跑是 `[ok] …（未与现场装配对账）` + 退出码 0 —— 一个 `--skip` 形态的
    开关就能把 `H-8` 修好的那步对账整个摘掉，而门照样绿。这条钉住"跳过了就没有结论"。
    """
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--no-live"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert p.returncode != 0, p.stdout + p.stderr
    assert p.returncode == 2, f"跳过对账是『没查成』（2），不是『有问题』（1）：{p.returncode}"
    first = (p.stdout or p.stderr).strip().splitlines()[0]
    assert first.startswith("[unknown]"), first
    assert "--no-live" in p.stdout, p.stdout


def test_the_live_probe_is_still_the_default():
    """正控（不许扩大化）：不带 `--no-live` 时门仍然真的对账并给 `ok`。

    没有这一条，"一律退 2"也能让上面那条通过 —— 而那道门就再也不会给结论了。
    """
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"), "--json"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads(p.stdout)
    assert data["verdict"] == "ok", data["reason"]
    assert data["live_counts"], "没有做现场装配对账，`ok` 就没有意义"


def test_an_incomplete_verdict_is_not_downgraded_by_no_live(tmp_path):
    """边界（`R6-5`）：`--no-live` 不许把已经查实的 `incomplete` 降级成 `unknown`。

    `incomplete`（查过了、结构有问题）比 `unknown`（没查成）强。把 1 改成 2
    等于拿"没查成"盖掉一条已经查实的发现 —— 那是把判据往弱的方向改。
    这里删掉草稿里的一节，让结构判据红，再看 `--no-live` 会不会把它盖掉。
    """
    body = DRAFT_NOQ.read_text(encoding="utf-8").replace("### O.3 明确不负责", "### O.3 别的")
    doc = tmp_path / "draft.md"
    doc.write_text(body, encoding="utf-8")
    p = subprocess.run(
        [sys.executable, str(REPO / "tools" / "verify_role_specs.py"),
         "--roles", "N,O,Q", "--doc", str(doc), "--no-live"],
        cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env=_GATE_ENV,
    )
    assert p.returncode == 1, p.stdout + p.stderr
    assert p.stdout.strip().splitlines()[0].startswith("[incomplete]"), p.stdout
    assert "对账" in p.stdout, p.stdout


# ============================================ `R6-6`：角色集合的门内对账


def test_the_gate_itself_cross_checks_expected_roles_against_the_live_list():
    """正控（`R6-6` 工具侧）：门拿到现场角色集合时与 `EXPECTED_ROLES` 对账并通过。

    改前这份对账只在 `tests/` 里（批 J 加的交叉断言）—— 跑门的时候看不见。
    """
    live_roles, reason = G.live_roles(root=REPO)
    assert live_roles is not None, reason
    assert tuple(G.EXPECTED_ROLES) == tuple(live_roles), (G.EXPECTED_ROLES, live_roles)
    result = G.check(DOC, live_role_list=live_roles)
    assert result["verdict"] == "ok", result["reason"]
    assert result["live_role_list"] == list(live_roles)


def test_an_extra_role_in_the_gates_own_table_makes_the_gate_red(monkeypatch):
    """负控（`R6-6` 工具侧）：门里那份表多塞一个角色 ⇒ 门必须红。

    这正是"现场加了角色、而门里的表没跟上"的反向形态（门里多写了一个）。
    改前它绿着：门里的表与现场名单之间没有任何判据。
    """
    live_roles, reason = G.live_roles(root=REPO)
    assert live_roles is not None, reason
    monkeypatch.setattr(G, "EXPECTED_ROLES", (*G.EXPECTED_ROLES, "N"), raising=True)
    monkeypatch.setattr(G, "DEFAULT_ROLES", None, raising=True)
    assert "N" in G.EXPECTED_ROLES, "注入没生效"
    result = G.check(DOC, live_role_list=live_roles)
    assert result["verdict"] == "incomplete", result["reason"]
    assert "EXPECTED_ROLES" in result["reason"], result["reason"]


def test_a_missing_role_in_the_live_list_makes_the_gate_red(monkeypatch):
    """负控 2（`R6-6` 工具侧）：现场少一个角色 ⇒ 门同样必须红（两个方向都注入）。"""
    live_roles, reason = G.live_roles(root=REPO)
    assert live_roles is not None, reason
    shorter = tuple(live_roles)[:-1]
    assert shorter != tuple(live_roles), "注入没生效"
    result = G.check(DOC, live_role_list=shorter)
    assert result["verdict"] == "incomplete", result["reason"]
    assert "EXPECTED_ROLES" in result["reason"], result["reason"]


def test_cli_role_set_mismatch_is_reported_end_to_end(monkeypatch, capsys):
    """端到端（`R6-6`）：`main()` 真的把现场角色集合接进判据，而不是只加了个形参。

    注入走"门里的表多一个角色"，然后跑 `main(["--json"])`：退出码必须是 1
    （查过了、不一致），而不是 0。
    """
    monkeypatch.setattr(G, "EXPECTED_ROLES", (*G.EXPECTED_ROLES, "N"), raising=True)
    monkeypatch.setattr(G, "DEFAULT_ROLES", None, raising=True)
    code = G.main(["--json"])
    out = capsys.readouterr().out
    assert code == 1, out
    data = json.loads(out)
    assert data["verdict"] == "incomplete", data["reason"]
    assert data["live_role_list"], data


# ============================================================ 与实时普查对账


def test_role_tool_counts_in_the_doc_match_the_live_census():
    """正向（文档 ↔ 实现一致）：文档每节标题里的工具条数 == `cli tools` 的实测普查。

    这条断言的价值全在"实测"两个字：硬编码一份 `{'A':20,…}` 只会把测试绑死在
    当前状态上（任何正当的工具增减都会让它红，而红了之后人会去改数字而不是看文档）。
    所以这里真的跑一次 `python -m agentflow.cli tools` 并解析它的输出 ——
    于是"文档里写的条数"与"实际能拿到几个工具"由同一次运行保证一致。
    """
    p = subprocess.run(
        [sys.executable, "-m", "agentflow.cli", "tools"],
        cwd=str(REPO / "src"), capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=300,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    assert p.returncode == 0, p.stdout + p.stderr
    line = next(ln for ln in p.stdout.splitlines() if "各角色工具数" in ln)
    census = json.loads(re.search(r"\{.*\}", line).group(0).replace("'", '"'))

    result = G.check(DOC)
    # 文档标题里每一节可能读到多个数字（例如 §C 提到"两层"与"17"），
    # 所以判据是"普查的那个数在该节读到的数字集合里"，而不是"恰好只有一个数字"。
    bad: dict[str, str] = {}
    for s in result["sections"]:
        role = s["role"]
        if role not in census:  # M 不进普查
            continue
        if census[role] not in s["tool_counts_in_titles"]:
            bad[role] = f"普查 {census[role]}，文档标题里读到 {s['tool_counts_in_titles']}"
    assert not bad, f"文档与实测普查不一致：{bad}"


def test_unknown_role_in_census_would_be_caught(tmp_path):
    """负控：把文档里 A 的条数改错 ⇒ 上面那条对账会红（证明它有牙）。

    注意：改错的那两个数从文档当次读出来（`G.check(DOC)["counts_by_role"]["A"]`），
    不写死：工具面一变（这一批 +2），写死的夹具会先红，而它红的原因是"夹具过期"
    而不是"判据会不会咬人"（`draft/37` §131 那一批实测撞过一次）。
    """
    was = G.check(DOC)["counts_by_role"]["A"][-1]
    now = was + 1

    def bump(lines: list[str]) -> list[str]:
        return [ln.replace(f"工具面（{was} 个，实测）", f"工具面（{now} 个，实测）")
                if ln.startswith("### A.4") else ln for ln in lines]

    doc = _mutate(tmp_path, bump)
    result = G.check(doc)
    assert was not in result["counts_by_role"]["A"] and now in result["counts_by_role"]["A"]


# ============================================================ 逐个工具的契约


def _registered_tool_names() -> list[str]:
    """从真实装配里取全部工具名（与 `cli tools` 用的是同一条路径）。

    为什么不解析 `cli tools` 的 stdout：那个命令默认只打印各角色的条数，
    要拿 55 个名字得逐个角色跑一次并解析。直接调 `build_registry` 更直接，
    而且它与 `cli.cmd_tools:335` 是同一个调用（含 `roles=tuple(ROLES)`）。
    """
    import tempfile
    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with tempfile.TemporaryDirectory(prefix="role_specs_reg_") as td:
        st = _store.Store(Path(td))
        st.init()
        #  这里与下面两处此前各有一句 `os.environ.setdefault("PYTHONIOENCODING", "utf-8")`
        # （2026-10-15 删）。它做了两件事，两件都不该做：
        #   ① 对本进程已经打开的 stdout 编码没有任何作用（那时它已经定了）；
        #   ② 污染父进程的 `os.environ`，于是同一趟 pytest 里后跑的测试起子进程时
        #      会继承它 —— 子进程吐 UTF-8、父进程仍按 GBK 解。
        # 真机后果（全量跑里唯一那条"只在全量跑里红"的用例）：`tests/test_temp_root_pin.py`
        # 的端到端负控 `_readerthread` 抛 `UnicodeDecodeError: 'gbk' codec can't decode
        # byte 0xa2 in position 584` ⇒ `proc.stdout` 变成 `None` ⇒ 断言里 `+` 抛 TypeError。
        # 编码的唯一正确钉法是"在起子进程那一处钉"（`subprocess.run(..., env=)` 或
        # `encoding=`）；会话级改环境变量是把"谁先跑"变成别人红绿的条件。
        build = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES))
        return sorted(build.registry.names())


def test_every_registered_tool_has_a_contract_row_in_role_specs():
    """正向（逐个工具的契约）：装配出来的每一个工具都必须在 `ROLE-SPECS.md` 里出现。

    用户点名要"逐个工具的契约"。一份"工具总表"最容易的坏法是漏行 ——
    新增一个工具而忘了写进去，没有任何东西会变红，而读文档的人会以为
    "这个工具大概不需要契约"。这条断言把"漏行"变成红点。

    它判的是"名字出现过"，不判那一行写得好不好（后者只能人看）。
    假阴性在哪：把工具名写进一句无关的话里也能通过；代价是它永远不会误报 ——
    对一条"防漏行"的门来说，这个方向是对的（宁可漏报，不要假报警）。
    """
    doc = DOC.read_text(encoding="utf-8")
    names = _registered_tool_names()
    assert names, "装配出 0 个工具 —— 这不是'契约齐全'，而是没查成"
    missing = [n for n in names if f"`{n}`" not in doc]
    assert not missing, f"这些工具在 docs/ROLE-SPECS.md 里找不到契约行：{missing}"


def test_tool_count_in_the_gate_matches_the_live_census():
    """正向（文档 ↔ 实现一致）：`ROLE-SPECS.md` §R0 标题里的工具总数 == 实时装配数。

    这条与上面那条互补：上面查"每个工具都有行"，这条查"总数没写错"。
    两条一起才能挡住"删了一个工具的契约行、但总数没改"与"加了工具、总数没改"两种漏法。
    """
    doc = DOC.read_text(encoding="utf-8")
    m = re.search(r"##\s*R0\.\s*全局工具总表（(\d+)\s*个", doc)
    assert m, "§R0 的标题里读不出工具总数 —— 判据本身失效了（没查成，不是通过）"
    stated = int(m.group(1))
    names = _registered_tool_names()
    assert stated == len(names), f"§R0 说 {stated} 个，实时装配是 {len(names)} 个"


# ============================================================ §R0 三列 ↔ 实时注册表


def _r0_rows() -> list[dict[str, str]]:
    """解析 §R0 的 55 行表，取出机械可比的三列：`side_effect` / 审批 / roles。

    只解析这三列是刻意的：它们是机器可判定的（注册表里有同名事实）。
    其余列（summary / 参数 / 返回结构 / 已知问题）是人写给人看的，
    机械比对只会制造假报警 —— 而假报警会训练人忽略整张表（`DEVELOPMENT.md` §6 的 P15）。

    解析必须只取紧挨着表头的那张连续表：`§R0.2` 小节里还有别的表，
    其中一行的第 2 列是 `` `agent_c.py:2538-2737` ``（那是"代码位置"而不是工具名）——
    把子小节的表一起扫进来会得到一条名叫 `agent_c.py:2538-2737` 的假工具，
    然后在下游 `registry.get()` 上炸。第一版就是这么错的，所以这里按"表头 + 连续 `|` 行"取。
    """
    lines = DOC.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("| # | 工具 |"))
    rows: list[dict[str, str]] = []
    for line in lines[start + 1:]:
        if not line.startswith("|"):
            break                      # 表结束 —— 后面的小节是别的表
        if set(line) <= set("|-: "):
            continue                   # 分隔行
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        m = re.fullmatch(r"`([^`]+)`", cells[1])
        if not m:
            continue
        rows.append({
            "tool": m.group(1),
            "side_effect": cells[3].strip("`").strip(),
            "needs_approval": cells[4],
            "roles": cells[5],
        })
    return rows


def test_r0_table_lists_every_tool_exactly_once():
    """正向：§R0 的行与实时注册表一一对应（不重不漏）。"""
    rows = _r0_rows()
    listed = [r["tool"] for r in rows]
    assert len(listed) == len(set(listed)), f"§R0 有重复行：{sorted(x for x in listed if listed.count(x) > 1)}"
    assert sorted(listed) == _registered_tool_names()


def test_r0_side_effect_column_matches_the_registry():
    """正向（文档 ↔ 实现一致）：§R0 的 `side_effect` 列必须等于注册表里的声明。

    为什么值得一条门：`side_effect` 是审批的唯一可信判据（`DEVELOPMENT.md` §6 的 P7）。
    文档里写 `read` 而代码里是 `network`，读者就会以为"这个工具不需要审批" ——
    而没有任何东西会因此变红。本轮的 `returns=` 真空通过（PROPOSALS G-4）
    是同一族缺陷，所以这里把"文档里那一列"也钉住。
    """
    import tempfile as _tf

    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with _tf.TemporaryDirectory(prefix="r0_table_") as td:
        st = _store.Store(Path(td))
        st.init()
        # （此处此前有 `os.environ.setdefault("PYTHONIOENCODING", "utf-8")`；2026-10-15 删，
        # 理由见 `_registered_tool_names` 里那一段 —— 会话级改环境变量会跨测试泄漏。）
        reg = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES)).registry
        bad: dict[str, str] = {}
        for r in _r0_rows():
            live = reg.get(r["tool"]).side_effect
            if r["side_effect"] != live:
                bad[r["tool"]] = f"文档={r['side_effect']!r} 实际={live!r}"
        assert not bad, f"§R0 的 side_effect 列与注册表不一致：{bad}"


def test_r0_approval_and_roles_columns_match_the_registry():
    """正向：§R0 的"审批"列与"roles"列也必须与注册表一致。

    - 审批列是 `是` / `否` 的自由写法，只判"是否提到需要审批"这一个布尔；
    - roles 列是 `A B C` 这种以空格分隔的角色字母。
    """
    import tempfile as _tf

    sys.path.insert(0, str(REPO / "src"))
    from agentflow import store as _store  # noqa: PLC0415
    from agentflow.tools import ROLES, build_registry  # noqa: PLC0415

    with _tf.TemporaryDirectory(prefix="r0_roles_") as td:
        st = _store.Store(Path(td))
        st.init()
        # （同上：会话级改 `os.environ` 的那一句 2026-10-15 删。）
        reg = build_registry(store=st, workspace_root=Path(td), roles=tuple(ROLES)).registry
        bad: dict[str, str] = {}
        for r in rows_to_check(reg, _r0_rows()):
            bad.update(r)
        assert not bad, f"§R0 的审批/roles 列与注册表不一致：{bad}"


def rows_to_check(reg, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """逐行比对审批列与 roles 列，返回 `{工具: 问题描述}` 的列表（空 = 全对）。"""
    out: list[dict[str, str]] = []
    for r in rows:
        spec = reg.get(r["tool"])
        problems: list[str] = []
        doc_says_approval = "是" in r["needs_approval"]
        if doc_says_approval != bool(spec.needs_approval):
            problems.append(f"审批 文档={r['needs_approval']!r} 实际={spec.needs_approval}")
        # 角色字母表要含主控 `M`：工具层的角色词汇是 `TOOL_ROLES` = 可被召唤的 A–H(+V,L) + 主控 M
        # （主控不可被召唤，但它拿编排面工具）。只认 A–H 会让主控那 8 行的 roles 列
        # 永远解析成空，于是"文档与注册表不一致"这条判据对它们永远报红（实测撞过）。
        # 2026-10-06（F-02）：`V` 也要在里面 —— 只读角色 V 拿到 11 件 `fs.*`/`table.*`/
        # `manuscripts.*` 的读工具，那些工具的 roles 列现在含 V；解析器漏掉 V 时
        # 这一条会报"文档少了 V"（假红）或者更糟：文档真漏了 V 也不报（假绿）。
        # 2026-10-23：`L` 同理 —— L 的三件工具（`formal.*`）的 roles 列只有 L；
        # 这个字母类原先只写到 `[A-HMV]`，那份写法记录的是 L 立项前的角色数。
        # 补上 L 不是放宽：漏掉它时 L 那一格会被解析成空集，于是"文档写了 L"与
        # "文档漏了 L"在这一条判据下长得一模一样。
        #
        # 但补上 L 之后有一格要先认标记再扫字母：`（无角色）` 是这一列里"谁都调不到"
        # 的显式写法（今天只有 `verify.check_formal` 一行）。那一格的解释串里写着
        # "形式化入口归 L 的 `formal.*`" —— 裸扫字母会把散文里的 L 读成"这一行只给
        # L 用"，而文档与注册表实际上是一致的（都没有角色）。红的原因是解析器把散文
        # 当成了名单，所以这里认标记、不认散文字母。
        if "无角色" in r["roles"]:
            doc_roles: list[str] = []
        else:
            doc_roles = [x for x in re.findall(r"\b([A-HMVL])\b", r["roles"])]
        if sorted(doc_roles) != sorted(spec.roles):
            problems.append(f"roles 文档={sorted(doc_roles)} 实际={sorted(spec.roles)}")
        if problems:
            out.append({r["tool"]: "；".join(problems)})
    return out
