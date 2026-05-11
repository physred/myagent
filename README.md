# myagent

基于大语言模型的 ReAct 智能助手框架，支持多模型切换、工具调用、RAG 检索增强、技能系统、会话管理和流式输出。

## 特性一览

- **多模型提供者** — 通过 `PROVIDER_TYPE` 环境变量在 OpenAI 兼容接口与 Anthropic Claude API 之间一键切换
- **ReAct 推理循环** — 思考 → 工具调用 → 观察 → 再推理，最多 10 轮自动迭代，直到得出最终回答
- **流式输出** — CLI 和 HTTP API 均支持逐 token 流式输出，自动抑制工具调用 JSON
- **工具系统** — 内置文件读写、目录管理、长期记忆、RAG 知识库检索等工具，可轻松扩展
- **技能系统** — 基于 `SKILL.md` 声明式定义高层任务规范，自动注入 system prompt
- **会话管理** — 多会话隔离持久化，超长对话自动归档摘要（Consolidator）
- **Hook 生命周期** — 事件驱动的钩子总线，覆盖请求、检索、模型调用、工具执行全流程
- **RAG 检索** — 集成外部知识库，支持 hybrid / semantic / keyword 搜索模式

## 项目结构

```
myagent/
├── agent/                     # 核心 Agent 模块
│   ├── main.py                # CLI 交互入口
│   ├── loop.py                # AgentLoop — ReAct 主循环
│   ├── hook.py                # HookBus — 事件总线
│   ├── session.py             # Session / SessionManager — 会话管理
│   ├── memory.py              # MemoryManager / Consolidator — 记忆与归档
│   ├── content.py             # ContextBuilder — 上下文构建（system prompt、历史、检索注入）
│   ├── rag_client.py          # RagClient — RAG 检索客户端
│   ├── skill.py               # Skill / SkillManager — 技能加载
│   └── tool/                  # 工具模块
│       ├── tool.py            # Tool 基类 + ToolRegistry
│       ├── filsesystem.py     # 文件系统工具（read_file / write_file / list_dir / create）
│       ├── remember.py        # 记忆工具（remember）
│       └── rag_retrieve.py    # RAG 检索工具（rag_retrieve）
├── provider/                  # 模型提供者
│   ├── base.py                # BaseModelProvider 抽象基类 + ProviderManager
│   ├── openai_provider.py     # OpenAI 兼容接口提供者
│   └── claude_provider.py     # Anthropic Claude API 提供者（响应归一化为 OpenAI 格式）
├── skill/                     # 技能定义目录（每个子目录一个 SKILL.md）
│   ├── qa-report/             # 知识问答报告生成技能
│   └── tomato-pick/           # 番茄采摘演示技能
├── utiles/
│   └── utiles.py              # JSON 括号计数器等工具函数
├── workspace/                 # 运行时工作空间
│   ├── sessions/              # 会话 JSON 持久化目录
│   ├── MEMORY.md              # 长期记忆文件
│   └── hook.log               # Hook 事件日志
├── api.py                     # FastAPI HTTP 服务入口
└── .env.example               # 环境变量模板
```

## 快速开始

### 1. 安装依赖

```bash
pip install openai anthropic fastapi uvicorn pydantic python-dotenv
```

> 仅使用 OpenAI 兼容接口时无需安装 `anthropic`；仅使用 CLI 时无需安装 `fastapi` / `uvicorn`。

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 填写模型密钥等配置
```

### 3. 启动运行

**CLI 交互模式**：

```bash
cd /data/hdd3/agent/myagent
python agent/main.py
```

**HTTP API 模式**：

```bash
cd /data/hdd3/agent/myagent
uvicorn api:app --host 0.0.0.0 --port 8001
```

## 环境变量参考

| 变量 | 说明 | 必填 |
|------|------|:----:|
| `PROVIDER_TYPE` | 提供者类型：`openai`（默认）或 `claude` | 否 |
| `OPENAI_MODEL_NAME` | OpenAI 模型名称 | OpenAI 时必填 |
| `OPENAI_API_KEY` | OpenAI API 密钥 | OpenAI 时必填 |
| `OPENAI_API_BASE` | OpenAI API 地址（兼容第三方） | 否 |
| `ANTHROPIC_MODEL_NAME` | Claude 模型名称 | Claude 时必填 |
| `ANTHROPIC_API_KEY` | Claude API 密钥 | Claude 时必填 |
| `ANTHROPIC_API_BASE` | Claude API 地址 | 否 |
| `AGENT_WORKSPACE` | 工作空间路径（存储会话与记忆） | 否 |
| `ENABLE_HOOK_LOG` | 启用 Hook 日志写入 `hook.log`（`1` 开启） | 否 |
| `RAG_API_URL` | RAG 后端检索接口 URL | 否 |
| `RAG_SEARCH_MODE` | 检索模式：`hybrid` / `semantic` / `keyword` | 否 |
| `RAG_TOP_K` | 检索召回条数（默认 `4`） | 否 |
| `RAG_MAX_CONTEXT_TOKENS` | 检索上下文最大 token 数 | 否 |

## HTTP API

服务启动后提供以下接口：

### 健康检查

```
GET /health
```

### 非流式聊天

```
POST /chat
Content-Type: application/json

{
  "query": "你好",
  "session_id": "default",
  "kb_id": null,
  "stream": false
}
```

响应：

```json
{
  "answer": "...",
  "session_id": "default",
  "reasoning": "1) RAG 检索: ...\n2) 生成最终回答",
  "tools": [{"name": "read_file", "input": "...", "output": "..."}],
  "sources": [{"chunk_id": "...", "source": "...", "score": 0.9, "text": "..."}]
}
```

### 流式聊天（SSE）

```
POST /chat/stream
Content-Type: application/json

{
  "query": "帮我写一个排序函数",
  "session_id": "default",
  "stream": true
}
```

返回 Server-Sent Events 流，事件类型包括：

- `token` — 逐 token 文本输出
- `step` — 推理步骤提示
- `tool` — 工具调用状态（executing / done）
- `retrieval_done` — RAG 检索完成
- `done` — 请求结束

## 核心模块说明

### AgentLoop（ReAct 主循环）

`agent/loop.py` 是整个框架的核心。处理流程：

1. 获取或创建会话，必要时触发 Consolidator 归档旧消息
2. 调用 RAG 检索获取相关知识片段，注入上下文
3. 进入 ReAct 循环（最多 10 轮）：
   - 调用 LLM 生成回复（支持流式/非流式）
   - 从回复中解析 `{"tool_call": {"name": "...", "arguments": {...}}}` 格式的工具调用
   - 如有工具调用，执行工具并将结果作为 Observation 追加到上下文
   - 如无工具调用，输出最终回答并结束
4. 达到迭代上限时强制要求模型直接回答

工具调用 JSON 解析采用括号深度计数 + 自动补全策略，能正确处理不完整的 JSON 输出。

### 模型提供者

通过 `ProviderManager` 统一管理。两个提供者的响应均归一化为 OpenAI ChatCompletion 格式：

- **OpenAIProvider** — 基于 `AsyncOpenAI`，支持任意 OpenAI 兼容接口
- **ClaudeProvider** — 基于 `AsyncAnthropic`，自动拆分 system 消息、归一化响应格式

### 工具系统

所有工具继承 `Tool` 基类（`agent/tool/tool.py`），通过 `ToolRegistry` 统一注册和调度：

| 工具名 | 功能 | 路径 |
|--------|------|------|
| `read_file` | 读取工作空间内文件内容 | `tool/filsesystem.py` |
| `write_file` | 向工作空间内写入文件 | `tool/filsesystem.py` |
| `list_dir` | 列出工作空间内目录内容 | `tool/filsesystem.py` |
| `create` | 在工作空间内创建文件或目录 | `tool/filsesystem.py` |
| `remember` | 追加一条笔记到长期记忆（MEMORY.md） | `tool/remember.py` |
| `rag_retrieve` | 调用 RAG 后端检索知识片段 | `tool/rag_retrieve.py` |

文件系统工具通过 `resolve_path` 限制在工作空间内，禁止路径遍历。

### 会话与记忆

- **SessionManager** — 会话以 JSON 文件持久化在 `workspace/sessions/` 下，支持多会话隔离
- **MemoryManager** — 管理长期记忆文件 `MEMORY.md` 和归档历史 `history.jsonl`
- **Consolidator** — 当会话上下文超过 token 预算时，自动将较早消息摘要归档到 `history.jsonl`，前移 `last_consolidated` 游标。支持模型摘要和轻量本地摘要两种降级策略

### Hook 系统

`HookBus`（`agent/hook.py`）提供 8 个生命周期事件：

| 事件 | 触发时机 |
|------|----------|
| `on_request_start` | 请求开始 |
| `before_retrieval` | RAG 检索前 |
| `after_retrieval` | RAG 检索后 |
| `before_model_call` | 模型调用前 |
| `after_model_call` | 模型调用后 |
| `before_tool_execute` | 工具执行前 |
| `after_tool_execute` | 工具执行后 |
| `on_request_end` | 请求结束 |

设置 `ENABLE_HOOK_LOG=1` 即可将所有事件写入 `workspace/hook.log`，格式为 `[时间戳] 事件名: payload`。

### 技能系统

技能是声明式的高层任务规范，存放在 `skill/` 目录下，每个子目录包含一个 `SKILL.md`。`SkillManager` 在启动时自动扫描并加载，将技能描述注入 system prompt。

技能不是工具，不能通过 `tool_call` 调用。它们为 Agent 提供任务执行的结构化指引。

## 扩展指南

### 添加新工具

1. 在 `agent/tool/` 下新建 `.py` 文件
2. 继承 `Tool` 基类，实现 `name`、`description`、`parameters` 属性和 `execute` 异步方法
3. 在 `agent/loop.py` 的 `AgentLoop.__init__` 中通过 `self.registry.register()` 注册

### 添加新技能

1. 在 `skill/` 下创建新目录
2. 编写 `SKILL.md`，使用 YAML front matter 定义 `name`、`description`、`always`
3. `SkillManager` 启动时自动加载，无需额外配置

### 添加新模型提供者

1. 在 `provider/` 下新建 `.py`，继承 `BaseModelProvider`
2. 实现 `call_model` 和 `call_model_stream` 方法，响应需归一化为 OpenAI ChatCompletion 格式
3. 在 `ProviderManager._PROVIDER_MAP` 中注册新类型及其环境变量前缀
4. 在 `provider/__init__.py` 中导出新类
