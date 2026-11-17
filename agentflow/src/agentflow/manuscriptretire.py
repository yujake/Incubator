# -*- coding: utf-8 -*-
"""「命题退休 ⇒ 它名下那份稿一并作废」的唯一判据（业主 2026-11-13 裁定）。

## 业主口径（逐字）

「一个命题通过规范性审查后拿到一个稿号，之后关于这个命题的内容就写在这个稿上，
就在这个稿号的稿上 edit。放弃命题时就是这个稿也一并作废。」
「每个角色分开口径，自己管自己，稿号跨角色可不一致，就和与命题号不一致一样。」

⇒ 三条由此落定：

1. 1:1 是每族各自的 1:1：F 的命题有一份 f-稿、E 有 e-稿、B 有 b-稿，三族稿号可以
   互不相同（正如稿号与命题号也不一致）。B 优化 = 改 B 自己那份 b-稿，
   「B 改不动 F 的稿」不是缺陷，是角色-族绑定（`manuscriptopen.ROLE_FAMILIES`）。
2. 命题「退休」（`abandoned` / `refuted`）⇒ 它名下那份稿一并作废。
3. 作废 = 只读（不可 edit）+ 收工门不再要它 + 不再算依据；
   稿文件留着（删/挪/换名全被写面拒：`manuscriptopen.foreign_refusal`）。

## 「哪几份稿属于这条命题」= 三个既有来源的并集

不新增格、不迁移老盘。三个来源各有各的覆盖面，缺一个就会漏：

| 源 | 覆盖 | 出处 |
|---|---|---|
| `statements.manuscript_id` | 最近一次收录的那份 | `agent_b/proof_receipt.py` |
| `statements.manuscripts`（`{路径号: 稿路径}`） | 逐路径记录 | `manuscriptpaths.PER_PATH_KEY` |
| `verifications[].manuscript` | 所有签行点过的稿 | `verifications.record_verification` 写的 `manuscript` |

为什么必须并第三源：同一路径号再收录一次时，`proof_receipt.write_proof_receipt` 会把
`manuscripts["1"]` 覆写成新的那一份（`per[str(no)] = rel`），旧的 f-稿就从行上消失了 ——
但 V 的那一签还留在 `verifications[].manuscript` 里。少了它，F 那份稿在"命题被作废"
之后仍会被读成可写、可要签。

## 三态

`checked=False` 只出现在「读不出来」（statements 台账 / 验证台账读不成）——
"没查成"绝不折成"没退休"（那会让收工门与写面同时放行一个该拦的东西）。
"""
from __future__ import annotations

from typing import Any, Mapping

from . import errorstate as _ES

#: 哪些 `status` 算「退休」（该命题名下那份稿一并作废）。
#:
#: 只有这两档：`abandoned`（明确放弃）与错误那一档（今天的词是 `refuted`，词表补丁
#: 落地后是 `error` —— 词从 `errorstate.ERROR_WORDS` 现取，不在这里抄第二份）。
#: `superseded` 不在列：它是概念行的墓碑（"被后来的一条取代"），取代者还在，
#: 稿不该跟着作废；`disputed` 也不在列：争议未裁，稿还要继续改。
RETIRED_STATUSES: tuple[str, ...] = ("abandoned", *_ES.ERROR_WORDS)

#: 写面拒信的正文（与 `manuscriptfreeze` 的三句拒信同形：一句原因 + 一句指路）。
RETIRED_MANUSCRIPT_MESSAGE = (
    "这一份稿所属的命题已经退休（status={status}）⇒ 这份稿一并作废：只读，不再 edit"
    "（稿文件留着，不删不移 —— 它是那一条命题「曾经做到哪一步」的唯一证据）"
)


def status_is_retired(status: Any) -> bool:
    """这个 `status` 是不是「退休」（`abandoned` / 错误那一档）。"""
    return str(status or "").strip() in RETIRED_STATUSES


def _statement_rows(store: Any) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """`statements` 的全部行（按号索引）；读不出来 ⇒ `(None, why)`。

    索引构造只有一处（`statementledger.index_by_id`），不在这里另写一份推导式。
    """
    if store is None:
        return None, "没有 store"
    try:
        from . import statementledger as _SL

        return _SL.index_by_id(store.rows("statements")), ""
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        return None, f"{type(exc).__name__}: {exc}"


def _verified_manuscripts(store: Any, statement_id: str) -> tuple[list[str], list[str]]:
    """这一条命题的签行点过的稿路径（第三源）：返回 `(路径列表, 读不出来的原因)`。

    读不出来不是"没有这一源"：调用方把它当"没查成"（fail-closed），否则
    F 那份稿会在命题退休之后仍然被读成可写。
    """
    root = str(getattr(store, "root", "") or "")
    if not root:
        return [], "没有工作区根 ⇒ 签行读不了"
    try:
        from . import verifications as _VR

        rows, _problems = _VR.list_verifications(root, statement_id=statement_id, limit=None)
    except Exception as exc:  # noqa: BLE001
        return [], f"验证台账读不出来（{type(exc).__name__}: {exc}）"
    out: list[str] = []
    for row in rows or ():
        rel = str(dict(row).get("manuscript") or "").strip().replace("\\", "/")
        if rel and rel not in out:
            out.append(rel)
    return out, ""


def manuscripts_of_statement(store: Any, statement_id: Any) -> dict[str, Any]:
    """这一条命题名下的稿（三个来源的并集，去重保序）。

    返回 `{checked, found, statement_id, status, manuscripts, sources, problems, why}`。
    - `manuscripts`：工作区相对路径列表（源里的路径原样，统一 `/` 分隔）；
    - `sources`：`{路径: [来源名...]}`（`manuscript_id` / `manuscripts` / `verifications`），
      让读的人看得出"这一份是哪一格给出的"；
    - `checked=False`：命题台账或验证台账读不出来（没查成 ≠ 没有稿）。
    """
    sid = str(statement_id or "").strip()
    out: dict[str, Any] = {"checked": False, "found": False, "statement_id": sid,
                           "status": "", "manuscripts": [], "sources": {},
                           "problems": [], "why": ""}
    if not sid:
        out.update(checked=True, why="没给命题号 ⇒ 没有可查的稿（不是「没有稿」）")
        return out
    rows, why = _statement_rows(store)
    if rows is None:
        out["why"] = f"`statements` 读不出来（{why}）⇒ 这一格没查成"
        return out
    row = rows.get(sid)
    if row is None:
        out.update(checked=True, why=f"命题 {sid} 不在册 ⇒ 没有名下稿可查")
        return out
    out.update(found=True, status=str(row.get("status") or ""))
    sources: dict[str, list[str]] = {}

    def _add(rel: Any, source: str) -> None:
        text = str(rel or "").strip().replace("\\", "/")
        if not text:
            return
        sources.setdefault(text, [])
        if source not in sources[text]:
            sources[text].append(source)

    _add(row.get("manuscript_id") or "", "manuscript_id")
    raw = row.get("manuscripts")
    if isinstance(raw, Mapping):
        for _group, rel in raw.items():
            _add(rel, "manuscripts")
    elif raw is not None:
        out["problems"].append(f"`manuscripts` 不是映射（{type(raw).__name__}）⇒ 逐路径那一源没读成")
    verified, vwhy = _verified_manuscripts(store, sid)
    if vwhy:
        out["problems"].append(vwhy)
    for rel in verified:
        _add(rel, "verifications")
    # `manuscript_id` 是裸号（`000003`）时不能当路径用（写面的每处判据都按
    # `reports/<前缀><号>.md` 认）；它是路径时照旧留在清单里。两种形态都留在
    # `manuscript_id` 那一格里，读的人不必猜。
    bare = str(row.get("manuscript_id") or "").strip()
    if bare and "/" not in bare and "\\" not in bare and bare in sources:
        sources.pop(bare, None)
    out["manuscripts"] = list(sources)
    out["sources"] = sources
    out["manuscript_id"] = bare
    out["checked"] = True
    if not out["manuscripts"] and not out["problems"]:
        out["why"] = (f"命题 {sid} 名下没有任何一份稿（三源都空）—— 这不代表它没有稿，"
                      "而是「稿与命题的对应关系从来没被记过」")
    return out


def statement_of_manuscript(store: Any, *, rel: Any = "",
                            manuscript_id: Any = "",
                            sign_rows: bool = True) -> dict[str, Any]:
    """反查：这一份稿属于哪一条命题（唯一实现；反查的三源与正查同一个并集）。

    返回 `{checked, found, stmt_id, status, retired, rel, why}`。
    三态：`checked=False` ⇒ 台账读不出来（没查成）；`found=False` ⇒ 查过了、三源都不指向
    任何一行（未在册的稿，例如 F 交上来还没被 B 收录的那一份）—— 那一档不是"没问题"，
    只是本判据对它不说话（plan 级那边另有门）。

    `sign_rows=False` 收窄到收录记录那两源（`statements.manuscript_id` 与
    `statements.manuscripts`），不读签行那一源。为什么有人要收窄：问"这一份稿收进了
    哪一行"（`obligations.registration_gap` 的「必须收录」义务）时，签行回答的是
    "谁签过它"—— 一份稿可以先被签在 A 上、后来收进 B，拿签行认领会把义务引到错的行。
    默认 `True` 让既有调用方（退休判据那三源）一个字节都不变。
    """
    text = str(rel or "").strip().replace("\\", "/")
    mid = str(manuscript_id or "").strip()
    out: dict[str, Any] = {"checked": False, "found": False, "stmt_id": "", "status": "",
                           "retired": False, "rel": text, "why": ""}
    if not text and not mid:
        out.update(checked=True, why="没给稿路径 / 稿号 ⇒ 反查不了（不是「不属于任何命题」）")
        return out
    rows, why = _statement_rows(store)
    if rows is None:
        out["why"] = f"`statements` 读不出来（{why}）⇒ 这一格没查成"
        return out
    hits: list[str] = []
    for sid, row in sorted(rows.items()):
        if text and str(row.get("manuscript_id") or "").strip() == text:
            hits.append(sid)
            continue
        if mid and str(row.get("manuscript_id") or "").strip() == mid:
            hits.append(sid)
            continue
        per = row.get("manuscripts")
        if text and isinstance(per, Mapping) and text in {
                str(v or "").strip().replace("\\", "/") for v in per.values()}:
            hits.append(sid)
    if not hits and text and sign_rows:
        # 第三源（签行）单独查：它按命题逐条读，成本高，只在前面两源都没命中时走。
        for sid, _row in sorted(rows.items()):
            verified, _vwhy = _verified_manuscripts(store, sid)
            if text in verified:
                hits.append(sid)
    if not hits:
        out.update(checked=True, why=(f"三源里没有一行指向 {text or mid!r} ⇒ 这一份稿不在册"
                                      "（本判据对它不说话）"))
        return out
    if len(hits) > 1:
        out["why"] = (f"{text or mid!r} 同时被 {len(hits)} 条命题指向（{hits}）—— "
                      "1:1 的判据被破了（同一份稿只能属于一条命题），本判据按第一行读，"
                      "但这件事本身要报")
    sid = hits[0]
    row = rows[sid]
    out.update(checked=True, found=True, stmt_id=sid,
               status=str(row.get("status") or ""),
               retired=status_is_retired(row.get("status")))
    return out


def retire_reading(store: Any, rel: Any) -> dict[str, Any]:
    """这一份稿现在能不能写：`retired=True` ⇒ 只读（命题已退休，稿一并作废）。

    与 `manuscriptfreeze.freeze_reading` 的分工：冻结回答"拿签之后别改"，这一格回答
    "命题已经退休了，这份稿随它作废"。两件事必须分开读（一份已签的稿可以所属命题还活着；
    一份未签的稿也可以所属命题已退休）。
    """
    out: dict[str, Any] = {"checked": False, "retired": False, "stmt_id": "", "status": "",
                           "rel": str(rel or ""), "why": "", "message": ""}
    got = statement_of_manuscript(store, rel=rel)
    out.update(checked=bool(got.get("checked")), stmt_id=str(got.get("stmt_id") or ""),
               status=str(got.get("status") or ""), retired=bool(got.get("retired")),
               why=str(got.get("why") or ""))
    if out["retired"]:
        out["message"] = RETIRED_MANUSCRIPT_MESSAGE.format(status=out["status"])
    return out


def flow_reading(store: Any, *, rel: Any = "", manuscript_id: Any = "") -> dict[str, Any]:
    """这一份稿「还要不要继续走」（收工门与写面共用的那一个读数）。

    `retired` = 所属命题 `abandoned` / `refuted`（稿一并作废）；`hard_to_prove` =
    所属命题的优化栏记着「难以自证」（不欠签，但也不算已优化）。
    两件事分开给：写面只认前者（退休才不可 edit），收工门两个都不再要签。
    """
    out: dict[str, Any] = {"checked": False, "found": False, "retired": False,
                           "hard_to_prove": {}, "stmt_id": "", "status": "",
                           "row": {}, "why": ""}
    got = statement_of_manuscript(store, rel=rel, manuscript_id=manuscript_id)
    out.update(checked=bool(got.get("checked")), found=bool(got.get("found")),
               retired=bool(got.get("retired")), stmt_id=str(got.get("stmt_id") or ""),
               status=str(got.get("status") or ""), why=str(got.get("why") or ""))
    if not out["found"]:
        return out
    try:
        from . import evidencebits as _EB

        rows = {str(r.get("stmt_id") or ""): dict(r) for r in store.rows("statements")}
        row = rows.get(out["stmt_id"]) or {}
        out["row"] = dict(row)
        out["hard_to_prove"] = dict(_EB.hard_to_prove_by_proof(row))
    except Exception as exc:  # noqa: BLE001 —— 读不出来是"没查成"
        out.update(checked=False, why=f"优化栏读不出来（{type(exc).__name__}: {exc}）")
    return out
