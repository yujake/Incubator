"""收工自动提交的读那一半（2026-11-11 从 `agent_f/delivery.py` 拆出）。

为什么要拆：`delivery.py` 在「收工自动提交」那一批之后 660 → 987 行，越过 `>800` 的
体量软基线；业主口径是基线不许抬，所以按「读 / 写」两条边界拆：

- 本模块：读那一半 —— `mss:` 记号的拼与解（`submission_token` / `parse_submission` /
  `submissions_of`）＋ 本工作区里 F 的稿 × V 的颁发表 ⇒ 每个稿号「该不该提交」的读数
  （`submission_candidates`，纯读：不碰 store、不写盘）；
- `agent_f/autosubmit.py`：写那一半 —— 收工那一趟选谁、事务里 append
  `tasks.artifacts`（原 `agent_f/step.py::_Step._auto_submit_signed` 的方法体）。

公开面一个字没变：`delivery.py` 在顶层回引本模块的六个公开名，`step.py` 与
`agent_d/write_report.py` 照旧按 `delivery.<name>` 取用（monkeypatch 面因此不变）。
判据：`tests/test_f_auto_submits_signed_manuscripts.py`。
"""
from __future__ import annotations

from typing import Any


# ============================================================ 收工自动提交（业主 2026-11-11 裁定 ①）
#
# 业主逐字（这一节要落实的那一条）：
#
#     「F侧报告收工时自动提交其名下未提交的V签稿」
#
# 三个前提都写在裁定里，这一节按它排：
#
# 1. 事实来源是 V 的颁发表，不是新表（同日裁定 ②：「维护拿签稿的稿号表可以和
#    V 自动维护的颁发出V签的表进行复用」）⇒ 本模块只读 `out/vsigns/<正文sha>.json`
#    （逐份签 = 证据；`issued.json` 是派生归档，不拿它下结论），不落任何新账；
# 2. 「已提交」的持久记号只有一处：F 自己的 `tasks.artifacts`（框架写、append-only）。
#    判据是「里面有没有这个稿号」，与版本无关（同日追加裁定）；
# 3. 一个稿号 = 一份文件（同日追加裁定：「一个稿号就相当于是该稿的文件名，
#    不再细分 version 几」）⇒ 提交时看的就是该稿号当前那一份文件；签的 sha 与当前
#    正文 sha 不一致 ⇒ 不提交、如实报，不替它挑「哪一版」。

#: F 的稿族（`vsigns.parse_manuscript_name` 的 `family` 格；只认这一族）。
FAMILY_F = "f-proof"

#: 「已提交」记号的前缀（`tasks.artifacts` 里的一项，形态沿用 `table:id` 那一套）。
SUBMISSION_PREFIX = "mss:"

#: 记号的字段分隔符（路径、sha 与 ISO 时刻都不含 `#`）。
SUBMISSION_SEP = "#"

#: 记号里字段的固定顺序（读侧按 `key=value` 取，顺序只影响可读性）。
SUBMISSION_FIELDS: tuple[str, ...] = (
    "path", "body_sha", "sign_sha", "file_sha", "proof_no",
    "statement_id", "at", "submitted_at",
)


def _proof_no_of(raw: Any) -> int:
    """证明号归一：认不出 / <1 ⇒ 1（与 `vsigns` 的缺省 `#p1` 同一口径）。"""
    try:
        no = int(raw or 1)
    except (TypeError, ValueError):
        return 1
    return no if no >= 1 else 1


def submission_token(*, manuscript_id: Any, path: Any = "", body_sha: Any = "",
                     sign_sha: Any = "", file_sha: Any = "", proof_no: Any = 1,
                     statement_id: Any = "", at: Any = "",
                     submitted_at: Any = "") -> str:
    """一份「已提交」记号（`tasks.artifacts` 里的一项）。

    为什么要一格带四样东西（稿号 + 正文 sha + 签 sha + 文件字节 sha + 时刻）：
    D 的携带单要按「地址 + 文件字节 sha256」递稿、B 要按正文 sha 认签，而
    「提交时是哪一版」必须能自证 —— 只留一个稿号，事后没人能判「盘上这份是不是
    当初提交的那一份」。

    `body_sha` 是 V 签盖的那段正文的 sha（`artifact_sha`，全仓同一把尺）；
    `sign_sha` 是签文件（`out/vsigns/<body_sha>.json`）的字节 sha256 —— 它回答
    「凭的是哪一份签」；`file_sha` 是盘上那份 `.md` 的字节 sha256（D/B 认地址用）。
    """
    mid = str(manuscript_id or "").strip()
    if not mid:
        raise ValueError("提交记号必须有稿号（`mss:<稿号>`）—— 没有稿号就没有可判的对象")
    values = {
        "path": str(path or "").strip().replace("\\", "/"),
        "body_sha": str(body_sha or "").strip().lower(),
        "sign_sha": str(sign_sha or "").strip().lower(),
        "file_sha": str(file_sha or "").strip().lower(),
        "proof_no": str(_proof_no_of(proof_no)),
        "statement_id": str(statement_id or "").strip(),
        "at": str(at or "").strip(),
        "submitted_at": str(submitted_at or "").strip(),
    }
    parts = [f"{SUBMISSION_PREFIX}{mid}"]
    for key in SUBMISSION_FIELDS:
        if values[key]:
            parts.append(f"{key}={values[key]}")
    return SUBMISSION_SEP.join(parts)


def parse_submission(token: Any) -> dict[str, Any] | None:
    """一条记号 ⇒ 结构（不是 `mss:` 前缀 ⇒ `None`；坏格静默缺省，不猜值）。"""
    text = str(token or "").strip()
    if not text.startswith(SUBMISSION_PREFIX):
        return None
    chunks = text.split(SUBMISSION_SEP)
    mid = chunks[0][len(SUBMISSION_PREFIX):].strip()
    if not mid:
        return None
    out: dict[str, Any] = {
        "manuscript_id": mid, "token": text, "path": "", "body_sha": "",
        "sign_sha": "", "file_sha": "", "proof_no": 0, "statement_id": "",
        "at": "", "submitted_at": "",
    }
    for chunk in chunks[1:]:
        key, sep, value = chunk.partition("=")
        if sep and key in out:
            out[key] = value
    out["proof_no"] = _proof_no_of(out.get("proof_no"))
    return out


def submissions_of(artifacts: Any) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """`tasks.artifacts` ⇒ `({稿号: 记号结构}, 问题)`。

    同一个稿号出现多条时保留最先读到的那一条（提交是 append-only；后来的重复
    不是第二次提交）。问题只收「长得像 `mss:` 却读不出稿号」的那些 —— 别的
    `artifacts` 项（路径、`file:` / 表行引用）不是这一格的事，不当问题。
    """
    out: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for token in artifacts or ():
        text = str(token or "").strip()
        if not text.startswith(SUBMISSION_PREFIX):
            continue
        rec = parse_submission(text)
        if rec is None:
            problems.append(f"`{text}` 不是一条可读的提交记号（`mss:<稿号>`）⇒ 跳过")
            continue
        out.setdefault(str(rec["manuscript_id"]), rec)
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
                   "statement_id": "", "proof_no": 0, "at": ""}
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
        if not one["proof_no"]:
            one["proof_no"] = _proof_no_of(doc.get("proof_no"))
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
        if not one["proof_no"]:
            one["proof_no"] = _proof_no_of(parsed.get("proof_no"))
    # ---- 每个稿号收成一格读数 ----
    for mid in order:
        one = by_mid[mid]
        paths = [str(x) for x in (one.get("paths") or []) if str(x)]
        signs = [dict(x) for x in (one.get("signs") or [])]
        cand: dict[str, Any] = {
            "manuscript_id": mid,
            "manuscript": paths[0] if paths else "",
            "proof_no": _proof_no_of(one.get("proof_no")),
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
