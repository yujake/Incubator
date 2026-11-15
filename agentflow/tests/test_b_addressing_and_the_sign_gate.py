# -*- coding: utf-8 -*-
"""B 的二次寻址与签块入库：清单优先、零模型调用、三档拒信（业主 2026-11-02）。

## 口径（逐字）

```text
B侧接收直接接收的是D侧呈递的研究手稿，D侧研究手稿收录包含各命题及其证明的多份F侧手稿地址，
B侧需寻址获得F侧证明及V签。
二次寻址做成自动工具，不要消耗LLM的token。
```

于是这一笔钉三件事：

1. B 的第一来源是 D 的研究手稿里那张携带单（`## 携带的证明手稿`）：清单点了名就按那个
   地址去读 F 的稿与签块；清单地址读不到 ⇒ 受控拒绝，不许换一条自己找的路（兜底读盘
   只是清单缺失时的降级）；
2. 这一整段是确定性纯函数（`depsection.read_carried_manuscript`），零模型调用；
3. 认签入库仍要过两道判据：手稿号 → 在册命题的映射 + 正文逐字 sha（`vsigns.manuscript_sign_gate`）。

## 判据

| # | 造什么 | 期望 |
|---|---|---|
| a | B 从 D 的清单收录一条（清单里有 F 稿地址 + 稿上有 9 格签块） | 收下、签读数真、寻址那一段前后差值为 0 |
| b | 同一笔的寻址读数 | `mode=auto`、`source=carried_by_D`、`address` / `list_item` / `list_report` 指得到 |
| c | 清单点了名、而那个地址读不到（盘上另有一份同名约定路径的稿） | 受控拒绝 `manuscript_address_unreadable`、没有降级去读那份稿、寻址零模型调用 |
| d | 反真空：把寻址函数打桩成"清单里没有这一条" | a 的 `v_sign.applied` 必须翻假（证明 a 量的是真寻址） |
| e | 三档签块拒信 | 每档 `code` 对、`reason` 一句、`suggestion` 点名真工具 / 真字段 |
"""
from __future__ import annotations

import hashlib
import pathlib

from agentflow import depsection as _DS
from agentflow import verifications as VR
from agentflow import vsigns as VS
from agentflow.agent_b import AgentB
from agentflow.secretary import Secretary
from agentflow.store import Store

FULL = "设 f 在 [0,1] 上连续；则 f 在该区间上一致连续。"
PROOF = ("1. 取 δ=ε：对任意 x,y∈[0,1]，|x-y|<δ ⇒ |f(x)-f(y)|<ε。\n"
         "2. 第 1 步的 δ 只依赖 ε、不依赖点 ⇒ 按定义即一致连续。")
SID = "000009"
REL = "reports/f-proof-000009.md"
REPORT = "reports/000009-research.md"
RAW = ("# F 的证明手稿：一致连续\n\n"
       "- 计划：0009 · 子目标：s1\n"
       "- 依赖面洗稿：已洗=true；执行者=secretary-F\n\n"
       "## 命题\n\n"
       f"{FULL}\n\n"
       "## 证明\n\n"
       f"{PROOF}\n\n"
       "## 依赖\n\n"
       "| 引用（F 的原话） | 命题号（stmt:NNNNNN） | 用在哪一步 | 路径号（第几条证明） |\n"
       "|---|---|---|---|\n"
       "（这一份证明没有引用任何在册命题 —— 空表就是声明。）\n")


def _body_sha() -> str:
    return VS._sign_sha(VS.manuscript_proof_body(RAW))


def _manuscript(*, manuscript_id: str = SID, sign: bool = True,
                block_sha: str = "") -> str:
    if not sign:
        return RAW
    # 2026-11-05 晚（业主）：签块必须有独立台账背书 —— 稿头自述（`reports/… #V签`）
    # 是假签。这块签盖的是在册命题 SID 的那一份正文，所以背书是
    # `verifications/000009.jsonl#v-000003`；`_ws` 里落那三行（真台账）。
    return VS.stamp_manuscript_sign(
        RAW, proof_sha=block_sha or _body_sha(), streak=3, need=3, verdict="成立",
        signer="V", at="2026-11-02T16:43:01+08:00",
        ledger=f"verifications/{SID}.jsonl#v-000003",
        statement_id=SID, manuscript_id=manuscript_id)


def _ws(tmp_path: pathlib.Path, *, manuscript: str, carried_path: str | None = None,
        disk_copy: bool = False) -> Store:
    st = Store(tmp_path / "ws")
    st.init()
    root = pathlib.Path(st.root)
    # 签的背书：三行真台账 + 一份可复算的签（D268 批 2：块不是签）。
    rows = []
    for _ in range(int(VR.SIGN_STREAK_NEED)):
        rows.append(VR.record_verification(
            str(root), statement_id=SID, proof_text=PROOF,
            verdict={"verdict": "成立", "findings": []},
            verifier="agent-V", flip=False,
            secretary_judge={"checked": True, "axis": "clean", "decision": "没问题",
                             "reason": "夹具：秘书判 clean"}))
    sha = VS._sign_sha(PROOF)
    passes = [{"verification_id": str(r["verification_id"]),
               "at": str(r.get("at") or ""), "proof_sha256": sha}
              for r in rows]
    got = VS.issue(str(root), artifact_sha=sha, streak=3, need=3,
                   ledger=f"verifications/{SID}.jsonl#{rows[-1]['verification_id']}",
                   statement_id=SID, proof_no=1, passes=passes, by="secretary:B")
    assert got.get("written") is True or got.get("idempotent") is True, got
    (root / "reports").mkdir(parents=True, exist_ok=True)
    if manuscript:
        (root / REL).write_text(manuscript, encoding="utf-8")
    if disk_copy:
        # 兜底读盘那一档会撞见的"约定路径"：清单地址读不到时不许退到这里来。
        other = f"reports/f-proof-{SID}.md"
        if other != REL:
            (root / other).write_text(_manuscript(), encoding="utf-8")
    target = carried_path if carried_path is not None else REL
    path = root / target
    sha = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
    rows = [{"statement_id": SID, "path": target, "sha256": sha}]
    (root / REPORT).write_text(
        "# D 的研究手稿\n\n" + _DS.render_carried_section(rows), encoding="utf-8")
    return st


class _CountingSeam:
    """计数缝：任何一次模型调用都被记下来（这一笔的判据是"一次都没有"）。"""

    wired = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def ask_json(self, prompt: str, *, system: str = "", task_id: str = "",
                 note: str = "") -> tuple[dict, object]:
        self.calls.append(str(task_id or note or "?"))

        class _Call:
            ok = True
            problem = ""
            detail = ""
            text = ""
            model = "fake"
            prompt_version = "t"
            prompt_sha256 = "0" * 64

        if str(note).endswith("proposition_identity"):
            # 2026-11-08：判定只有两档；这一条夹具测的是寻址（不该有候选），
            # 所以给一个合法的 different（旧夹具给的是「签发」—— 那是词表外的结论，
            # 现在按"没判成"受控拒，会把这一条判据挡在寻址之前）。
            return ({"decision": "different", "same_as": "", "canonical_name": "",
                     "route": "", "condition": "", "conclusion": "",
                     "reason": "夹具：没有候选 ⇒ 不同", "basis": []}, _Call())
        return {"decision": "签发", "reason": "夹具", "basis": ["夹具"]}, _Call()


def _register(st: Store, seam: _CountingSeam | None = None) -> dict:
    """B 收录：不给 `proof_manuscript`（让 B 自己按 D 的清单寻址）。"""
    sec = None
    if seam is not None:
        sec = Secretary("B", root=st.root, store=st, seam=seam, enable_model=True)
    b = AgentB(st, extractor=None, extract_text=None, secretary=sec, auto_secretary=sec is None)
    return b.register_statement(
        statement_full=FULL, statement_text=FULL, proof_text=PROOF,
        kind="theorem", label="探针命题", origin="own_result",
        evidence_kind="heuristic", quote_verified=None,
        quote_reason="夹具：自产证明，没有第二份文本可比对",
        line_range={"label": REL})


# ====================================================================== a + b
def test_a_addressing_reads_ds_list_with_zero_model_calls(tmp_path: pathlib.Path,
                                                          monkeypatch) -> None:
    """a+b B 按 D 的清单寻址收录：签认上了，且寻址那一段一次模型都没调。

    量的是"寻址这一步"的模型调用次数（前后差值），不是整笔收录：B 的秘书在写盘前还有
    一次命题同一性判定（`secretary:proposition_identity`，既有行为、不在寻址路径上）。
    报告里两个数都给：寻址 0 / 整笔 1。
    """
    st = _ws(tmp_path, manuscript=_manuscript())
    seam = _CountingSeam()
    deltas: list[int] = []
    real = _DS.read_carried_manuscript

    def _spy(root: object, **kw) -> dict:
        before = len(seam.calls)
        got = real(root, **kw)
        deltas.append(len(seam.calls) - before)
        return got

    monkeypatch.setattr(_DS, "read_carried_manuscript", _spy)
    got = _register(st, seam)

    assert got.get("ok") is True, got
    # D268 批 2：这一条路径把签的读数放在 `sign_filing` 里（可复算凭据），
    # 不再依赖 `v_sign.applied` 这个"块认签"的旧格。
    filing = dict(got.get("sign_filing") or {})
    assert filing.get("manuscript_signed") is True, filing
    assert filing.get("state") in ("signed", "signed_pending_filing"), filing
    addr = dict(got.get("addressing") or {})
    assert addr.get("mode") == "auto", addr
    assert addr.get("source") == _DS.SOURCE_CARRIED, addr
    assert addr.get("hit") is True, addr
    assert addr.get("address") == REL, addr
    assert addr.get("list_report") == REPORT, addr
    assert addr.get("list_item") == 1, addr
    assert deltas, "寻址函数一次都没被调到 ⇒ 这一条判据没量到寻址"
    assert all(d == 0 for d in deltas), f"二次寻址惊动了模型（逐次差值 {deltas}）"
    # 整笔收录里唯一那一次模型调用不属于寻址（既有行为，记在报告里）。
    assert all("address" not in c and "carried" not in c and "manuscript" not in c
               for c in seam.calls), seam.calls


# ====================================================================== c
def test_c_an_unreadable_address_is_a_refusal_not_a_disk_fallback(
        tmp_path: pathlib.Path) -> None:
    """c 清单点了名、地址读不到 ⇒ 受控拒绝；盘上另有一份同名稿也不许去读它。"""
    st = _ws(tmp_path, manuscript="", carried_path="reports/f-proof-gone.md",
             disk_copy=True)
    seam = _CountingSeam()
    got = _register(st, seam)

    assert got.get("ok") is not True, got
    assert got.get("kind") == _DS.REFUSED_ADDRESS, got
    text = f"{got.get('error') or ''}{got.get('reason') or ''}"
    assert "寻址" in text and "建议" in text, got
    addr = dict(got.get("addressing") or {})
    assert addr.get("refusal") == _DS.REFUSED_ADDRESS, addr
    assert addr.get("mode") == "auto", addr
    assert addr.get("hit") is False, addr
    assert addr.get("address") == "reports/f-proof-gone.md", addr
    # NT2（2026-11-15，业主裁定「判非平凡度是 B 处理一条录入的第一个动作」）之后，
    # 收录的第一步是判档（`secretary:statement_aesthetic`），它走同一条模型缝；
    # 这一笔的拒信（清单地址读不到）要到寻址那一步才查得出来 ⇒ 那一条已经发生了。
    # 于是这里把"允许的那一条"钉成精确字符串：多出任何一条（尤其带 address /
    # carried / manuscript 的）照样红 —— 寻址那一段本身仍然零模型调用（`test_a`
    # 用前后差值逐次量它，这一条不放宽那一条）。
    assert seam.calls == ["secretary:statement_aesthetic"], (
        f"受控拒绝那一路的模型调用不止 NT2 判档那一条：{seam.calls}")
    # 兜底读盘没有发生：真去读那份约定路径的稿，签块就会认上。
    assert "v_sign" not in got or not (got.get("v_sign") or {}).get("applied"), got
    rows = list(st.rows("statements"))
    assert rows == [], rows


# ====================================================================== d
def test_d_stubbing_the_addressing_function_turns_a_red(tmp_path: pathlib.Path,
                                                        monkeypatch) -> None:
    """d 反真空：把寻址打桩成"清单里没有这一条"⇒ 签认不上（a 量的是真寻址）。"""
    st = _ws(tmp_path, manuscript=_manuscript())
    seam = _CountingSeam()

    def _empty(root: object, *, statement_ids=(), proof_text="") -> dict:
        return {"checked": True, "source": _DS.SOURCE_NONE, "text": "", "path": "",
                "sha256": "", "carried_by": "", "tried": [], "why": "夹具：打桩成空",
                "named": False, "address": "", "item": 0, "list_report": "",
                "list_line": 0, "list_sha256": ""}

    monkeypatch.setattr(_DS, "read_carried_manuscript", _empty)
    got = _register(st, seam)
    v_sign = dict(got.get("v_sign") or {})
    assert v_sign.get("applied") is not True, (
        f"寻址被打桩成空而签照样认上了 ⇒ a 那条判据没有量到寻址：{v_sign}")
    assert v_sign.get("found") is not True, v_sign
    # 那一档的真实去路是"自产定理级没有 V 签"⇒ 受控拒绝（不是崩、也不是静默收下）。
    assert got.get("ok") is not True, got
    # 同上（c 那一条的注释）：拒绝发生在判档之后 ⇒ 允许且只允许 NT2 判档那一条调用；
    # 寻址被打桩成空，寻址本身一次模型都不许有。
    assert seam.calls == ["secretary:statement_aesthetic"], seam.calls


# ====================================================================== e 三档拒信
def _gate(read: dict, **kw) -> dict:
    return VS.manuscript_sign_gate(read, **kw)


def test_e1_a_legacy_block_is_manuscript_id_missing() -> None:
    """e1 旧 8 格块 ⇒ `manuscript_id_missing`；建议点名 `vsigns.land` 与第 9 格 `手稿号`。"""
    legacy = (_manuscript().replace("；手稿号=000009", ""))
    read = VS.manuscript_sign_standing(legacy, proof_sha=_body_sha(),
                                       manuscript_path=REL)
    gate = _gate(read, statement_id="")
    assert gate["code"] == "manuscript_id_missing", gate
    assert gate["reason"], gate
    assert "vsigns.land" in gate["suggestion"] and "手稿号" in gate["suggestion"], gate


def test_e2_an_unknown_id_is_manuscript_id_unresolved_for_a_registered_statement() -> None:
    """e2 第 9 格的号不在册 ⇒ 在册命题那一档 `manuscript_id_unresolved`；建议点名 `register_statement`。

    2026-11-05（D1，阻断级）：「新建命题」（`statement_id=""`）那一档不再判"号必须在册"
    —— 号是登记之后才可能有的。同一个块在那一档放行（判据改由正文 sha +
    `sign_ledger_backing` 的独立台账背书继续判），读数留 `new_statement_number_unregistered`。
    """
    text = _manuscript(manuscript_id="000777")
    read = VS.manuscript_sign_standing(text, proof_sha=_body_sha(),
                                       manuscript_path="reports/f-proof-000777.md")
    assert read["identity_state"] == "resolved", read
    # 在册命题那一档（非空号）：号不在册仍是硬拒。
    gate = _gate(read, statement_id=SID, registered=(SID,))
    assert gate["code"] == "manuscript_id_unresolved", gate
    assert "register_statement" in gate["suggestion"], gate
    # 新建命题那一档（空号）：不在册是常态，不拒（读数在 `new_statement_number_*`）。
    new = _gate(read, statement_id="", registered=(SID,))
    assert new["code"] == "" and new["admitted"] is True, new
    assert new.get("new_statement_number_unregistered") is True, new


def test_e3_another_statement_or_another_body_is_not_of_this_statement() -> None:
    """e3 号是别条命题的 / 正文不是同一份 ⇒ `manuscript_not_of_this_statement`。"""
    text = _manuscript()
    read = VS.manuscript_sign_standing(text, proof_sha=_body_sha(), manuscript_path=REL)
    gate = _gate(read, statement_id="000010", registered=(SID,))
    assert gate["code"] == "manuscript_not_of_this_statement", gate
    assert "proof_manuscript" in gate["suggestion"], gate

    # 正文逐字那一半：签块盖的是另一版正文（改一个字）。
    stale = _manuscript(block_sha=VR.text_sha(VS.manuscript_proof_body(RAW) + "改一个字"))
    stale_read = VS.manuscript_sign_standing(stale, proof_sha=_body_sha(),
                                             manuscript_path=REL)
    assert stale_read["body_mismatch"] is True, stale_read
    gate2 = _gate(stale_read, statement_id="", registered=())
    assert gate2["code"] == "manuscript_not_of_this_statement", gate2
    assert gate2["reason"] and gate2["suggestion"], gate2

    # 反真空：同一块在两条判据都过时才 admitted。
    ok = _gate(read, statement_id="", registered=(SID,))
    assert ok["code"] == "" and ok["admitted"] is True, ok
