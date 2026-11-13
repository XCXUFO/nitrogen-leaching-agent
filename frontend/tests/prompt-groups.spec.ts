import { expect, test } from "@playwright/test";
import type { PromptGroup, TaskCatalog, TaskPrompt, Trial } from "../src/lib/prompt-types";

test("manage examples, compare complete zero/few-shot groups and retain per-turn results", async ({ page }) => {
  const global = { prompt_id: "global", label: "共同全局", text: "先回答，再解释术语。", version: "global-v1" };
  const task = (scope: TaskPrompt["scope"]): TaskPrompt => ({ prompt_id: scope, scope, label: `${scope} 原版`, text: "相同的任务规则。", version: "task-v1", examples: [] });
  const tasks: TaskCatalog = { versions: [], active: { concept_explanation: task("concept_explanation"), knowledge_search: task("knowledge_search"), case_assistant: task("case_assistant") } };
  tasks.versions = Object.values(tasks.active);
  const base: PromptGroup = { group_id: "base", label: "基准组", version: "group-v1", communication: global, task_prompts: { ...tasks.active } };
  const groups = [base];
  let activeGroup = base;
  let activationFails = false;
  let trial: Trial | null = null;
  let activations = 0;
  let submitted: Record<string, unknown> | null = null;
  await page.route("**/api/eval/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/eval", "");
    const method = route.request().method();
    if (path === "/me") return route.fulfill({ json: { tester_id: "dev", role: "developer" } });
    if (path === "/login") return route.fulfill({ json: { token: "group-test", user: { tester_id: "dev", role: "developer" } } });
    if (path === "/prompt-versions") return route.fulfill({ json: [global] });
    if (path === "/active-prompt") { if (method === "PUT") activations++; return route.fulfill({ json: global }); }
    if (path === "/active-prompt-group") {
      if (method === "PUT") {
        if (activationFails) return route.fulfill({ status: 503, json: { detail: { message: "启用暂时失败，请重试" } } });
        const body = route.request().postDataJSON();
        activeGroup = groups.find(g => g.group_id === body.group_id)!;
        expect(activeGroup).toBeTruthy();
        tasks.active = { ...activeGroup.task_prompts };
        activations++;
      }
      return route.fulfill({ json: { group: activeGroup, communication: activeGroup.communication, task_prompts: activeGroup.task_prompts } });
    }
    if (path.endsWith("/active")) { activations++; return route.fulfill({ json: {} }); }
    if (path === "/task-prompts") {
      if (method === "POST") {
        const body = route.request().postDataJSON();
        expect(body.text).toBe(tasks.active.concept_explanation.text);
        expect(body.examples).toHaveLength(1);
        expect(body.examples[0]).toMatchObject({ confirmed: true, source_case: "CASE-1", source_revision: "2" });
        const saved = { ...body, prompt_id: "concept-few", version: "task-few" };
        tasks.versions.unshift(saved);
        return route.fulfill({ status: 201, json: saved });
      }
      return route.fulfill({ json: tasks });
    }
    if (path === "/prompt-groups") {
      if (method === "POST") {
        const body = route.request().postDataJSON();
        const group: PromptGroup = { group_id: "few-group", label: body.label, version: "group-few", communication: global,
          task_prompts: Object.fromEntries(Object.entries(body.task_prompt_ids).map(([scope, id]) => [scope, tasks.versions.find(p => p.prompt_id === id)!])) as PromptGroup["task_prompts"] };
        groups.unshift(group);
        return route.fulfill({ status: 201, json: group });
      }
      return route.fulfill({ json: groups });
    }
    if (path === "/explanation-trials") {
      if (method === "GET") return route.fulfill({ json: trial ? [trial] : [] });
      submitted = route.request().postDataJSON();
      expect(submitted).toMatchObject({ query: "WHCNS模型", material: "共同材料", followups: ["硝化作用是什么意思"], groups: { baseline: "base", candidate: "few-group" } });
      trial = { trial_id: "trial", query: "WHCNS模型", material: "共同材料", followups: ["硝化作用是什么意思"], status: "completed", groups: { baseline: base, candidate: groups[0] }, variants: {} };
      for (const variant of ["baseline", "candidate"] as const) {
        const few = variant === "candidate";
        trial.variants[variant] = { status: "succeeded", unused_task_scopes: ["knowledge_search", "case_assistant"], steps: ["WHCNS模型", "硝化作用是什么意思"].map((query, i) => ({
          run_id: `${variant}-${i}`, query, status: "succeeded", actual_prompt: global, skills: ["concept_explanation"],
          task_prompt_usage: [{ scope: "concept_explanation", version: few ? "task-few" : "task-v1", shot_mode: few ? "few-shot" : "zero-shot", example_count: few ? 1 : 0 }],
          response: { answer: `${few ? "带示例" : "无示例"}回答${i + 1}`, citations: [] },
        })) };
      }
      return route.fulfill({ status: 202, json: { ...trial, status: "accepted", variants: {} } });
    }
    if (path === "/explanation-trials/trial") return route.fulfill({ json: trial });
    return route.fulfill({ json: [] });
  });
  await page.goto("/evaluation/explanation-trials");
  await page.getByLabel("账号", { exact: true }).fill("dev");
  await page.getByLabel("密码", { exact: true }).fill("FixturePassword");
  await page.getByRole("button", { name: "进入工作台" }).click();
  await expect(page.getByRole("heading", { name: "Prompt 管理", exact: true })).toBeVisible();
  await expect(page.getByRole("tab", { name: "方案看板" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByLabel("当前生效方案", { exact: true })).toContainText("基准组");
  await page.getByRole("tab", { name: "Prompt 版本管理" }).click();
  await page.getByText("编辑并另存任务候选", { exact: true }).click();
  await page.getByLabel("任务候选名称", { exact: true }).fill("概念 few-shot");
  await page.getByRole("radio", { name: "few-shot · 带示例" }).check();
  await page.getByLabel("示例1问题", { exact: true }).fill("示范概念？");
  await page.getByLabel("示例1回答", { exact: true }).fill("这是示范回答。");
  await page.getByLabel("示例1来源", { exact: true }).fill("CASE-1");
  await page.getByLabel("示例1来源版本", { exact: true }).fill("2");
  await page.getByLabel("示例1核对范围", { exact: true }).fill("概念解释方式");
  await expect(page.getByRole("button", { name: "保存任务候选", exact: true })).toBeDisabled();
  await page.getByRole("checkbox", { name: "已核对示例内容与来源，确认可用作示范" }).check();
  await page.getByRole("button", { name: "保存任务候选", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("尚未启用");
  await page.getByRole("tab", { name: "Prompt 组测评", exact: true }).click();
  await page.getByLabel("右侧概念解释版本", { exact: true }).selectOption("concept-few");
  await page.getByLabel("右侧版本组名称", { exact: true }).fill("概念示例组");
  await expect(page.getByLabel("版本组差异")).toContainText("任务规则相同，仅示例不同");
  await expect(page.getByRole("button", { name: "开始左右组测评" })).toBeDisabled();
  await page.getByRole("button", { name: "保存右侧版本组" }).click();
  await expect(page.getByLabel("右侧已保存版本组")).toHaveValue("few-group");
  await page.getByLabel("用户问题", { exact: true }).fill("WHCNS模型");
  await page.getByLabel("固定输入材料", { exact: true }).fill("共同材料");
  await page.getByRole("button", { name: "添加后续问题" }).click();
  await page.getByLabel("第2轮问题", { exact: true }).fill("硝化作用是什么意思");
  await page.getByRole("button", { name: "开始左右组测评" }).click();
  await expect(page.getByRole("status")).toHaveText("对照已生成");
  await expect(page.getByLabel("左侧第1轮结果")).toContainText("无示例回答1");
  await expect(page.getByLabel("右侧第2轮结果")).toContainText("带示例回答2");
  await expect(page.getByLabel("右侧第2轮结果")).toContainText("few-shot，1 个示例");
  await expect(page.getByLabel("左侧第2轮结果")).toContainText("zero-shot");
  await expect(page.getByLabel("右侧版本组快照")).toContainText("这些任务及其示例尚未验证");
  expect(activations).toBe(0);
  await page.reload();
  await page.getByRole("tab", { name: "Prompt 组测评", exact: true }).click();
  await expect(page.getByLabel("右侧第2轮结果")).toContainText("带示例回答2");
  await page.getByRole("button", { name: "载入本次组合与输入" }).click();
  await expect(page.getByLabel("左侧已保存版本组")).toHaveValue("base");
  await expect(page.getByLabel("右侧已保存版本组")).toHaveValue("few-group");
  await expect(page.getByLabel("第2轮问题", { exact: true })).toHaveValue("硝化作用是什么意思");
  // Changing the draft must not change which saved result is activated.
  await page.getByLabel("右侧已保存版本组").selectOption("base");
  activationFails = true;
  await page.getByRole("button", { name: "将本次右侧方案设为当前方案", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "启用暂时失败" })).toBeVisible();
  expect(activeGroup.group_id).toBe("base");
  activationFails = false;
  await page.getByRole("button", { name: "将本次右侧方案设为当前方案", exact: true }).click();
  await expect(page.getByText("已启用方案「概念示例组」", { exact: false })).toBeVisible();
  expect(activeGroup.group_id).toBe("few-group");
  expect(activations).toBe(1);
  await page.getByRole("tab", { name: "方案看板" }).click();
  await expect(page.getByLabel("当前生效方案", { exact: true })).toContainText("概念示例组");
  await expect(page.getByLabel("当前生效方案", { exact: true })).toContainText("few-shot · 1 个示例");
  await expect(page.getByLabel("已保存方案 概念示例组", { exact: true }).getByRole("button", { name: "当前已生效" })).toBeDisabled();
  await page.getByLabel("搜索 Prompt 方案").fill("概念示例");
  await expect(page.getByLabel("已保存方案 基准组", { exact: true })).toHaveCount(0);
  await page.getByLabel("搜索 Prompt 方案").fill("");
  await page.getByRole("tab", { name: "Prompt 版本管理" }).click();
  await expect(page.getByLabel("任务 Prompt", { exact: true })).toContainText("当前生效：概念 few-shot");
  await page.reload();
  await expect(page.getByLabel("当前生效方案", { exact: true })).toContainText("概念示例组");
  await page.getByLabel("已保存方案 基准组", { exact: true }).getByRole("button", { name: "载入右侧测评" }).click();
  await expect(page.getByLabel("右侧已保存版本组")).toHaveValue("base");
  await page.getByRole("tab", { name: "方案看板" }).click();
  await page.getByLabel("已保存方案 基准组", { exact: true }).getByRole("button", { name: "设为当前方案", exact: true }).click();
  await expect(page.getByLabel("当前生效方案", { exact: true })).toContainText("基准组");
  expect(activations).toBe(2);
  await page.screenshot({ path: "/tmp/prompt-groups-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: "/tmp/prompt-groups-mobile.png", fullPage: true });
});
