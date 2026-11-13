import { expect, test } from '@playwright/test';
import type { ChatRequest, ChatResponse } from '../src/lib/types';

const reply = (changes: Partial<ChatResponse> = {}): ChatResponse => ({
  answer: '氮素淋失受到降雨和灌溉影响。水分下渗会带动硝态氮迁移，土壤质地和作物条件决定结论的适用范围。', citations: [], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
  retrieved_count: 0, model: 'test-only', route: 'knowledge', agent_route: 'KNOWLEDGE',
  file_evidence: [], run_id: 'test-run', conversation_id: 'test-session', trace_saved: true,
  outcome: 'complete', attachment: null, sections: [], warnings: [], ...changes,
});

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chat/session', route => route.fulfill({ status: 404, json: {} }));
});

test('answer feedback preserves the run identity and reuses its submission after a network failure', async ({ page }) => {
  await page.route('**/api/chat', route => route.fulfill({ json: reply() }));
  const feedback: { run_id: string; note: string; submission_id: string }[] = [];
  await page.route('**/api/chat/feedback', route => {
    feedback.push(route.request().postDataJSON());
    return feedback.length === 1 ? route.fulfill({ status: 503, json: { detail: { code: 'temporary_failure', message: '服务暂时不可用，请重试。' } } })
      : route.fulfill({ status: 201, json: { issue_id: 'issue-feedback', status: 'received' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: /^专业知识解答/ }).click();
  await page.getByRole('button', { name: '反馈问题', exact: true }).click();
  await page.getByLabel('哪里有问题，希望怎么改').fill('请补充适用条件与依据。');
  await page.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expect(page.locator('article').getByRole('status')).toContainText('重试');
  await page.getByRole('button', { name: '提交反馈', exact: true }).click();
  await expect(page.getByText('问题已提交，会连同原会话交给团队处理。', { exact: true })).toBeVisible();
  expect(feedback).toHaveLength(2);
  expect(feedback[0]).toEqual(feedback[1]);
  expect(feedback[1].run_id).toBe('test-run');
});

for (const example of [
  { title: '专业知识解答', response: reply(),
    second: '能用更通俗的话解释氮素淋失涉及的下渗过程吗？',
    third: '在氮素淋失问题中，降雨与灌溉分别怎样起作用？',
    fourth: '关于氮素淋失的结论，适用条件和局限是什么？' },
  { title: '案例', response: reply({ case_route: ['case_reference'], case_match: 'matched',
      case_references: [{ id: 'C-0000000000000001', title: '测试案例', source: '测试资料' }] }),
    second: '上面这个“测试案例”案例中的关键措施是什么，为什么这样做？',
    third: '上面这个“测试案例”案例有哪些适用条件，哪些做法不能直接照搬？',
    fourth: '上面这个“测试案例”案例的效果有哪些证据，哪些结论还不能确定？' },
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
    await expect(suggestions.getByRole('button')).toHaveCount(3);
    await suggestions.getByRole('button', { name: example.second, exact: true }).click();
    await expect(suggestions.getByRole('button', { name: example.third, exact: true })).toBeVisible();
    await suggestions.getByRole('button', { name: example.third, exact: true }).click();
    await expect(suggestions.getByRole('button', { name: example.fourth, exact: true })).toBeVisible();
    expect(requests.map(request => request.query).slice(1)).toEqual([example.second, example.third]);
    expect(new Set(requests.map(request => request.session_id)).size).toBe(1);
    expect(requests[1].history).toHaveLength(2);
    expect(requests[2].history).toHaveLength(4);
    for (const request of requests.slice(1)) {
      expect(request.case_ids).toEqual(example.title === '案例' ? ['C-0000000000000001'] : undefined);
    }
    await page.setViewportSize({ width: 390, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await suggestions.scrollIntoViewIfNeeded();
    await page.screenshot({ path: `/tmp/nitrogen-follow-ups-${example.title === '案例' ? 'case' : 'knowledge'}-mobile.png` });
    await suggestions.getByRole('button', { name: example.fourth, exact: true }).click();
    await expect(suggestions.getByRole('button', { name: example.fourth, exact: true })).toHaveCount(0);
    expect(requests[3].case_ids).toEqual(example.title === '案例' ? ['C-0000000000000001'] : undefined);
    if (example.title === '案例') await expect(suggestions).toHaveCount(0);
    await page.getByRole('button', { name: '打开侧边栏', exact: true }).click();
    await page.getByRole('dialog', { name: '历史对话' }).getByRole('button', { name: '新对话', exact: true }).click();
    await expect(suggestions).toHaveCount(0);
    await page.getByRole('button', { name: new RegExp(`^${example.title}`) }).click();
    await expect(suggestions.getByRole('button', { name: example.second, exact: true })).toBeVisible();
    expect(requests.at(-1)?.session_id).not.toBe(requests[0].session_id);
  });
}

test('case scope survives a failed suggestion, retry and answer regeneration', async ({ page }) => {
  const ids = ['C-0000000000000001', 'C-0000000000000002'];
  const response = reply({ case_match: 'matched', case_route: ['case_assistant'],
    case_gap_recorded: true,
    case_references: ids.map((id, index) => ({ id, title: `案例 ${index + 1}`, source: '测试资料' })) });
  const requests: ChatRequest[] = [];
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    if (requests.length === 2) return route.fulfill({ status: 502, json: { detail: { code: 'llm_timeout', message: '稍后重试' } } });
    return route.fulfill({ json: response });
  });
  await page.goto('/');
  await page.getByRole('button', { name: /^案例/ }).click();
  await expect(page.getByText(/本次路由：|此需求已记入案例待补充清单/)).toHaveCount(0);
  await expect(page.getByRole('heading', { name: '参考案例', exact: true })).toBeVisible();
  await page.getByRole('region', { name: '推荐追问' }).getByRole('button', { name: '上面这些案例有哪些适用条件，哪些做法不能直接照搬？', exact: true }).click();
  await page.getByRole('button', { name: '重试', exact: true }).click();
  await expect(page.locator('article')).toHaveCount(2);
  await page.getByRole('button', { name: '重新回答', exact: true }).click();
  await expect.poll(() => requests.length).toBe(4);
  expect(requests.slice(1).map((request) => request.case_ids)).toEqual([ids, ids, ids]);
  expect(requests[0].case_ids).toBeUndefined();
});

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

test('model outlook follows the answer and a new topic resets suggestions despite the same route', async ({ page }) => {
  let response = reply({ answer: '农业模型的未来可能包括机理模型与人工智能结合，用监测数据改善预测，并通过独立验证评估不确定性。这些是发展方向，不能作为确定的预测。' });
  const requests: ChatRequest[] = [];
  await page.route('**/api/chat', route => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: response });
  });
  await page.goto('/');
  await page.getByLabel('问题输入').fill('你认为农业模型的未来是什么？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const suggestions = page.getByRole('region', { name: '推荐追问' });
  await expect(suggestions.getByRole('button')).toHaveCount(3);
  await expect(suggestions).toContainText('哪些已有实际应用，哪些仍是研究设想');
  await expect(suggestions).toContainText('农业模型与人工智能结合');
  await expect(suggestions).not.toContainText('土壤、作物和气候');
  await expect(suggestions).not.toContainText('哪些因素对这个问题影响最大');
  await expect(suggestions).not.toContainText('文献依据');
  const first = await suggestions.getByRole('button').first().innerText();
  await suggestions.getByRole('button').first().click();
  await expect(suggestions.getByRole('button', { name: first, exact: true })).toHaveCount(0);
  expect(requests.at(-1)?.query).toBe(first);

  response = reply({ answer: '土壤质地描述砂、粉砂和黏粒的比例，它影响土壤孔隙、水分下渗与保水能力，不同作物和管理条件下的表现存在差异。' });
  await page.getByLabel('问题输入').fill('土壤质地是什么？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(suggestions).toContainText('土壤质地');
  await expect(suggestions).not.toContainText('农业模型');
  response = reply();
  await page.getByLabel('问题输入').fill('推荐一部电影');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(suggestions).toHaveCount(0);
});

test('no substantive answer produces no follow-ups and model questions do not assume unmentioned AI', async ({ page }) => {
  let response = reply({ answer: '暂时没有足够信息回答。' });
  await page.route('**/api/chat', route => route.fulfill({ json: response }));
  await page.goto('/');
  await page.getByLabel('问题输入').fill('你认为农业模型的未来是什么？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const suggestions = page.getByRole('region', { name: '推荐追问' });
  await expect(suggestions).toHaveCount(0);
  response = reply({ answer: '农业模型未来可能更重视多尺度过程、输入数据质量和独立验证，模型的适用条件仍需通过实际研究判断。' });
  await page.getByLabel('问题输入').fill('农业模型未来有哪些发展方向？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(suggestions.getByRole('button')).toHaveCount(2);
  await expect(suggestions).not.toContainText('人工智能');
});

test('evidence follow-up requires citations in the actual answer', async ({ page }) => {
  let response = reply();
  await page.route('**/api/chat', route => route.fulfill({ json: response }));
  await page.goto('/');
  await page.getByRole('button', { name: /^专业知识解答/ }).click();
  const suggestions = page.getByRole('region', { name: '推荐追问' });
  await expect(suggestions).not.toContainText('文献直接支持');
  response = reply({ citations: [{ index: 1, chunk_id: 'paper:1', source: 'paper.pdf', title: '氮淋失研究', snippet: '降雨影响淋失。', score: 1 }] });
  await page.getByLabel('问题输入').fill('氮素淋失有哪些研究依据？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect(suggestions).toContainText('哪些有文献直接支持，哪些仍需验证');
});
