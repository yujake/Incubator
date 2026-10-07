# B3 收官证据：删掉遗留取值 `network` 与两张翻译表

工单：`temp/B3-rest-workorder.md`。执行者：实现子智能体。核验者：主控（独立复跑）。
日期：2026-09-26。

> 本文件里每一句结论后面要么跟原始输出，要么写"未核实"。
> 命令一律在 `cd D:\Incubator\agentflow` 下跑，环境：
> `PYTHONIOENCODING=utf-8 PYTHONUTF8=1 PYTHONPATH=src`。

---

## A. 改动清单（文件 ↔ 工单节）

| 文件 | 工单节 | 改了什么 |
|---|---|---|
| `src/agentflow/tools/base.py`（禁改区） | §2.1/§2.2 | `SIDE_EFFECTS` 删 `network`；删 `NEEDS_APPROVAL` / `LEGACY_SIDE_EFFECTS` / `LEGACY_EFFECTS_BY_TOOL`；`__post_init__` 删遗留翻译段；`external`/`effect` 变成恒等；`needs_approval` 删 `NEEDS_APPROVAL` 分支 |
| `src/agentflow/tools/__init__.py`（禁改区） | §2.1/§2.2 | `SIDE_EFFECTS_WRITE = ("write_local",)`；删 `LEGACY_TRANSLATIONS` / `untranslated_legacy_tools` / `build_registry` 里的 `<legacy>` 段与 `__all__` 两项 |
| `src/agentflow/tools/verify_tools.py`（禁改区） | §2.4 | `verify.check_formal`：`declared_external="exec"`；`roles` `_ROLES` → `_ROLES_WRITE` |
| `src/agentflow/tools/search_tools.py` | §2.3 | `search.providers`→`read`+`egress`；`search.literature`→`read`+`egress`；`search.download`→`write_local`+`egress` |
| `src/agentflow/tools/ocr_tools.py` | §2.3 | `ocr.run`→`write_local`+`egress` |
| `src/agentflow/capabilities.py` | §2.1/§2.2/§2.4 | 词表与 `_WRITE_LIKE`；删 `LEGACY_NETWORK_AXES`；`action_axes` 三支塌两支；`_tool_axes` 恒等；删两个遗留分歧分支、新增 `two_layer_external_imprecise`；`_declared_side_effects` 认 `declared_external=`；`E.check_formal`→`read`+`exec`；`A.run_once`/`A.run`/`B.run` 见 §D-2 |
| `scripts/lint_rules.py` | §2.5 | 删 `_r010_read_legacy_table` 与整段调用；R010 不再读翻译表；`_r010_external_literal` 认两个字段名；`verify.check_formal` 移出 `_R010_ALLOWED_SITES` |
| `tests/test_tools_base.py` / `test_tools_readonly_roles.py` / `test_tools_audit_fixes.py` / `test_lint_rules.py` / `test_policy.py` / `test_core_audit_efgh.py` | §2.6 | 删遗留用例、加负控与四元组基线 |
| `tools/coverage_zero_test.py` | §2.6 | `_EXPECT_SIDE_EFFECTS_WRITE = frozenset({"write_local"})` |
| `DEVELOPMENT.md` / `docs/ROLE-SPECS.md` / `docs/PROPOSAL-side-effect-axes.md` | §2.7 | 判据表、H.4、§R0 五条工具行、3.2/7.1 的翻译表段落 |

未碰：`docs/PROPOSALS.md`、`draft/`（由登记子智能体回收）。

---

## B. 备份文件名 / 改前改后 sha256 / EOL 计数

备份（改前 `Copy-Item` 到 `temp/`，时间戳 `20260926-023418`）：

| 备份文件 |
|---|
| `temp/base.py.bak-b3rest-20260926-023418` |
| `temp/__init__.py.bak-b3rest-20260926-023418` |
| `temp/verify_tools.py.bak-b3rest-20260926-023418` |
| `temp/noai-approvals.json.bak-b3rest-20260926-024756`（台账副本） |

改前（`python -c` 逐文件算，`temp/_b3r_prehash.txt` 原始输出）：

```
src/agentflow/tools/base.py 1b6ccc4e30a6ef424497b8ae651ed698f334d7c205006d15d9c25dc6d3e69f8b CRLF= 784
src/agentflow/tools/__init__.py 69272d9746a368132ea2af53ea676e2438dc451dba825cc86c9ff5eda9281a28 CRLF= 356
src/agentflow/tools/verify_tools.py b5c81a20efd20644cdfa229449d31fa9ca68dd90fe7a5c56b7617d4ffe31318e CRLF= 796
```

改后（`temp/_b3r_eol_after.txt` 原始输出，含全部改动文件）：

```
src/agentflow/tools/base.py 59aab9a3857ef6ef99098c95d6b580585004113433c9e2a84ff030b77f1a66d1 bytes 36243 CRLF 713 LF 0
src/agentflow/tools/__init__.py 7309691667f4293dc145b95694d901fbc7eaadd2839d3e4120da664c8a865338 bytes 14649 CRLF 313 LF 0
src/agentflow/tools/verify_tools.py 8b8b87cf788bb1633c5e6201371e1488a1ec3a87e36683ba48ad4d8d272f0484 bytes 39744 CRLF 805 LF 0
src/agentflow/capabilities.py c0b5308727c31f929549fbe45402ac0f09aa4e5954ed07c387d0ef527b85547a bytes 86127 CRLF 1554 LF 0
src/agentflow/tools/search_tools.py 230386c475f12af788ec0576a4c4caf9b32466a064c59e2a7a2f67f7119cd1d5 bytes 61772 CRLF 1320 LF 0
src/agentflow/tools/ocr_tools.py 176d033a99e0f47a0b1ffe90e26a60ee9ac6f0f9113312904da7c00ad0c49612 bytes 55784 CRLF 1195 LF 0
scripts/lint_rules.py 9078a6e06686ba9ae1392ad5604721b94e5ab94897c1a51bc16ec63d8f4198b1 bytes 87064 CRLF 1655 LF 0
tests/test_tools_base.py 3b4a6510c8b4e5022684304b1f9744daa82733706bcae4625920e457fdc0ff16 bytes 30323 CRLF 646 LF 0
tests/test_tools_readonly_roles.py 50290aa002d575349d35483f9e94c93fac2f5300b458d1bf14db4383011d5ef3 bytes 13645 CRLF 253 LF 0
tests/test_tools_audit_fixes.py ba92e552424ce58e40ba4572d31de9e9ec0e7ab6ca54d446ba77912dd4bb187b bytes 54055 CRLF 1070 LF 0
tests/test_lint_rules.py f9467ece0ab5db6d52c9e7e641db7c9c986cfcf7708f7e9be20c726dcf4d3407 bytes 47609 CRLF 1012 LF 0
tests/test_policy.py 069f5bc8ca362f76842ed8b3a761f4c6d9d186bd4ee38e0a73d6af9b4a0a5557 bytes 29293 CRLF 605 LF 0
tests/test_core_audit_efgh.py daaa6af2fdda9d9583b818f8280624b2635a36fb45fe302c4943bcd33cf0975c bytes 47252 CRLF 991 LF 0
tools/coverage_zero_test.py 57641a3c462bf8adc90b3df547260903168c08628c974aac87ad0a5814d6b445 bytes 65511 CRLF 1315 LF 0
DEVELOPMENT.md 0382a47dec7e9656c683a9fd424e18965a3035e5d8e6d5bc88d9a3facf0a7376 bytes 124313 CRLF 0 LF 1211
docs/ROLE-SPECS.md 7139596007d0b0a54a9dad95b79cf17edce6208ac2eba38f74d3ddb0129c97fb bytes 172400 CRLF 0 LF 2185
docs/PROPOSAL-side-effect-axes.md cb22cf1c7b8d65c2183eed2230a747464b0b8db2bace6d6a2d8f17aebbff9c81 bytes 49922 CRLF 0 LF 726
.noai-approvals.json ebbba06c1a6a991eda931ec63221ea7e232e5b4da7631613f0479a7b99a72f3b bytes 10982 CRLF 0 LF 216
```

EOL 判定：三个禁改区文件的 CRLF 计数与改前一致（784 / 356 / 796 → 713 / 313 / 805 行数变了，
**每一个换行都是 CRLF，LF 列恒为 0**）；`DEVELOPMENT.md` 与两份 `docs/` 原本就是纯 LF，改后仍是
`CRLF 0`。全程只用了 `edit` 工具与 `open(..., newline="")` 语义的字节替换，未用 `Path.write_text()`
（G-42）。

---

## C. 三张表在本轮的真实地位（原始输出）

### C-1 `python -c "import agentflow.tools"`（G-45 第一条，先试再说）

```
tools import ok
```

`agentflow.capabilities` 导入（断言真的接上了）：

```
imports ok
non-info divergences above (none = clean)
```

### C-2 两处词表逐条

```
SIDE_EFFECTS = ("none", "read", "write_local")            # tools/base.py
SIDE_EFFECTS: tuple[str, ...] = ("none", "read", "write_local")   # capabilities.py
SIDE_EFFECTS_WRITE = ("write_local",)                     # tools/__init__.py
_WRITE_LIKE = ("write_local", UNKNOWN_SIDE_EFFECT)        # capabilities.py
```

`hasattr` 结构性判据（`tests/test_tools_base.py::test_legacy_translation_tables_are_gone`）：

```python
for mod, name in ((B, "LEGACY_SIDE_EFFECTS"), (B, "LEGACY_EFFECTS_BY_TOOL"),
                  (B, "NEEDS_APPROVAL"), (T, "LEGACY_TRANSLATIONS"),
                  (T, "untranslated_legacy_tools"), (C, "LEGACY_NETWORK_AXES")):
    assert not hasattr(mod, name)
```

### C-3 迁后工具的实测分布（`Counter` 原始输出，供登记子智能体照抄）

```
total tools 55
side_effect {'none': 5, 'write_local': 18, 'read': 32}
effect {'none': 5, 'write_local': 18, 'read': 32}
external {'none': 49, 'egress': 4, 'exec': 2}
needs_approval 21
by role {'A': 20, 'B': 18, 'C': 17, 'D': 37, 'E': 21, 'F': 32, 'G': 32, 'H': 22}
H side_effect {'read': 17, 'none': 5}
skipped []
```

对照改前快照（`axes-before-b3rest.json` 反算）：

```
before side_effect {'none': 5, 'write_local': 16, 'read': 30, 'network': 4}
before effect {'none': 5, 'write_local': 18, 'read': 32}
before external {'none': 50, 'egress': 4, 'exec': 1}
before needs_approval 20
before H 23
```

即：`read +2`（两个只读检索）、`write_local +2`（两个会写盘/下模型的）、`network -4`；
`needs_approval +1`（`verify.check_formal`）；`H 23 → 22`。
`none` 的 5 条两份快照逐条同名：`attack.check_budget`、`attack.pick_next_subgoal`、
`doc.compose_claim`、`doc.scan_claim`、`review.scan_document`。

---

## D. 验收判据逐条

### 判据 1：`python scripts/lint_rules.py` ⇒ `error 0`

原始输出（`temp/_b3r_lint_after3.txt`）：

```
[linter] 扫描 {'src_py': 53, 'tests_py': 87}；规则 11 条；模式 日常
[linter] 已退休 R006：文件级共现 → 判据移入 R010（逐工具 AST，点名到工具）；见 rule_R006 的 docstring 末节
[linter] error 0 / warning 3 / info 17
exit=0
```

改前基线（`temp/_b3r_lint_before.txt`）：

```
[linter] error 0 / warning 3 / info 19
exit=0
```

**判定：通过。** 差值 `warning ±0`、`info -2`。`info -2` 的逐条来源（R010 段）：
① `verify.check_formal` 的"已逐条登记为例外"info 消失（它现在真的声明 `exec`，不再需要豁免）；
② "逐工具遗留翻译表与实际遗留声明逐条一致（4 条）"消失（表已删）。
新增 1 条 info："遗留取值：0 处 `side_effect="network"`…"。三条 warning 与改前同名同源：
`R004` × 2（`agent_e.py:804` / `agent_f.py:1190`，改前就在的 G-1）+ `R010 ocr.run`
（"声明 egress 却查不到网络调用"——**改前也在**，因为改前它就已是 `egress` 的 `@tool` 声明）。
这三条都是改前既有项，不是本轮引入。

### 判据 2：`python -m pytest tests/ -q` ⇒ `0 failed`

原始输出（`temp/_b3r_full1.txt`，全量套件，4 分 36 秒；这是**裁决三落地之前**的状态）：

```
1 failed, 1871 passed, 8 deselected, 1 xfailed, 1 warning in 276.86s
exit=1
```

**判定：该 1 failed 已按主控裁决三处置完毕**（新增分区判据 + 两条负控，见 §H-1），
**结论由下面的复跑取代**。原始输出（`temp/_b3r_full2.txt`，裁决三落地之后）：

```
1874 passed, 8 deselected, 1 xfailed, 1 warning in 275.96s (0:04:35)
exit=0
```

**最终判定：通过（0 failed）。**

### 判据 3：`python tools/run_each_test_file.py` ⇒ 每文件独立跑 0 failed

**未跑。** 主控 02:5x 插话明确"逐文件那一遍是我的核验职责，我已经在准备"。
本子智能体**没有**运行 `python tools/run_each_test_file.py`，故本判据在本文件里记"未跑"。

### 判据 4：差分（`temp/_axes_diff.py`）

命令与原始输出见 `temp/_b3r_diff.txt`（完整，未截断）。**总条数 25**。
逐条判定如下（"预期内"= 工单 §4 列表点名过）：

| # | 差分键 | before → after | 判定 |
|---|---|---|---|
| 1 | `tools.search.providers.side_effect` | `network` → `read` | 预期内（§2.3） |
| 2 | `tools.search.literature.side_effect` | `network` → `read` | 预期内（§2.3） |
| 3 | `tools.search.download.side_effect` | `network` → `write_local` | 预期内（§2.3） |
| 4 | `tools.ocr.run.side_effect` | `network` → `write_local` | 预期内（§2.3） |
| 5 | `tools.verify.check_formal.external` | `none` → `exec` | 预期内（§2.4） |
| 6 | `tools.verify.check_formal.needs_approval` | `False` → `True` | 预期内（§2.4-1） |
| 7 | `tools.verify.check_formal.roles` | `[E,F,G,H]` → `[E,F,G]` | 预期内（§2.4） |
| 8 | `tools.verify.check_formal.sandbox_required` | `False` → `True` | 预期内（§2.4） |
| 9 | `actions.E.check_formal.side_effect` | `network` → `read` | 预期内（§2.4） |
| 10 | `actions.E.check_formal.external` | `egress` → `exec` | 预期内（§2.4） |
| 11 | `actions.E.check_formal.declared_external` | `None` → `exec` | 预期内（§2.4） |
| 12 | `actions.E.check_formal.effect` | `write_local` → `read` | 预期内（§2.4-3，不再是 `_WRITE_LIKE`） |
| 13 | `vocab.tools.SIDE_EFFECTS` | 去掉 `network` | 预期内（§2.1） |
| 14 | `vocab.capabilities.SIDE_EFFECTS` | 去掉 `network` | 预期内（§2.1） |
| 15 | `vocab.tools.SIDE_EFFECTS_WRITE` | `[write_local, network]` → `[write_local]` | 预期内（§2.1） |
| 16 | `vocab.tools.NEEDS_APPROVAL` | `[write_local, network]` → `[]`（键消失） | 预期内（§2.1） |
| 17 | `vocab.capabilities._WRITE_LIKE` | 去掉 `network` | 预期内（§2.1） |
| 18 | `for_role.H` | 少 `verify.check_formal`（23 → 22） | 预期内（§2.4-2） |
| 19 | `divergences` | 少 `two_layer_legacy_overclaims E.check_formal`（33 → 32 条） | 预期内（§2.4-4） |
| 20 | `actions.A.run_once.side_effect` | `network` → `write_local` | **预期外 → 见 §E-2** |
| 21 | `actions.A.run_once.declared_external` | `None` → `egress` | **预期外 → 见 §E-2** |
| 22 | `actions.A.run.side_effect` | `network` → `write_local` | **预期外 → 见 §E-2** |
| 23 | `actions.A.run.declared_external` | `None` → `egress` | **预期外 → 见 §E-2** |
| 24 | `actions.B.run.external` | `none` → `egress` | **预期外 → 见 §E-2** |
| 25 | `actions.B.run.declared_external` | `None` → `egress` | **预期外 → 见 §E-2** |

**未出现的预期内条目（重要）**：我**没有**新增 `two_layer_external_imprecise` 的实际命中条目 ——
真实树上两层现在逐条一致，所以该判据在真实树上产出 0 条（只在合成用例里被触发，
见 `tests/test_policy.py::test_two_layer_external_imprecise_is_a_warning_not_an_error`）。
因此 §4 里"若你新增了该判据，它带来的新条目也要逐条列出"= **没有新条目**。

快照自身的计数行：`written … tools=56 actions=48 divergences=32`（`tools=56` 是快照把
`__sandbox_available__` 也数进去的口径，真实工具 55；改前同一脚本也给 56）。

### 判据 5：负控必须有注入证明

**负控一：把 `network` 加回 `SIDE_EFFECTS`。**
注入的那一行（`Select-String` 原始输出）：

```
INJECTED-LINE: SIDE_EFFECTS = ("none", "read", "write_local", "network")
```

注入脚本：`temp/_b3r_negctl.py`（`inject-network` 动作，字节级替换，CRLF 安全）。跑：

```
$ python D:\Incubator\temp\_b3r_negctl.py inject-network
injected: SIDE_EFFECTS 里加回 network
$ python -m pytest tests/test_tools_base.py -q -k "network_is_no_longer or unregistered_legacy or needs_approval_tracks"
E       Failed: DID NOT RAISE ValueError
tests\test_tools_base.py:314: Failed
E       Failed: DID NOT RAISE ValueError
tests\test_tools_base.py:331: Failed
E       Failed: DID NOT RAISE ValueError
tests\test_tools_base.py:428: Failed
FAILED tests/test_tools_base.py::test_toolspec_needs_approval_tracks_dangerous_side_effects
FAILED tests/test_tools_base.py::test_network_is_no_longer_a_legal_side_effect
FAILED tests/test_tools_base.py::test_unregistered_legacy_tool_is_now_rejected_at_construction
3 failed, 36 deselected in 0.35s
exit=1
```

⇒ 注入真的生效（3 条用例由绿转红）。**已还原**：`restored from D:\Incubator\temp\_b3r_negctl_base.py`，
还原后 hash 与 §B 的改后 hash 一致（`59aab9a3…`），`LEGACY_` 在 `base.py` 只剩注释里 1 处提及。

**负控二：把 `LEGACY_SIDE_EFFECTS` 加回去。**
注入的那一行：

```
INJECTED-LINE 88: LEGACY_SIDE_EFFECTS: dict[str, tuple[str, str]] = {"network": ("egress", "none")}
```

跑：

```
$ python D:\Incubator\temp\_b3r_negctl.py inject-legacy-table
injected: 把 LEGACY_SIDE_EFFECTS 加回去
$ python -m pytest tests/test_tools_base.py -q -k "translation_tables_are_gone"
E           AssertionError: agentflow.tools.base.LEGACY_SIDE_EFFECTS 应当已随 B3 收官删除
E           assert not True
tests/test_tools_base.py:355: AssertionError
FAILED tests/test_tools_base.py::test_legacy_translation_tables_are_gone
1 failed, 38 deselected in 0.50s
exit=1
```

⇒ 注入真的生效，名字断言会因为"把表加回去"而变红。**已还原**（同上）。

### 判据 6：两个环境

- **Lean 环境：未跑。** 本轮没有在 `pwsh` 里加 Lean 的 PATH，也没有跑任何 Lean 相关命令。
  这一条按工单 §4.6 记"未跑"，**不是"通过"**。
- 默认（离线）环境：见判据 2 的原始输出。

---

## E. 未完成项 / 预期外项 / 必须由主控裁决的两点

### E-1 原唯一失败用例（**已按主控裁决三处置完毕**，原始证据留档）

全名：`tests/test_capabilities_two_layer.py::test_the_cross_check_actually_compares_at_least_one_action`

裁决前的原始输出（`temp/_b3r_2layer.txt`）：

```
....F                                                                    [100%]
=================================== FAILURES ===================================
_________ test_the_cross_check_actually_compares_at_least_one_action __________

    def test_the_cross_check_actually_compares_at_least_one_action() -> None:
        """对账面的下限：今天至少有 1 个动作真的被两层比对过。

        没有这条，一个"匹配全线失效"的实现（所有动作都进 unmatched）也会因为
        上面那条恒真的 error 断言而看起来正常 —— 这正是 `G-19` 的形态。
        """
        matched = [
            d for d in C.declaration_divergences() if d.code.startswith("two_layer_") and "<->" in d.where
        ]
>       assert matched, "两层比对一条都没做成 ⇒ 对账面是空的，而门会显示为通过"
E       AssertionError: 两层比对一条都没做成 ⇒ 对账面是空的，而门会显示为通过
E       assert []
tests/test_capabilities_two_layer.py:63: AssertionError
=========================== short test summary info ============================
FAILED tests/test_capabilities_two_layer.py::test_the_cross_check_actually_compares_at_least_one_action
1 failed, 4 passed in 1.49s
exit=1
```

**它当时为什么红**：该用例要求 `declaration_divergences()` 里至少有一条 `where` 含
`"<->"` 的记录，而工单 §2.2 把判据钉成"只在有分歧时才记录"；B3 收官后真实树上
两层逐条一致 ⇒ "比对成功且一致"的动作不产出任何记录 ⇒ `matched` 为空。
我当时把它登记为"待主控裁决"，**没有**自行改判据、也没有改测试。

**主控裁决三（更强形态，已落地）**：不往 `declaration_divergences()` 里塞一致项
（那个函数的名字就是"分歧"），而是新增一个**独立的公开分区判据**
`capabilities.two_layer_reconciliation()`，并让第 [7b] 条断言对账面是一个分区。
落地细节与原始输出见 §H。**裁决后该用例通过**。

⚠️ 我当时写的"约 6 个动作被两层比对过"是**错的**（主控实测与裁决后复跑都是 16）：

```
动作总数 48 ；compared 16 ；unmatched 32 ；ambiguous 0
记录的码分布 Counter({'two_layer_name_unmatched': 32})
级别分布 Counter({'info': 32})
```

### E-2 §D 判据 4 里 6 条预期外差分（**主控裁决一：全部确认**）

> **责任归属（主控要求写明）**：这 6 条是本工单 §2.3 **漏列**了
> `A.run_once` / `A.run` / `B.run` 这三个动作的目标值造成的 —— 工单只钉了
> "4 个工具"与 `E.check_formal`，而删掉 `network` 之后这三个动作必须同时改，
> 否则导入期就抛。责任在主控的工单，不在实现。主控复核结论：按
> `docs/PROPOSAL-side-effect-axes.md` §4.2 第 5 条走是**对的**。

工单 §2.2/§2.3 没有给这三个动作的目标值；但删掉 `network` 之后它们必须改，
否则 `ActionSpec` 在导入期就抛。我按下面的事实做了判断，主控已独立复跑确认：

**(a) `A.run_once` / `A.run` 的效果轴我选 `write_local`（不是 `read`），依据是代码与写集：**

- `agent_a.py:429`：`with self.store.tx("search_requests", "literature", actor=self.actor, note="register") as tx:`
- `agent_a.py:441`：`tx.upsert("literature", existing, note=f"dup_by:{hit_key}")`
- `agent_a.py:496`：`tx.upsert("literature", rowd, note=f"provider:{entry['provider']}")`
- `capabilities.WRITE_SETS["A"] = frozenset({"search_requests", "literature"})`

并且这是**导入期硬约束**：`assert_capabilities()` 第 [6] 条要求"写集非空 ⇒ 至少一个
`_WRITE_LIKE` 动作"。我先按"照抄工具层 `search.*` 的 `read`"实现，得到原始报错：

```
AssertionError: WRITE_SETS['A']=['literature', 'search_requests'] 非空（已减掉已登记的只读例外），
但该角色没有任何效果轴为 ('write_local', 'unknown') 的动作（实测轴值：['read']）
—— 写集说它会写表，效果轴说它不写：这两个判据不许分叉
```

⇒ 改成 `write_local` + `external="egress"` 后导入通过。请主控确认这个改判（它是 §D-4 的
20/22 号差分，也是那两条"预期外"条目的全部内容）。

**(b) `B.run` 的外部轴我选 `egress`（效果轴保持 `write_local` 不动），依据是两层对账判据的报错：**

```
AssertionError: 两层声明不一致（能力层低估了风险轴）：B.run <-> ocr.run: 工具层声明 external='egress'，
能力层声明 'none'（能力层**低估**了这根轴）—— 两层对同一个动作能不能触到我们不拥有的事有两个估值，
而能力表是并发与召唤判据的输入
```

⇒ `B.run` 会经 OCR 读 PDF，而 `ocr.run` 迁后声明 `egress`；这一格留着默认 `none` 会让
第 [7] 条在导入期炸。**主控裁决一：确认**（§D-4 的 24/25 号差分）。

### E-3 我另外做的一处必要修正：**B3 顺带修掉的 `G-47`**（主控裁决二：确认）

`capabilities._declared_side_effects`（读工具层源码的 AST 读取器）**改成了同时认
`declared_external=` 与 `external=`**；`scripts/lint_rules.py` 的 `_r010_specs` 同步
加了 `_r010_external_literal`。

**缺陷本身（B1/B2 带进来的，主控已另行登记为 `G-47`）**：AST 读取器只认**属性名**
`external=`，不认**字段名** `declared_external=` ⇒ 第二根轴对判据面**完全不可见**。
真实树上 `ToolSpec` 的第二根轴字段名是 `declared_external`（`external` 是属性名，
写进构造器会 `TypeError`，见 G-45），所以这条缺陷的后果是**每一个**显式声明了第二根轴的
工具都被读成默认值 `none`。原始证据（迁移前就跑过，`temp/_b3r_probe1.txt`）：

```
verify.run_experiment ('write_local', 'none', False)
verify.check_formal ('read', 'none', False)
verify.detect_verifier ('read', 'none', False)
search.providers ('network', 'none', False)
search.literature ('network', 'none', False)
search.download ('network', 'none', False)
ocr.run ('network', 'none', False)
```

第三分量 `False`（"没有显式声明"）是关键：`verify.run_experiment` 在 B3 第 0 步
**已经**写了 `declared_external="exec"`，而读取器把它读成 `('write_local', 'none', False)`。

修复后的实测（主控复核过的同一组读数）：

```
verify.run_experiment ('write_local', 'exec', True)
verify.check_formal ('read', 'exec', True)
ocr.run ('write_local', 'egress', True)
```

不改它，则 B3 收官后 `E.check_formal <-> verify.check_formal` 会变成
`two_layer_external_divergence`（**error** 级），`import agentflow.capabilities` 直接失败 ——
即"两层其实说同一句话、却因为读取器认错字段名而报不一致"。这正是一条由读错名字造出来的
假报警。同样地 R010 若不认 `declared_external=`，新建的
`tests/test_lint_rules.py::test_r010a_does_not_flag_a_tool_declaring_declared_external`
（负控）与 `::test_r010a_still_flags_declared_external_none_with_a_process_call`（正控）
这两条成对用例就会失去意义 —— 它们正是为"判据接在哪个字段名上"这件事写的。

### E-4 未核实项（明确登记）

| # | 项 | 状态 |
|---|---|---|
| 1 | Lean 环境（`pwsh` 里加 PATH）下的复跑 | **未跑** |
| 2 | `python tools/run_each_test_file.py` 逐文件那一遍 | **未跑**（主控核验职责） |
| 3 | `tests/test_tools_returns_declaration.py` 等是否还有其他遗留取值断言 | 全量套件已覆盖（判据 2 的 1871 passed），但**未逐文件人读** |
| 4 | `docs/ROLE-SPECS.md` 其余"实测快照"数字（第 68/74/283/2174 行等全局分布） | **本轮未对齐**（工单 §2.7 明确不要求；真实分布已在 §C-3 给出供照抄） |
| 5 | `_KNOWN_UNMATCHED_ACTIONS` 是否需要因本轮迁移删条目 | 实测**不需要**：`tests/test_capabilities_two_layer.py::test_the_registry_matches_todays_unmatched_set_exactly` 通过（32 条 unmatched 与登记表逐条相同） |
| 6 | `verify_role_specs.py` 的门 | 已跑，`exit=0`（输出见 §F） |
| 7 | `tests/test_role_specs_complete.py` | 已跑，`19 passed`（输出见 §F） |
| 8 | 裁决三落地后的**全量套件**（`pytest tests/ -q`） | 已发起（`temp/_b3r_full2.txt`）；**收工前以该文件的实际汇总行为准**，若与本文件写的数不同以文件为准 |
| 9 | 裁决三落地后逐文件那一遍 / Lean 那一遍 | **未跑**（主控核验职责） |

---

## F. 禁改区纪律与其余门的原始输出

### F-1 台账基线刷新（**无 `reviewers` 写入**）

```
$ python scripts/noai_gate.py --paths src/agentflow/tools/base.py src/agentflow/tools/__init__.py src/agentflow/tools/verify_tools.py --baseline --note "B3 收官：删掉遗留取值 network 与两张翻译表；四个工具 + verify.check_formal 迁到两根轴"
[baseline] 登记 3 条 / 未登记 0 条；台账：D:\Incubator\agentflow\.noai-approvals.json
  · src/agentflow/tools/base.py  refreshed  sha256 59aab9a3857e  [auth-audit]  authored=unknown/inferred  reviewers=0（**登记 ≠ 批准**，reviewers 只能由人 `--approve` 追加）
  · src/agentflow/tools/__init__.py  refreshed  sha256 7309691667f4  [auth-audit]  authored=unknown/inferred  reviewers=0（**登记 ≠ 批准**，reviewers 只能由人 `--approve` 追加）
  · src/agentflow/tools/verify_tools.py  refreshed  sha256 8b8b87cf788b  [prover-bridge]  authored=unknown/inferred  reviewers=0（**登记 ≠ 批准**，reviewers 只能由人 `--approve` 追加）
exit=0
```

`git diff`（`temp/_b3r_ledger_diff.txt`，节选三个禁改区条目；完整 diff 里另外四条
（`.noai-paths` / `AGENTS.md` / `scripts/release_check.py` / `tools/release_all.py`）是
**改前就已经在工作树里的历史改动**，本次 `--baseline` 一并把它们从 `changed_this_session:
true` 刷成了 `null` 并更新了 `sha256`，`reviewers` 一律为空）：

```diff
       "path": "src/agentflow/tools/__init__.py",
-      "sha256": "69272d9746a368132ea2af53ea676e2438dc451dba825cc86c9ff5eda9281a28",
+      "sha256": "7309691667f4293dc145b95694d901fbc7eaadd2839d3e4120da664c8a865338",
-      "change_note": "P-13 B1/B2: ToolSpec 第二根轴 + 交叉断言（AI 编写，待 2 名 reviewer 逐行走查）",
+      "change_note": "B3 收官：删掉遗留取值 network 与两张翻译表；四个工具 + verify.check_formal 迁到两根轴",
       "reviewers": [],
@@
       "path": "src/agentflow/tools/base.py",
-      "sha256": "1b6ccc4e30a6ef424497b8ae651ed698f334d7c205006d15d9c25dc6d3e69f8b",
+      "sha256": "59aab9a3857ef6ef99098c95d6b580585004113433c9e2a84ff030b77f1a66d1",
       "reviewers": [],
@@
       "path": "src/agentflow/tools/verify_tools.py",
-      "sha256": "a99bba5cdbc5c0fee1dd1dbb5550317348313429bb7615efe51964732e32a9bb",
+      "sha256": "8b8b87cf788bb1633c5e6201371e1488a1ec3a87e36683ba48ad4d8d272f0484",
       "reviewers": [],
```

`reviewers` 总计（原始输出）：

```
entries 16 reviewers_total 0
```

**判定：通过。** 只有 `sha256` / `generated_at` / `change_note` 变了，`reviewers` 全部仍为空，
`reviewers_total` 仍为 **0**。

### F-2 `python scripts/noai_gate.py --check-consistency`

```
一致：.noai-paths 与 AGENTS.md 的清单逐条相同
exit=0
```

### F-3 `python tools/verify_role_specs.py`（工单 §2.7 要求退出码 0）

```
[ok] D:\Incubator\agentflow\docs\ROLE-SPECS.md
9 个角色节（A B C D E F G H M）各自 8 个必备子节齐全
  [OK ] §A 文献检索                               行   295 子节 10  工具条数 [20]
  [OK ] §B 文献整理                               行   467 子节 10  工具条数 [18]
  [OK ] §C 只读图分析                              行   653 子节 10  工具条数 [17]
  [OK ] §D 研究                                 行   863 子节 10  工具条数 [37]
  [OK ] §E 数值实验与形式化验证                         行  1055 子节 10  工具条数 [21]
  [OK ] §F 多轮难题攻坚                             行  1221 子节 10  工具条数 [32]
  [OK ] §G 论文撰写                               行  1435 子节 10  工具条数 [32]
  [OK ] §H 审校（只读）                             行  1638 子节 10  工具条数 [22]
  [OK ] §M 主控（Conductor）                      行  1822 子节 10  工具条数 []
exit=0
```

### F-4 `python -m pytest tests/test_role_specs_complete.py -q`（工单 §2.7 要求）

```
...................                                                      [100%]
19 passed in 11.84s
exit=0
```

改这一节前它是红的（23 → 22 的条数对不上），原始报错：

```
E           AssertionError: §R0 的审批/roles 列与注册表不一致：{'verify.check_formal': "审批 文档='否' 实际=True；roles 文档=['E', 'F', 'G', 'H'] 实际=['E', 'F', 'G']"}
E           AssertionError: §R0 的
side_effect 列与注册表不一致：…（H.4 与 §R0 两处）
2 failed, 17 passed
```

改后除 §H.4（23 → 22、`{'read': 17, 'none': 5}`、删掉 `verify.check_formal` 一行、
"H 拿不到"清单加上它）之外，还改了 §R0 主表里五条工具行
（25 `ocr.run`、34 `search.download`、35 `search.literature`、36 `search.providers`、50 `verify.check_formal`）
的 `side_effect` / 审批 / `roles` 三列 —— 这三列是 `test_role_specs_complete.py` 逐行比对的列。

---

## H. 主控裁决三的落地（D-3：对账面必须是分区）

### H-1 落地内容

| 落点 | 改了什么 |
|---|---|
| `src/agentflow/capabilities.py` | **新增公开函数** `two_layer_reconciliation() -> dict`，返回 `{"total", "compared", "unmatched", "ambiguous"}`；抽出 `_candidates(spec, tools)` 与 `_reconcile(capabilities, tools)` 两个内部函数，让"分区"与"分歧"共用同一套匹配判据（`_divergences` 也改用它） |
| 同上 `assert_capabilities()` | 新增第 **[7b]** 条：三格之和 == `total`、三格两两不相交、`compared` 非空、`ambiguous` 必须为空（否则报"歧义…`_KNOWN_UNMATCHED_ACTIONS` 只管 unmatched，管不住这一格"） |
| 同上 `_KNOWN_UNMATCHED_ACTIONS` 注释 | 补明"它只管 `unmatched`，`ambiguous` 由第 [7b] 条的分区断言管" |
| `tests/test_capabilities_two_layer.py` | 原用例改成用分区判据（保留"匹配全线失效不许看起来正常"的原意）；新增两条负控 |

`ambiguous` 那一格**今天恰好是 0，而它原来不在任何登记表里** ⇒ 是一条真的
"对账面可以静默缩小"的缝；第 [7b] 条就是它的闸门（`G-19` 的同族形态）。

### H-2 原始输出：`import` + 分区读数

```
$ python -c "import agentflow.capabilities; print('ok')"
ok
exit=0

$ python -c "import agentflow.capabilities as C; r = C.two_layer_reconciliation(); ..."
动作总数 48 ；compared 16 ；unmatched 32 ；ambiguous 0
记录的码分布 Counter({'two_layer_name_unmatched': 32})
级别分布 Counter({'info': 32})
```

`compared` 的 16 条逐条（用于核对"比对真的做成了"）：

```
[('B.run', 'ocr.run'), ('C.neighbors', 'graph.neighbors'), ('C.relations_between', 'graph.relations_between'),
 ('E.run_experiment', 'verify.run_experiment'), ('E.check_formal', 'verify.check_formal'),
 ('E.evidence_for', 'verify.evidence_for'), ('E.list_experiments', 'verify.list_experiments'),
 ('F.create_plan', 'attack.create_plan'), ('F.step', 'attack.step'), ('F.status', 'attack.status'),
 ('F.list_plans', 'attack.list_plans'), ('G.compose_claim', 'doc.compose_claim'),
 ('G.register_dependency', 'doc.register_dependency'), ('G.build_document', 'doc.build_document'),
 ('H.verify_fixes', 'review.verify_fixes'), ('H.list_findings', 'review.list_findings')]
```

### H-3 原始输出：裁决指定的两条命令 + lint

```
$ python -m pytest tests/test_capabilities_two_layer.py tests/test_policy.py -q
.....................................................                    [100%]
53 passed in 4.18s
exit=0

$ python scripts/lint_rules.py
[linter] 扫描 {'src_py': 53, 'tests_py': 87}；规则 11 条；模式 日常
[linter] 已退休 R006：文件级共现 → 判据移入 R010（逐工具 AST，点名到工具）；见 rule_R006 的 docstring 末节
[linter] error 0 / warning 3 / info 17
exit=0
```

（裁决三落地**之前**这两条命令的原始状态：`lint error 2`（我自己新写的注释里带了
Markdown 强调标记，R009 抓到，已按 §A 的同一纪律清掉）、`test_capabilities_two_layer.py`
1 failed + 51 passed。清理后的最终读数如上。）

### H-4 两条负控的注入证明（两条例外都是"负控必须红"）

`test_the_partition_assertion_catches_an_ambiguous_action`：把 `_candidates` 打桩成对
`H.verify_fixes` 返回两个候选 ⇒ 实测 `recon["ambiguous"] == ["H.verify_fixes"]`，
且 `assert_capabilities()` 抛 `AssertionError`（匹配 `歧义`）。

`test_the_partition_assertion_catches_an_empty_compared_set`：把 `_candidates` 打桩成
恒返回 `[]`（匹配全线失效），并把 `_KNOWN_UNMATCHED_ACTIONS` 打桩成"全部动作"
（让第 [7] 条那两条登记表断言在这条负控下恰好都不触发）⇒ `compared == []`、
`ambiguous == []`、`unmatched == total`，唯一会红的就是第 [7b] 条的
`对账面是空的`。

**这两条负控是迭代出来的，过程本身是证据**（说明"负控命中了别的断言"这种假证明真的会发生）：

1. 第一版把 `compared` 清空的造法是"把能力表换成 handler 不存在的动作" ⇒
   报错落在第 [2] 条（`AgentA 上没有可调用的 'gone_run_once'`），不是目标断言；
2. 第二版改成"每个角色留一个真实但匹配不上的方法名" ⇒ ②`StopIteration`
   （有角色找不到这样的方法名）；
3. 第三版改成打桩 `_candidates` 恒返回 `[]` ⇒ 报错落在第 [7] 条
   （`出现了新的『两层没有比对』的动作`），**仍不是目标断言**；
4. 最终版再加一步 `_KNOWN_UNMATCHED_ACTIONS` 打桩 ⇒ 报错才落在目标断言
   `对账面是空的`。

### H-5 裁决三落地后的全量套件（`temp/_b3r_full2.txt`）

```
1874 passed, 8 deselected, 1 xfailed, 1 warning in 275.96s (0:04:35)
exit=0
```

### H-6 落地后的 sha256 / EOL（最终值，覆盖 §B 里对应行的旧值）

```
src/agentflow/capabilities.py deb226171d8ba3f1dcc9f96c60c2b8f718de6d94397476f0fc6f67b60d3da16c bytes 91496 CRLF 1648 LF 0
tests/test_capabilities_two_layer.py dad5199712e8eeb857d9d337444ff485f1a8208cffb7a8659980cad3e883aad9 bytes 7573 CRLF 132 LF 0
```

其余文件与 §B 表一致（`temp/_b3r_eol_final2.txt` 是这一轮的完整原始输出）。
`capabilities.py` 与 `tests/test_capabilities_two_layer.py` 都**不在**禁改区清单里，
所以台账无需再刷新；台账与磁盘的 hash 一致性在本轮结束时又核了一遍：**无漂移**
（`LEDGER DRIFT` 一条都没打印），`reviewers_total` 仍为 **0**。

---

## G. 一句话结论

`network` 与两张翻译表已从代码里彻底删除（含 `NEEDS_APPROVAL` / `LEGACY_TRANSLATIONS` /
`untranslated_legacy_tools` / `LEGACY_NETWORK_AXES` / R010 遗留分支），四个工具 +
`verify.check_formal` 已迁到两根轴上的确定值；lint `error 0`；差分 25 条
（19 条预期内、6 条主控裁决一确认的"工单漏列"）；两个负控注入均证明生效且已还原；
台账 `reviewers_total` 仍为 0、一致性门退出码 0；`verify_role_specs.py` 退出码 0、
`test_role_specs_complete.py` 19 passed。

裁决三落地后：**全量套件 `1874 passed, 0 failed`**（`temp/_b3r_full2.txt`），
原唯一失败用例（§E-1）按更强形态通过，并新增第 [7b] 条分区断言 + 两条负控
（堵住"`ambiguous` 可以静默长大"那条缝）。

**未跑**：Lean 环境那一遍、`tools/run_each_test_file.py` 逐文件那一遍
（两者都是主控的核验职责，见 §E-4 第 1/2/9 项）。
