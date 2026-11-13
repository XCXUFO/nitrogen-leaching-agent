export type SkillAvailability = "available" | "unavailable" | "unknown";
export type SkillSummary = {
  name: string;
  alias_of?: string | null;
  title: string;
  description: string;
  registered: boolean;
  generation: "llm" | "local" | "program" | "unknown";
  availability: SkillAvailability;
  availability_note: string;
  configuration: "read_only" | "limited";
};

export type SkillDetail = SkillSummary & {
  registry_description: string;
  scenarios: string[];
  examples: string[];
  inputs: string[];
  outputs: string[];
  limitations: string[];
  dependencies: { name: string; status: SkillAvailability; message: string; required: boolean }[];
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  harness_version: string;
  runtime_config_version: string | null;
  code_sha256: string | null;
  skill_version: string | null;
  checked_at: string;
};

export const availabilityLabels: Record<SkillAvailability, string> = {
  available: "本地依赖可用",
  unavailable: "必要依赖不可用",
  unknown: "依赖待验证",
};

export const generationLabels: Record<SkillSummary["generation"], string> = {
  llm: "AI 生成", local: "本地工具", program: "程序文案", unknown: "生成方式未采集",
};
