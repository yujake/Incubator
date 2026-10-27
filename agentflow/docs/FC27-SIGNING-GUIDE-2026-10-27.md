# FC-27 签字说明书（2026-10-27 第二批）

> 给**人**看的操作单。这一批改动落在禁改区（FC-27），按 `AGENTS.md` 的口径需要
> **两名 reviewer 各自逐行走查**，然后用 `scripts/noai_batch_sign.py` 把签字落进台账。
> 门是机器执行的：签完跑一遍 `python scripts/noai_gate.py --git --since <ref>`，
> 它从 `requires_human(1)` 变 `clean(0)` 才算完。

---

## 0. 三条不许越过的线（先读这三条）

```
① **登记 ≠ 批准**。`--baseline` 只把 sha256 记进台账（`reviewers` 永远是空数组）；
   批准只能由人 `--approve`。AI 不许跑 `--approve`，也不许自己写 `.noai-approvals.json`。
② **两条不同的名字**才算两名 reviewer（同名重复签只增加记录、不增加批准数；
   名字按归一化后比较，全角/零宽/尾空格算同一个）。
③ **scope 必须具体到"这一版我看了哪儿"**。写"看过了"等于没看 —— 门会拒。
   本说明书给的模板会把**路径 + 行数 + sha256 前 12 位**写进去，
   这样后来的人拿那 12 位跟盘上比，就知道当时签的是哪一版。
```

另一条同样重要：**签完之后文件再改一个字节，这一条的批准立刻作废**（台账钉的是当时那一版的内容）。
所以顺序是「先改完 → 再 `--baseline` → 再签字」；改完忘了重新登记就签，签的是旧版本。

---

## 1. 现状（2026-10-27 22:xx 的读数）

```
清单条目：46 条唯一路径（`.noai-paths`）
已满足 2 名：**2** 条 —— `src/agentflow/agentspec.py`、`src/agentflow/specs/__init__.py`
`--all` 实际会签：**39** 条
   （46 − 2 已满足 − `.noai-approvals.json` 自己 1 条（台账不能批准自己）
     − 盘上还不存在的预登记路径（`src/agentflow/release_check.py`）− 同一路径在清单里重复出现的次）
```

⚠️ 这三个数是 **2026-10-27 22:xx 的快照**；`--all` 会跳过已满足的与台账自己，
所以"会签多少条"每次都不同 —— 以 `--list` 的最后一行（`共 N 条：已满 2 名 X 条 / 待签 Y 条`）为准。

查现状（只读，一个字节都不写）：

```bash
python scripts/noai_batch_sign.py --list
```

它逐条打印：路径 / 已有 reviewer 数 / sha256 前 12 位 / 行数。**这份说明书不抄那张会变的表** ——
凡与上面命令的输出不一致，以命令为准。

---

## 2. 两位 reviewer 的动作（一人一份，各跑各的）

> 两个人**都要**看**全部 44 条**：每条路径需要 2 名不同 reviewer，所以不能分工覆盖。
> 若你们约定分工，那也只能是"你多看几遍、我多看几遍"的分工，不能是"你签前 22 条、我签后 22 条"。

### 2.1 先干跑（0 写入）

```bash
# 把 <你的名字> 换成你本人在台账里要留的名字（一个就够；两次都要是同一个名字）
python scripts/noai_batch_sign.py --all \
  --reviewer <你的名字> \
  --batch "2026-10-27 第二批 FC-27 重登记" \
  --scope-template "{path}（{lines}）逐行看过；sha {sha12}；本批 {batch}" \
  --note "逐行走查通过（本批见 docs/FC27-SIGNING-GUIDE-2026-10-27.md）" \
  --dry-run
```

`--dry-run` 会打印：将要签的路径清单、reviewer、**第一条的 scope 展开样子**、verdict、note。
**看一遍那份清单**：条数、路径、sha12 与你准备看的东西对得上再往下走。

### 2.2 真签

把上面那条命令的 `--dry-run` 去掉，并加 `--yes`（非交互环境）或直接在终端里按提示逐字输入 `yes`：

```bash
python scripts/noai_batch_sign.py --all \
  --reviewer <你的名字> \
  --batch "2026-10-27 第二批 FC-27 重登记" \
  --scope-template "{path}（{lines}）逐行看过；sha {sha12}；本批 {batch}" \
  --note "逐行走查通过（本批见 docs/FC27-SIGNING-GUIDE-2026-10-27.md）" \
  --yes
```

它会做四件事（顺序固定）：

```
① 预演每一条（用门自己的 add_approval，不落盘）—— 有一条不行就整批不签
② 逐条逐人 --approve，并**回读台账**确认真的写进去了
③ 重读台账做最终复核：N/44 条满足 2 名；不足的逐条列出
④ 若给了 --report-out / --status-json，落一份人读记录与一份机器读数
```

建议顺手带上记录（给第三个人复核用）：

```bash
  --report-out draft/FC27-签字记录-2026-10-27.md \
  --status-json temp/fc27_sign_status.json
```

### 2.3 两个人谁先谁后都行

台账是追加式的：甲签完是 `1/2`，乙签完变 `2/2`。**不需要协调次序**，也不需要甲等乙。
签到一半退出也没关系——已签的那几条是真签上的，重跑会自动跳过已满足的（见 §4）。

---

## 3. 签完怎么验（三种口径，从窄到宽）

```bash
# ① 逐条看批准状态（最窄：只回答"这 44 条现在几比几"）
python scripts/noai_batch_sign.py --list

# ② 门自己的批准判定（回答"全部命中路径是否都已获批准"；exit 0 = 是）
python scripts/noai_gate.py --check-approvals --paths $(cat agentflow/temp/_fc27_paths.txt 2>/dev/null) -q
#   没有上面那个清单文件时，直接对整批跑：
python scripts/noai_gate.py --git --since HEAD~1 -q     # 期望从 1(requires_human) 变 0(clean)

# ③ 发布门那一项（回答"发布前检查里 noai 这一项过不过"）
python scripts/release_check.py --only noai -q
```

三条都绿才叫签完。**只绿①不绿②** 通常是：签的时候盘上文件又被改过（hash 变了）⇒
重跑 `--baseline` 再签一遍，别去动判据。

---

## 4. 工具会拒绝的六种情形（这是设计，不是 bug）

```
· `--scope` 与 `--scope-template` 都为空 ⇒ 整批拒（scope 不许空）
· 同一个人在同一批里重复 → 只增加记录、不增加批准数（会在输出里明说）
· 某条的台账 hash 与盘上不一致（未登记 / 登记过但文件又改了）⇒ 那一条拒，并打印
  "要登记的就是这几条" + 可直接粘贴的 `--baseline --paths …` 命令（**本工具不代登记**）
· 非交互环境没给 `--yes` ⇒ 不签（台账一字未动）
· 一条预演失败 ⇒ **整批不签**（"批量签了一半"在结构上不会发生）
· `--all` 会跳过 `.noai-approvals.json` 自己（台账不能批准自己，理由码 `ledger_self_approval`）
```

**它永远不做**：不自己写台账格式（只调门的 `--approve`）、不代登记、不猜 hash、
不把"签了 1 名"说成"已批准"。

---

## 5. 常见问题

**Q：某个文件没在那份 44 条里，是不是不用签？**
不是。清单以 `.noai-paths` 为准；`--all` 只签"台账里还不足 2 名"的那些。
新登记的文件会在 `--list` 里出现。

**Q：签完之后有人又改了其中某个文件怎么办？**
那一条的批准立刻作废（hash 对不上，门会报 `stale`）。补的动作是：
`--baseline` 重新登记这一版 → 通知两名 reviewer 重新看 → 再签。**不许直接把台账的 sha 改成新值**
（那是伪造签字记录）。

**Q：能不能只找一个人签两次？**
不能。批准数按**不同姓名**计，同一个人签十次仍是 1 名。

**Q：这份说明书里的数字会过期吗？**
会，而且刻意不抄那张会变的表。任何数字与 `python scripts/noai_batch_sign.py --list` 不一致时，
**以命令输出为准**。

**Q：AI 能不能先替我们签，我们事后复核？**
不能。`AGENTS.md` 与 `noai_gate.py` 的 `ledger_self_approval` 都堵这一条：
AI 自批与"两人独立复核"在结构上无法区分。本批的登记（`--baseline`）是 AI 做的，
**批准（`--approve`）必须由人做** —— 这正是把两者分开的理由。

---

## 6. 这一批到底改了什么（给 reviewer 的起点）

```
p212  修 mp3-r3 真机暴露的根因：时钟/停机/程序归属、树与销号、文献三态、文件口保留区
p213  M 的自动审阅工具（conductor.patrol / review_child / patrol_verdict）+ 轮查规范动作
p214  全系统分块审查：性能治本（时钟安静一拍 251×、capabilities 导入 −92%、store 写放大 845→178ms 等）
      + 12 条真缺陷（见 draft/170）
```
逐条清账在 `draft/170-全系统分块审查总账-2026-10-27.md`；本批的登记清单由
`python scripts/noai_gate.py --check-ledger` 给出（它回答"清单里每一条在台账里都有条目吗"）。
