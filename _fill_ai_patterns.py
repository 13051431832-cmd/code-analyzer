"""
Backfill ai_patterns for existing classes using LLM classification.
Only updates the ai_patterns column — preserves existing ai_purpose and ai_interfaces.

Usage:
    python _fill_ai_patterns.py [--project-id N] [--batch-size 10] [--max-workers 5]
"""
import sys
import os
import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _process_batch(class_ids, batch_size, max_workers):
    """Process a batch of classes in parallel via LLM."""
    from api.database import SessionLocal
    from api import models
    from api.llm_service import generate_ai_metadata

    db = SessionLocal()
    try:
        processed = 0
        errors = 0

        for cls_id in class_ids:
            cls_obj = db.query(models.Class).filter(models.Class.id == cls_id).first()
            if not cls_obj or not cls_obj.code_snippet:
                errors += 1
                continue

            file_obj = db.query(models.File).filter(
                models.File.id == cls_obj.file_id
            ).first()
            lang = file_obj.language if file_obj else "python"

            try:
                ai_meta = generate_ai_metadata(cls_obj.code_snippet, "class", lang)
                patterns = ai_meta.get("patterns", []) if ai_meta else []
                if patterns:
                    cls_obj.ai_patterns = patterns
                    processed += 1
                else:
                    cls_obj.ai_patterns = []
                    processed += 1  # Mark as processed with empty array
            except Exception:
                errors += 1

        db.commit()
        return processed, errors
    finally:
        db.close()


def fill_patterns(project_id=None, batch_size=10, max_workers=5, max_classes=None):
    """Fill ai_patterns for classes missing them."""
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

        classes = query.all()
        if max_classes:
            classes = classes[:max_classes]
            total = len(classes)

        print(f"Backfilling patterns for {total} classes...")

        # Process in parallel batches
        class_ids = [c.id for c in classes]

        # Use ThreadPoolExecutor for parallel LLM calls
        total_processed = 0
        total_errors = 0
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            # Split into sub-batches per worker
            chunk_size = max(1, len(class_ids) // max_workers)
            for i in range(0, len(class_ids), chunk_size):
                chunk = class_ids[i:i + chunk_size]
                future = executor.submit(_process_batch, chunk, batch_size, 1)
                futures[future] = len(chunk)

            for future in as_completed(futures):
                processed, errors = future.result()
                total_processed += processed
                total_errors += errors
                elapsed = time.time() - start_time
                rate = total_processed / elapsed if elapsed > 0 else 0
                print(f"  Progress: {total_processed}/{total} "
                      f"({rate:.1f}/s) errors={total_errors}")

        elapsed = time.time() - start_time
        print(f"Done: {total_processed} classes processed "
              f"({total_errors} errors) in {elapsed:.0f}s")

        # Show coverage
        with_bases = db.query(models.Class).filter(
            models.Class.ai_patterns.isnot(None)
        ).count()
        total_classes = db.query(models.Class).count()
        print(f"Coverage: {with_bases}/{total_classes} classes have ai_patterns "
              f"({round(with_bases/total_classes*100, 1)}%)")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill ai_patterns for classes")
    parser.add_argument("--project-id", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--max-classes", type=int, default=None,
                        help="Limit number of classes to process")
    args = parser.parse_args()
    fill_patterns(args.project_id, args.batch_size, args.max_workers, args.max_classes)
