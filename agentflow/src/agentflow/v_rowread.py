# -*- coding: utf-8 -*-
"""行轴与签资格（轴只由秘书给）。

2026-11-20（VERSPLIT2）：`v_rowread.py` 是从 `verifications.py` 搬出的 22 块 / 709 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

import json
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）
from .proofloc import DEFAULT_PROOF_NO  # canonical 证明号只有一个出处（`proofloc`）


def secretary_judge_cell(secretary_judge: Mapping[str, Any] | None) -> dict[str, Any]:
    """把调用方给的判定归一成台账那一格；没给 ⇒ :data:`NO_SECRETARY_JUDGE`（不是省掉）。

    两个写口（:func:`record_verification` / :func:`record_pending_sign`）共用这一处：

    - 没给 / 给了空 Mapping ⇒ "未判成"那一格（无条件落盘，读侧因此分不出
      "新行没问过秘书"与"老行没有这一格"—— 前者被读成未判成，后者才走历史兼容）；
    - 给了 ⇒ 轴照写，但只有 `checked` 为真时轴才写得进去：`axis=clean` 与
      `checked=False` 同时出现是"问过、没判成"，那一档必须落成空轴 ——
      否则一行"没判成"会带着一条干净的轴过 `row_signable`。

    `record_verification` 另把 `decision` / `reason` 截短（老口径），本函数只归一轴与
    `checked`，其余键由调用方照原样带着（`basis` / `source` / `defect_step` 都在里头）。
    """
    if not isinstance(secretary_judge, Mapping) or not secretary_judge:
        return dict(NO_SECRETARY_JUDGE)
    out = dict(secretary_judge)
    checked = bool(out.get("checked"))
    axis = str(out.get("axis") or "").strip()
    out["axis"] = axis if (checked and axis in SECRETARY_JUDGE_AXES) else ""
    out["checked"] = checked
    return out


def list_verifications(root: str | Path, *, statement_id: str = "",
             limit: int | None = 50) -> tuple[list[dict[str, Any]], list[str]]:
    """列验证台账（可按命题过滤）；返回 `(行, 坏行说明)` —— 坏行照实报出，不静默跳过。

    ## 收录之后，已认领的 pending 行算在这本条命题的台账里（2026-11-10）

    改前只读 `verifications/*.jsonl` 顶层：没号先签那一档的行落在
    `verifications/pending/<正文 sha>.jsonl`，B 收录时只在那一行上回写 `statement_id`
    （`vsigns.bind_pending_claim`），文件不搬 ⇒ 收录之后
    `list_verifications(ws, statement_id=<号>)` 仍是 0 行：盘上有签、行上
    `reviewed_by.evidence` 也指着它，而"这条命题有谁审过"读出来是空的。现在这一口
    把已认领的 pending 行并进来（口径见 :func:`_claimed_pending_rows`）：
    未认领的行仍不属于任何命题，不会被算到任何号头上。

    ## 返回行混着两处：看 id 前缀（2026-11-10 业主确认的口径）

    这一口返回的行里，已认领的 pending 行会一起出现，它们的 `verification_id` 以
    `u-` 开头；顶层在册台账（`verifications/<号>.jsonl`）的行是 `v-` 开头。
    这是要的口径 ——「一条命题有谁审过」只读这一处，读的人不必再自己去 pending
    目录里翻。只要顶层在册行、不要 pending 行的人，请自己按 `u-` 前缀过滤
    （或直接读 :func:`verification_ledger_path`）；不要把混着 `u-` 行当成 bug。

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
    # 已认领的 pending 行（物理位置仍是 `verifications/pending/<sha>.jsonl`）：
    # 收录之后它们属于那一条命题，读侧并入同一份在册台账（口径见
    # `_claimed_pending_rows`；未认领的行不进来）。
    claimed, claimed_bad = verifications._claimed_pending_rows(root, statement_id=statement_id)
    problems.extend(claimed_bad)
    out.extend(claimed)
    out.sort(key=lambda r: (str(r.get("statement_id") or ""), str(r.get("verification_id") or "")))
    if limit is None:
        return out, problems
    return out[-max(0, int(limit)):] if int(limit) > 0 else [], problems


def ledger_reading(root: str | Path, *, store: Any = None) -> dict[str, Any]:
    """验证台账的"真身"读数：文件是正本，同名的数据表从来不存在（一处真身）。

    ## 为什么需要这一格（真机 sylow3，2026-10-24 的缺口二）
    V 的产物是工作区里 `verifications/<命题号>.jsonl` 的那些行（`schema.TABLES` 里
    没有 `verifications` 这张表：`store.rows("verifications")` 直接抛「未知表」）。
    于是一次运行结束时盘上有 `verifications/000000.jsonl` ... `000006.jsonl` 七份、
    十四行签，而按"数据表"那一面看（`data/` 目录里没有 `verifications.json`）是 0 行。
    两处口径从来没有被任何一格对起来过：文件面是 7 份、表面是 0 行，收工门、对应表、
    证据面各读各的一边 ⇒ 读的人只会看到"没有签"。

    这一格把这件事写成一次可机器读的读数，三态（不猜）：
    - `source`：这一档的正本永远是 `verifications/*.jsonl`（文件）。同名数据表
      `is_store_table=False`，`rows=None`（不是 0 —— "这张表不存在"与"表是空的"是两件事）。
    - `mirror`：如果盘上真有 `data/verifications.json`（派生副本 / 别人拷进去的），
      就逐条按 `verification_id` 对账；`agrees` 只有 `True` / `False` / `None` 三档，
      `None` = 没有副本可对（"没查"不是"对上了"）。
    - `problems` 非空 ⇒ 两面分家，`why` 说清差在哪几条。

    返回（键集合固定，读的人不必猜）：
    `checked` / `source` / `files` / `file_names` / `rows` / `claimed_pending` /
    `signed` / `signed_statements` / `table` / `mirror` / `agrees` / `problems` / `why` /
    `next_step`。

    `claimed_pending`（2026-11-10）：`rows` 里有几行是收录之后并入的 pending 行
    （物理上还在 `verifications/pending/`，见 :func:`_claimed_pending_rows`）。
    没有它，"文件 0 份、3 行"看起来像读数坏了；有了它，读的人知道那 3 行住在哪。
    """
    root_p = Path(str(root))
    out: dict[str, Any] = {
        "checked": False,
        "source": f"{VERIFICATIONS_DIR}/*.jsonl",
        "files": 0,
        "file_names": [],
        "rows": 0,
        "claimed_pending": 0,
        "signed": 0,
        "signed_statements": [],
        "table": {"name": VERIFICATIONS_DIR, "is_store_table": False, "rows": None,
                  "why": ""},
        "mirror": {"path": f"data/{VERIFICATIONS_DIR}.json", "present": False,
                   "rows": None, "agrees": None},
        "agrees": None,
        "problems": [],
        "why": "",
        "next_step": "",
    }
    # ---- 文件面（正本）
    base = verifications_dir(root_p)
    if not base.is_dir():
        out["why"] = (f"`{VERIFICATIONS_DIR}/` 不在盘上 ⇒ 这个工作区还没有一次签过"
                      "（这是「零签」，不是「读不到」：目录在不在与行读不读得出来是两件事）")
        out["next_step"] = "派 V 走 `verify.verify_proof`（产物就是那个目录下的一行）"
        _ledger_table_state(out, store)
        return out
    rows, bad = list_verifications(root_p, limit=None)
    out["checked"] = True
    out["file_names"] = sorted(p.name for p in base.glob("*.jsonl"))
    out["files"] = len(out["file_names"])
    out["rows"] = len(rows)
    #: 收录之后并入的 pending 行（`verification_id` 的 `u-` 前缀是这一档的唯一记号；
    #: 在册台账的行是 `v-`）。计数只为让"文件 0 份、N 行"这一形态读得懂。
    out["claimed_pending"] = sum(
        1 for r in rows
        if str(r.get("verification_id") or "").startswith(PENDING_PREFIX))
    signed = signed_rows(rows)
    out["signed"] = len(signed)
    out["signed_statements"] = sorted({_statement_id_of(r) for r in signed if _statement_id_of(r)})
    out["problems"] = list(bad)
    # ---- 表面：同名 store 表存不存在（"不存在"不许折成"0 行"）
    _ledger_table_state(out, store)
    # ---- 派生副本（如果有）
    mirror = dict(out["mirror"])
    mirror["rows"], mirror["present"] = verifications._ledger_mirror_rows(root_p)
    if mirror["present"] and isinstance(mirror["rows"], list):
        want = {str(r.get("verification_id") or "") for r in rows}
        have = {str(r.get("verification_id") or "") for r in mirror["rows"]}
        mirror["count"] = len(mirror["rows"])
        if want == have:
            mirror["agrees"] = True
        else:
            mirror["agrees"] = False
            mirror["missing_ids"] = sorted(want - have)
            mirror["extra_ids"] = sorted(have - want)
            out["problems"].append(
                f"`data/{VERIFICATIONS_DIR}.json` 与文件台账分家：文件 {len(want)} 条、"
                f"表 {len(have)} 条（文件有表没有的是 {mirror['missing_ids'][:6]}、"
                f"表有文件没有的是 {mirror['extra_ids'][:6]}）")
        out["agrees"] = mirror["agrees"]
    elif mirror["present"]:
        mirror["agrees"] = None
        out["problems"].append(
            f"`data/{VERIFICATIONS_DIR}.json` 在盘上但读不出来 ⇒ 这一面没查成"
            f"（{mirror.get('why') or '格式不认'}）")
    out["mirror"] = mirror
    if out["files"] and out["signed"] == 0:
        out["problems"].append(
            f"`{VERIFICATIONS_DIR}/` 有 {out['files']} 份台账、{out['rows']} 行，"
            "而没有一行签「成立」⇒ 审过但一次都没签住（这是读数，不是读不到）")
    if not out["problems"]:
        out["why"] = (f"文件台账 {out['files']} 份、{out['rows']} 行，"
                      f"其中签「成立」且无未解决 error 的 {out['signed']} 行"
                      f"（覆盖 {len(out['signed_statements'])} 条命题）")
        if out["claimed_pending"]:
            out["why"] += (f"；其中 {out['claimed_pending']} 行是收录之后并入的 pending 行"
                           f"（物理位置 `{VERIFICATIONS_DIR}/{PENDING_DIR_NAME}/`，"
                           "行上已回写 statement_id —— 口径见 `list_verifications`）")
        if not out["table"]["is_store_table"]:
            # 表面那一格不是「0 行」，而是「这张表不存在」：读的人要能从这一格直接知道
            # 该去读文件（改前这一步没有任何落点，于是「表 0 行」被当成了「没有签」）。
            out["why"] += "；" + str(out["table"]["why"])
    out["next_step"] = (
        "读验证台账只走这一个口（`verifications.list_verifications` / 本函数）："
        f"正本是 `{VERIFICATIONS_DIR}/<命题号>.jsonl`；要找「表」的那个人应当读"
        "`rows` / `signed` 这两格，而不是去找一张不存在的 `verifications` 表")
    return out


def _statement_id_of(row: Mapping[str, Any]) -> str:
    """一行签名属于哪条命题（正名 `stmt_id`，老行读 `statement_id`）。"""
    return str(row.get("stmt_id") or row.get("statement_id") or "")


def _ledger_table_state(out: dict[str, Any], store: Any) -> None:
    """同名数据表那一面的三态：它不是 store 表（`rows=None`），不是「0 行」。"""
    table = dict(out.get("table") or {})
    in_schema = False
    try:  # 只在拿得到 schema 时判；拿不到就如实说没查成
        in_schema = VERIFICATIONS_DIR in S.TABLES
    except Exception:  # noqa: BLE001 - 读不到 schema 时按"不在表里"继续，理由写在 why 里
        in_schema = False
    table["is_store_table"] = bool(in_schema)
    if in_schema:
        table["why"] = f"`{VERIFICATIONS_DIR}` 是 store 表 ⇒ 读表即可（与文件对账）"
        if store is not None:
            try:
                table["rows"] = len(list(store.rows(VERIFICATIONS_DIR)))
            except Exception as exc:  # noqa: BLE001 - 读不到表就是"没查成"
                table["why"] += f"；但这一次没读出来（{type(exc).__name__}: {exc}）"
        out["table"] = table
        return
    table["rows"] = None
    table["why"] = (
        f"`{VERIFICATIONS_DIR}` 不是一张 store 表（`schema.TABLES` 里没有它）⇒ "
        f"`store.rows(\"{VERIFICATIONS_DIR}\")` 只会抛「未知表」，"
        f"按表读的那一面永远读到 0 行；正本是工作区里的 `{VERIFICATIONS_DIR}/"
        "<命题号>.jsonl`。这一格给的就是「表不存在」（`rows=None`），"
        "而不是「表是空的」（那会是 0）")
    out["table"] = table


def _ledger_mirror_rows(root_p: Path) -> tuple[Any, bool]:
    """盘上有没有 `data/verifications.json`（派生副本）；有就把它读成行列表。"""
    path = root_p / "data" / f"{VERIFICATIONS_DIR}.json"
    if not path.is_file():
        return None, False
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - 读不出来如实交给调用方
        return {"why": f"{type(exc).__name__}: {exc}"}, True
    rows = doc.get("rows") if isinstance(doc, Mapping) else doc
    if not isinstance(rows, list):
        return {"why": "文件里没有 rows 数组"}, True
    return [dict(r) for r in rows if isinstance(r, Mapping)], True


def signing_gate_problem(row: Mapping[str, Any]) -> str:
    """台账那一行记下的"引用核实没查成"那一档（空串 = 没记，或记的是查成了）。

    为什么单独一格：`problem`（依赖台账读不出来）不是 `citation_checks` 里的任何一档
    —— 它是"这一档没查成"，而空数组只说明"没有条目可核"。两者折平之后，"没查成"就
    长成了"没有引用"（那一版 `signs_bit3` 只读 `citation_checks`，于是这种行照样签）。
    历史行没有 `citation_gate` 这一格 ⇒ 空串，读数逐字不变。
    """
    gate = row.get("citation_gate")
    if not isinstance(gate, Mapping):
        return ""
    return str(gate.get("problem") or "").strip()


def read_verdict(row: Mapping[str, Any]) -> str:
    """这一行上 V 写下的结论陈述（原样；p247 起不做任何折档）。

    ## 它只做一件事：取字段
    业主 2026-11-06 第三次收紧逐字：「V 的判词只是陈述」「不做折档」。所以这里
    原样返回台账上的 `verdict` 字符串（包括历史值 `看不出来`），不把它折成
    `成立` 或 `有毛病`、也不据此产生轴。轴只有一处：:func:`secretary_axis`。

    ## 历史行（不改写、也不折）
    老行上那四个字仍是原始读数（`list_verifications` 原样返回）。`read_verdict`
    把它们读出来是给人复核"它当年写的到底是什么"的；它们不参与计票、不参与签发
    （见 :func:`_hold_run_lengths` 与 :func:`row_signable`）。

    ## 为什么还留这个函数
    读数的展示面（`review_standing` / `bit3_payload` / 回执）要能逐字回放 V 写的那句话。
    判断面不再经过它 —— 判断面问 :func:`secretary_axis`。
    """
    return str(row.get("verdict") or "")


def row_signable(row: Mapping[str, Any]) -> bool:
    """行局部那一半：这一行自己够不够格签五元位第 3 位。

    ## 轴只认秘书给的（业主 2026-11-06 第三次收紧 · p247）
    第一句是 `secretary_axis(row) == "clean"`。这是轴（clean / fault）的唯一真源：
    由 V 的秘书读 V 的回复后语义判定并写清依据（`secretary_judge.axis`）。
    本函数不读 `verdict` 的字面 —— 按业主原话，「V 的判词只是陈述」，
    「不许按字面直接定轴」。没有轴的行（老行 / 没判成 / 秘书不在场）一律 False：
    fail-closed，不是"没问题"。

    再加三条机械闸（它们不是轴，也不改变轴）：
    - 未解决的 error：引用核实 / 依赖面审计落进来的 error；
    - `citation_gate.problem`（`:func:`signing_gate_problem`）：依赖台账读不出来，
      "没查成"与"核过、没有引用"必须分开；
    - 引用核实里挡签的档（`stronger` / `unrelated` / `inadmissible` / `unknown`）。

    ## 为什么它与 :func:`signs_bit3` 是两个名字而不是一个（业主 2026-10-29）
    「连续 3 次」这一条读不到：它要数台账尾部那几行（:func:`consecutive_holds`）。
    行局部谓词自己读台账就会造出"位上说签了、台账只签一次"的第二份账（`draft/124` §一②），
    所以两条轴在这里分开：本函数 = 这一行自己的资格；:func:`signs_bit3` =
    本函数 且 调用方递进来的连续读数。函数名刻意不同，免得读的人以为
    `signs_bit3(row)` 少了什么参数只是"默认值不同"。
    """
    if verifications.ledger_axis(row) != "clean":
        return False
    if int(row.get("unresolved_errors") or 0) != 0:
        return False
    if signing_gate_problem(row):
        return False
    return not citation_blocks(row)


def historical_axis(row: Mapping[str, Any]) -> str:
    """已废：历史兼容轴 —— 2026-11-06 裁定 2 起不再给轴，一律空串。

    ## 改前它做什么（这条缺陷的后半截）
    p247 到裁定 2 之间，这一格对"没有 `secretary_judge` 这一格"的行按 `verdict` 的
    字面给轴：`成立` ⇒ `clean`、`有毛病` ⇒ `fault`、其余（含历史值 `看不出来`）⇒ 空。
    本意是"让老台账读得出"，但它的判据是 `verdict` 这个字符串，而写口当时是
    条件写入（不给判定就根本不落这一格）—— 于是它同时成了第二条写路的第二半：

        `record_verification(verdict={"verdict": "成立"})`（一次秘书都不问）
        ⇒ 这一格不落盘 ⇒ 本函数按字面给 clean
        ⇒ `row_signable` = True、`_hold_run_lengths` 计一票
        ⇒ 三次这样的写 ⇒ `consecutive_holds.streak = 3` ⇒ 第 3 位被签住

    那就是业主说的"绕过秘书登记才是缺陷"，而且绕过去之后能签（现场读数见
    `temp/probe-secretary-census/probe_bypass_sign.py` 与
    `tests/test_v_axis_comes_from_the_secretary.py::test_l_*`）。

    ## 现在
    与 :func:`secretary_axis` 合流：没有那一格 ⇒ 空轴 = unjudged
    （由 :func:`ledger_axis` 的调用方按"不计票、不清零、不签发"处置）。函数名与这一格
    保留下来，是因为它是"这条按字面定轴的规则曾经存在"的唯一落点，也是这条裁定
    在代码里的墓碑：下一个想在读侧给老行补一条字面轴的人，改的就是这里。
    要看"这一行为什么没有轴"，读 :func:`axis_reading`。
    """
    return ""


def axis_reading(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一行的轴从哪来（纯读数，不参与判定；裁定 2 要的那句"这行没有秘书判定"）。

    `source` 三档：
    - `secretary`：这一行有 `secretary_judge` 这一格、且轴是词表里的两档之一；
    - `secretary_unjudged`：有那一格、但 `checked` 为假 / 轴读不出来
      （"问过、没判成"，框架失败，等判定接上之后重签）；
    - `none`：连那一格都没有 —— 老台账行，或者一次没有经过秘书的写入。
      这一档从前会被按 `verdict` 字面读成 clean，现在不算轴。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    axis = verifications.secretary_axis(row)
    if axis:
        return {"axis": axis, "source": "secretary", "why": f"轴由秘书给：{axis}"}
    if isinstance(got, Mapping):
        return {"axis": "", "source": "secretary_unjudged",
                "why": ("这一行的秘书判定没查成（checked=False 或轴读不出来）"
                        "⇒ 不计票、不清零、不签发")}
    return {"axis": "", "source": "none",
            "why": ("这一行没有 `secretary_judge` 这一格 ⇒ 没有秘书判定"
                    "（V 的判词只是陈述，不是轴）⇒ 不计票、不清零、不签发")}


def ledger_axis(row: Mapping[str, Any]) -> str:
    """这一行的轴：只认 `secretary_judge.axis`（裁定 2 起不再有字面回退）。

    没有这一格 / 轴读不出来 ⇒ 空串 = unjudged。见 :func:`historical_axis`（墓碑）与
    :func:`axis_reading`（读数）。
    """
    return verifications.secretary_axis(row)


def secretary_axis(row: Mapping[str, Any]) -> str:
    """这一行台账上的秘书判定轴（写侧 `SECRETARY_JUDGE_AXES`；没有这一格 ⇒ 空串）。

    只有写侧那两格（`clean` / `fault`）；其余一律空串。
    空串 = "这一行没有轴"（老行没有这一格 / 这一趟没查成 / 秘书不在场 / 老行上那个
    已取消的轴名）。读侧怎么处置它，由调用方那一条纪律决定：:func:`_hold_run_lengths`
    对"有这一格、但轴读不出来"的行是既不算票、也不清零（与"没有这一格"刻意分开 ——
    读不出轴 ≠ 判过 clean，`tests/test_v_sign_gate_streak.py` 的 z2(c) 钉着这条 fail-closed）。

    2026-11-02（追加裁定：那一档连历史兼容读也不留）：改前这里还认一个历史轴名
    （`SECRETARY_JUDGE_HISTORICAL_AXES = ("unsure",)`，2026-10-30 之前写下的行里有它）。
    那个常量与这一支一起删了 —— 老行上的那个值现在读出来是空轴，"那一档"在读侧不再有
    任何自己的位置：`_hold_run_lengths` 里也没有它的分支了（改前那条分支的结果与
    "轴读不出来"那条通用纪律逐字相同，删掉它等于删掉"承认那一档存在"的最后一行字）。

    取了词表外的值也归空串。那条保护落在写侧：`Secretary.judge` 对词表外的答法判
    `checked=False`（没查成），于是读侧看到的是"问过、没判成"那一档（既不算票也不清零），
    而不是"轴读不出来但算过了"。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return ""
    axis = str(got.get("axis") or "").strip()
    return axis if axis in SECRETARY_JUDGE_AXES else ""


def secretary_judged(row: Mapping[str, Any]) -> bool:
    """这一行的秘书判定是"判过了"还是"没判成"（`checked` 那一格；没有 ⇒ False）。

    为什么要单独一个读口（业主 2026-10-30）：没有这一格的老行与"判了、但没查成"的行
    长得不一样。p247 起两者的处置相同（都没有轴 ⇒ 不算票、也不清零），但读数仍必须分得开：
    "从没问过秘书"（老行）与"问过、没判成"（框架失败）是两件事。
    读侧只认这一格，不许自己再写一遍 `secretary_judge.checked` 的取值路径。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return False
    return bool(got.get("checked"))


def secretary_unjudged(row: Mapping[str, Any]) -> bool:
    """这一行写着"问过秘书、没判成"（有那一格、但 `checked` 为假）。

    与"没有那一格"（从没问过 / 老行）刻意分开：前者是这一趟的框架失败（业主
    2026-10-30 第三次裁定：没查成不是一种判定），它在连续计数里既不算票、也不清零；
    后者按"没判过"计入连续（:func:`_hold_run_lengths`）。两者必须分得开 —— 否则
    "这一趟没查成"会被读成"这一份还没判过"，而处置完全不同（前者等判定接上之后重签，
    后者就是正常的第几票）。
    """
    got = row.get(SECRETARY_JUDGE_KEY)
    if not isinstance(got, Mapping):
        return False
    return not bool(got.get("checked"))


def _streak_number(streak: Any) -> int | None:
    """把"连续读数"归一成一个整数；`None` = 这一档没有可用的读数。

    接受三种来路（都是同一件事的不同载体，不另立判据）：
    - `consecutive_holds` 的返回值（dict）：`checked` 为假 ⇒ `None`（没查成不是 0 次）；
    - 一个整数（已经数过的连续次数）；
    - `None` / 其它任何东西 ⇒ `None`（没有读数，与"读到 0"不同）。
    """
    if isinstance(streak, Mapping):
        if not bool(streak.get("checked")):
            return None
        try:
            return int(streak.get("streak") or 0)
        except (TypeError, ValueError):
            return None
    if isinstance(streak, bool) or streak is None:
        return None
    try:
        return int(streak)
    except (TypeError, ValueError):
        return None


def streak_ok(streak: Any, need: int | None = None) -> bool:
    """连续读数够不够发签（没读数 ⇒ 不够：fail-closed）。

    为什么 `None` 不许当"够"：`signs_bit3` 是本仓唯一的签字硬闸，而"调用方忘了传连续
    读数"与"连续次数够了"必须分得开。默认放行的话，任何一处漏传都会静默退回
    "一次成立就发签"—— 那正是这一条口径要取消的东西，而盘上不会有任何读数报它。

    `need=None` = 门槛现读 `SIGN_STREAK_NEED`（2026-10-30 改）。改前这里是
    `need: int = SIGN_STREAK_NEED` —— 默认参数在导入期求值，等于把门槛的第二个副本
    钉进了签字闸：门槛一旦不是 3（`agent_v.core.review_pass_bound` 的负控就把门槛
    临时打成 1 与 5），秘书那一端按新值判"够"，这一端按旧值判"没到门槛" —— 同一个门槛
    给出两个数，而"发签没落成"这句理由会把它说成"还差次数"。默认参数不是配置，它是一次
    快照；门槛要现读。
    """
    got = _streak_number(streak)
    if got is None:
        return False
    limit = int(verifications.SIGN_STREAK_NEED) if need is None else int(need)
    return got >= limit


def signs_bit3(row: Mapping[str, Any], *, streak: Any = None) -> bool:
    """这一行能不能签五元位第 3 位：行局部资格 且 连续次数够。

    `streak`（业主 2026-10-29）是台账派生的连续成立次数，三种载体见
    :func:`_streak_number`；不给就不签（fail-closed，理由见 :func:`streak_ok`）。

    为什么连续次数是入参而不是在这里现读台账：本函数是行局部谓词（被一批
    "手里只有一行"的地方调用，`numericproof` / `_gap_from_pending` / 各处读数），
    拿不到可靠的行序。硬塞一次读盘会让"这一行"与"它的位置"两件事在每个调用点各算一遍
    ——`draft/124` §一② 点名的那种第二份账就是这么长出来的。

    历史行（没有 `secretary_judge` 这一格）不受影响：连续计数把它们当"没判过"（计入），
    与这条口径上线之前的读数逐字相同。
    """
    if not row_signable(row):
        return False
    return verifications.streak_ok(streak)


def bit3_payload(row: Mapping[str, Any], *, streak: Any = None) -> dict[str, Any]:
    """把一行审校翻成五元位第 3 位那份读数（交给 `evidencebits.bits_of`）。

    签不了（`有毛病` / 有未解决 error / 引用核实挡签 / 连续次数不够）⇒ 返回 `{}`
    （第 3 位保持空）—— 这不是"忘了写"，是"没签"。`streak` 与 :func:`signs_bit3` 同义。
    老行上的 `看不出来` 不在这张"签不了"的清单里：它按
    :func:`read_verdict` 读成 `成立` ⇒ 只要连续次数够，它签得住（2026-11-02 追加裁定）。

    凭据里带 `proof_no` 与 `proof_sha256`（2026-10-22）：读侧要拿它们回答"位上说审过的
    那一份，还是不是现在这一份"（`evidencebits.bits_from_row` 与收工门的 R10 都读这两格）。
    """
    if not signs_bit3(row, streak=streak):
        return {}
    sid = str(row.get("stmt_id") or row.get("statement_id") or "")
    return {
        "reviewed": True,
        "reviewed_by": {
            "verifier": str(row.get("verifier") or "V"),
            "verification_id": str(row.get("verification_id") or ""),
            "round": row.get("round"),
            #: 凭据上记的是 V 写下的那句陈述（:func:`read_verdict` 原样取字段，不折档）；
            #: 轴的读数在下一格（p247：`reviewed_by.axis` 才是判定凭据，`verdict` 只是原话）。
            "verdict": read_verdict(row),
            "axis": verifications.ledger_axis(row),
            "evidence": f"verifications/{sid}.jsonl#"
                        f"{row.get('verification_id')}",
            "findings": list(row.get("findings") or []),
            "proof_no": proof_no_of(row),
            "proof_sha256": str(row.get("proof_sha256") or ""),
        },
    }


def _already_signed_locator(reviewed_by: Mapping[str, Any],
                            per: Mapping[int, bool],
                            sha_by: Mapping[int, str], no: int) -> str:
    """「这一位签过」能不能定位到一次具体签名（空串 = 判不了）。

    ## 为什么裸布尔不够（业主 2026-11-04 裁定 · 乙-11）

    `bits.reviewed=True` 是写侧留下的一个布尔。有台账的行由台账现算
    （`review_standing`）；而 `bit3_already_signed` 是 V 的短接判据 —— 它若拿一个
    没有任何定位凭据的裸布尔说"已经签过"，V 就不会再读一眼、直接返回
    `signed_bit3=True`。可定位 = `reviewed_by` 里有 `verification_id` 或
    `proof_sha256`，或逐条表（`reviewed_by_proof` / `reviewed_sha_by_proof`）里
    至少一条「为真且有 sha」。四者都没有 ⇒ 判不了、按没签过处理（照常送审）。
    这与 `closing._review_locator` 是同一把尺（那边早就是这么判的），只是这一格
    不 import closing（会成环）。
    """
    by = dict(reviewed_by or {})
    vid = str(by.get("verification_id") or "").strip()
    if vid:
        return f"verification_id={vid}"
    sha = str(by.get("proof_sha256") or "").strip()
    if sha:
        return f"proof_sha256={sha[:12]}"
    own = str((sha_by or {}).get(no) or "").strip()
    if own:
        return f"proof_sha256={own[:12]}"
    for n, ok in (per or {}).items():
        if not ok:
            continue
        got = str((sha_by or {}).get(n) or "").strip()
        if got:
            return f"proof_sha256={got[:12]}"
    return ""


def bit3_already_signed(row: Mapping[str, Any], *, proof_no: Any = DEFAULT_PROOF_NO,
                        proof_text: str = "") -> dict[str, Any]:
    """命题行上这一份证明的第 3 位是不是已经为真（纯读；2026-10-31）。

    ## 为什么要有这一格
    一条已经签过的命题不该再被送审。真机冒烟（工作区 `projects/abelian-smoke-20261030c`）
    的 `verifications/000001.jsonl` 有 12 行、全是同一份正文（同一个 `proof_sha256`）：
    v6–v8 三转 clean 之后第 3 位已经翻真，v9–v12 却还在被送审，其中 v10 被判成 fault
    —— 读侧（`agent_loop.v_rejections_digest` → `deliver_v_verdicts`）把那一转当成
    「有毛病要打回」，F 于是被叫去改一份已经签过的证明。判据落在写侧这一格：
    位已经为真 ⇒ 这一趟没有可做的审校（调用方据此短接，见 `AgentV.verify_proof`）。

    ## 它读什么、不读什么
    只读命题行（`statements` 那一行）上的五元位，并且现算
    （`evidencebits.bits_from_row`）：于是「签的是旧版正文」那一档在这里已经读成没签
    —— 改稿之后仍然会重审，那正是要的。不读台账、不读模型、不写任何东西：
    台账回答"这一签是怎么来的"，而"这一位现在是不是真的"只有命题行能回答。

    ## 逐条证明（`#p2` 不许借 `#p1` 的光）
    有逐条表（`bits.evidence.reviewed_by_proof`）时按证明号读：`#p2` 那条是假 ⇒ 不短接
    （哪怕汇总位 `bits.reviewed` 因为 `#p1` 为真）。没有逐条表（历史行 / 只翻汇总位的
    写者）⇒ 汇总位与 `reviewed_by` 是唯一凭据，此时按 `reviewed_by.proof_no` 判
    「签的是哪一份」；那一格也没有 ⇒ 按 canonical 读（老数据不带证明号）。

    ## 无可定位的凭据 ⇒ 不短接（业主 2026-11-04 裁定 · 乙-11）
    位写着真、而 `reviewed_by` 里既没有 `verification_id` 也没有 `proof_sha256`、
    逐条表里也没有任一条「为真且有 sha」⇒ 判不了，`signed=False`，照常送审。
    旧行 / repair / 手改行里可能只剩一个裸布尔；不拿它当"已经签过"。

    ## 返回（键集合固定；判不了也照样给全）
    `signed` / `proof_no` / `proof_sha256` / `reviewed_by` / `bits` / `why`。
    `signed=False` 的 `why` 写清是哪一档（位没翻 / 签过但正文改过 / 签的是别的证明 /
    没有命题行 / 证明号认不出 / 位没有可定位的凭据），读的人不必从几个假值里反推。
    """
    from . import evidencebits as _EB   # 惰性：与 `_reviewed_statement_row` 同一条纪律

    out: dict[str, Any] = {
        "signed": False, "proof_no": DEFAULT_PROOF_NO, "proof_sha256": "",
        "reviewed_by": {}, "bits": {}, "why": "",
    }
    if not isinstance(row, Mapping) or not row:
        out["why"] = "没有命题行 ⇒ 判不了「这一位签过没有」"
        return out
    no = as_proof_no(proof_no)
    if no < 1:
        out["why"] = f"证明号认不出：{proof_no!r}"
        return out
    out["proof_no"] = no
    bits = _EB.bits_from_row(row)
    out["bits"] = bits
    out["reviewed_by"] = dict((bits.get("evidence") or {}).get("reviewed_by") or {})
    sha_now = _sign_sha(proof_text) if str(proof_text or "").strip() else ""
    out["proof_sha256"] = sha_now
    if not bits.get("reviewed"):
        raw = row.get("bits") if isinstance(row.get("bits"), Mapping) else {}
        if raw.get("reviewed"):
            # 位在盘上写着真、读侧却现算成假：那是「签过、但签的不是现在这一份正文」
            # （`evidencebits._stale_review_cleared`）。它必须照常重审，不许短接。
            out["why"] = ("命题行上那一位写的是真，但那一签盖住的不是现在这一份正文"
                          "（读侧按过期现算成假）⇒ 改稿之后要重审")
        else:
            out["why"] = "命题行的第 3 位没翻（这一份证明没被签过）"
        return out
    per = _EB.reviewed_by_proof(bits)
    sha_by = _EB.reviewed_sha_by_proof(bits)
    if per:
        if not per.get(no):
            out["why"] = (f"第 3 位签的证明不是 #{no}（逐条表里 #{no} 为假）"
                          "⇒ 这一份不许借别的证明的光")
            return out
    else:
        signed_no = as_proof_no(out["reviewed_by"].get("proof_no")) \
            if out["reviewed_by"] else 0
        if signed_no and signed_no != no:
            out["why"] = f"第 3 位签的是 #{signed_no}，不是 #{no}"
            return out
    want = str(sha_by.get(no) or "")
    if want and sha_now and want != sha_now:
        out["why"] = (f"#{no} 那一签盖住的正文不是现在这一份"
                      f"（签的 sha {want[:12]}…，现在 {sha_now[:12]}…）")
        return out
    if not verifications._already_signed_locator(out["reviewed_by"], per, sha_by, no):
        # 位写着真、而凭据里没有任何可定位的签名 ⇒ 判不了，按没签过处理。
        # 这一支必须排在 `signed=True` 之前：短接是"省掉一次审校"，不能拿裸布尔换。
        out["why"] = ("第 3 位写着审过，但凭据里没有可定位的签名（`reviewed_by` 无 "
                      "`verification_id` / `proof_sha256`，逐条表也没有任一为真且有 sha）"
                      " ⇒ 判不了，按没签过处理：照常送审，不拿一个裸布尔短接")
        return out
    out["signed"] = True
    return out


def _is_legacy_row(row: Mapping[str, Any]) -> bool:
    """这一行是不是「历史形态」——没有单次送审的轮次标记。

    2026-11-02 起新写的台账行都带 `review_call`（同一趟 `verify_proof` 的调用 id）与
    `review_pass`（这趟里的第几轮）；老行没有这两个键。这两种行在判据上必须分开：

    - 新行：只有同一 `review_call` 内的 `review_pass=1..need` 才算一次送审的三轮；
    - 老行：读得出（`legacy_rows` 计数）、但不参与新签判断，也不按新规则重算成签。

    判据取"两个标记缺任一"而不是只看 `review_call`：半截写入（有 call id、没有轮次）
    同样说不清"这是第几轮"，按历史形态收是最保守的那一侧。
    """
    if not str(row.get("review_call") or "").strip():
        return True
    return row.get("review_pass") in (None, "")


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    NO_SECRETARY_JUDGE,
    PENDING_DIR_NAME,
    PENDING_PREFIX,
    SECRETARY_JUDGE_AXES,
    SECRETARY_JUDGE_KEY,
    VERIFICATIONS_DIR,
)
from .v_citation import (  # noqa: F401 — 实现在 v_citation.py
    citation_blocks,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    _sign_sha,
    as_proof_no,
    proof_no_of,
    verification_ledger_path,
    verifications_dir,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    signed_rows,
)
