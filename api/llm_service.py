import json
import re
from openai import OpenAI
from .config import config

import concurrent.futures
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

client = OpenAI(
    api_key=config.LLM_API_KEY,
    base_url=config.LLM_BASE_URL,
    max_retries=2,  # Auto-retry on transient failures (timeout, 429, 500)
)


# ---- Human-oriented explanations (kept for backward compatibility) ----

HUMAN_SYSTEM_PROMPT = """
你是一个资深的全栈开发导师，现在需要帮助一个完全没有编程基础的初学者理解代码。
1. **小白模式**：完全禁用专业术语（如递归、闭包、异步）。如果必须使用，请立刻用生活中的例子比喻解释。
2. **逻辑拆解**：把代码想象成做菜的步骤，一步一步说明先做了什么，后做了什么。
3. **语气**：亲切、耐心，像给朋友讲故事一样。

请严格按照以下 JSON 格式输出，不要包含任何其他文字：
{
  "simple": "一句话大白话",
  "logic": "详细拆解（Markdown格式）"
}
"""

# ---- AI-oriented metadata prompts ----

AI_FUNCTION_SYSTEM_PROMPT = """
你是一个AI代码分析引擎。分析以下代码，输出结构化的AI可消费元数据。
输出必须是严格有效的JSON，不要包含任何其他文字。

要求：
1. purpose: 一句话精确描述该函数的功能（≤20字）
2. inputs: 参数列表，每个参数包含 name, type, description。
   - type必须精确（如 int, str, list[str], dict, User, None），不要写成泛泛的 "any"
   - description 短且精确（≤15字）
3. outputs: 返回值的 type 和 description
   - type必须精确，void/None 返回写 null
4. side_effects: 副作用列表（数组）
   - 包括：修改了哪些外部状态、做了哪些I/O、抛出了什么异常
   - 无副作用时为空数组 []

输出格式：
{
  "purpose": "验证用户输入并返回类型化结果",
  "inputs": [
    {"name": "data", "type": "unknown", "description": "原始输入数据"},
    {"name": "schema", "type": "ZodSchema<T>", "description": "Zod验证模式"}
  ],
  "outputs": {"type": "T", "description": "验证后的类型化数据"},
  "side_effects": ["格式错误时抛出ZodError"]
}

重要规则：
- 不要使用比喻（如"像做菜一样"）
- 不要解释基本概念
- 类型信息必须精确、可被AI直接使用
- 如果代码包含错误处理，必须在side_effects中标明
- 如果代码调用外部API/数据库，必须在side_effects中标明
"""

AI_CLASS_SYSTEM_PROMPT = """
你是一个AI代码分析引擎。分析以下类定义，输出结构化的AI可消费元数据。
输出必须是严格有效的JSON，不要包含任何其他文字。

要求：
1. purpose: 一句话精确描述该类的作用（≤25字）
2. interfaces: 该类对外暴露的关键方法/属性列表
   每个interfaces包含 name, type（方法签名）, description（作用）
3. patterns: 该类使用的架构/设计模式列表（可空数组）
   参考模式库（选择最匹配的1-3个，如无匹配则返回空数组）：

   创建型: Factory, Abstract Factory, Builder, Singleton, Prototype, Dependency Injection
   结构型: Adapter, Decorator, Facade, Proxy, Composite, Bridge
   行为型: Strategy, Observer, Command, Template Method, Chain of Responsibility, Mediator, State, Visitor, Iterator
   架构型: MVC, Repository, Service Layer, DTO, Middleware, Pub/Sub, Provider, ORM

   每个pattern包含：
   - pattern: 模式名称（优先从上述列表选择，也可补充自定义模式）
   - confidence: "high" | "medium" | "low"
   - evidence: 一句话说明为什么匹配（≤30字）

输出格式：
{
  "purpose": "管理用户认证和会话状态",
  "interfaces": [
    {"name": "login", "type": "(email: str, password: str) -> User", "description": "用户登录认证"},
    {"name": "logout", "type": "() -> void", "description": "清除当前用户会话"}
  ],
  "patterns": [
    {"pattern": "Repository", "confidence": "high", "evidence": "直接与数据存储交互，封装查询逻辑"}
  ]
}

重要规则：
- 不要使用比喻
- 只包含public/protected的关键接口
- 方法签名(type)必须包含参数和返回类型
- patterns不要强行匹配，不确定时空数组即可
"""

# ---- Expert mode prompts (for experienced developers) ----

EXPERT_FUNCTION_SYSTEM_PROMPT = """
你是一个资深代码审查专家。分析以下代码以技术角度输出结构化的分析结果。
输出必须是严格有效的JSON，不要包含任何其他文字。

请分析以下维度：
1. purpose: 一句话技术性描述该函数的核心功能（≤20字）
2. tech_details: 技术实现细节，包括使用的设计模式、算法复杂度、性能考量（≤100字）
3. error_handling: 错误处理策略分析（≤50字）
4. concurrency: 并发/异步处理说明，包括锁、协程、线程安全等（≤50字，无则写null）
5. tradeoffs: 设计权衡和替代方案（≤50字）

输出格式：
{
  "purpose": "基于LRU的缓存查询函数",
  "tech_details": "使用OrderedDict实现LRU缓存，get/set均为O(1)。缓存未命中时查询DB并更新缓存",
  "error_handling": "查询失败时抛出DataAccessException，上层由Controller捕获处理",
  "concurrency": "使用threading.Lock保证并发安全，读多写少场景下性能良好",
  "tradeoffs": "使用内存缓存而非Redis，牺牲分布式能力换取低延迟"
}

重要规则：
- 使用技术性精确语言，面向有3年+经验的开发者
- 不要解释基本概念（如什么是缓存、什么是O(1)）
- 如果代码没有并发处理或错误处理，对应字段写null
- 设计模式名称必须精确（如"策略模式"而非"一种模式"）
"""

EXPERT_CLASS_SYSTEM_PROMPT = """
你是一个资深代码审查专家。分析以下类的定义以技术角度输出结构化的分析结果。
输出必须是严格有效的JSON，不要包含任何其他文字。

请分析以下维度：
1. purpose: 一句话技术性描述该类的职责（≤25字）
2. architecture: 类架构分析，包括使用的设计模式、继承/组合关系（≤100字）
3. responsibilities: 各方法的职责划分和交互方式（≤100字）
4. extension_points: 扩展点设计和开放接口分析（≤50字）

输出格式：
{
  "purpose": "管理数据库连接池和会话生命周期",
  "architecture": "使用工厂模式创建连接，池化管理复用连接，支持读写分离",
  "responsibilities": "get_conn()从池中获取连接，release()归还连接，execute()封装查询执行",
  "extension_points": "可通过实现ConnectionProvider接口自定义连接来源"
}

重要规则：
- 使用技术性精确语言，面向有3年+经验的开发者
- 不要解释基本概念
- 如果类设计较简单，没有特别的设计模式，对应字段写null
- 重点分析类的公共接口设计
"""


def lookup_cached_metadata(db: "Session", code_hash: str | None, content_type: str = "ai") -> dict | None:
    """
    Look up existing LLM results from any function with the same code_hash.
    Avoids redundant API calls when identical code appears in multiple projects.
    """
    if not db or not code_hash:
        return None
    from . import models

    cached = (
        db.query(models.Function)
        .filter(models.Function.code_hash == code_hash)
        .first()
    )
    if not cached:
        return None

    if content_type == "ai" and cached.ai_purpose:
        return {
            "purpose": cached.ai_purpose,
            "inputs": cached.ai_inputs or [],
            "outputs": cached.ai_outputs or {"type": "unknown", "description": ""},
            "side_effects": cached.ai_side_effects or [],
        }
    if content_type == "beginner" and cached.explanation_simple:
        return {
            "simple": cached.explanation_simple,
            "logic": cached.explanation_logic or "",
        }
    if content_type == "expert" and cached.expert_purpose:
        return {
            "purpose": cached.expert_purpose,
            "tech_details": cached.expert_tech_details,
            "error_handling": cached.expert_error_handling,
            "concurrency": cached.expert_concurrency,
            "tradeoffs": cached.expert_tradeoffs,
        }
    return None


def _validate_ai_metadata(result: dict, code_type: str) -> dict:
    """Validate and normalize LLM output structure to prevent type errors downstream."""
    if code_type == "function":
        # purpose: must be string
        if not isinstance(result.get("purpose"), str):
            result["purpose"] = ""
        # inputs: must be list of dicts with name/type/description
        inputs = result.get("inputs", [])
        if not isinstance(inputs, list):
            inputs = []
        validated_inputs = []
        for inp in inputs:
            if isinstance(inp, dict) and "name" in inp:
                validated_inputs.append({
                    "name": str(inp.get("name", "")),
                    "type": str(inp.get("type", "unknown")),
                    "description": str(inp.get("description", "")),
                })
        result["inputs"] = validated_inputs
        # outputs: must be dict with type/description
        outputs = result.get("outputs", {})
        if not isinstance(outputs, dict):
            outputs = {"type": "unknown", "description": ""}
        result["outputs"] = {
            "type": str(outputs.get("type", "unknown")),
            "description": str(outputs.get("description", "")),
        }
        # side_effects: must be list of strings
        side_effects = result.get("side_effects", [])
        if not isinstance(side_effects, list):
            side_effects = []
        result["side_effects"] = [str(s) for s in side_effects if s is not None]

    elif code_type == "class":
        if not isinstance(result.get("purpose"), str):
            result["purpose"] = ""
        interfaces = result.get("interfaces", [])
        if not isinstance(interfaces, list):
            interfaces = []
        validated_interfaces = []
        for iface in interfaces:
            if isinstance(iface, dict):
                validated_interfaces.append({
                    "name": str(iface.get("name", "")),
                    "type": str(iface.get("type", "")),
                    "description": str(iface.get("description", "")),
                })
        result["interfaces"] = validated_interfaces

        # Validate patterns
        patterns = result.get("patterns", [])
        if not isinstance(patterns, list):
            patterns = []
        valid_confidence = {"high", "medium", "low"}
        validated_patterns = []
        for p in patterns:
            if isinstance(p, dict) and "pattern" in p:
                conf = str(p.get("confidence", "medium"))
                if conf not in valid_confidence:
                    conf = "medium"
                validated_patterns.append({
                    "pattern": str(p.get("pattern", "")),
                    "confidence": conf,
                    "evidence": str(p.get("evidence", "")),
                })
        result["patterns"] = validated_patterns

    return result


def generate_explanation(code_snippet: str, code_type: str = "function", language: str = "python") -> dict:
    """
    调用 LLM 生成代码解释 (human-oriented, kept for backward compatibility).
    Returns: {"simple": "...", "logic": "..."}
    """
    try:
        lang_display = {"javascript": "JavaScript", "typescript": "TypeScript", "go": "Go", "java": "Java", "rust": "Rust", "python": "Python"}.get(language, language)

        if code_type == "function":
            user_prompt = f"请分析以下 {lang_display} 函数：\n{code_snippet}"
        else:
            user_prompt = f"请分析以下 {lang_display} 类：\n{code_snippet}"

        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": HUMAN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.5,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        json_str = json_match.group() if json_match else content
        result = json.loads(json_str)

        return {
            "simple": result.get("simple", "暂无解释"),
            "logic": result.get("logic", "暂无详细步骤")
        }

    except json.JSONDecodeError as e:
        print(f"[Human-Explanation] JSON decode error: {e}")
        lines = content.split('\n') if 'content' in dir() else [""]
        return {"simple": lines[0] if lines else "AI 解析出错", "logic": '\n'.join(lines[1:]) if len(lines) > 1 else ""}
    except Exception as e:
        return {"simple": f"AI 解析出错: {str(e)}", "logic": ""}


def generate_ai_metadata(code_snippet: str, code_type: str = "function", language: str = "python") -> dict:
    """
    Generate AI-oriented metadata for a code snippet.
    Returns structured JSON consumable by AI systems, not human-readable explanations.

    Returns:
    For functions: {"purpose": str, "inputs": list, "outputs": dict, "side_effects": list}
    For classes: {"purpose": str, "interfaces": list}
    """
    try:
        lang_display = {"javascript": "JavaScript", "typescript": "TypeScript", "go": "Go", "java": "Java", "rust": "Rust", "python": "Python"}.get(language, language)

        system_prompt = AI_FUNCTION_SYSTEM_PROMPT if code_type == "function" else AI_CLASS_SYSTEM_PROMPT
        code_label = f"{lang_display} {'函数' if code_type == 'function' else '类'}"

        user_prompt = f"请分析以下 {code_label}：\n\n{code_snippet}"

        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,  # Lower temperature for deterministic structured output
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        json_str = json_match.group() if json_match else content
        result = json.loads(json_str)
        result = _validate_ai_metadata(result, code_type)

        if code_type == "function":
            return {
                "purpose": result["purpose"],
                "inputs": result["inputs"],
                "outputs": result["outputs"],
                "side_effects": result["side_effects"],
            }
        else:
            return {
                "purpose": result["purpose"],
                "interfaces": result["interfaces"],
            }

    except json.JSONDecodeError as e:
        print(f"[AI-Metadata] JSON decode error: {e}, raw: {content if 'content' in dir() else 'N/A'}")
        return {"purpose": "", "inputs": [], "outputs": {"type": "unknown", "description": ""}, "side_effects": []} if code_type == "function" else {"purpose": "", "interfaces": []}
    except Exception as e:
        print(f"[AI-Metadata] Error: {e}")
        return {"purpose": "", "inputs": [], "outputs": {"type": "unknown", "description": ""}, "side_effects": []} if code_type == "function" else {"purpose": "", "interfaces": []}


def generate_expert_analysis(code_snippet: str, code_type: str = "function", language: str = "python") -> dict:
    """
    Generate expert-mode technical analysis for experienced developers.
    Returns structured technical analysis, not beginner-friendly explanations.

    For functions: {"purpose": str, "tech_details": str, "error_handling": str, "concurrency": str, "tradeoffs": str}
    For classes: {"purpose": str, "architecture": str, "responsibilities": str, "extension_points": str}
    """
    try:
        lang_display = {"javascript": "JavaScript", "typescript": "TypeScript", "go": "Go", "java": "Java", "rust": "Rust", "python": "Python"}.get(language, language)

        system_prompt = EXPERT_FUNCTION_SYSTEM_PROMPT if code_type == "function" else EXPERT_CLASS_SYSTEM_PROMPT
        code_label = f"{lang_display} {'函数' if code_type == 'function' else '类'}"

        user_prompt = f"请分析以下 {code_label}：\n\n{code_snippet}"

        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,
            response_format={"type": "json_object"}
        )

        content = response.choices[0].message.content.strip()
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        json_str = json_match.group() if json_match else content
        result = json.loads(json_str)

        if code_type == "function":
            return {
                "purpose": result.get("purpose", ""),
                "tech_details": result.get("tech_details"),
                "error_handling": result.get("error_handling"),
                "concurrency": result.get("concurrency"),
                "tradeoffs": result.get("tradeoffs"),
            }
        else:
            return {
                "purpose": result.get("purpose", ""),
                "architecture": result.get("architecture"),
                "responsibilities": result.get("responsibilities"),
                "extension_points": result.get("extension_points"),
            }

    except json.JSONDecodeError as e:
        print(f"[Expert-Analysis] JSON decode error: {e}")
        empty_func = {"purpose": "", "tech_details": None, "error_handling": None, "concurrency": None, "tradeoffs": None}
        empty_class = {"purpose": "", "architecture": None, "responsibilities": None, "extension_points": None}
        return empty_func if code_type == "function" else empty_class
    except Exception as e:
        print(f"[Expert-Analysis] Error: {e}")
        empty_func = {"purpose": "", "tech_details": None, "error_handling": None, "concurrency": None, "tradeoffs": None}
        empty_class = {"purpose": "", "architecture": None, "responsibilities": None, "extension_points": None}
        return empty_func if code_type == "function" else empty_class


def generate_project_overview(project_name: str, files_summary: list) -> str:
    """生成项目的整体架构与功能解读"""
    system_prompt = """
你是一位资深软件架构师和技术文档专家。请根据提供的项目文件摘要，分析整个项目的：
1. **整体功能**：这个项目是做什么的？主要解决什么问题？
2. **架构设计**：采用了什么架构模式（如分层、微服务、事件驱动等）？代码是如何组织的？
3. **模块划分与职责**：每个文件/模块承担什么职责？核心模块有哪些？
4. **模块间关系**：模块之间如何交互？数据流或调用关系是怎样的？

请用清晰、友好的 Markdown 格式输出，适当使用标题、列表、代码块等，帮助初学者理解整体设计。
如果信息不足以判断某些方面，请基于常见实践给出合理推测。
"""

    summary_text = f"项目名称：{project_name}\n\n文件列表及功能摘要：\n"
    for file in files_summary:
        summary_text += f"\n- 文件：`{file['path']}`\n"
        if file.get('classes'):
            summary_text += f"  类：{', '.join(file['classes'])}\n"
        if file.get('functions'):
            summary_text += f"  函数：{', '.join(file['functions'])}\n"
        if file.get('docstring_summary'):
            summary_text += f"  说明：{file['docstring_summary']}\n"

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": summary_text}
            ],
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"整体解读生成失败：{str(e)}"


def generate_beginner_overview(project_name: str, files_summary: list) -> str:
    """生成面向初学者的通俗项目解读（小白模式）"""
    system_prompt = """
你是一位擅长用通俗语言讲解技术的老师。请根据提供的项目文件摘要，用**非常通俗易懂**的方式解释这个项目：

1. **这个项目是做什么的？** — 用一句话概括，然后用一个日常生活中的类比来解释
2. **主要功能** — 用"它能帮你做这些事"的角度列出功能
3. **大概是怎么工作的？** — 用比喻（比如"就像餐厅里...""就像快递系统..."）来解释模块如何协作
4. **技术栈简介** — 简要说明用了什么技术（如"用Python写的"，"用了一个叫FastAPI的框架"），用一句话解释每个技术是干嘛的

要求：
- 避免专业术语，必须用术语时要附上通俗解释
- 使用 Markdown 格式，但不要太复杂
- 目标是让完全不懂编程的人也能大概理解
- 语气友好、鼓励
"""
    summary_text = f"项目名称：{project_name}\n\n文件列表及功能摘要：\n"
    for file in files_summary:
        summary_text += f"\n- 文件：`{file['path']}`\n"
        if file.get('classes'):
            summary_text += f"  类：{', '.join(file['classes'])}\n"
        if file.get('functions'):
            summary_text += f"  函数：{', '.join(file['functions'])}\n"
        if file.get('docstring_summary'):
            summary_text += f"  说明：{file['docstring_summary']}\n"

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": summary_text}
            ],
            temperature=0.5,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"小白模式解读生成失败：{str(e)}"


def generate_expert_overview(project_name: str, files_summary: list) -> str:
    """生成面向资深开发者的技术架构分析（专家模式）"""
    system_prompt = """
你是一位资深软件架构师。请根据提供的项目文件摘要，从技术角度深入分析该项目：

1. **架构总览** — 整体架构风格（分层/事件驱动/微服务等），项目结构组织方式
2. **核心技术选型** — 使用的框架、库、数据库等，以及选型背后的权衡
3. **模块深度分析** — 各核心模块的设计模式、关键抽象、接口设计
4. **数据流与交互** — 模块间的调用关系、数据流向、依赖管理
5. **性能与扩展性考量** — 可能存在的瓶颈、扩展性设计、并发处理策略
6. **值得注意的设计决策** — 代码中的设计模式使用、异常处理策略、测试策略等

要求：
- 使用专业但不冗余的技术语言
- 指出设计中可能的问题或改进空间
- 使用 Markdown 格式，支持代码块引用关键结构
- 假设读者有 5 年以上开发经验
"""
    summary_text = f"项目名称：{project_name}\n\n文件列表及功能摘要：\n"
    for file in files_summary:
        summary_text += f"\n- 文件：`{file['path']}`\n"
        if file.get('classes'):
            summary_text += f"  类：{', '.join(file['classes'])}\n"
        if file.get('functions'):
            summary_text += f"  函数：{', '.join(file['functions'])}\n"
        if file.get('docstring_summary'):
            summary_text += f"  说明：{file['docstring_summary']}\n"

    try:
        response = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": summary_text}
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"专家模式解读生成失败：{str(e)}"


# ---- Batch processing functions (ThreadPoolExecutor parallelization) ----


def generate_ai_metadata_batch(
    snippets: list[tuple[str, str, str]],
    max_workers: int = 5
) -> list[dict]:
    """
    Process multiple code snippets in parallel using ThreadPoolExecutor.

    Args:
        snippets: List of (code_snippet, code_type, language) tuples
        max_workers: Max concurrent LLM API calls (default 5)

    Returns:
        List of result dicts in the same order as input. Failed items return empty dicts.
    """
    results = [None] * len(snippets)

    def process_item(idx: int, snippet: tuple[str, str, str]) -> None:
        code, ctype, lang = snippet
        try:
            results[idx] = generate_ai_metadata(code, ctype, lang)
        except Exception as e:
            print(f"[AI-Metadata-Batch] Item {idx} failed: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_item, i, snippet)
            for i, snippet in enumerate(snippets)
        ]
        concurrent.futures.wait(futures)

    return [r if r is not None else {} for r in results]


def generate_explanation_batch(
    snippets: list[tuple[str, str, str]],
    max_workers: int = 5
) -> list[dict]:
    """
    Process multiple code snippets in parallel using ThreadPoolExecutor.

    Args:
        snippets: List of (code_snippet, code_type, language) tuples
        max_workers: Max concurrent LLM API calls (default 5)

    Returns:
        List of result dicts in the same order as input. Failed items return empty dicts.
    """
    results = [None] * len(snippets)

    def process_item(idx: int, snippet: tuple[str, str, str]) -> None:
        code, ctype, lang = snippet
        try:
            results[idx] = generate_explanation(code, ctype, lang)
        except Exception as e:
            print(f"[Explanation-Batch] Item {idx} failed: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_item, i, snippet)
            for i, snippet in enumerate(snippets)
        ]
        concurrent.futures.wait(futures)

    return [r if r is not None else {} for r in results]


def generate_expert_analysis_batch(
    snippets: list[tuple[str, str, str]],
    max_workers: int = 5
) -> list[dict]:
    """
    Process multiple code snippets in parallel using ThreadPoolExecutor.

    Args:
        snippets: List of (code_snippet, code_type, language) tuples
        max_workers: Max concurrent LLM API calls (default 5)

    Returns:
        List of result dicts in the same order as input. Failed items return empty dicts.
    """
    results = [None] * len(snippets)

    def process_item(idx: int, snippet: tuple[str, str, str]) -> None:
        code, ctype, lang = snippet
        try:
            results[idx] = generate_expert_analysis(code, ctype, lang)
        except Exception as e:
            print(f"[Expert-Analysis-Batch] Item {idx} failed: {e}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(process_item, i, snippet)
            for i, snippet in enumerate(snippets)
        ]
        concurrent.futures.wait(futures)

    return [r if r is not None else {} for r in results]


# ---- Bulk processing functions (multi-snippet per LLM call) ----

BULK_AI_METADATA_SYSTEM_PROMPT = """
你是一个AI代码分析引擎。分析以下多个代码片段，输出包含所有分析结果的JSON数组。
输出必须是严格有效的JSON数组，不要包含任何其他文字。

每个元素是单个代码片段的分析结果，格式取决于代码类型：

对于函数(function)，格式：
{
  "purpose": "一句话功能描述（≤20字）",
  "inputs": [{"name": "参数名", "type": "精确类型", "description": "作用（≤15字）"}],
  "outputs": {"type": "返回类型", "description": "返回值说明"},
  "side_effects": ["副作用描述"]
}

对于类(class)，格式：
{
  "purpose": "一句话类职责描述（≤25字）",
  "interfaces": [{"name": "方法名", "type": "方法签名", "description": "方法作用"}]
}

重要规则：
- 不要使用比喻
- 类型信息必须精确
- 按照输入顺序输出分析结果
"""

BULK_EXPLANATION_SYSTEM_PROMPT = """
你是一个资深的全栈开发导师，现在需要帮助一个完全没有编程基础的初学者理解多个代码片段。
1. **小白模式**：完全禁用专业术语（如递归、闭包、异步）。如果必须使用，请立刻用生活中的例子比喻解释。
2. **逻辑拆解**：把代码想象成做菜的步骤，一步一步说明先做了什么，后做了什么。
3. **语气**：亲切、耐心，像给朋友讲故事一样。

分析以下多个代码片段，输出包含所有分析结果的JSON数组。
每个元素格式：
{
  "simple": "一句话大白话",
  "logic": "详细拆解（Markdown格式）"
}

输出必须是严格有效的JSON数组，不要包含任何其他文字。
"""

BULK_EXPERT_ANALYSIS_SYSTEM_PROMPT = """
你是一个资深代码审查专家。分析以下多个代码片段以技术角度输出结构化的分析结果。
输出必须是严格有效的JSON数组，不要包含任何其他文字。

每个元素是单个代码片段的分析结果，格式取决于代码类型：

对于函数(function)，格式：
{
  "purpose": "技术性功能描述（≤20字）",
  "tech_details": "技术实现细节，包括设计模式、算法复杂度、性能考量（≤100字）",
  "error_handling": "错误处理策略（≤50字）",
  "concurrency": "并发/异步处理说明（≤50字，无则写null）",
  "tradeoffs": "设计权衡和替代方案（≤50字）"
}

对于类(class)，格式：
{
  "purpose": "技术性类职责描述（≤25字）",
  "architecture": "类架构分析，设计模式、继承/组合关系（≤100字）",
  "responsibilities": "各方法职责划分和交互方式（≤100字）",
  "extension_points": "扩展点设计和开放接口分析（≤50字）"
}

重要规则：
- 使用技术性精确语言，面向有3年+经验的开发者
- 不要解释基本概念
- 按照输入顺序输出分析结果
"""


def _build_snippet_list_text(snippets: list[tuple[str, str, str]]) -> str:
    """Build the numbered snippet list text for bulk prompts."""
    lang_map = {"javascript": "JavaScript", "typescript": "TypeScript", "go": "Go", "java": "Java", "rust": "Rust", "python": "Python"}
    items = []
    for i, (code, ctype, lang) in enumerate(snippets, 1):
        lang_display = lang_map.get(lang, lang)
        label = f"{lang_display} {'函数' if ctype == 'function' else '类'}"
        items.append(f"[{i}] ({ctype}) [{label}]\n{code}")
    return f"分析以下{len(snippets)}个代码片段：\n\n" + "\n\n".join(items)


def _extract_json_array(content: str) -> list | None:
    """Extract a JSON array from LLM response text. Returns None on failure."""
    try:
        json_match = re.search(r'\[.*\]', content, re.DOTALL)
        if not json_match:
            return None
        parsed = json.loads(json_match.group())
        if isinstance(parsed, list):
            return parsed
        return None
    except (json.JSONDecodeError, Exception):
        return None


def generate_ai_metadata_bulk(
    snippets: list[tuple[str, str, str]],
    batch_size: int = 10
) -> list[dict]:
    """
    Process code snippets in batches, sending multiple snippets per LLM call.

    The prompt tells the LLM to analyze ALL snippets at once and return a JSON array.
    Falls back to per-item generate_ai_metadata calls on parse failure.

    Args:
        snippets: List of (code_snippet, code_type, language) tuples
        batch_size: Max snippets per LLM call (default 10)

    Returns:
        List of result dicts in the same order as input.
    """
    if not snippets:
        return []

    results = [None] * len(snippets)

    def process_batch(batch_snippets: list[tuple[str, str, str]], start_idx: int) -> None:
        user_prompt = _build_snippet_list_text(batch_snippets)
        try:
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": BULK_AI_METADATA_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
            )
            content = response.choices[0].message.content.strip()
            parsed = _extract_json_array(content)

            if parsed is None:
                raise ValueError("Failed to parse JSON array from response")

            for j, idx in enumerate(range(start_idx, start_idx + len(batch_snippets))):
                if j < len(parsed) and isinstance(parsed[j], dict):
                    results[idx] = parsed[j]
                else:
                    results[idx] = {}

        except Exception as e:
            print(f"[AI-Metadata-Bulk] Batch start_idx={start_idx} failed: {e}, falling back to individual calls")
            for j, (code, ctype, lang) in enumerate(batch_snippets):
                idx = start_idx + j
                try:
                    results[idx] = generate_ai_metadata(code, ctype, lang)
                except Exception as e2:
                    print(f"[AI-Metadata-Bulk] Fallback item {idx} failed: {e2}")
                    results[idx] = {}

    for i in range(0, len(snippets), batch_size):
        batch = snippets[i:i + batch_size]
        process_batch(batch, i)

    return [r if r is not None else {} for r in results]


def generate_explanation_bulk(
    snippets: list[tuple[str, str, str]],
    batch_size: int = 10
) -> list[dict]:
    """
    Process code snippets in batches, sending multiple snippets per LLM call.

    Falls back to per-item generate_explanation calls on parse failure.

    Args:
        snippets: List of (code_snippet, code_type, language) tuples
        batch_size: Max snippets per LLM call (default 10)

    Returns:
        List of result dicts in the same order as input.
    """
    if not snippets:
        return []

    results = [None] * len(snippets)

    def process_batch(batch_snippets: list[tuple[str, str, str]], start_idx: int) -> None:
        user_prompt = _build_snippet_list_text(batch_snippets)
        try:
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": BULK_EXPLANATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.5,
            )
            content = response.choices[0].message.content.strip()
            parsed = _extract_json_array(content)

            if parsed is None:
                raise ValueError("Failed to parse JSON array from response")

            for j, idx in enumerate(range(start_idx, start_idx + len(batch_snippets))):
                if j < len(parsed) and isinstance(parsed[j], dict):
                    results[idx] = parsed[j]
                else:
                    results[idx] = {}

        except Exception as e:
            print(f"[Explanation-Bulk] Batch start_idx={start_idx} failed: {e}, falling back to individual calls")
            for j, (code, ctype, lang) in enumerate(batch_snippets):
                idx = start_idx + j
                try:
                    results[idx] = generate_explanation(code, ctype, lang)
                except Exception as e2:
                    print(f"[Explanation-Bulk] Fallback item {idx} failed: {e2}")
                    results[idx] = {}

    for i in range(0, len(snippets), batch_size):
        batch = snippets[i:i + batch_size]
        process_batch(batch, i)

    return [r if r is not None else {} for r in results]


def generate_expert_analysis_bulk(
    snippets: list[tuple[str, str, str]],
    batch_size: int = 10
) -> list[dict]:
    """
    Process code snippets in batches, sending multiple snippets per LLM call.

    Falls back to per-item generate_expert_analysis calls on parse failure.

    Args:
        snippets: List of (code_snippet, code_type, language) tuples
        batch_size: Max snippets per LLM call (default 10)

    Returns:
        List of result dicts in the same order as input.
    """
    if not snippets:
        return []

    results = [None] * len(snippets)

    def process_batch(batch_snippets: list[tuple[str, str, str]], start_idx: int) -> None:
        user_prompt = _build_snippet_list_text(batch_snippets)
        try:
            response = client.chat.completions.create(
                model=config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": BULK_EXPERT_ANALYSIS_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.2,
            )
            content = response.choices[0].message.content.strip()
            parsed = _extract_json_array(content)

            if parsed is None:
                raise ValueError("Failed to parse JSON array from response")

            for j, idx in enumerate(range(start_idx, start_idx + len(batch_snippets))):
                if j < len(parsed) and isinstance(parsed[j], dict):
                    results[idx] = parsed[j]
                else:
                    results[idx] = {}

        except Exception as e:
            print(f"[Expert-Analysis-Bulk] Batch start_idx={start_idx} failed: {e}, falling back to individual calls")
            for j, (code, ctype, lang) in enumerate(batch_snippets):
                idx = start_idx + j
                try:
                    results[idx] = generate_expert_analysis(code, ctype, lang)
                except Exception as e2:
                    print(f"[Expert-Analysis-Bulk] Fallback item {idx} failed: {e2}")
                    results[idx] = {}

    for i in range(0, len(snippets), batch_size):
        batch = snippets[i:i + batch_size]
        process_batch(batch, i)

    return [r if r is not None else {} for r in results]