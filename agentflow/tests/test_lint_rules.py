"""`scripts/lint_rules.py` 的测试。

## 为什么在合成小树上测，而不是在真实仓库上测

linter 是一个"目录 → 命中列表"的函数。在真实仓库上断言"命中数 == 7"会把测试
绑死在当前代码状态上：任何一次正常重构都会让它红，而红了之后人会去改数字
而不是去看规则 —— 那正是"测试变成橡皮图章"的路径。

所以这里用 `tmp_path` 造最小的合成树，每个用例只放触发/不触发那一条规则
所需的最少代码。这样：
- 规则的行为被精确钉住；
- 规则的校准（假阳性率）可以被逐条验证；
- 真实仓库的命中数由 `scripts/release_check.py` 负责观察，而不是由测试断言。

## 每个规则都要有正反两向（FC-09）

只有正向（"该触发的触发了"）不够 —— 一个永远报错的规则也能通过所有正向断言。
所以每条规则至少配一条"不该触发的确实没触发"。
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load_linter():
    """按路径导入 `scripts/lint_rules.py`（`scripts/` 不是包，不能普通 import）。"""
    spec = importlib.util.spec_from_file_location("_lint_rules_under_test", _SCRIPTS / "lint_rules.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load_linter()


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    """造一棵最小源码树：键是相对 `src/agentflow/` 的路径。

    顺带写一份最小 `.noai-paths`：R009（注释里的装饰）要按"是否禁改区"
    决定报 error 还是 info，读不到清单时它按三态纪律报"没查成"（error）——
    所以合成树也得声明禁改区，否则每一条用例都会多出一个与它无关的 error。
    声明的是一个没有任何用例会去写的文件，因此不影响其他规则的命中数。
    """
    base = tmp_path / "src" / "agentflow"
    base.mkdir(parents=True, exist_ok=True)
    for rel, body in files.items():
        p = base / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    (tmp_path / ".noai-paths").write_text(
        "# 合成树的禁改区清单（只为让 R009 能分流区内/区外）。\n"
        "[category: solver-core] 合成树的禁改区\n"
        "src/agentflow/frozen.py  [category: solver-core] 合成树里的假禁改区\n",
        encoding="utf-8",
    )
    return tmp_path


# ============================================================ R001 except-pass


def test_r001_flags_unexplained_swallow(tmp_path):
    """正向：没有任何解释的 `except: pass` ⇒ error。"""
    root = _tree(tmp_path, {"m.py": "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"})
    got = L.rule_R001_bare_except_pass(root)
    assert len(got) == 1 and got[0].level == "error" and got[0].line == 4


def test_r001_allows_explained_swallow(tmp_path):
    """负控（这条规则的校准）：带解释的忽略不报。

    第一版规则把所有 `except: pass` 都报成 error，在真实代码上产生 29 个 error，
    其中 22 个是故意且带注释的设计决定（"日志钩子坏了不该打断主流程"）。
    那会让这条门在第一次运行时就失去可信度 —— 假报警比不校验更糟。
    """
    root = _tree(tmp_path, {
        "a.py": "def f():\n    try:\n        g()\n    except Exception:  # 日志钩子坏了不该打断主流程\n        pass\n",
        "b.py": "def f():\n    try:\n        g()\n    except Exception:\n        # 同上：这里的失败不影响结论\n        pass\n",
        "c.py": "def f():\n    try:\n        g()\n    except Exception:  # noqa: BLE001\n        pass\n",
    })
    assert L.rule_R001_bare_except_pass(root) == []


def test_r001_ignores_non_pass_bodies(tmp_path):
    """负控：`except` 之后做了别的事（不是 `pass`）⇒ 不报（那是错误处理，不是吞掉）。"""
    root = _tree(tmp_path, {"m.py": "def f():\n    try:\n        g()\n    except Exception as e:\n        return str(e)\n"})
    assert L.rule_R001_bare_except_pass(root) == []


# ============================================================ R002 None→空容器


def test_r002_flags_bare_empty_return(tmp_path):
    """正向：`is None` 之后光秃秃地 `return []` ⇒ warning（本项目最贵的缺陷形态）。"""
    root = _tree(tmp_path, {
        "m.py": "def f(x):\n    if x is None:\n        return []\n    return x\n",
    })
    got = L.rule_R002_none_folds_to_empty(root)
    assert len(got) == 1 and got[0].level == "warning"


def test_r002_ignores_empty_return_carrying_a_reason(tmp_path):
    """负控（校准）：`return [], "<为什么>"` ⇒ 带回伴生原因 ⇒ 不报。

    这是 `tools/search_tools._literature_rows` 的形态（一次真实假阳性）：
    空表在下游是有效结论（`search.dedup_check` 会说"不是重复"），所以它
    必须同时带回"是没配 store 还是表坏了"。那正是三态纪律的正确写法。
    旧判据靠关键词匹配（`reason`/`checked`），而这里用的是中文理由字符串 ⇒ 被误报。
    """
    root = _tree(tmp_path, {
        "m.py": (
            "def f(ctx):\n"
            "    if ctx.store is None:\n"
            '        return [], "未配置 store（不是表坏了）"\n'
            "    return ctx.store.rows()\n"
        ),
    })
    assert L.rule_R002_none_folds_to_empty(root) == []


def test_r002_still_flags_empty_return_whose_second_element_is_none(tmp_path):
    """负控的反面（收紧边界）：`return [], None` ⇒ 仍然报。

    "带回一个伴生值"不等于"带回了一个原因"。第二元素是 `None` 时，
    调用方仍然分不出"没做"与"做了没有" —— 那正是这条规则要抓的形态。
    这一条防止上面那条放宽被滥用成"随便多返回一个东西就免检"。
    """
    root = _tree(tmp_path, {
        "m.py": "def f(x):\n    if x is None:\n        return [], None\n    return x\n",
    })
    got = L.rule_R002_none_folds_to_empty(root)
    assert len(got) == 1 and got[0].level == "warning", got


# ============================================================ R003 同名定义


def test_r003_flags_two_independent_implementations(tmp_path):
    """正向：两个模块各有独立实现 ⇒ warning（`slugify`/`normalize_doi` 的形态）。"""
    body = "def slugify(x):\n    y = x.strip()\n    return y\n"
    root = _tree(tmp_path, {"a.py": body, "b.py": body})
    got = L.rule_R003_duplicate_public_defs(root)
    assert len(got) == 2 and all(g.level == "warning" and "slugify" in g.message for g in got)


def test_r003_exempts_a_forwarder(tmp_path):
    """负控（这条规则的校准）：一份独立实现 + 一份转发 ⇒ 不报。

    `agent_d.detect_contradictions` 是刻意的转发（"唯一权威实现已移到 interactions.py"）。
    把它报成"两份实现"是假报警。
    """
    root = _tree(tmp_path, {
        "core.py": "def detect(x):\n    a = 1\n    return a\n",
        "adapter.py": "from .core import detect\n\ndef detect(x):\n    return detect(x)\n",
    })
    assert L.rule_R003_duplicate_public_defs(root) == []


def test_r003_exempts_forwarder_with_lazy_import(tmp_path):
    """负控（第二次校准）：转发体里有惰性 import 时仍算转发。

    这是本条规则一次真实的假阳性：`fetch.slugify` / `providers.normalize_doi`
    合并后写成

    ```python
    def slugify(text, ...):
        from .textutil import slugify as _impl   # 避免模块级循环依赖
        return _impl(text, ...)
    ```

    旧判据要求函数体字面上只有一条 return，于是把这份转发报成了
    "两份独立实现"。惰性 import 是实现细节，它没有重述任何判据。
    """
    root = _tree(tmp_path, {
        "core.py": "def slugify(x):\n    a = x.strip()\n    return a\n",
        "adapter.py": (
            "def slugify(x):\n"
            "    from .core import slugify as _impl\n"
            "    return _impl(x)\n"
        ),
    })
    assert L.rule_R003_duplicate_public_defs(root) == []


def test_r003_still_flags_return_preceded_by_assignment(tmp_path):
    """负控的反面（收紧边界）：return 之前有赋值 ⇒ 不算转发，仍要报。

    放宽"前导 import"不等于放宽一切：赋值/分支/`try` 能在转发之外
    悄悄改变语义（吞异常、补默认值、改返回值）—— 那正是这条规则要抓的形态。
    没有这一条，上一条放宽就会把"任何函数体只有一条 return 的包装"都放行。
    """
    root = _tree(tmp_path, {
        "core.py": "def slugify(x):\n    a = x.strip()\n    return a\n",
        "adapter.py": (
            "def slugify(x):\n"
            "    from .core import slugify as _impl\n"
            "    x = x or 'untitled'\n"          # ← 悄悄补了默认值
            "    return _impl(x)\n"
        ),
    })
    got = L.rule_R003_duplicate_public_defs(root)
    assert len(got) == 2 and all("slugify" in g.message for g in got), got


def test_r003_exempts_allowlisted_names(tmp_path):
    """负控：例外清单里的名字不报 warning（会以 `info` 记录，便于审计例外本身）。"""
    body = "def register(reg):\n    a = 1\n    return a\n"
    root = _tree(tmp_path, {"m1.py": body, "m2.py": body})
    got = L.rule_R003_duplicate_public_defs(root)
    assert all(g.level == "info" for g in got), got


# ============================================================ R004 注册表绕道


def test_r004_flags_registry_outside_tools(tmp_path):
    """正向：工具层之外构造 `ToolRegistry` ⇒ warning（绕过 roles 校验）。"""
    root = _tree(tmp_path, {"agent_x.py": "def install():\n    reg = ToolRegistry(name='x')\n    return reg\n"})
    got = L.rule_R004_registry_outside_tools(root)
    assert len(got) == 1 and got[0].line == 2


def test_r004_ignores_selftest_scaffolding(tmp_path):
    """负控（校准）：`_selftest()` 里的局部注册表是测试脚手架，不是装配点。"""
    root = _tree(tmp_path, {
        "agent_x.py": "def _selftest():\n    reg = ToolRegistry(name='x')\n    return reg\n",
    })
    assert L.rule_R004_registry_outside_tools(root) == []


def test_r004_does_not_match_inside_docstring(tmp_path):
    """负控（第二次校准）：docstring / 注释里提到 `ToolRegistry(` 不算构造注册表。

    这是本条规则一次真实的假阳性：`agent_d.validate_tool_roles` 的 docstring 里
    逐字写着

    ```text
    ``ToolRegistry(name="agent-D")`` + ``register_function``
    ```

    —— 那是在解释这个反模式（说明 `install_d_tools` 不走 `build_registry`），
    却被逐行正则当成了缺陷本身。"描述一个反模式"不等于"采用了这个反模式"，
    这条负控就是钉住这一点。
    """
    root = _tree(tmp_path, {
        "agent_x.py": (
            'def validate(reg):\n'
            '    """它自己 ``ToolRegistry(name="agent-D")`` + register_function。"""\n'
            "    return reg\n"
        ),
    })
    assert L.rule_R004_registry_outside_tools(root) == []


def test_r004_info_when_validator_is_declared(tmp_path, monkeypatch):
    """负控（校准三）：函数体里调用了已登记的校验器 ⇒ 降为 `info`，不是 warning。

    这正是规则提示里那句"或显式调用同一份校验函数（不要复制它的判据）"的
    可判定形式。用 monkeypatch 造一个临时名单，不动真实名单 ——
    否则这条测试会随真实名单增删而变红/变绿，那就不是在测判据了。
    """
    monkeypatch.setattr(L, "ROLE_VALIDATOR_CALLS", {"validate_roles": "测试用：假装它执行了同一份判据"})
    root = _tree(tmp_path, {
        "agent_x.py": (
            "def install():\n"
            "    reg = ToolRegistry(name='x')\n"
            "    validate_roles(reg)\n"
            "    return reg\n"
        ),
    })
    got = L.rule_R004_registry_outside_tools(root)
    assert len(got) == 1 and got[0].level == "info", got
    assert "validate_roles" in got[0].message


def test_r004_still_warns_when_validator_is_called_elsewhere_in_file(tmp_path, monkeypatch):
    """负控的反面（收紧边界）：校验器在文件里别处被调用 ⇒ 仍然是 warning。

    豁免必须按"最内层函数体"判定。若放宽到文件级，这条规则就退化成
    "文件级忽略" —— 而文件级忽略正是本项目最反对的形态（假阴性且看不出来）。
    """
    monkeypatch.setattr(L, "ROLE_VALIDATOR_CALLS", {"validate_roles": "测试用"})
    root = _tree(tmp_path, {
        "agent_x.py": (
            "def install():\n"
            "    reg = ToolRegistry(name='x')\n"      # ← 这一处没校验
            "    return reg\n"
            "\n"
            "def other():\n"
            "    validate_roles(None)\n"              # ← 校验在别的函数里
        ),
    })
    got = L.rule_R004_registry_outside_tools(root)
    assert len(got) == 1 and got[0].level == "warning", got


def test_role_validator_names_exist_in_the_real_tree():
    """反腐烂：`ROLE_VALIDATOR_CALLS` 里的每个名字都必须在真实代码里存在。

    没有这一条，名单会腐烂：函数被改名/删掉之后，名单里留着一个不存在的名字，
    于是豁免永远命中不了 —— 那是静默失效（门还在，只是再也不生效）。
    与 `.noai-paths` 的"理由里写符号名并由测试断言符号存在"是同一个手法。
    """
    import re as _re

    src = Path(__file__).resolve().parents[1] / "src" / "agentflow"
    text = "\n".join(
        p.read_text(encoding="utf-8") for p in src.rglob("*.py") if "__pycache__" not in p.parts
    )
    missing = [n for n in L.ROLE_VALIDATOR_CALLS if not _re.search(rf"\bdef\s+{_re.escape(n)}\b", text)]
    assert not missing, f"ROLE_VALIDATOR_CALLS 里的这些名字在源码树里没有 `def`：{missing}"


def test_registry_builders_exist_in_the_tools_layer():
    """反腐烂：`REGISTRY_BUILDERS` 里的名字必须在工具层里有 `def`。

    为什么钉在工具层：这两个名字的全部意义是"用正规的装配入口"。
    如果 `build_registry` 被挪走或改名，豁免就会指向一个不存在的东西 ——
    而那时 R004 会看起来还在工作（其它点仍会报），只是这一侧静默失效。
    """
    import re as _re

    tools = Path(__file__).resolve().parents[1] / "src" / "agentflow" / "tools"
    text = "\n".join(
        p.read_text(encoding="utf-8") for p in tools.rglob("*.py") if "__pycache__" not in p.parts
    )
    missing = [n for n in L.REGISTRY_BUILDERS if not _re.search(rf"\bdef\s+{_re.escape(n)}\b", text)]
    assert not missing, f"REGISTRY_BUILDERS 里的这些名字在工具层里没有 `def`：{missing}"


def test_r004_exempts_a_function_that_calls_a_registry_builder(tmp_path):
    """负控（校准四）：同一函数体里调了 `build_registry` ⇒ roles 校验跑过 ⇒ 不当 warning。

    真实案例：`agent_h.install_h_tools` 先 `build_registry(...)`（roles 已核），
    再从它的 `for_role("H")` 结果里筛出只读子集重新注册。这不是绕过。

    结果记成 `info` 而不是彻底不报：这条规则的价值有一半在"每一处构造注册表的
    地方都留下一条可审计的记录"。彻底不报会让"我没看见"与"校验过了"在输出里长得一样。
    """
    root = _tree(tmp_path, {
        "agent_x.py": (
            "def install():\n"
            "    build = build_registry(store=store)\n"
            "    reg = ToolRegistry(name='x')\n"
            "    return reg\n"
        ),
    })
    got = L.rule_R004_registry_outside_tools(root)
    assert len(got) == 1 and got[0].level == "info", got
    assert "build_registry" in got[0].message


def test_r004_exempts_nested_helpers_inside_a_selftest(tmp_path):
    """负控（校准三）：命中点在嵌套小工具里、而祖先函数是自检 ⇒ 不报。

    真实案例：`tools/fs_tools.py` 的自检里先定义了 `def check(...)`，
    然后在自检函数体里构造 `ToolRegistry(name="selftest")`。
    只按"最内层 def"判会让这条命中被当装配点（两个纯假阳性）；
    按整条嵌套链判才看得出它是 `_selftest` 里的脚手架。
    """
    root = _tree(tmp_path, {
        "tools_like.py": (
            "def _selftest():\n"
            "    def check(label, cond):\n"
            "        return label\n"
            "    reg = ToolRegistry(name='selftest')\n"
            "    return check('x', True)\n"
        ),
    })
    assert L.rule_R004_registry_outside_tools(root) == []


def test_r004_allowed_sites_still_exist():
    """反腐烂：`R004_ALLOWED_SITES` 的每个 `(文件, 函数)` 都必须在真实树里存在。

    例外的价值全在"它指的是真实存在的那个装配点"。
    一旦函数被改名或文件被挪走，键就指向空气 —— 例外永久静默，而报告里看不出
    （这不是"少报了一条"，是"豁免了一条不存在的规则"）。
    """
    repo = Path(__file__).resolve().parents[1]
    bad: list[str] = []
    for (rel, fn), reason in L.R004_ALLOWED_SITES.items():
        p = repo / rel
        if not p.is_file():
            bad.append(f"{rel} 不存在")
            continue
        if not re.search(rf"\bdef\s+{re.escape(fn)}\b", p.read_text(encoding="utf-8")):
            bad.append(f"{rel} 里没有 `def {fn}`")
        if len(reason.strip()) < 20:
            bad.append(f"({rel}, {fn}) 的理由太短 —— 写不出理由就该改代码，而不是加例外")
    assert not bad, bad


def test_r004_reports_a_declared_site_as_info_not_warning(tmp_path, monkeypatch):
    """正向：已登记的例外降为 `info`，且消息里带着理由（可审计，不是静默放过）。"""
    monkeypatch.setattr(
        L, "R004_ALLOWED_SITES",
        {("src/agentflow/agent_x.py", "install"): "测试用：该装配点用内联的 fail-closed 断言执行了同一条判据"},
    )
    root = _tree(tmp_path, {
        "agent_x.py": "def install():\n    reg = ToolRegistry(name='x')\n    return reg\n",
    })
    got = L.rule_R004_registry_outside_tools(root)
    assert len(got) == 1 and got[0].level == "info", got
    assert "已逐点登记为例外" in got[0].message


# ============================================================ R005 写死角色名单


def test_r005_flags_full_role_enumeration(tmp_path):
    """正向：枚举全部角色的字面量 ⇒ warning（`cli.cmd_tools` 的形态）。"""
    root = _tree(tmp_path, {"cli.py": 'ROLES_ALL = ("A", "B", "C", "D", "E", "F", "G", "H")\n'})
    got = L.rule_R005_hardcoded_role_list(root)
    assert len(got) == 1


def test_r005_allows_subset_role_declaration(tmp_path):
    """负控（校准）：子集声明（≤4 个）不报 —— 工具模块的 `_ROLES = ("E","F","G")` 是合法的。"""
    root = _tree(tmp_path, {
        "t1.py": '_ROLES = ("E", "F", "G")\n',
        "t2.py": '_ROLES = ("A", "B", "C", "D")\n',
    })
    assert L.rule_R005_hardcoded_role_list(root) == []


# ============================================================ R007 缺 docstring


def test_r007_daily_reports_a_distribution_not_just_a_number(tmp_path):
    """正向：日常模式给一条 `info`，且消息里带"缺失最多的模块"。

    这是本条规则一次真实的校准：它原先只打印一个全局数字
    （`公开函数 497 个，其中 188 个没有 docstring`）—— 不可行动。
    `DEVELOPMENT.md` §2.4 是一条成文规则，成文规则配一个不可行动的数字 = 这条规则没有门。
    """
    root = _tree(tmp_path, {
        "a.py": "def f():\n    return 1\n\ndef g():\n    return 2\n",          # 0/2 缺
        "b.py": "def h():\n    return 1\n\ndef k():\n    \"\"\"有。\"\"\"\n    return 2\n",
    })
    got = L.rule_R007_missing_docstring(root)
    assert len(got) == 1 and got[0].level == "info"
    assert "缺失最多的 5 个模块" in got[0].message


def test_r007_does_not_flag_underscore_functions(tmp_path):
    """负控：`_private` 不算公开函数（判据是名字，不是"有没有 docstring"）。"""
    root = _tree(tmp_path, {"a.py": "def _hidden():\n    return 1\n"})
    assert L.rule_R007_missing_docstring(root) == []


def test_r007_strict_upgrades_to_per_module_warnings(tmp_path):
    """负控（严格模式）：`strict=True` 时逐模块报 `warning`，日常模式仍是 `info`。

    为什么两档："更严"必须体现在判据上，不是体现在级别上。
    日常把 188 条升级成 warning 只会淹没输出（R001/R006 都栽在噪音上），
    而 `release_check` 的第 5 项只看 `error` —— 那种"升级"什么也挡不住。
    """
    root = _tree(tmp_path, {"a.py": "def f():\n    return 1\n"})
    assert [f.level for f in L.rule_R007_missing_docstring(root)] == ["info"]
    strict = L.rule_R007_missing_docstring(root, strict=True)
    assert len(strict) == 1 and strict[0].level == "warning", strict
    assert "a.py" in strict[0].path.replace("\\", "/")


def test_r007_clean_tree_reports_zero_missing(tmp_path):
    """负控：所有公开函数都有 docstring ⇒ 严格模式一条都不报。

    日常模式仍给一条 `info`，内容是"公开函数 N 个、其中 0 个没有 docstring" ——
    这是刻意的：零发现必须自证（参考体例 G13 的同一原则）。
    只报"有问题的"会让"我查过了，一个都没有"与"这条规则没跑成"在输出里长得一样。
    """
    root = _tree(tmp_path, {"a.py": 'def f():\n    """有。"""\n    return 1\n'})
    daily = L.rule_R007_missing_docstring(root)
    assert len(daily) == 1 and "0 个没有 docstring" in daily[0].message, daily
    assert L.rule_R007_missing_docstring(root, strict=True) == []


# ============================================================ R008 脚本退出码


def test_r008_flags_script_without_exit_code(tmp_path):
    """正向：`scripts/` 下的脚本没有退出码 ⇒ error。

    参考体例的教训："未报错"被误读为"无问题"（`draft/17-…md` §6）。
    """
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check.py").write_text("print('ok')\n", encoding="utf-8")
    got = L.rule_R008_scripts_without_exit_code(tmp_path)
    assert len(got) == 1 and got[0].level == "error"


def test_r008_accepts_script_with_exit_code(tmp_path):
    """负控：有 `sys.exit` / `SystemExit` 的脚本不报；`__init__.py` 不参与。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "check.py").write_text(
        "import sys\nsys.exit(0)\n", encoding="utf-8")
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    assert L.rule_R008_scripts_without_exit_code(tmp_path) == []


# ============================================================ R010 装置轴与代码不符

#: R010 的合成工具层最小骨架：`base.py` 里那张逐工具遗留翻译表（规则会去读它）。
#: 默认给空表：每个用例只放它自己要触发的那一条，别的条目会让
#: "翻译表里有多余条目"那条 warning 一起出现，把断言变成"数几条 warning"。
_R010_BASE = (
    '"""合成 base。"""\n'
    "LEGACY_EFFECTS_BY_TOOL: dict[str, tuple[str, str]] = {}\n"
)


def _tools_tree(tmp_path: Path, body: str, *, base: str = _R010_BASE) -> Path:
    """造一棵只有工具层的合成树（R010 只扫 `src/agentflow/tools/`）。"""
    base_dir = tmp_path / "src" / "agentflow" / "tools"
    base_dir.mkdir(parents=True, exist_ok=True)
    (base_dir / "base.py").write_text(base, encoding="utf-8")
    (base_dir / "sample_tools.py").write_text(body, encoding="utf-8")
    return tmp_path


def _r010(body: str, tmp_path: Path, *, base: str = _R010_BASE) -> list:
    return L.rule_R010_external_axis_mismatch(_tools_tree(tmp_path, body, base=base))


def test_r010a_flags_process_call_under_a_non_exec_declaration(tmp_path):
    """正控（必须命中 error）：声明 `external="none"` 而 handler 链里起子进程。

    这是 R006 的对偶方向：R006 问"声明读、实际联网/起进程"，
    R010-a 问"声明不执行、实际起子进程"。两者的判据形态不同：R010 按工具判，
    所以这个合成样本里没有别的 `side_effect="read"` 声明也照样命中。
    """
    got = _r010(
        "import subprocess\n"
        "\n"
        "\n"
        "def _spawn():\n"
        "    return subprocess.run(['echo', 'x'])\n"
        "\n"
        "\n"
        "TOOLS = [\n"
        "    dict(name='sample.spawn', side_effect='read', external='none', handler=lambda: _spawn()),\n"
        "]\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.spawn', summary='起进程',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _spawn(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    errors = [f for f in got if f.level == "error"]
    assert len(errors) == 1, got
    assert "sample.spawn" in errors[0].message and "起子进程" in errors[0].message


def test_r010a_does_not_flag_a_declared_exec_tool(tmp_path):
    """负控（必须不命中）：声明 `external="exec"` 且确实起子进程。

    "起了进程就报"是错的判据：声明为 exec 的工具起进程是如实的。
    """
    got = _r010(
        "import subprocess\n"
        "\n"
        "\n"
        "def _spawn():\n"
        "    return subprocess.run(['echo', 'x'])\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.spawn', summary='起进程', external='exec',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _spawn(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    assert [f for f in got if f.level == "error"] == [], got


def test_r010b_flags_egress_without_any_network_call(tmp_path):
    """正控（必须命中 warning）：声明 `external="egress"` 而全文无网络调用。

    级别刻意是 warning 而不是 error：本仓库有成文教训（P15）——
    假报警会训练人忽略告警。它最可能的成因是"保守标注"或"后端取决于配置"。
    """
    got = _r010(
        "def _pure():\n"
        "    return {'ok': True}\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.egress', summary='声称出网', external='egress',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _pure(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    warnings = [f for f in got if f.level == "warning"]
    assert len(warnings) == 1, got
    assert "sample.egress" in warnings[0].message
    assert [f for f in got if f.level == "error"] == []


def test_r010b_does_not_flag_egress_with_a_real_network_call(tmp_path):
    """负控（必须不命中）：声明 `external="egress"` 且 handler 链里真的有 HTTP 调用。"""
    got = _r010(
        "from urllib import request\n"
        "\n"
        "\n"
        "def _fetch():\n"
        "    return request.urlopen('http://example.invalid')\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.egress', summary='真出网', external='egress',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _fetch(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    assert [f for f in got if f.level in ("error", "warning")] == [], got


def test_r010_reports_legacy_count_and_the_per_tool_translation_table(tmp_path):
    """遗留取值必须被数出来，且逐工具翻译表必须与它逐条一致。

    这是 P-13 §3.2 的"一个不可行动的数字没有价值"的可判定形式：
    报告要给出清单（工具名），而不只是一个数字；而"表里有、声明里没有"
    与"声明里有、表里没有"两个方向都要能被判出来（前者是翻译表该删了，
    后者是有人新加了遗留工具却忘了登记原意）。
    """
    body = (
        "def _pure():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.legacy', summary='遗留', side_effect='network',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _pure())]\n"
    )
    legacy_base = (
        '"""合成 base。"""\n'
        "LEGACY_EFFECTS_BY_TOOL: dict[str, tuple[str, str]] = {\n"
        '    "sample.legacy": ("egress", "read"),\n'
        "}\n"
    )
    got = _r010(body, tmp_path, base=legacy_base)
    infos = " | ".join(f.message for f in got if f.level == "info")
    assert "遗留计数" in infos and "1 处" in infos and "sample.legacy" in infos, got
    assert "逐条一致" in infos, got

    # 反方向：声明里有、翻译表里没有 ⇒ error（新加的遗留工具必须显式登记原意）
    got2 = _r010(
        "def _pure():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.untranslated', summary='没登记', side_effect='network',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _pure())]\n",
        tmp_path,
    )
    assert any("没有它们的原意" in f.message for f in got2 if f.level == "error"), got2


def test_r010_reports_unknown_when_the_translation_table_is_missing(tmp_path):
    """三态：读不到逐工具翻译表 ⇒ error（没查成），不是"通过"。

    这与 R009 的"清单读不到就报 unknown"是同一条纪律：
    判据解析出空集时无条件通过，是本项目记过的 P16。
    """
    got = _r010(
        "def _pure():\n"
        "    return 1\n",
        tmp_path,
        base='"""没有翻译表的合成 base。"""\n',
    )
    assert any(f.level == "error" and "LEGACY_EFFECTS_BY_TOOL" in f.message for f in got), got


def test_r010_reports_count_so_a_broken_scanner_cannot_pass_silently(tmp_path):
    """反真空断言：报告里必须有"核对了 N 条"，且 N 随声明数变化。

    判据解析出空集会无条件通过 —— 所以"没有命中"必须能与"一条都没读到"分开。
    """
    one = _r010(
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.a', summary='s', params={'type': 'object', 'properties': {}},\n"
        "                     handler=lambda: 1)]\n",
        tmp_path,
    )
    two = _r010(
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.a', summary='s', params={'type': 'object', 'properties': {}},\n"
        "                     handler=lambda: 1),\n"
        "            ToolSpec(name='sample.b', summary='s', params={'type': 'object', 'properties': {}},\n"
        "                     handler=lambda: 1)]\n",
        tmp_path,
    )
    assert any("核对了 1 条" in f.message for f in one), one
    assert any("核对了 2 条" in f.message for f in two), two


def test_r010_allowed_sites_still_exist():
    """例外清单不许腐烂：每个键都必须真的指向一个"起进程、且没声明 exec"的工具。

    没有这条断言，例外清单会变成一张"永不生效的豁免"（本项目 R004 的
    `R004_ALLOWED_SITES` 也是这么守的）。判据直接在真实树上量：
    R010-a 的字面判据命中它，而它不在 error 列表里（说明豁免真的接上了）。
    """
    root = Path(__file__).resolve().parents[1]
    got = L.rule_R010_external_axis_mismatch(root)
    for name, reason in L._R010_ALLOWED_SITES.items():
        assert reason.strip(), f"{name} 的例外没有写理由"
        hit = [f for f in got if name in f.message and "已逐条登记为例外" in f.message]
        assert hit, f"{name} 在真实树上没有命中 R010-a —— 例外清单过期了（或它已声明 exec）"


def test_r010_known_gaps_are_reported_not_hidden():
    """已知漏检必须在报告里出现：`unknown` 与 `pass` 不许折叠成同一个"通过"。"""
    root = Path(__file__).resolve().parents[1]
    got = L.rule_R010_external_axis_mismatch(root)
    infos = " | ".join(f.message for f in got if f.level == "info")
    for name in L._R010_KNOWN_GAPS:
        assert name in infos, f"{name} 是已知漏检，但报告里没提它：{infos}"


def test_r010_real_tree_has_no_error(tmp_path):
    """真实树必须 0 error —— 一条常红的门与一条常绿的门一样没有信息量。

    这条断言的判据是 `scripts/lint_rules.py` 的退出码（发布门用它），
    这里只是让"真实树上 R010 是不是红的"在 CI 里有一个明确的点。
    """
    root = Path(__file__).resolve().parents[1]
    got = L.rule_R010_external_axis_mismatch(root)
    errors = [f.message for f in got if f.level == "error"]
    assert errors == [], errors


# ============================================================ R009 注释里的装饰


def test_r009_flags_bold_and_emoji_in_comment_and_docstring(tmp_path):
    """正向：注释里的成对星号、docstring 里的 emoji ⇒ error（禁改区之外）。

    判据只覆盖注释与 docstring：普通字符串字面量是产物
    （C/D 的报告正文本来就是 markdown，那里渲染得出加粗），不在本规则的范围内。
    """
    root = _tree(tmp_path, {"a.py": (
        '"""模块说明。\n\n⚠️ 这里是 docstring。\n"""\n'
        "\n\n"
        "def f():\n"
        "    # 这段注释里有" + "**" + "加粗" + "**" + "，但源码不渲染 markdown\n"
        "    return 1\n"
    )})
    got = L.rule_R009_decoration_in_comments(root)
    errors = [f for f in got if f.level == "error"]
    assert len(errors) == 1, got
    assert errors[0].path.replace("\\", "/").endswith("src/agentflow/a.py")
    assert "2 处" in errors[0].message


def test_r009_ignores_stars_inside_code_spans(tmp_path):
    """负控：反引号里的星号是示例，不是装饰。

    这条负控直接产自本项目自己的文档：规则自己的注释里就要写出 `**` 这个写法，
    如果判据不先摘掉代码跨度，规则就没法在自己的源码上通过。
    `` `220` ``（幂）、`` `a//b` ``（glob）、`` `handler(params)` ``（解包）
    都是字面语法，必须原样留着。
    """
    root = _tree(tmp_path, {"a.py": (
        '"""说明 ``x`` 与 `2**20`、`a/**/b`、`handler(**params)` 都是字面写法。\n"""\n'
        "\n\n"
        "def f():\n"
        "    #: 判据是 `**` 是否成对出现；见 `docs/`。\n"
        "    return 1\n"
    )})
    assert [f for f in L.rule_R009_decoration_in_comments(root) if f.level == "error"] == []


def test_r009_ignores_arrows_and_encoding_cookie(tmp_path):
    """负控（校准）：箭头 `→` `⇒`、`—` 与 `# -*- coding: utf-8 -*-` 都不是装饰。

    这两类是本仓库里最常见的"看着像、其实不是"：
    流程写法 `A → B` 与文件编码声明 `# -*- coding: utf-8 -*-`。
    第一版把箭头算进 emoji 范围，在真实树上得到 915 处命中 —— 绝大多数是箭头。
    把这类假阳性放进日常输出，这条规则在第一次运行后就会被人忽略。
    """
    root = _tree(tmp_path, {"a.py": (
        "# -*- coding: utf-8 -*-\n"
        '"""A → B ⇒ C，检索口径 —— 见 `search.*`。\n"""\n'
        "\n\n"
        "def f():\n"
        "    #: 调用方 → 工具层 → 存储；不做翻译。\n"
        "    return 1\n"
    )})
    assert [f for f in L.rule_R009_decoration_in_comments(root) if f.level == "error"] == []


def test_r009_zone_hits_are_info_not_error(tmp_path):
    """禁改区内的装饰只报一条汇总 `info`，不进 error。

    为什么不做成 error：禁改区按 FC-27 只能由人改，对它们报 error 等于造一条
    永远红的灯（要清它就得改人专属文件，且每个文件要 2 名 reviewer）。
    一条永远红的门和一条永远绿的门一样没有信息量。
    """
    root = _tree(tmp_path, {"frozen.py": '# 这里有' + "**" + '加粗' + "**" + '，但这个文件是禁改区。\n'})
    got = L.rule_R009_decoration_in_comments(root)
    assert [f for f in got if f.level == "error"] == []
    infos = [f for f in got if f.level == "info"]
    assert len(infos) == 1 and "frozen.py" in infos[0].message, got


def test_r009_reports_unknown_when_manifest_missing(tmp_path):
    """三态：读不到禁改区清单 ⇒ error（"没查成"），不是"干净"。

    没有清单就无法区分区内区外：区外的报 error，区内的只能报 info。
    分不清时若默认"都是区外"，命中会落到人专属文件上 —— 那会诱导人去改禁改区。
    """
    base = tmp_path / "src" / "agentflow"
    base.mkdir(parents=True)
    (base / "a.py").write_text('"""干净。"""\n', encoding="utf-8")
    got = L.rule_R009_decoration_in_comments(tmp_path)
    assert len(got) == 1 and got[0].level == "error", got
    assert "没有真正检查" in got[0].message


def test_r009_fails_when_its_own_scanner_is_broken(tmp_path, monkeypatch):
    """P16 负控：判据自检不过 ⇒ error，而不是"哪儿都没有装饰"。

    "判据解析出空集 ⇒ 无条件通过"是本项目记过的缺陷形态（§6 的 P16）。
    这里把扫描器换成永远返回空集的假货：真树扫描结果不变（本来就没装饰），
    但规则必须在自检那一步就失败 —— 否则扫描器坏掉与代码干净在输出上无法区分。
    """
    root = _tree(tmp_path, {"a.py": '"""干净。"""\n'})
    monkeypatch.setattr(L, "_r009_scan", lambda text: ([], 0))
    got = L.rule_R009_decoration_in_comments(root)
    assert [f for f in got if f.level == "error"], got
    assert "判据自检失败" in got[0].message


def test_r009_reports_unknown_when_no_source_files_scanned(tmp_path):
    """三态负控：一个源文件都没扫到（根写错了）⇒ error，不是"干净"。"""
    (tmp_path / ".noai-paths").write_text(
        "[category: solver-core] 合成树\n"
        "src/agentflow/frozen.py  [category: solver-core] 假禁改区\n",
        encoding="utf-8",
    )
    got = L.rule_R009_decoration_in_comments(tmp_path)
    assert len(got) == 1 and got[0].level == "error", got
    assert "一个源文件都没扫到" in got[0].message


def test_r009_accepts_tree_without_any_comment(tmp_path):
    """负控（校准）：一棵真的没有注释/docstring 的树不算"扫描器坏了"。

    第一版用"整棵树解析出 0 个注释 ⇒ error"当 P16 判据，
    结果在合成树上误报（那棵树里的文件确实没有注释）。
    自检样本才是判据接没接上的证据，树本身的注释多少不是。
    """
    root = _tree(tmp_path, {"a.py": "def f():\n    return 1\n"})
    assert [f for f in L.rule_R009_decoration_in_comments(root) if f.level == "error"] == []


def test_r009_counts_clean_zone_as_explicit_zero(tmp_path):
    """零发现必须自证：禁改区里没有装饰时也给一条"没有待清"的 `info`。

    只报"有问题的"会让"我查过了、一个都没有"与"这条规则没跑成"在输出里长得一样。
    """
    root = _tree(tmp_path, {"a.py": '"""干净。"""\n'})
    infos = [f for f in L.rule_R009_decoration_in_comments(root) if f.level == "info"]
    assert len(infos) == 1 and "没有装饰待清" in infos[0].message, infos


# ============================================================ 规范 ↔ 门 的一致性


def _rule_codes() -> list[str]:
    """从 `RULES` 的条目名里取出 `R0NN` 编号（条目名形如 `"R001 except-pass"`）。"""
    out: list[str] = []
    for name, _ in L.RULES:
        m = re.match(r"(R\d{3})\b", name)
        assert m, f"RULES 的条目名不以 R0NN 开头：{name!r}"
        out.append(m.group(1))
    return out


def _section6() -> str:
    """`DEVELOPMENT.md` 的 §6 正文（禁止模式清单）。读不到时返回空串，由调用方判失败。"""
    doc = (Path(__file__).resolve().parents[1] / "DEVELOPMENT.md").read_text(encoding="utf-8")
    if "## §6" not in doc:
        return ""
    return doc.split("## §6", 1)[1].split("\n## §7", 1)[0]


def test_every_lint_rule_is_registered_in_the_table():
    """规范 ↔ 门一致：每条规则都必须出现在 `RULES` 里，且规则号连续无洞。

    一个"定义了但没挂进 `RULES`"的规则会在报告里消失 —— 而它的函数还能被单独 import，
    于是"我有这条规则"这句话在读代码时是真的、在看报告时是假的。
    """
    codes = _rule_codes()
    digits = sorted(int(c[1:]) for c in codes)
    assert digits == list(range(1, len(digits) + 1)), codes


def test_documented_prohibition_table_covers_every_code_rule():
    """规范 ↔ 门一致：`DEVELOPMENT.md` §6 的禁止模式表必须提到每一条 `R0NN`。

    这是"规范与执行它的门不许分叉"的可判定形式：
    - 加一条 lint 规则却不写进 §6 ⇒ 人被规范误导（规范里查不到这条禁令）；
    - §6 写了 `R010` 而代码里没有 ⇒ 规范承诺了一个不存在的门（虚证）。

    本测试只判"每条规则的编号都在 §6 出现过"；它不判"§6 的每一行都有 lint"
    （那是 §6 自己声明的：P1–P9 与 P17 落成了 R001–R009，其余需人工）。
    """
    section = _section6()
    assert section, "读不到 DEVELOPMENT.md §6 —— 规范与门的对账没查成（不是通过）"
    missing = [c for c in _rule_codes() if f"{c}" not in section]
    assert not missing, f"这些规则没出现在 DEVELOPMENT.md §6 的禁止模式表里：{missing}"


def test_documented_lint_references_point_at_real_rules():
    """规范 ↔ 门一致（反向）：§6 里写的 `R0NN` 编号必须真的有对应的规则。

    防的是"规范承诺了一个不存在的门"——那是最坏的一种虚证：读者以为有这条自动判据，
    于是人不再去看。
    """
    section = _section6()
    assert section, "读不到 DEVELOPMENT.md §6 —— 反查没查成（不是通过）"
    referenced = {f"R{n}" for n in re.findall(r"\bR(\d{3})\b", section)}
    ghost = sorted(referenced - set(_rule_codes()))
    assert not ghost, f"DEVELOPMENT.md §6 引用了不存在的 lint 规则号：{ghost}"


# ============================================================ 报告与退出码


def test_linter_reports_unknown_when_tree_missing(tmp_path):
    """三态：读不到源码树 ⇒ 退出码 2（`unknown`），不是 0。

    这是本项目最反复的一条纪律：`unknown` 与 `pass` 必须分开。
    """
    rc = L.main(["--root", str(tmp_path)])
    assert rc == 2, "读不到源码树必须报 unknown(2)，不能静默当通过"


def test_linter_exit_code_zero_on_clean_tree(tmp_path, capsys):
    """负控：干净的小树 ⇒ 退出码 0。"""
    _tree(tmp_path, {"clean.py": '"""m。"''\n\n\ndef f(x):\n    """做点事。\n\n    为什么：因为需要。\n    """\n    return x\n'})
    assert L.main(["--root", str(tmp_path)]) == 0


def test_linter_runs_all_rules_and_reports_counts(tmp_path):
    """`run_all` 必须把所有规则都跑一遍，并把各自的命中汇进同一份报告。"""
    root = _tree(tmp_path, {"m.py": "def f():\n    try:\n        g()\n    except Exception:\n        pass\n"})
    rep = L.run_all(root)
    assert len(rep.rules_run) == len(L.RULES) >= 8
    d = rep.to_dict()
    assert d["error_count"] == 1 and d["scanned"]["src_py"] == 1
