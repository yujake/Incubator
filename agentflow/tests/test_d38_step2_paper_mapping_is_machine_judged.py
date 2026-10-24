# -*- coding: utf-8 -*-
"""D-38 第二步（2026-10-24）：论文对应表也进「机器可判」那一张表。

## 第一步之后还剩什么

bae5524 让收工门在「有命题、已成稿、而论文包里没有 MAPPING.json」时出 blocker
（`mapping_not_written`），也让 M 的人读验收表能写「未完成」。可机器可判那一张表
（`out/paper/ACCEPTANCE-CHECKS.json`）里没有对应的一档 ⇒ 同一条缺口在两张表上只能是
两句话，而收工门真正读的是机器可判那张（`closing.LEG_CHECK_KINDS` 里没有这一档，
写进去会被读成「词表外 kind」⇒ 整格 unknown）。

## 这一档的口径（`paper_mapping_rows`）

读数 = `out/paper/MAPPING.json` 里三格齐的行数（`file` 加数值定理的
`numeric_evidence` / `exhaustion_note`，或 Lean 的 `lean_file` / `lean_target`），分母 =
表里的行数。表不在盘上读 0（没产出）；表在而解析坏记「没查成」（不是 0）。

## 六条判据

| # | 判据 | 改前红在哪 |
|---|---|---|
| ① | 有 MAPPING 且三格齐 ⇒ 这一行 pass、machine_pass 不受影响 | 词表里没有这一档 ⇒ 那一行落 `acceptance_unknown_kind` |
| ② | 有 MAPPING 但三格不齐 ⇒ fail，并点名缺哪一格 | 同上：红的原因不是「不齐」 |
| ③ | 没有 MAPPING ⇒ fail，并点名 | 同上 |
| ④ | 老工作区缺这一行（那份 ACCEPTANCE-CHECKS.json 真的在盘上，只是没这一行）⇒ unknown、不判红，并在 problems 里点名 | 没有任何一档在说「缺这一行」：整格照样 pass，缺档静默 |
| ⑤ | 反真空：把三格判据打桩恒真 ⇒ ② 必红 | 改前没有那处判据可打桩（AttributeError ⇒ 红） |
| ⑥ | 反真空：把「缺档读 unknown」打桩成 pass ⇒ ④ 的反面必红 | 同上 |

⑦ 不在上面那六条里：它单独验 M 的读表工具（`conductor.acceptance`）对「缺失 / 记 na /
记未完成」三种形态都读得出来。六条判据在收工门那一侧，⑦ 在 M 那一侧。

夹具全部在 `tmp_path` 里自建（零模型调用）；真机工作区只在报告里以只读探针读一次，
不在判据里读。
"""
from __future__ import annotations

import json
import pathlib

import pytest

import paperfixture as FX
from agentflow import closing as CL
from agentflow import papercompile as PC
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import conductor_tools as CT

#: 这一档的受控档名（判据里写死字面量：这条判据钉的就是这个名字）。
LEG = "paper_mapping_rows"


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


#: 补一段参考文献：收工门的「论文要承载本轮结果」那一条要求 `\bibitem` 至少 2 条，
#: 而数值实验定理那份正文夹具只为「对应表」而生（没有参考文献）。它是在封 PDF 之前
#: 补的，所以回执仍然对得上盘上这份正文（先封后改 = 那一格会报 PDF 过期）。
_BIB = ("\\begin{thebibliography}{9}\n"
        "\\bibitem{r34} Radziszowski, Small Ramsey Numbers.\n"
        "\\bibitem{exh} E, exhaustion reading exp:000000.\n"
        "\\end{thebibliography}\n\n")


def _numeric_paper(tmp_path: pathlib.Path, *, patch: dict | None = None) -> pathlib.Path:
    """一个三格齐的合规论文包（可选地把某一格清空 ⇒ 不齐）。

    行与正文的夹具直接取 `test_numeric_theorem_writing_spec` 的那一份（同一个仓库里只留
    一份「合规数值实验定理」的形状）；成稿那一行取第一步判据文件的夹具（`documents`
    有行 = `doc.build_document` 成功过）。封 PDF 必须在写表之后：附录那一行
    `\\input{mapping-appendix}` 会让 `main.tex` 变长，先封后写 = 回执过期。
    """
    from test_d38_mapping_is_not_silently_missing import _document_row
    from test_numeric_theorem_writing_spec import _row as numeric_row
    from test_numeric_theorem_writing_spec import _workspace as numeric_workspace

    row = numeric_row(**(patch or {}))
    root = numeric_workspace(pathlib.Path(tmp_path) / "ws", rows=[row])
    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2, "rows": [_document_row()]})
    tex = root / "out" / "paper" / PC.TEX_NAME
    text = tex.read_text(encoding="utf-8")
    assert "\\end{document}" in text, text[:200]
    tex.write_bytes(text.replace("\\end{document}", _BIB + "\\end{document}", 1).encode("utf-8"))
    engine = FX.fake_engine(root / "_engine")
    with FX.use_engine(engine):
        PC.compile_paper(root)
    return root


def _ledger_workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """只有台账的工作区（有命题、已成稿，论文包整个不存在）。

    形态与第一步那两趟真机一致（`cube-ws` / `r34c`）：`out/paper` 里没有 MAPPING.json。
    """
    from test_d38_mapping_is_not_silently_missing import _document_row, _statement_row

    root = pathlib.Path(tmp_path) / "ws"
    store = Store(root)
    store.init(force=True)
    _dump(root / "data" / str(S.TABLES["statements"]["file"]),
          {"schema_version": 2, "rows": [_statement_row("000000")]})
    _dump(root / "data" / str(S.TABLES["documents"]["file"]),
          {"schema_version": 2, "rows": [_document_row()]})
    return root


def _checks(root: pathlib.Path, rows: list[dict]) -> pathlib.Path:
    """把机器可判的验收行写进项目（真实文件，不是打桩）。"""
    path = root / CL.ACCEPTANCE_CHECKS_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checks": rows}, ensure_ascii=False, indent=2),
                    encoding="utf-8", newline="\n")
    return path


def _gate(root: pathlib.Path, checks: tuple[str, ...] = ("acceptance",)):
    return CL.check_closing(Store(root), project_dir=str(root), checks=checks)


def _row_of(rep, kind: str = LEG) -> dict:
    """按 kind 取那一行（取不到 ⇒ 判据自己接错了，不是「通过」）。"""
    return next(r for r in rep.readings["acceptance"]["rows"]
                if str(r.get("kind") or "") == kind)


def _blocker_detail(rep) -> str:
    return "；".join(f.detail for f in rep.findings
                     if f.check == "acceptance" and f.level == "blocker")


# ============================================================ ① 三格齐 ⇒ pass


def test_1_a_written_mapping_with_the_three_cells_passes_this_row(tmp_path: pathlib.Path) -> None:
    """① 有 MAPPING 且三格齐 ⇒ 这一行 pass，且 machine_pass 不受影响。

    这一条盯三件：词表里有这一档；那一行真的按台账算出了 1（`state == computed`，
    不是 na/unreadable 混过去）；`paper` 与 `acceptance` 两格同时 pass、`machine_pass`
    仍是 True（新加的这一档不许把原本干净的交付读成 red）。
    """
    root = _numeric_paper(tmp_path)
    _checks(root, [{"id": "P12", "name": "论文对应表", "kind": LEG, "min": 1}])

    assert LEG in CL.LEG_CHECK_KINDS, sorted(CL.LEG_CHECK_KINDS)
    rep = _gate(root, ("paper", "acceptance"))
    row = _row_of(rep)
    assert row["state"] == "computed", row
    assert row["ok"] is True and row["got"] == 1, row
    assert row["detail"]["rows"] == 1 and row["detail"]["complete"] == 1, row
    assert row["detail"]["incomplete"] == [], row
    assert rep.readings["acceptance"]["rows_read"] == 1, rep.readings["acceptance"]
    assert rep.status["paper"] == "pass", rep.to_dict()
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert rep.machine_pass is True, rep.to_dict()
    assert not [f for f in rep.findings if f.code == "acceptance_unmet"], rep.findings


# ============================================================ ② 三格不齐 ⇒ 点名缺哪格


def test_2_an_incomplete_mapping_fails_and_names_the_missing_cell(tmp_path: pathlib.Path) -> None:
    """② 有 MAPPING 但三格不齐 ⇒ fail，并且点名缺的是哪一格（比 blocker 更细）。

    夹具把 `exhaustion_note` 清空：那一行仍然是数值实验定理（`numeric_evidence` 在 ⇒
    `papermapping.is_numeric_row` 为真），所以缺的就是第三格。断言落在三处：行读数
    （`incomplete[].missing`）、阈值（`got` 0 < 分母 1）、以及 blocker 正文里那句点名。
    """
    root = _numeric_paper(tmp_path, patch={"exhaustion_note": ""})
    _checks(root, [{"id": "P12", "name": "论文对应表", "kind": LEG, "min": 1}])

    rep = _gate(root)
    row = _row_of(rep)
    assert row["ok"] is False and row["got"] == 0, row
    assert row["min"] == 1, row
    assert row["detail"]["rows"] == 1 and row["detail"]["complete"] == 0, row
    assert [i["missing"] for i in row["detail"]["incomplete"]] == [["exhaustion_note"]], row
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    detail = _blocker_detail(rep)
    assert "exhaustion_note" in detail and "thm:r34" in detail, detail


# ============================================================ ③ 没有 MAPPING ⇒ 点名


def test_3_without_a_mapping_json_the_row_fails_and_names_the_file(tmp_path: pathlib.Path) -> None:
    """③ 没有 MAPPING ⇒ fail，并点名（0 行是读数，不是静默通过）。

    同一份工作区上再跑一次 `paper` 那一格：`mapping_not_written` 那条 blocker 必须
    照旧在、且只出现一次（两处同源，不重复报同一个理由码）。
    """
    root = _ledger_workspace(tmp_path)
    _checks(root, [{"id": "P1", "name": "手稿落盘", "kind": "document_rows", "min": 1},
                   {"id": "P12", "name": "论文对应表", "kind": LEG, "min": 1}])

    rep = _gate(root)
    row = _row_of(rep)
    assert row["ok"] is False and row["got"] == 0, row
    assert row["detail"]["exists"] is False, row
    assert row["detail"]["mapping_json"].endswith(PM.MAPPING_JSON_NAME), row
    assert rep.status["acceptance"] == "fail", rep.to_dict()
    detail = _blocker_detail(rep)
    assert PM.MAPPING_JSON_NAME in detail and "不在盘上" in detail, detail
    # 手稿那一行是满足的，不许被同一句话连坐
    assert _row_of(rep, "document_rows")["ok"] is True, rep.readings["acceptance"]["rows"]

    mapping_rep = _gate(root, ("paper",))
    codes = [f.code for f in mapping_rep.findings]
    assert codes.count("mapping_not_written") == 1, codes


# ============================================================ ④ 老工作区缺这一档 ⇒ unknown

def _old_workspace(tmp_path: pathlib.Path) -> pathlib.Path:
    """老工作区：真的有 ACCEPTANCE-CHECKS.json，只是里面没有 `paper_mapping_rows` 这一行。

    这一条必须是真夹具（判据文件不许打桩）：要求的正是「盘上那份文件里没有这一行」
    这个形态本身。
    """
    root = _ledger_workspace(tmp_path)
    _checks(root, [{"id": "P1", "name": "手稿落盘", "kind": "document_rows", "min": 1}])
    return root


def test_4_an_old_workspace_without_the_row_reads_unknown_and_is_not_red(
        tmp_path: pathlib.Path) -> None:
    """④ 兼容性：老工作区缺这一行 ⇒ unknown（没查成），不判红，并在 problems 里点名。

    两半：收工门那一侧（`missing_kinds` / `missing_kind_state` 与 problems 那一句）与读表
    工具那一侧（`conductor.acceptance` 的 problems 里有「缺 paper_mapping_rows」）。
    「不判红」的口径是严格的四条：不进 unmet、不出 blocker、不出 warning、`machine_pass`
    不受影响（缺一行不许让每一份老工作区的 findings 都多一条）。
    """
    root = _old_workspace(tmp_path)

    rep = _gate(root)
    acceptance = rep.readings["acceptance"]
    assert acceptance["missing_kinds"] == [LEG], acceptance
    assert acceptance["missing_kind_state"] == "unknown", acceptance
    assert any(LEG in str(p) and "缺" in str(p) for p in acceptance["problems"]), acceptance
    assert all(str(r.get("kind") or "") != LEG for r in acceptance["rows"]), acceptance["rows"]
    assert rep.status["acceptance"] == "pass", rep.to_dict()
    assert rep.blockers == [], rep.to_dict()
    assert rep.findings == [], rep.to_dict()
    assert rep.machine_pass is True, rep.to_dict()

    # 读表工具那一侧：M 唯一能看见「表缺哪一档」的地方
    (root / "out" / "paper" / "ACCEPTANCE.md").write_text(
        "# 验收表\n\n结论：逐条见下表\n\n| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n"
        "| P1 | 手稿落盘 | 成立 | documents 1 行 |\n",
        encoding="utf-8", newline="\n")
    res = CT.conductor_acceptance(Store(root), project_dir=".")
    assert res.ok is True, res
    assert any(LEG in str(p) and "没查成" in str(p) for p in res.data["problems"]), \
        res.data["problems"]


# ============================================================ ⑤ 反真空：三格判据


def test_5_stubbing_the_cell_judgement_true_turns_an_incomplete_row_green(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把「三格齐」的判据打桩恒真 ⇒ ② 必红（那一行的绿只能靠这处判据）。

    先证不齐时这一行是红的（真判据），再打桩、证它翻成绿的 —— 没有第二段，
    ② 的红可能只是「压根没算」，而不是「算出来不齐」。
    """
    root = _numeric_paper(tmp_path, patch={"exhaustion_note": ""})
    _checks(root, [{"id": "P12", "name": "论文对应表", "kind": LEG, "min": 1}])

    before = _gate(root)
    assert before.status["acceptance"] == "fail", before.to_dict()
    assert _row_of(before)["got"] == 0, _row_of(before)

    monkeypatch.setattr(CL, "_mapping_row_missing_cells", lambda *a, **k: [])
    after = _gate(root)
    row = _row_of(after)
    assert row["got"] == 1 and row["ok"] is True, row
    assert row["detail"]["incomplete"] == [], row
    assert after.status["acceptance"] == "pass", after.to_dict()


# ============================================================ ⑥ 反真空：缺档读 unknown


def test_6_stubbing_the_absent_kind_state_to_pass_turns_the_compat_reading_green(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ 反真空：把「缺档读 unknown」打桩成 pass ⇒ ④ 的反面必红。

    ④ 的判据是 `missing_kind_state == "unknown"`；桩成 pass 之后这一条必须不再成立。
    两段都写出来，才证明 ④ 钉的是「没查成」这一档，而不是一条恒真的断言。
    """
    root = _old_workspace(tmp_path)
    real = _gate(root)
    assert real.readings["acceptance"]["missing_kind_state"] == "unknown", \
        real.readings["acceptance"]

    monkeypatch.setattr(CL, "acceptance_absent_kind_state", lambda: "pass")
    stubbed = _gate(root)
    acceptance = stubbed.readings["acceptance"]
    assert acceptance["missing_kind_state"] == "pass", acceptance
    assert acceptance["missing_kind_state"] != "unknown", acceptance
    # 桩只改「读成什么」，不改「缺了哪一档」：点名还在（它不是一个同义的开关）
    assert acceptance["missing_kinds"] == [LEG], acceptance


# ============================================================ ⑦ 读表工具：三种形态


def _acceptance_md(root: pathlib.Path, verdict: str) -> None:
    """M 写的人读验收表（一行「论文对应表」）。"""
    path = root / "out" / "paper" / "ACCEPTANCE.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# 验收表\n\n结论：逐条见下表\n\n| 判据 | 名称 | 结论 | 读数 |\n|---|---|---|---|\n"
        "| P1 | 手稿落盘 | 成立 | documents 1 行 |\n"
        f"| P12 | 论文对应表 | {verdict} | 论文包里没有 out/paper/MAPPING.json |\n",
        encoding="utf-8", newline="\n")


def test_7_the_three_forms_of_this_row_are_all_readable_by_the_tool(
        tmp_path: pathlib.Path) -> None:
    """⑦（③ 的读表面）：缺失 / 记 na / 记「未完成」三种形态，`conductor.acceptance` 都读得出来。

    - 缺失：机器表里没有这一行 ⇒ problems 里有「缺 paper_mapping_rows … 没查成」，且工具
      照样 `ok`（不判红）；
    - 记 na：那一行 `na: true` + 理由 ⇒ problems 里有「标了 na … 不适用」；
    - 记「未完成」：人读表那一行解析成 `ok=False`（第一步就认得），而机器表里同时有一行
      ⇒ problems 里点名两张表的结论不一致（收工门只读机器那张）。
    """
    root = _old_workspace(tmp_path)
    _acceptance_md(root, "未完成")

    # 形态一：缺这一档
    res = CT.conductor_acceptance(Store(root), project_dir=".")
    assert res.ok is True, res
    assert any(LEG in str(p) and "缺" in str(p) and "没查成" in str(p)
               for p in res.data["problems"]), res.data["problems"]

    # 形态二：记 na（带理由）
    _checks(root, [{"id": "P1", "name": "手稿落盘", "kind": "document_rows", "min": 1},
                   {"id": "P12", "name": "论文对应表", "kind": LEG, "min": 1,
                    "na": True, "note": "这一趟没有写论文，对应表不适用"}])
    res = CT.conductor_acceptance(Store(root), project_dir=".")
    assert res.ok is True, res
    assert any(LEG in str(p) and "na" in str(p) and "不适用" in str(p)
               for p in res.data["problems"]), res.data["problems"]

    # 形态三：人读表记「未完成」，机器表里有一行 ⇒ 两张表不一致这件事要被点名
    assert any("未完成" in str(p) and "不一致" in str(p)
               for p in res.data["problems"]), res.data["problems"]

    # 反真空：人读表改成立、机器表那一行也在 ⇒ 这一档相关的提示必须消失（不是恒真的句子）
    _acceptance_md(root, "成立")
    _checks(root, [{"id": "P1", "name": "手稿落盘", "kind": "document_rows", "min": 1},
                   {"id": "P12", "name": "论文对应表", "kind": LEG, "min": 1}])
    clean = CT.conductor_acceptance(Store(root), project_dir=".")
    assert clean.ok is True, clean
    assert not [p for p in clean.data["problems"] if LEG in str(p)], clean.data["problems"]


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
