import { expect, test } from '@playwright/test';

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
  for (const name of ['文献管理', '案例与措施', '标签管理', '运行记录', '会话用例组']) {
    await expect(nav.getByRole('link', { name, exact: true })).toHaveCount(1);
  }
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
  await page.getByRole('link', { name: '内部人员登录' }).click();
  await expect(page.getByLabel('账号', { exact: true })).toBeVisible();
});

test('mobile browsing has no page overflow and all public modules are reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/showcase');
  const nav = page.getByRole('navigation', { name: '移动端展示导航' });
  for (const name of ['任务管理', '用例库', '执行记录', '问题处理', '回归对比', '审核队列', '文献管理', '运行记录']) {
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
  await page.route('**/api/chat/session', r => r.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', r => r.fulfill({ status: 429, json: { detail: { code: 'public_demo_limit', message: '今日实时体验额度已用完，请查看已保存案例，或明天再试。' } } }));
  await page.goto('/');
  await page.getByRole('button', { name: /专业知识解答/ }).click();
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
