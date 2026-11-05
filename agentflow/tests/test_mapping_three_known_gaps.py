# -*- coding: utf-8 -*-
"""三条已知缝隙：同一张表两个答案 / 空通道的自称 / 空通道的凭据（先红后绿）。

业主 2026-11-04：「未修项倒是修啊」。三条缝的共同形态是「同一条判据长出两个答案」：

| # | 现场 | 改前的两个答案 |
|---|---|---|
| 一 | `kind="example"`、台账那条命题的证明栏是程序（`proof_channel == numeric`） | 收工门读数按通道要 `numeric_evidence` / `exhaustion_note` / 索引四格 ⇒ `complete=0`；`mapping_reading` 被 `is_numeric_row` 的 kind 门挡住 ⇒ `state=pass` |
| 二 | 空通道（证明栏是散文）而 `numeric_evidence` 有值 | `mapping_reading` 按"这一行自己填了数值那两格"跑去判数值证明 ⇒ 报 `mapping_proof_program_missing`；收工门读数按空通道只数 `file` ⇒ 报齐（一边报一边不报） |
| 三 | 空通道却填了合法 `.lean` + 真实声明名 | `_lean_problems` 说「无问题」⇒ 两边都报齐（凭据格说"这条命题百分百为真"，可是这一行没有任何证明通道） |

## 修法（判据侧只有一处）

- `papermapping._numeric_row_reading` 是"这一行算不算数值凭据那一档"的唯一读法：通道一律问
  `numericproof.proof_channel`（经 `_credential_slot`），`kind` 不参与；通道判不出来
  （程序还没被 E 签成穷举）时用 `numerictheorem.is_program_proof` 兜底 —— 那条兜底
  只决定"按哪一支判"，不决定凭据格该不该填。
- 空通道而 `numeric_evidence` / `exhaustion_note` 有值 ⇒ `mapping_numeric_evidence_missing`
  （`_lean_problems` 第 6 条）：两边同时报，不再一边报一边不报。
- 空通道而凭据格填了任一格 ⇒ `mapping_lean_file_missing`（`_lean_problems` 第 5 条）：
  「这一行没有证明通道 ⇒ 凭据格不许填，填了就是无依据的声称」。收工门读数只调
  `_lean_problems`，没有第二套。

## 但缝隙一 2026-11-05 被业主判成「误拦」，那一支按通道优先重裁

2026-11-04 的修法把 `kind="example"` 的行按数值实验定理整档判：只要证明通道是程序，
就要 `numeric_evidence` / `exhaustion_note` / 索引四格。于是这些行按通道填好了凭据那一格
（`lean_file` = 证明栏第 ① 段那份 `.py`），读数仍说「凭据不够」。2026-11-05 的裁定：

- 凭据格按通道判（六类环境一视同仁）：证明栏是程序 ⇒ `lean_file` 填那份程序就齐；
- 附加义务按档位判：`numeric_evidence` / `exhaustion_note` / 索引四格 / 正文指回 E
  只压在 `papermapping.is_numeric_theorem_row` 为真的行（`STATEMENT_ENV_KINDS` =
  theorem / lemma / proposition / corollary）—— 例子与实验不是被证明的命题。

于是本文件 a 的期望按业主重裁改过（旧逐字 → 新逐字见 `test_a_...` 的 docstring）；
b / c 两条不动。这一改不退回 11-04 修掉的 kind 门：那道门问「这一行算不算数值行」，
凭据格与 `file` 都跟着 `kind` 走；现在的门只问「要不要那几格附加义务」。

## 这一组守 a–d（e/f 是静态面与回归面，读数见报告）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | example / experiment + numeric 通道、只填凭据格 ⇒ 三处读数（`mapping_reading` / 收工门 / `doc.mapping_cells`）都说齐；同现场换成 theorem ⇒ 仍缺 `numeric_evidence` | 改前 example 这一档报「凭据不够」（`mapping_numeric_evidence_missing` / `complete=0`） |
| a2 | example + 空通道 ⇒ 不是数值行（凭据两格空着就齐） | 与改前同（这一条钉住「别把空通道也当数值行」） |
| a3 | example + 证明栏是程序但还没被 E 签成穷举（`proof_channel` 为空）⇒ 凭据格认那份 `.py`；同现场 theorem 仍受控拒 | 改前「凭据不够」三处：缺 `lean_target`、`.py` 类别不符、缺 `numeric_evidence` |
| b | 空通道 + `numeric_evidence`/`exhaustion_note` 有值 ⇒ 两边同时报「没有数值证明通道」 | 改前一边 `mapping_proof_program_missing`、一边齐 |
| c | 空通道 + 合法 `.lean` + 真声明名 ⇒ 两边都不齐，点名「凭据格不许填」 | 改前两边都齐、`_lean_problems` 说无问题 |
| d | 把各自的修法摘掉（打桩/过滤）⇒ a/b/c 各回红 | 打桩前它们本来是绿的 —— 证明绿真的靠那几处判据 |

夹具复用 `test_numeric_theorem_writing_spec` 的构造器（同一个仓库里只留一份形状）。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

PROJECT = pathlib.Path(__file__).resolve().parents[1]
SRC = PROJECT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest  # noqa: E402

import test_numeric_theorem_writing_spec as SPEC  # noqa: E402
from agentflow import closing as CL  # noqa: E402
from agentflow import numericproof as NP  # noqa: E402
from agentflow import papermapping as PM  # noqa: E402
from agentflow.store import Store  # noqa: E402
from agentflow.tools import build_registry  # noqa: E402

#: 空通道那一行的正文证明（散文：不是程序，台账里也没有 E 签的穷举）。
PROSE = "对 n 作归纳：基例 n = 0 两端同为 0；归纳步提出公因式 (n + 1)^2 即得。"
#: 形式化那一份 Lean 源码（项目根相对：L 的真实落点 `code/formal/`）。
LEAN_REL = "code/formal/000004.lean"
LEAN_DECL = "free_group_factor_is_ii1"
LEAN_SRC = ("namespace FreeGroupFactor\n\n"
            "theorem free_group_factor_is_ii1 : True := trivial\n\n"
            "end FreeGroupFactor\n")


def _example_tex(kind: str = "example") -> str:
    """把正文那一条环境换成 `kind`（label 不变）—— 现场是"例子 / 实验环境里的数值定理"。"""
    return (SPEC.CLEAN_TEX
            .replace("\\begin{theorem}\\label{thm:r34}",
                     "\\begin{" + kind + "}\\label{ex:r34}")
            .replace("\\end{theorem}", "\\end{" + kind + "}"))


def _package_file(root: pathlib.Path, rel: str, body: bytes = b"proof\n") -> None:
    path = PM.package_dir(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)


def _reading(root: pathlib.Path) -> tuple[dict, dict]:
    """同一现场的两份读数：`mapping_reading` 与收工门那一格（`paper_mapping_cell_reading`）。"""
    return PM.mapping_reading(root), CL.paper_mapping_cell_reading(root, workspace_root=root)


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or ()]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or ())


def _incomplete(got: dict) -> dict:
    assert got["incomplete"], f"收工门读数没有点名任何一行：{got}"
    return got["incomplete"][0]


def _example_credential_only(kind: str = "example", **over: object) -> dict:
    """缝隙一的现场：`kind` = example / experiment + numeric 通道，只按通道填凭据那一格（`.py`）。

    缺的正是「数值实验定理」那几格附加义务（`numeric_evidence` / `exhaustion_note` /
    索引四格）：2026-11-05 的裁定是它们不压在例子 / 实验上（`kind` 只决定档位）。
    """
    row = SPEC._row(kind=kind, label="ex:r34", numeric_evidence="", exhaustion_note="",
                    evidence_kind="", evidence_path="", evidence_sha256="", v_signature=None)
    row.update(over)
    return row


def _empty_channel_with_numeric_claim(**over: object) -> dict:
    """缝隙二的现场：空通道，行自称有数值证据；`over` 用来换哪一格在自称。"""
    row = SPEC._row(file="proofs/thm.tex", numeric_evidence="exp:000000",
                    exhaustion_note="", lean_file="", lean_target="",
                    evidence_kind="", evidence_path="", evidence_sha256="",
                    v_signature=None)
    row.update(over)
    return row


def _empty_channel_with_credentials(**over: object) -> dict:
    """缝隙三的现场：空通道，凭据两格填了合法 `.lean` + 源码里真有的声明名。"""
    row = SPEC._row(file="proofs/thm.tex", lean_file=LEAN_REL, lean_target=LEAN_DECL,
                    numeric_evidence="", exhaustion_note="",
                    evidence_kind="", evidence_path="", evidence_sha256="",
                    v_signature=None)
    row.update(over)
    return row


def _empty_channel_ws(root: pathlib.Path, row: dict) -> pathlib.Path:
    """空通道的工作区：台账里那条命题的证明栏是散文，包里有一份 `proofs/thm.tex`。"""
    root = SPEC._workspace(root, rows=[row], statement=PROSE)
    _package_file(root, "proofs/thm.tex")
    return root


# ============================================================ a 缝隙一：凭据按通道、附加义务按档位

@pytest.mark.parametrize("env_kind", ["example", "experiment"])
def test_a_an_example_row_with_a_numeric_channel_is_complete_by_its_credential(
        tmp_path: pathlib.Path, env_kind: str) -> None:
    """a：`kind="example"` / `"experiment"` + numeric 通道、只填凭据格 ⇒ 三处读数都说齐。

    旧逐字 → 新逐字（业主 2026-11-05 重裁，为什么见模块 docstring）：

    - 旧：同一现场（`kind="example"`、numeric 通道、缺 `numeric_evidence`）断言
      `paper["state"] == "fail"`、`"mapping_numeric_evidence_missing" in _kinds(paper)`、
      `gate["complete"] == 0`、`one["missing"]` 里有 `numeric_evidence` ——
      即「example 行也要数值实验定理那几格」。
    - 新：`paper["state"] == "pass"`、两者都没有 `mapping_numeric_evidence_missing`、
      `gate["complete"] == 1`、`doc.mapping_cells` 的 `ok is True` —— 凭据那一格
      （`lean_file` = 证明栏第 ① 段那份 `.py`）按通道填了就齐；附加义务只压在命题类环境上。
    - 为什么：例子 / 实验不是被证明的命题（`STATEMENT_ENV_KINDS` 的口径），它们没有
      「这条定理压在哪条 E 的穷举读数上」这一问；旧期望把「凭据格填对了」读成「凭据不够」。

    b（既有档位不许变）也在这一条里：同一现场换成 `kind="theorem"` ⇒ 仍缺
    `numeric_evidence`，两边都不齐。
    """
    row = _example_credential_only(env_kind)
    root = SPEC._workspace(tmp_path / "ws", rows=[row], tex=_example_tex(env_kind))
    paper, gate = _reading(root)
    assert gate["rows"] == 1, gate
    assert gate["complete"] == 1 and gate["incomplete"] == [], gate
    assert paper["state"] == "pass", _details(paper)
    assert "mapping_numeric_evidence_missing" not in _kinds(paper), _details(paper)

    # 第三处读数（工具面）：同一现场 `doc.mapping_cells` 也说齐，且凭据格是那份程序。
    cells = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)
    assert cells["ok"] is True, cells["problems"]
    assert cells["channel"] == NP.PROOF_CHANNEL_NUMERIC, cells["channel"]
    assert cells["cells"]["file"] == SPEC.PROGRAM
    assert cells["cells"]["lean_file"] == SPEC.PROGRAM
    assert cells["cells"]["lean_target"] == ""
    # 附加义务那几格是「不适用」，不是「缺」：给空串并写明理由。
    for name in ("numeric_evidence", "exhaustion_note",
                 "evidence_kind", "evidence_path", "evidence_sha256", "v_signature"):
        assert cells["cells"].get(name) == "", (name, cells["cells"])
        assert "不适用" in cells["sources"].get(name, ""), (name, cells["sources"])

    # 第四处（写口）：`doc.write_mapping` 读的就是同一份判据 —— 这一行写得进去、state=pass。
    # 只交必填六格 + 凭据格（附加义务那几格在工具参数 schema 里是 enum / 条件必填，
    # 例子行不该也不交）。
    writable = {name: row[name] for name in
                ("kind", "label", "env_no", "ledger_id", "proof_no", "file", "lean_file",
                 "citation_loc_reason")}
    registry = build_registry(store=Store(root), workspace_root=root,
                              roles=("G",)).registry
    res = registry.call("doc.write_mapping", role="G", project=".", rows=[writable])
    assert res.ok is True, (res.error, res.meta)
    assert (res.data or {}).get("state") == "pass", res.data

    # ---- b）：同现场换成 theorem（既有档位）⇒ 仍按数值实验定理那一档判，一格都不许变。
    thm = SPEC._workspace(tmp_path / "thm",
                          rows=[_example_credential_only("theorem", label="thm:r34")],
                          tex=SPEC.CLEAN_TEX)
    paper2, gate2 = _reading(thm)
    assert paper2["state"] == "fail", _details(paper2)
    assert "mapping_numeric_evidence_missing" in _kinds(paper2), _details(paper2)
    assert gate2["complete"] == 0, gate2
    assert "numeric_evidence" in _incomplete(gate2)["missing"], gate2
    # 写口也同一个答案：theorem 这一档缺 `numeric_evidence` ⇒ 受控拒绝（不是见 example 就放）。
    thm_row = _example_credential_only("theorem", label="thm:r34")
    thm_writable = {name: thm_row[name] for name in
                    ("kind", "label", "env_no", "ledger_id", "proof_no", "file", "lean_file",
                     "citation_loc_reason")}
    thm_registry = build_registry(store=Store(thm), workspace_root=thm,
                                  roles=("G",)).registry
    thm_res = thm_registry.call("doc.write_mapping", role="G", project=".",
                                rows=[thm_writable])
    assert thm_res.ok is False, (thm_res.error, thm_res.data)
    assert thm_res.meta.get("kind") == "mapping_not_clean", thm_res.meta

    # 负控：同一档把附加义务也补齐 ⇒ 仍然齐（不是"见 example 就拒"）。
    ok = SPEC._workspace(tmp_path / "ok", rows=[SPEC._row(kind=env_kind,
                                                         label="ex:r34")],
                         tex=_example_tex(env_kind))
    paper3, gate3 = _reading(ok)
    assert gate3["complete"] == 1 and gate3["incomplete"] == [], gate3
    assert paper3["state"] == "pass", _details(paper3)


def test_a3_an_example_whose_program_is_not_signed_yet_is_still_complete(
        tmp_path: pathlib.Path) -> None:
    """a3：例子 + 证明栏第 ① 段是程序、E 还没签成穷举 ⇒ 凭据那一格仍然齐。

    这是交接文档（`docs/AUDIT-VSIGN-CHANNELS-AND-PROMPTS-2026-11-04.md` 三·1）登记的
    残余形态：台账那条命题的 `proof_text` 就是三段式证明栏（第 ① 段是
    `code/r34_check.py`），而 `experiments` 里那条还不是 E 签的穷举（`cross_check`）
    ⇒ `numericproof.proof_channel` 返回空串。行按通道把 `lean_file` 填成那份 `.py`。

    - 改前：「凭据不够」三处在报 —— `mapping_lean_missing`（缺 `lean_target`）、
      `mapping_lean_file_missing`（「不能把一份数值程序填进这一格」）、
      `mapping_numeric_evidence_missing`。
    - 改后：凭据格按通道认那一份 `.py`（例子 / 实验的数值凭据就是它），三处都不再报；
      `kind` 只决定要不要数值实验定理那几格附加义务（这一行不要）。
    - b（负控）：同现场换成 `theorem` ⇒ 仍按旧档判（那一份没签的 `.py` 仍受控拒、也仍缺
      `numeric_evidence`）—— 既有档位不跟着松。
    """
    root = SPEC._workspace(tmp_path / "ws", rows=[_example_credential_only()],
                           tex=_example_tex(), experiment="cross_check")
    paper, gate = _reading(root)
    assert paper["state"] == "pass", _details(paper)
    assert gate["complete"] == 1 and gate["incomplete"] == [], gate

    parsed, problems = PM.parse_rows(json.loads(
        (PM.package_dir(root) / PM.MAPPING_JSON_NAME).read_text(encoding="utf-8")))
    assert not problems, problems
    ledger = PM.read_ledger_tables(root)
    # 通道判不出来（还没被 E 签成穷举），但「证明栏第 ① 段是程序」这一档仍然认得出；
    # 附加义务（数值实验定理那一档）不压在例子 / 实验上。
    assert PM.is_numeric_row(parsed[0], ledger) is True
    assert PM.is_numeric_theorem_row(parsed[0], ledger) is False

    cells = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)
    assert cells["ok"] is True, cells["problems"]
    assert cells["channel"] == "", cells["channel"]
    assert cells["cells"]["file"] == SPEC.PROGRAM
    assert cells["cells"]["lean_file"] == SPEC.PROGRAM
    assert cells["cells"]["lean_target"] == ""
    assert cells["cells"]["numeric_evidence"] == ""

    # 负控（b）：theorem 同一现场 ⇒ 没签的那份 `.py` 不认、数值定理那几格仍缺。
    thm = SPEC._workspace(tmp_path / "thm",
                          rows=[_example_credential_only("theorem", label="thm:r34")],
                          tex=SPEC.CLEAN_TEX, experiment="cross_check")
    paper2, gate2 = _reading(thm)
    kinds2 = _kinds(paper2)
    assert paper2["state"] == "fail", _details(paper2)
    for kind in ("mapping_lean_file_missing", "mapping_numeric_evidence_missing"):
        assert kind in kinds2, (kind, _details(paper2))
    assert gate2["complete"] == 0, gate2


def test_a2_an_example_row_with_an_empty_channel_is_not_a_numeric_row(
        tmp_path: pathlib.Path) -> None:
    """a2（d）：`kind="example"` 而通道为空 ⇒ 仍按原样（不是数值行、也不要求附加义务）。

    「通道为空」= 证明栏是散文、台账里也没有 E 签的穷举：这一行没有数值凭据，
    所以它既不是数值行（`is_numeric_row` 为假，`file` 走论文包内那一支），也不承担
    数值实验定理那几格。凭据两格留空就齐 —— 这一条钉住「别把空通道也当数值行」。
    """
    row = SPEC._row(kind="example", label="ex:r34", file="proofs/thm.tex",
                    lean_file="", lean_target="", numeric_evidence="", exhaustion_note="",
                    evidence_kind="", evidence_path="", evidence_sha256="", v_signature=None)
    root = SPEC._workspace(tmp_path / "ws", rows=[row], tex=_example_tex(),
                           statement=PROSE)
    _package_file(root, "proofs/thm.tex")

    paper, gate = _reading(root)
    assert paper["state"] == "pass", _details(paper)
    assert gate["complete"] == 1 and gate["incomplete"] == [], gate

    parsed, problems = PM.parse_rows(json.loads(
        (PM.package_dir(root) / PM.MAPPING_JSON_NAME).read_text(encoding="utf-8")))
    assert not problems, problems
    ledger = PM.read_ledger_tables(root)
    built = parsed[0]
    assert PM.is_numeric_row(built, ledger) is False
    assert PM.is_numeric_theorem_row(built, ledger) is False
    cells = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)
    assert cells["channel"] == "", cells["channel"]
    for name in ("numeric_evidence", "exhaustion_note", "evidence_kind"):
        assert cells["cells"].get(name) == "", (name, cells["cells"])
        assert "不适用" in cells["sources"].get(name, ""), (name, cells["sources"])


# ============================================================ b 缝隙二：空通道的自称

def test_b_an_empty_channel_row_that_claims_numeric_evidence_is_reported_by_both(
        tmp_path: pathlib.Path) -> None:
    """b：空通道 + `numeric_evidence` 有值 ⇒ 两边同时报「没有数值证明通道」（改前一边报）。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_numeric_claim())

    paper, gate = _reading(root)
    assert paper["state"] == "fail", paper["reason"]
    assert "mapping_numeric_evidence_missing" in _kinds(paper), _details(paper)
    detail = _details(paper)
    assert "自称有数值证据" in detail and "没有数值证明通道" in detail, detail
    one = _incomplete(gate)
    assert one["channel"] == "", gate
    assert gate["complete"] == 0, gate
    # 收工门读数的原话必须是同一句（它只转发 `_lean_problems`，不另写一套）。
    assert one.get("problems"), gate
    assert any("自称有数值证据" in text and "没有数值证明通道" in text
               for text in one["problems"]), one

    # 第三处读数（`doc.mapping_cells`，2026-11-05 复核三点名的那一处）：同一句原话、
    # 归到同一格；它没有把这一行当数值行（数值那两格是「不适用」，不是补造值）。
    cells = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)
    assert cells["ok"] is False, cells["problems"]
    assert any(item["cell"] == "numeric_evidence"
               and "自称有数值证据" in item["why"] for item in cells["problems"]), cells
    assert cells["cells"]["numeric_evidence"] == "", cells["cells"]
    assert "不适用" in cells["sources"]["numeric_evidence"], cells["sources"]

    # 负控：把那一格清空 ⇒ 空通道 + 两格空 + 无数值自称 ⇒ 两边同时齐。
    clean = _empty_channel_ws(tmp_path / "clean", SPEC._row(
        file="proofs/thm.tex", numeric_evidence="", exhaustion_note="",
        lean_file="", lean_target=""))
    paper2, gate2 = _reading(clean)
    assert gate2["complete"] == 1, gate2
    assert paper2["state"] == "pass", _details(paper2)

    # 反方向：`exhaustion_note`（E 的两块读数）也算"自称有数值证据"——
    # 旧 `is_numeric_row` 认这两格，修后不许只剩一格在管。
    note = _empty_channel_ws(tmp_path / "note", _empty_channel_with_numeric_claim(
        numeric_evidence="", exhaustion_note=SPEC.NOTE))
    paper3, gate3 = _reading(note)
    assert "mapping_numeric_evidence_missing" in _kinds(paper3), _details(paper3)
    assert gate3["complete"] == 0, gate3


# ============================================================ c 缝隙三：空通道的凭据

def test_c_an_empty_channel_row_may_not_fill_the_credential_cells(
        tmp_path: pathlib.Path) -> None:
    """c：空通道 + 合法 `.lean` + 真声明名 ⇒ 两边都不齐（改前两边都齐）。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_credentials())
    lean = root / LEAN_REL
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_text(LEAN_SRC, encoding="utf-8", newline="\n")

    paper, gate = _reading(root)
    assert paper["state"] == "fail", paper["reason"]
    assert _kinds(paper) == ["mapping_lean_file_missing"], _details(paper)
    detail = _details(paper)
    for needle in ("没有证明通道", "凭据格不许填，填了就是无依据的声称", "类别与通道不一致"):
        assert needle in detail, (needle, detail)
    one = _incomplete(gate)
    assert one["channel"] == "", gate
    assert gate["complete"] == 0, gate
    assert one["missing"] == ["通道为空却填了 lean_file", "通道为空却填了 lean_target"], one
    assert any("凭据格不许填，填了就是无依据的声称" in text
               for text in one.get("problems") or ()), one

    # 只填一格也要被点名到"填了的那一格"（不许把 lean_target 的多填读成 lean_file 的缺）。
    only_target = _empty_channel_ws(tmp_path / "target",
                                    _empty_channel_with_credentials(lean_file=""))
    paper2, gate2 = _reading(only_target)
    assert "mapping_lean_file_missing" in _kinds(paper2), _details(paper2)
    assert _incomplete(gate2)["missing"] == ["通道为空却填了 lean_target"], gate2
    cells2 = PM.mapping_cells(only_target, workspace_root=only_target, statement_id=SPEC.SID)
    assert [item["cell"] for item in cells2["problems"]] == ["lean_target"], cells2

    # 三格里的第三格（任务点名：证明栏第 ① 段那份 `.py`）：填进凭据格同样算空通道多填。
    only_py = _empty_channel_ws(tmp_path / "py",
                                _empty_channel_with_credentials(lean_file=SPEC.PROGRAM,
                                                                lean_target=""))
    paper3, gate3 = _reading(only_py)
    assert _kinds(paper3) == ["mapping_lean_file_missing"], _details(paper3)
    assert _incomplete(gate3)["missing"] == ["通道为空却填了 lean_file"], gate3
    assert "lean_file" in _details(paper3), _details(paper3)
    cells3 = PM.mapping_cells(only_py, workspace_root=only_py, statement_id=SPEC.SID)
    assert [item["cell"] for item in cells3["problems"]] == ["lean_file"], cells3

    # 负控：两格都空 ⇒ 两边同时齐（"不适用"不是"缺"）。
    blank = _empty_channel_ws(tmp_path / "blank", SPEC._row(
        file="proofs/thm.tex", lean_file="", lean_target="",
        numeric_evidence="", exhaustion_note=""))
    paper4, gate4 = _reading(blank)
    assert gate4["complete"] == 1 and gate4["incomplete"] == [], gate4
    assert paper4["state"] == "pass", _details(paper4)


# ============================================================ d 反真空：摘掉修法各回红

def test_d1_putting_the_numeric_theorem_obligations_back_reopens_gap_one(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-a（反真空）：把「附加义务只压在定理类环境」那一支摘掉 ⇒ a 立刻回到「凭据不够」。

    打桩：让 `is_numeric_theorem_row` 直接等于 `is_numeric_row` —— 就是 2026-11-04 的旧口径
    （六类环境都要 `numeric_evidence` / `exhaustion_note` / 索引四格）。同一现场立刻变红，
    且红的就是 a 里那一条 `mapping_numeric_evidence_missing`：a 的绿真的靠「`kind` 只决定
    档位」这一支，不是靠「这条现场本来就没人查」。
    """
    root = SPEC._workspace(tmp_path / "ws", rows=[_example_credential_only()],
                           tex=_example_tex())
    before, gate_before = _reading(root)
    assert before["state"] == "pass", _details(before)
    assert gate_before["complete"] == 1 and gate_before["incomplete"] == [], gate_before

    monkeypatch.setattr(PM, "is_numeric_theorem_row", PM.is_numeric_row)
    after, gate = _reading(root)
    assert after["state"] == "fail", _details(after)
    assert "mapping_numeric_evidence_missing" in _kinds(after), _details(after)
    assert gate["complete"] == 0, gate
    assert "numeric_evidence" in _incomplete(gate)["missing"], gate


def test_d2_dropping_the_claim_check_reopens_gap_two(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-b：把 `_lean_problems` 摘空（那份自称判据只在它里面）⇒ 同一现场又报齐。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_numeric_claim())
    assert _reading(root)[1]["complete"] == 0

    monkeypatch.setattr(PM, "_lean_problems", lambda *args, **kwargs: [])
    paper, gate = _reading(root)
    assert gate["incomplete"] == [] and gate["complete"] == 1, gate
    assert paper["state"] == "pass", _details(paper)


def test_d3_dropping_the_credential_refusal_reopens_gap_three(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """d-c：把空通道的凭据拒绝那一条滤掉 ⇒ 同一现场又两边都齐。"""
    root = _empty_channel_ws(tmp_path / "ws", _empty_channel_with_credentials())
    lean = root / LEAN_REL
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_text(LEAN_SRC, encoding="utf-8", newline="\n")
    assert _reading(root)[1]["complete"] == 0

    real = PM._lean_problems

    def _without_credential_refusal(*args, **kwargs):
        return [one for one in real(*args, **kwargs)
                if "凭据格不许填" not in str(one.get("detail") or "")]

    monkeypatch.setattr(PM, "_lean_problems", _without_credential_refusal)
    paper, gate = _reading(root)
    assert gate["incomplete"] == [] and gate["complete"] == 1, gate
    assert paper["state"] == "pass", _details(paper)


# ============================================================ e 判据只有一处（静态面）

def test_e_proof_channel_is_defined_once_and_kind_no_longer_votes() -> None:
    """e：`def proof_channel` 只有 `numericproof` 一处；`is_numeric_row` 里没有 kind 门。"""
    package = SRC / "agentflow"
    defs = sorted(
        str(path.relative_to(package)).replace("\\", "/")
        for path in package.rglob("*.py")
        if re.search(r"^\s*def proof_channel\(", path.read_text(encoding="utf-8"), re.M))
    assert defs == ["numericproof.py"], defs

    text = (package / "papermapping.py").read_text(encoding="utf-8")
    assert len(re.findall(r"^def is_numeric_row\(", text, re.M)) == 1
    body = text.split("def is_numeric_row(", 1)[1].split("\ndef ", 1)[0]
    # 只核「代码」：docstring 里逐字引用改前那两条口径（说明"为什么删"），不算第二套判法。
    code = body.split('"""')[-1] if '"""' in body else body
    assert "_numeric_row_reading" in code, code
    for stale in ("LEAN_TARGETED_KINDS", "row.numeric_evidence", "row.exhaustion_note",
                  "ledger_row"):
        assert stale not in code, f"`is_numeric_row` 的代码里还留着改前那一套：{stale}"
    # 唯一读法里也只接线那两处判据，不自己判通道（同样只看代码）。
    reading = text.split("def _numeric_row_reading(", 1)[1].split("\ndef ", 1)[0]
    reading_code = reading.split('"""')[-1] if '"""' in reading else reading
    assert "NP.PROOF_CHANNEL_NUMERIC" in reading_code, reading_code
    assert "is_program_proof" in reading_code, reading_code
    assert "proof_column_script" not in reading_code, (
        "`_numeric_row_reading` 自己拿 proof_column_script 判通道 ⇒ 第二套判法")

    # 附加义务那一道边界也只有一处：`is_numeric_theorem_row` 读 `STATEMENT_ENV_KINDS`
    # 与 `is_numeric_row`，自己不判通道、也不看那一行填了哪几格。
    assert len(re.findall(r"^def is_numeric_theorem_row\(", text, re.M)) == 1
    theorem = text.split("def is_numeric_theorem_row(", 1)[1].split("\ndef ", 1)[0]
    theorem_code = theorem.split('"""')[-1] if '"""' in theorem else theorem
    assert "STATEMENT_ENV_KINDS" in theorem_code, theorem_code
    assert "is_numeric_row(" in theorem_code, theorem_code
    assert "proof_column_script" not in theorem_code, theorem_code
    for stale in ("row.numeric_evidence", "row.exhaustion_note"):
        assert stale not in theorem_code, f"`is_numeric_theorem_row` 自己判了：{stale}"


# ============================================================ f 既有回归（读数在报告里）

REGRESSION_FILES: tuple[str, ...] = (
    "test_numeric_theorem_writing_spec.py",
    "test_d38_mapping_is_not_silently_missing.py",
    "test_d38_step2_paper_mapping_is_machine_judged.py",
    "test_lean_file_is_taught_by_channel.py",
    "test_closing_mapping_reads_by_channel.py",
    "test_g_mapping_rows_declare_the_papermapping_cells.py",
)


def test_f_the_named_regression_files_are_still_on_disk() -> None:
    """f：那五组既有回归还在盘上（它们的绿由 pytest 那一趟读数给，不在这里伪造）。"""
    missing = [name for name in REGRESSION_FILES
               if not (PROJECT / "tests" / name).is_file()]
    assert not missing, missing


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
