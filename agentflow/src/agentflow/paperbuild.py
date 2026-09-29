# -*- coding: utf-8 -*-
"""论文包的构建 / 编译 / 锚核对：把项目里的三个脚本接成一条可判的序列。

## 这一层填的是哪个洞

`draft/28` §184.5 第 5 步：把打包与核对暴露成工具（终点门槛 B 是"由角色通过工具触发
从源重编 main.pdf，且渲染锚 0 漂移"）。在此之前，重编论文包只有一条路：人记着
`SUBMISSION.md` 里那四行命令、按顺序手敲 —— 而"顺序错了"的后果是一种同形的失败：
包看起来是新的，锚却已经过期，两者在验收里长得一样。

## 为什么不在这里重写判据

判据在项目脚本里（`make_paper.py` / `compile_paper.py` / `acceptance.py`），
这一层只做三件事，每一件都要能机械判：

1. 以受限的方式起子进程：工作目录锁在项目根、脚本必须在项目内、超时可控；
2. 读回脚本自己的 `REPRO_RESULT: {json}` 契约（原始退出码一字不改地带出来 ——
   本机 MiKTeX 会带着 PDF 写完却以 `0xC0000409` 退出，把那个码改写成"失败"或"成功"
   都是丢信息）；
3. 把三态结论翻成工具层的 ok/fail：0 一致 / 1 漂移 / 2 没查成。
   「没查成」绝不能看起来像「一致」—— 锚文件不存在时 `--check` 退出码就是 2。

## 一条实测出来的装置缺陷（本轮真机读数，登记在 `draft/28` §188）

`make_paper.py` 写的渲染锚（`RENDER-ANCHOR.json`）把源文件与编译产物放进同一张
哈希表（`main.tex` 与 `main.pdf` 都在里面），而锚是在渲染那一刻写的。
于是"重编一次 PDF"必然让 `main.pdf` 的字节变化（页数、内容都一样，变的是 PDF 内嵌的
时间戳与 ID）⇒ 按 `SUBMISSION.md` 写的顺序跑完，`--check` 报 1 处漂移：

    文件 main.pdf：内容与渲染时不同（56cc30f855b4 ≠ e46e64e40108）     实测 2026-09-29

也就是说：只要先写锚、后编译，"0 漂移"就不可达。本模块的 `build()` 用一条
可达的顺序绕开它（渲染 → 编译 → 再渲染一次把锚挪到新 PDF 上 → 核对），
修法（`draft/28` §191，用户已批准）：判据搬进 `agentflow.renderanchor`，
锚只管渲染产出的源文件，PDF 由编译回执（`COMPILE-RECEIPT.json`）管 ——
于是 `build()` 只需要 渲染 → 编译 → 核对 三步，"PDF 是从旧 tex 编的"变成一个精确可判的事实。
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: 项目里那两个脚本的相对路径（本仓论文包的约定；可用参数覆盖）。
DEFAULT_RENDER_SCRIPT = "code/make_paper.py"
DEFAULT_COMPILE_SCRIPT = "code/compile_paper.py"

#: 脚本约定的结论行前缀（`agent_e` 的惯例：一行 JSON，机器可读）。
REPRO_PREFIX = "REPRO_RESULT: "

#: 子进程默认超时（秒）。编译要跑两遍 pdflatex（21 页 ≈ 40s），渲染是秒级；
#: 取 1800 是给"机器很慢"留余量，同时不让一次工具调用无限挂住。
DEFAULT_TIMEOUT_SEC = 1800.0

#: 锚里的"锚文件就写在这里"（与 `make_paper.ANCHOR_NAME` 同一个名字的读法）。
ANCHOR_NAME = "RENDER-ANCHOR.json"


def _file_digest(path: Path) -> str:
    """文件内容哈希（读不了返回空串 —— 调用方按"读不到"处理，不编哈希）。"""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def parse_repro(text: str) -> dict[str, Any] | None:
    """取最后一行 `REPRO_RESULT: {json}`；没有或不是合法 JSON 就返回 None。

    为什么取最后一行：脚本可能先打印中间过程的读数，结论在最后；
    取第一行会在"脚本先报了一句话再给结论"时读到错的东西。
    """
    lines = [ln for ln in (text or "").splitlines() if ln.startswith(REPRO_PREFIX)]
    if not lines:
        return None
    try:
        data = json.loads(lines[-1][len(REPRO_PREFIX):])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def resolve_script(project_root: Path, script: str) -> tuple[Path | None, str]:
    """把 `script` 解析成项目内的一个真实文件。返回 `(路径, 问题)`。

    越界一律拒：绝对路径、`..`、跳出项目根的软链接都算 —— 这一层要起子进程，
    放宽等于"调用方决定跑什么"，而工具层的审批面把那个能力定义成 `exec`。
    """
    raw = str(script or "").strip()
    if not raw:
        return None, "script 不能为空"
    candidate = Path(raw)
    if candidate.is_absolute():
        return None, f"script 必须是项目内的相对路径（收到绝对路径 {raw}）"
    root = project_root.resolve()
    target = (project_root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None, f"script 跑出项目根了：{raw}"
    if not target.is_file():
        return None, f"脚本不在盘上：{target}（项目根 {root}）"
    return target, ""


def run_script(project_root: Path | str, script: str, *,
               timeout_sec: float = DEFAULT_TIMEOUT_SEC,
               extra_args: list[str] | None = None) -> dict[str, Any]:
    """在项目根里跑一个脚本，读回它的结论。不抛业务异常，一切如实落在返回值里。

    返回的键（工具层逐字声明，见 `tools/doc_tools.py`）：
    `script` / `script_path` / `argv` / `exit_code` / `timed_out` / `ok` / `result` /
    `elapsed_sec` / `stdout_tail` / `stderr_tail` / `repro_found` / `problem`。
    """
    root = Path(project_root)
    target, problem = resolve_script(root, script)
    if target is None:
        return {"script": script, "script_path": "", "argv": [], "exit_code": None,
                "timed_out": False, "ok": False, "result": None, "elapsed_sec": 0.0,
                "stdout_tail": "", "stderr_tail": "", "repro_found": False,
                "problem": problem}
    argv = [sys.executable, "-B", str(target), *(extra_args or [])]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=float(timeout_sec),
                              check=False)
        out, err, code, timed_out = proc.stdout or "", proc.stderr or "", proc.returncode, False
    except subprocess.TimeoutExpired as exc:  # noqa: BLE001 —— 超时是"没查成"，不是"跑失败了"
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        code, timed_out = None, True
    except OSError as exc:
        out, err, code, timed_out = "", f"{type(exc).__name__}: {exc}", None, False

    result = parse_repro(out)
    # 这一步算不算走成了：退出码 0 + 打出了结论行。结论行里若显式带 `ok`，
    # 它还必须是 True —— 两者矛盾时（exit 0 但 ok=false）不认成功。
    #
    # 为什么不能要求结论行里必须有 `ok`：本仓项目脚本的契约不一样 ——
    # `compile_paper.py` 打的是 `{"ok": ..., "pages": ...}`，而 `make_paper.py`
    # 打的是 `{"claims": ..., "render_anchor": ...}`（没有 ok 键，成功与否由退出码说）。
    # 这条规则是真机读数逼出来的：第一版要求 `result["ok"]`，于是 make_paper
    # 明明退出码 0、结论行齐全，却被判成"没走成"（实测 2026-09-29）。
    explicit = result.get("ok") if isinstance(result, dict) else None
    ok = bool(result is not None and not timed_out and code == 0 and explicit is not False)
    if timed_out:
        problem = "超时（没查成）"
    elif result is None:
        problem = "脚本没打印 `REPRO_RESULT:` 结论行 ⇒ 结论读不到（没查成，不是通过）"
    elif code != 0:
        problem = f"脚本以退出码 {code} 结束（结论行照读，退出码照留）"
    elif explicit is False:
        problem = "脚本自己说 ok=false（退出码 0 也没用：两个信号矛盾时按失败算）"
    else:
        problem = ""
    return {
        "script": script,
        "script_path": str(target),
        "argv": argv[1:],                       # 不含解释器路径（那是本机事实，不是契约）
        "exit_code": code,
        "timed_out": timed_out,
        "ok": ok,
        "result": result,
        "elapsed_sec": round(time.monotonic() - t0, 2),
        "stdout_tail": "\n".join(out.strip().splitlines()[-12:]),
        "stderr_tail": "\n".join(err.strip().splitlines()[-12:]),
        "repro_found": result is not None,
        "problem": problem,
    }


def render(project_root: Path | str, *, script: str = DEFAULT_RENDER_SCRIPT,
           timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """跑渲染脚本（默认 `code/make_paper.py`）：从库里的行重新产出稿件与配套。"""
    return run_script(project_root, script, timeout_sec=timeout_sec)


def compile_pdf(project_root: Path | str, *, script: str = DEFAULT_COMPILE_SCRIPT,
                timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """跑编译脚本（默认 `code/compile_paper.py`）：从 `main.tex` 重编 `main.pdf`。"""
    return run_script(project_root, script, timeout_sec=timeout_sec)


#: 锚核对的三态。中文名与退出码一起报出来，免得读的人自己去翻脚本。
ANCHOR_VERDICTS = {"consistent": 0, "drifted": 1, "unknown": 2}

#: 漂移行在 `--check` 输出里的样子（`[anchor]` 前缀之外的行）。
_DRIFT_LINE = re.compile(r"^\s*-\s+(表|文件)\s")


def anchor_check_script(project_root: Path | str, *, script: str = DEFAULT_RENDER_SCRIPT,
                        timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """跑项目脚本的 `--check`（默认 `make_paper.py --check`）：0 一致 / 1 漂移 / 2 没查成。

    这条走子进程（起的是项目里的脚本 ⇒ 工具层声明 `exec`），因此只读角色拿不到它；
    "只读角色也要能核这份包"由 `state()` 提供（同一份判据，进程内跑）。

    这条必须保持三态：`--check` 自己就用退出码区分"漂移"与"没查成"（锚不在），
    把它折成布尔会让"锚文件没了"看起来像"一致"。
    """
    got = run_script(project_root, script, timeout_sec=timeout_sec, extra_args=["--check"])
    code = got["exit_code"]
    drift = [ln.strip().lstrip("- ").strip()
             for ln in got["stdout_tail"].splitlines() if _DRIFT_LINE.match(ln)]
    if got["timed_out"] or code is None:
        verdict, why = "unknown", got["problem"] or "没查成"
    elif int(code) == 0 and drift:
        # 退出码说"一致"，输出里却有漂移行 ⇒ 两个信号互相矛盾。
        # 这种时候不给结论：说"一致"可能放过真漂移，说"漂移"可能冤枉一份好包。
        verdict, why = "unknown", ("脚本的退出码（0）与它打印的漂移行互相矛盾 ⇒ 没查成"
                                   "（两个信号打架时不许挑一个信）")
    elif int(code) == 0:
        verdict, why = "consistent", "包与库/盘一致"
    elif int(code) == 1:
        verdict, why = "drifted", "有漂移：这份包不是库里现在的样子"
    elif int(code) == 2:
        verdict, why = "unknown", "没查成（多半是锚文件不在盘上）"
    else:
        verdict, why = "unknown", f"退出码 {code} 不在三态词表里 ⇒ 没查成"
    root = Path(project_root)
    return {
        "verdict": verdict,
        "expected_exit_code": ANCHOR_VERDICTS[verdict],
        "exit_code": code,
        "drift": drift,
        "why": why,
        "script": got["script"],
        "anchor_path": str(root / "out" / "paper" / ANCHOR_NAME),
        "anchor_present": (root / "out" / "paper" / ANCHOR_NAME).is_file(),
        "anchor_sha256": _file_digest(root / "out" / "paper" / ANCHOR_NAME),
        "stdout_tail": got["stdout_tail"],
        "stderr_tail": got["stderr_tail"],
        "elapsed_sec": got["elapsed_sec"],
        "repro_found": got["repro_found"],
        "problem": got["problem"],
    }


#: 三维判定词表（与 `renderanchor.VERDICTS` 同一套）。
ANCHOR_DIMENSIONS: tuple[str, ...] = ("tables", "files", "receipt")


def anchor_check(project_root: Path | str, *, store: Any = None) -> dict[str, Any]:
    """核一份论文包（进程内，不起子进程、不出网）：三维 + 三态。

    判据只有一份实现：`agentflow.renderanchor.check`。这里做两件事 ——
    把三维结论翻成工具层要的三态读数，并把"哪一维判不了"与"哪一维漂移了"分开报
    （折成一个布尔会让"回执不在、PDF 来路判不了"看起来像"一致"）。
    """
    from . import renderanchor as RA

    got = RA.check_package(project_root, store=store)
    root = Path(project_root)
    if got["verdict"] == "consistent":
        why = "包与库/盘都对得上（0 漂移）"
    elif got["verdict"] == "drifted":
        why = "有漂移：这份包不是库里现在的样子"
    else:
        why = "没查成：" + ("；".join(got["problems"]) or "有一维判不了（不是一致）")
    return {
        "verdict": got["verdict"],
        "expected_exit_code": ANCHOR_VERDICTS[got["verdict"]],
        "dimensions": got["dimensions"],
        "drift": got["drift"],
        "problems": got["problems"],
        "why": why,
        "source": "in_process",
        "anchor_path": got["anchor_path"],
        "anchor_present": got["anchor_present"],
        "receipt_path": got["receipt_path"],
        "receipt_present": got["receipt_present"],
        "anchor_sha256": _file_digest(root / "out" / "paper" / ANCHOR_NAME),
        "rendered_at": got.get("rendered_at"),
        "compiled_at": got.get("compiled_at"),
        "receipt": got.get("receipt") or {},
        "checked": got.get("checked") or {},
        "problem": "" if got["verdict"] != "unknown" else why,
    }


def state(project_root: Path | str, *, store: Any = None) -> dict[str, Any]:
    """`anchor_check` 的别名：名字直说它不执行任何东西（只读角色走这条）。"""
    return anchor_check(project_root, store=store)




def build(project_root: Path | str, *, render_script: str = DEFAULT_RENDER_SCRIPT,
          compile_script: str = DEFAULT_COMPILE_SCRIPT,
          timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> dict[str, Any]:
    """从源重编一次论文包，并核对渲染锚。顺序是判据的一部分（见模块 docstring）。

    顺序：渲染 → 编译 → 再渲染（把锚挪到新 PDF 上）→ 核对。
    任何一步失败/超时 ⇒ `ok=False` 并指出是哪一步，绝不假装走完了。
    """
    root = Path(project_root)
    steps: list[dict[str, Any]] = []

    first = render(root, script=render_script, timeout_sec=timeout_sec)
    steps.append({"step": "render", **first})
    if not first["ok"]:
        return _failed("render", steps, root)

    built = compile_pdf(root, script=compile_script, timeout_sec=timeout_sec)
    steps.append({"step": "compile", **built})
    if not built["ok"]:
        return _failed("compile", steps, root)

    # 三步就够：判据搬进 `renderanchor` 并加上编译回执之后，"PDF 是不是从磁盘上
    # 这份 tex 编的"由回执那一维回答（`receipt`），不再需要"再渲染一次把锚挪过去"。
    checked = anchor_check(root)
    # 每一步的形状必须一致（都有 `ok`）：`anchor_check` 的返回值里没有 `ok` 键，
    # 直接塞进来会让读 `steps[*]["ok"]` 的调用方在第四步上 KeyError ——
    # 这是真机读数抓到的（脚本按步打印读数时崩在最后一步）。
    steps.append({"step": "anchor_check", "ok": checked["verdict"] == "consistent", **checked})
    pdf = root / "out" / "paper" / "main.pdf"
    return {
        "ok": checked["verdict"] == "consistent",
        "anchor": {k: checked[k] for k in ("verdict", "dimensions", "drift", "problems", "why",
                                           "anchor_path", "anchor_present", "receipt_path",
                                           "receipt_present", "anchor_sha256", "rendered_at",
                                           "compiled_at")},
        "pdf_path": str(pdf),
        "pdf_sha256": _file_digest(pdf),
        "pdf_bytes": pdf.stat().st_size if pdf.is_file() else 0,
        "pdf_pages": (built.get("result") or {}).get("pages"),
        "markers_missing": (built.get("result") or {}).get("markers_missing"),
        "compiler_exit_codes": (built.get("result") or {}).get("compiler_exit_codes"),
        "receipt": checked.get("receipt") or {},
        "steps": steps,
        "problem": ("" if checked["verdict"] == "consistent" else
                    f"锚没到 0 漂移（{checked['verdict']}）：{checked['why']}"),
    }


def _failed(step: str, steps: list[dict[str, Any]], root: Path) -> dict[str, Any]:
    """某一步没走成：如实指出是哪一步，其余读数留空（不编）。"""
    return {
        "ok": False,
        "anchor": {},
        "pdf_path": str(root / "out" / "paper" / "main.pdf"),
        "pdf_sha256": "",
        "pdf_bytes": 0,
        "pdf_pages": None,
        "markers_missing": None,
        "compiler_exit_codes": None,
        "receipt": {},
        "steps": steps,
        "problem": f"{step} 这一步没走成 ⇒ 后面的步骤没有跑（没查成，不是通过）",
    }


def selftest() -> int:
    """自检（离线、临时目录里造一个假项目）：跑脚本 / 越界拒绝 / 缺结论行 / 三态 / 三步。

    假项目的渲染与编译脚本自己调用 `agentflow.renderanchor` 写锚与回执 ——
    与真项目脚本走同一条路（判据只有一份实现，夹具也不另写一份）。
    """
    import tempfile

    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="paperbuild-selftest-") as td:
        root = Path(td) / "proj"
        (root / "code").mkdir(parents=True)
        (root / "out" / "paper").mkdir(parents=True)
        src = str(Path(__file__).resolve().parents[1])

        # 假渲染脚本：写 tex + 锚（真项目 `make_paper.py` 的契约）
        (root / "code" / "r.py").write_text(
            "import json, pathlib, sys\n"
            f"sys.path.insert(0, {src!r})\n"
            "from agentflow import renderanchor as RA\n"
            "from agentflow.store import Store\n"
            "root = pathlib.Path('.')\n"
            "out = root / 'out' / 'paper'\n"
            "out.mkdir(parents=True, exist_ok=True)\n"
            "(out / 'main.tex').write_text(chr(10).join(['\\\\date{2026-01-01}', 'body'])"
            " + chr(10), encoding='utf-8')\n"
            "st = Store(root); st.init(force=True)\n"
            "(out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)),"
            " encoding='utf-8')\n"
            "print('REPRO_RESULT: ' + json.dumps({'claims': 3}))\n",
            encoding="utf-8")
        # 假编译脚本：写 PDF + 回执
        (root / "code" / "c.py").write_text(
            "import json, pathlib, sys\n"
            f"sys.path.insert(0, {src!r})\n"
            "from agentflow import renderanchor as RA\n"
            "out = pathlib.Path('out/paper')\n"
            "(out / 'main.pdf').write_bytes(b'%PDF-1.4 fake')\n"
            "rec = RA.build_receipt(out, tex_sha256=RA.file_digest(out / 'main.tex'),"
            " pages=3, markers_missing=[], pdf_bytes=13, compiler_exit_codes=[0])\n"
            "(out / RA.RECEIPT_NAME).write_text(json.dumps(rec), encoding='utf-8')\n"
            "print('REPRO_RESULT: ' + json.dumps({'ok': True, 'pages': 3}))\n",
            encoding="utf-8")

        got = render(root, script="code/r.py", timeout_sec=60)
        if not got["ok"] or got["repro_found"] is not True:
            problems.append(f"渲染脚本没跑成：{got}")

        outside = run_script(root, "../../etc/passwd")
        if outside["exit_code"] is not None or "跑出项目根" not in outside["problem"]:
            problems.append(f"越界脚本没被拒：{outside}")

        absolute = run_script(root, str(root / "code" / "r.py"))
        if absolute["exit_code"] is not None or "绝对路径" not in absolute["problem"]:
            problems.append(f"绝对路径没被拒：{absolute}")

        missing = run_script(root, "code/nope.py")
        if missing["exit_code"] is not None or "不在盘上" not in missing["problem"]:
            problems.append(f"不存在的脚本没被拒：{missing}")

        (root / "code" / "silent.py").write_text("print('没有结论行')\n", encoding="utf-8")
        silent = run_script(root, "code/silent.py")
        if silent["repro_found"] or silent["ok"]:
            problems.append(f"没有结论行却判了通过：{silent}")

        # `--check` 脚本的三态（`doc.paper_anchor` 走这条）
        for code, want in ((0, "consistent"), (1, "drifted"), (2, "unknown")):
            name = f"c{code}.py"
            body = ("import sys\n"
                    "print('[anchor] 渲染时刻 X；锚覆盖 1 个文件')\n"
                    + ("" if code == 0 else
                       "print('    - 文件 main.tex：内容与渲染时不同')\n")
                    + (f"sys.exit({code})\n"))
            (root / "code" / name).write_text(body, encoding="utf-8")
            seen = anchor_check_script(root, script=f"code/{name}", timeout_sec=60)
            if seen["verdict"] != want:
                problems.append(f"退出码 {code} 翻成了 {seen['verdict']}（期望 {want}）")
            if code == 1 and not seen["drift"]:
                problems.append(f"漂移行没解析出来：{seen['stdout_tail']!r}")
            if code == 0 and seen["drift"]:
                problems.append(f"一致时不该有漂移行：{seen['drift']}")

        # 矛盾输入：退出码 0 却打了漂移行 ⇒ 必须判「没查成」，不许挑一个信
        (root / "code" / "liar.py").write_text(
            "import sys\n"
            "print('    - 文件 main.tex：内容与渲染时不同')\n"
            "sys.exit(0)\n", encoding="utf-8")
        liar = anchor_check_script(root, script="code/liar.py", timeout_sec=60)
        if liar["verdict"] != "unknown" or "矛盾" not in liar["why"]:
            problems.append(f"退出码与输出打架时没判「没查成」：{liar}")

        # ---- 进程内三维（`anchor_check` / `state`：只读角色走这条）
        fresh = Path(td) / "fresh"
        (fresh / "out" / "paper").mkdir(parents=True)
        seen = anchor_check(fresh)
        if seen["verdict"] != "unknown" or seen["source"] != "in_process":
            problems.append(f"没有锚时没判 unknown：{seen}")
        if state(fresh)["verdict"] != "unknown":
            problems.append("state() 与 anchor_check() 结论不一致（它们必须是同一条判据）")

        # ---- 三步序列：渲染 → 编译 → 核对
        done = build(root, render_script="code/r.py", compile_script="code/c.py", timeout_sec=60)
        names = [s["step"] for s in done["steps"]]
        if names != ["render", "compile", "anchor_check"]:
            problems.append(f"步骤不是三步：{names}")
        if not done["ok"] or done["anchor"]["verdict"] != "consistent":
            problems.append(f"三步跑完没到 0 漂移：{done['problem']} {done['anchor']}")
        if not done["receipt"].get("tex_sha256"):
            problems.append(f"没带出编译回执：{done['receipt']}")

        # 编译之后改 tex ⇒ 回执那一维必须报「旧 tex」
        (root / "out" / "paper" / "main.tex").write_text(
            "\\date{2026-01-01}" + "\n" + "body changed" + "\n", encoding="utf-8")
        stale = anchor_check(root)
        if stale["dimensions"]["receipt"] != "drifted":
            problems.append(f"旧 tex 没被判出来：{stale['dimensions']} {stale['drift']}")

        # 编译脚本失败 ⇒ 停在 compile
        (root / "code" / "bad.py").write_text("import sys\nprint('炸')\nsys.exit(1)\n",
                                              encoding="utf-8")
        stopped = build(root, render_script="code/r.py", compile_script="code/bad.py",
                        timeout_sec=60)
        if stopped["ok"] or [s["step"] for s in stopped["steps"]] != ["render", "compile"]:
            problems.append(f"编译失败没停在 compile：{stopped['steps']}")

    if problems:
        print("SELF-CHECK FAILED")
        for p in problems:
            print("  -", p)
        return 1
    print("SELF-CHECK DONE（脚本三态 / 进程内三维 / 三步序列 / 旧 tex / 失败即停）")
    return 0


if __name__ == "__main__":
    sys.exit(selftest())
