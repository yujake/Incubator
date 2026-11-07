# -*- coding: utf-8 -*-
"""判据：改名只看命题号，V 签另算（业主 2026-11-04 口径）。

业主口径（逐字）：

    把"改名"从"有没有 V 签"里拆出来 —— 登记成功（拿到命题号）就改名，签另算。

## 改前是什么样（87 的真机形态）

`reports/f-proof-plan-*.md` 有 6 份、按号命名的 0 份。追下去不是"没人写稿"，而是
「拿到号」这一步本身被 V 签卡住：`B.register_statement` 的机械录入闸要求"每一份要写进
台账的证明正文都有一份覆盖它的 V 签"⇒ F 的手稿没有签时整笔登记被拒 ⇒ F 手上永远没有
`stmt_id` ⇒ `publish_manuscript` 永远没被调用 ⇒ 稿一直叫计划名。计划名又会被下一轮覆盖，
于是依赖面内容寻址认不出被覆盖过的那 3/6 份。

## 这一份钉的四条

| 判据 | 它要证明的事 | 改前红在哪 |
|---|---|---|
| a | 登记拿到号、没有签 ⇒ 稿已改名成 `f-proof-<号>.md`，正文逐字不变 | F 的 proof 档拿不到号（`statement_id` 空），稿仍是计划名 |
| b | 有签 ⇒ 改名 + 签块跟着搬；sha 不符 ⇒ 搬失败并记 `publish_problem` | 搬块失败是静默的（只有 `except: pass`），也没有"搬没搬"的读数 |
| c | 没有号 ⇒ 不许改名（名字里不许凭空造号） | 改前已绿：负控，防止"先改名再补号" |
| d | 读侧不许把「文件名叫 `f-proof-<号>.md`」读成「已签」 | a 的改前红会先挡住；删掉签块后必须回落到待签 |

全部 tmp 工作区，不读写 `projects/`（真机工作区只读）。
"""
from __future__ import annotations

import pytest

import json
import pathlib
import sys

# 与 `tests/conftest.py` 同一个注入方式：这一份也要能在一棵临时源码树上单独跑。
_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agentflow import depsection as DS
from agentflow import verifications as VR
from agentflow import vsigns as VS


# ---------------------------------------------------------------- 命题形态闸的夹具答案
#
# 2026-11-07（业主裁定）：F 交稿之前多了一道"命题形态闸"
# （`agent_f/core.py::_proposition_form_gate` → `Secretary.judge_proposition_form`）。
# 它是一次模型调用，而这一份夹具里没有模型 ⇒ 判据会 fail-closed 拒收（那是对的行为）。
# 下面这个 autouse 夹具只替代那一次调用（给一个"形态合规"的答案），不摘闸：
# 闸照跑、判据仍是那一处实现；写成补丁而不是"让闸放行"，是为了让"夹具里没有模型"
# 这件事只在这一个地方被交代一次。
@pytest.fixture(autouse=True)
def _proposition_form_answers_ok(monkeypatch):
    from agentflow import secretary as _SEC

    monkeypatch.setattr(
        _SEC.Secretary, "judge_proposition_form",
        lambda self, **_kw: {"checked": True, "well_formed": True,
                             "conditions": "夹具：前提", "conclusion": "夹具：结论",
                             "problems": [], "decision": "夹具：形态合规",
                             "refused": "", "reason": "夹具：形态合规"})

from agentflow.agent_f import AgentF
from agentflow.store import Store

MANUSCRIPT_DIR = "reports"
SID = "000001"
PLAN = "000000"
PLAN_REL = f"{MANUSCRIPT_DIR}/f-proof-plan-{PLAN}.md"
BODY = "1. 由定理甲直接得到（依据：stmt:000000）。"
DEP_TABLE = (
    "## 依赖\n\n"
    "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
    "|---|---|---|---|\n"
    "| 由定理甲，G 有 p 阶元 | stmt:000000 | 第 1 步 | 1 |\n"
)


# ------------------------------------------------------------------ 夹具

def _plan_text(body: str = BODY) -> str:
    """登记之前那一份（计划名）手稿：页头 + 命题 + 证明 + 依赖四列表，且已洗过。"""
    text = (
        "# F 的证明手稿：由定理甲推出目标结论（判据夹具）\n\n"
        "- 命题号：stmt:（还没落号）\n"
        f"- 计划：{PLAN} · 子目标：s1\n\n"
        "## 命题\n\n"
        "由定理甲推出目标结论。\n\n"
        "## 证明\n\n"
        f"{body}\n\n"
        + DEP_TABLE
    )
    return DS.mark_washed(text, actor="secretary-F")


def _write(store: Store, rel: str, text: str) -> pathlib.Path:
    path = pathlib.Path(store.root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _read(store: Store, rel: str) -> str:
    return (pathlib.Path(store.root) / rel).read_text(encoding="utf-8")


def _f(store: Store, *, llm=None) -> AgentF:
    return AgentF(store, config={"workspace_root": store.root}, llm=llm)


def _without_proposition_line(text: str) -> str:
    """去掉开头那行"命题号"之后的正文。

    改名那一刻它从"还没落号"换成真号 —— 这是 `publish_manuscript` 明确要写的那一格
    （否则盘上出现"文件叫 f-proof-000001.md、正文说还没落号"的双读数）。除这一行，
    正文一个字都不许变：那是「改名」不是「改稿」。
    """
    return "\n".join(
        line for line in str(text or "").replace("\r\n", "\n").split("\n")
        if not line.strip().startswith("- 命题号"))


def _sign(text: str, *, proof_sha: str, manuscript_id: str,
          statement_id: str = "") -> str:
    return VS.stamp_manuscript_sign(
        text, proof_sha=proof_sha, streak=3, need=3, verdict="成立",
        at="2026-11-03T15:00:00+08:00",
        ledger=f"verifications/{SID}.jsonl", statement_id=statement_id,
        manuscript_id=manuscript_id)


class _Seam:
    """假模型缝（`judge.judge_json` 认 `complete(prompt) -> str` 这一种形状）。"""

    def __init__(self, product: dict) -> None:
        self.product = product
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(self.product, ensure_ascii=False)


def _proof_product() -> dict:
    """一条自足证明（不引在册命题）⇒ 不会撞上依赖面引用档位那道门。"""
    return {"product": "proof", "strategy": "套用已知定理",
            "why_strategy": "结论由已知定理逐条读出，不需要新构造",
            "steps": [
                {"n": 1, "text": "设目标结论的反面成立（前提）。", "cites": [],
                 "assumption": True},
                {"n": 2, "text": "由定义逐条推出矛盾（前提）。", "cites": [],
                 "assumption": True},
            ]}


def _run_proof_round(store: Store) -> dict:
    """跑一轮 F 的 proof 档（没有 V 签）。返回 `F.step` 的读数。"""
    seam = _Seam(_proof_product())
    f = _f(store, llm=seam)
    plan = f.create_plan(
        "引理：由定义推出目标结论", "PK-RENAME-SIGN", subgoals=[
            {"sid": "s1", "text": "由定义推出目标结论", "owner": "F",
             "testable": "手稿按命题号命名、签另算"}])
    assert plan.get("created") is True, plan
    return f.step(str(plan["plan_id"]))


def _number_of(out: dict) -> str:
    """这一轮拿到的命题号（没有 ⇒ 空串；不许从文件名里猜）。"""
    return str(out.get("statement_id") or "")


# ------------------------------------------------------------------ a 改名

def test_a_a_registered_number_renames_the_manuscript_without_any_sign(store: Store) -> None:
    """a：登记拿到号、没有签 ⇒ 稿改名成 `f-proof-<号>.md`，正文逐字不变。

    改前红：`publish_manuscript` 返回里没有 `sign_moved` / `publish_problem` 这两格，
    而端到端那一半更直接 —— 没有签时 F 连号都拿不到，稿一直是计划名。
    """
    text = _plan_text()
    _write(store, PLAN_REL, text)
    out = _f(store).publish_manuscript(
        {"ok": True, "path": PLAN_REL, "text": text, "rows": [], "named_by": "plan"},
        statement_id=SID)

    assert out.get("published") is True, out
    assert out.get("path") == f"{MANUSCRIPT_DIR}/f-proof-{SID}.md", out
    # 没有块 ⇒ 不改签、也不报问题（"签另算"不是"搬签失败"）。
    assert out.get("sign_moved") is False, out
    assert out.get("publish_problem") == {}, out
    assert not (pathlib.Path(store.root) / PLAN_REL).exists(), "计划名那份还在盘上"

    final = _read(store, out["path"])
    assert _without_proposition_line(final) == _without_proposition_line(text)
    assert f"- 命题号：stmt:{SID}" in final


def test_a2_f_registration_lands_a_manuscript_entry_and_the_number_comes_from_b(
        store: Store) -> None:
    """a2：F 的 proof 档先落手稿登记条目；命题号由 B 在 V 签之后认领时才发。

    2026-11-07（解耦 + 裁边）口径：`F→B` 那条边被裁去 ⇒ F 不再"登记拿到号"，
    它落的是 `reports/f-proof-plan-<计划号>.md` 这一条手稿登记条目；V 在命题还没在册时
    先签（pending），B 按正文 sha 认领 → 发号 → 把同一份稿转正成
    `reports/f-proof-<号>.md`。改前那两条（"没有签也拿得到号" / "拿到号就改名"）
    要防的事一样没少：没编号之前不凭空造号、编号之后盘上只有一份稿。
    """
    out = _run_proof_round(store)
    assert out.get("action") == "proof", out

    # ① F 这一侧：登记条目按计划名落，没有号（不凭空造号）
    assert out.get("proof_mode") == "registered", out
    assert out.get("manuscript_path") == PLAN_REL, out
    assert (pathlib.Path(store.root) / PLAN_REL).is_file(), out
    numbered = sorted(p.name for p in (pathlib.Path(store.root) / MANUSCRIPT_DIR).glob(
        "f-proof-*.md") if not p.name.startswith("f-proof-plan-"))
    assert numbered == [], numbered
    # 没有号 ⇒ 这一份还没签，交不了差
    assert out.get("delivery_state") == "waiting", out
    assert out.get("delivered") is False, out

    # ② 交稿链路：V 先签（pending）→ B 按 sha 认领 → 发号 + 转正
    sid, rel = _claim_number(store)
    assert sid, (sid, rel)
    assert rel == f"{MANUSCRIPT_DIR}/f-proof-{sid}.md", rel
    assert (pathlib.Path(store.root) / rel).is_file(), rel
    assert not (pathlib.Path(store.root) / PLAN_REL).exists(), (
        "按号命名之后计划名那份还在 ⇒ 盘上会有两份同一份稿")


def _claim_number(store: Store) -> tuple[str, str]:
    """把 F 那一轮的手稿走完交稿链路：V 先签（pending）→ B 按 sha 认领。

    返回 `(命题号, 转正后的手稿路径)`；号由 B 在认领那一刻发（F 侧不造号）。
    """
    from agentflow.agent_b import AgentB
    from conftest import sign_before_registration

    text = _read(store, PLAN_REL)
    body = VS.manuscript_proof_body(text).strip("\n")
    sign_before_registration(store.root, proof_text=body)
    b = AgentB(store, extractor=None, extract_text=None)
    got = b.register_statement(
        statement_full="由定理甲推出目标结论。",
        statement_text="由定理甲推出目标结论。",
        origin="own_result", kind="conjecture",
        label="F 攻坚 000000 子目标 s1", proof_text=body,
        proof_manuscript=PLAN_REL, evidence_kind="heuristic",
        line_range={"label": PLAN_REL},
        quote_reason="夹具：F 的手稿登记条目在 V 签之后由 B 认领")
    assert got.get("ok") is True, got
    sid = str(got.get("stmt_id") or "")
    return sid, f"{MANUSCRIPT_DIR}/f-proof-{sid}.md" if sid else ""


# ------------------------------------------------------------------ b 搬签

def test_b_a_matching_sign_block_moves_with_the_rename(store: Store) -> None:
    """b：有签 ⇒ 改名 + 签块跟着搬（sha 相符才搬）。

    改前红：改名那一笔把块搬过去时没给新稿号（`手稿号` 格是空的）⇒ 读侧是
    `identity_state=unmatched`；而且返回值里没有 `sign_moved` 可读。
    """
    text = _plan_text()
    sha = VR.proof_sha(VS.manuscript_proof_body(text))
    signed = _sign(text, proof_sha=sha, manuscript_id=f"plan-{PLAN}")
    _write(store, PLAN_REL, signed)

    out = _f(store).publish_manuscript(
        {"ok": True, "path": PLAN_REL, "text": signed, "rows": [], "named_by": "plan"},
        statement_id=SID)
    assert out.get("published") is True, out
    assert out.get("sign_moved") is True, out
    assert out.get("publish_problem") == {}, out

    final = _read(store, out["path"])
    block = VS.manuscript_sign_reading(final, manuscript_path=out["path"])
    assert block.get("found") is True, block
    assert block.get("signed") is True, block
    assert block.get("proof_sha256") == sha, block
    # 块要属于改名后的那一份（第 9 格跟着搬），否则读侧只能读成 unmatched。
    assert block.get("manuscript_id") == SID, block
    assert block.get("identity_state") == "resolved", block


def test_b2_a_stale_sign_block_is_not_moved_and_the_problem_is_read(store: Store) -> None:
    """b2：块盖的是另一版正文 ⇒ 不搬，并把「为什么没搬」记成 `publish_problem`。

    改前红：`except Exception: titled = titled` 那一句把搬块的所有失败吞掉，返回值里
    没有一格说"块没搬" —— 静默半改名。
    """
    text = _plan_text()
    stale = _sign(text, proof_sha="0" * 64, manuscript_id=f"plan-{PLAN}")
    assert f"- V 签：" in stale
    _write(store, PLAN_REL, stale)

    out = _f(store).publish_manuscript(
        {"ok": True, "path": PLAN_REL, "text": stale, "rows": [], "named_by": "plan"},
        statement_id=SID)
    assert out.get("published") is True, out
    assert out.get("sign_moved") is False, out
    assert dict(out.get("publish_problem") or {}).get("kind") == "sign_sha_mismatch", out

    final = _read(store, out["path"])
    assert VS.SIGN_MARK not in final, "sha 不符的块被搬进了按号命名的那一份"


# ------------------------------------------------------------------ c 负控

def test_c_without_a_number_the_manuscript_keeps_its_plan_name(store: Store) -> None:
    """c（负控）：还没有号 ⇒ 一个字都不许改名，名字里也不许凭空造号。"""
    text = _plan_text()
    _write(store, PLAN_REL, text)

    out = _f(store).publish_manuscript(
        {"ok": True, "path": PLAN_REL, "text": text, "rows": [], "named_by": "plan"},
        statement_id="")
    assert out.get("published") is False, out
    assert (pathlib.Path(store.root) / PLAN_REL).is_file(), "没有号却把计划名那份弄丢了"
    numbered = sorted(p.name for p in (pathlib.Path(store.root) / MANUSCRIPT_DIR).glob(
        "f-proof-*.md") if not p.name.startswith("f-proof-plan-"))
    assert numbered == [], numbered


# ------------------------------------------------------------------ d 反向

def test_d_a_numbered_filename_is_not_a_sign(store: Store) -> None:
    """d：名字叫 `f-proof-<号>.md` 不等于已签；删掉签块必须回落到「待签」。

    2026-11-07（解耦 + 裁边）：改成"登记条目先落计划名、B 认领时才按号命名"之后，
    这条判据的另一半（F 没有签时拿不到号）已由 `a2` 覆盖；这里只钉读侧那一条不变式：
    读侧认的是签块 / 台账，不是文件名。夹具直接在册一行命题 + 落一份按号命名、
    但没有签的稿（`publish_manuscript` 的既有入口），读数必须是「待签」。
    """
    from conftest import seed_statement_row

    seed_statement_row(store, statement_full="由定理甲推出目标结论。",
                       statement_text="由定理甲推出目标结论。",
                       kind="conjecture", stmt_id=SID, proof_text=BODY)
    text = _plan_text()
    _write(store, PLAN_REL, text)
    pub = _f(store).publish_manuscript(
        {"ok": True, "path": PLAN_REL, "text": text, "rows": [], "named_by": "plan"},
        statement_id=SID)
    assert pub.get("published") is True, pub
    rel = str(pub["path"])
    assert rel == f"{MANUSCRIPT_DIR}/f-proof-{SID}.md", rel

    final = _read(store, rel)
    body = VS.manuscript_proof_body(final)
    sha = VR.proof_sha(body)
    f = _f(store)

    waiting = f._read_sign(statement_id=SID, proof_text=body)["reading"]
    assert waiting.get("state") == "waiting", waiting
    assert waiting.get("delivered") is False, waiting

    # 盖一块真的签（sha 相符）⇒ 已签。这一步证明读侧认的是块，不是名字。
    _write(store, rel, _sign(final, proof_sha=sha, manuscript_id=SID,
                             statement_id=SID))
    signed = f._read_sign(statement_id=SID, proof_text=body)["reading"]
    assert signed.get("state") == "signed", signed

    # 把签块删掉：名字仍然是 `f-proof-<号>.md`，读数必须回到「待签」。
    stripped = "\n".join(
        line for line in _read(store, rel).replace("\r\n", "\n").split("\n")
        if not line.strip().startswith(VS.SIGN_MARK))
    _write(store, rel, stripped)
    back = f._read_sign(statement_id=SID, proof_text=body)["reading"]
    assert back.get("state") == "waiting", back
    assert back.get("delivered") is False, back


# ------------------------------------------------------------------ e 不毁签

def test_e_an_unsigned_draft_does_not_overwrite_a_signed_version(store: Store) -> None:
    """e：按号命名的那份已经签住旧版时，一份没有签的新稿不许整文件覆盖它。

    改前红：`publish_manuscript` 直接整文件写目标名，旧签块随旧正文一起消失
    （签另算不是毁签）。这一条是 a/b 的必要边界：改名只看号，但"号已经有了"
    不等于"可以拿没签的草稿把签过的那一版盖掉"。
    """
    old_body = "1. 签住的旧版证明（依据：stmt:000000）。"
    old_text = _plan_text(old_body)
    old_sha = VR.proof_sha(VS.manuscript_proof_body(old_text))
    signed_old = _sign(old_text, proof_sha=old_sha, manuscript_id=SID,
                       statement_id=SID)
    _write(store, f"{MANUSCRIPT_DIR}/f-proof-{SID}.md", signed_old)

    new_body = "1. 这一轮的新草稿，还没有签（依据：stmt:000000）。"
    new_text = _plan_text(new_body)
    _write(store, PLAN_REL, new_text)

    out = _f(store).publish_manuscript(
        {"ok": True, "path": PLAN_REL, "text": new_text, "rows": [], "named_by": "plan"},
        statement_id=SID)
    assert out.get("published") is False, out
    assert dict(out.get("publish_problem") or {}).get(
        "kind") == "target_holds_a_signed_version", out
    assert _read(store, f"{MANUSCRIPT_DIR}/f-proof-{SID}.md") == signed_old, (
        "已签的那一版被一份没签的草稿覆盖了")
    assert (pathlib.Path(store.root) / PLAN_REL).is_file(), "草稿也不许因此丢"
