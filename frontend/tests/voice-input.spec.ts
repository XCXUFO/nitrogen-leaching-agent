import { expect, test, type Page } from '@playwright/test';

type Result = { text: string; final: boolean };
interface MockRecognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  emit: (results: Result[]) => void;
  lateResult: (results: Result[]) => void;
  fail: (error: string) => void;
  end: () => void;
}
declare global {
  interface Window {
    __speech: {
      current: MockRecognition;
      starts: number;
      stops: number;
      aborts: number;
      pending: boolean;
      throwOnStart: boolean;
    };
  }
}

async function installSpeech(page: Page, prefixed = false) {
  await page.addInitScript(({ prefixed }) => {
    const state = window.__speech = { current: null as unknown as MockRecognition,
      starts: 0, stops: 0, aborts: 0, pending: false, throwOnStart: false };
    class MockSpeechRecognition {
      lang = '';
      continuous = false;
      interimResults = false;
      onstart: (() => void) | null = null;
      onresult: ((event: { results: { isFinal: boolean; 0: { transcript: string } }[] }) => void) | null = null;
      onerror: ((event: { error: string }) => void) | null = null;
      onend: (() => void) | null = null;
      savedResult: MockSpeechRecognition['onresult'] = null;
      start() {
        if (state.throwOnStart) throw new DOMException('denied', 'NotAllowedError');
        state.current = this;
        state.starts++;
        this.savedResult = this.onresult;
        if (!state.pending) this.onstart?.();
      }
      stop() { state.stops++; }
      abort() { state.aborts++; }
      emit(results: Result[]) {
        this.onresult?.({ results: results.map(result => ({ isFinal: result.final, 0: { transcript: result.text } })) });
      }
      lateResult(results: Result[]) {
        this.savedResult?.({ results: results.map(result => ({ isFinal: result.final, 0: { transcript: result.text } })) });
      }
      fail(error: string) { this.onerror?.({ error }); }
      end() { this.onend?.(); }
    }
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: prefixed ? undefined : MockSpeechRecognition });
    Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: prefixed ? MockSpeechRecognition : undefined });
  }, { prefixed });
}

test.beforeEach(async ({ page }) => {
  await page.route('**/api/chat/session', route => route.fulfill({ status: 404, json: {} }));
});

test('dictation preserves the draft, previews interim text and sends only after confirmation', async ({ page }) => {
  await installSpeech(page);
  let submitted: { query: string } | undefined;
  await page.route('**/api/chat', route => {
    submitted = route.request().postDataJSON();
    return route.fulfill({ status: 502, json: { detail: { code: 'llm_unreachable', message: 'offline' } } });
  });
  await page.goto('/');
  const input = page.getByLabel('问题输入');
  await input.fill('已有草稿：');
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止语音输入' })).toHaveAttribute('aria-pressed', 'true');
  expect(await page.evaluate(() => ({ lang: window.__speech.current.lang,
    continuous: window.__speech.current.continuous, interim: window.__speech.current.interimResults })))
    .toEqual({ lang: 'zh-CN', continuous: true, interim: true });
  await page.evaluate(() => window.__speech.current.emit([{ text: '氮素', final: false }]));
  await expect(page.getByRole('status')).toContainText('氮素');
  await page.screenshot({ path: '/tmp/nitrogen-voice-listening.png' });
  await expect(input).toHaveValue('已有草稿：');
  await page.evaluate(() => window.__speech.current.emit([{ text: '氮素淋失', final: true }]));
  await expect(input).toHaveValue('已有草稿： 氮素淋失');
  await page.evaluate(() => window.__speech.current.emit([
    { text: '氮素淋失', final: true }, { text: '有哪些因素', final: false },
  ]));
  await expect(input).toHaveValue('已有草稿： 氮素淋失');
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeDisabled();
  await input.press('Control+Enter');
  expect(submitted).toBeUndefined();
  await page.getByRole('button', { name: '停止语音输入' }).click();
  await expect(page.getByRole('status')).toContainText('正在识别');
  await page.evaluate(() => {
    window.__speech.current.emit([{ text: '氮素淋失', final: true }, { text: '受哪些因素影响？', final: true }]);
    window.__speech.current.end();
  });
  await expect(input).toHaveValue('已有草稿： 氮素淋失 受哪些因素影响？');
  expect(await page.evaluate(() => window.__speech.stops)).toBe(1);
  expect(submitted).toBeUndefined();
  await input.fill('氮素淋失主要受哪些因素影响？');
  await page.getByRole('button', { name: '发送', exact: true }).click();
  await expect.poll(() => submitted?.query).toBe('氮素淋失主要受哪些因素影响？');
  await expect(input).toHaveValue('');
});

test('prefixed recognition supports repeated sessions and mobile layout', async ({ page }) => {
  await installSpeech(page, true);
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto('/');
  for (const text of ['灌溉', '措施']) {
    await page.getByRole('button', { name: '语音输入', exact: true }).click();
    await page.evaluate(text => {
      window.__speech.current.emit([{ text, final: true }]);
      window.__speech.current.end();
    }, text);
  }
  await expect(page.getByLabel('问题输入')).toHaveValue('灌溉 措施');
  await expect(page.getByRole('button', { name: '语音输入', exact: true })).toBeInViewport();
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: '/tmp/nitrogen-voice-mobile.png' });
});

test('permission and recognition failures keep the draft and allow another attempt', async ({ page }) => {
  await installSpeech(page);
  await page.goto('/');
  await page.getByLabel('问题输入').fill('保留文字');
  for (const [error, message] of [
    ['not-allowed', '请允许麦克风权限'], ['audio-capture', '未找到可用的麦克风'],
    ['network', '语音识别连接失败'], ['no-speech', '未听到语音'],
  ]) {
    await page.getByRole('button', { name: '语音输入', exact: true }).click();
    await page.evaluate(error => window.__speech.current.fail(error), error);
    await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toContainText(message);
    await expect(page.getByLabel('问题输入')).toHaveValue('保留文字');
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
  }
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toHaveCount(0);
  await page.evaluate(() => window.__speech.current.end());
  await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toContainText('未识别到文字');
});

test('unsupported browsers and insecure pages retain keyboard input', async ({ page }) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, 'SpeechRecognition', { configurable: true, value: undefined });
    Object.defineProperty(window, 'webkitSpeechRecognition', { configurable: true, value: undefined });
  });
  await page.goto('/');
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toContainText('当前浏览器不支持语音输入');
  await page.getByLabel('问题输入').fill('键盘输入正常');
  await expect(page.getByRole('button', { name: '发送', exact: true })).toBeEnabled();
  await page.evaluate(() => Object.defineProperty(window, 'isSecureContext', { configurable: true, value: false }));
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toContainText('HTTPS');
});

test('switching conversations releases the microphone and ignores late results', async ({ page }) => {
  await installSpeech(page);
  await page.goto('/');
  await page.getByLabel('问题输入').fill('原对话');
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await page.evaluate(() => window.__speech.current.emit([{ text: '已识别文字', final: true }]));
  await page.getByRole('button', { name: '新对话', exact: true }).click();
  expect(await page.evaluate(() => window.__speech.aborts)).toBe(1);
  await page.evaluate(() => window.__speech.current.lateResult([{ text: '延迟结果', final: true }]));
  await expect(page.getByLabel('问题输入')).toHaveValue('');
  await page.getByRole('button', { name: '切换对话：原对话 已识别文字', exact: true }).click();
  await expect(page.getByLabel('问题输入')).toHaveValue('原对话 已识别文字');
  await expect(page.getByRole('button', { name: '语音输入', exact: true })).toBeVisible();
});

test('pending permission can be cancelled and synchronous start errors recover', async ({ page }) => {
  await installSpeech(page);
  await page.goto('/');
  await page.getByLabel('问题输入').fill('草稿');
  await page.evaluate(() => { window.__speech.pending = true; });
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('正在开启麦克风');
  await page.getByRole('button', { name: '停止语音输入' }).click();
  await expect(page.getByRole('button', { name: '语音输入', exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.__speech.aborts)).toBe(1);
  await page.evaluate(() => { window.__speech.throwOnStart = true; });
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toContainText('请允许麦克风权限');
  await expect(page.getByLabel('问题输入')).toHaveValue('草稿');
});

test('stopping recovers if the browser never finishes recognition', async ({ page }) => {
  await installSpeech(page);
  await page.goto('/');
  await page.clock.install();
  await page.getByRole('button', { name: '语音输入', exact: true }).click();
  await page.getByRole('button', { name: '停止语音输入' }).click();
  await page.clock.fastForward(5100);
  await expect(page.getByRole('form', { name: '聊天输入区' }).getByRole('alert')).toContainText('语音识别超时');
  await expect(page.getByRole('button', { name: '语音输入', exact: true })).toBeEnabled();
});
