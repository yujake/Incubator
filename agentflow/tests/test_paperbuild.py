"""论文包工具（`paperbuild` + `doc.paper_*`）的判据（`draft/28` §188，§191 之后对齐）。

## 这一组守什么

1. 受限地起子进程：项目根与脚本路径都必须落在工作区内（这一层起的是子进程，
   工具层按 `exec` 声明它）；
2. 结论必须能从脚本读回来：`REPRO_RESULT: {json}` 是契约，原始退出码一字不改；
3. 三态不许折平：脚本版核对（`anchor_check_script`，`doc.paper_anchor` 走它）
   0 一致 / 1 漂移 / 2 没查成；进程内版（`anchor_check`/`state`，`doc.paper_state` 走它）
   用三维结论 —— 后者的判据在 `tests/test_renderanchor.py` 里。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import paperbuild as PB
from agentflow import renderanchor as RA
from agentflow.store import Store
from agentflow.tools import build_registry

_SRC = str(pathlib.Path(RA.__file__).resolve().parents[1])


def _write(path: pathlib.Path, body: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


#: 假渲染脚本：写 `main.tex` + 渲染锚（真项目 `make_paper.py` 的契约）。
_RENDER = (
    "import json, pathlib, sys\n"
    f"sys.path.insert(0, {_SRC!r})\n"
    "from agentflow import renderanchor as RA\n"
    "from agentflow.store import Store\n"
    "root = pathlib.Path('.')\n"
    "out = root / 'out' / 'paper'\n"
    "out.mkdir(parents=True, exist_ok=True)\n"
    "lines = ['\\date{2026-01-01}', '正文']\n"
    "(out / 'main.tex').write_text(chr(10).join(lines) + chr(10), encoding='utf-8')\n"
    "st = Store(root)\n"
    "st.init(force=True)\n"
    "(out / RA.ANCHOR_NAME).write_text(json.dumps(RA.build_anchor(st, out)), encoding='utf-8')\n"
)


def _render_body(result_ok: bool = True) -> str:
    """渲染脚本正文（带结论行）。"""
    return _RENDER + (
        "print('REPRO_RESULT: ' + json.dumps({'claims': 24, 'ok': " + repr(result_ok) + "}))\n")


def _compile_body(*, result_ok: bool = True, exit_code: int = 0) -> str:
    """假编译脚本：写 PDF + 编译回执（真项目 `compile_paper.py` 的契约）。"""
    return (
        "import json, pathlib, sys\n"
        f"sys.path.insert(0, {_SRC!r})\n"
        "from agentflow import renderanchor as RA\n"
        "out = pathlib.Path('out/paper')\n"
        "(out / 'main.pdf').write_bytes(b'%PDF-1.4 fake')\n"
        "rec = RA.build_receipt(out, tex_sha256=RA.file_digest(out / 'main.tex'), pages=21,\n"
        "                       markers_missing=[], pdf_bytes=13,\n"
        f"                       compiler_exit_codes=[{exit_code}])\n"
        "(out / RA.RECEIPT_NAME).write_text(json.dumps(rec), encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': " + repr(result_ok) + ", 'pages': 21,\n"
        "      'markers_missing': [], 'pdf': 'main.pdf', 'pdf_bytes': 13, 'pdf_header': '%PDF-',\n"
        "      'text_extractor': 'stub', 'runs': [], 'compiler_exit_codes': [" + str(exit_code) + "],\n"
        "      'log_tail': 'stub', 'note': '夹具'}))\n"
        f"sys.exit({exit_code})\n")


def _make_project(root: pathlib.Path, *, check_exit: int = 0, check_drift: bool = False,
                  compile_ok: bool = True, compile_exit: int = 0) -> pathlib.Path:
    """造一个假论文包项目：渲染 / 编译 / 查锚（`--check` 那个分支）三个脚本。"""
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "code" / "make_paper.py", _render_body())
    _write(root / "code" / "compile_paper.py", _compile_body(result_ok=compile_ok,
                                                              exit_code=compile_exit))
    drift = ("print('    - 文件 main.tex：内容与渲染时不同')\n" if check_drift else "")
    _write(root / "code" / "check.py", (
        "import sys\n"
        "print('[anchor] 渲染时刻 X；锚覆盖 1 个源文件、1 张源表')\n"
        + drift
        + f"sys.exit({check_exit})\n"))
    return root


# ============================================================ 跑脚本


def test_run_script_reads_back_the_repro_result(tmp_path: pathlib.Path):
    """正控：脚本的结论行与原始退出码都能读回来（`result` 是脚本自己的 JSON）。"""
    root = _make_project(tmp_path / "proj")
    got = PB.render(root, script="code/make_paper.py", timeout_sec=60)
    assert got["ok"] and got["repro_found"], got
    assert got["exit_code"] == 0, got
    assert got["result"] == {"claims": 24, "ok": True}, got["result"]
    assert (root / "out" / "paper" / RA.ANCHOR_NAME).is_file()


def test_run_script_takes_the_last_repro_line(tmp_path: pathlib.Path):
    """边界：脚本可能先打中间读数再给结论 ⇒ 必须取最后一行，不许取第一行。"""
    root = tmp_path / "proj"
    _write(root / "code" / "two.py", (
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': False, 'which': 'first'}))\n"
        "print('中间的日志')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': True, 'which': 'last'}))\n"))
    got = PB.run_script(root, "code/two.py", timeout_sec=60)
    assert got["result"]["which"] == "last", got


def test_a_script_outside_the_project_is_refused(tmp_path: pathlib.Path):
    """负控（越界）：`..` 跳出项目根、绝对路径，一律拒 —— 这一层起的是子进程。"""
    root = _make_project(tmp_path / "proj")
    outside = PB.run_script(root, "../escape.py")
    assert outside["exit_code"] is None and "跑出项目根" in outside["problem"], outside
    absolute = PB.run_script(root, str(root / "code" / "make_paper.py"))
    assert absolute["exit_code"] is None and "绝对路径" in absolute["problem"], absolute


def test_resolve_script_answers_with_a_path_or_a_reason(tmp_path: pathlib.Path):
    """判据（越界判据本身）：`resolve_script` 只回两种东西 —— 真路径，或一句为什么。"""
    root = _make_project(tmp_path / "proj")
    ok_path, why = PB.resolve_script(root, "code/make_paper.py")
    assert ok_path is not None and why == "" and ok_path.is_file(), (ok_path, why)
    for bad, want in (("", "不能为空"), (str(tmp_path / "abs.py"), "绝对路径"),
                      ("../x.py", "跑出项目根"), ("code/none.py", "不在盘上")):
        path, reason = PB.resolve_script(root, bad)
        assert path is None and want in reason, (bad, path, reason)


def test_a_script_without_a_result_line_is_not_checked(tmp_path: pathlib.Path):
    """负控（三态）：脚本没打结论行 ⇒ `repro_found=False` + `ok=False`（没查成，不是通过）。"""
    root = tmp_path / "proj"
    _write(root / "code" / "silent.py", "print('我什么都没说')\n")
    got = PB.run_script(root, "code/silent.py", timeout_sec=60)
    assert got["repro_found"] is False and got["ok"] is False, got
    assert "REPRO_RESULT" in got["problem"], got


def test_a_timeout_is_not_checked_not_failed(tmp_path: pathlib.Path):
    """负控（超时）：跑不完 ⇒ `timed_out=True`、退出码为 None（不是"跑失败了"）。"""
    root = tmp_path / "proj"
    _write(root / "code" / "slow.py", "import time\ntime.sleep(30)\n")
    got = PB.run_script(root, "code/slow.py", timeout_sec=1)
    assert got["timed_out"] is True and got["exit_code"] is None and not got["ok"], got
    assert "超时" in got["problem"], got


def test_a_result_line_without_an_ok_key_still_counts_as_done(tmp_path: pathlib.Path):
    """正控（真机契约）：结论行里没有 `ok` 键时，退出码 0 就是"走成了"。

    `make_paper.py` 的结论行只有 `{"claims":…}`（没有 `ok`），`compile_paper.py` 有。
    第一版要求 `result["ok"]` ⇒ 明明跑成功的渲染被判成"没走成"（真机读数抓到的）。
    """
    root = tmp_path / "proj"
    _write(root / "code" / "no_ok.py",
           "import json\nprint('REPRO_RESULT: ' + json.dumps({'claims': 24}))\n")
    got = PB.run_script(root, "code/no_ok.py", timeout_sec=60)
    assert got["ok"] is True and got["repro_found"] is True and got["problem"] == "", got


def test_an_explicit_ok_false_with_exit_zero_is_not_done(tmp_path: pathlib.Path):
    """负控（信号矛盾）：退出码 0 但结论行里写着 `ok=false` ⇒ 不认成功，且说明理由。"""
    root = tmp_path / "proj"
    _write(root / "code" / "liar.py",
           "import json\nprint('REPRO_RESULT: ' + json.dumps({'ok': False, 'why': '没写出 PDF'}))\n")
    got = PB.run_script(root, "code/liar.py", timeout_sec=60)
    assert got["ok"] is False and "ok=false" in got["problem"], got


def test_a_nonzero_exit_code_keeps_the_result_and_the_code(tmp_path: pathlib.Path):
    """负控（退出码非 0）：结论行照读、退出码照留，但这一步不算走成。"""
    root = tmp_path / "proj"
    _write(root / "code" / "bad.py",
           "import json, sys\nprint('REPRO_RESULT: ' + json.dumps({'pages': 0}))\nsys.exit(3)\n")
    got = PB.run_script(root, "code/bad.py", timeout_sec=60)
    assert got["ok"] is False and got["exit_code"] == 3 and got["result"] == {"pages": 0}, got
    assert "退出码 3" in got["problem"], got


# ============================================================ 脚本版三态（doc.paper_anchor 走它）


@pytest.mark.parametrize(("exit_code", "verdict"), [(0, "consistent"), (1, "drifted"),
                                                    (2, "unknown")])
def test_anchor_check_script_maps_the_three_exit_codes(tmp_path: pathlib.Path, exit_code: int,
                                                       verdict: str):
    """正控（三态，脚本那一路）：0 一致 / 1 漂移 / 2 没查成，逐个钉住。"""
    root = _make_project(tmp_path / "proj", check_exit=exit_code, check_drift=(exit_code == 1))
    got = PB.anchor_check_script(root, script="code/check.py", timeout_sec=60)
    assert got["verdict"] == verdict, got
    assert got["expected_exit_code"] == exit_code, got
    if exit_code == 1:
        assert got["drift"] and "main.tex" in got["drift"][0], got
    else:
        assert got["drift"] == [], got


def test_a_contradictory_anchor_check_script_is_not_checked(tmp_path: pathlib.Path):
    """负控（矛盾）：退出码 0 却打了漂移行 ⇒ 判 `unknown`（两个信号打架时不挑一个信）。"""
    root = _make_project(tmp_path / "proj", check_exit=0, check_drift=True)
    got = PB.anchor_check_script(root, script="code/check.py", timeout_sec=60)
    assert got["verdict"] == "unknown" and "矛盾" in got["why"], got


# ============================================================ 三步序列与工具面


def test_build_stops_at_the_step_that_failed(tmp_path: pathlib.Path):
    """负控（不许假装走完）：编译脚本失败 ⇒ 只跑到 compile，`problem` 指出是哪一步。"""
    root = _make_project(tmp_path / "proj", compile_ok=False, compile_exit=1)
    got = PB.build(root, render_script="code/make_paper.py",
                   compile_script="code/compile_paper.py", timeout_sec=60)
    assert got["ok"] is False, got
    assert [s["step"] for s in got["steps"]] == ["render", "compile"], got["steps"]
    assert "compile" in got["problem"], got["problem"]


def _registry(tmp_path: pathlib.Path):
    """绑定 G 的注册表（`doc.paper_*` 的写侧只挂给 G）。"""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    built = build_registry(store=st, workspace_root=ws, roles=("G", "H"), strict=True)
    built.registry.bound_role = "G"
    return built.registry, ws


def test_the_paper_tools_are_exec_tools_for_the_writer_only(tmp_path: pathlib.Path):
    """判据（权限面）：四件 `exec` 只给 G；`doc.paper_state` 是 `read`，G 与 H 都有。"""
    registry, _ws = _registry(tmp_path)
    names = sorted(n for n in registry.names() if n.startswith("doc.paper"))
    assert names == ["doc.paper_anchor", "doc.paper_build", "doc.paper_compile",
                     "doc.paper_render", "doc.paper_state"], names
    for name in ("doc.paper_render", "doc.paper_compile", "doc.paper_build", "doc.paper_anchor"):
        spec = registry.get(name)
        assert spec.external == "exec" and spec.needs_approval is True, (name, spec.external)
        assert spec.roles == ("G",), (name, spec.roles)
    state = registry.get("doc.paper_state")
    assert state.external == "none" and state.roles == ("G", "H"), (state.external, state.roles)
    g_surface = [s.name for s in registry.for_role("G") if s.name.startswith("doc.paper")]
    h_surface = [s.name for s in registry.for_role("H") if s.name.startswith("doc.paper")]
    assert len(g_surface) == 5 and h_surface == ["doc.paper_state"], (g_surface, h_surface)


def test_paper_build_tool_reports_a_clean_rebuild(tmp_path: pathlib.Path):
    """正控（工具面）：`doc.paper_build` 在假项目上跑到 0 漂移，三步齐全。"""
    registry, ws = _registry(tmp_path)
    _make_project(ws / "projects" / "p9", check_exit=0)
    res = registry.call("doc.paper_build", project="projects/p9", timeout_sec=60,
                        render_script="code/make_paper.py", compile_script="code/compile_paper.py")
    assert res.ok, (res.error, res.meta)
    data = res.unwrap()
    assert data["ok"] is True and data["anchor"]["verdict"] == "consistent", data
    assert data["pdf_pages"] == 21 and data["pdf_sha256"], data
    assert data["receipt"].get("tex_sha256"), data["receipt"]


def test_paper_anchor_tool_separates_drift_from_not_checked(tmp_path: pathlib.Path):
    """负控（三态进工具层）：漂移与"没查成"的 `kind` 必须不同 —— 否则下游分不出。"""
    registry, ws = _registry(tmp_path)
    _make_project(ws / "projects" / "p9", check_exit=1, check_drift=True)
    res = registry.call("doc.paper_anchor", project="projects/p9", timeout_sec=60,
                        script="code/check.py")
    assert not res.ok and res.meta.get("kind") == "paper_anchor_drifted", res.meta
    _make_project(ws / "projects" / "p10", check_exit=2)
    res2 = registry.call("doc.paper_anchor", project="projects/p10", timeout_sec=60,
                         script="code/check.py")
    assert not res2.ok and res2.meta.get("kind") == "paper_anchor_unknown", res2.meta


def test_a_project_outside_the_workspace_is_refused(tmp_path: pathlib.Path):
    """负控（越界，工具层）：`project` 跳出工作区 ⇒ `kind=bad_project`，不起子进程。"""
    registry, _ws = _registry(tmp_path)
    for bad in ("../outside", str(tmp_path), "没有这个目录"):
        res = registry.call("doc.paper_build", project=bad, timeout_sec=60)
        assert not res.ok, (bad, res.data)
        assert res.meta.get("kind") == "bad_project", (bad, res.meta)


def test_the_paper_tools_are_visible_in_the_catalog(tmp_path: pathlib.Path):
    """判据（提示词面）：G 看到的目录里要有这五件 —— 看不见就等于没有。"""
    registry, _ws = _registry(tmp_path)
    catalog = registry.text_catalog(role="G")
    for name in ("doc.paper_render", "doc.paper_compile", "doc.paper_anchor", "doc.paper_build",
                 "doc.paper_state"):
        assert name in catalog, f"{name} 不在 G 的工具目录里"


def test_the_selftest_passes() -> None:
    """判据：模块自检必须过（它是 `python -m agentflow.paperbuild` 的内容）。"""
    assert PB.selftest() == 0


def test_the_build_reading_is_json_serializable(tmp_path: pathlib.Path):
    """判据（可审计）：`build` 的读数必须能原样序列化进报告（否则落盘会炸在下游）。"""
    root = _make_project(tmp_path / "proj", check_exit=0)
    got: dict[str, Any] = PB.build(root, render_script="code/make_paper.py",
                                   compile_script="code/compile_paper.py", timeout_sec=60)
    text = json.dumps(got, ensure_ascii=False)
    assert "anchor_check" in text and "receipt" in text, text[:200]
