# -*- coding: utf-8 -*-
"""业主 2026-10-22 晚三条裁定的判据（B-1 / B-2 / B-4）。

裁定逐字（照抄，不改口径）：

```text
B-1（D3）完全不做机械闸。只在提示词里提醒：
    「若出现被指认无可信度的文献，或待审核的文献，则不可当引文入库，只可当研究参考」
    ⇒ 不做 stage 强制、不做出处闸、不改 schema
B-2（D18）没有引文 / 自己编的命题必须从"猜想"注册
B-4 引文回验必须拿到东西：所谓"无来源可核"却仍然写上去了，一定有 我方研究手稿 当背书
    ⇒ no_source 这一档必须指向"我方手稿里的哪一处"
```

（上面第三句里的"我方研究手稿"原文是加粗的；本文件的注释与文档串不许出现 Markdown
强调标记，所以这里按纯文本抄 —— 判据不读强调标记，只读那几个字。）

五条判据，每条都要求"改前红"（没有这一条实现时它必红）：

| 判据 | 守什么 | 反真空 / 负控 |
|---|---|---|
| ① | A / B 的渲染提示词里含那两句的实质 | 把那一句删掉 ⇒ 判据红 |
| ② | own_result + 无 source + quote 不是 true + kind=lemma ⇒ 拒（`must_start_as_conjecture`） | kind 改成 conjecture ⇒ 通过（正控） |
| ③ | 盘上 kind=lemma 而现算 grade=conjecture ⇒ 收工门点名 `type_ahead_of_grade` | 概念行 / conjecture 行不许被点名（负控） |
| ④ | no_source 没给手稿位置 ⇒ 拒（`no_source_without_backing`）；给了 ⇒ 通过且理由里带那个位置 | — |
| ⑤ | 把 B-4 的判定 monkeypatch 成恒通过 ⇒ ④ 必红 | — |

为什么这一批是"提示词 + 写入口 + 读侧"三处而不是一道闸：B-1 的裁定原文就是"完全不做
机械闸"，所以它只有提示词这一条腿（判据 ① 也只钉文本在场）；B-2 与 B-4 才是判据 ——
前者钉"新行不许一进门就自报强档"，后者钉"说无来源可核就必须指得出我方手稿的哪一处"。
两条都不改 schema（`kind` 与 `quote_reason` 都是既有字段，拒绝码是既有的 `refuse` 机制）。
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from agentflow import agent_prompts as AP
from agentflow import closing
from agentflow import quoteevidence as QE
from agentflow.agent_b import AgentB
from agentflow.store import Store
from agentflow.tools import build_registry

#: 裁定给的那一句的实质（两段都要在场：说的是"不能干什么"与"只能干什么"）。
B1_MUST_SAY = "不可当引文入库"
B1_ONLY_AS = "只可当研究参考"

#: 我们自己手稿的一处（裁定给的第一个例子）。
BACKING = "manuscripts/handoffs.jsonl#0042"

TS = "2026-10-22T00:00:00+08:00"


def _b(st: Store) -> AgentB:
    return AgentB(st, extractor=None, extract_text=None, config={})


def _prompt(role: str) -> str:
    registry = build_registry().registry
    return AP.system_prompt(role, registry=registry, task="把这条链路走一遍",
                            workspace_root="D:/x")


def _b1_problems(text: str) -> list[str]:
    """这段提示词里 B-1 那一条的读数（空列表 = 说了）。

    只要两段的实质（"不可当引文入库" / "只可当研究参考"）—— 裁定允许措辞微调，
    所以不钉整句；但两段都缺一不可：只说"只可当研究参考"而没有"不可当引文入库"，
    读起来就成了一句建议（"当参考"），而不是一条禁令。
    """
    bad: list[str] = []
    if B1_MUST_SAY not in text:
        bad.append(f"缺「{B1_MUST_SAY}」")
    if B1_ONLY_AS not in text:
        bad.append(f"缺「{B1_ONLY_AS}」")
    return bad


def _own(**kw) -> dict:
    """一条 `origin="own_result"` 的登记参数（只含动作面声明过的键）。"""
    base = {
        "statement_full": "设 n≥3，则 n^2+n 是偶数。",
        "origin": "own_result",
        "doc_id": "000000",
        "proof_text": "证明：n^2+n = n(n+1)，相邻整数必有一偶。",
        "quote_verified": False,
        "quote_reason": "own_result：我方推导，没有第二份文本可比对",
    }
    base.update(kw)
    return base


def _ok(out) -> dict:
    got = out if isinstance(out, dict) else out.to_dict()
    return got


# ------------------------------------------------------------------ ① B-1 提示词
def test_b1_a_and_b_prompts_say_untrusted_literature_is_reference_only() -> None:
    """① B-1：A 与 B 的渲染提示词里都有那条提醒（其余角色不受它影响）。

    为什么钉"渲染出来的提示词"而不是钉 `specs/*.py` 的字符串：模型读到的是渲染结果。
    声明面写了、渲染路径漏了（段被 `brief_sections` 的空段口径吃掉）时，钉声明的那条
    判据照样绿，而模型一个字都没看到。
    """
    for role in ("A", "B"):
        text = _prompt(role)
        assert _b1_problems(text) == [], f"{role} 的提示词里 B-1 那一条不完整：" \
                                        f"{_b1_problems(text)}"

    # 反真空 ①：这条判据真的抓得住"没说"—— 删掉句子之后必须红。
    stripped = _prompt("A").replace(B1_MUST_SAY, "").replace(B1_ONLY_AS, "")
    assert _b1_problems(stripped), "把那一句删掉之后判据仍然绿 ⇒ 它什么也没守"

    # 反真空 ②：现算的段真的来自 `specs/a.py` / `specs/b.py` 的 policy 一格
    # （不是另抄的一份文案）：把 policy 去掉之后渲染出来的提示词里就没有它了。
    for role in ("A", "B"):
        brief = AP.ROLE_BRIEFS[role]
        assert any(B1_MUST_SAY in line for line in brief.policy), (
            f"{role} 的 policy 里没有 B-1 那一句 ⇒ 它不在唯一真身上（而在别处另抄了一份）")


def test_b1_the_reminder_is_a_prompt_not_a_gate(monkeypatch) -> None:
    """① 的负控（裁定的字面：完全不做机械闸）：拿掉 policy 那一格 ⇒ 提示词里就没有它。

    这一条同时钉住"只在提示词里提醒"这件事：如果哪天有人把这句话搬进 stage 强制或
    出处闸，这条判据不会红（它只管文本），而 B-1 的裁定会被违反 —— 所以判据的另一半
    在下面这条：写入口对"被指认不可信的文献"一个字节都不动（`literature` 的写入路径
    里没有任何 `no_source` / 可信度判定）。
    """
    dropped = {role: brief for role, brief in AP.ROLE_BRIEFS.items()}
    for role in ("A", "B"):
        brief = dropped[role]
        dropped[role] = dataclasses.replace(
            brief, policy=tuple(x for x in brief.policy if B1_MUST_SAY not in x))
    monkeypatch.setattr(AP, "ROLE_BRIEFS", dropped)
    for role in ("A", "B"):
        assert _b1_problems(_prompt(role)), (
            f"{role}：policy 那一格拿掉之后判据仍然绿 ⇒ 它读的不是 policy")


# ------------------------------------------------------------------ ② B-2 写侧
def test_b2_an_uncited_own_result_must_start_as_a_conjecture(store: Store) -> None:
    """② B-2：`own_result` + 无 source + quote 不是 true，声明成 lemma ⇒ 拒收。

    拒信要给出两条正路（改 kind / 走猜想登记那条路）—— 一次只点名一条，等于让智能体
    多跑两趟（`test_b_register_all_missing_hint.py` 的同一个口径）。
    """
    got = _ok(_b(store).register_statement(**_own(kind="lemma")))
    assert got.get("ok") is False, got
    assert got.get("kind") == "must_start_as_conjecture", got
    err = str(got.get("error") or "")
    assert "conjecture" in err and "register_conjecture" in err, err
    assert not store.rows("statements"), "被拒的一笔不许在盘上留下半行"

    # 正控：同一笔内容改成 kind="conjecture" ⇒ 通过（红不是写死的）。
    good = _ok(_b(store).register_statement(**_own(kind="conjecture")))
    assert good.get("ok") is True, good
    rows = store.rows("statements")
    assert len(rows) == 1 and str(rows[0].get("kind")) == "conjecture", rows

    # 负控（不许过度拦截）：有外部出处的那一笔照旧能声明成 lemma。
    with store.tx("literature", actor="test") as tx:
        tx.upsert("literature", {"lit_id": "0000", "title": "探针文献",
                                 "type": "J", "summary": "探针摘要",
                                 "path": "0000/source.txt", "processed": True,
                                 "created_at": TS, "created_by": "test"})
    ext = _ok(_b(store).register_statement(
        statement_full="设 G 是有限群，则 G 的阶有限。", origin="external_lit",
        source_lit_id="0000", page_range={"start": 1}, kind="lemma",
        quote_verified=False, quote_reason="与原文表述不一致（探针）"))
    assert ext.get("ok") is True, ext


def test_b2_kind_is_derived_exactly_once(store: Store, monkeypatch) -> None:
    """② 的附属判据：`kind` 只在一处派生（判据读的那个值 == 落库的那个值）。

    怎么判：把 `_self_authored_gate` 换成一个"只记下收到的 `kind`"的探针，再交一笔
    `kind="  conjecture  "`（带空白）。三处读数必须逐字相同：闸收到的、落库的、
    以及（拒收路径上）返回值里 `statement_kind` 的那个。

    为什么这条值得单独钉：改前这个缺省值在动作里算过两遍（`str(kind or "").strip()`
    与 `str(kind or "theorem")`），各算各的。谁在其中一处加个 `.strip()` 或改一次
    缺省值，"判据读的 kind"与"落库的 kind"就会分家 —— 而它们分家的形态是静默的：
    判据放过的行，落下去以后换了个 kind，没有任何读数会说这两者不是同一个。
    """
    from agentflow.agent_b import register_statement as RS

    seen: list[str] = []
    real = RS._RegisterStatement._self_authored_gate
    holder = type(_b(store))

    def probe(self, **kw):
        seen.append(str(kw.get("kind")))
        return {"needs_v": False, "refused": "", "reason": "",
                "reading": {"checked": True, "needs_v": False, "signed": False,
                            "kind": str(kw.get("kind")),
                            "origin": str(kw.get("origin")), "source_lit_id": "",
                            "stmt_id": "", "verification_id": "", "why": "探针"}}

    monkeypatch.setattr(holder, "_self_authored_gate", probe)
    try:
        out = _ok(_b(store).register_statement(**_own(kind="  conjecture  ")))
    finally:
        monkeypatch.setattr(holder, "_self_authored_gate", real)

    assert out.get("ok") is True, out
    assert seen == ["conjecture"], f"闸收到的 kind 没归一（{seen}）"
    assert store.rows("statements")[0]["kind"] == "conjecture", store.rows("statements")[0]

    # 拒收路径上标的也是同一个值（不是原始入参那个带空白的串）。
    bad = _ok(_b(store).register_statement(**_own(kind="  lemma  ",
                                                 statement_full="另一条探针命题。")))
    assert bad.get("kind") == "must_start_as_conjecture", bad
    assert bad.get("statement_kind") == "lemma", bad


# ------------------------------------------------------------------ ③ B-2 读侧
def _put_stmt(st: Store, stmt_id: str, *, kind: str, **kw) -> None:
    row = {"stmt_id": stmt_id, "origin": "own_result", "kind": kind,
           "statement_full": f"探针命题 {stmt_id}。", "status": "active",
           "quote_reason": "探针：这一行没有外部引文可核（三态里的那一句为什么）",
           "created_at": TS, "created_by": "test"}
    row.update(kw)
    with st.tx("statements", actor="test") as tx:
        tx.upsert("statements", row)


def test_b2_read_side_names_a_type_ahead_of_grade_row(store: Store) -> None:
    """③ B-2 读侧：盘上 kind=lemma 而现算 grade=conjecture ⇒ 收工门点名。

    为什么读侧还要判一次：写入期那道闸只管新行；历史行、别的写入路径、以及"登记时
    是猜想、后来证据位被清掉"的行它都管不着。
    """
    _put_stmt(store, "000001", kind="lemma")            # 没有证明 / 没有 V 的签 ⇒ 猜想
    _put_stmt(store, "000002", kind="conjecture")       # 本来就是猜想 ⇒ 不在这一档
    _put_stmt(store, "000003", kind="concept")          # 概念行 ⇒ 不参与等级链

    reading = closing.type_ahead_of_grade_rows(store)
    assert reading["state"] == "computed", reading
    assert reading["checked"] == 3, reading
    named = [r for r in reading["rows"] if r["class"] == closing.TYPE_AHEAD_OF_GRADE_CODE]
    assert [r["stmt_id"] for r in named] == ["000001"], named
    assert named[0]["kind"] == "lemma" and named[0]["grade"] == "conjecture", named[0]

    # 它真的接到了收工门上（不是只活在一个函数里）。
    rep = closing.check_closing(store, checks=())
    assert rep.readings["statement_grade"]["rows"][0]["stmt_id"] == "000001", \
        rep.readings["statement_grade"]

    # 负控：补上证明过程与 V 的签名之后它就够格了 ⇒ 不再点名（判据不是"永远红"）。
    _put_stmt(store, "000001", kind="lemma", proof_text="证明：探针。",
              bits={"proof": True, "reviewed": True, "numeric": "na", "formal": "na",
                    "audited": False, "origin": "own_result",
                    "evidence": {"proof_process": "证明：探针。", "proof_source": "own",
                                 "numeric_reason": "本行没有数值侧（探针）",
                                 "formal_reason": "本行不做形式化（探针）",
                                 "reviewed_by": {"evidence": "verification:v-1"}}})
    after = closing.type_ahead_of_grade_rows(store)
    assert [r["stmt_id"] for r in after["rows"]] == [], after


# ------------------------------------------------------------------ ④ B-4 背书
def _no_source(**kw) -> dict:
    base = {"kind": "conjecture",
            "quote_reason": "no_source：原文不在盘上，只有元数据"}
    base.update(kw)
    return _own(**base)


def test_b4_no_source_must_point_at_our_own_manuscript(store: Store) -> None:
    """④ B-4：说「无来源可核」而不给手稿位置 ⇒ 拒；给了 ⇒ 通过且理由里带那个位置。"""
    bad = _ok(_b(store).register_statement(**_no_source()))
    assert bad.get("ok") is False, bad
    assert bad.get("kind") == "no_source_without_backing", bad
    err = str(bad.get("error") or "")
    assert "handoffs.jsonl" in err and "out/paper/main.tex" in err, err
    assert not store.rows("statements"), "被拒的一笔不许在盘上留下半行"

    good = _ok(_b(store).register_statement(**_no_source(
        quote_reason=f"no_source：原文不在盘上，凭据是我方手稿 {BACKING}")))
    assert good.get("ok") is True, good
    row = store.rows("statements")[0]
    assert BACKING in str(row.get("quote_reason") or ""), row.get("quote_reason")

    # 另外两种写法（裁定给的例子）同样算"指到了哪一处"。
    for reason in ("no_source：见 out/paper/main.tex§3",
                   "no_source：见 stmt:000007"):
        got = _ok(_b(store).register_statement(**_no_source(
            statement_full=f"探针命题：{reason}", quote_reason=reason)))
        assert got.get("ok") is True, (reason, got)

    # 只写文件名不算"哪一处"（读的人仍然要在整篇里找）。
    loose = _ok(_b(store).register_statement(**_no_source(
        statement_full="探针命题：只写文件名", quote_reason="no_source：见 out/paper/main.tex")))
    assert loose.get("ok") is False and loose.get("kind") == "no_source_without_backing", loose


def test_b4_the_four_states_are_counted_apart() -> None:
    """④ 的读数一侧：`no_source` 与概念行不再被印成"假"或"未查"。"""
    rows = [
        {"stmt_id": "000000", "kind": "lemma", "quote_verified": None,
         "quote_reason": f"no_source：{BACKING}"},
        {"stmt_id": "000001", "kind": "lemma", "quote_verified": None,
         "quote_reason": "no_source：原文不在盘上"},
        {"stmt_id": "000002", "kind": "lemma", "quote_verified": None,
         "quote_reason": ""},
        {"stmt_id": "000003", "kind": "concept", "quote_verified": None,
         "quote_reason": ""},
        {"stmt_id": "000004", "kind": "lemma", "quote_verified": False,
         "quote_reason": "与原文不一致"},
    ]
    got = QE.no_source_reading(rows)
    assert got == {QE.NO_SOURCE_BACKED: 1, QE.NO_SOURCE_UNBACKED: 1,
                   QE.NO_SOURCE_ABSENT: 1, QE.NOT_APPLICABLE: 1}, got


# ------------------------------------------------------------------ ⑤ 反真空
def test_anti_vacuum_criterion_four_goes_red_without_the_no_source_check(
        store: Store, monkeypatch: pytest.MonkeyPatch) -> None:
    """⑤ 反真空：把 B-4 的判定 monkeypatch 成恒通过 ⇒ ④ 那条必红。

    "恒通过"的形态取最阴的一种：判定函数永远说"这一行没有走无来源那一档"（于是它
    从不拒绝，也不会被误判成坏代码）。这时 ④ 的第一段（缺背书必须拒）必然失守 ——
    证明 ④ 的红是那条判据造出来的，不是别的闸顺手挡的。
    """
    monkeypatch.setattr(QE, "declares_no_source", lambda text: False)
    with pytest.raises(AssertionError):
        test_b4_no_source_must_point_at_our_own_manuscript(store)
