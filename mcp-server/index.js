#!/usr/bin/env node
/**
 * Code Analyzer MCP Server
 *
 * Connects Claude Code to the code_analyzer database via MCP protocol.
 * Allows Claude Code to search analyzed code repositories for reference
 * implementations during development.
 *
 * Usage:
 *   1. Start the code_analyzer Docker containers: docker compose up -d
 *   2. Register in .claude.json (see README)
 *   3. Claude Code will automatically have access to search_code and get_reference tools
 */

const http = require('http');
const https = require('https');

const API_BASE = process.env.CODE_ANALYZER_API || 'http://localhost:8000';
const REQUEST_TIMEOUT = 10_000;

// ── Helpers ──────────────────────────────────────────────

function apiUrl(path) {
  const base = API_BASE.replace(/\/+$/, '');
  return `${base}${path}`;
}

function apiFetch(url) {
  const isHttps = url.startsWith('https');
  const client = isHttps ? https : http;

  return new Promise((resolve, reject) => {
    const req = client.get(url, { timeout: REQUEST_TIMEOUT }, (res) => {
      let data = '';
      res.on('data', (c) => (data += c));
      res.on('end', () => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`API returned ${res.statusCode}: ${data.slice(0, 200)}`));
          return;
        }
        try {
          resolve(JSON.parse(data));
        } catch {
          reject(new Error(`Invalid JSON response: ${data.slice(0, 200)}`));
        }
      });
    });
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('API request timed out'));
    });
  });
}

// ── MCP Protocol ─────────────────────────────────────────

function rpcResult(id, result) {
  return JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n';
}

function rpcError(id, code, message) {
  return JSON.stringify({ jsonrpc: '2.0', id, error: { code, message } }) + '\n';
}

// ── Tool Definitions ─────────────────────────────────────

const AI_TOOLS = [
  {
    name: 'get_ai_context',
    description:
      '[AI-OPTIMIZED] Get ultra-compact function context for AI consumption. ' +
      'Returns only what an AI needs to use a function correctly: purpose, inputs (name+type+desc), ' +
      'outputs, side_effects, and call graph stats. No human-oriented prose.\n\n' +
      'Call this BEFORE using a function to ensure correct invocation.',
    inputSchema: {
      type: 'object',
      properties: {
        function_id: {
          type: 'number',
          description: 'The function ID from search_code or ai_search results',
        },
      },
      required: ['function_id'],
    },
  },
  {
    name: 'get_ai_neighborhood',
    description:
      '[AI-OPTIMIZED] Get a function plus its immediate call graph neighbors. ' +
      'Returns compact graph with nodes (name, sig, purpose, return_type) and edges. ' +
      'Call this to understand how a function fits into the broader codebase before refactoring.',
    inputSchema: {
      type: 'object',
      properties: {
        function_id: {
          type: 'number',
          description: 'The function ID to analyze',
        },
        depth: {
          type: 'number',
          description: 'Traversal depth (1=immediate neighbors, 2=transitive, max 3)',
          default: 1,
        },
      },
      required: ['function_id'],
    },
  },
  {
    name: 'ai_search',
    description:
      '[AI-OPTIMIZED] Search code with AI-oriented results. ' +
      'Returns compact results prioritizing ai.purpose, ai.inputs, ai.outputs, ai.side_effects ' +
      'over human explanations. Designed for AI agent tool use.\n\n' +
      'Use this when you need to find relevant functions by task description, ' +
      'e.g., "find rate limiting middleware" or "find user validation function".',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Task description or search query',
        },
        limit: {
          type: 'number',
          description: 'Maximum results (default: 10, max: 50)',
          default: 10,
        },
        language: {
          type: 'string',
          description: 'Filter by programming language',
          enum: ['python', 'javascript', 'typescript', 'go', 'java', 'rust'],
        },
      },
      required: ['query'],
    },
  },
];

const TOOLS = [
  {
    name: 'search_code',
    description:
      'Search analyzed code repositories for function implementations. ' +
      'Returns ranked results with AI-oriented metadata (purpose, inputs, outputs, side_effects) ' +
      'plus call graph stats. Use this to find existing implementations, understand patterns, ' +
      'or get structured function references for AI consumption.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description:
            'Natural language search query describing what you are looking for ' +
            '(e.g., "rate limiting middleware", "user authentication", "database query helper")',
        },
        language: {
          type: 'string',
          description: 'Filter results by programming language',
          enum: ['python', 'javascript', 'typescript', 'go', 'java', 'rust'],
        },
        limit: {
          type: 'number',
          description: 'Maximum number of results to return (default: 10, max: 50)',
          default: 10,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_reference',
    description:
      'Get compact code reference context optimized for AI consumption. ' +
      'Returns only essential fields (function name, signature, code, explanation, context). ' +
      'Use this when you need quick code references during implementation.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query for finding relevant code references',
        },
        limit: {
          type: 'number',
          description: 'Maximum number of references to return (default: 5, max: 20)',
          default: 5,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_function_detail',
    description:
      'Get full details for a specific function by its ID, including file path, ' +
      'project name, and related functions. Use the ID from search_code results.',
    inputSchema: {
      type: 'object',
      properties: {
        function_id: {
          type: 'number',
          description: 'The function ID from search_code results',
        },
      },
      required: ['function_id'],
    },
  },
  {
    name: 'get_context',
    description:
      'Get the call context for a function: who calls it (callers) and ' +
      'what it calls (callees). Includes code preview snippets. Use this to ' +
      'understand how a function fits into the codebase before modifying it.',
    inputSchema: {
      type: 'object',
      properties: {
        function_id: {
          type: 'number',
          description: 'The function ID to analyze',
        },
      },
      required: ['function_id'],
    },
  },
  {
    name: 'get_impact',
    description:
      'BFS traversal of the function call impact chain. Use this to assess ' +
      'the blast radius of changes before refactoring or modifying code.\n\n' +
      'direction="upstream": find all functions that transitively call this function — ' +
      '"who is affected if I modify this?"\n\n' +
      'direction="downstream": find all functions this function transitively calls — ' +
      '"what does this depend on?"',
    inputSchema: {
      type: 'object',
      properties: {
        function_id: {
          type: 'number',
          description: 'The function ID to analyze',
        },
        depth: {
          type: 'number',
          description: 'Maximum traversal depth (default: 3, max: 10)',
          default: 3,
        },
        direction: {
          type: 'string',
          description: 'Traversal direction: "upstream" (callers) or "downstream" (callees)',
          default: 'upstream',
          enum: ['upstream', 'downstream'],
        },
      },
      required: ['function_id'],
    },
  },
  {
    name: 'get_file_functions',
    description:
      'Get all functions in a specific file, with signatures, explanations, and relationship counts. ' +
      'Use this when you need to understand how all functions in a file work together. ' +
      'Provide either file_id, or project_id + file_path to locate the file.',
    inputSchema: {
      type: 'object',
      properties: {
        file_id: {
          type: 'number',
          description: 'The file ID (from search_code results)',
        },
        project_id: {
          type: 'number',
          description: 'Project ID — required if file_id is not provided',
        },
        file_path: {
          type: 'string',
          description: 'File path within the project, e.g. "api/apps/user_app.py" — required if file_id is not provided',
        },
      },
    },
  },
  {
    name: 'search_grouped',
    description:
      'Search code and group results by file or project. ' +
      'Use this when you need to understand systematic patterns across multiple files — ' +
      'e.g., "how does authentication work end-to-end" or "show me all crawler functions grouped by file". ' +
      'Grouping by file shows you which files contain the most relevant functions, ' +
      'helping you understand multi-file feature implementations.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description:
            'Natural language search query (e.g., "user login", "crawler pipeline", "rate limiting")',
        },
        group_by: {
          type: 'string',
          description: 'Group results: "file" (by file path) or "project" (by project name)',
          enum: ['file', 'project'],
          default: 'file',
        },
        language: {
          type: 'string',
          description: 'Filter by programming language',
          enum: ['python', 'javascript', 'typescript', 'go', 'java', 'rust'],
        },
        limit: {
          type: 'number',
          description: 'Maximum number of search results (default: 30, max: 100)',
          default: 30,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'search_classes',
    description:
      'Search analyzed code repositories for class definitions. ' +
      'Returns ranked results with code snippets and AI explanations. ' +
      'Use this when you need to find class hierarchies, patterns, or understand ' +
      'object-oriented design in the analyzed codebase.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Natural language search query (e.g., "database model", "middleware class", "service layer")',
        },
        language: {
          type: 'string',
          description: 'Filter results by programming language',
          enum: ['python', 'javascript', 'typescript', 'go', 'java', 'rust'],
        },
        limit: {
          type: 'number',
          description: 'Maximum number of results (default: 10, max: 50)',
          default: 10,
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'get_project_stats',
    description:
      'Get aggregate statistics for all analyzed projects. ' +
      'Returns per-project counts of files, functions, classes, code snippet coverage, ' +
      'and explanation coverage percentages. Use this to understand the scope and ' +
      'completeness of the code analysis database before searching.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  ...AI_TOOLS,
];

// ── Message Handler ──────────────────────────────────────

async function handleMessage(msg) {
  const { id, method, params } = msg;

  // Notification — no response needed
  if (method === 'notifications/initialized' || method === 'notifications/cancelled') {
    return;
  }

  if (!id) return; // Only handle messages with id

  switch (method) {
    case 'initialize': {
      process.stdout.write(
        rpcResult(id, {
          protocolVersion: '2024-11-05',
          capabilities: { tools: {} },
          serverInfo: { name: 'code-analyzer-mcp', version: '1.0.0' },
        })
      );
      return;
    }

    case 'tools/list': {
      process.stdout.write(rpcResult(id, { tools: TOOLS }));
      return;
    }

    case 'tools/call': {
      const toolName = params?.name;
      const args = params?.arguments || {};

      try {
        let result;

        if (toolName === 'search_code') {
          const qs = new URLSearchParams({
            q: String(args.query),
            limit: String(args.limit || 10),
          });
          if (args.language) qs.set('language', args.language);
          result = await apiFetch(apiUrl(`/api/search?${qs}`));
        } else if (toolName === 'get_reference') {
          const qs = new URLSearchParams({
            q: String(args.query),
            limit: String(args.limit || 5),
          });
          result = await apiFetch(apiUrl(`/api/reference?${qs}`));
        } else if (toolName === 'get_function_detail') {
          result = await apiFetch(apiUrl(`/api/functions/${args.function_id}/detail`));
        } else if (toolName === 'get_context') {
          result = await apiFetch(apiUrl(`/api/functions/${args.function_id}/context`));
        } else if (toolName === 'get_impact') {
          const qs = new URLSearchParams({
            depth: String(args.depth || 3),
            direction: String(args.direction || 'upstream'),
          });
          result = await apiFetch(apiUrl(`/api/functions/${args.function_id}/impact?${qs}`));
        } else if (toolName === 'get_file_functions') {
          if (args.file_id) {
            result = await apiFetch(apiUrl(`/api/files/${args.file_id}`));
          } else if (args.project_id && args.file_path) {
            const qs = new URLSearchParams({
              project_id: String(args.project_id),
              file_path: args.file_path,
            });
            result = await apiFetch(apiUrl(`/api/files/by-path?${qs}`));
          } else {
            throw new Error('Provide either file_id, or project_id + file_path');
          }
        } else if (toolName === 'search_grouped') {
          const qs = new URLSearchParams({
            q: String(args.query),
            group_by: String(args.group_by || 'file'),
            limit: String(args.limit || 30),
          });
          if (args.language) qs.set('language', args.language);
          result = await apiFetch(apiUrl(`/api/search?${qs}`));
        } else if (toolName === 'search_classes') {
          const qs = new URLSearchParams({
            q: String(args.query),
            limit: String(args.limit || 10),
          });
          if (args.language) qs.set('language', args.language);
          result = await apiFetch(apiUrl(`/api/classes/search?${qs}`));
        } else if (toolName === 'get_project_stats') {
          result = await apiFetch(apiUrl(`/api/projects/stats`));
        } else if (toolName === 'get_ai_context') {
          result = await apiFetch(apiUrl(`/api/ai/functions/${args.function_id}/context`));
        } else if (toolName === 'get_ai_neighborhood') {
          const qs = new URLSearchParams({ depth: String(args.depth || 1) });
          result = await apiFetch(apiUrl(`/api/ai/functions/${args.function_id}/neighborhood?${qs}`));
        } else if (toolName === 'ai_search') {
          const qs = new URLSearchParams({
            q: String(args.query),
            limit: String(args.limit || 10),
          });
          if (args.language) qs.set('language', args.language);
          result = await apiFetch(apiUrl(`/api/ai/search?${qs}`));
        } else {
          process.stdout.write(rpcError(id, -32601, `Unknown tool: ${toolName}`));
          return;
        }

        process.stdout.write(
          rpcResult(id, {
            content: [{ type: 'text', text: JSON.stringify(result, null, 2) }],
          })
        );
      } catch (err) {
        const message = err.message.includes('connect')
          ? `Cannot connect to code_analyzer API at ${API_BASE}. Is Docker running? (docker compose up -d)`
          : `API error: ${err.message}`;

        process.stdout.write(rpcError(id, -32000, message));
      }
      return;
    }

    default: {
      process.stdout.write(rpcError(id, -32601, `Method not found: ${method}`));
    }
  }
}

// ── STDIN Loop ───────────────────────────────────────────

let buffer = '';
let pendingOps = 0;

process.stdin.on('data', (chunk) => {
  buffer += chunk.toString();
  const lines = buffer.split('\n');
  buffer = lines.pop() || '';

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    pendingOps++;
    handleMessage(JSON.parse(trimmed)).finally(() => {
      pendingOps--;
      maybeExit();
    });
  }
});

function maybeExit() {
  if (pendingOps <= 0) {
    // Keep alive — in real Claude Code usage stdin stays open
  }
}

process.stdin.on('end', () => {
  // Wait briefly for pending async operations, then exit
  const check = setInterval(() => {
    if (pendingOps <= 0) {
      clearInterval(check);
      process.exit(0);
    }
  }, 50);
  // Safety timeout
  setTimeout(() => process.exit(0), 5000);
});

process.stdin.resume();
