import { expect, type APIRequestContext, type Page } from '@playwright/test';

export function testAccount() {
  const username = process.env.EVAL_TEST_USERNAME;
  const password = process.env.EVAL_TEST_PASSWORD;
  if (!username || !password) throw new Error('Set EVAL_TEST_USERNAME and EVAL_TEST_PASSWORD for the isolated backend.');
  return { username, password };
}

export async function fillTestAccount(page: Page) {
  const account = testAccount();
  await page.getByLabel('账号', { exact: true }).fill(account.username);
  await page.getByLabel('密码', { exact: true }).fill(account.password);
}

export async function testSession(request: APIRequestContext, api: string) {
  const response = await request.post(`${api}/api/eval/login`, { data: testAccount() });
  expect(response.status()).toBe(200);
  return (await response.json()).token as string;
}
