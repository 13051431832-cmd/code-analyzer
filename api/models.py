from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from pgvector.sqlalchemy import Vector

Base = declarative_base()


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    repo_url = Column(Text)
    language = Column(String(50))
    last_analyzed_commit = Column(String(64))
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())

    overview_analysis = Column(Text, nullable=True)
    overview_analysis_updated_at = Column(DateTime, nullable=True)

    analysis_mode = Column(String(20), default="ai")
    """分析模式: 'beginner' = 小白模式, 'expert' = 专家模式, 'ai' = AI模式（默认）"""


class File(Base):
    __tablename__ = "files"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(Text, nullable=False)
    file_hash = Column(String(64))
    size_bytes = Column(Integer)
    language = Column(String(50))
    created_at = Column(DateTime, server_default=func.now())
    dependencies = Column(JSONB, nullable=True)

    __table_args__ = (Index("ix_files_project_path", "project_id", "file_path", unique=True),)


class Function(Base):
    __tablename__ = "functions"

    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    language = Column(String(50), nullable=True)
    signature = Column(Text)
    start_line = Column(Integer)
    end_line = Column(Integer)
    docstring = Column(Text)
    created_at = Column(DateTime, server_default=func.now())
    code_snippet = Column(Text, nullable=True)

    # AI 解释字段 (human-oriented, kept for backward compatibility)
    explanation_simple = Column(Text, nullable=True)
    explanation_logic = Column(Text, nullable=True)

    # ---- AI-oriented fields (for AI consumption, not human) ----
    ai_purpose = Column(Text, nullable=True)
    """One-line structured description of what this function does, for AI."""

    ai_inputs = Column(JSONB, nullable=True)
    """JSON array: [{"name": str, "type": str, "description": str}], parameter descriptions for AI."""

    ai_outputs = Column(JSONB, nullable=True)
    """JSON: {"type": str, "description": str}, what this function returns."""

    ai_side_effects = Column(JSONB, nullable=True)
    """JSON array: [str], side effects, state changes, errors thrown, I/O operations."""

    return_type = Column(String(255), nullable=True)
    """Parsed return type string (e.g. 'int', 'User', 'Promise<User>')."""

    # ---- Expert mode fields (for experienced developers) ----
    expert_purpose = Column(Text, nullable=True)
    """Technical one-line description of the function."""
    expert_tech_details = Column(Text, nullable=True)
    """Technical implementation details: design patterns, algorithms, performance considerations."""
    expert_error_handling = Column(Text, nullable=True)
    """Error handling strategy and edge cases."""
    expert_concurrency = Column(Text, nullable=True)
    """Concurrency/async handling details."""
    expert_tradeoffs = Column(Text, nullable=True)
    """Design trade-offs and alternative approaches."""

    # --- LLM processing fields ---
    code_hash = Column(String(64), nullable=True)

    # LLM 相关字段
    llm_description = Column(Text, nullable=True)
    llm_issues = Column(JSONB, nullable=True)
    llm_processed = Column(Boolean, default=False)
    embedding_id = Column(String(100), nullable=True)

    # 关联函数引用 (JSONB: [{id, name, file_path, project_name}])
    related_functions = Column(JSONB, nullable=True)

    # 向量嵌入 (pgvector, 1536维 — text-embedding-3-small默认维度)
    embedding = Column(Vector(1536), nullable=True)


class Class(Base):
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    start_line = Column(Integer)
    end_line = Column(Integer)
    docstring = Column(Text)

    code_snippet = Column(Text, nullable=True)

    # AI 解释字段 (human-oriented, kept for backward compatibility)
    explanation_simple = Column(Text, nullable=True)
    explanation_architecture = Column(Text, nullable=True)

    # ---- AI-oriented fields ----
    ai_purpose = Column(Text, nullable=True)
    ai_interfaces = Column(JSONB, nullable=True)
    """JSON: [{"name": str, "type": str, "description": str}], class methods/interfaces relevant for AI."""

    # ---- Expert mode fields (for experienced developers) ----
    expert_purpose = Column(Text, nullable=True)
    """Technical one-line description of the class."""
    expert_architecture = Column(Text, nullable=True)
    """Class architecture and design patterns used."""
    expert_responsibilities = Column(Text, nullable=True)
    """Responsibilities of each method and their interactions."""
    expert_extension_points = Column(Text, nullable=True)
    """Extension points and interface design."""


class FunctionRelationship(Base):
    """函数间关系表：追踪调用、导入、继承等关系"""
    __tablename__ = "function_relationships"

    id = Column(Integer, primary_key=True)
    source_function_id = Column(Integer, ForeignKey("functions.id", ondelete="CASCADE"), nullable=False, index=True)
    target_function_name = Column(String(255), nullable=False, index=True)
    target_file_id = Column(Integer, ForeignKey("files.id", ondelete="SET NULL"), nullable=True)
    relationship_type = Column(String(50), nullable=False, index=True)  # CALLS, IMPORTS, EXTENDS
    confidence = Column(Integer, default=5)  # 0-10 置信度
    context_line = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    status = Column(String(20), nullable=False, default="pending")
    current_step = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error_message = Column(Text)
    retry_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())

    # 进度相关字段
    progress_percent = Column(Integer, default=0)  # 进度百分比 0-100

    # 断点续传相关字段
    processed_files = Column(JSONB, default=[])  # 已处理的文件列表
    last_processed_file = Column(String(500))  # 最后处理的文件
    total_files = Column(Integer, default=0)  # 总文件数
    checkpoint_data = Column(JSONB)  # 其他检查点数据