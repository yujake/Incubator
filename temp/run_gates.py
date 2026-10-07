"""在**批边界、无写入**时一次跑完四道门，把读数写进一份带观测窗口的证据文件。

用法：`python temp/run_gates.py <标签>`（例如 `python temp/run_gates.py r62`）
输出：`temp/<标签>-gates.txt`（汇总）+ 各自的明细文件 `temp/<标签>-suite-default.txt` 等。

四道门（与 goal 判据三逐条对应）：
1. `python scripts/lint_rules.py` ⇒ `error 0`
2. `python -m pytest tests/ -q` 两种环境（默认 / Lean 进 PATH）各 `0 failed`
3. `python tools/run_each_test_file.py` 单独跑不过 0（两种环境各一次）
4. `python tools/release_all.py --since HEAD` 除 `release-check` 里的 `noai` 外无 fail

**开跑前自己先做两件事**（脚本会打出来，但不替你判断）：
- 打出每个"受审文件"的 mtime，让你能看出有没有人在写；
- 打出 `lint` 的即时读数（第 1 道门的第一手读数）。

`--assert-no-writers` 是**裸断言**，所以它**单独不够**（§73：父代理自己在没核实的情况下传过它）：
还要 `--writers-credential <落档的 list_agents 输出>`。脚本会核"有没有落档 / 多大 / 多旧 / 哈希"，
并**如实声明**它核实不了那份输出是不是真来自 `list_agents`。`--check-only` 只跑到静止前提为止。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(r"D:\Incubator\agentflow")
TEMP = Path(r"D:\Incubator\temp")
LEAN_BIN = r"D:\Incubator\temp\lean470\lean-4.7.0-windows\bin"


def _arg_value(name: str) -> str | None:
    """取 `--name <值>` 的值；找不到返回 None（`name` 本身是裸开关时也能用）。"""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def run(cmd: list[str], out: Path, env_extra: dict | None = None, cwd: Path = REPO):
    t0 = time.time()
    import os

    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "PYTHONPATH": "src"})
    if env_extra:
        env.update(env_extra)
    with out.open("wb") as fh:
        p = subprocess.run(cmd, cwd=str(cwd), stdout=fh, stderr=subprocess.STDOUT, env=env)
    return p.returncode, round(time.time() - t0, 1), out


def tail(p: Path, n: int = 4) -> list[str]:
    try:
        return p.read_text(encoding="utf-8", errors="replace").strip().split("\n")[-n:]
    except OSError:
        return ["(读不到)"]


def _tree_state() -> dict:
    """整棵工作树的 `(sha256, 字节, mtime)`（复用 `_who_writes.take`，不另写一份）。"""
    sys.path.insert(0, str(TEMP))
    import _who_writes as WW          # 同目录；它 import 时会把 stdout 设成 UTF-8
    
    return WW.take(REPO)["files"]


def _window_delta(before: dict, after: dict) -> tuple[list, list, list, list]:
    """窗口内三个**不同**的量：内容改了 / 新增了 / 消失了 / **只被 mtime 碰过**。

    为什么第四个必须单列（`2026-09-27` 买到）：`b78` 的收工核对只比 `sha256`，
    于是打印出"本窗口内改动 0 / 新增 0（**窗口内无写入** ⇒ 读数有效）"——
    而实测 `agentflow/data/events.jsonl`（0 字节）的 mtime 在窗口内从 12:25:58 走到 14:13:40，
    **确实有东西写过它**，只是写进去的字节与原来一模一样（都是空）。
    ⇒ 内容口径的结论是对的（受审字节没变），但"窗口内无写入"这句话是**假的**：
    门要证明的是"没有 writer 在跑"，而 mtime 是唯一能看见"写过但没改内容"的信号。
    """
    common = set(before) & set(after)
    changed = sorted(k for k in common if before[k]["sha256"] != after[k]["sha256"])
    added = sorted(set(after) - set(before))
    gone = sorted(set(before) - set(after))
    touched = sorted(k for k in common
                     if before[k]["sha256"] == after[k]["sha256"]
                     and before[k].get("mtime") != after[k].get("mtime"))
    return changed, added, gone, touched


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else f"gates-{datetime.now():%H%M}"
    log: list[str] = [f"===== 四道门 开始 {datetime.now().isoformat(timespec='seconds')} 标签={label} =====",
                      "# 开跑前：受审文件的 mtime（若有一行是「刚刚」，说明还有人在写 ⇒ 别信这次读数）"]
    for rel in ("src/agentflow", "tests", "tools", "scripts"):
        newest = max((p.stat().st_mtime for p in (REPO / rel).rglob("*.py")), default=0)
        log.append(f"#   {rel:16s} 最新 mtime = "
                   f"{datetime.fromtimestamp(newest):%Y-%m-%d %H:%M:%S}")

    # ---- 静止前提（**硬拦**）：判据三要求四道门在"批边界 + 无写入"时跑。
    # 光靠"我看了一眼 mtime"不算证明；这里做一次**逐字节**的前后快照（§40.2 / §45.6）。
    # 三件事缺一不可（第一版只做了第 1 件，被自己的测试打回）：
    #   ① 逐字节前后快照 —— 挡"正在写"；
    #   ② **足够长的窗口**（默认 30 秒）—— 6 秒挡不住"写者正在思考、下一步再写"；
    #   ③ 操作者**显式声明**"已核实没有 writer 在跑"（`--assert-no-writers`）——
    #      脚本无法调用 `list_agents`，所以它**不许假装知道**；它只如实记录"谁在什么时刻断言过"。
    static_sec = int(os.environ.get("GATES_STATIC_SECONDS", "30"))
    check_only = "--check-only" in sys.argv
    asserted = "--assert-no-writers" in sys.argv
    # `--only lint,suite` 之类的**部分门**读数（阶段 B 用：修复只动少数文件时不必重跑全套 ≈87 分钟）。
    # 纪律：未跑的门在汇总里记 `SKIP`，**绝不许**读成 pass —— 这份读数只能用于"被选中的那几道门"。
    only_raw = _arg_value("--only")
    only = {x.strip() for x in only_raw.split(",") if x.strip()} if only_raw else None
    known_only = ("lint", "suite", "suite-lean", "perfile", "perfile-lean", "release-all")
    if only is not None:
        unknown_only = sorted(only - set(known_only))
        if unknown_only:
            raise SystemExit(f"--only 里有不认识的门名：{unknown_only}；可选：{list(known_only)}")

    def want(name: str) -> bool:
        return only is None or name in only
    log += ["", f"# 静止前提：{static_sec} 秒逐字节快照 + 操作者显式断言（judge 三的硬要求）"]
    before = _tree_state()
    time.sleep(static_sec)
    now = _tree_state()
    moved, added, gone, touched_now = _window_delta(before, now)
    if moved or added or gone:
        log += [f"# ✗ 树不静止：改了 {len(moved)} / 新增 {len(added)} / 消失 {len(gone)}",
                *[f"#     {k}" for k in (moved + added + gone)[:20]],
                "# ⇒ **四道门没有开跑**（exit 2 = 没查成；不给你一份会被作废的读数）"]
        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 2
    log.append(f"# ✓ {static_sec} 秒内 {len(before)} 个文件逐字节未变"
               f"（基线 {TEMP / (label + '-sha-before.json')}）")
    if touched_now:
        # 内容没变、mtime 变了：有人**写过但写回同样的字节**。内容口径仍算静止，
        # 但这必须**看得见** —— 否则"没有 writer 在跑"这句话就没人核。
        log.append(f"# ! 其中 {len(touched_now)} 个文件在窗口内**只被 mtime 碰过**（内容未变）：")
        for k in touched_now[:20]:
            log.append(f"#     [{before[k].get('mtime')} → {now[k].get('mtime')}] {k}")
    if not asserted:
        log += ["# ✗ 没给 `--assert-no-writers`：静止窗口只能证明「刚刚没人写」，"
                "证明不了「没有 writer 正在思考」。脚本不替你猜 ⇒ 不开跑（exit 2）。",
                "#   用法：先用 `list_agents` 核实没有 writer，再 `python temp/run_gates.py <标签> "
                "--assert-no-writers --writers-credential temp/writers-cred-<标签>.txt`"]
        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 2
    log.append(f"# ✓ 操作者在 {datetime.now().isoformat(timespec='seconds')} 显式断言：已核实无 writer 在跑")

    # ---- 光有断言不够：§73 的教训是**父代理自己在没核实的情况下传过这个裸开关**。
    # 现在要求一份**落档凭据**（`list_agents` 的原始输出落成文件）。
    # 脚本能核实的：有没有落档 / 多大 / 多旧 / 内容哈希；它**核实不了**那份输出是不是
    # 真的来自 `list_agents` —— 那一半只能靠人，所以如实写在日志里（不许假装知道）。
    cred_arg = _arg_value("--writers-credential")
    cred_max_age = float(os.environ.get("GATES_CRED_MAX_AGE", "900"))
    if not cred_arg:
        log += ["# ✗ 没给 `--writers-credential <落档的 list_agents 输出>`：",
                "#   裸断言正是 §73 抓到的形态（说了「已核实」，其实只是「它两分钟没写」）。",
                "#   用法：`list_agents` 跑一遍，把原始输出存成 `temp/writers-cred-<标签>.txt`，",
                "#        再 `python temp/run_gates.py <标签> --assert-no-writers \\",
                "#            --writers-credential temp/writers-cred-<标签>.txt`",
                "#   ⇒ **四道门没有开跑**（exit 2）。"]
        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 2
    cred = Path(cred_arg)
    if not cred.is_absolute():
        # 相对路径按**当前工作目录**解析（文档里的用法是 `temp/writers-cred-<标签>.txt`，
        # 也就是从 `D:\Incubator` 跑）—— 第一版按 `TEMP` 解析，把
        # `temp/_credtest-ok.txt` 拼成了 `temp\temp\_credtest-ok.txt` 而报"不存在"（自测抓到）。
        cred = (Path.cwd() / cred).resolve()
    if not cred.is_file():
        log += [f"# ✗ 凭据文件不存在：{cred} ⇒ 四道门没有开跑（exit 2）。"]
        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 2
    raw = cred.read_bytes()
    if not raw.strip():
        log += [f"# ✗ 凭据文件是空的：{cred} ⇒ 空文件不算凭据（exit 2）。"]
        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 2
    age = time.time() - cred.stat().st_mtime
    if age > cred_max_age:
        log += [f"# ✗ 凭据太旧：{cred} 是 {age / 60:.1f} 分钟前的"
                f"（上限 {cred_max_age / 60:.1f} 分钟）—— 世界可能已经变了 ⇒ exit 2。",
                "#   （要放宽就设 `GATES_CRED_MAX_AGE`，但**别**把上限调到荒谬的大。）"]
        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 2
    log += [f"# ✓ 落档凭据 `{cred.name}`：{len(raw)} 字节，sha256:"
            f"{hashlib.sha256(raw).hexdigest()[:16]}，观测 "
            f"{datetime.fromtimestamp(cred.stat().st_mtime):%Y-%m-%d %H:%M:%S}"
            f"（距今 {age:.0f} 秒）",
            "#   诚实边界：脚本核实的是「有没有落档 / 多大 / 多旧 / 哈希」；"
            "**核实不了**那份输出是不是真来自 `list_agents` —— 那一半靠人。"]
    (TEMP / f"{label}-sha-before.json").write_text(
        json.dumps({"taken_at": datetime.now().isoformat(timespec="seconds"), "files": before},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    if check_only:
        log += ["# （--check-only）静止前提已通过，未跑四道门。"]

        (TEMP / f"{label}-gates.txt").write_text("\n".join(log) + "\n",
                                                 encoding="utf-8", newline="\n")
        print("\n".join(log))
        return 0
    log.append("")

    if want("lint"):
        rc, sec, out = run([sys.executable, "scripts/lint_rules.py"], TEMP / f"{label}-lint.txt")
        summary = [ln for ln in tail(out, 40) if "error" in ln and "warning" in ln]
        log += [f"1) lint  exit={rc}  {sec}s", f"   {summary[-1].strip() if summary else '(没找到汇总行)'}"]
        rc1 = rc
    else:
        log.append("1) lint  [SKIP]  --only 未选中（**不许读成 pass**）")
        rc1 = None

    if want("suite"):
        rc, sec, out = run([sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
                           TEMP / f"{label}-suite-default.txt")
        log += [f"2a) 全量（默认）  exit={rc}  {sec}s"] + [f"   {x}" for x in tail(out, 2)]
        rc2 = rc
    else:
        log.append("2a) 全量（默认）  [SKIP]  --only 未选中（**不许读成 pass**）")
        rc2 = None

    if want("suite-lean"):
        rc, sec, out = run([sys.executable, "-m", "pytest", "tests/", "-q", "-p", "no:cacheprovider"],
                           TEMP / f"{label}-suite-lean.txt", {"PATH": LEAN_BIN + ";" + str(
                               __import__("os").environ.get("PATH", ""))})
        log += [f"2b) 全量（Lean 进 PATH）  exit={rc}  {sec}s"] + [f"   {x}" for x in tail(out, 2)]
        rc3 = rc
    else:
        log.append("2b) 全量（Lean 进 PATH）  [SKIP]  --only 未选中（**不许读成 pass**）")
        rc3 = None

    if want("perfile"):
        rc, sec, out = run([sys.executable, "tools/run_each_test_file.py"],
                           TEMP / f"{label}-perfile-default.txt")
        log += [f"3a) 逐文件（默认）  exit={rc}  {sec}s"] + [f"   {x}" for x in tail(out, 2)]
        rc4 = rc
    else:
        log.append("3a) 逐文件（默认）  [SKIP]  --only 未选中（**不许读成 pass**）")
        rc4 = None

    if want("perfile-lean"):
        rc, sec, out = run([sys.executable, "tools/run_each_test_file.py"],
                           TEMP / f"{label}-perfile-lean.txt",
                           {"PATH": LEAN_BIN + ";" + str(__import__("os").environ.get("PATH", ""))})
        log += [f"3b) 逐文件（Lean 进 PATH）  exit={rc}  {sec}s"] + [f"   {x}" for x in tail(out, 2)]
        rc5 = rc
    else:
        log.append("3b) 逐文件（Lean 进 PATH）  [SKIP]  --only 未选中（**不许读成 pass**）")
        rc5 = None

    jpath = TEMP / f"{label}-release-all.json"
    if want("release-all"):
        # 改动集：**不给 `--since`**。本仓只有一个提交（HEAD=8f226cc），没有可用的祖先 ⇒
        # `HEAD..HEAD` 恒空，`--since HEAD` 正是 `F-R1d-01` 修掉的那种退化基线
        # （`noai_gate` 现在会判 unknown(2)，那是诚实结果，但会让这一步判不出 `noai`）。
        # 所以显式取"未提交 + 未跟踪"的改动集（唯一实现仍在 `noai_gate --print-changed` 里），
        # 落成文件后交给 `release_all --changed-file`（该开关优先于 `--since`）。
        chlog = TEMP / f"{label}-changed.log"
        run([sys.executable, "scripts/noai_gate.py", "--print-changed", "--root", "."], chlog)
        paths = [ln.strip() for ln in
                 chlog.read_text(encoding="utf-8", errors="replace").splitlines()
                 if ln.strip() and not ln.startswith(("[", "#"))]
        chfile = TEMP / f"{label}-changed.txt"
        chfile.write_text("\n".join(paths) + "\n", encoding="utf-8", newline="\n")
        rc, sec, out = run([sys.executable, "tools/release_all.py", "--changed-file", str(chfile),
                            "--json", str(jpath)], TEMP / f"{label}-release-all.log")
        log += [f"4) release_all --changed-file（{len(paths)} 条改动路径；不给 --since —— "
                f"本仓没有可用祖先）  exit={rc}  {sec}s"]
        try:
            o = json.loads(jpath.read_text(encoding="utf-8"))
            log.append(f"   counts={o.get('counts')}")
            for s in o.get("steps") or []:
                log.append(f"   [{str(s.get('verdict')):6s}] {str(s.get('key')):14s} "
                           f"exit={s.get('exit_code')} subcounts={s.get('subcounts')}")
                for it in s.get("subitems") or []:
                    if str(it.get("verdict")) != "pass":
                        log.append(f"        [{it.get('verdict')}] {it.get('key')}")
        except Exception as exc:  # noqa: BLE001
            log.append(f"   （读不了 JSON：{exc}）") + [f"   {x}" for x in tail(out, 6)]
        rc6 = rc
    else:
        log.append("4) release_all --since HEAD  [SKIP]  --only 未选中（**不许读成 pass**）")
        rc6 = None

    def _fmt(v):
        return "SKIP" if v is None else str(v)

    log += ["", f"===== 汇总：lint={_fmt(rc1)} 默认={_fmt(rc2)} lean={_fmt(rc3)} "
                f"perfile={_fmt(rc4)}/{_fmt(rc5)} release_all={_fmt(rc6)} ====="]
    if only is not None:
        log.append(f"# ! 这是一份**部分门**读数（--only {','.join(sorted(only))}）："
                   "未选中的门没有跑、记 SKIP —— **不许**把 SKIP 读成 pass，也不许拿它当判据三的读数。")

    # ---- 收工核对：本次窗口内**有没有人写**。内容被改/新增 ⇒ 这次读数作废（不是"大概没事"）。
    #      只被 mtime 碰过 ⇒ 内容口径仍有效，但**如实报数**，不再说"窗口内无写入"。
    after = _tree_state()
    ch2, add2, gone2, touch2 = _window_delta(before, after)
    if ch2 or add2 or gone2:
        tail_msg = "（**这次读数作废**：窗口内有人写）"
    elif touch2:
        tail_msg = (f"（**内容**口径有效，但窗口内**确实有人写过**这 {len(touch2)} 个文件"
                    "（字节没变、mtime 变了）⇒ 不许把这次读数说成「窗口内无写入」）")
    else:
        tail_msg = "（窗口内既无内容改动、也无 mtime 变化 ⇒ 读数有效）"
    log.append(f"# 收工核对：本窗口内改动 {len(ch2)} / 新增 {len(add2)} / 消失 {len(gone2)} "
               f"/ 仅 mtime 变 {len(touch2)}" + tail_msg)
    for k in (ch2 + add2 + gone2)[:20]:
        log.append(f"#     [内容] {k}")
    for k in touch2[:20]:
        log.append(f"#     [仅 mtime {before[k].get('mtime')} → {after[k].get('mtime')}] {k}")
    log.append(f"===== 结束 {datetime.now().isoformat(timespec='seconds')} =====")
    text = "\n".join(log) + "\n"
    (TEMP / f"{label}-gates.txt").write_text(text, encoding="utf-8", newline="\n")
    (TEMP / f"{label}-sha-after.json").write_text(
        json.dumps({"taken_at": datetime.now().isoformat(timespec="seconds"), "files": after},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print(text)
    # 退出码口径：内容被改 / 新增 / 消失 ⇒ 2（读数作废）；**只被 mtime 碰过 ⇒ 仍 0**
    # （受审字节没变，结论可用），但那件事已经在上面逐条打印，不许当成没发生。
    return 2 if (ch2 or add2 or gone2) else 0


if __name__ == "__main__":
    raise SystemExit(main())
