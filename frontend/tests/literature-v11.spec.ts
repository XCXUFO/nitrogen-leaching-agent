import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const token = `literature-test-tester-${'0'.repeat(32)}`;
const headers = { Authorization: `Bearer ${token}` };
const fixture = 'http://127.0.0.1:8107';

test('three-level showcase cascades include descendants and combine dimensions on mobile', async ({ page }, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/showcase/literature');
  await page.getByRole('button', { name: '地区级联选择' }).click();
  await page.getByRole('checkbox', { name: '广西', exact: true }).check();
  await page.getByRole('button', { name: '展开 广西', exact: true }).click();
  await page.getByRole('button', { name: '展开 广西 / 南宁', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '广西 / 南宁 / 示范县', exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('mobile-cascade.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '完成选择' }).click();
  await expect(page.getByRole('status')).toHaveText('共 1 条示例文献');
  await page.getByRole('combobox', { name: '使用状态', exact: true }).selectOption('all');
  await expect(page.getByRole('status')).toHaveText('共 2 条示例文献');
  await page.getByRole('button', { name: '地区级联选择' }).click();
  await page.getByRole('checkbox', { name: '广西 / 南宁', exact: true }).check();
  await expect(page.getByRole('checkbox', { name: '广西', exact: true })).not.toBeChecked();
  await page.getByRole('checkbox', { name: '广西 / 桂林', exact: true }).check();
  await page.getByRole('button', { name: '完成选择' }).click();
  await expect(page.getByRole('status')).toHaveText('共 2 条示例文献');
  await page.getByRole('button', { name: '研究对象级联选择' }).click();
  await page.getByRole('checkbox', { name: '冬小麦', exact: true }).check();
  await page.getByRole('button', { name: '完成选择' }).click();
  await expect(page.getByRole('status')).toHaveText('共 1 条示例文献');
  await page.getByRole('button', { name: '重置筛选' }).click();
  await expect(page.getByRole('status')).toHaveText('共 2 条示例文献');
});

test('tree adds children in place and keeps same names in different paths distinguishable', async ({ page }, info) => {
  await page.goto('/showcase/literature-tags');
  await page.getByRole('button', { name: /^地区/ }).click();
  await expect(page.getByText('南宁', { exact: true })).not.toBeVisible();
  await page.getByRole('button', { name: '展开 广西', exact: true }).click();
  await page.getByRole('button', { name: '在 广西 / 桂林 下新增标签' }).click();
  await page.getByLabel('新标签名称').fill('示范县');
  await page.getByRole('button', { name: '保存标签', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('示例标签已添加');
  await page.getByRole('button', { name: '展开全部', exact: true }).click();
  await expect(page.getByText('示范县', { exact: true })).toHaveCount(2);
  for (const [parent, name] of [['广西 / 桂林 / 示范县', '乡镇'], ['广西 / 桂林 / 示范县 / 乡镇', '试验点']]) {
    await page.getByRole('button', { name: `在 ${parent} 下新增标签`, exact: true }).click();
    await page.getByLabel('新标签名称').fill(name);
    await page.getByRole('button', { name: '保存标签', exact: true }).click();
    await expect(page.getByText(name, { exact: true })).toBeVisible();
  }
  await expect(page.getByRole('button', { name: '在 广西 / 桂林 / 示范县 / 乡镇 / 试验点 下新增标签' })).toHaveCount(0);
  await page.getByRole('button', { name: '收起全部', exact: true }).click();
  await page.getByLabel('搜索标签树').fill('试验点');
  await expect(page.getByText('试验点', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('tag-tree.png'), fullPage: true });
});

test('backend hierarchy persists and parent filtering returns direct and descendant papers', async ({ page, request }, info) => {
  test.skip(process.env.LITERATURE_V11_FIXTURE !== '1', 'Requires isolated fixture on 8107');
  const name = `地区验收-${Date.now()}`;
  // All management requests are forwarded to an isolated database, never the live library.
  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({ response: await route.fetch({ url: fixture + url.pathname + url.search }) });
  });
  await page.goto('/evaluation/literature-tags');
  await page.getByLabel('账号', { exact: true }).fill('cau_tester');
  await page.getByLabel('密码', { exact: true }).fill('CauTest123456');
  await page.getByRole('button', { name: '进入工作台' }).click();
  await page.getByPlaceholder('维度名称').fill(name);
  await page.getByRole('button', { name: '保存维度', exact: true }).click();
  await page.getByRole('button', { name: new RegExp(`^${name}`) }).click();
  for (const [parent, label] of [['', '广西'], ['广西', '南宁'], ['广西 / 南宁', '示范县'], ['广西', '桂林']]) {
    await page.getByRole('button', { name: parent ? `在 ${parent} 下新增标签` : '新增一级标签', exact: true }).click();
    await page.getByLabel('新标签名称').fill(label);
    await page.getByRole('button', { name: '保存标签', exact: true }).click();
    await expect(page.getByText(label, { exact: true })).toBeVisible();
  }
  await page.reload();
  await page.getByRole('button', { name: new RegExp(`^${name}`) }).click();
  await page.getByRole('button', { name: '展开全部', exact: true }).click();
  await expect(page.getByText('示范县', { exact: true })).toBeVisible();
  const taxonomy = await (await request.get(`${fixture}/api/literature/taxonomy`, { headers })).json();
  const dimension = taxonomy.dimensions.find((d: { name: string }) => d.name === name);
  const tags = taxonomy.tags.filter((t: { dimension_id: string }) => t.dimension_id === dimension.id);
  const id = (label: string) => tags.find((t: { name: string }) => t.name === label).id;
  expect(tags.find((t: { name: string }) => t.name === '示范县').parent_id).toBe(id('南宁'));
  for (const [index, label] of ['广西', '示范县', '桂林', '未打标'].entries()) {
    const raw = execFileSync('../backend/.venv/bin/python', ['-c', 'import fitz,sys; d=fitz.open(); d.new_page().insert_text((72,72),sys.argv[1]); sys.stdout.buffer.write(d.tobytes())', name + String(index)]);
    const up = await request.post(`${fixture}/api/literature/uploads?filename=example.pdf`, { headers, data: raw });
    expect(up.ok()).toBe(true);
    const saved = await request.post(`${fixture}/api/literature/papers`, { headers, data: { upload_id: (await up.json()).upload_id, title: name + label, tag_ids: label === '未打标' ? [] : [id(label)] } });
    expect(saved.ok()).toBe(true);
  }
  await page.getByRole('link', { name: '查看文献', exact: true }).click();
  await expect(page.getByRole('group', { name: '创建时间起', exact: true })).not.toBeVisible();
  await page.getByPlaceholder('搜索标题、作者、载体、DOI 或文献 ID').fill(name);
  await page.getByRole('button', { name: `${name}级联选择` }).click();
  await page.getByRole('checkbox', { name: '广西', exact: true }).check();
  await page.getByRole('button', { name: '完成选择' }).click();
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page.getByText('共 3 条结果', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: `${name}级联选择` }).click();
  await page.getByRole('button', { name: '展开 广西', exact: true }).click();
  await page.getByRole('checkbox', { name: '广西 / 南宁', exact: true }).check();
  await page.getByRole('button', { name: '完成选择' }).click();
  await page.getByRole('button', { name: '查询', exact: true }).click();
  await expect(page.getByText('共 1 条结果', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: name + '示范县', exact: true }).click();
  await page.getByRole('button', { name: '返回列表', exact: true }).click();
  await expect(page.getByText('共 1 条结果', { exact: true })).toBeVisible();
  await page.screenshot({ path: info.outputPath('compact-library.png'), fullPage: true });
});
