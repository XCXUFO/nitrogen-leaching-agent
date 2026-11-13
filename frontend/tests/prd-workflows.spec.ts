import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.getByLabel("账号", { exact: true }).fill("expert");
  await page.getByLabel("密码", { exact: true }).fill("Fixture1234");
  await page.getByRole("button", { name: "进入工作台" }).click();
}
async function account(page: Page) {
  await page.route("**/api/eval/login", route => route.fulfill({ json: { token: "prd-browser-token", user: { tester_id: "expert", role: "developer" } } }));
  await page.route("**/api/eval/me", route => route.fulfill({ json: { tester_id: "expert", role: "developer" } }));
}

test("global prompt management saves immutable versions and activates explicitly", async ({ page }) => {
  await account(page);
  const original = { prompt_id: "old", label: "全局原版", text: "先回答，再解释。", version: "v1" };
  const versions = [original];
  let active = original;
  let activations = 0;
  const taskPrompts = Object.fromEntries(["concept_explanation", "knowledge_search", "case_assistant"].map(scope => [scope, { ...original, prompt_id: `task-${scope}`, scope, examples: [] }]));
  await page.route("**/api/eval/task-prompts", route => route.fulfill({ json: { versions: Object.values(taskPrompts), active: taskPrompts } }));
  await page.route("**/api/eval/prompt-versions", route => {
    if (route.request().method() === "GET") return route.fulfill({ json: versions });
    const saved = { ...route.request().postDataJSON(), prompt_id: "custom", version: "v2" };
    versions.unshift(saved);
    return route.fulfill({ status: 201, json: saved });
  });
  await page.route("**/api/eval/prompt-groups", route => route.fulfill({ json: [] }));
  await page.route("**/api/eval/active-prompt-group", route => route.fulfill({ json: { group: null, communication: active,
    task_prompts: taskPrompts } }));
  await page.route("**/api/eval/active-prompt", route => {
    if (route.request().method() === "PUT") { activations++; active = versions.find(p => p.prompt_id === route.request().postDataJSON().prompt_id)!; }
    return route.fulfill({ json: active });
  });
  await page.goto("/evaluation/explanation-trials"); await login(page);
  await expect(page.getByRole("heading", { name: "Prompt 管理", exact: true })).toHaveCount(1);
  await page.getByRole("tab", { name: "Prompt 版本管理" }).click();
  await expect(page.getByRole("region", { name: "全局 Prompt Markdown 预览" })).toContainText(original.text);
  await page.getByRole("group", { name: "全局 Prompt 展示方式" }).getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("全局 Prompt", { exact: true }).fill("## 表达要求\n\n**解释合计**，保留单位。");
  await page.getByLabel("全局 Prompt 新版本名称").fill("新版表达");
  await page.getByRole("button", { name: "保存全局新版本" }).click();
  await expect(page.getByRole("status")).toContainText("已保存版本：新版表达；尚未启用。");
  expect(activations).toBe(0);
  await page.getByLabel("选择全局版本", { exact: true }).selectOption("custom");
  await page.getByRole("button", { name: "设为全局生效版本" }).click();
  await expect(page.getByRole("status")).toContainText("全局生效版本已切换为：新版表达");
  expect(activations).toBe(1);
  await page.reload();
  await page.getByRole("tab", { name: "Prompt 版本管理" }).click();
  await expect(page.getByLabel("选择全局版本", { exact: true })).toHaveValue("custom");
  await expect(page.getByRole("region", { name: "全局 Prompt Markdown 预览" }).getByRole("heading", { name: "表达要求" })).toBeVisible();
  await page.getByLabel("全局已保存版本").selectOption("old");
  await expect(page.getByRole("region", { name: "全局 Prompt Markdown 预览" })).toContainText(original.text);
});

test("registered literature distinguishes failed sync, retry, ready status and retained reload", async ({ page }) => {
  await account(page);
  const paper = { id: "P-SYNC", revision: 1, title: "已登记的测试文献", authors: [], authors_unknown: true, publication_type: "期刊论文", venue: "", venue_unknown: true, year: null, year_unknown: true, language: "中文", language_note: "", doi: "", source_url: "", source_note: "测试原件", abstract: "", conclusion: "", version_note: "", related_paper_ids: [], related_papers: [], internal_note: "", tag_ids: [], registration: "registered", usage: "normal", filename: "source.pdf", sha256: "test", created_by: "expert", updated_by: "expert", created_at: "2026-10-17T00:00:00Z", updated_at: "2026-10-17T00:00:00Z", registered_by: "expert", registered_at: "2026-10-17T00:00:00Z", events: [], search_sync: { status: "not_prepared", reason: "尚未同步全文索引", indexed_at: "", version: "", mode: "" } };
  let attempts = 0;
  await page.route("**/api/literature/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/taxonomy")) return route.fulfill({ json: { dimensions: [], tags: [] } });
    if (path.endsWith("/users")) return route.fulfill({ json: [] });
    if (path.endsWith("/config")) return route.fulfill({ json: { max_pdf_mb: 100 } });
    if (path.endsWith("/file")) return route.fulfill({ contentType: "application/pdf", body: "%PDF-test" });
    if (path.endsWith("/search-sync")) {
      paper.search_sync = ++attempts === 1 ? { ...paper.search_sync, status: "failed", reason: "正文提取失败，可重试" } : { status: "ready", reason: "", indexed_at: "2026-10-17", version: "content-v1", mode: "text" };
      return route.fulfill({ json: paper.search_sync });
    }
    return route.fulfill({ json: paper });
  });
  await page.goto("/evaluation/literature/P-SYNC"); await login(page);
  const sync = page.getByLabel("全文检索同步", { exact: true });
  await expect(sync).toContainText("尚未同步全文索引");
  await sync.getByRole("button", { name: "同步全文索引" }).click();
  await expect(sync).toContainText("同步失败");
  await sync.getByRole("button", { name: "重试同步" }).click();
  await expect(sync).toContainText("已就绪");
  await page.reload();
  await expect(page.getByLabel("全文检索同步", { exact: true })).toContainText("content-v1");
  expect(attempts).toBe(2);
});
