# -*- coding: utf-8 -*-
"""台账路径 + 证明号/哈希/判词解析。

2026-11-20（VERSPLIT2）：`v_paths.py` 是从 `verifications.py` 搬出的 17 块 / 385 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import manuscriptproducers as _MSUB  # 产出方格（路径族 × V 的父名单）
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）


class VerificationError(ValueError):
    """这次审校没查成（不是"有毛病"）：输出不合法、字段缺、取值不在词表里。"""


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


def _producer_cells(path: Any, *, producer_code: Any = "",
                    roster_role: Any = "") -> dict[str, Any]:
    """验证行上的产出方格（业主 2026-11-11 裁定 ①，甲）。

    事实来源只有手稿路径的族前缀：`manuscriptsubmission.producer_of` 用
    `manuscriptfamily` 现判、并拿 `capabilities.ALLOWED_EDGES` 现算「V 的父名单」
    做校验。`roster_role`（V 的秘书从名册读到的父角色）只作对账 —— 它与路径族
    不一致时记 `producer_problem`，但不改写 `producer_role`。
    """
    got = _MSUB.producer_of(str(path or ""), roster_role=str(roster_role or ""),
                            child_role="V")
    cells: dict[str, Any] = {
        "producer_role": str(got.get("producer_role") or _MSUB.UNKNOWN),
        "producer_code": str(producer_code or ""),
    }
    if str(got.get("problem") or "").strip():
        cells["producer_problem"] = str(got["problem"])
    if got.get("roster_mismatch"):
        cells["producer_problem"] = (
            (str(cells.get("producer_problem") or "") + "；").lstrip("；")
            + "名册里的父角色与路径族不一致（以路径族为准）")
    return cells


def producer_reading(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """读一条验证行的产出方格：老行没有这一格 ⇒ `unknown`（不硬填 F）。"""
    return _MSUB.verification_producer_reading(row)


def verifications_dir(root: str | Path) -> Path:
    """验证台账目录（工作区根下的 `verifications/`；只算路径，不建目录）。"""
    return Path(root) / VERIFICATIONS_DIR


def verification_ledger_path(root: str | Path, statement_id: str) -> Path:
    """一个命题一份台账：`verifications/<命题号>.jsonl`。

    命题号的形态判据只有一处：`schema.is_valid_id`（当前宽度六位，旧数据四位读侧兼容）——
    2026-10-14 之前这里自己写死了"恰好 4 位"，宽度一改就会把新号当场拒掉。
    """
    sid = str(statement_id or "").strip()
    if not S.is_valid_id(sid):
        raise VerificationError(
            f"命题号必须是 {S.ID_DIGITS} 位十进制字符串（旧数据里的 4 位号仍可读），"
            f"收到 {statement_id!r}")
    return verifications_dir(root) / f"{sid}.jsonl"


def _sign_sha(proof_text: Any) -> str:
    """签的对拍尺：转给唯一实现 `proofregistry.proof_sha`（手稿取 `## 证明` 小节）。

    为什么本模块内部不直接写 `proofregistry.proof_sha`：`proofregistry` 在模块顶层
    import 本模块（`from . import verifications as _VR`），顶层再反向 import 会形成
    循环；惰性 import 把这条边断在调用期，语义仍是同一把尺。这一段不是第二把尺：
    本模块自己的原样 sha 在 :func:`text_sha`，两者故意分开命名。
    """
    from . import proofregistry as _PR

    return _PR.proof_sha(proof_text)


def text_sha(proof_text: str) -> str:
    """给定文本的原样 sha256（逐字节，不切小节、不去首尾空行）。

    这一把尺服务的是"V 拿到的这一段，是不是稿里那一段"：整份手稿与它的
    `## 证明` 小节在这里给不同值。签的对拍尺是 `proofregistry.proof_sha`
    （手稿取小节）—— 两个语义故意分开命名，不许合并成一个函数（2026-11-09 T2
    收口的教训：合并之后 `given != body` 那道闸会把整份手稿也算成"同一份"）。

    一段证明正文（没有 `## 证明` 小节）两把尺同值；只有拿整份手稿来比时才分家。
    """
    return hashlib.sha256(str(proof_text or "").encode("utf-8")).hexdigest()


def as_proof_no(value: Any) -> int:
    """把一个证明号归一成正整数（`2` / `"2"` / `"p2"` / `"#p2"` / `"stmt:000004#p2"` 都认）；认不出 ⇒ 0。

    0 表示"这不是一个证明号"。写入口用它把调用方给的 `proof_no` 归一，读侧用它判
    "这一格有没有写证明号"；两处用同一个函数，免得一边认 `p2` 一边不认。
    带 `#pN` 尾巴的写法交给 `proofloc`（全仓拆这个尾巴的唯一解析点，业主 2026-10-22）：
    两份解析意味着"台账上是第 2 条、读出来是第 1 条"这种错没有任何东西会报。
    """
    text = str(value or "").strip()
    # 只带前缀的写法（`"#p2"`）先去掉那颗 `#`：`proofloc` 把"没有命题号的 `#p2`"判成坏尾巴
    # （它是在 `used_by` 上判的，那里确实没有命题号），而本函数的入参允许这种简写。
    if text.startswith("#") and "#" not in text[1:]:
        text = text[1:]
    if "#p" in text:
        from . import proofloc as _PL   # 惰性：`proofloc` 只被这一处与依赖读侧用到

        _head, no, problem = _PL.parse_used_by_checked(text)
        # 坏尾巴（`#p0` / `#p` / `#pabc` / 多段 …）不是"第 1 条证明"：`parse_used_by` 会把它们
        # 静默折成 canonical（它是给"读侧照读"用的），而这里的返回值是给调用方判
        # "这一格到底有没有写证明号"用的 —— 折成 1 会让"这不是一个证明号"读成"这就是 #p1"。
        # 0 是本函数唯一的"不是证明号"取值（调用方一律按 `or 1` 兜底 canonical）。
        return 0 if problem else no
    text = text.lstrip("#").lstrip("pP")
    try:
        got = int(text)
    except (TypeError, ValueError):
        return 0
    return got if got >= 1 else 0


def proof_no_strict(value: Any) -> int:
    """写侧收调用方给的证明号：认不出就抛 `VerificationError`（不静默折成 `#p1`）。

    与 :func:`proof_no_of` 的分界（2026-10-22 审计第 3 条）：`proof_no_of` 是读侧的
    "这一行属于哪一份证明"，拿不到答案就按 canonical 读（读侧折平只会让读数粗，
    不会让某一份证明凭空多一签）；本函数是写侧的"调用方说要签哪一份"，拿不到答案
    必须拒绝 —— 改前两处写口都写 `as_proof_no(x) or 1`，于是 `proof_no=0`
    （"这不是一个证明号"的哨兵）被静默折成 `#p1`：调用方说"签 #p2"，台账上记的是
    `proof_no=1`，而 `verdict=成立` 一个字节不少，两份证明的第 3 位读出来是反的。

    `None` 不是"认不出"，是"没给"（缺省 canonical，见 `proofloc`）。
    调用方要区分"没给参数"与"给了但认不出"，靠的就是传 `None` 与传一个坏值的差别。
    """
    if value is None:
        return DEFAULT_PROOF_NO
    got = as_proof_no(value)
    if got >= 1:
        return got
    raise VerificationError(
        f"证明号认不出：收到 {value!r}（合法写法是 1、2、3 … 或 '2' / 'p2' / '#p2'）"
        "⇒ 拒绝：不落台账、不改任何一位（按 #p1 记会让这一签挂到别的证明头上）")


def proof_no_of(row: Mapping[str, Any]) -> int:
    """这一行（签名行 / 证明清单项 / 任何带证明号的 dict）记的证明号；没写 ⇒ canonical（1）。

    0（"这不是一个证明号"）不出现在返回值里：调用方问的是"这一行属于哪一份证明"，
    而答案永远有一个 —— 没写就是 `#p1`（老数据的读法，业主 2026-10-22 口径：
    不带 `#pN` / 不带 `proof_no` 的老数据，读数与行为逐字不变，证明号缺省 1）。
    认不出的值同样按 1 读：读侧拿不到答案，比读成 canonical 更坏（`as_proof_no` 的
    0 留给"判这一格有没有写号"那一档用）。
    """
    for key in PROOF_NO_KEYS:
        value = row.get(key)
        if str(value or "").strip():
            got = as_proof_no(value)
            if got >= 1:
                return got
    return DEFAULT_PROOF_NO


def _read_proof_no(value: Any) -> int:
    """读侧收一个"要看哪一份证明"的号：没给 ⇒ canonical（1）；给了但认不出 ⇒ 0。

    ## 三档不许折平（业主 2026-10-22 裁定）
    - :func:`proof_no_of` 问的是"这一行属于哪一份证明"—— 答案永远有一个（老行没写就是
      `#p1`），所以它把认不出的值也读成 1；
    - :func:`proof_no_strict` 是写侧"调用方说要签哪一份"—— 认不出就抛错，一个字节都不写；
    - 本函数是读侧的"调用方点名要看哪一份"—— 它必须能回答"没有这一份"：字段/参数缺失
      才是 canonical，给了但认不出就是 0，不许折成 `#p1`。

    改前三处读口都写 `as_proof_no(x) or 1`：于是 `'abc'` / `0` / `2.0` 这类"这不是一个
    证明号"的值被静默读成 canonical —— 读数里看不出"号给错了"，而 `proof_text_of` 还会
    把 `#p1` 的正文端出来当作"你要的那一份"。折平在这里不是"读数粗一点"，是张冠李戴。

    空串与 `None` 同一档（都算"没写"）：老行可能把这一格写成空串，它与"键不存在"在读侧
    没有区别（`proof_no_of` 也是这么读的，见那里的 `if str(value or "").strip()`）。
    """
    if value is None or not str(value).strip():
        return DEFAULT_PROOF_NO
    return as_proof_no(value)


def proof_list(row: Mapping[str, Any]) -> list[tuple[int, str]]:
    """这条命题的证明清单 `[(proof_no, 正文), ...]`，`#p1` 恒在且排第一。

    两处来源（与 `PROOFS_KEY` 的注释同一口径）：
    - `#p1`（canonical）：行上的 `proof_text` —— 老写者（B / F / 秘书）只会写那一格，
      所以它必须继续是 canonical 的权威正文；
    - `#p2` 及以上：行 JSON 的 `proofs` 清单里，每项 `{"proof_no": n, "proof_text": …}`。
      清单里若也写了 1 号，读侧以 `proof_text` 为准（同一格不许有两个权威）。
    没有清单的旧行 ⇒ 只有一条 `(1, proof_text)`，读数与改前逐字相同。
    """
    out: list[tuple[int, str]] = [(1, str(row.get("proof_text") or ""))]
    raw = row.get(PROOFS_KEY)
    if not isinstance(raw, (list, tuple)):
        return out
    seen = {1}
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        no = proof_no_of(entry)
        if no <= 1 or no in seen:
            continue
        seen.add(no)
        out.append((no, str(entry.get("proof_text") or entry.get("text") or "")))
    return sorted(out, key=lambda item: item[0])


def proof_text_of(row: Mapping[str, Any], proof_no: int = 1) -> str:
    """这条命题的某一份证明现在长什么样（找不到那一份 ⇒ 空串）。

    证明号走 :func:`_read_proof_no`：没给 ⇒ `#p1`；给了但认不出（`'abc'` / `0` …）⇒
    空串，不端出 `#p1` 的正文。改前是 `as_proof_no(proof_no) or 1`，于是
    `proof_text_of(row, 'abc')` 读到的就是 canonical 那一份 —— 一个坏号得到的答案与
    "我要 #p1"逐字相同，而调用方无从分辨。
    """
    want = _read_proof_no(proof_no)
    if want < 1:
        return ""
    for no, text in proof_list(row):
        if no == want:
            return text
    return ""


def proof_label(statement_id: str, proof_no: int = 1) -> str:
    """读数里的写法：`000004#p2`（不带 `#pN` 的老写法等价于 `#p1`）。

    证明号认不出时写法里点名（`000004#p？（证明号认不出：'abc'）`），不折成 `#p1`：
    这个串会进 `why` / `detail` / 逐条计数项（`proofs_unreviewed` 等），折平会让一条
    坏号以 canonical 的身份出现在读数里，读的人只会看到"#p1 怎么样"，看不到"号给错了"。
    """
    sid = str(statement_id or "")
    no = _read_proof_no(proof_no)
    if no < 1:
        return f"{sid}#p？（证明号认不出：{proof_no!r}）"
    return f"{sid}#p{no}"


def parse_verdict(text: str) -> dict[str, Any]:
    """把 V 的那一句输出拆成字段；它不判定任何东西（p247：判词只是陈述）。

    "没查成"与"对证明的结论"必须分开：前者是检查器的问题（重试 / 修提示词），
    后者是对证明的判断。把两者折平，会让一次模型抽风在台账上留下"V 看过这份证明"
    ——那是一条假证据。

    ## 这里只做结构解析，不做任何词面折档（业主 2026-11-06 第三次收紧）
    业主逐字：「V 的判词只是陈述」；「不做折档」；「不许按词面把判不了 / 看不出来 /
    拿不准 / 我无法判断折成任何一态」。所以本函数：
    ① 只拆 JSON、取字段、洗 `findings` / `citation_checks`，把 `verdict` 原样留住；
    ② 不检查 `verdict` 是不是两态之一，也不因它写了什么就决定 clean / fault ——
       每一转的轴由 V 的秘书读这段回复后语义判定（`secretary_judge.axis`，
       见 :func:`secretary_axis`）；
    ③ `defect_step` 允许缺：秘书判 fault 而 V 没给步号时，由秘书定出那一步
       （`Secretary.judge_v_reply` 的 `defect_step` 读数），再写回这一行。

    只有结构本身不合法（不是 JSON / 缺 `verdict` 字段 / `findings` 形状坏 /
    `citation_checks` 形状坏）才是"没查成"：抛 `VerificationError`，不落行。
    """
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|```$", "", raw).strip()
    start, end = raw.find("{"), raw.rfind("}")
    body = raw[start:end + 1] if (start >= 0 and end > start) else raw
    try:
        got = json.loads(body)
    except ValueError as exc:
        raise VerificationError(f"V 的输出不是合法 JSON（{type(exc).__name__}: {exc}）") from exc
    if not isinstance(got, Mapping):
        raise VerificationError("V 的输出必须是对象")
    said = str(got.get("verdict") or "").strip()
    if not said:
        raise VerificationError("V 的输出缺 `verdict` 字段 ⇒ 没有可判的陈述（没查成）")
    #: 折档时代留下的原话（老调用方仍会带过来）；p247 起 `verdict` 自己就是原话。
    verdict_raw = str(got.get("verdict_raw") or "").strip()

    findings: list[dict[str, Any]] = []
    for item in (got.get("findings") or []):
        if not isinstance(item, Mapping):
            raise VerificationError("findings 的每一项都必须是对象")
        level = str(item.get("level") or "").strip()
        if level not in FINDING_LEVELS:
            raise VerificationError(f"finding.level 必须是 {FINDING_LEVELS} 之一，收到 {level!r}")
        findings.append({"level": level, "step": item.get("step"),
                         "kind": str(item.get("kind") or "").strip(),
                         "detail": str(item.get("detail") or "").strip()})
    defect_step = got.get("defect_step")
    if defect_step is not None and not isinstance(defect_step, int):
        raise VerificationError("defect_step 必须是整数或 null")
    checks = _citation_checks_raw(got.get("citation_checks"))
    return {"verdict": said, "verdict_raw": verdict_raw,
            "defect_step": defect_step,
            "quote": str(got.get("quote") or "").strip(),
            "why": str(got.get("why") or "").strip(),
            "findings": findings,
            "citation_checks": checks,
            "unresolved_errors": sum(1 for f in findings if f["level"] == "error")}


def kind_upgrade_witness(root: str | Path, row: Mapping[str, Any], *,
                         gap: Mapping[str, Any] | None = None,
                         proof_no: Any = None) -> str:
    """D-37 `_kind_upgrade` 留痕的唯一措辞：“签凭据（`out/vsigns/<sha>.json`）
    + 台账那一行（`verifications/<号>.jsonl#v-…`）”。

    ## 为什么必须有这一格（业主 2026-11-10 的裁量 ②）

    改前两条路各写各的：秘书那一支写「手稿签块（连续 3/3 成立…）」或
    「bits.reviewed（第 3 位…）」，B 那一支写「verifications/…jsonl#v-… 判成立」。
    读的人从 `_kind_upgrade.basis` 回不到"哪一签让它升的"：前者没有号、后者没有
    签文件。这一格把两边收成同一句 —— 先点名按正文 sha 命名的签文件（可点开复算），
    再点名台账那一行（可点开看三票）。没有签文件（只有台账 / pending）时就只留
    台账那一行；只有 `verification_id` 而没有台账路径时留 id。

    ## 纯读
    不写任何东西：`gap` 可由调用方传入（省一次台账读），不给就现读
    `proof_review_gap`。读不出来 / 没有正文 ⇒ 返回空串，由调用方退回它自己那句
    人话（不许把"没查成"编成一条凭据）。
    """
    if root is None:
        return ""
    try:
        no = as_proof_no(proof_no if proof_no is not None
                         else row.get("proof_no")) or 1
    except (TypeError, ValueError):
        no = 1
    body = proof_text_of(row, no)
    if not body.strip():
        return ""
    sha = verifications.text_sha(body)
    got = dict(gap or {})
    if not got:
        try:
            got = verifications.proof_review_gap(root, row, proof_no=no)
        except Exception:  # noqa: BLE001 —— 凭据读不出来就不编一条
            got = {}
    ledger = str(got.get("ledger") or "")
    vid = str(got.get("verification_id") or "")
    parts: list[str] = []
    try:
        from . import vsigns as _VS   # 惰性：签文件目录只有一处口径

        sign_rel = f"{_VS.SIGNS_DIR}/{sha}.json"
        if (Path(root) / sign_rel).is_file():
            parts.append(f"{sign_rel}#{vid}" if vid else sign_rel)
    except Exception:  # noqa: BLE001 —— 签文件读不到不算"没有"，只是这一句少一格
        pass
    if ledger:
        anchor = (ledger if (not vid or ledger.endswith(f"#{vid}"))
                  else f"{ledger}#{vid}")
        parts.append(f"台账 {anchor}")
    if not parts and vid:
        parts.append(f"verification_id {vid}")
    return " · ".join(parts)


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    FINDING_LEVELS,
    PROOFS_KEY,
    PROOF_NO_KEYS,
    VERIFICATIONS_DIR,
)
from .v_citation import (  # noqa: F401 — 实现在 v_citation.py
    _citation_checks_raw,
)
