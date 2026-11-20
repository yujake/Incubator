# -*- coding: utf-8 -*-
"""自检。

2026-11-20（VERSPLIT2）：`v_selftest.py` 是从 `verifications.py` 搬出的 1 块 / 101 行（块
逐字未动，逐名 AST 全等在 `temp/versplit2/` 可复算）。对 32 个被测试打桩的名字，读
一律写成 `verifications.<name>` —— 门面字典在调用那一刻才查，所以
`monkeypatch.setattr(verifications, ...)` 仍然到得了这里（`from .x import X` 是快照，
补丁到不了）。跨模块 import 放在文件末尾：模块之间有互相引用，定义全跑完再 import
才解得开环。
"""

from pathlib import Path

from . import schema as S  # 编号形态的唯一来源（六位 / 旧四位读侧兼容）


def selftest() -> int:
    """最小自检：冷启动提示词只有对象、两态可判、签位条件、追加式编号。"""
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="verifications_selftest_"))
    checks: list[tuple[str, bool]] = []
    prompt = verifications.cold_start_prompt("设 G 是群，则 c(G) ≤ 1。", "1. 由定义直接得到。",
                               readonly_facts="- stmt:0007 现状：猜想（第 2 位空）")
    checks.append(("提示词带命题与证明", "c(G) ≤ 1" in prompt and "由定义直接得到" in prompt))
    checks.append(("提示词带硬禁令", "易证" in prompt and "无依据的步骤" in prompt))
    # I12（冷启动）在这一层的判据是接口：拼提示词的函数只收字符串，
    # 没有任何 store / conductor / registry / session_root 参数 —— 于是"不给句柄"
    # 是结构性质，而不是"约定只读"（提示词里出现"没有 store 句柄"这几个字是说明，
    # 不是句柄本身；按子串判会把说明误判成句柄）。
    import inspect as _inspect

    params = set(_inspect.signature(verifications.cold_start_prompt).parameters)
    checks.append(("接口上没有句柄参数",
                   not (params & {"store", "conductor", "registry", "session_root"})))
    bad = parse_verdict('{"verdict": "有毛病", "defect_step": 2, "findings": '
                        '[{"level": "error", "step": 2, "kind": "无依据", "detail": "第 2 步"}]}')
    checks.append(("两态解析", bad["verdict"] == "有毛病" and bad["defect_step"] == 2))
    row = verifications.record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=bad)
    # 编号宽度不许写死（2026-10-14 业主裁定：4 位 → 6 位）：发号点是
    # `next_verification_id` 的 `f"v-{S.format_id(...)}"`，所以断言也从
    # `schema` 取形态。旧写法写死 `"v-0001"`，宽度一改这条自检就红 ——
    # 那是断言过期（`v-0001` 这一格属于旧四位号），不是发号器坏了。
    checks.append((f"编号从 v-{S.format_id(1)} 起（六位；旧四位号读侧兼容）",
                   row["verification_id"] == f"v-{S.format_id(1)}"))
    checks.append(("有毛病不签第 3 位", bit3_payload(row) == {}))
    good = parse_verdict('{"verdict": "成立", "findings": []}')
    first = verifications.record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    checks.append(("第 1 次成立只落台账、不翻位（业主 2026-10-29）",
                   bit3_payload(first, streak=consecutive_holds(root, "0007")).get("reviewed")
                   is not True))
    verifications.record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    ok_row = verifications.record_verification(root, statement_id="0007", proof_text="1. 由定义直接得到。", verdict=good)
    holds = consecutive_holds(root, "0007")
    checks.append((f"连续 {verifications.SIGN_STREAK_NEED} 次成立才签第 3 位",
                   holds["streak"] >= verifications.SIGN_STREAK_NEED
                   and bit3_payload(ok_row, streak=holds).get("reviewed") is True))
    checks.append(("追加式（四行）", len(list_verifications(root, limit=None)[0]) == 4))
    checks.append(("limit=0 是零条、limit=None 才是全量",
                   list_verifications(root, limit=0)[0] == []
                   and len(list_verifications(root, limit=None)[0]) == 4))
    try:
        parse_verdict("我不确定")
        unparsable = False
    except VerificationError:
        unparsable = True
    checks.append(("没查成抛错（不冒充审过了）", unparsable))
    # 2026-11-02（业主：这一档连历史兼容读也不留）：老行上的那一格按 `成立` 读、能签、
    # 而且算一票。三条一起判 —— 只判"读成成立"会漏掉"它在连续计数里仍被跳过"。
    legacy = {"verdict": "看不出来", "unresolved_errors": 0, "citation_checks": []}
    checks.append(("老行上的已取消档：原样读、且不算票",
                   read_verdict(legacy) == "看不出来" and not row_signable(legacy)))
    checks.append(("连续计数：成立, 已取消档, 成立 = [1,1,2]（那一档不投也不清零）",
                   _hold_run_lengths([
                       {"verdict": "成立", "proof_sha256": "x", "unresolved_errors": 0},
                       dict(legacy, proof_sha256="x"),
                       {"verdict": "成立", "proof_sha256": "x", "unresolved_errors": 0},
                   ]) == [1, 1, 2]))
    for name, good_ in checks:
        print(f"  [{'PASS' if good_ else 'FAIL'}] {name}")
    return 0 if all(g for _, g in checks) else 1


# 跨模块引用放在文件末尾：这些名字的实现在别的模块里，而两个模块可能互相
# 引用（顶层 `from .x import y` 在环里会在对方还没定义完时执行）。引用点
# 全部在函数体里，所以只要定义都跑完了，谁先被导入都拿得到。
from . import verifications  # 门面字典：被打桩的名字经它取
from .v_paths import (  # noqa: F401 — 实现在 v_paths.py
    VerificationError,
    parse_verdict,
)
from .v_rowread import (  # noqa: F401 — 实现在 v_rowread.py
    bit3_payload,
    list_verifications,
    read_verdict,
    row_signable,
)
from .v_streak import (  # noqa: F401 — 实现在 v_streak.py
    _hold_run_lengths,
    consecutive_holds,
)
