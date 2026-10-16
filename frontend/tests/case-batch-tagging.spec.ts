import { test, expect } from '@playwright/test';

test('case selection, one-click tagging, partial retry and receipt recovery', async ({ page }) => {
  const records = ['甲案例', '乙案例', '丙案例'].map((title, i) => ({
    id: `C-${String(i + 1).repeat(16)}`, title, revision: 1, summary: '分次施肥', enabled: true,
    has_explanation: false, updated_by: 'tester', updated_at: '2026-10-16T01:00:00Z', tag_ids: [] as string[],
  }));
  let job: { id: string; created_at: string; items: { case_id: string; title: string; status: string; message: string; retryable: boolean }[] } | null = null;
  let submitted: string[] = [];
  let retried = false;
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/case-library/taxonomy') json = { dimensions: [{ id: 'crop', name: '作物', enabled: true, selection: 'single' }], tags: [{ id: 'maize', dimension_id: 'crop', parent_id: null, name: '玉米', path: '玉米', enabled: true }] };
    else if (path === '/api/case-library') json = { items: records, total: 3, page: 1, page_size: 20 };
    else if (path === '/api/case-library/tag-jobs') {
      if (route.request().method() === 'POST') {
        submitted = route.request().postDataJSON().case_ids;
        expect(submitted).toEqual(records.slice(0, 2).map((item) => item.id));
        records[0].tag_ids = ['maize'];
        job = { id: 'job', created_at: '2026-10-16T01:00:00Z', items: records.slice(0, 2).map((item, index) => ({
          case_id: item.id, title: item.title, status: index ? 'failed' : 'ready', message: index ? '打标失败，请重试。' : '已保存', retryable: !!index,
        })) };
        json = job;
      } else json = { items: job ? [job] : [] };
    } else if (path === '/api/case-library/tag-jobs/job') json = job;
    else if (path === '/api/case-library/tag-jobs/job/retry') {
      retried = true;
      Object.assign(job!.items[1], { status: 'ready', message: '已保存', retryable: false });
      records[1].tag_ids = ['maize'];
      json = job;
    } else throw new Error(`Unexpected request ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/case-library');
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  const run = page.getByRole('button', { name: /^批量操作/ });
  const all = page.getByRole('checkbox', { name: '全选本页案例' });
  await expect(run).toBeDisabled();
  await page.getByRole('checkbox', { name: '选择案例 甲案例' }).check();
  await expect(all).toHaveJSProperty('indeterminate', true);
  await all.check();
  await expect(run).toHaveText('批量操作（3）');
  await page.getByRole('checkbox', { name: '选择案例 丙案例' }).uncheck();
  // Filter changes clear selection, including a round trip to the original filter.
  await page.getByLabel('开放状态').selectOption('enabled');
  await page.getByLabel('开放状态').selectOption('all');
  await expect(run).toBeDisabled();
  await all.check();
  await page.getByRole('checkbox', { name: '选择案例 丙案例' }).uncheck();
  await run.click();
  await page.getByRole("button", { name: "AI 一键打标", exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '案例 AI 打标' });
  await expect(dialog.getByRole('status')).toHaveText('已完成 1 / 2');
  await expect(dialog.getByText('打标失败，请重试。')).toBeVisible();
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(run).toBeDisabled();
  await expect(page.getByRole('row').filter({ has: page.getByRole('link', { name: '甲案例', exact: true }) })).toContainText('作物：玉米');
  await page.reload();
  await page.getByRole('button', { name: '打标记录', exact: true }).click();
  await dialog.getByRole('button', { name: /2 条 · 甲案例/ }).click();
  await dialog.getByRole('button', { name: '重试未完成' }).click();
  await expect(dialog.getByRole('status')).toHaveText('已完成 2 / 2');
  expect(retried).toBe(true);
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(page.getByRole('row').filter({ has: page.getByRole('link', { name: '乙案例', exact: true }) })).toContainText('作物：玉米');
  expect(submitted).toHaveLength(2);
});

for (const status of [405, 500, 422]) {
  test(`submission HTTP ${status} explains failure and preserves selection`, async ({ page }) => {
    await page.route('**/api/**', async (route) => {
      const path = new URL(route.request().url()).pathname;
      let json: unknown;
      if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
      else if (path === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'tester' } };
      else if (path === '/api/case-library/taxonomy') json = { dimensions: [], tags: [] };
      else if (path === '/api/case-library') json = { items: [{ id: 'C-1111111111111111', title: '待打标案例', tag_ids: [], summary: '材料', updated_at: '2026-10-16T00:00:00Z' }], total: 1, page: 1, page_size: 20 };
      else if (path === '/api/case-library/tag-jobs') {
        await route.fulfill({ status, json: { detail: status === 405 ? 'Method Not Allowed' : status === 422 ? [{ msg: 'invalid' }] : 'Internal Server Error' } }); return;
      } else throw new Error(`Unexpected request ${path}`);
      await route.fulfill({ json });
    });
    await page.goto('/evaluation/case-library');
    await page.getByLabel('账号', { exact: true }).fill('tester');
    await page.getByLabel('密码', { exact: true }).fill('password');
    await page.getByRole('button', { name: '进入工作台' }).click();
    await page.getByRole('checkbox', { name: '选择案例 待打标案例' }).check();
    await page.getByRole('button', { name: '批量操作（1）', exact: true }).click();
    await page.getByRole('button', { name: 'AI 一键打标', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '案例 AI 打标' });
    await expect(dialog.getByRole('alert')).toContainText(status === 405 ? '版本未更新' : status === 422 ? '案例选择无效' : 'HTTP 500');
    await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    await expect(page.getByRole('checkbox', { name: '选择案例 待打标案例' })).toBeChecked();
    await expect(page.getByRole('button', { name: '批量操作（1）', exact: true })).toBeEnabled();
  });
}

for (const conflict of [false, true]) {
  test(`batch availability ${conflict ? 'conflict preserves selection' : 'opens and closes selected records'}`, async ({ page }) => {
    let enabled = false, revision = 1;
    const requests: { items: { case_id: string; expected_revision: number }[]; enabled: boolean }[] = [];
    const filters: URLSearchParams[] = [];
    await page.route('**/api/**', async (route) => {
      const url = new URL(route.request().url());
      const path = url.pathname;
      let json: unknown;
      if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
      else if (path === '/api/eval/login') json = { token: 'test-token', user: { tester_id: 'tester', role: 'tester' } };
      else if (path === '/api/case-library/taxonomy') json = { dimensions: [], tags: [] };
      else if (path === '/api/case-library') {
        filters.push(url.searchParams);
        json = { items: [{ id: 'C-1111111111111111', title: '测试案例', enabled, revision, tag_ids: [] }], total: 1, page: 1, page_size: 20 };
      } else if (path === '/api/case-library/batch-availability') {
        expect(route.request().method()).toBe('PATCH');
        const body = route.request().postDataJSON(); requests.push(body);
        if (conflict) {
          await route.fulfill({ status: 409, json: { detail: { message: '部分案例已被修改或删除，本批次未作任何更改。请刷新列表后重新选择。' } } }); return;
        }
        enabled = body.enabled; revision++;
        json = { updated: 1, enabled };
      } else throw new Error(`Unexpected request ${path}`);
      await route.fulfill({ json });
    });
    await page.goto('/evaluation/case-library');
    await page.getByLabel('账号', { exact: true }).fill('tester');
    await page.getByLabel('密码', { exact: true }).fill('password');
    await page.getByRole('button', { name: '进入工作台' }).click();
    await expect(page.getByRole('button', { name: 'AI 一键打标', exact: true })).toHaveCount(0);
    await page.getByLabel('打标状态', { exact: true }).selectOption('tagged');
    await expect.poll(() => filters.at(-1)?.get('tag_status')).toBe('tagged');
    await page.getByLabel('打标状态', { exact: true }).selectOption('all');
    await expect.poll(() => filters.at(-1)?.get('tag_status')).toBe('all');
    await page.getByRole('checkbox', { name: '选择案例 测试案例' }).check();
    await page.getByRole('button', { name: '批量操作（1）', exact: true }).click();
    const dialog = page.getByRole('dialog', { name: '批量操作', exact: true });
    await dialog.getByRole('button', { name: '批量开放 Agent 使用' }).click();
    if (conflict) {
      await expect(dialog.getByRole('alert')).toContainText('本批次未作任何更改');
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
      await expect(page.getByRole('checkbox', { name: '选择案例 测试案例' })).toBeChecked();
    } else {
      await expect(dialog.getByRole('status')).toHaveText('已开放 1 条案例的 Agent 使用');
      await dialog.getByRole('button', { name: '关闭', exact: true }).click();
      await expect(page.getByRole('row').filter({ has: page.getByRole('link', { name: '测试案例', exact: true }) })).toContainText('已开放');
      await page.getByRole('checkbox', { name: '选择案例 测试案例' }).check();
      await page.getByRole('button', { name: '批量操作（1）', exact: true }).click();
      await dialog.getByRole('button', { name: '批量关闭 Agent 使用' }).click();
      await expect(dialog.getByRole('status')).toHaveText('已关闭 1 条案例的 Agent 使用');
      expect(requests[1]).toEqual({ items: [{ case_id: 'C-1111111111111111', expected_revision: 2 }], enabled: false });
    }
    expect(requests[0]).toEqual({ items: [{ case_id: 'C-1111111111111111', expected_revision: 1 }], enabled: true });
  });
}
