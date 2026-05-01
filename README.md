
# Code Analyzer MVP · 代码分析器

> **让 AI 理解你的代码库** — 自动分析 Git 仓库，提取结构化元数据，通过 MCP 协议让 Claude Code 直接搜索和理解代码。
>
> **Make your codebase AI-readable** — Automatically analyze Git repos, extract structured metadata, and let Claude Code search & understand code through MCP.

---

## 🚀 What Can You Do With It? 你能用它做什么？

### 🔍 For Claude Code Users — 给 Claude Code 用户

在你的 `~/.claude.json` 中添加一行配置，然后在任意 Claude Code 对话中直接搜索分析过的代码：

```json
{
  "mcpServers": {
    "code-analyzer": {
      "command": "node",
      "args": ["/path/to/code_analyzer_mvp/mcp-server/index.js"],
      "env": { "CODE_ANALYZER_API": "http://localhost:8000" }
    }
  }
}
```

配置完成后，Claude Code 自动获得 **12 个代码搜索工具**，使用方式如下：

#### 场景 1：找代码实现 (搜索函数)

在 Claude Code 中直接说：

> "找到这个项目里所有与 rate limiting 相关的函数"
> "search for user authentication middleware"
> "怎么实现文件上传的？找一下类似实现"

Claude 会自动调用 `ai_search` 或 `search_code` 工具，返回函数的用途、参数、返回值、副作用。

#### 场景 2：理解函数如何调用 (获取上下文)

> "解释一下第 42 号函数该怎么调用"
> "get context for function 42"
> "这个函数需要什么参数，返回什么？"

Claude 调用 `get_ai_context(42)`，得到 AI 优化的函数上下文（入参类型、返回值、副作用、调用图统计）。

#### 场景 3：重构前评估影响 (调用链分析)

> "如果我要修改 `handleLogin`，会影响哪些地方？"
> "show me the impact chain for function 42, depth 3 upstream"
> "谁调用了这个函数？它会调用谁？"

Claude 调用 `get_impact(42, 3, "upstream")`，BFS 遍历调用链，找出所有受影响的上游/下游函数。

#### 场景 4：理解跨文件功能 (分组搜索)

> "权限验证在整个项目里是怎么实现的？按文件分组显示"
> "show me all database queries grouped by file"
> "这个项目的 crawler pipeline 是什么结构？"

Claude 调用 `search_grouped({query: "crawler pipeline", group_by: "file"})`，按文件分组展示所有相关函数，帮助理解多文件实现的完整流程。

#### 场景 5：快速参考 (获取代码片段)

> "给我一个使用 JWT 做 API 认证的例子"
> "show me example of file upload handling"
> "数据库查询的 pattern 是什么？"

Claude 调用 `get_reference({query: "JWT authentication"})`，返回紧凑的代码参考，快速给出可用模式。

### 💻 For Terminal Users — 给终端用户

```bash
# 搜索代码
./ca.sh "rate limiting middleware" typescript 5

# 函数详情
./ca.sh detail 42

# 调用上下文
./ca.sh context 42

# 影响链分析
./ca.sh impact 42 3 upstream
```

### 🌐 For API Users — 给 API 用户

```bash
# 提交分析任务
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/user/repo.git"}'

# AI 优化搜索 (返回 purpose/inputs/outputs/side_effects)
curl "http://localhost:8000/api/ai/search?q=authentication&limit=5"

# 通用搜索 (返回详细解释和代码片段)
curl "http://localhost:8000/api/search?q=rate+limiting&language=typescript"

# 函数上下文
curl http://localhost:8000/api/ai/functions/42/context

# 影响链
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=upstream"
```

---

## 🎯 Why This Matters for AI 为什么对AI至关重要

### Before Code Analyzer 没有它的时候

| 问题 | 后果 |
|------|------|
| AI 每次都要从头读代码 | 浪费 token，回答慢 |
| 没有函数间的结构关系 | AI 不理解调用链影响 |
| 没有结构化元数据 | AI 只能猜测函数用途 |
| 跨会话不持久 | 每次重新分析 |

### After Code Analyzer 有了它之后

| 能力 | 效果 |
|------|------|
| 一次分析，永久查询 | 结构化元数据持久化在 PostgreSQL 中 |
| 函数级 AI 元数据 | `purpose` / `inputs` / `outputs` / `side_effects` |
| 调用图感知 | BFS 遍历上下游影响链 |
| MCP 原生集成 | Claude Code 直接调用 12 个搜索工具 |
| 断点续传 | 分析任务崩溃后可恢复，不丢失进度 |

---

## 🏗 Architecture 架构

```
┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐
│  Frontend │────▶│   API    │────▶│  Worker   │────▶│ Postgres │
│ (React)   │◀────│ (FastAPI)│◀────│ (Celery)  │◀────│   + Redis │
└──────────┘     └────┬─────┘     └─────┬─────┘     └──────────┘
                      │                  │
                      ▼                  ▼
               ┌──────────────┐  ┌──────────────┐
               │  MCP Server  │  │  LLM (DeepSeek)│
               │  (Node.js)   │  │  / OpenAI     │
               └──────────────┘  └──────────────┘
```

### Analysis Pipeline 分析管线

```
Git URL ──▶ 1. Clone ──▶ 2. Parse ──▶ 3. Extract ──▶ 4. LLM Generate ──▶ 5. Save to DB
            GitPython    AST/Regex     Relationships    (mode-dependent)   (checkpointed)
```

---

## 🚀 Quick Start 快速开始

### 前置条件

- Docker & Docker Compose
- LLM API Key (DeepSeek Chat 免费注册 / OpenAI / 兼容接口)

### 一键启动

```bash
# 1. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 2. 启动所有服务
docker compose up -d

# 3. 验证服务
curl http://localhost:8000/health
# → {"status":"ok","service":"code-analyzer-api"}

# 4. 分析第一个项目
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/opendataloader-project/opendataloader-pdf.git"}'
# → {"task_id": "abc123..."}

# 5. 查看进度
curl http://localhost:8000/api/analyze/abc123.../status

# 6. 分析完成后，在 Claude Code 中搜索
# 见上方 "For Claude Code Users" 部分
```

### 批量分析多个项目

```bash
# 批量提交
for repo in \
  "https://github.com/user/repo1.git" \
  "https://github.com/user/repo2.git"; do
  curl -s -X POST http://localhost:8000/api/analyze \
    -H "Content-Type: application/json" \
    -d "{\"repo_url\": \"$repo\"}"
  sleep 0.8
done

# 查看所有已分析项目
curl http://localhost:8000/api/projects
```

---

## 🔌 MCP Tools Reference MCP工具完整参考

注册 MCP 服务器后，Claude Code 自动拥有以下工具。你不需要手动调用——Claude 会根据你的问题自动选择合适的工具。

### AI 优化工具（默认推荐）

| 工具 | 用途 | 输入 | 输出 |
|------|------|------|------|
| `ai_search` | 按任务描述搜索函数 | `query`, `limit(可选)`, `language(可选)` | AI 结构化元数据 |
| `get_ai_context` | 获取函数调用上下文 | `function_id` | 用途、入参、返回值、副作用 |
| `get_ai_neighborhood` | 获取函数+调用图邻居 | `function_id`, `depth(可选)` | 图结构（节点+边） |

### 通用搜索工具

| 工具 | 用途 | 输入 |
|------|------|------|
| `search_code` | 通用代码搜索（含代码片段） | `query`, `language(可选)`, `limit(可选)` |
| `get_reference` | 紧凑代码参考 | `query`, `limit(可选)` |
| `search_grouped` | 按文件/项目分组搜索 | `query`, `group_by`, `language(可选)` |
| `search_classes` | 搜索类定义 | `query`, `language(可选)` |

### 函数分析工具

| 工具 | 用途 | 输入 |
|------|------|------|
| `get_function_detail` | 函数完整详情 | `function_id` |
| `get_context` | 调用者+被调用者 | `function_id` |
| `get_impact` | BFS 影响链分析 | `function_id`, `depth(可选)`, `direction(可选)` |
| `get_file_functions` | 获取文件内所有函数 | `file_id` 或 `project_id`+`file_path` |
| `get_project_stats` | 项目统计概览 | 无参数 |

### 典型的 Claude Code 工作流

```
你: "找到用户认证相关的函数"
  → Claude 调用 ai_search({query: "user authentication"})
  → 返回结果列表

你: "解释一下 42 号函数怎么调用"
  → Claude 调用 get_ai_context({function_id: 42})
  → 返回入参类型、返回值、副作用

你: "如果修改这个函数会影响谁？"
  → Claude 调用 get_impact({function_id: 42, depth: 3, direction: "upstream"})
  → 返回所有受影响的调用链
```

---

## 🎨 Three Analysis Modes 三种分析模式

同一份代码，三种视角。

| 模式 | 适用对象 | 生成内容 |
|------|---------|---------|
| `ai` (默认) | AI 代理 / MCP 工具 | 结构化元数据: `purpose`, `inputs`, `outputs`, `side_effects` |
| `beginner` | 编程初学者 | 通俗解释: `explanation_simple`, `explanation_logic` |
| `expert` | 有经验的开发者 | 技术分析: `tech_details`, `error_handling`, `concurrency`, `tradeoffs` |

```bash
# 切换模式
curl -X PUT http://localhost:8000/api/projects/{id}/mode?mode=expert

# 切换并完整重新分析
curl -X PUT "http://localhost:8000/api/projects/{id}/mode?mode=beginner&full_reanalysis=true"
```

---

## 🏗 Project Structure 项目结构

```
code_analyzer_mvp/
├── api/                     # FastAPI 后端
│   ├── main.py             # 应用入口、路由注册
│   ├── ai.py               # AI 优化搜索和函数上下文 API
│   ├── analyze.py          # 分析任务提交和状态查询
│   ├── tasks.py            # Celery 异步分析任务
│   ├── llm_service.py      # LLM 调用和提示词管理（三模式）
│   ├── crud.py             # 数据库 CRUD 操作
│   ├── search_service.py   # PostgreSQL 全文搜索
│   ├── models.py           # SQLAlchemy ORM 模型
│   ├── reanalyze.py        # 批量重新分析和模式切换
│   ├── relations.py        # 函数调用关系图
│   ├── config.py           # 全局配置
│   └── parsers/            # 代码解析器
│       ├── python_parser.py   # Python AST 解析
│       └── generic_parser.py  # 通用正则解析（JS/TS/Go/Java/Rust）
├── mcp-server/             # MCP 协议服务器
│   └── index.js            # 12 个 MCP 工具暴露为 Claude Code 可调用
├── frontend/               # React 前端界面
├── tests/                  # 测试套件
│   ├── conftest.py         # 测试 fixtures
│   └── test_three_mode.py  # 三模式集成测试（24 个）
├── ca.sh                   # 终端搜索 CLI
├── docker-compose.yml      # 容器编排
└── .env.example            # 环境变量模板
```

---

## 📖 Full API Reference 完整 API 参考

### 分析管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze` | 提交代码分析任务 |
| `GET` | `/api/analyze/{id}/status` | 查询分析任务状态 |
| `GET` | `/api/tasks/checkpoint` | 获取任务检查点 |
| `POST` | `/api/tasks/{id}/resume` | 恢复中断的任务 |
| `GET` | `/api/tasks/unfinished` | 获取所有未完成任务 |

### 项目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/projects` | 列出所有项目 |
| `GET` | `/api/projects/{id}/files` | 获取项目文件、函数、类 |
| `PUT` | `/api/projects/{id}/mode` | 切换项目分析模式 |
| `POST` | `/api/projects/{id}/switch-mode` | 切换模式并启动后台填充 |
| `POST` | `/api/projects/{id}/fill-mode-content` | 填充当前模式缺失内容 |
| `POST` | `/api/reanalyze/batch-migrate-mode` | 批量迁移所有项目模式 |
| `POST` | `/api/reanalyze/regenerate-overview/{id}` | 重新生成项目概览 |

### AI 优化搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/ai/search?q=...` | AI 优化搜索（紧凑结构化结果） |
| `GET` | `/api/ai/functions/{id}/context` | AI 函数上下文 |
| `GET` | `/api/ai/functions/{id}/neighborhood` | 函数调用图邻域 |

### 通用搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/search?q=...` | 通用搜索（详细解释+代码片段） |
| `GET` | `/api/reference?q=...` | 引用搜索（紧凑结果） |
| `GET` | `/api/classes/search?q=...` | 类搜索 |

### 函数分析

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/functions/{id}/detail` | 函数完整详情 |
| `GET` | `/api/functions/{id}/context` | 调用上下文（调用者+被调用者） |
| `GET` | `/api/functions/{id}/impact` | BFS 影响链分析 |

---

## 🌐 Supported Languages 支持的语言

| 语言 | 解析方式 | 支持程度 |
|------|---------|---------|
| Python | AST 解析 | 完整支持（精确的函数/类/参数识别） |
| JavaScript / JSX / TSX | 正则解析 | 支持 |
| TypeScript | 正则解析 | 支持 |
| Go | 正则解析 | 支持 |
| Java | 正则解析 | 支持 |
| Rust | 正则解析 | 支持 |
| 其他语言 | 通用正则 | 有限支持 |

---

## ⚙️ Tech Stack 技术栈

| 组件 | 技术 |
|------|------|
| API 框架 | FastAPI (Python 3.10) |
| 异步任务 | Celery + Redis (broker/backend) |
| 数据库 | PostgreSQL 15 |
| LLM | DeepSeek Chat (默认) / OpenAI 兼容接口 |
| 代码解析 | Python AST (Python) + 正则 (其他语言) |
| 前端 | React 18 + lucide-react |
| MCP 协议 | Node.js MCP Server (stdio) |
| 容器化 | Docker Compose |
| ORM | SQLAlchemy 2.0 |

---

## 🔧 Environment Variables 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql://code_analyzer:password@postgres:5432/code_analyzer_db` |
| `REDIS_URL` | Redis 连接串 | `redis://redis:6379/0` |
| `LLM_API_KEY` | LLM API 密钥 | **必填** |
| `LLM_MODEL` | LLM 模型名 | `deepseek-chat` |
| `LLM_BASE_URL` | LLM API 地址 | `https://api.deepseek.com` |
| `API_KEYS` | 项目 API 密钥 JSON | `{"mvp_key": "default_project"}` |
| `TEMP_DIR` | 临时目录 | `/tmp/code_analysis` |

---

## 🧪 Testing 测试

```bash
# 运行所有测试
docker compose exec api pytest tests/ -v

# 三模式测试
docker compose exec api pytest tests/test_three_mode.py -v

# 指定函数测试
docker compose exec api pytest tests/test_three_mode.py::TestProjectMode -v
```

---

## 📄 License

MIT

---

> Built for the AI era — where understanding code at scale is no longer a human-only job.
>
> 为 AI 时代而生——大规模理解代码不再只是人类的工作。
