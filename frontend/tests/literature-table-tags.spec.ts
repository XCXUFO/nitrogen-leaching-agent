import { expect, test, type Page } from "@playwright/test";

const tagPaths = ["土壤水分", "模型模拟", "土壤 / 硝态氮迁移", `研究条件 / ${"long-tag-".repeat(40)}`];
const tags = tagPaths.map((path, index) => ({ id: `tag-${index}`, dimension_id: index === 1 ? "method" : "research", name: path, path, enabled: 1, parent_id: null }));
async function open(page: Page, count = 4, record: { venue?: string } = {}) {
  await page.addInitScript(() => sessionStorage.setItem("nitrogen_account_session", JSON.stringify({ token: "tag-preview", username: "researcher" })));
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = [];
    if (path === "/api/eval/me") json = { tester_id: "researcher", role: "developer" };
    if (path === "/api/literature/config") json = { max_pdf_mb: 100 };
    if (path === "/api/literature/taxonomy") json = { dimensions: [{ id: "research", name: "研究内容", enabled: 1, selection: "multiple" }, { id: "method", name: "研究方法", enabled: 1, selection: "multiple" }], tags };
    if (path === "/api/literature/papers") json = { total: 1, page: 1, page_size: 20, counts: { total: 1, draft: 0, registered: 1, disabled: 0 }, items: [{
      id: "tag-paper", revision: 1, title: "长标签布局验证文献", authors: [], authors_unknown: true, venue: record.venue ?? "农业环境科学学报", publication_type: "期刊论文", year: 2025,
      tag_ids: tags.slice(0, count).map(tag => tag.id), registration: "registered", usage: "normal", created_by: "researcher", updated_by: "researcher",
      created_at: "2026-11-13T08:30:00Z", updated_at: "2026-11-13T08:30:00Z", search_sync: { status: "ready" },
    }] };
    await route.fulfill({ json });
  });
  await page.goto("/evaluation/literature");
  await expect(page.getByRole("button", { name: "长标签布局验证文献", exact: true })).toBeVisible({ timeout: 20000 });
  return page.getByRole("button", { name: `查看全部 ${count} 个标签`, exact: true });
}

test("two short tags are fully visible on separate lines without a remaining-count badge", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const trigger = await open(page, 2);
  await trigger.scrollIntoViewIfNeeded();
  const first = trigger.getByText("研究内容：土壤水分", { exact: true });
  const second = trigger.getByText("研究方法：模型模拟", { exact: true });
  await expect(first).toBeVisible();
  await expect(second).toBeVisible();
  await expect(trigger).not.toContainText("+");
  const firstBox = await first.boundingBox();
  const secondBox = await second.boundingBox();
  expect(secondBox!.y).toBeGreaterThanOrEqual(firstBox!.y + firstBox!.height);
  for (const label of [first, second]) expect(await label.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
});

test("tag capacity follows the record height as other column content grows and shrinks", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const record = { venue: "Journal of Physics: Conference Series ".repeat(6) };
  const trigger = await open(page, 4, record);
  const row = page.getByRole("row").filter({ hasText: "长标签布局验证文献" });
  await trigger.scrollIntoViewIfNeeded();
  await expect(trigger).toContainText(tagPaths[3]);
  await expect(trigger).not.toContainText("+");
  const tallHeight = (await row.boundingBox())!.height;

  record.venue = "JPCS";
  await page.getByRole("button", { name: "查询", exact: true }).click();
  await expect(row.getByRole("cell").nth(3)).toHaveText(record.venue);
  await expect(trigger).toContainText("+");
  expect((await row.boundingBox())!.height).toBeLessThan(tallHeight);

  record.venue = "Journal of Physics: Conference Series ".repeat(6);
  await page.getByRole("button", { name: "查询", exact: true }).click();
  await expect(trigger).toContainText(tagPaths[3]);
  await expect(trigger).not.toContainText("+");
});

test("long tags stay inside their table column and hover reveals every full label", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const trigger = await open(page);
  await trigger.scrollIntoViewIfNeeded();
  const row = page.getByRole("row").filter({ hasText: "长标签布局验证文献" });
  const bounds = await trigger.boundingBox();
  const nextColumn = await row.getByRole("cell").nth(7).boundingBox();
  expect(bounds!.width).toBeLessThanOrEqual(180);
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(nextColumn!.x);
  await trigger.hover();
  const popup = page.getByRole("dialog", { name: "文献全部标签", exact: true });
  await expect(popup).toBeVisible();
  await expect(popup.getByRole("listitem")).toHaveCount(4);
  for (const path of tagPaths) await expect(popup).toContainText(path);
  await popup.hover();
  await expect(popup).toBeVisible();
  expect(await popup.evaluate(element => element.scrollWidth <= element.clientWidth)).toBe(true);
  const popupBounds = await popup.boundingBox();
  expect(popupBounds!.x).toBeGreaterThanOrEqual(0);
  expect(popupBounds!.x + popupBounds!.width).toBeLessThanOrEqual(1440);
  await page.keyboard.press("Escape");
  await expect(popup).not.toBeVisible();
  await page.mouse.move(0, 0);
  await trigger.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(trigger).toBeFocused();
  await expect(popup).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(popup).not.toBeVisible();
});

test.describe("touch label popover", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
  test("tap reveals tags within the viewport and outside tap closes the popover", async ({ page }) => {
    const trigger = await open(page);
    await trigger.scrollIntoViewIfNeeded();
    await trigger.tap();
    const popup = page.getByRole("dialog", { name: "文献全部标签", exact: true });
    await expect(popup).toBeVisible();
    await expect(popup.getByRole("listitem")).toHaveCount(4);
    const bounds = await popup.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.getByRole("heading", { name: "文献管理", exact: true }).tap();
    await expect(popup).not.toBeVisible();
  });
});
