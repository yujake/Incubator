# -*- coding: utf-8 -*-
"""验证者（V）的证明级审校台账（`draft/39` §3.21 五，用户 2026-10-05 定案）。

## 这一层解决什么

五元证据位（§3.14）的第 3 位（"审过"）的 owner 是 V：一个 F 配一个验证者，
它把 F 交回来的证明按写成后的样子整体重读，做三件事（就是用户点名的 I12/I10/I17）：

1. I12 冷启动：每次审校开新会话，只给对象（证明全文）+ 只读查询面的读数，
   不给 F 的叙述、不给 store 句柄 ⇒ "独立性"是结构性质，而不是一句约定；
2. I10 硬禁令 + 同段依据：逐条查（无条件前提 / 无依据的步骤 / "易证、显然、trivial"
   这类缝 / 引用的命题是否干净），每条问题指到那一步并给理由；
3. I17 整篇重读：把证明当一次输入整体读（"这些缝正是正确的事实变成错误证明的地方"），
   而不是只逐单元核对。

## 落点与形态（与手稿同一形态：追加式 JSONL，不新增台账表）

`<工作区>/verifications/<命题号>.jsonl` —— 一行 = 一次审校。一行里至少要有：
输入证明的 `sha256`、三态结论、逐条 findings（每条带步号）、用了哪个只读面、验证者实例名。
编号 `v-0001…` 由脚本按文件内顺序发（与手稿编号、台账 id 同一套做法）。

## 三态纪律在这里的落法（这一层最容易出错的地方）

- `成立` / `有毛病` / `看不出来` 是对证明的三个结论；
- "检查器自己没跑成"（模型输出不是合法 JSON、字段缺、取值不在词表里）不是这三个之一 ——
  它是没查成：`record()` 在没有合法结论时抛 `VerificationError`，绝不写一行
  "看不出来"来冒充"审过了"。

## 签"审过"的条件（§3.21 五）

`verdict="成立"` 且 findings 里没有未解决的 `error` ⇒ `signs_bit3()` 为真，
`bit3_payload()` 给出五元位第 3 位那份读数（`reviewed=True` + 凭据）。
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from . import textutil as T  # 引用解析的唯一实现（`citation_ref_parts`，`P-5`）

#: 验证台账目录（工作区根下）。
VERIFICATIONS_DIR = "verifications"
#: 三态结论（顺序就是从"站不住"到"站得住"；`看不出来` 不是 `成立`）。
VERDICTS: tuple[str, ...] = ("有毛病", "看不出来", "成立")
#: findings 的级别（与 `schema.FINDING_LEVELS` 同词表）。
FINDING_LEVELS: tuple[str, ...] = ("error", "warning", "info")
#: 硬禁令的清单（I10 的最小形态）：命中这些短语的步骤必须被指出来。
#: 用户 2026-10-05 口径："F 禁止写'易证/显然/trivial/clearly/it is easy to see'"。
HARD_BAN_MARKERS: tuple[str, ...] = (
    "易证", "显然", "trivial", "clearly", "it is easy to see", "无须证明", "显然成立",
)
#: 一次审校至少要交代的四件事（缺一就不是"审过了"）。
REQUIRED_FIELDS: tuple[str, ...] = ("verdict", "statement_id", "proof_sha256")


class VerificationError(ValueError):
    """这次审校没查成（不是"有毛病"）：输出不合法、字段缺、取值不在词表里。"""


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().replace(microsecond=0).isoformat()


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


def cold_start_prompt(statement_full: str, proof_text: str,
                      *, readonly_facts: str = "") -> str:
    """V 的冷启动提示词（纯函数：只有对象 + 只读读数，没有 F 的叙述、没有 store 句柄）。

    为什么把"提示词怎么拼"做成纯函数而不是塞进角色循环里：I12 是一个结构性质 ——
    "给它的上下文里有没有 F 的叙述 / 有没有 store 句柄"必须能被判据直接断言
    （`tests/test_verifier_role.py` 就是这么判的）。塞进循环里之后，它只能靠"读代码相信"。

    `readonly_facts` 是已经渲染好的只读读数（命题/文献/实验台账的摘要，由调用方
    从只读查询面取好传进来）—— 传字符串而不是传 store，是为了让"它能碰什么"在接口上
    就固定下来。
    """
    # 开关读数（读不懂按"关"算：与 settings 的 fail-closed 同向）
    try:
        from .settings import lean_enabled as _le

        _lean_on = bool(_le()[0])
    except Exception:  # noqa: BLE001
        _lean_on = False
    return (
        "你是验证者（V）。你这一次只做一件事：把下面这份证明**按写成后的样子**整体重读一遍，"
        "判断它站不站得住。\n\n"
        "你不写、不改证明；不判这命题值不值得做；不做稿件级正式审查。\n\n"
        "## 硬禁令（命中哪一条就指到那一步）\n"
        "- 无条件前提（结论要的前提没写出来）；\n"
        "- 无依据的步骤（既没引到在册的 id，也没有同段内的推导）；\n"
        f"- 缝：{'、'.join(HARD_BAN_MARKERS)} 这类「跳过去」的措辞；\n"
        "- 引用到一条**不干净**的命题（还是猜想 / 已作废 / 只是 assumption）。\n\n"
        "## 只读读数（你只能看这些；没有 store 句柄，也不给你作者的任何解释）\n"
        f"{readonly_facts.strip() or '（调用方没有附只读读数）'}\n\n"
        "## 命题（含完整假设）\n"
        f"{str(statement_full or '').strip() or '（空）'}\n\n"
        "## 证明全文\n"
        f"{str(proof_text or '').strip() or '（空）'}\n\n"
        "## 只输出一个 JSON 对象（不要解释文字、不要代码围栏）\n"
        '{"verdict": "成立|有毛病|看不出来", "defect_step": <整数或 null>, '
        '"quote": "<命中的原话，逐字>", "why": "<一句话理由>", '
        '"findings": [{"level": "error|warning|info", "step": <整数或 null>, '
        '"kind": "<短语>", "detail": "<指到那一步的说明>"}]}\n'
        "- `defect_step`：有毛病时**必须**给出那一步的编号（从 1 起数，按证明里的步骤顺序）；\n"
        "- `看不出来`：信息不足、无法判断时的诚实结论 —— 它不是 `成立`；\n"
        "- 没有毛病才写 `成立`（空 findings 或只有 info/warning）。\n"
        # 2026-10-17（Lean 审计 S3）：**这是 V 的真实入口**（`agent_v/core.py` 用它，
        # 而 `system_prompt("V")` 全仓没有生产路径渲染）⇒ 开关与"成立≠proof"必须写在这里，
        # 否则 V 在 Lean 开着/关着时行为完全一样，而 H 会把它签的第 3 位当凭据。
        "\n## 你这个「成立」是什么强度\n"
        f"- 本会话 Lean 形式化：{'**已开启**' if _lean_on else '**已关闭**'}；\n"
        "- 你签的「成立」是**逐行读出来的结论**，它**永远不构成 `proof` 级证据** —— "
        "`evidence_kind=\"proof\"` 只由 `verify.check_formal` 的检查器输出产生；\n"
        "- 所以别在理由里写「已形式化验证」；要 proof 级证据，得请 M 派 E 走 `method=\"formal\"` 那条路。\n"
    )


def proof_sha(proof_text: str) -> str:
    """被审证明的 sha256（钉住"审的是哪一份"；与台账 id 的指纹口径同一套）。"""
    return hashlib.sha256(str(proof_text or "").encode("utf-8")).hexdigest()


def parse_verdict(text: str) -> dict[str, Any]:
    """把 V 的那一句输出解析成一次审校的结论；不合法 ⇒ 抛 `VerificationError`（没查成）。

    "没查成"与"看不出来"必须分开：前者是检查器的问题（重试/修提示词），
    后者是对证明的结论（诚实地说判不了）。把两者折平，会让一次模型抽风
    在台账上留下"V 看过这份证明，结论是看不出来"——那是一条假证据。
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
    verdict = str(got.get("verdict") or "").strip()
    if verdict not in VERDICTS:
        raise VerificationError(f"verdict 必须是 {VERDICTS} 之一，收到 {verdict!r}")
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
    if verdict == "有毛病" and defect_step is None:
        raise VerificationError(
            "verdict='有毛病' 必须给 defect_step（指到那一步）—— 只说'有毛病'"
            "等于把改哪儿留给作者猜"
        )
    return {"verdict": verdict, "defect_step": defect_step,
            "quote": str(got.get("quote") or "").strip(),
            "why": str(got.get("why") or "").strip(), "findings": findings,
            "unresolved_errors": sum(1 for f in findings if f["level"] == "error")}


def next_verification_id(root: str | Path, statement_id: str) -> str:
    """这个命题的验证台账里的下一个编号（`v-` + 当前宽度；宽度见 `schema.format_id`）。

    为什么从 `record_verification` 里抽出来一处具名函数（2026-10-14 改宽度那一笔）：
    它是**发号点**，而"每个发号点都发当前宽度"这条判据要能逐个真发一次 ——
    发号逻辑埋在写函数中间时，判据只能靠"读一遍代码"来假装检查过。
    """
    path = verification_ledger_path(root, statement_id)
    rows, _problems = JF.read_jsonl(path) if path.is_file() else ([], [])
    return f"v-{S.format_id(len(rows) + 1)}"


def record_verification(root: str | Path, *, statement_id: str, proof_text: str, verdict: Mapping[str, Any],
           verifier: str = "V", round_no: int | None = None,
           used_faces: Iterable[str] = (), submission_id: str = "") -> dict[str, Any]:
    """把一次审校写进这个命题的台账（追加一行），返回那一行。

    编号 `v-NNNN` 由脚本按文件内顺序发（`draft/39` §3.21 五：与手稿编号、台账 id 同一套）。
    写之前把结论再规范化一遍（`parse_verdict` 的同一套校验）—— 调用方绕开解析直接
    构造一个 dict 时，坏结论会在写入期被挡住，而不是等到下游读它的时候。
    """
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or [])},
                                       ensure_ascii=False, default=str))
    path = verification_ledger_path(root, statement_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows, problems = JF.read_jsonl(path)
    if problems:
        raise VerificationError(f"这个命题的验证台账有读不出来的行：{problems[:3]}")
    vid = next_verification_id(root, statement_id)
    row = {
        "verification_id": vid, "statement_id": str(statement_id),
        "verifier": str(verifier or "V"), "verdict": checked["verdict"],
        "defect_step": checked["defect_step"], "quote": checked["quote"],
        "why": checked["why"], "findings": checked["findings"],
        "unresolved_errors": checked["unresolved_errors"],
        "proof_sha256": proof_sha(proof_text),
        "proof_chars": len(str(proof_text or "")),
        "round": int(round_no) if round_no is not None else len(rows) + 1,
        "used_faces": [str(x) for x in used_faces],
        "submission_id": str(submission_id or ""),
        "at": _now_iso(),
    }
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return row


def list_verifications(root: str | Path, *, statement_id: str = "",
             limit: int | None = 50) -> tuple[list[dict[str, Any]], list[str]]:
    """列验证台账（可按命题过滤）；返回 `(行, 坏行说明)` —— 坏行照实报出，不静默跳过。

    ## `limit=None` 与 `limit=0` 必须分开（V1，`draft/44` J-14）

    实现此前写的是 `out[-limit:]`，而 `-0 == 0` ⇒ `limit=0` 恰好等于全量。
    那是一个靠运算符巧合成立的语义：调用方写 `limit=0`（"不要行"）会拿到全部行，
    而没有任何报错。三态纪律在分页上同样成立 —— "要零条"与"要全部"是两件事。

      - `limit=None` ⇒ 全量（"我要看完整本台账"）；
      - `limit=0`   ⇒ 零条（空表）；
      - `limit=n>0` ⇒ 末尾 n 条（按 (命题号, 编号) 排序后取尾部）。
    """
    base = verifications_dir(root)
    out: list[dict[str, Any]] = []
    problems: list[str] = []
    files = ([verification_ledger_path(root, statement_id)] if statement_id
             else sorted(base.glob("*.jsonl")) if base.is_dir() else [])
    for p in files:
        rows, bad = JF.read_jsonl(p)
        problems.extend(f"{p.name}: {b}" for b in bad)
        out.extend(rows)
    out.sort(key=lambda r: (str(r.get("statement_id") or ""), str(r.get("verification_id") or "")))
    if limit is None:
        return out, problems
    return out[-max(0, int(limit)):] if int(limit) > 0 else [], problems


def read_verification(root: str | Path, verification_id: str) -> dict[str, Any] | None:
    """按编号取一行（编号在同一命题的文件内唯一；跨文件重号 ⇒ 返回第一个并带 `ambiguous`）。"""
    want = str(verification_id or "").strip()
    rows, _problems = list_verifications(root, limit=None)
    hit = [r for r in rows if str(r.get("verification_id")) == want]
    if not hit:
        return None
    if len(hit) > 1:
        got = dict(hit[0])
        got["ambiguous"] = len(hit)
        return got
    return hit[0]


def signs_bit3(row: Mapping[str, Any]) -> bool:
    """这一行能不能签五元位第 3 位（§3.21 五：`成立` 且没有未解决的 error）。"""
    return (str(row.get("verdict") or "") == "成立"
            and int(row.get("unresolved_errors") or 0) == 0)


def bit3_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """把一行审校翻成五元位第 3 位那份读数（交给 `evidencebits.bits_of`）。

    签不了（`有毛病` / `看不出来` / 有未解决 error）⇒ 返回 `{}`（第 3 位保持空）——
    这不是"忘了写"，是"没签"。
    """
    if not signs_bit3(row):
        return {}
    return {
        "reviewed": True,
        "reviewed_by": {
            "verifier": str(row.get("verifier") or "V"),
            "verification_id": str(row.get("verification_id") or ""),
            "round": row.get("round"),
            "verdict": str(row.get("verdict") or ""),
            "evidence": f"verifications/{row.get('statement_id')}.jsonl#"
                        f"{row.get('verification_id')}",
            "findings": list(row.get("findings") or []),
        },
    }


def banned_markers_in(proof_text: str) -> list[str]:
    """这份证明里命中了哪些硬禁令短语（I10 的机械那一半，可离线复算）。"""
    text = str(proof_text or "")
    return [m for m in HARD_BAN_MARKERS if m in text]


#: `proof_review` 这一档的**凭据判据码**（2026-10-19，堵「假 proof_review」）。
#:
#: 两个码各有落点，不许合成一个（一个是写入期拒收，一个是审计期点名 ——
#: 同一句话在两个出口上的读者不同：写者要"改哪里"，审计要"存量有多少"）：
#:
#: - `CODE_WRITE`：写入期闸（`store.tx` 提交时）—— **当场拒收**，一行都不写；
#: - `CODE_AUDIT`：审计期档（`verify._check_13`）—— **error 级点名**，存量照读。
CODE_WRITE = "proof_review_without_evidence"
CODE_AUDIT = "proof_review_without_verification"

#: `proof_review` 这一档在 `statements.evidence_kind` 里的取值（口径见 `schema.EVIDENCE_KINDS`）。
PROOF_REVIEW_KIND = "proof_review"


def proof_review_gap(root: str | Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """一条 `evidence_kind="proof_review"` 的命题**有没有凭据** —— 纯读，不写任何东西。

    判据逐字来自 `schema.EVIDENCE_KINDS` 上面那段定义（2026-10-19 之前它只是注释，
    没有任何代码强制）：

        `proof_review` —— **证明经逐行审阅**（`statements` 表的 `proof_text` 非空
        ＋ V 的 `verifications` 里那一条签「成立」）。

    三条都要成立（缺哪一条就报哪一条，`why` 里逐字说清）：

    1. `proof_text` 非空 —— 没有被审的那份证明，"审过"无从谈起；
    2. `verifications/<命题号>.jsonl` 里有一行，且**最后那一行**签得住第 3 位
       （`signs_bit3`：`verdict="成立"` 且 `unresolved_errors == 0`）——
       取最后一行而不是"任意一行"：台账是追加式的，后面若有一条「有毛病」，
       那一版就已经不是"成立"了；
    3. 那一行记的 `proof_sha256` 就是**现在这一版** `proof_text` 的 sha256 ——
       台账记 sha 的唯一用途就是这个。不查它，"V 审过"就退化成"V 审过某个东西"，
       而这句话没法被任何读数证伪（改完证明不再送审，签名照样成立）。

    三态：读不到台账 / 台账有坏行 ⇒ `ok=False` 且 `checked=False`（那是**没查成**，
    不是"通过"也不是"有毛病"）；两者在调用方那里都**不许**放行（写入期拒收、
    审计期点名）——"查不到凭据"与"凭据不合格"对这条命题是同一件事。

    返回 `{"ok", "checked", "why", "statement_id", "verification_id", "verdict",
    "resolved_errors"…}` 的确切键：`{"ok", "checked", "why", "statement_id",
    "verification_id", "verdict", "round", "unresolved_errors", "sha_matches",
    "ledger", "rows", "problems", "checklist"}`。

    `checklist` 是**逐项过关读数**（`[{"item", "ok", "detail"}]`，三条与上面一一对应）。
    它只为拒信存在：业主 2026-10-19 的口径是"拒收消息要让人/模型一眼看出该补哪一项"——
    只给一段 `why` 时，读的人得在散文里自己找缺的是哪一格。它**不参与判据**
    （判据仍只看 `ok`），所以它写错不改判据、只改可读性。
    """
    sid = str(row.get("stmt_id") or row.get("statement_id") or "").strip()
    out: dict[str, Any] = {
        "ok": False, "checked": False, "why": "", "statement_id": sid,
        "verification_id": "", "verdict": "", "round": None,
        "sha_matches": None, "ledger": "", "rows": 0, "problems": [],
    }
    checks: list[dict[str, Any]] = [
        {"item": "proof_text 非空（有被审的那份证明）", "ok": False, "detail": "还没判到"},
        {"item": f"`verifications/<命题号>.jsonl` 里有签「成立」的那一行"
                 f"（verdict=成立 且 unresolved_errors=0）", "ok": False, "detail": "还没判到"},
        {"item": "那一行的 `proof_sha256` 等于现在这一版 `proof_text` 的 sha256",
         "ok": False, "detail": "还没判到"},
    ]
    out["checklist"] = checks
    # ---- 概念行：永远不算"有证明"（2026-10-21，本批缺陷一的读侧）
    #
    # 真机读数（`projects/mp3/data/statements.json`）：1143 条概念行**每一条**
    # 都带 `proof_text`（值是一个哨兵 `concept:primitive`）。于是"这一行有没有证明"
    # 的读数被顶高：`prose_reviewed_statements` 数的是"`proof_text` 非空且 V 签了
    # 成立"，一条概念行只要撞上一次签名就能进那一格；而 `proof_review_gap` 也只问
    # `proof_text` 非空 —— 它会把概念行当成"有一条被审过的证明"的候选。
    #
    # 判据只有一句：**概念不参与等级链**（`draft/97` §14.5，
    # `evidencebits.derive_grade` 对 `kind="concept"` 短路成 `not_applicable`），
    # 所以它既没有"证明"这一档，也不可能"有证明"。两档要分开说：
    # 带 `proof_text` 是**写入侧的污染**（要点名，让存量看得见），
    # 不带是**正常**（这一格对它不适用 —— 不是"缺证明"）。
    if str(row.get("kind") or "") == "concept":
        out["checked"] = True
        text_concept = str(row.get("proof_text") or "")
        if text_concept.strip():
            checks[0].update(ok=False, detail=f"{len(text_concept)} 字（概念行不该有）")
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"概念行不该带证明文本：命题 {sid or '（没有编号）'} 是 "
                          f"kind='concept'，而它的 `proof_text` 非空"
                          f"（{text_concept[:40]!r}）⇒ 概念不参与等级链，"
                          "`proof_text` 对它不是证明，而是一个哨兵；"
                          "任何'有没有证明'的读数都会被它顶高。"
                          "写入侧已经堵住（`conceptrows.concept_statement` 不写这一格），"
                          "这一条是存量行的点名：把这一格清空（定义/待补标记都在别的字段里）")
        else:
            checks[0]["detail"] = "概念行没有 proof_text（正常：概念不参与等级链）"
            checks[1]["detail"] = "概念行没有'证明'这一档，不适用"
            checks[2]["detail"] = "同上"
            out["why"] = (f"命题 {sid or '（没有编号）'} 是概念行（kind='concept'）："
                          "概念没有'证明'这一档（不参与等级链）⇒ 这一格对它**不适用**，"
                          "不许读成'有证明'，也不许读成'缺证明'")
        return out
    text = str(row.get("proof_text") or "")
    if not text.strip():
        out["checked"] = True
        checks[0]["detail"] = "空"
        checks[1]["detail"] = "没有被审的对象，不适用"
        checks[2]["detail"] = "没有被审的对象，不适用"
        out["why"] = (f"命题 {sid or '（没有编号）'} 的 evidence_kind="
                      f"{PROOF_REVIEW_KIND!r}，而 `proof_text` 是空的 ⇒ "
                      "没有被审的那份证明，「逐行审阅过」这句话就没有对象。"
                      "要么把证明过程写进 proof_text，要么把这一档降成 heuristic")
        return out
    checks[0].update(ok=True, detail=f"{len(text)} 字")
    if not S.is_valid_id(sid):
        checks[1]["detail"] = "命题号不是编号形态，查不到台账"
        checks[2]["detail"] = "同上"
        out["why"] = (f"命题号 {sid!r} 不是编号形态（{S.ID_DIGITS} 位，旧四位仍可读）⇒ "
                      f"`verifications/` 里查不到它，凭据无从核起")
        return out
    path = verification_ledger_path(root, sid)
    out["ledger"] = f"{VERIFICATIONS_DIR}/{sid}.jsonl"
    if not path.is_file():
        out["checked"] = True
        checks[1]["detail"] = f"`{out['ledger']}` 不在盘上（一次审校都没有）"
        checks[2]["detail"] = "没有那一行，无从比"
        out["why"] = (f"命题 {sid} 声称 evidence_kind={PROOF_REVIEW_KIND!r}，而 "
                      f"`{out['ledger']}` 不在盘上 ⇒ **一次审校都没有**。"
                      "这一档要求 V 的 `verifications` 里那一条签「成立」（且审的是现在"
                      "这一版）—— 没有它，这一行就只是「自称被审过」。"
                      f"两条出口：① 派 V 去 `verify_proof(stmt:{sid})`；"
                      "② 把 evidence_kind 降成 heuristic")
        return out
    rows, problems = JF.read_jsonl(path)
    out["rows"] = len(rows)
    out["problems"] = list(problems)
    if problems:
        checks[1]["detail"] = f"台账有读不出来的行：{problems[:3]}（没查成）"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 有读不出来的行（{problems[:3]}）⇒ "
                      "凭据**没查成**（不是「查过、没问题」）")
        return out
    if not rows:
        out["checked"] = True
        checks[1]["detail"] = "台账是空文件"
        checks[2]["detail"] = "同上"
        out["why"] = (f"`{out['ledger']}` 是空文件 ⇒ 一次审校都没落过"
                      "（「有这个文件」不等于「审过」）")
        return out

    def _key(r: Mapping[str, Any]) -> tuple[int, str]:
        try:
            return (int(r.get("round") or 0), str(r.get("verification_id") or ""))
        except (TypeError, ValueError):
            return (0, str(r.get("verification_id") or ""))

    latest = dict(max(rows, key=_key))
    out.update({
        "checked": True,
        "verification_id": str(latest.get("verification_id") or ""),
        "verdict": str(latest.get("verdict") or ""),
        "round": _key(latest)[0],
        # 给拒收消息用（"最近一签是 verdict=X、unresolved_errors=N"）：**读数**，
        # 不参与判据 —— 判据只看 `signs_bit3`（一处口径）。
        "unresolved_errors": int(latest.get("unresolved_errors") or 0),
    })
    if not signs_bit3(latest):
        checks[1]["detail"] = (f"最近一签 {out['verification_id']}：verdict={out['verdict']!r}、"
                               f"unresolved_errors={int(latest.get('unresolved_errors') or 0)}")
        checks[2]["detail"] = "没有签住，无从比"
        out["why"] = (f"命题 {sid} 的 evidence_kind={PROOF_REVIEW_KIND!r}，而 "
                      f"`{out['ledger']}` 里**最近一签**是 "
                      f"{out['verification_id']}：verdict={out['verdict']!r}、"
                      f"unresolved_errors={int(latest.get('unresolved_errors') or 0)}"
                      f"（why：{str(latest.get('why') or '')[:120]}）⇒ "
                      "**没有「成立」那一签**。这一档要的正是那一签"
                      "（「成立」且没有未解决的 error）")
        return out
    checks[1].update(ok=True, detail=f"{out['verification_id']}：{out['verdict']}")
    want = proof_sha(text)
    got = str(latest.get("proof_sha256") or "")
    out["sha_matches"] = (got == want)
    if got != want:
        checks[2]["detail"] = f"台账 {got[:12]}… ≠ 现行 {want[:12]}…（签的是另一版）"
        out["why"] = (f"命题 {sid} 的凭据 {out['verification_id']} 签的是**另一版**证明"
                      f"（台账 sha256={got[:12]}…，现在这一版={want[:12]}…）⇒ "
                      "审过的那份与现在这一份不是同一份，签名不覆盖现在这一版。"
                      f"改过证明就要重新派 V 走一遍（`verify_proof(stmt:{sid})`）")
        return out
    checks[2].update(ok=True, detail=f"{want[:12]}…")
    out["ok"] = True
    return out


#: 比 `proof_review` 更弱的证据档（降档告警用；顺序 = 由弱到强里的两档）。
WEAKER_THAN_PROOF_REVIEW: tuple[str, ...] = ("heuristic", "cross_check")


def weaker_than_evidence_gaps(root: str | Path,
                              rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里**够格 `proof_review` 却登记成更弱档**的那些 —— 纯读。

    ## 这条读数在说什么（2026-10-19，接 `proof_review_gap` 的反方向）

    `proof_review_gap` 管的是"自称审过、其实没签"（**虚报**，安全方向的反面）。
    这里是它的镜像：**凭据齐全、档位却写低了**（`heuristic` / `cross_check`）。
    真机形态（`projects/mp2` 的 `stmt:000003`）：`proof_text` 1909 字、V 的
    `verifications/000003.jsonl` 里 `v-000001` 签「成立」、`proof_sha256` 与现行
    正文相符 —— 按 `schema.EVIDENCE_KINDS` 的定义这条**就是** `proof_review`，
    而盘上落的是 `heuristic`。

    它不是虚报，所以**不是 error**：降档是安全方向，可以是有意的选择（例如
    "这份证明的范围比命题窄"）。但它必须是**看得见的选择**，不是默认值 ——
    长期把强结果写成弱档，代价是论文的强度声明系统性地偏低，而没有任何读数
    会指出这一点。

    ## 判据（只三条，与 `proof_review_gap` 同一处口径）

    1. `evidence_kind` 在 :data:`WEAKER_THAN_PROOF_REVIEW` 里；
    2. `proof_text` 非空（没有证明就谈不上"这份证明被审过"）；
    3. `proof_review_gap(...)` 判 `ok=True`（把那一行按 `proof_review` 重判一遍：
       V 最近一签是「成立」且 `proof_sha256` 等于现行正文）。

    概念行（`kind="concept"`）跳过：概念不参与等级链（见
    `evidencebits.derive_grade` 的 `not_applicable`），把它的 `proof_text`
    （"为什么这个概念良定义"）读成"一份被审过的证明"是另一种口径错误。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ek = str(row.get("evidence_kind") or "")
        if ek not in WEAKER_THAN_PROOF_REVIEW:
            continue
        if str(row.get("kind") or "") == "concept":
            continue
        if not str(row.get("proof_text") or "").strip():
            continue
        probe = dict(row)
        probe["evidence_kind"] = PROOF_REVIEW_KIND
        gap = proof_review_gap(root, probe)
        if not gap.get("ok"):
            continue
        sid = str(row.get("stmt_id") or row.get("statement_id") or "")
        out.append({
            "statement_id": sid,
            "evidence_kind": ek,
            "verification_id": gap.get("verification_id") or "",
            "ledger": gap.get("ledger") or "",
            "why": (f"命题 {sid} 登记成 evidence_kind={ek!r}，而它的凭据已经够 "
                    f"`proof_review`：`proof_text` 非空、`{gap.get('ledger') or ''}` 里 "
                    f"{gap.get('verification_id')} 签「成立」、`proof_sha256` 与现行正文相符"
                    "（判据与 `proof_review` 写入期那道闸同一处）。"
                    "降档是安全方向，所以这是 warning、不是 error；但它必须是有意的："
                    "要么把这一行升成 `proof_review`（判据已够格，写入不会被拒），"
                    "要么在报告里写清为什么故意留弱档。"),
        })
    return out


def proof_review_gaps(root: str | Path, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """一组 `statements` 行里**凭据不够**的那些 `proof_review`（空列表 = 都够）。

    只挑 `evidence_kind == "proof_review"` 的行去核（其它档不归这条判据管：
    `proof` 由 `evidencebits.bit_evidence_gaps` 核，`cross_check`/`heuristic` 只需声明）。
    """
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("evidence_kind") or "") != PROOF_REVIEW_KIND:
            continue
        gap = proof_review_gap(root, row)
        if not gap["ok"]:
            out.append(gap)
    return out


def unverified_statement_refs(root: str | Path,
                              plans: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """攻坚计划的 `history` 里点名了哪些 `statement_id`、而 `verifications` 里没有对应行。

    ## 为什么这一条落在「攻」那一格（2026-10-19，接 V 的回路的收工侧）

    F 把那一轮的论证落成 `statements` 的一行之后，`statement_id` 会进
    `attack_plans.history`（`agent_f/step.py` 的 P3-6 落点），**M 在 `attack.status`
    里看得见它**。看得见不等于有人去审：真机里那一栏可以一直是"F 交了、没人签"，
    而收工门那一格照样绿 —— 因为「攻」此前只问"计划推进了没有"，不问"交出来的那一条
    后来有没有人看"。

    这一条把两件事接上：**history 里有 `statement_id` ⇒ `verifications` 里必须有它的一行**
    （`verify_proof` 的产物）。没有 ⇒ 调用方（`closing._check_acceptance`）把那一格记
    `unknown`（不是 `pass`）—— "没签"与"签了"在读数上必须分得开。

    三态：`checked=False` ⇒ 这一格没查成（读不到 `verifications/` 目录或坏行），
    **不是**"一条都没缺"。`missing` 里逐条给出 `plan_id` / `round` / `statement_id` /
    `why`（0 行 / 读不到 / 编号形态不对）。

    `signed` 是"那一行签住了第 3 位"（`signs_bit3`）—— 它**不**决定这一条的红绿
    （`有毛病` 也是一条"有对应行"），红绿由 `missing` 决定；这个读数留着是因为
    "有行但没签"与"有行且签了"是给人看的两种不同状态。
    """
    refs: list[dict[str, Any]] = []
    problems: list[str] = []
    for plan in plans:
        if not isinstance(plan, Mapping):
            continue
        for entry in (plan.get("history") or []):
            if not isinstance(entry, Mapping):
                continue
            sid = str(entry.get("statement_id") or "").strip()
            if not sid:
                continue
            ref: dict[str, Any] = {
                "plan_id": str(plan.get("plan_id") or ""),
                "round": entry.get("round"),
                "statement_id": sid, "rows": None, "signed": None, "why": "",
            }
            try:
                path = verification_ledger_path(root, sid)
            except VerificationError as exc:
                ref["why"] = f"命题号 {sid!r} 不是编号形态（{exc}）⇒ 查不到它那一份台账"
                refs.append(ref)
                continue
            if not path.is_file():
                ref["rows"] = 0
                ref["signed"] = False
                ref["why"] = (f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 不在盘上 ⇒ "
                              "这一条命题**一次审校都没落过**")
                refs.append(ref)
                continue
            rows, bad = JF.read_jsonl(path)
            if bad:
                problems.extend(f"{VERIFICATIONS_DIR}/{sid}.jsonl: {b}" for b in bad)
                ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 有读不出来的行：{bad[:3]}"
                refs.append(ref)
                continue
            ref["rows"] = len(rows)
            ref["signed"] = any(signs_bit3(r) for r in rows)
            if not rows:
                ref["why"] = f"`{VERIFICATIONS_DIR}/{sid}.jsonl` 是空文件 ⇒ 一次审校都没落过"
            refs.append(ref)
    missing = [r for r in refs if not r.get("rows")]
    return {
        "checked": not problems,
        "problems": problems,
        "refs": refs,
        "missing": missing,
        "total": len(refs),
        "note": ("plan 的 `history` 里有 `statement_id` ⇒ `verifications/<命题号>.jsonl` 里"
                 "必须有它的一行（派 V 的 `verify.verify_proof` 就会落）。`missing` 非空 ⇒ "
                 "「攻（攻坚推进）」那一格记 `unknown`（不是 `pass`）；`signed` 只是读数："
                 "「有行但没签」由审计期那一档（`proof_review_without_verification`）点名"),
    }


# ============================================================ 断言与所引证据：方向 / 同一份证据复用
#
# 这一节是 `specs/g.py` policy[7]（「引用一个与断言相反的证据行，比没有引用更坏」）
# 与 policy[9]（「同一份证据不能当第二份用」）两条义务的**机械判据本体**。
#
# 为什么落在 `verifications`（而不是在 `verify._check_7` 里直接写一份）：
# 同一条口径在写入期（`doc_tools.check_proofs`，2026-10-13 起就有一条"引否证当支撑"）
# 与审计期（`verify._check_7`）各读一次 —— 两处各写一份判据必然漂移，而漂移的形态是
# "写入期拦下的，审计期照样说没问题"（FC-03 禁止的形态）。落法与
# `weaker_than_evidence_gaps` 同源：判据本体只此一份，两个出口都调它。

#: `experiments.result` 里"方向"只有两档有值；`inconclusive` 没有方向。
#: 真身是 `schema.EXPERIMENT_RESULTS`，这里只把"相反"那一个取值点名。
REFUTES = "refutes"
#: `negation_kind` 里"已证否"那一档（受控词表真身是 `schema.NEGATION_KINDS`）。
DISPROVED = "disproved"


def opposite_direction_evidence(claim: Mapping[str, Any],
                                experiment: Mapping[str, Any]) -> dict[str, Any] | None:
    """这条断言引用这条实验时，方向是不是反的 —— 判据本体（纯读，`None` = 不反）。

    ## 判的是什么（可机械化的那一半）

    一条实验行自己的结论是 `result="refutes"`（连同 `negation_kind="disproved"`，
    这是 `schema.Experiment.validate` 强制的），意思是**"它检验的那条命题被证否了"**。
    一条正文断言把它列进 `citations` 当支撑时，台账上必须能读出"这条断言正是在说
    「我们证否了它」" —— 机械读法就是 `is_negative=True` 且
    `negation_kind="disproved"`（`doc_tools.check_proofs` 2026-10-13 的口径，
    真机现场：`projects/p6t2-research-20261012b` 的 claim-2 把 `exp:0002`
    （`result="refutes"`）列进 `citations` 当支撑，一路写库）。

    判据只需要两个字段：证据行的 `result` / `negation_kind`，断言的
    `is_negative` / `negation_kind`。**这两组字段都在 schema 里**，不需要新字段。

    ## 哪一半判不了（如实登记，不硬造）

    反方向的那一支 —— **断言登记成"已证否"、却引一条 `result="supports"` 的实验** ——
    **不归本判据管**。理由不是"懒得写"，而是它判不了：`supports` 是相对于**实验行
    自己的 `claim`** 说的，而一条否定型断言（例如「不存在这样的图」）完全可能由一条
    `supports` 的实验支持（实验检验的命题本身就是那句否定命题）。更常见的是
    `supports` 只是 `cross_check`（数值支持）——「我们未能证明 P」引一条数值支持 P 的
    实验并不矛盾，"数值支持"本来就不构成证明。要判它，必须让实验行
    声明"它检验的命题相对于这条正文断言的正负极性"（例如 `tests_claim_id` +
    `direction` 两格），那是 schema 改动，不是审计侧能单方面补的。
    同理，`result="refutes"` 引一条正面断言也只有在"实验检验的就是这条断言所说的命题"
    时才是真相反 —— 本判据把"引用关系"当成那个链接（与写入期、收工门同一口径）。

    ## 返回值

    不反 ⇒ `None`。反 ⇒ 一个 dict（`experiment_id` / `result` / 断言侧字段 / `why`），
    写入期与审计期各自决定怎么呈现（`problem` / `Issue`），**判定本身不重复**。
    """
    if str(experiment.get("result") or "") != REFUTES:
        return None
    if bool(claim.get("is_negative")) and str(claim.get("negation_kind") or "") == DISPROVED:
        return None
    eid = str(experiment.get("experiment_id") or "")
    return {
        "experiment_id": eid,
        "result": REFUTES,
        "claim_is_negative": bool(claim.get("is_negative")),
        "claim_negation_kind": str(claim.get("negation_kind") or ""),
        "why": (
            f"它引了 {('exp:' + eid) if eid else '这条实验'} 当支撑，而那条实验自己的结论是 "
            f"`result={REFUTES!r}`（否证）⇒ 一条否证被当成支撑用了。"
            "要么把这条断言改成否定型并写 `is_negative=True` + "
            f"`negation_kind={DISPROVED!r}`（「我们证否了它」），"
            "要么换一条真正支持它的证据；只在正文里解释「那只是脚本内部判据的问题」不算数 —— "
            "台账上它仍然是 refutes。"
        ),
    }


def _freeze(value: Any) -> Any:
    """把 `observations.data` 变成可比较的规范形（dict 的键序不参与同一性）。"""
    if isinstance(value, Mapping):
        return tuple(sorted((str(k), _freeze(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def evidence_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    """一条实验行的"证据身份"：同一份读数只该算一份证据。

    ## 为什么身份不能只是 `experiment_id`

    真机读数（`draft/39` §6.27 的 D39，T2 第 9 趟 `p6k`）：一个脚本被派了 9 次，
    claim 分别是 W(2)/W(3)/W(4)…，而每次都打印**逐字相同**的 `data`（30 顶点 / 度 3）
    —— 那始终是同一个图。台账上于是有 9 条 `result="supports"`，手稿把它们当
    9 份独立证据引：同一份读数被当成了九份。这 9 条的 `experiment_id` 各不相同，
    所以"按 `experiment_id` 判重"看不见它。

    ## 身份的定义（与 E 写入期那条 note 同一处）

    - 有 `observations.data`（非空）⇒ 同脚本（`code_hash`）+ 同 `data` 即同一份证据
      （`code_hash` 为空也照比：历史行没有哈希时，"同 data" 仍是唯一可比的读数）；
    - 没有 `data` ⇒ 退回到 `experiment_id`（同一行被引两次是同一份证据；
      两行都没有 data 时**不**合并 —— 那会靠猜）。

    这条定义此前只在 `agent_e.run_experiment._reused_evidence_note` 里，
    现在两边都读这一个函数（FC-03：同一件事不许有两份定义）。
    """
    obs = row.get("observations")
    data = dict(obs.get("data") or {}) if isinstance(obs, Mapping) else {}
    if data:
        return ("data", str(row.get("code_hash") or ""), _freeze(data))
    return ("row", str(row.get("experiment_id") or ""))


def one_evidence_used_twice(documents: Iterable[Mapping[str, Any]],
                            experiments: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """同一份证据被**同一份稿件**里的两条不同断言当独立证据用 —— 纯读。

    ## 判据（一条）

    把每份稿件的 `claims[].citations` 里的 `exp:` 引用按 :func:`evidence_identity`
    归组；同一组里出现 ≥ 2 个**不同的 `claim_id`** ⇒ 报一条。

    为什么是 warning 而不是 error（与 `opposite_direction_evidence` 的 error 不同）：
    同一份证据被两条断言引用**可以是正当的** —— 定理与它的推论、综述里复述同一条读数、
    两条不同表述压在同一次计算上。台账分不出"两条独立支撑"与"一份支撑被数了两遍"，
    所以它必须是**看得见的读数**，不是硬拦。硬拦会红掉合规稿件（本项目最忌的
    "判据过窄 ⇒ 红掉合规输入"），而完全不说又正是 D39 的形态。
    处置写进 `why`：是复现就在正文与实验行 `notes` 里说清，否则换一条真正独立的证据。

    ## 范围只在一份稿件内

    跨稿件复用同一份证据是正常的（综述与论文引同一条实验）。判据只在同一份 `documents`
    行内部比较 —— 那是"一条断言引一条实验行"这句话的作用域。

    ## 返回值

    `[{doc_id, claim_ids, experiment_ids, why}]`；空列表 = 不报（正常形态）。
    """
    exp_by_id: dict[str, Mapping[str, Any]] = {}
    for row in experiments:
        if not isinstance(row, Mapping):
            continue
        eid = str(row.get("experiment_id") or "")
        if eid:
            exp_by_id[eid] = row
    out: list[dict[str, Any]] = []
    for doc in documents:
        if not isinstance(doc, Mapping):
            continue
        doc_id = str(doc.get("doc_id") or "")
        groups: dict[tuple[Any, ...], dict[str, list[str]]] = {}
        for claim in doc.get("claims") or []:
            if not isinstance(claim, Mapping):
                continue
            cid = str(claim.get("claim_id") or "")
            if not cid:
                continue
            for cite in claim.get("citations") or []:
                kind, ref = T.citation_ref_parts(cite)
                if kind != "exp":
                    continue
                row = exp_by_id.get(ref)
                if row is None:
                    continue          # 悬空引用由 `dangling_citation` 报，不在这里重复
                group = groups.setdefault(evidence_identity(row),
                                          {"claim_ids": [], "experiment_ids": []})
                if cid not in group["claim_ids"]:
                    group["claim_ids"].append(cid)
                if ref not in group["experiment_ids"]:
                    group["experiment_ids"].append(ref)
        for group in groups.values():
            claim_ids = sorted(group["claim_ids"])
            if len(claim_ids) < 2:
                continue
            experiment_ids = sorted(group["experiment_ids"])
            evidence = " / ".join(f"exp:{eid}" for eid in experiment_ids)
            if len(experiment_ids) == 1:
                same = f"同一条实验行（{evidence}）"
            else:
                same = (f"{evidence} 是同脚本 + 同 `data` 的两次运行"
                        "（`observations.data` 逐字相同）")
            out.append({
                "doc_id": doc_id,
                "claim_ids": claim_ids,
                "experiment_ids": experiment_ids,
                "why": (
                    f"稿件 {doc_id} 的断言 {'、'.join(claim_ids)} 都把 {evidence} 当独立证据用，"
                    f"而它是同一份证据（{same}）⇒ 一条证据被算成了两份。"
                    "若这是复现（同一个对象被核了两次），请在正文与实验行的 `notes` 里"
                    "说清「这不是第二份独立证据」；否则换一条真正独立的证据。"
                ),
            })
    return out


def selftest() -> int:
    """最小自检：冷启动提示词只有对象、三态可判、签位条件、追加式编号。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="verifications_selftest_"))
    checks: list[tuple[str, bool]] = []
    prompt = cold_start_prompt("设 G 是群，则 c(G) ≤ 1。", "1. 由定义直接得到。",
                               readonly_facts="- stmt:0007 现状：猜想（第 2 位空）")
    checks.append(("提示词带命题与证明", "c(G) ≤ 1" in prompt and "由定义直接得到" in prompt))
    checks.append(("提示词带硬禁令", "易证" in prompt and "无依据的步骤" in prompt))
    # I12（冷启动）在这一层的判据是接口：拼提示词的函数只收字符串，
    # 没有任何 store / conductor / registry / session_root 参数 —— 于是"不给句柄"
    # 是结构性质，而不是"约定只读"（提示词里出现"没有 store 句柄"这几个字是说明，
    # 不是句柄本身；按子串判会把说明误判成句柄）。
    import inspect as _inspect

    params = set(_inspect.signature(cold_start_prompt).parameters)
    checks.append(("接口上没有句柄参数",
                   not (params & {"store", "conductor", "registry", "session_root"})))
    bad = parse_verdict('{"verdict": "有毛病", "defect_step": 2, "findings": '
                        '[{"level": "error", "step": 2, "kind": "无依据", "detail": "第 2 步"}]}')
    checks.append(("三态解析", bad["verdict"] == "有毛病" and bad["defect_step"] == 2))
    row = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=bad)
    # 编号宽度**不许写死**（2026-10-14 业主裁定：4 位 → 6 位）：发号点是
    # `next_verification_id` 的 `f"v-{S.format_id(...)}"`，所以断言也从
    # `schema` 取形态。旧写法写死 `"v-0001"`，宽度一改这条自检就红 ——
    # 那是断言过期（`v-0001` 这一格属于旧四位号），不是发号器坏了。
    checks.append((f"编号从 v-{S.format_id(1)} 起（六位；旧四位号读侧兼容）",
                   row["verification_id"] == f"v-{S.format_id(1)}"))
    checks.append(("有毛病不签第 3 位", bit3_payload(row) == {}))
    good = parse_verdict('{"verdict": "成立", "findings": []}')
    ok_row = record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    checks.append(("成立才签第 3 位", bit3_payload(ok_row).get("reviewed") is True))
    checks.append(("追加式（两行）", len(list_verifications(root, limit=None)[0]) == 2))
    checks.append(("limit=0 是零条、limit=None 才是全量",
                   list_verifications(root, limit=0)[0] == []
                   and len(list_verifications(root, limit=None)[0]) == 2))
    try:
        parse_verdict("我不确定")
        unparsable = False
    except VerificationError:
        unparsable = True
    checks.append(("没查成抛错（不冒充看不出来）", unparsable))
    for name, good_ in checks:
        print(f"  [{'PASS' if good_ else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


if __name__ == "__main__":  # pragma: no cover - 自检入口
    raise SystemExit(selftest())
