# FIX6-F1 报告：门与台账的 CLI 通路（`R6-R1d-1` … `-7`）

批次：F1（第 6 轮修复批）　窗口：2026-09-27（单写窗口内一次做完）
依据：`temp/FIX6-DISPATCH.md`（F1 行 + 并发写者纪律）、`temp/FIX6-PLAN.md` 第 0/1/2/3 节、
`temp/REAUDIT6-R1d.json` 的 7 条 finding、`draft/28` 第 80 与第 85 节。

## 0. 改前 / 改后指纹

| 文件 | 改前 sha256 | 改后 sha256 | 字节 | 行 |
|---|---|---|---|---|
| `scripts/noai_gate.py`（禁改区 auth-audit） | `730f51e88546e1fe…` | `eca8f582601c56ae…` | 197033 → 216444 | 3936 → 4242 |
| `tests/test_noai_gate.py` | `587758dadfbf8ede…` | `88a8685f5ecbabc6…` | 106287 → 108172 | 2144 → 2166 |
| `tests/test_noai_gate_audit_channel.py`（**不在 §1 清单内，见 §4**） | `5b8ed564080b9564…` | `b3b243e2dfef3b92…` | 51817 → 55329 | 962 → 1005 |
| `tests/test_noai_gate_record_audit_cli.py`（新建） | —（不存在） | `9ce1ddc2c8f65be7…` | 16991 | 350 |
| `D:\Incubator\temp\batchR1c-evidence.md`（追加一节，不改原文） | 19775 字节 | | | |

备份（改前逐字节）：`temp/batchF1-noai_gate.py.bak` = `730f51e8…`（与 `REAUDIT6-R1d.json`
`files_sha256_before` 逐字相同）、`temp/batchF1-test_noai_gate.py.bak` = `587758da…`、
`temp/batchF1-test_noai_gate_audit_channel.py.bak` = `5b8ed564…`。

禁改区文件已按 §0.1 补进 `temp/zone-head-backups.tsv`（`scripts/noai_gate.py` 那一行：
`bytes=216444`、`current_sha256=eca8f582…`、`byte_identical_to_head=pending-human-walkthrough-F1`）。
未动：`.noai-approvals.json`（仍 `8175efc2…`）、`.noai-paths`、`AGENTS.md`、`src/` 其他文件、
`docs/`；**没有**重跑 `--baseline`。

## 1. 逐条 finding → 修法 → 正控 / 负控

负控统一由 `python temp/f1-neg-controls.py` 生成（原始读数：`temp/f1-neg-controls.txt`，
副本落在 `temp/f1-neg/`）。脚本每组都打印副本 sha256 与"与当前字节不同（注入生效）"。

### `R6-R1d-1`（high）`--record-audit` 每次调用 NameError

修法（照 `draft/28` §80.4 的 Y 版，**不用**审计者第一版的 `new_ledger.counted_audits`）：

- `_run_record_audit`：`updated.counted_audits` → `new_ledger.entry_for(info["path"]).counted_audits`；
- `record_audit(...)` 的 `audit_started_sha256=` / `independence=` 两行缩进对齐到 8 空格；
- 新增 `tests/test_noai_gate_record_audit_cli.py`（走真 CLI 的用例）。

正控（真 CLI，`temp/f1-neg-controls.txt`）：`--baseline` ⇒ exit 0；`--record-audit` ⇒
exit 0、stderr 空、台账里 audits 由 0 变 1。
负控：副本把那一行改回 `updated.counted_audits`（`gate-r1d6-key.py` 之外另有一份
`gate-nameerror` 形态；见 pytest `test_negative_control_nameerror_copy_is_red`）⇒ 子进程
exit ≠ 0 且 stderr 含 `NameError: name 'updated' is not defined`。
对应 pytest：`tests/test_noai_gate_record_audit_cli.py::test_record_audit_cli_exits_zero_and_writes_exactly_one_audit`
与 `::test_negative_control_nameerror_copy_is_red`（6 passed）。

### `R6-R1d-2`（medium）`--record-audit` 的退出码读数不再携带信息

修法：① 由 `-1` 恢复退出码的信息量；② 在 `temp/batchR1c-evidence.md` **追加**一节
"附：F1 修复批对本文 §1.4 那张表的读数标注"（不改原文），逐条标注那 9 个探针的
`--record-audit` 退出码在 `730f51e8` 这一版上恒为 1（不代表成功/被拒），并写明判定结论
只引 `--check-approvals` 的 `approval_status` / `distinct_*` / `detail`；③ 落口径：
写入侧失败由 stdout 的 `[record-audit] unknown(2)：…` 表达，不许靠退出码。

正控/负控：这是一条**读数标注**类工作，没有新判据可注入 ⇒ 它的正控是"标注之后原文
逐字节未变、且被标注的读数逐条对得上"：`batchR1c-evidence.md` 的原文段（§0–§7）未改，
新增内容在文件末尾；负控构造不出（没有可撤掉的实现），如实登记，**不计入强证据**。

### `R6-R1d-3`（low）时间戳可整体倒挂

修法（取 (a) 变严那一支）：新增 `audit_timestamps_not_monotonic()`（判"同一台账条目的
`counted_audits` 按盘上顺序 `at` 非递减"）+ 新理由码
`REASON_AUDIT_TIMESTAMPS_ORDER = "audit_timestamps_not_monotonic"`，
在 `evaluate_approval` 里判（在机审通路之前）；写侧 `record_audit` 追加前与
`entry.audits[-1].at` 比一次；输出措辞改成"审计者**自报**的时间戳（门只判可解析、
不在未来、次序非递减）"，`audit_timestamps` 的元素带 `basis=self_reported` 与
`gate_checked`（保留列表形态，不打断既有的按列表取值的探针）；另抽 `_parse_audit_at()`
一处实现给单条与整串共用。

正控（`temp/f1-neg-controls.txt`）：三条 `at` 递增 ⇒ `approved`（不变）；
三条 `at` 倒挂（03:00 → 02:00 → 01:00）⇒ `unapproved` /
`audit_timestamps_not_monotonic`（改前实测 approved，见 `REAUDIT6-R1d.json` 的 `-3`）。
负控：副本撤掉那条 `if order_problem: return ...`（`gate-r1d3-no-order.py`，
sha256 `5192ef96…` ≠ 当前 `eca8f582…`）⇒ 同一批倒挂时间戳重新 `approved`。

### `R6-R1d-4`（low）判据 0 不做 `max_share` 判定

修法：`if len(owned) == len(dims)` → `if len(owned) > max_share`
（`max_share = max(1, (require + 1) // 2)`），并删掉那个恒真的前置条件
`if len(dims) > max(1, (require+1)//2):`（它让算出来的上限从没用在判定上）；
两档文案（完全独占 / 超过上限）走同一理由码；`tests/test_noai_gate.py` 里那条用例的
注释与 docstring 改成它实际守的东西。**变严**，没有放宽任何既有判据。

正控（函数级自足探针，`temp/f1-neg-controls.txt`）：2 名审计者 × 各 2 个维度 ⇒ 返回空串
（放行）；3 名 × 各 1 个 ⇒ 返回空串；2 名 × 各 3 个（共 6 个维度）⇒ 返回"同一名审计者
供给了太多计入维度：…… 但其中 3 个来自同一名审计者（'s-2'）"。
负控：副本改回 `== len(dims)`（`gate-r1d4-maxshare.py`，sha256 `35b91f31…`）⇒ 同一批
6 维度**不再**返回"供给了太多维度"那句（改成由判据 2 报红）。

**如实登记（这条负控比前几条弱）**：`require = 3` 时"判据 0 报红"与"判据 2 放行"在
**可达状态上是互斥的** —— 判据 0 报红要求 `owned > 2`（3 个维度来自同一名审计者），
而那 3 个面两两相交 ⇒ 判据 2 必然也报红，于是 verdict 在改前/改后**都是 unapproved**，
只有理由码/文案不同（`REAUDIT6-R1d.json` 的 `-4` acceptance 说"必须非 approved；当前实测
approved ⇒ 红"，指的是它给的那个 2 人 × 4 维度最小复现；那一形态在 `max_share = 2` 下
`len(owned) = 2` 不大于上限，所以**在 `require = 3` 的常数下 `max_share` 的加强恰好不改变
任何可达形态的 verdict**）。这条 finding 的落地价值是"算出来的上限终于真的用在判定上了"
（理由码与文案变准、以后 `require` 变大时行为正确），不是"多挡住了一种原先进得来的形态"。
两个读数都在 `temp/f1-neg-controls.txt` 里，请按这个口径读。

### `R6-R1d-5`（low）观察面可由无关 token 撑开

修法（取 (a) + (b)）：新增 `_observation_tokens(scope, target_text, *, reuse_across=None)`
—— 第 1 层丢掉文件后缀 token（原口径），第 2 层只保留落在 `_identifiers_of(target_text)`
上的 token；`_observation_key` / `_disjoint_face_count` 都接 `target_text`；
`dimension_independence_problem` 的判据 1/2 与 `evaluate_approval` 的
`observation_surfaces` / `independent_observation_surfaces` 都按过滤后的口径算
（读不到被审对象时退回"自指"弱口径：只保留被别的审计也用到的 token —— 依据是
"至少一个 token 落在被审对象上"这条判据在判定口径下对每一条审计都要成立）。

正控（`temp/f1-neg-controls.txt`）：三条 scope 写成
`target.py alpha R1d-N2a` / `target.py beta R1d-N2b` / `target.py gamma R1d-N2c`
（`R6-R1d-5` 的 N2 原形）⇒ 报数是 `['alpha', 'beta', 'gamma']`、两两不相交 3 个；
把名字 token 去掉的干净形态 ⇒ 同一个读数（3 个）⇒ 判据不是靠名字 token 撑出来的。
负控：副本撤掉第 2 层（`gate-r1d5-faces.py`，sha256 `bf0a8717…`）⇒ 同一份台账的报数变成
`['alpha r1d-n2a', 'beta r1d-n2b', 'gamma r1d-n2c']`（名字 token 回来了）。
**如实登记（这条负控也弱）**：N2 形态的 verdict 在改前/改后都是 approved ——
判据 2 是"不相等才报红"，而面数从 3 掉到 1 在 `>=` 方向上是变松的那一侧，
所以过滤**不可能**把一个原本批准的形态判红（`chosen_filtered ≤ chosen_unfiltered`）。
这条 finding 落在"**报数说的是不是实话**"上：修完 `independent_observation_surfaces`
与 `observation_surfaces` 不再被无关 token 撑大（`REAUDIT6-R1d.json` 的 `-5` 原话：
"`independent_observation_surfaces = 3` 这句话在 N2 那个形态下说的不是实话"）。

### `R6-R1d-6`（low）公开返回值里的私有中间量 + 同名字段两处口径

修法：把 `"_target_text": target_text` 从 `record_audit` 的 `info` 里拿掉，
`_run_record_audit` **自己读**被审对象（与判定侧 `evaluate_approval` 同构：
`_target_path(target, root).read_text(...)`，读不到就把文本留空、由判据报红）；
`info` 另给显式计数名 `distinct_dimension_count`，CLI 打印与
`evaluate_approval` 的 `distinct_dimensions`（列表）同口径；`at` 那行的文案改成"自报"。

正控：真 CLI 上 `--record-audit` ⇒ exit 0；CLI 打印"不同维度 1/3"，而
`--check-approvals --json` 里 `distinct_dimensions == ['axes']` ⇒
`f"不同维度 {len(one['distinct_dimensions'])}/"` 命中同一句（pytest `::test_check_approvals_json_and_cli_agree_on_the_dimension_count`）。
负控：副本把 CLI 那一处改回 `info["_target_text"]`（`gate-r1d6-key.py`，sha256 `c47a6eda…`）
⇒ 同一条 CLI 子进程 exit 1、stderr 末行 `KeyError: '_target_text'`
（证明"CLI 自己读目标"这个修法是活的）。pytest `::test_negative_control_target_text_key_copy_is_red` 同形。

### `R6-R1d-7`（low）空字形填充码位没被折掉

修法：新增 `_INVISIBLE_FILLERS = ("\u115f", "\u1160", "\u3164", "\uffa0", "\u2800", "\u00ad")`
与 `normalize_subject` 里的第 4 步（类别 `Lo`/`So`、字形却是空的填充码位一律折掉）。
**不**改成"只允许 ASCII"（会误伤中文真姓名）。折断它们只可能把两个原本不等的串并成一个
（变严）；反向只发生在某个名字完全由这些码位构成时，而那时归一化结果是空串，
`_reviewer_identity_problem` 与 `record_audit` 的非空判据会拒掉（不是静默合并）。

正控：`normalize_subject('reaudit5-H') == normalize_subject('reaudit5-H' + U+3164)` ⇒ True
（逐个码位都测）；`_reviewer_identity_problem('reviewer-甲') == ''`、
`normalize_subject('reviewer-甲') != normalize_subject('reviewer-甲乙')`（真姓名不受影响）；
`_reviewer_identity_problem('\u3164') != ''`（只剩填充码位仍被拒）。
负控：副本把那一行注入成 `pass`（`gate-r1d7-filler.py`，sha256 `7e3b5e90…`）⇒ 同一对名字
重新不等（`'reaudit5-h' != 'reaudit5-h\u3164'`，False）。pytest 里
`::test_normalize_subject_folds_empty_glyph_fillers` 也做同一对注入。

## 2. 收工读数

### 2.1 lint（`python scripts/lint_rules.py`）

我自己的文件：**R009 命中 0**（逐文件核过：`scripts/noai_gate.py`、`tests/test_noai_gate.py`、
`tests/test_noai_gate_audit_channel.py`、`tests/test_noai_gate_record_audit_cli.py`、
`scripts/release_check.py`）。全树汇总行（原始）：

```text
[linter] 扫描 {'src_py': 53, 'tests_py': 119}；规则 12 条；模式 日常
[linter] error 1 / warning 0 / info 20
  ERROR R009 tests/test_r5_orchestration_cost.py:877  3 处注释/docstring 里有 Markdown 强调标记或 emoji
```

⇒ 当时全树唯一剩余的 R009 落在 `tests/test_r5_orchestration_cost.py`（**别人的所有权文件**，
F5 批的范围），不在我的清单里、我没有碰它。（期间还看到过 `tests/test_release_all.py` 的
SyntaxError 警告，那也在别人的清单里。）
**收工时的最终读数（含 F1-FOUND-1 补修之后）：`error 0 / warning 0 / info 20`**
—— 那两条都由各自的批收掉了，见 `temp/f1-lint-after.txt`。

### 2.2 定向用例（不跑全量）

```
python -m pytest tests/test_noai_gate.py tests/test_noai_gate_audit_channel.py \
  tests/test_noai_gate_record_audit_cli.py tests/test_noai_gate_umbrella_prefix.py -q -p no:cacheprovider
⇒ 159 passed in 25.97s
```

原始输出：`temp/f1-pytest-all.txt`。分文件：`test_noai_gate.py` 115 passed、
`test_noai_gate_audit_channel.py` 33 passed、`test_noai_gate_record_audit_cli.py` 6 passed、
`test_noai_gate_umbrella_prefix.py` 5 passed。

### 2.3 负控原始读数

`python temp/f1-neg-controls.py` ⇒ `temp/f1-neg-controls.txt`（副本在 `temp/f1-neg/`，
每组打印副本 sha256 与"注入生效"）。每条的正控/负控读数见本报告 §1。

## 3. 没修 / 修不动的

- `R6-R1d-2`：它的 ①②③ 都落地了，但"退出码恢复"依赖 `-1`，本身没有可注入的实现 ⇒
  **负控构造不出**，如实登记（不计入强证据）。
- `R6-R1d-4` 与 `-5`：修法（判定条件/过滤层）都落地了，但它们的负控**不能翻转 verdict**
  （原因逐条写在 §1：`require = 3` 时判据 0 与判据 2 的可达判红域互斥；过滤只会让面数变小，
  而判据 2 是"不足才报红"）⇒ 负控读数停在"实现层变活"（返回的判据文案 / 报数内容不同），
  **没有**"同一批台账由 approved 变 unapproved"那种强形态。如实登记，不把它算成强证据。
- 没有别的 finding 被跳过；7 条全部落地。

## 4. 实际改动文件与账面不一致的一处（如实报）

`FIX6-PLAN.md` §1 给我的清单是 `scripts/noai_gate.py`、新建
`tests/test_noai_gate_record_audit_cli.py`、`tests/test_noai_gate.py`、
`D:\Incubator\temp\batchR1c-evidence.md`。我**还改了**
`tests/test_noai_gate_audit_channel.py`（父代理在收工前也按 mtime 发现了），理由：

`R6-R1d-4` 把判据 0 从"只挡完全独占"改成"直接判 `len(owned) > max_share`"，该文件的
`_six_clean_audits()` 夹具（2 名审计者 × 各 3 个维度）正好落在新判据外面 ⇒ 9 条用例会因为
"夹具本身不合规"而红（它们的主题是证据锚/回执链，与判据 0 无关）。改动是：

1. `_six_clean_audits()` 的审计者分布 2 名（各 3 维度）→ 3 名（各 2 维度），
   正控用例名与断言 `distinct_auditors` 同步（2 → 3）；
2. `test_empty_scope_and_audit_started_sha_are_caught_at_the_field_layer`：
   原先用 `_six_clean_audits()[3:]` 那种下标切片构造"剩下的那些"，
   夹具改分布后切片取到的三条自己就够门槛（负控会假绿）⇒ 改成"3 名 × 各 1 个维度
   + 一条与其中一条同审计者同证据身份的坏记录"，断言钉在"这一条没被收录"上；
3. 其间还发现该用例原本那条 `out["approval_status"] == "unapproved"` 断言在下标切片
   形态下**本来就是假绿**（切片出来的三条自己就够门槛），所以断言改成不随夹具漂的形态。

判据一条都没放宽（改动只让夹具更合规、断言更贴它实际守的东西）。

## 5. 交付物

- `scripts/noai_gate.py`（禁改区，改后 `eca8f582601c56ae…`）
- `scripts/release_check.py`（禁改区，改后 `3bdf4510d8d519fc…`，见 F1-FOUND-1）
- `tests/test_noai_gate.py`（改后 `88a8685f5ecbabc6…`）
- `tests/test_noai_gate_audit_channel.py`（改后 `b3b243e2dfef3b92…`）
- `tests/test_noai_gate_record_audit_cli.py`（新建 `9ce1ddc2c8f65be7…`）
- `D:\Incubator\temp\batchR1c-evidence.md`（追加"附"一节）
- 备份：`temp/batchF1-{noai_gate.py,test_noai_gate.py,test_noai_gate_audit_channel.py}.bak`、
  `temp/batchF1FOUND1-release_check.py.bak`
- 负控脚本与读数：`temp/f1-neg-controls.py` / `.txt`、副本目录 `temp/f1-neg/`
- 读数：`temp/f1-lint-after.txt`、`temp/f1-pytest-all.txt`

---

## F1-FOUND-1：我的修法引入的跨文件不变量破坏（补修，父代理实测报回）

**这是我的修法引入的，不是既有缺陷。** 如实标注，并记下发现路径（父代理实测报回，
不是我自查出来的 —— 这一点也要如实写：我改 `R6-R1d-3` 时**没有**去跑
`tests/test_release_check_noai.py`，那正是"改了一侧、另一侧没接"的同一个形态，
只不过这次是我自己犯的）。

### 现象（父代理读数）

带门口径环境（`PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1`）跑
`pytest tests/test_release_check_noai.py -q` ⇒ 1 failed：

```text
tests/test_release_check_noai.py:346: in test_every_reason_code_the_gate_can_return_has_a_translation
E   AssertionError: 门会发出的理由码没有翻译：['audit_timestamps_not_monotonic']
```

### 根因

我为 `R6-R1d-3` 在 `scripts/noai_gate.py` 新加了
`REASON_AUDIT_TIMESTAMPS_ORDER = "audit_timestamps_not_monotonic"`，但没把它加进
`scripts/release_check.py` 的 `_APPROVAL_REASON_TEXT`（"门说的理由码 → 人读的一句话"的
单一来源）。那条测试是**双向交叉断言**（门的 `REASON_*` 取值集合 ⟺ 翻译表的键集合），
缺键与多键都会红 —— 这条断言正是为"改了门没改翻译"准备的，不是新缺陷。

### 修法

`scripts/release_check.py`（**禁改区 release-deploy**）的 `_APPROVAL_REASON_TEXT` 里补一条，
风格与既有条目一致（一句话说清"为什么不是 clean"，并点明这是审计者**自报**时间戳的次序问题、
门只判可解析/不在未来/次序非递减、不判内容真伪）；另留一段注释记下 `F1-FOUND-1` 的来历。
**没有**放宽/改动任何既有翻译，也**没有**动判据。

### 清单核对（不只补那一个字母串）

用同一条测试当判据做了双向核对（脚本读数）：

```text
门能发出的理由码共 12
  OK    approved / audit_evidence_unverifiable / audit_receipt_chain_unverifiable /
        audit_timestamp_unverifiable / hash_unavailable / insufficient_clean_audits /
        insufficient_independent_dimensions / insufficient_reviewers /
        ledger_self_approval / stale / unregistered
  MISS  audit_timestamps_not_monotonic        ← 唯一缺的那一个（已补）
表里多出来的（门发不出）：[]
```

⇒ `scripts/noai_gate.py` 里**没有别的**新理由码缺翻译；翻译表里也没有门已发不出的码。
（本批新加的其余输出字段 —— `audit_timestamps[].basis` / `.gate_checked`、
`info["distinct_dimension_count"]` —— 不在那张表的对账范围内，也没有别的判据约束它们；
它们的正控/负控见 §1 的 `-3` / `-6`。工具层的 `SELFTEST_CRITERIA` 一类是别的对账单，
本批没碰那些模块。）

### 指纹

| 文件 | 改前 sha256 | 改后 sha256 | 字节 | 行 |
|---|---|---|---|---|
| `scripts/release_check.py`（禁改区 release-deploy） | `1dba8c37` | `3bdf4510` | 65345 → 66205 | 1169 → 1179 |

备份（改前逐字节）：`temp/batchF1FOUND1-release_check.py.bak` = `1dba8c37…`
（= 改前工作区字节，与 `temp/zone-head-backups.tsv` 里那一行的 `current_sha256` 逐字相同）。
人审清单按父代理指示不手改 TSV（由 `temp/_zone_head_backup.py` 重跑覆盖）。

### 验证读数（两条）

```text
① pytest tests/test_release_check_noai.py -q   （带 PYTHONIOENCODING=utf-8 / PYTHONUTF8=1）
   ⇒ 24 passed in 3.64s   （改前：1 failed）

② pytest tests/test_noai_gate.py tests/test_noai_gate_audit_channel.py \
        tests/test_noai_gate_record_audit_cli.py tests/test_noai_gate_umbrella_prefix.py -q
   ⇒ 159 passed（与 §2.2 同，未受影响）

   五个文件合跑：183 passed in 26.12s      （原始输出 temp/f1-pytest-all.txt）
```

lint（`python scripts/lint_rules.py`）：**`error 0 / warning 0 / info 20`** —— 补修之后全树也干净了
（原始输出 `temp/f1-lint-after.txt`；此前唯一那条 `error 1` 在 F5 的
`tests/test_r5_orchestration_cost.py`，此刻已由那一批自己收掉）。

### 边界（如实记）

- 我**没有**动 `tests/test_role_specs_complete.py`，也**没有**去处理"不带那两个环境变量时
  多出的 4 条乱码断言失败"——父代理已登记那是环境依赖的既有测试脆弱性，不在本批范围。
- 这一条不改任何判据，`scripts/noai_gate.py` 的字节在补修前后**完全未变**
  （仍 `eca8f582…`）⇒ §1 的 7 条正控/负控读数全部仍然有效。
- 教训（记进本报告，供下一批看）：我改 `noai_gate.py` 之后只跑了自己清单里的 4 个测试文件，
  没跑"别人的文件里那条守着 `noai_gate` 的交叉断言"。下一批改门的 `REASON_*` / 输出字段时，
  至少要 `grep -l "noai_gate" tests/*.py` 把守着这份契约的测试一起跑。

---

## F1-R7 / R7-R6-1：R006 退休声明承诺的方向在 R010 里补回来（禁改区收尾）

### 复现（先自己量，再看 findings）

| 读数 | 人造树（声明 `external='none'` + handler 链里 `P.http_get_json`） |
|---|---|
| 改前 R010（改造前那一份实现，`temp/batchF1R7-lint_rules.py.bak`） | **0 条** error/warning（`R6` 的那条读数） |
| 改前 R006（同一棵人造树；今天已退休 ⇒ `[]`） | 改前那一版的 R006 在这棵树上报 **1 条 info**（`temp/lint_out.txt` 里留着它在**真实树**上的历史读数：6 个文件各 1 条 info，含 `agent_c.py` 的「4 处网络/子进程/模型调用」） |
| 改后 R010（当前字节） | **1 条 warning**：`demo.fetch 声明 external='none'（即'我对外什么都不做'），而它的 handler 链里出现了网络调用的标记（['provider 层的 HTTP 入口…']）` |

**结论：那个方向在今天的实现里结构上做得到** —— R006 留下的那张
`_R010_NETWORK_MARKERS` 与逐工具 handler 链解析都还在，缺的只是"声明 `none` 而链里联网"
这一档。所以走父代理给的第一条路（补回去），不是"承认缺口"。

### 修法（`scripts/lint_rules.py` 禁改区）

- `rule_R010_external_axis_mismatch` 新增子规则 **R010-c**：`external == "none"` 且
  handler 链里可达网络标记 ⇒ **warning**（不是 error：判据是字面标记可达，而那张标记表里
  `search`/`download` 按末段相等匹配 ⇒ 真实树上会命中 `re.search`/`rx.search`；假阳性一多，
  error 会把门常驻点亮然后被忽略，P15）；
- 新增 `_R010_NETWORK_FALSE_POSITIVES`（"标记命中了、但那个调用不是网络"的登记表）+ 三条
  可见性 info：这一档核对了 N 条声明 / 登记为假阳性的 M 条 / 还剩多少条声明 `none` 而
  **没有任何网络标记可达**（反真空：这个数字变成 0 说明扫描器没读到声明）；
- **不许放宽既有规则**：R010-a（exec）与 R010-b（egress）的判据、标记表、`_R010_ALLOWED_SITES`
  一个字符都没动；新条件刻意用 `== "none"` 而不是 `!= "egress"`（后者会把如实的 `exec`
  也报进来，且 `subprocess` 同时是网络标记表成员 ⇒ 每个 exec 工具被重复报两次）；
- `RETIRED_RULES["R006"]`、`rule_R006` 与 `rule_R010` 的 docstring 改成承认"两个方向都在
  R010 里"（此前那句"判据移入 R010"是假承诺）。

### 正控 / 负控（成对，原始读数 `temp/f1r7-pair.txt`）

| 树 | 样本 | 正控（必须命中） | 负控（必须不命中） |
|---|---|---|---|
| A | 声明 `none` + 链里 `P.http_get_json` | 改后 **1 条 warning、点名 `demo.fetch`**；改前 **0 条** | — |
| B | 声明 `egress` + 确实联网 | — | **0 条**（如是实的声明，走 R010-b 那一侧） |
| C | 声明 `none` + 链里只有本地处理 | — | **0 条** |

仓内判据：`tests/test_lint_rules.py` 新增 3 条正/负控
（`test_r010c_flags_a_none_declaration_that_reaches_a_network_call` /
`..._does_not_flag_a_none_declaration_without_any_network_call` /
`..._does_not_flag_an_egress_declaration_that_really_goes_out`）+
1 条假阳性表守活（`test_r010c_known_false_positives_are_reported_not_hidden`）。
另：`test_network_is_no_longer_recognised_as_a_legacy_declaration` 的合成树被拆成两块
（旧写法的 `sample.legacy` 用纯净 handler、另外补一个 `sample.notexec` 承担"起进程 ⇒ error"），
因为补进 R010-c 之后一个起进程的 handler 会同时命中"起进程"与"网络标记"（`subprocess` 本来就
在网络标记表里）—— 不拆的话那条用例锁的东西会被新那一档的文案顶替掉。判据一条都没放宽。

### 真实树读数（`temp/f1r7-lint-after.txt`）

```
[linter] error 0 / warning 0 / info 25
```

R010-c 在真实树上命中 **3 条**，三条都登记为字面假阳性（以 info 出现）：

| 工具 | 命中的标记 | 为什么不是缺陷 |
|---|---|---|
| `doc.build_document` | `search` | 命中的是 `re.search`（标准库正则，`import re` 在文件顶部） |
| `fs.search` | `search` | 命中的是 `rx.search`（`rx = re.compile(pattern)` 之后的匹配） |
| `verify.detect_verifier` | `subprocess` | R006 的口径把"网络/子进程/模型调用"三类共用一张表 ⇒ 只起进程、不出网 |

⇒ R010-c 在真实树上**今天不报任何 warning**（0 个真缺陷），但它**判得动**（人造树上 1 条
warning 可复现、可注入）。这一点如实写在报告里：它现在的价值是"方向接上了 + 报数诚实"，
不是"今天抓到了三个缺陷"。

### 文档同步（`DEVELOPMENT.md`，**该文件不属我** —— 只改了提到 R006/R010 的那几处）

按父代理"只改提到 R006/R010 的那一处句子"的指示，但核对时发现**同一件事在三个地方**
都只写了两个方向，只改 `:665` 会让 §4.3 第 3 行与 §6-P7 继续承诺"两个方向"：
（1）`:665` 第 13 项；（2）§4.3 第 3 项；（3）§6-P7 的"检查方式/落地"两栏。
三处都补成"三个方向"并点明 `R7-R6-1` 补的是哪一个。**只动这三处**，F8 正在改的另外几处数字
（`:74` / `:86` / `:95` / `:129` / `:153` 等）一个字节都没碰；我也把 `:665` 里那句
`info 20` 按当次实测更新为 `info 25` 并注明 `R7-R6-1` 的来历。

### 指纹

| 文件 | 改前 sha256 | 改后 sha256 |
|---|---|---|
| `scripts/lint_rules.py`（禁改区 auth-audit） | `c7a4b0e5` | `1a48dd63` |
| `tests/test_lint_rules.py`（不在我的原清单里 —— 见下） | `b8400581` | `04351581` |
| `DEVELOPMENT.md`（不属我） | `2df301be` | `206b8f5d` |

备份：`temp/batchF1R7-lint_rules.py.bak`（=`c7a4b0e5…`）、
`temp/batchF1R7-DEVELOPMENT.md.bak`（=`2df301be…`）。禁改区 TSV 按指示不手改。

**两处超出原清单的文件（如实登记，供父代理对账）**：① `tests/test_lint_rules.py`
（不在 FIX6-PLAN 第 1 节给我的清单里）—— `R7-R6-1` 的成对判据必须有名字，仓内惯例是落在
`tests/test_lint_rules.py`（R010 的既有四条正/负控都在那里）；② `DEVELOPMENT.md` 的第二、
三处（父代理只点名 `:665`，但同一句承诺在三处，只改一处会留下两处假话）。

### 验证读数

```text
pytest tests/test_lint_rules.py tests/test_lint_rules_r004_retired.py \
       tests/test_lint_rules_r006_retired.py tests/test_lint_rules_r011_dead_vocab.py \
       tests/test_lint_rules_r012_newline.py -q      ⇒ 86 passed
python scripts/lint_rules.py                          ⇒ error 0 / warning 0 / info 25
```

---

## F1-R7 / R7-R1d-1：报数口径只修了一半（`noai_gate.py`）

### 现象（`R1d` 的实测，我复核过）

`R6-R1d-5` 的第 2 层过滤（只保留落在 `_identifiers_of(target_text)` 上的 token）需要一个
**非空** `target_text`，而报数发生在**读被审对象之前** ⇒ 那一处只能用 docstring 说的"自指弱口径"
（`reuse_across`）；而 5 个调用点传的 `reuse_across` **都含本条自己的 `scope`** ⇒
`toks & reused == toks`，退路是**恒等不过滤**。后果：**未批准**的那些条目（操作者真正要去
处理的那一档）的 `observation_surfaces` 仍会被与观察对象无关的自由文本撑开。

### 修法（按 `R1d` 实测过的那条；两处一起）

1. **读被审对象提前**：抽 `_read_target_text(path, repo)`，在 `evaluate_approval` 里
   `distinct_dimensions` 之后读一次，`observation_surfaces` / `independent_observation_surfaces`
   与后面的判据**共用同一个** `target_text`（机审那一支里原先自己读的那段删掉，注释注明同构）；
2. **退路剔掉自己的 `scope`**：`_observation_tokens` 新增 `drop_self_scope`，5 个调用点全部
   传 `True`（含 `record_audit` 的 `info` 那一处）。

判定顺序、理由码、写侧一律没动；`dimension_independence_problem` 自己的调用点
（`_disjoint_face_count(...)`）走的是内部那一遍（它已经按 `drop_self_scope=True` 算 key）。

### 正控 / 负控（`temp/f1r7-r1d1-clean.py` / `.txt`）

- **对照 A（只把"读"退回改前形态，但保留分支自己的读 = 真正的改前形态）**：
  **10 个场景的 `approval_status`/`approval_reason` 逐字相同（10/10）**，而报数在
  **5 个场景**上变干净：

  | 场景 | 当前报数 | 撤早读后 |
  |---|---|---|
  | 03 unapproved 2×2 带名字 token | `['alpha','beta']` | `['alpha r7-name-1','beta r7-name-2']` |
  | 04 unapproved 2×1 | `['alpha']` | `['alpha r7-name-1']` |
  | 06 unapproved scope 全是假符号 | `[]` | `['import int return']` |
  | 02 approved 3×1 带名字 token | `['alpha','beta','gamma']` | `['alpha r7-n0','beta r7-n1','gamma r7-n2']` |
  | 10 approved 人审通路 | `['alpha']` | `['alpha r7-n1']` |

  （对照 A 的副本 sha256：`7320bd1439a578bf…` ≠ 当前 `f05a43b01088936c…`，锚点各命中 1 次。）
- **对照 B（保留早读、只撤"剔自己"）**：函数级读数翻转 ——
  `_observation_key('src/a.py alpha R7-NAME-1', '', reuse_across=[两条 scope])`：
  当前 `''`、副本 `'alpha r7-name-1'`；只把本条自己作为 `reuse_across` 时当前 `''`、
  副本 `'alpha r7-name-1'`（副本 sha256 `20728c5a67524d48…`）。
  **如实记它的边界**：退路那一支只在"被审对象读不到"时才被走到（对象可读时两处都用
  `target_text` 过滤），所以它没有端到端的差异读数 —— 强读数在函数级。
- 仓内判据：`tests/test_noai_gate.py::test_r1c_f1_dimensions_must_lie_on_pairwise_disjoint_surfaces`
  里那条 `_disjoint_face_count(counted)` 改成显式传 `_REAL_TARGET_SRC`（理由见该处注释：
  不传文本走的是"读不到"那一支的退路，与判定口径不是同一个集合；读数是 3）。

### 边界（如实记）

`R1d` 报的那句"未批准分支仍不过滤"在修完之后只剩一种残留：**被审对象读不到**时
（对象被删/权限/编码），报数回到弱口径 —— 那时报数是诚实的（对象读不到，判据 3 会报
"没查成"），三条实现（当前 / 撤早读 / 撤剔自己）在那条路径上给出同一个报数，
读数在 `temp/f1r7-r1d1-clean.txt` 的"端到端"一节。

---

## F1-R7 / R7-R1d-2：时间戳次序判据的接线验收缺口（补测试）

### 现象（`R1d` 的实测，我复核过）

`R6-R1d-3` 的判定侧接线（`if order_problem: return ...`）**没有任何测试守着**：
把整棵树复制到 temp、只把那一行改成 `if False:`，四个冻结测试文件跑出 **159 passed**。
写入侧那一半（`record_audit` 拒收更早的 `at`）同样没有测试。

### 修法：新增 `tests/test_noai_gate_timestamp_order.py`（3 条）

1. `test_descending_audit_timestamps_are_rejected`：判定侧 —— 三条 `at` 递增 ⇒ `approved`；
   三条 `at` 倒挂（03:00→02:00→01:00）⇒ `unapproved` / `REASON_AUDIT_TIMESTAMPS_ORDER`、
   detail 含"倒挂"；判据本体两个方向各一条断言（函数对而接线没接的情形由第 3 条守）；
2. `test_record_audit_refuses_to_append_an_earlier_timestamp`：写入侧 —— `now` 比台账里
   最后一条更晚 ⇒ 写得进去；更早 ⇒ `LedgerError`（含"倒挂"）；
3. `test_injection_negative_control_severing_the_wiring_turns_this_file_red`：
   **注入负控** —— 用已收集的文件清单把整棵树复制到 `tmp_path`（清单法：漏掉一整个目录时
   子进程 pytest 会"收集不到测试"而非 0 退出 ⇒ 假绿），只把判定侧那两行改成 `if False:`，
   断言"锚点在 `noai_gate.py` 里恰好命中 1 次"、打印副本 sha256、再用**子进程**跑本文件 ⇒
   必须非 0 且失败的就是第 1 条（实测：`FAILED ...::test_descending_audit_timestamps_are_rejected`）。

### 检测力（这条测试真的能拿到那一处接线）

```text
当前字节：      pytest tests/test_noai_gate_timestamp_order.py -q ⇒ 3 passed
注入副本：      同一文件（子树副本里跑）⇒ 1 failed（test_descending_audit_timestamps_are_rejected）
                副本 sha256 与当前不同、锚点恰好 1 次（都在断言里）
```

⇒ 这就是 `R7-R1d-2` 要的那一条：**把接线撤掉，测试必须红**（改前是 159 passed）。

### 指纹

| 文件 | 改前 sha256 | 改后 sha256 |
|---|---|---|
| `scripts/noai_gate.py`（本节的 `R7-R1d-1` 改动） | `eca8f582`（F1-FOUND-1 之后） | `f05a43b0` |
| `tests/test_noai_gate.py` | `88a8685f` | `0e69e554` |
| `tests/test_noai_gate_timestamp_order.py`（新建） | — | `e36dbf07` |

### 验证读数

```text
pytest tests/test_noai_gate.py tests/test_noai_gate_audit_channel.py \
       tests/test_noai_gate_record_audit_cli.py tests/test_noai_gate_umbrella_prefix.py \
       tests/test_noai_gate_timestamp_order.py tests/test_release_check_noai.py -q
⇒ 186 passed in 37.70s          （原始输出 temp/f1r7-pytest.txt）

python scripts/lint_rules.py    ⇒ error 0 / warning 0 / info 25
```

（R009 的两处命中由我自己当场清掉：`tests/test_noai_gate_timestamp_order.py` 的
docstring 与 `tests/test_noai_gate.py:2056` 的注释里的 Markdown 强调标记。）

---

## F1-R10：把三条"签字前契约"的测试改成签字后的契约

### 触发者不是代码，是人的签字

所有者 2026-09-27 完成 18 个禁改区文件的逐行走查，并把签字落进 `.noai-approvals.json`
（17 条各 2 名不同 reviewer；台账自身 `reviewers` 仍为 0，且门对它恒判 `ledger_self_approval`）。
**这三条变红不是 `F10` 或 `F9` 造成的**：同一批字节、同一个判据，改的只有台账（人的签名记录）。
世界变了 ⇒ 三条编码了"签字前契约"的用例跟着失效。

### 三条失败断言的原始输出（逐字，见 `temp/fix6_f10_before.txt`）

```text
>       assert G.LEDGER_NAME not in paths, "台账不该给自己登记（它永远 unapproved，登记只会制造噪音）"
E       AssertionError: 台账不该给自己登记（它永远 unapproved，登记只会制造噪音）
E       assert '.noai-approvals.json' not in {'.noai-approvals.json', '.noai-paths', 'AGENTS.md', ...}
tests\test_noai_gate.py:1407: AssertionError

>       assert _verdict(["src/agentflow/dedup.py"]) == "fail"
E       AssertionError: assert 'pass' == 'fail'
tests\test_release_check_noai.py:44: AssertionError

>       assert RC.main([*_ONLY_NOAI, "--changed-file", str(ch)]) == 1
E       AssertionError: assert 2 == 1
tests\test_release_check_noai.py:85: AssertionError
（同一次运行里 noai 那一项自己打印的是：[PASS] …1 条通路 = **人审**，各 ≥2 名不同 reviewer 完成逐行走查）
```

### 为什么失效

1. `test_real_ledger_is_readable_and_registers_the_round` 断言的两件"签字前形态"
   （台账不给自己登记、每条 `authored_basis == "inferred"`）在签字后同时为假：
   17 条变 `attested`，台账也把自己登记了进去。第一条先炸，第二条（`== inferred`）
   就在它后面几行，同样已失效。
2. `test_a_zone_change_is_fail` 断言"命中禁改区 ⇒ fail"。签字后 `dedup.py` 拿到
   2 名不同 reviewer 且 `sha256` 与盘上一致 ⇒ 判 `pass` ⇒ `assert 'pass' == 'fail'`。
3. `test_cli_changed_file_with_a_zone_path_is_fail` 断言退出码 1；同一原因下 noai 项判
   `pass`，总判定只因 `--skip` 关掉七项记 `unknown` ⇒ 2。

### 新契约（逐字）

```text
未批准（unregistered / stale / insufficient_reviewers）⇒ fail/未获批准；
有 2 名不同 reviewer 且 sha256 与盘上这一版一致 ⇒ 不判 fail（pass，通路 = 人审）。
```

判定在 `noai_gate.evaluate_approval`（禁改区，本批一个字节都没动）。测试侧只改：

| 用例（全部落在允许改的两个测试文件里） | 新契约 |
|---|---|
| `test_a_zone_change_with_two_reviewers_is_a_human_pass`（替换 `test_a_zone_change_is_fail`） | 当前字节 + 真实台账 ⇒ `pass`、`pass_path == "human"`、`approval_reason == approved`、`distinct_reviewers >= 2`、`current_sha256 == entry_sha256` |
| `test_negative_control_a_zone_change_without_signatures_is_fail`（新） | 副本台账把该条 `reviewers` 清空 ⇒ `fail`、退出码 1、`insufficient_reviewers` |
| `test_negative_control_a_zone_change_whose_hash_drifted_is_fail`（新） | 副本台账把该条 `sha256` 改一位 ⇒ `fail`、退出码 1、`stale` |
| `test_cli_changed_file_with_an_approved_zone_path_is_a_human_pass`（替换 `test_cli_changed_file_with_a_zone_path_is_fail`） | CLI：已批准禁改区路径 ⇒ 该项 `pass`/`human`，总判定 `unknown`(2)（七项被 `--skip`） |
| `test_negative_control_cli_unapprovable_zone_path_is_still_fail`（新） | CLI：改动集含 `.noai-approvals.json`（自指 ⇒ 恒 unapproved）⇒ 退出码 1 |
| `test_real_ledger_is_readable_and_registers_the_round`（重写，只改判据） | 结构性不变量：版本号、`generated_at` 可解析、条数 ≥ 13、覆盖那 13 个路径、每条必需键齐、`sha256` 是 64 位小写 hex、`authored`/`authored_basis` 取自受控取值、`distinct_reviewers <= len(reviewers)`。**不断言签字状态** |
| `test_real_ledger_registers_itself_but_can_never_approve_itself`（新） | 真实台账登记了自己，而门对它恒判 `unapproved` / `ledger_self_approval`（判据第 1 条，排在 hash 与人数之前 ⇒ 不会因人签字而失效） |

未批准那一档的机器判据没有变软，也没有被删：`tests/test_noai_gate.py` 里
`test_approvals_unregistered_is_unapproved_with_own_reason`、`..._stale_hash_...`、
`..._one_reviewer_is_not_enough`、`test_ledger_never_approves_itself` 原样保留（一字未改）。

### 正控 / 负控读数（`temp/fix6_f10_probe.py` ⇒ `temp/fix6_f10_probe.txt`）

```text
真实台账 D:\Incubator\agentflow\.noai-approvals.json  sha256 = 3122d94864e7a352cb50c083f00b9d71290f9dcd04025c8292ca8e9a4d43c7c5
src/agentflow/dedup.py 盘上 sha256 = 7a406dfd31b4b9da094dbe44382079f6ce103cf9caf874ff413ce55dbee31205

正控  当前字节 + 真实台账      ⇒ verdict=pass  gate_exit=0  pass_path=human
                              approval_status=approved  reason=approved  distinct_reviewers=2
                              entry_sha12=7a406dfd31b4  cur_sha12=7a406dfd31b4   （两者一致）

负控① 副本把该条 reviewers 清空 ⇒ verdict=fail  gate_exit=1  reason=insufficient_reviewers
      副本 <tmp>\neg1\.noai-approvals.json  sha256 = 3fed72c6621df918bfd0265aae892166555b68241627df95ad3e11aff0092155
      注入生效：reviewers 2 条 -> 0 条（断言里带副本路径与两处 sha256）

负控② 副本把该条 sha256 改一位 ⇒ verdict=fail  gate_exit=1  reason=stale  distinct_reviewers=2（签名仍在，仍不放行）
      副本 <tmp>\neg2\.noai-approvals.json  sha256 = 15ce8a1e1161a418102f93f708f229b951e9e71759a6cd77ddd7742b712ad346
      注入生效：7a406dfd… -> 0a406dfd…；盘上那一版仍是 7a406dfd…

负控③（CLI 面）改动集含 .noai-approvals.json ⇒ release_check 退出码 = 1
              （门打印 .noai-approvals.json：台账不能批准自己（本文件就是台账本体）
                （台账判定 unapproved/ledger_self_approval））
```

**有没有"构造不出负控"的条目**：没有。5 条新判据全部配了负控；其中两条台账负控打在
`tmp_path` 下的真实台账副本上（先断言"改前 ≠ 改后"且"副本 sha256 ≠ 真实台账 sha256"，
证明注入生效），CLI 那条用"自指"这一档 —— 它恒为 unapproved，不会因为将来有人签字而失效。
唯一**刻意没有**做负控的形式是"某条 `reviewers` 为空 ⇒ fail"以真实台账为对象：那条判据本身
已经由上面的人造世界用例与两条副本负控覆盖，而拿真实台账当对象会在人签字后变成假红
（正是本次要修掉的那类脆弱写法）。

### 指纹（改前 / 改后 sha256）

| 文件 | 改前 sha256 | 改后 sha256 | 说明 |
|---|---|---|---|
| `tests/test_noai_gate.py` | `0e69e554fc009ad6fce6c1e55a92672a787cd980093de673fc75686ef2370da3` | `58ddc9b3da154589caca617ce9ab2166d5e67446a46a57dc541d797c942b83d3` | 97 → 98 条 `test_*` |
| `tests/test_release_check_noai.py` | `8206b3d01e3db24a15fbc8845abe737fc32d8a6e8d1709e29503abafc76c1e1a` | `bfa2e649355d8e2a20019b8a2fd4ce22e094ad91cb9dbfc4c23570b02327f95d` | 24 → 27 条 `test_*` |
| `.noai-approvals.json` | — | `3122d94864e7a352cb50c083f00b9d71290f9dcd04025c8292ca8e9a4d43c7c5` | **本批未动**（人的签字记录） |

未动禁改区文件的机器证据（mtime 与本批开工前逐字相同）：

```text
.noai-approvals.json        2026/9/27 8:58:42   23263 字节   （本批开工前就是这一版）
.noai-paths                 2026/9/26 22:17:26  11882 字节
AGENTS.md                   2026/9/26 22:17:26  12949 字节
tests/test_noai_gate.py     2026/9/27 9:25:25  112938 字节   （本批改动的两个文件之一）
tests/test_release_check_noai.py 2026/9/27 9:25:10 31252 字节（本批改动的另一个）
```

### `test_*` 的 AST 变化清单

`tests/test_noai_gate.py`（模块级函数 114 → 115，`test_*` 97 → 98）

- 删：无。
- 改：`test_real_ledger_is_readable_and_registers_the_round` —— 名字与签名不变，函数体整体重写
  （去掉 `G.LEDGER_NAME not in paths` 与 `authored_basis == "inferred"` 两条断言，
  换成结构性不变量断言）。
- 增：`test_real_ledger_registers_itself_but_can_never_approve_itself`。
- 增（模块级常量）：`_ROUND_COVERED`、`_REQUIRED_ENTRY_KEYS`。其余 96 条 `test_*` 与 17 个
  既有 helper 一字未动。

`tests/test_release_check_noai.py`（模块级函数 29 → 35，`test_*` 24 → 27）

- 删：`test_a_zone_change_is_fail`、`test_cli_changed_file_with_a_zone_path_is_fail`。
- 增：`test_a_zone_change_with_two_reviewers_is_a_human_pass`、
  `test_negative_control_a_zone_change_without_signatures_is_fail`、
  `test_negative_control_a_zone_change_whose_hash_drifted_is_fail`、
  `test_cli_changed_file_with_an_approved_zone_path_is_a_human_pass`、
  `test_negative_control_cli_unapprovable_zone_path_is_still_fail`。
- 增（helper）：`_zone_item`、`_ledger_copy_with`、`_approval_of`。
- 增（模块级）：`_ROOT`（`sys.path` 注入）、`import sys`、`import scripts.noai_gate as G`、
  `_REAL_ROOT`、`_REAL_LEDGER`、`_APPROVED_ZONE_PATH`、`_UNAPPROVABLE_ZONE_PATH`。
- 未动：`_verdict`（仍有 3 条用例用它）与其余 22 条 `test_*`。

### 验证读数

```text
python -m pytest tests/test_noai_gate.py tests/test_release_check_noai.py tests/test_release_check_items.py -q
⇒ 168 passed in 30.12s        （改前：3 failed, 161 passed）

python -m pytest tests/test_noai_gate_audit_channel.py tests/test_noai_gate_umbrella_prefix.py -q
⇒ 38 passed in 12.32s
python -m pytest tests/test_noai_gate_record_audit_cli.py tests/test_noai_gate_timestamp_order.py -q
⇒ 9 passed in 5.71s

python scripts/lint_rules.py
⇒ [linter] error 0 / warning 0 / info 25      （R009 对我改的两个文件命中 0；
   我加进注释/docstring 的 Markdown 强调标记由我自己当场清掉后复跑）
```

未跑全量（按批次边界）。未改 `.noai-approvals.json`、未改任何禁改区实现文件。

