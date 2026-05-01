#!/bin/bash
# Code Analyzer CLI wrapper - query code database from terminal
# Usage: ./ca.sh "search query" [language] [limit]
# Example: ./ca.sh "rate limiting middleware" typescript 5

API_BASE="http://localhost:8000"
QUERY="$1"
LANGUAGE="${2:-}"
LIMIT="${3:-10}"

if [ -z "$QUERY" ]; then
    echo "Usage: ca <query> [language] [limit]"
    echo ""
    echo "Available tools:"
    echo "  search <query> [lang] [limit]  - Search function implementations"
    echo "  ref <query> [limit]            - AI-optimized reference"
    echo "  detail <id>                    - Function detail by ID"
    echo "  context <id>                   - Call context (callers + callees)"
    echo "  impact <id> [depth] [dir]      - BFS impact chain"
    exit 1
fi

# URL-encode the query
ENCODED_QUERY=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$QUERY'))")

LANG_PARAM=""
if [ -n "$LANGUAGE" ]; then
    LANG_PARAM="&language=$LANGUAGE"
fi

curl -s "$API_BASE/api/search?q=$ENCODED_QUERY$LANG_PARAM&limit=$LIMIT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('results', [])
print(f'\\n=== Code Analyzer: \"$QUERY\" ===')
print(f'找到 {len(results)} 个结果')
print('-' * 60)
for r in results:
    name = r.get('name', '?')
    lang = r.get('language', '?')
    sig = r.get('code_snippet', '')[:120].replace(chr(10), ' ')
    proj = r.get('project_name', '?')
    path = r.get('file_path', '?')
    score = r.get('score', 0)
    fid = r.get('id', '?')
    print(f'  [{lang}] {name} (score: {score:.3f}, id: {fid})')
    print(f'  项目: {proj}')
    print(f'  路径: {path}')
    print(f'  签名: {sig}')
    print()
"
