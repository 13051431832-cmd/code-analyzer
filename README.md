
# Code Analyzer MVP · 代码分析器

> **Multi-language code analysis system** with LLM-powered structured metadata extraction, MCP protocol integration, and AI-optimized search.
>
> **多语言代码分析系统**，集成 LLM 结构化元数据提取、MCP 协议接口和 AI 优化搜索。

<p align="center">
  <a href="#-overview-概览">Overview</a> •
  <a href="#-why-code-analyzer-for-ai-为什么对ai尤为重要">Why AI?</a> •
  <a href="#-quick-start-快速开始">Quick Start</a> •
  <a href="#-architecture-架构">Architecture</a> •
  <a href="#-mcp-integration-mcp集成">MCP</a> •
  <a href="#-three-analysis-modes-三种分析模式">Modes</a> •
  <a href="#-api-reference-api参考">API</a>
</p>

---

## 📋 Overview 概览

Code Analyzer automatically clones Git repositories, parses function/class structures across multiple languages, generates structured metadata via LLM, and exposes everything through AI-optimized search APIs and the Model Context Protocol (MCP).

代码分析器自动克隆 Git 仓库，跨语言解析函数/类结构，通过 LLM 生成结构化元数据，并通过 AI 优化搜索 API 和 MCP 协议暴露所有分析结果。

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

### Tech Stack 技术栈

| Component 组件 | Technology 技术 |
|---|---|
| API Framework | FastAPI (Python 3.10) |
| Async Tasks | Celery + Redis |
| Database | PostgreSQL 15 |
| LLM | DeepSeek Chat (default) / OpenAI-compatible |
| Code Parsing | Python AST + regex multi-language |
| Frontend | React 18 |
| MCP Protocol | Node.js stdio server |
| ORM | SQLAlchemy 2.0 |
| Containerization | Docker Compose |

---

## 🎯 Why Code Analyzer for AI? 为什么对AI尤为重要

### The Problem 问题

When an AI assistant (like Claude, ChatGPT) encounters a codebase, it can only see what's in its context window. Reading entire repositories is slow, expensive, and often misses the structural relationships between functions. Without structured metadata, the AI has to re-analyze code from scratch every time.

当 AI 助手遇到一个代码库时，它只能看到上下文窗口中的内容。阅读整个仓库既慢又昂贵，而且常常错过函数间的结构关系。没有结构化元数据，AI 每次都必须从头开始分析代码。

### The Solution 解决方案

Code Analyzer pre-processes codebases and extracts **AI-consumable structured metadata** so the AI never has to read raw code again to understand what something does.

代码分析器预处理代码库并提取 **AI 可直接消费的结构化元数据**，使 AI 无需再阅读原始代码就能理解功能。

| Without Code Analyzer | With Code Analyzer |
|---|---|
| Read 100+ files raw | Ask 1 query → get structured result |
| Guess call relationships | Get explicit call graph |
| Re-analyze every session | Pre-computed metadata persists |
| No function-level context | Full AI-oriented context per function |

### Key AI Advantages 对AI的核心优势

1. **AI-Optimized Search (`/api/ai/search`)** — Returns compact results with `purpose`, `inputs`, `outputs`, `side_effects` fields designed specifically for AI consumption. No noise, no irrelevant code.

2. **Call Graph Awareness** — BFS traversal of upstream (affected by) and downstream (depends on) function chains. AI understands impact without reading every file.

3. **Three-Tier Analysis** — Same code, different audiences: `ai` mode (structured metadata for MCP/agents), `beginner` mode (plain explanations for learners), `expert` mode (deep technical analysis for developers).

4. **MCP Native Integration** — Exposes all analysis as MCP tools. Claude Code (and any MCP client) can call `ai_search`, `get_ai_context`, `get_impact` directly without HTTP gymnastics.

5. **Resumable Batch Analysis** — Analysis tasks survive worker restarts. Scan 50+ repos overnight — checkpoints ensure no work is lost.

6. **Language-Agnostic** — Python AST (deep parsing) + regex (JavaScript, TypeScript, Go, Java, Rust, and more). One analysis pipeline, many languages.

---

## 🚀 Quick Start 快速开始

### Prerequisites 前置条件

- Docker & Docker Compose
- LLM API Key (DeepSeek / OpenAI / compatible)

### Setup 部署

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env: set LLM_API_KEY

# 2. Start all services
docker compose up -d

# 3. Verify
curl http://localhost:8000/health
# → {"status":"ok","service":"code-analyzer-api"}
```

### Analyze Your First Repository 分析第一个仓库

```bash
# Submit analysis task
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/user/repo.git"}'
# → {"task_id": "..."}

# Check status
curl http://localhost:8000/api/analyze/{task_id}/status

# List all projects
curl http://localhost:8000/api/projects

# AI-optimized search
curl "http://localhost:8000/api/ai/search?q=authentication&limit=5"
```

---

## 🏗 Architecture 架构

```
code_analyzer_mvp/
├── api/                     # FastAPI backend
│   ├── main.py             # App entry, routes
│   ├── ai.py               # AI-optimized search & context
│   ├── analyze.py          # Analysis task submission
│   ├── tasks.py            # Celery async tasks
│   ├── llm_service.py      # LLM invocation & prompts
│   ├── crud.py             # Database CRUD
│   ├── search_service.py   # Full-text search
│   ├── models.py           # SQLAlchemy models
│   ├── schemas.py          # Pydantic schemas
│   ├── config.py           # Global configuration
│   ├── celery_app.py       # Celery app config
│   ├── database.py         # SQLAlchemy engine/session
│   ├── projects.py         # Project management
│   ├── functions.py        # Function details
│   ├── classes.py          # Class details
│   ├── files.py            # File-function associations
│   ├── relations.py        # Call graph API
│   ├── reanalyze.py        # Batch reanalysis
│   └── parsers/            # Code parsers
│       ├── python_parser.py   # Python AST parser
│       └── generic_parser.py  # Regex multi-language
├── mcp-server/             # MCP protocol server
│   └── index.js            # Exposes API as MCP tools
├── frontend/               # React UI
├── tests/                  # Test suite
│   ├── conftest.py
│   └── test_three_mode.py  # 24 integration tests
├── worker/                 # Celery worker config
├── ca.sh                   # CLI search tool
└── docker-compose.yml      # Container orchestration
```

### Analysis Pipeline 分析管线

```
Repository URL
    │
    ▼
┌─────────────┐     ┌──────────────┐     ┌────────────────┐
│ 1. Clone    │────▶│ 2. Parse     │────▶│ 3. Extract     │
│ (GitPython) │     │ (AST/Regex)  │     │ Relationships  │
└─────────────┘     └──────────────┘     └───────┬────────┘
                                                  │
                    ┌─────────────────────────────┘
                    ▼
         ┌──────────────────┐     ┌─────────────────┐
         │ 4. LLM Generate  │────▶│ 5. Save to DB   │
         │ (mode-dependent) │     │ (checkpointed)  │
         └──────────────────┘     └─────────────────┘
```

---

## 🔌 MCP Integration MCP集成

### Register the MCP Server 注册MCP服务器

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "code-analyzer": {
      "command": "node",
      "args": ["/path/to/code_analyzer_mvp/mcp-server/index.js"],
      "env": {
        "CODE_ANALYZER_API": "http://localhost:8000"
      }
    }
  }
}
```

### Available MCP Tools 可用工具

| Tool 工具 | What It Does 功能 | AI Value 对AI的价值 |
|---|---|---|
| `ai_search` | AI-optimized code search | Find relevant code without reading raw files |
| `search_code` | General code search | Detailed code snippets + explanations |
| `get_ai_context` | Function context for AI consumption | Understand how to use a function correctly |
| `get_ai_neighborhood` | Function + call graph neighbors | Refactor safely — see impact before changing |
| `get_impact` | BFS call chain traversal | Upstream/downstream dependency analysis |
| `get_function_detail` | Full function detail | Deep dive into any function |
| `search_grouped` | Search grouped by file/project | Browse organizational structure |
| `get_project_stats` | Aggregate project statistics | Overview of analyzed codebase health |

---

## 🎨 Three Analysis Modes 三种分析模式

Each project can be analyzed in three modes — the same code, different audiences.

每个项目可设置三种分析模式——同一份代码，不同受众。

| Mode 模式 | Audience 受众 | Content 生成内容 |
|---|---|---|
| `ai` (default) | AI agents, MCP tools | `purpose`, `inputs` (JSONB), `outputs` (JSONB), `side_effects` (JSONB) |
| `beginner` | Programming learners | `explanation_simple`, `explanation_logic` |
| `expert` | Experienced developers | `tech_details`, `error_handling`, `concurrency`, `tradeoffs` |

```bash
# Switch mode 切换模式
curl -X PUT http://localhost:8000/api/projects/{id}/mode?mode=expert

# Switch and fully reanalyze 切换并完整重新分析
curl -X PUT "http://localhost:8000/api/projects/{id}/mode?mode=beginner&full_reanalysis=true"
```

**Key design 设计原则:**
- AI metadata is always generated (MCP depends on it)
- Mode switching preserves existing content
- Checkpoint-based progress survives restarts

---

## 📖 API Reference API参考

### Core 核心

| Method | Path | Description 说明 |
|---|---|---|
| `POST` | `/api/analyze` | Submit analysis task 提交分析任务 |
| `GET` | `/api/analyze/{id}/status` | Query task status 查询任务状态 |
| `GET` | `/api/projects` | List all projects 列出所有项目 |
| `GET` | `/api/projects/{id}/files` | Project files & functions 项目文件与函数 |

### AI-Optimized (MCP targets) AI优化

| Method | Path | Description 说明 |
|---|---|---|
| `GET` | `/api/ai/search?q=...` | AI-optimized search AI优化搜索 |
| `GET` | `/api/ai/functions/{id}/context` | AI function context AI函数上下文 |
| `GET` | `/api/ai/functions/{id}/neighborhood` | Call graph neighborhood 调用图邻域 |

### Search 搜索

| Method | Path | Description 说明 |
|---|---|---|
| `GET` | `/api/search?q=...` | General search 通用搜索 |
| `GET` | `/api/reference?q=...` | Compact reference search 引用搜索 |
| `GET` | `/api/classes/search?q=...` | Class search 类搜索 |

### Mode Management 模式管理

| Method | Path | Description 说明 |
|---|---|---|
| `PUT` | `/api/projects/{id}/mode` | Switch analysis mode 切换分析模式 |
| `POST` | `/api/reanalyze/batch-migrate-mode` | Batch mode migration 批量迁移模式 |

### Resume & Checkpoint 断点续传

| Method | Path | Description 说明 |
|---|---|---|
| `GET` | `/api/tasks/{id}/checkpoint` | Get task checkpoint 获取检查点 |
| `POST` | `/api/tasks/{id}/resume` | Resume interrupted task 恢复中断任务 |
| `GET` | `/api/tasks/unfinished` | List unfinished tasks 列出未完成任务 |

---

## 💻 CLI Tool CLI工具

```bash
# Search code 搜索代码
./ca.sh "rate limiting middleware" typescript 5

# Function details 函数详情
./ca.sh detail 42

# Function context 函数上下文
./ca.sh context 42

# Impact chain 影响链
./ca.sh impact 42 3 upstream
```

---

## 🧪 Testing 测试

```bash
# All tests
docker compose exec api pytest tests/ -v

# Mode tests
docker compose exec api pytest tests/test_three_mode.py -v
```

---

## 🌐 Supported Languages 支持的语言

| Language 语言 | Parser 解析器 | Status 状态 |
|---|---|---|
| Python | AST | Full support 完整支持 |
| JavaScript / JSX / TSX | Regex | Supported 支持 |
| TypeScript | Regex | Supported 支持 |
| Go | Regex | Supported 支持 |
| Java | Regex | Supported 支持 |
| Rust | Regex | Supported 支持 |
| Others | Generic regex | Limited 有限支持 |

---

## ⚙️ Environment Variables 环境变量

| Variable 变量 | Description 说明 | Default 默认值 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://code_analyzer:password@postgres:5432/code_analyzer_db` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` |
| `LLM_API_KEY` | LLM API key | Required 必填 |
| `LLM_MODEL` | LLM model name | `deepseek-chat` |
| `LLM_BASE_URL` | LLM API endpoint | `https://api.deepseek.com` |
| `API_KEYS` | Project API keys JSON | `{"mvp_key": "default_project"}` |
| `TEMP_DIR` | Temp directory | `/tmp/code_analysis` |
| `SEARCH_DEFAULT_LIMIT` | Default search limit | `20` |
| `SEARCH_MAX_LIMIT` | Max search limit | `100` |

---

## 🔬 Internal Schema 数据库结构

```
projects               files                  functions
├── id                 ├── id                  ├── id
├── name               ├── project_id (FK)     ├── file_id (FK)
├── repo_url           ├── file_path           ├── name
├── language           ├── file_hash           ├── signature
├── analysis_mode      ├── language            ├── code_snippet
│   (ai/beginner/      └── dependencies        ├── ai_purpose
│    expert)               (JSONB)             ├── ai_inputs (JSONB)
├── overview_analysis                         ├── ai_outputs (JSONB)
└── last_analyzed_commit                      ├── ai_side_effects (JSONB)
                                              ├── explanation_simple
classes                function_relationships ├── explanation_logic
├── id                 ├── id                  ├── expert_purpose
├── file_id (FK)       ├── source_fn_id (FK)  ├── expert_tech_details
├── name               ├── target_fn_name      ├── expert_error_handling
├── code_snippet       ├── relationship_type   ├── expert_concurrency
├── ai_purpose         │   (CALLS/IMPLEMENTS  ├── expert_tradeoffs
├── ai_interfaces      │    /EXTENDS)          └── related_functions
├── explanation_simple └── confidence               (JSONB)
└── expert_responsibilities
```

---

## 📄 License 许可证

MIT

---

> Built for the AI era — where understanding code at scale is no longer a human-only job.
>
> 为 AI 时代而生——大规模理解代码不再只是人类的工作。
