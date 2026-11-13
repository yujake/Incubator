# -*- coding: utf-8 -*-
"""判据：B 写入链的五处缺陷（2026-11-05 手工走查 walk-e2e 的 D1 / D2 / D3 / D6）。

## 证据

走查报告在 `temp/walk-e2e-20261105/REPORT.md`（逐字读数在同目录 `calls.jsonl` /
`collect.json`）。这一份把五条判据钉在真实入口（`AgentB.register_statement` /
`Secretary.record_manuscript_dependency_face`）上，每条带反真空：把那一处修法摘掉，
判据必须变红 —— 绿不是来自夹具太松。

| # | 判据 | 改前为什么红 |
|---|---|---|
| D1 a | B 只引 A（`derived_from=[A]`、不给自己稿）⇒ B 的 `proof_text` 不许出现 A 的正文、`bits.reviewed` 不许借 A 的签 | 兜底读盘按 `derived_from` 的号把 `reports/f-proof-A.md` 读成 B 的稿（走查 stmt:000001 的正文 = stmt:000000 的正文） |
| D1 a- | 反真空：把 `_manuscript_is_own` 打成恒真 ⇒ a 变红（正文与签都被借来） | 没有这一支时打桩点不存在 |
| D1 b | A 的稿不许被当 B 的稿读：`manuscript_source=none`、`addressing.hit=false` | 同上（`source=disk`、`address=reports/f-proof-A.md`） |
| D1 c | 依赖边只来自稿里 `## 依赖` 表（`quote` 是表里那行原话、`label` 是"手稿依赖段…"） | 改前按 `derived_from` 扫描落边，表里那行的 `quote` 不在边上 |
| D2 a | 在册命题 + 有稿有签 ⇒ 一次 `register_statement` 后等级 `pre_theorem`、`bits.proof/reviewed=true`、`ok=true` | 升档先算档后写正文 ⇒ 写入期闸整笔拒（`proof_review_without_evidence`） |
| D2 b | 打桩让升档被拒 ⇒ `ok=false` + 拒码，且 `canonical_written` 说清正文写没写（正文写了、升档那一笔没写成，分开报；等级由五元位现算） | 改前不看 `checked/refused`，继续写正文并回 `ok=true/upgraded=true` |
| D2 c | 反真空：把升档判据的三路凭据全打桩成"没签"（手稿签块 / `bits.reviewed` ＋ 台账 / pending）⇒ 升档那一笔不请求（`upgrade_refused` 点名 `CODE_WRITE`）；等级仍由五元位现算，不受这条 lane 的桩影响 | 没有这一支时"有稿"会被读成"签过" |
| D3 a | 同一条边（同 used_by + 来源号 + path_group）经两路描述 ⇒ 只 1 行 | `_dep_step_key` 把 `kind` / `label` 算进身份 ⇒ 2 行 |
| D3 b | 两条不同的边（来源号不同）⇒ 仍 2 行（不许过度合并） | 同上 |
| D3 c | 反真空：把 `kind` / `label` 塞回身份键 ⇒ a 变红 | 没有可打桩点 |
| D6 a | 写完 1 条边之后回执 `deps_missing.state=present`（不再是 `missing`） | 读数在写边之前算（同一份回执里"说缺"与"刚写了 1 条"打架） |
| D6 b | 一条没写且正文零引用 ⇒ `not_applicable` | 三态不许折平 |
| D6 c | 一条没写但正文有引用 ⇒ 受控拒绝 / `missing`（按现行口径） | 静默跳过 |
| D6 d | 反真空：把"写完之后的那几条"从回执里摘掉（`_manuscript_deps_after_write` 少报）⇒ a 变红 | 没有这一支时读的是秘书那一份旧读数 |

零模型调用：B / 秘书这条路只碰 store 与台账；签用 `verifications.record_verification`
的机械三连（不调模型）。
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import agentflow.agent_b.register_statement as RS  # noqa: E402
import agentflow.secretary as SEC  # noqa: E402
from agentflow import depsection as DS  # noqa: E402
from agentflow import evidencebits as EB  # noqa: E402
from agentflow import schema as S  # noqa: E402
from agentflow import verifications as VR  # noqa: E402
from agentflow import vsigns as VS  # noqa: E402
from agentflow.agent_b import AgentB  # noqa: E402
from agentflow.secretary import Secretary  # noqa: E402
from agentflow.store import Store  # noqa: E402

FULL_A = "命题 A：1+1=2。"
BODY_A = "1. 按自然数的后继定义，1+1 就是 s(1)，而 s(1)=2。\n2. 因此 1+1=2。"
FULL_B = "命题 B：2+2=4，由命题 A 推得。"
BODY_B = "1. 由 stmt:{a} 得 1+1=2。\n2. 因此 2+2=4。"
EMPTY_TABLE = (
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |\n"
    "|---|---|---|\n"
    "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


# ---------------------------------------------------------------- 夹具

def _ws(tmp_path: pathlib.Path, name: str = "ws") -> Store:
    st = Store(tmp_path / name)
    st.init()
    return st


def _agent(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _own(full: str, **kw) -> dict:
    payload = {
        "statement_full": full, "statement_text": full[:20], "origin": "own_result",
        "kind": "conjecture", "doc_id": S.format_id(0),
        "quote_reason": "我方自产命题，没有外部引文要比对",
    }
    payload.update(kw)
    return payload


def _row(st: Store, sid: str) -> dict:
    return next(dict(r) for r in st.rows("statements")
                if str(r.get("stmt_id") or "") == str(sid))


def _manuscript(*, sid: str, proposition: str, body: str,
                deps: str = EMPTY_TABLE, plan: str = "000001", sgid: str = "s1",
                wash_actor: str = "secretary-F") -> str:
    head = [f"# F 的证明手稿：{proposition[:40]}", ""]
    if plan:
        head.append(f"- 计划：{plan} · 子目标：{sgid}")
    if wash_actor:
        head.append(f"- 依赖面洗稿：已洗=true；执行者={wash_actor}")
    head += ["", "## 命题", "", proposition, "", "## 证明", "", body,
             "", "## 依赖", "", deps]
    return "\n".join(head)


def _put(st: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(st.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _sign_three(st: Store, *, sid: str, text: str, rel: str, body: str) -> None:
    """签块 + 台账连续三次「成立」：签必须盖住 body 的 sha。"""
    stamped = VS.stamp_manuscript_sign(
        text, proof_sha=VR.text_sha(body), streak=VR.SIGN_STREAK_NEED,
        need=VR.SIGN_STREAK_NEED, verdict="成立",
        at="2026-11-05T12:00:00+08:00",
        ledger=f"verifications/{sid}.jsonl#v-000003",
        statement_id=sid, manuscript_id=sid)
    _put(st, rel, stamped)
    for _i in range(int(VR.SIGN_STREAK_NEED)):
        VR.record_verification(
            st.root, statement_id=sid, proof_text=body,
            verdict={"verdict": "成立", "findings": []}, verifier="agent-V",
            store=st, proof_no=1, manuscript=rel, secretary_judge={"checked": True, "axis": "clean", "decision": "没问题", "reason": "夹具：秘书判 clean"})


def _register_conjecture(st: Store, full: str) -> str:
    got = _agent(st).register_statement(
        **_own(full, proof_text="", evidence_kind="cross_check"))
    assert got.get("ok") is True, got
    return str(got["stmt_id"])


def _promote_to_proof_review(st: Store, sid: str, body: str) -> str:
    """把一条在册命题抬到 `pre_theorem`（先落签、再改档；只给夹具用）。

    2026-11-05 口径：等级是唯一的轴 —— 可引资格由 `evidencebits.derive_grade` 从五元位
    现算，`evidence_kind` 只是历史列。所以这一格除了写 `proof_text`，还要把第 2 位
    （`proof`）落成真：只改 `evidence_kind` 的旧写法在新口径下等级仍是 `conjecture`
    （第 3 位由 `_sign_three` 的台账写回翻真），引用门会如实拒它。
    """
    rel = f"reports/f-proof-{sid}.md"
    text = _manuscript(sid=sid, proposition=_row(st, sid)["statement_full"],
                       body=body, deps=EMPTY_TABLE)
    row = _row(st, sid)
    row["proof_text"] = body
    row["bits"] = EB.bits_of(origin=str(row.get("origin") or "own_result"),
                             proof=True, proof_process=body,
                             kind=str(row.get("kind") or ""))
    with st.tx("statements", actor="test", note="fixture:seed-body") as tx:
        tx.upsert("statements", row)
    _sign_three(st, sid=sid, text=text, rel=rel, body=body)
    row = _row(st, sid)
    # 档位只由等级反算（`kind_from_bits`）：`proof ∧ reviewed` ⇒ `pre_theorem`，
    # 反算名是 `proof_review`。历史列与现算等级逐字对应，不是另写一份真值。
    row["evidence_kind"] = EB.kind_from_bits(row["bits"], kind=str(row.get("kind") or ""))
    row["kind"] = "theorem"
    with st.tx("statements", actor="test", note="fixture:seed-grade") as tx:
        tx.upsert("statements", row)
    return rel


# ============================================================ D1
def test_d1_a_a_cited_manuscript_is_never_the_new_rows_body(
        tmp_path: pathlib.Path) -> None:
    """D1 a/b：B 只引 A（不给自己稿）⇒ A 的正文与签都不许被借来。"""
    st = _ws(tmp_path)
    a = _register_conjecture(st, FULL_A)
    _promote_to_proof_review(st, a, BODY_A)  # 盘上 reports/f-proof-<a>.md（声明 stmt:a）

    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text="", evidence_kind="heuristic", derived_from=[a]))
    assert got.get("ok") is True, got
    bid = str(got["stmt_id"])
    row = _row(st, bid)
    assert str(row.get("proof_text") or "") == "", (
        f"B 的 proof_text 出现了 A 的正文：{row.get('proof_text')!r}")
    assert BODY_A.split("\n")[0] not in str(row.get("proof_text") or "")
    assert (row.get("bits") or {}).get("reviewed") is not True, row.get("bits")
    assert str(got.get("proof_text_source") or "") != DS.SOURCE_MANUSCRIPT, got
    # b：A 的稿没有被当成 B 的稿读
    assert str(got.get("manuscript_source") or "") == DS.SOURCE_NONE, got
    assert (got.get("addressing") or {}).get("hit") is False, got.get("addressing")
    assert not list(st.rows("dependencies"))


def test_d1_a_reverse_vacuum_putting_the_ownership_check_back_makes_it_red(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D1 a-：把"只认本行稿"那一步摘掉（恒真）⇒ 改前的形态回来（a 变红）。

    2026-11-10（D268 批 2）：这条反真空钉的"借来"有两个半边，两半边的结论不一样：

    - 正文那一半仍然被借来（`proof_text == BODY_A`）—— 摘掉归属检查，D1 的漏洞
      就回来了，这是这条判据要量的东西，一个字没改；
    - 签那一半不再借得动：批 2 起签是 `out/vsigns/<正文 sha>.json` 里一份按
      （命题号, 证明号）绑定的可复算凭据，A 的那一签读到 B 头上是 `borrowed`
      ⇒ 第 3 位不翻。旧断言钉的是"块时代"的形态（稿上的九格块与号无关，借了正文
      就顺带借到签），批 2 之后那不是等价读数：`reviewed=True` 会等于说"签可以被
      借"，与「借光不算签」正相反。新断言比旧的更严：它把"正文借到了"与"签借不到"
      分开钉住 —— 前者仍然红（漏洞可量），后者是一条新的护栏。

    所以下面同时断 `reviewed is not True` 与"那一签的读数就是 borrowed（不是没查
    成、也不是查无此签）"，后者保证前者的绿来自凭据的号绑定这一根线。
    """
    monkeypatch.setattr(RS, "_manuscript_is_own", lambda **kw: True)
    st = _ws(tmp_path)
    a = _register_conjecture(st, FULL_A)
    _promote_to_proof_review(st, a, BODY_A)
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text="", evidence_kind="heuristic", derived_from=[a]))
    assert got.get("ok") is True, got
    row = _row(st, str(got["stmt_id"]))
    assert str(row.get("proof_text") or "") == BODY_A, (
        "打桩之后 B 的 proof_text 没有变成 A 的正文 ⇒ 这条反真空没接到 D1 那根线上")
    # 批 2：正文被借到了，而 A 的签按 (命题号, 证明号) 绑定 ⇒ 借不到。
    assert (row.get("bits") or {}).get("reviewed") is not True, row.get("bits")
    reading = VS.sign_reading(
        st.root, statement_id=str(got["stmt_id"]), proof_text=BODY_A, proof_no=1)
    assert reading.get("state") == "borrowed", reading


def test_d1_c_the_dependency_face_comes_from_the_manuscripts_table(
        tmp_path: pathlib.Path) -> None:
    """D1 c：依赖边来自稿里 `## 依赖` 表的那一行（`quote` 是表里原话）。"""
    st = _ws(tmp_path)
    a = _register_conjecture(st, FULL_A)
    _promote_to_proof_review(st, a, BODY_A)
    b = _register_conjecture(st, FULL_B)
    body = BODY_B.format(a=a)
    table = (
        "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |\n"
        "|---|---|---|\n"
        f"| 由命题 A，1+1=2。 | stmt:{a} | 第 1 步 |\n")
    text = _manuscript(sid=b, proposition=FULL_B, body=body, deps=table)
    rel = f"reports/f-proof-{b}.md"
    _sign_three(st, sid=b, text=text, rel=rel, body=body)
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text=body, proof_manuscript=text,
              evidence_kind="proof_review", kind="conjecture"))
    assert got.get("ok") is True, got
    deps = [dict(d) for d in st.rows("dependencies")
            if str(d.get("used_by")) == f"stmt:{b}"]
    assert len(deps) == 1, deps
    assert deps[0]["source_stmt_id"] == a, deps
    assert deps[0]["quote"] == "由命题 A，1+1=2。", deps
    assert str(deps[0]["label"]).startswith("手稿依赖段（第 "), deps


# ============================================================ D2
def _signed_registered_case(tmp_path: pathlib.Path,
                            name: str = "d2") -> tuple[Store, str, str, str]:
    """在册一条猜想 + 盘上一份带签的稿 + 台账三次「成立」（D2 的现场）。"""
    st = _ws(tmp_path, name)
    sid = _register_conjecture(st, FULL_B)
    # 正文不点 `stmt:` 号：这一份夹具只判 D2 的「正文先写、档位后升」，不判依赖面。
    # 改前写 `BODY_B.format(a="000000")`（= 本行自己的号）：它在册之后，正文点号而
    # `## 依赖` 表 0 行会被另一道真闸（`depsection.dependency_consistency_problem`，
    # 2026-11-05 33e25783 落的那一道）整笔拒成 `deps_table_disagrees_with_proof`，
    # 量不到 D2。依赖面那几条判据在 D1 c / D6 里各自有正控与反真空。
    body = "1. 由定义直接得到 2+2=4。\n2. 因此 2+2=4。"
    text = _manuscript(sid=sid, proposition=FULL_B, body=body, deps=EMPTY_TABLE)
    rel = f"reports/f-proof-{sid}.md"
    _sign_three(st, sid=sid, text=text, rel=rel, body=body)
    return st, sid, body, text


def test_d2_a_one_call_writes_the_body_then_upgrades(tmp_path: pathlib.Path) -> None:
    """D2 a：一次调用后正文进去、等级到 `pre_theorem`、reviewed 翻真、ok=true。

    2026-11-05 口径（等级是唯一的轴）：旧断言看的是历史列 `evidence_kind=="proof_review"`；
    判定面现在读 `depsection.statement_grade`，所以这一格钉等级（`pre_theorem`）。
    第 2 位（`proof`）与第 3 位（`reviewed`）仍逐格钉住 —— 它们是等级的承重凭据。
    """
    st, sid, body, text = _signed_registered_case(tmp_path)
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text=body, proof_manuscript=text,
              evidence_kind="proof_review", kind="conjecture"))
    assert got.get("ok") is True, got
    assert got.get("upgraded") is True, got
    assert got.get("canonical_written") is True, got
    row = _row(st, sid)
    assert DS.statement_grade(row) == "pre_theorem", row
    assert (row.get("bits") or {}).get("proof") is True, row.get("bits")
    assert (row.get("bits") or {}).get("reviewed") is True, row.get("bits")
    assert str(row.get("proof_text") or "") == body, row


def test_d2_b_a_refused_upgrade_says_so_and_says_whether_the_body_was_written(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D2 b：打桩让升档被拒 ⇒ ok=false + 拒码；正文写了没写分开说（不糊成一个 true）。"""
    import agentflow.store as ST

    real_gate = ST._refuse_fake_proof_review

    def _reject_upgrade(root, table, doc, *, before_rows=()):
        rows = doc.get("rows") if isinstance(doc, dict) else None
        before = {str(r.get("stmt_id") or ""): r for r in (before_rows or ())}
        changed = [r for r in (rows or [])
                   if before.get(str(r.get("stmt_id") or "")) != r]
        if any(str(r.get("evidence_kind") or "") == "proof_review" for r in changed):
            raise ValueError(f"{VR.CODE_WRITE}：判据打桩：升档那一笔整笔拒")
        return real_gate(root, table, doc, before_rows=before_rows)

    monkeypatch.setattr(ST, "_refuse_fake_proof_review", _reject_upgrade)
    st, sid, body, text = _signed_registered_case(tmp_path)
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text=body, proof_manuscript=text,
              evidence_kind="proof_review", kind="conjecture"))
    assert got.get("ok") is False, got
    assert got.get("kind") == VR.CODE_WRITE, got
    assert got.get("upgraded") is not True, got
    # "正文是否写入"必须说清：这一笔正文写了（canonical_written=true），升档那一笔被拒。
    assert got.get("canonical_written") is True, got
    row = _row(st, sid)
    # 等级不是"档位那一笔"写出来的：它由五元位现算（正文与签已经在预写那一笔落进这一行），
    # 所以升档事务被拒之后行上的等级仍是 pre_theorem。旧断言钉的是历史列（cross_check），
    # 那只是"升档那一笔没写成"的读数；判定面读的是这里这一格。
    assert DS.statement_grade(row) == "pre_theorem", row
    assert (row.get("bits") or {}).get("proof") is True, row.get("bits")
    assert (row.get("bits") or {}).get("reviewed") is True, row.get("bits")
    assert str(row.get("proof_text") or "") == body, (
        "拒的是升档，不是正文：正文这一格要说得出它写没写")


def _no_upgrade_basis(monkeypatch: pytest.MonkeyPatch) -> None:
    """把升档的三路凭据全打桩成"没签"（B 与秘书读的是同一组，任一路命中即升档）。

    为什么不能只摘手稿那一支：这一份夹具的台账里也有三次「成立」（`_sign_three`）
    ⇒ 只要 B 与秘书按三路判据读，台账那一支照样能把档位顶上去，而 `D2 c` 要量的
    是"没有凭据就不许升"。两处一起摘，判据才量得到"升档真的靠凭据"。
    """
    monkeypatch.setattr(SEC, "_manuscript_upgrade_basis",
                        lambda **kw: {"checked": True, "signed": False,
                                      "basis": "", "why": "打桩：手稿那一支不存在",
                                      "manuscript": {}})
    monkeypatch.setattr(VR, "proof_review_gap", _no_gap)


def _no_gap(*_a, **_kw) -> dict:
    """`verifications.proof_review_gap` 的"没有凭据"读数（台账 / pending 那一支不存在）。"""
    return {"ok": False, "checked": True, "why": "打桩：台账 / pending 那一支不存在",
            "state": "unsigned", "verification_id": "", "ledger": "",
            "sha_matches": None, "proof_no": None, "rows": 0,
            "problems": [], "checklist": []}


def test_d2_c_reverse_vacuum_without_the_manuscript_evidence_stays_weak(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D2 c：把升档判据的三路凭据全打桩成"没签" ⇒ 升档那一笔不请求、`upgrade_refused`
    如实说；而等级由五元位现算，不受这条 lane 的桩影响（这一行仍有 proof ＋ reviewed）。

    ## 旧名里的 "stays weak" 现在指历史档位列，不指等级（2026-11-05 口径）
    改前这条判据钉 `row.evidence_kind == "cross_check"` —— 那次"没升"只是历史列没动。
    等级成为唯一的轴之后，同一行的等级读的是 `bits`：这份夹具的手稿签块与台账三次
    「成立」都是真凭据，`_attach_proofs` 认签之后 `reviewed` 翻真 ⇒ 现算等级
    `pre_theorem`。所以断言改成等级，并把"升档这一笔被拒"钉在它自己的读数上
    （`upgraded` / `upgrade_refused`）—— 两件事不许再糊成一个词。

    2026-11-05 补：B 的预写那一格改成与秘书同口径（三路任一路命中）之后，只摘手稿
    那一支不再足以让历史列回落 —— 这份夹具的台账本来就有三次「成立」。所以反真空的
    打桩点跟着判据走：两路全摘。
    """
    _no_upgrade_basis(monkeypatch)
    st, sid, body, text = _signed_registered_case(tmp_path)
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text=body, proof_manuscript=text,
              evidence_kind="proof_review", kind="conjecture"))
    assert got.get("ok") is True, got
    assert got.get("upgraded") is not True, got
    assert got.get("canonical_written") is True, got
    row = _row(st, sid)
    assert DS.statement_grade(row) == "pre_theorem", row
    assert (row.get("bits") or {}).get("reviewed") is True, row.get("bits")
    assert (got.get("upgrade_refused") or {}).get("refused") == VR.CODE_WRITE, got


# ============================================================ D3
def _two_routes_reading(st: Store, *, kind: str, label: str) -> None:
    """两路描述同一条边：第一路 derived_from 形态、第二路稿里 `## 依赖` 形态。

    2026-11-06（业主口径的纠正）：被引的那条要先够格（在册 ∧ `pre_theorem`）——
    引一条 `conjecture` 现在整笔受控拒，D3 量的是"同一身份键怎么算"而不是那道引用门。
    """
    sec = Secretary("B", root=st.root, store=st)
    a = str(st.rows("statements")[0].get("stmt_id") or "")
    b = str(st.rows("statements")[1].get("stmt_id") or "")
    _promote_to_proof_review(st, a, "证明：夹具：被引的那一条。")
    g1 = [[{"stmt_id": a, "kind": kind, "label": label, "quote": "", "path_group": 1}]]
    sec.record_manuscript_dependency_face(b, g1, note="test:d3:route-1")
    rows = [{"stmt_id": a, "quote": "由定理甲", "step": "第 1 步", "path_group": 1}]
    g2 = DS.deps_groups(rows, {a: "proposition", b: "theorem"})
    sec.record_manuscript_dependency_face(b, g2, note="test:d3:route-2")


def test_d3_a_one_edge_is_one_row_whichever_route_describes_it(
        tmp_path: pathlib.Path) -> None:
    """D3 a：同一条边经两路描述 ⇒ `dependencies` 只 1 行（`kind`/`label` 不算身份）。"""
    st = _ws(tmp_path, "d3")
    _register_conjecture(st, FULL_A)
    _register_conjecture(st, FULL_B)
    _two_routes_reading(st, kind="theorem", label="stmt:000000")
    deps = [dict(d) for d in st.rows("dependencies")]
    assert len(deps) == 1, deps


def test_d3_b_two_different_edges_still_take_two_rows(tmp_path: pathlib.Path) -> None:
    """D3 b：两条不同的边（来源号不同）⇒ 仍 2 行（别过度合并）。"""
    st = _ws(tmp_path, "d3b")
    _register_conjecture(st, FULL_A)
    _register_conjecture(st, "命题 C：另一条。")
    b = _register_conjecture(st, FULL_B)
    sec = Secretary("B", root=st.root, store=st)
    ids = [str(r.get("stmt_id")) for r in st.rows("statements")]
    a, c = ids[0], ids[1]
    for src in (a, c):
        #: 2026-11-06：被引的两条都要够格（在册 ∧ pre_theorem），否则引用门先拒。
        _promote_to_proof_review(st, src, f"证明：夹具：被引的 {src}。")
        groups = [[{"stmt_id": src, "kind": "theorem", "label": f"stmt:{src}",
                    "quote": "", "path_group": 1}]]
        sec.record_manuscript_dependency_face(b, groups, note="test:d3:diff")
    deps = [dict(d) for d in st.rows("dependencies")
            if str(d.get("used_by")) == f"stmt:{b}"]
    assert len(deps) == 2, deps


def test_d3_c_reverse_vacuum_putting_label_back_splits_the_edge(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D3 c：把 `kind` / `label` 塞回身份键 ⇒ a 变红（同一条边落两行）。"""
    saved = SEC._dep_step_key

    def _with_kind_and_label(row):
        return saved(row) + (str(row.get("kind") or ""), str(row.get("label") or ""))

    monkeypatch.setattr(SEC, "_dep_step_key", _with_kind_and_label)
    st = _ws(tmp_path, "d3c")
    _register_conjecture(st, FULL_A)
    _register_conjecture(st, FULL_B)
    _two_routes_reading(st, kind="theorem", label="stmt:000000")
    deps = [dict(d) for d in st.rows("dependencies")]
    assert len(deps) == 2, (
        "把 kind/label 塞回身份键之后同一条边仍只 1 行 ⇒ 这条反真空没接到 D3 那根线上")


# ============================================================ D6
def _d6_case(tmp_path: pathlib.Path, *, with_ref: bool,
             name: str = "d6") -> tuple[Store, str, dict]:
    st = _ws(tmp_path, name)
    a = _register_conjecture(st, FULL_A)
    _promote_to_proof_review(st, a, BODY_A)
    b = _register_conjecture(st, FULL_B)
    body = BODY_B.format(a=a) if with_ref else "证明：由定义直接得到，不引用任何在册命题。"
    table = EMPTY_TABLE
    if with_ref:
        table = (
            "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 |\n"
            "|---|---|---|\n"
            f"| 由命题 A，1+1=2。 | stmt:{a} | 第 1 步 |\n")
    text = _manuscript(sid=b, proposition=FULL_B, body=body, deps=table)
    rel = f"reports/f-proof-{b}.md"
    _sign_three(st, sid=b, text=text, rel=rel, body=body)
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text=body, proof_manuscript=text,
              evidence_kind="proof_review", kind="conjecture"))
    return st, b, got


def test_d6_a_the_receipt_reads_the_dependency_face_after_the_write(
        tmp_path: pathlib.Path) -> None:
    """D6 a：写完 1 条边之后 `deps_missing.state=present`（不是 missing）。"""
    st, b, got = _d6_case(tmp_path, with_ref=True)
    assert got.get("ok") is True, got
    md = dict(got.get("manuscript_deps") or {})
    assert int(md.get("deps_written") or 0) == 1, got
    reading = dict(got.get("deps_missing") or {})
    assert reading.get("state") == SEC.DEPS_MISSING_PRESENT, reading
    assert int(reading.get("deps_written") or 0) == 1, reading
    assert str(reading.get("why") or "").strip(), reading


def test_d6_b_no_edge_and_no_reference_is_not_applicable(
        tmp_path: pathlib.Path) -> None:
    """D6 b：一条没写且正文零引用 ⇒ `not_applicable`（不是"缺依赖"）。"""
    _st, _b, got = _d6_case(tmp_path, with_ref=False, name="d6b")
    assert got.get("ok") is True, got
    reading = dict(got.get("deps_missing") or {})
    assert reading.get("state") == SEC.DEPS_MISSING_NOT_APPLICABLE, reading
    assert int(reading.get("deps_written") or 0) == 0, reading


def test_d6_c_an_edge_that_cannot_be_written_is_refused(tmp_path: pathlib.Path) -> None:
    """D6 c：正文有引用而稿里没有 `## 依赖` 段 ⇒ 受控拒绝（不静默跳过）。"""
    st = _ws(tmp_path, "d6c")
    a = _register_conjecture(st, FULL_A)
    _promote_to_proof_review(st, a, BODY_A)
    body = BODY_B.format(a=a)
    no_section = ("# F 的证明手稿：夹具\n\n\n"
                  "## 命题\n\n夹具命题。\n\n## 证明\n\n" + body + "\n")
    got = _agent(st).register_statement(
        **_own(FULL_B, proof_text=body, proof_manuscript=no_section,
              evidence_kind="heuristic", kind="conjecture"))
    assert got.get("ok") is False, got
    assert got.get("kind") == DS.REFUSED_SECTION_MISSING, got
    assert not [d for d in st.rows("dependencies")
                if str(d.get("used_by")) == f"stmt:{got.get('stmt_id') or ''}"]


def test_d6_d_reverse_vacuum_dropping_the_post_write_edges_makes_it_missing(
        tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """D6 d：把"写完之后补落的那几条"从回执里摘掉 ⇒ a 变红（回落到 missing）。"""
    real = AgentB._manuscript_deps_after_write

    def _under_report(self, sec, stmt_id, deps_groups, **kw):
        # `**kw`：这条桩只改"写后回报"的读数，而被打的真函数后来多收了命名关键字
        # （`manuscript=` / `body_sha=` 一类）。桩要跟着收下它们、原样转给真实现，
        # 否则红的是"桩的签名"，而不是它要反真空的那条判据。
        got = real(self, sec, stmt_id, deps_groups, **kw)
        if got:
            return {**dict(got), "deps_written": 0}
        return got

    monkeypatch.setattr(AgentB, "_manuscript_deps_after_write", _under_report)
    _st, _b, got = _d6_case(tmp_path, with_ref=True, name="d6d")
    reading = dict(got.get("deps_missing") or {})
    assert reading.get("state") == SEC.DEPS_MISSING_ABSENT, (
        "把后落的那几条从回执里摘掉之后仍读成 present ⇒ 这条反真空没接上")


if __name__ == "__main__":          # pragma: no cover - 手工跑这一份时用
    raise SystemExit(pytest.main([__file__, "-q"]))
