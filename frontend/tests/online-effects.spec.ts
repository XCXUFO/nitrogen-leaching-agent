import { expect, test, type Page } from "@playwright/test";
import type { OnlineMetrics } from "../src/lib/online-metrics";

async function mock(page: Page, role = "developer") {
  const requests: string[] = [];
  await page.route("**/api/eval/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/eval", "");
    requests.push(path + url.search);
    const user = { tester_id: "metrics-user", role };
    if (path === "/login") return route.fulfill({ json: { token: "metrics-browser-token", user } });
    if (path === "/me") return route.fulfill({ json: user });
    if (path === "/online-metrics") {
      const ratio = { numerator: 0, denominator: 0, rate: null };
      const step = { success: ratio, attempt_failure: ratio, retrieval_no_result: ratio, excluded: {}, observed_steps: 0 };
      const metrics: OnlineMetrics = {
        metric_version: "session-primary-v1", unit: "session", updated_at: "2026-10-17T09:00:00Z",
        filters: Object.fromEntries(url.searchParams), sessions: 2, questions: 5, states: { succeeded: 5 },
        session_states: { normal: 2 }, mean_turns: 2.5, multi_turn: { numerator: 1, denominator: 2, rate: .5 },
        turn_distribution: [{ turns: 1, sessions: 1 }, { turns: 4, sessions: 1 }],
        recent_sessions: role === "developer" ? [{ session_id: "conversation-one", run_id: "run-one", topic: "折氮量解释", created_at: "2026-10-17T09:00:00Z", turns: 4, status: "normal", trace_missing: 0 }] : [],
        reruns: { attempts: 0, succeeded: 0, recovered_failed_primary: 0, sessions: 0 },
        steps: { tool: step, skill: step, service: step }, trace_missing: 0,
        by_task: { explanation: 2 }, by_skill: [{ skill: "case_explanation", sessions: 2, calls: 5, failures: 0, runs: 5, mean_latency_ms: 20 }],
        daily: [{ date: "2026-10-17", sessions: 2, abnormal_sessions: 0, turns: 5 }],
      };
      return route.fulfill({ json: metrics });
    }
    if (path === "/sessions") return route.fulfill({ json: { total: 0, items: [] } });
    if (path === "/sessions/run-one") return route.fulfill({ json: {
      session_id: "conversation-one", topic: "折氮量解释", created_at: "2026-10-17T09:00:00Z",
      operator_id: "visitor", status: "正常", latency_ms: 20, turn_count: 1,
      turns: [{ run_id: "run-one", input: "折氮量是什么意思？", answer: "保留的历史回答。", started_at: "2026-10-17T09:00:00Z", status: "ok", latency_ms: 20 }],
    } });
    return route.fulfill({ json: [] });
  });
  return requests;
}

async function login(page: Page) {
  await page.getByLabel("账号", { exact: true }).fill("metrics-user");
  await page.getByLabel("密码", { exact: true }).fill("Fixture1234");
  await page.getByRole("button", { name: "进入工作台" }).click();
}

test("session metrics retain filters and link to conversation records without review UI", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  const requests = await mock(page);
  await page.goto("/evaluation/online-effects?mode=auto&source=formal");
  await login(page);
  await expect(page.getByRole("heading", { name: "会话运行概览", exact: true })).toBeVisible();
  await expect(page.getByText("包含 5 轮提问", { exact: true })).toBeVisible();
  await expect(page.getByText("50.0%（1/2）", { exact: true })).toBeVisible();
  await expect(page.getByText("4 轮：1 个会话", { exact: true })).toBeVisible();
  await expect(page.getByText("暂无可计算样本（0/0）").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "正式会话审查", exact: true })).toHaveCount(0);
  for (const label of ["审查状态", "样本来源", "主要归因"]) await expect(page.getByLabel(label, { exact: true })).toHaveCount(0);
  await expect(page.getByText("有效人工审查覆盖")).toHaveCount(0);
  await page.getByRole("link", { name: "case_explanation", exact: true }).click();
  await expect(page).toHaveURL(/online-effects\?.*skill=case_explanation/);
  await expect(page.getByLabel("实际 Skill", { exact: true })).toHaveValue("case_explanation");
  await expect.poll(() => requests.some(path => path.includes("/online-metrics?") && path.includes("skill=case_explanation") && path.includes("mode=auto") && path.includes("source=formal"))).toBe(true);
  await page.getByRole("link", { name: "查看会话运行记录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "运行记录", exact: true })).toBeVisible();
  expect(requests.some(path => path.includes("formal-runs") || path.includes("formal-samples"))).toBe(false);
  expect(errors).toEqual([]);
});

test("session state filters and drilldown keep the full conversation accessible", async ({ page }) => {
  const requests = await mock(page);
  await page.goto("/evaluation/online-effects?source=formal&skill=case_explanation");
  await login(page);
  await page.getByRole("link", { name: "截至当前全轮正常：2", exact: true }).click();
  await expect(page).toHaveURL(/status=normal/);
  await expect(page.getByRole("combobox", { name: "会话状态", exact: true })).toHaveValue("normal");
  await expect.poll(() => requests.some(path => path.includes("/online-metrics?") && path.includes("status=normal") && path.includes("skill=case_explanation"))).toBe(true);
  await page.getByRole("link", { name: "查看完整会话", exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/runs\/run-one$/);
  await expect(page.getByText("保留的历史回答。", { exact: true })).toBeVisible();
  expect(requests).toContain("/sessions/run-one");
});

test("old review list and detail links open the conversation records", async ({ page }) => {
  const requests = await mock(page);
  await page.goto("/evaluation/formal-reviews?review_status=unreviewed");
  await login(page);
  await expect(page).toHaveURL(/\/evaluation\/runs$/);
  await expect(page.getByRole("heading", { name: "运行记录", exact: true })).toBeVisible();
  await page.goto("/evaluation/formal-reviews/run-one");
  await expect(page).toHaveURL(/\/evaluation\/runs\/run-one$/);
  await expect(page.getByText("保留的历史回答。", { exact: true })).toBeVisible();
  expect(requests).toContain("/sessions/run-one");
  expect(requests.some(path => path.includes("formal-runs"))).toBe(false);
});

test("reviewer can still view execution statistics on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page, "reviewer");
  await page.goto("/evaluation/online-effects");
  await login(page);
  await expect(page.getByRole("heading", { name: "实际 Skill 调用与耗时" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "会话运行概览", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "查看完整会话", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "查看会话运行记录", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "打开导航" }).click();
  const nav = page.getByRole("dialog", { name: "移动端导航" });
  await expect(nav.getByRole("link", { name: "正式会话审查", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "线上看板", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
