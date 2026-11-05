# -*- coding: utf-8 -*-
"""收工门那一档「对应表齐了几行」的读数必须按「证明通道」数格（先红后绿）。

## 缺陷（2026-11-04 已核实）

提示词面（`agent_prompts` 的同日改动）与判据面（`papermapping._lean_problems`）今天都改成
按「这一条命题的证明通道」判凭据格：numeric 通道必填 `lean_file`（证明栏第 ① 段那份
`.py`）、formal 通道必填 `lean_file` + `lean_target`、空通道两格允许为空。而收工门那一格
读数（`closing._mapping_row_missing_cells`）仍按旧口径数：

- numeric 行只数 `file` + `numeric_evidence` + `exhaustion_note`，不数 `lean_file`；
- Lean 两格的前提是「开关开 + 盘上有产物」（一个全局读数），不是「这一行的通道」。

⇒ 照新提示词缺 `lean_file` 的 numeric 行，收工门读数仍然报「齐」，而 MAPPING 判据会拒
—— 同一张表两个答案。

## 这一组守五条（改前红在哪写在每条里）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | numeric 行缺 `lean_file`、其余齐 ⇒ 读数点名缺 `lean_file` | 改前读数报「齐」（`complete=1`、`incomplete=[]`） |
| b | 同一条补上 `lean_file` ⇒ 读数报齐（正控） | 改前也是齐 —— 这一条钉住「别把正控弄红」 |
| c | formal 行缺 `lean_target` ⇒ 读数点名缺 `lean_target`（回归） | 通道 formal 而开关开、盘上有产物时改前也报；改后仍须报 |
| d | 空通道行两格留空 ⇒ 不报缺（负控：不适用 ≠ 缺） | 改前在「开关开 + 盘上有产物」时把两格读成缺 |
| e | 判据只有一处：把 `numericproof.proof_channel` 打桩成恒空 ⇒ a 的回落到旧形态 | 改前它本来就不看通道（打桩前后同一个答案） |

## 第二笔：凭据格「多填 / 填错」也要跟判据同一结论（g–k）

这一族的判法不在 closing：读数只调 `papermapping._lean_problems`，它报红 ⇒ 这一行不齐；
它说没问题 ⇒ 读数不许自己再判一次。

| # | 判据 | 改前红在哪 |
|---|---|---|
| g | 空通道只填 `lean_file` ⇒ 不齐，点名「通道为空却填了 lean_file」 | 改前旧读数只看两格空不空 ⇒ 报齐 |
| h | 空通道两格都空 ⇒ 齐（负控） | 改前也是齐 |
| i | 空通道两格都填 ⇒ 不齐，两格都点名（`_lean_problems` 判类别不符） | 改前报齐 |
| j | 打桩 `_lean_problems` 恒空 ⇒ g 的现场立刻报齐（判法只在那一处） | 改前本来就不调它 |
| k | numeric 行填了 `lean_target` ⇒ 不齐，点名「lean_target（数值通道不填）」 | 改前报齐 |

夹具复用 `test_numeric_theorem_writing_spec` 里那一份「合规数值实验定理」（同一个仓库里
只留一份形状）；全部在 `tmp_path` 里自建，零模型调用。
"""
from __future__ import annotations

import json
import pathlib

import pytest

from agentflow import closing as CL
from agentflow import numericproof as NP
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.settings import ENV_LEAN_ENABLED

from test_numeric_theorem_writing_spec import PROGRAM, SID, _row, _workspace

#: formal 通道那一份 Lean 源码（项目根相对：L 的真实落点 `code/formal/`）。
FORMAL_LEAN = "code/formal/000004.lean"
FORMAL_DECL = "theorem free_group_factor_is_ii1 : True := trivial\n"
#: 空通道那一行的正文证明（不是程序、台账里也没有 E 签的穷举）。
PROSE_PROOF = "对 n 作归纳：基例 n = 0 两端同为 0；归纳步提出公因式 (n+1)^2 即得。"


def _reading(root: pathlib.Path) -> dict:
    """收工门那一格读数（`_leg_reading` 的唯一实现，`paper_mapping_rows` 走它）。"""
    return CL.paper_mapping_cell_reading(root, workspace_root=root)


def _numeric_row_without_credential() -> dict:
    """a 的现场：numeric 通道、缺 `lean_file`，其余（file / E 读数 / 两块落点 / 索引四格）齐。"""
    return _row(lean_file="")


def _formal_row_without_target() -> dict:
    """c 的现场：formal 通道、`lean_file` 在、`lean_target` 空。"""
    return _row(file="proofs/thm.tex", lean_file=FORMAL_LEAN, lean_target="",
                numeric_evidence="", exhaustion_note="",
                evidence_kind="", evidence_path="", evidence_sha256="", v_signature=None)


def _empty_channel_row(**over: object) -> dict:
    """空通道那一行的现场（证明是散文），凭据两格默认留空；`over` 用来造「多填」。"""
    row = _row(file="main.tex", lean_file="", lean_target="",
               numeric_evidence="", exhaustion_note="",
               evidence_kind="", evidence_path="", evidence_sha256="", v_signature=None)
    row.update(over)
    return row


def _write_lean_artifact(root: pathlib.Path) -> None:
    """盘上真的落一份 Lean 产物（旧口径「开关开 + 有产物」那一半的触发器）。"""
    path = root / FORMAL_LEAN
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(FORMAL_DECL, encoding="utf-8", newline="\n")


def _make_experiment_formal(root: pathlib.Path) -> None:
    """把台账里那条 E 的实验改成 formal 通道（`method=formal` + 一份 `.lean`）。

    `numericproof.proof_channel` 的 formal 分支认这一种（证明栏是散文、台账里有一条
    `method="formal"` + `evidence_kind="proof"` 的 `.lean` 行），也认证明栏直接写
    `.lean` 的那一种。这一条用前者：证明栏不是程序，所以旧口径的 `is_numeric_row` 不会
    把它抢到数值那一支 —— c 才是真正的"formal 行缺 target"回归。

    这一行同时要绑到这条命题（2026-11-05 起 formal 通道按命题号绑，谓词是
    `evidencebits.formal_row_bound_to`）：这一条命题是 `stmt:{SID}`，
    不绑的 formal 行不是它的凭据。
    """
    path = root / "data" / str(S.TABLES["experiments"]["file"])
    doc = json.loads(path.read_text(encoding="utf-8"))
    for item in doc["rows"]:
        item["method"] = NP.FORMAL_METHOD
        item["code_path"] = FORMAL_LEAN
        item["evidence_kind"] = "proof"
        item["claim_key"] = f"stmt:{SID}"
    path.write_bytes((json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# ============================================================ a 改前红：numeric 缺 lean_file


def test_a_a_numeric_row_missing_the_credential_cell_is_counted_incomplete(
        tmp_path: pathlib.Path) -> None:
    """a：numeric 行缺 `lean_file` ⇒ 收工门读数必须点名缺 `lean_file`（改前报齐）。"""
    root = _workspace(tmp_path / "ws", rows=[_numeric_row_without_credential()])
    got = _reading(root)

    assert got["rows"] == 1, got
    assert [item["missing"] for item in got["incomplete"]] == [["lean_file"]], got
    assert got["complete"] == 0, got


# ============================================================ b 正控：补上就读齐


def test_b_the_same_row_reads_complete_once_the_credential_cell_is_filled(
        tmp_path: pathlib.Path) -> None:
    """b：同一条补上 `lean_file`（= 夹具里那份证明栏第 ① 段的程序）⇒ 读数报齐。"""
    root = _workspace(tmp_path / "ws", rows=[_row()])
    got = _reading(root)

    assert got["rows"] == 1, got
    assert got["incomplete"] == [], got
    assert got["complete"] == 1, got


# ============================================================ c 回归：formal 缺 lean_target


def test_c_a_formal_row_missing_the_target_is_still_counted_incomplete(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c：formal 行缺 `lean_target` ⇒ 读数必须点名（开关开、盘上有产物这一档也不许漏）。"""
    monkeypatch.setenv(ENV_LEAN_ENABLED, "1")
    root = _workspace(tmp_path / "ws", rows=[_formal_row_without_target()],
                      statement=PROSE_PROOF)
    _make_experiment_formal(root)
    _write_lean_artifact(root)
    got = _reading(root)

    assert got["rows"] == 1, got
    assert [item["missing"] for item in got["incomplete"]] == [["lean_target"]], got
    assert got["complete"] == 0, got


# ============================================================ d 负控：空通道不适用 ≠ 缺


def test_d_an_empty_channel_row_does_not_read_as_missing_its_credential_cells(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d：空通道行两格留空 ⇒ 不报缺（改前「开关开 + 有产物」时会读成缺两格）。"""
    monkeypatch.setenv(ENV_LEAN_ENABLED, "1")
    root = _workspace(tmp_path / "ws", rows=[_empty_channel_row()], statement=PROSE_PROOF)
    _write_lean_artifact(root)
    got = _reading(root)

    assert got["rows"] == 1, got
    assert got["incomplete"] == [], got
    assert got["complete"] == 1, got
    # 旧键一个都不许少（M 与 webui 在读）：只改计数口径，不改名字。
    assert {"path", "exists", "rows", "complete", "incomplete", "implicit_min",
            "lean", "note"} <= set(got), sorted(got)
    assert {"enabled", "source", "artifacts", "required"} <= set(got["lean"]), got["lean"]


# ============================================================ e 判据只有一处：打桩通道


def test_e_stubbing_the_proof_channel_falls_back_to_the_old_reading(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """e：把 `numericproof.proof_channel` 打桩成恒空 ⇒ a 的回落到旧形态（报齐）。

    这一条证明读数真的在用那一处判据：桩一打，同一份现场立刻变了答案。
    """
    root = _workspace(tmp_path / "ws", rows=[_numeric_row_without_credential()])
    before = _reading(root)
    assert [item["missing"] for item in before["incomplete"]] == [["lean_file"]], before

    monkeypatch.setattr(NP, "proof_channel", lambda *a, **k: "")
    after = _reading(root)

    assert after["incomplete"] == [], after
    assert after["complete"] == 1, after
    assert after["complete"] != before["complete"], (before, after)


# ============================================================ ② 的补钉：索引四格按既有判据数


def test_f_a_numeric_row_missing_index_cells_is_counted_by_the_existing_criterion(
        tmp_path: pathlib.Path) -> None:
    """② 的补钉：numeric 行的索引四格缺两格 ⇒ 也报不齐（判据是 evidence_index_problems）。"""
    root = _workspace(tmp_path / "ws", rows=[_row(evidence_sha256="", v_signature=None)])
    got = _reading(root)

    assert got["rows"] == 1, got
    one = got["incomplete"][0]
    assert set(one["missing"]) == {"evidence_sha256", "v_signature"}, got
    assert one["index_problems"], got
    assert got["complete"] == 0, got


# ============================================================ 空通道凭据格：「多填」也要读成不齐
#
# 这一组的判法不在这里：整组只看 `papermapping._lean_problems` 的结论（读数只做落位）。
# 改前红：旧读数对空通道只看「两格空不空」，多填一格/两格都算齐。


def test_g_an_empty_channel_row_with_one_credential_cell_filled_is_incomplete(
        tmp_path: pathlib.Path) -> None:
    """空通道只填 `lean_file`（一份数值程序）⇒ 不齐，点名「通道为空却填了 lean_file」。"""
    root = _workspace(tmp_path / "ws",
                      rows=[_empty_channel_row(lean_file=PROGRAM)], statement=PROSE_PROOF)
    got = _reading(root)

    one = got["incomplete"][0]
    assert one["missing"] == ["通道为空却填了 lean_file"], got
    assert one["channel"] == "", got
    assert got["complete"] == 0, got
    # `problems` 是 `_lean_problems` 的原话（不是这里另写的一句）。
    assert any("类别与通道不一致" in text for text in one["problems"]), got


def test_h_an_empty_channel_row_with_both_credential_cells_blank_is_complete(
        tmp_path: pathlib.Path) -> None:
    """负控：空通道两格都空 ⇒ 齐（「不适用」不是「缺」）。"""
    root = _workspace(tmp_path / "ws", rows=[_empty_channel_row()], statement=PROSE_PROOF)
    got = _reading(root)

    assert got["incomplete"] == [], got
    assert got["complete"] == 1, got


def test_i_an_empty_channel_row_with_both_credential_cells_filled_is_incomplete(
        tmp_path: pathlib.Path) -> None:
    """空通道两格都填（`.py` + 声明名）⇒ 不齐，两格都点名（`_lean_problems` 同结论）。"""
    root = _workspace(tmp_path / "ws",
                      rows=[_empty_channel_row(lean_file=PROGRAM, lean_target="R34.isThm")],
                      statement=PROSE_PROOF)
    got = _reading(root)

    one = got["incomplete"][0]
    assert one["missing"] == ["通道为空却填了 lean_file", "通道为空却填了 lean_target"], got
    assert got["complete"] == 0, got
    assert one["problems"], got


def test_j_stubbing_the_lean_problems_criterion_clears_the_multi_fill_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """空通道「多填」的判法只许来自 `_lean_problems`：打桩成恒空 ⇒ 同一现场立刻报齐。"""
    root = _workspace(tmp_path / "ws",
                      rows=[_empty_channel_row(lean_file=PROGRAM)], statement=PROSE_PROOF)
    assert _reading(root)["complete"] == 0

    monkeypatch.setattr(PM, "_lean_problems", lambda *a, **k: [])
    after = _reading(root)

    assert after["incomplete"] == [], after
    assert after["complete"] == 1, after


def test_k_a_numeric_row_with_lean_target_filled_is_incomplete(
        tmp_path: pathlib.Path) -> None:
    """数值通道填了 `lean_target` ⇒ 不齐，点名「lean_target（数值通道不填）」。"""
    root = _workspace(tmp_path / "ws", rows=[_row(lean_target="R34.isThm")])
    got = _reading(root)

    one = got["incomplete"][0]
    assert one["missing"] == ["lean_target（数值通道不填）"], got
    assert one["channel"] == "numeric", got
    assert any("在数值证明通道上没有落点" in text for text in one["problems"]), got
    assert got["complete"] == 0, got



