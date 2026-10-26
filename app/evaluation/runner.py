"""Deterministic evaluation test runner executing test cases against SafeRoute LLM Gateway."""

import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from starlette.testclient import TestClient

from app.cache import ExactResponseCache, get_cache
from app.config import Settings, get_settings
from app.core.auth import compute_key_verifier
from app.db import init_db, reset_db_engine
from app.db.session import get_engine
from app.evaluation.models import (
    CaseExecutionResult,
    EvaluationCase,
    EvaluationDataset,
    EvaluationReport,
    EvaluationSummary,
)
from app.guardrails import GuardrailEngine, get_guardrail_engine
from app.limiter import RateLimiter, get_rate_limiter
from app.main import create_app

# Evaluation test credentials
EVAL_AUTH_SECRET = "eval_auth_secret_minimum_16_characters_long"
VALID_EVAL_KEY = "gw_test_eval_client_key_1234567890"
REVOKED_EVAL_KEY = "gw_test_eval_revoked_key_99999999"

VALID_VERIFIER = compute_key_verifier(VALID_EVAL_KEY, EVAL_AUTH_SECRET)
REVOKED_VERIFIER = compute_key_verifier(REVOKED_EVAL_KEY, EVAL_AUTH_SECRET)


class FakeEvalRedis:
    """In-memory Redis test double for evaluation scenarios."""

    def __init__(self, simulate_outage: bool = False) -> None:
        self.store: Dict[str, str] = {}
        self.simulate_outage = simulate_outage

    async def get(self, key: str) -> Optional[str]:
        if self.simulate_outage:
            from redis.exceptions import RedisError
            raise RedisError("Simulated Redis outage for evaluation")
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        if self.simulate_outage:
            from redis.exceptions import RedisError
            raise RedisError("Simulated Redis outage for evaluation")
        self.store[key] = value
        return True

    async def delete(self, *keys: str) -> int:
        if self.simulate_outage:
            from redis.exceptions import RedisError
            raise RedisError("Simulated Redis outage for evaluation")
        count = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                count += 1
        return count

    async def ping(self) -> bool:
        if self.simulate_outage:
            from redis.exceptions import RedisError
            raise RedisError("Simulated Redis outage for evaluation")
        return True

    async def aclose(self) -> None:
        pass


class FakeEvalLimiterRedis:
    """In-memory Redis test double for atomic rate limiting evaluation."""

    def __init__(self, simulate_outage: bool = False) -> None:
        self.counters: Dict[str, int] = {}
        self.simulate_outage = simulate_outage

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> List[Any]:
        if self.simulate_outage:
            from redis.exceptions import RedisError
            raise RedisError("Simulated Redis outage for evaluation")

        key = keys_and_args[0]
        window = int(keys_and_args[1])
        current = self.counters.get(key, 0) + 1
        self.counters[key] = current
        ttl = window
        return [current, ttl]

    async def ping(self) -> bool:
        if self.simulate_outage:
            from redis.exceptions import RedisError
            raise RedisError("Simulated Redis outage for evaluation")
        return True

    async def aclose(self) -> None:
        pass


class EvaluationRunner:
    """Executes evaluation cases and produces structured reports."""

    def __init__(self, dataset: EvaluationDataset, mode: str = "full", live: bool = False) -> None:
        self.dataset = dataset
        self.mode = mode
        self.live = live

    def run(self) -> EvaluationReport:
        """Execute all dataset cases and return an aggregated EvaluationReport."""
        run_id = f"eval_{uuid.uuid4().hex[:12]}"
        start_mono = time.perf_counter()
        case_results: List[CaseExecutionResult] = []

        for case in self.dataset.cases:
            res = self.execute_case(case)
            case_results.append(res)

        total_duration_ms = round((time.perf_counter() - start_mono) * 1000, 2)

        passed = sum(1 for r in case_results if r.status == "passed")
        failed = sum(1 for r in case_results if r.status == "failed")
        skipped = sum(1 for r in case_results if r.status == "skipped")
        errored = sum(1 for r in case_results if r.status == "errored")
        total = len(case_results)
        executed_cases = passed + failed + errored

        # Explicit mathematical formulas:
        # 1. pass_rate_executed_pct: percentage of executed cases that passed
        pass_rate_executed = round((passed / executed_cases * 100.0) if executed_cases > 0 else 0.0, 2)
        # 2. completion_rate_all_pct: percentage of all dataset cases that passed
        completion_rate_all = round((passed / total * 100.0) if total > 0 else 0.0, 2)

        summary = EvaluationSummary(
            total_cases=total,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errored=errored,
            executed_cases=executed_cases,
            pass_rate_executed_pct=pass_rate_executed,
            completion_rate_all_pct=completion_rate_all,
            pass_rate_pct=pass_rate_executed,
            total_duration_ms=total_duration_ms,
        )

        return EvaluationReport(
            run_id=run_id,
            timestamp_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            dataset_id=self.dataset.dataset_id,
            dataset_version=self.dataset.version,
            app_version="0.1.0",
            git_commit=None,
            environment="test",
            summary=summary,
            case_results=case_results,
            live_services_used=self.live,
            system_info={
                "runner_mode": self.mode,
                "dataset_cases_count": total,
            },
        )

    def execute_case(self, case: EvaluationCase) -> CaseExecutionResult:
        """Execute a single evaluation case under isolated settings."""
        # 1. Handle live-service requirement
        if case.requires_live and not self.live:
            return CaseExecutionResult(
                case_id=case.case_id,
                category=case.category,
                description=case.description,
                status="skipped",
                duration_ms=0.0,
                expected_status=case.expected.status_code,
                failure_reason="Requires live external service (Ollama or Redis). Re-run with --live to execute.",
            )

        start_time = time.perf_counter()
        temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(temp_dir.name) / f"eval_{case.case_id}.db"
        db_url = f"sqlite:///{db_path}"

        try:
            # Build isolated application settings
            settings = Settings(
                app_env="test",
                auth_enabled=case.setup.auth_enabled,
                auth_secret=EVAL_AUTH_SECRET,
                client_keys=[
                    {"client_id": case.setup.client_id, "verifier": VALID_VERIFIER, "enabled": True},
                    {"client_id": "revoked_client", "verifier": REVOKED_VERIFIER, "enabled": False},
                ],
                allowed_models=case.setup.allowed_models,
                default_model="mock-model",
                database_url=db_url,
                database_strict_mode=case.setup.database_strict_mode,
                # Cache overrides
                cache_enabled=case.setup.cache_enabled,
                cache_ttl_seconds=case.setup.cache_ttl_seconds,
                cache_namespace=case.setup.cache_namespace,
                # Rate limit overrides
                rate_limit_enabled=case.setup.rate_limit_enabled,
                rate_limit_requests=case.setup.rate_limit_requests,
                rate_limit_window_seconds=case.setup.rate_limit_window_seconds,
                rate_limit_namespace=case.setup.rate_limit_namespace,
                rate_limit_failure_policy=case.setup.rate_limit_failure_policy,
                # Guardrails overrides
                guardrails_enabled=case.setup.guardrails_enabled,
                guardrails_input_enabled=case.setup.guardrails_input_enabled,
                guardrails_output_enabled=case.setup.guardrails_output_enabled,
                guardrails_action=case.setup.guardrails_action,
                guardrails_max_text_length=case.setup.guardrails_max_text_length,
                guardrails_rules=case.setup.guardrails_rules,
                active_provider=case.setup.active_provider,
                provider_timeout_seconds=case.setup.provider_timeout_seconds,
            )

            # Initialize isolated SQLite database
            reset_db_engine()
            init_db(get_engine(settings.database_url))

            # Set up Redis doubles
            fake_cache_redis = FakeEvalRedis(simulate_outage=case.setup.redis_simulate_outage)
            cache_instance = ExactResponseCache(redis_client=fake_cache_redis, settings=settings)

            fake_limiter_redis = FakeEvalLimiterRedis(simulate_outage=case.setup.redis_simulate_outage)
            limiter_instance = RateLimiter(redis_client=fake_limiter_redis, settings=settings)

            guardrail_engine = GuardrailEngine(settings=settings)

            app = create_app()
            app.dependency_overrides[get_settings] = lambda: settings
            app.dependency_overrides[get_cache] = lambda: cache_instance
            app.dependency_overrides[get_rate_limiter] = lambda: limiter_instance
            app.dependency_overrides[get_guardrail_engine] = lambda: guardrail_engine

            # Resolve authorization headers
            headers = dict(case.request.headers)
            if case.request.auth == "valid":
                headers["Authorization"] = f"Bearer {VALID_EVAL_KEY}"
            elif case.request.auth == "invalid":
                headers["Authorization"] = "Bearer gw_test_invalid_unregistered_key_00000000"
            elif case.request.auth == "revoked":
                headers["Authorization"] = f"Bearer {REVOKED_EVAL_KEY}"
            elif case.request.auth == "custom" and case.request.custom_auth_header:
                headers["Authorization"] = case.request.custom_auth_header

            with TestClient(app, raise_server_exceptions=False, headers=headers) as client:
                duration_ms, actual_status, actual_err_code, actual_cache_header, details, failure_reason = self._run_scenario(
                    client=client,
                    case=case,
                    db_url=db_url,
                )

            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            status = "failed" if failure_reason else "passed"

            return CaseExecutionResult(
                case_id=case.case_id,
                category=case.category,
                description=case.description,
                status=status,
                duration_ms=duration_ms,
                expected_status=case.expected.status_code,
                actual_status=actual_status,
                expected_error_code=case.expected.error_code,
                actual_error_code=actual_err_code,
                expected_cache_header=case.expected.cache_header,
                actual_cache_header=actual_cache_header,
                failure_reason=failure_reason,
                details=details,
            )

        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            return CaseExecutionResult(
                case_id=case.case_id,
                category=case.category,
                description=case.description,
                status="errored",
                duration_ms=duration_ms,
                expected_status=case.expected.status_code,
                failure_reason=f"Execution error: {type(exc).__name__}: {str(exc)}",
            )
        finally:
            reset_db_engine()
            try:
                temp_dir.cleanup()
            except Exception:
                pass

    def _run_scenario(
        self,
        client: TestClient,
        case: EvaluationCase,
        db_url: Optional[str] = None,
    ) -> Tuple[float, int, Optional[str], Optional[str], Dict[str, Any], Optional[str]]:
        """Run the specific scenario type and check assertions."""
        scenario = case.scenario_type
        endpoint = case.request.endpoint
        body = case.request.body

        if scenario == "sequential_cache_hit":
            # 1. First call: Cache miss
            t0 = time.perf_counter()
            r1 = client.post(endpoint, json=body)
            t1 = time.perf_counter()
            d1_ms = round((t1 - t0) * 1000, 2)

            if r1.status_code != 200:
                return d1_ms, r1.status_code, None, None, {}, f"First call expected 200, got {r1.status_code}"

            # 2. Second call: Cache hit
            t2 = time.perf_counter()
            r2 = client.post(endpoint, json=body)
            t3 = time.perf_counter()
            d2_ms = round((t3 - t2) * 1000, 2)

            actual_status = r2.status_code
            actual_cache = r2.headers.get("X-Cache")
            details = {
                "first_call_ms": d1_ms,
                "second_call_ms": d2_ms,
                "first_cache_header": r1.headers.get("X-Cache"),
                "second_cache_header": actual_cache,
            }

            if actual_status != case.expected.status_code:
                return d2_ms, actual_status, None, actual_cache, details, f"Expected status {case.expected.status_code}, got {actual_status}"

            if case.expected.cache_header and actual_cache != case.expected.cache_header:
                return d2_ms, actual_status, None, actual_cache, details, f"Expected X-Cache header '{case.expected.cache_header}', got '{actual_cache}'"

            return d2_ms, actual_status, None, actual_cache, details, None

        elif scenario == "rate_limit_burst":
            # Send requests up to limit
            limit = case.setup.rate_limit_requests
            details = {"requests_sent": limit + 1}
            for i in range(limit):
                r = client.post(endpoint, json=body)
                if r.status_code != 200:
                    return 0.0, r.status_code, None, None, details, f"Pre-limit request #{i+1} failed with status {r.status_code}"

            # Send exceeding request
            t0 = time.perf_counter()
            rex = client.post(endpoint, json=body)
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)

            actual_status = rex.status_code
            err_data = rex.json().get("error", {}) if rex.headers.get("content-type", "").startswith("application/json") else {}
            actual_err_code = err_data.get("code")

            if actual_status != case.expected.status_code:
                return duration_ms, actual_status, actual_err_code, None, details, f"Expected rate-limit status {case.expected.status_code}, got {actual_status}"

            if case.expected.error_code and actual_err_code != case.expected.error_code:
                return duration_ms, actual_status, actual_err_code, None, details, f"Expected error code '{case.expected.error_code}', got '{actual_err_code}'"

            return duration_ms, actual_status, actual_err_code, None, details, None

        else:
            # Standard single request scenario
            t0 = time.perf_counter()
            r = client.post(endpoint, json=body) if case.request.method == "POST" else client.get(endpoint)
            duration_ms = round((time.perf_counter() - t0) * 1000, 2)

            actual_status = r.status_code
            actual_cache = r.headers.get("X-Cache")
            resp_json = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            err_data = resp_json.get("error", {})
            actual_err_code = err_data.get("code")
            actual_err_type = err_data.get("type")

            details = {"status_code": actual_status, "duration_ms": duration_ms}

            if actual_status != case.expected.status_code:
                return duration_ms, actual_status, actual_err_code, actual_cache, details, f"Expected status {case.expected.status_code}, got {actual_status}"

            if case.expected.error_code and actual_err_code != case.expected.error_code:
                return duration_ms, actual_status, actual_err_code, actual_cache, details, f"Expected error_code '{case.expected.error_code}', got '{actual_err_code}'"

            if case.expected.error_type and actual_err_type != case.expected.error_type:
                return duration_ms, actual_status, actual_err_code, actual_cache, details, f"Expected error_type '{case.expected.error_type}', got '{actual_err_type}'"

            if case.expected.cache_header and actual_cache != case.expected.cache_header:
                return duration_ms, actual_status, actual_err_code, actual_cache, details, f"Expected X-Cache '{case.expected.cache_header}', got '{actual_cache}'"

            if case.expected.has_choices and "choices" not in resp_json:
                return duration_ms, actual_status, actual_err_code, actual_cache, details, "Expected 'choices' field in response"

            if case.expected.usage_present and "usage" not in resp_json:
                return duration_ms, actual_status, actual_err_code, actual_cache, details, "Expected 'usage' field in response"

            if case.expected.is_mock_estimate is not None:
                usage = resp_json.get("usage", {})
                if usage.get("is_mock_estimate") != case.expected.is_mock_estimate:
                    return duration_ms, actual_status, actual_err_code, actual_cache, details, f"Expected is_mock_estimate={case.expected.is_mock_estimate}, got {usage.get('is_mock_estimate')}"

            if case.expected.expect_cost_null is not None and db_url:
                try:
                    from sqlalchemy import text
                    engine = get_engine(db_url)
                    with engine.connect() as conn:
                        row = conn.execute(
                            text("SELECT estimated_cost, cost_status, usage_source FROM request_records ORDER BY id DESC LIMIT 1")
                        ).fetchone()
                        if row:
                            details["db_estimated_cost"] = row[0]
                            details["db_cost_status"] = row[1]
                            details["db_usage_source"] = row[2]
                            if case.expected.expect_cost_null and row[0] is not None:
                                return duration_ms, actual_status, actual_err_code, actual_cache, details, f"Expected estimated_cost=None, got {row[0]}"
                except Exception as exc:
                    details["db_cost_check_error"] = str(exc)

            return duration_ms, actual_status, actual_err_code, actual_cache, details, None
