import { test, expect } from '@playwright/test';

test('batch limit, defaults, mixed uploads, background receipts and review links', async ({ page }) => {
  let batch: unknown = null;
  let uploaded = 0;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = {};
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/literature/taxonomy') json = { dimensions: [], tags: [] };
    else if (path === '/api/literature/users') json = [];
    else if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    else if (path === '/api/literature/papers') json = { items: [], total: 0, counts: { total: 0, draft: 0, registered: 0, disabled: 0 } };
    else if (path === '/api/literature/uploads') {
      const filename = new URL(route.request().url()).searchParams.get('filename');
      if (filename === 'duplicate.pdf') {
        await route.fulfill({ status: 409, json: { detail: { message: '已有相同内容的 PDF。', paper_id: 'P-OLD' } } }); return;
      }
      json = { upload_id: `upload-${++uploaded}` };
    } else if (path === '/api/literature/imports') {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        expect(body.ai_extract).toBe(true);
        expect(body.ai_tag).toBe(true);
        expect(body.upload_ids).toHaveLength(2);
        batch = { id: 'batch-1', created_at: '2026-10-15T01:00:00Z', items: [
          { filename: 'first.pdf', paper_id: 'P-FIRST', status: 'ready', warnings: [] },
          { filename: 'second.pdf', paper_id: 'P-SECOND', status: 'warning', warnings: ['AI 打标暂不可用，草稿已保存。'] },
        ] };
        json = batch;
      } else json = { items: batch ? [batch] : [] };
    } else if (path === '/api/literature/imports/batch-1') json = batch;
    else throw new Error(`Unexpected request: ${path}`);
    await route.fulfill({ status: 200, json });
  });
  await page.goto('/evaluation/literature');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByRole('button', { name: '批量导入', exact: true }).click();
  await expect(page.getByLabel('AI 解析字段')).toBeChecked();
  await expect(page.getByLabel('AI 一键打标')).toBeChecked();
  const pdf = (name: string) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF- fixture ' + name) });
  await page.getByLabel('批量选择 PDF').setInputFiles(Array.from({ length: 101 }, (_, i) => pdf(`${i}.pdf`)));
  await expect(page.getByRole('alert').filter({ hasText: '最多 100 篇' })).toBeVisible();
  expect(uploaded).toBe(0);
  await page.getByLabel('批量选择 PDF').setInputFiles([pdf('first.pdf'), pdf('duplicate.pdf'), pdf('second.pdf'), { ...pdf('first.pdf'), name: 'same-content.pdf' }, { name: 'empty.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(0) }]);
  await page.getByRole('button', { name: '上传并校验' }).click();
  await expect(page.getByText('有效文献 2 篇 / 已选择 5 篇')).toBeVisible();
  await expect(page.getByText('与本批次文件内容重复。', { exact: false })).toBeVisible();
  await expect(page.getByText('文件为空。', { exact: false })).toBeVisible();
  expect(uploaded).toBe(2);
  await page.getByRole('button', { name: '处理并录入' }).click();
  await expect(page.getByRole('link', { name: '审核文献' })).toHaveCount(2);
  await expect(page.getByText('AI 打标暂不可用，草稿已保存。')).toBeVisible();
  await expect(page.getByRole('link', { name: '查看现有文献' })).toHaveAttribute('href', '/evaluation/literature/P-OLD');
  await expect(page.getByRole('link', { name: '审核文献' }).first()).toHaveAttribute('href', '/evaluation/literature/P-FIRST?edit=1');
  await page.getByRole('button', { name: '关闭流程' }).click();
  await page.getByRole('button', { name: '近期批次与恢复' }).click();
  await page.getByRole('button', { name: /批量导入 · .*first.pdf/ }).click();
  await expect(page.getByRole('link', { name: '审核文献' })).toHaveCount(2);
  await page.reload();
  await page.getByRole('button', { name: '批量导入', exact: true }).click();
  await expect(page.getByRole('link', { name: '审核文献' })).toHaveCount(0);
  await page.getByRole('button', { name: '关闭流程' }).click();
  await page.getByRole('button', { name: '近期批次与恢复' }).click();
  await page.getByRole('button', { name: /批量导入 · .*first.pdf/ }).click();
  await expect(page.getByText('AI 打标暂不可用，草稿已保存。')).toBeVisible();
});

test('repeated file selections accumulate and retain completed uploads', async ({ page }) => {
  const uploaded: string[] = [];
  let submitted: string[] = [];
  const batch = { id: 'accumulated', created_at: '2026-10-16T00:00:00Z', items: [
    { filename: 'first.pdf', paper_id: 'P-FIRST', status: 'ready', warnings: [] },
    { filename: 'second.pdf', paper_id: 'P-SECOND', status: 'ready', warnings: [] },
  ] };
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let json: unknown = {};
    if (url.pathname === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (url.pathname === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (url.pathname.endsWith('/taxonomy')) json = { dimensions: [], tags: [] };
    else if (url.pathname.endsWith('/users')) json = [];
    else if (url.pathname.endsWith('/config')) json = { max_pdf_mb: 100 };
    else if (url.pathname.endsWith('/papers')) json = { items: [], total: 0, counts: { total: 0, draft: 0, registered: 0, disabled: 0 } };
    else if (url.pathname.endsWith('/uploads')) {
      uploaded.push(url.searchParams.get('filename')!);
      json = { upload_id: `upload-${uploaded.length}` };
    } else if (url.pathname.endsWith('/imports') && route.request().method() === 'POST') {
      submitted = route.request().postDataJSON().upload_ids;
      json = batch;
    } else if (url.pathname.endsWith('/imports/accumulated')) json = batch;
    else throw new Error(`Unexpected request: ${url.pathname}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/literature');
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByRole('button', { name: '批量导入', exact: true }).click();
  const picker = page.getByLabel('批量选择 PDF');
  const pdf = (name: string) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF- fixture ' + name) });
  await picker.setInputFiles([pdf('first.pdf'), pdf('remove.pdf')]);
  await page.getByRole('button', { name: '移除 remove.pdf', exact: true }).click();
  await page.getByRole('button', { name: '上传并校验' }).click();
  await expect(page.getByText('有效文献 1 篇 / 已选择 1 篇')).toBeVisible();
  await picker.setInputFiles([]); // Cancelling must not clear the existing queue.
  await expect(page.getByText('有效文献 1 篇 / 已选择 1 篇')).toBeVisible();
  await picker.setInputFiles(Array.from({ length: 100 }, (_, i) => pdf(`${i}.pdf`)));
  await expect(page.getByRole('alert').filter({ hasText: '已保留当前队列' })).toBeVisible();
  await expect(page.getByText('有效文献 1 篇 / 已选择 1 篇')).toBeVisible();
  await picker.setInputFiles([pdf('second.pdf'), { ...pdf('first.pdf'), name: 'renamed-first.pdf' }]);
  await expect(page.getByText('有效文献 1 篇 / 已选择 3 篇')).toBeVisible();
  await expect(page.getByRole('button', { name: '处理并录入', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '上传并校验' }).click();
  await expect(page.getByText('有效文献 2 篇 / 已选择 3 篇')).toBeVisible();
  await expect(page.getByText('与本批次文件内容重复。', { exact: false })).toBeVisible();
  expect(uploaded).toEqual(['first.pdf', 'second.pdf']);
  await page.getByLabel('AI 解析字段').uncheck();
  await page.getByLabel('AI 一键打标').uncheck();
  await page.getByRole('button', { name: '处理并录入', exact: true }).click();
  await expect(page.getByRole('link', { name: '审核文献' })).toHaveCount(2);
  expect(submitted).toEqual(['upload-1', 'upload-2']);
});
