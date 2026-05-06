"""
Continue AI metadata fill for projects with low coverage.
Runs directly within the Docker container (bypasses HTTP timeout).

Uses parallel ThreadPoolExecutor for bulk LLM calls.
Batch of 10 functions per LLM call, 5 parallel workers = 50 funcs/cycle.
"""
import sys
import os
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.database import SessionLocal
from api import models


def _process_bulk_batch(args):
    """Process a sub-batch of functions via bulk LLM.
    Runs in its own thread with its own DB session."""
    func_objects, snippets = args
    from api.database import SessionLocal
    from api import models
    from api.llm_service import generate_ai_metadata_bulk

    db = SessionLocal()
    try:
        results = generate_ai_metadata_bulk(snippets, batch_size=len(snippets))
        processed = 0
        errors = 0
        for func_obj, ai_meta in zip(func_objects, results):
            try:
                func = db.query(models.Function).filter(
                    models.Function.id == func_obj.id
                ).first()
                if func and ai_meta and ai_meta.get("purpose"):
                    func.ai_purpose = ai_meta.get("purpose")
                    func.ai_inputs = ai_meta.get("inputs")
                    func.ai_outputs = ai_meta.get("outputs")
                    func.ai_side_effects = ai_meta.get("side_effects")
                    outputs = ai_meta.get("outputs", {})
                    if outputs and isinstance(outputs, dict):
                        func.return_type = outputs.get("type")
                    processed += 1
                else:
                    errors += 1
            except Exception:
                errors += 1
        db.commit()
        return processed, errors
    except Exception as e:
        db.rollback()
        return 0, len(func_objects)
    finally:
        db.close()


def fill_project_ai(project_ids, batch_size=10, max_workers=5, max_funcs=None):
    """Fill AI metadata in parallel using bulk LLM calls."""
    db = SessionLocal()
    try:
        projects = db.query(models.Project).filter(
            models.Project.id.in_(project_ids)
        ).all()

        if not projects:
            print(f"No projects found for IDs: {project_ids}")
            return

        print(f"Found {len(projects)} projects to process")

        for proj in projects:
            missing = (
                db.query(models.Function)
                .join(models.File)
                .filter(
                    models.File.project_id == proj.id,
                    models.Function.ai_purpose.is_(None),
                    models.Function.code_snippet.isnot(None),
                )
                .all()
            )

            if max_funcs and len(missing) > max_funcs:
                missing = missing[:max_funcs]

            if not missing:
                print(f"[{proj.name}] No missing AI metadata")
                continue

            print(f"[{proj.name}] Processing {len(missing)} functions "
                  f"(batch_size={batch_size}, workers={max_workers})...")
            start_time = time.time()
            total_processed = 0
            total_errors = 0

            # Build all func-snippet pairs
            all_funcs = []
            for func in missing:
                file_obj = db.query(models.File).filter(
                    models.File.id == func.file_id
                ).first()
                lang = file_obj.language if file_obj else "python"
                all_funcs.append((func, (func.code_snippet, "function", lang)))

            # Process in chunks for periodic commit
            chunk_size = batch_size * max_workers * 4  # e.g. 200
            for chunk_start in range(0, len(all_funcs), chunk_size):
                chunk = all_funcs[chunk_start:chunk_start + chunk_size]

                # Group into sub-batches of batch_size each
                sub_batches = []
                for i in range(0, len(chunk), batch_size):
                    batch_items = chunk[i:i + batch_size]
                    funcs = [item[0] for item in batch_items]
                    snippets = [item[1] for item in batch_items]
                    sub_batches.append((funcs, snippets))

                # Process sub-batches in parallel
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    futures = {executor.submit(_process_bulk_batch, sb): sb
                              for sb in sub_batches}
                    for future in as_completed(futures):
                        p, e = future.result()
                        total_processed += p
                        total_errors += e

                done = min(chunk_start + chunk_size, len(all_funcs))
                elapsed = time.time() - start_time
                rate = total_processed / elapsed if elapsed > 0 else 0
                print(f"  [{proj.name}] {done}/{len(all_funcs)} - "
                      f"{total_processed} ok, {total_errors} err "
                      f"({rate:.1f} func/s, {elapsed:.0f}s elapsed)")

            elapsed = time.time() - start_time
            print(f"[{proj.name}] COMPLETE: {total_processed} processed, "
                  f"{total_errors} errors in {elapsed:.0f}s")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Continue AI metadata fill")
    parser.add_argument("--project-ids", type=str, default="126,39,81,37",
                       help="Comma-separated project IDs")
    parser.add_argument("--batch-size", type=int, default=10,
                       help="Snippets per LLM call inside bulk")
    parser.add_argument("--workers", type=int, default=5,
                       help="Parallel bulk workers")
    parser.add_argument("--max-funcs", type=int, default=None,
                       help="Max functions per project (for testing)")
    args = parser.parse_args()

    project_ids = [int(x.strip()) for x in args.project_ids.split(",")]
    print(f"Projects: {project_ids}")
    print(f"Batch: {args.batch_size}/call, Workers: {args.workers}")

    fill_project_ai(project_ids, batch_size=args.batch_size,
                    max_workers=args.workers, max_funcs=args.max_funcs)
