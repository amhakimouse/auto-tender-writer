"""Sanity check for the LLM brain — run inside the Docker container."""
import sys

errors = []

# 1. Import every module
try:
    from app.llm.client import call_llm, _strip_json_fences, _get_gemini_client
    from app.llm.orchestrator import (
        evaluate_compliance, score_technical_section, extract_financial_data,
        run_enterprise_triage, format_cv_for_tender_llm, draft_narrative,
        extract_tender_requirements,
    )
    from app.schemas.llm_schemas import (
        ComplianceChecklist, TechnicalScore, FinancialData,
        create_empty_compliance_result, create_empty_technical_score,
    )
    from app.tasks.evaluation_tasks import evaluate_offer_task, evaluate_tender_batch_task
    from app.tasks.notification_tasks import draft_award_letters_task, draft_appeal_ack_task
    from app.core.config import settings
    print("[OK] All imports successful")
except Exception as e:
    errors.append(f"IMPORT ERROR: {e}")

# 2. Check provider config
try:
    assert settings.LLM_PROVIDER == "gemini", f"Wrong provider: {settings.LLM_PROVIDER}"
    assert settings.GEMINI_API_KEY,           "GEMINI_API_KEY is empty"
    assert settings.GEMINI_MODEL,             "GEMINI_MODEL is empty"
    print(f"[OK] Provider={settings.LLM_PROVIDER}, Model={settings.GEMINI_MODEL}")
except AssertionError as e:
    errors.append(f"CONFIG ERROR: {e}")

# 3. Empty factory must not crash
try:
    empty = create_empty_technical_score()
    assert empty.criteria_scores == [], "Expected empty criteria_scores"
    print("[OK] create_empty_technical_score() factory works")
except Exception as e:
    errors.append(f"FACTORY ERROR: {e}")

# 4. Fence stripping
try:
    fenced = "```json\n{\"hello\": 1}\n```"
    result = _strip_json_fences(fenced)
    assert result == '{"hello": 1}', f"Strip result wrong: {result!r}"
    print("[OK] _strip_json_fences() works")
except Exception as e:
    errors.append(f"FENCE STRIP ERROR: {e}")

if errors:
    print("\nFAILED:")
    for err in errors:
        print(f"  - {err}")
    sys.exit(1)
else:
    print("\nALL CHECKS PASSED")
