import { test, expect } from '@playwright/test';

test('AI tags and conclusion can be reviewed, edited, saved and reloaded', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  let record = {
    id: 'P-TEST', revision: 1, title: '玉米田氮素淋失研究', authors: [], authors_unknown: false,
    publication_type: null, venue: '', venue_unknown: false, year: null, year_unknown: false,
    language: null, language_note: '', doi: '', source_url: '', source_note: '', abstract: '原有摘要',
    conclusion: '', version_note: '', related_paper_ids: [], related_papers: [], internal_note: '',
    tag_ids: ['maize'], registration: 'draft', usage: 'normal', filename: 'source.pdf', sha256: '',
    created_by: 'review-only', updated_by: 'review-only', created_at: '2026-10-15T01:00:00Z',
    updated_at: '2026-10-15T01:00:00Z', registered_by: null, registered_at: null, events: [],
  };
  const conclusion = 'Reduced irrigation decreased nitrogen leaching.\nResults apply to the study site.';
  let tagCalls = 0;
  let saveCalls = 0;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown = {};
    if (path === '/api/eval/me') json = { tester_id: 'review-only', role: 'developer' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'review-only', role: 'developer' } };
    else if (path === '/api/literature/taxonomy') json = {
      dimensions: [{ id: 'crop', name: '作物', enabled: 1, selection: 'single' }, { id: 'topic', name: '主题', enabled: 1, selection: 'multiple' }],
      tags: [{ id: 'maize', dimension_id: 'crop', parent_id: null, name: '玉米', path: '玉米', enabled: 1 },
        { id: 'leaching', dimension_id: 'topic', parent_id: null, name: '氮素淋失', path: '氮素淋失', enabled: 1 }],
    };
    else if (path === '/api/literature/users') json = [];
    else if (path === '/api/literature/papers' && route.request().method() === 'GET') json = { items: [], total: 0, counts: { total: 0, draft: 0, registered: 0, disabled: 0 } };
    else if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    else if (path === '/api/literature/papers/P-TEST/file') {
      await route.fulfill({ status: 200, contentType: 'application/pdf', body: '%PDF- preview fixture' }); return;
    } else if (path === '/api/literature/extract') {
      json = { fields: { title: '不应填入的标题', abstract: '不应填入的摘要', conclusion }, pages_read: 8, method: 'ai', warning: '' };
    } else if (path === '/api/literature/suggest-tags') {
      const body = route.request().postDataJSON();
      expect(body.paper_id).toBe('P-TEST');
      expect(body.conclusion).toBe(conclusion);
      expect(body.tag_ids).toContain('maize');
      if (++tagCalls === 2) {
        await route.fulfill({ status: 503, json: { detail: { message: 'AI 打标暂时失败，请重试；已有标签未修改。' } } }); return;
      }
      json = { tag_ids: ['maize', 'leaching'], added_tag_ids: ['leaching'], pages_read: 8 };
    } else if (path === '/api/literature/papers/P-TEST') {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON();
        expect(body.conclusion).toBe(conclusion + '\n手工补充说明');
        expect(body.tag_ids).toEqual(['maize', 'leaching']);
        if (++saveCalls === 1) {
          await route.fulfill({ status: 503, json: { detail: { message: '保存失败，请重试。' } } }); return;
        }
        record = { ...record, ...body, revision: record.revision + 1 };
      }
      json = record;
    } else throw new Error(`Unexpected API request: ${path}`);
    await route.fulfill({ status: 200, json });
  });

  await page.goto('/evaluation/literature/P-TEST?edit=1');
  await page.getByLabel('账号', { exact: true }).fill('cau_mock');
  await page.getByLabel('密码', { exact: true }).fill('CauMock123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.locator('summary').filter({ hasText: '来源与补充说明' }).click();
  const conclusionField = page.getByRole('textbox', { name: '结论', exact: true });
  await page.getByRole('button', { name: 'AI 解析字段', exact: true }).click();
  await page.getByRole('button', { name: '填入所选字段' }).click();
  await expect(conclusionField).toHaveValue(conclusion);


  await conclusionField.fill('已有人工结论');
  await page.getByRole('button', { name: 'AI 解析字段', exact: true }).click();
  const panel = page.locator('section').filter({ has: page.getByRole('heading', { name: 'PDF 字段解析建议', exact: true }) });
  await expect(panel.getByRole('checkbox', { name: '全选解析字段', exact: true })).toBeChecked();
  await expect(conclusionField).toHaveValue('已有人工结论');
  await panel.getByRole('checkbox', { name: '全选解析字段', exact: true }).uncheck();
  await expect(panel.getByRole('button', { name: '填入所选字段' })).toBeDisabled();
  await panel.getByRole('checkbox', { name: '全选解析字段', exact: true }).check();
  await panel.getByRole('button', { name: '填入所选字段' }).click();
  await expect(conclusionField).toHaveValue(conclusion);
  await page.getByRole('button', { name: 'AI 一键打标', exact: true }).click();
  await expect(page.getByRole('button', { name: '移除标签 氮素淋失' })).toBeVisible();
  await expect(page.getByRole('button', { name: '移除标签 玉米' })).toBeVisible();
  await page.getByRole('button', { name: 'AI 一键打标', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'AI 打标暂时失败' })).toBeVisible();
  await expect(page.getByRole('button', { name: '移除标签 氮素淋失' })).toBeVisible();
  await conclusionField.fill(conclusion + '\n手工补充说明');
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(conclusionField).toHaveValue(conclusion + '\n手工补充说明');
  await expect(page.getByRole('main').getByRole('alert').filter({ hasText: '保存失败' })).toBeVisible();
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/literature\/P-TEST$/);
  await page.reload();
  await page.locator('summary').filter({ hasText: '来源与补充说明' }).click();
  await expect(page.getByText(conclusion + '\n手工补充说明', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '氮素淋失', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});
