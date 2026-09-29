"""论文包工具（`paperbuild` + `doc.paper_*`）的判据（`draft/28` §188）。

## 这一组守什么

`draft/28` §184.5 第 5 步要的是"把打包与核对暴露成工具"，而终点门槛 B 是
"由角色通过工具触发从源重编 main.pdf，且渲染锚 0 漂移"。这两句话把判据钉在三处：

1. 受限地起子进程：项目根与脚本路径都必须落在工作区内。这一层起的是子进程
   （`declared_external="exec"`），放宽等于把"跑什么、在哪跑"交给调用方；
2. 结论必须能从脚本读回来：脚本的 `REPRO_RESULT: {json}` 是契约，原始退出码
   一字不改地带出来 —— 本机 MiKTeX 会写完 PDF 却以 `0xC0000409` 退出，
   把那个码改写成"失败"或"成功"都是丢信息；
3. 三态不许折平：锚核对 0 一致 / 1 漂移 / 2 没查成；退出码与输出互相矛盾时
   判"没查成"（两个信号打架时不许挑一个信）。

全部离线：假项目在 `tmp_path` 里现造，脚本是会写文件、打结论行的几行 Python。
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from agentflow import paperbuild as PB
from agentflow.store import Store
from agentflow.tools import build_registry

# ============================================================ 假项目


def _write(path: pathlib.Path, body: str) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _fake_render_script(root: pathlib.Path, *, result_ok: bool = True) -> pathlib.Path:
    """假渲染脚本：写 `main.tex`（带日期行），再打一行结论。"""
    return _write(root / "code" / "make_paper.py", (
        "import json, pathlib, sys\n"
        "p = pathlib.Path('out/paper/main.tex')\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('\\\\date{2026-01-01}\\n正文\\n', encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': %r, 'claims': 24}))\n"
        % result_ok
    ))


def _fake_compile_script(root: pathlib.Path, *, result_ok: bool = True,
                         exit_code: int = 0) -> pathlib.Path:
    """假编译脚本：写一个 `main.pdf`（内容随便），再打一行结论。

    结论行的键集合照抄真脚本（`compile_paper.py` 的 result）：工具层的 `returns=`
    声明的是那份契约，夹具只给三个键的话，"声明了却没给"这条判据会以为工具在吹牛
    —— 实测撞过（`test_tools_returns_declaration` 报 `doc.paper_compile` 声明了一套、
    返回另一套）。夹具要么照契约给全，要么就别声明 —— 这里选择照契约给全。
    """
    keys = ("{'ok': " + repr(result_ok) + ", 'pdf': 'main.pdf', 'pdf_bytes': 13, "
            "'pdf_header': '%PDF-', 'pages': 21, 'text_extractor': 'stub', "
            "'markers_missing': [], 'runs': [{'pass': 1, 'exit_code': " + str(exit_code) + "}], "
            "'compiler_exit_codes': [" + str(exit_code) + "], 'log_tail': 'stub', "
            "'note': '夹具：不是真编译'}")
    body = (
        "import json, pathlib, sys\n"
        "p = pathlib.Path('out/paper/main.pdf')\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_bytes(b'%PDF-1.4 fake')\n"
        "print('REPRO_RESULT: ' + json.dumps(" + keys + "))\n"
        "sys.exit(" + str(exit_code) + ")\n"
    )
    return _write(root / "code" / "compile_paper.py", body)


def _make_project(root: pathlib.Path, *, check_exit: int = 0, check_drift: bool = False) -> pathlib.Path:
    """造一个最小的论文包项目：渲染 / 编译 / 查锚三个脚本。

    `check_drift` 默认 False：只有"有漂移"那几种用例才该打漂移行 —— 别的情况下打，
    脚本自己的两个信号（退出码与输出）就打架了，而那个形态有专门的用例在测。
    """
    root.mkdir(parents=True, exist_ok=True)
    _fake_render_script(root)
    _fake_compile_script(root)
    drift = ("    print('    - 文件 main.pdf：内容与渲染时不同')\n"
             if check_drift else "")
    # 查锚走的是同一个渲染脚本 + `--check`（与真实项目同形）
    _write(root / "code" / "make_paper.py", (
        "import json, pathlib, sys\n"
        "if '--check' in sys.argv:\n"
        "    print('[anchor] 渲染时刻 X；锚覆盖 1 个文件、1 张源表')\n"
        + drift
        + "    sys.exit(%d)\n" % check_exit
        + "p = pathlib.Path('out/paper/main.tex')\n"
        "p.parent.mkdir(parents=True, exist_ok=True)\n"
        "p.write_text('\\\\date{2026-01-01}\\n正文\\n', encoding='utf-8')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': True, 'claims': 24}))\n"
    ))
    return root


# ============================================================ paperbuild：跑脚本与三态


def test_run_script_reads_back_the_repro_result(tmp_path: pathlib.Path):
    """正控：脚本的结论行与原始退出码都能读回来（`result` 是脚本自己的 JSON）。"""
    root = _make_project(tmp_path / "proj")
    got = PB.render(root, timeout_sec=60)
    assert got["ok"] and got["repro_found"], got
    assert got["exit_code"] == 0, got
    assert got["result"] == {"ok": True, "claims": 24}, got["result"]
    assert (root / "out" / "paper" / "main.tex").is_file()


def test_run_script_takes_the_last_repro_line(tmp_path: pathlib.Path):
    """边界：脚本可能先打中间读数再给结论 ⇒ 必须取最后一行，不许取第一行。"""
    root = tmp_path / "proj"
    _write(root / "code" / "two.py", (
        "import json\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': False, 'which': 'first'}))\n"
        "print('中间的日志')\n"
        "print('REPRO_RESULT: ' + json.dumps({'ok': True, 'which': 'last'}))\n"
    ))
    got = PB.run_script(root, "code/two.py", timeout_sec=60)
    assert got["result"]["which"] == "last", got


def test_a_script_outside_the_project_is_refused(tmp_path: pathlib.Path):
    """负控（越界）：`..` 跳出项目根的脚本一律拒 —— 这一层起的是子进程。"""
    root = _make_project(tmp_path / "proj")
    outside = PB.run_script(root, "../escape.py")
    assert outside["exit_code"] is None and "跑出项目根" in outside["problem"], outside
    absolute = PB.run_script(root, str(root / "code" / "make_paper.py"))
    assert absolute["exit_code"] is None and "绝对路径" in absolute["problem"], absolute


def test_resolve_script_answers_with_a_path_or_a_reason(tmp_path: pathlib.Path):
    """判据（越界判据本身）：`resolve_script` 只回两种东西 —— 真路径，或一句为什么。

    为什么单独测它：它是"这一层到底允不允许起这个子进程"的唯一判据函数，而上面那些
    负控走的是 `run_script`（它把这个函数包成结构化结果）。判据函数自己没有直接判据时，
    它坏掉可能让负控"红在别的原因上"，看起来像查过了。
    """
    root = _make_project(tmp_path / "proj")
    ok_path, why = PB.resolve_script(root, "code/make_paper.py")
    assert ok_path is not None and why == "" and ok_path.is_file(), (ok_path, why)
    # 绝对路径这一条用 `tmp_path` 下的真绝对路径：`"/etc/passwd"` 在 Windows 上
    # `Path.is_absolute()` 是 False（没有盘符）⇒ 它走的是"跑出项目根"那一支，
    # 拿它测"绝对路径"这一档会得到一个平台相关的结论（第一版就是这么写错的）。
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
    """负控（超时）：跑不完 ⇒ `timed_out=True`、`ok=False`、退出码为 None（不是"跑失败了"）。"""
    root = tmp_path / "proj"
    _write(root / "code" / "slow.py", "import time\ntime.sleep(30)\n")
    got = PB.run_script(root, "code/slow.py", timeout_sec=1)
    assert got["timed_out"] is True and got["exit_code"] is None and not got["ok"], got
    assert "超时" in got["problem"], got


def test_a_result_line_without_an_ok_key_still_counts_as_done(tmp_path: pathlib.Path):
    """正控（真机契约）：结论行里没有 `ok` 键时，退出码 0 就是"走成了"。

    这条是从真机读数补回来的：`make_paper.py` 的结论行只有
    `{"claims":…, "render_anchor":…}`（没有 `ok`），而 `compile_paper.py` 有。
    第一版要求 `result["ok"]` ⇒ 明明跑成功的渲染被判成"没走成"。
    """
    root = tmp_path / "proj"
    _write(root / "code" / "no_ok.py",
           "import json\nprint('REPRO_RESULT: ' + json.dumps({'claims': 24}))\n")
    got = PB.run_script(root, "code/no_ok.py", timeout_sec=60)
    assert got["ok"] is True and got["repro_found"] is True, got
    assert got["problem"] == "", got


def test_an_explicit_ok_false_with_exit_zero_is_not_done(tmp_path: pathlib.Path):
    """负控（信号矛盾）：退出码 0 但结论行里写着 `ok=false` ⇒ 不认成功，且说明理由。"""
    root = tmp_path / "proj"
    _write(root / "code" / "liar.py",
           "import json\nprint('REPRO_RESULT: ' + json.dumps({'ok': False, 'why': 'PDF 没写出来'}))\n")
    got = PB.run_script(root, "code/liar.py", timeout_sec=60)
    assert got["ok"] is False and "ok=false" in got["problem"], got


def test_a_nonzero_exit_code_keeps_the_result_and_the_code(tmp_path: pathlib.Path):
    """负控（退出码非 0）：结论行照读、退出码照留，但这一步不算走成。"""
    root = tmp_path / "proj"
    _write(root / "code" / "bad.py",
           "import json, sys\nprint('REPRO_RESULT: ' + json.dumps({'pages': 0}))\nsys.exit(3)\n")
    got = PB.run_script(root, "code/bad.py", timeout_sec=60)
    assert got["ok"] is False and got["exit_code"] == 3, got
    assert got["result"] == {"pages": 0}, got
    assert "退出码 3" in got["problem"], got


@pytest.mark.parametrize(("exit_code", "verdict"), [(0, "consistent"), (1, "drifted"),
                                                    (2, "unknown")])
def test_anchor_check_maps_the_three_exit_codes(tmp_path: pathlib.Path, exit_code: int,
                                                verdict: str):
    """正控（三态）：0 一致 / 1 漂移 / 2 没查成，逐个钉住（漂移行要能解析出来）。"""
    root = _make_project(tmp_path / "proj", check_exit=exit_code, check_drift=(exit_code == 1))
    got = PB.anchor_check(root, timeout_sec=60)
    assert got["verdict"] == verdict, got
    assert got["expected_exit_code"] == exit_code, got
    if exit_code == 1:
        assert got["drift"] and "main.pdf" in got["drift"][0], got
    else:
        assert got["drift"] == [], got


def test_a_contradictory_anchor_check_is_not_checked(tmp_path: pathlib.Path):
    """负控（矛盾）：退出码 0 却打了漂移行 ⇒ 判 `unknown`（两个信号打架时不挑一个信）。"""
    root = _make_project(tmp_path / "proj", check_exit=0, check_drift=True)
    got = PB.anchor_check(root, timeout_sec=60)
    assert got["verdict"] == "unknown" and "矛盾" in got["why"], got


# ============================================================ paperbuild：序列


def test_build_runs_the_four_steps_in_order_and_ends_at_zero_drift(tmp_path: pathlib.Path):
    """正控（门槛 B 的形状）：渲染 → 编译 → 再渲染 → 查锚，四步齐全且最终 0 漂移。"""
    root = _make_project(tmp_path / "proj", check_exit=0)
    # 真项目里 `main.tex` 是上一轮渲染留下的：先造一份（与本次渲染只差日期行），
    # 否则"两次渲染是否相同"这个读数本来就"比不了" —— 那是另一条用例的事。
    _write(root / "out" / "paper" / "main.tex", "\\date{2025-12-31}\n正文\n")
    got = PB.build(root, timeout_sec=60)
    assert got["ok"] is True, got
    assert [s["step"] for s in got["steps"]] == ["render", "compile", "render_after_compile",
                                                 "anchor_check"], got["steps"]
    assert got["anchor"]["verdict"] == "consistent" and got["anchor"]["drift"] == [], got["anchor"]
    assert got["pdf_pages"] == 21 and got["pdf_bytes"] > 0, got
    assert got["tex_content_stable"] is True, got["tex_note"]
    # 每一步的形状必须一致：都能回答"这一步走成了没有"。
    # 少了这条断言，第四步（anchor_check）漏掉 `ok` 这种事在单测里看不见 ——
    # 而它是在真机上按步打印读数时炸出来的（KeyError: 'ok'）。
    for step in got["steps"]:
        assert isinstance(step.get("ok"), bool), step
        assert {"step", "ok", "exit_code"} <= set(step), sorted(step)


def test_build_on_a_fresh_project_cannot_compare_the_two_renders(tmp_path: pathlib.Path):
    """边界（三态）：项目里没有上一轮的 `main.tex` ⇒ "两次渲染相同"是"比不了"，
    不许写成"相同"（否则"没查"又被读成"查过了、没问题"）。"""
    root = _make_project(tmp_path / "proj", check_exit=0)
    got = PB.build(root, timeout_sec=60)
    assert got["ok"] is True, got
    assert got["tex_content_stable"] is False and "比不了" in got["tex_note"], got["tex_note"]


def test_build_stops_at_the_step_that_failed(tmp_path: pathlib.Path):
    """负控（不许假装走完）：编译脚本失败 ⇒ 只跑到 compile，`problem` 指出是哪一步。"""
    root = _make_project(tmp_path / "proj")
    _fake_compile_script(root, result_ok=False, exit_code=1)
    got = PB.build(root, timeout_sec=60)
    assert got["ok"] is False, got
    assert [s["step"] for s in got["steps"]] == ["render", "compile"], got["steps"]
    assert "compile" in got["problem"], got["problem"]


def test_tex_content_stable_ignores_only_the_date_line():
    """判据（这条读数的口径）：只有日期行不同 ⇒ 稳定；正文差一个字 ⇒ 不稳定。"""
    a = "\\date{2026-01-01}\n正文\n"
    b = "\\date{2026-09-29}\n正文\n"
    c = "\\date{2026-09-29}\n正文改了\n"
    assert PB.tex_content_stable(a, b)[0] is True, PB.tex_content_stable(a, b)
    assert PB.tex_content_stable(a, c)[0] is False, PB.tex_content_stable(a, c)
    assert PB.tex_content_stable(None, b)[0] is False, "读不到时要判「比不了」"


# ============================================================ 工具面


def _registry(tmp_path: pathlib.Path, *, root: pathlib.Path | None = None):
    ws = root or (tmp_path / "ws")
    ws.mkdir(parents=True, exist_ok=True)
    st = Store(ws)
    st.init()
    build = build_registry(store=st, workspace_root=ws, roles=("G", "H"), strict=True)
    # 绑定角色（`P-14`）：`doc.paper_*` 只挂给 G，不绑的话调用会被 `role_denied` 拒 ——
    # 那样测的就不是越界判据，而是"我没绑角色"。
    build.registry.bound_role = "G"
    return build.registry, ws


def test_the_paper_tools_are_exec_tools_for_the_writer_only(tmp_path: pathlib.Path):
    """判据（权限面）：四个工具声明 `exec` 且只挂给 G —— 只读角色拿不到（结构性剥离）。"""
    registry, _ws = _registry(tmp_path)
    names = [n for n in registry.names() if n.startswith("doc.paper")]
    assert sorted(names) == ["doc.paper_anchor", "doc.paper_build", "doc.paper_compile",
                             "doc.paper_render"], names
    for name in names:
        spec = registry.get(name)
        assert spec.external == "exec", (name, spec.external)
        assert spec.needs_approval is True, (name, "exec 工具必须走审批")
        assert spec.roles == ("G",), (name, spec.roles)
    h_surface = [s.name for s in registry.for_role("H")]
    assert not [n for n in h_surface if n.startswith("doc.paper")], h_surface


def test_paper_build_tool_reports_a_clean_rebuild(tmp_path: pathlib.Path):
    """正控（工具面）：`doc.paper_build` 在假项目上跑到 0 漂移，读数与模块层一致。"""
    registry, ws = _registry(tmp_path)
    _make_project(ws / "projects" / "p9", check_exit=0)
    res = registry.call("doc.paper_build", project="projects/p9", timeout_sec=60)
    assert res.ok, (res.error, res.meta)
    data = res.unwrap()
    assert data["ok"] is True and data["anchor"]["verdict"] == "consistent", data
    assert data["pdf_pages"] == 21, data
    assert data["pdf_sha256"], data


def test_paper_anchor_tool_separates_drift_from_not_checked(tmp_path: pathlib.Path):
    """负控（三态进工具层）：漂移与"没查成"的 `kind` 必须不同 —— 否则下游分不出。"""
    registry, ws = _registry(tmp_path)
    _make_project(ws / "projects" / "p9", check_exit=1)
    res = registry.call("doc.paper_anchor", project="projects/p9", timeout_sec=60)
    assert not res.ok and res.meta.get("kind") == "paper_anchor_drifted", res.meta
    _make_project(ws / "projects" / "p10", check_exit=2)
    res2 = registry.call("doc.paper_anchor", project="projects/p10", timeout_sec=60)
    assert not res2.ok and res2.meta.get("kind") == "paper_anchor_unknown", res2.meta


def test_a_project_outside_the_workspace_is_refused(tmp_path: pathlib.Path):
    """负控（越界，工具层）：`project` 跳出工作区 ⇒ `kind=bad_project`，不起子进程。"""
    registry, _ws = _registry(tmp_path)
    for bad in ("../outside", str(tmp_path), "没有这个目录"):
        res = registry.call("doc.paper_build", project=bad, timeout_sec=60)
        assert not res.ok, (bad, res.data)
        assert res.meta.get("kind") == "bad_project", (bad, res.meta)


def test_the_paper_tools_are_visible_in_the_catalog(tmp_path: pathlib.Path):
    """判据（提示词面）：G 看到的目录里要有这四个工具 —— 看不见就等于没有。"""
    registry, _ws = _registry(tmp_path)
    catalog = registry.text_catalog(role="G")
    for name in ("doc.paper_render", "doc.paper_compile", "doc.paper_anchor", "doc.paper_build"):
        assert name in catalog, f"{name} 不在 G 的工具目录里"


def test_the_selftest_passes() -> None:
    """判据：模块自检必须过（它是 `python -m agentflow.paperbuild` 的内容）。"""
    assert PB.selftest() == 0


def test_the_build_reading_is_json_serializable(tmp_path: pathlib.Path):
    """判据（可审计）：`build` 的读数必须能原样序列化进报告（否则落盘会炸在下游）。"""
    root = _make_project(tmp_path / "proj", check_exit=0)
    got: dict[str, Any] = PB.build(root, timeout_sec=60)
    text = json.dumps(got, ensure_ascii=False)
    assert "render_after_compile" in text, text[:200]
