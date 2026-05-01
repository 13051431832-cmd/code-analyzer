
# Code Analyzer MVP · 代码分析器

> **让 AI 理解你的代码库** — 自动分析 Git 仓库，提取结构化元数据，通过 MCP 协议让 Claude Code 直接搜索和理解代码。
>
> **Make your codebase AI-readable** — Automatically analyze Git repos, extract structured metadata, and let Claude Code search & understand code through MCP.

---

## 📋 Table of Contents 目录

- [🎯 Claude Code Integration Claude Code集成](#-claude-code-integration-claude-code集成)
- [💻 Terminal CLI 终端命令行](#-terminal-cli-终端命令行)
- [🌐 Web API 接口](#-web-api-接口)
- [🖥️ Frontend UI 前端界面](#️-frontend-ui-前端界面)
- [🎨 Three Analysis Modes 三种分析模式](#-three-analysis-modes-三种分析模式)
- [📦 Batch Analysis 批量分析](#-batch-analysis-批量分析)
- [🔌 Offline Mode 离线模式](#-offline-mode-离线模式)
- [🔬 Code Parsing 代码解析](#-code-parsing-代码解析)
- [🔍 Search System 搜索系统](#-search-system-搜索系统)
- [📊 Relationship Graph 调用关系图](#-relationship-graph-调用关系图)
- [🚀 Quick Start 快速开始](#-quick-start-快速开始)
- [🏗 Architecture 架构](#-architecture-架构)
- [📖 API Reference API参考](#-api-reference-api参考)
- [⚙️ Configuration 配置](#️-configuration-配置)
- [🧪 Testing 测试](#-testing-测试)
- [📄 License 许可证](#-license-许可证)

---

## 🎯 Claude Code Integration Claude Code集成

注册 MCP 服务器后，在任意 Claude Code 对话中直接搜索分析过的代码：

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

配置完成后，Claude Code 自动获得 **14 个代码搜索工具**：

### 搜索工具

| 工具 | 你在 Claude 中这样说 | 返回结果 |
|------|---------------------|---------|
| `ai_search` | "找到所有 rate limiting 相关函数" | 结构化元数据: purpose / inputs / outputs / side_effects |
| `search_code` | "搜索 authentication 的实现" | 代码片段 + 详细解释 + 调用图统计 |
| `search_classes` | "找到数据模型的类定义" | 类定义 + AI 解释 |
| `search_grouped` | "按文件显示所有数据库查询" | 按文件/项目分组，理解跨文件实现 |
| `get_reference` | "给个 JWT 认证的代码参考" | 紧凑的代码片段 |

### 函数分析工具

| 工具 | 你在 Claude 中这样说 | 返回结果 |
|------|---------------------|---------|
| `get_ai_context` | "42 号函数怎么调用？" | 用途、入参类型、返回值、副作用 |
| `get_function_detail` | "查看 42 号函数完整信息" | 函数全貌：文件路径、项目名、相关函数 |
| `get_context` | "谁调用了 42？它调用了谁？" | 调用者列表 + 被调用者列表 + 代码预览 |
| `get_ai_neighborhood` | "42 号函数在调用图中的位置" | 图结构：节点（签名/用途）+ 边 |
| `get_impact` | "修改 42 会影响哪些地方？" | BFS 遍历上下游影响链 |
| `get_file_functions` | "查看 app.py 里所有函数" | 文件内所有函数 + 签名 + 解释 |
| `get_project_stats` | "这个数据库里有多少项目？" | 项目统计：文件数、函数数、覆盖率 |

### 典型工作流

```
你: "找到用户认证相关的函数"
  → Claude 调用 ai_search({query: "user authentication"})
  → 返回 10 个匹配函数的元数据

你: "解释一下 42 号函数怎么调用"
  → Claude 调用 get_ai_context({function_id: 42})
  → 返回入参类型、返回值、副作用、调用图统计

你: "如果修改这个函数会影响谁？"
  → Claude 调用 get_impact({function_id: 42, depth: 3, direction: "upstream"})
  → 返回所有上游调用链（谁在用它）

你: "重构前先看看这个函数怎么融入项目"
  → Claude 调用 get_ai_neighborhood({function_id: 42, depth: 1})
  → 返回函数 + 直接调用邻居
```

---

## 💻 Terminal CLI 终端命令行

无需启动浏览器，直接在终端中搜索和分析代码：

```bash
# 搜索函数实现
./ca.sh "rate limiting middleware" typescript 5

# 函数详情
./ca.sh detail 42

# 调用上下文（调用者 + 被调用者）
./ca.sh context 42

# 影响链分析（BFS 遍历）
./ca.sh impact 42 3 upstream
```

CLI 支持的操作：

| 命令 | 说明 | 示例 |
|------|------|------|
| `search <query> [lang] [limit]` | 搜索函数实现 | `./ca.sh "rate limit" go 10` |
| `detail <id>` | 函数完整详情 | `./ca.sh detail 42` |
| `context <id>` | 调用上下文 | `./ca.sh context 42` |
| `impact <id> [depth] [dir]` | 影响链分析 | `./ca.sh impact 42 3 upstream` |

---

## 🌐 Web API 接口

所有功能通过 REST API 暴露，支持任何 HTTP 客户端：

```bash
# 提交分析任务
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/user/repo.git"}'
# → {"task_id": "abc123...", "status": "pending"}

# 查询任务状态（含进度百分比和当前步骤）
curl http://localhost:8000/api/analyze/abc123.../status
# → {"status": "processing", "progress": 45, "current_step": "Parsing files"}

# 列出所有已分析项目
curl http://localhost:8000/api/projects
# → [{"id": 1, "name": "my-project", "language": "python", "analysis_mode": "ai", ...}]

# AI 优化搜索（返回结构化元数据，专为 AI 消费优化）
curl "http://localhost:8000/api/ai/search?q=authentication&limit=5"
# → {"results": [{"name": "authenticate", "ai": {"purpose": "...", "inputs": [...], ...}, ...}]}

# 通用搜索（返回详细解释和代码片段）
curl "http://localhost:8000/api/search?q=rate+limiting&language=typescript"

# 函数上下文
curl http://localhost:8000/api/ai/functions/42/context

# 影响链分析
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=upstream"

# 按文件分组搜索（理解跨文件实现）
curl "http://localhost:8000/api/search?q=crawler+pipeline&group_by=file"

# 项目统计概览
curl http://localhost:8000/api/projects/stats
```

---

## 🖥️ Frontend UI 前端界面

React 前端提供图形化浏览界面，适合人类阅读分析结果：

```
frontend/
├── public/index.html
└── src/
    ├── App.js              # 应用入口
    ├── index.js            # 渲染入口
    └── CodeLearningView.jsx  # 主界面：模式切换、代码展示、解释查看
```

启动后访问 `http://localhost:3000`，支持：
- 项目列表浏览
- 函数/类结构展示
- 代码片段 + AI 解释对照查看
- 三种分析模式切换查看

---

## 🎨 Three Analysis Modes 三种分析模式

同一份代码，三种视角。这是 Code Analyzer 的核心差异化功能。

| 模式 | 适用对象 | 生成内容 |
|------|---------|---------|
| `ai` **(默认)** | AI 代理、MCP 工具 | `purpose`, `inputs`(JSONB), `outputs`(JSONB), `side_effects`(JSONB) |
| `beginner` | 编程初学者 | `explanation_simple`(通俗解释), `explanation_logic`(逻辑说明) |
| `expert` | 有经验的开发者 | `tech_details`, `error_handling`, `concurrency`, `tradeoffs` |

### 模式切换

```bash
# 切换为专家模式
curl -X PUT http://localhost:8000/api/projects/1/mode?mode=expert

# 切换模式并完整重新分析（重新调用 LLM 生成）
curl -X PUT "http://localhost:8000/api/projects/1/mode?mode=beginner&full_reanalysis=true"

# 批量迁移所有项目到同一模式
curl -X POST http://localhost:8000/api/reanalyze/batch-migrate-mode \
  -H "Content-Type: application/json" \
  -d '{"target_mode": "expert"}'
```

### 设计原则

| 原则 | 说明 |
|------|------|
| AI 元数据始终生成 | MCP 工具依赖 `ai_` 字段，即使切换模式也不会丢失 |
| 模式切换保留已有内容 | 切换到新模式时，旧模式的内容不会被覆盖 |
| 可增量填充 | 使用 `fill-mode-content` 仅为缺失模式填充，无需重头开始 |
| 断点续传 | LLM 批处理过程中断可从检查点恢复 |

### 模式内容示例

**ai 模式**（一个函数的元数据）:
```json
{
  "ai_purpose": "验证用户 JWT token 并返回用户信息",
  "ai_inputs": [{"name": "token", "type": "str", "desc": "JWT token from Authorization header"}],
  "ai_outputs": [{"name": "user", "type": "dict", "desc": "用户信息包含 id, email, role"}],
  "ai_side_effects": ["读取 Redis 缓存", "写入审计日志"]
}
```

**beginner 模式**:
```json
{
  "explanation_simple": "这个函数检查用户的登录凭证是否有效。你给它一个密码，它去数据库查一下对不对，对了就让你登录，不对就拒绝。",
  "explanation_logic": "接收用户名和密码 → 从数据库查找用户 → 用 bcrypt 验证密码哈希 → 生成 session → 返回结果"
}
```

**expert 模式**:
```json
{
  "expert_purpose": "OAuth2 密码流认证，支持多因子认证回退",
  "expert_tech_details": "使用 passlib 的 bcrypt 进行密码哈希验证，通过 SQLAlchemy async session 查询用户记录",
  "expert_error_handling": "UserNotFound -> 404, PasswordMismatch -> 401, AccountLocked -> 423",
  "expert_concurrency": "每个请求独立 session，无共享状态，天然线程安全",
  "expert_tradeoffs": "使用 bcrypt 成本因子 12：安全性高但每次验证约 250ms"
}
```

---

## 📦 Batch Analysis 批量分析

支持大规模批量分析，设计目标是一次性扫描数十个仓库。

```bash
# 批量提交 51 个仓库
for repo in \
  "https://github.com/user/repo1.git" \
  "https://github.com/user/repo2.git"; do
  curl -s -X POST http://localhost:8000/api/analyze \
    -H "Content-Type: application/json" \
    -d "{\"repo_url\": \"$repo\"}"
  sleep 0.8  # 避免单 worker 过载
done
```

### 断点续传（Checkpoint Resume）

这是批量分析的关键保障。任何任务在每一步都会保存检查点：

| 检查点 | 保存内容 | 恢复行为 |
|--------|---------|---------|
| Clone 完成 | 项目记录创建 | 跳过 clone 直接解析 |
| 文件解析 | `processed_files` JSONB 数组 | 只解析未处理文件 |
| LLM 批处理 | 已处理函数 ID 列表 | 跳过已生成函数 |
| 关系提取 | 已处理文件列表 | 跳过已分析文件 |

```bash
# 查看任务断点
curl http://localhost:8000/api/tasks/{task_id}/checkpoint

# 恢复中断的任务（worker 重启后使用）
curl -X POST http://localhost:8000/api/tasks/{task_id}/resume

# 列出所有未完成的任务
curl http://localhost:8000/api/tasks/unfinished
```

**实际验证**: 一次从 Chrome 书签中提取了 85 个 GitHub 仓库，跳过已分析的 34 个，批量提交 51 个新仓库。任务在 10 worker 并发下稳定运行，部分仓库 151 文件/195 函数在数分钟内完成分析。

---

## 🔌 Offline Mode 离线模式

Code Analyzer 支持完全离线运行，无需持续依赖 LLM API。

### 如何工作

1. **在线时**: 正常分析仓库，LLM 生成结构化元数据，保存到 PostgreSQL
2. **离线时**: MCP 服务器自动回退到本地 SQLite 数据库，继续提供搜索和上下文查询
3. **同步**: `sync_to_sqlite.py` 脚本将 PostgreSQL 数据同步到本地 SQLite 文件

```bash
# 将 PostgreSQL 数据同步到本地 SQLite
python sync_to_sqlite.py \
  --pg-url "postgresql://user:pass@host:5432/db" \
  --sqlite-path ./mcp-server-local/code_analyzer.db

# 启动离线 MCP 服务器（不依赖 Docker）
node mcp-server-local/index.js
```

**适用场景**:
- 开发环境网络受限的团队
- 笔记本电脑离线时仍需要搜索已分析代码
- 减少 LLM API 调用成本
- CI/CD 环境中不需要 LLM 生成的只读查询

### 离线 MCP 服务器配置

```json
{
  "mcpServers": {
    "code-analyzer-offline": {
      "command": "node",
      "args": ["/path/to/code_analyzer_mvp/mcp-server-local/index.js"],
      "env": {
        "DB_PATH": "/path/to/code_analyzer_mvp/mcp-server-local/code_analyzer.db"
      }
    }
  }
}
```

---

## 🔬 Code Parsing 代码解析

多语言解析引擎，支持 6+ 语言。

| 语言 | 解析方式 | 解析深度 | 提取内容 |
|------|---------|---------|---------|
| Python | **AST 解析** | 精确语法树 | 函数、类、参数类型、装饰器、docstring、返回值类型 |
| JavaScript/JSX/TSX | 正则解析 | 函数/类签名 | 函数、类、导出 |
| TypeScript | 正则解析 | 函数/类签名 | 函数、类、接口 |
| Go | 正则解析 | 函数签名 | 函数、方法、结构体 |
| Java | 正则解析 | 类/方法签名 | 类、方法、注解 |
| Rust | 正则解析 | 函数签名 | 函数、trait、impl |
| 其他 | 通用正则 | 粗略识别 | 基础函数定义 |

**Python AST 解析优势**: Python 使用原生 `ast` 模块进行精确解析，可以提取：
- 带默认值的精确参数列表
- 返回类型注解
- 装饰器链
- 类继承关系
- 函数体内调用关系

---

## 🔍 Search System 搜索系统

基于 PostgreSQL 全文检索，支持多种搜索方式。

### 技术实现

| 组件 | 实现 |
|------|------|
| 索引引擎 | PostgreSQL `tsvector` + `ts_rank` |
| 搜索范围 | 函数名、代码片段、AI 元数据、解释字段 |
| 过滤 | 按编程语言过滤 |
| 分组 | 按文件路径或项目分组 |

### 搜索类型对比

| 搜索类型 | 端点 | 数据来源 | 用途 |
|---------|------|---------|------|
| AI 优化搜索 | `/api/ai/search` | `ai_purpose`, `ai_inputs`, `ai_outputs`, `ai_side_effects` | MCP 工具 / AI 代理消费 |
| 通用搜索 | `/api/search` | 全部字段 + 代码片段 | 人类阅读 + 详细理解 |
| 引用搜索 | `/api/reference` | 精简字段 | 快速代码参考 |
| 类搜索 | `/api/classes/search` | 类定义字段 | 查找类定义和 OOP 结构 |

---

## 📊 Relationship Graph 调用关系图

自动提取函数间的调用、实现、继承关系，构建完整的调用图。

### 提取的关系类型

| 关系类型 | 说明 | 示例 |
|---------|------|------|
| `CALLS` | 函数 A 调用函数 B | `handleLogin` CALLS `validatePassword` |
| `IMPLEMENTS` | 方法实现接口/抽象 | `JSONSerializer` IMPLEMENTS `BaseSerializer` |
| `EXTENDS` | 类继承 | `AdminUser` EXTENDS `BaseUser` |

### 影响链分析

```
上游（谁受我影响）:                   下游（我依赖谁）:
                                    
  api/login.py:handleRequest          api/auth.py:validateToken
        │                                    │
        ▼                                    ▼
  api/auth.py:authenticate ── CALLS ──▶ api/auth.py:validatePassword
        │                                    │
        ▼                                    ▼
  api/auth.py:authorize                lib/bcrypt.py:hashPassword
```

```bash
# 上游分析：谁调用了这个函数（修改会影响谁）
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=upstream"

# 下游分析：这个函数调用了谁（它依赖什么）
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=downstream"

# 简要上下文
curl http://localhost:8000/api/functions/42/context
# → {"callers": [...], "callees": [...]}
```

---

## 🚀 Quick Start 快速开始

### 前置条件

- Docker & Docker Compose
- LLM API Key (DeepSeek Chat [免费注册](https://platform.deepseek.com/) / OpenAI / 兼容接口)

### 一键启动

```bash
# 1. 克隆仓库
git clone https://github.com/13051431832-cmd/code-analyzer.git
cd code-analyzer

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 3. 启动所有服务
docker compose up -d

# 4. 验证服务
curl http://localhost:8000/health
# → {"status":"ok","service":"code-analyzer-api"}

# 5. 分析一个项目
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/opendataloader-project/opendataloader-pdf.git"}'
# → {"task_id": "abc123..."}

# 6. 查看进度
curl http://localhost:8000/api/analyze/abc123.../status

# 7. 分析完成后，搜索代码
curl "http://localhost:8000/api/ai/search?q=file+processing&limit=5"
```

### 注册 MCP 服务器（Claude Code）

在 `~/.claude.json` 中添加：

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

重启 Claude Code，即可在对话中使用 all 14 个搜索工具。

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

### 分析管线

```
                       ┌────────────────────────────────────┐
                       │          Analysis Pipeline          │
                       ├────────────────────────────────────┤
  GitHub URL ──▶ 1. Clone ──▶ 2. Parse ──▶ 3. Extract ──▶ 4. LLM ──▶ 5. Save
                GitPython     AST/Regex    Relationships  Generate    to DB
                               │              │              │         │
                               ▼              ▼              ▼         ▼
                         函数/类签名       CALLS关系      AI元数据    PostgreSQL
                         参数提取         IMPLEMENTS     通俗解释    断点续传
                         类型注解         EXTENDS        专家分析    多模式
```

### 项目结构

```
code_analyzer_mvp/
├── api/                          # FastAPI 后端
│   ├── main.py                  # 应用入口 + 路由注册 + CORS
│   ├── ai.py                    # AI 优化搜索 / 函数上下文 / 调用图邻域
│   ├── analyze.py               # 分析任务提交 + 状态查询
│   ├── tasks.py                 # Celery 异步任务（~1300行核心逻辑）
│   ├── llm_service.py           # LLM 调用 + 三模式提示词管理
│   ├── crud.py                  # 数据库 CRUD 操作
│   ├── search_service.py        # PostgreSQL tsvector 全文搜索
│   ├── models.py                # SQLAlchemy ORM（6个模型）
│   ├── schemas.py               # Pydantic 请求/响应模型
│   ├── config.py                # 全局配置
│   ├── reanalyze.py             # 批量重新分析 + 模式切换
│   ├── relations.py             # 函数调用关系图
│   ├── projects.py              # 项目管理
│   ├── functions.py             # 函数详情
│   ├── classes.py               # 类详情
│   ├── files.py                 # 文件-函数关联
│   ├── database.py              # SQLAlchemy 引擎/会话
│   ├── report_generator.py      # 分析报告生成
│   └── parsers/                 # 代码解析器
│       ├── python_parser.py     # Python AST 解析（精确语法树）
│       └── generic_parser.py    # 通用正则解析（JS/TS/Go/Java/Rust）
├── mcp-server/                  # MCP 协议服务器（在线版）
│   └── index.js                 # 14 个 MCP 工具
├── mcp-server-local/            # MCP 协议服务器（离线版）
│   └── index.js                 # 不需要 Docker，基于 SQLite
├── frontend/                    # React 前端
│   └── src/
│       ├── CodeLearningView.jsx # 主界面（模式切换 + 代码展示）
│       └── App.js
├── tests/                       # 测试套件
│   ├── conftest.py              # TestClient + sample_project fixtures
│   └── test_three_mode.py       # 三模式集成测试（24 个用例）
├── worker/                      # Celery worker 配置
├── ca.sh                        # 终端搜索 CLI
├── sync_to_sqlite.py            # PostgreSQL → SQLite 同步脚本
├── docker-compose.yml           # 容器编排（5 个服务）
├── .env.example                 # 环境变量模板
└── requirements.txt             # Python 依赖
```

---

## 📖 API Reference API参考

### 分析任务

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze` | 提交分析任务 |
| `GET` | `/api/analyze/{id}/status` | 查询任务状态 |
| `GET` | `/api/tasks/{id}/checkpoint` | 获取任务检查点 |
| `POST` | `/api/tasks/{id}/resume` | 恢复中断任务 |
| `GET` | `/api/tasks/unfinished` | 列出未完成任务 |

### 项目管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/projects` | 列出所有项目 |
| `GET` | `/api/projects/stats` | 项目统计 |
| `GET` | `/api/projects/{id}` | 项目详情 |
| `GET` | `/api/projects/{id}/files` | 项目文件 + 函数/类 |
| `PUT` | `/api/projects/{id}/mode` | 切换分析模式 |
| `POST` | `/api/projects/{id}/switch-mode` | 切换模式 + 后台填充 |
| `POST` | `/api/projects/{id}/fill-mode-content` | 填充缺失模式内容 |
| `POST` | `/api/reanalyze/batch-migrate-mode` | 批量迁移模式 |
| `POST` | `/api/reanalyze/regenerate-overview/{id}` | 重新生成项目概览 |
| `DELETE` | `/api/projects/{id}` | 删除项目 |

### AI 优化搜索（MCP 工具调用）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/ai/search` | AI 优化搜索 |
| `GET` | `/api/ai/functions/{id}/context` | AI 函数上下文 |
| `GET` | `/api/ai/functions/{id}/neighborhood` | 调用图邻域 |

### 通用搜索

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/search` | 通用搜索 |
| `GET` | `/api/reference` | 引用搜索 |
| `GET` | `/api/classes/search` | 类搜索 |

### 函数分析

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/functions/{id}/detail` | 函数详情 |
| `GET` | `/api/functions/{id}/context` | 调用上下文 |
| `GET` | `/api/functions/{id}/impact` | 影响链 |

### 文件和类

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/files/{id}` | 文件详情 |
| `GET` | `/api/files/by-path` | 按路径查文件 |
| `GET` | `/api/classes/{id}` | 类详情 |

---

## ⚙️ Configuration 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DATABASE_URL` | PostgreSQL 连接 | `postgresql://code_analyzer:password@postgres:5432/code_analyzer_db` |
| `REDIS_URL` | Redis 连接 | `redis://redis:6379/0` |
| `LLM_API_KEY` | LLM API 密钥 | **必填** |
| `LLM_MODEL` | 模型名 | `deepseek-chat` |
| `LLM_BASE_URL` | API 地址 | `https://api.deepseek.com` |
| `API_KEYS` | API 密钥 JSON | `{"mvp_key": "default_project"}` |
| `TEMP_DIR` | 临时目录 | `/tmp/code_analysis` |
| `SEARCH_DEFAULT_LIMIT` | 默认搜索条数 | `20` |
| `SEARCH_MAX_LIMIT` | 最大搜索条数 | `100` |

### Docker Compose 服务

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `postgres` | postgres:15 | 5432 | 主数据库 |
| `redis` | redis:7 | 6379 | 消息队列 + 结果后端 |
| `api` | 自构建 | 8000 | FastAPI 应用 |
| `worker` | 自构建 | - | Celery 异步任务（10 并发） |
| `frontend` | node:18 | 3000 | React UI |

---

## 🧪 Testing 测试

```bash
# 运行所有测试
docker compose exec api pytest tests/ -v

# 三模式集成测试（24 个测试用例）
docker compose exec api pytest tests/test_three_mode.py -v

# 指定类测试
docker compose exec api pytest tests/test_three_mode.py::TestProjectMode -v
```

---

## 📄 License 许可证

MIT

---

> Built for the AI era — where understanding code at scale is no longer a human-only job.
>
> 为 AI 时代而生——大规模理解代码不再只是人类的工作。
