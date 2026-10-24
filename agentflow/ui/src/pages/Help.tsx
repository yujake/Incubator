/*
 * 使用说明（业主 2026-10-12：「完善 Web UI（使用说明、设置窗口、接线完整），
 * 特别照顾体验感与对多智能体系统的监控能力」）。
 *
 * 这一页刻意**不调任何端点**：它讲的是"其余八页各自在看什么、要动手时该做什么"，
 * 而每一页自己都会把当刻的盘上读数摆出来。说明文写死在页面里，是因为它讲的是
 * 这套系统的**用法**（页面分工、名册、三态、退出码、预算、写面），
 * 不是盘上会变的读数。
 *
 * 一条自律：这一页里出现的每一条命令、每一个数字都必须是真在跑的动词、真在用的
 * 常量 —— 出处逐条写在旁边（`cli.py` 的 `EXIT_CODE_BY_STOP`、`budget.py` 的
 * `total_usd`、`readers.py` 的 `ROUTES` 与 `ROSTER_NODES_MAX`）。
 * 判据 `tests/test_webui_help_is_current.py` 钉着其中五条（名册 / 三态 / 退出码 /
 * 预算 / 写面，逐节一条），改坏一条就红。
 */
import { Card } from "../components/Card";

/** 一行"命令 + 一句人话"。 */
interface CmdRow {
  cmd: string;
  why: string;
}

/** 一页"读哪条端点 + 回答什么问题"。 */
interface PageRow {
  page: string;
  reads: string;
  answers: string;
}

/** 一档退出码。 */
interface ExitRow {
  code: string;
  meaning: string;
  when: string;
}

/** 一条常见误解。 */
interface MisreadRow {
  wrong: string;
  right: string;
}

const OPEN: CmdRow[] = [
  {
    cmd: "python -m agentflow.cli --root <工作区> web",
    why: "起用户端网页（默认只监听本机）。--root 是全局参数，必须写在 web 之前 —— 写在后面 argparse 会拒，退出码 2",
  },
  {
    cmd: "python -m agentflow.cli --root <工作区> web --port 0 --json",
    why: "让系统给一个空闲端口，只打印一行 URL 的 JSON —— 起后台任务时用它拿确切地址",
  },
  {
    cmd: "python -m agentflow.cli --root <工作区> web --open",
    why: "起来之后用默认浏览器打开那一页",
  },
  {
    cmd: "python -m agentflow.cli --root <工作区> web --allow-writes",
    why: "打开写面（缺省只读）：起一趟 / 插话 / 叫停 / 改设置 / 改预算 / 预热提示词缓存都走这一档；答问除外 —— POST /answer 是既有写路径，不进那张授权矩阵，缺省也放行",
  },
  {
    cmd: "python -m agentflow.cli --root <工作区> web --no-settings-write",
    why: "只关掉「本机」页的设置写面，其余写面照旧",
  },
  {
    cmd: "python -m agentflow.cli --root <工作区> web --token <口令>",
    why: "给访问口令（也可用环境变量 AGENTFLOW_WEB_TOKEN）；给了就必须带上",
  },
];

const RUNS: CmdRow[] = [
  {
    cmd: "agentflow --root <工作区> init",
    why: "建一个工作区（data/ 与 library/ 落盘；其余目录用到时才建）",
  },
  {
    cmd: "agentflow --root <工作区> run-agent M --task '<一句话任务>' --sid <会话号>",
    why: "真跑一趟：主控 M 决定派谁做什么，其余角色由它唤起（会话号用来续跑与查账）",
  },
  {
    cmd: "agentflow --root <工作区> run-agent M --task '<同一句话>' --sid <会话号> --resume",
    why: "从检查点续跑（任务指纹不一致会被拒 —— 拿 A 的进度续 B 是另一件事）",
  },
  {
    cmd: "agentflow --root <工作区> stop --reason user",
    why: "优雅停：落一个停机开关，在飞的那一趟在下一个检查点收工（「在飞」页能看到它）",
  },
  {
    cmd: "agentflow --root <工作区> stop --force",
    why: "直接停：连子孙进程一起杀（不可逆，页面上要先过一道确认）",
  },
  {
    cmd: "agentflow --root <工作区> status-report",
    why: "写一份状态报告（落 STATUS-<时间>.md/.json，「在飞」页的「状态报告」那一栏就是它）",
  },
  {
    cmd: "agentflow --root <工作区> verify",
    why: "一致性审计（不看它，台账里的矛盾不会有任何地方报出来）",
  },
];

const BUDGET: CmdRow[] = [
  {
    cmd: "agentflow --root <工作区> budget --status",
    why: "看这一趟的总预算 / 已花 / 剩余 / 追加历史（三态：没设过 ≠ 读不出来）",
  },
  {
    cmd: "agentflow --root <工作区> budget --set 5",
    why: "设一个总额度（覆盖式：这一笔按 set 记进追加历史，旧的那几笔不删；第一次设预算用它）",
  },
  {
    cmd: "agentflow --root <工作区> budget --add 2 --note '让它跑完'",
    why: "追加一笔（运行期生效：下一次花钱之前的那个闸门就现读到新上限，不用重启）",
  },
];

/** 九页（`main.tsx` 的 `ROUTES` 九条；顺序 = 顶部导航的顺序，`/run/:sid` 跟在首页后面）。 */
const PAGES: PageRow[] = [
  {
    page: "对话（/）",
    reads: "GET /api/state（共享快照）· /api/chat · /api/live",
    answers: "主控在问什么、团队说到哪；这一句话会走到哪（回答 / 插话 / 续跑 / 起一趟），动笔前先在按钮旁说清",
  },
  {
    page: "一趟详情（/run/会话号）",
    reads: "GET /api/run/{sid} · /api/run-index · /api/run/{sid}/events · /api/live",
    answers: "这一趟走到哪、花了多少（检查点与事件求和并排）、逐条事件、交付说明、停机开关",
  },
  {
    page: "在飞（/live）",
    reads: "GET /api/live · /api/status-reports · /api/usage · /api/roster",
    answers: "现在有没有人在跑、盘上有没有停机开关、最近的状态报告与用量、整棵名册树",
  },
  {
    page: "预算（/budget）",
    reads: "GET /api/budget",
    answers: "总额度 / 已花 / 剩余 / 追加历史，外加按角色与按归口的拆解；这一页也能追加或重设",
  },
  {
    page: "证据链（/evidence）",
    reads: "GET /api/evidence",
    answers: "命题（含非平凡度 T0–T4 / 未判、五元位五位各一格：numeric / proof / "
      + "reviewed 按证明逐条 / formal 按路径 / audited）、猜想、实验（「报告」一列链到 "
      + "out/experiments/<号>/exhaustion.md）、审校发现、引文回验（五档，含 no_evidence）、"
      + "证明级验证（reviewed 按证明逐条、证明一致性而非 sha 原文）、秘书决策 —— "
      + "七栏各带自己的三态",
  },
  {
    page: "产物（/artifacts）",
    reads: "GET /api/artifacts",
    answers: "九张卡（数字与标题同数 ARTIFACT_CARDS；第九张是实验产物的落点）："
      + "台账上的产物与一致性对账（一致 / 不一致 / unknown，sha 原文不上屏）、"
      + "台账写入笔数与 commit 标记两格、交接手稿、验收表的机器可判行、体例、任务结果、"
      + "实验产物落点（code/exp 与 out/experiments/<号>/{design,exhaustion}.md）",
  },
  {
    page: "验收（/acceptance）",
    reads: "GET /api/acceptance（可带 ?cap_usd=）",
    answers: "五条判据 + 五种辅助读数，逐条 pass / fail / unknown（第三档是没查成，不是通过）",
  },
  {
    page: "本机（/machine）",
    reads: "GET /api/machine",
    answers: "工具链（含 Lean 开关）、模型接线、设置三段 —— 这一页也能改设置、翻开关",
  },
  {
    page: "使用说明（/help）",
    reads: "一条端点都不调",
    answers: "就是本页：九页分工、名册、三态、退出码、预算、写面",
  },
];

/** 退出码六档（`cli.EXIT_CODE_BY_STOP` 归的档，不是 `if` 链）。 */
const EXITS: ExitRow[] = [
  {
    code: "0",
    meaning: "正常完成",
    when: "给了结论（stop_reason=final）",
  },
  {
    code: "1",
    meaning: "行为异常",
    when: "没接线 / 模型没认 key / 没返回 / 连不上 / 输出吃光 / 坏 JSON 或坏参数超限 / 没 notify，以及任何没登记的新 reason（没登记一律归 1）",
  },
  {
    code: "2",
    meaning: "研究启动失败",
    when: "检查点读不到、任务指纹不符、上一趟已收工、会话记录里重建不出那一步 —— 一步模型都没调就交回去了",
  },
  {
    code: "3",
    meaning: "等待用户",
    when: "问了人、停在等回答；人答完（agentflow answer）之后用 --resume 接着跑",
  },
  {
    code: "4",
    meaning: "正常且中途停止",
    when: "用户叫停（强停与优雅停）、父叫停、预算耗尽；加预算或人答完即可 --resume",
  },
  {
    code: "5",
    meaning: "正常且自行停止，但没有 final",
    when: "原地打转（同调用 + 同读数连击到上限）、escalated 交给召唤者",
  },
];

const MISREADS: MisreadRow[] = [
  {
    wrong: "页面显示 0，就是什么都没有",
    right: "只有 computed 档的 0 才算「读到了、里面是 0」。unreadable / not_applicable 两档的计数栏是 null —— 那是「没读到」，不是「没有」。",
  },
  {
    wrong: "名册是空的，说明没有子代理",
    right: "名册面板给出 answer=unknown，说的是「名册没读到」（目录不在 / 一个名册文件都没有 / 读不出来 / 有一条读不出来）。名册只在有人被派活时才落盘，后端给 count=null（一行都没读到）或只读到的那几个（读到一部分），而不是 0。",
  },
  {
    wrong: "退出码不是 0，就是坏了",
    right: "3 / 4 / 5 都是正常形态：停在等人、被叫停（含预算耗尽）、它自己判定收工。只有 1 是行为异常。",
  },
  {
    wrong: "不设预算，就是不许花钱",
    right: "不设 = 无限制（source=unlimited）。要限制就显式设一个数：传多少就是多少，累计制。",
  },
  {
    wrong: "写面默认关着，说明网页还接不了线",
    right: "八条 POST 全在路由表里（/answer、/api/stop、/api/submit、/api/settings、/api/budget、/api/run、/api/task、/api/cache/warm）；缺省只读是因为服务端要 --allow-writes 才放行（/api/ 下那七条写端点如此；/answer 是既有写路径、缺省也放行），不是没接线。",
  },
];

export function Help() {
  return (
    <>
      <Card title="这是什么">
        <div class="readings">
          面向数学研究的多智能体协同框架：十一个角色（A–H、V、L、M）各有分工，主控 M 决定派谁做什么。
每一步都由模型决定、由框架执行并落盘；旁边八页读的就是那些盘上事实（加上本页一共九页）。
        </div>
        <div class="readings">
          角色一句话：A 检索并登记文献 · B 抽概念建关系 · C 算图与计数（只读）·
          D 研究循环（把方向收敛成结论或如实说证据不足）· E 数值实验（形式化不归它）·
          F 多轮难题攻坚 · G 写稿 · H 审校（只读）· V 证明级验证（只读）·
          L 形式化验证（把 B 登记的那条命题忠实搬进 Lean 真跑，只写形式化实验那一格）· M 主控。
        </div>
      </Card>

      <Card title="怎么开（网页只读是缺省，写面要显式打开）">
        <div class="readings">
          一条命令起网页：
          <span class="mono">python -m agentflow.cli --root &lt;工作区&gt; web</span>
          。下文命令表里的 <span class="mono">agentflow</span> 与 <span class="mono">python -m agentflow.cli</span>
          是同一个入口（<span class="mono">pyproject.toml</span> 的 <span class="mono">[project.scripts]</span>）；
          没装包时用后者。
        </div>
        <table class="table">
          <thead>
            <tr>
              <th>命令</th>
              <th>它在做什么</th>
            </tr>
          </thead>
          <tbody>
            {OPEN.map((row) => (
              <tr key={row.cmd}>
                <td>
                  <span class="mono">{row.cmd}</span>
                </td>
                <td>{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div class="readings">
          写面现状：八条 POST 已全部接线 ——
          <span class="mono">POST /answer</span>（答问）·
          <span class="mono">/api/stop</span>（叫停）·
          <span class="mono">/api/submit</span>（提交检索请求）·
          <span class="mono">/api/settings</span>（改设置）·
          <span class="mono">/api/budget</span>（改预算）·
          <span class="mono">/api/run</span>（起一趟）·
          <span class="mono">/api/task</span>（插话）·
          <span class="mono">/api/cache/warm</span>（预热提示词缓存）。没有「登记了还没落地」的写端点。
        </div>
        <div class="readings">
          授权次序是四层：回环来源 ⇒ CSRF 令牌 ⇒ <span class="mono">--allow-writes</span> ⇒
          （只有改设置才要）设置写面 —— 这四层管的是 <span class="mono">/api/</span>
          下那七条写端点；<span class="mono">POST /answer</span> 是既有写路径，不进那张矩阵（只落审计）。
          每一次到达写端点的尝试（含被拒）都追加一行
          <span class="mono">web-actions.jsonl</span>；<span class="mono">/api/</span>
          下未注册的路径回 404，那一类不算一次写尝试。
        </div>
      </Card>

      <Card title="九个页面各看什么">
        <table class="table">
          <thead>
            <tr>
              <th>页</th>
              <th>读哪些端点</th>
              <th>它回答什么问题</th>
            </tr>
          </thead>
          <tbody>
            {PAGES.map((row) => (
              <tr key={row.page}>
                <td>
                  <span class="mono">{row.page}</span>
                </td>
                <td>
                  <span class="mono">{row.reads}</span>
                </td>
                <td>{row.answers}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div class="readings">
          全站只订阅一次 <span class="mono">GET /api/stream</span>（SSE），九页共享那份快照与连接态；
          每一页再各取自己那几条端点，于是「盘上新增 ⇒ 流里出现 ⇒ 页面重取」这条链是通的。
          「一趟详情」要从首页的「会话概览」里点进来，顶部导航里没有它。
        </div>
      </Card>

      <Card title="名册怎么读（树 / 绝对编号 / 深度 / 收件箱三格）">
        <div class="readings">
          真身在盘上：<span class="mono">out/roster/&lt;父编号&gt;.jsonl</span> ——
          一个父一份名册，文件里每一行是一个子；文件名就是父的绝对编号。
          「在飞」页里那张卡读 <span class="mono">GET /api/roster</span>（只读：路由表里没有配对的 POST）。
        </div>
        <div class="readings">
          <b>树</b>：一个 agent 一个节点。后端按前序给（父一定在子前面），左缩进就是
          <span class="mono">depth</span>（根 = 1）。这个深度是"这棵树里的距离"，不是台账里的
          <span class="mono">tasks.depth</span>（全局召唤深度）—— 两者在根就是顶趟时相等，其余情况差一个常数。
        </div>
        <div class="readings">
          <b>绝对编号</b>：<span class="mono">task_id</span> 是这一套的主键（形如
          <span class="mono">t-000002</span>）；名册名 <span class="mono">name</span> 一经退役永久不复用，
          根不在任何人的名册里 ⇒ 它的名字是空串（面板写"顶层·无名册名"）。
        </div>
        <div class="readings">
          <b>收件箱</b>：<span class="mono">data/tasks.json</span> 里
          <span class="mono">parent_task_id</span> 指向这个节点、且
          <span class="mono">item_state</span> 不是 <span class="mono">done</span> 的板项。
          三格分开给：<span class="mono">unread</span>（queued + claimed：还没被读进任何一步）、
          <span class="mono">seen_not_acked</span>（seen：读了、还缺一个 ack）、
          <span class="mono">open_total</span>（未消总数 = 未读 + 已读未 ack + 状态读不出来的那些）。
          徽标写「未读 N · 已读未 ack M」——「他还没看」与「他看了但框架没让他 ack」
          是两件事，合成一个"积压"数会让它在正常流程下只涨不落。
          点开节点能看按状态与按种类的分布，
          一个节点最多列 10 条（<span class="mono">ROSTER_INBOX_ITEMS</span>），正文截到 160 字，
          剩下几条写在 <span class="mono">inbox.more</span> 里。
        </div>
        <div class="readings">
          节点的状态与"在飞"来自 <span class="mono">data/tasks.json</span> 的实例行
          （<span class="mono">pending</span> / <span class="mono">running</span> 算在飞）；
          节点上限 500（<span class="mono">ROSTER_NODES_MAX</span>），超了置
          <span class="mono">truncated=true</span>。面板底下那一行「对账」把台账里的代理行、名册上的节点、
          以及"有父但不在任何名册里"的行（名册机制上线之前落的）三个数摆在一起。
        </div>
      </Card>

      <Card title="容易读混的六格读数（未读 / 板项与在飞 / 待答 / 台账写入 / 会话事件条数 / 宿主进程 pid）">
        <div class="readings">
          <b>收件箱徽标</b>：写 <span class="mono">未读 N · 已读未 ack M</span>
          （没有未消条目时写「收件箱：没有未消的条目」；读不到时写「收件箱：未读到」）。
          <span class="mono">unread</span> 是还没被读进任何一步的（<span class="mono">queued</span> +
          <span class="mono">claimed</span>），<span class="mono">seen_not_acked</span> 是读了、
          缺的是那个 ack。点开节点另给三格：未读 / 已读未 ack / 未消（<span class="mono">open_total</span>），
          外加「其中状态读不出来 N 条」（词表外的行单列，不并进前两格）。
        </div>
        <div class="readings">
          <b>板项与在飞不能混算</b>：板项行是 <span class="mono">kind</span> 非空、
          <span class="mono">item_state</span> 不是 <span class="mono">done</span> 的那些行；
          「在飞」看的是实例行（<span class="mono">kind</span> 为空、<span class="mono">status</span>
          是 <span class="mono">pending</span> / <span class="mono">running</span>）。
          状态报告那一栏的「在飞」只数实例行：不分开数会把「板上有十几条要消的项」写成「在飞十几」。
        </div>
        <div class="readings">
          <b>待答两处同一个数</b>：首页会话概览那一列与「说一句」那张卡的副标题都写
          <span class="mono">（全局待答清单）</span>，取的是同一份清单
          （<span class="mono">/api/state</span> 的 <span class="mono">pending_questions</span>），
          不按当前选中的会话过滤 —— 别的会话在等人回答也是事实，而且 <span class="mono">qid</span>
          只在会话内唯一，所以每一条各自带着自己的会话号提交。
        </div>
        <div class="readings">
          <b>台账写入笔数 ≠ 事件文件行数</b>：首页那张台账卡写
          <span class="mono">台账写入 N 笔（其中 commit 标记 M 行）</span>。
          每提交一次事务写两行（一行事件 + 一行 <span class="mono">op=commit</span> 的提交标记），
          所以 <span class="mono">N + M</span> 才是 <span class="mono">data/events.jsonl</span>
          的总行数；<span class="mono">N</span> 回答的是「写了多少笔」。读不成 JSON 的坏行按行计入
          <span class="mono">N</span>，并在下面那句说明里单独点名；台账文件不在盘上时两格都是
          <span class="mono">unknown</span>（不是 0）。
        </div>
        <div class="readings">
          <b>两种「条数」不是一回事</b>：首页「会话概览」那一列逐字是
          <span class="mono">事件条数（会话）</span> —— 它数的是这一段会话自己的事件条数
          （<span class="mono">sessions/&lt;会话号&gt;.jsonl</span> 里的行数，
          <span class="mono">events_seen</span>），每段各从 0 起数，别的段不算；
          下面「台账」那张卡里的「台账写入 N 笔」数的是整个工作区的写入事务
          （<span class="mono">upserts</span>），commit 标记行另计。两个数并排摆着、
          名字又只差一个字，很容易拿一个去核另一个 —— 于是 2026-10-23 起列名写成
          「事件条数（会话）」：它回答「这一段说了多少」，台账那一格回答「整个工作区
          落了多少笔」。两者不相等不是缺陷，是两把尺子。
        </div>
        <div class="readings">
          <b>进程面那一列是宿主进程的 pid</b>：「在飞」页进程面的列名逐字是
          <span class="mono">宿主进程 pid</span>，表头上方那句说明写的是同一件事 ——
          同一趟 run 里所有角色共用同一个宿主进程，所以多行会印出同一个号。
          要分辨「这一行是谁」看角色与会话号；绝对的 <span class="mono">task_id</span>
          在名册那张卡里。
        </div>
      </Card>

      <Card title="三态与「没读到」的语义（这一节最要紧）">
        <table class="table">
          <thead>
            <tr>
              <th>读数</th>
              <th>它说的是什么</th>
              <th>计数栏</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <span class="mono">computed</span>
              </td>
              <td>已读出：源读到了。数字是真的，可以是 0（读到了，只是里面一行都没有）。</td>
              <td>真数字</td>
            </tr>
            <tr>
              <td>
                <span class="mono">not_applicable</span>
              </td>
              <td>不适用：这个工作区还没有那一族数据（还没写过）。合法初态，不是出错。</td>
              <td>
                <span class="mono">null</span>，不是 0
              </td>
            </tr>
            <tr>
              <td>
                <span class="mono">unreadable</span>
              </td>
              <td>未读出：源在盘上但读不出来（坏 JSON / 无权限 / 把目录当文件读）。</td>
              <td>
                <span class="mono">null</span> + 一句 reason
              </td>
            </tr>
          </tbody>
        </table>
        <div class="readings">
          <b>「没读到」不等于「没有」</b>：页面把每一格的三态与 reason 原样摆出来，
          只有 computed 档的 0 才读成"没有"。名册那条端点另用一套字：
          <span class="mono">answer="ok"</span>（名册真读成了）/
          <span class="mono">answer="unknown"</span>（名册没读到 —— 目录不在、目录里一个名册文件都没有、
          目录读不出来、有一条读不出来，这些都算），此时 <span class="mono">count</span>
          一行都没读到时是 <span class="mono">null</span>、只读到一部分时是那一部分的真数字
          —— 不是 0。「在飞」面同理：它的
          <span class="mono">answer</span> 只有「有」/「没有」/「没查成」三档，读不出来时显"没查成"，
          不许显"没有"。
        </div>
        <div class="readings">
          另外两套词表各自独立，不许互相顶替：交付说明走
          <span class="mono">ok</span> / <span class="mono">missing</span> /
          <span class="mono">unknown</span>（「一趟详情」那一栏）；验收判据走
          <span class="mono">pass</span> / <span class="mono">fail</span> /
          <span class="mono">unknown</span>（第三档 = 没查成，不是通过 —— 不给
          <span class="mono">cap_usd</span> 时「在成本上限内」那一格就是它）。
        </div>
        <div class="readings">
          报错看三处：「在飞」的停机开关与用量；「产物」「证据链」每行的三态与理由；
          会话记录 <span class="mono">sessions/&lt;会话号&gt;.jsonl</span> 里每一步的
          <span class="mono">problem</span> 与 <span class="mono">detail</span>。
        </div>
      </Card>

      <Card title="退出码六档（一趟 run-agent 为什么停）">
        <table class="table">
          <thead>
            <tr>
              <th>退出码</th>
              <th>含义</th>
              <th>什么时候</th>
            </tr>
          </thead>
          <tbody>
            {EXITS.map((row) => (
              <tr key={row.code}>
                <td>
                  <span class="mono">{row.code}</span>
                </td>
                <td>{row.meaning}</td>
                <td>{row.when}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div class="readings">
          口径只有一张表（<span class="mono">cli.EXIT_CODE_BY_STOP</span>）：没登记的
          <span class="mono">stop_reason</span> 一律归 1，不许归 0 —— 把"新增了一档而没人归类"读成"做完了"
          是最贵的一种错。<span class="mono">--rounds N</span> 那条多轮路径查同一张表，只多两档：
          轮数用完且最后一轮给了 final ⇒ 0，没给 ⇒ 5；续跑发现这一程已跑完 ⇒ 0。
        </div>
      </Card>

      <Card title="预算怎么算（不限制步数，只限制钱）">
        <div class="readings">
          寄存器是工作区里那一份 <span class="mono">budget.json</span>：只有一格额度
          <span class="mono">total_usd</span>（外加 append-only 的
          <span class="mono">added[]</span> 追加历史）。它只回答一个问题：这一趟的总预算上限是多少。
        </div>
        <div class="readings">
          <b>不传 = 无限制</b>：不设寄存器、也不给命令行上限（<span class="mono">--budget-usd</span> /
          <span class="mono">--fallback-usd</span>）⇒ 上限是 None（读数里
          <span class="mono">source=unlimited</span>），不会因预算停止。
          <b>传多少就是多少</b>：给了多少，上限就是多少。
          <b>累计制</b>：<span class="mono">total_usd</span> 是总额度，已花取
          <span class="mono">usage_ledger</span> 的累计（唯一权威账），剩余 = 总额度 − 已花。
        </div>
        <div class="readings">
          每次支出之前闸门现读额度；扣完时优雅收尾并落停机请求，总额可能略微越界
          （「预算」页显示为"已越上限"，是读数而非错误）。追加只增不减；要减只能用
          <span class="mono">--set</span> 显式重设（覆盖式）。
        </div>
        <table class="table">
          <thead>
            <tr>
              <th>命令</th>
              <th>它在做什么</th>
            </tr>
          </thead>
          <tbody>
            {BUDGET.map((row) => (
              <tr key={row.cmd}>
                <td>
                  <span class="mono">{row.cmd}</span>
                </td>
                <td>{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div class="readings">
          寄存器与命令行上限都没设 ⇒ 不限量；寄存器读不出来 ⇒ 退回命令行上限，
          并把原因原样显示，不折成「不限量」。
        </div>
        <div class="readings">
          别把这格和 <span class="mono">cap_usd</span> 混了：<span class="mono">cap_usd</span> 是「验收」页
          给 <span class="mono">GET /api/acceptance</span> 的成本上限（判「在成本上限内」那一格），
          不进预算寄存器，也不参与停机。
        </div>
      </Card>

      <Card title="Lean 开关（省钱的那一档）">
        <div class="readings">
          形式化验证需安装 Lean 与 Mathlib，是本机最贵的一段，故设开关。关闭时全员不做形式化，
 论文仍可写到「逐行审阅过的证明，未经机器检查」档；缺省关闭（省钱）。
<span class="mono">lean_enabled</span>（开关）与 <span class="mono">lean_ready</span>
（本机是否装好）是两条独立事实，见「本机」页。
        </div>
      </Card>

      <Card title="常用命令（真跑的那几条）">
        <div class="readings">
          <span class="mono">--root &lt;工作区&gt;</span> 是全局参数，须写在子命令之前（缺省为本仓库的 agentflow/）。
        </div>
        <table class="table">
          <thead>
            <tr>
              <th>命令</th>
              <th>它在做什么</th>
            </tr>
          </thead>
          <tbody>
            {RUNS.map((row) => (
              <tr key={row.cmd}>
                <td>
                  <span class="mono">{row.cmd}</span>
                </td>
                <td>{row.why}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="常见误解（逐条说清）">
        <table class="table">
          <thead>
            <tr>
              <th>容易读成</th>
              <th>页面上的事实</th>
            </tr>
          </thead>
          <tbody>
            {MISREADS.map((row) => (
              <tr key={row.wrong}>
                <td>{row.wrong}</td>
                <td>{row.right}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
