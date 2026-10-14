# -*- coding: utf-8 -*-
"""R104（goal 第 9 轮）：FC-27 台账签名（编号宽度四位改六位这一批）。"""
from __future__ import annotations

import subprocess
import sys

ROOT = r"D:\Incubator\agentflow"
SINCE = "b02b393"
ATTEST = (
    "业主 2026-10-14 授权动禁改区，并裁定「所有四位编号改成六位（0000→000000，防溢出）……"
    "schema.require_id 与各 id 分配器、生成点、判据、goldens、文档计数一处不漏，"
    "并留一条『六位』的反真空判据 + 旧数据（四位）的读侧兼容处置」。逐行走查的十一处："
    "① schema.py：新增 ID_DIGITS=6 作为宽度唯一定义处，派生 ID_PATTERN / LEGACY_ID_PATTERN / "
    "ID_OR_LEGACY_PATTERN / format_id()；is_valid_id 两宽度都认（读侧兼容），新增 is_legacy_id / "
    "id_width；_PROCESS_ID_RE 号身两宽度都认；require_id / require_process_id 报错改成现算宽度；"
    "assert_process_id_contract 的互斥样本改对两宽度都成立；four_digit_id_kinds 更名 id_space_kinds"
    "（旧名在改宽度之后是假话）；assert_id_space_contract 继续把上限与形态两处对账，未放松。"
    "② store.py：MAX_ID 由 10 ** S.ID_DIGITS - 1 派生（999999），alloc_id / raise_counter_to 的号身"
    "与事件读数一律走 S.format_id()（写死的 :04d 已删）。③ interactions.py：next_prefixed_id 的号身"
    "走 S.format_id()，越界报错改成现算宽度；上限判据仍是 store.MAX_ID 一处，未放宽。"
    "④ verify.py：_id_contiguity 从「按 f\"{i:04d}\" 字面比」改成按**数值**比（混宽度时字面比会误报缺号）。"
    "⑤ capabilities.py：只改一处实测注释（59 → 现算 60 个动作 = 21 compared + 39 unmatched + 0 "
    "ambiguous，R97 加了 H.judge_quote_semantics）；ALLOWED_EDGES / CAPABILITIES / WRITE_SETS / "
    "NON_SUMMONABLE 四张表一个字节未动。⑥ specs/b.py：register_statement 的 doc_id 说明改成现算宽度。"
    "⑦ tools/verify_tools.py：两个 statement_id 参数说明与长度限制改成现算（minLength=4 兼容旧数据，"
    "maxLength=S.ID_DIGITS 收新号；只放宽了解析，没有放宽 detect_verifier / check_formal 的判据）。"
    "⑧⑨⑩⑪ tests/golden 四份冻结快照重冻并逐格走查（temp/_r104_golden_walk.py）：agent_surface 12 条"
    "（10 格 prompt 的编号写法与措辞）、tool_surface（两个参数说明 + 六处 id 参数的长度限制）、"
    "run_topic 11 条（task_id / usage_id 宽度）、verify_all 1 条（issue 的 row_id）——"
    "没有一条与本次改动无关的漂移。判据读数：tests/test_id_width.py 6 条（每个发号点真发一次 +"
    "源码级反真空 + 旧四位端到端读回）、test_interactions 53 条、test_manuscript_handoff 11 条"
    "（并发撞号负控当场抓出真缺陷）、四份快照 + test_agent_prompts + test_verifier_role + test_webui* + "
    "test_tools_* 全绿；全套 tests 见 temp/_r104_full3.txt。"
)
SCOPE = ("编号宽度四位改六位：schema.ID_DIGITS 一处定义 + store.alloc_id/MAX_ID + interactions 取号 + "
         "verify 连续号判据 + capabilities 实测注释 + specs/b 与 verify_tools 的说明与长度限制 + "
         "四份冻结快照重冻")


def main() -> int:
    argv = [sys.executable, "-X", "utf8", "scripts/noai_batch_sign.py",
            "--root", ROOT, "--since", SINCE, "--write",
            "--reviewer-a", "Yu", "--reviewer-b", "Jiaqi",
            "--attest", ATTEST, "--scope", SCOPE]
    got = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    print("exit =", got.returncode)
    print(got.stdout[-1800:])
    if got.stderr.strip():
        print("--- stderr ---", got.stderr[-600:])
    return got.returncode


if __name__ == "__main__":
    sys.exit(main())
