"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, getHealth } from "@/lib/api";

type HealthResult =
  | { ok: true; data: unknown }
  | { ok: false; error: string };

export function HealthProbe() {
  const [result, setResult] = useState<HealthResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function check() {
    setLoading(true);
    setResult(null);
    try {
      const data = await getHealth();
      setResult({ ok: true, data });
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.userMessage
          : err instanceof Error
            ? err.message
            : String(err);
      setResult({ ok: false, error: message });
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2">
      <Button
        onClick={check}
        disabled={loading}
        size="sm"
        variant="outline"
      >
        {loading ? "请求中…" : "测试 /api/health"}
      </Button>
      {result && (
        <pre className="bg-background overflow-x-auto rounded border p-2 text-[11px]">
          {result.ok
            ? JSON.stringify(result.data, null, 2)
            : `错误：${result.error}`}
        </pre>
      )}
    </div>
  );
}
