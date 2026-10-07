/*
 * 不可逆动作的确认按钮（叫停 / 写设置 / 覆盖 key 都要过它）。
 *
 * 两次确认是这里的全部内容：第一次点击只"上膛"并把影响写给人看，第二次才真的
 * 调 `onConfirm`。`requireForce` 是第二道（`force` 那种"直接杀进程"的动作）：
 * 上膛之后还要勾一个框才允许点第二次。
 *
 * W0 没有任何写端点，所以这个组件还没有被页面用起来 —— 它先在这里，
 * 是为了让 W3 的写面有唯一的入口可走（不许页面自己接一个裸按钮）。
 */
import { useState } from "preact/hooks";

export interface ConfirmButtonProps {
  action: string;
  impact: string;
  onConfirm: () => void;
  requireForce?: boolean;
}

export function ConfirmButton(props: ConfirmButtonProps) {
  const [armed, setArmed] = useState(false);
  const [forced, setForced] = useState(false);
  const blocked = armed && props.requireForce === true && !forced;

  if (!armed) {
    return (
      <button
        class="btn"
        type="button"
        onClick={() => {
          setArmed(true);
        }}
      >
        {props.action}
      </button>
    );
  }
  return (
    <span class="tri">
      <span class="readings">{props.impact}</span>
      {props.requireForce === true ? (
        <label class="opt">
          <input
            type="checkbox"
            checked={forced}
            onChange={(ev) => {
              setForced(ev.currentTarget.checked);
            }}
          />
          <span class="readings">我确认这一下是不可逆的</span>
        </label>
      ) : null}
      <button
        class="btn btn-armed"
        type="button"
        disabled={blocked}
        onClick={() => {
          props.onConfirm();
          setArmed(false);
          setForced(false);
        }}
      >
        确认{props.action}
      </button>
      <button
        class="btn"
        type="button"
        onClick={() => {
          setArmed(false);
          setForced(false);
        }}
      >
        取消
      </button>
    </span>
  );
}
