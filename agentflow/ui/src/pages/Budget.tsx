/*
 * 预算窗口（业主 2026-10-12：「做预算设置和显示窗口，用户可追加预算，
 * 运行消耗的钱从总预算里实时扣除，扣完时自动发送优雅停止请求」）。
 *
 * 输入：`api.getBudget()` → `BudgetView`（B 线 `readers.budget_face`：
 * 总额度来自盘上的寄存器 `<工作区>/budget.json`，已花来自 `usage_ledger`）。
 * 写：`postBudget()` → `POST /api/budget`（`action=add|set`，永远带 `confirm=1`）。
 *
 * 这一页上有三条三态纪律，都是"说清是哪一档"：

 * 1. **总额度**：寄存器不在盘上 ⇒ `not_applicable`（还没设过，合法初态）；
 *    寄存器在但读不出来 ⇒ `unreadable` + `problem`（那一档**不是**"不限量"）；
 * 2. **已花**：`spent_tri` 单独一栏 —— 账本读不出来时它是 `unreadable`，
 *    而金额那两栏显 `unknown`，**不许折成 $0.000000**；
 * 3. **抠完为负**：`exceeded` 是读数不是错误（业主：「可能会继续扣成负的一点点，
 *    但无大碍」）—— 剩余为负时显示成一条明确的读数，而不是把它藏起来。
 */
import { useState } from "preact/hooks";

import { api, postBudget, whyOf } from "../api";
import { Badge } from "../components/Badge";
import { Card } from "../components/Card";
import { ConfirmButton } from "../components/ConfirmButton";
import { Money, formatUsd } from "../components/Money";
import { Table, buckets, cell } from "../components/Table";
import { TriState, isUnreadable } from "../components/TriState";
import { useFace } from "../live";

/** 追加历史一行（`budget.reading()` 的 `added[]`）。 */
interface EntryRow extends Record<string, unknown> {
  kind: string;
  usd: number;
  by: string;
  at: string;
  note: string;
}

export function Budget() {
  const face = useFace(() => api.getBudget());
  const [amount, setAmount] = useState("1");
  const [note, setNote] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);

  if (face.data === null) {
    return (
      <Card
        title="预算"
        tone={face.problem === "" ? "plain" : "problem"}
        right={face.problem === "" ? null : <TriState tri="unreadable" reason={face.problem} label="预算面" />}
      >
        <span class="readings">{face.problem === "" ? "正在读盘……" : face.problem}</span>
      </Card>
    );
  }

  const b = face.data;
  const added = b.added as unknown as EntryRow[];
  const byRole = buckets(b.by_role as unknown as Record<string, unknown>);
  const byScope = buckets(b.by_scope as unknown as Record<string, unknown>);
  const parsed = Number(amount);

  const submit = (which: "add" | "set"): void => {
    setBusy(true);
    setResult("");
    postBudget({ action: which, usd: parsed, note })
      .then((got) => {
        setResult(`${got.ok ? "成了" : "没成"}（tri=${got.tri}）：${got.reason}`);
        face.reload();
      })
      .catch((exc: unknown) => {
        setResult(`写请求失败：${whyOf(exc)}`);
      })
      .finally(() => {
        setBusy(false);
      });
  };

  return (
    <>
      <Card
        title="预算"
        subtitle={`来源 ${b.source}`}
        tone={isUnreadable(b.tri) ? "problem" : "plain"}
        right={<TriState tri={b.tri} label="预算面" reason={b.reason} />}
      >
        <div class="readings">
          总预算 <span class="mono">{formatUsd(b.total_usd)}</span> · 已花{" "}
          <Money usd={b.spent_usd} unknownCalls={0} />
          {isUnreadable(b.spent_tri) ? (
            <span class="tri-reason">{b.spent_reason}</span>
          ) : null}
        </div>
        <div class="readings">
          剩余 <span class="mono">{formatUsd(b.remaining_usd)}</span> ·{" "}
          {b.exceeded ? (
            <Badge kind="badge-unknown" text="已越上限" />
          ) : (
            <Badge kind="badge-pass" text="还没越上限" />
          )}
        </div>
        <div class="readings">
          寄存器 <span class="mono">{b.path}</span>（在盘上{" "}
          <span class="mono">{String(b.exists)}</span>）· 历史{" "}
          <span class="mono">{String(b.added_count)}</span> 条 · 账本{" "}
          <span class="mono">{cell(b.entries)}</span> 笔 /{" "}
          <span class="mono">{cell(b.tokens)}</span> tokens
        </div>
        {b.problem === "" ? null : (
          <div class="readings">
            寄存器读不出来：<span class="mono">{b.problem}</span>。
            此项不等于"不限量"：闸门退回到命令行给出的上限。
          </div>
        )}
        {b.source === "unlimited" ? (
          <div class="readings">
            当前无上限：不会因预算停止。可在下方输入金额后选择「重设总额」。
          </div>
        ) : null}
      </Card>

      <Card title="追加 / 重设">
        <div class="readings">
          「追加」在总额上做加法，「重设」直接用给定值覆盖。两者都在下一笔支出前生效。
        </div>
        <div class="readings">
          <label class="opt">
            <span>美元</span>
            <input
              type="text"
              value={amount}
              onInput={(ev) => {
                setAmount(ev.currentTarget.value);
              }}
            />
          </label>
          <label class="opt">
            <span>说明</span>
            <input
              type="text"
              value={note}
              onInput={(ev) => {
                setNote(ev.currentTarget.value);
              }}
            />
          </label>
        </div>
        {/* 两个按钮各占一行：并排时两段 note 会连成一句读不断的长句（R89 实测）。 */}
        <div class="readings">
          <ConfirmButton
            action="追加额度"
            impact={`会把总额改成 ${formatUsd(b.total_usd)} + ${
              Number.isFinite(parsed) ? formatUsd(parsed) : "（读不成数字）"
            }`}
            onConfirm={() => {
              submit("add");
            }}
            disabled={busy || !Number.isFinite(parsed)}
            note={
              !Number.isFinite(parsed)
                ? "金额读不成数字 —— 先改成数字（按钮点不动，也不假装成功）"
                : busy
                  ? "正在写……"
                  : "写面没开（agentflow web --allow-writes）时后端回 403，回执如实显示"
            }
          />
        </div>
        <div class="readings">
          <ConfirmButton
            action="重设总额"
            impact={`会把总额覆盖成 ${
              Number.isFinite(parsed) ? formatUsd(parsed) : "（读不成数字）"
            }（旧总额也记进追加历史）`}
            onConfirm={() => {
              submit("set");
            }}
            disabled={busy || !Number.isFinite(parsed)}
            note={
              !Number.isFinite(parsed)
                ? "金额读不成数字 —— 先改成数字"
                : busy
                  ? "正在写……"
                  : "覆盖式：旧总额只留在追加历史里"
            }
          />
        </div>
        {result === "" ? null : <div class="readings">{result}</div>}
      </Card>

      <Card title="追加历史" subtitle="谁在何时改了多少">
        <Table
          rows={added}
          empty="暂无追加或重设记录。"
          columns={[
            { key: "kind", title: "动作" },
            { key: "usd", title: "美元", render: (r) => <span class="mono">{cell(r.usd)}</span> },
            { key: "by", title: "谁" },
            { key: "at", title: "什么时候", render: (r) => <span class="mono">{r.at}</span> },
            { key: "note", title: "说明",
              render: (r) => (r.note === "" ? "（没写说明）" : r.note) },
          ]}
        />
      </Card>

      <Card title="按角色 / 按归口" subtitle="谁花的、为什么花的">
        <Table
          rows={byRole}
          empty="账本里还没有行（读过、是空的）。"
          columns={[
            { key: "name", title: "角色" },
            { key: "usd", title: "美元", render: (r) => <span class="mono">{r.usd}</span> },
            { key: "tokens", title: "tokens", render: (r) => <span class="mono">{r.tokens}</span> },
            { key: "entries", title: "笔数" },
            { key: "attempts", title: "尝试" },
          ]}
        />
        <Table
          rows={byScope}
          empty="账本里还没有行（读过、是空的）。"
          columns={[
            { key: "name", title: "归口" },
            { key: "usd", title: "美元", render: (r) => <span class="mono">{r.usd}</span> },
            { key: "tokens", title: "tokens", render: (r) => <span class="mono">{r.tokens}</span> },
            { key: "entries", title: "笔数" },
            { key: "attempts", title: "尝试" },
          ]}
        />
      </Card>
    </>
  );
}
