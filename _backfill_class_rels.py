"""
Backfill class.base_classes and class_relationships by re-parsing files.
Reads files from the local filesystem and extracts extends/implements
using the existing parsers, then writes to Class.base_classes JSONB
and class_relationships table.

Usage:
    python _backfill_class_rels.py [--project-id N]
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.database import SessionLocal
from api import models
from api.parsers import detect_and_parse


def backfill_class_rels(project_id: int | None = None):
    db = SessionLocal()
    try:
        query = db.query(models.Class).filter(
            models.Class.base_classes.is_(None)
        )
        if project_id:
            query = query.join(
                models.File, models.File.id == models.Class.file_id
            ).filter(models.File.project_id == project_id)

        classes = query.all()
        if not classes:
            print("No classes need backfilling")
            return

        # Group by file for efficient parsing
        file_ids = list(set(c.file_id for c in classes))
        print(f"Backfilling class relationships for {len(classes)} classes in {len(file_ids)} files...")

        updated = 0
        skipped = 0
        for i, file_id in enumerate(file_ids):
            file_obj = db.query(models.File).filter(models.File.id == file_id).first()
            if not file_obj:
                continue

            project = db.query(models.Project).filter(
                models.Project.id == file_obj.project_id
            ).first()
            if not project or not project.repo_url:
                continue

            # Construct local path
            repo_dir = os.path.join("/repos", project.name.replace(" ", "_"))
            if not os.path.isdir(repo_dir):
                continue

            full_path = os.path.join(repo_dir, file_obj.file_path)
            if not os.path.isfile(full_path):
                continue

            try:
                parse_result = detect_and_parse(full_path)
            except Exception:
                continue

            extends = parse_result.get("extends", [])
            if not extends:
                continue

            # Group extends by class name
            extends_by_class: dict[str, list[dict]] = {}
            for ext in extends:
                extends_by_class.setdefault(ext["class"], []).append(ext)

            # Update classes in this file
            file_classes = db.query(models.Class).filter(
                models.Class.file_id == file_id,
                models.Class.base_classes.is_(None),
            ).all()

            for cls in file_classes:
                cls_extends = extends_by_class.get(cls.name, [])
                if not cls_extends:
                    continue

                base_classes = [{"name": e["parent"], "line": e.get("line")} for e in cls_extends]
                cls.base_classes = base_classes
                updated += 1

                # Create class_relationships
                for ext in cls_extends:
                    try:
                        existing = db.query(models.ClassRelationship).filter(
                            models.ClassRelationship.source_class_id == cls.id,
                            models.ClassRelationship.target_class_name == ext["parent"],
                            models.ClassRelationship.relationship_type == "EXTENDS",
                        ).first()
                        if not existing:
                            rel = models.ClassRelationship(
                                source_class_id=cls.id,
                                target_class_name=ext["parent"],
                                relationship_type="EXTENDS",
                                confidence=5,
                                context_line=ext.get("line"),
                            )
                            db.add(rel)
                    except Exception:
                        pass

            if (i + 1) % 500 == 0:
                db.commit()
                print(f"  Progress: {i+1}/{len(file_ids)} files ({updated} classes updated)")

        db.commit()
        print(f"Done: {updated} classes updated, {skipped} skipped")

        # Show final coverage
        total = db.query(models.Class).count()
        with_bases = db.query(models.Class).filter(
            models.Class.base_classes.isnot(None)
        ).count()
        with_rel = db.query(models.ClassRelationship).count()
        print(f"Coverage: {with_bases}/{total} classes have base_classes ({round(with_bases/total*100, 1)}%)")
        print(f"class_relationships rows: {with_rel}")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill class relationships")
    parser.add_argument("--project-id", type=int, default=None)
    args = parser.parse_args()
    backfill_class_rels(args.project_id)
