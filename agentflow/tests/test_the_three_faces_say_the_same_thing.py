# -*- coding: utf-8 -*-
"""判据：提示词 × 动作面 × 工具面在三处说同一件事（2026-11-10 审计的 11 条收口）。

## 这一条守的是哪五格（每格都"改前红、改后绿"）

| 格 | 改前（红在哪） | 改后（这一条读什么） |
|---|---|---|
| L1-1 | `specs/e.py` 说 `E.run_experiment` 有 `proof_manuscript`，动作面/工具面都没有 ⇒ 参数门必拒 | 动作面拒收它，且题面改成「`run_experiment` 自己落、回执里的那一格」 |
| L1-2 | `specs/v.py` 说 `notes/…` 也收，而 `sign_carrier` 判 legacy、在册/未在册两支都必拒 | `notes/` 不可签，题面写「签的载体只认 `reports/{f,b,e}-proof-*`」 |
| L1-3 | `specs/b.py` 的 `proof_manuscript` 说明说 `notes/…` 可作手稿路径收录，指针支必拒 | 指针支说明只收 `reports/` 规范名，并点名 `notes/` 是 legacy |
| L3-1 | `fs.write` 说 A/B 在 `reports/` 下拒「三族」，保留表拒四族（含 `e-num`） | summary 的指针句 + `path` 说明里逐字点名四族，行为仍四族全拒 |
| L3-2 | `conductor.status_report` 声明 `side_effect="read"` 却写两份报告文件 | 声明 `write_local`，与同类的 `review.report` 同一取值 |

`L2-1…L2-6`（refs 的 `q:/c:`、citations 的 `eval:`、`## 证明` 三态、手稿族五档、
`table.search` 两列、签块身份三态）由 `temp/_audit_prompt_tool_consistency.py` 的
`audit_items.txt` 逐条给读数；这一条只把「能被断言钉死的五格」钉住。

## 为什么这五格值得一条判据

这五条的共同形态是「两处声明相反、而两侧都各自自洽」—— 单测、类型检查、lint 全绿，
只有模型照着一边去写、在另一边撞墙时才暴露。所以判据必须同时读「两处」：
题面（或 summary）一句 + 动作面 / 实现一次，缺任何一处都只是纸面通过。
"""
from __future__ import annotations

import pathlib
import tempfile

from agentflow import agent_prompts as AP
from agentflow import capabilities as C
from agentflow.conductor import calling_as
from agentflow.store import Store
from agentflow.tools import build_registry
from agentflow.tools.base import ParamError, validate_params

TASK = "审计用任务（判据）"


def _registry(root: pathlib.Path):
    store = Store(root / "ws")
    store.init()
    return build_registry(store=store, workspace_root=root / "ws").registry


def _prompt(role: str, registry, root: pathlib.Path) -> str:
    return AP.system_prompt(role, registry=registry, task=TASK,
                            workspace_root=str(root / "ws"))


def test_l1_1_e_has_no_proof_manuscript_parameter_and_the_prompt_points_at_the_receipt(
        tmp_path: pathlib.Path) -> None:
    """L1-1：`proof_manuscript` 不是 `run_experiment` 的入参（它是回执里的一格）。"""
    act = [a for a in C.CAPABILITIES["E"] if a.action == "run_experiment"][0]
    try:
        validate_params(act.params, {"claim": "x", "claim_key": "k",
                                     "script_path": "code/x.py",
                                     "proof_manuscript": "reports/e-proof-000001.md"})
    except ParamError:
        pass
    else:  # pragma: no cover - 改回「接受」时红在这里
        raise AssertionError("E.run_experiment 接受了 proof_manuscript —— "
                             "题面那句「那一格就是它」会重新变成可执行的动作")

    text = _prompt("E", _registry(tmp_path), tmp_path)
    assert "不是入参" in text, "E 的题面没写清 proof_manuscript 是回执格、不是入参"
    assert "自己落" in text, "E 的题面没说稿由 run_experiment 自己落"


def test_l1_2_v_only_signs_reports_carriers(tmp_path: pathlib.Path) -> None:
    """L1-2：`notes/` 是 legacy、不可签；题面写死「只认 reports/{f,b,e}-proof-*」。"""
    from agentflow import manuscriptfamily as MFAM

    assert MFAM.sign_carrier("notes/f-proof-000001.md")["ok"] is False
    assert MFAM.sign_carrier("reports/f-proof-000001.md")["ok"] is True
    text = _prompt("V", _registry(tmp_path), tmp_path)
    assert "签的载体只认" in text, "V 的题面还在说 notes/… 也收"
    assert "`notes/…` 收不了" in text, "V 的题面没写清 notes/ 为什么不行（legacy 档）"


def test_l1_3_b_pointer_branch_only_takes_reports(tmp_path: pathlib.Path) -> None:
    """L1-3：B 的 `proof_manuscript` 说明在两个分支上可收性相反 —— 指针支只收 reports/。"""
    act = [a for a in C.CAPABILITIES["B"] if a.action == "register_statement"][0]
    desc = str((act.params.get("properties") or {}).get("proof_manuscript", {})
               .get("description") or "")
    assert "指针支只收" in desc, "B 的说明没写「指针支只收 reports/ 规范名」这个前提"
    assert "legacy" in desc, "B 的说明没写清 notes/ 是 legacy 档、必拒"
    assert "`reports/…` / `notes/…`" not in desc, (
        "B 的说明还在把 reports/ 与 notes/ 并列成合法入口")


def _fs_write_faces(reg) -> tuple[str, str]:
    """`fs.write` 的两面：summary（指针句）与 `path` 参数说明（矩阵本体）。"""
    spec = reg.get("fs.write")
    props = spec.params.get("properties") or {}
    path_desc = str((props.get("path") or {}).get("description") or "")
    return str(spec.summary), path_desc


def fs_write_reserved_face_problems(summary: str, path_desc: str) -> list[str]:
    """L3-1 的双面判据：summary 指路 × `path` 说明里的四族矩阵本体。

    2026-11-17（CMP1）四族保留面矩阵从 `fs.write` 的 summary 搬进了 `path` 参数的
    description，summary 只留一句「各族另拒面见 `path` 说明」。判据跟着矩阵本体走，
    但两面都要核：只核矩阵不核指针 ⇒ 模型读 summary 时找不到路；只核指针不核
    矩阵 ⇒ 矩阵可以被清空而判据照样绿（纸面通过）。
    """
    problems: list[str] = []
    if "见 `path` 说明" not in summary:
        problems.append(
            "fs.write 的 summary 没把四族矩阵指给 `path` 说明 —— 指针句没了，"
            "这段保留面在工具面上就断了")
    for fam in ("f-proof-", "b-proof-", "e-proof-", "e-num-"):
        if f"`{fam}`" not in path_desc:
            problems.append(
                f"fs.write 的 `path` 说明没点名 A/B 拒写的 {fam!r}（保留表里有这一条）")
    if "四族" not in path_desc:
        problems.append(
            "fs.write 的 `path` 说明没把 A/B 的拒写面写成「四族」—— 逐名但不计数，"
            "读起来仍像可以随便挑一族")
    if "这三族" in summary or "这三族" in path_desc:
        problems.append("fs.write 还在说「三族」—— 矩阵少算一族")
    return problems


def test_l3_1_fs_write_names_the_four_reserved_families(tmp_path: pathlib.Path) -> None:
    """L3-1：`fs.write` 的 summary 指路、`path` 说明里点名四族，与保留表逐字一致。

    CMP1 把矩阵搬进 `path` 之后，这条判据不再在 summary 里找四族，而是核
    「summary 的指针句确实指向 path」＋「path 说明里的矩阵本体四族逐名且计作四族」，
    行为面照旧四族全拒。两面任缺一面都只是纸面通过。
    """
    root = tmp_path
    reg = _registry(root)
    summary, path_desc = _fs_write_faces(reg)
    problems = fs_write_reserved_face_problems(summary, path_desc)
    assert problems == [], "fs.write 的 summary 与 `path` 说明说的不是同一件事：\n  " + \
        "\n  ".join(problems)

    for fam in ("f-proof", "b-proof", "e-proof", "e-num"):
        with calling_as("t-l31", "B"):
            got = reg.call("fs.write", role="B", path=f"reports/{fam}-000001.md",
                           content="x", overwrite=True)
        assert got.ok is False, f"B 写 reports/{fam}-000001.md 没被拒（与声明面相反）"


def test_negative_control_l3_1_deleting_the_matrix_from_path_goes_red(
        tmp_path: pathlib.Path) -> None:
    """负控（L3-1）：把 `path` 说明里的矩阵删掉 ⇒ ② 必红；删指针句 / 改回三族同样红。

    这条负控盯的是「判据有没有跟着矩阵搬家」：矩阵搬进 `path` 之后，若判据还在
    summary 里找四族，那么把 `path` 的矩阵整段删掉它照样绿 —— 那就是纸面通过。
    """
    reg = _registry(tmp_path)
    summary, path_desc = _fs_write_faces(reg)
    # 反负控：原样那一份不许被误判
    assert fs_write_reserved_face_problems(summary, path_desc) == []

    # (a) 矩阵整段删掉（只留路径语义）⇒ 必红
    matrix_gone = "相对工作区根的路径。"
    problems = fs_write_reserved_face_problems(summary, matrix_gone)
    assert problems, "把 `path` 说明里的四族矩阵删掉而判据没红 ⇒ 它没在看新落点"
    assert any("f-proof-" in p for p in problems), problems

    # (b) summary 的指针句删掉 ⇒ 必红（否则「指路」这句话没人验）
    pointer = "各族另拒面见 `path` 说明。"
    assert pointer in summary, "夹具前提：summary 里真有那句指针"
    assert fs_write_reserved_face_problems(summary.replace(pointer, ""), path_desc), (
        "summary 丢了指针句而判据没红 ⇒ 模型读 summary 时找不到矩阵")

    # (c) 矩阵改回「三族」⇒ 必红（逐名与计数必须同时对上）
    assert "四族" in path_desc, "夹具前提：矩阵里写着「四族」"
    assert fs_write_reserved_face_problems(summary, path_desc.replace("四族", "三族")), (
        "矩阵写成「三族」而判据没红 ⇒ 它只数名字、不数族数")

    # (d) 旧写法「这三族」重新出现（summary 或 path 任一面）⇒ 必红
    assert fs_write_reserved_face_problems(summary + "这三族", path_desc)
    assert fs_write_reserved_face_problems(summary, path_desc + "这三族")


def test_l3_2_status_report_declares_the_write_it_does(tmp_path: pathlib.Path) -> None:
    """L3-2：写两份报告文件的 `conductor.status_report` 必须声明 `write_local`。"""
    reg = _registry(tmp_path)
    assert str(reg.get("conductor.status_report").side_effect) == "write_local"
    assert str(reg.get("review.report").side_effect) == "write_local", (
        "同类工具 review.report 已经是 write_local；这条判据的对照物丢了")


def test_l2_5_table_search_teaches_the_two_statement_columns(tmp_path: pathlib.Path) -> None:
    """L2-5：`table.search` 在 statements 上只搜 label / statement_full，渲染行要能读到。"""
    reg = _registry(tmp_path)
    summary = str(reg.get("table.search").summary)
    assert "`label`" in summary and "`statement_full`" in summary, (
        "table.search 的渲染行没点名 statements 的两列 ⇒ 模型只能按「内容面」猜")
