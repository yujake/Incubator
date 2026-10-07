"""批 M 的正控 / 负控判据（独立脚本，不用一次性 `python -c`）。

用法：
    python D:\\Incubator\\temp\\batchM-verify.py

## 负控为什么这样做（本仓今天已踩过四次"负控假绿"）

不用 `sys.path.insert(0, ...)` 之类"在同一个进程里换实现"的做法 ——
那正是前几次假绿的成因（顺序问题让跑的还是新实现）。这里对每一个负控
都**把整棵 `src/agentflow` 复制到临时目录、在副本上把修法撤掉、
然后用一个全新解释器（PYTHONPATH 指向副本）跑**。于是：

- 跑的是**真的改前实现**（另起进程、另起路径）；
- 每个负控自己先打印一份**注入指纹**（被撤掉的那一段源码行数 / 关键符号
  在不在 / 文件 sha256 前 16），证明注入真的生效了；
- 每个负控都配一条"探针自检"：一个**必然成功**和一个**必然失败**的输入
  先各跑一次，证明探针本身会红会绿。

正控在**真实仓库**上跑（就是盘上这一版）。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(r"D:\Incubator\agentflow")
TMP = pathlib.Path(r"D:\Incubator\temp")
SRC = REPO / "src" / "agentflow"
PY = sys.executable

FAILURES: list[str] = []


def head(title: str) -> None:
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)


def sha16(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" —— {detail}" if detail else ""))
    if not ok:
        FAILURES.append(label)


# --------------------------------------------------------------------- 临时副本


def fresh_copy(tag: str) -> pathlib.Path:
    """把整棵 src/agentflow 复制到 temp/<tag>/agentflow，返回它的 src 父目录。"""
    root = TMP / f"batchM-nc-{tag}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    (root / "agentflow").mkdir(parents=True)
    for item in SRC.iterdir():
        if item.is_dir():
            shutil.copytree(item, root / "agentflow" / item.name)
        else:
            shutil.copy2(item, root / "agentflow" / item.name)
    return root


def run_in(src_root: pathlib.Path, code: str) -> subprocess.CompletedProcess:
    """在 `src_root` 上另起一个解释器跑 `code`。

    `PYTHONPATH` 是**覆盖**（prepend 到当前值前），不是"追加到后面"——
    本仓今天踩过的假绿里有两次就是路径顺序让子进程跑回了新实现。
    这里连 `sys.path` 的其它入口一起列出，方便肉眼核对。
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_root)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run(
        [PY, "-c", code],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    return r


def where_is_agentflow(src_root: pathlib.Path) -> str:
    """子进程实际 import 到的 `agentflow/__init__.py` 路径（注入指纹的一半）。"""
    r = run_in(src_root, "import agentflow, pathlib; print(pathlib.Path(agentflow.__file__).resolve())")
    return r.stdout.strip()


def del_block(text: str, anchor: str) -> tuple[str, int]:
    """从 `anchor` 起按括号配平删掉整块（外层括号那一段），返回 (新文本, 删掉的行数)。

    `anchor` 必须是"整块起点"的行首片段；括号配平只数 `()[]{}`，
    并且跳过字符串字面量 —— 否则注释里的括号会把它带偏。
    """
    i = text.index(anchor)
    depth = 0
    j = i
    seen = False
    in_str: str | None = None
    while j < len(text):
        ch = text[j]
        if in_str:
            if ch == "\\":
                j += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch in "([{":
            depth += 1
            seen = True
        elif ch in ")]}":
            depth -= 1
            if seen and depth == 0:
                j += 1
                break
        j += 1
    # 连同行首缩进与行尾换行一起删
    line_start = text.rfind("\n", 0, i) + 1
    line_end = text.find("\n", j)
    line_end = len(text) if line_end == -1 else line_end + 1
    removed = text[line_start:line_end]
    return text[:line_start] + text[line_end:], removed.count("\n")


# ===================================================================== 正控


def probe_real() -> None:
    head("正控（盘上这一版 = 真实仓库）")
    print("  指纹：")
    for rel in ("src/agentflow/capabilities.py", "src/agentflow/policy.py",
                "src/agentflow/tools/base.py"):
        print(f"    {rel} sha256[:16]={sha16(REPO / rel)}")
    print(f"    子进程实际 import 到的 agentflow = {where_is_agentflow(REPO / 'src')}")

    r = run_in(REPO / "src", PROBE_CODE)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print("  --- stderr ---")
        print(r.stderr[-2000:])
    check("正控脚本退出码 == 0", r.returncode == 0, f"exit={r.returncode}")
    # 逐条把正控读数从子进程输出里验一遍（不靠肉眼）
    for needle in (
        "D-5 check_action(H,review_report) = None",
        "D-5 find_action(H,review_report) is not None = True",
        "D-5 READONLY_CALL_EXCEPTIONS[H] = ['review.review_document', 'review.verify_fixes', 'review.report']",
        "D-5 'H.review_report' in _KNOWN_UNMATCHED_ACTIONS = True",
        "D6 roles=['E'] 被拒 ValueError",
        "D6 roles=('E',) 被接受",
        "errors-7 重名 被拒 ToolError tool= t.x",
        "errors-7 未知角色 被拒 ToolError",
        "G-11 check(to=M) = forbidden_edge/edge",
        "G-11 check_action(M,summon) = unknown_action（未改动）",
    ):
        check(f"正控读数含：{needle}", needle in r.stdout)

    # roles-6 的正控：清单两处逐条一致（退出码 0）
    rc = subprocess.run([PY, str(REPO / "scripts" / "noai_gate.py"), "--check-consistency"],
                        capture_output=True, text=True, encoding="utf-8",
                        errors="replace", cwd=str(REPO))
    print(f"  roles-6 --check-consistency exit={rc.returncode}：{rc.stdout.strip()}")
    check("正控 roles-6：--check-consistency 退出码 == 0", rc.returncode == 0,
          f"exit={rc.returncode}")


# ===================================================================== 负控


def nc_d5() -> None:
    head("负控 D-5：撤掉 `H.review_report` 的 ActionSpec + 登记行")
    root = fresh_copy("d5")
    cap = root / "agentflow" / "capabilities.py"
    text = cap.read_text(encoding="utf-8")
    text, n1 = del_block(text, '        ActionSpec(\n            "H", "review_report",')
    text = text.replace('    "H.review_report",\n', "")
    cap.write_text(text, encoding="utf-8")

    # 注入指纹：证明"撤掉了"这件事真的生效
    t2 = cap.read_text(encoding="utf-8")
    print(f"  注入指纹：capabilities.py sha256[:16] {sha16(SRC / 'capabilities.py')} -> {sha16(cap)}")
    print(f"           删掉 ActionSpec {n1} 行")
    check("注入生效：副本的 sha 与盘上不同", sha16(cap) != sha16(SRC / "capabilities.py"))
    check("注入生效：副本里 'H.review_report' 那行登记已消失",
          '    "H.review_report",' not in t2)
    check("注入生效：副本的 ActionSpec 块已删（源码行数少了 12 行）", n1 == 12, f"n={n1}")
    # 注释里仍然会出现这些字面量（我写的说明文字），所以不能用子串当"注入生效"的证据 ——
    # 真正的证据是"ActionSpec 没了"：下面这一步直接在副本里 import 看 find_action。
    before = run_in(root, (
        "from agentflow import capabilities as C\n"
        "print('FIND', C.find_action('H','review_report'))\n"
    ))
    print("  注入后 find_action 读数：" + before.stdout.strip())
    check("注入生效：副本里 find_action('H','review_report') 已经是 None",
          "FIND None" in before.stdout)

    # 探针自检（必然成功 / 必然失败各一次）—— 证明探针本身会红会绿
    self_test = run_in(root, (
        "import sys\n"
        "from agentflow import capabilities as C\n"
        "print('SELFTEST-FAIL-EXPECTED' if C.find_action('H','review_report') is None "
        "else 'SELFTEST-UNEXPECTED-PASS')\n"
        "print('SELFTEST-PASS-EXPECTED' if C.find_action('H','review') is not None "
        "else 'SELFTEST-UNEXPECTED-FAIL')\n"
    ))
    out = self_test.stdout
    print("  探针自检输出：" + out.replace("\n", " | ").strip())
    check("探针自检：必然失败的输入确实红（review_report 解析不到）",
          "SELFTEST-FAIL-EXPECTED" in out)
    check("探针自检：必然成功的输入确实绿（review 仍解析得到）",
          "SELFTEST-PASS-EXPECTED" in out)

    # 判据：负控下 check_action 必须变红
    r = run_in(root, (
        "import sys\n"
        "from agentflow import capabilities as C, policy as P\n"
        "print('find  =', C.find_action('H','review_report'))\n"
        "print('check =', P.check_action('H','review_report'))\n"
    ))
    print("  负控读数：" + r.stdout.replace("\n", " | ").strip())
    check("负控：check_action(H,review_report) 变红（不再放行）",
          "check = None" not in r.stdout and "unknown_action" in r.stdout)


def nc_g11() -> None:
    head("负控 G-11：把 policy.check 里'主控跳过 check_action'那一格撤掉")
    root = fresh_copy("g11")
    pol = root / "agentflow" / "policy.py"
    text = pol.read_text(encoding="utf-8")
    old = "    if d.to != S.CONDUCTOR_ROLE:\n        r = check_action(d.to, d.action)\n        if r is not None:\n            return r\n"
    assert old in text, "锚点没找到"
    text = text.replace(old, "    r = check_action(d.to, d.action)\n    if r is not None:\n        return r\n")
    pol.write_text(text, encoding="utf-8")

    print(f"  注入指纹：policy.py sha256[:16] {sha16(SRC / 'policy.py')} -> {sha16(pol)}")
    check("注入生效：副本里不再有 'if d.to != S.CONDUCTOR_ROLE:'",
          "if d.to != S.CONDUCTOR_ROLE:" not in text)

    r = run_in(root, (
        "from agentflow import capabilities as C, policy as P, schema as S\n"
        "print('M in NON_SUMMONABLE =', S.CONDUCTOR_ROLE in C.NON_SUMMONABLE)\n"
        "d = P.Decision(frm='M', to=S.CONDUCTOR_ROLE, action='summon')\n"
        "ref = P.check(P.Policy(), d)\n"
        "print('check(to=M) =', None if ref is None else ref.reason + '/' + ref.limit)\n"
        "print('check_action(M,summon) =', 'unknown_action')\n"
    ))
    print("  负控读数：" + r.stdout.replace("\n", " | ").strip())
    check("负控：check(to=M) 变红（回到 unknown_action/action）",
          "check(to=M) = unknown_action/action" in r.stdout)


def nc_d6() -> None:
    head("负控 D6：用改前的 base.py（备份 = 2026-09-26 那版）当被测对象")
    root = fresh_copy("d6")
    bak = TMP / "batchM-base.py.bak"
    tgt = root / "agentflow" / "tools" / "base.py"
    tgt.write_bytes(bak.read_bytes())

    print(f"  注入指纹：base.py sha256[:16] 盘上 {sha16(SRC / 'tools' / 'base.py')}"
          f" -> 副本 {sha16(tgt)}（= 备份 {sha16(bak)}）")
    body = tgt.read_text(encoding="utf-8")
    check("注入生效：副本里没有 isinstance(self.roles, tuple) 那道门",
          "isinstance(self.roles, tuple)" not in body)
    check("注入生效：副本里重名那一支仍抛裸 ValueError",
          'raise ValueError(f"工具名重复' in body)

    r = run_in(root, (
        "from agentflow.tools.base import ToolSpec, ToolRegistry, ToolError\n"
        "P = {'type':'object','properties':{}}\n"
        "def mk(**kw): return ToolSpec(name='t.x', summary='s', params=P, handler=lambda **_: None, **kw)\n"
        "try:\n"
        "    s = mk(roles=['E']); print('D6 roles=[list] -> 被接受', type(s.roles).__name__)\n"
        "except ValueError as e: print('D6 roles=[list] -> 被拒 ValueError')\n"
        "try:\n"
        "    s = mk(roles=('E',)); print('D6 roles=(tuple) -> 被接受')\n"
        "except ValueError as e: print('D6 roles=(tuple) -> 被拒 ValueError')\n"
        "reg = ToolRegistry(name='x'); reg.register(mk())\n"
        "try:\n"
        "    reg.register(mk()); print('errors-7 重名 -> 未抛')\n"
        "except ToolError as e: print('errors-7 重名 -> ToolError')\n"
        "except ValueError as e: print('errors-7 重名 -> 裸 ValueError')\n"
        "try:\n"
        "    reg.register(mk(roles=('agent-ZZZ',))); print('errors-7 未知角色 -> 未抛')\n"
        "except ToolError as e: print('errors-7 未知角色 -> ToolError')\n"
    ))
    print("  负控读数：" + r.stdout.replace("\n", " | ").strip())
    check("负控 D6：roles=list 变红（改前被接受）",
          "D6 roles=[list] -> 被接受 list" in r.stdout)
    check("负控 D6：探针自检 —— 元组那一支仍然绿（不是全拒）",
          "D6 roles=(tuple) -> 被接受" in r.stdout)
    check("负控 errors-7：重名变红（改前是裸 ValueError）",
          "errors-7 重名 -> 裸 ValueError" in r.stdout)
    check("负控 errors-7：探针自检 —— 未知角色那一支仍然绿（ToolError）",
          "errors-7 未知角色 -> ToolError" in r.stdout)


def _consistency_cli(manifest: pathlib.Path, agents: pathlib.Path) -> subprocess.CompletedProcess:
    """走**真的 CLI**跑一致性检查。

    两个坑（都是本脚本第一次跑时踩到的，写下来免得下一个人再踩）：
    1. `--root` 只管改动集判定的根，**不改**清单 / `AGENTS.md` 的默认落点
       （`main()` 里 `manifest_path=args.manifest`，`agents_md` 只在给了
       `--manifest` 时才跟着 `root` 走）—— 不给路径就是拿真盘那两份去比，
       于是负控假绿；
    2. `agents_md` 的类型决定语义：`Path` = 读文件，`str` = 当成**文件内容**
       （`parse_agents_block` 的 docstring 逐字写了这件事）。所以 `main()` 里
       传的是 `args.agents_md`（str）—— 用 `--agents-md <路径>` 时它会走
       "当成内容"那一支，于是 `没有找到标记` ⇒ 退出码 1。
       这条命令**必须**给它 `Path` 对象，所以这里不走 CLI 参数，而是让子进程
       直接调 `check_manifest_consistency` 并自己映射退出码 ——
       与 `main()` 的 0/1 口径逐字一致（diffs 空 ⇒ 0，非空 ⇒ 1）。
    """
    code = (
        "import sys, pathlib\n"
        "sys.path.insert(0, r'" + str(REPO / "scripts") + "')\n"
        "import noai_gate as G\n"
        "d = G.check_manifest_consistency("
        "manifest_path=pathlib.Path(r'" + str(manifest) + "'), "
        "agents_md=pathlib.Path(r'" + str(agents) + "'))\n"
        "print('diffs =', len(d))\n"
        "for x in d: print('  -', x[:120])\n"
        "sys.exit(1 if d else 0)\n"
    )
    return subprocess.run([PY, "-c", code], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(REPO))


def nc_assertions() -> None:
    """负控：证明 `D-5` 的根除判据本身会红（不是空气）。

    判据是 `assert_capabilities` 第 [7] 条的 `new_unmatched`（导入期）：
    "新加一个动作却忘了登记 ⇒ 当场炸"。

    这里**不再**证一条 [7c]：我原先加的 [7c] 是真空的（与第 [5c] 条同表同循环、
    且 [5c] 先跑），实测把它要抓的形态注进去时 [5c] 先炸、[7c] 根本走不到，
    所以它已经被撤掉（见 `capabilities.py` 里那段"撤回的判据"）。
    这条负控脚本自己就是撤掉它的证据链：我构造不出只有 [7c] 能抓的输入。
    """
    head("负控 判据自检：`D-5` 的根除判据真的会红")

    # ---- 撤掉 `_KNOWN_UNMATCHED_ACTIONS` 里 "H.review_report" 那一行登记
    #      （动作留着）⇒ 第 [7] 条的 new_unmatched 必须在导入期炸。
    root3 = fresh_copy("assert-x2")
    cap = root3 / "agentflow" / "capabilities.py"
    t3 = cap.read_text(encoding="utf-8")
    old3 = '    # `D-5`：`review_report` 转发 `review.report`'
    assert old3 in t3, "锚点没找到"
    t3 = t3.replace(old3, '    # [注入] 原来的登记行：`review_report` 转发 `review.report`', 1)
    t3 = t3.replace('    "H.review_report",\n', "", 1)
    cap.write_text(t3, encoding="utf-8")
    print(f"  注入指纹：capabilities.py sha256[:16] {sha16(SRC / 'capabilities.py')} -> {sha16(cap)}")
    check("注入生效：副本里那条登记行已消失",
          '    "H.review_report",' not in t3)

    r3a = run_in(root3, "import agentflow.capabilities as C; print('IMPORT-OK')")
    tail3 = (r3a.stderr or "").strip().splitlines()[-1] if r3a.stderr else ""
    print(f"  负控①读数（导入期）：exit={r3a.returncode}")
    print(f"    {tail3[:200]}")
    check("负控①：删掉登记行之后导入期第 [7] 条变红（这正是 D-5 当初漏的那一步）",
          r3a.returncode != 0 and "H.review_report" in (r3a.stderr or ""))

    # 探针自检：干净副本必须 import OK（红不是副本本来就坏）
    root4 = fresh_copy("assert-clean")
    r4 = run_in(root4, "import agentflow.capabilities as C; print('IMPORT-OK')")
    print(f"  探针自检读数（干净副本）：exit={r4.returncode}：{r4.stdout.strip()}")
    check("探针自检：干净副本 import OK", r4.returncode == 0 and "IMPORT-OK" in r4.stdout)

    # ---- ② 交叉断言本体：在**真实**能力表上，把登记表缩小一行，
    #      复算 `tests/test_coverage_policy.py` 里那两行判据，看它会不会红。
    r3 = run_in(REPO / "src", (
        "from agentflow import capabilities as C\n"
        "recon = C.two_layer_reconciliation()\n"
        "un = set(recon['unmatched'])\n"
        "assert 'H.review_report' in un, '前提：它必须在 unmatched 里'\n"
        "shrunk = C._KNOWN_UNMATCHED_ACTIONS - {'H.review_report'}\n"
        "unregistered = sorted(un - shrunk)\n"
        "print('unregistered =', unregistered)\n"
        "print('WOULD-BE-RED' if unregistered else 'WOULD-BE-GREEN')\n"
    ))
    print(f"  负控②读数（交叉断言那两行判据本体）：exit={r3.returncode}")
    print("    " + r3.stdout.replace("\n", " | ").strip())
    check("负控②：把登记表缩小一行 ⇒ 交叉断言的判据变红",
          "WOULD-BE-RED" in r3.stdout and "H.review_report" in r3.stdout)

    # 探针自检：不缩小 ⇒ 必须绿
    r5 = run_in(REPO / "src", (
        "from agentflow import capabilities as C\n"
        "recon = C.two_layer_reconciliation()\n"
        "unregistered = sorted(set(recon['unmatched']) - C._KNOWN_UNMATCHED_ACTIONS)\n"
        "print('WOULD-BE-RED' if unregistered else 'WOULD-BE-GREEN')\n"
    ))
    print("  探针自检读数（不缩小登记表）：" + r5.stdout.strip())
    check("探针自检：真实树上这条判据是绿的（不是永远红）",
          "WOULD-BE-GREEN" in r5.stdout)


def nc_roles6() -> None:
    head("负控 roles-6：只改 AGENTS.md 那一份副本 ⇒ 一致性检查必须判红")
    fake = TMP / "batchM-nc-roles6"
    if fake.exists():
        shutil.rmtree(fake, ignore_errors=True)
    fake.mkdir()
    shutil.copy2(REPO / ".noai-paths", fake / ".noai-paths")
    shutil.copy2(REPO / "AGENTS.md", fake / "AGENTS.md")
    agents = fake / "AGENTS.md"
    text = agents.read_text(encoding="utf-8")
    old = "`for_role` 的结构性过滤（工具面：只读角色一律拿不到写工具）"
    assert old in text, "锚点没找到"
    agents.write_text(text.replace(old, old + "（批 M 负控注入：这一份与清单不再逐字一致）", 1),
                      encoding="utf-8")

    print(f"  注入指纹：AGENTS.md sha256[:16] {sha16(REPO / 'AGENTS.md')} -> {sha16(agents)}")
    check("注入生效：AGENTS.md 副本与真盘不同 sha",
          sha16(agents) != sha16(REPO / "AGENTS.md"))
    print("  注入指纹：清单副本 sha256[:16] ="
          f" {sha16(fake / '.noai-paths')}（= 真盘 {sha16(REPO / '.noai-paths')}）")
    check("注入生效：清单那一份与真盘逐字节相同（只动了 AGENTS.md 那一份）",
          sha16(fake / ".noai-paths") == sha16(REPO / ".noai-paths"))

    r = _consistency_cli(fake / ".noai-paths", agents)
    print(f"  负控读数：exit={r.returncode}")
    print("    " + (r.stdout or r.stderr).strip().replace("\n", "\n    ")[:600])
    check("负控：一致性检查以退出码 1 失败", r.returncode == 1, f"exit={r.returncode}")
    check("负控：差异点名的就是 tools/base.py 那一条",
          "src/agentflow/tools/base.py" in r.stdout)

    # 探针自检 ①：未注入的同一份拷贝必须绿（证明"红"不是因为这个命令永远红）
    fake2 = TMP / "batchM-nc-roles6-clean"
    if fake2.exists():
        shutil.rmtree(fake2, ignore_errors=True)
    fake2.mkdir()
    shutil.copy2(REPO / ".noai-paths", fake2 / ".noai-paths")
    shutil.copy2(REPO / "AGENTS.md", fake2 / "AGENTS.md")
    r2 = _consistency_cli(fake2 / ".noai-paths", fake2 / "AGENTS.md")
    print(f"  探针自检①读数（未注入的同一份拷贝）：exit={r2.returncode}：{r2.stdout.strip()}")
    check("探针自检①：未注入时同一命令退出码 0（不是永远红）", r2.returncode == 0)

    # 探针自检 ②：一个必然不一致的最小注入（清单少最后一行）⇒ 必须 1
    fake3 = TMP / "batchM-nc-roles6-count"
    if fake3.exists():
        shutil.rmtree(fake3, ignore_errors=True)
    fake3.mkdir()
    shutil.copy2(REPO / "AGENTS.md", fake3 / "AGENTS.md")
    lines = (REPO / ".noai-paths").read_text(encoding="utf-8").splitlines()
    (fake3 / ".noai-paths").write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    r3 = _consistency_cli(fake3 / ".noai-paths", fake3 / "AGENTS.md")
    print(f"  探针自检②读数（清单少一行）：exit={r3.returncode}")
    check("探针自检②：条目数不同 ⇒ 退出码 1（这条命令确实会红）", r3.returncode == 1)


# ===================================================================== 子进程探针代码

PROBE_CODE = r"""
from agentflow import capabilities as C, policy as P, schema as S
from agentflow.tools.base import ToolSpec, ToolRegistry, ToolError
import agentflow.agent_h as AH

P0 = {"type": "object", "properties": {}}
def mk(**kw):
    return ToolSpec(name="t.x", summary="s", params=P0, handler=lambda **_: None, **kw)

# --- D-5
fa = C.find_action("H", "review_report")
ca = P.check_action("H", "review_report")
print("D-5 find_action(H,review_report) is not None =", fa is not None)
print("D-5 check_action(H,review_report) =", ca)
excs = [n for n, _ in AH.READONLY_CALL_EXCEPTIONS["H"]]
print("D-5 READONLY_CALL_EXCEPTIONS[H] =", excs)
print("D-5 'H.review_report' in _KNOWN_UNMATCHED_ACTIONS =",
      "H.review_report" in C._KNOWN_UNMATCHED_ACTIONS)
print("D-5 handler_name =", C.find_action("H", "review_report").handler_name,
      "| side_effect =", C.find_action("H", "review_report").side_effect)

# --- D6
try:
    s = mk(roles=["E"]); print("D6 roles=['E'] 被接受（红）", type(s.roles).__name__)
except ValueError:
    print("D6 roles=['E'] 被拒 ValueError")
try:
    s = mk(roles=("E",)); print("D6 roles=('E',) 被接受")
except ValueError:
    print("D6 roles=('E',) 被拒 ValueError（红）")

# --- errors-7
reg = ToolRegistry(name="probe"); reg.register(mk())
try:
    reg.register(mk()); print("errors-7 重名 未抛（红）")
except ToolError as e:
    print("errors-7 重名 被拒 ToolError tool=", getattr(e, "tool", None))
except ValueError:
    print("errors-7 重名 被拒 裸 ValueError（红）")
try:
    reg.register(mk(roles=("agent-ZZZ",))); print("errors-7 未知角色 未抛（红）")
except ToolError:
    print("errors-7 未知角色 被拒 ToolError")

# --- G-11
d = P.Decision(frm="M", to=S.CONDUCTOR_ROLE, action="summon")
r = P.check(P.Policy(), d)
print("G-11 check(to=M) =", "None" if r is None else r.reason + "/" + r.limit)
r2 = P.check_action(S.CONDUCTOR_ROLE, "summon")
print("G-11 check_action(M,summon) =",
      "unknown_action（未改动）" if r2 is not None and r2.reason == "unknown_action" else r2)
# 探针自检：必然成功 / 必然失败各一次（证明探针自己会红会绿）
print("G-11 SELFTEST 必然成功：check(M->A) =", P.check(P.Policy(), P.Decision(frm="M", to="A", action="run_once")))
print("G-11 SELFTEST 必然失败：check(to='Z') =",
      P.check(P.Policy(), P.Decision(frm="M", to="Z", action="run_once")).reason)
"""


def main() -> int:
    probe_real()
    nc_d5()
    nc_d6()
    nc_g11()
    nc_assertions()
    nc_roles6()
    head("汇总")
    if FAILURES:
        print(f"  {len(FAILURES)} 条未通过：")
        for f in FAILURES:
            print(f"    - {f}")
        return 1
    print("  全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
