import { expect, test, type Page } from "@playwright/test";

const sessions = [
  { session_id: "layout-1", topic: "玉米种植条件下，如何减少氮素淋失？", review_status: "pending", turn_count: 4 },
  { session_id: "layout-2", topic: "不同土壤质地对硝态氮迁移的影响", review_status: "needs_changes", turn_count: 12 },
].map(item => ({ ...item, created_at: "2026-11-13T08:30:00Z", operator_id: "researcher", status: "正常", latency_ms: 1200 }));
const communication = { prompt_id: "global", label: "科研答复", text: "根据资料回答。", version: "v1" };
const taskPrompts = Object.fromEntries(["concept_explanation", "knowledge_search", "case_assistant"].map(scope => [scope,
  { prompt_id: scope, scope, label: `${scope} v1`, text: "核对资料。", version: "v1", examples: [] },
]));
const group = { group_id: "layout-group", label: "科研问答基准方案", version: "v1", communication, task_prompts: taskPrompts };

async function mock(page: Page) {
  await page.addInitScript(() => sessionStorage.setItem("nitrogen_account_session", JSON.stringify({ token: "layout-token", username: "researcher" })));
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    let json: unknown = [];
    if (url.pathname === "/api/eval/me") json = { tester_id: "researcher", role: "developer" };
    if (url.pathname === "/api/eval/sessions") json = { total: 42, items: sessions };
    if (url.pathname === "/api/eval/prompt-versions") json = [communication];
    if (url.pathname === "/api/eval/prompt-groups") json = [group];
    if (url.pathname === "/api/eval/active-prompt-group") json = { group, communication, task_prompts: taskPrompts };
    if (url.pathname === "/api/eval/task-prompts") json = { versions: Object.values(taskPrompts), active: taskPrompts };
    await route.fulfill({ json });
  });
}

test("desktop controls and table columns align, with a single page heading", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mock(page);
  await page.goto("/evaluation/runs");
  await expect(page.getByText("共查到 42 条会话记录")).toBeVisible();
  await expect(page.getByRole("main").getByRole("heading")).toHaveCount(1);
  const controls = [page.getByRole("textbox", { name: "会话信息", exact: true }), page.getByRole("combobox", { name: "审核状态", exact: true }),
    page.getByRole("combobox", { name: "运行状态", exact: true }), page.getByRole("button", { name: "查询", exact: true }), page.getByRole("button", { name: "重置", exact: true })];
  const boxes = await Promise.all(controls.map(control => control.boundingBox()));
  const bottoms = boxes.map(box => box!.y + box!.height);
  expect(Math.max(...bottoms) - Math.min(...bottoms)).toBeLessThanOrEqual(1);
  expect(boxes.every(box => box!.height === 36)).toBe(true);
  const table = page.getByRole("table", { name: "会话运行记录" });
  const numbers = table.getByRole("row").nth(1).getByRole("cell").nth(2);
  expect(await numbers.evaluate(cell => getComputedStyle(cell).textAlign)).toBe("right");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "收起侧边栏" }).click();
  await expect(page.getByRole("button", { name: "展开侧边栏" })).toBeVisible();
  await page.getByRole("button", { name: "展开侧边栏" }).focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await page.screenshot({ path: "/tmp/workbench-layout-desktop.png", fullPage: true });
});

test("mobile keeps table scrolling local and restores navigation focus after Escape", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page);
  await page.goto("/evaluation/runs");
  await expect(page.getByText("共查到 42 条会话记录")).toBeVisible();
  await expect(page.getByLabel("会话信息", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "查询", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  const open = page.getByRole("button", { name: "打开导航" });
  await open.click();
  await expect(page.getByRole("dialog", { name: "移动端导航" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "移动端导航" })).not.toBeVisible();
  await expect(open).toBeFocused();
  await page.screenshot({ path: "/tmp/workbench-layout-mobile.png", fullPage: true });
});

test("Prompt tabs support keyboard navigation and version columns share a baseline", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await mock(page);
  await page.goto("/evaluation/explanation-trials");
  await expect(page.getByLabel("当前生效方案", { exact: true })).toContainText(group.label);
  const tabs = page.getByRole("tablist", { name: "Prompt 管理功能" });
  await tabs.getByRole("tab", { name: "方案看板", exact: true }).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.getByRole("tab", { name: "Prompt 版本管理", exact: true })).toBeFocused();
  await expect(tabs.getByRole("tab", { name: "Prompt 版本管理", exact: true })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(tabs.getByRole("tab", { name: "方案看板", exact: true })).toBeFocused();
  const positions = await page.getByLabel(`已保存方案 ${group.label}`, { exact: true }).locator("dt").evaluateAll(labels => labels.map(label => label.getBoundingClientRect().y));
  expect(positions).toHaveLength(4);
  expect(Math.max(...positions) - Math.min(...positions)).toBeLessThanOrEqual(1);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
