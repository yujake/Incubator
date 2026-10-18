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


# ============================================================ R004 注册表绕道（已退休）
#
# R004 的全部用例随判据一起退休 —— 它们断言的是"lint 能探测出绕过装配期角色校验的
# 构造点"，而 `P-1` 把判据下沉到 `ToolRegistry.register*` 之后这个探测面变成真空。
# 退休的可断言形态（登记 + 不产生 findings + 编号保留 + 接替者真的在 + 豁免表已收掉）
# 见 `tests/test_lint_rules_r004_retired.py`（与 R006 的 `test_lint_rules_r006_retired.py`
# 逐条同族）。旧用例留在这里会断言三张已经不存在的豁免表 —— 那是"永不生效的豁免"。


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

#: R010 的合成工具层最小骨架。
#:
#: B3 收官删掉了遗留取值 `network` 与两张翻译表，R010 因此不再读任何
#: `base.py` 里的表。这个骨架只留一个文件，让合成树与真实树同形
#: （规则只扫 `src/agentflow/tools/`，`base.py` 缺了不影响判定）。
_R010_BASE = '"""合成 base（B3 收官后 R010 不再从 base.py 读任何表）。"""\n'


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

    判据形态与 R006（已退休）不同：R006 是文件级共现、指不出是哪一个工具；
    R010 按工具判 —— 所以这个合成样本里没有别的 `side_effect="read"` 声明也照样命中，
    而且断言的是"消息里点名了那个工具"（`sample.spawn`），那正是 R006 做不到的那一格。
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


def test_r010a_does_not_flag_a_tool_declaring_declared_external(tmp_path):
    """负控：真实写法 `declared_external="exec"` 必须被读到（G-45 的字段名）。

    这条用例是"读错字段名"的直接负控：`ToolSpec` 的字段叫 `declared_external`
    （`external` 是属性名，写进构造器会 `TypeError`），而 `@tool` 装饰器的
    关键字叫 `external`。只认后者时，真实树上所有 `ToolSpec(..., declared_external=…)`
    都会被读成默认值 `none` —— 于是一个如实的 `exec` 声明会被报成 error，
    而报告里"声明写错"与"声明没被读见"长得一模一样（三态纪律要防的正是它）。
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
        "    return [ToolSpec(name='sample.spawn', summary='起进程', declared_external='exec',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _spawn(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    assert [f for f in got if f.level == "error"] == [], got
    assert [f for f in got if "sample.spawn" in f.message and f.level in ("error", "warning")] == [], got


def test_r010a_still_flags_declared_external_none_with_a_process_call(tmp_path):
    """正控：显式写 `declared_external="none"` 而起进程 ⇒ 仍然必须 error。

    与上一条成对：只有"能读到这个字段名"才会让这条 error 出现/消失，
    两条一起才说明判据接上的是真实字段（而不是"谁都不报"）。
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
        "    return [ToolSpec(name='sample.spawn', summary='起进程', declared_external='none',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _spawn(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    errors = [f for f in got if f.level == "error"]
    assert len(errors) == 1, got
    assert "sample.spawn" in errors[0].message


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


def test_r010c_flags_a_none_declaration_that_reaches_a_network_call(tmp_path):
    """正控（必须命中 warning）：声明 `external="none"` 而 handler 链里真的联网。

    这是 R006 当年问的那个方向（`side_effect="read"` / `external="none"` 的工具
    实际联网），在 R010 的逐工具口径下的落地。为什么必须有它：R006 退休时
    `RETIRED_RULES` 写的是"判据移入 R010"，而 R010 此前只有"非 exec 而起子进程"
    与"声明 egress 而看不到网络"两条 —— 于是这个方向在门里没有任何判据看得见
    （`R7-R6-1` 在人造树上实测：改前 R010 报 0 条、而改前的 R006 报 1 条）。

    级别是 warning 而不是 error：判据是"字面标记可达"，而 `search` / `download`
    两条标记按末段相等匹配，真实树上会被 `re.search` / `rx.search` 这类正则方法命中
    （那两条已登记在 `_R010_NETWORK_FALSE_POSITIVES`）。
    """
    got = _r010(
        "from agentflow import providers as P\n"
        "\n"
        "\n"
        "def _fetch():\n"
        "    return P.http_get_json('https://example.invalid/x')\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.fetch', summary='声称不对外', declared_external='none',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _fetch(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    warnings = [f for f in got if f.level == "warning"]
    assert len(warnings) == 1, got
    assert "sample.fetch" in warnings[0].message, warnings[0].message
    assert "R006" in warnings[0].message, "这条要写清它是 R006 那个方向的接续"
    # 与 R010-a 分开：它起的是"联网"这件事，不该被误报成起进程
    assert [f for f in got if f.level == "error"] == [], got


def test_r010c_does_not_flag_a_none_declaration_without_any_network_call(tmp_path):
    """负控（必须不命中）：声明 `none` 而链里只有本地处理 ⇒ 一个字都不报。

    与上一条成对：判据的两侧都要有名字，否则"补了一条新判据"与"补了一条常红的灯"
    在报告里长得一模一样。
    """
    got = _r010(
        "def _read(path):\n"
        "    with open(path, encoding='utf-8') as fh:\n"
        "        return fh.read()\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.read', summary='只读本地', declared_external='none',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _read('x'),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    assert [f for f in got if f.level in ("error", "warning")] == [], got


def test_r010c_does_not_flag_an_egress_declaration_that_really_goes_out(tmp_path):
    """负控（必须不命中）：声明 `egress` 且确实联网 ⇒ 那是如实的声明，不许报。

    这一条同时钉住"方向"：`external == 'egress'` 走的是 R010-b（声明出网却看不到网络），
    不是这一档；把两个方向混成"只要链里有网络标记就报"会把如实的 `egress` 声明也算成缺陷。
    """
    got = _r010(
        "from urllib import request\n"
        "\n"
        "\n"
        "def _fetch():\n"
        "    return request.urlopen('http://example.invalid')\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.egress', summary='真出网', declared_external='egress',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _fetch(),\n"
        "                     side_effect='read')]\n",
        tmp_path,
    )
    assert [f for f in got if f.level in ("error", "warning")] == [], got


def test_r010c_known_false_positives_are_reported_not_hidden():
    """R010-c 的假阳性登记表必须在报告里出现，且它指的工具真的还命中这一档。

    为什么要把"我判不了的那几条"变成判据（而不是注释）：静默豁免是本项目最忌的形态。
    这条与 `test_r010_egress_blind_spots_still_exist` 同族 —— 一张永不生效的豁免表
    会腐烂成"看起来还在挡着什么"。
    """
    root = Path(__file__).resolve().parents[1]
    got = L.rule_R010_external_axis_mismatch(root)
    infos = " | ".join(f.message for f in got if f.level == "info")
    assert "R010-c" in infos, "这一档的读数必须出现在报告里（判据接上了没有的证据）"
    assert "_R010_NETWORK_FALSE_POSITIVES" in infos or "已知字面假阳性" in infos, infos[:400]
    for name, reason in L._R010_NETWORK_FALSE_POSITIVES.items():
        hit = [f for f in got if f.level == "info" and name in f.message]
        assert hit, f"{name} 在真实树上没有命中 R010-c —— 假阳性表过期了（或它已改声明）"
        assert reason.strip(), name
    assert [f for f in got if f.level == "warning"] == [], (
        "真实树上不该有 R010-c 的 warning：命中的每一条都必须在假阳性表里（否则要改声明）"
    )


def test_r010_reports_zero_legacy_and_no_longer_reads_any_translation_table(tmp_path):
    """B3 收官：遗留取值已清零，规则不再读任何翻译表。

    迁移期这条规则会去读 `base.py` 的 `LEGACY_EFFECTS_BY_TOOL`，并在读不到时
    报 error（"没查成"）。那个取值与那两张表都删掉之后，这条判据的对象消失了：
    留着它就是一条"永远读不到、永远报 error"的灯 —— 而常红的门与常绿的门
    一样没有信息量。所以现在断言两件事：

    1. 报告里有一条明确的"0 处遗留取值"info（而不是这个事实从报告里消失）；
    2. 合成树里没有任何翻译表时，规则不报 error（它不再依赖那张表）。
    """
    got = _r010(
        "def _pure():\n"
        "    return 1\n",
        tmp_path,
        base='"""没有翻译表的合成 base。"""\n',
    )
    assert [f for f in got if f.level == "error"] == [], got
    infos = " | ".join(f.message for f in got if f.level == "info")
    assert "遗留取值：0 处" in infos, got
    assert "LEGACY_EFFECTS_BY_TOOL" in infos, "这条 info 应当点名被删掉的那两张表"


def test_network_is_no_longer_recognised_as_a_legacy_declaration(tmp_path):
    """负控：合成树里写 `side_effect="network"` ⇒ 规则不再把它翻译成 `egress`。

    迁移期这一条会被翻译成 `egress` 并走进 R010-b 的判据。现在那个取值已从
    词表里删掉，真实树上它连 `ToolSpec` 都构造不出来；这条用例锁的是
    规则里也不再留那条旁路 —— 它只按声明说话（这里是默认的 `none`）。

    合成树因此分两条：`sample.legacy`（`side_effect='network'`、handler 纯净）
    用来问"没有那条翻译旁路"；`sample.notexec`（默认 `none`、handler 起进程）
    用来问"起进程却声明不是 exec 照旧是 error"。第二块是 `R7-R6-1` 之后补的：
    补进 R010-c 之后，一个起进程的 handler 会同时命中"起进程"与"网络标记"
    （`subprocess` 本来就在 `_R010_NETWORK_MARKERS` 里），于是把两块分开写
    才让这条用例继续锁它真正要锁的东西（而不是被新那一档的文案顶替掉）。
    """
    got = _r010(
        "import subprocess\n"
        "\n"
        "\n"
        "def _pure():\n"
        "    return 1\n"
        "\n"
        "\n"
        "def _spawn():\n"
        "    return subprocess.run(['echo', 'x'])\n"
        "\n"
        "\n"
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.legacy', summary='旧写法', side_effect='network',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _pure()),\n"
        "            ToolSpec(name='sample.notexec', summary='起进程', declared_external='none',\n"
        "                     params={'type': 'object', 'properties': {}}, handler=lambda: _spawn())]\n",
        tmp_path,
    )
    warnings = " | ".join(f.message for f in got if f.level == "warning")
    assert "sample.legacy" not in warnings, (
        "规则仍在把 side_effect='network' 当出网声明来判 —— 那条旁路必须删掉"
    )
    # `sample.legacy` 的 handler 现在是纯净的 ⇒ 它一个字都不该报（旧写法不再带来任何判据）
    assert [f for f in got if "sample.legacy" in f.message] == [], got
    assert any(f.level == "error" and "sample.notexec" in f.message for f in got), got


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

    没有这条断言，例外清单会变成一张"永不生效的豁免"（R004 的
    `R004_ALLOWED_SITES` 就是那样退场的：判据改由注册期承担之后，那张表
    连同它的豁免一起收掉了）。判据直接在真实树上量：
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


def test_r010_egress_blind_spots_are_registered_and_still_fire():
    """R010-b 的已知盲区：登记了、真的还命中、且报告里看得见（不许静默豁免）。

    三条一起断言，缺一条这张表就变形：
    - 每条都写了理由（否则它是一张没有内容的豁免）；
    - 每条都真的命中 R010-b（否则它是一张永不生效的豁免 —— `R004_ALLOWED_SITES`
      退场时就是那个形态）；
    - 登记后仍然以 info 出现在报告里（"哪一段我核不了"必须可见）。
    """
    root = Path(__file__).resolve().parents[1]
    got = L.rule_R010_external_axis_mismatch(root)
    infos = " | ".join(f.message for f in got if f.level == "info")
    warnings = " | ".join(f.message for f in got if f.level == "warning")
    for name, why in L._R010_EGRESS_BLIND_SPOTS.items():
        assert why.strip(), f"{name} 的盲区登记没有写理由"
        assert name in infos, f"{name} 登记为盲区，但报告里没提它：{infos}"
        assert name not in warnings, (
            f"{name} 已登记为已知盲区，却仍然以 warning 出现 —— 登记没接上判据"
        )


def test_r010_never_uses_a_silent_exemption_for_an_unregistered_egress_tool(tmp_path):
    """负控：一个没有登记的 egress 工具必须仍然报 warning（登记不是开后门）。"""
    got = _r010(
        "def _to_specs():\n"
        "    return [ToolSpec(name='sample.egress', summary='s',\n"
        "                     params={'type': 'object', 'properties': {}},\n"
        "                     side_effect='read', declared_external='egress',\n"
        "                     handler=lambda: 1)]\n",
        tmp_path,
    )
    warnings = " | ".join(f.message for f in got if f.level == "warning")
    assert "sample.egress" in warnings, got
    # 且提示里必须给出"怎么登记"这条路（可动作），而不是一句"要么……要么……"
    assert "_R010_EGRESS_BLIND_SPOTS" in warnings, warnings


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


#: 2026-10 文档拆分：禁止模式清单（P1–P18）随规范搬进 `docs/DEVELOPMENT-SPEC.md`，
#: 编号从 `DEVELOPMENT.md` 的 `§6` 变成 `§8` —— 判据的对象（那张禁止模式表）一个字没变，
#: 变的只是它住哪一节。读不到仍然返回空串、由调用方判失败（fail-closed，不折成通过）。
_SPEC = Path(__file__).resolve().parents[1] / "docs" / "DEVELOPMENT-SPEC.md"
_SPEC_PROHIBITION_HEADER = "## [规范] §8"


def _section6() -> str:
    """`docs/DEVELOPMENT-SPEC.md` 的 §8 正文（禁止模式清单）。读不到时返回空串，由调用方判失败。"""
    doc = _SPEC.read_text(encoding="utf-8")
    if _SPEC_PROHIBITION_HEADER not in doc:
        return ""
    return doc.split(_SPEC_PROHIBITION_HEADER, 1)[1].split("\n## ", 1)[0]


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
