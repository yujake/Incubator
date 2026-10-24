# -*- coding: utf-8 -*-
r"""D-40：G 的写作参照物是 B 台账登记的命题，不是 L 的形式化分解（业主 2026-10-24）。

业主原话（唯一权威）：
    「G 的写作只参照 B 侧收录的证明，如果参照 L 侧的形式化会切割太细。」
同日口径更正：
    「形式化细节不进论文正文。」

## 这一组守五条

1. G 渲染出来的提示词里读得到两层意思：「正文的定理/引理/命题结构以 B 台账登记的命题为准
   / 一条命题对一个环境」与「L 的形式化产物只作凭据、形式化细节不进正文、凭据只在对应表
   那一行与 experiments 那一行」；
2. G 的技能正文（落盘成 skills/G/....md、模型用 fs.read 读的那一份）里同样读得到；
3. 反真空：把那一句从 policy 里删掉，第 1 条必红；换回去又绿；
4. 结构判据：正文 6 个定理类环境、台账 1 条命题（cube2 的现场：1 个 theorem 加 5 个
   \newtheorem{claim}[theorem]{Lemma} 印成的 Lemma）=> doc.write_mapping 受控拒绝，
   拒信点名「正文多出 5 个定理类环境，台账里没有对应命题」以及那 5 个 label；
5. 反真空：正文环境数 == 台账命题数 => 必须放行（读数里的 statement_surplus 是空的）。

全部用例都在 tmp_path 下自建工作区，一个模型调用都不发。
"""
from __future__ import annotations

import dataclasses
import json
import pathlib
import re

import pytest

from agentflow import agent_prompts as AP
from agentflow import agent_skills as SK
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow.store import Store
from agentflow.tools import build_registry

#: 强调符号与空白：判"读到的意思"，不判排版（与 test_d36 的口径同一条）。
_EMPHASIS = re.compile(r"[\s*`]+")

#: 第 1、2 条必须读到的意思（去掉强调与空白之后逐条核）。
#:
#: 左边是提示词 / 技能正文里的话；右边是它对应的那件事（报错时用它说清缺了什么）。
#: 拆成八条而不是一整句：语序可以改，意思不许缺 —— 缺哪一条，模型就会从某一条路上
#: 把 L 的形式化分解搬回正文。
_NEEDLES: tuple[tuple[str, str], ...] = (
    ("以 B 台账登记的命题为准", "正文结构以台账命题为准"),
    ("一条命题对一个环境", "一条命题只占一个定理类环境"),
    ("形式化产物只作", "L 的产物只是凭据，不是正文目录的来源"),
    ("形式化细节不进正文", "形式化细节不进正文"),
    ("附录与脚注也不进", "附录与脚注也不搬形式化细节"),
    ("凭据的落点只有两处", "凭据只在对应表那一行与 experiments 那一行"),
    ("指向对应表里那一行", "正文最多一句结论并指向对应表"),
    ("不得用来伪装定理类环境", "claim 宏不许冒充定理类环境"),
)

#: 提示词渲染下限（反真空：空串或占位文本不许通过）。
_MIN_CHARS = 3000

_TASK = "整理成论文"
_ROOT = "D:/x"
_FACTS = ("这台机器上的证明工具链（现算读数，不是记忆）：\n"
          "- 检查器：（判据夹具，与机器无关）")
_FORMAL = ("你这一岗怎么写形式化（由上面那份读数现算）：\n"
           "- （判据夹具：这一次按自足文件写）")


def _flat(text: str) -> str:
    """去掉强调符号与所有空白 —— 判"读到的意思"，不判排版。"""
    return _EMPHASIS.sub("", str(text))


def _render_g() -> str:
    """真的渲染一遍 G 的提示词（纯函数，零模型调用）。"""
    return AP.system_prompt("G", registry=build_registry().registry, task=_TASK,
                            workspace_root=_ROOT, toolchain_facts=_FACTS,
                            toolchain_formal=_FORMAL)


def _prompt_problems(text: str) -> list[str]:
    """第 1 条的正文：渲染后的提示词里缺了哪几个意思（空清单 = 都在）。"""
    if len(str(text)) < _MIN_CHARS:
        return [f"渲染出来的提示词只有 {len(str(text))} 字（下限 {_MIN_CHARS}）"
                " ⇒ 这一条没有落脚点（它不是在判一份真的提示词）"]
    flat = _flat(text)
    return [f"读不到「{needle}」这件事（{why}）—— 这一句必须逐字进 specs/g.py 的 policy"
            for needle, why in _NEEDLES if _flat(needle) not in flat]


# ============================================================ 1 提示词
def test_1_the_g_prompt_says_the_body_follows_the_b_registry() -> None:
    """① G 的渲染提示词里读得到那两层意思（八条逐条核）。"""
    text = _render_g()
    bad = _prompt_problems(text)
    assert bad == [], "\n".join(bad)
    # 那段的真身是 specs/g.py 的 policy（提示词只是把它渲染出来）：两处都要有，
    # 否则"提示词里有"可能只是别的一段碰巧写着同样的话。
    from agentflow.specs import g as GS

    policy = "\n".join(GS.SPEC.brief.policy)
    missing = [needle for needle, _why in _NEEDLES if needle not in policy]
    assert missing == [], f"specs/g.py 的 policy 里缺 {missing}"


# ============================================================ 2 技能正文
def test_2_the_g_skill_body_reads_the_same_rule(tmp_path: pathlib.Path) -> None:
    """② G 的技能正文里同样读得到；而且落盘之后那份文件里也读得到。"""
    rows = [s for s in SK.skills_for("G") if s.slug == "成稿-正文自己写"]
    assert len(rows) == 1, [s.slug for s in SK.skills_for("G")]
    body = rows[0].body
    missing = [needle for needle, _why in _NEEDLES if needle not in body]
    assert missing == [], f"技能正文里缺 {missing}"

    SK.materialize(tmp_path)
    landed = (pathlib.Path(tmp_path) / SK.SKILLS_DIR / "G"
              / "成稿-正文自己写.md")
    assert landed.is_file(), f"技能没有落到盘上：{landed}"
    text = landed.read_text(encoding="utf-8")
    missing2 = [needle for needle, _why in _NEEDLES if needle not in text]
    assert missing2 == [], f"落盘那一份里缺 {missing2}（fs.read 读到的是它）"


# ============================================================ 3 反真空
def test_3_deleting_the_sentence_turns_criterion_one_red(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 反真空：把那一句从 policy 里删掉 ⇒ ① 必红；换回去又绿。"""
    brief = AP.ROLE_BRIEFS["G"]
    kept = tuple(p for p in brief.policy if "以 B 台账登记的命题为准" not in str(p))
    assert len(kept) == len(brief.policy) - 1, (
        "夹具前提：那一条 policy 真的装着这句话（否则下面删的是空）")
    stripped = dataclasses.replace(brief, policy=kept)
    monkeypatch.setitem(AP.ROLE_BRIEFS, "G", stripped)
    bad = _prompt_problems(_render_g())
    assert bad, ("把那一段删掉之后第 1 条还是绿的 ⇒ 它判的不是提示词里那段话")
    assert any("以 B 台账登记的命题为准" in one for one in bad), bad

    # 负控的负控：换回去 ⇒ 判据重新成立（这一半让本条在改前也红）
    monkeypatch.setitem(AP.ROLE_BRIEFS, "G", brief)
    assert _prompt_problems(_render_g()) == [], "换回去之后第 1 条仍然红"


# ============================================================ 夹具：台账与正文
SID = S.format_id(0)
SID2 = S.format_id(1)
EXP = S.format_id(0)

#: cube2 的现场（2026-10-24 抓到的）：Lean 文件把证明拆成 6 个 theorem，G 照它写正文 ——
#: 1 个 theorem 环境 + 5 个 \begin{claim}（导言区把 claim 印成 Lemma）。台账只有 1 条命题。
CUBE2_CLAIM_LABELS: tuple[str, ...] = (
    "lem:base", "lem:twodvd", "lem:clear", "lem:alg", "lem:step",
)

_CUBE2_TEX = (
    "\\documentclass[11pt]{ctexart}\n"
    "\\usepackage{amsmath,amssymb,amsthm}\n"
    "\n"
    "\\newtheorem{theorem}{Theorem}[section]\n"
    "\\newtheorem{claim}[theorem]{Lemma}\n"
    "\n"
    "\\begin{document}\n"
    "\\section{Main results}\n"
    "\\begin{claim}[Base case $n=1$]\\label{lem:base}\n"
    "The base case holds.\n"
    "\\end{claim}\n"
    "\\begin{proof}\n"
    "Direct computation.\n"
    "\\end{proof}\n"
    "\\begin{claim}[Two divides a product of consecutive integers]\\label{lem:twodvd}\n"
    "A product of two consecutive integers is even.\n"
    "\\end{claim}\n"
    "\\begin{proof}\n"
    "One of the two is even.\n"
    "\\end{proof}\n"
    "\\begin{claim}[Clearing the denominator]\\label{lem:clear}\n"
    "The denominator can be cleared.\n"
    "\\end{claim}\n"
    "\\begin{proof}\n"
    "Multiply by the common denominator.\n"
    "\\end{proof}\n"
    "\\begin{claim}[The induction identity]\\label{lem:alg}\n"
    "The algebraic identity holds.\n"
    "\\end{claim}\n"
    "\\begin{proof}\n"
    "Expand both sides.\n"
    "\\end{proof}\n"
    "\\begin{claim}[The induction step]\\label{lem:step}\n"
    "The induction step follows.\n"
    "\\end{claim}\n"
    "\\begin{proof}\n"
    "Apply the identity.\n"
    "\\end{proof}\n"
    "\\begin{theorem}[Nicomachus' theorem]\\label{thm:nicomachus}\n"
    "The sum of the first $n$ cubes is the square of the $n$-th triangular number.\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "Induction on $n$.\n"
    "\\end{proof}\n"
    "\\end{document}\n"
)

#: 干净那一档：2 个 theorem 环境 + 1 个 experiment 环境，台账 2 条命题 + 1 条实验。
#: 另有一个印成 Claim 的自定义环境 —— 它不是定理类环境（不冒充 Lemma），不该被算进来。
_CLEAN_TEX = (
    "\\documentclass[11pt]{ctexart}\n"
    "\\usepackage{amsmath,amssymb,amsthm}\n"
    "\n"
    "\\newtheorem{theorem}{Theorem}[section]\n"
    "\\newtheorem{claim}{Claim}[section]\n"
    "\n"
    "\\begin{document}\n"
    "\\section{Main results}\n"
    "\\begin{theorem}\\label{thm:nicomachus}\n"
    "The sum of the first $n$ cubes is the square of the $n$-th triangular number.\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "Induction on $n$.\n"
    "\\begin{claim}\\label{claim:step}\n"
    "An intermediate step.\n"
    "\\end{claim}\n"
    "\\end{proof}\n"
    "\\begin{theorem}\\label{thm:faulhaber}\n"
    "The Faulhaber formula holds for odd powers.\n"
    "\\end{theorem}\n"
    "\\begin{proof}\n"
    "Compare coefficients.\n"
    "\\end{proof}\n"
    "\\begin{experiment}\\label{exp:scan}\n"
    "A numerical scan.\n"
    "\\end{experiment}\n"
    "\\end{document}\n"
)

#: cube2 台账里那一行命题（`kind` 是定理类 ⇒ 算一条命题）。
_CUBE2_STATEMENTS: list[dict] = [
    {"stmt_id": SID, "origin": "own_result", "kind": "theorem",
     "statement_text": "立方和恒等式：1^3+...+n^3 = (n(n+1)/2)^2",
     "proof_text": "对 n 作归纳。"},
]

#: 干净那一档的台账：2 条命题 + 1 条实验。
_CLEAN_TABLES: dict[str, list[dict]] = {
    "statements": [
        {"stmt_id": SID, "origin": "own_result", "kind": "theorem",
         "statement_text": "立方和恒等式", "proof_text": "对 n 作归纳。"},
        {"stmt_id": SID2, "origin": "own_result", "kind": "proposition",
         "statement_text": "Faulhaber 公式", "proof_text": "比较系数。"},
    ],
    "experiments": [{"experiment_id": EXP}],
}


def _dump(path: pathlib.Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def _workspace(root: pathlib.Path, *, tex: str,
               tables: dict[str, list[dict]]) -> pathlib.Path:
    """造一个工作区：台账几张表 + 论文包里的 main.tex（对应表由工具那一步写）。"""
    root = pathlib.Path(root)
    store = Store(root)
    store.init()
    for table, rows in tables.items():
        path = root / "data" / str(S.TABLES[table]["file"])
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["rows"] = [dict(row) for row in rows]
        _dump(path, doc)
    package = PM.package_dir(root)
    package.mkdir(parents=True, exist_ok=True)
    (package / PM.PC.TEX_NAME).write_bytes(tex.encode("utf-8"))
    return root


def _call_write_mapping(root: pathlib.Path, rows: list[dict]):
    """走真的工具层（`doc.write_mapping`），不是直接调 `papermapping`。"""
    store = Store(root)
    registry = build_registry(store=store, workspace_root=root, roles=("G",)).registry
    return registry.call("doc.write_mapping", role="G", project=".", rows=rows)


def _theorem_row(label: str, env_no: int, ledger_id: str, proof_no: int) -> dict:
    """一条定理行（`file` 指向包里那份 main.tex：证明就在正文里）。"""
    return {"kind": "theorem", "label": label, "env_no": env_no,
            "ledger_id": ledger_id, "proof_no": proof_no, "file": "main.tex",
            "citation_loc_reason": "own result: the proof is in this paper"}


def _details(meta: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in meta.get("problems") or [])


# ============================================================ 4 结构判据（红）
def test_4_more_environments_than_registered_propositions_is_refused_by_name(
        tmp_path: pathlib.Path) -> None:
    """④ 6 个环境 vs 1 条命题 ⇒ doc.write_mapping 受控拒绝，并点名那 5 个 label。"""
    root = _workspace(tmp_path, tex=_CUBE2_TEX, tables={"statements": _CUBE2_STATEMENTS})
    rows = [_theorem_row("thm:nicomachus", 1, f"stmt:{SID}#p1", 1)]
    res = _call_write_mapping(root, rows)
    assert res.ok is False, f"6 个定理类环境对 1 条命题却写成功了：{res.data}"
    assert res.meta.get("kind") == "mapping_not_clean", res.meta
    assert "正文多出 5 个定理类环境" in str(res.error or ""), res.error

    reason = str(res.meta.get("reason") or "")
    assert "正文多出 5 个定理类环境，台账里没有对应命题" in reason, reason
    for label in CUBE2_CLAIM_LABELS:
        assert label in reason, reason
    detail = _details(res.meta)
    assert "正文多出 5 个定理类环境，台账里没有对应命题" in detail, detail
    for label in CUBE2_CLAIM_LABELS:
        assert label in detail, detail
    # 受控：三份照旧写出去了（拒的是"这张表读不过"，不是"半张表"）
    assert (PM.package_dir(root) / PM.MAPPING_JSON_NAME).is_file()
    payload = json.loads((PM.package_dir(root) / PM.MAPPING_JSON_NAME).read_text(encoding="utf-8"))
    assert len(payload["rows"]) == 1, payload

    # 读数：扫描器真的看见了那 6 个环境（5 个印成 Lemma 的 claim 也算）
    got = PM.mapping_reading(root)
    assert got["envs"] == 1, ("对应表那六类里只有 1 个 theorem", got["envs"])
    assert got["statement_envs"] == 6, ("1 个 theorem + 5 个印成 Lemma 的 claim", got)
    assert got["statement_surplus"] == list(CUBE2_CLAIM_LABELS), got["statement_surplus"]


# ============================================================ 5 反真空（绿）
def test_5_as_many_environments_as_propositions_is_allowed(
        tmp_path: pathlib.Path) -> None:
    """⑤ 反真空：正文环境数 == 台账命题数 ⇒ 必须放行（surplus 为空）。"""
    root = _workspace(tmp_path, tex=_CLEAN_TEX, tables=_CLEAN_TABLES)
    rows = [
        _theorem_row("thm:nicomachus", 1, f"stmt:{SID}#p1", 1),
        _theorem_row("thm:faulhaber", 2, f"stmt:{SID2}#p1", 1),
        {"kind": "experiment", "label": "exp:scan", "env_no": 1,
         "ledger_id": f"exp:{EXP}", "proof_no": 1, "file": "main.tex",
         "citation_loc_reason": "own experiment: the scan is reported in the paper"},
    ]
    res = _call_write_mapping(root, rows)
    assert res.ok is True, (res.error, res.meta)
    assert res.data.get("state") == "pass", res.data

    got = PM.mapping_reading(root)
    assert got["state"] == "pass", (got["reason"], _details(got))
    # 印成 Claim 的那个自定义环境不是定理类环境；定理类只有那两个 theorem。
    assert got["statement_envs"] == 2, got["statement_envs"]
    assert got["statement_surplus"] == [], got["statement_surplus"]


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
