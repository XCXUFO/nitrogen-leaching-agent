import { test, expect } from '@playwright/test';

test.use({ channel: 'chromium' });

const initial = { id: 'C-1111111111111111', revision: 1, title: '玉米案例', body: '分次施肥，未记载结果。', explanation: '人工解释', supplementary: '', source: '', enabled: true, created_by: 'tester', updated_by: 'tester', created_at: '2026-10-14T00:00:00Z', updated_at: '2026-10-14T00:00:00Z' };

test('AI draft adoption, conflict preservation, navigation guard and explicit save', async ({ page }) => {
  const saved = { ...initial };
  let saves = 0;
  let fail = true;
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/case-library/explanation-draft') {
      expect(route.request().postDataJSON().body).toBe('<p>更新的原文</p>');
      json = { draft: 'AI 生成的新解释' };
    } else if (path === `/api/case-library/${initial.id}`) {
      if (route.request().method() === 'PUT') {
        saves++;
        if (fail) { await route.fulfill({ status: 409, json: { detail: { code: 'case_conflict', message: '内容已被其他人更新。已保留你的输入。' } } }); return; }
        expect(route.request().postDataJSON().expected_revision).toBe(2);
        Object.assign(saved, route.request().postDataJSON(), { revision: 3 });
      }
      json = saved;
    } else throw new Error(`Unexpected ${path}`);
    await route.fulfill({ json });
  });
  await page.goto(`/evaluation/case-library/${initial.id}?edit=1`);
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByRole('textbox', { name: '案例与措施原文 *', exact: true }).fill('更新的原文');
  await expect(page.getByText('案例内容已修改，请检查解释是否仍与原文一致。')).toBeVisible();
  await page.getByRole('button', { name: 'AI 生成解释', exact: true }).click();
  await expect(page.getByText('AI 生成的新解释', { exact: true })).toBeVisible();
  await expect(page.getByRole('textbox', { name: '解释与说明（选填）', exact: true })).toHaveValue('人工解释');
  expect(saves).toBe(0);
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '采用初稿' }).click();
  await page.getByRole('textbox', { name: '解释与说明（选填）', exact: true }).fill('人工核对的新解释');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('已保留');
  await expect(page.getByRole('textbox', { name: '解释与说明（选填）', exact: true })).toHaveValue('人工核对的新解释');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('link', { name: '取消', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '解释与说明（选填）', exact: true })).toHaveValue('人工核对的新解释');
  page.once('dialog', (dialog) => dialog.dismiss());
  await page.getByRole('button', { name: '加载最新版本', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '解释与说明（选填）', exact: true })).toHaveValue('人工核对的新解释');
  saved.revision = 2;
  saved.body = '他人更新后的原文';
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '加载最新版本', exact: true }).click();
  await expect(page.getByRole('textbox', { name: '案例与措施原文 *', exact: true })).toHaveText('他人更新后的原文');
  await page.getByRole('textbox', { name: '案例与措施原文 *', exact: true }).fill('更新的原文');
  await page.getByRole('textbox', { name: '解释与说明（选填）', exact: true }).fill('人工核对的新解释');
  fail = false;
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${initial.id}$`));
  await expect(page.getByText('人工核对的新解释', { exact: true })).toBeVisible();
  expect(saved.body).toBe('<p>更新的原文</p>');
});

test('minimum fields save after draft failure with Agent closed by default', async ({ page }) => {
  let created: Record<string, unknown> = {};
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/case-library/explanation-draft') { await route.fulfill({ status: 502, json: { detail: { message: '解释生成失败，请重试或手动填写。' } } }); return; }
    else if (path === '/api/case-library' && route.request().method() === 'POST') { created = route.request().postDataJSON(); json = { ...initial, ...created }; }
    else if (path === `/api/case-library/${initial.id}`) json = { ...initial, ...created };
    else throw new Error(`Unexpected ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/case-library/new');
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByLabel('标题 *', { exact: true }).fill('只填必填项');
  await page.getByRole('textbox', { name: '案例与措施原文 *', exact: true }).fill('原始材料');
  await page.getByRole('button', { name: 'AI 生成解释', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('生成失败');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${initial.id}$`));
  expect(created).toMatchObject({ enabled: false, source: '', explanation: '', supplementary: '' });
});

test('title filter, availability changes, deletion and standalone explanation', async ({ page }) => {
  let item: typeof initial | null = { ...initial };
  const queries: string[] = [];
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname, method = route.request().method();
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/case-library') {
      queries.push(url.search);
      const matches = item && item.title.includes(url.searchParams.get('keyword') || '') && (url.searchParams.get('availability') !== 'disabled' || !item.enabled);
      json = { items: matches && item ? [{ ...item, summary: item.body, has_explanation: true }] : [], total: matches ? 1 : 0, page: 1, page_size: 20 };
    } else if (path === `/api/case-library/${initial.id}/availability`) {
      expect(route.request().postDataJSON()).toEqual({ enabled: false, expected_revision: 1 });
      item = { ...initial, enabled: false, revision: 2 }; json = item;
    } else if (path === `/api/case-library/${initial.id}`) {
      if (method === 'DELETE') { expect(route.request().postDataJSON()).toEqual({ expected_revision: 2 }); item = null; json = { deleted: true }; }
      else json = item;
    } else if (path === '/api/chat') {
      const body = route.request().postDataJSON();
      expect(body.case_skill).toBe('explain');
      expect(body.case_ids).toEqual([]);
      expect(body.session_id).toMatch(/^[\w-]{36}$/);
      json = { answer: '分次施肥是把肥料分几次施入。', citations: [], case_references: [], file_evidence: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }, retrieved_count: 0, model: 'fixture' };
    } else throw new Error(`Unexpected ${method} ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/case-library');
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('link', { name: '玉米案例', exact: true })).toBeVisible();
  await page.getByLabel('按标题搜索').fill('水稻');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await expect(page.getByText('暂无符合条件的案例')).toBeVisible();
  expect(queries.some((query) => new URLSearchParams(query).get('keyword') === '水稻')).toBeTruthy();
  await page.getByLabel('按标题搜索').fill('');
  await page.getByRole('button', { name: '搜索', exact: true }).click();
  await page.getByLabel('开放状态').selectOption('disabled');
  await expect(page.getByText('暂无符合条件的案例')).toBeVisible();
  await page.getByLabel('开放状态').selectOption('all');
  await page.getByRole('link', { name: '玉米案例', exact: true }).click();
  await page.getByRole('button', { name: '关闭 Agent 使用', exact: true }).click();
  await expect(page.getByRole('button', { name: '开放 Agent 使用', exact: true })).toBeVisible();
  page.once('dialog', async (dialog) => { expect(dialog.message()).toContain('玉米案例'); await dialog.accept(); });
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/case-library$/);
  await expect(page.getByText('暂无符合条件的案例')).toBeVisible();
  await page.getByLabel('选择 Skill').selectOption('explain');
  await page.getByLabel('验证问题或专业文字').fill('解释分次施肥的含义');
  await page.getByRole('button', { name: '验证效果', exact: true }).click();
  await expect(page.getByText('分次施肥是把肥料分几次施入。', { exact: true })).toBeVisible();
});

test('Word table paste keeps empty cells, edits rows and columns, and survives save and reload', async ({ page }) => {
  let saved: Record<string, unknown> = { ...initial };
  let draftBody = '';
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let json: unknown;
    if (path === '/api/eval/me') json = { tester_id: 'tester', role: 'tester' };
    else if (path === '/api/eval/login') json = { token: 'mock-session-token', user: { tester_id: 'tester', role: 'tester' } };
    else if (path === '/api/case-library/explanation-draft') {
      draftBody = route.request().postDataJSON().body;
      expect(route.request().postDataJSON().body_format).toBe('html');
      json = { draft: '尿素用量原文未填写，不能补值。' };
    } else if (path === '/api/case-library' && route.request().method() === 'POST') {
      saved = { ...initial, ...route.request().postDataJSON() }; json = saved;
    } else if (path === `/api/case-library/${initial.id}`) json = saved;
    else throw new Error(`Unexpected ${path}`);
    await route.fulfill({ json });
  });
  await page.goto('/evaluation/case-library/new');
  await page.getByLabel('账号', { exact: true }).fill('tester');
  await page.getByLabel('密码', { exact: true }).fill('test-password');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByLabel('标题 *', { exact: true }).fill('清徐玉米第二次追肥');
  const editor = page.getByRole('textbox', { name: '案例与措施原文 *', exact: true });
  await editor.click();
  await editor.evaluate((element) => {
    const data = new DataTransfer();
    data.setData('text/html', '<html><body><!--StartFragment--><h2>第二次追肥：13-14展叶</h2><table class="MsoTableGrid" style="border-collapse:collapse"><tr><th>名称</th><th>规格</th><th>亩用量（公斤）</th></tr><tr><td>尿素</td><td>N:46%</td><td><p class="MsoNormal">&nbsp;</p></td></tr><tr><td>工业一胺</td><td>N:12%,P:61%</td><td>3</td></tr></table><p>条件：20℃，灌溉量 m³/亩。</p><!--EndFragment--></body></html>');
    data.setData('text/plain', '尿素 N:46%');
    element.dispatchEvent(new ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }));
  });
  const table = editor.locator('table');
  await expect(table.locator('tr')).toHaveCount(3);
  await expect(table.locator('tr').nth(1).locator('td').nth(2)).toHaveText(/^\s*$/);
  await table.locator('tr').nth(1).locator('td').nth(0).click();
  await page.getByRole('button', { name: '下方插行', exact: true }).click();
  await expect(table.locator('tr')).toHaveCount(4);
  await table.locator('tr').nth(2).locator('td').nth(0).click();
  await page.getByRole('button', { name: '删除行', exact: true }).click();
  await expect(table.locator('tr')).toHaveCount(3);
  await table.locator('tr').nth(1).locator('td').nth(0).click();
  await page.getByRole('button', { name: '右侧插列', exact: true }).click();
  await expect(table.locator('tr').nth(1).locator('td')).toHaveCount(4);
  await table.locator('tr').nth(1).locator('td').nth(1).click();
  await page.getByRole('button', { name: '删除列', exact: true }).click();
  await expect(table.locator('tr').nth(1).locator('td')).toHaveCount(3);
  await table.locator('tr').nth(2).locator('td').nth(2).locator('p').fill('3.5');
  await page.getByRole('button', { name: 'AI 生成解释', exact: true }).click();
  await expect(page.getByText('尿素用量原文未填写，不能补值。', { exact: true })).toBeVisible();
  expect(draftBody).toContain('<table');
  expect(draftBody).toContain('N:46%');
  await page.getByRole('button', { name: '采用初稿' }).click();
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`${initial.id}$`));
  expect(saved.body_format).toBe('html');
  await page.reload();
  const displayed = page.locator('[aria-label="案例与措施正文"]');
  await expect(displayed.locator('table tr')).toHaveCount(3);
  await expect(displayed.locator('table tr').nth(1).locator('td').nth(2)).toHaveText(/^\s*$/);
  await expect(displayed.locator('table tr').nth(2).locator('td').nth(2)).toHaveText('3.5');
  await expect(displayed).toContainText('20℃，灌溉量 m³/亩');
  await page.getByRole('link', { name: '编辑', exact: true }).click();
  await expect(editor.locator('table tr')).toHaveCount(3);
  await expect(editor.locator('table tr').nth(1).locator('td').nth(2)).toHaveText(/^\s*$/);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(editor).toBeVisible();
  await expect(page.getByRole('textbox', { name: '解释与说明（选填）', exact: true })).toBeVisible();
});
