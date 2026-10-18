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
  await page.route('**/api/eval/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/eval', '');
    calls.push(path);
    if (path === '/me') return route.fulfill({ json: { tester_id: 'human-reviewer', role } });
    if (path === '/login') return route.fulfill({ json: { token: 'review-token', user: { tester_id: 'human-reviewer', role } } });
    if (path === '/sessions') {
      const filtered = sessions.filter(item => !url.searchParams.get('review_status') || item.review_status === url.searchParams.get('review_status'))
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
  return { sessions, calls, conflictNext: () => { conflict = true; } };
}

test('daily entry has five primary links and approves directly without task or case setup', async ({ page }) => {
  const { calls } = await setup(page);
  const nav = page.getByRole('navigation', { name: '工作台导航' }).first();
  await expect(nav.getByRole('link')).toHaveCount(5);
  await expect(nav.getByRole('link', { name: '任务管理', exact: true })).toHaveCount(0);
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await expect(page.getByText('原问题A', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '通过并看下一条' }).click();
  await expect(page.getByText('原问题B', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '通过并看下一条' }).click();
  await expect(page.getByText('共查到 0 条会话记录')).toBeVisible();
  expect(calls.some(path => ['/tasks', '/cases', '/executions'].includes(path))).toBe(false);
});

test('marking, editing links, retest and human confirmation form one conversation workflow', async ({ page }) => {
  const { sessions } = await setup(page, 'tester');
  await page.getByRole('link', { name: '查看', exact: true }).first().click();
  await page.getByRole('button', { name: '标记问题', exact: true }).click();
  await page.getByLabel('哪里有问题，希望怎么改').fill('解释需要补充适用条件');
  await page.getByRole('button', { name: '保存问题' }).click();
  await expect(page.getByLabel('已标记问题')).toContainText('解释需要补充适用条件');
  await expect(page.getByRole('button', { name: '通过', exact: true })).toBeDisabled();
  await expect(page.getByRole('link', { name: '原始案例 ↗' })).toHaveAttribute('href', '/evaluation/case-library/case-material');
  await expect(page.getByRole('link', { name: '调整 Prompt ↗' })).toHaveAttribute('href', '/evaluation/explanation-trials?source_run=run-A');
  await page.getByRole('button', { name: '修改后重新验证' }).click();
  await expect(page.getByLabel('验证回答')).toContainText('修改后的回答，已补充适用条件。');
  await expect(page.getByText('原回答，需要核对条件。', { exact: true })).toBeVisible();
  expect(sessions[0].review_status).toBe('needs_changes');
  await page.screenshot({ path: '/tmp/nitrogen-lightweight-review-desktop.png', fullPage: true });
  await page.getByRole('button', { name: '确认解决', exact: true }).click();
  await page.getByRole('button', { name: '通过', exact: true }).click();
  expect(sessions[0].review_status).toBe('passed');
  expect(sessions[0].review!.history.at(-1)?.review_kind).toBe('human');
  await page.getByText('补充意见 / 协助复核（可选）', { exact: true }).click();
  await page.getByLabel('补充审核意见').fill('师兄已核对原文，条件一致。');
  await page.getByRole('button', { name: '保存意见' }).click();
  await page.getByText(/审核历史（/).click();
  await expect(page.getByText('师兄已核对原文，条件一致。', { exact: true })).toBeVisible();
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
  await page.getByRole('link', { name: '返回列表', exact: true }).click();
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
  await page.route('**/api/eval/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/eval', '');
    let value: unknown = [];
    if (path === '/me') value = { tester_id: 'collaborator', role: 'tester' };
    if (path === '/login') value = { token: 'collaborator-token', user: { tester_id: 'collaborator', role: 'tester' } };
    if (path === '/explanation-method') value = { version: 'v1', prompts: { baseline: prompt, candidate: prompt } };
    if (path === '/prompt-versions') value = [prompt];
    if (path === '/active-prompt') value = prompt;
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
  await expect(page.getByLabel('固定输入材料', { exact: false })).toHaveValue('用户：玉米农田有哪些影响因素？\n\n助手：水分与土壤条件。');
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
