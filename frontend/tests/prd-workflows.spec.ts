import { expect, test, type Page } from "@playwright/test";

async function login(page: Page) {
  await page.getByLabel("账号", { exact: true }).fill("expert");
  await page.getByLabel("密码", { exact: true }).fill("Fixture1234");
  await page.getByRole("button", { name: "进入工作台" }).click();
}
async function account(page: Page) {
  await page.route("**/api/eval/login", route => route.fulfill({ json: { token: "prd-browser-token", user: { tester_id: "expert", role: "reviewer" } } }));
  await page.route("**/api/eval/me", route => route.fulfill({ json: { tester_id: "expert", role: "reviewer" } }));
}

test("prompt versions can be saved, compared and selected globally without per-question ratings", async ({ page }) => {
  await account(page);
  const oldPrompt = { prompt_id: "old", label: "原版解释 v1", text: "原有的解释要求。", version: "prompt-old", sha256: "old-hash", actor: "builtin", created_at: "2026-10-17T00:00:00Z" };
  const newPrompt = { ...oldPrompt, prompt_id: "new", label: "增强解释 v2", text: "先回应问题，再解释术语，保留数字口径。", version: "prompt-new", sha256: "new-hash" };
  const customText = "## 表达要求\n\n**把合计解释清楚**，保留单位。\n\n| 口径 | 说明 |\n| --- | --- |\n| 合计 | 三次总和 |\n\n```text\n160 kg/ha\n```";
  const versions = [newPrompt, oldPrompt];
  let active = newPrompt;
  let activations = 0;
  const prompts = { baseline: oldPrompt, candidate: newPrompt };
  const trial = { trial_id: "trial-one", query: "合计是什么意思？", material: "160 kg/ha 是三次合计。", material_fingerprint: "fixed-input", method_version: "prompt-comparison-v1", status: "running", prompts, variants: {} };
  let posts = 0;
  await page.route("**/api/eval/explanation-method", route => route.fulfill({ json: { version: "v1", title: "CDC Clear Communication Index", edition: "August 2019", url: "https://www.cdc.gov/ccindex/index.html", adaptation: "本地中文表达规则", notice: "方法参考。", scope: "日常回答统一使用全局生效版本。", prompts } }));
  await page.route("**/api/eval/prompt-versions", route => {
    if (route.request().method() === "GET") return route.fulfill({ json: versions });
    const body = route.request().postDataJSON();
    const saved = { ...newPrompt, ...body, prompt_id: "custom", version: "prompt-custom", sha256: "custom-hash" };
    versions.unshift(saved);
    return route.fulfill({ status: 201, json: saved });
  });
  await page.route("**/api/eval/active-prompt", route => {
    if (route.request().method() === "PUT") { activations++; active = versions.find(item => item.prompt_id === route.request().postDataJSON().prompt_id)!; }
    return route.fulfill({ json: active });
  });
  await page.route("**/api/eval/explanation-trials", route => {
    if (route.request().method() === "GET") return route.fulfill({ json: posts ? [trial] : [] });
    const body = route.request().postDataJSON(); posts++;
    expect(body.query).toBe(trial.query); expect(body.material).toBe(trial.material);
    expect(body.prompts.baseline.text).toBe(oldPrompt.text);
    expect(body.prompts.candidate.text).toBe(customText);
    trial.prompts.candidate = { ...newPrompt, ...body.prompts.candidate };
    return route.fulfill({ status: 202, json: trial });
  });
  await page.route("**/api/eval/explanation-trials/trial-one", route => route.fulfill({ json: { ...trial, status: "completed", variants: { baseline: { run_id: "baseline", status: "succeeded", answer: "现有表达。" }, candidate: { run_id: "candidate", status: "succeeded", answer: "三次的总和是160 kg/ha，各次分配未知。" } } } }));
  await page.goto("/evaluation/explanation-trials"); await login(page);
  await expect(page.getByRole("heading", { name: "Prompt 迭代", exact: true })).toHaveCount(1);
  await expect(page.getByRole("region", { name: "旧版 Prompt Markdown 预览", exact: true })).toContainText(oldPrompt.text);
  await page.getByRole("group", { name: "旧版 Prompt 展示方式", exact: true }).getByRole("button", { name: "原文", exact: true }).click();
  await expect(page.getByLabel("旧版 Prompt", { exact: true })).toHaveValue(oldPrompt.text);
  await expect(page.getByLabel("旧版 Prompt", { exact: true })).toHaveAttribute("readonly", "");
  await page.getByLabel("新版已保存版本", { exact: true }).selectOption("old");
  await page.getByRole("group", { name: "新版 Prompt 展示方式", exact: true }).getByRole("button", { name: "编辑", exact: true }).click();
  await expect(page.getByLabel("新版 Prompt", { exact: true })).toHaveValue(oldPrompt.text);
  await page.getByLabel("新版 Prompt 名称", { exact: true }).fill("清晰解释 v3");
  await page.getByLabel("新版 Prompt", { exact: true }).fill(customText);
  await page.getByRole("group", { name: "新版 Prompt 展示方式", exact: true }).getByRole("button", { name: "Markdown", exact: true }).click();
  const preview = page.getByRole("region", { name: "新版 Prompt Markdown 预览", exact: true });
  await expect(preview.getByRole("heading", { name: "表达要求", exact: true })).toBeVisible();
  await expect(preview.getByRole("table")).toContainText("三次总和");
  await expect(preview.locator("strong")).toHaveText("把合计解释清楚");
  await expect(preview.locator("pre")).toContainText("160 kg/ha");
  await page.getByRole("button", { name: "保存为新版本" }).click();
  await expect(page.getByText("已保存版本：清晰解释 v3", { exact: true })).toBeVisible();
  expect(posts).toBe(0); expect(activations).toBe(0);
  await page.getByLabel("用户问题", { exact: true }).fill(trial.query);
  await page.getByLabel("固定输入材料", { exact: true }).fill(trial.material);
  await page.getByRole("button", { name: "生成同题对照" }).click();
  await expect(page.getByRole("status")).toHaveText("对照已生成");
  await expect(page.getByRole("region", { name: "本次旧版 Prompt Markdown 预览", exact: true })).toContainText(oldPrompt.text);
  await expect(page.getByRole("region", { name: "本次新版 Prompt Markdown 预览", exact: true }).getByRole("heading", { name: "表达要求", exact: true })).toBeVisible();
  await expect(page.getByLabel("新版对照结果")).toContainText("各次分配未知");
  await expect(page.getByLabel("评价类型", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("评价结论", { exact: true })).toHaveCount(0);
  expect(activations).toBe(0);
  await page.getByLabel("选择全局版本", { exact: true }).selectOption("custom");
  await page.getByRole("button", { name: "设为全局生效版本" }).click();
  await expect(page.getByText("全局生效版本已切换为：清晰解释 v3，之后的新回答使用此版本。", { exact: true })).toBeVisible();
  expect(activations).toBe(1);
  await page.reload();
  await expect(page.getByLabel("选择全局版本", { exact: true })).toHaveValue("custom");
  await expect(page.getByRole("region", { name: "新版 Prompt Markdown 预览", exact: true }).getByRole("heading", { name: "表达要求", exact: true })).toBeVisible();
  await page.getByLabel("旧版已保存版本", { exact: true }).selectOption("new");
  await expect(page.getByRole("region", { name: "旧版 Prompt Markdown 预览", exact: true })).toContainText(newPrompt.text);
  expect(posts).toBe(1);
  await page.screenshot({ path: test.info().outputPath("prompt-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
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
