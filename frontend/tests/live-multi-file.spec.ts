import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { test, expect } from '@playwright/test';

test.skip(!process.env.LIVE_MULTI_FILE_REPRO, 'Requires an isolated local backend and two real result tables.');

test('two real workbooks stay separate across selection and removal', async ({ page }) => {
  const api = process.env.LIVE_API_BASE ?? 'http://127.0.0.1:8002';
  const requests: Array<{ query: string; file_id?: string; history?: unknown[] }> = [];
  const responses: Array<{ answer: string; run_id: string; agent_route: string; file_evidence: Array<{ filename: string; field: string }> }> = [];
  await page.route('**/api/**', route => {
    const original = new URL(route.request().url());
    return route.continue({ url: new URL(original.pathname + original.search, api).toString() });
  });
  page.on('request', request => { if (request.url().endsWith('/api/chat')) requests.push(request.postDataJSON()); });
  page.on('response', async response => {
    if (response.url().endsWith('/api/chat') && response.ok()) responses.push(await response.json());
  });
  await page.goto('/');
  const base = resolve(process.cwd(), '../data/demo');
  await page.getByLabel('附加结果表').setInputFiles([
    { name: 'Nbal_out.xls', mimeType: 'application/vnd.ms-excel', buffer: readFileSync(resolve(base, 'Nbal_out.xls')) },
    { name: 'waterbal_out.xls', mimeType: 'application/vnd.ms-excel', buffer: readFileSync(resolve(base, 'waterbal_out.xls')) },
  ]);
  await expect(page.getByRole('radio', { name: /选择文件 Nbal_out.xls/ })).toBeChecked();
  await expect(page.getByRole('radio', { name: /选择文件 waterbal_out.xls/ })).not.toBeChecked();
  async function send(query: string) {
    const before = responses.length;
    await page.getByLabel('问题输入').fill(query);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect.poll(() => responses.length).toBe(before + 1);
  }
  await send('硝态氮最大值及日序');
  expect(responses[0].file_evidence[0].filename).toBe('Nbal_out.xls');
  expect(responses[0].answer).toContain('3.65926384925842');
  await page.getByRole('radio', { name: /选择文件 waterbal_out.xls/ }).check();
  await send('PREC 最大值及日序');
  expect(requests[1].file_id).not.toBe(requests[0].file_id);
  expect(requests[1].history).toBeUndefined();
  expect(responses[1].file_evidence[0].filename).toBe('waterbal_out.xls');
  expect(responses[1].file_evidence[0].field).toContain('PREC');
  await send('Nbal_out.xls 中 PREC 最大值');
  expect(responses[2].agent_route).toBe('CLARIFY');
  expect(responses[2].file_evidence).toEqual([]);
  await page.getByRole('button', { name: '移除附件：waterbal_out.xls' }).click();
  await send('PREC 最大值及日序');
  expect(requests[3].file_id).toBeUndefined();
  expect(responses[3].agent_route).toBe('CLARIFY');
  await page.getByRole('radio', { name: /选择文件 Nbal_out.xls/ }).check();
  await send('硝态氮最小值及日序');
  expect(requests[4].file_id).toBe(requests[0].file_id);
  expect(requests[4].history).toBeUndefined();
  expect(responses[4].file_evidence[0].filename).toBe('Nbal_out.xls');
  console.log('LIVE_MULTI_FILE', JSON.stringify(responses.map((response, index) => ({
    index, run_id: response.run_id, route: response.agent_route, question: requests[index].query,
    file_id_present: Boolean(requests[index].file_id), evidence: response.file_evidence,
  }))));
});
