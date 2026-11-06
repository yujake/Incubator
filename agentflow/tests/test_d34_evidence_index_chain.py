# -*- coding: utf-8 -*-
"""判据 ①–⑦（D-34）：D 的报告是目录，B 顺索引取正文，V 的签按对象内容 sha 认领。

## 业主口径（逐字）

> ①「E 拿着有 V 签名的报告上报 D 找 B 入库，和 F 拿着 V 签名的证明上报 D 找 B 入库是一个逻辑」
> ②「一般来说 D 会是 E 和 F 的父代理，所以我的用词是上报，即向上找 D 而非向下派 D。
>    如果向上直接是 M 也无所谓，M 会派 D」
> ③「D 侧报告的多半是新成果，B 基本都是从 D 的报告看到定理（命题），经索引看 F 侧证明或
>    E 侧报告，并核实 V 签，然后 B 拿着这些注册定理（命题）入库」

⇒ 模型：D 的报告＝目录（新成果＋索引）｜F 证明 / E 报告＝正文｜V 签＝盖章｜B＝读者。
改前缺的正是末尾那一句：目录里没有 E 那本的条目。

| # | 判据 | 改前为什么红 |
|---|---|---|
| ① | D 的报告里数值定理那条有指向 E 报告的索引（path + sha） | `papermapping` 没有这一档判据，缺四格的行照样 pass |
| ② | B 顺索引取到 E 报告 + V 签 ⇒ 登记成 proof；索引指不到对象 ⇒ 拒并点名缺哪一段 | B 只按命题号找签，索引这一环对 E 侧不存在 |
| ③ | B 顺索引取到 F 的证明 + V 签 ⇒ 登记成 proof（老路回归，不许改坏） | 非三段式的证明栏在 ⑥ 那一档被一律拒，F 的证明进不了 proof |
| ④ | V 的签与对象 sha 不符 ⇒ 拒 | 索引里的签没有任何东西核，写什么都被当成签过了 |
| ⑤ | V 在命题尚未登记时审的签不丢（按 sha 可认领；r34b 丢掉的那条「成立」） | `statement_missing` ⇒ 不落台账 ⇒ 结论只能 escalation 掉 |
| ⑥ | 反真空：把"索引解析"打桩恒成功 ⇒ ②③ 的负控必红 | 判据自身要能红 |
| ⑦ | 历史不追溯：r34b 那 4 条 cross_check 不升档 | 新闸若"扫全库升档"，历史行会被顺手抬上去 |

全部用例在 `tmp_path` 里自建工作区，一个模型调用都不发（V 的会审路径是机械七项）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib

import pytest

from conftest import add_literature, sync_counters  # noqa: E402

from agentflow import evidencebits as EB
from agentflow import exhaustionreport as ER
from agentflow import numericproof as NP
from agentflow import papermapping as PM
from agentflow import schema as S
from agentflow import verifications as VR
from agentflow.agent_b import AgentB
from agentflow.agent_e import AgentE
from agentflow.agent_v import AgentV
from agentflow.store import Store

TS = "2026-10-23T00:00:00+08:00"
SCRIPT_REL = "code/enum_ramsey34.py"
BODY = "对任意正整数 n，R(3,4)=9。"

#: 一个真的穷举脚本（与 `test_b_third_party_signature_gate.py` 同形：搜索空间的数字在
#: "报数之前"的代码段里有着落）。
EXHAUSTIVE_PROBE = """
import json
N = 9
SPACE = 2 ** 36
TOTAL = 68719476736
print("REPRO_RESULT: " + json.dumps({
    "result": "supports", "evidence_kind": "cross_check",
    "observations": {
        "exhaustive": True,
        "design": "把 R(3,4)=9 的上界归约成 K_9 的二染色穷举：按 4-子集布尔赋值编码逐点检查",
        "enumeration": ("枚举 K_9 全部 2^36 = 68719476736 个二染色；先按顶点置换取 canonical form "
                        "去掉对称性重数，再按 3-子集/4-子集的对称性剪枝；每个染色都落在枚举里，"
                        "无一遗漏；边界：n=9 是上界侧的全部，n<=8 由 witness 覆盖"),
        "search_space": {"graph": "K_9", "colourings": 68719476736},
    },
    "counterexample": None, "negation_kind": "not_proved",
    "bound": {"n": 9}, "strategy": "canonical form + symmetry breaking",
}))
"""

#: F 侧的证明（自然语言：不是三段式程序证明栏）。
F_PROOF = (
    "Proof. 设 G 是 K_9 的一个 2-着色。取顶点 1，它的红邻域与蓝邻域里至少一个不小于 4。"
    "若红邻域有 4 个点，这 4 点之间要么有一条红边（与顶点 1 成红 K_3），要么全是蓝边"
    "（成一色 K_4）。两种情形都给出目标子图，故上界成立。"
)
#: F 那份证明落在盘上的文件（相对仓库根）。
F_PROOF_REL = "proofs/000009-p1.md"


# ------------------------------------------------------------------ 夹具

def _store(tmp_path: pathlib.Path) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    return st


def _write(store: Store, rel: str, body: str) -> str:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return rel


def _run_exhaustive(store: Store) -> dict:
    """E 真跑一次穷举实验，并把 ②③ 落到盘上（这一步之后那条实验才是 proof）。"""
    _write(store, SCRIPT_REL, EXHAUSTIVE_PROBE)
    out = AgentE(store, config={}, workspace_root=store.root).run_experiment(
        "R(3,4)=9（K_9 的二染色穷举）", "ramsey34=9", SCRIPT_REL, method="numeric")
    row = [r for r in store.rows("experiments") if r["experiment_id"] == out["experiment_id"]][0]
    sig = NP.signature_of(row)
    facts = ER.land_report(
        store.root, experiment_id=row["experiment_id"], claim=row.get("claim"),
        claim_key=row.get("claim_key"), script_path=row.get("code_path"),
        script_sha256=row.get("code_hash"), design=sig.get("design"),
        enumeration=sig.get("enumeration"), search_space=sig.get("search_space"),
        result=row.get("result"), evidence_kind=row.get("evidence_kind"))
    obs = dict(row.get("observations") or {})
    obs[ER.REPORT_KEY] = facts
    redo = NP.sign_experiment(
        method=row["method"],
        derived={"result": row.get("result"), "evidence_kind": row.get("evidence_kind"),
                 "negation_kind": row.get("negation_kind"), "observations": obs},
        code_path=row.get("code_path"), code_hash=row.get("code_hash"),
        certificate=row.get("certificate"), search_bound=row.get("search_bound") or {},
        experiment_id=row["experiment_id"])
    new_row = dict(row, evidence_kind=redo["evidence_kind"],
                   observations=redo["observations"])
    with store.tx("experiments", actor="test") as tx:
        tx.upsert("experiments", new_row, note="e-sign")
    sync_counters(store)
    return {"column": NP.proof_column(new_row), "row": new_row,
            "experiment_id": row["experiment_id"],
            "report_rel": ER.report_relpath(row["experiment_id"])}


def _bytes_sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_index(store: Store, **cells) -> list[dict]:
    """把 D 报告的那一行（目录行）写到 `out/paper/MAPPING.json`（唯一写口）。"""
    row = {"kind": "theorem", "label": "thm:r34", "env_no": 1,
           "ledger_id": f"stmt:{S.format_id(0)}", "proof_no": 1,
           "file": SCRIPT_REL,
           "citation_loc_reason": "我方自产命题（E 签的穷举证明），没有外部引文"}
    row.update(cells)
    PM.write_mapping(store.root, [PM.Row(**row)])
    return PM.index_rows(store.root)


def _index_for_e_report(store: Store, env: dict, **over) -> list[dict]:
    """E 报告那一路的索引四格（`evidence_kind=report`，对象是那份报告文件）。"""
    report = pathlib.Path(store.root) / env["report_rel"]
    sha = _bytes_sha(report)
    cells = {"numeric_evidence": f"exp:{env['experiment_id']}",
             "exhaustion_note": env["report_rel"],
             "evidence_kind": NP.INDEX_KIND_REPORT,
             "evidence_path": env["report_rel"],
             "evidence_sha256": sha,
             "v_signature": {"verdict": "成立", "sha256": sha}}
    cells.update(over)
    return _write_index(store, **cells)


def _index_for_f_proof(store: Store, *, sha: str, **over) -> list[dict]:
    """F 证明那一路的索引四格（`evidence_kind=proof`，对象是那份证明文件）。"""
    cells = {"file": F_PROOF_REL,
             "evidence_kind": NP.INDEX_KIND_PROOF,
             "evidence_path": F_PROOF_REL,
             "evidence_sha256": sha,
             "v_signature": {"verdict": "成立", "sha256": sha}}
    cells.update(over)
    return _write_index(store, **cells)


def _b(store: Store) -> AgentB:
    return AgentB(store, extractor=None, extract_text=None)


def _file(store: Store, *, column: str, kind: str = "theorem",
          evidence_kind: str = "proof", body: str = BODY,
          manuscript: str = "") -> dict:
    return _b(store).register_statement(
        origin="own_result", kind=kind, label="R(3,4)=9", statement_full=body,
        statement_text=body[:40], proof_text=column, evidence_kind=evidence_kind,
        doc_id=S.format_id(0), line_range={"start": 1}, quote_verified=False,
        quote_reason="own_result：我方推导，没有第二份文本可比对",
        proof_manuscript=manuscript)


def _file_conjecture(store: Store, *, column: str, body: str = BODY,
                     manuscript: str = "") -> dict:
    """先按猜想落库（V 只审在册的命题 ⇒ 会审之前这一条只能是猜想）。"""
    return _file(store, column=column, kind="conjecture",
                 evidence_kind=NP.SUPPORTED_ONLY_KIND, body=body,
                 manuscript=manuscript)


def _statement(store: Store, body: str = BODY) -> dict:
    return next(r for r in store.rows("statements")
                if str(r.get("statement_full") or "").strip() == body)


def _ledger(store: Store, sid: str, rows: list[dict]) -> pathlib.Path:
    """手写一份 V 的台账（F 侧那一路要走模型，所以这里只控 verdict 与 sha）。"""
    path = pathlib.Path(store.root) / VR.VERIFICATIONS_DIR / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(dict(r, stmt_id=sid, statement_id=sid), ensure_ascii=False)
             for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


# ============================================================ ① D 的报告里有没有索引
def _mapping_workspace(root: pathlib.Path, *, cells: dict | None = None) -> pathlib.Path:
    """一个真实的工作区："E 跑过 + B 按猜想登记 + 论文包 + 对应表那一行"。

    用真台账（不是手写 JSON）造夹具：`mapping_reading` 会按 `ledger_id` 去表里解析，
    而"数值实验定理那一行"的每一格都要与台账对得上（`numeric_evidence` / `exhaustion_note`
    / 三段式证明栏 / 索引四格）。
    """
    root = pathlib.Path(root)
    store = _store(root.parent / (root.name + "-store"))
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    filed = _file_conjecture(store, column=env["column"])
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])
    report = pathlib.Path(store.root) / env["report_rel"]
    sha = _bytes_sha(report)
    row = {"kind": "theorem", "label": "thm:r34", "env_no": 1,
           "ledger_id": f"stmt:{sid}", "proof_no": 1, "file": SCRIPT_REL,
           # 2026-11-04：`lean_file` 是「机器核验凭据」那一格 —— 数值证明通道填的就是
           # 证明栏第 ① 段那份程序（与 `file` 同一份），不再只是 Lean 源码的位置。
           "lean_file": SCRIPT_REL,
           "numeric_evidence": f"exp:{env['experiment_id']}",
           "exhaustion_note": env["report_rel"],
           "evidence_kind": NP.INDEX_KIND_REPORT,
           "evidence_path": env["report_rel"],
           "evidence_sha256": sha,
           "v_signature": {"verdict": "成立", "sha256": sha},
           "citation_loc_reason": "我方自产命题（E 签的穷举证明），没有外部引文"}
    row.update(cells or {})
    package = PM.package_dir(store.root)
    package.mkdir(parents=True, exist_ok=True)
    (package / "main.tex").write_bytes(
        ("\\documentclass{article}\n\\begin{document}\n"
         "\\begin{theorem}\\label{thm:r34}\nR(3,4) = 9.\n\\end{theorem}\n"
         "\\begin{proof}\nE's exhaustion of all 2^36 colourings, program "
         "\\texttt{code/enum\\_ramsey34.py}, reading "
         f"\\texttt{{exp:{env['experiment_id']}}}.\n"
         "\\end{proof}\n\\end{document}\n").encode("utf-8"))
    PM.write_package(store.root, [PM.Row(**row)])
    return store.root


def _kinds(reading: dict) -> list[str]:
    return [str(p.get("kind")) for p in reading.get("problems") or []]


def _details(reading: dict) -> str:
    return " ｜ ".join(str(p.get("detail")) for p in reading.get("problems") or [])


@pytest.mark.usefixtures("signed_v_handoffs")
def test_1_the_d_report_indexes_the_e_report(tmp_path: pathlib.Path) -> None:
    """① 数值实验定理那一行带四格 ⇒ pass；没有指向 E 报告的索引（path + sha）⇒ 红。

    改前红：`papermapping` 没有这一档判据，缺四格的行照样 `state=pass`。
    """
    ok_root = _mapping_workspace(tmp_path / "ok")
    got = PM.mapping_reading(ok_root)
    assert got["problems"] == [], _details(got)
    assert got["state"] == "pass", got["reason"]

    # 四个格各缺一次：每一次都必须红，且点名缺的是那一格。
    for cell in (NP.INDEX_PATH_FIELD, NP.INDEX_SHA_FIELD, NP.INDEX_SIGN_FIELD,
                 NP.INDEX_KIND_FIELD):
        root = _mapping_workspace(tmp_path / f"no-{cell}", cells={cell: ""})
        bad = PM.mapping_reading(root)
        assert bad["state"] == "fail", (cell, bad["reason"])
        assert NP.INDEX_PATH_FIELD.replace("evidence_", "") or True
        assert "mapping_numeric_evidence_missing" in _kinds(bad), (cell, _details(bad))
        assert cell in _details(bad), (cell, _details(bad))


@pytest.mark.usefixtures("signed_v_handoffs")
def test_1b_the_index_must_point_at_the_bytes_on_disk(tmp_path: pathlib.Path) -> None:
    """① 的另一半：索引写了 path + sha，但 sha 与盘上那份对象不符 ⇒ 红（点名 sha）。"""
    root = _mapping_workspace(tmp_path / "ws", cells={
        NP.INDEX_SHA_FIELD: "0" * 64,
        NP.INDEX_SIGN_FIELD: {"verdict": "成立", "sha256": "0" * 64}})
    got = PM.mapping_reading(root)
    assert got["state"] == "fail", got["reason"]
    assert "mapping_numeric_evidence_missing" in _kinds(got), _details(got)
    assert NP.INDEX_SHA_FIELD in _details(got), _details(got)


# ============================================================ ② E 报告那一路
class _Call:
    """`llmseam.SeamCall` 的替身：`judge()` 只读 ok / problem / detail。"""

    ok = True
    problem = ""
    detail = ""
    text = ""
    model = "fake"
    prompt_version = "t"
    prompt_sha256 = "0" * 64


class _VSecretarySeam:
    """V 的秘书那一档的假缝（`ask_json` 形状）：照剧本签。

    业主 2026-10-29 的追加口径：V 不再自己发签，发签权在 V 的秘书手上 ——
    所以"V 签上了"这条夹具要给它一个带判断面的秘书，否则 `checked=False` 不放签
    （fail-closed）。这里按 `note` 分档回预置结论。
    """

    wired = True

    def __init__(self) -> None:
        self.seen: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = ""):
        self.seen.append(str(note))
        kind = str(note).split(":", 1)[-1]
        answers = {"v_reply_defect": {"decision": "没问题", "reason": "夹具：读不出缺陷"},
                   "sign_issuance": {"decision": "签发", "reason": "夹具：连续次数够了"}}
        return dict(answers.get(kind, {})), _Call()


def _verify_three(store: Store, sid: str, column: str,
                  *, exp_id: str = "") -> tuple[dict, dict]:
    """让 V 审三次同一份证明栏（会审是机械的，不用模型），返回 (第 1 次, 第 3 次)。

    第 1 次必须"不签上"、第 3 次必须"签上"：业主 2026-10-29 的连续 3 次口径。

    2026-11-04（业主裁定 甲）：在册送审必须带手稿（签要落在稿上）⇒ 穷举这一档的
    载体是 E 自己那一趟落下的 `reports/e-proof-<实验号>.md`（`run_experiment` 的
    `land_manuscript` 写的，`## 证明` 与证明栏逐字同源）。判据一个字没改。
    """
    from agentflow import secretary as SEC

    sec = SEC.Secretary("V", root=store.root, store=store,
                        seam=_VSecretarySeam(), enable_model=True)
    v = AgentV(store, workspace_root=store.root, secretary=sec)
    manuscript = ER.proof_manuscript_relpath(exp_id) if str(exp_id or "").strip() else ""
    first = v.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
    assert first.get("checked") is True, first
    assert first.get("signed_bit3") is False, (
        "第 1 次「成立」就签上了第 3 位（连续 3 次才发签）", first)
    v.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
    third = v.verify_proof(sid, proof_text=column, proof_manuscript=manuscript)
    assert third.get("checked") is True and third.get("verdict") == "成立", third
    assert third.get("signed_bit3") is True, third
    assert dict(third.get("sign_issuance") or {}).get("issued") is True, third
    return first, third


def _e_case(tmp_path: pathlib.Path) -> tuple[Store, dict, str]:
    """E 跑穷举 ⇒ B 先按猜想登记 ⇒ V 会审三次、签「成立」⇒ D 写索引。"""
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    filed = _file_conjecture(store, column=env["column"])
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])
    _verify_three(store, sid, env["column"], exp_id=str(env["experiment_id"]))
    _index_for_e_report(store, env)
    return store, env, sid


@pytest.mark.usefixtures("signed_v_handoffs")
def test_2_b_takes_the_e_report_through_the_index(tmp_path: pathlib.Path) -> None:
    """② B 顺索引取到 E 报告 + V 签 ⇒ 登记成 proof；索引指不到对象 ⇒ 拒并点名缺哪一段。"""
    store, env, _sid = _e_case(tmp_path / "ok")
    got = _file(store, column=env["column"])
    assert got.get("ok") is True, got
    row = _statement(store)
    assert row["kind"] == "theorem", row
    assert row["evidence_kind"] == "proof", row

    # 负控一：索引指不到对象（盘上那份报告没了）⇒ 拒，且点名 evidence_path。
    gone, gone_env, _ = _e_case(tmp_path / "gone")
    (pathlib.Path(gone.root) / gone_env["report_rel"]).unlink()
    bad = _file(gone, column=gone_env["column"])
    assert bad.get("ok") is False, bad
    assert bad.get("kind") == "proof_needs_third_party_signature", bad
    error = str(bad.get("error") or "")
    assert "顺索引取对象没成" in error, error
    assert NP.INDEX_PATH_FIELD in error or gone_env["report_rel"] in error, error

    # 负控二：对象被换过（sha 对不上）⇒ 拒，且点名 evidence_sha256。
    tampered, tam_env, _ = _e_case(tmp_path / "tampered")
    target = pathlib.Path(tampered.root) / tam_env["report_rel"]
    target.write_bytes(target.read_bytes() + "\n（这一行是改稿之后加的）\n".encode("utf-8"))
    bad2 = _file(tampered, column=tam_env["column"])
    assert bad2.get("ok") is False, bad2
    assert NP.INDEX_SHA_FIELD in str(bad2.get("error") or ""), bad2.get("error")


@pytest.mark.usefixtures("signed_v_handoffs")
def test_2b_a_signed_exhaustion_is_proof_before_b_files_it(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """回归（2026-11-04，2026-11-05 改读等级）：穷举程序 + V 三转签 ⇒ `theorem`。

    业主口径（`schema.EVIDENCE_KINDS` / `evidencebits.derive_grade`）：穷举数值证明 +
    针对该穷举的 V 签 ⇒ 与 Lean 形式化同级，都算 `theorem`；`pre_theorem` 是
    "V 逐行审过文字证明"那一档，V 不能逐行走查一份程序 ⇒ 穷举题停在 `pre_theorem`
    本身就是错的终态。

    三段都量：① 签落那一刻等级现算就是 `theorem`（不是"再登记一次才升"）；
    ② B 拿着同一份内容来登记仍然 `ok=True`（本来就在终态档，不是重复登记）；
    ③ 反真空：把"按通道落 numeric 位"的判据摘掉 ⇒ 同一条链必须回到 `pre_theorem`。
    """
    store, env, _sid = _e_case(tmp_path / "ok")
    row = _statement(store)
    assert EB.bits_from_row(row)["grade"] == "theorem", row
    bits = dict(row.get("bits") or {})
    assert bits.get("proof") is True and bits.get("reviewed") is True, bits
    assert bits.get("numeric") == "verified", bits
    trace = dict(row.get(VR.GRADE_RECOMPUTED_KEY) or {})
    assert trace.get("to") == "theorem", trace
    assert trace.get("to_kind") == "proof", trace
    assert trace.get("from") == "strong_conjecture", trace
    assert trace.get("channel") == "exhaustion", trace
    assert int(trace.get("proof_no") or 0) == 1, trace

    got = _file(store, column=env["column"])
    assert got.get("ok") is True, got
    # B 这一笔是"同一条已在册、证据档到位"：不新建行，历史列按现算等级反算成 proof。
    assert got.get("new_row") is False, got
    assert got.get("evidence_kind") == "proof", got
    final = _statement(store)
    assert final["kind"] == "theorem", final
    assert final["evidence_kind"] == "proof", final
    assert EB.bits_from_row(final)["grade"] == "theorem", final

    # ---- ③ 反真空：摘掉"按通道落 numeric 位"⇒ 同一条链必须回到 pre_theorem ----
    no_channel = _store(tmp_path / "no-channel")
    add_literature(no_channel, S.format_id(0))
    env2 = _run_exhaustive(no_channel)
    # 打桩要在任何写那一行的路径之前：B 登记（`_attach_proofs`）与 V 落签
    # 都会调 `_grade_recomputed_from_signature`，两次都要把通道判成"找不到"。
    monkeypatch.setattr(NP, "find_signed_exhaustion_for_column",
                        lambda *a, **k: None)
    filed2 = _file_conjecture(no_channel, column=env2["column"])
    assert filed2.get("ok") is True, filed2
    _verify_three(no_channel, str(filed2["stmt_id"]), env2["column"],
                  exp_id=str(env2["experiment_id"]))
    row2 = _statement(no_channel)
    assert EB.bits_from_row(row2)["grade"] == "pre_theorem", (
        "把穷举通道判据打桩成「找不到」之后仍然是 theorem ⇒ 上面那条的绿不是它给的", row2)
    assert dict(row2.get(VR.GRADE_RECOMPUTED_KEY) or {}).get("to") == "pre_theorem", row2
    assert dict(row2.get(VR.GRADE_RECOMPUTED_KEY) or {}).get("to_kind") == "proof_review", row2


# ============================================================ ③ F 证明那一路
def _f_case(tmp_path: pathlib.Path, *, sign_sha: str | None = None) -> tuple[Store, str]:
    """F 的证明 + V 的签 + D 报告里的一行索引（`evidence_kind=proof`）。

    业主 2026-10-29：第 3 位要「同一份正文连续 3 次成立」才翻 ⇒ 台账里是三票
    （v-000001/2/3，同一 sha、同一证明号），而不是改前那一票。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    _write(store, F_PROOF_REL, F_PROOF)
    filed = _file_conjecture(store, column=F_PROOF)
    assert filed.get("ok") is True, filed
    sid = str(filed["stmt_id"])
    sha = _bytes_sha(pathlib.Path(store.root) / F_PROOF_REL)
    # 2026-11-06（裁定 2 / 3 之后）：台账行的轴只能由秘书给 —— 没有
    # `secretary_judge` 这一格的行，`row_signable` 判 False（`ledger_axis` 不再按
    # `verdict` 的字面回退）。这里手写三票是"控制 verdict 与 sha"的夹具，不是"绕过
    # 秘书"：给上与真写口（`verifications.record_verification`）同形的判定格，
    # 三票才仍然是三票。断言一个字没改。
    judge = {"checked": True, "axis": "clean", "decision": "没问题",
             "reason": "夹具：秘书读不出缺陷（F 侧那一路要走模型，这里只控 verdict 与 sha）"}
    _ledger(store, sid, [{"verification_id": f"v-{i:06d}", "proof_no": 1,
                          "verdict": "成立", "proof_sha256": _text_sha(F_PROOF),
                          "object_sha256": sha, "object_path": F_PROOF_REL,
                          "secretary_judge": dict(judge),
                          "at": TS}
                         for i in (1, 2, 3)])
    _index_for_f_proof(store, sha=sha,
                       v_signature={"verdict": "成立", "sha256": sign_sha or sha})
    return store, sid


@pytest.mark.usefixtures("signed_v_handoffs")
def test_3_b_takes_the_f_proof_through_the_index(tmp_path: pathlib.Path) -> None:
    """③ B 顺索引取到 F 的证明 + V 签 ⇒ 登记成 proof（老路回归，不许被这次改坏）。"""
    store, _sid = _f_case(tmp_path / "ok")
    got = _file(store, column=F_PROOF)
    assert got.get("ok") is True, got
    row = _statement(store)
    assert row["kind"] == "theorem" and row["evidence_kind"] == "proof", row


@pytest.mark.usefixtures("signed_v_handoffs")
def test_3b_the_old_statement_ledger_route_still_works(tmp_path: pathlib.Path) -> None:
    """③ 的老路（按命题号的签，没有索引）：一个字节都没被这次改动弄坏。"""
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    filed = _file_conjecture(store, column=env["column"])
    sid = str(filed["stmt_id"])
    _first, signed = _verify_three(store, sid, env["column"],
                                   exp_id=str(env["experiment_id"]))
    assert signed.get("verdict") == "成立", signed
    # 没有 MAPPING.json（`index_rows` 空）⇒ 走原来那一路
    assert PM.index_rows(store.root) == []
    got = _file(store, column=env["column"])
    assert got.get("ok") is True, got
    assert _statement(store)["evidence_kind"] == "proof"


# ============================================================ ④ V 的签与对象 sha 不符
@pytest.mark.usefixtures("signed_v_handoffs")
def test_4_a_signature_on_another_object_is_refused(tmp_path: pathlib.Path) -> None:
    """④ V 的签与对象 sha 不符 ⇒ 拒（索引里写「成立」也不行）。"""
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    filed = _file_conjecture(store, column=env["column"])
    sid = str(filed["stmt_id"])
    AgentV(store, workspace_root=store.root).verify_proof(sid, proof_text=env["column"])
    _index_for_e_report(store, env, v_signature={
        "verdict": "成立", "sha256": _text_sha("另一份对象（不是这一份报告）")})
    got = _file(store, column=env["column"])
    assert got.get("ok") is False, f"V 的签与对象 sha 不符却登记成 proof 了：{got}"
    error = str(got.get("error") or "")
    assert "V 的签与对象 sha 不符" in error, error
    assert _statement(store)["evidence_kind"] != "proof"


# ============================================================ ⑤ 先签后登记
def test_5_a_sign_made_before_registration_is_not_lost(tmp_path: pathlib.Path) -> None:
    """⑤ V 在命题尚未登记时审的签不丢（按内容 sha 可认领 —— r34b 丢掉的那条「成立」）。

    现场复刻：`statements` 0 行，V 审 E 那份报告判「成立」。改前那一签没有落点，
    只能 escalation，结论丢了；现在它落在 `verifications/pending/<sha>.jsonl`，
    B 登记之后按同一个 sha 认领。

    这一条刻意不挂 `signed_v_handoffs`：那一格会在登记之前先补一票签（`_sign` 的
    连续计数因此从 0 起变成 1 起，认领那一档也被它抢走），把"先签后登记"这个现场
    造坏。这里的一签是显式的 `verifications.record_pending_sign`（V 的未在册那一支
    走的正是它），认领与否只由正文 sha 决定。

    2026-11-04（业主裁定 甲）之后这一条有两处按新口径走：
    - 在册/未在册的正判都必须带手稿（签块只在文件上）⇒ 送审带
      `reports/e-proof-<实验号>.md`（E 自己那一趟落的那一份，`## 证明` 与证明栏
      逐字同源），`kind` 因此是 `proof_unregistered_signed`（按号稿那一支），
      不再是只给内联正文时的 `numeric_evidence_unregistered`；
    - 登记那一笔也要带同一份稿（`proof_manuscript`），否则整笔拒
      `proof_manuscript_required`。
    判据本体（那一签不丢、按内容 sha 认领得到）一个字没改：下面仍逐条判
    pending 行、verdict、object_sha256 与 `route=pending`。
    """
    store = _store(tmp_path)
    add_literature(store, S.format_id(0))
    env = _run_exhaustive(store)
    assert list(store.rows("statements")) == []

    man_rel = ER.proof_manuscript_relpath(env["experiment_id"])
    signed = AgentV(store, workspace_root=store.root).verify_proof(
        S.format_id(0), proof_text=env["column"], proof_manuscript=man_rel)
    assert signed.get("checked") is True, signed
    # 改前（只给内联正文）：`numeric_evidence_unregistered`。甲之后走按号稿那一支：
    # `proof_unregistered_signed`（签要落在稿上，那一支才有落点）。
    assert signed.get("kind") == "proof_unregistered_signed", signed
    assert signed.get("verdict") == "成立", signed
    assert signed.get("signed_bit3") is False, signed
    pending_dir = pathlib.Path(store.root) / VR.VERIFICATIONS_DIR / VR.PENDING_DIR_NAME
    landed = sorted(pending_dir.glob("*.jsonl"))
    assert landed, "命题还没在册时审的那一签没有落盘（r34b 丢的就是它）"
    row = json.loads(landed[0].read_text(encoding="utf-8").splitlines()[0])
    assert row["verdict"] == "成立", row
    assert len(str(row.get("object_sha256") or "")) == 64, row

    # 登记：先猜想、再升定理级（B-2/B-3 的既有顺序），索引不需要 —— 认的是内容 sha。
    filed = _file_conjecture(store, column=env["column"], manuscript=man_rel)
    assert filed.get("ok") is True, filed
    got = _file(store, column=env["column"], manuscript=man_rel)
    assert got.get("ok") is True, (
        f"命题登记之前审的那一签丢了：{got}")
    final = _statement(store)
    assert final["kind"] == "theorem" and final["evidence_kind"] == "proof", final

    # 那一签仍在盘上，且按内容 sha 认领得到（不是被"搬走"了）。
    sig = NP.latest_third_party_sign(store.root, proof_text=env["column"],
                                     statement_id=str(filed["stmt_id"]))
    assert sig["found"] is True and sig["verdict"] == "成立", sig
    assert sig["route"] == "pending", sig


# ============================================================ ⑥ 反真空
def _stub_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    """把"顺索引取对象"打桩成恒成功（按 entry 的 evidence_path 现算 sha，problems 恒空）。"""
    def _fake(root, entry):
        got = NP.index_entry_of(entry)
        path = pathlib.Path(str(root)) / got["path"]
        sha = _bytes_sha(path) if path.is_file() else ""
        return {"checked": True, "found": True, "path": got["path"], "sha256": sha,
                "verdict": "成立", "problems": [], "why": "（打桩：恒成功）"}

    monkeypatch.setattr(NP, "resolve_index", _fake, raising=True)


@pytest.mark.usefixtures("signed_v_handoffs")
def test_6_stubbing_the_index_resolution_makes_the_negatives_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ 反真空：把"索引解析"打桩恒成功 ⇒ ②③ 的负控必红。

    两个负控（② 的对象不在盘上 / ③ 的签与对象不符）在真判据下都是拒；桩一打，
    它们必须当场被放行 —— 否则那两条红就不是"索引解析"在管。
    """
    # ② 的负控
    gone, gone_env, _ = _e_case(tmp_path / "gone")
    (pathlib.Path(gone.root) / gone_env["report_rel"]).unlink()
    assert _file(gone, column=gone_env["column"]).get("ok") is False
    _stub_resolve(monkeypatch)
    assert _file(gone, column=gone_env["column"]).get("ok") is True, (
        "把索引解析打桩成恒成功之后仍然被拒 ⇒ ② 的红不是它管的")


@pytest.mark.usefixtures("signed_v_handoffs")
def test_6b_stubbing_it_also_frees_the_f_proof_negative_control(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑥ 的另一半（③）：签与对象 sha 不符那一档，桩一打必须放行。"""
    store, _sid = _f_case(tmp_path / "ws", sign_sha=_text_sha("别的对象"))
    assert _file(store, column=F_PROOF).get("ok") is False
    _stub_resolve(monkeypatch)
    assert _file(store, column=F_PROOF).get("ok") is True, (
        "把索引解析打桩成恒成功之后仍然被拒 ⇒ ③ 的红不是它管的")


# ============================================================ ⑦ 历史不追溯
@pytest.mark.usefixtures("signed_v_handoffs")
def test_7_historical_cross_check_rows_are_not_upgraded(tmp_path: pathlib.Path) -> None:
    """⑦ r34b 那 4 条 cross_check 不升档（新闸不许"扫全库升档"）。"""
    store = _store(tmp_path)
    bodies = [f"r34b 的历史命题 #{i}：一条只拿到数值支持的断言。" for i in range(1, 5)]
    for body in bodies:
        got = _file(store, column="由脚本抽了一批点，结论支持。", kind="conjecture",
                    evidence_kind=NP.SUPPORTED_ONLY_KIND, body=body)
        assert got.get("ok") is True, got
    before = {str(r["statement_full"]): str(r.get("evidence_kind")) for r in store.rows("statements")}
    assert set(before.values()) == {NP.SUPPORTED_ONLY_KIND}, before

    # 把 D-34 的读侧整条跑一遍（读目录、找签、看索引）—— 历史行一个字都不许动。
    assert PM.index_rows(store.root) == []
    for body in bodies:
        assert NP.filing_problems(origin="own_result", evidence_kind=NP.SUPPORTED_ONLY_KIND,
                                  proof_text="由脚本抽了一批点，结论支持。",
                                  experiments=store.rows("experiments"),
                                  root=store.root, statements=store.rows("statements"),
                                  statement_full=body,
                                  index_rows=PM.index_rows(store.root)) == []
    after = {str(r["statement_full"]): str(r.get("evidence_kind")) for r in store.rows("statements")}
    assert after == before, ("历史行被改了：", after, before)
    assert "proof" not in set(after.values()), after


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))


#: 2026-11-02 准入闸默认 strict 之后，本文件的夹具一律先给"B 即将写进台账的那一份
#: 证明正文"补一签（真签：在册走台账、未在册走 pending）。见 conftest 的同名 fixture。
