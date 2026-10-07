import { test, expect, type Page } from '@playwright/test';

const reply = (answer: string) => ({
  answer, citations: [{ index: 1, source: 'data/papers/synthetic_maize.pdf', chunk_id: 'synthetic::001', score: .8, snippet: 'Synthetic browser test evidence. This is not an agronomic source.', title: '测试论文题名', author_hint: '测试作者', year: '2024', document_id: 'test-document', document_available: true }],
  usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 }, retrieved_count: 1, model: 'test-only',
  route: 'knowledge', agent_route: 'KNOWLEDGE', file_evidence: [], run_id: 'test-run', conversation_id: 'test-session', trace_saved: true,
  outcome: 'complete', attachment: null, sections: [], warnings: [],
});
async function send(page: Page, text: string) {
  await page.getByLabel('问题输入').fill(text); await page.getByRole('button', { name: '发送', exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/files/status', route => route.fulfill({ json: {
    files: route.request().postDataJSON().file_ids.map((file_id: string) => ({ file_id, status: 'available' })),
  } }));
});

test('Markdown tables, code, scoped citations and mobile overflow', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.route('**/api/chat', (route) => route.fulfill({ json: reply('### 结果说明\n**明确结论** [1] 与未提供的 [99]。\n\n| 指标 | 数值 |\n| --- | --- |\n| NO3 | 1.5 |\n\n```python\nprint("[1]")\n```\n\n<script>window.badScript = true</script>\n![remote](https://example.invalid/tracker.png)\n[unsafe](javascript:alert(1))') }));
  await page.goto('/'); await send(page, '测试 Markdown');
  await expect(page.getByRole('heading', { name: '结果说明' })).toBeVisible();
  await expect(page.getByRole('table')).toContainText('NO3');
  await expect(page.locator('pre code')).toContainText('print("[1]")');
  await expect(page.getByRole('button', { name: '查看引用 1', exact: true })).toHaveCount(1);
  await expect(page.getByText('测试论文题名')).not.toBeVisible();
  await expect(page.getByText('文献依据 · 1 篇')).toBeVisible();
  await expect(page.getByRole('button', { name: '查看引用 99' })).toHaveCount(0);
  await page.getByRole('button', { name: '查看引用 1', exact: true }).click();
  await expect(page.getByText('测试论文题名')).toBeVisible();
  await expect(page.getByText('作者：测试作者 · 年份：2024')).toBeVisible();
  await expect(page.getByRole('blockquote')).toHaveCount(1);
  await expect(page.getByText('开发者定位')).toHaveCount(0);
  await page.getByRole('button', { name: '返回回答' }).click();
  expect(await page.evaluate(() => 'badScript' in window)).toBe(false);
  await expect(page.locator('.markdown-answer img')).toHaveCount(0);
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0);
  await send(page, '第二轮引用');
  const marks = page.getByRole('button', { name: '查看引用 1', exact: true });
  await expect(marks).toHaveCount(2); await marks.last().click();
  expect(await page.evaluate(() => document.activeElement?.id.endsWith('-citation-1'))).toBe(true);
  const ids = await page.locator('li[id$="-citation-1"]').evaluateAll((els) => els.map((e) => e.id));
  expect(new Set(ids).size).toBe(2);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible();
  expect(errors).toEqual([]);
  await page.screenshot({ path: '/tmp/nitrogen-browser-mobile.png' });
});

test('copy feedback changes on every click and resets', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'clipboard', { configurable: true,
      value: { writeText: async () => {} } });
  });
  await page.route('**/api/chat', route => route.fulfill({ json: reply('可复制的回答') }));
  await page.goto('/'); await send(page, '复制反馈');
  for (let i = 0; i < 2; i++) {
    await page.getByRole('button', { name: '复制回答', exact: true }).click();
    await expect(page.getByRole('button', { name: '已复制', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: '复制回答', exact: true })).toBeVisible({ timeout: 1800 });
  }
});

test('retry does not duplicate user turn or history, clear rotates conversation', async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await page.route('**/api/chat', (route) => {
    requests.push(route.request().postDataJSON());
    return requests.length === 1 ? route.fulfill({ status: 502, json: { detail: { code: 'llm_unreachable', message: 'offline' } } }) : route.fulfill({ json: reply('恢复成功') });
  });
  await page.goto('/'); await send(page, '失败后重试');
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.getByText('恢复成功')).toBeVisible();
  await expect(page.getByText('失败后重试', { exact: true })).toHaveCount(1);
  expect(requests[0].history).toEqual(requests[1].history);
  await page.getByRole('button', { name: '新对话' }).click();
  await send(page, '新会话');
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2].session_id).not.toBe(requests[0].session_id);
});

test('dragged attachments, invalid files and expired attachment clear stale state', async ({ page }) => {
  await page.route('**/api/files?*', (route) => route.fulfill({ json: { file_id: 'browser-file', filename: 'Nbal_out.xlsx', status: 'pending', sha256: 'test', format: 'xlsx', kind: null, rows: null, expires_in_seconds: 1800 } }));
  await page.route('**/api/chat', (route) => route.fulfill({ status: 404, json: { detail: { code: 'file_not_found', message: 'expired' } } }));
  await page.goto('/');
  const transfer = await page.evaluateHandle(() => { const data = new DataTransfer(); data.items.add(new File(['fixture'], 'Nbal_out.xlsx')); return data; });
  await page.getByRole('form', { name: '聊天输入区' }).dispatchEvent('drop', { dataTransfer: transfer });
  await expect(page.getByText('已上传 · 提问时自动分析')).toBeVisible();
  await send(page, '硝态氮最大值');
  await expect(page.getByLabel('对话记录').getByRole('alert')).toBeVisible();
  await expect(page.getByRole('button', { name: '移除附件', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '重试', exact: true })).toHaveCount(0);
  await page.getByLabel('附加结果表').setInputFiles({ name: 'wrong.pdf', mimeType: 'application/pdf', buffer: Buffer.from('x') });
  await expect(page.locator('footer').getByRole('alert')).toContainText('.xls');
});

test('IME composition does not accidentally submit Ctrl+Enter', async ({ page }) => {
  let calls = 0;
  await page.route('**/api/chat', (route) => { calls++; return route.fulfill({ json: reply('完成') }); });
  await page.goto('/'); await page.getByLabel('问题输入').fill('组合输入');
  await page.getByLabel('问题输入').dispatchEvent('keydown', { key: 'Enter', ctrlKey: true, isComposing: true });
  expect(calls).toBe(0);
  await page.getByLabel('问题输入').press('Control+Enter');
  await expect(page.getByText('完成', { exact: true })).toBeVisible(); expect(calls).toBe(1);
});

test('sent files stay available when collapsed and new conversation clears context', async ({ page }) => {
  const requests: Record<string, unknown>[] = [];
  await page.route('**/api/files?*', route => route.fulfill({ json: {
    file_id: 'browser-file', filename: 'Nbal_out.xlsx', status: 'pending', sha256: 'test',
    format: 'xlsx', kind: null, rows: null, expires_in_seconds: 1800,
  } }));
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    const withFile = Boolean((requests.at(-1)?.file_ids as string[])?.length);
    const numeric = withFile;
    return route.fulfill({ json: {
      ...reply(numeric ? '数值结果' : '请先上传文件'),
      route: numeric ? 'file' : 'clarification',
      agent_route: numeric ? 'FILE_ANALYSIS' : 'CLARIFY',
      attachment: numeric ? { filename: 'Nbal_out.xlsx', status: 'ready', rows: 352, kind: 'nitrogen' } : null,
      file_evidence: numeric ? [{ filename: 'Nbal_out.xlsx', sha256: 'test', sheet: 'Nbal_out',
        field: 'leak_NO3(kg N ha-1)', unit: 'kg N ha-1', operation: 'max', value: 3.6593,
        model_day: 283, cell: 'Nbal_out!C284', day_cell: 'Nbal_out!A284', occurrences: 1,
        data_range: 'Nbal_out!C2:C353', tool_version: 'test', schema_id: 'test' }] : [],
    } });
  });
  await page.goto('/');
  await page.getByLabel('附加结果表').setInputFiles({ name: 'Nbal_out.xlsx', mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.from('test') });
  await send(page, '硝态氮最大值及日序');
  await expect(page.getByText('本会话可引用：Nbal_out.xlsx')).toBeVisible();
  await expect(page.getByRole('button', { name: '移除附件', exact: true })).toHaveCount(0);
  await send(page, '那最小值呢？');
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].file_ids).toEqual(['browser-file']);
  expect(requests[1].history).toHaveLength(2);
  await page.getByRole('button', { name: /收起文件：Nbal_out.xlsx/ }).click();
  await send(page, '那最小值呢？');
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2].file_ids).toEqual(['browser-file']);
  expect(requests[2].history).toHaveLength(4);
  await page.getByRole('button', { name: '新对话' }).click();
  await send(page, '你能做什么？');
  await expect.poll(() => requests.length).toBe(4);
  expect(requests[3].file_ids).toEqual([]);
  expect(requests[3].history).toBeUndefined();
  expect(requests[3].session_id).not.toBe(requests[2].session_id);
});

test('all session files are sent automatically and duplicate bytes are skipped before upload', async ({ page }) => {
  const requests: Array<{ file_ids: string[]; history?: unknown[] }> = [];
  let uploads = 0;
  const { createHash } = await import('node:crypto');
  await page.route('**/api/files?*', route => {
    uploads++;
    const filename = new URL(route.request().url()).searchParams.get('filename')!;
    const hash = createHash('sha256').update(route.request().postDataBuffer()!).digest('hex');
    return route.fulfill({ json: { file_id: `id-${uploads}`, filename, status: 'pending',
      sha256: hash, format: 'xlsx', kind: null, rows: null, expires_in_seconds: 1800 } });
  });
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: reply('已分析相关文件') });
  });
  await page.goto('/');
  const input = page.getByLabel('附加结果表');
  const file = (name: string, text: string) => ({ name, mimeType: 'application/octet-stream', buffer: Buffer.from(text) });
  await input.setInputFiles([file('same.xlsx', 'a'), file('same.xlsx', 'b')]);
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false })).toHaveCount(2);
  await expect(page.getByRole('radio')).toHaveCount(0);
  await input.setInputFiles(file('renamed.xlsx', 'a'));
  await expect(page.getByText(/已跳过重复文件/)).toBeVisible();
  expect(uploads).toBe(2);
  await send(page, 'PREC 最大值及日序');
  await expect(page.getByText('已分析相关文件')).toBeVisible();
  expect(requests[0].file_ids).toEqual(['id-1', 'id-2']);
  await page.getByRole('button', { name: /收起文件/ }).first().click();
  await input.setInputFiles(file('again.xlsx', 'a'));
  await expect(page.getByText(/已跳过重复文件：again.xlsx/)).toBeVisible();
  expect(uploads).toBe(2);
  await input.setInputFiles(file('wrong.pdf', 'x'));
  await expect(page.locator('footer').getByRole('alert')).toContainText('.xls');
  await send(page, '那最小值呢？');
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].file_ids).toEqual(['id-1', 'id-2']);
  expect(requests[1].history).toHaveLength(2);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.getByRole('button', { name: /收起文件/ })).toBeVisible();
  await expect(page.getByText(/暂存 30 分钟/)).toHaveCount(0);
  await page.screenshot({ path: '/tmp/nitrogen-session-files-mobile.png' });
  await page.getByRole('button', { name: '新对话' }).click();
  await expect(page.getByLabel('会话文件列表')).toHaveCount(0);
});

test('session count and combined size reject only excess files', async ({ page }) => {
  let uploaded = 0;
  await page.route('**/api/files?*', route => {
    uploaded++;
    const filename = new URL(route.request().url()).searchParams.get('filename')!;
    return route.fulfill({ json: { file_id: `size-${uploaded}`, filename, status: 'pending',
      sha256: `hash-${uploaded}`, format: 'xlsx', kind: null, rows: null, expires_in_seconds: 1800 } });
  });
  await page.goto('/');
  const input = page.getByLabel('附加结果表');
  const file = (name: string, size: number) => ({ name, mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: Buffer.alloc(size) });
  await input.setInputFiles([file('a.xlsx', 9 * 1024 * 1024), file('b.xlsx', 9 * 1024 * 1024),
    file('c.xlsx', 9 * 1024 * 1024), file('d.xlsx', 9 * 1024 * 1024)]);
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false }).nth(3)).toBeVisible({ timeout: 30000 });
  await input.setInputFiles(file('too-much.xlsx', 5 * 1024 * 1024));
  await expect(page.locator('footer').getByRole('alert')).toContainText('40 MiB');
  expect(uploaded).toBe(4);
  await input.setInputFiles(file('e.xlsx', 1024));
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false }).nth(4)).toBeVisible();
  await input.setInputFiles(file('sixth.xlsx', 1024));
  await expect(page.locator('footer').getByRole('alert').last()).toContainText('5 份');
  expect(uploaded).toBe(5);
  await input.setInputFiles(file('oversize.xlsx', 10 * 1024 * 1024 + 1));
  await expect(page.locator('footer').getByRole('alert').last()).toContainText('10 MiB');
  expect(uploaded).toBe(5);
});

test('server-valid files survive the original deadline and still deduplicate after adding another file', async ({ page }) => {
  const { createHash } = await import('node:crypto');
  let uploads = 0;
  const requests: { file_ids: string[] }[] = [];
  await page.route('**/api/files?*', route => route.fulfill({ json: {
    file_id: `expiry-${++uploads}`, filename: new URL(route.request().url()).searchParams.get('filename'),
    status: 'pending', sha256: createHash('sha256').update(route.request().postDataBuffer()!).digest('hex'),
    format: 'xlsx', expires_in_seconds: 1800,
  } }));
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: { ...reply('附件可用'), attachments: [{ file_id: 'expiry-1', status: 'ready' }] } });
  });
  await page.goto('/');
  const file = (name: string, content: string) => ({ name, mimeType: 'application/octet-stream', buffer: Buffer.from(content) });
  await page.getByLabel('附加结果表').setInputFiles(file('first.xlsx', 'first'));
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false })).toBeVisible();
  await page.evaluate(() => { const start = Date.now(); Date.now = () => start + 29 * 60000; });
  await send(page, '硝态氮最大值');
  await expect(page.getByText('附件可用', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: /收起文件：first.xlsx/ }).click();
  await page.evaluate(() => { const start = Date.now(); Date.now = () => start + 2 * 60000; });
  await page.getByLabel('附加结果表').setInputFiles(file('second.xlsx', 'second'));
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false })).toBeVisible();
  await send(page, '那最小值呢？');
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].file_ids).toEqual(['expiry-1', 'expiry-2']);
  await expect(page.getByText('附件可用', { exact: true })).toHaveCount(2);
  await page.getByLabel('附加结果表').setInputFiles(file('renamed.xlsx', 'first'));
  await expect(page.getByText(/已跳过重复文件：renamed.xlsx/)).toBeVisible();
  expect(uploads).toBe(2);
});

test('server-expired files can be reuploaded while status failures preserve the original files', async ({ page }) => {
  const { createHash } = await import('node:crypto');
  let uploads = 0;
  let statusFails = true;
  await page.route('**/api/files?*', route => route.fulfill({ json: {
    file_id: `expiry-${++uploads}`, filename: 'same.xlsx', status: 'pending',
    sha256: createHash('sha256').update(route.request().postDataBuffer()!).digest('hex'),
    format: 'xlsx', expires_in_seconds: 1800,
  } }));
  await page.route('**/api/files/status', route => statusFails
    ? route.fulfill({ status: 503, json: { detail: { code: 'file_store_full', message: '暂时无法核验附件' } } })
    : route.fulfill({ json: { files: [{ file_id: 'expiry-1', status: 'expired' }] } }));
  await page.goto('/');
  const file = { name: 'same.xlsx', mimeType: 'application/octet-stream', buffer: Buffer.from('same') };
  await page.getByLabel('附加结果表').setInputFiles(file);
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false })).toBeVisible();
  await page.getByLabel('附加结果表').setInputFiles(file);
  await expect(page.getByText('暂时无法核验附件', { exact: true })).toBeVisible();
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false })).toBeVisible();
  expect(uploads).toBe(1);
  statusFails = false;
  await page.getByLabel('附加结果表').setInputFiles(file);
  await expect(page.getByText(/会话文件已失效：same.xlsx/)).toBeVisible();
  await expect(page.getByText('已上传 · 提问时自动分析', { exact: false })).toHaveCount(1);
  expect(uploads).toBe(2);
  await expect(page.getByText(/已跳过重复文件/)).toHaveCount(0);
});

test('papers are deduplicated and every citation opens the matching paper', async ({ page }) => {
  const response = reply('第一处 [1]，同一文献第二处 [2]。');
  response.citations.push({ ...response.citations[0], index: 2, chunk_id: 'synthetic::002' });
  await page.route('**/api/chat', route => route.fulfill({ json: response }));
  await page.goto('/'); await send(page, '重复文献');
  await expect(page.getByText('文献依据 · 1 篇')).toBeVisible();
  await page.getByRole('button', { name: '查看引用 2', exact: true }).click();
  await expect(page.getByText('测试论文题名')).toHaveCount(1);
  await expect(page.locator('li[id$="-citation-1"]')).toBeFocused();
  await expect(page.locator('li[id$="-citation-2"]')).toHaveCount(0);
  await expect(page.locator('article')).not.toContainText('synthetic');
  await expect(page.getByRole('blockquote')).toContainText('Synthetic browser');
  await page.getByText('文献依据 · 1 篇').click();
  await expect(page.locator('li[id$="-citation-1"]')).not.toBeVisible();
});

test('missing metadata and absent evidence do not invent article details', async ({ page }) => {
  await page.route('**/api/chat', route => route.fulfill({ json: {
    ...reply('信息不全'), citations: [{ index: 1, source: 'private_123.pdf', chunk_id: 'internal', score: .9, snippet: 'hidden' }],
  } }));
  await page.goto('/'); await send(page, '缺失信息');
  await page.getByText('文献依据 · 1 篇').click();
  await expect(page.getByText('文献标题暂缺')).toBeVisible();
  await expect(page.getByText('作者：暂缺 · 年份：暂缺')).toBeVisible();
  await expect(page.getByText('原文暂不可用')).toBeVisible();
  await expect(page.locator('article')).not.toContainText('private_123');
  await page.route('**/api/chat', route => route.fulfill({ json: { ...reply('没有文献依据的回答'), citations: [] } }));
  await send(page, '无依据');
  await expect(page.locator('article').last()).toContainText('没有文献依据的回答');
  await expect(page.locator('article').last().locator('summary')).toHaveCount(0);
});

test('literature preview, download, close and unavailable feedback', async ({ page }) => {
  await page.route('**/api/chat', route => route.fulfill({ json: reply('阅读原文 [1]') }));
  await page.route('**/api/documents/test-document?*', route => route.fulfill({ contentType: 'application/pdf', body: '%PDF-1.4\n%%EOF' }));
  await page.goto('/'); await send(page, '查看原文');
  await page.getByRole('button', { name: '查看引用 1', exact: true }).click();
  await page.getByRole('button', { name: '预览文献' }).click();
  await expect(page.getByRole('dialog', { name: '文献预览' })).toBeVisible();
  await expect(page.locator('iframe[title="文献原文"]')).toHaveAttribute('src', /^blob:/);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await expect(page.getByRole('button', { name: '预览文献' })).toBeFocused();
  const downloading = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载文献' }).click();
  expect((await downloading).suggestedFilename()).toBe('测试论文题名.pdf');
  await page.route('**/api/documents/test-document?*', route => route.fulfill({ status: 404, json: { detail: { message: 'missing' } } }));
  await page.getByRole('button', { name: '预览文献' }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('文献原文暂时无法获取');
  await page.getByRole('button', { name: '关闭预览' }).click();
  await page.getByRole('button', { name: '下载文献' }).click();
  await expect(page.locator('article').getByRole('alert')).toContainText('文献原文暂时无法获取');
});

test('clipboard rejection shows failure instead of success', async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(navigator, 'clipboard', { configurable: true,
    value: { writeText: async () => { throw new Error('denied'); } } }));
  await page.route('**/api/chat', route => route.fulfill({ json: reply('复制失败测试') }));
  await page.goto('/'); await send(page, '复制失败');
  await page.getByRole('button', { name: '复制回答' }).click();
  await expect(page.getByText('复制失败，请手动选择复制')).toBeVisible();
  await expect(page.getByText('已复制', { exact: true })).toHaveCount(0);
});

test('reading earlier answers stays put when pending response arrives; latest restores navigation', async ({ page }) => {
  let release: (() => void) | undefined;
  let count = 0;
  await page.route('**/api/chat', async route => {
    count++;
    if (count === 3) await new Promise<void>(resolve => { release = resolve; });
    await route.fulfill({ json: reply(Array.from({ length: 35 }, (_, i) => `第 ${count} 轮，第 ${i + 1} 段内容。`).join('\n\n')) });
  });
  await page.goto('/');
  await send(page, '第一轮长回答');
  await expect(page.locator('article')).toHaveCount(1);
  await send(page, '第二轮长回答');
  await expect(page.locator('article')).toHaveCount(2);
  await send(page, '第三轮长回答');
  await expect.poll(() => Boolean(release)).toBe(true);
  const panel = page.getByLabel('对话记录');
  await panel.evaluate(el => { el.scrollTo({ top: 0, behavior: 'instant' }); el.dispatchEvent(new Event('scroll')); });
  await expect(page.getByRole('button', { name: '最新消息' })).toBeVisible();
  release!();
  await expect(page.locator('article')).toHaveCount(3);
  expect(await panel.evaluate(el => el.scrollTop)).toBeLessThan(100);
  await page.getByRole('button', { name: '最新消息' }).click();
  await expect.poll(() => panel.evaluate(el => el.scrollHeight - el.scrollTop - el.clientHeight)).toBeLessThan(160);
  await expect(page.getByRole('button', { name: '新对话' })).toBeVisible();
  await expect(page.getByLabel('问题输入')).toBeEnabled();
});
