import { test, expect } from '@playwright/test';

test('slow upload preserves a title typed while waiting', async ({ page }) => {
  let release!: () => void;
  let entered!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const received = new Promise<void>((resolve) => { entered = resolve; });
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = {};
    if (path === '/api/eval/me') json = { tester_id: 'review-only', role: 'developer' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'review-only', role: 'developer' } };
    else if (path === '/api/literature/taxonomy') json = { dimensions: [], tags: [] };
    else if (path === '/api/literature/users') json = [];
    else if (path === '/api/literature/papers' && route.request().method() === 'GET') json = { items: [], total: 0, counts: { total: 0, draft: 0, registered: 0, disabled: 0 } };
    else if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    else if (path === '/api/literature/uploads') { entered(); await pending; json = { upload_id: 'mock-upload', filename: 'source.pdf' }; }
    else if (path === '/api/literature/extract') json = { fields: { title: 'AI title' }, pages_read: 1, method: 'ai', warning: '' };
    else throw new Error(`Unexpected API request: ${path}`);
    await route.fulfill({ status: 200, json });
  });
  await page.goto('/evaluation/literature/new');
  await page.getByLabel('账号', { exact: true }).fill('cau_mock');
  await page.getByLabel('密码', { exact: true }).fill('CauMock123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.locator('input[type=file]').setInputFiles({ name: 'source.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF- intercepted fixture') });
  await received;
  const title = page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox');
  await title.fill('手工填写的论文标题');
  release();
  await expect(page.getByRole('main').getByRole('status')).toContainText('已读取 PDF');
  await expect(title).toHaveValue('手工填写的论文标题');
});

test('conflicting edit preserves inputs until latest version is explicitly loaded', async ({ page }) => {
  const paper = { id: 'P-TEST', revision: 1, title: '原始标题', authors: [], authors_unknown: false, publication_type: null, venue: '', venue_unknown: false, year: null, year_unknown: false, language: null, language_note: '', doi: '', source_url: '', source_note: '', abstract: '', version_note: '', related_paper_ids: [], related_papers: [], internal_note: '', tag_ids: [], registration: 'draft', usage: 'normal', filename: 'source.pdf', sha256: '', created_by: 'review-only', updated_by: 'review-only', created_at: '2026-10-10T18:30:00Z', updated_at: '2026-10-10T18:30:00Z', registered_by: null, registered_at: null, events: [] };
  let conflict = false;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = {};
    if (path === '/api/eval/me') json = { tester_id: 'review-only', role: 'developer' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'review-only', role: 'developer' } };
    else if (path === '/api/literature/taxonomy') json = { dimensions: [], tags: [] };
    else if (path === '/api/literature/users') json = [];
    else if (path === '/api/literature/papers' && route.request().method() === 'GET') json = { items: [], total: 0, counts: { total: 0, draft: 0, registered: 0, disabled: 0 } };
    else if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    else if (path === '/api/literature/papers/P-TEST') {
      if (route.request().method() === 'PUT') {
        expect(route.request().postDataJSON().expected_revision).toBe(1);
        conflict = true;
        await route.fulfill({ status: 409, json: { detail: { code: 'paper_revision_conflict', message: '文献已被其他操作更新，当前输入已保留。' } } }); return;
      }
      json = conflict ? { ...paper, revision: 2, title: '他人更正后的标题' } : paper;
    } else if (path === '/api/literature/papers/P-TEST/file') {
      await route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF- preview fixture' }); return;
    } else throw new Error(`Unexpected API request: ${path}`);
    await route.fulfill({ status: 200, json });
  });
  await page.goto('/evaluation/literature/P-TEST?edit=1');
  await page.getByLabel('账号', { exact: true }).fill('cau_mock');
  await page.getByLabel('密码', { exact: true }).fill('CauMock123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  const title = page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox');
  await title.fill('我的未保存标题');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('当前输入已保留');
  await expect(title).toHaveValue('我的未保存标题');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: '加载最新版本重新编辑' }).click();
  await expect(title).toHaveValue('我的未保存标题');
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '加载最新版本重新编辑' }).click();
  await expect(title).toHaveValue('他人更正后的标题');
});
