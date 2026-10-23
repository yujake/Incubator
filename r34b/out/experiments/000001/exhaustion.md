# exp:000001 的数值实验读数（作者：E）

- 命题：R(3,4) = 9: every red/blue 2-colouring of E(K_9) contains a red K_3 or a blue K_4, and there exists a red/blue 2-colouring of E(K_8) containing neither.
- 命题键：r34-ramsey-exactly-9
- 程序：code/r34_verify.py（sha256 76b4c735d4008f57）
- 搜索空间：{"completed": true, "explored_nodes_n9_degree_bounded": 1920213, "explored_nodes_n9_plain_capped": 4000001, "n_max": 9, "space": "red/blue 2-colourings of E(K_9), |space| = 2^36 = 68719476736", "strategy": "deterministic DFS, lexicographic edge order, prune on forbidden configuration (red K3 / blue K4); n=9 additionally with red-degree<=3 prune"}
- 结论：supports（等级 cross_check）
- 读数落点：out/experiments/000001/exhaustion.md
- 原始 stdout：out/experiments/000001.log（exit_code=0，runtime=7.172s）

## 程序地址

- 程序：`code/r34_verify.py`（工作区相对路径；本报告不改它一行逻辑，只把它的读数写成可复核的文字）
- 原始输出：`out/experiments/000001.log`
- 复现命令：`verify.run_experiment(claim=<上面的命题>, claim_key='r34-ramsey-exactly-9', script_path='code/r34_verify.py', method='exhaustive_search')`

## 程序设计思路

数据结构：`red[v]` / `blue[v]` 是邻接位掩码，`rdeg[v]` 是红度计数，`colour` 是边→0/1 的字典，边按字典序 `(0,1),(0,2),...,(n-2,n-1)` 排成列表 `edges`，深度优先按下标 `e` 逐条边染色。

递归体（`search` 内 `dfs(e)`）：

1. 先试染红。禁染的判据是「新边 (i,j) 染红会不会立刻凑出红 K_3」——只需查 `red[i] & red[j] != 0`（两端已有共同红邻点即成立），因为只新增了这一条边，新的红三角形必过它。
2. 再试染蓝。禁染的判据由 `blue_edge_creates_clique` 给出：蓝 K_3 时查 `blue[i] & blue[j] != 0`；蓝 K_4 时枚举共同蓝邻点 `N = blue[i] & blue[j]`，要求其中存在一条蓝边（`N` 里两个点 a,b 满足 `blue[a]` 含 b）——同样是「新蓝团必过新边」这一条。
3. 剪枝之所以不丢解：红 K_3 与蓝 K_4 都是**单调**禁形——部分着色里已经含了，任何加边扩展都还含着，所以剪掉的子分支里不可能有干净解。
4. 另有一路独立的校验器 `forbidden_configuration(n, colour, blue_clique)`：对**完整**着色用 `itertools.combinations` 穷举所有三元组/四元组暴力复查，与 DFS 的位掩码路径不共用代码。K_8 的见证就是先由 DFS 给出、再由这个独立校验器复核的。
5. n=9 另跑一个「红度 ≤ 3」的变体（`max_red_deg=3`），依据是 docstring 里的引理 L：干净着色里 N_R(v) 必为红独立集（否则过 v 有红三角形），故 N_R(v) 内所有边皆蓝，若 |N_R(v)| ≥ 4 则凑出蓝 K_4，所以每点红度 ≤ 3。
6. 自校准：同一套机器跑 (红 K_3, 蓝 K_3)，已知答案 R(3,3)=6 —— n=5 应有解、n=6 应无解。
7. 节点数 / 秒数双上限（`cap_nodes` / `cap_seconds`）只用来给运行封顶；一旦触顶 `capped=True`，那次搜索就**不再**算穷尽（下方 n=9 的 plain 那一路正是如此）。

## 穷举论证

**搜索空间有多大。** n=9 时边数 m = 9·8/2 = 36，着色数 |space| = 2^36 = 68719476736。n=8 时 m = 28，|space| = 2^28 = 268435456。这些数字由脚本 `edges` 列表长度直接给出（REPRO_RESULT 的 scaling 里每条都带 `edges` 字段：n=8 是 28，n=9 是 36）。

**哪些搜索真的是穷尽的。**

- n=5,6,7,8 的 plain 搜索全部 `capped=False`（节点数分别 265 / 987 / 10770 / 130006 / 1420332），按上文第 3 条的单调性，剪掉的分支里不可能有干净解 ⇒ 这四个 n 上 `count` 是**精确**的干净着色数：n=6 为 2812、n=7 为 13842、n=8 为 17640。
- n=8 的 17640 > 0，且脚本取其中第一个解交给独立校验器 `forbidden_configuration` 复核，返回「no red K3 and no blue K4」，28 条边齐全 —— 这就是下界见证：K_8 上存在既无红 K_3 又无蓝 K_4 的着色。它的 12 条红边原话见 `out/experiments/000001.log` 的 `CERTIFICATE K8:` 一行：`[[0, 1], [0, 2], [0, 3], [1, 4], [1, 5], [2, 4], [2, 6], [3, 5], [3, 7], [4, 7], [5, 6], [6, 7]]`。
- n=9 的 **plain** 搜索触顶：`nodes=4000001, capped=True(cap_reason=nodes), count=0`。触顶的搜索**不是**穷尽的：它没搜完，`count=0` 只说明「搜到的那 400 万个节点里没有解」，**单独不构成上界**。
- n=9 的 **红度 ≤ 3 变体**跑完了：`nodes=1920213, count=0, capped=False`。剪枝合法性来自引理 L（程序 docstring 有散文证明，本报告第 5 条复述其内容）：干净着色每点红度必 ≤ 3，所以被剪掉的分支里不可能有干净解。于是「剪枝后的空间被完整枚举且计数为 0」＋「剪枝不丢解」⇒ K_9 上不存在干净着色，即上界 R(3,4) ≤ 9。
- 剪枝的经验旁证（不是证明）：n=7 与 n=8 上 plain 与红度受限两路的干净着色数逐一相等（13842 = 13842，17640 = 17640，`agree=True`），说明在这两个能完整对照的规模上剪枝没吃掉解。引理 L 本身是散文证明，代码里的这一条只是自洽性检查。

**边界处理。** n 的上界是 9：n ≤ 8 由 plain 完整枚举覆盖（其中 n=8 给出见证），n=9 由上界一侧覆盖（剪枝后完整枚举计数 0）。命题不需要 n ≥ 10：R(3,4) = 9 的两侧就由「K_8 有干净着色」与「K_9 无干净着色」闭合。

**自校准。** 同一套 DFS 跑 (红 K_3, 蓝 K_3)：n=5 得 12 个无单色三角形着色（>0，已知），n=6 得 0 且未触顶（已知 R(3,3)=6）——两档都与已知答案吻合，说明代码不是静默错的。

**已知局限（如实记）。** ① 引理 L 的合法性来自散文证明 + n=7,8 的经验对账，未在代码里被独立形式化验证；若引理 L 为假，则 n=9 上界那一档不成立。② plain n=9 搜索触顶，不构成独立第二证据。③ 以上都是这台脚本这一次运行的读数，重跑请用上面的复现命令。

## 运行环境

Python 3.11.4；exit_code=0；runtime=7.172s

作者：E
