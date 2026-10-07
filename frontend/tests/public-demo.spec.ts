import { expect, test } from '@playwright/test';

test('visitor completes real example calculation and follow-up without signing in', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.goto('/');
  await page.getByRole('button', { name: /使用示例文件体验/ }).click();
  await expect(page.getByText(/3\.659/).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText(/283/).first()).toBeVisible();
  await page.getByRole('button', { name: '那最小值呢？', exact: true }).click();
  await expect(page.getByText(/191/).first()).toBeVisible();
  await page.getByRole('button', { name: '移除会话文件', exact: true }).click();
  await page.getByLabel('问题输入').fill('那最小值呢？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByText(/请先上传 WHCNS/).last()).toBeVisible();
  await page.getByRole('link', { name: '查看评测后台' }).click();
  await expect(page.getByText('展示模式 · 仅供浏览')).toBeVisible();
  expect(errors).toEqual([]);
});

test('public backend supports browsing, filtering, deep links and provenance without management requests', async ({ page }) => {
  const management: string[] = [];
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/eval')) management.push(r.url()); });
  await page.goto('/showcase');
  await expect(page.getByRole('heading', { name: '回答之外，还要能解释如何验证。' })).toBeVisible();
  await page.getByRole('link', { name: '从一个完整对话案例开始' }).click();
  await expect(page.getByRole('heading', { name: '连续追问与附件移除', exact: true })).toBeVisible();
  await expect(page.getByText(/191/).first()).toBeVisible();
  await page.reload();
  await expect(page.getByRole('heading', { name: '验证目标与判断标准' })).toBeVisible();
  const nav = page.getByRole('navigation', { name: '展示后台导航', exact: true });
  await nav.getByRole('link', { name: '用例库', exact: true }).click();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByRole('heading', { name: '从问题登记到回归复测' })).toBeVisible();
  await nav.getByRole('link', { name: '回归对比', exact: true }).click();
  await expect(page.getByRole('heading', { name: '从问题登记到回归复测' })).toBeVisible();
  await nav.getByRole('link', { name: '用例库', exact: true }).click();
  await page.getByLabel('搜索公开案例').fill('文献');
  await expect(page.getByRole('heading', { name: '有出处的文献解释' })).toBeVisible();
  await page.getByRole('link', { name: /有出处的文献解释/ }).click();
  await expect(page.getByRole('heading', { name: /引用与原文摘录/ })).toBeVisible();
  await nav.getByRole('link', { name: '回归对比', exact: true }).click();
  await page.getByRole('link', { name: /从问题登记到回归复测/ }).click();
  await expect(page.getByText('fail（合成）', { exact: true })).toBeVisible();
  await expect(page.getByText('pass（合成）', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: /创建|提交评分|运行回归|上传资产|分派/ })).toHaveCount(0);
  expect(management).toEqual([]);
  await page.screenshot({ path: '/tmp/nitrogen-demo-desktop.png', fullPage: true });
  await page.getByRole('link', { name: '管理登录' }).click();
  await expect(page.getByLabel('评测访问密钥')).toBeVisible();
});

test('mobile browsing has no page overflow and all public modules are reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/showcase');
  const nav = page.getByRole('navigation', { name: '移动端展示导航' });
  for (const name of ['评测任务', '用例库', '执行记录', '问题管理', '回归对比', '审核状态', '资料与证据', '运行记录']) {
    await nav.getByRole('link', { name, exact: true }).click();
    await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.goto('/showcase/cases/composed');
  await expect(page.getByRole('heading', { name: '验证目标与判断标准' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nitrogen-demo-mobile.png', fullPage: true });
});

test('quota and loading failures provide a usable recovery path', async ({ page }) => {
  await page.route('**/api/chat', r => r.fulfill({ status: 429, json: { detail: { code: 'public_demo_limit', message: '今日实时体验额度已用完，请查看已保存案例，或明天再试。' } } }));
  await page.goto('/');
  await page.getByRole('button', { name: /试试文献问答/ }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('今日实时体验额度');
  await page.getByRole('link', { name: '也可以查看已保存的历史示例' }).click();
  await expect(page.getByRole('heading', { name: '验证目标与判断标准' })).toBeVisible();
  await page.route('**/api/demo/catalog', r => r.abort());
  await page.reload();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('暂时无法读取');
  await page.unroute('**/api/demo/catalog');
  await page.getByRole('button', { name: '重新加载' }).click();
  await expect(page.getByRole('heading', { name: '验证目标与判断标准' })).toBeVisible();
});
