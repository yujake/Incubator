"""收工自动提交的读那一半。

按「读 / 写」两条边界拆：本模块是读那一半 —— `mss:` 记号的拼与解（`submission_token` /
`parse_submission` / `submissions_of`）＋ 本工作区里 F 的稿 × V 的颁发表 ⇒ 每个稿号
「该不该提交」的读数（`submission_candidates`，纯读：不碰 store、不写盘）；
`agent_f/autosubmit.py` 是写那一半 —— 收工那一趟选谁、事务里 append
`tasks.artifacts`。

公开面只增不改：`delivery.py` 在顶层回引本模块的公开名，`step.py` 与
`agent_d/write_report.py` 照旧按 `delivery.<name>` 取用（monkeypatch 面因此不变）。
判据：`tests/test_f_auto_submits_signed_manuscripts.py`。

## 稿的身份 = (族, 稿号)（2026-11-16，与 `manuscriptclosing` / 携带单对齐）

四族各有自己的号段、都从 `000000` 起（`manuscriptids` 的四条计数器）⇒ 同一号跨族
在真机上是常态（`projects/lp-ball` 的 000000 被 b-proof + e-num + f-proof 三族共用）。
`mss:` 记号因此写 `mss:<族>-<号>`（`mss:e-num-000000`），族名与
`manuscriptfamily.FAMILY_ORDER` 逐字相同、形状与 `refvocab` / `depsection` 的
`mss:<family>-<id>` 是同一个东西 —— 三处不各造一份写法。

老记号 `mss:<号>`（2026-11-16 之前写的）仍读：族由记号自己的 `path=` 载体路径补；
补不上就交给读侧按唯一性裁定（:func:`resolve_submission` 的三态 —— 同号跨族 ⇒ 不猜）。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .. import manuscriptfamily as _MFAM


# ============================================================ 收工自动提交
#
# 三个前提，这一节按它排：
#
# 1. 事实来源是 V 的颁发表，不是新表（「维护拿签稿的稿号表可以和 V 自动维护的颁发出
#    V 签的表进行复用」）⇒ 本模块只读 `out/vsigns/<正文sha>.json`（逐份签 = 证据；
#    `issued.json` 是派生归档，不拿它下结论），不落任何新账；
# 2. 「已提交」的持久记号只有一处：F 自己的 `tasks.artifacts`（框架写、append-only）。
#    判据是「里面有没有这个稿号」，与版本无关；
# 3. 一个稿号 = 一份文件（「一个稿号就相当于是该稿的文件名，不再细分 version 几」）⇒
#    提交时看的就是该稿号当前那一份文件；签的 sha 与当前正文 sha 不一致 ⇒ 不提交、
#    如实报，不替它挑「哪一版」。

#: F 的稿族（`vsigns.parse_manuscript_name` 的 `family` 格；只认这一族）。
FAMILY_F = "f-proof"

#: 「已提交」记号的前缀（`tasks.artifacts` 里的一项，形态沿用 `table:id` 那一套）。
SUBMISSION_PREFIX = "mss:"

#: 「这不是一次提交、是一条来源记录」的那一档 `kind=` 取值（2026-11-13 业主裁定）。
#:
#: `B.open_polish_copy` 复制出一份优化副本时，会往自己那一行 `tasks.artifacts` 记
#: `mss:<新稿号>#kind=polish#source=<源稿号>#path=<副本>#at=<时刻>`：它答的是
#: 「这份 b-稿是从哪份已签稿复制来的」（事实），不是「这份稿被提交了」。
#: 两者同族（都是 `mss:` 记号、同一张表），但读侧必须分得开：`submissions_of`
#: 跳过这一档（否则优化副本会被读成"已提交"）。
POLISH_SOURCE_KIND = "polish"

#: 记号的字段分隔符（路径、sha 与 ISO 时刻都不含 `#`）。
SUBMISSION_SEP = "#"

#: 记号里字段的固定顺序（读侧按 `key=value` 取，顺序只影响可读性）。
#:
#: 2026-11-11 业主裁定：「proof_no 确实该退役……手稿产出侧和 V 签侧甚至呈递侧可退役，
#: 台账不能退役」⇒ 新写的记号不再有 `proof_no` 这一格（一个稿号 = 一份文件）。
#: 老记号里已有的 `proof_no=` 仍读得出（`parse_submission` 的字段表照收），只是不再
#: 由这一侧写出来 —— 读能力不删，新写不产生。
SUBMISSION_FIELDS: tuple[str, ...] = (
    "path", "body_sha", "sign_sha", "file_sha",
    "statement_id", "at", "submitted_at", "via",
)

#: `via` 的取值（2026-11-11 甲：签触发 / 收工触发必须分得开）。
#:
#: 同一份记号格式（`mss:`），只多一格 `via=` —— 读侧（`manuscriptsubmission.
#: submission_reading`）按它回答「这一份是签那一刻置的，还是收工扫到的」。
#: 老记号没有这一格 ⇒ 读侧按产出方族回落（F/E ⇒ 收工、B ⇒ 收录），不是「没提交」。
VIA_SIGN = "sign_issued"
VIA_CLOSING = "closing_auto_submit"


# ============================================================ 稿的身份：(族, 稿号)
#
# 四族（`manuscriptfamily.FAMILY_ORDER`）各有自己的号段、都从 `000000` 起 ⇒ 同一号
# 跨族是常态，单号做身份会把两族的稿折成一份。这里的三个纯函数是 `mss:` 记号那一侧
# 的身份读法：记号头怎么拆、字典键怎么拼、从读数里按 (族, 号) 取哪一枚。
def _family_of_carrier(rel: Any) -> str:
    """载体路径 ⇒ 族（`reports/e-num-000000.md` ⇒ `e-num`）；认不出 ⇒ 空串（不猜）。

    老记号 `mss:<号>` 没有族那一格，族只能从它的 `path=` 读出来。名字不是手稿形
    （`notes/foo.md`）或根本没有 `path=` ⇒ 空串 —— 那时"族唯一确定"不成立。
    """
    got = _MFAM.classify_manuscript(str(rel or ""))
    return str(got.get("name_family") or "")


def submission_identity(raw: Any) -> tuple[str, str]:
    """`mss:` 头（前缀之后那一段）⇒ `(族, 稿号)`；没写族 ⇒ `("", 原文)`。

    `e-num-000000` ⇒ `("e-num", "000000")`；`f-proof-plan-42` ⇒
    `("f-proof", "plan-42")`；`000000` ⇒ `("", "000000")`。前缀逐个从
    `manuscriptfamily` 的族表取（唯一真身），四族前缀互不为前缀 ⇒ 拆分无歧义，
    不需要第二条正则（与 `depsection._mss_split` 同一口径）。
    """
    text = str(raw or "").strip()
    for family in _MFAM.FAMILY_ORDER:
        prefix = _MFAM.prefix_of(family)
        if prefix and text.startswith(prefix):
            return family, text[len(prefix):].strip()
    return "", text


def submission_key(family: Any, manuscript_id: Any) -> str:
    """身份 ⇒ 带族键 `<族>:<稿号>`；族认不出 ⇒ 裸 `<稿号>`。

    这是 `submissions_of` 在"同号跨族"时用的键。单族时它仍退回裸号（见
    :func:`submissions_of`）：改前的读侧（`agent_f/autosubmit.py` 的
    `mid in submitted`、`parse_submission(token)["manuscript_id"] not in existing`）
    因此逐字不变 —— 那条读侧不在本批的改动面里。
    """
    fam = str(family or "").strip()
    mid = str(manuscript_id or "").strip()
    return f"{fam}:{mid}" if fam and mid else mid


def resolve_submission(records: Any, *, family: Any = "", manuscript_id: Any = "",
                       families: Any = ()) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """从 `submissions_of` 的读数里按 (族, 稿号) 取一枚记号 ⇒ `(记号, 读数)`；三态，绝不猜。

    | 情形 | `reading["state"]` | 返回的记号 |
    |---|---|---|
    | 身份精确命中（带族键；单族时沿用裸号键） | `hit` | 那一枚 |
    | 只有老记号、族由载体路径 / 调用点上下文唯一确定 | `legacy_hit` | 那一枚 |
    | 老记号而该号跨族出现（族定不下来） | `ambiguous` | `None` |
    | 没有这一份的记号 | `absent` | `None` |

    `family=""` 是"调用方只知道稿号"：这时按读数里出现过的族唯一性裁定（只有一族 ⇒
    用它；两族以上 ⇒ `ambiguous`）。`families` 是调用点已知的"这一号在盘上 / 候选里
    出现在哪几族"（`submission_reading` 扫 `reports/`、E 收工用候选清单）—— 老记号
    没有族时，它让"这枚记号属于哪一族"有据可判；多于一族就不猜。

    读数的 `why` 逐字点名「跨族同号」（`ambiguous` 那一档），调用方原样往上带。
    """
    records = records if isinstance(records, Mapping) else {}
    mid = str(manuscript_id or "").strip()
    fam = str(family or "").strip()
    reading: dict[str, Any] = {
        "state": "", "why": "", "family": fam, "manuscript_id": mid,
        "key": "", "keys": [], "families": [],
    }
    if not mid:
        reading.update(state="absent", why="没有稿号 ⇒ 没有可判的提交记号")
        return None, reading
    #: 这一号在读数里出现过的族（每条记号自己带 `families` 那一格）。
    seen: set[str] = set()
    for rec in records.values():
        if not isinstance(rec, Mapping) or str(rec.get("manuscript_id") or "") != mid:
            continue
        seen.update(str(x) for x in (rec.get("families") or ()) if str(x))
        if str(rec.get("family") or ""):
            seen.add(str(rec.get("family") or ""))
    seen.update(str(x) for x in (families or ()) if str(x))
    reading["families"] = sorted(seen)

    def _ambiguous(keys: list[str], why: str) -> tuple[None, dict[str, Any]]:
        return None, {**reading, "state": "ambiguous", "keys": keys,
                      "why": (f"{why}（跨族同号、无法唯一定位：稿号 {mid} 出现在 "
                              + "、".join(reading["families"])
                              + "）⇒ 不猜是哪一份；要读哪一族就给稿路径或带族记号")}

    # 1) 身份精确命中（带族键）。键就是身份 —— 命中即那一份。
    if fam:
        exact = records.get(submission_key(fam, mid))
        if exact is not None and not exact.get("ambiguous"):
            return exact, {**reading, "state": "hit",
                           "key": submission_key(fam, mid),
                           "why": f"按 (族, 稿号) = ({fam}, {mid}) 命中提交记号"}
    # 2) 老记号（单族时 `submissions_of` 沿用裸号键；跨族时族认不出的那几条也落在这里）
    bare = records.get(mid)
    if bare is not None:
        if bare.get("ambiguous"):
            keys = [str(x) for x in (bare.get("tokens") or ()) if str(x)]
            return _ambiguous(keys, "这一号的老记号不止一条、而族定不下来")
        bare_fam = str(bare.get("family") or "")
        if bare_fam and fam and bare_fam != fam:
            # 那一枚明确是另一族的稿 ⇒ 这一族没有提交记号（不是"没查成"）。
            return None, {**reading, "state": "absent",
                          "why": (f"`tasks.artifacts` 里稿号 {mid} 的提交记号属于 "
                                  f"{bare_fam}，不是 {fam} ⇒ 这一族没有提交记号")}
        if bare_fam:
            return bare, {**reading, "state": "hit", "key": mid,
                          "why": f"老记号的族由载体路径确定为 {bare_fam}（稿号 {mid}）"}
        # 族真的没写：由调用点上下文 / 读数里出现过的族唯一性裁定。
        if fam:
            other = seen - {fam}
            if other:
                return _ambiguous(
                    [str(bare.get("token") or "")],
                    "这一号的老记号没写族、而它落在跨族同号的号段上")
            return bare, {**reading, "state": "legacy_hit", "key": mid,
                          "why": (f"老记号 `mss:{mid}` 没有族；这一号只在 {fam} 出现 ⇒ "
                                  "族唯一确定，按它读")}
        if len(seen) > 1:
            return _ambiguous([str(bare.get("token") or "")],
                              "这一号的老记号没写族、而它在多族出现")
        if len(seen) == 1:
            only = next(iter(seen))
            return bare, {**reading, "state": "legacy_hit", "key": mid,
                          "why": (f"老记号 `mss:{mid}` 没有族；这一号只在 {only} 出现 ⇒ "
                                  "族唯一确定，按它读")}
        return bare, {**reading, "state": "legacy_hit", "key": mid,
                      "why": (f"老记号 `mss:{mid}` 没有族；读数里只有这一条、"
                              "也没有别的族可对照 ⇒ 按它读（族留空）")}
    # 3) 只有带族键（跨族形态下 `submissions_of` 不给裸号键）。
    if not fam:
        if len(seen) > 1:
            return _ambiguous([], "只给了稿号、而这一号在多族都有提交记号")
        if len(seen) == 1:
            one_key = submission_key(next(iter(seen)), mid)
            rec = records.get(one_key)
            if rec is not None and not rec.get("ambiguous"):
                return rec, {**reading, "state": "hit", "key": one_key,
                             "why": f"稿号 {mid} 只在一族（{next(iter(seen))}）有提交记号"}
    return None, {**reading, "state": "absent",
                  "why": (f"`tasks.artifacts` 里没有稿号 {mid} 在"
                          + (f" {fam} " if fam else "任何族 ")
                          + "的提交记号 ⇒ 未提交")}


def _proof_no_of(raw: Any) -> int:
    """证明号归一：认不出 / <1 ⇒ 1（与 `vsigns` 的缺省 `#p1` 同一口径）。

    只给老记号的读侧兼容用（`parse_submission`）；新写的记号不带这一格。
    """
    try:
        no = int(raw or 1)
    except (TypeError, ValueError):
        return 1
    return no if no >= 1 else 1


def submission_token(*, manuscript_id: Any, family: Any = "", path: Any = "",
                     body_sha: Any = "",
                     sign_sha: Any = "", file_sha: Any = "", proof_no: Any = 1,
                     statement_id: Any = "", at: Any = "",
                     submitted_at: Any = "", via: Any = "") -> str:
    """一份「已提交」记号（`tasks.artifacts` 里的一项）。

    头写 `mss:<族>-<号>`（`mss:e-num-000000`）：四族各有自己的号段、都从 `000000`
    起 ⇒ 单号做身份会把两族的稿折成一份。族名取 `manuscriptfamily.FAMILY_ORDER`
    那一套（与 `refvocab` / 携带单同一形）。`family` 没给或认不出时退到载体的
    路径族（`path=reports/e-num-000000.md` ⇒ `e-num`）；两条都认不出才写老形
    `mss:<号>` —— 读侧仍认老形，但新写一律带族（只要族认得出来）。

    为什么要一格带四样东西（稿号 + 正文 sha + 签 sha + 文件字节 sha + 时刻）：
    D 的携带单要按「地址 + 文件字节 sha256」递稿、B 要按正文 sha 认签，而
    「提交时是哪一版」必须能自证 —— 只留一个稿号，事后没人能判「盘上这份是不是
    当初提交的那一份」。

    `body_sha` 是 V 签盖的那段正文的 sha（`artifact_sha`，全仓同一把尺）；
    `sign_sha` 是签文件（`out/vsigns/<body_sha>.json`）的字节 sha256 —— 它回答
    「凭的是哪一份签」；`file_sha` 是盘上那份 `.md` 的字节 sha256（D/B 认地址用）。

    `proof_no` 形参保留只为旧调用点不必改签名：新记号不写它（业主 2026-11-11，
    一稿一份之后它不携带任何身份）。老记号里已有的那一格仍可读
    （`parse_submission` 的字段表里留着它）。
    """
    mid = str(manuscript_id or "").strip()
    if not mid:
        raise ValueError(
            "提交记号必须有稿号（`mss:<族>-<号>` / 老形 `mss:<号>`）—— 没有稿号就没有可判的对象")
    values = {
        "path": str(path or "").strip().replace("\\", "/"),
        "body_sha": str(body_sha or "").strip().lower(),
        "sign_sha": str(sign_sha or "").strip().lower(),
        "file_sha": str(file_sha or "").strip().lower(),
        "statement_id": str(statement_id or "").strip(),
        "at": str(at or "").strip(),
        "submitted_at": str(submitted_at or "").strip(),
        # `via`：这一枚记号是谁置的（`sign_issued` / `closing_auto_submit` /
        # `ingested_to_ledger`）。空串 = 老调用点没给，按产出方族回落。
        "via": str(via or "").strip(),
    }
    # 族：认得的才写进键。未知族不写（`mss:F-000000` 读回来会被当成一个假稿号），
    # 退到载体的路径族；载体也认不出 ⇒ 老形（读侧仍认）。
    fam = str(family or "").strip()
    if fam not in _MFAM.FAMILY_ORDER:
        fam = ""
    if not fam:
        fam = _family_of_carrier(values["path"])
    head = f"{SUBMISSION_PREFIX}{fam}-{mid}" if fam else f"{SUBMISSION_PREFIX}{mid}"
    parts = [head]
    for key in SUBMISSION_FIELDS:
        if values[key]:
            parts.append(f"{key}={values[key]}")
    return SUBMISSION_SEP.join(parts)


def parse_submission(token: Any) -> dict[str, Any] | None:
    """一条记号 ⇒ 结构（不是 `mss:` 前缀 ⇒ `None`；坏格静默缺省，不猜值）。

    头拆成 `(族, 稿号)`：`mss:e-num-000000` ⇒ `family="e-num"`；老形
    `mss:000000` ⇒ `family=""`（族留给读侧按唯一性裁定）。`carrier_family` 是从
    记号自己的 `path=` 读出来的族 —— 两者都在时它们必须一致（否则就是把另一族的稿
    读成这一份，`submissions_of` 会点名跳过）。
    """
    text = str(token or "").strip()
    if not text.startswith(SUBMISSION_PREFIX):
        return None
    chunks = text.split(SUBMISSION_SEP)
    family, mid = submission_identity(chunks[0][len(SUBMISSION_PREFIX):])
    if not mid:
        return None
    out: dict[str, Any] = {
        "manuscript_id": mid, "token": text, "path": "", "body_sha": "",
        "sign_sha": "", "file_sha": "", "proof_no": 0, "statement_id": "",
        "at": "", "submitted_at": "", "via": "",
        # `kind`：本模块写出的提交记号不带这一格；`kind=polish` 是
        # `B.open_polish_copy` 的来源记录（同族、不同义，`submissions_of` 跳过它）。
        "kind": "",
        # 族：头里那一格是权威；老形没有（空串）。`carrier_family` 是 `path=` 的族。
        "family": "", "carrier_family": "",
    }
    for chunk in chunks[1:]:
        key, sep, value = chunk.partition("=")
        if sep and key in out:
            out[key] = value
    # 族只认头那一格：`#family=` 不是记号格式的一部分（坏格静默缺省，不猜值）。
    out["family"] = family
    out["carrier_family"] = _family_of_carrier(out.get("path"))
    # 老记号可能有 `proof_no=`（2026-11-11 之前写的）：照读，缺省按 canonical 1。
    # 新记号不再写这一格 —— "新写不产生"不等于"读侧删掉"。
    out["proof_no"] = _proof_no_of(out.get("proof_no"))
    return out


def submissions_of(artifacts: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """`tasks.artifacts` ⇒ `({身份键: 记号结构}, 问题)`。

    ## 键是稿的身份，不是单号（2026-11-16）

    - 一个号只出现在一族 ⇒ 沿用老键 `<稿号>`（改前的读侧因此逐字不变）；
    - 同一个号出现在两族以上 ⇒ 每族各一个键 `<族>:<稿号>` —— 两枚记号不再折成一行
      （改前 `setdefault(mid)` 让 `e-proof-000000` 的读数带着 `e-num-000000` 的
      path/via）；
    - 老记号（`mss:<号>`）的族由它自己的 `path=` 载体路径补上；补不上就仍是裸号键，
      由 :func:`resolve_submission` 按唯一性裁定（跨族同号 ⇒ 不猜）。

    同一个身份出现多条时保留最先读到的那一条（提交是 append-only；后来的重复不是
    第二次提交）—— 改前语义。但族定不下来的裸号键上出现两条不同记号 ⇒ 不挑一条
    （`ambiguous=True`，`resolve_submission` 因此回 `ambiguous`），否则就是
    "在两条不知道属于谁的记号里猜一条"。

    问题只收「长得像 `mss:` 却读不出稿号」与「键里的族与载体族对不上」的那些 ——
    别的 `artifacts` 项（路径、`file:` / 表行引用）不是这一格的事，不当问题。
    """
    parsed: list[dict[str, Any]] = []
    problems: list[str] = []
    for token in artifacts or ():
        text = str(token or "").strip()
        if not text.startswith(SUBMISSION_PREFIX):
            continue
        rec = parse_submission(text)
        if rec is None:
            problems.append(
                f"`{text}` 不是一条可读的提交记号（`mss:<族>-<号>` 或老形 `mss:<号>`）⇒ 跳过")
            continue
        # 来源记录不是提交：`B.open_polish_copy` 写的 `kind=polish` 那一档答的是
        # "这份副本是从哪份已签稿复制来的"（事实）。把它当提交会让优化副本一出生
        # 就被读成"已提交"（`submission_reading.state`），而它明明还没送审。
        if str(rec.get("kind") or "") == POLISH_SOURCE_KIND:
            continue
        declared = str(rec.get("family") or "")
        carrier = str(rec.get("carrier_family") or "")
        if declared and carrier and declared != carrier:
            # 键说这一份是甲族、载体却是乙族的稿 ⇒ 读下去就是把乙族的稿当成甲族那份。
            problems.append(
                f"`{text}` 的族对不上：键写的是 {declared}，而载体 {rec.get('path')!r} 是 "
                f"{carrier} 的稿 ⇒ 跳过（不把另一族的稿读成这一份）")
            continue
        # 族：头里写的优先，没有就用载体路径补（老记号那一档）。
        rec["family"] = declared or carrier
        parsed.append(rec)
    #: 号 ⇒ 这一号在读数里出现过的族（跨族同号的证据；`resolve_submission` 读它）。
    fams_by_mid: dict[str, set[str]] = {}
    #: 号 ⇒ 这一号有没有"族认不出"的记号（老形 / 没带 path）。有它时带族的记号必须
    #: 用带族键，否则会被那条裸号键压在同一个键上、谁先读到谁留下 —— 那就把一枚
    #: 明确的记号读丢了。此时裸号键仍留给那条族认不出的记号（读侧按唯一性裁定）。
    unknown_mids: set[str] = set()
    for rec in parsed:
        rec_mid = str(rec["manuscript_id"])
        rec_fam = str(rec.get("family") or "")
        if rec_fam:
            fams_by_mid.setdefault(rec_mid, set()).add(rec_fam)
        else:
            unknown_mids.add(rec_mid)
    out: dict[str, dict[str, Any]] = {}
    for rec in parsed:
        mid = str(rec["manuscript_id"])
        rec_fam = str(rec.get("family") or "")
        fams = sorted(fams_by_mid.get(mid, set()))
        rec["families"] = fams
        # 单族且没有族认不出的记号 ⇒ 沿用老键（改前读侧逐字不变）；两族以上、或同号
        # 还有一条族认不出的记号 ⇒ 带族键（两族同号 / 明暗两种写法都不再折成一行）。
        if rec_fam and (len(fams) > 1 or mid in unknown_mids):
            key = submission_key(rec_fam, mid)
        else:
            key = mid
        rec["key"] = key
        prev = out.get(key)
        if prev is None:
            out[key] = rec
            continue
        if str(prev.get("token") or "") == str(rec.get("token") or ""):
            continue
        if prev.get("ambiguous"):
            continue
        if not rec_fam and not str(prev.get("family") or ""):
            # 两条不同记号都只有裸号、族真的定不下来 ⇒ 不许挑一条（跨族同号）。
            out[key] = {
                "manuscript_id": mid, "family": "", "families": fams, "key": key,
                "token": "", "path": "", "ambiguous": True,
                "tokens": [str(prev.get("token") or ""), str(rec.get("token") or "")],
                "why": (f"稿号 {mid} 的提交记号不止一条、而族定不下来（跨族同号）⇒ "
                        "不猜是哪一条"),
            }
    return out, problems


def submission_candidates(root: Any) -> dict[str, Any]:
    """本工作区里 F 名下的稿 × V 的颁发表 ⇒ 每个稿号「该不该提交」的读数（纯读）。

    ## 事实来源（业主 2026-11-11 裁定 ②：复用 V 的颁发表）

    - 签：`out/vsigns/<正文sha>.json`（逐份）—— 用 `vsigns.credential_reading`
      读并复算（文件在不算签：复算不过就不是签）；`issued.json` 只是派生归档，不拿它下结论；
    - 稿：签文件自己写下的 `artifact_path` + `reports/` 下 F 族前缀的 `*.md`（前缀从
      `manuscriptfamily` 派生，不在这里再写一份；还没签的稿也要能读成「未签 ⇒ 不入提交单」）。

    ## 判据（业主 2026-11-11 追加裁定：一个稿号 = 一份文件）

    - `signed=True` 只在签的 `artifact_sha` == 该文件当前正文 sha、且签复算通过时；
    - 签过、之后正文又改了（两个 sha 不一致）⇒ `state="body_changed_after_sign"`，
      不提交，读数点名两个 sha；
    - 同一个稿号指到两份不同的文件 ⇒ `state="ambiguous_path"`，不提交（这里不替它
      挑「哪一版」：一稿号一文件是业主口径，挑本身就把那条纪律放过了）；
    - 没有签的稿 ⇒ `state="unsigned"`，`why` 逐字说「未签 ⇒ 不入提交单」。

    返回 `{checked, candidates, problems, why}`；`checked=False` = 颁发表/目录列不出来
    （「没查成」，不是「一份都没签」）。
    """
    import hashlib
    from pathlib import Path

    from .. import manuscriptfamily as _MFAM
    from .. import proofregistry as _PR
    from .. import vsigns as _VS

    out: dict[str, Any] = {"checked": True, "candidates": [], "problems": [], "why": ""}
    root_p = Path(str(root or "."))
    d = _VS.signs_dir(root)
    try:
        files = (sorted(p for p in d.glob("*.json") if p.name != _VS.INDEX_NAME)
                 if d.is_dir() else [])
    except OSError as exc:  # noqa: BLE001 —— 列不出来 = 没查成
        out.update(checked=False, why=(
            f"`{_VS.SIGNS_DIR}/` 列不出来（{type(exc).__name__}: {exc}）⇒ "
            "拿签稿这一格没查成（不是「一份都没签」）"))
        return out
    #: 稿号 ⇒ 这一号的签与文件（同号多条目在这里聚，最后一并判「一稿号一文件」）。
    by_mid: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def _bucket(mid: str) -> dict[str, Any]:
        one = by_mid.get(mid)
        if one is None:
            one = {"manuscript_id": mid, "paths": [], "signs": [],
                   "statement_id": "", "at": ""}
            by_mid[mid] = one
            order.append(mid)
        return one

    for path in files:
        cred = _VS.credential_reading(root, path.stem)
        doc = dict(cred.get("sign") or {})
        if not doc:
            out["problems"].append(
                f"{path.name}：签读不出来（{cred.get('why') or '没有理由'}）"
                " ⇒ 这一份这次不提交（没查成，不是「没签」）")
            continue
        if not cred.get("checked"):
            # 签文件读到了、台账读不出来：仍进表（候选会落 `sign_unbacked`），
            # 这样「有签却这次没提交」有一句可读的理由，不是静默消失。
            out["problems"].append(
                f"{path.name}：签的复算没查成（{cred.get('why') or '没有理由'}）"
                " ⇒ 这一份这次不提交（没查成，不是「没签」）")
        rel = str(doc.get("artifact_path") or "").strip().replace("\\", "/")
        parsed = _VS.parse_manuscript_name(rel)
        if str(parsed.get("family") or "") != FAMILY_F:
            continue
        mid = str(parsed.get("manuscript_id") or "")
        if not mid:
            out["problems"].append(
                f"{path.name}：签的载体 {rel!r} 认不出 F 的稿号 ⇒ 不提交（不猜一个号）")
            continue
        try:
            sign_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:  # noqa: BLE001 —— 读不出来仍进表（只是没有签 sha）
            sign_sha = ""
            out["problems"].append(
                f"{path.name}：签文件读不出来（{type(exc).__name__}: {exc}）")
        one = _bucket(mid)
        if rel and rel not in one["paths"]:
            one["paths"].append(rel)
        one["signs"].append({
            "signed_sha": str(cred.get("artifact_sha") or path.stem).strip().lower(),
            "at": str(doc.get("at") or ""),
            "sign_file": _VS.rel(path, root),
            "sign_sha": sign_sha,
            "recomputable": bool(cred.get("recomputable")),
            "code": str(cred.get("problem") or ""),
            "why": str(cred.get("why") or ""),
        })
        if not one["statement_id"]:
            one["statement_id"] = str(doc.get("statement_id") or "").strip()
        if str(doc.get("at") or "") > str(one["at"] or ""):
            one["at"] = str(doc.get("at") or "")
    # ---- 还没签的稿也要点名（判据 c：「未签 ⇒ 不入提交单」必须读得到）----
    # 前缀从 `manuscriptfamily` 派生（唯一真身）：本文件不再写 `f-proof-` 这个字面量。
    reports = root_p / _VS.SIGN_CARRIER_DIR
    try:
        report_paths = (sorted(reports.glob(f"{_MFAM.prefix_of(FAMILY_F)}*.md"))
                        if reports.is_dir() else [])
    except OSError as exc:  # noqa: BLE001 —— 列不出来 = 这一半没查成
        report_paths = []
        out["problems"].append(
            f"`{_VS.SIGN_CARRIER_DIR}/` 列不出来（{type(exc).__name__}: {exc}）"
            " ⇒ 未签的稿这一半没查成")
    for path in report_paths:
        rel = _VS.rel(path, root)
        parsed = _VS.parse_manuscript_name(rel)
        if str(parsed.get("family") or "") != FAMILY_F:
            continue
        mid = str(parsed.get("manuscript_id") or "")
        if not mid:
            continue
        one = _bucket(mid)
        if rel not in one["paths"]:
            one["paths"].append(rel)
    # ---- 每个稿号收成一格读数 ----
    for mid in order:
        one = by_mid[mid]
        paths = [str(x) for x in (one.get("paths") or []) if str(x)]
        signs = [dict(x) for x in (one.get("signs") or [])]
        cand: dict[str, Any] = {
            # 稿的身份 = (族, 稿号)：这一份只认 F 族（本函数只扫 F 的签），
            # 写侧（`agent_f/autosubmit.py`）与读侧都按这一格拼记号 / 查已提交。
            "family": FAMILY_F,
            "manuscript_id": mid,
            "manuscript": paths[0] if paths else "",
            "statement_id": str(one.get("statement_id") or ""),
            "signed_sha": "", "sign_sha": "", "at": str(one.get("at") or ""),
            "current_sha": "", "file_sha": "",
            "signed": False, "state": "", "why": "",
            "signs": [{"signed_sha": s["signed_sha"], "at": s["at"],
                       "sign_file": s["sign_file"]} for s in signs],
        }
        if len(paths) > 1:
            cand.update(state="ambiguous_path", why=(
                "同一个稿号指到多份不同的文件（" + "、".join(paths) + "）⇒ "
                "一稿号一文件（业主 2026-11-11），这一份不提交 —— "
                "这里不替它挑「哪一版」"))
            out["candidates"].append(cand)
            continue
        rel = cand["manuscript"]
        if not rel:
            cand.update(state="manuscript_missing", why=(
                "颁发表里这一份签没有 `artifact_path` ⇒ 没有地址可提交"))
            out["candidates"].append(cand)
            continue
        try:
            blob = (root_p / rel).read_bytes()
        except OSError as exc:
            cand.update(state="manuscript_missing", why=(
                f"签的载体 `{rel}` 读不出来（{type(exc).__name__}: {exc}）"
                " ⇒ 不提交（没有可交的文件）"))
            out["candidates"].append(cand)
            continue
        cand["file_sha"] = hashlib.sha256(blob).hexdigest()
        try:
            text = blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            cand.update(state="manuscript_unreadable", why=(
                f"签的载体 `{rel}` 不是 UTF-8 文本（{exc}）⇒ 不提交"))
            out["candidates"].append(cand)
            continue
        cand["current_sha"] = _PR.proof_sha(text)
        matching = [s for s in signs if s["signed_sha"] == cand["current_sha"]]
        if matching:
            hit = matching[0]
            cand.update(signed_sha=hit["signed_sha"], sign_sha=hit["sign_sha"],
                        at=str(hit["at"] or cand["at"]))
            if hit["recomputable"]:
                cand.update(signed=True, state="signed", why=(
                    f"已拿签（签 sha={hit['signed_sha']}，与现行正文一致）⇒ 可提交"))
            else:
                cand.update(state="sign_unbacked", why=(
                    f"签文件在、sha 也与现行正文一致（{hit['signed_sha']}），但复算不上"
                    f"（{hit['code'] or '?'}）：{hit['why']} ⇒ 不提交"
                    "（这也是一条签，只是签不住）"))
        elif signs:
            latest = max(signs, key=lambda s: str(s.get("at") or ""))
            cand.update(signed_sha=latest["signed_sha"], sign_sha=latest["sign_sha"],
                        at=str(latest["at"] or ""), state="body_changed_after_sign",
                        why=(
                            f"这一份签过之后正文又变了（签 sha={latest['signed_sha']} / "
                            f"现在 sha={cand['current_sha']}）⇒ 按只读/冻结纪律这不该发生，"
                            "不提交（不是「取哪一版」）"))
        else:
            cand.update(state="unsigned", why=(
                "未签 ⇒ 不入提交单（V 的颁发表里没有这一份现行的签）"))
        out["candidates"].append(cand)
    out["why"] = (f"颁发表里 {len(files)} 份签、盘上 {len(report_paths)} 份 F 的稿 ⇒ "
                  f"{len(out['candidates'])} 个稿号"
                  + (f"；{len(out['problems'])} 条读数问题" if out["problems"] else ""))
    return out
