import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

test.skip(!process.env.CANDIDATE_MANAGEMENT || !process.env.EVAL_TEST_API, 'Isolated candidate backend only.');

test('candidate Case upload/import and review queue remain usable', async ({ page }) => {
  const api = process.env.EVAL_TEST_API!;
  const token = readFileSync(resolve(process.cwd(), '../backend/var/eval/access-credentials.txt'), 'utf8')
    .split('\n').find((line) => line.startsWith('local-developer '))?.split(':')[1].trim();
  if (!token) throw new Error('Local developer identity missing');
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/eval/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${api}${url.pathname}${url.search}` });
    await route.fulfill({ response, headers: { ...response.headers(), 'access-control-allow-origin': '*' } });
  });
  await page.goto('/evaluation/cases');
  await page.getByLabel('评测访问密钥').fill(token);
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('heading', { name: '用例版本目录' })).toBeVisible();
  await page.getByLabel('检索已发布用例').fill('F05');
  const row = page.getByRole('row').filter({ hasText: 'F05' }).filter({ hasText: 'v2' });
  await row.getByRole('button', { name: '查看用例' }).click();
  await expect(page).toHaveURL(/F05%402$/);
  await page.getByRole('navigation', { name: '工作台导航' }).first().getByRole('link', { name: '资产目录', exact: true }).click();
  await page.getByLabel('资产类型').selectOption('evidence');
  await page.getByLabel('资产来源').fill('isolated candidate browser test');
  await page.getByLabel('上传资产文件').setInputFiles({ name: 'candidate-proof.txt', mimeType: 'text/plain', buffer: Buffer.from('synthetic evidence') });
  await page.getByRole('button', { name: '上传资产', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: '已上传并登记 candidate-proof.txt' })).toBeVisible();
  const headers = { Authorization: `Bearer ${token}` };
  const cases = await (await page.request.get(`${api}/api/eval/cases?latest=false`, { headers })).json();
  const template = cases.find((item: { case: { case_id: string; version: number } }) => item.case.case_id === 'NEW01' && item.case.version === 2).case;
  const unique = `CANDIDATE${Date.now()}`;
  await page.getByRole('navigation', { name: '工作台导航' }).first().getByRole('link', { name: '用例库', exact: true }).click();
  await page.getByText('批量导入草稿', { exact: true }).click();
  await page.getByLabel('批量导入用例 JSON').fill(JSON.stringify([{ ...template, case_id: unique, version: 1, attachment_requirements: [] }]));
  await page.getByRole('button', { name: '导入草稿' }).click();
  await expect(page.getByRole('status').filter({ hasText: '已导入 1 份草稿' })).toBeVisible();
  await page.getByRole('link', { name: '管理草稿' }).click();
  await expect(page.getByLabel('已有用例草稿').locator('option').filter({ hasText: unique })).toHaveCount(1);
  await page.getByRole('navigation', { name: '工作台导航' }).first().getByRole('link', { name: '审核队列', exact: true }).click();
  await page.getByLabel('筛选审核状态').selectOption('pending_development');
  await expect(page.getByLabel('独立审核队列')).toContainText('待开发评分');
  expect(errors).toEqual([]);
});

test('candidate Issue state change keeps original evidence and history', async ({ page }) => {
  const api = process.env.EVAL_TEST_API!;
  const token = readFileSync(resolve(process.cwd(), '../backend/var/eval/access-credentials.txt'), 'utf8')
    .split('\n').find((line) => line.startsWith('local-developer '))?.split(':')[1].trim();
  if (!token) throw new Error('Local developer identity missing');
  const headers = { Authorization: `Bearer ${token}` };
  const executionResponse = await page.request.post(`${api}/api/eval/executions`, { headers, data: { case_id: 'NEW01', case_version: 2 } });
  expect(executionResponse.status()).toBe(201);
  const eid = (await executionResponse.json()).execution_id;
  const query = await page.request.post(`${api}/api/eval/executions/${eid}/query`, { headers, data: { query: '你好' } });
  expect(query.status()).toBe(200);
  const runId = (await query.json()).events[0].run_id;
  const review = await page.request.post(`${api}/api/eval/executions/${eid}/reviews`, { headers, data: {
    overall: 'fail', route_correct: 'yes', tool_correct: 'n.a.', evidence_correct: 'n.a.', answer_correct: 'no',
    notes: 'synthetic candidate browser issue only',
  } });
  expect(review.status()).toBe(201);
  const issueResponse = await page.request.post(`${api}/api/eval/issues`, { headers, data: {
    execution_id: eid, event_sequence: 1, title: `Candidate issue ${Date.now()}`,
    assignee: 'local-developer', evidence_note: 'synthetic isolated browser test',
  } });
  expect(issueResponse.status()).toBe(201);
  const issue = await issueResponse.json();
  await page.route('**/api/eval/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${api}${url.pathname}${url.search}` });
    await route.fulfill({ response, headers: { ...response.headers(), 'access-control-allow-origin': '*' } });
  });
  await page.goto(`/evaluation/issues/${issue.issue_id}`);
  await page.getByLabel('评测访问密钥').fill(token);
  await page.getByRole('button', { name: '进入工作台' }).click();
  const card = page.getByRole('article', { name: `问题：${issue.title}` });
  await expect(card).toContainText(runId);
  await card.getByLabel(`${issue.title} 状态`).selectOption('in_progress');
  await card.getByLabel(`${issue.title} 处理备注`).fill('assigning candidate follow-up');
  await card.getByRole('button', { name: '保存处理记录' }).click();
  await expect(card).toContainText('处理中');
  await card.getByText('处理历史 2 条').click();
  await expect(card).toContainText('assigning candidate follow-up');
  const saved = await (await page.request.get(`${api}/api/eval/issues/${issue.issue_id}`, { headers })).json();
  expect(saved.status).toBe('in_progress');
  expect(saved.run_id).toBe(runId);
  expect(saved.history).toHaveLength(2);
});
