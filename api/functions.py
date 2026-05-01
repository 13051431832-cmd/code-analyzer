from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from . import crud, models, schemas, database

router = APIRouter()

@router.post("/functions/{function_id}/regenerate", response_model=schemas.Function)
def regenerate_function(function_id: int, db: Session = Depends(database.get_db)):
    """重新生成某个函数的分析内容（根据项目模式选择对应生成方式）"""
    func = db.query(models.Function).filter(models.Function.id == function_id).first()
    if not func:
        raise HTTPException(status_code=404, detail="Function not found")

    # 获取项目模式
    file_obj = db.query(models.File).filter(models.File.id == func.file_id).first()
    project = db.query(models.Project).filter(models.Project.id == file_obj.project_id).first() if file_obj else None
    mode = project.analysis_mode if project else "ai"
    lang = func.language or "python"

    from . import llm_service

    if mode == "expert":
        result = llm_service.generate_expert_analysis(func.code_snippet, "function", lang)
        func.expert_purpose = result.get("purpose")
        func.expert_tech_details = result.get("tech_details")
        func.expert_error_handling = result.get("error_handling")
        func.expert_concurrency = result.get("concurrency")
        func.expert_tradeoffs = result.get("tradeoffs")
    elif mode == "ai":
        result = llm_service.generate_ai_metadata(func.code_snippet, "function", lang)
        func.ai_purpose = result.get("purpose", "")
        func.ai_inputs = result.get("inputs", [])
        func.ai_outputs = result.get("outputs", {})
        func.ai_side_effects = result.get("side_effects", [])
        func.return_type = result.get("outputs", {}).get("type") if result.get("outputs") else None
    else:  # beginner
        result = llm_service.generate_explanation(func.code_snippet, "function", lang)
        func.explanation_simple = result.get("simple", "")
        func.explanation_logic = result.get("logic", "")

    db.commit()
    db.refresh(func)
    return func