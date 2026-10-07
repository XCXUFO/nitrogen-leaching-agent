import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

test.skip(!process.env.LIVE_CHAT_REPRO, 'Run against local backend with LIVE_CHAT_REPRO=1');

test('live new conversation and Nbal_out attachment evidence', async ({ page }) => {
  const requests: unknown[] = [];
  const responses: unknown[] = [];
  if (process.env.LIVE_API_BASE) {
    await page.route('**/api/**', route => {
      const original = new URL(route.request().url());
      const destination = new URL(original.pathname + original.search, process.env.LIVE_API_BASE);
      return route.continue({ url: destination.toString() });
    });
  }
  page.on('request', request => {
    if (request.url().endsWith('/api/chat')) requests.push(request.postDataJSON());
  });
  page.on('response', async response => {
    if (response.url().endsWith('/api/chat')) {
      responses.push({ status: response.status(), body: await response.json() });
    }
  });
  await page.goto('/');
  await page.getByLabel('问题输入').fill('你能做什么？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByLabel('对话记录').getByText('农业模型助手', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: '新对话' }).click();
  await page.getByLabel('问题输入').fill('你能做什么？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => responses.length).toBe(2);
  await page.screenshot({ path: '/tmp/ui02-before.png' });

  const source = resolve(process.cwd(), '../data/demo/Nbal_out.xls');
  await page.getByLabel('附加结果表').setInputFiles({ name: 'Nbal_out.xls', mimeType: 'application/vnd.ms-excel', buffer: readFileSync(source) });
  await expect(page.getByText('已上传 · 提问时自动分析')).toBeVisible();
  await page.getByLabel('问题输入').fill('硝态氮最大值及日序');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => responses.length).toBe(3);
  await page.screenshot({ path: '/tmp/ui05-before.png' });
  await page.getByLabel('问题输入').fill('那最小值呢？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => responses.length).toBe(4);
  await expect(page.getByText('本会话可引用：Nbal_out.xls')).toBeVisible();
  await expect(page.getByRole('button', { name: '移除附件', exact: true })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/ui06-after.png' });
  await page.getByRole('button', { name: /收起文件：Nbal_out.xls/ }).click();
  await page.getByLabel('问题输入').fill('那最小值呢？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => responses.length).toBe(5);
  await expect(page.getByText('本会话可引用：Nbal_out.xls')).toHaveCount(0);
  await page.getByRole('button', { name: '新对话' }).click();
  await page.getByLabel('问题输入').fill('那最小值呢？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => responses.length).toBe(6);
  const sent = requests as Array<{ session_id: string; file_ids?: string[]; history?: unknown[] }>;
  expect(sent[1].session_id).not.toBe(sent[0].session_id);
  expect(sent[1].history).toBeUndefined();
  expect(sent[2].file_ids).toHaveLength(1);
  expect(sent[3].file_ids).toEqual(sent[2].file_ids);
  expect(sent[4].file_ids).toEqual(sent[2].file_ids);
  expect(sent[4].history).toBeDefined();
  expect(sent[5].session_id).not.toBe(sent[4].session_id);
  expect(sent[5].file_ids).toEqual([]);
  expect(sent[5].history).toBeUndefined();
  const result = responses.map((item, index) => {
    const value = item as { status: number; body: { answer: string; run_id: string; agent_route: string; file_evidence: unknown[] } };
    return { index, status: value.status, answer: value.body.answer, run_id: value.body.run_id,
      route: value.body.agent_route, evidence_count: value.body.file_evidence.length };
  });
  console.log('LIVE_CHAT_REPRO', JSON.stringify({ requests, result }));
});
