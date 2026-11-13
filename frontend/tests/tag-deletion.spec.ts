import { expect, test, type Page } from '@playwright/test';

async function setup(page: Page, reject = false) {
  let deleted = false;
  const requests: string[] = [];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'developer' };
    else if (path === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'developer' } };
    else if (path === '/api/literature/taxonomy') json = {
      dimensions: [{ id: 'topic', name: '主题', enabled: 1, selection: 'multiple', required: 0 }],
      tags: deleted ? [] : [{ id: 'old', name: '旧标签', path: '旧标签', dimension_id: 'topic', parent_id: null,
        description: '', enabled: 1, sort_order: 0, paper_count: 1200, case_count: 25 }],
    };
    else if (path === '/api/literature/users') json = [];
    else if (path === '/api/literature/config') json = { max_pdf_mb: 100 };
    else if (path === '/api/literature/asset-tag-jobs') json = { items: [] };
    else if (path === '/api/literature/tags/old') {
      requests.push(route.request().method());
      if (reject) {
        await route.fulfill({ status: 500, json: { detail: { message: '删除失败，关联未修改。' } } });
        return;
      }
      deleted = true;
      json = { deleted: true, detached_paper_count: 1201, detached_case_count: 26 };
    } else throw new Error(`Unexpected request ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/literature-tags');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.locator('[data-tag-id="old"]')).toBeVisible();
  return requests;
}

test('delete assigned tag confirms detachment, reports actual counts and clears editing', async ({ page }) => {
  const requests = await setup(page);
  await page.evaluate(() => sessionStorage.setItem('literature-filters', JSON.stringify({ tags: ['old', 'kept'], keyword: '氮素', page: 3 })));
  const row = page.locator('[data-tag-id="old"]');
  await row.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByRole('heading', { name: '编辑标签' })).toBeVisible();
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('1200 篇文献、25 条案例');
    expect(dialog.message()).toContain('解除此标签的全部关联');
    expect(dialog.message()).toContain('文献、案例正文及其他标签均保留');
    await dialog.accept();
  });
  await row.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByRole('main').getByRole('status')).toContainText('1201 篇文献、26 条案例');
  await expect(row).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '编辑标签' })).toHaveCount(0);
  expect(await page.evaluate(() => JSON.parse(sessionStorage.getItem('literature-filters')!))).toEqual({ tags: ['kept'], keyword: '氮素', page: 1 });
  expect(requests).toEqual(['DELETE']);
});

test('cancel or failed deletion retains the tag and shows the error', async ({ page }) => {
  const requests = await setup(page, true);
  const row = page.locator('[data-tag-id="old"]');
  page.once('dialog', (dialog) => dialog.dismiss());
  await row.getByRole('button', { name: '删除', exact: true }).click();
  expect(requests).toEqual([]);
  await expect(row).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await row.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('删除失败');
  await expect(row).toBeVisible();
  expect(requests).toEqual(['DELETE']);
});
