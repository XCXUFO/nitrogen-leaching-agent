import { expect, test, type Page } from '@playwright/test';

const source = { case_id: 'case-1', source_session_id: 'session-1', title: '施氮量多轮更正', expected: '最终采用150，每次50，保留玉米条件。', notes: '', revision: 1, seed_history: [],
  turns: [{ query: '总施氮180，分3次。', baseline_answer: '原回答：每次60。', baseline_config: 'build-old', source_run_id: 'run-1', attachments: [] },
    { query: '更正为150，每次多少？', baseline_answer: '旧版本错误沿用60。', baseline_config: 'build-old', source_run_id: 'run-2', attachments: [] }] };
const group = { group_id: 'group-1', title: '多轮与语言', notes: '', case_count: 1, turn_count: 2, cases: [source] };

async function setup(page: Page, role = 'reviewer') {
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  const batch = { batch_id: 'batch-1', version_name: 'v0.4.1', config_version: 'build-new', created_at: '2026-11-13T08:00:00Z', status: 'completed', acceptance: 'pending', group_ids: [group.group_id], group_titles: [group.title], case_count: 1, completed_cases: 1, cases: [source], results: [{ case: structuredClone(source), session_id: 'replay-1', status: 'succeeded', turns: [
    { run_id: 'new-1', query: source.turns[0].query, status: 'succeeded', response: { answer: '新版本：每次60。' } },
    { run_id: 'new-2', query: source.turns[1].query, status: 'succeeded', response: { answer: '新版本已更正：每次50。' } }], judgment: undefined as undefined | { conclusion: string; note: string; actor: string; at: string } }] };
  const groups = [group];
  let hasBatch = false;
  await page.route('**/api/eval/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/eval', '');
    const body = route.request().postDataJSON() ?? {};
    if (route.request().method() !== 'GET') requests.push({ path, body });
    if (path === '/login') return route.fulfill({ json: { token: 'token-1', user: { tester_id: 'human', role } } });
    if (path === '/me') return route.fulfill({ json: { tester_id: 'human', role } });
    if (path === '/case-groups') return route.fulfill({ json: groups });
    if (path === '/case-groups/group-1/cases') return route.fulfill({ status: 201, json: source });
    if (path === '/case-groups/group-1') return route.fulfill({ json: group });
    if (path === '/conversation-batches' && route.request().method() === 'POST') { hasBatch = true; return route.fulfill({ status: 202, json: batch }); }
    if (path === '/conversation-batches') return route.fulfill({ json: hasBatch ? [batch] : [] });
    if (path.endsWith('/judgments')) { batch.results[0].judgment = { ...body, actor: 'human', at: '2026-11-13T09:00:00Z' }; batch.acceptance = body.conclusion; return route.fulfill({ json: batch }); }
    if (path === '/conversation-batches/batch-1') return route.fulfill({ json: batch });
    if (path === '/conversation-cases/case-1') return route.fulfill({ json: { ...source, versions: hasBatch ? [{ batch_id: batch.batch_id, version_name: batch.version_name, config_version: batch.config_version, created_at: batch.created_at, result: batch.results[0] }] : [] } });
    if (path === '/sessions/session-1') return route.fulfill({ json: { session_id: 'session-1', topic: '整段会话', created_at: '2026-11-13T07:00:00Z', operator_id: 'human', turn_count: 2, status: '正常', latency_ms: 50, review: { revision: 0, issues: [], retests: [], history: [] }, turns: source.turns.map((t, i) => ({ run_id: `run-${i + 1}`, input: t.query, answer: t.baseline_answer, status: 'ok', started_at: '2026-11-13T07:00:00Z', request_snapshot: { query: t.query, has_attachments: false } })) } });
    if (path === '/conversation-issues') return route.fulfill({ json: [{ issue_id: 'issue-1', session_id: source.source_session_id, run_id: 'run-2', note: '更正后仍使用旧条件', status: 'open', source: 'feedback', category: '上下文', assignee: '', revision: 1, created_at: '2026-11-13T08:00:00Z', created_by: 'human', history: [], cases: [source], groups: [group] }] });
    return route.fulfill({ json: [] });
  });
  await page.goto('/evaluation/case-groups');
  await page.getByLabel('账号', { exact: true }).fill('human');
  await page.getByLabel('密码', { exact: true }).fill('Password123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('heading', { name: '用例组管理', exact: true })).toBeVisible();
  return { requests, batch };
}

test('expert replays a whole group, reviews each conversation and compares version answers in its case', async ({ page }) => {
  const { requests } = await setup(page);
  await page.getByRole('navigation', { name: '工作台导航' }).first().getByRole('link', { name: '版本管理', exact: true }).click();
  await page.getByLabel('选择用例组：多轮与语言').check();
  await page.getByLabel('待验证版本名称').fill('v0.4.1');
  await page.getByRole('button', { name: '重跑所选用例组（1）' }).click();
  await expect(page.getByLabel('本次版本验证')).toContainText('待验收');
  expect(requests.find((r) => r.path === '/conversation-batches')?.body.group_ids).toEqual(['group-1']);
  await expect(page.getByText('新版本已更正：每次50。', { exact: true })).toBeVisible();
  await page.getByLabel('验收依据：施氮量多轮更正').fill('两轮均核对，第二轮使用新条件150/3=50。');
  await page.getByRole('button', { name: '符合预期', exact: true }).click();
  await expect(page.getByLabel('本次版本验证')).toContainText('验收通过');
  await page.getByRole('button', { name: '查看前后版本回答', exact: true }).click();
  const comparison = page.getByLabel('会话用例与版本回答');
  await expect(comparison.getByText('旧版本错误沿用60。', { exact: true })).toBeVisible();
  await expect(comparison.getByText('新版本已更正：每次50。', { exact: true })).toBeVisible();
  await expect(page.getByText('开发者版本确认与回退', { exact: true })).toHaveCount(0);
  await comparison.getByLabel('此会话的验证版本').fill('v0.4.1 单独复测');
  await comparison.getByRole('button', { name: '重跑完整会话', exact: true }).click();
  await expect(page).toHaveURL(/case-groups\/versions\?case=case-1&batch=batch-1/);
  expect(requests.filter((r) => r.path === '/conversation-batches').at(-1)?.body.case_ids).toEqual(['case-1']);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('whole conversation can be marked into an existing group from its run record', async ({ page }) => {
  const { requests } = await setup(page);
  await page.goto('/evaluation/runs/session-1');
  await page.getByRole('button', { name: '加入用例组', exact: true }).click();
  await page.getByRole('combobox', { name: '用例组', exact: true }).selectOption('group-1');
  await page.getByLabel('预期表现', { exact: true }).fill('更正后每次50。');
  await page.getByRole('button', { name: '保存完整会话', exact: true }).click();
  await expect(page.getByText('完整会话已保存。')).toBeVisible();
  const capture = requests.find((r) => r.path === '/case-groups/group-1/cases');
  expect(capture?.body.session_id).toBe('session-1');
  expect(capture?.body).not.toHaveProperty('run_id');
});

test('ordinary account can inspect conversations and issues but has no mutation controls', async ({ page }) => {
  await setup(page, 'tester');
  await expect(page.getByText('当前账号仅可查看；专家和开发者可执行日常评测。')).toBeVisible();
  await expect(page.getByRole('button', { name: '新建用例组', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('待验证版本名称')).toHaveCount(0);
  await page.getByRole('link', { name: '查看版本记录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '版本管理', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '版本验证记录', exact: true })).toBeVisible();
  await expect(page.getByLabel('待验证版本名称')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /重跑所选用例组/ })).toHaveCount(0);
  await page.goto('/evaluation/runs/session-1');
  await expect(page.getByRole('button', { name: '通过', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '加入用例组', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '标记问题', exact: true })).toHaveCount(0);
  await page.goto('/evaluation/issues');
  await page.getByRole('button', { name: /更正后仍使用旧条件/ }).click();
  await expect(page.getByRole('link', { name: '查看完整原会话', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '保存处理结果', exact: true })).toHaveCount(0);
});

test('expert issue workflow exposes its source conversation, group and embedded version comparison', async ({ page }) => {
  await setup(page);
  await page.goto('/evaluation/issues');
  await page.getByRole('combobox', { name: '问题来源', exact: true }).selectOption('feedback');
  await page.getByRole('button', { name: /更正后仍使用旧条件/ }).click();
  await expect(page.getByRole('link', { name: '多轮与语言 · 重跑此组', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: '多轮与语言 · 重跑此组', exact: true })).toHaveAttribute('href', '/evaluation/case-groups/versions?group=group-1');
  await page.getByRole('button', { name: '查看前后版本回答：施氮量多轮更正', exact: true }).click();
  await expect(page.getByLabel('会话用例与版本回答')).toContainText('旧版本错误沿用60。');
});

test('group maintenance and version verification have separate pages and preserve the selected group', async ({ page }) => {
  await setup(page);
  const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
  await expect(nav.getByRole('link', { name: '用例组管理', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('heading', { name: '用例组管理', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '新建用例组', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '版本验证记录', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('待验证版本名称')).toHaveCount(0);
  await page.getByRole('link', { name: '多轮与语言 · 1 段会话 / 2 轮', exact: true }).click();
  await expect(page.getByRole('heading', { name: '用例组管理 · 详情', exact: true })).toBeVisible();
  const caseList = page.getByRole('list', { name: '会话用例', exact: true });
  await expect(caseList.getByText(`第 1 轮：${source.turns[0].query}`, { exact: true })).toBeVisible();
  await expect(caseList.getByText(`第 2 轮：${source.turns[1].query}`, { exact: true })).toBeVisible();
  await expect(page.getByLabel('会话用例与版本回答')).toHaveCount(0);
  await caseList.getByRole('link', { name: '施氮量多轮更正 · 2 轮', exact: true }).click();
  await expect(page).toHaveURL('/evaluation/case-groups/group-1/cases/case-1');
  await expect(page.getByRole('heading', { name: '会话用例 · 详情', exact: true })).toBeVisible();
  await expect(caseList).toHaveCount(0);
  await expect(page.getByRole('button', { name: '编辑预期标准', exact: true })).toBeVisible();
  await expect(page.getByLabel('此会话的验证版本')).toHaveCount(0);
  await expect(page.getByRole('link', { name: '返回所属用例组', exact: true })).toHaveAttribute('href', '/evaluation/case-groups/group-1');
  await expect(page.getByRole('navigation', { name: '面包屑' }).getByRole('link', { name: '用例组详情', exact: true })).toHaveAttribute('href', '/evaluation/case-groups/group-1');
  await page.reload();
  await expect(page.getByLabel('会话用例与版本回答')).toContainText('旧版本错误沿用60。');
  await page.goBack();
  await expect(caseList).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await caseList.getByRole('link', { name: '施氮量多轮更正 · 2 轮', exact: true }).click();
  await expect(page.getByLabel('会话用例与版本回答')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('link', { name: '返回所属用例组', exact: true }).click();
  await expect(caseList).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole('link', { name: '验证此组', exact: true }).click();
  await expect(page).toHaveURL('/evaluation/case-groups/versions?group=group-1');
  await expect(nav.getByRole('link', { name: '版本管理', exact: true })).toHaveAttribute('aria-current', 'page');
  await expect(nav.getByRole('link', { name: '用例组管理', exact: true })).not.toHaveAttribute('aria-current', 'page');
  await expect(page.getByRole('navigation', { name: '面包屑' })).toHaveText('工作台会话用例组版本管理');
  await expect(page.getByLabel('选择用例组：多轮与语言')).toBeChecked();
  await expect(page.getByLabel('筛选用例组')).toHaveValue('group-1');
  await expect(page.getByRole('button', { name: '新建用例组', exact: true })).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('heading', { name: '版本管理', exact: true })).toBeVisible();
  await expect(page.getByLabel('选择用例组：多轮与语言')).toBeChecked();
});

test('version deep links and legacy batch links open the verification and case comparison', async ({ page }) => {
  test.setTimeout(120000);
  await setup(page);
  await page.goto('/evaluation/case-groups/group-1?case=case-1');
  await expect(page).toHaveURL('/evaluation/case-groups/group-1/cases/case-1');
  await expect(page.getByLabel('会话用例与版本回答')).toContainText('旧版本错误沿用60。');
  await expect(page.getByRole('list', { name: '会话用例', exact: true })).toHaveCount(0);
  await page.goto('/evaluation/case-groups?case=case-1');
  await expect(page).toHaveURL('/evaluation/case-groups/cases/case-1');
  await expect(page.getByLabel('会话用例与版本回答')).toBeVisible();
  await expect(page.getByRole('link', { name: '返回用例组管理', exact: true })).toHaveAttribute('href', '/evaluation/case-groups');
  await page.goto('/evaluation/case-groups/group-1?case=case-1&batch=batch-1');
  await expect(page).toHaveURL(/case-groups\/versions\?batch=batch-1&case=case-1&group=group-1/, { timeout: 15000 });
  await expect(page.getByRole('heading', { name: '版本管理', exact: true })).toBeVisible();
  await expect(page.getByLabel('本次版本验证')).toContainText('v0.4.1');
  await expect(page.getByLabel('会话用例与版本回答')).toContainText('旧版本错误沿用60。');
  await expect(page.getByLabel('选择用例组：多轮与语言')).toBeChecked();
  await page.reload();
  await expect(page.getByLabel('本次版本验证')).toContainText('v0.4.1');
  await expect(page.getByLabel('会话用例与版本回答')).toContainText('旧版本错误沿用60。');
  await page.goto('/evaluation/case-groups?case=case-1&batch=batch-1');
  await expect(page).toHaveURL(/case-groups\/versions\?batch=batch-1&case=case-1$/, { timeout: 15000 });
  await expect(page.getByLabel('本次版本验证')).toContainText('v0.4.1');
});

test('both child pages remain reachable in collapsed and mobile navigation', async ({ page }) => {
  await setup(page);
  await page.getByRole('button', { name: '收起侧边栏', exact: true }).click();
  const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
  await nav.getByRole('link', { name: '版本管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '版本管理', exact: true })).toBeVisible();
  await nav.getByRole('link', { name: '用例组管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '用例组管理', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: '打开导航', exact: true }).click();
  const drawer = page.getByRole('dialog', { name: '移动端导航' });
  await drawer.getByRole('link', { name: '版本管理', exact: true }).click();
  await expect(drawer).not.toBeVisible();
  await expect(page.getByRole('heading', { name: '版本管理', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '打开导航', exact: true }).click();
  await drawer.getByRole('link', { name: '用例组管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '用例组管理', exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
