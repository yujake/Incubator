# batchR1c 证据（v2，含口径裁决①②）—— 独立重审 R1b 的 7 条 finding 的处置

**批次**：R1c　**落点**：`agentflow/scripts/noai_gate.py`（禁改区 FC-27 auth-audit）+ `agentflow/tests/test_noai_gate.py`
**改前备份**：`temp/batchR1c-noai_gate.py.bak`（= 审计者冻结的那一版，逐字节相同）
**v2 变更**：按口径裁决①（**正控不是地基** ⇒ 另立新正控 + 落"观察面两两不相交"的更强判据）
与裁决②（**恢复长度下限**）收口；v1 的两处取舍作废，详见 §4。

## 0. 改前 / 改后指纹

| 文件 | 改前 sha256 | 改后 sha256 | 行数 |
|---|---|---|---|
| `scripts/noai_gate.py` | `d8f625ca2d289cd3eaf98a804ae743bb3d5694a784833804abe2c5623957b71f` | `730f51e88546e1feea7d79f2a45be072d375fe9c049c1bf2348e70de0ffcf7f8` | 3285 → 3936 |
| `tests/test_noai_gate.py` | `abe5e4643fd628eb2b77091f498ac9a778f2955caf7a547029946e447bf03d46` | `61321eaba9857a43076515376be01c7231dc9d772c88c6668213542c4fc9d88f` | 1419 → 2144 |

改前 sha256 与 `REAUDIT5-R1b.json` 的 `files_sha256_before["scripts/noai_gate.py"]` **逐字相同**（`d8f625ca…`）⇒ 备份确实是审计者审的那一版。

**未动的文件**：`.noai-approvals.json` = `8175efc213d9b0eeef3a4180c08ae0527025c64ff9e40b2ceed77071b6adcefe`（改前 = 改后）；`.noai-paths` / `AGENTS.md` / `src/` / `docs/` / `README.md` / `DEVELOPMENT.md` 一个字节都没改。**没有**重跑 `--baseline`。

## 1. 四道硬约束读数（原始输出）

### 1.1 `pytest tests/test_noai_gate.py -q`

```
115 passed in 15.20s
```

（改前 104 passed；+11 是本批新增用例 —— 7 条 finding + 裁决① 的观察面判据，见 §5。）

### 1.2 `python scripts/noai_gate.py --git --since HEAD`

```
GATE EXIT=1
[requires_human] required_approvals=2
requires_human：18 条改动落在 **FC-27 禁 AI 区**（auth-audit、eval-criteria、provenance-dedup、
prover-bridge、release-deploy、schema-migration、solver-core）⇒ 必须由人编写或人逐行走查，
并需要 2 名 reviewer 批准。
```

### 1.3 `.noai-approvals.json`

```
真实台账：条目数 = 16；reviewers 元素总数 = 0；audits 总数 = 0
台账 sha256 = 8175efc213d9b0eeef3a4180c08ae0527025c64ff9e40b2ceed77071b6adcefe
```

### 1.4 审计者的 9 个探针（本批之后）

| 探针 | 读数 |
|---|---|
| `reaudit5-R1b-pos.py` | **正控 FAIL（预期）/ 负控 PASS**。它的正控现在判 `unapproved / insufficient_independent_dimensions`（clean_audits=3、3×3，但观察面只有 1 个）—— 裁决① 判定它**本身是弱场景**，所以这个 FAIL 是**预期读数**，不是回归。探针原样保留（R1b 的历史证据）。 |
| `reaudit5-R1b-solo.py` | `A=unapproved（aud=3）`（对照 A 也共用一个观察面 ⇒ 现在被挡）、`B=unapproved（aud=2 dim=4）⇒ B 被挡` |
| `reaudit5-R1b-atk4.py` | `exit=1 requires_human unapproved/insufficient_independent_dimensions`，`distinct_auditors=2`（改前 3） |
| `reaudit5-R1b-atk5.py` | `distinct_reviewers=1`（改前 3）、`exit=1 unapproved` |
| `reaudit5-R1b-attack.py` | 汇总表 25 行**全部非 approved**（改前有 approved 行，例如 `n5_atk`）；`n5_atk` 改前 approved → 现 `insufficient_independent_dimensions` |
| `reaudit5-R1b-attack2.py` | N6 段在**写入侧**抛 `LedgerError：时间戳不合格 —— at(2099) 落在未来`（改前照收）⇒ 中途崩溃；判定侧读数见 `temp/batchR1c-self-at.txt` |
| `reaudit5-R1b-ledger.py` | `reviewers_total 求和 = 0`；`判据：通过（16 条全 0）` |
| `reaudit5-R1b-constraints.py` / `-emoji.py` | 与改前一致（`--check-consistency` 0 / 命中读数不变 / emoji 无输出） |

## 2. 口径裁决①：正控另立 + 更强判据

### 2.1 新正控 `temp/batchR1c-pos2.py`（`python temp/batchR1c-pos2.py`）

三条审计的 `scope` **分别指向目标里不同的标识符**（`alpha` / `beta` / `gamma`），
证据各自记录**不同的观察**（不是同一句复制三遍）：

```
   $ --record-audit pos2-A1/axes   scope='target.py alpha'   exit=0
   $ --record-audit pos2-A2/roles  scope='target.py beta'    exit=0
   $ --record-audit pos2-A3/errors scope='target.py gamma'   exit=0
   $ --check-approvals --json           exit=0
       verdict                = clean
       status                 = approved
       reason                 = approved
       clean_audits           = 3
       distinct_auditors      = 3
       distinct_dimensions    = ['axes', 'roles', 'errors']
       observation_surfaces   = ['alpha', 'beta', 'gamma']
       audit_timestamps       = ['2026-09-27T01:12:53+08:00', … ×3]
       evidence_problems      = []
   >>> 新正控断言（exit=0 / clean / approved / clean_audits=3 / 3×3 / 观察面=3） ⇒ 通过
```

探针自校（同脚本 B 段）：把三条的 `scope` 全改成 `target.py alpha` ⇒
`exit=1 unapproved/insufficient_independent_dimensions`、`观察面 1 个` ⇒
`自校断言（同观察面 ⇒ 非 approved） ⇒ 通过`。**总结：新正控 PASS / 自校 PASS**（`temp/batchR1c-pos2.txt`）。

### 2.2 更强判据的实现

`dimension_independence_problem` 现在有四条（写侧 `_run_record_audit` 共用）：

- **判据 0** 一名审计者不能独占门槛（`require=3` ⇒ 每人至多 `ceil(3/2)=2` 个计入维度）；
- **判据 1** 同一名审计者的多条记录不许共用同一个观察面；
- **判据 2（新，裁决①）**把每个 `scope` 折成一个符号**集合**（观察面），用
  `_disjoint_face_count()` 数出**最多能挑出多少个两两不相交的观察面**（贪心按集合大小升序，
  确定性排序键），要求它 **≥ 计数的维度数**。它比"数不同的观察面字符串"强：
  `alpha beta` 与 `alpha` 是两个不同字符串、却是两个**相交**的集合（后者是前者的子集）
  ⇒ 算**一次**观察。
- **判据 3** `scope` 的某个 token 必须是目标里真实存在的标识符。

`--check-approvals --json` 新增两个字段：`observation_surfaces`（观察面字符串列表）与
`independent_observation_surfaces`（**两两不相交的个数**）。

### 2.3 判据 2 的负控（`python temp/batchR1c-neg-rule2.py`）

攻击 = 裁决① 点名的**分摊形态**：4 个维度、2 名审计者，观察面
`{alpha} {beta} {gamma} {alpha beta}`（每人内部不重复 ⇒ 判据 1 看不见；相交 ⇒ 判据 2 挡）。

```
0. 指纹：gate sha256 = 409c5784cd01… / 行数 = 3935
A. [正控] exit=0 clean approved/approved clean=4 aud=2 dim=4
          面=['alpha','beta','delta','gamma'] 两两不相交=4
B. [攻击] exit=1 requires_human unapproved/insufficient_independent_dimensions clean=4 aud=2 dim=4
          面=['alpha','alpha beta','beta','gamma'] 两两不相交=3
   detail = …但它们的 `scope` 只给出 4 个观察面、其中**两两不相交的只有 3 个**…不放行…
   判据 2 的直接读数：两两不相交的观察面 3 个 < 维度 4 个
C. 负控指纹：dimension_independence_problem 已替换为**只含判据 0/1**的改前形态
   [负控] exit=0 clean approved/approved clean=4 aud=2 dim=4
总结：正控 PASS / 攻击被挡 PASS / 负控（撤掉判据 2 ⇒ 攻击变绿）PASS
```

⇒ **分辨力就在判据 2 上**：撤掉它，同一条台账从 `unapproved` 翻到 `approved`。
（该探针的指纹行有一处字符串探针失效，见 §6 第 8 条；判据确实在源码里，由
`temp/batchR1c-pos2.py` 的指纹与 pytest 用例交叉证实。）

### 2.4 `reaudit5-R1b-pos.py` 被哪个新正控取代、为什么

**取代者**：`temp/batchR1c-pos2.py`。
**一句话**：那条探针的三条审计只有一个观察面（3 名审计者共用同一句
`--audit-scope 'target.py VALUE bump'`），它看起来像三次独立观察，其实是同一个面被数了三次
—— 正是 `R5-R1b-1` 说的形态。它原样保留为 R1b 的历史证据，但不再是本批的地基。

## 3. 口径裁决②：恢复长度下限

`negative_control_problem` 现在是**四条都要满足**（门只加不减）：
① 长度 ≥ `NEGCTL_MIN_CHARS=40`；② 出现"怎么比"标记；③ 出现"比出来什么"标记；
④ 不是重复填充。v1 移除 ① 的理由（迁就 `tests/test_noai_gate_audit_channel.py` 的 13 字符夹具）
**被判不成立**，已恢复。

整族逐形态核对（`temp/batchR1c-probe.txt` 的 R5-R1b-6 段）：

```
正控·够长且合规的本批负控        problem=(通过)
长度不足·13 字符（预期被拒）      problem=负控太短（13 < 40 字符）…
空话·'改前'+'啊'*60            problem=负控里没有写出**比出来看到了什么**…
空话·'negative '+'x'*60       problem=（同上）
空话·占位 20 次                 problem=（同上）
空话·n/a + 填充                 problem=（同上）
负控指纹：negative_control_problem 已换成『长度 ≥ 40 + 标记词』的改前形态
改前读数 = ['通过', '太短', '通过', '通过', '通过', '通过']
           ↑正控   ↑13字符  ↑四种空话在改前**全部通过**
```

| 形态 | 改前（长度+标记词） | 改后（四条） |
|---|---|---|
| `''` / `'n/a'` / `'  '` | 拒 | 拒 |
| `'改前' + '啊'*60` | **通过** | **拒** |
| `'negative ' + 'x'*60` | **通过** | **拒** |
| `'负控：（此栏无内容）' + '占位'*20 + ' 改前'` | **通过** | **拒** |
| `'n/a ' + ' '*40 + ' HEAD ' + ' '*10` | **通过** | **拒** |
| `'改前' + '占位'*30` | **通过** | **拒** |
| `'改前会报出 network'`（13 字符） | 拒（太短） | **拒（太短 —— 预期）** |
| `_R1C_NC`（够长且写清怎么比/比出来什么） | 通过 | 通过 |

⇒ **改前能过、现在过不了的形态有 5 种；"改前拒、改后过"的形态 0 种** —— 整族是变严的，
长度门回来了，没有任何一处放宽。夹具那句 13 字符负控现在**预期被拒**（专门修那个文件的
批次会把夹具连同样例一起改成合规写法）。

## 4. v1 的两处取舍（已按裁决作废）

| v1 的做法 | 裁决 | v2 的做法 |
|---|---|---|
| 为保住 `reaudit5-R1b-pos.py` 只落判据 0+1，把"观察面数 ≥ 维度数"登记为残余 | ① 正控不是地基 ⇒ 必须落更强判据 | 判据 2 落地（**两两不相交**的计数 ≥ 维度数）；另立 `temp/batchR1c-pos2.py` 作新正控 |
| 移除 `≥40` 长度门，迁就 13 字符夹具 | ② 理由不成立 ⇒ 恢复 | 长度门恢复；13 字符夹具**预期被拒** |

## 5. 新增用例（`tests/test_noai_gate.py`，每条 finding 正控 + 注入负控）

| 用例 | 正控 | 注入负控 |
|---|---|---|
| `test_r1c_f2_distinct_reviewers_normalizes_name_collation` | 4 种同形写法 ⇒ 1 名 | 换回原始字符串比较 ⇒ 3 名 ⇒ approved |
| `test_r1c_f3_normalize_subject_folds_combining_marks` | U+FE0F/FE0E/20E3/0301 归一为 1 | 换回"只去 Cf" ⇒ 5 种；换回 H-1a 之前 ⇒ 全角算另一名 |
| `test_r1c_f3_reviewer_writer_requires_a_readable_name` | 中文姓名写得进去 | 零宽/纯标点姓名 ⇒ `LedgerError` |
| `test_r1c_f1_same_auditor_cannot_supply_all_dimensions` | 3 名审计者各 1 维度、各有独立面 ⇒ approved | 撤掉判据 ⇒ 攻击 approved（clean=4 aud=2 dim=4） |
| `test_r1c_f1_same_auditor_cannot_reuse_one_observation_surface` | 两两不相交的 scope ⇒ approved | 撤掉判据 ⇒ 攻击 approved |
| `test_r1c_f1_dimensions_must_lie_on_pairwise_disjoint_surfaces`（裁决①） | 4 条各占不相交落点 ⇒ approved、`independent_observation_surfaces == 4` | 撤掉判据 2（只留 0/1）⇒ 分摊攻击 approved |
| `test_r1c_f4_independence_must_be_a_statement` | 真声明 ⇒ 计入 | `x` ⇒ 判据本体非空 + 掉出 clean_audits + 写侧拒写 |
| `test_r1c_f5_scope_must_name_a_real_symbol` | `_identifiers_of = {alpha,beta,gamma,delta,total}`、真符号 scope ⇒ approved | 换回词法扫描 ⇒ 关键字重新算标识符 |
| `test_r1c_f6_negative_control_must_say_what_was_seen` | 够长且写清"怎么比 + 比出来什么" ⇒ 通过 | 换回"长度+标记词" ⇒ 四种空话变绿 |
| `test_r1c_f6_length_floor_is_restored`（裁决②） | 够长合规负控通过 | 13 字符短句被拒（标尺：去掉长度门就变红） |
| `test_r1c_f7_at_must_be_parseable_and_not_from_the_future` | 正常 at ⇒ approved + 输出报时间戳 | 撤掉判据 ⇒ 2099 照收 ⇒ approved |

## 5b. 发布门 `lint error 0`：清掉本文件的 R009（判据三第 1 条）

`python scripts/lint_rules.py` 在收口前报 **error 3**，其中一条在我的文件里
（`ERROR R009 tests/test_noai_gate.py:1422  24 处注释/docstring 里有 Markdown 强调标记或 emoji`）。

**改前备份**：`temp/batchR1c-test_noai_gate-v2beforeR009.py.bak`
（sha256 `61321eaba9857a43076515376be01c7231dc9d772c88c6668213542c4fc9d88f` = 清理前那一版；
旧备份 `temp/batchR1c-test_noai_gate.py.bak`（`abe5e464…`，v1 之前的原始版）**没被覆盖**）。

**做了什么**（`temp/batchR1c-r009-clean.py`，逐处可复核、带三道护栏）：
- 只动**注释与 docstring** 两类区间（与 R009 的判据同构）；**不动代码**
  （`**kw` / `**os.environ` 是 Python 语法）与**普通字符串字面量**（R009 不扫它们）；
- 37 行里的 `**X**` / `X**…**` 去掉星号、保留文字；两处 `⚠️`（U+26A0+U+FE0F）换成"注意："；
- 护栏：① 清理结果里不许还有装饰；② 区间**之外**的字符逐字未动（代码没被碰）；
  ③ 区间内除星号/emoji 外逐字相同（正文没被改）；
- 行数 **2144 → 2144**（一行没增删），测试数 **115 → 115**。

**读数**：
```
改前：R009 命中 24 处 / 扫到 220 个注释或文档串
已写盘。改后：R009 命中 0 处 / 扫到 220 个注释或文档串

[linter] 扫描 {'src_py': 53, 'tests_py': 110}；规则 12 条；模式 日常
[linter] error 2 / warning 0 / info 21     ← 我这一条已清；剩 2 条不在我的可写集合里
  ERROR R009 tests/test_noai_gate_audit_channel.py:70  32 处…
  ERROR R009 tests/test_fc05_contract.py:341  3 处…

pytest tests/test_noai_gate.py -q  ⇒  115 passed in 14.61s
```

**"只动注释/docstring"的独立证据**（`temp/batchR1c-r009-codecheck.py`：逐 token 比较两份文件，
跳过 COMMENT 与 `ast` 认出来的 docstring）：
```
改前 batchR1c-test_noai_gate-v2beforeR009.py.bak: 非注释/非 docstring token = 12461；docstring = 104
改后 test_noai_gate.py:                          非注释/非 docstring token = 12461；docstring = 104
两侧 token 序列逐字相同？ True
```
（包含全部普通字符串字面量与断言表达式 —— 它们一字未动。）文件 sha256：
`61321eaba985…`（清理前）→ `587758dadfbf…`（清理后）。

**剩下的两条不是我能清的**：`tests/test_noai_gate_audit_channel.py`（并行批次 01:19 重写，
`git status` 里还是未跟踪 `??`）与 `tests/test_fc05_contract.py`（批 S 的范围）——
两者都不在我的可写集合里。所以 `lint error 0` 这条发布门**我这一侧完成，整门仍未绿**。


## 6. 我没做到的 / 不确定的（如实登记）

1. **裁决① 的判据 2 只保证"`scope` 落点两两不相交"，不保证 `scope` 与证据内容真的对得上**。
   给每条维度编一个不同 `scope`、而证据里其实只有一次观察的攻击者仍能过判据 2 ——
   那需要把 `scope` 的符号与证据正文里的读数逐条绑定，超出本批能定的口径。**未验证**。
2. **跨文字系统同形字**（西里尔 `а` U+0430 vs 拉丁 `a` U+0061）归一化挡不住（`NFKC` 不折、
   类别不是 `Cf/Mn/Me`）。**重新触发条件**：有人把手写 `reviewers` 或 `--auditor` 写成另一种
   文字系统的同形字。处置需要**受控主体名册**（外部锚），不是再加归一化规则（加规则会误伤
   中文真姓名）。按裁决要求保留为残余。
3. **负控一律是"内存注入"**，不是 `git show HEAD:` 的改前实现：本仓库 `HEAD` 里的
   `noai_gate.py` 是 84448 字节 / 1904 行的三世代前版本（`temp/batchR1c-headsnap.py`），
   连 `counted_audits` / `distinct_reviewers` / `_reviewer_identity_problem` 都没有，
   **跑不出这 7 条的改前形态**。每条负控都打印"替换了哪个符号 + 该符号是否仍在当前源码里"
   作为注入生效的指纹（例如 `当前源码里那一行还在吗？ False`）。
4. **`_identifiers_of` 变严的代价（未验证）**：改成 `ast` 定义处口径后，`scope` 里只写
   **引用**而来的名字（例如 `math.floor` 而目标是别名导入）会算"不是目标里的标识符"。
   本批 9 个探针 + 11 条新用例都没踩到，但**没有穷举所有合法 scope 写法**；
   非 `.py` 目标自动回退词法口径。
5. **写侧对 `at` 也加了同一条判据** ⇒ `reaudit5-R1b-attack2.py` 会在 N6 段中途崩溃
   （判据变严的必然结果；我没改那个探针，补了 `temp/batchR1c-self-at.py` 记判定侧读数）。
6. **`reaudit5-R1b-pos.py` 现在是红的**（正控 FAIL）—— 这是裁决① 明确接受的**预期读数**
   （它是弱场景）。它仍然 `exit=1`，不影响任何硬约束读数。
7. **`tests/test_noai_gate_audit_channel.py` 由并行批次改写了**：我 v1 报告里的
   "13 failed（改前就红）"是针对**旧版本**的读数；该文件在 01:19:41 被另一个批次重写
   （962 行），现在 `33 passed`（与我的文件合跑 `148 passed`）。我**没有**改那个文件
   （不在我的可写集合里）。我最早一次合跑曾见它报 1 条失败，随后两次（单跑与合跑）都是全绿
   —— 那次失败发生在文件被并行改写的窗口内，**我没能复现**，如实登记。
8. **`temp/batchR1c-neg-rule2.py` 的指纹行有一处瑕疵**：它的 `rule2_line` 探针字符串
   写的是 v2 早期形态（`if keys_all and len(keys_all) < len(dims):`），而实现后来重构成了
   `_disjoint_face_count()` 调用 ⇒ 那一行打印 `在源码里？ False`，**容易被误读成"判据不在源码里"**。
   它不影响负控读数（负控是替换函数、不是匹配字符串）；判据确实在源码里
   （`_disjoint_face_count` + `if chosen < len(dims)`），由 `temp/batchR1c-pos2.py` 的指纹与
   `test_r1c_f1_dimensions_must_lie_on_pairwise_disjoint_surfaces` 交叉证实。
9. **没有**重跑 `--baseline`；**没有**动 `.noai-approvals.json`；**没有**用任何非人类动作
   让任何通路变绿；**没有**放宽任何既有判据（§3 的整族核对表是逐形态的）。

## 7. 交付物

- 改好的两个文件：`scripts/noai_gate.py`、`tests/test_noai_gate.py`
- 备份：`temp/batchR1c-noai_gate.py.bak`（sha256 `d8f625ca…`）
- 探针与读数：
  - `temp/batchR1c-pos2.py` / `.txt` —— **新正控**（3 条不同观察面 ⇒ approved）
  - `temp/batchR1c-neg-rule2.py` / `.txt` —— **判据 2 的负控**（撤掉 ⇒ 分摊攻击变绿）
  - `temp/batchR1c-probe.py` / `.txt` —— 7 条 finding 的正控/负控汇总 + 硬约束读数
  - `temp/batchR1c-self-dim.py` / `.txt`、`temp/batchR1c-self-at.py` / `.txt` —— 单元探针
  - `temp/batchR1c-pristine-check.py` / `.txt` —— 用**改前那一份** gate 证明外部文件的红与本次改动无关
  - `temp/batchR1c-R1b-pos.txt` / `batchR1c-after-reaudit5-R1b-*.txt` —— 审计者 9 个探针在本批之后的读数
  - `temp/batchR1c-pytest-noai_gate.txt`（`115 passed`）、`batchR1c-pytest-both.txt`（`148 passed`）、
    `batchR1c-hardconstraint-git.txt`（`GATE EXIT=1`）

---

## 附：F1 修复批对本文 §1.4 那张表的**读数标注**（`R6-R1d-2`，2026-09-27 由 F1 追加）

**这一节不改上面任何一行读数**（它们是 R1c 的历史证据），只标注**哪些位在这一版上不再携带信息**。

事实（`R6-R1d-1` / `R6-R1d-2`）：`scripts/noai_gate.py` 的 `730f51e8…` 那一版（= 本文记录的
"改后"那一版）里，`--record-audit` 这条 CLI 通路**每一次调用都以未捕获的 `NameError` 结束**
（`_run_record_audit` 读了一个 `record_audit()` 内部才有的局部名 `updated`）。后果：

1. **§1.4 里所有 `--record-audit` 的退出码（以及 §1.1 之外任何引用它的探针读数）在
   `730f51e8` 这一版上恒为 1，不代表写入成功、也不代表被拒。** 逐条受影响的是：
   `reaudit5-R1b-pos.py` / `-solo.py` / `-atk4.py` / `-atk5.py` / `-attack.py` /
   `-attack2.py` / `-ledger.py` / `-constraints.py` / `-emoji.py` —— 这 9 个探针里凡是调用
   `--record-audit` 的那几行，退出码读数**全部作废**；写入其实都成功了（探针自己打印的
   "清白审计 1/2/3/4 条"递增就是证据）。
2. **判定结论仍然有效**，但它们只该引 `--check-approvals` 的那几个位：
   `approval_status` / `approval_reason` / `distinct_auditors` / `distinct_dimensions` /
   `distinct_reviewers` / `detail`。本文里"`distinct_auditors=2`（改前 3）"这类结论属于这一类
   —— 它们与退出码无关，逐字仍然成立。
3. **该通路已在 F1 批修好**（`new_ledger.entry_for(info["path"]).counted_audits`，见
   `temp/FIX6-F1.md`）；修好之后同一条 CLI 的退出码恢复携带信息（F1 的正控：`--baseline` ⇒ 0、
   `--record-audit` ⇒ 0 且台账真多一条）。
4. **写入侧失败今后必须由 stdout 的 `[record-audit] unknown(2)：…` 表达，不许靠退出码**
   （`_fail()` 的既有形态）；判定侧失败由 `approval_status` 三态表达。这两句是本条的落地口径。

