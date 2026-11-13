import { fillTestAccount } from './evaluation-login-helper';
import { test, expect } from '@playwright/test';

test('isolated live backend: baseline, replay, comparison and independent scoring', async ({ page, request }) => {
  test.skip(!process.env.EVAL_TEST_API, 'Requires the isolated evaluation test backend, never the shared review database.');
  test.setTimeout(120000);
  const api = process.env.EVAL_TEST_API!;
  const errors: string[] = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/eval/**', async route => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${api}${url.pathname}${url.search}` });
    await route.fulfill({ response, headers: { ...response.headers(), 'access-control-allow-origin': '*' } });
  });
  await page.goto('/evaluation/tasks/new');
  await fillTestAccount(page);
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByLabel('构建版本')).not.toHaveValue('');
  const version = await page.getByLabel('构建版本').inputValue();
  const token = await page.evaluate(() => JSON.parse(sessionStorage.getItem('nitrogen_account_session')!).token);
  const headers = { Authorization: `Bearer ${token}` };
  await page.getByLabel('任务用例 NEW01@2').check();
  await page.getByLabel('任务标题').fill(`browser task ${Date.now()}`);
  await page.getByLabel('知识库版本').fill('no-rag-test');
  await page.getByRole('button', { name: '创建任务' }).click();
  await page.getByRole('button', { name: '批量准备我的执行' }).click();
  await page.getByLabel('任务详情').getByRole('button', { name: /打开执行/ }).click();
  await expect(page).toHaveURL(/\/evaluation\/executions\/[^/?]+/);
  const baselineUrl = page.url();
  const baselineId = new URL(baselineUrl).pathname.split('/').pop()!;
  for (const query of ['你能做什么？', '你好']) {
    await expect(page.getByLabel('执行问题')).toBeEnabled();
    await page.getByLabel('执行问题').fill(query);
    await page.getByRole('button', { name: '发送本轮' }).click();
  }
  await expect(page.getByRole('button', { name: '复制回答' })).toHaveCount(2);
  await page.getByLabel('总体结论').selectOption('fail');
  await page.getByLabel('路由是否正确').selectOption('yes');
  await page.getByLabel('工具使用是否正确').selectOption('n.a.');
  await page.getByLabel('证据是否支持').selectOption('n.a.');
  await page.getByLabel('答案是否正确').selectOption('no');
  await page.getByLabel('评分说明').fill('SYNTHETIC failure for isolated issue workflow only.');
  await page.getByRole('button', { name: '提交并冻结评分' }).click();
  await expect(page.getByRole('heading', { name: '已保存的开发试评' })).toBeVisible();
  const originalResponse = await request.get(`${api}/api/eval/executions/${baselineId}`, { headers });
  expect(originalResponse.status()).toBe(200);
  const original = await originalResponse.json();
  const event = original.events.find((e: { action: string }) => e.action === 'query');
  expect(event).toBeTruthy();
  const issueTitle = `BROWSER TEST ONLY: issue ${Date.now()}`;
  // Legacy execution issues remain visible in the unified conversation issue view.
  const issueResponse = await request.post(`${api}/api/eval/issues`, { headers, data: {
    execution_id: baselineId, event_sequence: event.sequence, title: issueTitle,
    assignee: 'browser-developer', evidence_note: 'Synthetic check of original evidence and independent scoring.',
  } });
  expect(issueResponse.status()).toBe(201);
  const issue = await issueResponse.json();
  await page.goto('/evaluation/issues');
  await page.getByRole('button', { name: new RegExp(issueTitle) }).click();
  await expect(page.getByRole('link', { name: '查看完整原会话' })).toBeVisible();
  await expect(page.getByRole('button', { name: '转入会话问题处理' })).toBeVisible();
  await page.goto(baselineUrl);
  await page.getByRole('link', { name: '保存基线 / 回归对比' }).click();
  const title = `BROWSER TEST ONLY: capability flow ${Date.now()}`;
  await page.getByLabel('回归基线标题').fill(title);
  await page.getByRole('button', { name: '保存为回归基线' }).click();
  const card = page.locator('article').filter({ hasText: title });
  await card.getByRole('button', { name: '用当前版本重跑' }).click();
  await expect(card.getByRole('button', { name: '比较结果' }).first()).toBeVisible({ timeout: 30000 });
  await card.getByRole('button', { name: '比较结果' }).first().click();
  await expect(page.getByRole('region', { name: '版本比较结果' })).toContainText('0 轮存在内容或配置变化');
  await card.getByRole('button', { name: '打开新执行 / 人工评分' }).first().click();
  await expect(page).toHaveURL(/\/evaluation\/executions\/[^/?]+/);
  const candidateId = new URL(page.url()).pathname.split('/').pop()!;
  expect(candidateId).not.toBe(baselineId);
  await page.getByRole('button', { name: '提交并冻结评分' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '请先选择：总体结论' })).toBeVisible();
  await page.getByLabel('总体结论').selectOption('pass');
  await page.getByLabel('路由是否正确').selectOption('yes');
  await page.getByLabel('工具使用是否正确').selectOption('n.a.');
  await page.getByLabel('证据是否支持').selectOption('n.a.');
  await page.getByLabel('答案是否正确').selectOption('yes');
  await page.getByLabel('评分说明').fill('AUTOMATED BROWSER TEST ONLY; not a professional review.');
  await page.getByRole('button', { name: '提交并冻结评分' }).click();
  await expect(page.getByRole('heading', { name: '已保存的开发试评' })).toBeVisible();
  await expect(page.getByRole('button', { name: '提交并冻结评分' })).toHaveCount(0);
  const linked = await request.post(`${api}/api/eval/issues/${issue.issue_id}/retests`, { headers, data: {
    execution_id: candidateId, fix_version: version, notes: 'Synthetic independent replay review.',
  } });
  expect(linked.status()).toBe(201);
  const unchanged = await (await request.get(`${api}/api/eval/executions/${baselineId}`, { headers })).json();
  const candidate = await (await request.get(`${api}/api/eval/executions/${candidateId}`, { headers })).json();
  expect(unchanged.review).toEqual(original.review);
  expect(candidate.review.overall).toBe('pass');
  expect(candidate.review.review_id).not.toBe(original.review.review_id);
  await page.goto('/evaluation/issues');
  await page.getByRole('button', { name: new RegExp(issueTitle) }).click();
  await expect(page.getByRole('heading', { name: '问题处理 · 已解决' })).toBeVisible();
  expect(errors).toEqual([]);
});
