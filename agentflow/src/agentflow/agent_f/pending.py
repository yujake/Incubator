# -*- coding: utf-8 -*-
"""「已登记、V 签还没到」的稿：一处扫描，三个读者共用（INV7 / 业主 2026-11-18）。

## 这一格修的是什么（`agentflow/temp/inv7/INV7-REPORT.md`，`projects/lp-ball-7`）

F 在 10:02:18 已经把旧落点 `reports/f-proof-000001.md`（当时正文还写在 `reports/` 下）
登记进盘（稿头有正文 sha /
命题指纹 / 版本行 ⇒ `proofregistry.parse_entry` 认它是登记条目），`v_sign` 那一格
也如实读成 `unsigned`（「这一份正文还没有一份能算数的签」）。可同一拍的
`delivery` 却读成 `total=0` / `proof_count=0` / `still_unsubmitted=[]` /
`researched_no_output` —— 于是 10:07:19 与 10:12:20 两次 `agent_park` 都判
`pending_work=false`，F 没有拿到任何模型回合去执行「下一步：派 V」。

根因不是两个读数各自算错，而是「成果的身份只认 `statements` 行」：B 的收录在
V 签之后，所以一份「已登记、等签」的稿在 `history` 里没有 `statement_id`，
`delivery.outputs_of` 数不到它；而 `v_sign` 读的是手稿 × 签的颁发表，两处口径
分家。本模块把「盘上已登记的稿」收成一份可复用的扫描，`delivery` / 挂机判据 /
M 的读数都从它取数 —— 一处分家就三处一起红（判据
`tests/test_f_registered_unsigned_is_pending.py` 的 e 条、
`tests/test_producer_owns_the_manuscript_until_signed.py` 的 g 条）。

## 业主 2026-11-18 裁定：「谁写稿，谁就对稿负责」

改前扫描只管 `f-proof`，挂机判据也写死 `role == "F"`；E 的 `reports/e-proof-*.md`
与 B 的 `reports/b-proof-*.md` 已登记未送审时，它们的产出者照样可以挂机。现在：

- 产出者（`manuscript_producer`）按两路事实读，不按角色字面量：
  1. `ARTIFACTS.jsonl` 的 `producer` 字段（`artifacts.read_ledger` 一次读全，
     按 `path` 索引；取这份稿的最后一条登记）—— "谁把这份稿登记进盘"；
  2. 没有台账行时退回稿族：`manuscriptproducers.producer_of(rel)["producer_role"]`
     （`PRODUCER_OF_FAMILY` 是族 ⇒ 产出者的唯一映射表，事实来源是路径前缀）；
  3. 两者都没有 ⇒ `producer_role=""`，这份稿不进任何角色的待办（不猜）。
  台账与稿族不一致时 `producer_source="artifacts"` 照台账走（谁登记谁负责），
  另记 `producer_conflict=True`：那是读数，不是静默改归属。
- 已登记也有两路证据：稿头元信息（`proofregistry.parse_entry` 的 `checked`，
  F/B 写）或产物台账那一行（E 的 `exhaustionreport.land_manuscript` 只登记台账，
  稿头没有 `- 版本：`）。改前只认稿头 ⇒ E 的稿永远读成"草稿"。
- 哪些族要读这张表：`manuscriptfamily.needs_sign(family)` 为真的三族
  （`f-proof` / `b-proof` / `e-proof`）；`e-num` 走绿色通道、不签，不进来。
- 哪些角色是产出者：`manuscriptopen.ROLE_FAMILIES`（手稿写口的角色面，
  唯一一张角色-族表）⇒ F / E / B。其余角色（A/C/G/H/M）不因这一条被拦。

## 判据

- 未签：`vsign.delivery_reading` 的四档里不是 `signed`。`waiting` 是「等签」
  （含真的还没送审）；`rejected` 是 V 判过没过；`unknown` 是签那一格没查成 ——
  三档都需要产出者的动作，所以都进待办（三态纪律：不把「没查成」折成「没事」）；
- 等待时长：从登记时刻算（稿头 `- 登记时间：` 优先，否则台账那一行的 `at`），
  唯一取时口 `clock.now()`（假时钟也走它）；
- 纯读：只列各族自己的正文目录（`manuscripts/F|B|E/`）、只算 sha、只读签与台账；一个字节都不写盘。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

# 「稿」的身份前缀 `mss:` 不在这里定义：写记号那一侧的真身是
# `agent_f/submission.py::SUBMISSION_PREFIX`（本模块只读盘，不写 `tasks.artifacts`）。
# 改前这里留过一份零引用的 `MANUSCRIPT_OUTPUT_PREFIX = "mss:"` —— 第三份字面量，
# 读的人会以为待办扫描按它发号（判据：`tests/test_roleclean2_c_e_f_g_residue.py` ②）。


def _empty(why: str = "") -> dict[str, Any]:
    return {"checked": True, "count": 0, "items": [], "rows": [],
            "problems": [], "why": why}


def producer_families(role: Any) -> tuple[str, ...]:
    """这个角色产出手稿的族（唯一来源 `manuscriptopen.ROLE_FAMILIES`）。

    空元组 = 它不是产出者（A/C/G/H/M 与 V）—— 调用方据此判「这一条与我无关」，
    而不是在调用点写死一个角色字母。名字刻意不叫 `families_of`：那是
    `manuscriptopen` 的公开名，同名转发会被 R003 记成第二个实现。
    """
    from .. import manuscriptopen as _MO

    return tuple(_MO.families_of(role))


def producer_roles() -> tuple[str, ...]:
    """产出手稿的角色（从 `manuscriptopen.ROLE_FAMILIES` 现读，不另写一份名单）。"""
    from .. import manuscriptopen as _MO

    return tuple(sorted(str(x) for x in _MO.ROLE_FAMILIES))


def sign_families() -> tuple[str, ...]:
    """要 V 签的稿族（`e-num` 走绿色通道、不签 ⇒ 不进这张表）。"""
    from .. import manuscriptfamily as _MFAM

    return tuple(f for f in _MFAM.FAMILY_ORDER if _MFAM.needs_sign(f))


def _owners_index(root: Any) -> tuple[dict[str, list[dict[str, Any]]] | None, str]:
    """`ARTIFACTS.jsonl` 一次读全 ⇒ `{工作区相对路径: [登记行…]}`（读不成给 None）。

    为什么一次读全：`artifacts.owners_of` 每问一条路径就重读整本台账；挂机判据
    每一拍按角色问一次，稿多、台账长时会变成 N×M 次解析。索引与 `owners_of`
    同一份数据（`read_ledger` 是唯一读口），不另写第二份台账读法。

    返回 `(None, 理由)` = 整本台账读不出来 —— 那一段调用方按 fail-closed 处置
    （"不知道谁写了这份稿"不许折成"没人写"）。有坏行但仍读出记录时，索引照给、
    理由进 `problems`：那几行可能正好是某一份稿的归属，所以它也要被看见。
    """
    from .. import artifacts as _A

    try:
        records, bad = _A.read_ledger(root)
    except Exception as exc:  # noqa: BLE001 —— 读不成是「没查成」，不是「没有登记」
        return None, f"`{_A.LEDGER_NAME}` 读不出来（{type(exc).__name__}: {exc}）"
    index: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        rel = str(row.get("path") or "").replace("\\", "/")
        index.setdefault(rel, []).append(dict(row))
    if bad:
        return index, (f"`{_A.LEDGER_NAME}` 有 {len(bad)} 行读不出来"
                       f"（{str(bad[0])[:80]}）⇒ 这几份的产出者/登记可能漏读")
    return index, ""


def manuscript_producer(root: Any, rel: Any, *, entry: Mapping[str, Any] | None = None,
                        owners: Any = None) -> dict[str, Any]:
    """这一份稿「谁写的 / 什么时候登记」（纯读；台账 producer 优先，稿族兜底）。

    `owners` 给了就复用（`scan_registered` 一次读全台账之后的 `path` 那一格）；
    没给就现读 `artifacts.owners_of`。返回：

    `checked` / `producer_role` / `producer_source`（`artifacts` | `manuscript_family` |
    `""`）/ `producer_instance` / `producer_actor` / `instance_source` / `ledger_producer` /
    `family` / `family_role` / `producer_conflict` /
    `registered` / `registered_source`（`manuscript_head` | `artifacts` | `""`）/
    `registered_at` / `why`。

    ## 实例归属（K8，业主 2026-11-18）

    「谁写稿，谁就对稿负责」里的「谁」是实例，不是角色：同族两份稿各由不同的 F
    实例产出时，每一趟只该管自己那一份。实例从产物台账那一行读，两路事实：

    - `instance` 字段（K1/K2 起 `artifacts.record(instance=…)` 会写；写稿口
      `manuscriptform.commit_manuscript` 已经传它）；
    - `producer` 是实例级 actor（`agent-F-F1`）时由 `identity.split_actor` 拆出标签
      （老台账 / 别的写口只写 actor 的那一档）。

    两路都没有 ⇒ `producer_instance=""`（已登记但没有实例归属）：它不进任何实例的
    「我名下」，读侧另给 `unattributed` 记账，不静默算给谁。

    三态：台账读不出来 ⇒ `checked=False`（这一份的归属没查成，不折成「没有登记」）。
    """
    from .. import artifacts as _A
    from .. import manuscriptproducers as _MP

    raw = str(rel or "").strip().replace("\\", "/")
    head = dict(entry or {})
    out: dict[str, Any] = {
        "checked": True, "producer_role": "", "producer_source": "",
        "producer_instance": "", "producer_actor": "", "instance_source": "",
        "ledger_producer": "", "family": "", "family_role": "",
        "producer_conflict": False, "registered": False, "registered_source": "",
        "registered_at": "", "why": "",
    }
    if not raw:
        out.update(checked=False, why="没有稿路径 ⇒ 产出者与登记都没查成")
        return out
    fam = dict(_MP.producer_of(raw) or {})
    out["family"] = str(fam.get("family") or "")
    out["family_role"] = str(fam.get("producer_role") or "")
    if owners is None:
        try:
            owners = _A.owners_of(root, raw)
        except Exception as exc:  # noqa: BLE001 —— 读不成是「没查成」
            out.update(checked=False,
                       why=(f"产物台账读不出来（{type(exc).__name__}: {exc}）"
                            " ⇒ 这一份的产出者没查成（不是「没有归属」）"))
            return out
    records = [dict(r) for r in (owners or ()) if isinstance(r, Mapping)]
    last = records[-1] if records else {}
    ledger_producer = str(last.get("producer") or "").strip()
    ledger_instance = str(last.get("instance") or "").strip()
    producer_set = set(str(x) for x in _MP.PRODUCER_OF_FAMILY.values())
    actor_role, actor_instance = "", ""
    if ledger_producer:
        from .. import identity as _ID

        for one in sorted(producer_set):
            got = _ID.split_actor(one, ledger_producer)
            if got.get("matched"):
                actor_role = one
                actor_instance = str(got.get("instance") or "")
                break
    if ledger_producer in producer_set:
        out.update(ledger_producer=ledger_producer, producer_role=ledger_producer,
                   producer_source="artifacts")
    elif actor_role:
        # K1/K2 之后写的是实例级 actor（`agent-F-F1`）：角色从 actor 前缀读，
        # 归因到「那个实例」而不是折回角色桶。
        out.update(ledger_producer=ledger_producer, producer_role=actor_role,
                   producer_source="artifacts")
    elif out["family_role"]:
        # 台账写了一个不产出手稿的角色（或外部生产者）：手稿只能由 `ROLE_FAMILIES`
        # 那几个角色写出来，自报不改写事实（与 `manuscriptproducers` 同一条纪律）。
        out.update(producer_role=out["family_role"],
                   producer_source="manuscript_family")
    # ---- 实例归属只在「台账说是谁写的」那一档才认（K8） ----------------------
    if out["producer_source"] == "artifacts" and out["producer_role"]:
        from .. import identity as _ID

        if ledger_instance:
            out.update(producer_instance=ledger_instance,
                       producer_actor=_ID.actor_for(out["producer_role"], ledger_instance),
                       instance_source="artifacts.instance")
        elif actor_instance:
            out.update(producer_instance=actor_instance, producer_actor=ledger_producer,
                       instance_source="artifacts.producer")
        else:
            # 台账只写了角色桶（`producer="F"`、无 instance）：这一份没有实例归属。
            out.update(producer_actor=ledger_producer, instance_source="")
    elif out["producer_source"] == "manuscript_family":
        from .. import identity as _ID

        out.update(producer_actor=_ID.actor_for(out["producer_role"], ""),
                   instance_source="")
    if (ledger_producer and out["family_role"]
            and ledger_producer != out["family_role"]):
        out["producer_conflict"] = True
        out["why"] += (f"台账登记的产出者是 {ledger_producer!r}，稿族是 "
                       f"{out['family_role']} ⇒ 按稿族定产出者，这条不一致进读数")
    # ---- 「已登记」两路证据：稿头元信息 / 产物台账那一行 --------------------
    if bool(head.get("checked")):
        out.update(registered=True, registered_source="manuscript_head",
                   registered_at=str(head.get("registered_at") or ""))
    if records:
        if not out["registered"]:
            out.update(registered=True, registered_source="artifacts",
                       registered_at=str(last.get("at") or ""))
        elif not out["registered_at"]:
            out["registered_at"] = str(last.get("at") or "")
    if not out["producer_role"] and not out["why"]:
        out["why"] = (f"`{raw}` 的产出者判不出来（台账没有一条角色登记、稿族也认不出）"
                      " ⇒ 不进任何角色的待办（不猜一个角色）")
    return out


def waiting_reading(registered_at: Any) -> dict[str, Any]:
    """登记到现在等了多久（秒 + 人话；唯一取时口 `clock.now()`）。

    登记时刻读不出来 / 时钟读不到 ⇒ `waiting_sec=None`、`waiting_text=""` ——
    「时长读不出来」不是「等了 0 秒」。
    """
    out: dict[str, Any] = {"waiting_sec": None, "waiting_text": ""}
    text = str(registered_at or "").strip()
    if not text:
        return out
    try:
        from .. import clock as _CLK

        at = _CLK.parse_iso(text)
        now = _CLK.now().wall
        secs = max(0, int((now - at).total_seconds()))
        out.update(waiting_sec=secs, waiting_text=_CLK.human_sec(secs))
    except Exception:  # noqa: BLE001 —— 读不出来是「时长读不出来」，不是 0
        return {"waiting_sec": None, "waiting_text": ""}
    return out


def manuscript_cell_text(row: Mapping[str, Any]) -> str:
    """一份稿的人话读数（稿路径 + 产出者 + 正文 sha 前 12 + 等待时长 + 签那一档）。"""
    sha = str(row.get("sha") or "")
    sha_text = (sha[:12] + "…") if sha else "sha 读不出来"
    wait = str(row.get("waiting_text") or "") or "等待时长读不出来"
    state = str(row.get("state_label") or row.get("state") or "")
    producer = str(row.get("producer_role") or "")
    who = f"{producer}，" if producer else ""
    return (f"{row.get('manuscript') or '?'}"
            f"（{who}{sha_text}，等了 {wait}{('，' + state) if state else ''}）")


def scan_registered(root: Any, *, family: Any = None,
                    families: Any = None) -> dict[str, Any]:
    """扫各族自己的正文目录（`manuscripts/F|B|E/`，目录真身 `manuscriptfamily.dir_of`）
    下要签的稿，只留「已登记」的那些（纯读）。

    `family` 给一个族名（`f-proof`）就只扫它；`families` 给一串；都不给 ⇒ 扫
    所有要签的族（`sign_families()`）。返回 `{checked, rows, problems, why}`；
    `rows` 每项 `{manuscript_id, manuscript, text, entry, label, family,
    producer_role, producer_source, registered_at, producer_checked}`。

    `checked=False` 只表示目录列不出来（「没查成」）；单份稿读不出来 / 台账读不出来
    进 `problems`，不冒充「这一份不存在」。
    """
    from .. import manuscriptfamily as _MFAM
    from .. import proofregistry as _PR
    from .. import vsigns as _VS

    f_dir = _MFAM.dir_of("f-proof")
    out = _empty()
    if not str(root or "").strip():
        out.update(checked=False,
                   why="没有工作区根 ⇒ 已登记稿这一格没查成（不是「没有稿」）")
        return out
    if families:
        wanted = tuple(str(f) for f in families if str(f))
    elif family:
        wanted = (str(family),)
    else:
        wanted = sign_families()
    wanted = tuple(dict.fromkeys(wanted))
    pairs: list[tuple[str, str]] = []
    for fam in wanted:
        prefix = str(_MFAM.prefix_of(fam) or "")
        if not prefix:
            out["problems"].append(f"稿族 {fam!r} 没有前缀 ⇒ 这一格没查成（跳过它）")
            continue
        pairs.append((fam, prefix))
    if not pairs:
        out.update(checked=False, why="没有可扫的稿族 ⇒ 已登记稿这一格没查成")
        return out
    try:
        # 2026-11-22（B2b-2）：一族一个目录（`manuscripts/F|B|E/`）；不再共用一个根。
        paths: list[tuple[str, Path]] = []
        for fam, prefix in pairs:
            d = Path(str(root)) / _MFAM.dir_of(fam)
            if d.is_dir():
                paths.extend((fam, p) for p in sorted(d.glob(f"{prefix}*.md")))
    except OSError as exc:  # noqa: BLE001 —— 列不出来 = 没查成
        out.update(checked=False,
                   why=(f"`{f_dir}/` 列不出来（{type(exc).__name__}: {exc}）"
                        " ⇒ 已登记稿这一格没查成（不是「一份都没有」）"))
        return out
    owners, ledger_problem = _owners_index(root)
    if owners is None:
        # 台账整本读不出来 ⇒ 产出者与登记都没查成（fail-closed：不许当成「没有稿」）。
        out.update(checked=False,
                   why=(ledger_problem or f"`{f_dir}/` 这一格没查成")
                   + " ⇒ 已登记稿这一格没查成（不是「没有稿」）")
        return out
    if ledger_problem:
        out["problems"].append(ledger_problem)
    rows: list[dict[str, Any]] = []
    by_family: dict[str, int] = {}
    for _fam_of_path, path in paths:
        rel = f"{_MFAM.dir_of(_fam_of_path)}/{path.name}"
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out["problems"].append(
                f"`{rel}` 读不出来（{type(exc).__name__}: {exc}）⇒ 这一份这次没查成")
            continue
        entry = dict(_PR.parse_entry(text) or {})
        got = dict(manuscript_producer(root, rel, entry=entry, owners=owners.get(rel, [])))
        if not got.get("checked"):
            out["problems"].append(f"`{rel}`：{got.get('why') or '登记/归属没查成'}")
            continue
        if not got.get("registered"):
            continue          # 草稿（既没有稿头元信息、也没有台账行）：还没登记
        parsed = dict(_VS.parse_manuscript_name(rel) or {})
        fam = str(got.get("family") or "")
        by_family[fam] = by_family.get(fam, 0) + 1
        rows.append({"manuscript_id": str(parsed.get("manuscript_id")
                                         or entry.get("manuscript_id") or ""),
                     "manuscript": rel, "text": text, "entry": entry,
                     "label": str(entry.get("label") or ""),
                     "family": fam,
                     "producer_role": str(got.get("producer_role") or ""),
                     "producer_source": str(got.get("producer_source") or ""),
                     "producer_instance": str(got.get("producer_instance") or ""),
                     "producer_actor": str(got.get("producer_actor") or ""),
                     "instance_source": str(got.get("instance_source") or ""),
                     "producer_checked": bool(got.get("checked")),
                     "registered_at": str(got.get("registered_at") or ""),
                     "why": str(got.get("why") or "")})
    out["rows"] = rows
    detail = "、".join(f"{fam}×{n}" for fam, n in sorted(by_family.items()))
    out["why"] = (f"正文本目录下 {len(paths)} 份 "
                  f"{'/'.join(fam for fam, _p in pairs)} 的稿里有 {len(rows)} 份"
                  "「已登记」" + (f"（{detail}）" if detail else ""))
    return out


def summon_action(row: Mapping[str, Any]) -> dict[str, Any]:
    """这一份稿「下一步」的可执行动作（summon 形状：`role="V"` + 要审的稿路径）。

    真机 step 8 的 tool result 里只有一句「下一步：派 V 审这一份」；F 想在
    `self_assessment` 里写同一件事又被封闭参数表拒掉。这一格把「下一步」变成
    结构化的动作读数（不是替它派，派活仍是产出者自己的动作）。`task` 里的
    「谁这一趟交差」按这一份稿的产出者现读（不是写死 F）。
    """
    rel = str(row.get("manuscript") or "")
    mid = str(row.get("manuscript_id") or "")
    sha = str(row.get("sha") or row.get("sha256") or "")
    producer = str(row.get("producer_role") or "")
    tail = (f"（稿号 {mid}，正文 sha {sha[:12]}…）" if mid else "")
    who = f"{producer} 这一趟交差" if producer else "产出者这一趟交差"
    return {
        "tool": "framework_summon",
        "shape": "summon",
        "role": "V",
        "task": (f"审这一份证明稿 {rel}{tail}：判它成立/不成立，"
                 f"给出逐条 findings 与结论；拿到签才算 {who}"),
        "manuscript": rel,
        "manuscript_id": mid,
    }


def manuscript_reading(root: Any, row: Mapping[str, Any], *,
                       reading: Mapping[str, Any] | None = None,
                       store: Any = None) -> dict[str, Any]:
    """一份已登记稿的 V 签读数（四档；`reading` 给了就复用，不重复读盘）。

    `store` 给了就同时读一格生命周期（`lifecycle.state_of_manuscript`，K10 的单一判据）：
    `completed`（已拿签）/ `abandoned`（命题退休）都不在活跃集里；`unsubmitted_reading`
    只把活跃的那些算成"待办"，`checked=False` 的那一档照旧进待办（没查成不等于没事）。
    """
    from .. import proofregistry as _PR
    from . import vsign as _VS

    got = dict(reading or {})
    rel = str(row.get("manuscript") or "")
    if not got:
        try:
            got = dict(_VS.delivery_reading(
                root, statement_id="", proof_text=str(row.get("text") or ""),
                manuscript_paths=(rel,) if rel else ()))
        except Exception as exc:  # noqa: BLE001 —— 读不成是「没查成」，不是「没签」
            got = {"state": _VS.STATE_UNKNOWN, "label": "没查成",
                   "delivered": False, "checked": False,
                   "why": f"读签这一格没跑成（{type(exc).__name__}: {exc}）"}
    state = str(got.get("state") or _VS.STATE_UNKNOWN)
    entry = dict(row.get("entry") or {})
    sha = str(got.get("sha") or entry.get("sha256") or "")
    if not sha:
        try:
            sha = _PR.proof_sha(str(row.get("text") or ""))
        except Exception:  # noqa: BLE001 —— sha 只是读数，算不出来不带走结论
            sha = ""
    out = {
        "manuscript_id": str(row.get("manuscript_id") or ""),
        "manuscript": rel,
        "label": str(row.get("label") or ""),
        "family": str(row.get("family") or ""),
        "producer_role": str(row.get("producer_role") or ""),
        "producer_source": str(row.get("producer_source") or ""),
        "producer_instance": str(row.get("producer_instance") or ""),
        "producer_actor": str(row.get("producer_actor") or ""),
        "registered_at": str(row.get("registered_at") or ""),
        "sha": sha,
        "state": state,
        "state_label": str(got.get("label") or ""),
        "signed": bool(got.get("delivered")),
        "checked": bool(got.get("checked", True)),
        "why": str(got.get("why") or ""),
    }
    out.update(waiting_reading(out["registered_at"]))
    out["next_action"] = summon_action(out)
    # ---- 生命周期（K10）：活跃集是「还在不在推」的唯一判据 ---------------------
    life: dict[str, Any] = {"checked": False, "state": "", "raw": "",
                            "why": "没有 store ⇒ 生命周期读不到（这一份按签表读）"}
    if store is not None and rel:
        try:
            from .. import lifecycle as _LC

            life = dict(_LC.state_of_manuscript(store, rel))
        except Exception as exc:  # noqa: BLE001 —— 判不了就如实说（不折成已完工）
            life = {"checked": False, "state": "", "raw": "",
                    "why": f"生命周期没查成（{type(exc).__name__}: {exc}）"}
    out["lifecycle_state"] = str(life.get("state") or "")
    out["lifecycle_checked"] = bool(life.get("checked"))
    out["lifecycle_why"] = str(life.get("why") or "")
    return out


def unsubmitted_reading(root: Any, *, producer: Any = None, owner: Any = None,
                        family: Any = None, families: Any = None,
                        store: Any = None) -> dict[str, Any]:
    """已登记、V 签还没到的稿（`count` > 0 ⇒ 这一拍有活）。

    ## 谁问「我名下」：`owner`（K8，业主 2026-11-18）

    改前这一格只认 `producer`（角色）：「哪些稿要送审」被实现成「哪个角色的每一趟
    都对同族所有稿负责」—— 两个 F 实例各有一份待签稿时，每一趟都读到 2 份
    （`temp/AUDIT-VD`：M 的挂机第 4 条按角色筛待签稿 ⇒ 任何 F 实例都读到 count=2）。

    现在两条并立、各有各的读者：

    - `owner` 给了（实例标签，或实例级 actor）⇒ 只留这个实例产出的稿；
      同族里没有实例归属的那些进 `unattributed`（不静默算给谁，也不静默丢掉）；
    - `producer` 给了（角色）⇒ 只留这个角色产出的稿（M 的全局读数 / 角色级直调）；
    - 两个都不给 ⇒ 全部（M 要逐份看见）。

    返回 `{checked, count, items, rows, problems, why, producer, owner, unattributed}`；
    `items` 每项是 :func:`manuscript_reading` 的那一格（带 `next_action` /
    `waiting_sec`）。
    """
    scan = scan_registered(root, family=family, families=families)
    rows = [dict(r) for r in (scan.get("rows") or []) if isinstance(r, Mapping)]
    who = str(producer or "").strip()
    if who:
        rows = [r for r in rows if str(r.get("producer_role") or "") == who]
    mine = str(owner or "").strip()
    unattributed: list[dict[str, Any]] = []
    if mine:
        kept: list[dict[str, Any]] = []
        for row in rows:
            instance = str(row.get("producer_instance") or "")
            actor = str(row.get("producer_actor") or "")
            if instance == mine or (actor and actor == mine):
                kept.append(row)
            elif not instance:
                unattributed.append(row)
        rows = kept
    out = {"checked": bool(scan.get("checked")), "count": 0, "items": [],
           "rows": rows, "problems": list(scan.get("problems") or []),
           "why": "", "producer": who, "owner": mine,
           "unattributed": unattributed, "inactive": []}
    items: list[dict[str, Any]] = []
    inactive: list[dict[str, Any]] = []
    for row in rows:
        got = manuscript_reading(root, row, store=store)
        # 活跃集判据（K10）：`lifecycle.state_of_manuscript` 说 completed / abandoned
        # 就不算待办；没查成的那一档照旧进待办（签字表那一路在这里只当兜底）。
        if got.get("lifecycle_checked") and str(got.get("lifecycle_state") or "") not in (
                "active",):
            inactive.append(got)
            continue
        if got.get("signed"):
            continue
        items.append(got)
    out["items"] = items
    out["inactive"] = inactive
    out["count"] = len(items)
    if not out["checked"]:
        out["why"] = str(scan.get("why") or "已登记稿这一格没查成（不是「没有稿」）")
    elif items:
        out["why"] = (f"名下 {len(items)} 份已登记、V 签还没到的稿："
                      + "、".join(manuscript_cell_text(x) for x in items[:6]))
    elif mine:
        out["why"] = (f"名下没有「已登记、V 签还没到」的稿"
                      f"（{scan.get('why') or '查过了'}）")
        if unattributed:
            out["why"] += (f"；另有 {len(unattributed)} 份已登记稿没有实例归属"
                           "（不计入任何实例）："
                           + "、".join(str(r.get("manuscript") or "") for r in unattributed[:3]))
    elif who:
        out["why"] = (f"名下没有「已登记、V 签还没到」的稿"
                      f"（{scan.get('why') or '查过了'}）")
    else:
        out["why"] = str(scan.get("why") or "没有「已登记、V 签还没到」的稿")
    return out


