import { test, expect } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';

// Read-only acceptance immediately after migration. Never modifies real papers.
test.skip(process.env.LITERATURE_MIGRATION_CHECK !== '1', 'Requires a migrated library and existing local credentials');
test.use({ trace: 'off', video: 'off' }); // Do not record login credentials.

test('migrated papers are globally visible and original PDFs remain intact', async ({ page }, info) => {
  test.setTimeout(180_000);
  const report = JSON.parse(readFileSync(process.env.LITERATURE_MIGRATION_REPORT ?? '../backend/var/literature/migration-20261011.json', 'utf8'));
  const credentials = readFileSync('../backend/var/eval/account-credentials.txt', 'utf8').trim().split('\n')
    .map((line) => line.match(/^(\S+) \((tester|developer|reviewer)\): (\S+)$/))
    .filter((entry) => entry !== null);
  expect(credentials.length).toBeGreaterThan(0);
  expect(report.failed).toBe(0);
  expect(report.items).toHaveLength(90);
  const expectedIds = report.items.map((entry: { paper_id: string }) => entry.paper_id).sort();
  const tokens: string[] = [];
  for (const credential of credentials) {
    const login = await page.request.post('/api/eval/login', { data: { username: credential[1], password: credential[3] } });
    expect(login.status()).toBe(200);
    const token = (await login.json()).token;
    tokens.push(token);
    const response = await page.request.get('/api/literature/papers?page_size=100', { headers: { Authorization: `Bearer ${token}` } });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.total).toBe(90);
    expect(result.items.map((paper: { id: string }) => paper.id).sort()).toEqual(expectedIds);
    expect(result.counts).toEqual({ total: 90, draft: 90, registered: 0, disabled: 0 });
    for (const paper of result.items) expect(paper.tag_ids).toEqual([]);
    await response.dispose();
  }
  const token = tokens[0];
  const headers = { Authorization: `Bearer ${token}` };
  for (const entry of report.items) {
    const response = await page.request.get(`/api/literature/papers/${entry.paper_id}/file?download=true`, { headers });
    expect(response.status()).toBe(200);
    expect(createHash('sha256').update(await response.body()).digest('hex')).toBe(entry.sha256);
    await response.dispose();
  }
  await page.goto('/evaluation/literature');
  await page.getByLabel('账号', { exact: true }).fill(credentials[0][1]);
  await page.getByLabel('密码', { exact: true }).fill(credentials[0][3]);
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByText('共 90 条结果', { exact: true })).toBeVisible();
  await page.getByLabel('每页条数').selectOption('100');
  await expect(page.locator('tbody tr')).toHaveCount(90);
  await expect(page.getByText('未打标（全局）', { exact: true })).toHaveCount(90);
  await page.screenshot({ path: info.outputPath('migrated-library.png'), fullPage: true });
  const first = report.items[0];
  await page.locator('tbody tr').filter({ hasText: first.paper_id }).getByRole('button', { name: '查看', exact: true }).click();
  await expect(page.getByRole('heading', { name: first.legacy_metadata.title, exact: true })).toBeVisible();
  await expect(page.getByText('未打标（全局），可在编辑时逐步补充分类。', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '预览', exact: true }).click();
  await expect(page.getByTitle('PDF 预览')).toHaveAttribute('src', /^blob:/);
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存草稿', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '分类标签', exact: true })).toBeVisible();
});
