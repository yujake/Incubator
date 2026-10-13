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
          面向数学研究的多智能体协同框架：十个角色（A–H、V、M）各有分工，主控 M 决定派谁做什么。
每一步都由模型决定、由框架执行并落盘；旁边七页读的就是那些盘上事实。
        </div>
        <div class="readings">
          角色一句话：A 检索并登记文献 · B 抽概念建关系 · C 算图与计数（只读）·
          D 研究循环（把方向收敛成结论或如实说证据不足）· E 数值实验（没有 Lean 时不做形式化）·
          F 多轮难题攻坚 · G 写稿 · H 审校（只读）· V 证明级验证 · M 主控。
        </div>
      </Card>

      <Card title="七页各自在看什么">
        <div class="readings">
          <b>待回答</b>：盘上有问题在等人回答。在飞：有没有循环/进程在跑、停机开关、
          最近的状态报告与用量。预算：总预算与已花、追加历史、按角色与归口的拆解。
          证据链：命题、猜想、实验、审校发现、关系、验证台账。产物：台账上的产物、
          交接、验收表、体例检查、稿件。验收：逐条判据的读数。本机：工具链（含 Lean
          开关）、模型接线、设置三段 —— 这一页也能改设置。
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

      <Card title="预算：不限制步数，只限制钱">
        <div class="readings">
        不限制步数，只限制钱：每次支出之前闸门现读额度；扣完时优雅收尾并落停机请求，
总额可能略微越界（「预算」页显示为"已越上限"，是读数而非错误）。
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
      </Card>

      <Card title="Lean 开关（省钱的那一档）">
        <div class="readings">
          形式化验证需安装 Lean 与 Mathlib，是本机最贵的一段，故设开关。关闭时全员不做形式化，
论文仍可写到「逐行审阅过的证明，未经机器检查」档；缺省关闭（省钱）。
<span class="mono">lean_enabled</span>（开关）与 <span class="mono">lean_ready</span>
（本机是否装好）是两条独立事实，见「本机」页。
        </div>
      </Card>

      <Card title="报错去哪看">
        <div class="readings">
          每个读数都处于三档之一：已读出（绿）/ 不适用（灰）/ 未读出（黄），并附原因。
「读不出来」与「读到了、里面是空的」是两个词。
        </div>
        <div class="readings">
          出错看三处：「在飞」的停机开关与用量；「产物」「证据链」每行的三态与理由；
会话记录 <span class="mono">sessions/&lt;会话号&gt;.jsonl</span> 里每一步的
<span class="mono">problem</span> 与 <span class="mono">detail</span>。
        </div>
        <div class="readings">
        写面（起一趟 / 插话 / 叫停 / 改设置 / 改预算）默认关闭，需
<span class="mono">agentflow web --allow-writes</span> 启动；每次写尝试（含被拒）都会记一行审计。
        </div>
      </Card>
    </>
  );
}
