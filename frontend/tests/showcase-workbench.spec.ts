import { expect, test, type Page } from '@playwright/test';
import { readFileSync } from 'node:fs';

const management = new Map<Page, string[]>();
const errors = new Map<Page, string[]>();
test.beforeEach(async ({ page }) => {
  management.set(page, []); errors.set(page, []);
  page.on('pageerror', (error) => errors.get(page)!.push(error.message));
  page.on('request', (request) => {
    if (/^\/api\/(literature|case-library|eval)(\/|$)/.test(new URL(request.url()).pathname)) management.get(page)!.push(request.url());
  });
  await page.route('**/api/**', (route) => route.fulfill({ status: 503, json: { detail: 'isolated showcase test' } }));
  await page.route('**/api/demo/catalog', (route) => route.fulfill({ contentType: 'application/json', body: readFileSync('../data/demo/catalog.json', 'utf8') }));
});
test.afterEach(async ({ page }) => {
  expect(management.get(page)).toEqual([]);
  expect(errors.get(page)).toEqual([]);
  management.delete(page); errors.delete(page);
});

test('overview links new modules even when historical catalog is unavailable', async ({ page }) => {
  await page.route('**/api/demo/catalog', (route) => route.abort());
  await page.goto('/showcase');
  await expect(page.getByText('同步至 2026-10-17')).toBeVisible();
  await expect(page.getByRole('link', { name: '体验案例与措施', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '收起侧边栏' }).click();
  await expect(page.getByRole('button', { name: '展开侧边栏' })).toBeVisible();
  await page.getByRole('link', { name: '体验星标问题', exact: true }).click();
  await expect(page.getByRole('heading', { name: '星标问题', exact: true })).toBeVisible();
  await expect(page.getByText('独立合成流程示例', { exact: false })).toBeVisible();
});

test('literature imports mixed batch, retries only failed item and reviews drafts', async ({ page }) => {
  await page.goto('/showcase/literature');
  await page.getByRole('button', { name: '批量导入示例', exact: true }).click();
  await page.getByRole('button', { name: '开始预置导入', exact: true }).click();
  await expect(page.getByText('共 3 条示例文献', { exact: true })).toBeVisible();
  await page.getByText('查看本次处理记录', { exact: true }).click();
  await expect(page.getByText('重复文件 · 未再次导入', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '重试失败示例', exact: true }).click();
  await expect(page.getByText('共 4 条示例文献', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '重试失败示例', exact: true })).toHaveCount(0);
  await expect(page.getByText('重试完成 · 已保存示例草稿', { exact: false })).toBeVisible();
  await page.getByRole('link', { name: '重试后的水稻研究（流程示例）', exact: true }).click();
  await expect(page.getByRole('heading', { name: '重试后的水稻研究（流程示例）', exact: true })).toBeVisible();
  await expect(page.getByText('草稿', { exact: true })).toBeVisible();
  await expect(page.getByText('结论：措施应用前需核对', { exact: false })).toBeVisible();
  await page.getByRole('link', { name: '返回文献管理', exact: true }).click();
  await page.reload();
  await expect(page.getByText('共 2 条示例文献', { exact: true })).toBeVisible();
});

test('batch selection clears with filters and independent AI options preserve registration', async ({ page }) => {
  await page.goto('/showcase/literature');
  await page.getByRole('checkbox', { name: '全选本页文献' }).check();
  await expect(page.getByRole('button', { name: 'AI 处理所选文献（2）' })).toBeEnabled();
  await page.getByLabel('搜索示例文献').fill('冬小麦');
  await expect(page.getByRole('button', { name: 'AI 处理所选文献（0）' })).toBeDisabled();
  await page.getByLabel('搜索示例文献').fill('');
  await expect(page.getByRole('button', { name: 'AI 处理所选文献（0）' })).toBeDisabled();
  await page.getByRole('checkbox', { name: '选择文献 冬小麦氮素淋失研究（流程示例）' }).check();
  await page.getByRole('checkbox', { name: '批量 AI 一键打标', exact: true }).uncheck();
  await page.getByRole('button', { name: 'AI 处理所选文献（1）' }).click();
  await page.getByRole('link', { name: '冬小麦氮素淋失研究（流程示例）', exact: true }).click();
  await expect(page.getByRole('heading', { name: '冬小麦氮素淋失研究（流程示例）', exact: true })).toBeVisible();
  await expect(page.getByText('已登记', { exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '广西 / 南宁 / 示范县', exact: true })).toBeVisible();
  await expect(page.getByText('示例作者甲；示例研究团队', { exact: true })).toBeVisible();
});

test('single paper selectively adopts suggestions and saves summary and conclusion', async ({ page }) => {
  await page.goto('/showcase/literature/SAMPLE-001');
  await page.getByRole('button', { name: '继续整理与打标' }).click();
  await page.getByRole('button', { name: '查看预置解析建议' }).click();
  await page.getByRole('checkbox', { name: '全选解析字段' }).uncheck();
  await page.getByRole('checkbox', { name: '采用摘要', exact: true }).check();
  await page.getByRole('checkbox', { name: '采用结论', exact: true }).check();
  await page.getByRole('button', { name: '填入所选建议' }).click();
  await expect(page.getByLabel('作者（按署名顺序）', { exact: true })).toHaveValue('');
  await expect(page.getByLabel('摘要', { exact: true })).toHaveValue(/合成流程示例/);
  await expect(page.getByLabel('结论', { exact: true })).toHaveValue(/措施应用前/);
  await page.getByRole('button', { name: '下一步', exact: true }).click();
  await page.getByRole('button', { name: '采用预置 AI 标签建议' }).click();
  await page.getByRole('button', { name: '保存示例草稿' }).click();
  await expect(page.getByText('结论：措施应用前需核对', { exact: false })).toBeVisible();
});

test('case shared tags, batch opening and follow-up recheck availability', async ({ page }) => {
  await page.goto('/showcase/case-library');
  await page.getByRole('checkbox', { name: '全选本页案例' }).check();
  await page.getByRole('button', { name: 'AI 一键打标（2）' }).click();
  await expect(page.getByText('已采用预置标签建议', { exact: false })).toHaveCount(2);
  await page.getByRole('checkbox', { name: '全选本页案例' }).check();
  await page.getByRole('button', { name: '批量开放', exact: true }).click();
  await page.getByRole('button', { name: '运行固定问题示例' }).click();
  await expect(page.getByText('演示路由：case_reference → case_explanation', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: '全选本页案例' }).check();
  await page.getByRole('button', { name: '批量关闭', exact: true }).click();
  await page.getByRole('button', { name: '追问第一个案例' }).click();
  await expect(page.getByText('当前范围内没有仍开放的案例。', { exact: false })).toBeVisible();
  await page.getByRole('navigation', { name: '展示后台导航' }).getByRole('link', { name: '标签管理', exact: true }).click();
  await expect(page.getByRole('link', { name: '关联案例 2 条', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '关联案例 2 条', exact: true }).click();
  await expect(page.getByText('共 2 条合成案例', { exact: true })).toBeVisible();
});

test('case editor preserves rich table, reviews explanation and shares new tags', async ({ page }) => {
  await page.goto('/showcase/case-library/new');
  await page.getByLabel('案例标题', { exact: true }).fill('含表格的合成案例');
  await page.getByRole('textbox', { name: '案例与措施原文 *', exact: true }).fill('表格示例原文，适用条件待审核。');
  await page.getByRole('button', { name: '插入表格', exact: true }).click();
  await expect(page.locator('#case-body table')).toBeVisible();
  await page.getByRole('button', { name: 'AI 解释初稿示例' }).click();
  await expect(page.getByLabel('解释与适用条件', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: '采用解释初稿', exact: true }).click();
  await page.getByRole('checkbox', { name: '开放给案例问答', exact: true }).check();
  await page.getByRole('button', { name: '保存案例示例', exact: true }).click();
  await expect(page.getByRole('heading', { name: '含表格的合成案例', exact: true })).toBeVisible();
  await expect(page.getByText('【预置解释初稿】', { exact: false })).toBeVisible();
  await expect(page.locator('main table')).toBeVisible();
});

test('starred questions survive module navigation and reset across all modules on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/showcase/starred-questions');
  await page.getByRole('button', { name: '新增问题', exact: true }).click();
  await page.getByRole('textbox', { name: '问题', exact: true }).fill('这个参数如何核对？');
  await page.getByLabel('对应答案（选填）', { exact: true }).fill('需要先核对原文和单位。');
  await page.getByRole('button', { name: '保存问题示例' }).click();
  await expect(page.getByText('共 2 条示例问题', { exact: true })).toBeVisible();
  const nav = page.getByRole('navigation', { name: '移动端展示导航' });
  await nav.getByRole('link', { name: '文献管理', exact: true }).click();
  await nav.getByRole('link', { name: '星标问题', exact: true }).click();
  await expect(page.getByText('这个参数如何核对？', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑', exact: true }).last().click();
  await page.getByLabel('对应答案（选填）', { exact: true }).fill('已修改的人工答案。');
  await page.getByRole('button', { name: '保存问题示例' }).click();
  await expect(page.getByText('已修改的人工答案。', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await nav.getByRole('link', { name: '案例与措施', exact: true }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '重置示例' }).click();
  await nav.getByRole('link', { name: '星标问题', exact: true }).click();
  await expect(page.getByText('共 1 条示例问题', { exact: true })).toBeVisible();
});
