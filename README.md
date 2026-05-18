
# Code Analyzer MVP

> **Make your codebase AI-readable** — Automatically analyze Git repos, extract structured metadata, and let Claude Code search & understand code through MCP.

---

## What Problem Does This Solve

Grep finds text. Code Analyzer finds **meaning**.

When an LLM writes code, it needs to understand *what a function does, what it expects, what it returns, and what side effects it causes* — not just where the string "handleLogin" appears. Code Analyzer pre-compiles codebases into AI-consumable metadata so that Claude Code can search across 25+ projects, trace call graphs, and understand function semantics before making changes.

**It is NOT a grep replacement.** For routine searches ("where is function X defined"), grep is faster. Code Analyzer is for four specific scenarios where grep falls short:

| Scenario | Trigger | Tool |
|----------|---------|------|
| **A. Cross-project pattern search** | "How did we implement auth in other projects?" | `ai_search` → `get_ai_context` |
| **B. Refactoring impact analysis** | "Who will break if I change this function?" | `get_impact` / `get_ai_neighborhood` |
| **C. Unfamiliar project onboarding** | "How is this repo organized?" | `get_project_stats` → `get_module_graph` |
| **D. Class hierarchy navigation** | "What inherits from this base class?" | `get_class_hierarchy` / `get_subclasses` |

---

## 📋 Table of Contents

- [What Problem Does This Solve](#what-problem-does-this-solve)
- [🎯 Claude Code Integration](#-claude-code-integration)
- [💻 Terminal CLI](#-terminal-cli)
- [🌐 Web API](#-web-api)
- [🖥️ Frontend UI](#️-frontend-ui)
- [🎨 Three Analysis Modes](#-three-analysis-modes)
- [📦 Batch Analysis with Checkpoint Resume](#-batch-analysis-with-checkpoint-resume)
- [🔌 Offline Mode](#-offline-mode)
- [🔬 Code Parsing](#-code-parsing)
- [🔍 Search System](#-search-system)
- [📊 Relationship Graph](#-relationship-graph)
- [🚀 Quick Start](#-quick-start)
- [🏗 Architecture](#-architecture)
- [📖 API Reference](#-api-reference)
- [⚙️ Configuration](#️-configuration)
- [🧪 Testing](#-testing)
- [📄 License](#-license)

---

## 🎯 Claude Code Integration

Register the MCP server in `~/.claude.json`:

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

Once configured, add trigger rules to your project's `CLAUDE.md` so Claude Code knows when to use it. Do NOT use it as a blanket grep replacement. Use it in four specific scenarios:

### Scenario A: Cross-project pattern search
When implementing a feature that likely exists in another indexed project.

```
Claude calls: ai_search → get_ai_context (if match found)
```

### Scenario B: Refactoring impact analysis
Before modifying a function that may be called elsewhere.

```
Claude calls: get_ai_neighborhood → get_impact
```

### Scenario C: Unfamiliar project onboarding
When starting work in a repo you haven't explored.

```
Claude calls: get_project_stats → get_module_graph
```

### Scenario D: Class inheritance
When dealing with class hierarchies.

```
Claude calls: get_class_hierarchy → get_subclasses
```

### Full Tool Reference

| Tool | Purpose |
|------|---------|
| `ai_search` | Cross-project semantic search with structured metadata |
| `get_ai_context` | Ultra-compact function context for calling conventions |
| `get_ai_neighborhood` | Function + immediate call graph neighbors |
| `get_impact` | BFS traversal: upstream (who calls me) or downstream (what I depend on) |
| `get_module_graph` | Module-level dependency topology |
| `get_project_stats` | Aggregate stats for all indexed projects |
| `get_class_hierarchy` | Full inheritance chain (parents, children, interfaces) |
| `get_subclasses` | Find all classes extending a given parent |
| `get_file_dependencies` | Import dependencies for a file |
| `get_file_importers` | Files that import from a given file |
| `search_code` | Full search with explanations and code snippets |
| `search_classes` | Class search with architecture pattern filters |
| `search_grouped` | Search results grouped by file or project |
| `get_reference` | Compact code reference for AI consumption |
| `get_function_detail` | Full function profile |
| `get_file_functions` | All functions in a file |
| `get_context` | Callers + callees list |

---

## 💻 Terminal CLI

Search and analyze code directly from your terminal:

```bash
# Search for function implementations
./ca.sh "rate limiting middleware" typescript 5

# Function details
./ca.sh detail 42

# Call context (callers + callees)
./ca.sh context 42

# Impact chain analysis (BFS traversal)
./ca.sh impact 42 3 upstream
```

CLI commands:

| Command | Description | Example |
|---------|-------------|---------|
| `search <query> [lang] [limit]` | Search functions | `./ca.sh "rate limit" go 10` |
| `detail <id>` | Full function detail | `./ca.sh detail 42` |
| `context <id>` | Call context | `./ca.sh context 42` |
| `impact <id> [depth] [dir]` | Impact chain | `./ca.sh impact 42 3 upstream` |

---

## 🌐 Web API

All features are accessible via REST API from any HTTP client:

```bash
# Submit an analysis task
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/user/repo.git"}'
# → {"task_id": "abc123...", "status": "pending"}

# Check task status (with progress percentage and current step)
curl http://localhost:8000/api/analyze/abc123.../status
# → {"status": "processing", "progress": 45, "current_step": "Parsing files"}

# List all analyzed projects
curl http://localhost:8000/api/projects

# AI-optimized search (structured metadata for AI consumption)
curl "http://localhost:8000/api/ai/search?q=authentication&limit=5"

# General search (detailed explanations and code snippets)
curl "http://localhost:8000/api/search?q=rate+limiting&language=typescript"

# Function context
curl http://localhost:8000/api/ai/functions/42/context

# Impact chain analysis
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=upstream"

# Search grouped by file (understand multi-file implementations)
curl "http://localhost:8000/api/search?q=crawler+pipeline&group_by=file"

# Project statistics overview
curl http://localhost:8000/api/projects/stats
```

---

## 🖥️ Frontend UI

A React-based graphical interface for browsing analysis results:

```
frontend/
├── public/index.html
└── src/
    ├── App.js              # Application entry
    ├── index.js            # Render entry
    └── CodeLearningView.jsx  # Main view: mode switching, code display, explanations
```

Access at `http://localhost:3000` after startup. Supports:
- Project list browsing
- Function/class structure display
- Side-by-side code + AI explanation view
- Three analysis mode switching

---

## 🎨 Three Analysis Modes

Same code, three perspectives. This is the core differentiator of Code Analyzer.

| Mode | Audience | Generated Content |
|------|----------|-------------------|
| `ai` **(default)** | AI agents, MCP tools | `purpose`, `inputs`(JSONB), `outputs`(JSONB), `side_effects`(JSONB) |
| `beginner` | Programming learners | `explanation_simple`, `explanation_logic` |
| `expert` | Experienced developers | `tech_details`, `error_handling`, `concurrency`, `tradeoffs` |

### Switching Modes

```bash
# Switch to expert mode
curl -X PUT http://localhost:8000/api/projects/1/mode?mode=expert

# Switch and fully reanalyze (regenerate all LLM content)
curl -X PUT "http://localhost:8000/api/projects/1/mode?mode=beginner&full_reanalysis=true"

# Batch migrate all projects to same mode
curl -X POST http://localhost:8000/api/reanalyze/batch-migrate-mode \
  -H "Content-Type: application/json" \
  -d '{"target_mode": "expert"}'
```

### Design Principles

| Principle | Description |
|-----------|-------------|
| AI metadata always generated | `ai_` fields are never lost during mode switches (MCP depends on them) |
| Mode switching preserves existing content | Switching to a new mode does not overwrite old mode's content |
| Incremental fill | Use `fill-mode-content` to add missing mode content without a full reanalysis |
| Checkpoint resume | LLM batch processing can resume from checkpoints on interruption |

### Mode Content Examples

**ai mode** (structured metadata for a function):
```json
{
  "ai_purpose": "Validate user JWT token and return user info",
  "ai_inputs": [{"name": "token", "type": "str", "desc": "JWT token from Authorization header"}],
  "ai_outputs": [{"name": "user", "type": "dict", "desc": "User info with id, email, role"}],
  "ai_side_effects": ["Reads Redis cache", "Writes audit log"]
}
```

**beginner mode** (plain explanation):
```json
{
  "explanation_simple": "This function checks if a user's login credentials are valid. You give it a password, it checks against the database — if correct, you're logged in; if not, access is denied.",
  "explanation_logic": "Receives username + password → looks up user in database → verifies password hash with bcrypt → generates session → returns result"
}
```

**expert mode** (deep technical analysis):
```json
{
  "expert_purpose": "OAuth2 password flow authentication with MFA fallback",
  "expert_tech_details": "Uses passlib's bcrypt for password hash verification via SQLAlchemy async session",
  "expert_error_handling": "UserNotFound → 404, PasswordMismatch → 401, AccountLocked → 423",
  "expert_concurrency": "Each request has its own session — no shared state, naturally thread-safe",
  "expert_tradeoffs": "bcrypt cost factor 12: high security at ~250ms per verification"
}
```

---

## 📦 Batch Analysis with Checkpoint Resume

Supports large-scale batch analysis — designed to scan dozens of repositories in one go.

```bash
# Batch submit 50+ repositories
for repo in \
  "https://github.com/user/repo1.git" \
  "https://github.com/user/repo2.git"; do
  curl -s -X POST http://localhost:8000/api/analyze \
    -H "Content-Type: application/json" \
    -d "{\"repo_url\": \"$repo\"}"
  sleep 0.8  # avoid overloading single worker
done
```

### Checkpoint System

Every task saves progress at each step. If the worker restarts, the task resumes from the last checkpoint:

| Checkpoint | Saved State | Resume Behavior |
|------------|-------------|-----------------|
| Clone complete | Project record created | Skip clone, go direct to parsing |
| Files parsed | `processed_files` JSONB array | Parse only unprocessed files |
| LLM batch | List of processed function IDs | Skip already-generated functions |
| Relationship extraction | List of processed files | Skip already-analyzed files |

```bash
# View task checkpoint
curl http://localhost:8000/api/tasks/{task_id}/checkpoint

# Resume interrupted task (use after worker restart)
curl -X POST http://localhost:8000/api/tasks/{task_id}/resume

# List all unfinished tasks
curl http://localhost:8000/api/tasks/unfinished
```

**Verified in production**: Extracted 85 GitHub repositories from Chrome bookmarks, skipped 34 already-analyzed repos, and batch-submitted 51 new ones. Tasks ran stably with 10 concurrent workers — a 151-file/195-function repo completed within minutes.

---

## 🔌 Offline Mode

Code Analyzer supports fully offline operation without continuous LLM API dependency.

### How It Works

1. **Online**: Analyze repos normally, LLM generates structured metadata, saved to PostgreSQL
2. **Offline**: MCP server falls back to local SQLite database, continues serving search and context queries
3. **Sync**: `sync_to_sqlite.py` copies PostgreSQL data to a local SQLite file

```bash
# Sync PostgreSQL data to local SQLite
python sync_to_sqlite.py \
  --pg-url "postgresql://user:pass@host:5432/db" \
  --sqlite-path ./mcp-server-local/code_analyzer.db

# Start offline MCP server (no Docker required)
node mcp-server-local/index.js
```

**Use cases**:
- Teams with restricted network access
- Laptop disconnected from internet but still needs to search analyzed code
- Reduce LLM API costs
- Read-only queries in CI/CD environments

### Offline MCP Server Configuration

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

## 🔬 Code Parsing

Multi-language parsing engine supporting 6+ languages.

| Language | Parser | Parse Depth | Extracted Information |
|----------|--------|-------------|----------------------|
| Python | **AST** (native `ast` module) | Full syntax tree | Functions, classes, parameter types, decorators, docstrings, return types |
| JavaScript/JSX/TSX | Regex | Function/class signatures | Functions, classes, exports |
| TypeScript | Regex | Function/class signatures | Functions, classes, interfaces |
| Go | Regex | Function signatures | Functions, methods, structs |
| Java | Regex | Class/method signatures | Classes, methods, annotations |
| Rust | Regex | Function signatures | Functions, traits, impl blocks |
| Others | Generic regex | Rough recognition | Basic function definitions |

**Python AST advantage**: Python uses the native `ast` module for precise parsing — it extracts:
- Exact parameter lists with default values
- Return type annotations
- Decorator chains
- Class inheritance relationships
- Function call relationships within bodies

---

## 🔍 Search System

PostgreSQL full-text search engine with multiple search modes.

### Technical Implementation

| Component | Implementation |
|-----------|---------------|
| Index engine | PostgreSQL `tsvector` + `ts_rank` |
| Search scope | Function names, code snippets, AI metadata, explanation fields |
| Filtering | By programming language |
| Grouping | By file path or project |

### Search Types Compared

| Search Type | Endpoint | Data Source | Purpose |
|------------|----------|-------------|---------|
| AI-optimized | `/api/ai/search` | `ai_purpose`, `ai_inputs`, `ai_outputs`, `ai_side_effects` | AI agent / MCP tool consumption |
| General | `/api/search` | All fields + code snippets | Human reading + detailed understanding |
| Reference | `/api/reference` | Compact fields | Quick code reference |
| Class | `/api/classes/search` | Class definition fields | OOP structure discovery |

---

## 📊 Relationship Graph

Automatically extracts function call, implementation, and inheritance relationships to build a complete call graph.

### Relationship Types

| Type | Description | Example |
|------|-------------|---------|
| `CALLS` | Function A calls function B | `handleLogin` CALLS `validatePassword` |
| `IMPLEMENTS` | Method implements interface/abstract | `JSONSerializer` IMPLEMENTS `BaseSerializer` |
| `EXTENDS` | Class inherits from another | `AdminUser` EXTENDS `BaseUser` |

### Impact Chain Analysis

```
Upstream (who I affect):            Downstream (what I depend on):

  api/login.py:handleRequest          api/auth.py:validateToken
        │                                    │
        ▼                                    ▼
  api/auth.py:authenticate ── CALLS ──▶ api/auth.py:validatePassword
        │                                    │
        ▼                                    ▼
  api/auth.py:authorize                lib/bcrypt.py:hashPassword
```

```bash
# Upstream analysis: who calls this function (who is affected if I modify it)
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=upstream"

# Downstream analysis: what does this function call (what does it depend on)
curl "http://localhost:8000/api/functions/42/impact?depth=3&direction=downstream"

# Brief context (callers + callees)
curl http://localhost:8000/api/functions/42/context
# → {"callers": [...], "callees": [...]}
```

---

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- LLM API Key (DeepSeek Chat [free signup](https://platform.deepseek.com/) / OpenAI / compatible)

### One-Click Startup

```bash
# 1. Clone
git clone https://github.com/13051431832-cmd/code-analyzer.git
cd code-analyzer

# 2. Configure environment
cp .env.example .env
# Edit .env: set LLM_API_KEY

# 3. Start all services
docker compose up -d

# 4. Verify
curl http://localhost:8000/health
# → {"status":"ok","service":"code-analyzer-api"}

# 5. Analyze a project
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/opendataloader-project/opendataloader-pdf.git"}'

# 6. Check progress
curl http://localhost:8000/api/analyze/<task_id>/status

# 7. Search analyzed code
curl "http://localhost:8000/api/ai/search?q=file+processing&limit=5"
```

### Register MCP Server (for Claude Code)

Add to `~/.claude.json`:

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

Restart Claude Code — all 14 search tools are available immediately in any conversation.

---

## 🏗 Architecture

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

### Analysis Pipeline

```
                       ┌────────────────────────────────────────────┐
                       │            Analysis Pipeline               │
                       ├────────────────────────────────────────────┤
  GitHub URL ──▶ 1. Clone ──▶ 2. Parse ──▶ 3. Extract ──▶ 4. LLM ──▶ 5. Save
                GitPython     AST/Regex    Relationships  Generate    to DB
                               │              │              │         │
                               ▼              ▼              ▼         ▼
                         Function/class    CALLS rels     AI metadata  PostgreSQL
                         signatures        IMPLEMENTS     explanations Checkpoint
                         parameters        EXTENDS        expert       Multi-mode
```

### Project Structure

```
code_analyzer_mvp/
├── api/                          # FastAPI backend
│   ├── main.py                  # App entry + route registration + CORS
│   ├── ai.py                    # AI-optimized search / function context / neighborhood
│   ├── analyze.py               # Task submission + status queries
│   ├── tasks.py                 # Celery async tasks (~1300 lines of core logic)
│   ├── llm_service.py           # LLM invocation + 3-mode prompt templates
│   ├── crud.py                  # Database CRUD operations
│   ├── search_service.py        # PostgreSQL tsvector full-text search
│   ├── models.py                # SQLAlchemy ORM (6 models)
│   ├── schemas.py               # Pydantic request/response models
│   ├── config.py                # Global configuration
│   ├── reanalyze.py             # Batch reanalysis + mode switching
│   ├── relations.py             # Function call relationship graph
│   ├── projects.py              # Project management
│   ├── functions.py             # Function details
│   ├── classes.py               # Class details
│   ├── files.py                 # File-function associations
│   ├── database.py              # SQLAlchemy engine/session
│   ├── report_generator.py      # Analysis report generation
│   └── parsers/                 # Code parsers
│       ├── python_parser.py     # Python AST parser (precise syntax tree)
│       └── generic_parser.py    # Generic regex parser (JS/TS/Go/Java/Rust)
├── mcp-server/                  # MCP protocol server (online)
│   └── index.js                 # 14 MCP tools for Claude Code
├── mcp-server-local/            # MCP protocol server (offline)
│   └── index.js                 # No Docker needed, SQLite-based
├── frontend/                    # React frontend
│   └── src/
│       ├── CodeLearningView.jsx # Main view (mode switching + code display)
│       └── App.js
├── tests/                       # Test suite
│   ├── conftest.py              # TestClient + sample_project fixtures
│   └── test_three_mode.py       # 3-mode integration tests (24 test cases)
├── worker/                      # Celery worker config
├── ca.sh                        # Terminal search CLI
├── sync_to_sqlite.py            # PostgreSQL → SQLite sync script
├── docker-compose.yml           # Container orchestration (5 services)
├── .env.example                 # Environment variable template
└── requirements.txt             # Python dependencies
```

---

## 📖 API Reference

### Analysis Tasks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/analyze` | Submit analysis task |
| `GET` | `/api/analyze/{id}/status` | Query task status |
| `GET` | `/api/tasks/{id}/checkpoint` | Get task checkpoint |
| `POST` | `/api/tasks/{id}/resume` | Resume interrupted task |
| `GET` | `/api/tasks/unfinished` | List unfinished tasks |

### Project Management

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/stats` | Project statistics |
| `GET` | `/api/projects/{id}` | Project details |
| `GET` | `/api/projects/{id}/files` | Project files + functions/classes |
| `PUT` | `/api/projects/{id}/mode` | Switch analysis mode |
| `POST` | `/api/projects/{id}/switch-mode` | Switch mode + background fill |
| `POST` | `/api/projects/{id}/fill-mode-content` | Fill missing mode content |
| `POST` | `/api/reanalyze/batch-migrate-mode` | Batch mode migration |
| `POST` | `/api/reanalyze/regenerate-overview/{id}` | Regenerate project overview |
| `DELETE` | `/api/projects/{id}` | Delete project |

### AI-Optimized Search (MCP targets)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/ai/search` | AI-optimized search |
| `GET` | `/api/ai/functions/{id}/context` | AI function context |
| `GET` | `/api/ai/functions/{id}/neighborhood` | Call graph neighborhood |

### General Search

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/search` | General search |
| `GET` | `/api/reference` | Compact reference search |
| `GET` | `/api/classes/search` | Class search |

### Function Analysis

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/functions/{id}/detail` | Function details |
| `GET` | `/api/functions/{id}/context` | Call context |
| `GET` | `/api/functions/{id}/impact` | Impact chain |

### Files & Classes

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/files/{id}` | File details |
| `GET` | `/api/files/by-path` | Lookup file by path |
| `GET` | `/api/classes/{id}` | Class details |

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection | `postgresql://code_analyzer:password@postgres:5432/code_analyzer_db` |
| `REDIS_URL` | Redis connection | `redis://redis:6379/0` |
| `LLM_API_KEY` | LLM API key | **Required** |
| `LLM_MODEL` | Model name | `deepseek-chat` |
| `LLM_BASE_URL` | API endpoint | `https://api.deepseek.com` |
| `API_KEYS` | API keys JSON | `{"mvp_key": "default_project"}` |
| `TEMP_DIR` | Temp directory | `/tmp/code_analysis` |
| `SEARCH_DEFAULT_LIMIT` | Default search limit | `20` |
| `SEARCH_MAX_LIMIT` | Max search limit | `100` |

### Docker Compose Services

| Service | Image | Port | Description |
|---------|-------|------|-------------|
| `postgres` | postgres:15 | 5432 | Primary database |
| `redis` | redis:7 | 6379 | Message broker + result backend |
| `api` | self-built | 8000 | FastAPI application |
| `worker` | self-built | - | Celery async tasks (10 concurrency) |
| `frontend` | node:18 | 3000 | React UI |

---

## 🧪 Testing

```bash
# Run all tests
docker compose exec api pytest tests/ -v

# Three-mode integration tests (24 test cases)
docker compose exec api pytest tests/test_three_mode.py -v

# Class-specific test
docker compose exec api pytest tests/test_three_mode.py::TestProjectMode -v
```

---

## 📄 License

MIT

---

> Built for the AI era — where understanding code at scale is no longer a human-only job.
