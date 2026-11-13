"use client";

import { type GroupActivation, type PromptGroup, groupIsActive, promptButton as button } from "@/lib/prompt-types";

export function PromptGroupActivationButton({ group, activeGroup, activating, onActivate, label = "设为当前方案" }: GroupActivation & { group: PromptGroup; label?: string }) {
  const current = groupIsActive(group, activeGroup);
  return <button type="button" className={button} disabled={activating !== null || current} onClick={() => void onActivate(group)}>{activating === group.group_id ? "正在启用…" : current ? "当前已生效" : label}</button>;
}
