# myagent

基于大语言模型的多功能智能助手框架，支持多模型提供者切换、工具调用、技能管理、RAG 检索和会话管理。

## 特性

- 多模型提供者 — 通过环境变量在 OpenAI 兼容接口与 Anthropic Claude API 之间切换
- 工具集成 — 文件读写、目录管理、记忆存储、RAG 知识库检索
- 技能系统 — 基于目录的技能管理，通过 `SKILL.md` 定义技能规范
- 会话管理 — 多会话隔离、上下文保持、超长对话自动归档摘要
- Hook 系统 — 事件驱动的生命周期钩子，支持日志记录与监控
- RAG 检索 — 集成外部知识库检索，支持 hybrid/semantic/keyword 模式

## 项目结构

```
myagent/
├── agent/                    # 核心 Agent 模块
│   ├── main.py               # CLI 入口
│   ├── loop.py               # Agent 主循环（对话、工具调用、多轮推理）
│   ├── hook.py               # Hook 事件总线
│   ├── session.py            # 会话管理（多会话隔离、持久化）
│   ├── memory.py             # 记忆管理 + Consolidator（超长对话归档摘要）
│   ├── content.py            # 上下文构建（system prompt、历史、检索结果拼接）
│   ├── rag_client.py         # RAG 检索客户端
│   ├── skill.py              # 技能加载器
│   └── tool/                 # 工具模块
│       ├── tool.py           # 工具基类 + ToolRegistry
│       ├── filsesystem.py    # 文件系统工具（读/写/列目录/创建）
│       ├── remember.py       # 记忆工具
│       └── rag_retrieve.py   # RAG 检索工具
├── provider/                 # 模型提供者
│   ├── base.py               # BaseModelProvider 抽象基类 + ProviderManager
│   ├── openai_provider.py    # OpenAI 兼容接口提供者
│   └── claude_provider.py    # Anthropic Claude API 提供者
├── skill/                    # 技能定义目录
│   ├── qa-report/            # QA 报告生成技能
│   └── tomato-pick/          # 番茄任务选择技能
├── workspace/                # 运行时工作空间
│   ├── sessions/             # 会话 JSON 存储
│   └── MEMORY.md             # 长期记忆文件
├── api.py                    # FastAPI HTTP 服务入口
└── .env.example              # 环境变量模板
```

## 快速开始

### 1. 安装依赖

```bash
pip install openai anthropic fastapi uvicorn
```

> 仅使用 OpenAI 兼容接口时可不装 `anthropic`；仅使用 CLI 时可不装 `fastapi` / `uvicorn`。

### 2. 配置环境变量

复制模板并填写：

```bash
cp .env.example .env
```

关键字段说明：

| 变量 | 说明 | 必填 |
|------|------|------|
| `PROVIDER_TYPE` | 提供者类型：`openai`（默认）或 `claude` | 否 |
| `OPENAI_MODEL_NAME` | OpenAI 接口的模型名 | OpenAI 时必填 |
| `OPENAI_API_KEY` | OpenAI 接口密钥 | OpenAI 时必填 |
| `OPENAI_API_BASE` | OpenAI 接口地址 | 否 |
| `ANTHROPIC_MODEL_NAME` | Claude 接口的模型名 | Claude 时必填 |
| `ANTHROPIC_API_KEY` | Claude 接口密钥 | Claude 时必填 |
| `ANTHROPIC_API_BASE` | Claude 接口地址 | 否 |
| `AGENT_WORKSPACE` | 工作空间路径 | 否 |
| `ENABLE_HOOK_LOG` | 启用 Hook 日志（`1` 开启） | 否 |
| `RAG_API_URL` | RAG 后端检索接口 URL | 否 |
| `RAG_SEARCH_MODE` | 检索模式 | 否 |
| `RAG_TOP_K` | 检索召回条数 | 否 |
| `RAG_MAX_CONTEXT_TOKENS` | 检索上下文最大 token | 否 |

完整列表见 `.env.example`。

### 3. 运行

**CLI 交互模式**（从项目根目录启动）：

```bash
python -m agent.main
# 或
python agent/main.py
```

**HTTP 服务模式**：

```bash
uvicorn api:app --host 0.0.0.0 --port 8001
```

健康检查：

```bash
curl http://localhost:8001/health
```

聊天请求：

```bash
curl -X POST http://localhost:8001/chat \
   -H "Content-Type: application/json" \
   -d '{"query": "你好", "session_id": "default"}'
```

## 模型提供者

通过 `ProviderManager` 统一管理，由 `PROVIDER_TYPE` 环境变量决定使用哪个提供者。每个提供者读取自己前缀的环境变量（如 `OPENAI_*` 或 `ANTHROPIC_*`），模型名、密钥、地址各自独立配置。

两个提供者的响应格式已统一为 OpenAI ChatCompletion 格式，上层代码无需感知差异。

## 工具系统

所有工具继承 `Tool` 基类并通过 `ToolRegistry` 注册：

| 工具 | 文件 | 功能 |
|------|------|------|
| `ReadFileTool` | `tool/filsesystem.py` | 读取文件内容 |
| `WriteFileTool` | `tool/filsesystem.py` | 写入文件 |
| `ListDirTool` | `tool/filsesystem.py` | 列出目录内容 |
| `CreateTool` | `tool/filsesystem.py` | 创建文件或目录 |
| `RememberTool` | `tool/remember.py` | 写入长期记忆 |
| `RagRetrieveTool` | `tool/rag_retrieve.py` | 知识库检索 |

## Hook 系统

事件总线支持以下生命周期事件：

- `on_request_start` / `on_request_end` — 请求开始/结束
- `before_retrieval` / `after_retrieval` — RAG 检索前后
- `before_model_call` / `after_model_call` — 模型调用前后
- `before_tool_execute` / `after_tool_execute` — 工具执行前后

设置 `ENABLE_HOOK_LOG=1` 可将所有事件写入 `workspace/hook.log`。

## 开发指南

### 添加新工具

1. 在 `agent/tool/` 下新建 `.py` 文件
2. 继承 `Tool` 基类，实现 `execute` 方法
3. 在 `agent/loop.py` 的 `__init__` 中注册到 `ToolRegistry`

### 添加新技能

1. 在 `skill/` 下创建目录
2. 编写 `SKILL.md` 定义技能规范
3. `SkillManager` 会自动加载

### 添加新模型提供者

1. 在 `provider/` 下新建 `.py` 文件，继承 `BaseModelProvider`
2. 实现 `call_model` 方法，响应需归一化为 OpenAI ChatCompletion 格式
3. 在 `ProviderManager._PROVIDER_MAP` 中注册新类型及其环境变量前缀
