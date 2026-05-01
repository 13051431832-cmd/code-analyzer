from sqlalchemy.orm import Session
from . import models


def generate_project_report(db: Session, project_id: int, output_path: str):
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise ValueError("Project not found")

    files = db.query(models.File).filter(models.File.project_id == project_id).all()

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"# 代码分析报告: {project.name}\n\n")
        f.write(f"**仓库**: {project.repo_url}\n")
        f.write(f"**语言**: {project.language}\n")

        # 安全地获取更新时间
        updated_time = project.updated_at or project.created_at
        f.write(f"**分析时间**: {updated_time}\n\n")

        f.write("## 项目概览\n\n")
        f.write(f"- 文件总数: {len(files)}\n")

        total_functions = 0
        total_classes = 0
        for file in files:
            func_count = db.query(models.Function).filter(models.Function.file_id == file.id).count()
            class_count = db.query(models.Class).filter(models.Class.file_id == file.id).count()
            total_functions += func_count
            total_classes += class_count
        f.write(f"- 函数总数: {total_functions}\n")
        f.write(f"- 类总数: {total_classes}\n\n")

        f.write("## 文件列表\n\n")
        for file in files:
            f.write(f"### {file.file_path}\n")
            funcs = db.query(models.Function).filter(models.Function.file_id == file.id).all()
            classes = db.query(models.Class).filter(models.Class.file_id == file.id).all()
            if classes:
                f.write("#### 类\n")
                for cls in classes:
                    f.write(f"- **{cls.name}** (行 {cls.start_line}-{cls.end_line})\n")
                    if cls.docstring:
                        f.write(f"  - {cls.docstring[:100]}\n")
                    if cls.explanation_simple:
                        f.write(f"  - 💡 {cls.explanation_simple[:100]}\n")
            if funcs:
                f.write("#### 函数\n")
                for func in funcs:
                    f.write(f"- `{func.signature}` (行 {func.start_line}-{func.end_line})\n")
                    if func.docstring:
                        f.write(f"  - {func.docstring[:100]}\n")
                    if func.explanation_simple:
                        f.write(f"  - 💡 {func.explanation_simple[:100]}\n")
            f.write("\n")

    return output_path