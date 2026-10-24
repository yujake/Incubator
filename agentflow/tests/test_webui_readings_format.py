# -*- coding: utf-8 -*-
"""显示格式（业主 2026-10-23）：sha 只报一致 / 命题标注非平凡度 / 第 4 位按路径。

## 业主原话

> 「需要动 ui 侧对产物，台账，证据链等等的显示格式，这些都略有过时。
> （注：对于 sha 值用户并不关心，只用显示是否一致即可）。另外对于命题的显示要标注
> 非平凡度等级。」

## 五条判据

| # | 判据 | 负控（反真空） |
|---|---|---|
| ① | 页面读的那批字段里没有 sha 那一族，且它们的取值里没有 8 / 12 / 64 位十六进制；「一致 / 不一致 / unknown」三档词都在 | 给一个"读了 `sha256` 且值是一串 64 位十六进制"的人造页面 ⇒ 检查函数必须报 |
| ② | 命题列表里每一条都有 `T0`–`T4` 或"未判"；判不了的那一条 `level is None`、`label` 空 | 把"判不了"打桩成 `level=0` ⇒ 同一个检查函数必须报 |
| ③ | 台账按 `upserts` / `commit_markers` 两格显示（Home / Run / Artifacts 三页同一句），且不再有"事件 N 条"那种总行数口径 | 喂回改前那段源码 ⇒ 检查函数必须报 |
| ④ | 第 4 位按路径显示（`路径1 verified ｜ 路径2 pending`）、引文读数含 `no_evidence`、reviewed 按证明逐条 | 把逐路径读数折成一条汇总 ⇒ 逐路径那一支的用例必须红 |
| ⑤ | "sha 一致性"打桩成恒一致 ⇒ 不一致那一支的用例必红 | 它本身就是反真空 |

## 为什么"读源码 + 读后端读数"两头都验

与 `tests/test_webui_pages.py` 同一条理由：只验后端，页面可以不读那一格；只验源码，
源码里可以写着一个后端不存在的键。页面是客户端渲染的（本批不 build，收口统一
build），所以 Python 这一侧看不到 DOM —— "渲染出来的文本里没有 sha"这一侧的证据是
两条，合起来才成立：

1. 页面源码里出现的字段名里没有 sha 那一族（它拿不到哈希，就印不出哈希）；
2. 后端在这份工作区上给那批字段的值里没有十六进制 sha（有的话第 1 条也白搭）。

## 夹具

一份小工作区（`format_ws`）把五种形态一次造齐：两档真的档位 + 一条没判过 + 一条
旧刻度的"0"、一条 `no_evidence` 的引文、一条二维第 4 位（`#p1` verified / `#p2`
pending）、一条两条证明的验证台账、一个被改过的落盘文件、一个不在盘上的文件、
`code/exp/` 与 `out/experiments/000001/{design,exhaustion}.md`。
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from agentflow import evidencebits as EB
from agentflow import exhaustionreport as EX
from agentflow import schema as S
from agentflow import secretary as SEC
from agentflow import webui as W
from agentflow.store import Store
from agentflow.webui import readers as R

#: 交付包根（`agentflow/`）。
REPO = pathlib.Path(__file__).resolve().parents[1]
UI_SRC = REPO / "ui" / "src"

TS = "2026-10-23T00:00:00+08:00"

#: 命题正文（非平凡度台账按正文的 sha 折叠，所以夹具里这几句会被真写一遍台账）。
FULL_T0 = "对任意正整数 n，若 n 是偶数，则 n 的平方也是偶数。"
FULL_T2 = "每一个大于 2 的偶数都是两个素数之和。"
FULL_UNJUDGED = "还没判过档位的那一条。"
FULL_OLD_SCALE = "旧刻度的行。"
PROOF_P1 = "证明：设 n = 2k，则 n 的平方 = 4k^2 = 2(2k^2)，故为偶数。"


# ====================================================================== 造工作区
def _write_bytes(path: pathlib.Path, text: str) -> None:
    """按字节写一个文本文件（LF 行尾，不受 Windows 的换行翻译影响）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _write_json(path: pathlib.Path, doc: object) -> None:
    """写一个 JSON 文件（UTF-8、LF、末尾一个换行）。"""
    _write_bytes(path, json.dumps(doc, ensure_ascii=False, indent=2) + "\n")


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    """写一个 JSONL 文件（键排序，于是同样的输入逐字节同形）。"""
    _write_bytes(path, "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
                               for r in rows))


def _write_table(root: pathlib.Path, table: str, rows: list[dict]) -> None:
    """直接落一张 store 表的快照（`{"schema_version": …, "rows": [...]}`）。"""
    _write_json(root / "data" / str(S.TABLES[table]["file"]),
                {"schema_version": S.SCHEMA_VERSION, "rows": rows})


#: 第 4 位二维、第 3 位逐条的那一份位记录（`#p1` 验过并签过、`#p2` 还没做也没签）。
_BITS_PER_PATH: dict = {
    "numeric": "pending", "proof": True, "reviewed": True,
    "formal": {"1": "verified", "2": "pending"}, "audited": False,
    "evidence": {
        "formal_by_proof": {"1": {"checker": "lean4", "experiment_id": "000001"}},
        # 第 3 位按证明逐条的那张表（写侧是 `verifications.sign_statement`）：
        # 只签了 `#p1` ⇒ `#p2` 不许借它的光。
        "reviewed_by_proof": {"1": True, "2": False},
    },
}


def _format_ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """一份把五条判据要的形态一次造齐的小工作区（见文件头「夹具」那一节）。"""
    root = tmp_path / "ws"
    root.mkdir(parents=True)
    Store(root).init()
    _write_table(root, "statements", [
        # 1) 档位 T0 + 引文逐字通过 + 第 4 位是二维的（#p1 verified / #p2 pending）
        {"stmt_id": "000001", "origin": "own_result", "kind": "theorem",
         "statement_text": "偶数平方仍是偶数", "statement_full": FULL_T0,
         "proof_text": PROOF_P1, "quote_verified": True, "quote_mode": "verbatim",
         "quote_span": "p3:norm[10:40]", "created_by": "B", "created_at": TS,
         "bits": _BITS_PER_PATH},
        # 2) 档位 T2 + 引文 no_evidence（说通过，而盘上拿不出可复核的区间）
        {"stmt_id": "000002", "origin": "own_result", "kind": "theorem",
         "statement_text": "", "statement_full": FULL_T2, "proof_text": "",
         "quote_verified": True, "quote_mode": "verbatim", "quote_span": "",
         "created_by": "B", "created_at": TS},
        # 3) 档位台账里没有这一条 ⇒ 未判（不是 T0）
        {"stmt_id": "000003", "origin": "own_result", "kind": "theorem",
         "statement_text": "还没判过档位的那一条", "statement_full": FULL_UNJUDGED,
         "proof_text": "", "quote_verified": None, "created_by": "B", "created_at": TS},
        # 4) 旧刻度的行（没有 scale 标记、nontriviality 写 0）⇒ 也是未判，不是 T0
        {"stmt_id": "000004", "origin": "own_result", "kind": "theorem",
         "statement_text": "旧刻度的行", "statement_full": FULL_OLD_SCALE,
         "proof_text": "", "quote_verified": False, "quote_mode": "semantic",
         "created_by": "B", "created_at": TS},
    ])
    # 非平凡度台账：两行走唯一的写口，再手工补一行旧刻度（没有 `scale` 标记）。
    SEC.append_nontriviality(root, statement_full=FULL_T0, level=0, basis="平凡但真")
    SEC.append_nontriviality(root, statement_full=FULL_T2, level=2, basis="方法平凡、量大")
    with SEC.nontriviality_path(root).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"at": TS,
                                 "statement_sha256": SEC._statement_sha(FULL_OLD_SCALE),
                                 "nontriviality": 0, "label": "T0", "basis": "旧刻度"},
                                ensure_ascii=False, sort_keys=True) + "\n")
    # 实验：一个脚本在盘上（与台账的 sha 不符）、一个脚本不在盘上（没得比）；
    # 另有一条实验号成形的（`000001`）：它的穷举论证报告真的落在盘上
    # （`out/experiments/000001/exhaustion.md`）⇒ 证据链那张实验表要能链到它。
    _write_bytes(root / "code" / "exp" / "a.py", "print('x')\n")
    _write_table(root, "experiments", [
        {"experiment_id": "000001", "method": "numeric", "result": "supports",
         "evidence_kind": "numeric", "code_path": "code/exp/a.py",
         "code_hash": "b" * 64, "created_by": "E", "created_at": TS},
        {"experiment_id": "e-1", "method": "numeric", "result": "supports",
         "evidence_kind": "numeric", "code_path": "code/exp/a.py",
         "code_hash": "b" * 64, "created_by": "E", "created_at": TS},
        {"experiment_id": "e-2", "method": "numeric", "result": "supports",
         "evidence_kind": "numeric", "code_path": "code/exp/not-there.py",
         "code_hash": "c" * 64, "created_by": "E", "created_at": TS},
    ])
    # 验证台账：V 签的那一份（`proof_sha256` 故意与命题现在那一份不同）
    _write_jsonl(root / "verifications" / "000001.jsonl", [
        {"verification_id": "v-000001", "statement_id": "000001", "stmt_id": "000001",
         "proof_no": 1, "verifier": "agent-V", "verdict": "成立",
         "unresolved_errors": 0, "proof_sha256": "d" * 64,
         "proof_chars": len(PROOF_P1), "at": TS},
    ])
    # 产物台账：一个文件在盘上被改过（不一致）、一个不在盘上（没得比）
    _write_bytes(root / "out" / "changed.txt", "after\n")
    _write_jsonl(root / "ARTIFACTS.jsonl", [
        {"at": TS, "path": "out/changed.txt", "sha256": "e" * 64, "bytes": 6,
         "producer": "agent-E", "kind": "log", "task_id": "", "exit_code": 0, "note": ""},
        {"at": TS, "path": "out/absent.txt", "sha256": "f" * 64, "bytes": 6,
         "producer": "agent-E", "kind": "log", "task_id": "", "exit_code": 0, "note": ""},
    ])
    # 实验产物的落点两处
    _write_bytes(root / "out" / "experiments" / "000001" / "design.md", "# 设计\n")
    _write_bytes(root / "out" / "experiments" / "000001" / "exhaustion.md", "# 穷举论证\n")
    return root


@pytest.fixture()
def format_ws(tmp_path: pathlib.Path) -> pathlib.Path:
    """五条判据共用的那一份小工作区。"""
    return _format_ws(tmp_path)


# ====================================================================== 读源码
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT = re.compile(r"^[ \t]*//.*$", re.M)
#: 一次字段访问：`x.key` / `x?.key` / `x["key"]`。
_READ = re.compile(r"[.?\[]\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?\s*\]?")
#: 表格列声明：`{ key: "sha256", … }` 也算"页面读了那一栏"。
_READ_COLUMN = re.compile(r"\bkey:\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']")

#: 十六进制串（8 / 12 / 64 位都算 —— 业主点名的三种长度，含"截断显示前 8 位"那种）。
_HEX = re.compile(r"\b[0-9a-fA-F]{8}\b|\b[0-9a-fA-F]{12}\b|\b[0-9a-fA-F]{64}\b")
#: sha 那一族的字段名：真正持有一个哈希的那些（`sha256` / `proof_sha256` /
#: `statement_sha256` / `code_hash` / `digest`）。`sha_consistency` 不在其中 ——
#: 它持有的是一个词（一致 / 不一致 / unknown），不是哈希。
_SHA_FIELD = re.compile(r"sha256$|(^|_)hash$|(^|_)sha$|digest$", re.I)

def _strip_js_comments(text: str) -> str:
    """剥掉块注释与整行注释（注释上不了屏，判据只看会渲染的部分）。"""
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", text))


def _page_text(name: str) -> str:
    """一页或一个组件的源码（不在盘上就 skip —— 理由里写明）。"""
    for path in (UI_SRC / "pages" / f"{name}.tsx", UI_SRC / "components" / f"{name}.tsx"):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    pytest.skip(f"前端那一页/组件还没落地：{name}.tsx 不在盘上")
    return ""  # pragma: no cover - pytest.skip 已经抛了


def _page_reads(text: str) -> set[str]:
    """页面源码里出现过的字段名集合（剥注释后）。"""
    body = _strip_js_comments(text)
    return ({m.group(1) for m in _READ.finditer(body)}
            | {m.group(1) for m in _READ_COLUMN.finditer(body)})


def _hex_hits(value: object, depth: int = 0) -> list[str]:
    """一个读数里出现的十六进制 sha（8 / 12 / 64 位）；递归进对象与数组。"""
    if depth > 8:
        return []
    if isinstance(value, str):
        return [m.group(0) for m in _HEX.finditer(value)]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out += _hex_hits(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out += _hex_hits(item, depth + 1)
        return out
    return []


def _field_values(payload: object, depth: int = 0) -> dict[str, list[object]]:
    """读数里每个字段名 → 它出现过的那些取值（递归收；数组逐项展开）。

    为什么要摊平：页面读的是"字段"，而不是"某一条具体位置上的字段"。一个页面
    读了 `verifications`（那一栏的行）并不等于它读了行里的 `proof_sha256` ——
    摊平之后这两件事才分得开。
    """
    out: dict[str, list[object]] = {}
    if depth > 8:
        return out
    if isinstance(payload, dict):
        for key, value in payload.items():
            out.setdefault(str(key), []).append(value)
            for sub_key, sub_values in _field_values(value, depth + 1).items():
                out.setdefault(sub_key, []).extend(sub_values)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            for sub_key, sub_values in _field_values(item, depth + 1).items():
                out.setdefault(sub_key, []).extend(sub_values)
    return out


def _sha_leak_problems(label: str, reads: set[str], payload: object) -> list[str]:
    """页面读到的东西里有没有 sha：字段名是一半，取值里的十六进制是另一半。

    纯函数（负控喂人造输入就能证明它会红）：
    ① 页面读的字段名里不许有"持有一个哈希"的那一族；
    ② 那些字段在这份读数上的取值里不许有 8 / 12 / 64 位十六进制。

    ②只扫标量取值：一格表格印的就是一个标量，而容器（一栏行数组）本身不上屏 ——
    它里面的每一格各有自己的字段名，也就各自受①管。这条边界写在这里，免得
    "读了 `experiments` 那一栏"被误判成"读了行里的 `code_hash`"。
    """
    problems: list[str] = []
    fields = _field_values(payload)
    for name in sorted(reads):
        if _SHA_FIELD.search(name):
            problems.append(f"{label} 读了 sha 字段 `{name}`（sha 原文不该上屏）")
    for name in sorted(reads):
        for value in fields.get(name, []):
            if isinstance(value, (dict, list, tuple)):
                continue
            hits = _hex_hits(value)
            if hits:
                problems.append(f"{label} 读到的那批字段里带着十六进制 sha（`{name}` 里"
                                f"{len(hits)} 处，首个 {len(hits[0])} 位）")
                break
    return problems


# ====================================================================== 判据①
def test_criterion_1_no_sha_text_reaches_the_screen(format_ws: pathlib.Path) -> None:
    """判据①：页面读的那批字段里没有 sha 那一族，取值里也没有十六进制 sha。

    两头都验（见文件头「为什么两头都验」）：页面源码读的字段名、以及后端在这份工作区
    上给那些字段的值。三档词（一致 / 不一致 / unknown）必须在渲染层（`Consistency`
    组件）里，且两个页面都用它。
    """
    ev = R.evidence_chain(format_ws)
    art = R.artifacts_face(format_ws)
    problems: list[str] = []
    for page, payload in (("Evidence", ev), ("Artifacts", art)):
        problems += _sha_leak_problems(page, _page_reads(_page_text(page)), payload)
    # 全站都算：九页与每个组件都不许读"持有一个哈希"的那一族字段
    # （这一条不依赖具体读数，所以用一个空 payload）。
    for path in (sorted((UI_SRC / "pages").glob("*.tsx"))
                 + sorted((UI_SRC / "components").glob("*.tsx"))):
        problems += _sha_leak_problems(path.name, _page_reads(path.read_text(encoding="utf-8")),
                                       {})
    assert problems == [], problems

    # 反真空：这份工作区上 sha 真的在（否则"没有 sha 上屏"这句话是空的）。
    blob = _hex_hits({"statements": ev["statements"], "verifications": ev["verifications"],
                      "ledger": art["ledger"], "ledger_verify": art["ledger_verify"],
                      "experiments": ev["experiments"]})
    assert len([h for h in blob if len(h) == 64]) >= 4, (
        f"夹具里的 sha 没读出来 ⇒ 判据①是空的：{blob}")

    # 三档词在渲染层，两个页面都真的用了它。
    comp = _strip_js_comments(_page_text("Consistency"))
    for word in ("一致", "不一致", "unknown（没得比）"):
        assert word in comp, f"`Consistency` 组件里没有「{word}」这一档"
    for page in ("Evidence", "Artifacts"):
        assert "<Consistency" in _strip_js_comments(_page_text(page)), (
            f"{page} 页没有用 `Consistency` 渲染一致性")


def test_criterion_1_negative_control_a_page_that_still_prints_the_hash() -> None:
    """判据①的反真空：一个仍然读 `sha256` 的页面 + 一份带 64 位十六进制的读数 ⇒ 必须报。

    两半都喂：只在源码里读了 `sha256`（取值干净）也要报；只在取值里有哈希也要报。
    """
    old = 'const rows = art.ledger; columns={[ { key: "sha256", title: "sha256" } ]};'
    payload = {"ledger": [{"sha256": "a" * 64}]}
    problems = _sha_leak_problems("样本", _page_reads(old), payload)
    assert problems, "改前那种写法居然通过了"
    assert any("`sha256`" in p for p in problems), problems
    assert any("十六进制" in p for p in problems), problems

    # 反面：只读路径与字节的页面、取值里没有哈希 ⇒ 一条都不报。
    clean = 'const rows = art.ledger; columns={[ { key: "path" }, { key: "bytes" } ]};'
    assert _sha_leak_problems("样本", _page_reads(clean),
                              {"ledger": [{"path": "out/a.txt", "bytes": 3}]}) == []
    # 一致性那一格不算"读了 sha 字段"：它持有的是一个词。
    assert _sha_leak_problems("样本", {"sha_consistency"},
                              {"sha_consistency": "mismatch"}) == []


# ====================================================================== 判据②
#: 页面上一格非平凡度的显示词（"有档位就印档位，没有就印未判"）。
TIER_WORDS = ("T0", "T1", "T2", "T3", "T4", "未判")

#: 夹具那四条命题应该印出来的档位（判不了的两条都是「未判」，不是 T0）。
WANTED_TIERS = {"000001": "T0", "000002": "T2", "000003": "未判", "000004": "未判"}


def _tier_word(row: dict) -> str:
    """一行命题在页面上会印出来的那个词（与 `Nontriviality.tierText` 同一个判据）。"""
    label = str(row.get("nontriviality_label") or "")
    return label if label != "" else "未判"


def _tier_words(rows: list[dict]) -> dict[str, str]:
    """整张命题列表印出来的档位（判据②核的就是这一份字典）。"""
    return {str(row.get("stmt_id")): _tier_word(row) for row in rows}


def _tier_problems(rows: list[dict]) -> list[str]:
    """命题列表的非平凡度那一格：每条都要有 T0–T4 或「未判」，且未判不是 T0。"""
    problems: list[str] = []
    for row in rows:
        sid = row.get("stmt_id")
        word = _tier_word(row)
        level = row.get("nontriviality")
        if word not in TIER_WORDS:
            problems.append(f"{sid} 的档位是 `{word}`（不在 T0–T4 / 未判 里）")
        if word == "未判" and level is not None:
            problems.append(f"{sid} 印着「未判」，而读数里 level={level!r}"
                            "（未判必须与 T0 分开）")
        if word == "T0" and level is None:
            problems.append(f"{sid} 被印成 T0，而读数里 level 是 None"
                            "（那是把「没人判过」冒充成基础定理）")
    return problems


def test_criterion_2_every_proposition_shows_a_tier_or_unjudged(
        format_ws: pathlib.Path) -> None:
    """判据②：每条命题都有 T0–T4 或「未判」；未判 ≠ T0（含旧刻度那一行）。

    旧刻度那一行是这一条最锋利的一半：盘上写着 `nontriviality: 0`、没有 `scale`
    标记 —— 按旧刻度那是"判不了"，2026-10-23 之后 0 才是 T0。读侧必须读成未判。
    """
    rows = R.evidence_chain(format_ws)["statements"]
    assert len(rows) == 4, rows
    assert _tier_problems(rows) == [], _tier_problems(rows)

    words = _tier_words(rows)
    assert words == WANTED_TIERS, words
    # 未判 ≠ T0：两件事在读数上分得开（level 是 None 而不是 0）。
    unjudged = [r for r in rows if _tier_word(r) == "未判"]
    assert all(r["nontriviality"] is None for r in unjudged), unjudged
    assert all(r["nontriviality_tri"] == "unknown" for r in unjudged), unjudged
    t0 = [r for r in rows if _tier_word(r) == "T0"]
    assert t0 and t0[0]["nontriviality"] == 0, t0
    # hover 给 label：T0 那句说"基础定理或初步结论"，T2 那句标明 T2。
    assert "基础定理" in str(t0[0]["nontriviality_meaning"]), t0[0]
    t2 = [r for r in rows if _tier_word(r) == "T2"][0]
    assert t2["nontriviality_meaning"].startswith("T2"), t2

    # 渲染面：组件里的兜底词是「未判」，而且页面真的读 `nontriviality_label`。
    comp = _strip_js_comments(_page_text("Nontriviality"))
    assert 'export const TIER_UNJUDGED = "未判"' in comp, "组件的兜底词不是「未判」"
    assert 'return label === "" ? TIER_UNJUDGED : label;' in comp, (
        "`tierText` 的兜底不再是「未判」（被折成 T0 了？）")
    assert "nontriviality_label" in _page_reads(_page_text("Evidence")), (
        "Evidence 页没有读 nontriviality_label ⇒ 命题列表上没有非平凡度那一格")


def test_criterion_2_negative_control_folding_unjudged_into_t0_is_reported(
        format_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据②的反真空：把"判不了"打桩成 T0 ⇒ 上面那条判据必红。

    打桩打在 `secretary.nontriviality_of`（读侧唯一读口）上：它一旦把未经判定的命题
    答成 `level=0`，`_tier_words` 里那两条就从「未判」变成「T0」—— 于是上面那句
    `assert words == WANTED_TIERS` 当场红。这里把那句话原样再核一遍（用断言异常）。
    """
    before = R.evidence_chain(format_ws)["statements"]
    assert _tier_words(before) == WANTED_TIERS, _tier_words(before)

    def _stub(root: object, statement_full: str) -> dict:
        del root, statement_full
        return {"tri": "computed", "level": 0, "label": "T0", "basis": "打桩"}

    monkeypatch.setattr(SEC, "nontriviality_of", _stub)
    after = R.evidence_chain(format_ws)["statements"]
    assert _tier_words(after)["000003"] == "T0", _tier_words(after)
    with pytest.raises(AssertionError):
        assert _tier_words(after) == WANTED_TIERS, "未判被折成 T0 之后这一句必须红"
    # 另一半：盘上写着"没有档位"而页面印 T0 的那种自相矛盾，`_tier_problems` 当场点名。
    folded = [dict(r) for r in before]
    folded[2]["nontriviality_label"] = "T0"
    problems = _tier_problems(folded)
    assert problems, "印着 T0 而读数里没有档位，检查函数居然不报"
    assert any("冒充" in p for p in problems), problems


# ====================================================================== 判据③
#: 显示台账读数的页面（`Home` 的「台账」卡、`Run` 的同名牌、`Artifacts` 新增的那一张）。
LEDGER_PAGES = ("Home", "Run", "Artifacts")


def _ledger_page_problems(source: str) -> list[str]:
    """一页里那三样（纯函数：给负控喂改前那段源码用）。"""
    body = _strip_js_comments(source)
    problems: list[str] = []
    for token in ("upserts", "commit_markers", "commit 标记"):
        if token not in body:
            problems.append(f"页面上没有 `{token}`（口径没写到数字旁边）")
    if "台账事件" in body:
        problems.append("页面上还写着「台账事件 N 条」（那是改前那个数总行数的口径）")
    return problems


def test_criterion_3_the_ledger_shows_upserts_and_commit_markers(
        format_ws: pathlib.Path) -> None:
    """判据③：三页的台账都按 `upserts` / `commit_markers` 两格显示，没有总行数口径。"""
    problems: list[str] = []
    for page in LEDGER_PAGES:
        problems += [f"{page}：{p}" for p in _ledger_page_problems(_page_text(page))]
    assert problems == [], problems

    # 后端那份读数也真的给两格，且两个数相加 = events.jsonl 的总行数（守恒）。
    store = Store(format_ws)
    row = S.Dependency(dep_id=S.format_id(1), used_by="stmt:000001", kind="theorem",
                       label="stmt:000002", status="closed", status_reason="",
                       source_stmt_id="000002", source_experiment_id=None,
                       source_lit_id=None, path_group=1, created_at=TS)
    row.validate()
    with store.tx("dependencies", actor="test") as tx:
        tx.upsert("dependencies", row.to_dict(), note="criterion-3")
    ledger = W.snapshot(format_ws)["ledger"]
    assert ledger["upserts"] is not None, ledger
    assert ledger["commit_markers"] is not None, ledger
    raw = [ln for ln in (format_ws / "data" / "events.jsonl")
           .read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert ledger["upserts"] + ledger["commit_markers"] == len(raw), (ledger, len(raw))
    assert ledger["events"] == ledger["upserts"], ledger


def test_criterion_3_negative_control_the_old_total_row_wording_is_reported() -> None:
    """判据③的反真空：把一页换回改前"台账事件 N 条"那种写法 ⇒ 检查函数必须红。"""
    old = """
    <Card title="台账">
      <div class="readings">
        台账事件 <span class="mono">{snapshot.ledger.events}</span> 条 ·
        tasks 行数 <span class="mono">{snapshot.ledger.tables}</span>
      </div>
    </Card>
    """
    problems = _ledger_page_problems(old)
    assert problems, "改前那一段源码居然通过了"
    assert any("upserts" in p for p in problems), problems
    assert any("台账事件" in p for p in problems), problems


# ====================================================================== 判据④
def test_criterion_4_bit4_is_per_path_and_the_quote_reading_has_no_evidence(
        format_ws: pathlib.Path) -> None:
    """判据④：第 4 位按路径、引文五档（含 `no_evidence`）、reviewed 按证明逐条。"""
    ev = R.evidence_chain(format_ws)
    first = ev["statements"][0]
    assert first["formal_paths"] == [{"proof_no": 1, "state": "verified"},
                                     {"proof_no": 2, "state": "pending"}], first["formal_paths"]
    # 汇总那一层仍然成立（任一路径通过就算过 ⇒ 派生等级是正式定理），
    # 而"是哪一条路径撑起来的"逐条可读 —— 两层都在。
    assert first["grade"] == "theorem", first
    assert first["grade_label"] == "正式定理", first

    states = {str(r["stmt_id"]): r["quote_state"] for r in ev["statements"]}
    assert states == {"000001": "verbatim", "000002": "no_evidence",
                      "000003": "unchecked", "000004": "mismatch"}, states
    assert set(states.values()) <= set(EB.QUOTE_STATES), states

    # reviewed 按证明逐条：这一行带着它签的是第几条证明。
    assert [int(v["proof_no"]) for v in ev["verifications"]] == [1], ev["verifications"]

    # 渲染面：路径记号、五档词、证明号那一格。
    src = _strip_js_comments(_page_text("Evidence"))
    assert "形式化：" in src and "路径${p.proof_no}" in src, (
        "Evidence 页没有按路径印第 4 位（`形式化：路径1 …`）")
    for word in ("逐字通过", "语义通过", "no_evidence", "没有可复核的区间"):
        assert word in src, f"Evidence 页的引文读数里没有「{word}」这一档"
    assert 'key: "proof_no"' in src, "证明级那一栏没有逐条印证明号"


def test_criterion_4_negative_control_folding_the_paths_into_one_state_is_reported(
        format_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据④的反真空：把第 4 位折成一条汇总 ⇒ 逐路径那一支的用例必红。"""
    before = R.evidence_chain(format_ws)["statements"][0]
    assert len(before["formal_paths"]) == 2, before["formal_paths"]

    def _folded(row: object) -> dict:
        del row
        return {1: "verified"}

    monkeypatch.setattr(EB, "formal_by_proof", _folded)
    after = R.evidence_chain(format_ws)["statements"][0]
    assert len(after["formal_paths"]) == 1, after["formal_paths"]
    assert after["formal_paths"] != [{"proof_no": 1, "state": "verified"},
                                     {"proof_no": 2, "state": "pending"}], (
        "折成一条汇总之后，逐路径那两句居然还绿着")


# ====================================================================== 判据⑤
def _expect_ledger_mismatch(reading: dict) -> None:
    """判据核的那一件事：被改过的那个文件必须读成"不一致"（打桩之后它必须红）。"""
    rows = {str(r["path"]): r for r in reading["ledger_verify"]}
    assert rows["out/changed.txt"]["sha_consistency"] == R.SHA_MISMATCH, rows["out/changed.txt"]


def test_criterion_5_stubbing_sha_consistency_as_always_matching_breaks_it(
        format_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据⑤（反真空）：把 sha 一致性打桩成恒一致 ⇒ 不一致那一支的用例必红。

    三档各有各的用例：被改过的文件是 `mismatch`、不在盘上的文件是 `unknown`
    （不是 `mismatch`）—— 后者钉的是"没得比不等于不一致"。
    """
    base = R.artifacts_face(format_ws)
    _expect_ledger_mismatch(base)
    rows = {str(r["path"]): r for r in base["ledger_verify"]}
    assert rows["out/absent.txt"]["sha_consistency"] == R.SHA_UNKNOWN, rows["out/absent.txt"]
    assert rows["out/absent.txt"]["sha_consistency"] != R.SHA_MISMATCH, rows["out/absent.txt"]

    # 打桩：恒一致。于是"不一致"那一支的用例必须红。
    monkeypatch.setattr(R, "sha_consistency", lambda want, now: R.SHA_MATCH)
    stubbed = R.artifacts_face(format_ws)
    with pytest.raises(AssertionError):
        _expect_ledger_mismatch(stubbed)
    # 恒一致的危险在这里：它把"真的一致"与"根本没得比"一起说成"一致"。
    stubbed_rows = {str(r["path"]): r for r in stubbed["ledger_verify"]}
    assert stubbed_rows["out/changed.txt"]["sha_consistency"] == R.SHA_MATCH
    assert stubbed_rows["out/absent.txt"]["sha_consistency"] == R.SHA_MATCH


def test_criterion_5_every_consistency_site_goes_through_the_one_function() -> None:
    """判据⑤的另一半：四处一致性读数都得走 `sha_consistency`（否则打桩覆盖不到它们）。

    四处：产物台账 / 台账对账 / 实验的代码 / 证明级。前两处在 `artifacts_face`，
    后两处在 `evidence_chain` —— 源码里出现的那几个读法必须都来自同一个函数
    （实验那一格先过 `code_consistency` 加第四档「已撤销」，比值本身仍交给
    `sha_consistency`，于是"把比较打桩成恒一致"照样覆盖得到它）。
    """
    src = (REPO / "src" / "agentflow" / "webui" / "readers.py").read_text(encoding="utf-8")
    for name in ('got["code_sha_consistency"] = code_consistency(',
                 'got["proof_sha_consistency"] = sha_consistency(',
                 '"sha_consistency": _ledger_verify_consistency(r)'):
        assert name in src, f"`readers.py` 里没有这一处（{name}）"
    assert 'return sha_consistency(row.get("sha256"), row.get("sha256_now"))' in src, (
        "台账核对那一行没有真比两份 sha")
    assert "return sha_consistency(want, got)" in src, (
        "实验行的代码一致没有走同一个比值函数（第四档只是状态，不是第二份比较）")


# ====================================================================== 反真空（四面落点）
def test_the_four_landing_points_are_in_place() -> None:
    """反真空：四处落点都在盘上，少一处上面几条会以 skip 的形态静默变绿。

    四处：① `Consistency` 组件 ② `Nontriviality` 组件 ③ `Evidence` 页的命题三格
    ④ `Artifacts` 页的实验产物落点那一栏。
    """
    for rel in (("components", "Consistency.tsx"), ("components", "Nontriviality.tsx"),
                ("pages", "Evidence.tsx"), ("pages", "Artifacts.tsx")):
        path = UI_SRC.joinpath(*rel)
        assert path.is_file(), f"{path} 不在盘上"

    ev = _strip_js_comments(_page_text("Evidence"))
    for token in ("nontriviality_label", "quote_state", "formal_paths", "proof_no",
                  "proof_sha_consistency"):
        assert token in ev, f"Evidence 页缺 `{token}`"

    art = _strip_js_comments(_page_text("Artifacts"))
    for token in ("experiment_spots", "code_exp", "sha_consistency", "upserts",
                  "commit_markers"):
        assert token in art, f"Artifacts 页缺 `{token}`"
    assert "out/experiments" in art, "产物页没有写实验产物的落点"
    assert "code/exp" in art, "产物页没有写 code/exp 那处落点"


# ============================================================ 第二批（§f/g/h/i）
"""业主 2026-10-23 那张"略有过时"的清单里剩下的四件（②③ 两条都归 §g）。

| # | 件 | 判据 | 负控 |
|---|---|---|---|
| ⑥ | f：首页那一列的名字 | 页面上逐字是「事件条数（会话）」，裸「事件」那一列不再有；说明页写清两种条数不是一回事 | 喂回改前那一段源码（裸「事件」+ 说明页缺那一段）⇒ 必须报 |
| ⑦ | g：五位每位一格 | 五格标题逐条在（numeric / proof / reviewed / formal / audited），第 4 位仍按路径 | 把第 4 位折成一句汇总 ⇒ 必须报 |
| ⑧ | g：reviewed 按证明逐条 | 读数里 `reviewed_paths` 一条证明一行；页面上是 `#p1 / #p2` 两个记号 | 把逐条那张表折成「最近一签」⇒ 只剩一条 |
| ⑨ | h：实验表的「报告」列 | 读数给仓库相对落点 `out/experiments/<号>/exhaustion.md`；页面挂链接（指向产物页那张落点卡），没有报告写「无」 | 见 ⑪ |
| ⑩ | i：产物页文件头的栏数 | 文件头那个数字与 `ARTIFACT_CARDS` 的条数、页面真挂的卡数三者相等，且是 9（第九张是实验产物的落点） | 少挂一张卡 / 还写着「七栏」⇒ 必须报 |
| ⑪ | 反真空（④ 的另一面） | 把「报告」列打桩成恒空 ⇒ ⑨ 的检查函数必红 | 它本身就是反真空 |

## 为什么「报告」列指向产物页那张卡、而不是直接链到文件

报告不在 web 服务的静态路由下（`routes.ROUTES` 只有 `/static/{file...}` 与页面），
拿仓库相对路径当 `href` 点下去只会回到应用 —— 那是死链。所以这一格的链接指向产物页
「实验产物的落点」那张卡（`/artifacts#experiment-spots`），而链接的文字仍是仓库相对
路径 `out/experiments/<号>/exhaustion.md`（业主点名的那一份）。判据两头都钉：链接的
目标卡真的存在（产物页那张卡有那个 `id`），文字是相对仓库路径、不是绝对路径。
"""


# ====================================================================== 判据⑥（§f）
#: 首页「会话概览」那一列的名字（业主点名的逐字形态）。
SESSION_EVENT_COLUMN = "事件条数（会话）"


def _two_counts_problems(home: str, help_text: str) -> list[str]:
    """两种"条数"分开了吗（纯函数：负控喂改前那两段源码就能证明它会红）。

    首页那一列数的是这一段会话的事件条数（`SessionRow.events_seen`），台账那张卡
    数的是整个工作区的写入笔数（`upserts`）+ commit 标记行数。两个数并排摆着而名字
    只差一个字（「事件」/「台账写入」），读的人很容易拿一个去核另一个。
    """
    body = _strip_js_comments(home)
    help_body = _strip_js_comments(help_text)
    problems: list[str] = []
    if SESSION_EVENT_COLUMN not in body:
        problems.append(f"Home 页没有「{SESSION_EVENT_COLUMN}」这一列")
    if 'title: "事件"' in body:
        problems.append("Home 页还写着裸「事件」那一列（与台账的写入笔数并排会混）")
    if SESSION_EVENT_COLUMN not in help_body:
        problems.append(f"说明页没有点名那一列（「{SESSION_EVENT_COLUMN}」）")
    if "不是一回事" not in help_body:
        problems.append("说明页没有写「两种条数不是一回事」")
    for token, why in (("upserts", "台账那一格的口径（写入笔数）"),
                       ("commit 标记", "commit 标记行另计这一句"),
                       ("会话", "会话那一边的口径")):
        if token not in help_body:
            problems.append(f"说明页缺 {token!r}：{why}")
    return problems


def test_criterion_6_home_says_event_count_per_session() -> None:
    """判据⑥（§f）：Home 那一列叫「事件条数（会话）」；说明页写清两种条数不是一回事。"""
    assert _two_counts_problems(_page_text("Home"), _page_text("Help")) == [], (
        _two_counts_problems(_page_text("Home"), _page_text("Help")))

    # 改的只是名字：那一格仍然读 `events_seen`（不许把整列撤掉装作"不混了"）。
    assert "events_seen" in _page_text("Home"), (
        "Home 页不再读 events_seen —— 改名不许把那一格撤掉")


def test_criterion_6_negative_control_the_bare_event_title_is_reported() -> None:
    """判据⑥的反真空：改前那一列（裸「事件」）+ 没有那一段说明 ⇒ 检查函数必须报。"""
    old_home = 'columns={[ { key: "sid", title: "会话" }, { key: "events_seen", title: "事件" } ]}'
    #: 说明页改前只有「台账写入笔数 ≠ 事件文件行数」那一段，没有会话那一半。
    old_help = ("台账写入 N 笔（其中 commit 标记 M 行）· 每提交一次事务写两行")
    problems = _two_counts_problems(old_home, old_help)
    assert problems, "改前那两段源码居然通过了"
    assert any("裸「事件」" in p for p in problems), problems
    assert any(SESSION_EVENT_COLUMN in p for p in problems), problems
    assert any("不是一回事" in p for p in problems), problems


# ====================================================================== 判据⑦（§g）
#: 五元位的五个名字（后端唯一来源：`evidencebits.BIT_NAMES`）。
#: 每一位在页面上占一格，标题逐字含这个名字。
BIT_CELL_TITLES: tuple[str, ...] = (
    "第 1 位·numeric（数值实验）",
    "第 2 位·proof（有证明）",
    "第 3 位·reviewed（按证明）",
    "第 4 位·formal（按路径）",
    "第 5 位·audited（正式审查）",
)


def _bit_cell_problems(source: str) -> list[str]:
    """五位每位一格：五个标题都在，且第 4 位仍然是按路径那两句（纯函数）。

    第 4 位那两句（`形式化：` / `路径${p.proof_no}`）是 2026-10-23 那一批的成果：
    把它折成一句汇总就等于让 `#p2` 借 `#p1` 的光，所以这一条不许退化。
    """
    body = _strip_js_comments(source)
    problems = [f"Evidence 页没有「{title}」这一格" for title in BIT_CELL_TITLES
                if title not in body]
    if "形式化：" not in body or "路径${p.proof_no}" not in body:
        problems.append("第 4 位不再是按路径显示（退化成了汇总）")
    if "reviewed_paths" not in body:
        problems.append("第 3 位没有读 reviewed_paths（reviewed 没按证明逐条）")
    return problems


def test_criterion_7_the_five_bits_each_get_their_own_cell(format_ws: pathlib.Path) -> None:
    """判据⑦（§g）：五个位名都在页面上，每位一格；第 4 位仍按路径。"""
    # 五位的名字只有一个来源（反真空：这一句不成立时下面的标题就是自说自话）。
    assert EB.BIT_NAMES == ("numeric", "proof", "reviewed", "formal", "audited"), EB.BIT_NAMES
    rows = R.evidence_chain(format_ws)["statements"]
    first = rows[0]
    assert first["bit_numeric"] == "pending", first
    assert first["bit_proof"] == "verified", first
    assert first["bit_reviewed"] == "verified", first
    assert first["bit_audited"] == "pending", first
    # 一条没有位记录的命题：四格都读得出它们是"没做"，而不是缺席。
    bare = [r for r in rows if r["stmt_id"] == "000003"][0]
    for key in ("bit_numeric", "bit_proof", "bit_reviewed", "bit_audited"):
        assert bare[key] == "pending", (key, bare[key])

    assert _bit_cell_problems(_page_text("Evidence")) == [], (
        _bit_cell_problems(_page_text("Evidence")))


def test_criterion_7_negative_control_folding_bit4_into_one_word_is_reported() -> None:
    """判据⑦的反真空：把第 4 位折成一句汇总（不再按路径）⇒ 检查函数必须报。"""
    folded = """
      columns={[
        { key: "stmt_id", title: "命题号" },
        { key: "formal_paths", title: "第 4 位·formal（按路径）", render: (r) => cell(r.grade_label) },
        { key: "reviewed_paths", title: "第 3 位·reviewed（按证明）", render: (r) => cell(r.bit_reviewed) },
      ]}
    """
    problems = _bit_cell_problems(folded)
    assert problems, "折成汇总之后检查函数居然不报"
    assert any("按路径" in p for p in problems), problems
    assert any("numeric" in p for p in problems), problems


# ====================================================================== 判据⑧（§g）
def test_criterion_8_reviewed_is_signed_one_proof_at_a_time(format_ws: pathlib.Path) -> None:
    """判据⑧（§g）：reviewed 按证明逐条 —— 读数一条证明一行，页面读到 `#p1` / `#p2`。"""
    first = R.evidence_chain(format_ws)["statements"][0]
    assert first["reviewed_paths"] == [{"proof_no": 1, "reviewed": True},
                                       {"proof_no": 2, "reviewed": False}], first["reviewed_paths"]
    # 汇总位与逐条那一层是两件事：`reviewed` 是"任一条签过"，逐条才说得出是哪一条。
    assert first["bit_reviewed"] == "verified", first["bit_reviewed"]

    body = _strip_js_comments(_page_text("Evidence"))
    assert "#p${p.proof_no}" in body, "第 3 位不是按证明逐条印（没有 `#p` 那个记号）"
    assert "已签" in body and "未签" in body, "第 3 位没有分出「签过 / 没签」两档"


def test_criterion_8_negative_control_folding_reviewed_into_one_word_is_reported(
        format_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据⑧的反真空：把逐条那张表折成「最近一签」⇒ 只剩一条，正控那一句必须红。"""
    before = R.evidence_chain(format_ws)["statements"][0]["reviewed_paths"]
    assert len(before) == 2, before

    monkeypatch.setattr(EB, "reviewed_by_proof", lambda row: {1: True})
    after = R.evidence_chain(format_ws)["statements"][0]["reviewed_paths"]
    assert len(after) == 1, after
    with pytest.raises(AssertionError):
        assert after == [{"proof_no": 1, "reviewed": True},
                         {"proof_no": 2, "reviewed": False}], (
            "折成最近一签之后，逐条那一句居然还绿着")


# ====================================================================== 判据⑨（§h）
def _report_column_problems(rows: list[dict]) -> list[str]:
    """实验表的「报告」列：落点是仓库相对的 `out/experiments/<号>/exhaustion.md`。

    三档各说各的（三态纪律）：
    - `computed`：盘上有那一份 ⇒ 落点必须成形，且不许是绝对路径 / 反斜杠；
    - `not_applicable`：没有报告（实验号不成形，或报告还没落盘）⇒ 落点为空；
    - `unreadable`：读不出来 ⇒ 不算"没有"。

    真空防线在最后一句：一条 `computed` 都没有时这一列是空的，而"空列"与"没做这一列"
    在页面上长得一样。
    """
    problems: list[str] = []
    linked = 0
    for row in rows:
        eid = str(row.get("experiment_id") or "")
        path = str(row.get("exhaustion_path") or "")
        tri = str(row.get("exhaustion_tri") or "")
        if tri == "computed":
            linked += 1
            if not (path.startswith("out/experiments/")
                    and path.endswith("/exhaustion.md")):
                problems.append(
                    f"{eid} 的报告落点不是 out/experiments/<号>/exhaustion.md：{path!r}")
            if "\\" in path or path.startswith("/") or ":" in path:
                problems.append(f"{eid} 的报告落点不是仓库相对路径：{path!r}")
        elif tri == "not_applicable":
            if path != "":
                problems.append(f"{eid} 没有报告，却仍给了一个落点：{path!r}")
        elif tri != "unreadable":
            problems.append(f"{eid} 的 exhaustion_tri 是词表外的值：{tri!r}")
    if linked == 0:
        problems.append("实验表里一条「有报告」的行都没有 ⇒ 「报告」那一列没有落脚点")
    return problems


def test_criterion_9_the_experiment_table_links_the_exhaustion_report(
        format_ws: pathlib.Path) -> None:
    """判据⑨（§h）：实验表挂上 `out/experiments/<号>/exhaustion.md`，没有报告写「无」。"""
    rows = R.evidence_chain(format_ws)["experiments"]
    assert _report_column_problems(rows) == [], _report_column_problems(rows)
    by_id = {str(r["experiment_id"]): r for r in rows}
    assert by_id["000001"]["exhaustion_path"] == "out/experiments/000001/exhaustion.md", by_id
    assert by_id["000001"]["exhaustion_tri"] == "computed", by_id["000001"]
    # 没有报告的那两条（实验号不成形 ⇒ 判不出落点）：落点为空 = 页面上写「无」。
    for eid in ("e-1", "e-2"):
        assert by_id[eid]["exhaustion_path"] == "", by_id[eid]
        assert by_id[eid]["exhaustion_tri"] == "not_applicable", by_id[eid]

    body = _strip_js_comments(_page_text("Evidence"))
    assert 'key: "exhaustion_path"' in body, "实验表没有「报告」那一列"
    assert 'title: "报告"' in body, "「报告」那一列的名字不对"
    assert 'const REPORT_SPOT_HREF = "/artifacts#experiment-spots"' in body, (
        "「报告」那一格没有指向产物页的实验落点卡")
    assert "{r.exhaustion_path}" in body, "链接的文字不是那份报告的仓库相对路径"
    assert "exhaustion_tri" in body, "「报告」那一格没有按三态分档"
    assert "无（" in body, "没有报告时没有写「无」"
    # 链接指向的那张卡真的在（否则链接死在一个不存在的锚点上）。
    assert 'id="experiment-spots"' in _strip_js_comments(_page_text("Artifacts")), (
        "产物页那张实验落点卡没有 `id=\"experiment-spots\"`，链接会落在空处")


def test_criterion_11_negative_control_an_always_empty_report_column_is_reported(
        format_ws: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """判据⑪（反真空）：把「报告」列打桩成恒空 ⇒ 判据⑨ 的检查函数必红。"""
    assert _report_column_problems(R.evidence_chain(format_ws)["experiments"]) == []

    monkeypatch.setattr(EX, "report_relpath", lambda experiment_id: "")
    stubbed = R.evidence_chain(format_ws)["experiments"]
    assert all(r["exhaustion_path"] == "" for r in stubbed), stubbed
    assert all(r["exhaustion_tri"] == "not_applicable" for r in stubbed), stubbed
    with pytest.raises(AssertionError):
        assert _report_column_problems(stubbed) == [], (
            "打桩成恒空之后，判据⑨ 那一句居然还绿着")


# ====================================================================== 判据⑩（§i）
#: 产物页文件头声明的栏数（业主点名的数字：九张卡）。
ARTIFACT_CARD_COUNT = 9

#: 文件头那个数字（中文数字）与它的值。
_HEADER_NUMERALS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _artifact_registry(source: str) -> dict[str, str]:
    """`ARTIFACT_CARDS` 那张表：`{键: 标题}`（按声明顺序，`dict` 的插入序就是栏序）。"""
    body = _strip_js_comments(source)
    start = body.find("export const ARTIFACT_CARDS")
    if start < 0:
        return {}
    end = body.find("} as const;", start)
    block = body[start:end if end > 0 else len(body)]
    return {m.group(1): m.group(2)
            for m in re.finditer(r"\n\s+([A-Za-z_][A-Za-z0-9_]*):\s*\n?\s*\"([^\"]+)\"", block)}


def _artifact_card_count_problems(source: str) -> list[str]:
    """文件头那个数字 == `ARTIFACT_CARDS` 的条数 == 页面真挂的卡数（纯函数）。

    三者相等才叫"自证"：标题与数字来自同一张表，加一张卡忘了登记（或忘了改文件头
    那个中文数字）都会当场红。改前那个数字是手写在文件头里的，加了卡它不会动 ——
    于是"七栏"与屏幕上九张卡同时存在了一个批次。
    """
    body = _strip_js_comments(source)
    problems: list[str] = []
    cards = _artifact_registry(source)
    if not cards:
        problems.append("产物页没有 `ARTIFACT_CARDS` 那张表（文件头那个数字没有单一来源）")
        return problems
    declared = re.search(r"共([一二三四五六七八九十])张卡", source)
    if declared is None:
        problems.append("文件头没有声明这张纸有几张卡（缺「共N张卡」那一句）")
    elif _HEADER_NUMERALS[declared.group(1)] != len(cards):
        problems.append(
            f"文件头写着 {declared.group(1)}张卡，而 `ARTIFACT_CARDS` 有 {len(cards)} 条")
    if "const CARD_COUNT = Object.keys(ARTIFACT_CARDS).length" not in body:
        problems.append("页面那个数字不是从 `ARTIFACT_CARDS` 数出来的")
    mounted = set(re.findall(r"title=\{ARTIFACT_CARDS\.([A-Za-z_][A-Za-z0-9_]*)", body))
    missing = sorted(set(cards) - mounted)
    if missing:
        problems.append(f"`ARTIFACT_CARDS` 登记了 {len(cards)} 条，这几张却没挂出来：{missing}")
    unknown = sorted(mounted - set(cards))
    if unknown:
        problems.append(f"页面挂了表里没有的卡：{unknown}")
    for stale_form in ("七栏 · 整面 tri=", "七栏，每栏自己一个三态"):
        if stale_form in source:
            problems.append(f"文件头还写着改前那句「{stale_form}」（实际已是九张卡）")
    return problems


def test_criterion_10_the_artifacts_header_counts_the_cards_it_renders() -> None:
    """判据⑩（§i）：产物页文件头声明的栏数 == 实际卡片数（九张，第九张是实验落点）。"""
    source = _page_text("Artifacts")
    assert _artifact_card_count_problems(source) == [], (
        _artifact_card_count_problems(source))
    cards = _artifact_registry(source)
    assert len(cards) == ARTIFACT_CARD_COUNT, list(cards)
    # 第九张是什么：实验产物的落点（业主那句"并说明第九张是什么"的机器读数）。
    assert "实验" in list(cards.values())[-1], list(cards.values())[-1]
    # 那张镜子卡（台账的第二个独立读数）读的是共享快照，不是这一面的栏 ——
    # 它写在表外，文件头里点过名（所以"九"不与它矛盾）。
    assert "第二个独立读数" in source, "产物页那张台账镜子卡不见了"
    body = _strip_js_comments(source)
    assert "${CARD_COUNT} 张卡" in body, "页面副标题没有数那张表"


def test_criterion_10_negative_control_a_missing_card_or_the_old_number_is_reported() -> None:
    """判据⑩的反真空：少挂一张卡 / 还写着「七栏」/ 文件头数字与表不符 ⇒ 必须报。"""
    source = _page_text("Artifacts")
    assert _artifact_card_count_problems(source) == []
    dropped = source.replace("title={ARTIFACT_CARDS.", 'title="x"', 1)
    problems = _artifact_card_count_problems(dropped)
    assert problems and any("却没挂出来" in p for p in problems), problems
    # 改前那句「七栏」写回注释里 ⇒ 必须点到它。
    stale = source.replace("export const ARTIFACT_CARDS", "/* 七栏 · 整面 tri=computed */\n"
                                                         "export const ARTIFACT_CARDS", 1)
    stale_problems = _artifact_card_count_problems(stale)
    assert stale_problems and any("七栏" in p for p in stale_problems), stale_problems
    # 文件头那个中文数字与表差一条 ⇒ 必须点到那个数。
    miscount = source.replace("九张卡", "八张卡", 1)
    miscount_problems = _artifact_card_count_problems(miscount)
    assert miscount_problems and any("八张卡" in p for p in miscount_problems), miscount_problems
