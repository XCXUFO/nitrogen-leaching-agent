import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

test.skip(!process.env.EVAL_TEST_API || !process.env.TASK_MANAGEMENT_LIVE, 'Requires isolated backend and a temporary copied database.');

test('two-case task is prepared once and opens historical executions', async ({ page }) => {
  const api = process.env.EVAL_TEST_API!;
  const credentials = process.env.EVAL_TEST_TOKEN ? '' : readFileSync(resolve(process.cwd(), '../backend/var/eval/access-credentials.txt'), 'utf8');
  const token = process.env.EVAL_TEST_TOKEN ?? credentials.split('\n').find((line) => line.startsWith('local-developer '))?.split(':')[1].trim();
  if (!token) throw new Error('Local developer test identity missing');
  await page.route('**/api/eval/**', async (route) => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${api}${url.pathname}${url.search}` });
    await route.fulfill({ response, headers: { ...response.headers(), 'access-control-allow-origin': '*' } });
  });
  await page.goto('/evaluation/tasks/new');
  await page.getByLabel('评测访问密钥').fill(token);
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('heading', { name: '任务管理' })).toBeVisible();
  await page.getByLabel('任务用例 NEW01@2').check();
  await page.getByLabel('任务标题').fill(`isolated task ${Date.now()}`);
  await page.getByLabel('知识库版本').fill('isolated-no-rag');
  await page.getByLabel('任务用例 F05@2').check();
  await expect(page.getByText('已选 2 / 50')).toBeVisible();
  await page.getByRole('button', { name: '创建任务' }).click();
  await expect(page.getByLabel('任务详情')).toContainText('2 个用例版本');
  await page.getByRole('button', { name: '批量准备我的执行' }).click();
  await expect(page.getByLabel('任务详情')).toContainText('已准备 2');
  await expect(page.getByLabel('任务详情').getByRole('button', { name: /打开执行/ })).toHaveCount(2);
  await page.getByRole('button', { name: '批量准备我的执行' }).click();
  await expect(page.getByLabel('任务详情')).toContainText('执行 2 次');
  await page.getByLabel('任务详情').getByRole('button', { name: /打开执行/ }).first().click();
  await expect(page.getByLabel('执行问题')).toBeEnabled();
  await expect(page.getByText('临时上下文不可用', { exact: false })).toHaveCount(0);
  await page.getByLabel('执行问题').fill('你能做什么？');
  await page.getByRole('button', { name: '发送本轮', exact: true }).click();
  await expect(page.getByText('第 1 步 · query', { exact: false })).toBeVisible();
  await page.getByRole('link', { name: '返回所属任务', exact: true }).click();
  await expect(page.getByLabel('任务详情')).toContainText('已开始 1');
  await page.getByLabel('任务详情').getByRole('button', { name: /打开执行/ }).last().click();
  await expect(page.getByLabel('执行问题')).toBeEnabled();
  await expect(page.getByText('第 1 步 · query', { exact: false })).toHaveCount(0);
});
