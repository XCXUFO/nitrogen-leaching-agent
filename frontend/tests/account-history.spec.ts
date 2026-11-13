import { expect, test, type Page } from '@playwright/test';
import type { AccountChatHistory, ChatRequest, ChatResponse, SavedConversation } from '../src/lib/types';

const response = (answer: string) => ({ answer, citations: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  retrieved_count: 0, model: 'history-test', route: 'knowledge', file_evidence: [], outcome: 'complete',
  attachment: null, sections: [], warnings: [], run_id: 'history-run', conversation_id: 'history-conversation',
  agent_route: 'KNOWLEDGE', trace_saved: true }) as ChatResponse;
const initial = (id: string, query: string): SavedConversation => ({ id, title: query, created_at: '2026-10-18', updated_at: '2026-10-18',
  turns: [{ run_id: `run-${id}`, turn_id: `turn-${id}`, request: { query, history: [], attachments: [],
    turnId: `turn-${id}`, requestId: `request-${id}` }, status: 'succeeded', response: response(`回答：${query}`),
    error: null, expires_at: 0, recoverable: false }] });

async function send(page: Page, query: string) {
  await page.getByLabel('问题输入').fill(query);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByLabel('对话记录')).toContainText(`回答：${query}`);
}

test('completed account chats survive refresh, fresh windows, logout and switching accounts', async ({ page, context }) => {
  test.setTimeout(120_000);
  const saved = new Map<string, SavedConversation[]>();
  const requests: ChatRequest[] = [];
  await context.route('**/api/**', route => {
    const url = new URL(route.request().url());
    const token = route.request().headers().authorization?.slice(7) || '';
    const user = token === 'token-b' ? 'b' : 'a';
    if (url.pathname === '/api/eval/login') {
      const name = route.request().postDataJSON().username;
      return route.fulfill({ json: { token: `token-${name}`, user: { tester_id: name, role: 'tester' } } });
    }
    if (url.pathname === '/api/eval/me') return route.fulfill({ json: { tester_id: user, role: 'tester' } });
    if (url.pathname === '/api/eval/logout') return route.fulfill({ status: 204 });
    if (url.pathname === '/api/chat/session') return route.fulfill({ status: 404, json: {} });
    if (url.pathname === '/api/chat/history') return route.fulfill({ json: { items: saved.get(user) || [], total: saved.get(user)?.length || 0 } satisfies AccountChatHistory });
    if (url.pathname === '/api/chat') {
      const body: ChatRequest = route.request().postDataJSON(); requests.push(body);
      const items = saved.get(user) || [];
      let item = items.find(item => item.id === body.session_id);
      const turn = initial(body.session_id!, body.query).turns[0];
      turn.turn_id += `-${requests.length}`;
      if (!item) { item = { ...initial(body.session_id!, body.query), turns: [] }; items.unshift(item); }
      item.turns.push(turn); saved.set(user, items);
      return route.fulfill({ json: turn.response });
    }
    return route.fulfill({ json: {} });
  });
  await page.addInitScript(() => sessionStorage.setItem('nitrogen_account_session', JSON.stringify({ token: 'token-a', username: 'a' })));
  await page.goto('/');
  await send(page, '账户 A 的问题');
  const sessionId = requests[0].session_id;
  await page.reload();
  await expect(page.getByLabel('对话记录')).toContainText('回答：账户 A 的问题');
  await send(page, '账户 A 的追问');
  expect(requests[1].session_id).toBe(sessionId);
  expect(requests[1].history).toEqual([{ role: 'user', content: '账户 A 的问题' }, { role: 'assistant', content: '回答：账户 A 的问题' }]);
  await page.getByRole('button', { name: '退出登录' }).click();
  await expect(page.getByLabel('对话记录')).not.toContainText('账户 A 的问题');

  const fresh = await context.newPage();
  await fresh.goto('/');
  await fresh.getByRole('link', { name: '内部人员登录' }).click();
  await fresh.getByLabel('账号', { exact: true }).fill('b');
  await fresh.getByLabel('密码', { exact: true }).fill('example-password');
  await fresh.getByRole('button', { name: '进入工作台' }).click();
  await expect(fresh.getByLabel('问题输入')).toBeVisible({ timeout: 15_000 });
  await expect(fresh.getByLabel('对话记录')).not.toContainText('账户 A 的问题');
  await send(fresh, '账户 B 的问题');
  await fresh.getByRole('button', { name: '退出登录' }).click();
  await fresh.getByRole('link', { name: '内部人员登录' }).click();
  await fresh.getByLabel('账号', { exact: true }).fill('a');
  await fresh.getByLabel('密码', { exact: true }).fill('example-password');
  await fresh.getByRole('button', { name: '进入工作台' }).click();
  await expect(fresh.getByLabel('对话记录')).toContainText('账户 A 的追问');
  await expect(fresh.getByLabel('对话记录')).not.toContainText('账户 B 的问题');
  await fresh.close();
});

test('loads older account histories, keeps over ten chats and retries an initial read failure', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('nitrogen_account_session', JSON.stringify({ token: 'token-a', username: 'a' })));
  const items = Array.from({ length: 32 }, (_, i) => initial(`saved-${i}`, `历史问题 ${i}`));
  let allowHistory = false;
  await page.route('**/api/eval/me', route => route.fulfill({ json: { tester_id: 'a', role: 'tester' } }));
  await page.route('**/api/chat/history?*', route => {
    if (!allowHistory) return route.fulfill({ status: 503, json: {} });
    const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
    return route.fulfill({ json: { items: items.slice(offset, offset + 30), total: items.length } });
  });
  await page.goto('/');
  await expect(page.getByText('历史会话暂时无法加载，请重试。', { exact: true })).toBeVisible({ timeout: 15_000 });
  allowHistory = true;
  await page.getByRole('button', { name: '重试加载历史会话' }).click();
  const sidebar = page.getByRole('complementary', { name: '历史对话' });
  await expect(sidebar.getByRole('button', { name: /^切换对话：/ })).toHaveCount(30);
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeDisabled();
  await sidebar.getByRole('button', { name: '加载更早的对话' }).click();
  await expect(sidebar.getByRole('button', { name: /^切换对话：/ })).toHaveCount(32);
  await sidebar.getByRole('button', { name: '新对话', exact: true }).click();
  await expect(sidebar.getByRole('button', { name: /^切换对话：/ })).toHaveCount(33);
  await sidebar.getByRole('button', { name: '切换对话：历史问题 31', exact: true }).click();
  await expect(page.getByLabel('对话记录')).toContainText('回答：历史问题 31');
});

test('a fresh account window recovers an unfinished regeneration without resubmitting', async ({ page }) => {
  await page.addInitScript(() => sessionStorage.setItem('nitrogen_account_session', JSON.stringify({ token: 'token-a', username: 'a' })));
  const saved = initial('running-chat', '已提交的问题');
  saved.turns[0] = { ...saved.turns[0], status: 'running', recoverable: true, expires_at: Date.now() / 1000 + 3600 };
  let submissions = 0;
  await page.route('**/api/eval/me', route => route.fulfill({ json: { tester_id: 'a', role: 'tester' } }));
  await page.route('**/api/chat/history?*', route => route.fulfill({ json: { items: [saved], total: 1 } }));
  await page.route('**/api/chat/session', route => route.fulfill({ json: { protocol: 'chat-runs-v1' } }));
  await page.route('**/api/chat', route => { submissions++; return route.abort(); });
  await page.route('**/api/chat/requests/*?*', route => route.fulfill({ json: {
    protocol: 'chat-runs-v1', run_id: 'run-running-chat', turn_id: saved.turns[0].turn_id,
    request_id: saved.turns[0].request.requestId, primary_run_id: 'run-running-chat', rerun_of_run_id: null,
    status: 'succeeded', outcome: 'complete', result: response('后台完成的新回答'), result_saved: true,
    error: null, events: [], last_sequence: 0,
  } }));
  await page.goto('/');
  await expect(page.getByLabel('对话记录')).toContainText('后台完成的新回答');
  await expect(page.getByLabel('对话记录')).not.toContainText('回答：已提交的问题');
  await expect(page.getByLabel('对话记录').getByText('已提交的问题', { exact: true })).toHaveCount(1);
  await expect(page.getByLabel('问题输入')).toBeEnabled();
  expect(submissions).toBe(0);
});

test('restored case suggestions and regeneration retain their structured case scope', async ({ page }) => {
  const ids = ['C-0000000000000001'];
  const saved = initial('case-history', '上面这个案例的适用条件是什么？');
  saved.turns[0].recoverable = true;
  saved.turns[0].expires_at = Date.now() / 1000 + 3600;
  saved.turns[0].request.caseIds = ids;
  saved.turns[0].response = { ...response('这份案例记录了滴灌措施，未记载确定的效果。'),
    case_match: 'matched', case_route: ['case_assistant'],
    case_references: [{ id: ids[0], title: '玉米滴灌', source: '测试资料' }] };
  const requests: ChatRequest[] = [];
  await page.addInitScript(() => sessionStorage.setItem('nitrogen_account_session', JSON.stringify({ token: 'token-a', username: 'a' })));
  await page.route('**/api/eval/me', route => route.fulfill({ json: { tester_id: 'a', role: 'tester' } }));
  await page.route('**/api/chat/history?*', route => route.fulfill({ json: { items: [saved], total: 1 } }));
  await page.route('**/api/chat/session', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: saved.turns[0].response });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '重新回答', exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].case_ids).toEqual(ids);
  await page.getByRole('region', { name: '推荐追问' }).getByRole('button').last().click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].case_ids).toEqual(ids);
});
