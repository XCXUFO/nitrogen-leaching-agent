import { test, expect, type Page } from '@playwright/test';

const reply = (answer: string) => ({
  answer, citations: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  retrieved_count: 0, model: 'test-only', route: 'knowledge', agent_route: 'KNOWLEDGE',
  file_evidence: [], outcome: 'complete', attachment: null, sections: [], warnings: [],
});
type Request = { query: string; session_id: string; file_ids: string[]; history?: { role: string; content: string }[] };
async function send(page: Page, text: string) {
  await page.getByLabel('问题输入').fill(text);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.getByLabel('问题输入')).toBeEnabled();
}
function history(page: Page, title: string) {
  return page.getByRole('button', { name: `切换对话：${title}`, exact: true });
}
const newChat = (page: Page) => page.getByRole('button', { name: '新对话', exact: true }).click();
const attachment = (name: string) => ({ name, mimeType: 'text/plain', buffer: Buffer.from(name) });

test.beforeEach(async ({ page }) => {
  await page.route('**/api/files/status', route => route.fulfill({ json: {
    files: route.request().postDataJSON().file_ids.map((file_id: string) => ({ file_id, status: 'available' })),
  } }));
  await page.route('**/api/files/release', route => route.fulfill({ json: {} }));
  await page.route('**/api/files?*', route => {
    const filename = new URL(route.request().url()).searchParams.get('filename')!;
    return route.fulfill({ json: { file_id: filename, filename, status: 'pending', sha256: filename, format: 'txt', expires_in_seconds: 1800 } });
  });
});

test('restores messages and drafts with isolated history, files and session IDs', async ({ page }) => {
  const requests: Request[] = [];
  const releases: unknown[] = [];
  await page.route('**/api/files/release', route => { releases.push(route.request().postDataJSON()); return route.fulfill({ json: {} }); });
  await page.route('**/api/chat', route => {
    const request = route.request().postDataJSON(); requests.push(request);
    return route.fulfill({ json: reply(`回答：${request.query}`) });
  });
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles(attachment('A.txt'));
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await send(page, '问题 A');
  await page.getByRole('button', { name: /收起文件：A.txt/ }).click();
  await page.getByLabel('问题输入').fill('A 的草稿');
  await newChat(page);
  await expect(page.getByLabel('问题输入')).toHaveValue('');
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
  await send(page, '问题 B');
  await page.getByLabel('问题输入').fill('B 的草稿');
  await history(page, '问题 A').click();
  await expect(history(page, '问题 A')).toHaveAttribute('aria-current', 'true');
  await expect(page.getByLabel('问题输入')).toHaveValue('A 的草稿');
  await expect(page.getByLabel('对话记录')).toContainText('回答：问题 A');
  await expect(page.getByLabel('对话记录')).not.toContainText('问题 B');
  await expect(page.getByRole('button', { name: /展开已收起的会话文件/ })).toBeVisible();
  await send(page, 'A 的追问');
  expect(requests[1].file_ids).toEqual([]);
  expect(requests[1].history).toBeUndefined();
  expect(requests[1].session_id).not.toBe(requests[0].session_id);
  expect(requests[2].session_id).toBe(requests[0].session_id);
  expect(requests[2].file_ids).toEqual(['A.txt']);
  expect(requests[2].history).toEqual([{ role: 'user', content: '问题 A' }, { role: 'assistant', content: '回答：问题 A' }]);
  await history(page, '问题 B').click();
  await expect(page.getByLabel('问题输入')).toHaveValue('B 的草稿');
  expect(releases).toEqual([]);
  await page.setViewportSize({ width: 320, height: 700 });
  await expect(history(page, '问题 A')).toBeHidden();
  await page.getByRole('button', { name: '打开侧边栏' }).click();
  await expect(history(page, '问题 A')).toBeVisible();
  await page.getByRole('button', { name: '收起侧边栏' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeInViewport();
});

test('caps retained conversations at ten, reuses blanks and releases only the least recent files', async ({ page }) => {
  const releases: { file_ids: string[]; session_id: string }[] = [];
  await page.route('**/api/files/release', route => { releases.push(route.request().postDataJSON()); return route.fulfill({ json: {} }); });
  await page.route('**/api/chat', route => route.fulfill({ json: reply('测试回答') }));
  await page.goto('/');
  await newChat(page); await newChat(page);
  await expect(page.getByRole('navigation', { name: '对话列表' }).getByRole('button')).toHaveCount(1);
  for (let index = 1; index <= 10; index++) {
    if (index > 1) await newChat(page);
    if (index <= 2) {
      await page.getByLabel('选择会话文件').setInputFiles(attachment(`${index}.txt`));
      await expect(page.getByText('已上传', { exact: true })).toBeVisible();
    }
    await send(page, `对话 ${index}`);
  }
  expect(releases).toEqual([]);
  await expect(page.getByText(/已达到.*个对话/)).toHaveCount(0);
  await expect(page.getByText(/10\s*个|\/10(?!\d)|上限/)).toHaveCount(0);
  await history(page, '对话 1').click(); // Opening an older chat makes it recent again.
  await newChat(page);
  await expect(page.getByRole('navigation', { name: '对话列表' }).getByRole('button')).toHaveCount(10);
  await expect(history(page, '对话 1')).toBeVisible();
  await expect(history(page, '对话 2')).toHaveCount(0);
  await expect(page.getByText('已达到 10 个对话，最早使用的对话已移除。')).toBeVisible();
  await expect.poll(() => releases.length).toBe(1);
  expect(releases[0].file_ids).toEqual(['2.txt']);
  await newChat(page);
  await expect(page.getByRole('navigation', { name: '对话列表' }).getByRole('button')).toHaveCount(10);
  await history(page, '对话 1').click();
  await expect(page.getByRole('navigation', { name: '对话列表' }).getByRole('button')).toHaveCount(9);
  await expect(page.getByLabel('对话记录')).toContainText('测试回答');
});

test('desktop history sits on the left and can collapse without losing the active draft', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('/');
  const sidebar = page.getByRole('complementary', { name: '历史对话' });
  const input = page.getByLabel('问题输入');
  await expect(sidebar).toBeVisible();
  await expect(page.getByText(/上限|\/10(?!\d)|刷新或关闭后清空/)).toHaveCount(0);
  const bounds = await sidebar.boundingBox();
  const content = await page.getByLabel('对话记录').boundingBox();
  expect(bounds!.x).toBe(0);
  expect(bounds!.height).toBe(800);
  expect(content!.x).toBeGreaterThanOrEqual(bounds!.width);
  const draft = '这是需要保留并根据可用宽度自动换行的输入内容。'.repeat(6);
  await input.fill(draft);
  const expandedHeight = await input.evaluate(element => element.clientHeight);
  await page.getByRole('button', { name: '收起侧边栏' }).click();
  await expect(sidebar).toBeHidden();
  await expect(page.getByRole('button', { name: '打开侧边栏' })).toBeFocused();
  await expect(input).toHaveValue(draft);
  await expect.poll(() => input.evaluate(element => element.clientHeight)).toBeLessThanOrEqual(expandedHeight);
  await page.getByRole('button', { name: '打开侧边栏' }).click();
  await expect(sidebar).toBeVisible();
  await expect(input).toHaveValue(draft);
  await expect.poll(() => input.evaluate(element => element.clientHeight)).toBe(expandedHeight);
  await page.screenshot({ path: testInfo.outputPath('desktop-sidebar.png') });
});

test('mobile drawer closes on selection, new chat, Escape and backdrop, with focus contained', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const toggle = page.getByRole('button', { name: '打开侧边栏' });
  const drawer = page.getByRole('dialog', { name: '历史对话' });
  await expect(page.getByRole('navigation', { name: '对话列表' })).toBeHidden();
  await page.getByLabel('问题输入').fill('手机端的草稿');
  await newChat(page);
  await toggle.click();
  await expect(drawer).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('mobile-drawer.png') });
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Shift+Tab');
  expect(await drawer.evaluate(element => element.contains(document.activeElement))).toBe(true);
  await history(page, '手机端的草稿').click();
  await expect(drawer).toBeHidden();
  await expect(page.getByLabel('问题输入')).toHaveValue('手机端的草稿');
  await expect(toggle).toBeFocused();
  await toggle.click();
  await drawer.getByRole('button', { name: '新对话', exact: true }).click();
  await expect(drawer).toBeHidden();
  await expect(page.getByLabel('问题输入')).toHaveValue('');
  await toggle.click();
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(toggle).toBeFocused();
  await toggle.click();
  await page.mouse.click(380, 400);
  await expect(drawer).toBeHidden();
  await toggle.click();
  await page.setViewportSize({ width: 1280, height: 800 });
  await expect(drawer).toBeHidden();
  await expect(page.getByRole('complementary', { name: '历史对话' })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 700 });
  await expect(page.getByRole('navigation', { name: '对话列表' })).toBeHidden();
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('mobile-chat.png') });
});

test('restores a failed request for retry and blocks switching while an answer is pending', async ({ page }) => {
  const requests: Request[] = [];
  let finish!: () => void;
  await page.route('**/api/chat', async route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 1) return route.fulfill({ status: 502, json: { detail: { code: 'llm_unreachable', message: 'offline' } } });
    if (requests.length === 3) await new Promise<void>(resolve => { finish = resolve; });
    return route.fulfill({ json: reply('成功') });
  });
  await page.goto('/'); await send(page, '失败的问题');
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeVisible();
  await newChat(page); await send(page, '另一个问题');
  await history(page, '失败的问题').click();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect.poll(() => Boolean(finish)).toBe(true);
  await expect(history(page, '另一个问题')).toBeDisabled();
  await expect(page.getByRole('button', { name: '新对话', exact: true })).toBeDisabled();
  finish();
  await expect(page.getByLabel('对话记录').getByText('成功', { exact: true })).toBeVisible();
  await expect(page.getByLabel('对话记录').getByText('失败的问题', { exact: true })).toHaveCount(1);
  expect(requests[2]).toEqual(requests[0]);
});

test('keeps draft-only and file-only conversations and clears history on refresh', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('问题输入').fill('只写草稿'); await newChat(page);
  await page.getByLabel('选择会话文件').setInputFiles(attachment('未发送.txt'));
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await newChat(page);
  await history(page, '只写草稿').click();
  await expect(page.getByLabel('问题输入')).toHaveValue('只写草稿');
  await history(page, '未发送.txt').click();
  await expect(page.getByLabel('会话文件列表')).toContainText('未发送.txt');
  await page.reload();
  await expect(page.getByRole('navigation', { name: '对话列表' }).getByRole('button')).toHaveCount(1);
  await expect(page.getByLabel('问题输入')).toHaveValue('');
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
});

test('renews archived attachments and applies delayed expiration to its owning conversation', async ({ page }) => {
  const checks: { session_id: string; file_ids: string[] }[] = [];
  let expire!: () => void;
  await page.route('**/api/files/status', async route => {
    const request = route.request().postDataJSON(); checks.push(request);
    if (request.file_ids.includes('A.txt')) await new Promise<void>(resolve => { expire = resolve; });
    return route.fulfill({ json: { files: request.file_ids.map((file_id: string) => ({ file_id, status: file_id === 'A.txt' ? 'expired' : 'available' })) } });
  });
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles(attachment('A.txt'));
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await newChat(page);
  await page.getByLabel('选择会话文件').setInputFiles(attachment('B.txt'));
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect.poll(() => Boolean(expire)).toBe(true);
  await expect.poll(() => checks.length).toBe(2);
  expect(new Set(checks.map(item => item.session_id)).size).toBe(2);
  await history(page, 'A.txt').click(); // A was archived when the check started.
  expire();
  await expect(page.getByText('部分会话文件已失效，请重新上传。')).toBeVisible();
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
  await history(page, 'B.txt').click();
  await expect(page.getByLabel('会话文件列表')).toContainText('B.txt');
  await expect(page.getByText('部分会话文件已失效，请重新上传。')).toHaveCount(0);
});

test('blocks switching during upload and releases attachments from all retained conversations on pagehide', async ({ page }) => {
  const releases: { file_ids: string[] }[] = [];
  let finish!: () => void;
  // Force the fetch fallback so cleanup requests remain observable in this test.
  await page.addInitScript(() => { navigator.sendBeacon = () => false; });
  await page.route('**/api/files/release', route => { releases.push(route.request().postDataJSON()); return route.fulfill({ json: {} }); });
  await page.route('**/api/files?*', async route => {
    const filename = new URL(route.request().url()).searchParams.get('filename')!;
    if (filename === 'B.txt') await new Promise<void>(resolve => { finish = resolve; });
    return route.fulfill({ json: { file_id: filename, filename, status: 'pending', sha256: filename, format: 'txt', expires_in_seconds: 1800 } });
  });
  await page.goto('/');
  await page.getByLabel('选择会话文件').setInputFiles(attachment('A.txt'));
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  await newChat(page);
  await page.getByLabel('选择会话文件').setInputFiles(attachment('B.txt'));
  await expect.poll(() => Boolean(finish)).toBe(true);
  await expect(history(page, 'A.txt')).toBeDisabled();
  await expect(page.getByRole('button', { name: '新对话', exact: true })).toBeDisabled();
  finish();
  await expect(page.getByText('已上传', { exact: true })).toBeVisible();
  expect(releases).toEqual([]);
  await page.evaluate(() => window.dispatchEvent(new Event('pagehide')));
  await expect.poll(() => releases.length).toBe(2);
  expect(releases.flatMap(item => item.file_ids).sort()).toEqual(['A.txt', 'B.txt']);
});
