"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

const MAX_LEN = 1000;

interface Props {
  onSubmit: (query: string) => void;
  disabled?: boolean;
}

export function ChatForm({ onSubmit, disabled }: Props) {
  const [value, setValue] = useState("");
  const trimmed = value.trim();
  const tooLong = value.length > MAX_LEN;
  const canSubmit = !disabled && trimmed.length > 0 && !tooLong;

  return (
    <form
      className="space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (canSubmit) {
          onSubmit(trimmed);
          setValue("");
        }
      }}
    >
      <textarea
        className="border-input bg-background placeholder:text-muted-foreground focus-visible:ring-ring/50 focus-visible:border-ring w-full resize-y rounded-md border px-3 py-2 text-sm shadow-xs outline-none transition-[color,box-shadow] focus-visible:ring-3 disabled:opacity-50"
        rows={3}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="例如：氮素淋失主要受什么因素影响？"
        disabled={disabled}
        aria-label="问题输入"
      />
      <div className="flex items-center justify-between">
        <span
          className={`text-xs ${tooLong ? "text-destructive" : "text-muted-foreground"}`}
        >
          {value.length} / {MAX_LEN}
        </span>
        <Button type="submit" disabled={!canSubmit} size="lg">
          {disabled ? "正在思考…" : "提交"}
        </Button>
      </div>
    </form>
  );
}
