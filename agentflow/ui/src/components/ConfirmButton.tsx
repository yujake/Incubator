/*
 * 不可逆动作的确认按钮（叫停 / 写设置 / 覆盖 key 都要过它）。
 *
 * 两次确认是这里的全部内容：第一次点击只"上膛"并把影响写给人看，第二次才真的
 * 调 `onConfirm`。`requireForce` 是第二道（`force` 那种"直接杀进程"的动作）：
 * 上膛之后还要勾一个框才允许点第二次。
 *
 * `disabled` 那一档是三态纪律在按钮上的落点：端点还没上线（C 线 W3/W4）时，
 * 页面必须**点不动**并说清"写面还没落地"，而不是按下去假装成功。
 */
import { useState } from "preact/hooks";

export interface ConfirmButtonProps {
  action: string;
  impact: string;
  onConfirm: () => void;
  requireForce?: boolean;
  /** 端点还没落地（或写面没开）⇒ 按钮点不动；理由写在 `note` 里。 */
  disabled?: boolean;
  note?: string;
}

export function ConfirmButton(props: ConfirmButtonProps) {
  const [armed, setArmed] = useState(false);
  const [forced, setForced] = useState(false);
  const blocked = armed && props.requireForce === true && !forced;

  if (props.disabled === true) {
    return (
      <span class="tri">
        <button class="btn" type="button" disabled>
          {props.action}
        </button>
        {props.note === undefined || props.note === "" ? null : (
          <span class="tri-reason">{props.note}</span>
        )}
      </span>
    );
  }

  if (!armed) {
    return (
      <span class="tri">
        <button
          class="btn"
          type="button"
          onClick={() => {
            setArmed(true);
          }}
        >
          {props.action}
        </button>
        {props.note === undefined || props.note === "" ? null : (
          <span class="tri-reason">{props.note}</span>
        )}
      </span>
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
