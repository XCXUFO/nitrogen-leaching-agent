import { expect, test } from "@playwright/test";
import type { ChatRequest, ChatResponse } from "../src/lib/types";

test("retrieval scope stays internal for sending and regenerating answers", async ({ page }) => {
  const requests: ChatRequest[] = [];
  await page.route("**/api/chat/session", (route) => route.fulfill({ status: 404, json: {} }));
  await page.route("**/api/chat", (route) => {
    const body = route.request().postDataJSON() as ChatRequest;
    requests.push(body);
    const response: ChatResponse = {
      answer: "已有文献范围内的说明。", citations: [], file_evidence: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      retrieved_count: 1, model: "fixture", route: "knowledge", agent_route: "KNOWLEDGE", run_id: "scope-run", conversation_id: "scope-session",
      trace_saved: true, outcome: "complete", attachment: null, sections: [], warnings: [],
      literature_scope: { mode: "inferred_tags", paper_count: 2, total_papers: 12, filters: [{ term: "玉米", paths: ["作物 / 玉米"] }], expanded: true },
    };
    return route.fulfill({ json: response });
  });
  await page.goto("/");
  await expect(page.getByRole("checkbox", { name: /扩大到其他本地文献/ })).toHaveCount(0);
  await page.getByLabel("问题输入").fill("玉米氮素淋溶过程");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("已有文献范围内的说明。", { exact: true })).toBeVisible();
  await expect(page.getByLabel("本次文献范围")).toHaveCount(0);
  await expect(page.getByText(/标签范围内|已按本次设置扩大|匹配标签：/)).toHaveCount(0);
  expect(requests[0]).not.toHaveProperty("allow_local_scope_expansion");
  await page.getByRole("button", { name: "重新回答", exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).not.toHaveProperty("allow_local_scope_expansion");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
