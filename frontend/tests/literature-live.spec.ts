import { test, expect, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

// Run only against tests.literature_fixture, never against a populated library.
test.skip(process.env.LITERATURE_LIVE_TEST !== '1', 'Requires the isolated literature fixture server');
const token = `literature-test-tester-${'0'.repeat(32)}`;
const headers = { Authorization: `Bearer ${token}` };
const pdf = (text: string) => execFileSync('../backend/.venv/bin/python', ['-c',
  'import fitz,sys; d=fitz.open(); d.new_page().insert_text((72,72),sys.argv[1]); sys.stdout.buffer.write(d.tobytes())', text]);

async function login(page: Page, path = '/evaluation/literature') {
  await page.goto(path);
  await page.getByLabel('账号', { exact: true }).fill('cau_tester');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await expect(page.getByRole('button', { name: '退出登录' })).toBeVisible();
}

test('PDF draft, validation, registration, edit cancellation, preview and lifecycle', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  const name = `浏览器验收 ${Date.now()}`;
  const raw = pdf(name);
  await login(page);
  await page.getByRole('button', { name: '新增文献' }).click();
  await page.locator('input[type=file]').setInputFiles({ name: 'acceptance.pdf', mimeType: 'application/pdf', buffer: raw });
  await expect(page.getByRole('status')).toContainText('文件已上传');
  await page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox').fill(name);
  await page.getByRole('button', { name: '保存草稿', exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/evaluation\/literature\/P-[A-F0-9]+$/);
  const id = page.url().split('/').pop()!;
  await expect(page.locator('dl')).toContainText('未填写');
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await page.getByRole('button', { name: '完成登记', exact: true }).click();
  await expect(page.getByRole('main').getByRole('alert')).toContainText('请填写作者或标记未知');
  await expect(page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox')).toHaveValue(name);
  await page.getByRole('group', { name: '作者（按论文署名顺序）' }).getByRole('checkbox', { name: '未知' }).check();
  await page.getByRole('group', { name: '发表形式', exact: true }).getByRole('combobox').selectOption('期刊论文');
  await page.getByRole('group', { name: '发表载体', exact: true }).getByRole('checkbox', { name: '未知' }).check();
  await page.getByRole('group', { name: '发表年份', exact: true }).getByRole('checkbox', { name: '未知' }).check();
  await page.getByRole('group', { name: '论文语言', exact: true }).getByRole('combobox').selectOption('英文');
  await page.getByRole('group', { name: '出处说明', exact: true }).getByRole('textbox').fill('自动化验收合成文件');
  await page.getByRole('button', { name: '完成登记', exact: true }).click();
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByRole('button', { name: '保存草稿' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '选择 PDF' })).toBeDisabled();
  await page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox').fill('不应保存');
  page.once('dialog', (d) => d.dismiss());
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await expect(page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox')).toHaveValue('不应保存');
  page.once('dialog', (d) => d.accept());
  await page.getByRole('button', { name: '取消', exact: true }).click();
  await page.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox')).toHaveValue(name);
  await page.getByRole('group', { name: '内部备注', exact: true }).getByRole('textbox').fill('修改已保存');
  await page.getByRole('button', { name: '保存修改', exact: true }).click();
  await expect(page.locator('dl')).toContainText('修改已保存');
  await page.getByRole('button', { name: '预览', exact: true }).click();
  await expect(page.getByTitle('PDF 预览')).toHaveAttribute('src', /^blob:/);
  await page.getByRole('button', { name: '关闭', exact: true }).click();
  const file = await page.request.get(`/api/literature/papers/${id}/file?download=true`, { headers });
  expect(file.status()).toBe(200);
  expect(await file.body()).toEqual(raw);
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '下载', exact: true }).click();
  expect((await downloadPromise).suggestedFilename()).toBe('acceptance.pdf');
  await page.screenshot({ path: info.outputPath('registered-paper.png'), fullPage: true });
  page.once('dialog', (d) => d.accept('暂存')); await page.getByRole('button', { name: '停用', exact: true }).click();
  await expect(page.getByRole('button', { name: '恢复', exact: true })).toBeVisible();
  page.once('dialog', (d) => d.accept()); await page.getByRole('button', { name: '恢复', exact: true }).click();
  await expect(page.getByRole('button', { name: '停用', exact: true })).toBeVisible();
  page.on('dialog', async (d) => { await d.accept(d.type() === 'prompt' ? '验收清理' : undefined); });
  await page.getByRole('button', { name: '删除', exact: true }).click();
  await expect(page.getByRole('button', { name: '新增文献' })).toBeVisible();
  expect((await page.request.get(`/api/literature/papers/${id}`, { headers })).status()).toBe(404);
  expect(errors).toEqual([]);
});

test('taxonomy tree, related paper selection, filter persistence and duplicate upload', async ({ page }, info) => {
  const name = `主题 ${Date.now()}`;
  await login(page, '/evaluation/literature-tags');
  await page.getByPlaceholder('维度名称').fill(name);
  await page.getByRole('button', { name: '保存维度', exact: true }).click();
  await page.getByRole('button', { name: new RegExp(`^${name}`) }).click();
  await page.getByRole('button', { name: '新增一级标签' }).click();
  await page.getByLabel('新标签名称').fill('父标签');
  await page.getByRole('button', { name: '保存标签', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('标签已保存');
  await page.getByRole('button', { name: '在 父标签 下新增标签' }).click();
  await page.getByLabel('新标签名称').fill('子标签');
  await page.getByRole('button', { name: '保存标签', exact: true }).click();
  await expect(page.getByText('子标签', { exact: true })).toBeVisible();
  const taxonomy = await (await page.request.get('/api/literature/taxonomy', { headers })).json();
  const dimension = taxonomy.dimensions.find((d: { name: string }) => d.name === name);
  const child = taxonomy.tags.find((t: { name: string; dimension_id: string }) => t.name === '子标签' && t.dimension_id === dimension.id);
  const raw = pdf(name);
  const upload = await (await page.request.post('/api/literature/uploads?filename=related.pdf', { headers, data: raw })).json();
  const paper = await (await page.request.post('/api/literature/papers', { headers, data: { upload_id: upload.upload_id, title: name, tag_ids: [child.id] } })).json();
  await page.getByRole('link', { name: '查看文献', exact: true }).click();
  await page.getByRole('button', { name: '新增文献' }).click();
  await page.getByLabel('搜索关联文献').fill(name);
  await page.getByRole('group', { name: '关联文献', exact: true }).getByRole('button', { name: new RegExp(name) }).click();
  await expect(page.getByRole('button', { name: '移除关联', exact: true })).toBeVisible();
  await page.locator('input[type=file]').setInputFiles({ name: 'renamed.pdf', mimeType: 'application/pdf', buffer: raw });
  await expect(page.getByRole('main').getByRole('alert')).toContainText('已有相同内容的 PDF');
  await expect(page.getByRole('button', { name: `查看现有文献 ${paper.id}` })).toBeVisible();
  page.once('dialog', (d) => d.accept()); await page.getByRole('button', { name: '取消', exact: true }).click();
  const search = page.getByPlaceholder('搜索标题、作者、载体、DOI 或文献 ID');
  await search.fill(name); await page.getByRole('button', { name: '查询', exact: true }).click();
  await page.getByRole('button', { name, exact: true }).click();
  await page.getByRole('button', { name: /返回列表/ }).click();
  await expect(search).toHaveValue(name);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: '新增文献' })).toBeVisible();
  await page.screenshot({ path: info.outputPath('mobile-library.png'), fullPage: true });
  await page.request.post(`/api/literature/papers/${paper.id}/delete`, { headers, data: { reason: 'fixture cleanup' } });
});

test('large PDF passes through the Next proxy without truncation', async ({ request }) => {
  const raw = execFileSync('../backend/.venv/bin/python', ['-c',
    'import fitz,sys; d=fitz.open(); d.new_page(); x=d.get_new_xref(); d.update_object(x,"<<>>"); d.update_stream(x,b"x"*(12*1024*1024),compress=False); sys.stdout.buffer.write(d.tobytes())'], { maxBuffer: 15 * 1024 * 1024 });
  const response = await request.post('/api/literature/uploads?filename=large.pdf', { headers, data: raw });
  expect(response.status()).toBe(200);
  const uploaded = await response.json();
  expect(uploaded.size).toBe(raw.length);
  expect(uploaded.sha256).toBe(createHash('sha256').update(raw).digest('hex'));
});

test('unsaved input survives cancelled browser back and upload retry', async ({ page }) => {
  await login(page);
  await page.getByRole('button', { name: '新增文献' }).click();
  await expect(page).toHaveURL(/\/literature\/new$/);
  const title = page.getByRole('group', { name: '论文标题', exact: true }).getByRole('textbox');
  await title.fill('保留未保存的输入');
  const dialog = page.waitForEvent('dialog', { timeout: 10000 });
  await page.evaluate(() => window.history.back());
  await (await dialog).dismiss();
  await expect(page).toHaveURL(/\/literature\/new$/);
  await expect(title).toHaveValue('保留未保存的输入');
  await page.route('**/api/literature/uploads?*', (route) => route.fulfill({ status: 502, contentType: 'text/html', body: 'gateway error' }), { times: 1 });
  const raw = pdf(`retry ${Date.now()}`);
  await page.locator('input[type=file]').setInputFiles({ name: 'retry.pdf', mimeType: 'application/pdf', buffer: raw });
  await expect(page.getByRole('main').getByRole('alert')).toContainText('上传服务暂时不可用');
  await expect(title).toHaveValue('保留未保存的输入');
  await page.locator('input[type=file]').setInputFiles({ name: 'retry.pdf', mimeType: 'application/pdf', buffer: raw });
  await expect(page.getByRole('status')).toContainText('文件已上传');
  await expect(title).toHaveValue('保留未保存的输入');
  page.once('dialog', (d) => d.accept());
  await page.evaluate(() => window.history.back());
  await expect(page).toHaveURL(/\/literature$/);
  await expect(page.getByRole('button', { name: '新增文献' })).toBeVisible();
});

test('100 MB PDF is accepted and 100 MB plus one byte is rejected', async ({ request }) => {
  test.skip(process.env.LITERATURE_SIZE_BOUNDARY_TEST !== '1', 'Explicit opt-in for the memory-intensive upload boundary test');
  test.setTimeout(120000);
  const raw = execFileSync('../backend/.venv/bin/python', ['-c',
    'import fitz,sys; target=100*1024*1024; d=fitz.open(); d.new_page(); x=d.get_new_xref(); d.update_object(x,"<<>>"); d.update_stream(x,b"x"*target,compress=False); overhead=len(d.tobytes())-target; d.update_stream(x,b"x"*(target-overhead),compress=False); raw=d.tobytes(); assert len(raw)==target; sys.stdout.buffer.write(raw)'], { maxBuffer: 110 * 1024 * 1024 });
  const config = await (await request.get('/api/literature/config', { headers })).json();
  expect(config.max_pdf_mb).toBe(100);
  const accepted = await request.post('/api/literature/uploads?filename=boundary.pdf', { headers, data: raw, timeout: 90000 });
  expect(accepted.status()).toBe(200);
  const uploaded = await accepted.json();
  expect(uploaded.size).toBe(raw.length);
  expect(uploaded.sha256).toBe(createHash('sha256').update(raw).digest('hex'));
  const rejected = await request.post('/api/literature/uploads?filename=oversize.pdf', { headers, data: Buffer.concat([raw, Buffer.from(' ')]), timeout: 90000 });
  expect(rejected.status()).toBe(413);
  expect((await rejected.json()).detail.code).toBe('file_too_large');
});
