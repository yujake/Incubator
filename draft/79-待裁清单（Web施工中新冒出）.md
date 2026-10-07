# draft/79 待裁清单（Web 端施工中新冒出来的）

> **用途**：所有者已经裁完 `draft/72`/`draft/76` 那两批（21 + 20 道），并交代"新冒出来的待裁项攒成选择题一次提交"。
> 这份就是那个筐 —— 只收**施工/写简报时真撞上的**新岔路，每题给：出处（盘上 `file:line` 或实测读数）· 选项 · 每个选项的代价 · 我的建议 · 不裁会怎样。
> **规矩**：① 只收"不裁就没法继续"或"不裁就会做错"的；② 每条都要有可复算的出处，不许凭印象；③ 我**不代签**，`draft/79` 攒够一批再一次性交。

---

## T1 `browser` marker 与 `addopts` 不一致：`-m browser` 到底靠什么"默认排除"

**撞上它的地方**：写 C 线简报（`temp/_line_C_brief.md` 任务 8）时核 `pyproject.toml`。

**盘上事实**（三条，都可复算）：
1. `agentflow/pyproject.toml:69`：`addopts = "-m 'not network'"` —— 只排除 `network`。
2. `agentflow/pyproject.toml:70–72`：`markers` 现在只有一行 `network`（**没有** `browser`）。
3. `draft/77 §2.2` 第 2 行要加的 marker 描述是"`browser: 需要 Playwright 与浏览器；**默认排除**，用 -m browser 显式运行（未装 ⇒ unknown，不是 pass）`"，而 `draft/73 §2.8` 的实现形状是 `pytestmark = [pytest.mark.browser]` + 未装 ⇒ `skip`。
⇒ **合起来读：`marker` 说"默认排除"，但仓里没有任何一行真的排除它**；真排除它的只有"本机没装 playwright 所以 skip"这个**环境巧合**。**装了** playwright 的人跑一次 `python -m pytest`，四个浏览器用例会被真跑（很可能因为要起服务、要开浏览器而变慢/不稳）。

**三种解法与代价**：

| 选项 | 做法 | 代价 |
|---|---|---|
| **T1-a** | `addopts` 改成 `-m 'not network and not browser'` | 动了**既有行**（与 `draft/77 §2.2` 那句"两处都是加行、不改任何既有行"冲突）⇒ 签字包要**改口径**、reviewer 的走查项要加一条；好处是语义最干净 |
| **T1-b** | 在 `tests/conftest.py` 的 `pytest_configure` 里注册 marker 并默认 `deselect`（不碰 `pyproject.toml`） | 不用动禁改区（少一个签字点），但 `conftest.py` 是 **B 线**的文件 ⇒ 跨线改动，得先让 B 线做完或改归属；判据要额外钉"默认收集但不跑" |
| **T1-c** | 什么都不改：靠"未装 playwright ⇒ skip"近似"默认排除" | 零改动；但"opt-in"只在没装的环境里成立，**装了的人默认会跑** —— 与 `draft/76` F1"opt-in"字面不符，属于把口径写宽了 |

**我的建议**：**T1-a**。理由：`-m 'not network'` 这条 **本来**就是本仓"默认跑什么"的单一开关，加 `and not browser` 是一行、语义唯一、且不引入跨线改动；`draft/77 §2.2` 那句"只加行"是**可以改准的描述**（它是我写的，不是裁定），改准它比让 `marker` 描述里留一句做不到的"默认排除"更诚实。若你更看重"签字面越小越好"，那就 **T1-b**。

**不裁会怎样**：C 线到 W4 时只能按现状落 marker，`browser` 用例在**装了** playwright 的机器上默认跑；发布门第 7 步（前端步）也会跑 `pnpm typecheck/build`，两者叠加会让"默认 18 分钟门"变得不稳。**结论：不裁不致命，但会把一个已知不一致留进 `pyproject.toml` 的签字版里。**

---

## 现状

- 已攒：**1 题**（T1）—— **已裁并落地**（见下）。
- 攒到"再攒就没法继续"或所有者喊收时，一次性提交。

---

## T1 已裁并落地（2026-10-07）

**裁法**：所有者本轮交代「如有必需，允许动禁改区」⇒ 按 **T1-a** 落地（`addopts` 改成
`-m 'not network and not browser'`），提交 `498bd75`。上面三选项的代价仍然有效：若你更看重
"签字面越小越好"，改回 T1-b 是 `tests/conftest.py` 里加十行的事（那要等 B 线的文件腾出来）。

**落地读数**：
- `pyproject.toml`：`addopts = "-m 'not network and not browser'"` · `markers` 两条
  （`network` / `browser`，后者描述里写明"未装就是 unknown（skip），不是 pass"）·
  `optional-dependencies.browser = ["playwright>=1.44"]`（运行期依赖仍然只有 `filelock`）。
- 复算：`python -B -c "import tomllib,pathlib;d=tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'));print(d['tool']['pytest']['ini_options']['addopts'])"`。
- FC-27 读数（**诚实读数，签字仍需补记**）：`python -B scripts/noai_gate.py --git --since 5c6e441 --check-approvals`
  ⇒ 命中 3 条、3 条未获批准（`stale` 2 = `pyproject.toml` + `tools/release_all.py`；`unregistered` 1 = 刻意不入库的演示物）
  ⇒ 这两条要按 `draft/77 §2.4/§2.5` 走查并签（我不代签自己的这一版）。
