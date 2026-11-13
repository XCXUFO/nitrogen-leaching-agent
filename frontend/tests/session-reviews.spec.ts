import { expect, test, type Page } from '@playwright/test';
import type { SessionDetail } from '../src/lib/evaluation-api';

function fixture(id: string, day: string): SessionDetail {
  return { session_id: id, topic: `会话${id}`, created_at: `${day}T08:30:00Z`, operator_id: 'visitor_example',
    status: '正常', latency_ms: 100, turn_count: 1, review_status: 'pending', reviewed_turn_count: 0, open_issue_count: 0,
    turns: [{ run_id: `run-${id}`, input: `原问题${id}`, answer: '原回答，需要核对条件。', started_at: `${day}T08:30:00Z`,
      status: 'ok', outcome: 'complete', latency_ms: 100, error_code: null, request_snapshot: { query: `原问题${id}`, has_attachments: false },
      evidence: [{ source_type: 'case', source_id: 'case-material', provenance: { title: '原始案例' } }] }],
    review: { revision: 0, reviewed_turn_count: 0, issues: [], retests: [], history: [] } };
}

async function setup(page: Page, role = 'developer') {
  const sessions = [fixture('A', '2026-10-18'), fixture('B', '2026-10-17')];
  const calls: string[] = [];
  let conflict = false;
  let queueFailure = false;
  await page.route('**/api/eval/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/eval', '');
    calls.push(path);
    if (path === '/me') return route.fulfill({ json: { tester_id: 'human-reviewer', role } });
    if (path === '/login') return route.fulfill({ json: { token: 'review-token', user: { tester_id: 'human-reviewer', role } } });
    if (path === '/sessions') {
      if (queueFailure) { queueFailure = false; return route.fulfill({ status: 503, json: { detail: '暂时无法读取列表' } }); }
      const filtered = sessions.filter(item => !url.searchParams.get('review_status') || item.review_status === url.searchParams.get('review_status'))
        .filter(item => !url.searchParams.get('status') || item.status === url.searchParams.get('status'))
        .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.session_id.localeCompare(a.session_id));
      const offset = Number(url.searchParams.get('offset')) || 0;
      return route.fulfill({ json: { total: filtered.length, items: filtered.slice(offset, offset + (Number(url.searchParams.get('limit')) || 20)) } });
    }
    const current = sessions.find(item => path.startsWith(`/sessions/${item.session_id}`));
    if (current && request.method() === 'GET') return route.fulfill({ json: current });
    if (current && path.endsWith('/reviews')) {
      const body = request.postDataJSON();
      if (conflict) { conflict = false; current.review!.revision++; return route.fulfill({ status: 409, json: { detail: { code: 'review_changed', message: '有人更新了审核意见，请刷新记录后继续；当前输入已保留。' } } }); }
      current.review!.revision++;
      current.review!.history.push({ action: body.action, recorded_by: 'human-reviewer', recorded_at: '2026-10-18T09:00:00Z', note: body.note ?? '', review_kind: 'human' });
      if (body.action === 'pass') { current.review_status = 'passed'; current.reviewed_turn_count = current.turn_count; }
      if (body.action === 'issue') {
        current.review_status = 'needs_changes'; current.open_issue_count = 1;
        current.review!.issues.push({ issue_id: body.action_id, run_id: body.run_id, note: body.note, status: 'open', recorded_by: 'human-reviewer' });
      }
      if (body.action === 'resolve') { current.review!.issues[0].status = 'resolved'; current.open_issue_count = 0; current.review_status = 'pending'; }
      return route.fulfill({ json: current });
    }
    if (current && path.endsWith('/retests')) {
      const body = request.postDataJSON();
      current.review!.revision++;
      current.review!.retests.push({ run_id: 'verification-one', source_run_id: body.source_run_id, issue_id: body.issue_id,
        recorded_at: '2026-10-18T09:00:00Z', recorded_by: 'human-reviewer', status: 'succeeded', answer: '修改后的回答，已补充适用条件。' });
      return route.fulfill({ status: 202, json: current });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/evaluation');
  await page.getByLabel('账号', { exact: true }).fill('reviewer');
  await page.getByLabel('密码', { exact: true }).fill('ReviewPassword123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByText('共查到 2 条会话记录')).toBeVisible();
  return { sessions, calls, conflictNext: () => { conflict = true; }, failNextQueue: () => { queueFailure = true; } };
}

test('daily entry groups conversation evaluation links and approves directly without task or case setup', async ({ page }) => {
  const { calls } = await setup(page);
  const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
  await expect(nav.getByRole('link', { name: '会话用例组', exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: '问题处理', exact: true })).toBeVisible();
  await expect(nav.getByRole('link', { name: '回归对比', exact: true })).toHaveCount(0);
  await expect(nav.getByRole('link', { name: '任务管理', exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await expect(page.getByText('原问题A', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '通过并看下一条' }).click();
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '通过并看下一条' }).click();
  await expect(page.getByText('共查到 0 条会话记录')).toBeVisible();
  expect(calls.some(path => ['/tasks', '/cases', '/executions'].includes(path))).toBe(false);
});

test('expert marking and processing links keep the original conversation', async ({ page }) => {
  const { sessions } = await setup(page, 'reviewer');
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '标记问题', exact: true }).click();
  await page.getByLabel('哪里有问题，希望怎么改').fill('解释需要补充适用条件');
  await page.getByRole('button', { name: '保存问题' }).click();
  await expect(page.getByLabel('已标记问题')).toContainText('解释需要补充适用条件');
  await expect(page.getByRole('button', { name: '通过', exact: true })).toBeDisabled();
  await expect(page.getByRole('link', { name: '原始案例 ↗' })).toHaveAttribute('href', '/evaluation/case-library/case-material');
  await expect(page.getByRole('link', { name: '调整 Prompt ↗' })).toHaveAttribute('href', '/evaluation/explanation-trials?source_run=run-A');
  await expect(page.getByRole('link', { name: '验证完整会话并处理问题' })).toHaveAttribute('href', '/evaluation/issues');
  await expect(page.getByRole('button', { name: '加入用例组' })).toBeVisible();
  expect(sessions[0].review_status).toBe('needs_changes');
  await page.getByText('补充意见 / 协助复核（可选）', { exact: true }).click();
  await page.getByLabel('补充审核意见').fill('师兄已核对原文，条件一致。');
  await page.getByRole('button', { name: '保存意见' }).click();
  await page.getByText(/审核历史（/).click();
  await expect(page.getByText('师兄已核对原文，条件一致。', { exact: true })).toBeVisible();
});

test('a saved issue can be followed by the next conversation without approving it', async ({ page }) => {
  const { sessions } = await setup(page, 'reviewer');
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '标记问题', exact: true }).click();
  await page.getByLabel('哪里有问题，希望怎么改').fill('需要补充条件');
  await expect(page.getByRole('button', { name: '下一条', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '保存问题', exact: true }).click();
  await expect(page.getByLabel('已标记问题')).toContainText('需要补充条件');
  await expect(page.getByRole('button', { name: '通过并看下一条' })).toBeDisabled();
  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  expect(sessions[0].review_status).toBe('needs_changes');
  expect(sessions[0].review!.history.map(item => item.action)).toEqual(['issue']);
  expect(sessions[1].review!.revision).toBe(0);
  await expect(page.getByLabel('哪里有问题，希望怎么改')).toHaveCount(0);
});

test('previous returns to an approved conversation after it leaves the pending queue, including after reload', async ({ page }) => {
  const { sessions } = await setup(page);
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '通过并看下一条' }).click();
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '上一条', exact: true }).click();
  await expect(page.getByText('原问题A', { exact: true })).toBeVisible();
  expect(sessions[0].review_status).toBe('passed');
  expect(sessions[1].review!.revision).toBe(0);
});

test('previous follows filtered ordering across pages and stops at the first record', async ({ page }) => {
  const { sessions } = await setup(page);
  for (let index = 0; index < 10; index++) sessions.push(fixture(`C${index}`, '2026-10-18'));
  await page.goto('/evaluation/runs/A?review_status=pending&page=2&size=10&operator_id=visitor_example');
  await page.getByRole('button', { name: '上一条', exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/C0\?review_status=pending&page=1&size=10&operator_id=visitor_example$/);
  await expect(page.getByText('原问题C0', { exact: true })).toBeVisible();
  await page.goto('/evaluation/runs/C9?review_status=pending&page=1&size=10');
  await page.getByRole('button', { name: '上一条', exact: true }).click();
  await expect(page.getByText('已经是第一条记录。')).toBeVisible();
  expect(sessions.every(item => item.review!.revision === 0)).toBe(true);
});

test('attachments are visible per turn with an explicit fallback for incomplete historical records', async ({ page }) => {
  const { sessions } = await setup(page);
  const original = sessions[0].turns[0];
  original.request_snapshot = { query: original.input, has_attachments: true, attachments: [
    { filename: '氮平衡结果.xlsx', format: 'xlsx' }, { filename: '田间记录.txt', format: 'txt' },
  ] };
  sessions[0].turns.push({ ...original, run_id: 'old-file-run', input: '旧文件问题',
    request_snapshot: { query: '旧文件问题', has_attachments: true },
    evidence: [{ source_type: 'file', provenance: { filename: '旧结果.xls' } }] },
  { ...original, run_id: 'unknown-file-run', input: '文件名缺失', evidence: [],
    request_snapshot: { query: '文件名缺失', has_attachments: true } },
  { ...original, run_id: 'no-file-run', input: '未携带附件的问题', evidence: [],
    request_snapshot: { query: '未携带附件的问题', has_attachments: false } });
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  const attachments = page.getByLabel('本轮附件', { exact: true });
  await expect(attachments).toHaveCount(4);
  await expect(attachments.nth(0)).toContainText('氮平衡结果.xlsx');
  await expect(attachments.nth(0)).toContainText('田间记录.txt');
  await expect(attachments.nth(1)).toContainText('旧结果.xls');
  await expect(attachments.nth(2)).toContainText('本轮携带附件，历史记录未保存文件名。');
  await expect(attachments.nth(3)).toContainText('本轮未携带附件');
  await page.getByRole('button', { name: '标记问题', exact: true }).first().click();
  await expect(page.getByRole('button', { name: '上一条', exact: true })).toBeDisabled();
});

test('runtime status is visible in the main search bar and persists when returning from a record', async ({ page }) => {
  const { sessions } = await setup(page);
  sessions[1].status = '异常';
  await expect(page.getByRole('combobox', { name: '运行状态', exact: true })).toBeVisible();
  await page.getByRole('combobox', { name: '运行状态', exact: true }).selectOption('异常');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page.getByText('共查到 1 条会话记录')).toBeVisible();
  await expect(page.getByText('会话B', { exact: true })).toBeVisible();
  await expect(page.getByText('会话A', { exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: '查看', exact: true }).click();
  await page.getByRole('link', { name: '返回运行记录', exact: true }).click();
  await expect(page.getByRole('combobox', { name: '运行状态', exact: true })).toHaveValue('异常');
  await page.getByRole('combobox', { name: '运行状态', exact: true }).selectOption('正常');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page.getByText('会话A', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '重置', exact: true }).click();
  await expect(page.getByText('共查到 2 条会话记录')).toBeVisible();
});

test('attachment dialog previews text safely, downloads originals and closes with Escape', async ({ page }) => {
  const { sessions } = await setup(page);
  sessions[0].turns[0].request_snapshot = { has_attachments: true,
    attachments: [{ filename: '田间记录.txt', sha256: 'document-hash', format: 'txt' }] };
  await page.route('**/attachments/**/preview?*', route => route.fulfill({ json: {
    kind: 'text', filename: '田间记录.txt', text: '玉米灌溉记录：100 mm\n<script>alert(1)</script>',
  } }));
  await page.route('**/attachments/**/content', route => route.fulfill({ body: 'original file', contentType: 'application/octet-stream' }));
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  const trigger = page.getByRole('button', { name: '预览附件：田间记录.txt' });
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: '附件预览' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('玉米灌溉记录：100 mm');
  await expect(dialog).toContainText('<script>alert(1)</script>');
  const downloadEvent = page.waitForEvent('download');
  await dialog.getByRole('button', { name: '下载原文件' }).click();
  expect((await downloadEvent).suggestedFilename()).toBe('田间记录.txt');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
});

test('attachment table switches sheets and paginates within a mobile dialog', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { sessions } = await setup(page);
  sessions[0].turns[0].request_snapshot = { has_attachments: true,
    attachments: [{ filename: '氮平衡.xlsx', sha256: 'table-hash', format: 'xlsx' }] };
  await page.route('**/attachments/**/preview?*', route => {
    const params = new URL(route.request().url()).searchParams;
    const sheet = Number(params.get('sheet')) || 0;
    const offset = Number(params.get('offset')) || 0;
    return route.fulfill({ json: { kind: 'table', filename: '氮平衡.xlsx', sheet, offset,
      sheets: ['氮平衡', '水平衡'], total_rows: 101, total_columns: 2, columns_truncated: false,
      rows: sheet === 1 ? [['灌溉量', 50]] : offset ? [['末行', 101]] : Array.from({ length: 100 }, (_, i) => [`第${i + 1}行`, i]),
    } });
  });
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '预览附件：氮平衡.xlsx' }).click();
  const dialog = page.getByRole('dialog', { name: '附件预览' });
  await expect(dialog.getByRole('cell', { name: '第1行', exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: '下一页数据' }).click();
  await expect(dialog.getByRole('cell', { name: '末行', exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: '下一页数据' })).toBeDisabled();
  await dialog.getByLabel('工作表').selectOption('1');
  await expect(dialog.getByRole('cell', { name: '灌溉量', exact: true })).toBeVisible();
  expect(await dialog.evaluate(element => element.getBoundingClientRect().right <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nitrogen-run-attachment-preview-mobile.png', fullPage: true });
  await dialog.getByRole('button', { name: '关闭预览' }).click();
  await expect(dialog).not.toBeVisible();
});

test('PDF preview changes pages and missing historical originals are explained', async ({ page }) => {
  const { sessions } = await setup(page);
  sessions[0].turns[0].request_snapshot = { has_attachments: true,
    attachments: [{ filename: '报告.pdf', sha256: 'pdf-hash', format: 'pdf' }, { filename: '旧附件.txt', sha256: 'missing-hash' }] };
  await page.route('**/attachments/**/preview?*', route => {
    if (route.request().url().includes('missing-hash')) return route.fulfill({ status: 404,
      json: { detail: { message: '这份历史附件的原文件未保存，暂时无法预览。请重新上传后提交问题。' } } });
    return route.fulfill({ json: { kind: 'pdf', filename: '报告.pdf', page_count: 2,
      page: Number(new URL(route.request().url()).searchParams.get('page')) || 1,
      image: 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aYuoAAAAASUVORK5CYII=',
    } });
  });
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '预览附件：报告.pdf' }).click();
  const dialog = page.getByRole('dialog', { name: '附件预览' });
  await expect(dialog.getByRole('img', { name: '附件第 1 页预览' })).toBeVisible();
  await dialog.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(dialog.getByText('第 2 / 2 页')).toBeVisible();
  await expect(dialog.getByRole('button', { name: '下一页', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: '关闭预览' }).click();
  await page.getByRole('button', { name: '预览附件：旧附件.txt' }).click();
  await expect(dialog.getByRole('alert')).toContainText('原文件未保存');
});

for (const sameTime of [false, true]) {
  test(`saving an issue and continuing preserves filters and ordering (same time: ${sameTime})`, async ({ page }) => {
    const { sessions } = await setup(page, 'reviewer');
    if (sameTime) sessions[1].created_at = sessions[0].created_at;
    const first = sameTime ? 'B' : 'A';
    const next = sameTime ? 'A' : 'B';
    const query = 'review_status=pending&information=会话&operator_id=visitor_example&size=10&page=1';
    await page.goto(`/evaluation/runs/${first}?${query}`);
    await page.getByRole('button', { name: '标记问题', exact: true }).click();
    await page.getByLabel('哪里有问题，希望怎么改').fill('保留问题并继续审核');
    await page.getByRole('button', { name: '保存并看下一条' }).click();
    await expect(page.getByText(`原问题${next}`, { exact: true })).toBeVisible();
    const url = new URL(page.url());
    expect(url.pathname).toBe(`/evaluation/runs/${next}`);
    expect(url.searchParams).toEqual(new URLSearchParams(query));
    const saved = sessions.find(item => item.session_id === first)!;
    expect(saved.review_status).toBe('needs_changes');
    expect(saved.review!.issues[0].note).toBe('保留问题并继续审核');
  });
}

test('next conversation crosses a page boundary without changing review status', async ({ page }) => {
  const { sessions } = await setup(page);
  for (let index = 0; index < 10; index++) sessions.push(fixture(`C${index}`, '2026-10-18'));
  await page.goto('/evaluation/runs/C0?review_status=pending&page=1&size=10');
  await expect(page.getByText('原问题C0', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(page).toHaveURL(/\/runs\/A\?review_status=pending&page=2&size=10$/);
  await expect(page.getByText('原问题A', { exact: true })).toBeVisible();
  expect(sessions.every(item => item.review!.revision === 0)).toBe(true);
});

test('save and continue keeps an unsaved note on conflict and can retry navigation after saving', async ({ page }) => {
  const control = await setup(page);
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '标记问题', exact: true }).click();
  await page.getByLabel('哪里有问题，希望怎么改').fill('不能丢失或重复提交');
  control.conflictNext();
  await page.getByRole('button', { name: '保存并看下一条' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('有人更新了审核意见');
  await expect(page.getByLabel('哪里有问题，希望怎么改')).toHaveValue('不能丢失或重复提交');
  await expect(page).toHaveURL(/\/runs\/A$/);
  await page.getByRole('button', { name: '刷新记录', exact: true }).click();
  control.failNextQueue();
  await page.getByRole('button', { name: '保存并看下一条' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('切换下一条失败');
  await expect(page.getByLabel('已标记问题')).toContainText('不能丢失或重复提交');
  await expect(page.getByLabel('哪里有问题，希望怎么改')).toHaveCount(0);
  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  expect(control.sessions[0].review!.issues).toHaveLength(1);
});

test('next on the last flagged conversation returns to its filtered list without cycling', async ({ page }) => {
  const { sessions } = await setup(page);
  for (let index = 0; index < 10; index++) sessions.push(fixture(`C${index}`, '2026-10-18'));
  sessions.forEach(item => { item.review_status = 'needs_changes'; item.open_issue_count = 1; });
  await page.goto('/evaluation/runs/B?review_status=needs_changes&page=2&size=10');
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一条', exact: true }).click();
  await expect(page).toHaveURL(/\/runs\?review_status=needs_changes&page=2&size=10$/);
  await expect(page.getByText('共查到 12 条会话记录')).toBeVisible();
  expect(sessions.every(item => item.review_status === 'needs_changes')).toBe(true);
});

test('review conflicts preserve the note through refresh and reload, and list filters survive returning', async ({ page }) => {
  const control = await setup(page, 'reviewer');
  await page.getByLabel('会话信息', { exact: true }).fill('会话');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page).toHaveURL(/information=/);
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '标记问题' }).click();
  await page.getByLabel('哪里有问题，希望怎么改').fill('冲突后仍应保留这段意见');
  control.conflictNext();
  await page.getByRole('button', { name: '保存问题' }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('有人更新了审核意见');
  await page.getByRole('button', { name: '刷新记录', exact: true }).click();
  await expect(page.getByLabel('哪里有问题，希望怎么改')).toHaveValue('冲突后仍应保留这段意见');
  await page.reload();
  await expect(page.getByLabel('哪里有问题，希望怎么改')).toHaveValue('冲突后仍应保留这段意见');
  await page.getByRole('button', { name: '保存问题' }).click();
  await page.getByRole('link', { name: '返回运行记录', exact: true }).click();
  await expect(page.getByLabel('会话信息', { exact: true })).toHaveValue('会话');
  await page.getByRole('button', { name: '需修改', exact: true }).click();
  await expect(page.getByText('共查到 1 条会话记录')).toBeVisible();
});

test('reviewing on a phone keeps the form and actions inside the screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await setup(page);
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '标记问题' }).click();
  await expect(page.getByLabel('哪里有问题，希望怎么改')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nitrogen-lightweight-review-mobile.png', fullPage: true });
});

test('prompt iteration opened from an answer carries its question and text context', async ({ page }) => {
  const prompt = { prompt_id: 'saved', label: '当前表达', text: '清楚解释适用条件。', version: 'v1' };
  const task = (scope: string) => ({ ...prompt, scope, examples: [] });
  const group = { group_id: 'group', label: '当前组', version: 'group-v1', communication: prompt,
    task_prompts: { concept_explanation: task('concept_explanation'), knowledge_search: task('knowledge_search'), case_assistant: task('case_assistant') } };
  await page.route('**/api/eval/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/eval', '');
    let value: unknown = [];
    if (path === '/me') value = { tester_id: 'collaborator', role: 'tester' };
    if (path === '/login') value = { token: 'collaborator-token', user: { tester_id: 'collaborator', role: 'tester' } };
    if (path === '/explanation-method') value = { version: 'v1', prompts: { baseline: prompt, candidate: prompt } };
    if (path === '/prompt-versions') value = [prompt];
    if (path === '/active-prompt') value = prompt;
    if (path === '/active-prompt-group') value = { group, communication: prompt, task_prompts: group.task_prompts };
    if (path === '/prompt-groups') value = [group];
    if (path === '/sessions/original-run') value = { turns: [{ run_id: 'original-run', input: '那灌溉呢？', request_snapshot: {
      history: [{ role: 'user', content: '玉米农田有哪些影响因素？' }, { role: 'assistant', content: '水分与土壤条件。' }],
    } }] };
    return route.fulfill({ json: value });
  });
  await page.goto('/evaluation/explanation-trials?source_run=original-run');
  await page.getByLabel('账号', { exact: true }).fill('collaborator');
  await page.getByLabel('密码', { exact: true }).fill('ReviewPassword123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByLabel('用户问题', { exact: true })).toHaveValue('那灌溉呢？');
  await expect(page.getByRole('tab', { name: 'Prompt 组测评', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.getByText('共同初始历史 · 2 条', { exact: true }).click();
  await expect(page.getByText('用户：玉米农田有哪些影响因素？', { exact: true })).toBeVisible();
  await expect(page.getByText('助手：水分与土壤条件。', { exact: true })).toBeVisible();
});

test('finishing the last conversation in all records returns to its page without cycling through approved records', async ({ page }) => {
  const { sessions } = await setup(page);
  for (let index = 0; index < 10; index++) sessions.push(fixture(`C${index}`, '2026-10-18'));
  await page.goto('/evaluation/runs/B?review_status=&page=2&size=10');
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '通过并看下一条' }).click();
  await expect(page).toHaveURL(/\/evaluation\/runs\?review_status=&page=2&size=10$/);
  await expect(page.getByText('共查到 12 条会话记录')).toBeVisible();
});
