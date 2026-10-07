"""批 L 的判据探针（正控 + 负控），可重复跑。

## 为什么不做"一次性 python -c"

共同规矩第 2 条：负控必须**证明注入生效**。本仓今天已踩过四次"负控假绿"
（`sys.path` 两次 `insert(0,…)` 的顺序、只断言"源码里有这个串"、把自检夹具
算成生产写入点、`f"HEAD:{Path}"` 在 Windows 上给出反斜杠）。所以本探针：

1. **正控**：在真工作区跑批 L 新写的那几条用例（`pytest <nodeid>`）；
2. **负控**：在 `temp/batchL-neg/<case>/` 里跑**同一份用例的副本**，但那份副本
   里的名字绑在 `git HEAD` 的改前实现上（见 `batchL-neg/batchl_neg.py`）；
   同一批断言**必须变红**；
3. **注入自证**：负控输出里必须出现 `[OLD-IMPL]` 行（`__file__` 指向快照 +
   sha256 前 16 位 + 关键属性的取值），探针据此断言"跑的是改前那份"；
4. **探针自校准**：先用一对"必然成功 / 必然失败"的输入证明 `pytest` 这个入口
   与"红/绿"这个读数本身可信。

第 2 点曾经踩到第五个坑并留档：只把 `sys.modules` 换掉是不够的 —— 用例文件里
`from agentflow.formalgw import …` 是**导入期**绑定的名字，换 `sys.modules`
不影响它，实测那样跑出来的负控是**绿的**（假绿）。所以副本必须改写 import。

用法：
    python D:\\Incubator\\temp\\batchL-probe.py            # 全部
    python D:\\Incubator\\temp\\batchL-probe.py E-3 C1     # 只跑这几条
退出码：0 = 全部符合预期；1 = 有不符合预期的读数（含负控假绿）。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(r"D:\Incubator\agentflow")
TEMP = Path(r"D:\Incubator\temp")
SNAP = TEMP / "batchL-head-snapshots"
NEG = TEMP / "batchL-neg"

#: 被测文件 -> 仓库根相对路径（`git show HEAD:` 用斜杠形式）。
TARGETS = {
    "verify_tools": "agentflow/src/agentflow/tools/verify_tools.py",
    "formalgw": "agentflow/src/agentflow/formalgw.py",
    "agent_b": "agentflow/src/agentflow/agent_b.py",
    "verify": "agentflow/src/agentflow/verify.py",
}


def sha16(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


def cur_file(rel: str) -> Path:
    return REPO / rel.split("agentflow/", 1)[1]


# --------------------------------------------------------------- pytest 驱动


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(TEMP) + os.pathsep + env.get("PYTHONPATH", "")
    return env


def run_pytest(nodeids: list[str], timeout: int = 900) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, "-m", "pytest", *nodeids, "-q", "-s",
                           "-p", "no:cacheprovider"],
                          cwd=str(REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=_env(), timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def run_neg(case: str, nodeid: str, timeout: int = 900) -> tuple[int, str]:
    """跑负控目录里的用例副本。

    环境变量里必须带 `PYTHONPATH=temp/batchL-neg`：那份 `sitecustomize.py` 负责在
    **任何用例文件被导入之前**把 `src` / `tests` / `batchL-neg` 三条路径装好
    （不这么做的实测形态是 `ModuleNotFoundError: No module named 'agentflow'` ——
    红是环境造成的，读数是废的）。
    """
    env = _env()
    env["PYTHONPATH"] = str(NEG) + os.pathsep + env["PYTHONPATH"]
    path = NEG / case / nodeid
    proc = subprocess.run([sys.executable, "-m", "pytest", str(path), "-q", "-s",
                           "-p", "no:cacheprovider"],
                          cwd=str(REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env, timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def tail(text: str, n: int = 16) -> str:
    return "\n".join(text.splitlines()[-n:])


def old_impl_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith("[OLD-IMPL]")]


# --------------------------------------------------------------- 探针自校准


def calibrate() -> bool:
    """用一对"必然成立 / 必然不成立"的输入校准探针自己。

    - 必然成功：当前实现下 `test_status_source_unreadable_...` 必须绿；
    - 必然失败：同一个断言、改前实现（负控副本）必须红。

    如果连这一对都给不出 绿/红，说明探针入口本身坏了，后面的读数一律不采信。
    """
    node = ("tests/test_formalgw.py::"
            "test_status_source_unreadable_when_the_source_path_cannot_be_read")
    rc_green, out_green = run_pytest([node])
    rc_red, out_red = run_neg("e3", node.split("::", 1)[1].join(
        ["test_formalgw_snap.py::", ""]))
    print(f"  [校准] 必然成功的输入 ⇒ 退出码 {rc_green}（要 0）")
    print(f"  [校准] 必然失败的输入（改前 formalgw）⇒ 退出码 {rc_red}（要非 0）")
    good = rc_green == 0 and rc_red != 0
    print(f"  [校准] 探针可信？ {good}")
    if not good:
        print(tail(out_green, 8))
        print(tail(out_red, 8))
    return good


# --------------------------------------------------------------- 各条判据

E3_NODE = ("tests/test_formalgw.py::"
           "test_status_source_unreadable_when_the_source_path_cannot_be_read")
E3_NODE2 = ("tests/test_formalgw.py::"
            "test_status_decl_mismatch_still_holds_when_the_file_was_read_fine")

E11_NODES = [
    "tests/test_agent_b.py::test_misdeclared_page_is_flagged_in_stored_quote_check",
    "tests/test_agent_b.py::test_a_correct_page_does_not_count_as_out_of_declared_range",
    "tests/test_verify_quote_levels.py::test_misdeclared_page_range_is_reported_by_deep_verify",
    "tests/test_verify_quote_levels.py::test_a_correct_page_range_is_not_reported",
    "tests/test_verify_quote_levels.py::test_page_range_mismatch_is_warning_not_error",
]

C1_NODE = ("tests/test_tools_audit_fixes.py::"
           "test_code_hash_failure_kinds_match_its_declaration_every_branch")

D10_NODE = ("tests/test_verify_extended.py::"
            "test_unknown_citation_kind_message_lists_every_declared_prefix")
D10_NODE2 = ("tests/test_verify_extended.py::"
             "test_negative_control_the_old_message_would_be_caught")


def _neg_node(case: str, nodeid: str) -> str:
    """把 `tests/xxx.py::name` 换成负控目录里的 `xxx_snap.py::name`。"""
    path, _, name = nodeid.partition("::")
    stem = Path(path).stem
    return f"{stem}_snap.py::{name}"


def ctl_e3() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    rc, text = run_pytest([E3_NODE])
    out.append(("E-3 正控：读不到源码 ⇒ source_unreadable", rc == 0, tail(text, 6)))

    rc2, text2 = run_neg("e3", _neg_node("tests/test_formalgw.py", E3_NODE))
    marks = old_impl_lines(text2)
    out.append((f"E-3 负控注入生效（{len(marks)} 行 [OLD-IMPL]）",
                any("formalgw_HEAD.py" in m for m in marks), "\n".join(marks)))
    out.append(("E-3 负控：改前 formalgw ⇒ 该判据变红（decl_mismatch）",
                rc2 != 0 and "decl_mismatch" in text2, tail(text2, 8)))

    rc3, text3 = run_pytest([E3_NODE2])
    out.append(("E-3 正控的另一半：文件读到了、只是没有那个声明 ⇒ 仍 decl_mismatch",
                rc3 == 0, tail(text3, 6)))
    return out


def ctl_e11() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    rc, text = run_pytest(E11_NODES)
    out.append(("E-11 正控：agent_b 计数 + verify --deep 报出 + 防误伤", rc == 0, tail(text, 6)))

    rc2, text2 = run_neg("e11-agentb", _neg_node("tests/test_agent_b.py", E11_NODES[0]))
    marks = old_impl_lines(text2)
    out.append((f"E-11 负控注入生效（agent_b 快照，{len(marks)} 行 [OLD-IMPL]）",
                any("agent_b_HEAD.py" in m for m in marks), "\n".join(marks)))
    out.append(("E-11 负控：改前 agent_b ⇒ 没有那一档计数，判据变红",
                rc2 != 0 and "quotes_out_of_declared_range" in text2, tail(text2, 12)))

    rc3, text3 = run_neg("e11-verify",
                         _neg_node("tests/test_verify_quote_levels.py", E11_NODES[2]))
    marks3 = old_impl_lines(text3)
    out.append((f"E-11 负控注入生效（verify 快照，{len(marks3)} 行 [OLD-IMPL]）",
                any("verify_HEAD.py" in m for m in marks3), "\n".join(marks3)))
    out.append(("E-11 负控：改前 verify ⇒ --deep 一声不响，判据变红",
                rc3 != 0 and "page_range_mismatch" in text3, tail(text3, 10)))
    return out

def ctl_c1() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    rc, text = run_pytest([C1_NODE])
    out.append(("C1 正控：声明失败词表与各分支实测 kind 逐值相同", rc == 0, tail(text, 6)))

    inj = TEMP / "_batchL_c1_injected_verify_tools.py"
    if not inj.exists():
        out.append(("C1 负控：注入副本不存在", False,
                    "先跑 python temp/_batchL_mkinject.py"))
        return out
    rc2, text2 = run_neg("c1", _neg_node("tests/test_tools_audit_fixes.py", C1_NODE))
    out.append((f"C1 负控：改前 _hash_of（注入副本 sha256前16={sha16(inj.read_bytes())}）"
                "⇒ 该判据变红", rc2 != 0 and "tool_error" in text2, tail(text2, 10)))
    return out


def ctl_d1() -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    scanner = TEMP / "audit-b" / "line_ref_scan.py"
    env = _env()

    cur = REPO / "src/agentflow/tools/verify_tools.py"
    proc = subprocess.run([sys.executable, str(scanner), "src/agentflow", str(cur)],
                          cwd=str(REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    last = proc.stdout.strip().splitlines()[-1]
    out.append(("D1 正控：verify_tools.py 0 处行号漂移", last.endswith("共 0 处行号漂移"), last))

    head = SNAP / "verify_tools_HEAD.py"
    proc2 = subprocess.run([sys.executable, str(scanner), "src/agentflow", str(head)],
                           cwd=str(REPO), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=env)
    text2 = proc2.stdout
    drift = re.findall(r"引用 `(base\.py:\d+(?:-\d+)?)`", text2)
    out.append((f"D1 负控：改前快照仍报漂移（命中 {drift}）",
                "base.py:381-382" in text2, text2.strip().splitlines()[-1]))
    head_text = head.read_text(encoding="utf-8")
    out.append((f"D1 负控指纹：{head.name} sha256前16={sha16(head_text)} 行数"
                f"={len(head_text.splitlines())}，含 'base.py:381-382'?"
                f"{'base.py:381-382' in head_text}",
                "base.py:381-382" in head_text, ""))
    return out


def ctl_d10(neg_dir: str = "d10") -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    rc, text = run_pytest([D10_NODE, D10_NODE2])
    out.append(("D10 正控：消息与词表双向一致 + 改前那句话确实会红", rc == 0, tail(text, 6)))

    rc2, text2 = run_neg(neg_dir, _neg_node("tests/test_verify_extended.py", D10_NODE))
    marks = old_impl_lines(text2)
    out.append((f"D10 负控注入生效（verify 快照，{len(marks)} 行 [OLD-IMPL]）",
                any("verify_HEAD.py" in m for m in marks), "\n".join(marks)))
    out.append(("D10 负控：改前 verify.py ⇒ 消息漏 eval:，判据变红",
                rc2 != 0 and "eval" in text2, tail(text2, 8)))
    return out


CONTROLS = {
    "E-3": ctl_e3,
    "E-11": ctl_e11,
    "C1": ctl_c1,
    "D1": ctl_d1,
    "D10": ctl_d10,
}


def main(argv: list[str]) -> int:
    want = [a for a in argv[1:] if a in CONTROLS] or list(CONTROLS)
    print("=" * 78)
    print("批 L 探针：正控 = 改后实现；负控 = git HEAD 的改前实现（必须变红）")
    print(f"仓库：{REPO}")
    print(f"快照：{SNAP}    负控目录：{NEG}")
    print("=" * 78)

    print("\n[0] 指纹（改后 vs 改前）")
    for key, rel in TARGETS.items():
        p = cur_file(rel)
        if p.exists():
            text = p.read_text(encoding="utf-8")
            print(f"  改后 {p.relative_to(REPO)}  sha256前16={sha16(text)} 行数={len(text.splitlines())}")
    for f in sorted(SNAP.glob("*_HEAD.py")):
        text = f.read_text(encoding="utf-8")
        print(f"  快照 {f.name}  sha256前16={sha16(text)} 行数={len(text.splitlines())}")

    print("\n[1] 校准探针自己（必然成功 / 必然失败的输入）")
    if not calibrate():
        print("\n✗ 探针自身不可信 —— 后面的读数不采信")
        return 1

    results: list[tuple[str, bool, str]] = []
    for key in want:
        print(f"\n[2] {key}")
        for label, ok, detail in CONTROLS[key]():
            results.append((label, ok, detail))
            print(f"  [{'OK' if ok else 'FAIL'}] {label}")

    bad = [r for r in results if not r[1]]
    print("\n" + "=" * 78)
    print(f"合计 {len(results)} 条读数，{len(results) - len(bad)} 条符合预期，{len(bad)} 条不符合")
    for label, _ok, detail in bad:
        print(f"  [FAIL] {label}")
        for ln in tail(detail, 6).splitlines():
            print(f"         {ln}")
    print("=" * 78)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
