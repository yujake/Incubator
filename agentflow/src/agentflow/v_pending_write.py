# -*- coding: utf-8 -*-
"""pending 写口（两层锁 + 跨文件发号）。

2026-11-20（VERSPLIT2）：`v_pending_write.py` 是从 `verifications.py` 搬出的 6 块 / 266 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

import json
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

from . import jsonlfile as JF
from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）


_PENDING_LOCKS: dict[str, Any] = {}


_PENDING_LOCKS_GUARD = threading.Lock()


def _pending_lock_for(key: str) -> Any:
    """同一目录的进程内锁（`filelock` 在同进程里不保证线程安全，两层都要）。"""
    with _PENDING_LOCKS_GUARD:
        lock = _PENDING_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _PENDING_LOCKS[key] = lock
        return lock


@contextmanager
def pending_write_lock(root: str | Path) -> Iterator[None]:
    """pending 台账的写临界区：进程内一把 + 跨进程一把（K14；两层都要）。

    罩的是「读这一份台账的行 → 取 `u-<号>` / `round` → 追加」这一整段。
    只罩追加不够：两个进程都能读到同一份旧行，于是各自取号、各自写同一号 ——
    而台账是 append-only 的，撞号不会覆盖正文，但它会让按 `verification_id`
    定位的读者（认领回写 / 判词送达 / 找 anchor）串到别人那一行。
    形态与 `vreviews._review_write_lock` 逐字同源（那里是 V 稿号，这里是 pending 号）。

    目录先建出来：台账与 `<目录>.lock` 都落在这一层（`filelock` 不替我们建父目录）。
    等锁超时 ⇒ 受控抛 `VerificationError`（不静默跳过锁）。
    """
    gate = pending_dir(root)
    gate.mkdir(parents=True, exist_ok=True)
    lock_path = gate.parent / f"{gate.name}{PENDING_LOCK_SUFFIX}"
    key = str(lock_path.resolve())
    try:
        from filelock import FileLock, Timeout
    except Exception as exc:  # noqa: BLE001 —— 装不上锁就不能假装有锁
        raise VerificationError(
            f"pending 台账的跨进程锁建不出来（{type(exc).__name__}: {exc}）⇒ 这一签不落盘"
        ) from exc
    with _pending_lock_for(key):
        cross = FileLock(str(lock_path), timeout=PENDING_LOCK_TIMEOUT)
        try:
            cross.acquire()
        except Timeout as exc:
            raise VerificationError(
                f"pending 台账的写锁等不到（{PENDING_LOCK_TIMEOUT}s，另一个写者卡住了）"
                "⇒ 这一签不落盘（判不了不抢一把没有的锁）") from exc
        try:
            yield
        finally:
            try:
                cross.release()
            except Exception:  # noqa: BLE001 —— 释放失败不改变本笔已落盘的结论
                pass


def _next_pending_verification_id(root: str | Path) -> str:
    """pending 台账的下一号：跨所有文件取 `u-<号>` 的最大值 + 1（K6③）。

    改前每一份台账各发各的（`u-{len(rows)+1}`）⇒ 两份台账的第一行都叫
    `u-000001`，"哪一签"在跨文件的读数面上撞号（锚点 `台账路径#u-号` 才唯一，
    单看 `u-号` 不唯一）。现在号源扫 `verifications/pending/*.jsonl` 的全部行取最大
    +1：新号跨文件唯一；老行原样读（不重编号、不迁移）。读不出来的文件跳过 ——
    它由调用方在读行时按既有三态报出，不在这里静默把它当成"没有号"。

    调用点必须在 :func:`pending_write_lock` 里（K14）：号源读的是盘上全部行，
    锁外的两个进程会读到同一份最大值、各发同一个号。锁本身不在这里抢 —— 发号器
    是纯读，罩它的那段临界区由写口（:func:`record_pending_sign`）声明，这样
    "读行 → 取号 → 追加"是同一个临界区，而不是两次各锁一段。
    """
    top = 0
    base = pending_dir(root)
    try:
        files = sorted(base.glob("*.jsonl"))
    except OSError:
        return f"{PENDING_PREFIX}{S.format_id(1)}"
    for file in files:
        rows, _problems = JF.read_jsonl(file)
        for row in rows:
            text = str((row or {}).get("verification_id") or "")
            if not text.startswith(PENDING_PREFIX):
                continue
            rest = text[len(PENDING_PREFIX):]
            if rest.isdigit():
                top = max(top, int(rest))
    return f"{PENDING_PREFIX}{S.format_id(top + 1)}"


def record_pending_sign(root: str | Path, *, proof_text: str, verdict: Mapping[str, Any],
                        verifier: str = "V", object_sha256: Any = "",
                        object_path: Any = "",
                        producer_path: Any = "",
                        producer_code: Any = "",
                        roster_role: Any = "",
                        secretary_judge: Mapping[str, Any] | None = None,
                        washed_relay: Mapping[str, Any] | None = None,
                        review_call: Any = "", review_pass: Any = None,
                        review_scope: str = "",
                        at: Any = "") -> dict[str, Any]:
    """把"命题还没在册时"的一次审校落进 pending 台账，返回那一行。

    为什么要这一格（D-34，r34b 的真机现场）：V 审完判「成立」，而 `statements` 是 0 行 ——
    `record_verification` 要一个合法命题号才写得出 `verifications/<号>.jsonl`，于是那一签
    没有落点，结论只能 escalation 掉。结论丢了不是"没审"，是"审了没处记"。

    落点按对象内容的 sha 分文件：`object_sha256`（那份报告 / 证明文件的字节 sha256）给了
    就用它，没给就退到证明正文的 sha（`proof_sha256`）。两个 sha 都写进行里，所以 B 后来
    认领时按哪一个都找得到（"顺序不再重要"）。

    结论一样要过 `parse_verdict`（结构解析；p247 起它不判定、不折档）。
    `secretary_judge`（p247）随同一行落盘 —— axis 是这一行唯一的轴来源；不给 ⇒ 这一行
    没有轴，`row_signable` 为假（fail-closed，不会按 `verdict` 字面签）。
    引用核实那一格（`citation_checks`）随同一行落盘，形状与 `record_verification` 逐格相同。

    ## `washed_relay`：洗过的转达文本（2026-11-16，与 `record_verification` 同形）

    在册那一支的"秘书洗稿"落在 `record_verification` 的 `washed_relay` 格；未在册这一支
    此前没有这一格 ⇒ 主路上（F 的稿几乎总是先未在册）「秘书洗稿 → 转达 F」不发生。
    修法只在写口补同一格，条件写入与在册那一支逐字相同：只有 `washed=True` 才写，
    "没有这一格"必须是"没洗过 / 洗不出来"，不许写一份空文本冒充洗过。读侧
    （`vsigns._defect_text` / `agent_loop._washed_text`）按同一个键读。

    ## `review_call` / `review_pass` / `at`：一行一笔身份（2026-11-17，业主裁定）

    业主逐字：「三次连续过审才能签…不存在 V 秘书判一次审过后直接落签…（是系统计数
    落签）」。要让"系统计数"数得出来，每一行必须自己说清"我是哪一趟送审的第几轮"：

    - `review_call` —— 这一趟送审的调用 id（同一趟的几行逐字相同）；
    - `review_pass` —— 这一趟的第几轮（1..need）；
    - `object_sha256` —— 被审那一份稿的字节 sha（认领 / 签文件按它找）；
    - `at` —— 这一轮判词落下的时刻（调用方把判词时刻递进来；不给才取写行时刻）。
      改前三行是一次批量写的、`at` 取写行时刻 ⇒ 三行必然同秒，盘上分不出
      "三次独立审阅"与"一次审阅、三行重述"。

    不给这三格（老调用点 / 夹具）⇒ `review_call=""`、`review_pass=None`、`at=写行时刻`
    —— 读侧按历史形态（`legacy`）读，不许静默当成新形态的一份。
    """
    checked = parse_verdict(json.dumps({"verdict": verdict.get("verdict"),
                                        # 老调用方带的原话照旧带下去（审计用）。
                                        "verdict_raw": verdict.get("verdict_raw", ""),
                                        "defect_step": verdict.get("defect_step"),
                                        "quote": verdict.get("quote", ""),
                                        "why": verdict.get("why", ""),
                                        "findings": list(verdict.get("findings") or []),
                                        "citation_checks": list(verdict.get("citation_checks") or [])},
                                       ensure_ascii=False, default=str))
    text = str(proof_text or "")
    sha = _sign_sha(text)
    obj = str(object_sha256 or "").strip().lower()
    key = obj or sha
    path = pending_ledger_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with pending_write_lock(root):
        rows, problems = JF.read_jsonl(path)
        if problems:
            raise VerificationError(f"pending 台账有读不出来的行：{problems[:3]}")
        row = {
            # 跨文件唯一（K6③）：`u-<号>` 不再按"这一份台账第几行"发，而是全目录取最大 +1。
            "verification_id": _next_pending_verification_id(root),
            # 没有命题号是这一档的定义（命题还没在册）：两个键都留空串而不是缺键 ——
            # 读的人要能分辨"这一行不属于任何命题"与"这一行是旧格式、没有这个键"。
            "statement_id": "", "stmt_id": "",
            # 2026-11-11 业主裁定：新行不再写 `proof_no`（V 签侧退役；老行读侧照旧）。
            # 这一行是哪一份正文：`proof_sha256`；哪一份载体：`object_sha256` / `object_path`。
            "verifier": str(verifier or "V"), "verdict": checked["verdict"],
            "defect_step": checked["defect_step"], "quote": checked["quote"],
            "why": checked["why"], "findings": checked["findings"],
            "unresolved_errors": checked["unresolved_errors"],
            "citation_checks": list(checked.get("citation_checks") or []),
            "proof_sha256": sha, "proof_chars": len(text),
            #: 对象（盘上那一份报告 / 证明文件）的字节 sha256 与相对路径：认领时按它。
            "object_sha256": obj, "object_path": str(object_path or "").strip().replace("\\", "/"),
            "round": len(rows) + 1, "used_faces": [], "submission_id": "",
            #: 2026-11-17（系统计数）：这一行是哪一趟送审的第几轮（键无条件存在 ——
            #: "没有这一格"与"这一格是空的"必须分得开；老调用点不传 ⇒ 空串 / None，
            #: 读侧按 legacy 读，见 `sign_counting`）。
            "review_call": str(review_call or "").strip(),
            "review_pass": (int(review_pass) if isinstance(review_pass, int)
                            and not isinstance(review_pass, bool) else None),
            #: 这一轮判词的时刻（调用方给）：不给才取写行时刻（老行为）。
            "at": str(at or "").strip() or verifications._now_iso(),
            "landed": "pending",
        }
        # ---- 产出方格（甲）：新行无条件写 `producer_role`，老行读侧记 unknown ----------
        row.update(_producer_cells(str(producer_path or object_path or ""),
                                   producer_code=producer_code,
                                   roster_role=roster_role))
        if str(checked.get("verdict_raw") or "").strip():
            #: 老调用方带过来的原话（只在真带了时写）。
            row["verdict_raw"] = str(checked["verdict_raw"]).strip()
        #: p247：轴是这一行唯一的判定来源（由 V 的秘书读回复后语义判定）。
        #: 无条件写（业主裁定 2）：改前是"给了才写"，于是没给的那一行落进
        #: `historical_axis` 的历史兼容支、按 `verdict` 字面拿到 clean —— 三行不经秘书的
        #: 「成立」就能凑满连续次数并签住第 3 位。现在没给就写 :data:`NO_SECRETARY_JUDGE`
        #: （未判成：`checked=False` + 空轴），`row_signable` 为假、连续计数不算票。
        row[SECRETARY_JUDGE_KEY] = secretary_judge_cell(secretary_judge)
        #: 洗过的那一份转达文本（与 `record_verification` 同形、同一个键）：
        #: 只在秘书真的洗出来时写（`washed=True`）—— 洗不出来的那一档不写这一格：
        #: 台账上"没有这一格"必须是"没洗过/洗不出来"，而不许写一份空文本冒充洗过。
        #: 未在册这一支的读者是 C 段交付面（`vsigns._defect_text` / V 的转达路径）。
        if isinstance(washed_relay, Mapping) and washed_relay.get("washed"):
            row["washed_relay"] = {
                "text": str(washed_relay.get("text") or ""),
                "findings": [dict(f) for f in (washed_relay.get("findings") or [])
                             if isinstance(f, Mapping)],
                "dropped": [dict(f) for f in (washed_relay.get("dropped") or [])
                            if isinstance(f, Mapping)],
            }
        #: 同 `record_verification`：I10 硬禁令的机械命中只作读数（条件写入、不参与判定）。
        _pending_banned = banned_markers_in(text)
        if _pending_banned:
            row["hard_ban_markers"] = list(_pending_banned)
        _append_verification(path, row)
        return row


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_vocab import (  # noqa: F401 — 实现在 v_vocab.py
    PENDING_LOCK_SUFFIX,
    PENDING_LOCK_TIMEOUT,
    PENDING_PREFIX,
    SECRETARY_JUDGE_KEY,
)
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    _producer_cells,
    _sign_sha,
    parse_verdict,
)
from .v_pending_read import (  # noqa: F401 — 实现在 v_pending_read.py
    pending_dir,
    pending_ledger_path,
)
from .v_ledger_write import (  # noqa: F401 — 实现在 v_ledger_write.py
    _append_verification,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    secretary_judge_cell,
)
from .v_defect import (  # noqa: F401 — 实现在 v_defect.py
    banned_markers_in,
)
