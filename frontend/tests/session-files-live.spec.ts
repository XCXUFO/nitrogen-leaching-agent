import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';
import type { ChatResponse } from '../src/lib/types';

test.skip(!process.env.P00_LIVE_API, 'Requires isolated P00 local backend');

test('fresh P00 session uses real nitrogen and water workbooks throughout the conversation', async ({ page }) => {
  const records: { query: string; request: unknown; response: ChatResponse }[] = [];
  const directory = '/tmp/nitrogen-p00-evidence';
  mkdirSync(directory, { recursive: true });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: new URL(url.pathname + url.search, process.env.P00_LIVE_API).toString() });
    if (url.pathname === '/api/chat') records.push({ query: route.request().postDataJSON().query, request: route.request().postDataJSON(), response: await response.json() });
    await route.fulfill({ response });
  });
  const send = async (query: string) => {
    const index = records.length;
    await page.getByLabel('问题输入').fill(query);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect.poll(() => records.length).toBe(index + 1);
    await expect(page.getByLabel('问题输入')).toBeEnabled();
    return records[index].response;
  };
  await page.goto('/');
  if (process.env.P00_SCREENSHOT_FONT) {
    const font = readFileSync(process.env.P00_SCREENSHOT_FONT).toString('base64');
    await page.addStyleTag({ content: `@font-face { font-family: P00CJK; src: url(data:font/ttf;base64,${font}); } body { font-family: var(--font-geist-sans), P00CJK, sans-serif; }` });
    await page.evaluate(() => document.fonts.ready);
  }
  await send('你能做什么？');
  await page.getByLabel('问题输入').fill('未发送草稿');
  await page.getByRole('button', { name: '新对话' }).click();
  await expect(page.getByLabel('问题输入')).toHaveValue('');
  await send('你能做什么？');
  const root = resolve(process.cwd(), '../data/demo');
  const input = page.getByLabel('附加结果表');
  await input.setInputFiles(['Nbal_out.xls', 'waterbal_out.xls'].map(name => ({ name, mimeType: 'application/vnd.ms-excel', buffer: readFileSync(resolve(root, name)) })));
  await expect(page.getByText(/已上传 · 提问时自动分析/)).toHaveCount(2);
  const maximum = await send('硝态氮最大值及日序');
  expect(maximum.file_evidence[0].value).toBeCloseTo(3.65926384925842, 12);
  expect(maximum.file_evidence[0].cell).toBe('Nbal_out!C284');
  expect(maximum.answer).toContain('352 条记录');
  const minimum = await send('那最小值呢？');
  expect(minimum.file_evidence[0]).toMatchObject({ value: 0, model_day: 2, occurrences: 191, cell: 'Nbal_out!C3' });
  await page.getByRole('button', { name: /收起文件：Nbal_out.xls/ }).click();
  expect((await send('那最小值呢？')).file_evidence[0].value).toBe(0);
  const rain = await send('PREC 最大值及日序');
  expect(rain.file_evidence[0]).toMatchObject({ value: 86, model_day: 276, cell: 'WtaBal_out!K277' });
  expect((await send('Nbal_out.xls 中 PREC 最大值')).file_evidence).toEqual([]);
  const combined = await send('硝态氮和 PREC 的最大值及日序');
  expect(combined.file_evidence).toHaveLength(2);
  await input.setInputFiles({ name: '重复副本.xls', mimeType: 'application/vnd.ms-excel', buffer: readFileSync(resolve(root, 'Nbal_out.xls')) });
  await expect(page.getByText(/已跳过重复文件/)).toBeVisible();
  await page.getByLabel('对话记录').evaluate(el => { el.scrollTo({ top: el.scrollHeight, behavior: 'instant' }); });
  await page.screenshot({ path: `${directory}/desktop.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: `${directory}/mobile.png` });
  await page.getByRole('button', { name: '新对话' }).click();
  const fresh = await send('那最小值呢？');
  expect(fresh.file_evidence).toEqual([]);
  expect(fresh.citations).toEqual([]);
  expect(fresh.answer).toContain('上传');
  expect((await send('它能解决什么问题？')).citations).toEqual([]);
  writeFileSync(`${directory}/runs.json`, JSON.stringify({ tested_at: new Date().toISOString(), records }, null, 2));
});
