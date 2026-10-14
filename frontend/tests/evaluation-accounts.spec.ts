import { expect, test } from '@playwright/test';

test.skip(!process.env.ACCOUNTS_TEST_API, 'Requires tests.accounts_fixture with a temporary database');
const accounts = [
  ['cau_dev', '开发者'], ['cau_expert1', '领域审核人'], ['cau_expert2', '领域审核人'],
  ['cau_tester1', '测试者'], ['cau_tester2', '测试者'], ['cau_tester3', '测试者'],
];

test.beforeEach(async ({ page }) => {
  await page.route('**/api/eval/**', async route => {
    const url = new URL(route.request().url());
    await route.fulfill({ response: await route.fetch({ url: `${process.env.ACCOUNTS_TEST_API}${url.pathname}${url.search}` }) });
  });
});

for (const [username, role] of accounts) {
  test(`${username} logs in with the correct navigation and logs out`, async ({ page }) => {
    await page.goto('/evaluation/cases');
    await expect(page.getByLabel('评测访问密钥')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '注册', exact: true })).toHaveCount(0);
    await page.getByLabel('账号', { exact: true }).fill(username);
    await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
    const response = page.waitForResponse(response => response.url().endsWith('/api/eval/login'));
    await page.getByRole('button', { name: '进入工作台' }).click();
    const token = (await (await response).json()).token;
    await expect(page.locator('header').getByText(role, { exact: true })).toBeVisible();
    const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
    await expect(nav.getByRole('link', { name: '审核队列', exact: true })).toHaveCount(role === '测试者' ? 0 : 1);
    await expect(nav.getByRole('link', { name: '运行记录', exact: true })).toHaveCount(role === '开发者' ? 1 : 0);
    await nav.getByRole('link', { name: '任务管理', exact: true }).click();
    await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
    await page.getByRole('button', { name: '退出登录' }).click();
    await expect(page.getByLabel('密码', { exact: true })).toHaveValue('');
    const expired = await page.request.get(`${process.env.ACCOUNTS_TEST_API}/api/eval/me`, { headers: { Authorization: `Bearer ${token}` } });
    expect(expired.status()).toBe(401);
  });
}

test('wrong password stays on login; refresh retains the session and URL', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/evaluation/cases');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester1');
  await page.getByLabel('密码', { exact: true }).fill('wrong');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toHaveText('账号或密码错误。');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  await page.reload();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  await expect(page.getByLabel('账号', { exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(/\/evaluation\/cases$/);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('revoked session returns to login when a protected request is made', async ({ page }) => {
  await page.goto('/evaluation/cases');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester2');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  const response = page.waitForResponse(response => response.url().endsWith('/api/eval/login'));
  await page.getByRole('button', { name: '进入工作台' }).click();
  const token = (await (await response).json()).token;
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  await page.request.post(`${process.env.ACCOUNTS_TEST_API}/api/eval/logout`, { headers: { Authorization: `Bearer ${token}` } });
  await page.getByRole('navigation', { name: '工作台导航' }).first().getByRole('link', { name: '任务管理', exact: true }).click();
  await expect(page.getByLabel('账号', { exact: true })).toBeVisible();
  await expect(page.getByRole('main').getByRole('alert')).toHaveText('登录已失效，请重新登录。');
});
