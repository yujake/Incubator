/** 一个徽标：`kind` 决定视觉档（pass / fail / unknown / plain），`text` 是逐字读数。 */
export interface BadgeProps {
  kind: string;
  text: string;
}

export function Badge(props: BadgeProps) {
  return <span class={`badge ${props.kind}`}>{props.text}</span>;
}
