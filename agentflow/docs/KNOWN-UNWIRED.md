# 已知未接线（工具模块清单）

这份清单回答一个具体的问题：`src/agentflow/tools/` 下面有哪个 `*_tools.py` 模块
**没有被装配**（不在 `src/agentflow/tools/__init__.py` 的 `_MODULES` 里）。

为什么它必须是一份可机核的清单，而不是散落在几段 docstring 里：
"某个模块写了、但没人装配"这件事**不会报错**。它不会让导入失败、不会让任何判据变红，
只会让一件工具在某个角色的工具面上**静默缺席** —— 而"缺席"与"这个角色不需要它"
在读数上长得一模一样。清单是让"缺席"变成一个被写下来的决定。

判据：`tests/test_known_unwired_modules.py`。它逐条核三件事 ——
① `tools/` 下每个没装配的模块都在这份清单里（没有静默漏登记的）；
② 清单里每一项都真的是一个模块文件、且真的没被装配（没有过期条目）；
③ 两个方向的集合相等（既不漏、也不多）。

维护纪律：新建一个 `*_tools.py` 却不装配它 ⇒ 上面那条判据当场变红，要么装配它
（`_MODULES` 加一行，工具数与两份冻结快照跟着重冻），要么在这里点名并写清理由。
把模块从这份清单里删掉而它仍然没被装配 ⇒ 同样变红。

## 机器可读的那一段

`tests/test_known_unwired_modules.py` 只读下面这个区块（逐行一个模块名，不带反引号、
不带说明）。区块外的正文是给人读的，判据不解析它。

<!-- KNOWN-UNWIRED:BEGIN -->
cache_tools
conjecture_tools
<!-- KNOWN-UNWIRED:END -->

## 逐条

### `cache_tools` —— 两档提示词缓存的两件工具（`cache.status` / `cache.warm`）

- 它是什么：`cache.status`（只读：两档 × 四格读数 + 换 key 提醒）与
  `cache.warm`（写 + 起子进程：真预热一档，`dry_run` 缺省 true）。两件都只挂给主控 M
  （`roles=("M",)`），实现转发到 `cachectl.py`。
- 为什么没挂：业主此前裁定「本轮不挂」。它们的真实用户面是命令行
  （`agentflow cache status|warm`）与网页上的那两个按钮；工具面这一档是"主控在对话里
  代跑一条只读读数"，不是任何执行角色的职责。
- 若要挂上：`tools/__init__.py` 的 `_MODULES` 加一行 `"cache_tools"` ⇒ 工具数 97 → 99，
  `tests/golden/tool_surface_snapshot.json` 与 `tests/golden/agent_surface_snapshot.json`
  要重冻（两份快照的 `count` 与工具名清单逐格都会变）。这一步改的是权限面
  （M 会多拿到两件工具，其中一件能花钱），所以按 FC-27 走人审。
- 读数口径：清单只声明"没装配"，不声明"坏了"。`cache.status` 在命令行与网页面上照旧可用。

### `conjecture_tools` —— `conjecture.register_conjecture`

- 它是什么：`D.register_conjecture` 的落地工具（`conjecture.register_conjecture`）。
- 为什么没挂：它由 D 这一侧**直接 import**（`agent_d/_support.py` 里 `from ..tools import
  conjecture_tools as CT`），不经过装配表。这条路径在 `capabilities._TOOL_MODULE_EXTRAS`
  里逐条登记过（连同"读进来"与"它是工具面的一件"必须分开算的理由），所以它早就是
  一个被写下来的决定；这份清单只是把它点名到同一处。
- 若要挂上：同上（`_MODULES` 加一行、重冻两份快照、按 FC-27 走人审）。注意它与
  `cache_tools` 不是一回事：前者的工具是"被直接 import 的执行路径"，后者是"面上一件都没有"。

## 不在这份清单里的东西

- **Lean 专属模块**（`formal_tools`）在开关关着时**不装配**：那是按用户开关的刻意的
  跳过（`leanscope.LEAN_ONLY_TOOL_MODULES`），不是缺陷，读数记在
  `RegistryBuild.lean_off` 里，判据见 `tests/test_lean_switch.py`。
- **模块装配失败**（`register()` 抛异常、`roles` 拼错被拒）：那是 `RegistryBuild.skipped`
  里的一条缺陷，`strict=True` 时直接抛，不该被写进这份清单当成"已知"。
