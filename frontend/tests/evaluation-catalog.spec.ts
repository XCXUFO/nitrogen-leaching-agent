import { test, expect } from '@playwright/test';

test('isolated catalog: asset, draft and immutable Case publication', async ({ page }) => {
  test.skip(!process.env.EVAL_TEST_API, 'Requires an isolated evaluation backend.');
  const api = process.env.EVAL_TEST_API!;
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.route('**/api/eval/**', async (route) => {
    const url = new URL(route.request().url());
    const response = await route.fetch({ url: `${api}${url.pathname}${url.search}` });
    await route.fulfill({ response, headers: { ...response.headers(), 'access-control-allow-origin': '*' } });
  });
  await page.goto('/evaluation/assets');
  await page.getByLabel('评测访问密钥').fill('browser-test-developer-token-0000000000000000');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByLabel('资产路径').fill('data/raw/whcns/received-2026-09-26/package/模型/Nbal_out.xls');
  await page.getByLabel('资产来源').fill('isolated browser catalog test');
  await page.getByRole('button', { name: '登记资产' }).click();
  await expect(page.getByRole('status').filter({ hasText: '已登记 Nbal_out.xls' })).toBeVisible();
  await page.getByRole('navigation', { name: '工作台导航' }).first().getByRole('link', { name: '用例库', exact: true }).click();
  await page.getByLabel('检索已发布用例').fill('F05');
  await page.getByRole('row').filter({ hasText: 'F05' }).filter({ hasText: 'v2' }).getByRole('button', { name: '查看用例' }).click();
  await page.getByRole('button', { name: '复制当前用例为新草稿' }).click();
  await page.getByText('高级：用例 JSON', { exact: true }).click();
  const editor = page.getByLabel('用例 JSON', { exact: true });
  const value = JSON.parse(await editor.inputValue());
  const caseId = `CATBROWSER${Date.now()}`;
  await editor.fill(JSON.stringify({ ...value, case_id: caseId, version: 1, title: 'Browser catalog test only' }, null, 2));
  await page.getByRole('checkbox').last().check();
  await page.getByRole('button', { name: '创建草稿' }).click();
  await expect(page.getByRole('status').filter({ hasText: '草稿已保存' })).toBeVisible();
  await page.getByLabel('草稿备注').fill('unsaved revision must not publish');
  await expect(page.getByRole('button', { name: '发布冻结版本' })).toBeDisabled();
  await expect(page.getByText('有未保存的修改，请先保存新修订再发布。')).toBeVisible();
  await page.getByRole('button', { name: '保存新修订' }).click();
  await expect(page.getByRole('status').filter({ hasText: '草稿已保存：修订 2' })).toBeVisible();
  const draftId = await page.getByLabel('已有用例草稿').inputValue();
  const headers = { Authorization: 'Bearer browser-test-developer-token-0000000000000000' };
  const saved = await (await page.request.get(`${api}/api/eval/case-drafts/${draftId}`, { headers })).json();
  const updated = await page.request.put(`${api}/api/eval/case-drafts/${draftId}`, { headers, data: {
    case: saved.case, fixture_asset_ids: saved.fixture_asset_ids, notes: 'concurrent revision', expected_revision: 2,
  } });
  expect(updated.status()).toBe(200);
  await page.getByRole('button', { name: '刷新目录' }).click();
  await page.getByRole('button', { name: '发布冻结版本' }).click();
  await expect(page.getByRole('alert').filter({ hasText: '草稿已有新修订' })).toBeVisible();
  expect((await (await page.request.get(`${api}/api/eval/cases?latest=false`, { headers })).json()).some((item: {case: {case_id: string}}) => item.case.case_id === caseId)).toBe(false);
  await page.getByRole('button', { name: '重新打开已保存修订（丢弃本地修改）' }).click();
  await expect(page.getByLabel('草稿备注')).toHaveValue('concurrent revision');
  await page.getByRole('button', { name: '发布冻结版本' }).click();
  await expect(page.getByRole('status').filter({ hasText: `${caseId} v1 已发布` })).toBeVisible();
  expect((await (await page.request.get(`${api}/api/eval/cases?latest=false`, { headers })).json()).some((item: {case: {case_id: string}}) => item.case.case_id === caseId)).toBe(true);
  expect(errors).toEqual([]);
});
