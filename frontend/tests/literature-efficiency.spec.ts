import { expect, test, type Page, type Route } from '@playwright/test';

const paper = (id: string) => ({
  id, revision: 1, title: `Paper ${id}`, authors: [], authors_unknown: false, publication_type: null,
  venue: '', venue_unknown: false, year: null, year_unknown: false, language: null, language_note: '',
  doi: '', source_url: '', source_note: '', abstract: '', conclusion: '', version_note: '', related_paper_ids: [],
  internal_note: '', tag_ids: [], registration: 'draft', usage: 'normal', filename: `${id}.pdf`, sha256: '',
  created_by: 'tester', updated_by: 'tester', created_at: '2026-10-15T01:00:00Z', updated_at: '2026-10-15T01:00:00Z',
  registered_by: null, registered_at: null, events: [], related_papers: [],
});
const pdf = (name: string) => ({ name, mimeType: 'application/pdf', buffer: Buffer.from('%PDF- fixture') });
async function mockCommon(page: Page, custom: (route: Route, path: string) => Promise<boolean>) {
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (await custom(route, path)) return;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'developer' };
    else if (path === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'developer' } };
    else if (path === '/api/literature/taxonomy') json = {
      dimensions: [{ id: 'crop', name: '作物', enabled: 1, selection: 'single' }],
      tags: ['first', 'second'].map((id) => ({ id, dimension_id: 'crop', parent_id: null, name: id, path: id, enabled: 1 })),
    };
    else if (path === '/api/literature/users') json = [];
    else if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    else if (path === '/api/literature/imports') json = { items: [] };
    else if (path === '/api/literature/duplicates') json = { papers: [] };
    else if (path === '/api/literature/papers') json = { items: [], total: 0, counts: { total: 0, draft: 0, registered: 0, disabled: 0 } };
    else throw new Error(`Unexpected request ${path}`);
    await route.fulfill({ status: 200, json });
  });
}
async function login(page: Page, path: string) {
  await page.goto(path);
  await page.getByLabel('账号', { exact: true }).fill('cau_tester');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
}

test('select 90 existing records and run independent AI operations', async ({ page }) => {
  const records = Array.from({ length: 90 }, (_, i) => paper(`P-${i}`));
  const requests: { paper_ids: string[]; ai_extract: boolean; ai_tag: boolean }[] = [];
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/papers') {
      const size = Number(new URL(route.request().url()).searchParams.get('page_size') || 20);
      await route.fulfill({ json: { items: records.slice(0, size), total: 90, counts: { total: 90, draft: 90, registered: 0, disabled: 0 } } }); return true;
    }
    if (path === '/api/literature/imports/job') { await route.fulfill({ json: { id: 'job', items: [] } }); return true; }
    if (path === '/api/literature/batch-ai') {
      requests.push(route.request().postDataJSON());
      await route.fulfill({ status: 202, json: { id: 'job', items: [] } }); return true;
    }
    return false;
  });
  await login(page, '/evaluation/literature');
  const run = page.getByRole('button', { name: 'AI 解析所选文献', exact: true });
  await expect(page.getByRole('button', { name: '批量 AI 解析 · 已选 0 篇' })).toBeDisabled();
  await page.getByLabel('每页条数', { exact: true }).selectOption('100');
  await expect(page.getByRole('checkbox', { name: /^选择文献 / })).toHaveCount(90);
  await page.getByLabel('全选本页文献', { exact: true }).check();
  await page.getByRole('button', { name: '批量 AI 解析 · 已选 90 篇' }).click();
  await expect(page.getByLabel('AI 解析字段', { exact: true })).toBeChecked();
  await expect(page.getByLabel('AI 一键打标', { exact: true })).toBeChecked();
  await page.getByLabel('AI 一键打标', { exact: true }).uncheck();
  await run.click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0]).toEqual({ paper_ids: records.map((record) => record.id), ai_extract: true, ai_tag: false });
  await expect(page.getByRole('button', { name: '批量 AI 解析 · 已选 0 篇' })).toBeVisible();
  await page.getByRole('button', { name: '关闭流程' }).click();
  await page.getByRole('checkbox', { name: /^选择文献 / }).first().check();
  await page.getByRole('button', { name: '批量 AI 解析 · 已选 1 篇' }).click();
  await page.getByLabel('AI 解析字段', { exact: true }).uncheck();
  await expect(run).toBeDisabled();
  await page.getByLabel('AI 一键打标', { exact: true }).check();
  await run.click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1]).toEqual({ paper_ids: ['P-0'], ai_extract: false, ai_tag: true });
  await page.getByRole('button', { name: '关闭流程' }).click();
  await page.getByLabel('全选本页文献', { exact: true }).check();
  await page.getByLabel('每页条数', { exact: true }).selectOption('20');
  await expect(page.getByRole('button', { name: '批量 AI 解析 · 已选 0 篇' })).toBeVisible();
});

test('single upload auto fills and tags; replacement clears old PDF fields and failed upload preserves new file', async ({ page }) => {
  let saved: Record<string, unknown> | undefined;
  const tagged: string[] = [];
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/uploads') {
      const name = new URL(route.request().url()).searchParams.get('filename')!;
      if (name === 'bad.pdf') await route.fulfill({ status: 422, json: { detail: { message: 'PDF 无法正常打开。' } } });
      else await route.fulfill({ json: { upload_id: name.replace('.pdf', '') } });
      return true;
    }
    if (path === '/api/literature/extract') {
      const id = route.request().postDataJSON().upload_id;
      await route.fulfill({ json: { fields: { title: `${id} title`, abstract: id === 'first' ? 'Old abstract' : '', conclusion: `${id} conclusion` }, pages_read: 2, warning: '', method: 'ai' } }); return true;
    }
    if (path === '/api/literature/suggest-tags') {
      const body = route.request().postDataJSON();
      tagged.push(body.upload_id);
      expect(body.title).toBe(`${body.upload_id} title`);
      expect(body.tag_ids).toEqual([]);
      await route.fulfill({ json: { tag_ids: [body.upload_id], added_tag_ids: [body.upload_id] } }); return true;
    }
    if (path === '/api/literature/papers' && route.request().method() === 'POST') {
      saved = route.request().postDataJSON();
      await route.fulfill({ json: { ...paper('P-SAVED'), ...saved } }); return true;
    }
    if (path === '/api/literature/papers/P-SAVED') {
      await route.fulfill({ json: { ...paper('P-SAVED'), ...saved } }); return true;
    }
    if (path.endsWith('/file')) { await route.fulfill({ contentType: 'application/pdf', body: '%PDF-fixture' }); return true; }
    return false;
  });
  await login(page, '/evaluation/literature/new');
  const upload = page.locator('input[type=file]');
  const title = page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox');
  await upload.setInputFiles(pdf('first.pdf'));
  await expect(title).toHaveValue('first title');
  await expect(page.getByRole('button', { name: '移除标签 first' })).toBeVisible();
  await expect(page.getByLabel('全选解析字段', { exact: true })).toBeChecked();
  await upload.setInputFiles(pdf('second.pdf'));
  await expect(title).toHaveValue('second title');
  await expect(page.getByRole('button', { name: '移除标签 second' })).toBeVisible();
  await expect(page.getByRole('button', { name: '移除标签 first' })).toHaveCount(0);
  await page.locator('summary').filter({ hasText: '来源与补充说明' }).click();
  await expect(page.getByRole('group', { name: '摘要', exact: true }).getByRole('textbox')).toHaveValue('');
  await expect(page.getByRole('textbox', { name: '结论', exact: true })).toHaveValue('second conclusion');
  await upload.setInputFiles(pdf('bad.pdf'));
  await expect(page.getByRole('alert').filter({ hasText: 'PDF 无法正常打开' })).toBeVisible();
  await expect(title).toHaveValue('second title');
  await expect(page.getByRole('button', { name: '移除标签 second' })).toBeVisible();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect.poll(() => saved?.upload_id).toBe('second');
  expect(saved?.title).toBe('second title');
  expect(saved?.abstract).toBe('');
  expect(saved?.tag_ids).toEqual(['second']);
  expect(tagged).toEqual(['first', 'second']);
});

test('late extraction from replaced file cannot update fields or start old tagging', async ({ page }) => {
  let oldRoute: Route | undefined;
  const tagged: string[] = [];
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/uploads') {
      await route.fulfill({ json: { upload_id: new URL(route.request().url()).searchParams.get('filename')!.replace('.pdf', '') } }); return true;
    }
    if (path === '/api/literature/extract') {
      if (route.request().postDataJSON().upload_id === 'first') { oldRoute = route; return true; }
      await route.fulfill({ json: { fields: { title: 'New correct title' }, warning: '', pages_read: 1, method: 'ai' } }); return true;
    }
    if (path === '/api/literature/suggest-tags') {
      tagged.push(route.request().postDataJSON().upload_id);
      await route.fulfill({ json: { tag_ids: ['second'], added_tag_ids: ['second'] } }); return true;
    }
    return false;
  });
  await login(page, '/evaluation/literature/new');
  await page.locator('input[type=file]').setInputFiles(pdf('first.pdf'));
  await expect.poll(() => Boolean(oldRoute)).toBe(true);
  await page.locator('input[type=file]').setInputFiles(pdf('second.pdf'));
  await expect(page.getByRole('button', { name: '移除标签 second' })).toBeVisible();
  await oldRoute!.fulfill({ json: { fields: { title: 'Late wrong title' }, warning: '', pages_read: 1, method: 'ai' } });
  await expect(page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox')).toHaveValue('New correct title');
  expect(tagged).toEqual(['second']);
});

test('filter parents remain partial until explicitly selected and global untagged clears tags', async ({ page }) => {
  const queries: string[] = [];
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/taxonomy') {
      await route.fulfill({ json: { dimensions: [{ id: 'topic', name: '主题', enabled: 1 }], tags: [
        { id: 'parent', parent_id: null, name: '父级', path: '父级' },
        { id: 'a', parent_id: 'parent', name: '甲', path: '父级 / 甲' },
        { id: 'b', parent_id: 'parent', name: '乙', path: '父级 / 乙' },
      ].map((node) => ({ ...node, dimension_id: 'topic', enabled: 1 })) } }); return true;
    }
    if (path === '/api/literature/papers') queries.push(route.request().url());
    return false;
  });
  await login(page, '/evaluation/literature');
  await page.getByRole('button', { name: '主题级联选择' }).click();
  const parent = page.getByRole('checkbox', { name: '父级', exact: true });
  await page.getByText('父级', { exact: true }).click();
  await expect(parent).toBeChecked();
  await page.getByRole('button', { name: '展开 父级' }).click();
  await expect(parent).toBeChecked();
  await page.getByText('父级', { exact: true }).click();
  await expect(parent).not.toBeChecked();
  // Click the padded blank area, away from the checkbox and label text.
  await page.locator('label[title="父级 / 甲"]').click({ position: { x: 120, y: 35 } });
  await expect(page.getByRole('checkbox', { name: '父级', exact: true })).not.toBeChecked();
  await page.getByRole('checkbox', { name: '父级 / 乙', exact: true }).check();
  await expect(parent).not.toBeChecked();
  await expect(parent).toHaveJSProperty('indeterminate', true);
  await parent.check();
  await expect(parent).toBeChecked();
  await expect(parent).toHaveJSProperty('indeterminate', false);
  await page.getByRole('checkbox', { name: '父级 / 甲', exact: true }).uncheck();
  await expect(page.getByRole('checkbox', { name: '父级', exact: true })).not.toBeChecked();
  await page.getByRole('checkbox', { name: '父级', exact: true }).check();
  await expect(page.getByRole('checkbox', { name: '父级 / 甲', exact: true })).toBeChecked();
  await page.getByRole('checkbox', { name: '父级 / 乙', exact: true }).uncheck();
  await expect(page.getByRole('checkbox', { name: '父级', exact: true })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: '父级 / 甲', exact: true })).toBeChecked();
  await page.getByRole('button', { name: '关闭标签选择' }).click();
  await page.getByRole('checkbox', { name: '未打标（全局）' }).check();
  await expect.poll(() => queries.at(-1)).toContain('untagged=true');
  expect(new URL(queries.at(-1)!).searchParams.has('tags')).toBe(false);
});

test('current AI batch keeps failures for individual retry and shows completion', async ({ page }) => {
  const item = { filename: 'P-1.pdf', paper_id: 'P-1', status: 'warning', warnings: ['解析暂时失败'], retryable: true };
  const batch = { id: 'current', items: [item] };
  let retried = false;
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/papers') { await route.fulfill({ json: { items: [paper('P-1')], total: 1, counts: { total: 1, draft: 1, registered: 0, disabled: 0 } } }); return true; }
    if (path === '/api/literature/batch-ai' || path === '/api/literature/imports/current') { await route.fulfill({ json: batch }); return true; }
    if (path === '/api/literature/imports/current/retry') {
      expect(route.request().postDataJSON()).toEqual({ paper_ids: ['P-1'] });
      retried = true; Object.assign(item, { status: 'ready', warnings: [], retryable: false });
      await route.fulfill({ json: batch }); return true;
    }
    if (path === '/api/literature/imports') throw new Error('Must not fetch historical batches');
    return false;
  });
  await login(page, '/evaluation/literature');
  await page.getByLabel('全选本页文献', { exact: true }).check();
  await page.getByRole('button', { name: '批量 AI 解析 · 已选 1 篇' }).click();
  await page.getByRole('button', { name: 'AI 解析所选文献', exact: true }).click();
  await expect(page.getByText('解析暂时失败', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '重新解析此文献' }).click();
  await expect(page.getByText('本批次全部成功解析并录入，流程已完成。')).toBeVisible();
  expect(retried).toBe(true);
  await page.getByRole('button', { name: '完成', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
});

test('untagged checkbox immediately filters maize records and survives reload', async ({ page }) => {
  const records = [paper('PLAIN'), { ...paper('MAIZE'), tag_ids: ['first'] }];
  await mockCommon(page, async (route, path) => {
    if (path !== '/api/literature/papers') return false;
    const params = new URL(route.request().url()).searchParams;
    const items = params.get('untagged') === 'true' ? records.filter((record) => !record.tag_ids.length) : records;
    await route.fulfill({ json: { items, total: items.length, counts: { total: 2, draft: 2, registered: 0, disabled: 0 } } });
    return true;
  });
  await login(page, '/evaluation/literature');
  await expect(page.getByRole('button', { name: 'Paper MAIZE', exact: true })).toBeVisible();
  await page.getByLabel('未打标（全局）', { exact: true }).check();
  await expect(page.getByRole('button', { name: 'Paper MAIZE', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Paper PLAIN', exact: true })).toBeVisible();
  await expect(page.getByText('共 1 条结果', { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel('未打标（全局）', { exact: true })).toBeChecked();
  await expect(page.getByRole('button', { name: 'Paper MAIZE', exact: true })).toHaveCount(0);
  await page.getByLabel('未打标（全局）', { exact: true }).uncheck();
  await expect(page.getByRole('button', { name: 'Paper MAIZE', exact: true })).toBeVisible();
});

test('tag editing stays locked through extraction and tagging, then manual choices persist', async ({ page }) => {
  let extraction: Route | undefined;
  let tagging: Route | undefined;
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/uploads') { await route.fulfill({ json: { upload_id: 'first' } }); return true; }
    if (path === '/api/literature/extract') { extraction = route; return true; }
    if (path === '/api/literature/suggest-tags') { tagging = route; return true; }
    return false;
  });
  await login(page, '/evaluation/literature/new');
  await page.locator('input[type=file]').setInputFiles(pdf('first.pdf'));
  await expect.poll(() => Boolean(extraction)).toBe(true);
  const picker = page.getByRole('button', { name: '作物级联选择' });
  await expect(picker).toBeDisabled();
  await extraction!.fulfill({ json: { fields: { title: 'Extracted title' }, warning: '', pages_read: 1, method: 'ai' } });
  await expect.poll(() => Boolean(tagging)).toBe(true);
  await expect(picker).toBeDisabled();
  await tagging!.fulfill({ json: { tag_ids: ['first'], added_tag_ids: ['first'] } });
  await expect(picker).toBeEnabled();
  await picker.click();
  await page.getByRole('checkbox', { name: 'second', exact: true }).check();
  await expect(page.getByRole('button', { name: '移除标签 second' })).toBeVisible();
  await expect(page.getByRole('button', { name: '移除标签 first' })).toHaveCount(0);
});

test('interrupted queued item can retry while other entries remain active', async ({ page }) => {
  const batch = { id: 'interrupted', created_at: '2026-10-16T01:00:00Z', items: [
    { filename: 'stale.pdf', paper_id: 'P-STALE', status: 'queued', retryable: true, warnings: [] },
    { filename: 'active.pdf', paper_id: 'P-ACTIVE', status: 'processing', retryable: false, warnings: [] },
  ] };
  let retried = false;
  await mockCommon(page, async (route, path) => {
    if (path === '/api/literature/imports') { await route.fulfill({ json: { items: [batch] } }); return true; }
    if (path === '/api/literature/imports/interrupted') { await route.fulfill({ json: batch }); return true; }
    if (path === '/api/literature/imports/interrupted/retry') {
      expect(route.request().postDataJSON()).toEqual({ paper_ids: ['P-STALE'] });
      retried = true;
      Object.assign(batch.items[0], { status: 'ready', retryable: false });
      await route.fulfill({ json: batch }); return true;
    }
    return false;
  });
  await login(page, '/evaluation/literature');
  await page.getByRole('button', { name: '近期批次与恢复' }).click();
  await page.getByRole('button', { name: /批量导入 · .*stale.pdf/ }).click();
  await expect(page.getByText('本批次正在处理…')).toBeVisible();
  await page.getByRole('button', { name: '重新解析此文献' }).click();
  await expect.poll(() => retried).toBe(true);
});
