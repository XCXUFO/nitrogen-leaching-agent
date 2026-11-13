import { expect, test } from '@playwright/test';

const created = '2026-10-05T08:30:00+00:00';
const session = { session_id: 'front-session-one', topic: '氮素淋失影响因素', created_at: created,
  operator_id: 'visitor_example123', status: '正常', latency_ms: 230, turn_count: 2 };
const trace = (run_id: string, input: string, answer: string) => ({ run_id, input, answer, started_at: created,
  status: 'ok', outcome: 'complete', latency_ms: 115, error_code: null,
  decision: { route: 'KNOWLEDGE', reason_code: 'knowledge_intent' },
  tool_calls: [{ skill: 'knowledge_search', status: 'ok', latency_ms: 110 }],
  execution_plan: { version: 'task-routing-v1', mode: 'auto', tasks: [{ subtask_id: 't1', candidate_skills: ['knowledge_search'] }], actual_calls: [{ skill: 'knowledge_search', status: 'ok' }], outcome: 'complete' },
  retrieval: [{ source_type: 'literature', pipeline: { version: 'local-postings-v1', status: 'ready', candidate_count: 12, rebuilt_materials: 0, elapsed_ms: 6, coverage: 'bounded' } }],
  starred_match: { status: 'partial', adopted: [{ question_id: 'q', answer: '已有维护答复', covered_aspects: ['尺度原因'] }], remaining_subtask_ids: ['t1'], uncovered_aspects: ['如何构建'] },
  state_before: { crop: null }, state_after: { crop: null }, evidence: [], sections: [], warnings: [] });

test('conversation records filter, paginate and reveal both turns with their traces', async ({ page }) => {
  const searches: URLSearchParams[] = [];
  await page.route('**/api/eval/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/eval', '');
    if (path === '/me') return route.fulfill({ json: { tester_id: 'dev', role: 'developer' } });
    if (path === '/login') return route.fulfill({ json: { token: 'mock-session-token', user: { tester_id: 'dev', role: 'developer' } } });
    if (path === '/sessions') {
      searches.push(url.searchParams);
      const filtered = url.searchParams.get('information') === 'none';
      return route.fulfill({ json: { total: filtered ? 0 : 50, items: filtered ? [] : [session] } });
    }
    if (path === '/sessions/front-session-one') return route.fulfill({ json: {
      ...session, turns: [trace('run-one', '氮素淋失有哪些影响因素？', '主要涉及降雨和土壤。'),
        trace('run-two', '那灌溉呢？', '灌溉也可能增加淋失。')],
    } });
    return route.fulfill({ json: [] });
  });
  await page.goto('/evaluation/runs');
  await page.getByLabel('账号', { exact: true }).fill('cau_mock');
  await page.getByLabel('密码', { exact: true }).fill('CauMock123');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByText('共查到 50 条会话记录')).toBeVisible();
  await page.getByLabel('每页条数').selectOption('10');
  await expect(page.getByRole('button', { name: '5', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '下一页' }).click();
  await expect.poll(() => searches.at(-1)?.get('offset')).toBe('10');
  await page.getByLabel('会话信息').fill('none');
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page.getByText('共查到 0 条会话记录')).toBeVisible();
  await page.getByRole('button', { name: '重置' }).click();
  await expect(page.getByText('共查到 50 条会话记录')).toBeVisible();
  await page.getByRole('link', { name: '查看', exact: true }).click();
  await expect(page).toHaveURL(/\/evaluation\/runs\/front-session-one$/);
  await expect(page.getByText('氮素淋失有哪些影响因素？', { exact: true })).toBeVisible();
  await expect(page.getByText('那灌溉呢？', { exact: true })).toBeVisible();
  await expect(page.getByLabel('路由与调用脉络')).toHaveCount(2);
  const second = page.getByRole('listitem').filter({ hasText: '那灌溉呢？' });
  await second.getByText('展开本轮 MQ 明细 · Run run-two').click();
  await expect(second.getByText('本轮计划：1 项子任务', { exact: false })).toBeVisible();
  await expect(second.getByText('星标前置：部分覆盖', { exact: false })).toBeVisible();
  await expect(second.getByText('检索索引：local-postings-v1', { exact: false })).toBeVisible();
  await expect(second.getByRole('link', { name: '查看当前能力说明：knowledge_search' })).toHaveAttribute('href', '/evaluation/skills/knowledge_search');
  await second.getByText('路由决策').click();
  await expect(second.getByText('knowledge_intent').first()).toBeVisible();
});
