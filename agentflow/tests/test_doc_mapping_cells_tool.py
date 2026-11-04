# -*- coding: utf-8 -*-
"""判据：`doc.mapping_cells` 直接取「对应表那一行该填的格」（业主 2026-11-04）。

业主原话：「如果数据位置都知道，要给 G 开发辅助工具直接拿到」。于是这一件只读工具
按命题号交回逐格的值、逐格的来源、逐格的问题 —— 而不是让 G 再去台账里翻一遍、
在提示词里猜「这一格该填哪一类」。

## 这一组判据各自只证明一件事

| # | 判据 | 它钉的是什么 |
|---|---|---|
| a | 干净的数值定理行（四格齐全）⇒ 工具给出全部格，每格 `sources` 指得回真位置 | 读数不是空的、来源不是"大概在台账里" |
| b | 缺 `lean_file` ⇒ `problems` 点名，且 why 与判据原话逐字相同 | 判据只有一处（没有第二套"该不该填"） |
| c | `evidence_sha256` 抄错 ⇒ 报"不符"，且交回的仍是现算的 sha | sha 必须现算，不静默用抄来的数 |
| d | 没有签 ⇒ `v_signature` 缺失被点名（不是空串冒充「签过」） | 三态纪律：没签 ≠ 签过了 |
| e | 把 `numericproof.proof_channel` 打桩成恒空 ⇒ channel 与凭据格清单回落到旧形态 | 通道判定只调那一处 |
| f | 工具面/写集里没有它；它对盘上 `data/` 的写调用为 0 | 只读 |
| g | 同一现场：工具说"齐"而 `papermapping.mapping_reading` 判拒 ⇒ 红 | 两条读数不许两个答案 |

## 夹具的来路

现场直接复用 `tests/test_numeric_theorem_writing_spec.py` 的构造器（`_workspace` /
`_row` / `_statement` / `_experiment`）：那条穷举证明的证明栏、E 的两块读数、索引四格
都在那里，另起一份夹具就会长出第二个"干净的数值定理行"口径（正是本仓最忌的形态）。
本文件只补两样那里没有的东西：`verifications/<命题号>.jsonl` 里那一签（d 的对手方），
以及 `PM.mapping_reading` 的对照读数（g）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

import test_numeric_theorem_writing_spec as SPEC

from agentflow import numericproof as NP
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import SIDE_EFFECTS_WRITE, build_registry

# ============================================================ 夹具


def _note_sha() -> str:
    return hashlib.sha256(SPEC.NOTE_TEXT.encode("utf-8")).hexdigest()


def _write_sign(root: pathlib.Path, *, sha: str, verdict: str = "成立",
                object_path: str = SPEC.NOTE) -> pathlib.Path:
    """V 的审校台账里那一签（`numericproof.latest_third_party_sign` 的唯一读口）。

    写给的是"这一份对象"：`object_sha256` = 盘上那份读数的字节 sha、`object_path` 也是它。
    这正是收工门与 B 的入库闸认签的口径（`_sign_row_pins`），不是另造一套。
    """
    path = root / "verifications" / f"{SPEC.SID}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "verification_id": "v-000001",
        "verdict": verdict,
        "statement_id": SPEC.SID,
        "proof_sha256": hashlib.sha256(SPEC.PROOF_COLUMN.encode("utf-8")).hexdigest(),
        "object_sha256": str(sha).lower(),
        "object_path": object_path,
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _scene(tmp_path: pathlib.Path, *, row_over: dict | None = None,
           sign: bool = True, sign_verdict: str = "成立") -> pathlib.Path:
    """一个"数值实验定理 + 四格齐全"的现场（工作区根 = 项目根）。"""
    root = pathlib.Path(tmp_path) / "ws"
    root.mkdir(parents=True)
    SPEC._workspace(root, rows=None)
    if sign:
        _write_sign(root, sha=_note_sha(), verdict=sign_verdict)
    row = {**SPEC._row(), **(row_over or {})}
    PM.write_package(root, [PM.Row(**row)], workspace_root=root)
    return root


def _reading(root: pathlib.Path) -> dict:
    return PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)


def _cells_of(problems: list[dict]) -> list[str]:
    return [str(item.get("cell")) for item in problems]


def _write_row(root: pathlib.Path, row: dict) -> None:
    """按盘的形状重写 json（只改行，不动 md/附录 —— 这一组不看那两份）。"""
    path, _md = PM.mapping_paths(root)
    path.write_bytes((json.dumps({"rows": [row]}, ensure_ascii=False, indent=2)
                      + "\n").encode("utf-8"))


@pytest.fixture()
def registry(tmp_path: pathlib.Path):
    """G 的工具面（与 `doc.write_mapping` 的判据同一条装配路径）。"""
    ws = tmp_path / "toolface"
    ws.mkdir()
    store = Store(ws)
    store.init()
    return build_registry(store=store, workspace_root=ws, roles=("G",),
                          strict=True).registry


# ============================================================ a 干净的现场：格齐、来源指得回

def test_a_a_complete_numeric_row_yields_every_cell_with_its_source(tmp_path) -> None:
    """a：数值定理行、四格齐全 ⇒ 九格都给、每格 source 指得回真位置。"""
    root = _scene(tmp_path)
    got = _reading(root)

    assert got["checked"] is True, got
    assert got["ok"] is True, got["problems"]
    assert got["channel"] == NP.PROOF_CHANNEL_NUMERIC, got["channel"]

    cells, sources = got["cells"], got["sources"]
    assert set(cells) == set(PM.MAPPING_CELL_FIELDS), (sorted(cells), sorted(
        PM.MAPPING_CELL_FIELDS))
    # 逐格的值：数值通道那一行该填的东西，一处不差
    assert cells["file"] == SPEC.PROGRAM
    assert cells["lean_file"] == SPEC.PROGRAM          # 数值通道 = 证明栏第 ① 段那份 .py
    assert cells["lean_target"] == ""                  # 数值程序没有 Lean 声明名
    assert cells["numeric_evidence"] == f"exp:{SPEC.EID}"
    assert cells["exhaustion_note"] == SPEC.NOTE
    assert cells["evidence_kind"] == "report"
    assert cells["evidence_path"] == SPEC.NOTE
    assert cells["evidence_sha256"] == _note_sha()      # 现算
    assert cells["v_signature"] == {"verdict": "成立", "sha256": _note_sha()}

    # 逐格的来源：要么指回"哪张表哪一行哪一格"，要么写清"现算"
    assert set(sources) == set(cells)
    assert "experiments#exp:" in sources["file"] or "statements#stmt:" in sources["file"]
    assert f"stmt:{SPEC.SID}" in sources["lean_file"]
    assert f"exp:{SPEC.EID}" in sources["numeric_evidence"]
    assert "report_relpath" in sources["exhaustion_note"]
    assert "现算" in sources["evidence_sha256"] and "object_sha256" in sources["evidence_sha256"]
    assert "verifications/" in sources["v_signature"]
    # 不适用那两格也要说清为什么（空串不是"缺"，是判据说过的取值）
    assert "不适用" in sources["lean_target"]


# ============================================================ b 缺 lean_file：点名 + 同一句话

def test_b_a_missing_credential_cell_is_named_in_the_criterions_own_words(tmp_path) -> None:
    """b：缺 `lean_file` ⇒ problems 点名那一格，且 why 与 `_lean_problems` 的 detail 逐字相同。"""
    root = _scene(tmp_path, row_over={"lean_file": ""})
    got = _reading(root)

    assert got["ok"] is False, "缺一格却判齐了"
    assert "lean_file" in _cells_of(got["problems"]), got["problems"]

    # 判据原话（同一个函数、同一份台账）：工具里那一条必须逐字等于它
    rows, problems = PM.parse_rows(json.loads(
        (PM.package_dir(root) / PM.MAPPING_JSON_NAME).read_text(encoding="utf-8")))
    assert not problems, problems
    ledger = PM.read_ledger_tables(root)
    judged = [item for item in PM._lean_problems(
        rows, PM.package_dir(root), root, ledger)
        if str(item.get("kind")) == "mapping_lean_missing"]
    assert judged, "夹具前提：判据真的报了 mapping_lean_missing"
    want = str(judged[0]["detail"])
    hits = [item for item in got["problems"]
            if item["cell"] == "lean_file" and item["why"] == want]
    assert hits, ("工具里那条不是判据原话：\n"
                  f"判据：{want}\n工具：{got['problems']}")
    # 值本身仍然取得到（工具的价值：告诉 G 该填什么），但"当前这一行缺它"照样点名
    assert got["cells"]["lean_file"] == SPEC.PROGRAM


# ============================================================ c sha 抄错：报不符、仍给现算值

def test_c_a_copied_sha_that_does_not_match_the_disk_is_reported(tmp_path) -> None:
    """c：`evidence_sha256` 抄错 ⇒ problems 报"不符"，交回的仍是现算值，且不当通过。"""
    root = _scene(tmp_path, row_over={"evidence_sha256": "0" * 64})
    got = _reading(root)

    assert got["ok"] is False, "抄错的 sha 居然判过了"
    assert "evidence_sha256" in _cells_of(got["problems"]), got["problems"]
    assert any("不符" in item["why"] for item in got["problems"]
               if item["cell"] == "evidence_sha256"), got["problems"]
    # 不许静默用抄来的数：cells 里必须是盘上现算的那一份
    assert got["cells"]["evidence_sha256"] == _note_sha() != "0" * 64
    assert "现算" in got["sources"]["evidence_sha256"]


# ============================================================ d 没有签：点名，不许空串冒充

def test_d_a_row_that_claims_a_sign_without_one_is_flagged(tmp_path) -> None:
    """d：表里写了 `v_signature` 而台账里没有那一签 ⇒ 点名 v_signature（不拿空串冒充）。"""
    root = _scene(tmp_path, sign=False)
    got = _reading(root)

    assert got["ok"] is False, "没有任何签却判齐了"
    assert "v_signature" in _cells_of(got["problems"]), got["problems"]
    # 这一格拿不到就不交（不是给一个 "" 或表里抄来的值）
    assert "v_signature" not in got["cells"], got["cells"]
    assert any("没有 V 的签" in item["why"] for item in got["problems"]
               if item["cell"] == "v_signature"), got["problems"]

    # 反真空：把那一签补上 ⇒ 同一现场这一格就取得到（否则上面那条可能是恒真的）
    _write_sign(root, sha=_note_sha())
    again = _reading(root)
    assert again["cells"].get("v_signature") == {"verdict": "成立", "sha256": _note_sha()}


# ============================================================ e 反真空：通道只调那一处

def test_e_stubbing_proof_channel_falls_back_to_the_old_shape(monkeypatch, tmp_path) -> None:
    """e：把 `numericproof.proof_channel` 打桩成恒空 ⇒ channel 与凭据格清单回落到旧形态。"""
    root = _scene(tmp_path)
    base = _reading(root)
    assert base["channel"] == NP.PROOF_CHANNEL_NUMERIC
    assert base["cells"]["lean_file"] == SPEC.PROGRAM

    monkeypatch.setattr(NP, "proof_channel", lambda *args, **kwargs: "")
    got = _reading(root)

    # 通道没了：凭据那两格按"空通道"填（不适用），不再把证明栏那份 .py 塞进 lean_file
    assert got["channel"] == "", got["channel"]
    assert got["cells"]["lean_file"] == ""
    assert got["cells"]["lean_target"] == ""
    assert "不适用" in got["sources"]["lean_file"]
    assert got["cells"].get("lean_file") != SPEC.PROGRAM
    # 这一条打桩只影响"通道"这一处判据：数值那两格仍由 `is_numeric_row` 判
    # （通道判不出来，但证明栏第 ① 段就是那份程序）—— 证明通道清单不是这里另写的一套
    assert got["cells"]["numeric_evidence"] == f"exp:{SPEC.EID}"


# ============================================================ f 只读

def test_f_the_tool_is_read_only_and_writes_nothing(registry, tmp_path) -> None:
    """f：工具面里有它、写集里没有它；它对盘上 `data/` 一个字节都不写。"""
    surface = {spec.name: spec for spec in registry.for_role("G")}
    assert "doc.mapping_cells" in surface, sorted(surface)
    spec = surface["doc.mapping_cells"]
    assert spec.side_effect == "read", spec.side_effect
    assert spec.declared_external == "none", spec.declared_external
    writes = [name for name, one in surface.items()
              if one.side_effect in SIDE_EFFECTS_WRITE]
    assert "doc.mapping_cells" not in writes, writes
    assert spec.needs_approval is False

    # 探针：同一现场调一次，`data/` 下每个文件的内容与 mtime 都不许变
    root = _scene(tmp_path)
    data = root / "data"
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
              for path in sorted(data.rglob("*")) if path.is_file()}
    got = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)
    assert got["checked"] is True
    after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
             for path in sorted(data.rglob("*")) if path.is_file()}
    assert set(before) == set(after)
    changed = [str(path) for path in before if before[path] != after[path]]
    assert changed == [], f"只读工具改了盘上的台账：{changed}"


# ============================================================ g 与既有判据同一个答案

def test_g_the_tool_never_says_clean_where_the_mapping_criterion_rejects(tmp_path) -> None:
    """g：同一现场 —— 工具说"齐"而 `mapping_reading` 判拒 ⇒ 这条红。"""
    scenes = {
        "clean": ({}, True),
        "no_lean_file": ({"lean_file": ""}, True),
        "wrong_sha": ({"evidence_sha256": "0" * 64}, True),
        "program_missing": ({"file": "code/not-there.py", "lean_file": "code/not-there.py"}, True),
        "no_evidence": ({"numeric_evidence": ""}, True),
        "no_sign": ({}, False),
    }
    seen_clean = False
    seen_red = False
    for name, (over, sign) in scenes.items():
        root = _scene(tmp_path / name, row_over=over, sign=sign)
        tool = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)
        paper = PM.mapping_reading(root, workspace_root=root)
        if tool["ok"]:
            seen_clean = True
            # 工具说"齐" ⇒ papermapping 那条判据也必须说 pass（两条读数不许两个答案）
            assert paper["state"] == "pass", (
                f"{name}：工具说齐了，papermapping 却判 {paper['state']}："
                f"{[p.get('kind') for p in paper['problems']]}")
        if paper["state"] != "pass":
            seen_red = True
            assert tool["ok"] is False, (
                f"{name}：papermapping 判 {paper['state']}，工具却说齐了 —— "
                f"{[p.get('kind') for p in paper['problems']]}")
    # 反真空：这一组里既要有"两边都绿"、也要有"两边都红"的现场，否则对比是空的
    assert seen_clean and seen_red, (seen_clean, seen_red)


# ============================================================ 形式化那一档：声明名来自 .lean

#: 一份只有一条顶层声明的 Lean 源码（`lean_target` 从它里面列出来）。
LEAN_SOURCE = "namespace Demo\n\ntheorem main_result : True := trivial\n\nend Demo\n"

#: 形式化通道的正文：一条定理 + 紧跟的证明环境。
FORMAL_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\begin{theorem}\\label{thm:formal}\n"
    "The walk converges.\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "Checked by the proof assistant.\n"
    "\\end{proof}\n"
    "\\end{document}\n"
)


def _formal_scene(tmp_path: pathlib.Path) -> pathlib.Path:
    """一个形式化通道的现场：正文是自然语言证明，形式化那一行在 `experiments` 里。

    刻意不让 `proof_text` 本身就是 `.lean` 路径：那种写法 `proof_channel` 会直接判成
    formal（`is_lean_path`），`is_numeric_row` 于是也说"不是数值定理"（`file` 要写成
    仓库根相对）。这一条要测的是 formal 通道那两格，所以走正常的形态 —— 证明正文是
    散文、`.lean` 落在 `experiments` 的 `code_path`（`numericproof.formal_slot` 的 formal 支路）。
    """
    root = pathlib.Path(tmp_path) / "ws"
    root.mkdir(parents=True)
    store = Store(root)
    store.init()
    for table, table_rows in (
        ("statements", [{
            "stmt_id": SPEC.SID, "origin": "own_result", "kind": "theorem",
            "statement_text": "The walk converges", "statement_full": "The walk converges.",
            "proof_text": "The walk converges: every step shrinks the distance by half.",
            "evidence_kind": "proof",
            "bits": {"numeric": "none", "formal": "signed", "reviewed": "none",
                     "proof": "none", "audited": "none"},
            "status": "active",
        }]),
        ("experiments", [{
            "experiment_id": SPEC.EID, "claim": "The walk converges",
            "claim_key": f"stmt:{SPEC.SID}", "method": "formal", "evidence_kind": "proof",
            "result": "supports", "code_path": "code/formal/000001.lean",
            "verifier_output": "checked", "observations": {},
        }]),
    ):
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = {"rows": table_rows}
        path.write_bytes((json.dumps(doc, ensure_ascii=False, indent=2)
                          + "\n").encode("utf-8"))
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / "main.tex").write_bytes(FORMAL_TEX.encode("utf-8"))
    lean = root / "code" / "formal" / "000001.lean"
    lean.parent.mkdir(parents=True, exist_ok=True)
    lean.write_bytes(LEAN_SOURCE.encode("utf-8"))
    row = {
        "kind": "theorem", "label": "thm:formal", "env_no": 1,
        "ledger_id": f"stmt:{SPEC.SID}", "proof_no": 1, "file": "main.tex",
        "lean_file": "code/formal/000001.lean", "lean_target": "main_result",
        "citation_loc_reason": "我方自产命题，没有外部引文",
    }
    _write_row(root, row)
    return root


def test_h_a_formal_row_gets_its_declaration_name_from_the_lean_source(tmp_path) -> None:
    """形式化那一档：`lean_file` 是那份 `.lean`，`lean_target` 是源码里那个声明名。"""
    root = _formal_scene(tmp_path)
    got = PM.mapping_cells(root, workspace_root=root, statement_id=SPEC.SID)

    assert got["channel"] == NP.PROOF_CHANNEL_FORMAL, got
    assert got["cells"]["lean_file"] == "code/formal/000001.lean"
    assert got["cells"]["lean_target"] == "main_result"
    assert "000001.lean" in got["sources"]["lean_target"]
    # 理论行的 `file` 是正文里那个环境所在的包内文件（不是仓库根相对的）
    assert got["cells"]["file"] == "main.tex"
    assert "main.tex:" in got["sources"]["file"]
    assert got["ok"] is True, got["problems"]


# ============================================================ 工具层的接线（成功/失败两态）
def test_the_tool_face_carries_the_cells_back_in_both_states(tmp_path) -> None:
    """注册后的调用：干净现场走 `ok`，缺格现场走 `ok=False` 且逐格读数照样带回。"""
    root = _scene(tmp_path)
    store = Store(root)
    store.init()
    surface = build_registry(store=store, workspace_root=root, roles=("G",),
                             strict=True).registry
    res = surface.call("doc.mapping_cells", role="G", project=".",
                       statement_id=SPEC.SID)
    assert res.ok, (res.error, res.meta)
    assert res.data["cells"]["file"] == SPEC.PROGRAM

    _write_row(root, {**SPEC._row(), "lean_file": ""})
    res2 = surface.call("doc.mapping_cells", role="G", project=".",
                        statement_id=f"stmt:{SPEC.SID}")
    assert not res2.ok, "缺一格却回了 ok"
    assert res2.meta.get("kind") == "mapping_cells_incomplete", res2.meta
    assert "lean_file" in [item["cell"] for item in res2.meta["problems"]]
    # 失败读数里那两栏照样带回来：`cells` 是"该填什么"（这里仍取得到），`problems` 是
    # "现在这一行为什么不算齐" —— 两件事分开，读的人不用猜
    assert res2.meta["cells"]["lean_file"] == SPEC.PROGRAM
    assert res2.meta["channel"] == NP.PROOF_CHANNEL_NUMERIC
