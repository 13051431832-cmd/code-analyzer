"""
Backfill file.dependencies for all files by re-parsing imports.
Reads files from the local filesystem and extracts import statements
using the existing parsers, then writes to file.dependencies JSONB.

Usage:
    python _backfill_file_deps.py [--project-id N]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.database import SessionLocal
from api import models
from api.parsers import detect_and_parse


def backfill_file_deps(project_id: int | None = None):
    db = SessionLocal()
    try:
        query = db.query(models.File).filter(
            models.File.dependencies.is_(None)
        )
        if project_id:
            query = query.filter(models.File.project_id == project_id)

        files = query.all()
        if not files:
            print("No files need backfilling")
            return

        print(f"Backfilling dependencies for {len(files)} files...")
        updated = 0
        skipped = 0
        for i, file_obj in enumerate(files):
            project = db.query(models.Project).filter(
                models.Project.id == file_obj.project_id
            ).first()
            if not project or not project.repo_url:
                skipped += 1
                continue

            # Construct local path
            repo_dir = os.path.join(
                "/repos",
                project.name.replace(" ", "_"),
            )
            if not os.path.isdir(repo_dir):
                skipped += 1
                continue

            full_path = os.path.join(repo_dir, file_obj.file_path)
            if not os.path.isfile(full_path):
                skipped += 1
                continue

            try:
                parse_result = detect_and_parse(full_path)
                if parse_result.get("imports"):
                    file_obj.dependencies = {
                        "imports": [
                            {"source": imp["target"], "line": imp["line"]}
                            for imp in parse_result["imports"]
                        ]
                    }
                    updated += 1
            except Exception:
                skipped += 1
                continue

            if (i + 1) % 500 == 0:
                db.commit()
                print(f"  Progress: {i+1}/{len(files)} ({updated} updated, {skipped} skipped)")

        db.commit()
        print(f"Done: {updated} files updated, {skipped} skipped")

        # Show final coverage
        total = db.query(models.File).count()
        with_deps = db.query(models.File).filter(
            models.File.dependencies.isnot(None)
        ).count()
        print(f"Coverage: {with_deps}/{total} ({round(with_deps/total*100, 1)}%)")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill file dependencies")
    parser.add_argument("--project-id", type=int, default=None)
    args = parser.parse_args()
    backfill_file_deps(args.project_id)
