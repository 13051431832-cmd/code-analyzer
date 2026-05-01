from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime

# ---------- Project ----------
class ProjectBase(BaseModel):
    name: str
    repo_url: Optional[str] = None
    language: Optional[str] = None

class ProjectCreate(ProjectBase):
    pass

class Project(ProjectBase):
    id: int
    overview_analysis: Optional[str] = None
    analysis_mode: str = "ai"
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        orm_mode = True

# ---------- File ----------
class FileBase(BaseModel):
    file_path: str
    language: Optional[str] = None
    size_bytes: Optional[int] = None

class File(FileBase):
    id: int
    project_id: int
    functions: List['Function'] = []

    class Config:
        orm_mode = True

# ---------- Function ----------
class FunctionBase(BaseModel):
    name: str
    signature: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    docstring: Optional[str] = None
    code_snippet: Optional[str] = None
    language: Optional[str] = None

class Function(FunctionBase):
    id: int
    file_id: int
    explanation_simple: Optional[str] = None
    explanation_logic: Optional[str] = None
    ai_purpose: Optional[str] = None
    ai_inputs: Optional[Any] = None
    ai_outputs: Optional[Any] = None
    ai_side_effects: Optional[Any] = None
    return_type: Optional[str] = None
    expert_purpose: Optional[str] = None
    expert_tech_details: Optional[str] = None
    expert_error_handling: Optional[str] = None
    expert_concurrency: Optional[str] = None
    expert_tradeoffs: Optional[str] = None
    llm_description: Optional[str] = None
    llm_issues: Optional[Any] = None
    llm_processed: bool = False

    class Config:
        orm_mode = True

# ---------- AnalysisTask ----------
class AnalysisTask(BaseModel):
    id: int
    project_id: int
    status: str
    current_step: Optional[str] = None
    progress_percent: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    class Config:
        orm_mode = True

# 解决循环引用
File.update_forward_refs()