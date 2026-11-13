# -*- coding: utf-8 -*-
"""未入册命题的 `## 命题` 原位重写（W2·甲，2026-11-13；受控写口）。

## 为什么需要它

真机 `projects/octahedron-20261113`：`reports/f-proof-000002.md` 的 V 签已经通过，而
`## 命题` 那一节写成了修订说明（「按 V u-000005 的唯一缺陷修订第 7 步……」）。B 收编时
拒收（`proposition_form_refused`，见 `agent_b/register_statement.py` 的
`_manuscript_form_refusal`），拒收的改法写着「同一稿号原位重写 `## 命题`」。可是今天
没有任何写口做得到：

- `proofregistry.register_or_rewrite` 的重写档只换 `## 证明` 与 `## 依赖`，改命题指纹
  会撞 `proposition_text_changed`（那条纪律是"不许用挂证明改命题正文"）；
- `fs.write` / `fs.edit` 按名拒写 `f-proof-*`（`RESERVED_ARTIFACT_TABLE`）；
- 已拿签的稿被 `manuscriptfreeze` 冻成只读。

而这一档确实存在"该改"的情形：「命题还没进 `statements`」（B 从没收过它），签盖的是
`## 证明` 的 sha —— 改 `## 命题` 不动那个 sha。所以这是一个「兜底写口」（不是主路径：
主路径是 F 落稿那一刻的形态闸，W1 已接在 `proofregistry:666`）。

## 三条边界（缺一不许）

1. 只在"这份稿还没被收进 `statements`"时允许」。已登记的命题走重新登记，不走改写
   （改一条已入册命题的陈述，等于换了一条命题：`proposition_text_changed` 那条纪律）。
2. 「改后必须过语义同一性判定」：改前 / 改后是「同一条」命题（复用
   `proposition_identity` 那一根轴，`Secretary.judge_same_proposition`，两态）。
   "判不了"⇒ 拒（fail-closed）。这一格刻意没有文字相似度 / 长度比这类机械兜底：
   真机那段修订说明与定理陈述共享大量字符，任何机械尺子都会把它判成"同一段"。
3. 「受控写口，不在冻结面上开洞」：冻结的是「已签的正文」（`## 证明`）。本写口只换
   `## 命题` 那一节与稿头的命题指纹，`## 证明` 一个字节不动；因此它把三句声明写进读数
   （`DECLARATIONS`）：改的是命题节 / 正文 sha 未变 / 不需要重签。

## 不做什么

- 不重签、不碰 `vsigns` / `verifications`：签的有效性由"正文 sha 未变"直接兑现；
- 不写 `statements`：这一笔只让稿可被 B 收编，登记仍是 B 的事；
- 不新增动作、不改冻结面、不碰 `RESERVED_ARTIFACT_TABLE`。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import manuscriptfamily as _MFAM
from . import manuscriptform as _MF
from . import proofregistry as _PR

#: 受控码（闭集；测试与拒收文案照这几个名字读）。
REFUSED_MISSING = "manuscript_missing"
REFUSED_UNREADABLE = "manuscript_unreadable"
REFUSED_NOT_A_MANUSCRIPT = "manuscript_not_a_sign_carrier"
REFUSED_NO_PROPOSITION = "manuscript_proposition_missing"
REFUSED_REGISTERED = "proposition_already_registered"
REFUSED_DIFFERENT = "proposition_identity_refused"
REFUSED_UNJUDGED = "proposition_identity_unjudged"
REFUSED_WRITE = "manuscript_write_failed"
REFUSED_BODY_MOVED = "proof_body_would_move"

#: 这一笔改了什么、没改什么 —— 三句一起进读数（读的人不必猜"签还算不算"）。
DECLARATIONS: tuple[str, ...] = (
    "只改 `## 命题` 那一节（与稿头的命题指纹）",
    "`## 证明` 的正文 sha 逐字未变（签盖的是它）",
    "不需要重签：签仍然有效",
)

#: 成功之后给产出方的下一步（不经过 D：命题台账的判据不在他手上）。
NEXT_STEP = ("同一稿号、同一份稿重交 B 的收藏（`own.ingest_manuscript(mode=\"register\", "
             "manuscript=<同一路径>)`）；正文 sha 没变 ⇒ V 的签按同一 sha 认领，不用重签")


def _norm_proposition(text: Any) -> str:
    """命题正文的规范化值（与 `proposition_fingerprint` 同一把尺，只归一空白）。"""
    return " ".join(str(text or "").replace("\u3000", " ").split())


def _registered_row(rows: list[dict[str, Any]], *, rel: str, manuscript_id: str,
                    proposition: str) -> dict[str, Any]:
    """这份稿的命题是不是已经进了 `statements`（命中 ⇒ 那一行；空 = 未入册）。

    三个判据任一成立就算"已入册"（宁可拒、不可改错对象）：

    - 行上 `manuscript_id` 等于这份稿的稿号（B 收录时写的那一格）；
    - 行的逐路径记录（`manuscripts`：`{"1": rel, …}`）里有这份稿；
    - 行上的命题正文与这份稿的 `## 命题` 逐字（规范化后）相同 —— 哪怕稿号对不上，
      这段陈述也已经入册了，改它就是改一条已登记的命题。
    """
    want = _norm_proposition(proposition)
    for row in rows:
        if manuscript_id and str(row.get("manuscript_id") or "") == manuscript_id:
            return dict(row)
        paths = [str(v) for v in (row.get("manuscripts") or {}).values()]
        if rel and rel in paths:
            return dict(row)
        if want and _norm_proposition(row.get("statement_full")) == want:
            return dict(row)
    return {}


def rewrite_proposition(*, store: Any, root: Any, manuscript: Any,
                        proposition: Any, secretary: Any,
                        label: str = "", kind: str = "conjecture",
                        task_id: str = "") -> dict[str, Any]:
    """把一份「未入册」手稿的 `## 命题` 原位换成新陈述（受控写口；三条边界见模块 docstring）。

    参数：`manuscript` 是工作区相对路径（`reports/f-proof-*.md` 等签载体）；`proposition`
    是新的那一节正文；`secretary` 是给出同一性判定的那名秘书（调用方注入：F 用自己
    的秘书，测试用替身）。`store` / `root` 都必填 —— 边界 ① 要读 `statements`。

    返回键固定（成功与受控拒同形，读的人不必猜）：
    `checked / ok / attempted / refused / why / manuscript / manuscript_id / family /
    proposition_before / proposition_after / proposition_sha256_before /
    proposition_sha256_after / proof_sha256_before / proof_sha256_after / body_unchanged /
    statements_row / identity / sign / declarations / wrote / next_step`。
    """
    rel = str(manuscript or "").strip().replace("\\", "/")
    out: dict[str, Any] = {
        "checked": False, "ok": False, "attempted": False, "refused": "", "why": "",
        "manuscript": rel, "manuscript_id": "", "family": "",
        "proposition_before": "", "proposition_after": "",
        "proposition_sha256_before": "", "proposition_sha256_after": "",
        "proof_sha256_before": "", "proof_sha256_after": "", "body_unchanged": False,
        "statements_row": {}, "identity": {}, "sign": {},
        "declarations": list(DECLARATIONS), "wrote": False, "next_step": "",
    }
    new_prop = str(proposition or "").strip()
    if not rel:
        out.update(refused=REFUSED_MISSING, why="没有给手稿路径 ⇒ 不知道改哪一份")
        return out
    shape = _MFAM.classify_manuscript(rel)
    family = str(shape.get("family") or "")
    out["family"] = family
    out["manuscript_id"] = str(shape.get("manuscript_id") or "")
    carrier = _MFAM.sign_carrier(rel)
    if not carrier.get("ok"):
        out.update(refused=REFUSED_NOT_A_MANUSCRIPT, why=(
            f"`{rel}` 不是签的载体（{carrier.get('code') or '认不出族'}）⇒ 这一族没有"
            "「改命题节、签不动」这回事，原位重写不适用于它"))
        return out
    path = Path(str(root or "")) / rel
    if not str(root or "") or not path.is_file():
        out.update(refused=REFUSED_MISSING,
                   why=f"`{rel}` 不在盘上 ⇒ 没有可改的稿（这一档不新建稿）")
        return out
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out.update(refused=REFUSED_UNREADABLE,
                   why=f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 整笔不写"
                       "（读不到的稿不能当成没有）")
        return out
    _head, sections = _PR.split_sections(text)
    old_prop = next((body for name, body in sections if name == "命题"), "")
    old_prop = str(old_prop).strip()
    out["proposition_before"] = old_prop
    out["proposition_after"] = new_prop
    out["proposition_sha256_before"] = _PR.proposition_fingerprint(old_prop)
    out["proposition_sha256_after"] = _PR.proposition_fingerprint(new_prop)
    out["proof_sha256_before"] = _PR.proof_sha(text)
    out["checked"] = True
    if not old_prop:
        out.update(refused=REFUSED_NO_PROPOSITION, why=(
            f"`{rel}` 里没有 `## 命题` 那一节（或那一节是空的）⇒ 没有可原位替换的对象"
            "（缺节不等于「要新建一节」：那会改稿的形状，这一档不做）"))
        return out
    if not new_prop:
        out.update(refused=REFUSED_NO_PROPOSITION,
                   why="新命题正文是空的 ⇒ 没有可写下去的东西")
        return out
    if _norm_proposition(old_prop) == _norm_proposition(new_prop):
        # 幂等：同一段文字再交一次 ⇒ 一个字节都不动（也不花一次同一性判定）。
        out.update(ok=True, why="改前与改后是同一段文字（规范化后逐字相同）⇒ 一个字节没动",
                   body_unchanged=True, next_step=NEXT_STEP)
        out["proof_sha256_after"] = out["proof_sha256_before"]
        return out
    out["attempted"] = True

    # ---- 边界 ①：已入册 ⇒ 拒（走重新登记） --------------------------------------
    try:
        rows = [dict(r) for r in store.rows("statements")]
    except Exception as exc:  # noqa: BLE001 —— 读不到台账 = 判不了"入没入册"
        out.update(refused=REFUSED_UNJUDGED, why=(
            f"`statements` 台账读不出来（{type(exc).__name__}: {exc}）⇒ 判不了这份稿"
            "入没入册（读不到 ≠ 未入册）"))
        return out
    hit = _registered_row(rows, rel=rel, manuscript_id=out["manuscript_id"],
                          proposition=old_prop)
    if hit:
        sid = str(hit.get("stmt_id") or "")
        out["statements_row"] = hit
        out.update(refused=REFUSED_REGISTERED, why=(
            f"这份稿的命题已经入册（stmt:{sid or '?'}）⇒ 不允许原位改：改一条已登记命题的"
            "陈述等于换了一条命题，走重新登记（新的一条）或「放弃 + 换号」；"
            "本写口只服务「命题还没被收进 statements」的那一档"))
        return out

    # ---- 边界 ②：语义同一性判定（两态；判不了 ⇒ 拒） ----------------------------
    try:
        identity = dict(secretary.judge_same_proposition(
            before=old_prop, after=new_prop, label=str(label or ""),
            kind=str(kind or "conjecture"), task_id=task_id) or {})
    except Exception as exc:  # noqa: BLE001 —— 判定那一问炸了 = 没判成（fail-closed）
        identity = {"checked": False,
                    "reason": f"同一性判定调用失败（{type(exc).__name__}: {exc}）⇒ 没判成"}
    out["identity"] = identity
    if not identity.get("checked"):
        out.update(refused=REFUSED_UNJUDGED, why=(
            "同一性判定没判成（没缝 / 开关关着 / 超时 / 坏 JSON / 词表外）⇒ 受控拒："
            "「没判成」不许折成「同一条」。" + str(identity.get("reason") or "")))
        return out
    if str(identity.get("decision") or "") != "same":
        out.update(refused=REFUSED_DIFFERENT, why=(
            "同一性判定说这不是同一条命题（decision="
            f"{identity.get('decision')!r}）⇒ 受控拒：改后的陈述是另一条命题，"
            "应当登记成新的一条（新稿号 / 重新登记），不许借「改命题节」换命题。"
            + str(identity.get("reason") or "")))
        return out

    # ---- 边界 ③：受控写口（只换 `## 命题` 与稿头指纹；正文一个字节不动） ----------
    new_text, replaced = _PR.replace_section(text, "命题", new_prop)
    if not replaced:
        out.update(refused=REFUSED_WRITE, why=(
            "`## 命题` 那一节没换成（切节口径认不出它）⇒ 整笔不写（不整份重写）"))
        return out
    new_text = _PR.rewrite_proposition_head(
        new_text, new_fp=out["proposition_sha256_after"])
    #: 落盘之前先核一次"正文没动"：核不过就一个字节都不写（不是写完了再报）。
    body_after = _PR.proof_sha(new_text)
    out["proof_sha256_after"] = body_after
    out["body_unchanged"] = body_after == out["proof_sha256_before"]
    if not out["body_unchanged"]:
        out.update(refused=REFUSED_BODY_MOVED, why=(
            "换 `## 命题` 之后 `## 证明` 的正文 sha 变了 ⇒ 这一笔会动到签盖的那段字节，"
            "整笔不写（冻结面不开洞）"))
        return out
    try:
        _MF._atomic_write(path, new_text)
    except OSError as exc:
        out.update(refused=REFUSED_WRITE, why=(
            f"`{rel}` 没写成（{type(exc).__name__}: {exc}）⇒ 盘上那一份没变"))
        return out
    # ---- 签的现状（读数；不是判据） ----------------------------------------------
    try:
        from . import manuscriptfreeze as _FZ

        out["sign"] = dict(_FZ.freeze_reading(root, rel))
    except Exception as exc:  # noqa: BLE001 —— 签读数读不出来只影响读数
        out["sign"] = {"checked": False, "why": f"签的现状没读成（{type(exc).__name__}: {exc}）"}
    out.update(ok=True, wrote=True, next_step=NEXT_STEP,
               why=("已原位重写 `## 命题`（同一稿号、同一份稿）：正文 sha 未变、签仍有效；"
                    "下一步把这份稿重交 B 收编，不用重签"))
    return out
