import { test, expect } from '@playwright/test';

test('starred question conflict preserves draft and requires explicit reload before saving', async ({ page }) => {
  let record = { question_id: 'shared', question: '原始问题', answer: '原始答案', revision: 1, created_at: '2026-10-16', updated_at: '2026-10-16' };
  const writes: Record<string, unknown>[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'mock-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/eval/starred-questions') json = [record];
    else if (path === '/api/eval/starred-questions/shared') {
      const body = route.request().postDataJSON();
      writes.push(body);
      if (body.expected_revision !== record.revision) {
        await route.fulfill({ status: 409, json: { detail: { code: 'starred_question_conflict', message: '内容已被其他人更新。' } } });
        return;
      }
      record = { ...record, question: body.question, answer: body.answer, revision: record.revision + 1 };
      json = record;
    } else throw new Error(`Unexpected API request ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/starred-questions');
  await page.getByLabel('账号', { exact: true }).fill('review');
  await page.getByLabel('密码', { exact: true }).fill('mock-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  const form = page.getByRole('form', { name: '编辑问题' });
  await form.getByRole('textbox').first().fill('修改问题措辞');
  record = { ...record, answer: '专家补录答案', revision: 2 };
  await form.getByRole('button', { name: '保存', exact: true }).click();
  await expect(form.getByRole('alert')).toContainText('你的输入已保留');
  await expect(form.getByRole('textbox').first()).toHaveValue('修改问题措辞');
  await expect(form.getByRole('textbox').nth(1)).toHaveValue('原始答案');
  await expect(form.getByRole('button', { name: '保存', exact: true })).toBeDisabled();
  expect(writes[0].expected_revision).toBe(1);
  await form.getByRole('button', { name: '载入最新版本' }).click();
  await expect(form.getByRole('textbox').nth(1)).toHaveValue('专家补录答案');
  await form.getByRole('textbox').first().fill('修改问题措辞');
  await form.getByRole('button', { name: '保存', exact: true }).click();
  await expect(form).toHaveCount(0);
  expect(writes[1].expected_revision).toBe(2);
  expect(record.answer).toBe('专家补录答案');
  expect(record.question).toBe('修改问题措辞');
});

test('all children leave parent partial; selecting parent includes directly assigned cases', async ({ page }) => {
  let lastFilter = '';
  const records = ['parent', 'maize', 'wheat'].map((tag, i) => ({
    id: `C-${String(i + 1).repeat(16)}`, title: `Tagged ${tag}`, summary: 'Fixture', revision: 1,
    tag_ids: [tag], enabled: true, has_explanation: false, updated_by: 'tester', updated_at: '2026-10-16T01:00:00Z',
  }));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let json: unknown;
    if (url.pathname === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (url.pathname === '/api/eval/login') json = { token: 'mock-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (url.pathname === '/api/case-library/taxonomy') json = {
      dimensions: [{ id: 'crop', name: '作物', enabled: true, selection: 'multiple' }],
      tags: [
        { id: 'parent', dimension_id: 'crop', name: '粮食', path: '粮食', parent_id: null, enabled: true },
        { id: 'maize', dimension_id: 'crop', name: '玉米', path: '粮食 / 玉米', parent_id: 'parent', enabled: true },
        { id: 'wheat', dimension_id: 'crop', name: '小麦', path: '粮食 / 小麦', parent_id: 'parent', enabled: true },
      ],
    };
    else if (url.pathname === '/api/case-library') {
      lastFilter = url.searchParams.get('tags') || '';
      const items = !lastFilter || lastFilter.includes('parent') ? records : records.filter(record => lastFilter.split(',').includes(record.tag_ids[0]));
      json = { items, total: items.length, page: 1, page_size: 20 };
    } else throw new Error(`Unexpected API request ${url.pathname}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/case-library');
  await page.getByLabel('账号', { exact: true }).fill('review');
  await page.getByLabel('密码', { exact: true }).fill('mock-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('link', { name: 'Tagged parent', exact: true })).toBeVisible();
  await page.locator('summary').filter({ hasText: '分类标签' }).click();
  await page.getByRole('button', { name: '作物级联选择' }).click();
  await page.getByRole('button', { name: '展开 粮食' }).click();
  await page.getByRole('checkbox', { name: '粮食 / 玉米', exact: true }).check();
  await page.getByRole('checkbox', { name: '粮食 / 小麦', exact: true }).check();
  const parent = page.getByRole('checkbox', { name: '粮食', exact: true });
  await expect(parent).not.toBeChecked();
  await expect(parent).toHaveJSProperty('indeterminate', true);
  await expect.poll(() => lastFilter).toBe('maize,wheat');
  await expect(page.getByRole('link', { name: 'Tagged parent', exact: true })).toHaveCount(0);
  await parent.check();
  await expect(parent).toBeChecked();
  await expect(parent).toHaveJSProperty('indeterminate', false);
  await expect.poll(() => lastFilter).toBe('parent');
  await expect(page.getByRole('link', { name: 'Tagged parent', exact: true })).toBeVisible();
});
