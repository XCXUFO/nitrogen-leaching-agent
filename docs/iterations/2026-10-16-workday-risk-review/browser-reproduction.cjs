const path = require('node:path');
const { chromium, expect } = require(path.resolve(__dirname, '../../../frontend/node_modules/@playwright/test'));

(async () => {
  const browser = await chromium.launch({ channel: 'chromium' });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    let lastFilter = '';
    const records = ['parent', 'maize', 'wheat'].map((tag, i) => ({
      id: `C-${String(i + 1).repeat(16)}`, title: `Tagged ${tag}`, summary: 'Fixture', revision: 1,
      tag_ids: [tag], enabled: true, has_explanation: false, updated_by: 'tester', updated_at: '2026-10-16T01:00:00Z',
    }));
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url());
      let data;
      if (url.pathname === '/api/eval/me') data = { tester_id: 'tester', role: 'tester' };
      else if (url.pathname === '/api/eval/login') data = { token: 'review-only-mocked-token', user: { tester_id: 'tester', role: 'tester' } };
      else if (url.pathname === '/api/case-library/taxonomy') data = {
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
        data = { items, total: items.length, page: 1, page_size: 20 };
      } else throw new Error(`Unexpected mocked endpoint ${url.pathname}`);
      await route.fulfill({ json: data });
    });
    await page.goto(`${process.env.UI_BASE_URL || 'http://127.0.0.1:3000'}/evaluation/case-library`);
    await page.getByLabel('账号', { exact: true }).fill('review');
    await page.getByLabel('密码', { exact: true }).fill('review-mocked-password');
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
    await expect(parent).toHaveJSProperty('indeterminate', false);
    await expect.poll(() => lastFilter).toBe('parent');
    await expect(page.getByRole('link', { name: 'Tagged parent', exact: true })).toBeVisible();
    console.log('FIXED: selecting the partial parent includes directly parent-tagged cases.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
