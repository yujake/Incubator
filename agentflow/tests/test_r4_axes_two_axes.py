"""`axes-1` / `axes-3` / `axes-4` 的回归判据（`tools/base.py` + `capabilities.py`
+ `tools/verify_tools.py`，前两者之一与后者都在 FC-27 禁改区）。

改前备份：`temp/zone-backup-r4-src_agentflow_tools_base.py` /
`temp/zone-backup-r4-src_agentflow_capabilities.py` /
`temp/zone-backup-r4-src_agentflow_tools_verify_tools.py`。

这三条的共同形态是文档与事实相反（不是风格问题）：
`axes-1` 说词表只有一份（实际两份）、`axes-3` 把不可达的 `True` 档写成活的三种取值、
`axes-4` 说 `check_formal` 不需要审批（实测需要）。所以判据分两半：
行为断言（读声明，不读文档）+ 文本断言（文档不再说反话）。
"""
from __future__ import annotations

import pathlib

import pytest

from agentflow.tools import build_registry

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentflow"
BASE_PY = SRC / "tools" / "base.py"
VERIFY_TOOLS_PY = SRC / "tools" / "verify_tools.py"
CAPABILITIES_PY = SRC / "capabilities.py"


@pytest.fixture
def reg(store):
    return build_registry(store=store, workspace_root=store.root, strict=True).registry


# ============================================================ axes-4（行为为主）


def test_check_formal_declares_exec_and_needs_approval(reg) -> None:
    """`axes-4` 的正控：三件套必须等于 `(read, exec, True)`。

    这条读的是声明，不是文档 —— 改 `declared_external` 会让它红。
    """
    sp = reg._specs["verify.check_formal"]
    assert (sp.side_effect, sp.external, sp.needs_approval) == ("read", "exec", True)


def test_detect_verifier_does_not_need_approval(reg) -> None:
    """成对的那一条：`detect_verifier` 是 `read` + `none` ⇒ 不需要审批。

    没有它，"把两个工具都改成需要审批"也能让上一条通过，而那句 docstring
    要区分的正是"两处说法不一致"这件事。
    """
    sp = reg._specs["verify.detect_verifier"]
    assert (sp.side_effect, sp.external, sp.needs_approval) == ("read", "none", False)


def test_the_approval_claim_in_the_docstring_matches_the_declaration() -> None:
    """`axes-4` 的文本判据：那句"两者都不需要审批"必须只出现在修改说明里。

    为什么必须用文本判据：这句错的后果就是"读它的人把审批面记错"，
    而审批面本身（声明）是对的 —— 没有任何行为测试能发现文档在说谎。

    判据形状（第一版写错过）：`assert 旧句子 not in text` 会红，因为改后的
    docstring 引用了那句错话来解释改了什么。所以要区分"作为结论出现"
    与"作为被引用的错话出现" —— 前者是裸行，后者前面有引号或"旧版"字样。
    """
    text = VERIFY_TOOLS_PY.read_text(encoding="utf-8")
    bad = [ln.strip() for ln in text.splitlines()
           if "两者都不需要审批" in ln and "旧版" not in ln and '"' not in ln]
    assert bad == [], f"这句错话仍作为结论出现：{bad}"
    assert '**但"都不需要审批"只对 `detect_verifier` 成立**' in text, \
        "改后的口径说明不见了（判据的落点变了，请更新本用例）"
    # 反向守卫：不许有人"为了这句话成真"去把 exec 的声明抹掉
    assert '"exec"' in text, "check_formal 的第二根轴声明不见了 —— 那是把两根轴压回一档"


# ============================================================ axes-1（两份字面量）


def test_both_vocabularies_exist_and_agree() -> None:
    """`axes-1` 的事实面：两处各有一份字面量，且逐字相等。

    旧 docstring 说"只有一份、capabilities import 这里" —— 那句与代码事实相反。
    这里断言的是事实：两份都在、内容一致（由导入期交叉断言钉住）。
    """
    from agentflow import capabilities as C
    from agentflow.tools import base as B

    assert tuple(B.EXTERNAL) == tuple(C.EXTERNAL) == ("none", "egress", "exec")
    assert tuple(B.SIDE_EFFECTS) == tuple(C.SIDE_EFFECTS)
    assert tuple(B.EFFECT) == tuple(C.EFFECT)


def test_the_docstring_no_longer_claims_a_single_source() -> None:
    """`axes-1` 的文本判据：那句"只有这一份"必须只出现在修改说明里。

    与 `axes-4` 同一个形状：改后的 docstring 会引用那句错话来解释改了什么，
    所以判据要区分"作为结论出现"（裸行）与"作为被引用的错话出现"。
    """
    text = BASE_PY.read_text(encoding="utf-8")
    bad = [ln.strip() for ln in text.splitlines()
           if "取值清单只有这一份" in ln and "旧docstring" not in ln and '"' not in ln]
    assert bad == [], f"这句错话仍作为结论出现：{bad}"
    assert "取值清单**有两份字面量**" in text, "改后的口径说明不见了"
    assert "`capabilities.py`" in text, "必须点名第二个落点"


# ============================================================ axes-3（不可达的那一档）


def test_sandbox_available_is_none_and_has_no_wiring() -> None:
    """`axes-3` 的事实面：默认 `None`，且全仓库没有任何设置入口。

    判据用"grep 每一处出现都能归类"：定义 / 读取 / 未使用的导入 / 测试注入。
    出现第五类（例如 `build_registry(..., sandbox_available=...)`）就该更新本用例 ——
    那意味着有人补齐了入口，而 `axes-3` 的口径随之变化。
    """
    import subprocess
    import sys

    from agentflow.tools import base as B

    assert B.SANDBOX_AVAILABLE is None, (
        "默认值不再是 None —— 那会让 needs_approval 的判据在生产里变档；"
        "若这是有意补齐的入口，请连同 draft/28 的 axes-3 一起更新"
    )
    out = subprocess.run(
        [sys.executable, "-c",
         "import pathlib,sys\n"
         "root=pathlib.Path(sys.argv[1])\n"
         "hits=[]\n"
         "for p in list(root.rglob('*.py')):\n"
         "    for i,l in enumerate(p.read_text(encoding='utf-8').splitlines(),1):\n"
         "        if 'SANDBOX_AVAILABLE' in l:\n"
         "            hits.append(f\"{p.relative_to(root)}:{i}:{l.strip()}\")\n"
         "print(chr(10).join(hits))\n",
         str(SRC.parent.parent)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    assert lines, "扫描没读到任何出现 —— 判据没接上（不是'没问题'）"
    # 允许的四类：定义、from-import 那一行、读取点、测试里的 monkeypatch/setattr
    allowed = ("SANDBOX_AVAILABLE: bool | None = None", "SANDBOX_AVAILABLE",
               "import SANDBOX_AVAILABLE", "monkeypatch.setattr", "setattr(")
    for ln in lines:
        assert any(a in ln for a in allowed), f"出现了一处未归类的地方：{ln}"
    # 装配层不得接受它作为参数 —— 那是 axes-3 里"补齐入口"的另一条口径
    assert "sandbox_available=" not in out.stdout, \
        "有人补了 sandbox_available 入口：axes-3 的口径要一起更新（并需人审）"


def test_the_unreachable_true_branch_is_documented_as_unreachable() -> None:
    """`axes-3` 的文本判据：`True` 那一档必须被显式登记为不可达。

    旧版把它与 `None` / `False` 并列写成"三种有意义的取值"，读者会以为三档都活着。
    """
    text = BASE_PY.read_text(encoding="utf-8")
    assert "`True` 这一档在**当前环境里不可达**" in text, \
        "docstring 没有登记这一档不可达（读者会以为三档都在用）"
    assert "没有任何配置或装配入口" in text, "没有写清'没有入口'这个事实"
