# -*- coding: utf-8 -*-
"""D-69：论文对应表要自己暴露"论文说定理 / 台账说猜想 / V 签没签"，并把抬档那条链接上。

## 现场（`projects/sylow3`，只读复算）

```
projects/sylow3/out/paper/MAPPING.json 五行，机械上都对（label 在 main.tex 里都在、
env 与台账 label 对得上）：thm:path1→stmt:000003、lem:center→stmt:000004、
lem:fixed→stmt:000005、thm:path2→stmt:000006、thm:path3→stmt:000000
```

两处落差：

1. `stmt:000004` / `000005` / `000006` 的台账 `kind` 仍是 `conjecture`
   （`evidence_kind="cross_check"`），而论文里排成 lemma / lemma / theorem
   ⇒ 对应表没说谎，但它没让这个落差可见（表里只有"论文里排成什么"，没有"台账说是什么"）；
2. 五行实际 `bits.evidence.reviewed_by_proof={"1": true}`、V 判决全是「成立」，
   而表里没有"V 签没签"这一格。

## 判据（六条，每条都写明"改前红在哪"）

| # | 判据 | 改前红在哪 |
|---|---|---|
| a | 对应表每行带 `ledger_kind`，且与台账里那一行的 `kind` 逐条相等 | 表里根本没有这一格（只有论文侧的 `kind`） |
| b | 每行带 `reviewed`（已签 / 没签 / 未读到），且与 `reviewed_by_proof` 逐条相等 | 同上：表里没有 V 那一格，`reviewed_by_proof` 只在命题目录里 |
| c | 三份文件（json / md / 附录 tex）三处同源：同一行同两格逐字一致 | 两格不存在，谈不上一致 |
| d | 落差读数：论文 env=theorem/lemma 而行 kind=conjecture ⇒ 报一条读数并点名 label → stmt | 没有任何一格报这件事（对应表三态只看"表与正文对不对得上"） |
| e | 抬档：V 落「成立」⇒ 同一笔事务里该行 `kind` 由 conjecture 变 theorem，且读数写明依据 | V 那一签只翻第 3 位；`kind` 要等"同一份内容再交一次"才抬，而没人会回头做 |
| f | 反真空：把 ① 的填充打桩成空 ⇒ a 红；把 ③ 的抬档打桩成空 ⇒ e 红；台账读不到 ⇒ `未读到`（不是 `没签`） | 三条判据本身不存在，反真空无从谈起 |

全部用例都在 `tmp_path` 下自建工作区，一个模型调用都不发（零模型钱）。

## 与 D-37 的关系（口径变化只在一处，写在 `tests/test_d37_kind_follows_grade.py`）

D-37 已经有"`kind` 该不该跟着证据升"的唯一判据（`evidencebits.kind_following_grade`），
它的两个写侧落点都不在"V 签字"这条路上（秘书那一支只在"同一份内容再交一次"时跑，
B 那一格只在第 4 位同步出变化时跑）。D-69 把这一格接到签名那一笔事务里，判据一个字
没变 —— 变的只是"什么时候写"。
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.store import Store

#: 中文正文（"中文论文"那一档：附录按论文语言出中文，于是三份文件的两格逐字可比）。
#: 五条环境与五条台账行一一对上（lemma 两条、theorem 两条、experiment 一条）。
ZH_TEX = (
    "\\documentclass[11pt]{ctexart}\n"
    "\\begin{document}\n"
    "\\section{主结果}\n"
    "本文给出一个自足的证明：对每个整数，下面这条引理都成立，理由逐条写在后面。\n"
    "证明按归纳进行，每一步都由前一步推出，读者可以逐行检查这里写下的每一步。\n"
    "讨论与开放问题放在最后一节，边界与反例在那里逐条说明，这里不再重复叙述。\n"
    "\\begin{lemma}\\label{lem:signed}\n"
    "第一条引理（台账里还只是猜想）。\n"
    "\\end{lemma}\n"
    "\\begin{theorem}\\label{thm:other}\n"
    "第二条定理（台账里写的是 lemma）。\n"
    "\\end{theorem}\n"
    "\\begin{lemma}\\label{lem:unsigned}\n"
    "第三条引理（V 没签）。\n"
    "\\end{lemma}\n"
    "\\begin{theorem}\\label{thm:nosig}\n"
    "第四条定理（逐份签名表里没有这一份 ⇒ 未读到）。\n"
    "\\end{theorem}\n"
    "\\begin{experiment}\\label{exp:scan}\n"
    "一条实验（不算「排成定理」，不进落差读数）。\n"
    "\\end{experiment}\n"
    "\\end{document}\n"
)

#: 一条证明正文（V 签的就是它；`proof_sha256` 按它现算）。
PROOF = "对 n 作归纳：基例显然，归纳步由前一步推出，故命题成立。"


def _signed_bits(*, proof_no: int = 1, verdict: str = "成立") -> dict:
    """一条"V 已签"的 `bits`（与 `verifications._reviewed_statement_row` 落的形状一致）。"""
    return {
        "numeric": "na", "proof": True, "reviewed": True, "formal": "na", "audited": False,
        "origin": "own_result",
        "evidence": {
            "numeric_reason": "这一条不做数值验证",
            "proof_process": PROOF,
            "proof_source": "own",
            "reviewed_by": {"verifier": "agent-V", "verification_id": "v-000001",
                            "verdict": verdict, "proof_no": int(proof_no),
                            "proof_sha256": VR.proof_sha(PROOF),
                            "evidence": "verifications/000001.jsonl#v-000001"},
            "reviewed_by_proof": {str(int(proof_no)): True},
            "reviewed_sha_by_proof": {str(int(proof_no)): VR.proof_sha(PROOF)},
        },
    }


#: 台账里那四行命题（D-69 的两个现场各占一条）：
#:
#: - `000001`：`kind="conjecture"` 而 V 已签「成立」⇒ 论文里排成 lemma（落差 ① 的现场）；
#: - `000002`：`kind="lemma"`、V 已签 ⇒ 与论文的 theorem 对不上（这一条不进落差读数：
#:   业主的读数只管"台账仍是 conjecture"那一档）；
#: - `000003`：`kind="conjecture"`、逐份签名表为假 ⇒ 论文里排成 lemma 而 V 没签；
#: - `000004`：`kind="lemma"`、`bits` 里根本没有逐份签名表 ⇒ 那一格"未读到"。
LEDGER_STATEMENTS: list[dict] = [
    {"stmt_id": "000001", "kind": "conjecture", "origin": "own_result",
     "statement_text": "第一条引理", "proof_text": PROOF, "bits": _signed_bits()},
    {"stmt_id": "000002", "kind": "lemma", "origin": "own_result",
     "statement_text": "第二条定理", "proof_text": PROOF, "bits": _signed_bits()},
    {"stmt_id": "000003", "kind": "conjecture", "origin": "own_result",
     "statement_text": "第三条引理", "proof_text": PROOF,
     "bits": {"numeric": "na", "proof": True, "reviewed": False, "formal": "na",
              "audited": False, "origin": "own_result",
              "evidence": {"proof_process": PROOF, "proof_source": "own",
                           "reviewed_by_proof": {"1": False}}}},
    {"stmt_id": "000004", "kind": "lemma", "origin": "own_result",
     "statement_text": "第四条定理", "proof_text": PROOF,
     "bits": {"numeric": "na", "proof": True, "reviewed": False, "formal": "na",
              "audited": False, "origin": "own_result",
              "evidence": {"proof_process": PROOF, "proof_source": "own"}}},
]

#: 对应表那五行（`ledger_kind` / `reviewed` 一律不填：写侧按台账现读现填）。
ROWS: list[dict] = [
    {"kind": "lemma", "label": "lem:signed", "env_no": 1,
     "ledger_id": "stmt:000001", "proof_no": 1, "file": "main.tex",
     "citation_loc_reason": "own result：完整证明就在本文第 3 节，没有外部引文可定位"},
    {"kind": "theorem", "label": "thm:other", "env_no": 1,
     "ledger_id": "stmt:000002", "proof_no": 1, "file": "main.tex",
     "citation_loc_reason": "own result：完整证明就在本文第 3 节，没有外部引文可定位"},
    {"kind": "lemma", "label": "lem:unsigned", "env_no": 2,
     "ledger_id": "stmt:000003", "proof_no": 1, "file": "main.tex",
     "citation_loc_reason": "own result：完整证明就在本文第 3 节，没有外部引文可定位"},
    {"kind": "theorem", "label": "thm:nosig", "env_no": 2,
     "ledger_id": "stmt:000004", "proof_no": 1, "file": "main.tex",
     "citation_loc_reason": "own result：完整证明就在本文第 3 节，没有外部引文可定位"},
    {"kind": "experiment", "label": "exp:scan", "env_no": 1,
     "ledger_id": "exp:000001", "proof_no": 1, "file": "main.tex"},
]

#: 这三行按台账现读出来该是什么（`(ledger_kind, reviewed)`）。
EXPECTED_CELLS: dict[str, tuple[str, str]] = {
    "lem:signed": ("conjecture", "已签（判决：成立）"),
    "thm:other": ("lemma", "已签（判决：成立）"),
    "lem:unsigned": ("conjecture", "没签"),
    "thm:nosig": ("lemma", "未读到"),
    # 实验行：`experiments` 表没有 `kind` 这一列 ⇒ 这一格是"未读到"（不是"不是定理"）。
    "exp:scan": ("未读到", "未读到"),
}


# ------------------------------------------------------------------ 夹具

def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(root: pathlib.Path, *,
               statements: list[dict] | None = None,
               rows: list[dict] | None = ROWS,
               write_package: bool = True) -> pathlib.Path:
    """造一个工作区：台账三张表 + 中文正文 + 对应表三份（走 `write_package` 那个写口）。

    `write_package=False` 时不写表（用来量"写侧根本没填"那一档）。
    """
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    for table, table_rows in (("statements",
                               LEDGER_STATEMENTS if statements is None else statements),
                              ("experiments", [{"experiment_id": "000001",
                                                "method": "numeric",
                                                "evidence_kind": "heuristic"}]),
                              ("relations", [{"relation_id": "000001"}])):
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(row) for row in table_rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PM.PC.TEX_NAME).write_bytes(ZH_TEX.encode("utf-8"))
    if write_package:
        PM.write_package(root, [PM.Row(**dict(row)) for row in (rows or [])],
                         workspace_root=root)
    return root


def _json_rows(root: pathlib.Path) -> list[dict]:
    path, _md = PM.mapping_paths(root)
    return list(json.loads(path.read_text(encoding="utf-8"))["rows"])


def _md_cells(root: pathlib.Path) -> dict[str, dict[str, str]]:
    """md 里每一行那两格（按表头找列号，不按位置猜）。"""
    _json_path, md_path = PM.mapping_paths(root)
    lines = md_path.read_text(encoding="utf-8").splitlines()
    header = [line for line in lines if line.startswith("| # |")]
    assert len(header) == 1, lines[:5]
    columns = [cell.strip() for cell in header[0].strip().strip("|").split("|")]
    label_at = columns.index("label")
    kind_at = columns.index(PM.LEDGER_KIND_FIELD)
    reviewed_at = columns.index(PM.REVIEWED_FIELD)
    out: dict[str, dict[str, str]] = {}
    for line in lines:
        if not line.startswith("| ") or line.startswith("| # |") or line.startswith("|---"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        out[cells[label_at]] = {PM.LEDGER_KIND_FIELD: cells[kind_at],
                                PM.REVIEWED_FIELD: cells[reviewed_at]}
    return out


def _appendix_cells(root: pathlib.Path) -> dict[str, dict[str, str]]:
    """附录里每一行那两格（取 `MAPPING-ROW` 那条机器可读注释的最后两格）。"""
    block = PM.appendix_path(root).read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {}
    for line in block.splitlines():
        text = line.strip()
        if not text.startswith(PM.APPENDIX_ROW_PREFIX.strip()):
            continue
        parts = text[len(PM.APPENDIX_ROW_PREFIX.strip()):].strip().split("|")
        out[parts[2]] = {PM.LEDGER_KIND_FIELD: parts[-2], PM.REVIEWED_FIELD: parts[-1]}
    return out


def _ledger_kind(root: pathlib.Path, stmt_id: str) -> str:
    path = pathlib.Path(root) / "data" / str(S.TABLES["statements"]["file"])
    for row in json.loads(path.read_text(encoding="utf-8"))["rows"]:
        if str(row.get("stmt_id") or "") == stmt_id:
            return str(row.get("kind") or "")
    return ""


def _ledger_kind_problems(root: pathlib.Path) -> list[str]:
    """判据 a 的本体：每行的 `ledger_kind` 与台账里那一行相等（空清单 = 都相等）。

    抽成函数是为了让反真空那一条打同一份判据：`fill_ledger_cells` 一打桩成空，
    它必须报出问题 —— 否则"a 绿"可能只是"这一条断言从没真的比过"。
    """
    problems: list[str] = []
    for row in _json_rows(root):
        if PM.LEDGER_KIND_FIELD not in row:
            problems.append(f"{row.get('label')}：这一行没有 {PM.LEDGER_KIND_FIELD} 那一格")
            continue
        got = str(row[PM.LEDGER_KIND_FIELD])
        if not got:
            problems.append(f"{row.get('label')}：台账 kind 是空的（空不许等于没问题）")
            continue
        row_id = str(row["ledger_id"]).split("#")[0]
        want = (PM.LEDGER_CELL_UNREADABLE
                if row_id.startswith("exp:") else _ledger_kind(root, row_id.replace("stmt:", "")))
        if got != want:
            problems.append(f"{row.get('label')}：表里 {got!r}，台账 {want!r}")
    return problems


def _upgrade_problems(row: dict, sid: str) -> list[str]:
    """判据 e 的本体：V 判成立之后 `kind` 是 theorem 且留痕写明依据（空清单 = 都对）。

    与 `_ledger_kind_problems` 同一个理由抽成函数：反真空那一条要打桩之后打同一份判据。
    """
    problems: list[str] = []
    if str(row.get("kind") or "") != "theorem":
        problems.append(f"kind 仍是 {row.get('kind')!r}（V 判成立之后应当抬成 theorem）")
    trace = dict(row.get("_kind_upgrade") or {})
    if (trace.get("from"), trace.get("to")) != ("conjecture", "theorem"):
        problems.append(f"升档留痕不对：{trace.get('from')!r} → {trace.get('to')!r}")
    if f"verifications/{sid}.jsonl#v-" not in str(trace.get("basis") or ""):
        problems.append(f"升档依据没有点名那一签：{trace.get('basis')!r}")
    return problems


# ------------------------------------------------------------------ a 台账 kind 那一格

def test_a_every_row_carries_the_ledger_kind(tmp_path: pathlib.Path) -> None:
    """a) 每行带 `ledger_kind`，且与台账里那一行的 `kind` 逐条相等。

    改前红：`MAPPING.json` 的每一行只有论文侧的 `kind`（"排成什么环境"），没有
    "台账说这一条是什么" —— 于是 sylow3 那三行（论文 lemma / 台账 conjecture）
    在表上完全看不出来。
    """
    root = _workspace(tmp_path / "ws")
    rows = _json_rows(root)
    assert len(rows) == len(ROWS), rows
    assert _ledger_kind_problems(root) == [], _ledger_kind_problems(root)
    # 逐条点名：这一条夹具真的同时含"台账说猜想"与"台账说引理"两档。
    assert [r[PM.LEDGER_KIND_FIELD] for r in rows] == [v[0] for v in EXPECTED_CELLS.values()]


# ------------------------------------------------------------------ b V 那一格

def test_b_every_row_carries_the_signature_verdict(tmp_path: pathlib.Path) -> None:
    """b) 每行带 `reviewed`（已签 / 没签 / 未读到），且与 `reviewed_by_proof` 逐条相等。

    改前红：表里没有 V 那一格。`reviewed_by_proof` 只在命题目录的 `bits` 里，
    读论文的人（H / 业主 / B）看不到"这一行签没签"。
    """
    root = _workspace(tmp_path / "ws")
    rows = _json_rows(root)
    got = {str(r["label"]): str(r[PM.REVIEWED_FIELD]) for r in rows}
    want = {label: cells[1] for label, cells in EXPECTED_CELLS.items()}
    assert got == want, (got, want)


# ------------------------------------------------------------------ c 三份同源

def test_c_the_three_files_agree_verbatim(tmp_path: pathlib.Path) -> None:
    """c) json / md / 附录 tex 三处同源：同一行同两格逐字一致。

    比的是三份文件里那两格的字面：json 的两个键、md 的两列、附录 `MAPPING-ROW`
    注释的最后两格。附录是中文论文那一档（`paper_language` 读到 `zh`），所以
    D-45 的语言那一层不参与比较 —— 英文论文里这两格按语言出词，那是既有口径
    （`_LEDGER_CELL_TEXT`），不在这里比字面。
    """
    root = _workspace(tmp_path / "ws")
    assert PM.paper_language(root) == PM.PAPER_LANGUAGE_ZH
    json_cells = {str(r["label"]): {PM.LEDGER_KIND_FIELD: str(r[PM.LEDGER_KIND_FIELD]),
                                    PM.REVIEWED_FIELD: str(r[PM.REVIEWED_FIELD])}
                  for r in _json_rows(root)}
    md_cells = _md_cells(root)
    tex_cells = _appendix_cells(root)
    assert set(json_cells) == set(md_cells) == set(tex_cells), (
        set(json_cells), set(md_cells), set(tex_cells))
    for label in json_cells:
        assert md_cells[label] == json_cells[label], (label, "md", md_cells[label],
                                                      json_cells[label])
        assert tex_cells[label] == json_cells[label], (label, "附录", tex_cells[label],
                                                       json_cells[label])
    # 读侧认这一份附录是"与 json 一致的"（三份不只是字面一样，判据也认）。
    tex = (PM.package_dir(root) / PM.PC.TEX_NAME).read_text(encoding="utf-8")
    state, problems = PM._appendix_reading(root, tex, PM.parse_rows(
        {"rows": _json_rows(root)})[0])
    assert (state, problems) == ("present", []), (state, problems)


# ------------------------------------------------------------------ d 落差读数

def test_d_the_gap_is_reported_and_named(tmp_path: pathlib.Path) -> None:
    """d) 论文 env=theorem/lemma 而台账 kind=conjecture ⇒ 报一条读数并点名 label → stmt。

    这一条同时量另一半：论文里排成定理而 V 没签的那一行，以及"签没签读不到"那一行
    单列（三态：读不到不算"没签"）。两条都不拦门：`state` 不是它们说了算的。
    """
    root = _workspace(tmp_path / "ws")
    reading = PM.mapping_reading(root)
    gaps = reading["kind_gap"]
    assert gaps["count"] == 2, gaps
    named = [f"{it['label']} → {it['ledger_id']}" for it in gaps["items"]]
    assert named == ["lem:signed → stmt:000001", "lem:unsigned → stmt:000003"], named
    assert "论文里以 theorem/lemma 环境出现" in str(gaps["why"]), gaps["why"]
    for item in gaps["items"]:
        assert item["ledger_kind"] == "conjecture", item
        assert item["env_kind"] in PM.THEOREM_ENV_KINDS, item

    unsigned = reading["theorem_unsigned"]
    assert unsigned["count"] == 1, unsigned
    assert [it["label"] for it in unsigned["items"]] == ["lem:unsigned"], unsigned
    assert "论文里排成定理但 V 没签" in str(unsigned["why"]), unsigned["why"]
    # "读不到"那一行单列，不算进"没签"。
    assert [it["label"] for it in unsigned["unreadable"]] == ["thm:nosig"], unsigned
    assert "V 签没签读不到" in str(unsigned["why"]), unsigned["why"]

    # 两条读数都进了 `reason`（成文/收工那一句读得到），且都不在 `problems` 里。
    assert "落差读数" in str(reading["reason"]), reading["reason"]
    assert reading["kind_gap"]["count"] not in (None, ""), reading["kind_gap"]
    kinds = [str(p.get("kind") or "") for p in reading["problems"]]
    assert "kind_gap" not in kinds and "theorem_unsigned" not in kinds, kinds
    # 实验那一行不进这两条读数（"排成定理"这句话说的是 theorem/lemma 这两个环境名）。
    assert all(it["label"] != "exp:scan" for it in gaps["items"] + unsigned["items"])


# ------------------------------------------------------------------ e V 落成立 ⇒ 抬档

#: 一条"按猜想落库"的命题（真机 B 的登记参数形状；与 D-37 的夹具同源）。
FULL = "对任意整数 n≥0：1^3 + 2^3 + … + n^3 = (n(n+1)/2)^2。"


def _own(**kw) -> dict:
    base = {"statement_full": FULL, "statement_text": "sum-of-cubes", "label": "sum-of-cubes",
            "origin": "own_result", "kind": "conjecture", "doc_id": S.format_id(0),
            "line_range": {"start": 1}, "quote_verified": False,
            "quote_reason": "own_result：我方推导，没有第二份文本可比对",
            "proof_text": PROOF}
    base.update(kw)
    return base


def _signed_row(tmp_path: pathlib.Path, **kw) -> tuple[Store, str, dict]:
    """按猜想登记一条命题，再让 V 判「成立」（`record_verification` 是 V 的写入口）。"""
    store = Store(tmp_path / "sig")
    store.init()
    filed = AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        **_own(**kw))
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])
    out = VR.record_verification(store.root, statement_id=sid, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 verifier="agent-V", store=store)
    assert out.get("checked") is True and out.get("verdict") == "成立", out
    row = [dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid][0]
    return store, sid, row


def test_e_a_signed_conjecture_becomes_a_theorem_in_the_same_write(
        tmp_path: pathlib.Path) -> None:
    """e) V 落「成立」⇒ 同一笔事务里该行 `kind` 由 conjecture 变 theorem，读数写明依据。

    改前红：V 那一签只翻第 3 位（`bits.reviewed` / `reviewed_by_proof`），`kind` 那一格
    要等"同一份内容再交一次"才抬（秘书那一支）—— 而没有人会回头做那一步，于是
    sylow3 那三行到今天还是 `conjecture`，论文却已经把它们排成 lemma / theorem。

    三态的另一半也在这里：判不了（凭据不够）就不抬，且读数不许说"已抬"。
    """
    store, sid, row = _signed_row(tmp_path)
    assert _upgrade_problems(row, sid) == [], _upgrade_problems(row, sid)
    trace = dict(row.get("_kind_upgrade") or {})
    assert trace.get("from") == "conjecture" and trace.get("to") == "theorem", trace
    assert f"verifications/{sid}.jsonl#v-" in str(trace.get("basis") or ""), trace
    # 第 3 位那一笔照旧（抬档没有拿"位"去冒充"签"）。
    bits = dict(row.get("bits") or {})
    assert bits.get("reviewed") is True, bits
    assert (bits.get("evidence") or {}).get("reviewed_by_proof") == {"1": True}, bits

    # 读数：签名入口把"因为哪一签而抬"写在返回里（不是只在盘上悄悄改一格）。
    out = VR.record_verification(store.root, statement_id=sid, proof_text=PROOF,
                                 verdict={"verdict": "成立", "findings": []},
                                 verifier="agent-V", store=store)
    writeback = dict(out.get("statement_writeback") or {})
    # 已经是 theorem ⇒ 起点不再是 conjecture ⇒ 这一笔不重复抬（三态：不适用范围不写）。
    assert writeback.get("kind_upgrade") in ({}, None), writeback


def test_e2_a_rejected_verdict_does_not_lift_anything(tmp_path: pathlib.Path) -> None:
    """e) 的另一半（反真空）：V 判「有毛病」⇒ `kind` 一个字节不动。

    "反正都会升"是这一批最危险的假绿：如果抬档不挂在"成立"上，上面那条绿就是白给。
    """
    store = Store(tmp_path / "rej")
    store.init()
    filed = AgentB(store, extractor=None, extract_text=None, config={}).register_statement(
        **_own())
    sid = str(filed["stmt_id"])
    out = VR.record_verification(
        store.root, statement_id=sid, proof_text=PROOF,
        verdict={"verdict": "有毛病", "defect_step": 2,
                 "findings": [{"level": "error", "step": 2, "kind": "gap",
                               "detail": "归纳步不成立"}]},
        verifier="agent-V", store=store)
    assert out.get("verdict") == "有毛病", out
    row = [dict(r) for r in store.rows("statements") if str(r.get("stmt_id")) == sid][0]
    assert row["kind"] == "conjecture", row
    assert "_kind_upgrade" not in row, row


# ------------------------------------------------------------------ f 反真空 + 三态

def test_f1_stubbing_the_fill_makes_a_red(tmp_path: pathlib.Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空（①）：把 `fill_ledger_cells` 打桩成"原样返回" ⇒ a 必红。

    打桩之后 json 里那两格是空的 ⇒ a（"每行带台账 kind 且与台账相等"）当场不成立。
    这一条挡的是"表里那两格只是碰巧填上了"那种假绿。
    """
    monkeypatch.setattr(PM, "fill_ledger_cells", lambda root, rows, **kw: list(rows))
    root = _workspace(tmp_path / "empty")
    rows = _json_rows(root)
    assert [str(r[PM.LEDGER_KIND_FIELD]) for r in rows] == [""] * len(ROWS), rows
    problems = _ledger_kind_problems(root)
    assert problems, "把填充打桩成空之后 a 仍然绿 ⇒ 那条断言没有真的比过"


def test_f2_stubbing_the_upgrade_makes_e_red(tmp_path: pathlib.Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    """f) 反真空（③）：把抬档那一格打桩成空 ⇒ e 必红（`kind` 停在 conjecture）。

    打的是 `verifications._kind_upgrade_from_signature` 这一个落点：它空了，
    "V 落成立 ⇒ kind 变 theorem"就不成立 —— 这正是改前那一版的行为。
    """
    monkeypatch.setattr(VR, "_kind_upgrade_from_signature",
                        lambda row, **kw: {"row": dict(row), "kind_upgrade": {}, "note": ""})
    _store, sid, row = _signed_row(tmp_path)
    problems = _upgrade_problems(row, sid)
    assert problems, "把抬档打桩成空之后 e 仍然绿 ⇒ 那条断言没有真的比过"
    assert row["kind"] == "conjecture", row
    assert "_kind_upgrade" not in row, row


def test_f3_an_unreadable_ledger_says_unread_not_unsigned(
        tmp_path: pathlib.Path) -> None:
    """f) 三态：台账读不到 ⇒ `reviewed = 未读到`，而且不是 `没签`。

    三种"读不到"各来一次：台账里没有那一行 / 逐份签名表里没有这一份 /
    判决原话那一格空。折成"没签"就等于把没查成报成一个关于 V 做过什么的结论。
    """
    missing_row = PM.ledger_cells(None, 1)
    assert missing_row[PM.REVIEWED_FIELD] == PM.LEDGER_CELL_UNREADABLE, missing_row
    assert missing_row[PM.REVIEWED_FIELD] != PM.REVIEWED_UNSIGNED_CELL
    assert missing_row[PM.LEDGER_KIND_FIELD] == PM.LEDGER_CELL_UNREADABLE, missing_row

    no_key = {"stmt_id": "000009", "kind": "lemma",
              "bits": {"evidence": {"reviewed_by_proof": {"2": True}}}}
    cells = PM.ledger_cells(no_key, 1)
    assert cells[PM.REVIEWED_FIELD] == PM.LEDGER_CELL_UNREADABLE, cells
    # 另一份签过不算这一份签过（不许借光）：那一份本身读得出来。
    assert PM.ledger_cells(no_key, 2)[PM.REVIEWED_FIELD].startswith("已签"), cells

    silent = {"stmt_id": "000010", "kind": "",
              "bits": {"evidence": {"reviewed_by_proof": {"1": True}}}}
    cells = PM.ledger_cells(silent, 1)
    # 签过、但判决原话那一格读不到 ⇒ 两件事分开写，都不折成"没签"。
    assert cells[PM.REVIEWED_FIELD] == "已签（判决：未读到）", cells
    assert cells[PM.LEDGER_KIND_FIELD] == PM.LEDGER_CELL_UNREADABLE, cells

    # 台账整个读不到时，写侧也照样把"未读到"写进三份文件（不许印成空白）。
    root = _workspace(tmp_path / "noledger", statements=[])
    rows = _json_rows(root)
    assert {str(r[PM.REVIEWED_FIELD]) for r in rows} == {PM.LEDGER_CELL_UNREADABLE}, rows
    md_cells = _md_cells(root)
    assert {c[PM.REVIEWED_FIELD] for c in md_cells.values()} == {
        PM.LEDGER_CELL_UNREADABLE}, md_cells


def test_f4_the_marker_sentence_survives(tmp_path: pathlib.Path) -> None:
    """边界：附录头那句"不要手改"仍在，且两格进了附录的机器可读注释。

    业主点名的边界是"三份同源渲染，附录头那句『不要手改』保留"。这一条把它钉住：
    加了两格之后，附录的第一行仍然是那句界标，而且它说的是同一件事。
    """
    root = _workspace(tmp_path / "ws")
    block = PM.appendix_path(root).read_text(encoding="utf-8")
    assert block.splitlines()[0] == PM.APPENDIX_BEGIN, block.splitlines()[:2]
    assert "do not edit by hand" in PM.APPENDIX_BEGIN
    keys = [line for line in block.splitlines()
            if line.strip().startswith(PM.APPENDIX_ROW_PREFIX.strip())]
    assert len(keys) == len(ROWS), keys
    for line in keys:
        assert line.count("|") >= 11, line
