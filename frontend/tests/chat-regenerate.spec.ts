import { test, expect, type Page } from '@playwright/test';

const reply = (answer: string) => ({
  answer, citations: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  retrieved_count: 0, model: 'test-only', route: 'knowledge', agent_route: 'KNOWLEDGE',
  file_evidence: [], outcome: 'complete', attachment: null, sections: [], warnings: [],
});
const failedReply = (outcome = 'clarification') => ({
  ...reply('机制结论与引用或适用范围未通过核对。'), outcome,
  warnings: [{ code: 'mechanism_scope_invalid', message: '未通过核对' }],
});
async function send(page: Page, query: string) {
  await page.getByLabel('问题输入').fill(query);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByLabel('问题输入')).toBeEnabled();
}

test.beforeEach(async ({ page }) => {
  // These cases exercise the legacy transport; recovery has its own suite.
  await page.route('**/api/chat/session', route => route.fulfill({ status: 404, json: {} }));
  await page.route('**/api/files/status', route => route.fulfill({ json: {
    files: route.request().postDataJSON().file_ids.map((file_id: string) => ({ file_id, status: 'available' })),
  } }));
  await page.route('**/api/files/release', route => route.fulfill({ json: {} }));
  await page.route('**/api/files?*', route => {
    const filename = new URL(route.request().url()).searchParams.get('filename')!;
    return route.fulfill({ json: { file_id: filename, filename, status: 'pending', sha256: filename,
      format: 'txt', expires_in_seconds: 1800 } });
  });
});

for (const outcome of ['clarification', 'partial']) {
  test(`regenerates a ${outcome} response returned with HTTP 200 in place`, async ({ page }) => {
    const requests: unknown[] = [];
    await page.route('**/api/chat', route => {
      requests.push(route.request().postDataJSON());
      return route.fulfill({ json: requests.length === 1 ? failedReply(outcome) : reply('恢复成功') });
    });
    await page.goto('/');
    await send(page, '氮素淋失主要受哪些因素影响？');
    await page.getByRole('button', { name: '重新回答', exact: true }).click();
    await expect(page.locator('article')).toHaveCount(1);
    await expect(page.locator('article')).toContainText('恢复成功');
    await expect(page.getByText('机制结论与引用或适用范围未通过核对。')).toHaveCount(0);
    await expect(page.getByLabel('对话记录').getByText('氮素淋失主要受哪些因素影响？', { exact: true })).toHaveCount(1);
    expect(requests[1]).toEqual(requests[0]);
    await page.setViewportSize({ width: 320, height: 700 });
    await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}

test('restores the original history and attachments after switching conversations and keeps the draft', async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: requests.length === 2 ? failedReply() : reply('测试回答') });
  });
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'A.txt', mimeType: 'text/plain', buffer: Buffer.from('A') });
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await send(page, '先讨论小麦');
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'A.txt', mimeType: 'text/plain', buffer: Buffer.from('A') });
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await send(page, '氮素淋失有哪些影响因素？');
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'B.txt', mimeType: 'text/plain', buffer: Buffer.from('B') });
  await expect(page.getByText('已上传', { exact: true })).toHaveCount(1);
  await page.getByLabel('问题输入').fill('未发送的草稿');
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  await send(page, '另一段对话');
  await page.getByRole('button', { name: '切换对话：先讨论小麦', exact: true }).click();
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toHaveCount(1);
  await page.getByRole('button', { name: '重新回答', exact: true }).click();
  await expect(page.getByLabel('问题输入')).toBeEnabled();
  await expect(page.getByLabel('问题输入')).toHaveValue('未发送的草稿');
  expect(requests[3]).toEqual(requests[1]);
  expect(requests[3].file_ids).toEqual(['A.txt']);
  expect(requests[3].history).toEqual([
    { role: 'user', content: '先讨论小麦' }, { role: 'assistant', content: '测试回答' },
  ]);
  await expect(page.locator('article')).toHaveCount(2);
});

test('blocks duplicate regeneration, retains the old answer on network failure, and can retry again', async ({ page }) => {
  const requests: unknown[] = [];
  let finish!: () => void;
  await page.route('**/api/chat', async route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 2) {
      await new Promise<void>(resolve => { finish = resolve; });
      return route.fulfill({ status: 502, json: { detail: { code: 'llm_unreachable', message: 'offline' } } });
    }
    return route.fulfill({ json: requests.length === 1 ? failedReply() : reply('重试恢复成功') });
  });
  await page.goto('/'); await send(page, '原问题');
  await page.getByRole('button', { name: '重新回答', exact: true }).evaluate(button => {
    (button as HTMLButtonElement).click(); (button as HTMLButtonElement).click();
  });
  await expect.poll(() => Boolean(finish)).toBe(true);
  await expect(page.getByRole('button', { name: '正在重新回答…', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: '新对话', exact: true })).toBeEnabled();
  expect(requests).toHaveLength(2);
  finish();
  await expect(page.getByLabel('对话记录').getByRole('alert')).toBeVisible();
  await expect(page.locator('article')).toContainText('机制结论与引用或适用范围未通过核对。');
  await page.getByRole('button', { name: '重新回答', exact: true }).click();
  await expect(page.locator('article')).toContainText('重试恢复成功');
  await expect(page.getByLabel('对话记录').getByRole('alert')).toHaveCount(0);
  await expect(page.locator('article')).toHaveCount(1);
  expect(requests[2]).toEqual(requests[0]);
});

test('does not regenerate with expired original attachments', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/chat', route => { calls++; return route.fulfill({ json: failedReply() }); });
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles({ name: 'A.txt', mimeType: 'text/plain', buffer: Buffer.from('A') });
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await send(page, '文件中的结论是什么？');
  await page.route('**/api/files/status', route => route.fulfill({ json: {
    files: [{ file_id: 'A.txt', status: 'expired' }],
  } }));
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect(page.getByRole('button', { name: '重新回答', exact: true })).toBeDisabled();
  await expect(page.getByText('原问题的附件已失效，请重新上传后再次提问。')).toBeVisible();
  expect(calls).toBe(1);
});
