import { expect, test } from '@playwright/test';

test.skip(!process.env.ACCOUNTS_TEST_API, 'Requires an isolated accounts fixture');
test.beforeEach(async ({ page }) => {
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    await route.fulfill({ response: await route.fetch({ url: `${process.env.ACCOUNTS_TEST_API}${url.pathname}${url.search}` }) });
  });
});

for (const [username, role] of [['cau_dev', '开发者'], ['cau_expert1', '领域审核人'], ['cau_tester1', '测试者']]) {
  test(`${role}: front login, navigation, reload and shared logout`, async ({ page }) => {
    if (role === '领域审核人') await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.getByRole('link', { name: '内部人员登录' }).click();
    await page.getByLabel('账号', { exact: true }).fill(username);
    await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
    await page.getByRole('button', { name: '进入工作台' }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByLabel('内部人员身份')).toContainText(username);
    await expect(page.getByLabel('内部人员身份')).toContainText(role);
    await page.getByRole('link', { name: '管理工作台' }).click();
    await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
    await page.reload();
    await expect(page.locator('header')).toContainText(username);
    await expect(page.getByLabel('密码', { exact: true })).toHaveCount(0);
    await page.locator('header').getByRole('link', { name: '返回对话' }).click();
    await expect(page).toHaveURL(/\/$/);
    await page.reload();
    await expect(page.getByLabel('内部人员身份')).toContainText(username);
    await page.getByRole('button', { name: '退出登录' }).click();
    await expect(page.getByRole('link', { name: '内部人员登录' })).toBeVisible();
    await page.goto('/evaluation');
    await expect(page.getByLabel('密码', { exact: true })).toBeVisible();
  });
}

test('front requests use verified identity and credentials remain window-scoped', async ({ page, context }) => {
  await page.goto('/evaluation');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester2');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.locator('header').getByRole('link', { name: '返回对话' }).click();
  const chatRequest = page.waitForRequest(request => request.url().endsWith('/api/chat'));
  await page.getByRole('button', { name: '了解支持的能力' }).click();
  const request = await chatRequest;
  expect(request.headers().authorization).toMatch(/^Bearer /);
  await expect(page.getByRole('button', { name: '复制回答' })).toBeVisible();
  const stored = await page.evaluate(() => ({ local: JSON.stringify(localStorage), session: sessionStorage.getItem('nitrogen_account_session') }));
  expect(stored.local).not.toContain('CauTest123456');
  expect(stored.local).not.toContain(request.headers().authorization.slice(7));
  expect(stored.session).not.toContain('CauTest123456');
  const newWindow = await context.newPage();
  await newWindow.goto('/');
  await expect(newWindow.getByRole('link', { name: '内部人员登录' })).toBeVisible();
  await newWindow.close();
  await page.reload();
  await expect(page.getByLabel('内部人员身份')).toContainText('cau_tester2');
});

test('background renewal keeps the open window signed in and revocation clears both views', async ({ page }) => {
  await page.clock.install();
  await page.goto('/evaluation');
  await page.getByLabel('账号', { exact: true }).fill('cau_expert2');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  const loginResponse = page.waitForResponse(response => response.url().endsWith('/api/eval/login'));
  await page.getByRole('button', { name: '进入工作台' }).click();
  const token = (await (await loginResponse).json()).token;
  await page.locator('header').getByRole('link', { name: '返回对话' }).click();
  const renewal = page.waitForResponse(response => response.url().endsWith('/api/eval/me'));
  await page.clock.runFor(5 * 60 * 1000);
  expect((await renewal).status()).toBe(200);
  await page.request.post(`${process.env.ACCOUNTS_TEST_API}/api/eval/logout`, { headers: { Authorization: `Bearer ${token}` } });
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.getByRole('link', { name: '内部人员登录' })).toBeVisible();
});

test('a late unauthorized response from the previous account cannot log out the new account', async ({ page }) => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/api/chat', async route => {
    await pending;
    await route.fulfill({ status: 401, json: { detail: { code: 'evaluation_unauthorized', message: '旧会话已失效' } } });
  });
  await page.goto('/evaluation?returnTo=%2F');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester3');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByLabel('内部人员身份')).toContainText('cau_tester3');
  const request = page.waitForRequest('**/api/chat');
  await page.getByRole('button', { name: '了解支持的能力' }).click();
  await request;
  await page.getByRole('button', { name: '退出登录' }).click();
  await page.getByRole('link', { name: '内部人员登录' }).click();
  await page.getByLabel('账号', { exact: true }).fill('cau_dev');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByLabel('内部人员身份')).toContainText('cau_dev');
  const stale = page.waitForResponse('**/api/chat');
  release();
  await stale;
  await expect(page.getByLabel('内部人员身份')).toContainText('cau_dev');
  await page.reload();
  await expect(page.getByLabel('内部人员身份')).toContainText('cau_dev');
});

test('temporary restoration failure retains credentials and can be retried', async ({ page }) => {
  await page.goto('/evaluation');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester3');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
  let fail = true;
  await page.route('**/api/eval/me', async route => {
    if (fail) { fail = false; await route.abort(); }
    else await route.fulfill({ response: await route.fetch({ url: `${process.env.ACCOUNTS_TEST_API}/api/eval/me` }) });
  });
  await page.reload();
  await page.getByRole('button', { name: '重新验证登录' }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
});
