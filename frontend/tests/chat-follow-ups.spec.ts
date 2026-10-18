import { expect, test } from '@playwright/test';
import type { ChatRequest, ChatResponse } from '../src/lib/types';

const reply = (changes: Partial<ChatResponse> = {}): ChatResponse => ({
  answer: '本轮测试回答', citations: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  retrieved_count: 0, model: 'test-only', route: 'knowledge', agent_route: 'KNOWLEDGE',
  file_evidence: [], run_id: 'test-run', conversation_id: 'test-session', trace_saved: true,
  outcome: 'complete', attachment: null, sections: [], warnings: [], ...changes,
});

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chat/session', route => route.fulfill({ status: 404, json: {} }));
});

for (const example of [
  { title: '专业知识解答', response: reply(),
    second: '能用更通俗的话解释一下上面提到的关键机制吗？',
    third: '结合前面的解释，田间管理可以从哪些方面改进？',
    fourth: '请把前面的要点整理成一份可操作的检查清单。' },
  { title: '案例', response: reply({ case_route: ['case_reference'], case_match: 'matched',
      case_references: [{ id: 'case-one', title: '测试案例', source: '测试资料' }] }),
    second: '上面案例中的关键措施是什么，为什么这样做？',
    third: '如果换成多雨地区，参考这些措施时需要调整什么？',
    fourth: '请基于前面的案例，整理一份分步骤的实施参考。' },
]) {
  test(`${example.title} guides later rounds in the same conversation and resets for a new one`, async ({ page }) => {
    const requests: ChatRequest[] = [];
    await page.route('**/api/chat', route => {
      requests.push(route.request().postDataJSON());
      return route.fulfill({ json: example.response });
    });
    await page.goto('/');
    if (example.title === '专业知识解答') {
      await expect(page.getByRole('button', { name: /^专业知识解答/ })).toBeVisible();
      await page.screenshot({ path: '/tmp/nitrogen-home-entry-cards.png' });
    }
    await page.getByRole('button', { name: new RegExp(`^${example.title}`) }).click();
    const suggestions = page.getByRole('region', { name: '推荐追问' });
    await expect(suggestions.getByRole('button')).toHaveCount(4);
    await suggestions.getByRole('button', { name: example.second, exact: true }).click();
    await expect(suggestions.getByRole('button', { name: example.third, exact: true })).toBeVisible();
    await suggestions.getByRole('button', { name: example.third, exact: true }).click();
    await expect(suggestions.getByRole('button', { name: example.fourth, exact: true })).toBeVisible();
    expect(requests.map(request => request.query).slice(1)).toEqual([example.second, example.third]);
    expect(new Set(requests.map(request => request.session_id)).size).toBe(1);
    expect(requests[1].history).toHaveLength(2);
    expect(requests[2].history).toHaveLength(4);
    await suggestions.getByRole('button', { name: example.fourth, exact: true }).click();
    await expect(suggestions.getByRole('button')).toHaveCount(4);
    await expect(suggestions.getByRole('button', { name: example.fourth, exact: true })).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await suggestions.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/nitrogen-follow-ups-${example.title === '案例' ? 'case' : 'knowledge'}-mobile.png` });
    await page.getByRole('button', { name: '打开侧边栏', exact: true }).click();
    await page.getByRole('dialog', { name: '历史对话' }).getByRole('button', { name: '新对话', exact: true }).click();
    await expect(suggestions).toHaveCount(0);
    await page.getByRole('button', { name: new RegExp(`^${example.title}`) }).click();
    await expect(suggestions.getByRole('button', { name: example.second, exact: true })).toBeVisible();
    expect(requests.at(-1)?.session_id).not.toBe(requests[0].session_id);
  });
}

test('unmatched cases guide users to refine the search and file answers omit these suggestions', async ({ page }) => {
  let response = reply({ case_route: ['case_reference'], case_match: 'missing' });
  await page.route('**/api/chat', route => route.fulfill({ json: response }));
  await page.goto('/');
  await page.getByRole('button', { name: /^案例/ }).click();
  const suggestions = page.getByRole('region', { name: '推荐追问' });
  await expect(suggestions).toContainText('为了找到合适的案例，我还需要补充哪些背景信息？');
  await expect(suggestions).not.toContainText('上面案例中的关键措施');
  response = reply({ route: 'file', agent_route: 'FILE_ANALYSIS' });
  await page.getByLabel('问题输入').fill('分析一下模型结果');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(page.locator('article')).toHaveCount(2);
  await expect(suggestions).toHaveCount(0);
});
