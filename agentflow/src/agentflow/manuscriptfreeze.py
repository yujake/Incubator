# -*- coding: utf-8 -*-
"""拿签之后冻结：这一份稿只读。

## 业主口径（逐字）

```text
② 「稿通过后相当于这个命题证完了，后续只对稿允许有只读权，但由于尚未入台账暂无引用权，
    需要维护拿签稿的稿号表（在一次攻坚中应该是持续追加，后续交稿时一并递交给D）」

「同稿号多个版本是错误的，一个稿号就相当于是该稿的文件名……拿 V 签冻结后交哪份是明确的」
```

## 判据读 V 的颁发表（不新开一门）

「这一份已拿签」就等于「V 的颁发表里有它」—— 本模块不自己记账、不看稿头自述、
不看 `bits.reviewed`。数据只来自：

1. `vsigns.signed_table(root)` 里 `artifact_path` 等于这一份稿的那些行（`issue` 会写
   `artifact_path`）；
2. 老签没有 `artifact_path` 那一档：稿上有 `- V 签：` 块、而块里那个正文 sha 在
   颁发表里查得到（`vsigns.sign_of`）—— 仍然只信颁发表，块只是"这一份稿声明自己签过"。

## 四种状态（三态纪律：不折平）

| `state` | 什么意思 | 写口怎么处置 |
|---|---|---|
| `signed` | 签的 sha == 稿当前正文 sha ⇒ 正常冻结 | 受控拒（只读） |
| `edited_after_sign` | 签的 sha ≠ 稿当前正文 sha ⇒ 签后改过正文（违规态） | 受控拒，并把"签后改过正文"如实报出来 |
| `unsigned` | 查过了，颁发表里没有一份签指着它 | 放行（照旧能写） |
| `unchecked` | 这一格没查成（颁发表读不出来） | 不按"没签"放行：受控拒，理由说"没查成" |

`e-num` 不是签的载体（绿色通道），它永远 `state=unsigned`：那一族没有"拿签"这回事。

## 谁在拦（三处写口，一处判据）

- `tools/fs_tools.py::_reserved_refusal` —— `fs.write` / `fs.edit` / `fs.delete` /
  `fs.move` 四个写口共用那一处；
- `agent_f/core.py::_hand_proof` —— `attack.step(product=…)` 会沿用子目标已有的稿号
  （`reports/f-proof-<稿号>.md` 就地重写），那一格也要拦；
- `manuscriptform.promote_formal` —— 老盘搬家（`F.promote_manuscript` /
  `B.promote_formal` 共用的唯一实现）：把一份已签的稿改名/搬走就是改它。

三处都调 :func:`freeze_reading`，拒信都逐字来自 :data:`FREEZE_MESSAGE` /
:data:`EDITED_AFTER_SIGN_MESSAGE` —— 同一件事不许三处各说各的。

## 「暂无引用权」不在本模块

未收录（不在 `statements`）⇒ 已有的可引门已经在挡（`claims` / `citable_*` 那一批按
台账行判），这里不新加门、也不放宽它：冻结只回答"能不能写"，不回答"能不能引"。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import manuscriptfamily as _MFAM
from . import proofregistry as _PR
from . import vsigns as _VS

#: 受控码（三处写口的 `refused` / `kind`）。
MANUSCRIPT_FROZEN = "manuscript_frozen"

#: 冻结的拒信（逐字；业主口径：「后续只对稿允许有只读权」）。
#: 末尾那句指路是这条纪律的唯一正路：开优化副本（复制成 B 号、清签、改正文）。
FREEZE_MESSAGE = (
    "这一份已经拿签（签 sha={sha}），只读；要改就开 B 的优化副本"
    "（`B.open_polish_copy(statement_id=…)` → 复制成新的 B 号稿 → 改正文 → 重新送 V）"
)

#: 「签后改过正文」的拒信（违规态，如实报出来，不静默放过）。
EDITED_AFTER_SIGN_MESSAGE = (
    "这一份已经拿签（签 sha={sha}），但稿当前正文的 sha 是 {body} ⇒ 签后改过正文"
    "（违规态：拿签之后只对稿允许有只读权）。这一份只读；要改就开 B 的优化副本"
    "（`B.open_polish_copy(statement_id=…)`），或在改之前就别拿签"
)

#: 没查成那一档的拒信（不许折成"没签，可以写"）。
UNCHECKED_MESSAGE = (
    "拿签稿的颁发表读不出来（{why}）⇒ 判不了这一份签过没有，按只读处理"
    "（三态纪律：没查成不等于没签）；先把 `out/vsigns/` 修好再写"
)

#: 四种状态（闭集）。
STATES: tuple[str, ...] = ("signed", "edited_after_sign", "unsigned", "unchecked")


def freeze_reading(root: Any, rel: Any) -> dict[str, Any]:
    """这一份稿现在能不能写（`frozen=True` ⇒ 只读）。

    返回 `{checked, rel, is_manuscript, frozen, state, sign_sha, body_sha,
    attributed, block_found, block_signed, why, message}`。

    - `is_manuscript=False` ⇒ 它不是手稿形名字（冻结管不到它；`frozen=False`）；
    - `state` 见模块 docstring 的四档；`message` 是写口要原样回给模型的那句话。
    """
    raw = str(rel or "").strip().replace("\\", "/")
    out: dict[str, Any] = {
        "checked": True, "rel": raw, "is_manuscript": False, "frozen": False,
        "state": "unsigned", "sign_sha": "", "body_sha": "", "attributed": False,
        "block_found": False, "block_signed": False, "why": "", "message": "",
    }
    carrier = _MFAM.sign_carrier(raw)
    if not carrier.get("ok"):
        # `e-num` 不是签的载体（绿色通道不拿签）⇒ 没有"拿签后冻结"这回事。
        out.update(is_manuscript=bool(carrier.get("family")),
                   why=(f"`{raw}` 不是签的载体（{carrier.get('code') or '—'}）⇒ "
                        "这一族没有「拿签后冻结」这回事"))
        return out
    out["is_manuscript"] = True
    target = Path(str(root or "")) / raw
    if not str(root or "") or not target.is_file():
        out["why"] = f"`{raw}` 不在盘上 ⇒ 新建它不受冻结约束（不是「没查成」）"
        return out
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        out.update(checked=False, frozen=True, state="unchecked",
                   why=f"`{raw}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一格没查成",
                   message=UNCHECKED_MESSAGE.format(why=f"{type(exc).__name__}: {exc}"))
        return out
    out["body_sha"] = _PR.proof_sha(_VS.manuscript_proof_body(text))
    block = _VS.manuscript_sign_reading(text, manuscript_path=raw)
    out["block_found"] = bool(block.get("found"))
    out["block_signed"] = bool(block.get("signed"))
    table = _VS.signed_table(root)
    if not table.get("checked"):
        out.update(checked=False, frozen=True, state="unchecked",
                   why=(f"拿签稿的颁发表没查成：{table.get('why') or '（没有理由）'}"),
                   message=UNCHECKED_MESSAGE.format(
                       why=str(table.get("why") or "颁发表列不出来")))
        return out
    # 这些行只读（数条数、取最后一行的签 sha），不再整批 `dict(...)` 拷一遍：
    # `signed_table` 每次交出的就是那一趟新读出来的 dict。
    entries = table.get("entries") or []
    by_path = [e for e in entries if str(e.get("artifact_path") or "") == raw]
    if by_path:
        out["attributed"] = True
        sign_sha = str(by_path[-1].get("artifact_sha") or "")
        return _finish(out, sign_sha=sign_sha,
                       why=(f"V 的颁发表里有 {len(by_path)} 份签指着 `{raw}`"))
    # 老签（`artifact_path` 是空的那一档）：只认"稿上声明签过 + 那个 sha 在颁发表里"。
    block_sha = str(block.get("proof_sha256") or "")
    if block.get("found") and block_sha:
        got = _VS.sign_of(root, block_sha)
        if got.get("found"):
            out["attributed"] = True
            return _finish(
                out, sign_sha=block_sha,
                why=(f"稿上的签块声明签过 {block_sha[:12]}…，而 V 的颁发表里确有这一签"
                     "（老签没记 `artifact_path`，按稿上的声明认领）"))
    return _finish(out, sign_sha="",
                   why=(f"查过了：V 的颁发表里没有一份签指着 `{raw}`"
                        "（按路径与稿上的签块都找过）⇒ 这一份没拿签，可以写"))


def _finish(out: dict[str, Any], *, sign_sha: str, why: str) -> dict[str, Any]:
    """把"有没有签"折成四档状态与那句拒信（`out` 就地改并返回）。"""
    out["sign_sha"] = str(sign_sha or "")
    if not out["sign_sha"]:
        out.update(frozen=False, state="unsigned", why=why, message="")
        return out
    body = str(out.get("body_sha") or "")
    if out["sign_sha"] == body:
        out.update(frozen=True, state="signed", why=why,
                   message=FREEZE_MESSAGE.format(sha=out["sign_sha"]))
        return out
    out.update(frozen=True, state="edited_after_sign", why=why,
               message=EDITED_AFTER_SIGN_MESSAGE.format(sha=out["sign_sha"], body=body))
    return out
