"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

type HealthResult =
  | { ok: true; data: unknown }
  | { ok: false; error: string };

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  const [result, setResult] = useState<HealthResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function checkHealth() {
    setLoading(true);
    setResult(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/health`);
      if (!response.ok) {
        setResult({
          ok: false,
          error: `HTTP ${response.status} ${response.statusText}`,
        });
        return;
      }
      const data: unknown = await response.json();
      setResult({ ok: true, data });
    } catch (err) {
      setResult({
        ok: false,
        error: err instanceof Error ? err.message : String(err),
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-dvh max-w-2xl flex-col items-center justify-center gap-8 px-6 py-16">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-semibold tracking-tight">
          氮淋失风险决策 Agent — Hello World
        </h1>
        <p className="text-muted-foreground text-sm">
          验证前后端连通的最小页面
        </p>
      </div>

      <Button onClick={checkHealth} disabled={loading} size="lg">
        {loading ? "请求中..." : "测试后端连接"}
      </Button>

      {result && (
        <pre className="bg-muted text-foreground w-full overflow-x-auto rounded-lg border p-4 text-xs">
          {result.ok
            ? JSON.stringify(result.data, null, 2)
            : `错误：${result.error}`}
        </pre>
      )}

      <p className="text-muted-foreground text-xs">
        API base: <code>{API_BASE_URL}</code>
      </p>
    </main>
  );
}
