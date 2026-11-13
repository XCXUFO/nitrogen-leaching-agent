import { expect, test, type Page } from '@playwright/test';

const record = { id: 'readonly-case', revision: 1, title: '玉米水氮案例', body: '玉米分次施肥，未提供效果数据。', body_format: 'plain',
  explanation: '已保存的解释。', supplementary: '', source: '', enabled: true, tag_ids: [], has_explanation: true,
  summary: '玉米分次施肥。', created_by: 'developer', updated_by: 'developer', created_at: '2026-11-13T08:00:00Z', updated_at: '2026-11-13T08:00:00Z' };
const paper = { id: 'readonly-paper', revision: 1, title: '农田氮素研究', authors: [], authors_unknown: true, venue: '', venue_unknown: true,
  year: null, year_unknown: true, publication_type: '期刊论文', language: '中文', language_note: '', doi: '', source_url: '', source_note: '',
  abstract: '已保存的摘要。', conclusion: '已保存的结论。', version_note: '', internal_note: '', related_paper_ids: [], related_papers: [],
  tag_ids: [], registration: 'draft', usage: 'normal', filename: 'study.pdf', sha256: 'fixture', events: [], search_sync: { status: 'ready' },
  created_by: 'developer', updated_by: 'developer', created_at: '2026-11-13T08:00:00Z', updated_at: '2026-11-13T08:00:00Z' };

async function setup(page: Page, role: string) {
  const reads: string[] = [];
  const mutations: string[] = [];
  await page.addInitScript(() => sessionStorage.setItem('nitrogen_account_session', JSON.stringify({ token: 'readonly-token', username: 'reader' })));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    reads.push(path + url.search);
    if (route.request().method() !== 'GET') {
      mutations.push(path);
      return route.fulfill({ status: 403, json: { detail: { message: '仅可查看。' } } });
    }
    let json: unknown = [];
    if (path === '/api/eval/me') json = { tester_id: 'reader', role };
    if (path.endsWith('/taxonomy')) json = { dimensions: [], tags: [] };
    if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    if (path === '/api/case-library') json = { items: [record], total: 1, page: 1, page_size: 20 };
    if (path === '/api/case-library/' + record.id) json = record;
    if (path === '/api/literature/papers') json = { items: [paper], total: 1, page: 1, page_size: 20, counts: { total: 1, draft: 1, registered: 0, disabled: 0 } };
    if (path === '/api/literature/papers/' + paper.id) json = paper;
    if (path.endsWith('/file')) return route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' });
    return route.fulfill({ json });
  });
  return { reads, mutations };
}

for (const role of ['tester', 'reviewer']) {
  test(`${role} can search and read cases without entering a material editor`, async ({ page }) => {
    const state = await setup(page, role);
    await page.goto('/evaluation/case-library');
    const search = page.getByRole('textbox', { name: '关键词搜索' });
    await expect(search).toBeEnabled();
    await search.fill('玉米');
    await page.getByRole('button', { name: '搜索', exact: true }).click();
    await expect.poll(() => state.reads.some(url => url.includes('keyword=%E7%8E%89%E7%B1%B3'))).toBe(true);
    await page.getByRole('combobox', { name: '开放状态' }).selectOption('enabled');
    await expect.poll(() => state.reads.some(url => url.includes('availability=enabled'))).toBe(true);
    await expect(page.getByRole('link', { name: '新增案例', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: /^批量操作/ })).toHaveCount(0);
    await page.getByRole('link', { name: record.title, exact: true }).click();
    await expect(page.getByText(record.explanation, { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: '编辑', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '删除', exact: true })).toHaveCount(0);
    await page.goto(`/evaluation/case-library/${record.id}?edit=1`);
    await expect(page.getByText(record.explanation, { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '保存', exact: true })).toHaveCount(0);
    await page.goto('/evaluation/case-library/new');
    await expect(page.getByRole('alert').filter({ hasText: '新增案例需要开发者权限' })).toBeVisible();
    expect(state.mutations).toEqual([]);
  });

  test(`${role} can query literature, preview and download PDFs without modifying records`, async ({ page }) => {
    const state = await setup(page, role);
    await page.goto('/evaluation/literature');
    const search = page.getByRole('textbox', { name: '搜索文献' });
    await expect(search).toBeEnabled();
    await search.fill('氮素');
    await page.getByRole('button', { name: '查询', exact: true }).click();
    await expect.poll(() => state.reads.some(url => url.includes('keyword=%E6%B0%AE%E7%B4%A0'))).toBe(true);
    await expect(page.getByRole('button', { name: '编辑', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '删除', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: paper.title, exact: true }).click();
    await expect(page.getByTitle('PDF 原文预览')).toHaveAttribute('src', /^blob:/);
    await expect(page.getByRole('button', { name: 'AI 解析字段', exact: true })).toHaveCount(0);
    await expect(page.getByRole('button', { name: '同步全文索引', exact: true })).toHaveCount(0);
    const download = page.waitForEvent('download');
    await page.getByRole('button', { name: '下载', exact: true }).click();
    expect((await download).suggestedFilename()).toBe(paper.filename);
    await page.goto(`/evaluation/literature/${paper.id}?edit=1`);
    await expect(page.getByTitle('PDF 原文预览')).toHaveAttribute('src', /^blob:/);
    await expect(page.getByRole('button', { name: '保存草稿', exact: true })).toHaveCount(0);
    await page.goto('/evaluation/literature/new');
    await expect(page.getByRole('alert').filter({ hasText: '新增文献需要开发者权限' })).toBeVisible();
    expect(state.mutations).toEqual([]);
  });
}
