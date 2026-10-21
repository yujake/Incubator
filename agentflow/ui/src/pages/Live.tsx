/*
 * 在飞（业主 2026-10-12：「特别照顾……对多智能体系统的监控能力」）。
 *
 * 输入三条只读端点，各管一件事（分开的理由写在 B 线 `readers.live_face` 的 docstring）：
 *
 * - `api.getLive()` → `LiveView`：**现在有没有人在跑**。会话面（某角色起了没收到工）
 *   与进程面（登记着且真活着的 pid）是两条判据，缺一路都会漏；停机开关与近几条
 *   停机/中断历史一并给出（"我按过停没有、谁按的"只有盘上那份说得清）。
 * - `api.getStatusReports()` → `StatusReportsView`：`out/review/STATUS-*` 最近几份
 *   （`statusreport` 一直在写、此前盘上没有任何读者）。
 * - `api.getUsage()` → `UsageView`：用量台账的汇总（总计 + 按角色 + 按归口）。
 *
 * 三态纪律在这一页上的落点：`answer` 只有三档字面量（"有" / "没有" / "没查成"）——
 * 读不出来时**必须**显"没查成"，不许显"没有"（那会把"没查成"读成"没人跑"，
 * 而用户正要用这一格决定要不要叫停）。
 *
 * ## 2026-10-21（业主的「名册监视」）：这一页多了第四张卡 —— 名册树
 * 用户端此前没有任何地方看得到"谁是谁的子、每个子代理的绝对编号与名册名"：名册的
 * 真身（`out/roster/<父编号>.jsonl`）在盘上，而页面只有 `/api/live` 那一份"谁在跑"。
 * 现在这一页接上 `api.getRoster()`（`<RosterPanel />`，实现只有一处）：它既补上
 * 「在飞」那两张表里只有角色名、没有绝对编号的缺口，也把父→子那一层摆出来。
 * 为什么落在这里而不是新开一页：监控面的问题是"现在有谁在跑、谁是谁的子"，两件事
 * 在同一屏才读得通（另开一页=让人来回对号）。
 */
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { Money } from "../components/Money";
import { RosterPanel } from "../components/Roster";
import { Table, cell } from "../components/Table";
import { StopButtons } from "../components/Stop";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";

/** `running_loops()` 的一行（逐字透传 stopctl 的字典）。 */
interface LoopRow extends Record<string, unknown> {
  role: string;
  sid: string;
  since: string;
}

/** `live_pids()` 的一行。 */
interface PidRow extends Record<string, unknown> {
  pid: number;
  role: string;
  sid: string;
  started_at: string;
}

interface ReportRow extends Record<string, unknown> {
  name: string;
  json_path: string;
  bytes: number | null;
  ts: string;
}

interface BucketRow {
  name: string;
  usd: string;
  tokens: string;
  entries: string;
}

function buckets(rec: Record<string, unknown>): BucketRow[] {
  return Object.keys(rec)
    .sort()
    .map((name) => {
      const one = (rec[name] ?? {}) as Record<string, unknown>;
      return {
        name,
        usd: cell(one.usd),
        tokens: cell(one.tokens),
        entries: cell(one.entries),
      };
    });
}

export function Live() {
  const liveFace = useFace(() => api.getLive());
  const reports = useFace(() => api.getStatusReports());
  const usage = useFace(() => api.getUsage());

  const l = liveFace.data;
  const running = (l?.running ?? []) as unknown as LoopRow[];
  const pids = (l?.live ?? []) as unknown as PidRow[];
  const history = (l?.history ?? []) as unknown as Array<Record<string, unknown>>;
  const interrupts = (l?.interrupts ?? []) as unknown as Array<Record<string, unknown>>;
  const switchState = (l?.switch ?? {}) as Record<string, unknown>;

  return (
    <>
      <Card
        title="在飞"
        subtitle={l === null ? "" : `结论：${l.answer === "" ? "unknown" : l.answer}`}
        tone={l !== null && isUnreadable(l.tri) ? "problem" : "plain"}
        right={
          l === null ? (
            liveFace.problem === "" ? null : <TriState tri="unreadable" reason={liveFace.problem} label="在飞面" />
          ) : (
            <TriState tri={l.tri} label="在飞面" reason={l.reason} />
          )
        }
      >
        {l === null ? (
          <span class="readings">{liveFace.problem === "" ? "正在读盘……" : liveFace.problem}</span>
        ) : (
          <>
            {l.unreadable_sessions.length > 0 ? (
              <div class="readings">
                这些会话读不出来：
                <span class="mono">{l.unreadable_sessions.join("、")}</span>
              </div>
            ) : null}
            <Table
              rows={running}
              empty="没有在跑的循环。"
              columns={[
                { key: "role", title: "角色", render: (r) => <Badge kind="badge-unknown" text={String(r.role)} /> },
                { key: "sid", title: "会话号", render: (r) => <span class="mono">{r.sid}</span> },
                { key: "since", title: "从什么时候起", render: (r) => <span class="mono">{r.since}</span> },
              ]}
            />
            <Table
              rows={pids}
              empty="进程面：没有登记在盘上且活着的进程。"
              columns={[
                { key: "pid", title: "pid", render: (r) => <span class="mono">{String(r.pid)}</span> },
                { key: "role", title: "角色" },
                { key: "sid", title: "会话号", render: (r) => <span class="mono">{r.sid}</span> },
                { key: "started_at", title: "起于", render: (r) => <span class="mono">{r.started_at}</span> },
              ]}
            />
          </>
        )}
      </Card>

      {/* 名册那一棵树（2026-10-21）：父→子 + 绝对编号 + 深度 + 收件箱积压。
          紧挨着「在飞」那张卡，因为"谁在跑"与"它是谁的子"是同一个问题。 */}
      <RosterPanel />

      <Card
        title="停机开关与历史"
        subtitle="叫停就在这里：下面两个按钮"
        right={
          l === null ? null : (
            <Badge
              kind={l.switch_present ? "badge-fail" : "badge-pass"}
              text={l.switch_present ? "盘上有停机开关" : "盘上没有停机开关"}
            />
          )
        }
      >
        {/* 业主 2026-10-13：「网页中没找到停机开关」——它此前只长在「一趟详情」里，
            而人要叫停时待的往往是这一页。现在这一页就是它的落点：先给一句导引，
            再给同一对按钮（`components/Stop.tsx`，与「一趟详情」共用）。 */}
        <div class="readings">
          叫停的落点是工作区 <span class="mono">runs/</span> 下那一个跨进程开关：在飞的循环
          在下一个检查点读到它就收工，把已做过的事留在台账与会话记录里。
          <b>要停就按下面那对按钮</b>（优雅停 / 强制停），「一趟详情」页里是同一对。
        </div>
        {l === null ? null : <StopButtons onDone={() => liveFace.reload()} />}
        {l === null ? null : (
          <>
            <div class="readings">
              停机开关：
            </div>
            {l.switch_present ? (
              <Table
                rows={[switchState]}
                empty="（开关在盘上但读成了空对象 —— 这一档本身是读数）"
                columns={[
                  { key: "by", title: "谁按的" },
                  { key: "reason", title: "理由码" },
                  { key: "at", title: "什么时候", render: (r) => <span class="mono">{cell(r.at)}</span> },
                  { key: "force", title: "force" },
                ]}
              />
            ) : (
              <div class="readings">盘上没有停机开关。</div>
            )}
 <div class="readings">近几条停机历史（runs/stop-history.jsonl）：</div>
            <Table
              rows={history}
              empty="还没有停机历史。"
              columns={[
                { key: "at", title: "什么时候", render: (r) => <span class="mono">{cell(r.at)}</span> },
                { key: "by", title: "谁" },
                { key: "reason", title: "理由" },
                { key: "level", title: "档" },
              ]}
            />
            <div class="readings">近几条中断（父叫停子代理那一档）：</div>
            <Table
              rows={interrupts}
              empty="还没有中断记录。"
              columns={[
                { key: "at", title: "什么时候", render: (r) => <span class="mono">{cell(r.at)}</span> },
                { key: "task_id", title: "台账号", render: (r) => <span class="mono">{cell(r.task_id)}</span> },
                { key: "by", title: "谁" },
              ]}
            />
          </>
        )}
      </Card>

      <Card
        title="状态报告"
        subtitle={reports.data === null ? "" : `共 ${cell(reports.data.count)} 份`}
        right={
          reports.data === null ? (
            reports.problem === "" ? null : <TriState tri="unreadable" reason={reports.problem} label="状态报告" />
          ) : (
            <TriState tri={reports.data.tri} label="状态报告" reason={reports.data.reason} />
          )
        }
      >
        {reports.data === null ? (
          <span class="readings">{reports.problem === "" ? "正在读盘……" : reports.problem}</span>
        ) : (
          <>
            <div class="readings">
 落点 <span class="mono">{reports.data.dir}</span>（STATUS-&lt;时间&gt;.md/.json）。
            </div>
            <Table
              rows={(reports.data.reports ?? []) as unknown as ReportRow[]}
              empty="暂无状态报告。"
              columns={[
                { key: "ts", title: "时间戳", render: (r) => <span class="mono">{r.ts}</span> },
                { key: "name", title: "文件", render: (r) => <span class="mono">{r.name}</span> },
                { key: "bytes", title: "字节", render: (r) => <span class="mono">{cell(r.bytes)}</span> },
                { key: "json_path", title: "JSON", render: (r) => <span class="mono">{r.json_path === "" ? "（没有）" : "有"}</span> },
              ]}
            />
          </>
        )}
      </Card>

      <Card
        title="用量"
        subtitle={usage.data === null ? "" : `账本 ${cell(usage.data.entries)} 笔`}
        right={
          usage.data === null ? (
            usage.problem === "" ? null : <TriState tri="unreadable" reason={usage.problem} label="用量" />
          ) : (
            <TriState tri={usage.data.tri} label="用量" reason={usage.data.reason} />
          )
        }
      >
        {usage.data === null ? (
          <span class="readings">{usage.problem === "" ? "正在读盘……" : usage.problem}</span>
        ) : (
          <>
            <div class="readings">
              合计 <Money usd={null} unknownCalls={0} />{" "}
              {Object.keys(usage.data.spent).length === 0 ? null : (
                <span class="mono">
                  {cell(usage.data.spent.entries)} 笔 · {cell(usage.data.spent.tokens)} tokens
                </span>
              )}
            </div>
            <div class="readings">
              （合计那两栏在上面的「预算」页里有金额读数；这一页给的是按角色与按归口的
              拆解 —— 谁花的、为了什么花的。）
            </div>
            <Table
              rows={buckets(usage.data.by_role as unknown as Record<string, unknown>)}
              empty="账本里还没有行。"
              columns={[
                { key: "name", title: "角色" },
                { key: "usd", title: "美元", render: (r) => <span class="mono">{r.usd}</span> },
                { key: "tokens", title: "tokens", render: (r) => <span class="mono">{r.tokens}</span> },
                { key: "entries", title: "笔数" },
              ]}
            />
            <Table
              rows={buckets(usage.data.by_scope as unknown as Record<string, unknown>)}
              empty="账本里还没有行。"
              columns={[
                { key: "name", title: "归口" },
                { key: "usd", title: "美元", render: (r) => <span class="mono">{r.usd}</span> },
                { key: "tokens", title: "tokens", render: (r) => <span class="mono">{r.tokens}</span> },
                { key: "entries", title: "笔数" },
              ]}
            />
          </>
        )}
      </Card>
    </>
  );
}
