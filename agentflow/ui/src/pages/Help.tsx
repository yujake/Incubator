/*
 * 使用说明（业主 2026-10-12：「完善 Web UI（使用说明、设置窗口、接线完整），
 * 特别照顾体验感与对多智能体系统的监控能力」）。
 *
 * 这一页刻意**不调任何端点**：它讲的是"其余七页各自在看什么、要动手时该做什么"，
 * 而每一页自己都会把当刻的盘上读数摆出来。说明文写死在页面里，是因为它讲的是
 * 这套系统的**用法**（角色分工、预算、开关、报错去哪看），不是盘上会变的读数。
 *
 * 一条自律：这一页里出现的每一条命令都必须是真在跑的动词与参数
 * （`agentflow --help` 与 `python -m agentflow <动词> --help` 是它们的唯一出处）。
 */
import { Card } from "../components/Card";

/** 一行"命令 + 一句人话"。 */
interface CmdRow {
  cmd: string;
  why: string;
}

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
    why: "优雅停：落一个停机开关，在飞的那一趟在下一个检查点收工（本页「在飞」能看到它）",
  },
  {
    cmd: "agentflow --root <工作区> stop --force",
    why: "直接停：连子孙进程一起杀（不可逆，页面上要两次确认）",
  },
  {
    cmd: "agentflow --root <工作区> status-report",
    why: "写一份状态报告（落 STATUS-<时间>.md/.json，本页「状态报告」那一栏就是它）",
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
    why: "设一个总额度（旧总额记进历史；第一次设预算用它）",
  },
  {
    cmd: "agentflow --root <工作区> budget --add 2 --note '让它跑完'",
    why: "追加一笔（运行期生效：下一次花钱之前的那个闸门就现读到新上限，不用重启）",
  },
];

export function Help() {
  return (
    <>
      <Card title="这是什么">
        <div class="readings">
          一套面向数学研究的多智能体协同框架：十个角色（A–H、V、M）各有分工，
 主控 M 决定派谁做什么，其余角色由它唤起。每一步都是模型说的、框架执行的——
          框架负责把"谁在什么时候做了什么、成没成、为什么没成"如实落盘，
          这一页旁边的七页读的就是那些盘上事实。
        </div>
        <div class="readings">
          角色一句话：A 检索并登记文献 · B 抽概念建关系 · C 算图与计数（只读）·
          D 研究循环（把方向收敛成结论或如实说证据不足）· E 数值实验（没有 Lean 时不做形式化）·
          F 多轮难题攻坚 · G 写稿 · H 审校（只读）· V 证明级验证 · M 主控。
        </div>
      </Card>

      <Card title="七页各自在看什么">
        <div class="readings">
 <b>待回答</b>：盘上有问题在等人回答（答了才继续）。在飞：现在有没有循环/进程在跑、
 盘上有没有停机开关、最近的状态报告与用量拆解。预算：总预算与已花、追加历史、
 按角色与按归口的拆解，以及追加/重设的按钮。证据链：命题、猜想、实验、审校发现、
 关系、验证台账。产物：台账上的产物、交接、验收表、体例检查、稿件。
          **验收**：内容级验收（每一条判据的读数）。**本机**：工具链在哪（含 Lean 开关）、
          模型接线、设置三段 —— 这一页也能改设置。
        </div>
      </Card>

      <Card title="常用命令（真跑的那几条）">
        <div class="readings">
          所有命令的第一个参数是 <span class="mono">--root &lt;工作区&gt;</span>：
 它是全局参数，必须写在子命令前面（写在后面 argparse 会判成"无法识别的参数"）。
          不给就是本仓库的 agentflow/ 目录。
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

      <Card title="预算：不限制步数，只限制钱">
        <div class="readings">
 步数只上报、不强制收工（裁定 12-K）；真正会拦住一趟的是钱：
          每一次花钱之前那道闸门现读额度，扣完时这一趟优雅收尾并落一个停机请求，
          最终读数可能略微越过上限（业主：「可为负一点点，但无大碍」——那一档在
          「预算」页上是"已越上限"这条读数，不是错误）。
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
          没有寄存器也没有命令行上限 ⇒ 不限量（这一档在「预算」页上写得很清楚）。
          寄存器读不出来 ⇒ 闸门退回命令行给的那个上限，并把问题原样显示 ——
          **不折成"不限量"**。
        </div>
      </Card>

      <Card title="Lean 开关（省钱的那一档）">
        <div class="readings">
          形式化验证要装 Lean 与 Mathlib，那是这台机器上最贵的一段。所以有一个开关：
          关掉时全体角色不做形式化（E 的面里没有那一档，"负责形式化"这个说法也不出现），
          论文照样能写到「逐行审阅过的证明，未经机器检查」那一档；打开且装好了才是老套路。
 缺省关闭（省钱）。开关状态在「本机」页上一眼能看见：
          它（<span class="mono">lean_enabled</span>）与"这台机器上装没装"
          （<span class="mono">lean_ready</span>）是两条独立的事实，别混起来读。
        </div>
      </Card>

      <Card title="报错去哪看">
        <div class="readings">
          三态纪律贯穿全站：每个读数都可能处在"算出来了 / 用不着（还没写过）/
 没查成"三档之一，页面把它们分别画成绿 / 灰 / 黄，并附上理由那一句——
          "读不出来"与"读到了、里面是空的"在本系统里是两个词，任何一页都不会把前者
          折成后者。
        </div>
        <div class="readings">
          跑一趟里出的错按三处收集：① 「在飞」页的停机开关与用量（谁被停了、钱花在哪）；
          ② 「产物」与「证据链」页里每一行的三态与理由；③ 会话记录
          <span class="mono">sessions/&lt;会话号&gt;.jsonl</span> 里每一步的
          <span class="mono">problem</span> 与 <span class="mono">detail</span>
          （例如"没等到模型返回（超时）"与"输出预算被思考吃光"是两档不同的失败，
          处置方向相反，所以它们不共用一个码）。
        </div>
        <div class="readings">
 写面（停机 / 入队检索请求 / 改设置 / 改预算）默认关着：要开得用
          <span class="mono">agentflow web --allow-writes</span> 启动服务；
          每一次写尝试（含被拒的）都会追加一行审计，回执里带这次写的三态与理由。
        </div>
      </Card>
    </>
  );
}
