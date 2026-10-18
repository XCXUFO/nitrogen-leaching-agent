import { expect, test, type Page } from '@playwright/test';
import type { ChatRequest, ChatRunEvent, ChatRunView } from '../src/lib/types';

const answer = (text = '恢复后的完整回答') => ({
  answer: text, citations: [], usage: { prompt_tokens: 0, completion_tokens: 0, total_tokens: 0 },
  retrieved_count: 0, model: 'isolated-browser-test', route: 'direct' as const, file_evidence: [],
  run_id: 'run-one', conversation_id: 'conversation', agent_route: 'DIRECT' as const, trace_saved: true,
  outcome: 'complete' as const, attachment: null, sections: [], warnings: [],
});
function event(sequence: number, type: string, status: string, extra = {}): ChatRunEvent {
  return { event_id: `event-${sequence}`, run_id: 'run-one', sequence, time: new Date().toISOString(),
    type, status, summary: '测试事件', ...extra };
}
function receipt(request: ChatRequest, changes: Partial<ChatRunView> = {}): ChatRunView {
  return { protocol: 'chat-runs-v1', run_id: 'run-one', turn_id: request.turn_id!, request_id: request.request_id!,
    primary_run_id: 'run-one', rerun_of_run_id: request.rerun_of_run_id ?? null, status: 'running', outcome: null,
    events: [event(1, 'run_accepted', 'accepted'), event(2, 'step_started', 'running', { step_id: 'step-one', name: '文献检索' })],
    last_sequence: 2, result: null, result_saved: false, error: null, ...changes };
}
async function send(page: Page) {
  await page.getByLabel('问题输入').fill('原问题');
  await page.getByRole('button', { name: '发送', exact: true }).click();
}
test.beforeEach(async ({ page }) => {
  await page.route('**/api/chat/session', route => route.fulfill({ json: { protocol: 'chat-runs-v1' } }));
  await page.route('**/api/files/release', route => route.fulfill({ json: {} }));
});

for (const [code, message] of [
  ['llm_unreachable', '暂时无法连接大模型服务'],
  ['llm_timeout', '大模型响应超时'],
]) {
  test(`shows the cause of a saved ${code} failure and permits an explicit rerun`, async ({ page }) => {
    const requests: ChatRequest[] = [];
    await page.route('**/api/chat/requests/*?*', route => route.fulfill({ status: 404, json: {} }));
    await page.route('**/api/chat', route => {
      const request: ChatRequest = route.request().postDataJSON();
      requests.push(request);
      return route.fulfill({ status: 202, json: receipt(request, requests.length === 1 ? {
        status: 'failed', error: { code, message: '本次处理未完成，请稍后重新执行。', http_status: 502 },
      } : { status: 'succeeded', result: answer(), result_saved: true }) });
    });
    await page.goto('/'); await send(page);
    await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText(message);
    await expect(page.getByLabel('对话记录')).not.toContainText('本次处理未完成，请稍后重新执行。');
    await page.getByRole('button', { name: '重试', exact: true }).click();
    await expect(page.locator('article')).toContainText('恢复后的完整回答');
    expect(requests).toHaveLength(2);
    expect(requests[1].request_id).not.toBe(requests[0].request_id);
    expect(requests[1].turn_id).toBe(requests[0].turn_id);
    expect(requests[1].rerun_of_run_id).toBe('run-one');
  });
}

test('finds a lost first receipt, merges real steps by sequence and never resubmits a known run', async ({ page }) => {
  let request: ChatRequest | undefined;
  let posts = 0;
  const cursors: string[] = [];
  let finish = false;
  await page.route('**/api/chat/requests/*?*', route => request
    ? route.fulfill({ json: receipt(request) }) : route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => { posts++; request = route.request().postDataJSON(); return route.abort('connectionreset'); });
  await page.route('**/api/chat/runs/*?*', route => {
    cursors.push(new URL(route.request().url()).searchParams.get('after')!);
    return route.fulfill({ json: receipt(request!, finish ? {
      status: 'succeeded', result: answer(), result_saved: true, last_sequence: 4,
      events: [event(3, 'step_finished', 'succeeded', { step_id: 'step-one', name: '文献检索', outcome: 'no_result' }), event(4, 'run_finished', 'succeeded')],
    } : { events: [] }) });
  });
  await page.goto('/'); await send(page);
  await expect(page.getByLabel('实际执行步骤')).toContainText('文献检索');
  await expect(page.getByLabel('实际执行步骤').locator('li')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '新对话', exact: true })).toBeEnabled();
  await page.setViewportSize({ width: 320, height: 700 });
  await expect(page.getByLabel('处理进度')).toBeVisible();
  await page.screenshot({ path: '/tmp/chat-runs-progress-mobile.png' });
  finish = true;
  await expect(page.locator('article')).toContainText('恢复后的完整回答');
  await expect(page.getByLabel('处理进度')).toHaveCount(0);
  await expect(page.getByLabel('实际执行步骤')).toHaveCount(0);
  await expect(page.getByText(/^处理过程 ·/)).toHaveCount(0);
  await expect(page.getByLabel('对话记录').getByText('原问题', { exact: true })).toHaveCount(1);
  expect(posts).toBe(1); expect(cursors.every(cursor => cursor === '2')).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test('manual reconnect after repeated polling failures queries the same submission', async ({ page }) => {
  const requests: ChatRequest[] = [];
  await page.route('**/api/chat/requests/*?*', route => requests.length
    ? route.fulfill({ json: receipt(requests[0], { status: 'succeeded', result: answer(), result_saved: true }) })
    : route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => { requests.push(route.request().postDataJSON()); return route.fulfill({ status: 202, json: receipt(requests[0]) }); });
  await page.route('**/api/chat/runs/*?*', route => route.abort('connectionreset'));
  await page.goto('/'); await send(page);
  await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText('执行可能仍在继续', { timeout: 15_000 });
  await expect(page.getByLabel('问题输入')).toBeDisabled();
  await expect(page.getByRole('button', { name: '附加文件', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('article')).toContainText('恢复后的完整回答');
  await expect(page.getByLabel('问题输入')).toBeEnabled();
  expect(requests).toHaveLength(1);
  await expect(page.getByLabel('对话记录').getByText('原问题', { exact: true })).toHaveCount(1);
});

test('a new conversation preserves a disconnected run for recovery after refresh', async ({ page }) => {
  const requests: ChatRequest[] = [];
  let finishOriginal = false;
  await page.route('**/api/chat/requests/*?*', route => {
    const requestId = new URL(route.request().url()).pathname.split('/').at(-1);
    const request = requests.find(item => item.request_id === requestId);
    return request ? route.fulfill({ json: receipt(request, finishOriginal ? {
      status: 'succeeded', result: answer('找回第一个对话的结果'), result_saved: true,
    } : {}) }) : route.fulfill({ status: 404, json: {} });
  });
  await page.route('**/api/chat', route => {
    const request: ChatRequest = route.request().postDataJSON();
    requests.push(request);
    return route.fulfill({ status: 202, json: receipt(request, requests.length === 1 ? {} : {
      run_id: 'new-conversation-run', primary_run_id: 'new-conversation-run',
      status: 'succeeded', result: answer('新对话的回答'), result_saved: true,
    }) });
  });
  await page.route('**/api/chat/runs/*?*', route => route.abort('connectionreset'));
  await page.goto('/'); await send(page);
  await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText('执行可能仍在继续', { timeout: 15_000 });
  await expect(page.getByLabel('问题输入')).toBeDisabled();
  await expect(page.getByText('原问题的执行状态尚未确认，请先重试找回结果，或新建对话继续提问。')).toBeVisible();
  const pendingKey = 'nitrogen_pending_runs_v1:visitor';
  await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), pendingKey)).toContain(requests[0].request_id!);

  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await page.getByLabel('问题输入').fill('新对话中的问题');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('article')).toContainText('新对话的回答');
  expect(requests).toHaveLength(2);
  expect(requests[1].session_id).not.toBe(requests[0].session_id);
  // Reaching the conversation limit may evict completed histories, never the
  // disconnected run whose only recovery IDs still live in the browser.
  for (let index = 0; index < 9; index++) {
    await page.getByRole('button', { name: '新对话', exact: true }).click();
    await page.getByLabel('问题输入').fill(`其他对话 ${index}`);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('article')).toContainText('新对话的回答');
  }
  await expect(page.getByRole('button', { name: '切换对话：原问题', exact: true })).toHaveCount(1);
  await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), pendingKey)).toContain(requests[0].request_id!);

  finishOriginal = true;
  await page.reload();
  await expect(page.locator('article')).toContainText('找回第一个对话的结果');
  await expect(page.getByLabel('问题输入')).toBeEnabled();
  await expect.poll(() => page.evaluate(key => sessionStorage.getItem(key), pendingKey)).toBeNull();
  expect(requests).toHaveLength(11);
});

test('attachment expiry while disconnected preserves the submitted run for recovery', async ({ page }) => {
  let request: ChatRequest | undefined;
  let complete = false;
  let posts = 0;
  await page.route('**/api/files?*', route => route.fulfill({ json: {
    file_id: 'expired-file', filename: 'original.txt', status: 'pending', sha256: 'original-hash', format: 'txt', expires_in_seconds: 1800,
  } }));
  await page.route('**/api/files/status', route => route.fulfill({ json: {
    files: [{ file_id: 'expired-file', status: 'expired' }],
  } }));
  await page.route('**/api/chat/requests/*?*', route => request
    ? route.fulfill({ json: receipt(request, complete ? {
      status: 'succeeded', result: answer('附件过期后仍找回原结果'), result_saved: true,
    } : {}) }) : route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => {
    posts++; request = route.request().postDataJSON();
    return route.fulfill({ status: 202, json: receipt(request!) });
  });
  await page.route('**/api/chat/runs/*?*', route => route.abort('connectionreset'));
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'original.txt', mimeType: 'text/plain', buffer: Buffer.from('original') });
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await send(page);
  await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText('执行可能仍在继续', { timeout: 15_000 });
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByText('部分会话文件已失效，请重新上传。')).toBeVisible();
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('nitrogen_pending_runs_v1:visitor'))).toContain(request!.request_id!);
  complete = true;
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('article')).toContainText('附件过期后仍找回原结果');
  expect(posts).toBe(1);
});

test('explicit regeneration changes request and run but preserves turn, original history and primary', async ({ page }) => {
  const requests: ChatRequest[] = [];
  await page.route('**/api/chat/requests/*?*', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => {
    const request: ChatRequest = route.request().postDataJSON(); requests.push(request);
    return route.fulfill({ status: 202, json: receipt(request, { run_id: `run-${requests.length}`, primary_run_id: 'run-1',
      status: 'succeeded', outcome: 'complete', result_saved: true, result: answer(`第${requests.length}次结果`) }) });
  });
  await page.goto('/'); await send(page);
  await expect(page.locator('article')).toContainText('第1次结果');
  await page.getByRole('button', { name: '重新回答', exact: true }).click();
  await expect(page.locator('article')).toContainText('第2次结果');
  expect(requests[1].turn_id).toBe(requests[0].turn_id);
  expect(requests[1].request_id).not.toBe(requests[0].request_id);
  expect(requests[1].rerun_of_run_id).toBe('run-1');
  expect(requests[1].history).toEqual(requests[0].history);
  expect(requests[1].file_ids).toEqual(requests[0].file_ids);
  await expect(page.locator('article')).toHaveCount(1);
});

test('terminal failure is not automatically rerun; deliberate retry links a new execution', async ({ page }) => {
  const requests: ChatRequest[] = [];
  await page.route('**/api/chat/requests/*?*', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => {
    const request = route.request().postDataJSON(); requests.push(request);
    return route.fulfill({ status: 202, json: receipt(request, requests.length === 1 ? {
      status: 'interrupted', outcome: 'unknown', events: [],
    } : { run_id: 'run-two', status: 'succeeded', result: answer(), result_saved: true }) });
  });
  await page.goto('/'); await send(page);
  await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText('原运行已结束');
  expect(requests).toHaveLength(1);
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('article')).toContainText('恢复后的完整回答');
  expect(requests[1].request_id).not.toBe(requests[0].request_id);
  expect(requests[1].turn_id).toBe(requests[0].turn_id);
  expect(requests[1].rerun_of_run_id).toBe('run-one');
});

test('expired recovery does not submit again and a new conversation gets a new namespace', async ({ page }) => {
  let expired = true;
  let posts = 0;
  await page.route('**/api/chat/requests/*?*', route => route.fulfill(expired ? {
    status: 410, json: { detail: { code: 'recovery_expired', message: 'expired' } },
  } : { status: 404, json: {} }));
  await page.route('**/api/chat', route => { posts++; return route.fulfill({ json: answer() }); });
  await page.goto('/'); await send(page);
  await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText('恢复窗口已结束');
  await expect(page.getByRole('button', { name: '重试', exact: true })).toHaveCount(0);
  expect(posts).toBe(0);
  expired = false;
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await send(page); await expect(page.locator('article')).toContainText('恢复后的完整回答');
  expect(posts).toBe(1);
});

test('volatile clarification hides progress and keeps the unsaved result notice', async ({ page }) => {
  await page.route('**/api/chat/requests/*?*', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => route.fulfill({ status: 202, json: receipt(route.request().postDataJSON(), {
    status: 'unknown', outcome: 'clarification', result: { ...answer('请补充模型文件'), route: 'clarification', outcome: 'clarification' },
    events: [event(2, 'step_finished', 'succeeded', { step_id: 'step-one', name: '文件检查', outcome: 'clarification' })],
  }) }));
  await page.goto('/'); await send(page);
  await expect(page.locator('article')).toContainText('请补充模型文件');
  await expect(page.getByLabel('处理进度')).toHaveCount(0);
  await expect(page.getByLabel('实际执行步骤')).toHaveCount(0);
  await expect(page.getByText(/^处理过程 ·/)).toHaveCount(0);
  await expect(page.getByText('本次结果尚未保存，关闭页面后可能无法找回。')).toBeVisible();
});

test('refresh restores the accepted pending request by lookup without another POST', async ({ page }) => {
  let request: ChatRequest | undefined;
  let posts = 0;
  let complete = false;
  await page.route('**/api/files?*', route => route.fulfill({ json: {
    file_id: 'run-file', filename: 'pending.txt', status: 'pending', sha256: 'pending-hash', format: 'txt', expires_in_seconds: 1800,
  } }));
  await page.route('**/api/files/status', route => route.fulfill({ json: {
    files: [{ file_id: 'run-file', status: 'available' }],
  } }));
  await page.route('**/api/chat/requests/*?*', route => request
    ? route.fulfill({ json: receipt(request, complete ? { status: 'succeeded', result: answer('刷新找回的原结果'), result_saved: true } : {}) })
    : route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => { posts++; request = route.request().postDataJSON(); return route.fulfill({ status: 202, json: receipt(request!) }); });
  await page.route('**/api/chat/runs/*?*', route => route.fulfill({ json: receipt(request!, { events: [] }) }));
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'pending.txt', mimeType: 'text/plain', buffer: Buffer.from('pending') });
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await send(page);
  await expect(page.getByLabel('处理进度')).toBeVisible();
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
  expect(request!.file_ids).toEqual(['run-file']);
  complete = true;
  await page.reload();
  await expect(page.locator('article')).toContainText('刷新找回的原结果');
  await expect(page.getByLabel('处理进度')).toHaveCount(0);
  await expect(page.getByLabel('实际执行步骤')).toHaveCount(0);
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeEnabled();
  expect(posts).toBe(1);
  await expect(page.getByLabel('对话记录').getByText('原问题', { exact: true })).toHaveCount(1);
});

test('groups actual retry attempts and displays partial starred coverage separately', async ({ page }) => {
  let finish = false;
  let request: ChatRequest;
  await page.route('**/api/chat/requests/*?*', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', route => {
    request = route.request().postDataJSON();
    return route.fulfill({ status: 202, json: receipt(request, {
      last_sequence: 5,
      events: [event(1, 'step_finished', 'succeeded', { step_id: 'starred', name: '已有问答匹配', kind: 'service', outcome: 'partial_coverage' }),
        event(2, 'step_started', 'running', { step_id: 'search', name: '补充文献', attempt_no: 1 }),
        event(3, 'step_finished', 'failed', { step_id: 'search', name: '补充文献', attempt_no: 1 }),
        event(4, 'step_started', 'running', { step_id: 'search', name: '补充文献', attempt_no: 2 }),
        event(5, 'step_finished', 'succeeded', { step_id: 'search', name: '补充文献', attempt_no: 2, outcome: 'no_result' })],
    }) });
  });
  await page.route('**/api/chat/runs/*?*', route => route.fulfill({ json: receipt(request, {
    last_sequence: 5, events: [],
    ...(finish ? { status: 'succeeded', outcome: 'partial', result_saved: true, result: { ...answer(), outcome: 'partial' } } : {}),
  }) }));
  await page.goto('/'); await send(page);
  await expect(page.getByLabel('处理进度')).toBeVisible();
  await expect(page.getByLabel('实际执行步骤').locator(':scope > li')).toHaveCount(2);
  await expect(page.getByLabel('实际执行步骤')).toContainText('已找到部分解答');
  await page.getByText('已记录 2 次尝试', { exact: true }).click();
  await expect(page.getByText('第 1 次 · 执行失败')).toBeVisible();
  await expect(page.getByText('第 2 次 · 已完成 · 未找到相关结果')).toBeVisible();
  finish = true;
  await expect(page.locator('article')).toContainText('恢复后的完整回答');
  await expect(page.locator('article')).toContainText('部分完成');
  await expect(page.getByLabel('处理进度')).toHaveCount(0);
  await expect(page.getByLabel('实际执行步骤')).toHaveCount(0);
  await expect(page.getByText(/^处理过程 ·/)).toHaveCount(0);
});

test('parallel conversations recover after refresh and keep progress, answers and failures isolated', async ({ page }) => {
  const requests = new Map<string, ChatRequest>();
  const states = new Map<string, 'succeeded' | 'failed'>();
  const view = (request: ChatRequest) => {
    const runId = `run-${request.request_id}`;
    const status = states.get(request.query) ?? 'running';
    return receipt(request, {
      run_id: runId, primary_run_id: runId, status,
      last_sequence: status === 'running' ? 2 : 3,
      events: [{ ...event(status === 'running' ? 2 : 3, status === 'running' ? 'step_started' : 'step_finished', status, {
        step_id: 'work', name: `处理${request.query}`,
      }), run_id: runId }],
      result: status === 'succeeded' ? { ...answer(`${request.query}的回答`), run_id: runId, conversation_id: request.session_id ?? null } : null,
      result_saved: status === 'succeeded',
      error: status === 'failed' ? { code: 'llm_unreachable', message: `${request.query}执行失败`, http_status: 502 } : null,
    });
  };
  await page.route('**/api/chat/requests/*?*', route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1);
    const request = [...requests.values()].find(item => item.request_id === id);
    return request ? route.fulfill({ json: view(request) }) : route.fulfill({ status: 404, json: {} });
  });
  await page.route('**/api/chat', route => {
    const request: ChatRequest = route.request().postDataJSON();
    requests.set(`run-${request.request_id}`, request);
    return route.fulfill({ status: 202, json: view(request) });
  });
  await page.route('**/api/chat/runs/*?*', route => {
    const id = new URL(route.request().url()).pathname.split('/').at(-1)!;
    return route.fulfill({ json: view(requests.get(id)!) });
  });
  const sidebar = (title: string) => page.getByRole('button', { name: `切换对话：${title}`, exact: true });
  const ask = async (query: string) => {
    await page.getByLabel('问题输入').fill(query);
    await page.getByRole('button', { name: '发送', exact: true }).click();
  };
  await page.goto('/'); await ask('会话 A');
  await expect(page.getByLabel('实际执行步骤')).toContainText('处理会话 A');
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await expect(page.getByLabel('实际执行步骤')).toHaveCount(0);
  await ask('会话 B');
  await expect(page.getByLabel('实际执行步骤')).toContainText('处理会话 B');
  await sidebar('会话 A').click();
  await expect(page.getByLabel('实际执行步骤')).toContainText('处理会话 A');
  await expect(page.getByLabel('实际执行步骤')).not.toContainText('处理会话 B');
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem('nitrogen_pending_runs_v1:visitor') || '{}').conversations?.length ?? 0)).toBe(2);
  await page.reload();
  await expect(sidebar('会话 A')).toHaveAttribute('aria-busy', 'true');
  await expect(sidebar('会话 B')).toHaveAttribute('aria-busy', 'true');
  await sidebar('会话 A').click();
  await expect(page.getByLabel('实际执行步骤')).toContainText('处理会话 A');
  states.set('会话 B', 'succeeded');
  await expect(sidebar('会话 B')).not.toHaveAttribute('aria-busy', 'true');
  await expect(page.getByLabel('问题输入')).toBeDisabled();
  await expect(page.locator('article')).toHaveCount(0);
  await sidebar('会话 B').click();
  await expect(page.locator('article')).toContainText('会话 B的回答');
  await expect(page.getByLabel('处理进度')).toHaveCount(0);
  await page.getByLabel('问题输入').fill('会话 B 的草稿');
  states.set('会话 A', 'failed');
  await expect(sidebar('会话 A')).not.toHaveAttribute('aria-busy', 'true');
  await expect(page.getByLabel('对话记录').getByRole('alert')).toHaveCount(0);
  await expect(page.getByLabel('问题输入')).toHaveValue('会话 B 的草稿');
  await sidebar('会话 A').click();
  await expect(page.getByLabel('对话记录').getByRole('alert')).toContainText('暂时无法连接大模型服务');
  await expect(page.locator('article')).toHaveCount(0);
  expect(requests.size).toBe(2);
  await expect(page.getByRole('navigation', { name: '对话列表' }).getByRole('button')).toHaveText(['会话 B', '会话 A']);
});

test('the first parallel chat and upload share visitor initialization before submitting actions', async ({ page }) => {
  let bootstraps = 0;
  let finishBootstrap!: () => void;
  const initialized = new Promise<void>(resolve => { finishBootstrap = resolve; });
  await page.route('**/api/chat/session', async route => {
    bootstraps++;
    await initialized;
    return route.fulfill({ json: { protocol: 'chat-runs-v1' }, headers: {
      'set-cookie': 'visitor_bootstrap=ready; Path=/api; HttpOnly; SameSite=Lax',
    } });
  });
  const cookies: string[] = [];
  await page.route('**/api/files?*', async route => {
    cookies.push((await route.request().allHeaders()).cookie ?? '');
    return route.fulfill({ json: {
      file_id: 'parallel-file', filename: 'parallel.txt', status: 'pending', sha256: 'parallel-hash', format: 'txt', expires_in_seconds: 1800,
    } });
  });
  await page.route('**/api/chat/requests/*?*', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/chat', async route => {
    cookies.push((await route.request().allHeaders()).cookie ?? '');
    const request: ChatRequest = route.request().postDataJSON();
    return route.fulfill({ status: 202, json: receipt(request, {
      status: 'succeeded', result_saved: true, result: answer(`${request.query}的回答`),
    }) });
  });
  await page.goto('/'); await send(page);
  await expect.poll(() => bootstraps).toBe(1);
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'parallel.txt', mimeType: 'text/plain', buffer: Buffer.from('parallel') });
  await expect(page.getByLabel('会话文件列表')).toContainText('正在上传附件');
  expect(bootstraps).toBe(1);
  expect(cookies).toHaveLength(0);
  finishBootstrap();
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await page.getByLabel('问题输入').fill('另一个问题');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('article')).toContainText('另一个问题的回答');
  await expect.poll(() => cookies.length).toBe(3);
  expect(cookies.every(cookie => cookie.includes('visitor_bootstrap=ready'))).toBe(true);
  await page.getByRole('button', { name: '切换对话：原问题', exact: true }).click();
  await expect(page.locator('article')).toContainText('原问题的回答');
});
