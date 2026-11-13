import { expect, test, type Page } from "@playwright/test";

async function setup(page: Page, role = "developer", failure = false) {
  const submissions: unknown[] = [];
  let retries = 0;
  let submitted = false;
  const job = () => ({ id: "all-assets", actor: "developer", created_at: "2026-11-11T08:00:00Z", mode: "merge", total: 2,
    counts: failure && !retries ? { ready: 1, failed: 1 } : { ready: 2 }, assets: { literature: 1, case: 1 },
    active: false, interrupted: false, taxonomy_changed: false, retryable: failure && !retries,
    items: [
      { kind: "case", asset_id: "C-ABC", title: "玉米案例", status: failure && !retries ? "failed" : "ready", message: failure && !retries ? "打标失败，请重试。" : "已保存", before_tags: ["maize"], after_tags: ["maize", "nitrogen", "irrigation", "model"] },
      { kind: "literature", asset_id: "paper-one", title: "氮素论文", status: "ready", message: "已保存", before_tags: [], after_tags: ["maize", "nitrogen", "irrigation", "model"] },
    ] });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown;
    if (path === "/api/eval/me") json = { tester_id: role, role };
    else if (path === "/api/eval/login") json = { token: "test-token", user: { tester_id: role, role } };
    else if (path === "/api/literature/taxonomy") json = {
      dimensions: ["crop", "topic", "variable", "method"].map((id, i) => ({ id, name: ["作物", "研究内容", "研究变量", "研究方法"][i], enabled: 1, selection: "multiple", required: 0 })),
      tags: ["maize", "nitrogen", "irrigation", "model"].map((id, i) => ({ id, name: ["玉米", "氮淋溶", "灌溉", "WHCNS"][i], path: ["粮食作物 / 玉米", "氮淋溶", "灌溉", "WHCNS"][i], dimension_id: ["crop", "topic", "variable", "method"][i], parent_id: null, description: "", enabled: 1, sort_order: i, paper_count: 0 })),
    };
    else if (path === "/api/literature/users") json = [];
    else if (path === "/api/literature/config") json = { max_pdf_mb: 100 };
    else if (path === "/api/literature/asset-tag-jobs") {
      if (route.request().method() === "POST") {
        submissions.push(route.request().postDataJSON()); submitted = true; json = job();
      } else json = { items: submitted ? [job()] : [] };
    } else if (path === "/api/literature/asset-tag-jobs/all-assets") json = job();
    else if (path === "/api/literature/asset-tag-jobs/all-assets/retry") { retries += 1; json = job(); }
    else throw new Error(`Unexpected request ${path}`);
    await route.fulfill({ json });
  });
  await page.goto("/evaluation/literature-tags");
  await page.getByLabel("账号", { exact: true }).fill(`cau_${role}`);
  await page.getByLabel("密码", { exact: true }).fill("CauTest123456");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "标签维度", exact: true })).toBeVisible();
  return { submissions, retries: () => retries };
}

test("developer starts whole-library tagging and can reopen saved results", async ({ page }) => {
  const state = await setup(page);
  const panel = page.getByRole("region", { name: "全库一键打标" });
  await expect(panel).toBeVisible();
  await expect(panel.getByLabel("全库打标方式")).toHaveValue("merge");
  await panel.getByRole("button", { name: "一键打标全部资产" }).click();
  await expect(panel.getByRole("status")).toContainText("已处理 2 / 2");
  await expect(panel.getByRole("status")).toContainText("文献 1 篇 · 案例 1 条");
  await expect(panel.getByRole("link", { name: "案例 · 玉米案例" })).toHaveAttribute("href", "/evaluation/case-library/C-ABC");
  const paper = panel.getByRole("listitem").filter({ has: page.getByRole("link", { name: "文献 · 氮素论文" }) });
  await expect(paper).toContainText("标签 0 → 4 个");
  for (const label of ["作物：粮食作物 / 玉米", "研究内容：氮淋溶", "研究变量：灌溉", "研究方法：WHCNS"]) {
    await expect(paper.getByRole("group", { name: "本次新增标签" })).toContainText(label);
  }
  const caseRow = panel.getByRole("listitem").filter({ has: page.getByRole("link", { name: "案例 · 玉米案例" }) });
  await expect(caseRow).toContainText("标签 1 → 4 个");
  await expect(caseRow.getByRole("group", { name: "本次新增标签" })).not.toContainText("玉米");
  expect(state.submissions).toEqual([{ mode: "merge" }]);
  await page.reload();
  await expect(panel.getByRole("status")).toContainText("已处理 2 / 2");
  expect(state.submissions).toHaveLength(1);
});

test("replacement is explicit and failed items can be retried", async ({ page }) => {
  const state = await setup(page, "developer", true);
  const panel = page.getByRole("region", { name: "全库一键打标" });
  await panel.getByLabel("全库打标方式").selectOption("replace");
  await expect(panel).toContainText("重新打标会替换每项资产的已有标签");
  await panel.getByRole("button", { name: "一键打标全部资产" }).click();
  await expect(panel).toContainText("失败 1");
  expect(state.submissions).toEqual([{ mode: "replace" }]);
  await panel.getByRole("button", { name: "重试失败或中断项" }).click();
  await expect(panel).toContainText("成功 2 · 失败 0");
  expect(state.retries()).toBe(1);
});

for (const role of ["tester", "reviewer"]) {
  test(`${role} can browse tags without modification or whole-library tagging controls`, async ({ page }) => {
    await setup(page, role);
    await expect(page.getByRole("region", { name: "全库一键打标" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "保存维度" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "新增一级标签" })).toHaveCount(0);
    const search = page.getByRole("textbox", { name: "搜索标签树" });
    await expect(search).toBeEnabled();
    await search.fill("玉米");
    await expect(page.getByText("玉米", { exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "关联文献" })).toBeVisible();
  });
}
