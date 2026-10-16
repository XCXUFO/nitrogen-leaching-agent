import { expect, test } from '@playwright/test';

test('unresponsive login times out and allows retry', async ({ page }) => {
  let respond = false;
  await page.route('**/api/eval/login', async route => {
    if (!respond) return;
    await route.fulfill({ status: 401, json: { detail: { message: '账号或密码错误。' } } });
  });
  await page.goto('/evaluation/case-library');
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('button', { name: '正在验证…' })).toBeDisabled();
  await expect(page.locator('form').getByRole('alert')).toHaveText('登录服务响应超时，请稍后重试。', { timeout: 20000 });
  await expect(page.getByRole('button', { name: '进入工作台' })).toBeEnabled();
  respond = true;
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.locator('form').getByRole('alert')).toHaveText('账号或密码错误。');
});
