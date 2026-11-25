# -*- coding: utf-8 -*-
"""收录回执那一格：把这一份正文的号与指纹写到 `statements` 顶层。

只做两件事：这一行真有一份正文时，把它的号（`proof_no`）与现算的正文 sha 写到
`statements` 顶层；并把这一份稿记进逐路径记录（`manuscripts`：路径号 ⇒ 稿的
工作区相对路径）。`manuscript_id` 仍是"最近一次收录的那份稿"的兼容读数，语义不变。

为什么回执与"第 2 位这次翻没翻"解耦：一条新建的「命题 + 证明」（`bits.proof` 一开始
就为真）走不到"翻位"那一支，不解耦就永远拿不到回执 —— 返回值说第 1 份，而盘上
`proof_no` / `proof_sha256` 一个字节都没写。号只从这一笔的落点读，不猜。

为什么还要逐路径那一格（2026-11-13，V1-A）：一份命题可以有多条证明路径，而
`manuscript_id` 只有一格 —— 每收录一条路径就被覆写成"最后一次"。于是"第 1 条路径
是哪份稿"只剩签行那一处读数，而收录前落下的 pending 行在收录之前不属于任何命题
（`verifications._claimed_pending_rows` 只认已认领的）。这一格按路径号各留一份，
读侧（`manuscriptpaths.path_reading`）就能在"从没有在册重签过"的那条路径上认出稿。
老盘没有这一格 ⇒ 读侧一个字都不加（退回旧口径），不写迁移脚本。
"""
from __future__ import annotations

from typing import Any, Mapping

from .. import manuscriptpaths as _MP
from .. import proofregistry as _PR
from ._support import _norm_manuscript_rel


def _kept_per_path(row: Mapping[str, Any]) -> dict[str, str]:
    """行上已有的逐路径记录 ⇒ 一份可写的 `{路径号: 稿路径}`（坏形状 ⇒ 空字典）。

    坏形状（不是映射 / 值不是字符串）不在这里猜：读侧
    `manuscriptpaths._per_path_manuscripts` 会把它记成一条读数问题（"没读成"），
    写侧遇到它只会用这一笔的读数重建这一格 —— 重建的是这一笔的路径，
    别的路径在那份坏值里本来就没有可救的内容。
    """
    raw = row.get("manuscripts")
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, str] = {}
    for group, rel in raw.items():
        text = _norm_manuscript_rel(rel)
        if text:
            out[str(group)] = text
    return out


def write_proof_receipt(
    row: dict,
    out: dict,
    *,
    body_now: str,
    proof_no: int,
    manuscript_id: str,
    manuscript: str = "",
    root: Any = "",
) -> None:
    """把这一行现在这一份证明的号 / 正文指纹 / 稿号写到顶层（就地改 `row` 与 `out`）。

    只在"这一行真有一份正文"时由调用方进来（e-num 那一档没有正文 ⇒ 顶层不写 ——
    没有证明就不许读出"第 1 份证明"）。

    `proof_no` 就是这一份稿的路径号（B 收录事务里分的那个号，canonical = 1）：
    逐路径记录用它当键，于是"第几条路径 ⇒ 哪份稿"与依赖行 / 签行同号。
    `manuscript` 是这一份稿的工作区相对路径（收方读稿那一路有；只给正文的
    `register_statement` 调用没有 ⇒ 这一笔只写 `manuscript_id`，逐路径记录不写）。

    `root` 给得出工作区根时，逐路径记录连记录时的字节 sha 一起写
    （`manuscriptpaths.record_manuscript` 的同一处写口）：名字可复用、可覆盖，
    只存名字的话"这条命题的稿被换成了别条命题的证明"永远没有东西能判红
    （2026-11-26 真机 sunflower-digest-2 的现场）。读不到那份文件 ⇒ 不写 sha，
    绝不编一个（"没记"与"记了、对得上"必须分得开）。
    """
    want_sha = _PR.proof_sha(body_now)
    mid = str(manuscript_id or row.get("manuscript_id") or "")
    # 这一格要写四处（比较一次、写 row 两格、写回执一格）：转换只做一次。
    no = int(proof_no)
    rel = _norm_manuscript_rel(manuscript)
    per = _kept_per_path(row)
    #: 逐路径记录这一笔该不该写：有稿、号合法、而且这一号上还不是这一份稿。
    add_path = bool(rel and no >= 1 and per.get(str(no), "") != rel)
    if (str(row.get("proof_sha256") or "") != want_sha
            or int(row.get("proof_no") or 0) != no
            or (bool(mid) and str(row.get("manuscript_id") or "") != mid)
            or add_path):
        row["proof_no"] = no
        row["proof_sha256"] = want_sha
        out["proof_receipt"] = {"proof_no": no,
                                "proof_sha256": want_sha}
        # ---- 行上记 `manuscript_id`（F 自己的稿号）
        #
        # 稿名与命题号不再绑定 ⇒ "这一行是哪一份稿"只能由这一格回答。
        # F 的稿号与命题号不同形（前者是 F 自己发的六位号），D 的携带单、
        # F 的交差读数、B 的签块闸都按它回找那份稿。
        #
        # 2026-11-13 起它的语义固定为"最近一次收录的那份稿"：逐路径的记录在
        # 下面那一格，两者不是同一件事 —— 这一格会被第 2 条路径覆写，那一格不会。
        if mid:
            row["manuscript_id"] = mid
            out["proof_receipt"]["manuscript_id"] = mid
        # ---- 逐路径的稿：`{路径号: 稿路径}` + `{路径号: 字节 sha}`（这一行每条路径各一份，不互相覆写）
        #
        # 只写行、不进 `proof_receipt` 的键集合：回执答的是"这一行现在这一份"，
        # 逐路径是"这一行的每一条路径"，读口是 `manuscriptpaths.path_reading`
        # （一个读口，不在这里另开第二份）。
        if add_path:
            wrote = _MP.record_manuscript(row, no, rel, root=root)
            row["manuscripts"] = dict(row.get(_MP.PER_PATH_KEY) or {})
            out["proof_receipt"]["manuscript_bytes"] = {
                "path": wrote.get("path", ""), "sha256": wrote.get("sha256", ""),
                "sha_known": bool(wrote.get("sha_known"))}
