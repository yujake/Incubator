# -*- coding: utf-8 -*-
"""现算十一格提示词摘要，与 `tests/test_agent_prompts.py` 里那张冻结表对账（可选写回）。

## 为什么它是长期工具，而不是某趟真机的取证

提示词每改一段、`PROMPT_VERSION` 每抬一版，这十一格摘要就必然变一次
（`tests/test_agent_prompts.py` 的冻结表是「这一版是哪些段」的指纹）。重算这件事
跟着改动走，不是跟着某次事故走 ⇒ 它属于 `scripts/`，不属于 `temp/`。
（原稿：`temp/_recompute_digests.py`，2026-11-20 提升。）

## 为什么必须借判据自己的函数

摘要口径里有四处夹具替换（工具链读数 / 形式化写法 / 派活上限 / 版本行归一）。
自己另写一份就等于另立一个口径 —— 而这条判据正是靠「同口径」才有牙。
所以本脚本 import 判据文件、只调它的 `_surface_digest` 与 `_registry`（后者与判据的
`registry` 夹具逐字相同：不带工作区的注册表，它没有 fs 工具）。

## 用法（在 `agentflow/` 下）

    python scripts/recompute_prompt_digests.py            # 只报：0=一致 / 1=漂了 / 2=没查成
    python scripts/recompute_prompt_digests.py --write    # 写回冻结表与版本号

退出码沿用本仓三态：0 = 查过、一致；1 = 查过、有格不一致；2 = 没查成
（判据文件 import 不进来 / 读不出 / 写失败）。没查成不是一致。
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
JUDGE = TESTS / "test_agent_prompts.py"


def _judge():
    """按路径导入判据文件（`tests/` 不是包，且它自己会 import 若干测试期夹具）。"""
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(TESTS))
    import conftest  # noqa: F401  —— 钉环境（Lean 开 / 设置文件 / 机器事实）与判据同一条

    spec = importlib.util.spec_from_file_location("TP", JUDGE)
    if spec is None or spec.loader is None:
        raise ImportError(f"加载不了 {JUDGE}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _registry():
    from agentflow.tools import build_registry

    return build_registry().registry


def compute(mod) -> dict[str, str]:
    """逐角色现算摘要（键集合与判据的 `ALL_ROLES` 同源）。"""
    reg = _registry()
    return {role: mod._surface_digest(role, reg) for role in mod.ALL_ROLES}


def _current_version() -> str:
    from agentflow import agent_prompts as AP

    return str(AP.PROMPT_VERSION)


def _rewrite(text: str, digests: dict[str, str], version: str) -> tuple[str, list[str]]:
    """把冻结表与版本号改写成现算值；返回 (新文本, 改了的角色名)。"""
    hits: list[str] = []
    for role, digest in digests.items():
        pat = re.compile(rf'(\n    "{re.escape(role)}": ")[0-9a-f]{{64}}(",)')
        text, n = pat.subn(rf"\g<1>{digest}\g<2>", text, count=1)
        if n:
            hits.append(role)
    text, n = re.subn(r'(_FROZEN_PROMPT_VERSION = ")[^"]+(")',
                      rf"\g<1>{version}\g<2>", text, count=1)
    if n:
        hits.append("_FROZEN_PROMPT_VERSION")
    return text, hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="现算十一格提示词摘要，与 tests/test_agent_prompts.py 的冻结表对账")
    ap.add_argument("--write", action="store_true",
                    help="把冻结表与 _FROZEN_PROMPT_VERSION 写回成现算值（缺省只报）")
    args = ap.parse_args(argv)

    try:
        mod = _judge()
        digests = compute(mod)
        version = _current_version()
    except Exception as exc:  # noqa: BLE001 - 任何一步失败都是"没查成"
        print(f"[unknown] 算不出摘要：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    frozen = dict(getattr(mod, "_FROZEN_PROMPT_DIGESTS", {}))
    frozen_version = str(getattr(mod, "_FROZEN_PROMPT_VERSION", ""))
    drift = [r for r in digests if frozen.get(r) != digests[r]]
    missing = [r for r in digests if r not in frozen]
    for role in sorted(digests):
        mark = "OK " if frozen.get(role) == digests[role] else "DRIFT"
        print(f"  [{mark}] {role} 现算 {digests[role][:16]}…  冻结 {str(frozen.get(role, ''))[:16]}…")
    print(f"  版本：现算 {version} / 冻结 {frozen_version}")
    if missing:
        print(f"[warn] 冻结表里没有这些角色：{missing}")

    if args.write:
        try:
            text = JUDGE.read_text(encoding="utf-8")
            new_text, hits = _rewrite(text, digests, version)
            if new_text != text:
                JUDGE.write_text(new_text, encoding="utf-8", newline="")
        except OSError as exc:
            print(f"[unknown] 写不回：{type(exc).__name__}: {exc}", file=sys.stderr)
            return 2
        print(f"[write] 改了 {len(hits)} 处：{hits}")
        return 0

    same = not drift and not missing and version == frozen_version
    print("[ok] 冻结表与现算一致" if same else
          f"[drift] 不一致：角色 {drift}；版本 {'一致' if version == frozen_version else '不一致'}")
    return 0 if same else 1


if __name__ == "__main__":
    raise SystemExit(main())
