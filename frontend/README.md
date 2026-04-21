# Frontend — 氮淋失风险决策 Agent

Next.js 16 (App Router) + TypeScript + Tailwind 4 + shadcn/ui。

## 本地启动

```bash
# 安装依赖
pnpm install

# 复制环境变量示例
cp .env.local.example .env.local

# 启动开发服务器（Turbopack）
pnpm dev
```

打开 <http://localhost:3000>，点击 "测试后端连接" 验证 `${NEXT_PUBLIC_API_BASE_URL}/api/health`。

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | 后端地址（无末尾斜杠） | `http://localhost:8000` |

## 目录结构

```
frontend/
├── src/
│   ├── app/              # 路由（App Router）
│   ├── components/ui/    # shadcn/ui 组件
│   └── lib/              # 工具函数 (cn 等)
├── public/
└── package.json
```

## shadcn/ui

- baseColor: `slate`
- icon library: `lucide`
- 添加新组件：`pnpm dlx shadcn@latest add <component>`

详细开发流程见仓库根目录的 [docs/development.md](../docs/development.md)。
