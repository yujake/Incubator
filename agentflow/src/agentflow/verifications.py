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
