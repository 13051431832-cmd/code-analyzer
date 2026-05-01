"""
Test fixtures for code_analyzer three-mode system tests.

These tests run against the running Docker compose stack.
Usage: PYTHONPATH=/app docker compose exec -T api pytest tests/ -v
"""

import os
import sys

# Ensure /app is on the path
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

import pytest
from fastapi.testclient import TestClient

# Point to the running API service
os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("DATABASE_URL", "postgresql://code_analyzer:password@postgres:5432/code_analyzer_db"),
)
os.environ.setdefault("REDIS_URL", os.environ.get("REDIS_URL", "redis://redis:6379/0"))

from api.main import app


@pytest.fixture
def client():
    """FastAPI TestClient pointing at the running app."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sample_project_id(client) -> int:
    """Get the first project from the database, or skip if none exist."""
    response = client.get("/api/projects")
    assert response.status_code == 200
    projects = response.json()
    if not projects:
        pytest.skip("No projects in database — run an analysis first")
    return projects[0]["id"]


@pytest.fixture
def sample_function_id(client, sample_project_id) -> int:
    """Get the first function from the sample project."""
    response = client.get(f"/api/projects/{sample_project_id}/files")
    assert response.status_code == 200
    data = response.json()
    for file_obj in data.get("files", []):
        funcs = file_obj.get("functions", []) or []
        if funcs:
            return funcs[0]["id"]
    pytest.skip("No functions found in sample project")


@pytest.fixture
def mock_llm(monkeypatch):
    """Mock LLM calls to avoid real API costs during testing."""

    async def mock_chat(*args, **kwargs):
        class MockChoice:
            class MockMessage:
                content = '{"purpose": "test purpose", "inputs": [], "outputs": {}, "side_effects": []}'
            message = MockMessage()

        class MockResponse:
            choices = [MockChoice()]
        return MockResponse()

    monkeypatch.setattr("api.llm_service.client.chat.completions.create", mock_chat)
