# NOAI-GOVERNANCE —— FC-27 禁 AI 区门的机制说明

> 本文件讲**机制本身**：门怎么判、为什么这么判、以及它**做不到**什么。
> 配套的两份人读文档是：
> - `AGENTS.md`（给 AI 编码者的硬约束，含 `NOAI-MANIFEST` 清单区块）；
> - `NOAI-REVIEW-REGISTER.md`（本轮逐文件复核登记表：谁该读哪些符号、批准栏）。
>
> 机器可读的三份是：`.noai-paths`（禁改区清单）、`.noai-approvals.json`（hash 台账）、
> `scripts/noai_gate.py`（门，退出码 0/1/2）。

---

## 1. 门的三种结论与退出码

```text
0 = clean          查过了：要么没命中禁改区，要么命中项的 hash 与台账一致**且**已有 2 名 reviewer
1 = requires_human 查过了：命中且**未获批准**（从没登记 / hash 已漂 / 走查人数不足）
2 = unknown        **没查成**（清单或台账读不到、解析不了、结构不对、不是 git 仓库、没给改动集）
```

**`unknown` 绝不是 `clean`。** 把"没检查"与"检查过了没问题"折叠成同一个"通过"，
是本项目反复踩过的坑（成熟项目的原话：*"多数脚本不设退出码，于是『未报错』被误读为『无问题』"*）。
所以任何"读不到 / 解析不了 / 结构不对"都必须走退出码 2 —— 这在代码里是
`LedgerError ⇒ GateResult(verdict="unknown")` 这一条路径，测试里有对应负控：

| 情形 | 结论 | 为什么不能是别的 |
|---|---|---|
| 清单不存在 / 解析失败 | `unknown`(2) | 没清单就没法判命中 |
| 命中但**台账不存在** | `unknown`(2) | "没有记录"不等于"没有未批准的改动" |
| 命中但台账**不是合法 JSON** | `unknown`(2) | 解析不了就没查成 |
| 命中但台账**结构不合规**（版本不认识 / 条目缺 `sha256` / `reviewers` 不是数组 / 同一路径两条） | `unknown`(2) | 结构读不懂时，**不许**按"没有批准记录"处理 |
| 命中路径**内容读不到**（被删/变成目录） | `unknown`(2) | 拿不到 hash 就判不了"是不是被批准的那一版" |
| 没有命中 | `clean`(0) | **台账读不读都不影响这个结论**（台账只在需要它时才是必需的） |

### 两条命令

```text
python scripts/noai_gate.py --paths <改动文件…>                    # 只判"命中没命中"（+ 台账 stale 对账一行，见下）
python scripts/noai_gate.py --check-approvals --paths <改动文件…>   # 命中 + 台账判定（推荐）
python scripts/noai_gate.py --check-approvals --paths <文件> --json # 同上，机器可读
python scripts/noai_gate.py --check-consistency                    # 两处清单逐条一致（不一致 ⇒ 2）
python scripts/noai_gate.py --check-canonical                      # 规范哈希口径一致性（门 vs signatures；见下）
```

`--check-canonical`（`R-33`，2026-09-29）：本门算回执哈希用的**规范 JSON 口径**与
`agentflow.signatures`（稿件内容哈希）**是不是同一份**。同一载荷两侧哈希必须逐字相等，
否则报 `divergent`（退出码 **1** —— "查过了、口径分叉了"）；本包 import 不了 ⇒ `unknown(2)`
（**没查成，不许读成一致**）。它存在的原因是：门**不能** import 本包（它必须能被单独复制运行，
见 `scripts/noai_gate.py::_receipt_digest` 的 docstring），所以那里留了一份自己的字节 ——
而"没人看着的第二份口径"必须有一条机器判据钉住。

`--check-approvals` 可以配 `--paths` / `--stdin` / `--git` 三者之一 —— 与既有的
`--paths` 完全相同，**不许两个来源混用**（混用时无法判断"这次到底检查了哪些路径"，直接 2）。

### 一处**刻意保留**的不对称（读路径 vs 写路径），它不是 bug

| 动作 | `--root` 影响清单吗 | 为什么 |
|---|---|---|
| 读：`--paths` / `--check-approvals`（配 `--manifest`） | **不影响** —— 不给 `--manifest` 时清单按**本脚本所在仓库**解析（既有行为，一字未改） | 读动作判错只是"报错"，且改动它会改变既有 CLI 行为与既有测试的语义 |
| 写：`--baseline` / `--approve` | **影响** —— 清单按 `<root>/.noai-paths` 解析 | 写动作写错地方**不可逆**（把 A 仓库的基线写进 B 仓库的台账），所以按显式 `--root` 走，而不是按"脚本恰好在哪个目录"猜 |

所以在沙箱/临时仓库里演练 `--check-approvals` 时要**同时**给 `--manifest` 与 `--root`：

```text
python scripts/noai_gate.py --check-approvals --paths src/a.py \
    --root <沙箱> --manifest <沙箱>/.noai-paths
```

---

## 2. hash 为什么比 git 更强

`D:\Incubator\agentflow` **不是 git 仓库**：`--git` 永远 `unknown(2)`，
所以"这次改了哪些文件"在这个环境里取不到。但这不是死路 —— **内容 hash 就是版本**。

`.noai-approvals.json` 为每条命中路径记下**当前内容的 sha256**、谁写的（`authored`）、
改了什么（`change_note`）以及**已完成的人工逐行走查记录**（`reviewers`）。

于是"命中之后批准没批准"变成一个可判定的问题：

| 对比 | git diff | hash 台账 |
|---|---|---|
| 能说出"文件变了" | ✅ | ✅ |
| 能说出"**变的是不是被批准的那一版**" | ❌（git 不知道你批准的是哪一版） | ✅（`stale`） |
| 批准之后**又被悄悄改了** | ❌ 只报"文件有改动"，无批准语义可比 | ✅ 台账里的 hash 与盘上不一致 ⇒ 立刻 `stale` |
| 需要版本控制系统的历史 | 需要 | 不需要（磁盘内容就是事实） |

`stale` 的判定消息里**必须打出两个 hash**（各前 12 位）：

```text
[requires_human] required_approvals=2
  - src/agentflow/verify.py  命中 src/agentflow/verify.py  [auth-audit]  …
      ⇒ [unapproved] stale：台账里被批准的那一版是 06e9d7677875，盘上现在这一版是 a1b2c3d4e5f6 …
```

**hash 是字节级的**（不做行尾/编码归一化）。理由是两个方向的代价不对称：
假 `stale` 只是让人多走查一次（可恢复）；假 `approved` 会让没走查的版本被当成走查过的版本
（不可恢复）。CRLF/LF 的差别**是**内容差别。

> **`stale` 在默认路径上也报（`R-62`，2026-09-29）**：上面那段是 `--check-approvals` 的输出。
> 而 CI 跑的是 `--git --since <ref>`（走默认的 `check_paths` 那一支）—— 它原来**一句 stale 都不说**，
> 于是"台账钉的不是提交进去的那一版"这件事在 CI 的路径上看不见。现在默认路径在命中禁改区之后
> **只读地**补一句对账（不改 verdict、不改退出码）：
>
> ```text
> [requires_human] required_approvals=2
> requires_human：1 条改动落在 **FC-27 禁 AI 区**（类别：auth-audit）⇒ …
> ⚠️ 台账 **stale** 1 条（被批准的那一版与盘上不是同一版 ⇒ 旧批准不许沿用；
>    `--check-approvals` 会给出逐条结论）：src/agentflow/capabilities.py
>    （台账 5d245fe74bde ≠ 盘上 ac8a0f41712f）
> ```
>
> 读不到台账时它写的是"**没查成**，不是'没有 stale'"（三态纪律落在这一句上）。

### 理由码（人需要据此决定下一步动作）

| `approval_reason` | 含义 | 人的动作 |
|---|---|---|
| `unregistered` | 台账里**从没登记**过这个路径 | 跑 `--baseline` 登记，然后走查签字 |
| `stale` | 登记过，但**被批准的那一版不是现在这一版** | 先确认以哪一版为复核对象；必要时重跑 `--baseline`（会清空该条批准语义），再走查 |
| `insufficient_reviewers` | hash 一致，但**不同姓名的 reviewer 不足 2 名** | 继续安排走查签字 |
| `ledger_self_approval` | 命中集里出现了**台账自己** | 无事可做：这条**永远**不批准（见 §4） |
| `hash_unavailable` | 拿不到磁盘内容（文件被删/不可读） | 先让文件回到可读状态，否则整体是 `unknown` |

---

## 3. 登记 ≠ 批准（两个动作不许合并）

| 动作 | 命令 | 谁跑 | 写什么 |
|---|---|---|---|
| **登记** | `--baseline --paths <文件…>` | 工具 / AI 都可以 | `sha256` + `glob` + `category` + 摘要；**`reviewers` 永远是 `[]`** |
| **批准** | `--approve <文件> --reviewer <姓名> --scope "<走了哪些行/函数>"` | **只能是人** | 追加一条 `{name, at, scope, note, verdict}` |

把两者合成一个动作，等于让 AI 自己给自己发批准 —— 那正是 FC-27 要防的事。
所以 `--baseline` 的 help 文本与输出里都写着"登记 ≠ 批准"，并且有一条测试断言
`--baseline` 生成的条目 `reviewers == []`。

刷新时的两条规则（**不对称是刻意的**）：

- 内容 hash **变了** ⇒ 清空 `reviewers`。旧签名批准的是**旧那一版**，
  把它留在新 hash 上正是本台账要堵的"批准之后又被悄悄改了"。
- 内容 hash **没变** ⇒ 保留已有 `reviewers`。台账钉住的对象是**内容版本**，
  不是"某一次登记动作"；清空会产生一个**反向激励**（人越勤快重跑基线，
  人工记录越容易被摧毁）。完整理由见 §5.5。

`--baseline` 里**不命中禁改区**的路径不登记（没有 `glob` / `category` 可写），
但整体退出码为 **2**：有一个路径没做成，"部分成功"报 0 会让它变成没人发现的事。
命中的那些**照常登记**（不因为一条不合格就整批放弃）。

---

## 4. 台账自指禁止

`.noai-approvals.json` **自己也在禁改区清单里**（`[category: auth-audit]`）。
它在命中集里出现时**永远**判 `unapproved`，理由码 `ledger_self_approval`，
**优先于** hash 判定与人数判定（哪怕它的 hash 一致、reviewers 有 2 名）。

为什么必须禁止：台账的内容会因为"写入一条批准记录"而变化。若允许它自批准，就把
"**AI 把自己的改动写进台账并声称已批准**"变成一条合法路径 —— 台账既是记录者又是被记录者，
整个机制的可信度就归零。`--approve` 也拒绝给台账自己签字（退出码 2）。

因此**台账不给自己登记条目**：登记它只会制造一条永远 `stale`、永远 `unapproved` 的噪音。

---

## 5. 人工批准的操作流程

### 5.1 一次走查

```text
# 1) 看现在是不是"被批准的那一版"（预期：stale 或 insufficient_reviewers 或 unregistered）
python scripts/noai_gate.py --check-approvals --paths src/agentflow/verify.py

# 2) 登记当前版本（若第 1 步报 unregistered；报 stale 时先确认以哪一版为对象）
python scripts/noai_gate.py --baseline --paths src/agentflow/verify.py --note "本轮改了什么"

# 3) 逐行读文件，对着登记表 §2.1 该条的"复核要点"确认语义（不是格式）

# 4) 签字（hash 必须先与磁盘一致，否则拒绝写入并以退出码 2 结束）
python scripts/noai_gate.py --approve src/agentflow/verify.py \
    --reviewer "张三" --scope "verify_all + number_without_eval_scope + eval: 解析（全文）" \
    --note "判据未被放宽；新门确实挂在 verify_all 返回里；unknown/not_applicable 与 pass 分得开"

# 5) 复算
python scripts/noai_gate.py --check-approvals --paths src/agentflow/verify.py
```

`--scope` **必须具体到符号或行区间**。写"看过了"等于没看 ——
与清单理由"只在一边写理由，等价于另一边没有理由"是同一个道理。
`--approve` 会拒绝空 `--scope` 与空 `--reviewer`。

### 5.2 为什么是 2 名，且**不是可配置项**

`REQUIRED_APPROVALS_ON_HIT = 2`（`scripts/noai_gate.py`）写死，**不做成参数**：

- 为什么是 2 而不是 1：**1 名 reviewer 与"作者自己再看一遍"在结构上无法区分**；
  要拿到**互相独立**的复核，最少需要 2 个人。
- 为什么不可配置：**可配置的准入门槛等于没有门槛** —— 下一个赶时间的人会把它改成 0 或 1，
  而且那次改动**不会有任何测试变红**（常量从 2 改成 1 之后，"命中 ⇒ requires_human"
  这条判据在 1 名 reviewer 时仍然自洽）。写死 + 一条断言
  （`test_required_approvals_constant_is_two`）才让"2"是一个事实而不是一个约定。

**批准数按"不同姓名"计，不按记录条数计**：同一个人签两次不是 2 名 reviewer。
重复的签名记录**照实保留**（它是事实，人可能对同一版做了两轮走查），
只是不增加批准数，并在输出里明确提示。

### 5.3 台账的字段

```jsonc
{
  "ledger_version": 1,              // 不认识的版本 ⇒ unknown（不许按老结构硬读）
  "generated_at": "<ISO 时间，带时区>",
  "entries": [
    {
      "path": "src/agentflow/verify.py",   // 仓库相对、正斜杠（台账的键）
      "glob": "src/agentflow/verify.py",   // 命中的清单条目（命中多条时这里是第一条）
      "category": "auth-audit",            // 必须是 FC-27 七类之一
      "sha256": "<磁盘当前内容的 sha256，十六进制小写>",  // 字节级，不归一化
      "authored": "ai-agent",              // human / ai-agent / unknown（判不出来就 unknown，不许猜）
      "authored_basis": "inferred",         // **结论有多强**：attested / inferred（**必填，缺了 ⇒ unknown**）
      "change_note": "<这次改了什么>",      // 登记时写；判不出来要写明"无法从仓库判定"
      "changed_this_session": true,        // true / false / null（null = 无法从仓库判定）
      "reviewers": [                       // **只能由人填**
        {"name": "…", "at": "<ISO 时间>", "scope": "…", "note": "…", "verdict": "…"}
      ],
      "also_hits": [                       // 同一路径命中的**其它**清单条目（不许静默丢掉）
        {"glob": "…", "category": "…", "reason": "…"}
      ]
    }
  ]
}
```

三态纪律在台账里的两处用法：

- `authored` 有第三态 `unknown`：**"这一段是谁写的"经常查不出来**，
  猜成 `human` 会把 AI 的改动洗成人写的，猜成 `ai-agent` 会把人的署名抹掉。
- `changed_this_session` 有第三态 `null`：**"登记了它"与"它被改过"是两件事**。
  登记一个本轮没动的文件（为了将来能比对它有没有漂移）与登记一个刚被改的文件，
  是两种不同的记录，不能合并表达。

### 5.4 `authored` 是**结论**，`authored_basis` 是**这个结论有多强**

两个字段必须成对出现，且**含义不能混**：

| `authored_basis` | 含义 | 门能做什么 |
|---|---|---|
| `attested` | 有**直接证据**：改动者自己声明，或人签字时声明 | 只能**强迫它被写下来**；这个声明**无法机械验证**（与 §6.6 同族） |
| `inferred` | 从 **mtime + 会话边界**推断（如"这一轮 mtime 落在本会话窗口内 ⇒ 本轮是 AI 在写"） | 能判定"它只是推断"，并在输出里**显式标注** |

为什么要拆成两个字段：一条只有一个 `authored: "ai-agent"` 的记录，**看起来像事实**，
而它可能只是推断。读台账的人（以及将来的复算脚本）不该被迫去猜这件事。

两条硬规则：

1. **`authored_basis` 必填**：缺了就判结构不合规 ⇒ `unknown(2)`。
   **刻意不给默认值** —— 给了默认值，"我没写依据"会被静默变成"依据是推断"，
   而这两件事不是同一种东西（三态纪律的同一用法）。
2. **`inferred` 必须露在人读的那一行**：`--check-approvals` 的理由行里会带
   一句"（署名归属为**推断**，据 mtime 与会话边界得出，非独立证据）"；
   `attested` 则带"（署名归属由改动者/签字人**声明**：attested，门无法机械验证该声明）"。

`--baseline` 的默认是 `--authored unknown --authored-basis inferred`（**不猜**）；
显式给了 `--authored` / `--authored-basis` 就照写，**hash 未变也写** ——
对**同一版内容**给出更强的归属声明是改进，不是换对象（两个参数的行为必须对称，
否则会出现"署名改了、依据没改"这种半截状态）。

### 5.5 为什么"hash 未变 ⇒ 保留 reviewers"

台账钉住的对象是**内容版本**，不是"某一次登记动作"。`hash` 没变 ⇒
被批准的那一版**就是**盘上这一版，签名依然指向同一个对象。

反过来，如果任何一次 `--baseline` 都清空签名，那会产生一个**反向激励**：
人越勤快地重跑基线，人工记录越容易被摧毁 —— 而"勤快"恰恰是我们希望鼓励的行为。
**判据要让人更愿意跑它，而不是更不敢跑它。**

（`hash` 变了 ⇒ 清空签名：旧签名批准的是**旧那一版**，留在新 hash 上就是
"批准之后又被悄悄改了"的那种形态。）

---

## 6. 本机制**做不到**的事（结构性限制，必须一起读）

1. **hash 一致 ≠ 实现正确。** 台账证明的是"这一版就是被批准的那一版"，
   **不证明它是对的**。这是两类问题，不要因为门变绿就跳过语义走查。
2. **它不是 git，没有"改动集"这个客观事实。** `--check-approvals` 需要调用方给出
   改动集（`--paths` / `--stdin`）；在没有 git 的环境里，**"哪些文件被改了"仍然要人说**。
   `--git` 在本仓库恒为 `unknown(2)` —— 这是正确行为，不是缺陷。
3. **它抓不到"已经发生"的那次改动内容。** `--baseline` 之后能机械抓到的是**从此往后**的漂移；
   上一轮改了哪几行，只能靠人逐行走查（登记表 §2 里 5 个文件"符号面相同"正是这个缺口）。
4. **它不保护清单之外的文件。** `.noai-paths` 漏一个文件，门不会报错，只会不命中 ——
   一个**静默的假阴性**。清单的完备性本身要人定期复查。
5. **`unknown(2)` 需要人真的停下来。** 门会正确报 `unknown`，但**没有任何机制阻止人在
   `unknown` 状态下继续**（当前 `release_check.py` 只把它记为 `unknown`，不阻断）。
   要让 `unknown` 真的拦人，必须把它接到 CI 的**阻断判决**上。
6. **`--approve` 拦不住一个不诚实的人。** 它记录"谁、什么时候、走了哪些行"，
   但**无法验证**签名者真的读了。它的实际作用是让"没走查"变成一件**需要刻意说谎**
   才能做到的事 —— 这比"忘记走查"高一个门槛，但不是密码学保证。
   同族的另一条：**`authored_basis: "attested"` 也无法机械验证**（见 §5.4）。
   我们**刻意不为它造测试** —— 一条"attested 必须有证据"的机械判据做不到，
   硬造只会得到一条**永远为真**的测试，而永远为真的测试比没有测试更糟
   （它会让"这条被覆盖了"成为一种错觉）。能做的只有：强迫它被写下来、
   在输出里标注它依赖声明者诚实。
7. **它不防篡改。** 台账文件本身可以被改写（它就是禁改区里的一个普通文件）。
   它能做的是：让"改写台账"这件事留下一条需要人走查才成立的记录 ——
   而不是**阻止**它。真正的保证来自"台账也在禁改区里 + 2 名 reviewer"这条人审约束。
8. **单条路径的判定不覆盖"多条 glob 的语义差异"。** 一条路径命中多条 glob 时
   （如 `dedup.py` 同时在 solver-core 与 provenance-dedup），台账只对**内容**做一次判定，
   另外几条记进 `also_hits`；"这两个类别的复核要点各自都被走查过"仍然要人保证
   （在 `--scope` 里写清楚）。
