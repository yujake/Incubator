# -*- coding: utf-8 -*-
"""pending 读侧（哪一行算那一签）。

2026-11-20（VERSPLIT2）：`v_pending_read.py` 是从 `verifications.py` 搬出的 14 块 / 540 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF


def pending_dir(root: str | Path) -> Path:
    """pending 台账的目录（只算路径，不建目录）。"""
    return verifications_dir(root) / PENDING_DIR_NAME


def pending_ledger_path(root: str | Path, key: str) -> Path:
    """一份 pending 台账：`verifications/pending/<内容 sha>.jsonl`（按对象内容分文件）。"""
    text = str(key or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise VerificationError(
            "pending 台账的文件名必须是 64 位十六进制的 sha256（按对象内容分文件），"
            f"收到 {key!r}")
    return pending_dir(root) / f"{text}.jsonl"


def _pending_ledgers(
    root: str | Path,
) -> tuple[list[tuple[Path, list[dict[str, Any]]]], list[str]]:
    """`verifications/pending/` 的逐份台账（按文件名序；行序 = 追加序），坏行照实报。

    为什么单列这一格（2026-11-11，p284）：`pending` 的一"份"台账就是同一份正文
    的那一叠签（文件名 = 正文 sha 或载体对象的 sha）。票数与"是不是同一份正文"
    只能在同一份文件里数 —— 摊平成一张跨文件的行表之后，两张 sha 不同的台账会被
    读成一条连续序列。:func:`pending_rows` 仍是"全部行"那一口（跨文件，给只问
    "有没有这一签"的调用方），本函数是"哪一叠"那一口的唯一入口。
    """
    base = pending_dir(root)
    ledgers: list[tuple[Path, list[dict[str, Any]]]] = []
    problems: list[str] = []
    if not base.is_dir():
        return ledgers, problems
    for file in sorted(base.glob("*.jsonl")):
        rows, bad = JF.read_jsonl(file)
        problems.extend(f"{PENDING_DIR_NAME}/{file.name}: {b}" for b in bad)
        ledgers.append((file, [dict(r) for r in rows]))
    return ledgers, problems


def pending_stacks(
    root: str | Path,
) -> tuple[list[tuple[Path, list[dict[str, Any]]]], list[str]]:
    """`verifications/pending/` 的逐份台账（公开读口，实现在 :func:`_pending_ledgers`）。

    为什么需要它（2026-11-17，PASSROWS1 的现场）：pending 台账按"载体"分文件
    （`record_pending_sign` 的键是 `object_sha256 or proof_sha256`），而同一份正文
    可以有两个载体 ⇒ 它的几行会住在两叠台账里。回写认领（`vsigns.bind_pending_claim`）
    必须知道"哪一行住在哪一份文件里"才写得回去；摊平之后的 `pending_rows` 只剩行，
    写回去就无从定位。这里只是把那个私有读口公开，判据与行序一个字没动。
    """
    return _pending_ledgers(root)


def pending_rows(root: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """pending 台账的全部行（按落盘顺序；坏行照实报出，不静默跳过）。"""
    ledgers, problems = _pending_ledgers(root)
    #: `_pending_ledgers` 交出来的每一行已经是那一份文件的一份新拷贝（它与盘上/缓存
    #: 都不共享），这里不再逐行 `dict(...)` 拷第二遍。
    return [row for _file, rows in ledgers for row in rows], problems


def _issued_anchor_of_pending(root: str | Path, *, sha: str,
                              tail: Mapping[str, Any]) -> dict[str, Any] | None:
    """尾行不是结论时，认「已经发出去的那一签」锚在的那一行（R10FIX-D2）。

    ## 断链在哪（真机 lp-ball-10，2026-11-19）

    `reports/f-proof-000001.md` 的 3/3 签在 13:42:16 由 `sign_counting` 数出来并颁发了
    （`out/vsigns/4e418348….json`，`ledger=verifications/pending/ef286c92….jsonl#u-000024`）。
    11 秒后 V 又对同一份稿跑了一趟，那一趟的第 2 轮落成 `u-000025`，秘书判 没查成
    （`axis=""`、`checked=false`）。而 `pending_sign` 的认领口径是"最后扫到的那一行说了
    算" ⇒ 它交回的是 `u-000025`、`row_signable` 为假 ⇒ 认领与凭据读数双双 fail-closed：
    B 收录那一笔不回写 `statement_id`、`kind` 停在 `conjecture`，验收表 R7 读成
    `unknown`（「plan 点名了 stmt:000015 而 verifications 没有对应的行」）。

    ## 判据（三态，不折平）

    - 尾行自己签得住（`row_signable`）⇒ 不改判（照旧"最近一次审校说了算"）；
    - 尾行的轴是 `fault` ⇒ 不改判：那是"后来那一趟说它坏了"，旧签不许复活；
    - 尾行只是没判成 / 没轴（不是结论）且这一份正文有一份复算通过的签 ⇒ 认那一签
      锚在的那一行；
    - 其余（没有签文件 / 复算不通过 / 锚点不在 pending / 那一行也签不住）⇒ `None`，
      调用方照旧按尾行判（fail-closed）。

    读数只取两份既有实现：`vsigns.credential_reading`（签文件存在 + 票数是同一趟数出
    来的）与 `vsigns.sign_ledger_backing`（锚点那一行在盘上、sha 相符、自己签得住）。

    返回 `{"row", "path"}`（`path` 是锚点那一行所在的那叠台账 —— 同一份正文住两叠时，
    票数只能在那一叠里数）；不适用 ⇒ `None`，调用方照旧按尾行判。
    """
    if not str(sha or "").strip():
        return None
    if row_signable(tail):
        return None
    if str(verifications.ledger_axis(tail) or "") == "fault":
        return None
    try:
        from . import vsigns as _VS

        cred = _VS.credential_reading(root, sha)
        if not cred.get("recomputable"):
            return None
        where = str(cred.get("where") or "").replace("\\", "/")
        if not where.startswith(f"{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/"):
            return None
        backing = _VS.sign_ledger_backing(root, where, proof_sha256=sha)
    except Exception:  # noqa: BLE001 —— 读不动 ⇒ 不改判（fail-closed）
        return None
    if not backing.get("ok"):
        return None
    row = dict(backing.get("row") or {})
    if not row:
        return None
    #: `path` 交回去：PASSROWS1 起同一份正文可以住在两叠待认领台账里，锚点那一行
    #: 可能在另一叠。调用方要拿它把 `passes` 换成锚点那一叠（票数只能在那一叠里数）。
    return {"row": row, "path": str(backing.get("path") or "")}


def _pending_claim_of(row: Mapping[str, Any]) -> str:
    """这一行 pending 归给哪一条命题（两个号同值；都空 = 还没认领）。"""
    return str((row or {}).get("stmt_id") or (row or {}).get("statement_id") or "").strip()


def _pending_stack_of_row(
    row: Mapping[str, Any], *,
    stacks: Sequence[tuple[Path, Sequence[Mapping[str, Any]]]],
) -> list[dict[str, Any]]:
    """这一行所在的那一叠 pending 台账（整份文件、行序 = 追加序）。

    ## 为什么取整叠，而不是只取已认领的行（2026-11-20，READUNIFY）

    签是「一叠」的事：`record_pending_sign` 按载体分文件，签发那一刻数的是同一份文件里
    的几转。同一份正文后来又被 V 审了一转、而那一转还没认领时，它仍是这一签之后的
    那一转 —— V2FIX 的第二路只读已认领的行，于是「锚行之后有 fault」这一档永远读不出来
    （真机 `lp-ball-12` 的 000071：u-000045 判 `fault`、而 u-000042..44 已认领）。

    找不到那一叠时退回只有这一行（fail-closed：不借别叠的行来当凭据）。
    """
    vid = str(row.get("verification_id") or "")
    at = str(row.get("at") or "")
    sha = str(row.get("proof_sha256") or "")
    #: 文件名的键就是 `record_pending_sign` 的 `object_sha256 or proof_sha256`：先按它定位
    #: （同一个 `u-` 号在不同叠里会重复，见 lp-ball-10 的三叠都有 u-000001），再核这一行
    #: 真的在那份文件里；对不上才退回逐行扫描。
    key = str(row.get("object_sha256") or sha or "").strip().lower()

    def _has(rows: Sequence[Mapping[str, Any]]) -> bool:
        return any(str(one.get("verification_id") or "") == vid
                   and str(one.get("at") or "") == at
                   and str(one.get("proof_sha256") or "") == sha
                   for one in rows)

    for _file, rows in stacks:
        if key and Path(str(_file)).stem.lower() == key and _has(rows):
            return [dict(r) for r in rows]
    for _file, rows in stacks:
        if _has(rows):
            return [dict(r) for r in rows]
    return [dict(row)]


def _pending_sign_row(root: str | Path, *, rows: Sequence[Mapping[str, Any]],
                      tail: Mapping[str, Any] | None = None,
                      sha: str = "") -> dict[str, Any]:
    """这一叠 pending 行里，哪一行算「那一签」—— 全仓唯一的取行实现。

    ## 为什么要有这一格（2026-11-20，READUNIFY）

    同一份盘上两个读口各取各的行，就会一个说「有签」、一个说「没签」：

    - 读口① :func:`pending_sign`（认领 / 凭据 / B 的入库闸都从它取数）在
      R10FIX-D2 之后认「已发签锚在的那一行」；
    - 读口② :func:`unverified_statement_refs` 的第二路（V2FIX）取 `claimed_rows[-1]`。

    真机 `lp-ball-10` 的 `stmt:000015`：4 行 pending 前 3 行 3/3、签文件
    `out/vsigns/4e418348….json` 锚在 u-000024，尾行 u-000025 没判成（没轴）⇒
    ① 认 u-000024（有签），② 取 u-000025（missing）。两处对「哪一行算这一签」必须
    只有一个答案，所以两个读口都调本函数，判据本体仍是 :func:`_issued_anchor_of_pending`。

    ## 取哪一行（三档，不折平）

    - 这一份正文有一份已发出的签、锚点在盘上、那一行自己签得住 ⇒ 认锚行
      （签文件是「这一份正文被签过」的唯一凭据）；
    - 锚点之后那一行（同一份正文的最后一行）判 `fault` ⇒ 否决：后来的否决盖过更早
      的成立（与 `closing._one_manuscript_sign` 的 RETIRE-E3 同一条纪律）；
    - 没有签文件 / 锚点不在盘上 / 锚行也签不住 ⇒ 按尾行判（尾行签得住才有签，
      没判成不算）。这条兜底就是「先签后收录」里还没签发时的旧射程
      （`tests/test_closing_gate.py` 的 V2FIX 正控与
      `tests/test_pending_sign_claims_the_new_statement.py` 都压在这一档上）。

    `rows` 是这一叠（同一份正文的）行，`tail` 缺省取最后一行，`sha` 缺省取行的
    `proof_sha256`。返回 `{row, anchored, path, signable, state, sha, why}`；`state`
    只有 `anchor` / `vetoed` / `tail` 三档（读数用，不另立判据）。
    """
    pile = [dict(r) for r in (rows or ()) if isinstance(r, Mapping)]
    last = dict(tail) if isinstance(tail, Mapping) else (pile[-1] if pile else {})
    want = str(sha or last.get("proof_sha256") or "")
    anchored = (verifications._issued_anchor_of_pending(root, sha=want, tail=last)
                if last else None)
    row = dict(anchored.get("row") or {}) if anchored else last
    vid = str(row.get("verification_id") or "")
    signable = bool(row) and row_signable(row)
    if anchored:
        state, why = "anchor", (
            f"这一份正文有已发出的签，锚在 {vid}（那一行签得住）⇒ 认锚行"
            "（尾行只是一趟没判成的重审，不盖掉那一签）")
    elif last and str(verifications.ledger_axis(last) or "") == "fault":
        state, why = "vetoed", (
            f"尾行 {vid} 判 fault ⇒ 后来的否决盖过更早的成立，不算有签")
    else:
        state, why = "tail", (
            f"没有可认的签文件锚点 ⇒ 按尾行 {vid} 判"
            f"（{'签得住' if signable else '签不住'}）")
    return {
        "row": row, "anchored": bool(anchored),
        "path": str((anchored or {}).get("path") or ""),
        "signable": signable, "state": state, "sha": want, "why": why,
    }


def pending_sign(root: str | Path, *, object_sha256: Any = "",
                 proof_shas: Sequence[str] = ()) -> dict[str, Any]:
    """按对象内容的 sha 认领 pending 台账里的那一签（最近一次有结论的审校说了算）。

    返回 `{"found","verdict","proof_sha256","object_sha256","ledger","row","passes",
    "why"}`。`found=False` 只表示"pending 里没有盖住这一份的签"，不是"没查成"；
    读不出来时才抛 `VerificationError`（三态：没查成不许折成没有签）。

    `row` 是认到的那一整行（`found=True` 时非空）：判据在调用方那一侧，而它们要的
    `unresolved_errors` / `citation_checks` / `citation_gate` 三格只在行上 ——
    交半行出去等于逼调用方退回"只看 verdict 那个词"。

    `passes`（2026-11-11，p284）是那一签所在的那一叠台账的全部行（行序 = 追加序）。
    为什么要交出去：票数与"三票同一份正文"只能在同一份 pending 台账里数
    （见 :func:`_pending_ledgers`）；只交最后那一行，调用方就只数得出"有一票"，
    于是"一票也抬档"（`_gap_from_pending` 的 p284 注释）。

    ## 2026-11-17（PASSROWS1）：同一份正文有几叠时，认「票数最多的那一叠」

    改前这里"最后扫到的那一行说了算"，而扫描序是文件名（sha）的字典序 ⇒ 同一份正文
    一旦住在两叠里，认到哪一叠全凭 sha 撞成什么：实测同一条链连跑，台账读成 1 行 /
    3 行两种，登记出来的 kind 随之在 `conjecture` / `theorem` 之间跳（真值 4 行 =
    V 的三转 + 准入门那一份前提签，`theorem`）。所以改成按"这一份正文在该叠里有几行"
    取最大，同票数仍按文件名序；`hit_rows` 仍是那一叠（`passes` 的射程不动）。

    ## 2026-11-19（R10FIX-D2）：尾行不是结论时，认已发签锚在的那一行

    上面那条"最后一行说了算"只在最后一行是结论时成立。V 完全可以在一份稿拿到
    签之后再跑一趟（真机 lp-ball-10 的 13:42:52 那一趟），而那一趟可能没判成 / 没
    留下轴 —— 那一行不是结论，却把之前那份 3/3 的签盖掉了。判据本体在
    :func:`_issued_anchor_of_pending`（尾行 `fault` 仍按尾行算；没签文件仍按尾行算）。
    `anchored_at_issued_sign` 是这一格的读数（读的人能看出"这不是尾行"）。
    """
    out: dict[str, Any] = {"found": False, "verdict": "", "proof_sha256": "",
                           "object_sha256": "", "ledger": "", "row": {},
                           "passes": [], "why": ""}
    obj = str(object_sha256 or "").strip().lower()
    wants = {str(s or "").strip().lower() for s in (proof_shas or ()) if str(s or "").strip()}
    ledgers, problems = _pending_ledgers(root)
    if problems:
        raise VerificationError("；".join(problems[:3]))
    hit: dict[str, Any] | None = None
    hit_rows: list[dict[str, Any]] = []
    hit_votes = 0
    for _file, rows in ledgers:
        matched = 0
        last: dict[str, Any] | None = None
        for row in rows:
            got_obj = str(row.get("object_sha256") or "").strip().lower()
            got_proof = str(row.get("proof_sha256") or "").strip().lower()
            if obj:
                if got_obj != obj:
                    continue
            elif wants:
                if got_proof not in wants:
                    continue
            else:
                continue
            matched += 1
            last = row
        #: 同一份正文住在两叠里时（`record_pending_sign` 按载体分文件），认「票数最多
        #: 的那一叠」：一叠只有一行的准入门前提签不可能是一份三转签的凭据，而票数与载体
        #: 稿号（第 9 格）都只在"那一签自己那一叠"里对得上。同票数仍按文件名序
        #: （与改前的 tie-break 一致），所以这一格仍然确定 —— 只是不再由"谁名字大"决定。
        if last is not None and matched >= hit_votes:
            hit = last
            hit_rows = rows
            hit_votes = matched
    if hit is None:
        where = (f"对象 sha256 {obj[:12]}…" if obj else f"证明正文 sha {sorted(wants)[:1]}")
        out["why"] = (f"`{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/` 里没有盖住这一份"
                      f"（{where}）的签 —— 命题还没在册时 V 也没审过它")
        return out
    # ---- R10FIX-D2：尾行不是结论时，认已经发出去的那一签锚在的那一行 ----------
    # 位置在这里（而不是调用方）：`pending_sign` 是"这一份正文有没有签"的唯一读口，
    # 认领 / 凭据（`proof_review_gap`）/ B 的入库闸都从它取数；在调用方各修一遍
    # 会让"哪一行算这一签"出现第二份口径。取行本体在 :func:`_pending_sign_row`
    # （2026-11-20 READUNIFY：V2FIX 第二路也调它，两个读口同一个答案）。
    picked = verifications._pending_sign_row(
        root, rows=hit_rows, tail=hit, sha=str(hit.get("proof_sha256") or ""))
    if picked.get("anchored"):
        out["anchored_at_issued_sign"] = {
            "tail": str(hit.get("verification_id") or ""),
            "verification_id": str((picked.get("row") or {}).get("verification_id") or ""),
            "why": ("尾行不是结论（没判成 / 没轴）而这一份正文已经发过签 ⇒ "
                    "认那一签锚在的那一行（fault 与没签文件两档仍按尾行算）"),
        }
        hit = dict(picked.get("row") or {})
        # 同一份正文可能住在两叠台账里（PASSROWS1）：票数只能在锚点那一叠里数。
        # `sign_ledger_backing` 交回的是相对路径（`verifications/pending/<sha>.jsonl`），
        # 而 `ledgers` 里是绝对的 —— 按文件名比（pending 台账的文件名就是它自己的键）。
        _anchor_name = Path(str(picked.get("path") or "")).name
        if _anchor_name:
            for _file, rows in ledgers:
                if Path(str(_file)).name == _anchor_name:
                    hit_rows = rows
                    break
    out.update(found=True, verdict=str(hit.get("verdict") or ""),
               proof_sha256=str(hit.get("proof_sha256") or ""),
               object_sha256=str(hit.get("object_sha256") or ""),
               #: 认到的那一整行（2026-10-27 补）。为什么要交出去：`signs_bit3` 要读
               #: `unresolved_errors` / `citation_checks` / `citation_gate` 三格，而它们
               #: 改前在这一格里被丢掉了 ⇒ 调用方只能退回"看 verdict 那个词"，
               #: 于是同一行内容在 pending 与命题台账两处被两套判据读。
               row=dict(hit),
               #: 这一签所在那一叠台账的全部行（票数 / 同一份正文的判据处，p284）。
               passes=[dict(r) for r in hit_rows],
               ledger=(f"{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/"
                       f"{str(hit.get('object_sha256') or hit.get('proof_sha256') or '')[:64]}"
                       f".jsonl#{hit.get('verification_id') or '?'}"))
    out["why"] = (f"{out['ledger']} 是按对象内容 sha 认领到的那一签，"
                  f"verdict={out['verdict']!r}")
    return out


def _claimed_pending_rows(root: str | Path, *, statement_id: str = ""
                          ) -> tuple[list[dict[str, Any]], list[str]]:
    """`verifications/pending/` 里已经认领的那些行（收录之后它们属于某一条命题）。

    ## 为什么要在读侧并进来（2026-11-10，缺陷：收录之后 `list_verifications` 读成 0 行）

    没号先签那一档的台账行物理上住在 `verifications/pending/<正文 sha>.jsonl`（按内容
    sha 分文件，D-34 的落点：同一份正文只认领一次）。B 收录拿到号之后，认领这一步
    （`vsigns.bind_pending_claim`，唯一写口）只在那一行上回写 `statement_id` / `stmt_id` /
    `claimed_at`，不搬文件：签块与签文件的 `台账=` 仍指着
    `verifications/pending/<sha>.jsonl#u-…`，搬走就会让那块签的背书断掉。

    于是"已认领的 pending 行"有两种读法：搬进 `verifications/<号>.jsonl`，或读侧把它算进
    在册台账。这里选后者（本函数是唯一并入口）：物理位置不变、签的锚点不变，读的人按
    「这条命题有谁审过」问 `list_verifications` 时能读到它们。

    ## 口径（只认已认领的，不认未认领的）

    - 有 `statement_id` / `stmt_id` ⇒ 这一行已经属于那一条命题 ⇒ 算在册台账；
    - 两个都空 ⇒ 它还不属于任何命题（V 审过、还没被收录）⇒ 不算任何一条命题的记录，
      继续只由 pending 那一层读（`pending_rows` / `pending_sign`）。

    两套口径不并存：`list_verifications` 是"一条命题的验证记录"的唯一读口，未在册那一档
    的读口是 `pending_rows`；本函数只把前者的射程扩到"已认领"，不改 pending 文件的
    角色（它仍是那一签的正本）。
    """
    rows, problems = pending_rows(root)
    want = str(statement_id or "").strip()
    out: list[dict[str, Any]] = []
    for row in rows:
        sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
        if not sid:
            continue
        if want and sid != want:
            continue
        #: `rows` 已经是 `pending_rows` 为这一趟新拷出来的一批行，这里不再拷第三遍。
        out.append(row)
    return out, problems


def _pending_standing_rows(root: str | Path, *, statement_id: str, sha: str,
                           proof_no: int, proof_text: str) -> dict[str, Any] | None:
    """`review_standing` 的 pending 回退：把「先签后收录」那一叠行交出来（FIX186-D1）。

    ## 为什么需要它

    「先签后收录」是主路：V 在命题还没在册时审、B 收录时才拿到号 ⇒ 那一签住在
    `verifications/pending/<载体 sha>.jsonl`，在册台账 `verifications/<命题号>.jsonl`
    可能根本不存在（lp-ball-11 的 000005：pending 里同一个 `review_call` 3/3「成立」，
    在册台账没有这个文件）。`proof_review_gap` 早就有这条回退
    （`:5960-5988` 的 `_pending_signed`），`review_standing` 没有 ⇒ 同一件事两个
    读口两个答案：`statement_review_reading` 读成 unsigned、`final_gaps` 因此 +1、
    acceptance 的 `construct_leg.linked.where` 指向一个不存在的文件。

    本函数只负责"把哪一批行交给 `review_standing`"，判定仍只有那一套
    （`_hold_runs` / `row_signable` / `signs_bit3`）—— 不新造第二份判据。

    返回 `{rows, ledger, rows_total}` 或 `None`（pending 里也没有盖住这一份的签）。
    认领给别的命题的行一律不交出去（借光会让别人的签变成这一条的凭据）。
    """
    if not str(proof_text or "").strip():
        return None
    try:
        got = pending_sign(root, proof_shas=(sha,))
    except VerificationError:
        return None
    if not got.get("found"):
        return None
    row = dict(got.get("row") or {})
    claimed = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
    want = str(statement_id or "").strip()
    if claimed and want and claimed != want:
        return None
    passes = [dict(r) for r in (got.get("passes") or []) if isinstance(r, Mapping)]

    def _claimed_of(one: Mapping[str, Any]) -> str:
        return str(one.get("stmt_id") or one.get("statement_id") or "").strip()

    mine = [r for r in passes
            if proof_no_of(r) == int(proof_no)
            and str(r.get("proof_sha256") or "").strip().lower() == str(sha).lower()
            # 同一叠里混着"认给别的命题"的行也不许借（逐行判，而不只看认到的那一行）。
            and (_claimed_of(r) in ("", want))]
    if not mine:
        return None
    return {"rows": mine, "ledger": str(got.get("ledger") or ""),
            "rows_total": len(passes)}


def _pending_signed(root: str | Path, proof_text: Any) -> dict[str, Any] | None:
    """命题还没在册时 V 审的那一签（按这一份正文的 sha 认领）；没有 ⇒ `None`。

    D-34：`verifications/pending/<sha>.jsonl` 里的那一行是真的审过（七项机械会审），
    只是当时没有命题号可挂。它是"先签后登记"那一半的证据面，所以在
    :func:`proof_review_gap` 里与"这一条命题台账里的那一签"同等看待 —— 判据仍然只有
    这一处（`signs_bit3`：成立且没有未解决 error）。
    """
    text = str(proof_text or "")
    if not text.strip():
        return None
    try:
        got = pending_sign(root, proof_shas=(_sign_sha(text),))
    except VerificationError:
        return None
    if not got.get("found"):
        return None
    return got


def _pending_claim_streak(passes: Sequence[Mapping[str, Any]],
                          proof_sha256: Any, *, review_call: str = "") -> dict[str, Any]:
    """一叠 pending 台账的尾部连续票数 / 是不是同一份正文（纯读；p284）。

    ## 为什么这一格必须存在（根因）

    p283 把"已认领给本命题"的 pending 行读成 `pending=False / claimed=True`，好让
    `allow_pending=False` 的收录路认它 —— 但 `_gap_from_pending` 的 `ok` 原先只问
    `row_signable`（行局部），并在注释里写"连续闸在这一档不适用"。那句在 p283 之前
    成立（未认领的 pending 只够过准入闸、从不抬 kind），p283 之后就不成立了：
    同一份凭据现在真的会被当作升档依据 ⇒ 一票就能把 conjecture 抬成 theorem
    （2026-11-11 全量：`test_mapping_shows_ledger_kind_and_signature` 三条红）。
    台账那一路从来不是"有一行成立就发签"：`signs_bit3` 要 `SIGN_STREAK_NEED` 票、
    且这几票签的是同一份正文（`_hold_run_lengths` 在 sha 变化处清零）。这一格就是
    把那同一道闸搬到 pending 这一支上 —— 计数实现仍只有 :func:`_hold_run_lengths`
    一处（不新造第二套"怎么数"）。

    ## 返回

    `checked`（这一格读成了）/ `votes`（尾部连续成立几票）/ `need` / `same_sha`
    （最新一票的 `proof_sha256` 是不是本条命题正文的 sha）/ `ok`（够不够当定理凭据
    = `same_sha and votes >= need`）/ `tail_sha`。`votes=0` 是"读到了、一票没有"，
    与"没查成"（`checked=False`）不同 —— 不过 pending 这一支的行是刚读出来的，
    坏行在读 `pending` 台账时已经由调用方抛成"没查成"。
    """
    rows = [dict(r) for r in (passes or ()) if isinstance(r, Mapping)]
    want_sha = str(proof_sha256 or "").strip().lower()
    #: `review_call` 是"这一票数的是哪一趟送审"（R10FIX-D2）：`pending_sign` 在"尾行不是
    #: 结论"时会改认已发签锚在的那一行，票数就必须按那一行所在的送审数 —— 否则 3/3
    #: 签会被它之后一笔没判完的送审（`review_pass=2`、缺 1/3）数成 0 票。
    #: 缺省 = 尾行那一趟（改前逐字不变）。`tail_sha` 仍取台账尾部那一行：它回答
    #: "最新一票签的是不是本条正文"（三票不同 sha 那一档靠它，不靠数出来的那一组）。
    tail_sha = str(rows[-1].get("proof_sha256") or "").strip().lower() if rows else ""
    same_sha = bool(tail_sha) and bool(want_sha) and tail_sha == want_sha
    need = int(verifications.SIGN_STREAK_NEED)
    # ---- K7（2026-11-18）：与服务端签发同一把尺 ---------------------------------
    #
    # 改前这里 `_hold_run_lengths(rows)` 数的是"同一份正文的全部历史行"—— 跨多少趟
    # 送审都攒在一起。而签发那条路（`vsigns.issue` → `sign_counting.count_ledger_file`）
    # 只认同一个 `review_call` 内 `review_pass=1..need` 的那几行（老行才退回
    # `legacy_tail`）。两把尺的后果很具体：lp-ball-8 的 pending 台账里 a1741 那份
    # 正文有 7 行 clean，分别来自 7 趟送审、每趟 `review_pass=1` —— 旧尺数成 7/3、
    # 直接抬档，签发那一路数成 1/3、根本不发。现在这里也委托同一份实现：
    # 有 `review_call` ⇒ `sign_counting.count_rows`；没有 ⇒ `legacy_tail`（历史形态，
    # 与签发那条路的兼容门逐字同义）。
    from . import sign_counting as _SC

    tail_call = (str(review_call or "").strip()
                 or (str(rows[-1].get("review_call") or "").strip() if rows else ""))
    if tail_call:
        counted = _SC.count_rows(rows, review_call=tail_call,
                                 proof_sha256=want_sha, need=need)
    else:
        counted = _SC.legacy_tail(rows, proof_sha256=want_sha, need=need)
    votes = int(counted.get("count") or 0)
    return {
        "checked": True, "votes": votes, "need": need, "tail_sha": tail_sha,
        "same_sha": bool(same_sha), "ok": bool(same_sha and counted.get("ok")),
        "review_call": tail_call, "counted_by": str(counted.get("counted_by") or ""),
        "terminated": str(counted.get("terminated") or ""),
    }


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    PENDING_DIR_NAME,
    VERIFICATIONS_DIR,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    _sign_sha,
    proof_no_of,
    verifications_dir,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    row_signable,
)
