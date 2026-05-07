"""
Backfill ai_patterns for existing classes using bulk LLM classification.
Sends multiple classes per LLM call for efficiency — patterns-only prompt.

Usage:
    python _fill_ai_patterns.py [--project-id N] [--batch-size 15] [--max-workers 5]
"""
import sys
import os
import argparse
import time
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


PATTERNS_BULK_SYSTEM_PROMPT = """你是一个代码架构分析引擎。分析以下多个类的代码片段，判断它们使用了哪些架构/设计模式。
输出必须是严格有效的JSON数组，每个元素对应一个类，不要包含任何其他文字。

每个元素的格式：
{
  "patterns": [
    {"pattern": "模式名", "confidence": "high|medium|low", "evidence": "证据（≤30字）"}
  ]
}

如果类不匹配任何已知模式，返回空数组：{"patterns": []}

已知模式分类法（LLM可额外添加自定义模式）：

创建型：
- Factory - 创建对象的工厂方法或工厂类
- Abstract Factory - 创建一系列相关对象的抽象工厂
- Builder - 分步骤构建复杂对象
- Singleton - 全局单例模式
- Prototype - 通过克隆创建对象
- Dependency Injection - 依赖注入容器或注入点

结构型：
- Adapter - 接口适配/转换
- Decorator - 装饰器模式，动态添加职责
- Facade - 外观模式，简化复杂子系统接口
- Proxy - 代理模式，控制访问
- Composite - 组合模式，树形结构
- Bridge - 桥接模式，分离抽象与实现

行为型：
- Strategy - 策略模式，算法可替换
- Observer - 观察者模式，事件监听
- Command - 命令模式，请求封装
- Template Method - 模板方法模式
- Chain of Responsibility - 责任链模式
- Mediator - 中介者模式
- State - 状态模式
- Visitor - 访问者模式
- Iterator - 迭代器模式

架构型：
- MVC/MVP/MVVM - Model-View-* 架构
- Repository - 仓储模式，数据访问抽象
- Service Layer - 服务层模式
- DTO - 数据传输对象
- Middleware - 中间件模式
- Pub/Sub - 发布订阅模式
- Provider - 提供者模式
- ORM/Active Record - 对象关系映射

通用型：
- Exception/Error - 异常或错误类
- Test Case - 测试用例类
- Config/Configuration - 配置类
- Utility/Helper - 工具类/辅助类
- Enum/Enumeration - 枚举类型
- Data Object/Struct - 纯数据载体（无行为）
- Event - 事件类
- Wrapper/Delegation - 包装/委托类
- Callback/Handler - 回调/处理器类

规则：
- confidence: high=明确是该模式, medium=大概率是, low=可能是
- evidence: 从代码中引用关键标识符（类名、方法名、继承关系）
- 只标记有明确证据的模式，不要猜测
- 按输入顺序输出，每个类一个元素"""


def _extract_json_array(content: str) -> list | None:
    """Extract a JSON array from LLM response text."""
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


def _validate_patterns(patterns):
    """Validate and normalize patterns list."""
    if not isinstance(patterns, list):
        return []
    valid_confidence = {"high", "medium", "low"}
    result = []
    for p in patterns:
        if isinstance(p, dict) and "pattern" in p:
            conf = str(p.get("confidence", "medium"))
            if conf not in valid_confidence:
                conf = "medium"
            result.append({
                "pattern": str(p.get("pattern", "")),
                "confidence": conf,
                "evidence": str(p.get("evidence", "")),
            })
    return result


def _process_batch_bulk(class_data: list[tuple[int, str, str]], batch_size: int):
    """Process classes in bulk via LLM — one call per batch_size classes."""
    from api.database import SessionLocal
    from api import models
    from api.config import config
    from openai import OpenAI

    client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    db = SessionLocal()

    try:
        processed = 0
        errors = 0

        for i in range(0, len(class_data), batch_size):
            batch = class_data[i:i + batch_size]

            # Build prompt with numbered class snippets
            items = []
            for j, (cls_id, code, lang) in enumerate(batch, 1):
                items.append(f"[{j}] ({lang})\n{code}")
            user_prompt = f"分析以下{len(batch)}个类：\n\n" + "\n\n".join(items)

            try:
                response = client.chat.completions.create(
                    model=config.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": PATTERNS_BULK_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.1,
                )
                content = response.choices[0].message.content.strip()
                parsed = _extract_json_array(content)

                if parsed is None:
                    raise ValueError("Failed to parse JSON array")

                # Update database for each class in the batch
                for j, (cls_id, _, _) in enumerate(batch):
                    cls_obj = db.query(models.Class).filter(models.Class.id == cls_id).first()
                    if cls_obj:
                        if j < len(parsed) and isinstance(parsed[j], dict):
                            raw_patterns = parsed[j].get("patterns", [])
                        else:
                            raw_patterns = []
                        cls_obj.ai_patterns = _validate_patterns(raw_patterns)
                        processed += 1
                    else:
                        errors += 1

                db.commit()

            except Exception as e:
                print(f"  [Batch] classes {batch[0][0]}-{batch[-1][0]} failed: {e}")
                errors += len(batch)
                db.rollback()
                # Fallback: set empty patterns for failed batch
                for cls_id, _, _ in batch:
                    cls_obj = db.query(models.Class).filter(models.Class.id == cls_id).first()
                    if cls_obj:
                        cls_obj.ai_patterns = []
                db.commit()

        return processed, errors
    finally:
        db.close()


def fill_patterns(project_id=None, batch_size=15, max_workers=5, max_classes=None):
    """Fill ai_patterns for classes missing them, using bulk LLM calls."""
    from api.database import SessionLocal
    from api import models

    db = SessionLocal()
    try:
        query = db.query(models.Class).filter(models.Class.ai_patterns.is_(None))
        if project_id:
            query = query.join(
                models.File, models.File.id == models.Class.file_id
            ).filter(models.File.project_id == project_id)

        total = query.count()
        if total == 0:
            print("No classes need pattern backfilling")
            return

        print(f"Total classes needing patterns: {total}")
        print(f"Batch size: {batch_size}, Workers: {max_workers}")
        print(f"Estimated LLM calls: {total // batch_size + 1}")

        classes = query.all()
        if max_classes:
            classes = classes[:max_classes]
            total = len(classes)
            print(f"Limited to {total} classes")

        # Build class data: (id, code_snippet, language)
        class_data = []
        skipped = 0
        for c in classes:
            if not c.code_snippet or len(c.code_snippet.strip()) < 10:
                # Mark empty/trivial classes as processed with empty patterns
                c.ai_patterns = []
                skipped += 1
                continue
            file_obj = db.query(models.File).filter(models.File.id == c.file_id).first()
            lang = file_obj.language if file_obj else "python"
            class_data.append((c.id, c.code_snippet, lang))

        if skipped:
            db.commit()
            print(f"Skipped {skipped} classes with insufficient code (stored empty patterns)")

        if not class_data:
            print("No classes with valid code snippets to process")
            return

        print(f"Processing {len(class_data)} classes with code snippets...")

        # Split into worker chunks
        chunk_size = max(1, len(class_data) // max_workers)
        chunks = []
        for i in range(0, len(class_data), chunk_size):
            chunks.append(class_data[i:i + chunk_size])

        total_processed = 0
        total_errors = 0
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for chunk in chunks:
                future = executor.submit(_process_batch_bulk, chunk, batch_size)
                futures[future] = len(chunk)

            for future in as_completed(futures):
                processed, errors = future.result()
                total_processed += processed
                total_errors += errors
                elapsed = time.time() - start_time
                rate = total_processed / elapsed if elapsed > 0 else 0
                pct = (total_processed / len(class_data)) * 100
                print(f"  Progress: {total_processed}/{len(class_data)} "
                      f"({pct:.1f}%) {rate:.1f}/s errors={total_errors}")

        elapsed = time.time() - start_time
        print(f"\nDone: {total_processed} classes processed "
              f"({total_errors} errors) in {elapsed:.0f}s "
              f"({total_processed/elapsed:.1f}/s avg)")

        # Show coverage
        with_patterns = db.query(models.Class).filter(
            models.Class.ai_patterns.isnot(None)
        ).count()
        total_classes = db.query(models.Class).count()
        print(f"Coverage: {with_patterns}/{total_classes} classes have ai_patterns "
              f"({round(with_patterns/total_classes*100, 1)}%)")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill ai_patterns for classes (bulk LLM)")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=15,
                        help="Classes per LLM call (default: 15)")
    parser.add_argument("--max-workers", type=int, default=5,
                        help="Parallel workers (default: 5)")
    parser.add_argument("--max-classes", type=int, default=None,
                        help="Limit number of classes to process")
    args = parser.parse_args()
    fill_patterns(args.project_id, args.batch_size, args.max_workers, args.max_classes)
