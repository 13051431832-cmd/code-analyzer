"""
Tests for the three-mode analysis system (ai / beginner / expert).

Prerequisites:
- Docker compose stack is running (docker-compose up -d)
- At least one project has been analyzed

Run with:
    docker-compose exec api pytest tests/ -v
"""

import pytest


# ── Mode switching ─────────────────────────────────────────


class TestProjectMode:
    """Project-level mode management."""

    def test_project_list_includes_mode(self, client):
        """Project listing should include analysis_mode field."""
        response = client.get("/api/projects")
        assert response.status_code == 200
        projects = response.json()
        assert isinstance(projects, list)
        if projects:
            assert "analysis_mode" in projects[0]

    def test_project_file_detail_includes_mode(self, client, sample_project_id):
        """GET /projects/{id}/files should return analysis_mode."""
        response = client.get(f"/api/projects/{sample_project_id}/files")
        assert response.status_code == 200
        data = response.json()
        assert "analysis_mode" in data
        assert data["analysis_mode"] in ("beginner", "expert", "ai")

    def test_switch_project_mode(self, client, sample_project_id):
        """Switch to each valid mode and verify."""
        for mode in ("beginner", "expert", "ai"):
            response = client.put(
                f"/api/projects/{sample_project_id}/mode",
                params={"mode": mode},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["analysis_mode"] == mode

    def test_switch_invalid_mode(self, client, sample_project_id):
        """Invalid mode should return 400."""
        response = client.put(
            f"/api/projects/{sample_project_id}/mode",
            params={"mode": "invalid"},
        )
        assert response.status_code == 400

    def test_mode_switch_full_reanalysis(self, client, sample_project_id):
        """Switch mode with full_reanalysis=True should return task_id."""
        response = client.put(
            f"/api/projects/{sample_project_id}/mode",
            params={"mode": "ai", "full_reanalysis": True},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["full_reanalysis"] is True
        assert "task_id" in data


# ── Search / Detail endpoints ──────────────────────────────


class TestExpertFieldsVisibility:
    """Expert and beginner fields should appear in detail/search endpoints."""

    def test_search_includes_expert_fields(self, client, sample_project_id):
        """search_code() results should include expert_* fields."""
        response = client.get("/api/search", params={"q": "def "})
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", data.get("functions", []))
        if results:
            expert_fields = [
                "expert_purpose", "expert_tech_details",
                "expert_error_handling", "expert_concurrency", "expert_tradeoffs",
            ]
            for field in expert_fields:
                assert field in results[0], f"Missing field: {field}"

    def test_search_includes_function_expert_fields(self, client, sample_project_id):
        """search should include function expert_* fields in results."""
        response = client.get("/api/search", params={"q": "def "})
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", [])
        if results:
            func_expert_fields = [
                "expert_purpose", "expert_tech_details",
                "expert_error_handling", "expert_concurrency", "expert_tradeoffs",
            ]
            for field in func_expert_fields:
                assert field in results[0], f"Missing function expert field: {field}"

    def test_function_detail_includes_expert_fields(self, client, sample_project_id):
        """GET /functions/{id}/detail should include expert_* and explanation_* fields."""
        # Get a function id from the project
        resp = client.get(f"/api/projects/{sample_project_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        target_func = None
        for file_obj in data.get("files", []):
            funcs = file_obj.get("functions", []) or []
            if funcs:
                target_func = funcs[0]
                break

        if not target_func:
            pytest.skip("No functions found")

        response = client.get(f"/api/functions/{target_func['id']}/detail")
        assert response.status_code == 200
        func = response.json()

        # All three modes' fields should be present in the schema
        for field in ("expert_purpose", "explanation_simple", "ai_purpose"):
            assert field in func, f"Missing field: {field}"

    def test_class_detail_includes_expert_fields(self, client, sample_project_id):
        """GET /classes/{id} should include expert_* fields."""
        # Find a class in the project
        resp = client.get(f"/api/projects/{sample_project_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        target_class = None
        for file_obj in data.get("files", []):
            classes = file_obj.get("classes", []) or []
            if classes:
                target_class = classes[0]
                break

        if not target_class:
            pytest.skip("No classes found")

        response = client.get(f"/api/classes/{target_class['id']}")
        assert response.status_code == 200
        cls_data = response.json()
        for field in ("expert_purpose", "expert_architecture", "ai_purpose"):
            assert field in cls_data, f"Missing field: {field}"


# ── AI search returns AI-only ──────────────────────────────


class TestAiSearchExcludesModeFields:
    """AI-optimized search should NOT return beginner/expert fields."""

    def test_ai_search_has_ai_fields_only(self, client):
        """ai_search results should contain nested ai object, not flat expert_* fields."""
        response = client.get("/api/ai/search", params={"q": "def "})
        assert response.status_code == 200
        data = response.json()
        results = data.get("results", [])
        if results:
            first = results[0]
            # AI fields are nested under "ai" key
            assert "ai" in first, "Missing 'ai' key"
            for field in ("purpose", "inputs", "outputs", "side_effects"):
                assert field in first["ai"], f"Missing AI field: ai.{field}"
            # Expert fields should NOT be top-level in AI search
            for field in ("expert_purpose", "expert_tech_details", "explanation_simple"):
                assert field not in first, f"AI search should not include flat field: {field}"

    def test_ai_context_has_ai_fields(self, client, sample_project_id):
        """get_ai_context should return AI-oriented fields."""
        # Get a function id
        resp = client.get(f"/api/projects/{sample_project_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        target_func = None
        for file_obj in data.get("files", []):
            funcs = file_obj.get("functions", []) or []
            if funcs:
                target_func = funcs[0]
                break

        if not target_func:
            pytest.skip("No functions found")

        response = client.get(f"/api/ai/functions/{target_func['id']}/context")
        assert response.status_code == 200
        context = response.json()
        # AI context nests fields under "ai" key
        assert "ai" in context
        for field in ("purpose", "inputs", "outputs", "side_effects"):
            assert field in context["ai"], f"Missing AI context field: ai.{field}"


# ── Missing summary ────────────────────────────────────────


class TestMissingSummary:
    """Re-analyze missing summary should track mode-specific gaps."""

    def test_missing_summary_includes_mode_fields(self, client):
        """GET /reanalyze/missing-summary should include expert/beginner tracking."""
        response = client.get("/api/reanalyze/missing-summary")
        assert response.status_code == 200
        data = response.json()
        summary = data.get("summary", {})
        for field in (
            "total_missing_beginner_explanations",
            "total_missing_expert_analyses",
            "total_missing_class_beginner_explanations",
            "total_missing_class_expert_analyses",
        ):
            assert field in summary, f"Missing summary field: {field}"

    def test_missing_summary_filter_by_mode(self, client):
        """Filter by mode should work."""
        for mode in ("beginner", "expert", "ai"):
            response = client.get("/api/reanalyze/missing-summary", params={"mode": mode})
            assert response.status_code == 200

    def test_missing_summary_has_analysis_mode_per_project(self, client):
        """Each project in the summary should report its analysis_mode."""
        response = client.get("/api/reanalyze/missing-summary")
        assert response.status_code == 200
        data = response.json()
        for project in data.get("projects", []):
            assert "analysis_mode" in project
            assert project["analysis_mode"] in ("beginner", "expert", "ai")


# ── Regenerate endpoint ────────────────────────────────────


class TestRegenerateEndpoint:
    """Function regenerate endpoint should respect project mode."""

    def test_regenerate_function(self, client, sample_project_id):
        """POST /functions/{id}/regenerate should work."""
        # Get a function with code_snippet
        resp = client.get(f"/api/projects/{sample_project_id}/files")
        assert resp.status_code == 200
        data = resp.json()
        target_func = None
        for file_obj in data.get("files", []):
            functions = file_obj.get("functions", []) or []
            for f in functions:
                if f.get("code_snippet"):
                    target_func = f
                    break
            if target_func:
                break

        if not target_func:
            pytest.skip("No function with code_snippet found")

        response = client.post(f"/api/functions/{target_func['id']}/regenerate")
        assert response.status_code == 200
        result = response.json()
        assert result["id"] == target_func["id"]

    def test_regenerate_nonexistent_function(self, client):
        """Regenerate nonexistent function should return 404."""
        response = client.post("/api/functions/999999/regenerate")
        assert response.status_code == 404


# ── Project overview mode-awareness ────────────────────────


class TestProjectOverview:
    """Project overview should be mode-aware."""

    def test_regenerate_overview_with_mode(self, client, sample_project_id):
        """POST /reanalyze/regenerate-overview with mode parameter."""
        for mode in ("beginner", "expert", "ai"):
            response = client.post(
                f"/api/reanalyze/regenerate-overview/{sample_project_id}",
                params={"mode": mode},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["mode"] == mode
            assert data["status"] == "regenerated"

    def test_regenerate_overview_defaults_to_project_mode(self, client, sample_project_id):
        """Regenerate overview without mode should use project's current mode."""
        response = client.post(
            f"/api/reanalyze/regenerate-overview/{sample_project_id}",
        )
        assert response.status_code == 200
        data = response.json()
        assert "mode" in data

    def test_regenerate_overview_invalid_mode(self, client, sample_project_id):
        """Invalid mode should return 400."""
        response = client.post(
            f"/api/reanalyze/regenerate-overview/{sample_project_id}",
            params={"mode": "invalid"},
        )
        assert response.status_code == 400

    def test_project_overview_endpoint(self, client, sample_project_id):
        """GET /projects/{id}/overview should return markdown."""
        response = client.get(f"/api/projects/{sample_project_id}/overview")
        assert response.status_code == 200
        data = response.json()
        assert "overview" in data


# ── Batch mode-aware endpoints ─────────────────────────────


class TestBatchModeAwareEndpoints:
    """Batch regeneration and migration endpoints."""

    def test_fill_mode_content(self, client, sample_project_id):
        """POST /reanalyze/project/{id}/fill-mode-content should work."""
        response = client.post(
            f"/api/reanalyze/project/{sample_project_id}/fill-mode-content",
            params={"limit": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["analysis_mode"] in ("beginner", "expert", "ai")
        assert "summary" in data
        assert "ai_functions_processed" in data["summary"]

    def test_switch_mode_reanalyze_endpoint(self, client, sample_project_id):
        """POST /reanalyze/project/{id}/switch-mode should trigger Celery task."""
        response = client.post(
            f"/api/reanalyze/project/{sample_project_id}/switch-mode",
            params={"new_mode": "ai"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["new_mode"] == "ai"
        assert "Background task started" in data["message"]

    def test_switch_mode_invalid(self, client, sample_project_id):
        """Invalid mode should return 400."""
        response = client.post(
            f"/api/reanalyze/project/{sample_project_id}/switch-mode",
            params={"new_mode": "invalid"},
        )
        assert response.status_code == 400

    def test_batch_migrate_mode(self, client):
        """POST /reanalyze/batch-migrate-mode should trigger migrations."""
        response = client.post(
            "/api/reanalyze/batch-migrate-mode",
            params={"target_mode": "ai", "limit_per_project": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["target_mode"] == "ai"
        assert "projects_triggered" in data
        assert "total_projects" in data
