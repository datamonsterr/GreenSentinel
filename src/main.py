import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse

from src.api.agent_runtime_routes import router as agent_runtime_router
from src.api.agent_workflow_routes import router as workflow_router
from src.api.classifier_routes import (
    ClassifierUnavailableException,
    _extract_bundle_from_raw,
    _run_heuristic_fallback,
)
from src.api.classifier_routes import (
    router as classifier_router,
)
from src.api.routes import router
from src.api.test_routes import router as test_router
from src.config import get_settings
from src.models.schemas import HealthResponse
from src.services.case_service import get_case_service

# Railway/uvicorn production deployments run with no explicit logging config,
# so a bare `logging.getLogger(__name__).warning(...)` anywhere in `src.*`
# (e.g. `driver_tool_error`, `tool_execution_failed`) only reaches stderr via
# the stdlib's `lastResort` handler if nothing has already attached a root
# handler. Only configure once, and only when nothing else (pytest's log
# capture included) has already installed a handler, so test runs are
# unaffected.
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting %s in %s mode", settings.app_name, settings.app_env)

    # Startup warm-up for fraud classifier
    app.state.classifier_loaded = False
    if settings.fraud_classifier_enabled:
        try:
            from src.api.classifier_routes import get_classifier_service

            classifier = get_classifier_service()
            dummy_bundle = {
                "points": [],
                "pickup": [105.8542, 21.0285],
                "dropoff": [105.8600, 21.0350],
            }
            if hasattr(classifier, "predict"):
                classifier.predict(dummy_bundle)
            app.state.classifier_loaded = True
            logger.info("Fraud classifier successfully loaded and warmed up.")
        except Exception as exc:
            logger.error("Failed to warm up fraud classifier: %s", exc)
            app.state.classifier_loaded = False

    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="AI20K Agent",
    description="AI Agent built with LangGraph",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_origin_regex=r"https://.*\.vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")
app.include_router(router)
app.include_router(classifier_router, prefix="/api/v1")
app.include_router(classifier_router)
app.include_router(agent_runtime_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(test_router, prefix="/test/api/v1")


@app.exception_handler(ClassifierUnavailableException)
async def classifier_unavailable_exception_handler(request: Request, exc: ClassifierUnavailableException):
    settings_fn = request.app.dependency_overrides.get(get_settings, get_settings)
    current_settings = settings_fn()
    if current_settings.jev_allow_heuristic_fallback and request.url.path.endswith("/assess"):
        try:
            body = await request.json()
            bundle = _extract_bundle_from_raw(body)
            fallback_resp = Response()
            res = await _run_heuristic_fallback(bundle, current_settings, time.perf_counter(), fallback_resp)
            response = JSONResponse(status_code=200, content=res.model_dump())
            if "Server-Timing" in fallback_resp.headers:
                response.headers["Server-Timing"] = fallback_resp.headers["Server-Timing"]
            return response
        except Exception as e:
            logger.error("Heuristic fallback error in exception handler: %s", e)

    return JSONResponse(
        status_code=503,
        content={
            "detail": f"Classifier unavailable: {exc.detail}",
            "assessment_source": "classifier_unavailable",
            "category": "insufficient_evidence",
        },
    )


@app.get("/health", response_model=HealthResponse)
async def health():
    case_service = get_case_service()
    db_status = await case_service.check_database_health()
    return HealthResponse(status="ok", env=settings.app_env, database=db_status)


@app.get("/ready")
@app.get("/api/v1/ready")
async def ready():
    case_service = get_case_service()
    db_status = await case_service.check_database_health()
    classifier_loaded = getattr(app.state, "classifier_loaded", False)
    return {
        "status": "ready" if db_status == "connected" else "degraded",
        "database": db_status,
        "classifier_loaded": classifier_loaded,
    }


@app.get("/", include_in_schema=False)
async def root():
    import os

    base_url = os.getenv("VERCEL_APP_URL", "https://p-063.vercel.app").rstrip("/")
    return RedirectResponse(url=f"{base_url}/workplace")


@app.get("/workplace", include_in_schema=False)
async def workplace():
    import os

    base_url = os.getenv("VERCEL_APP_URL", "https://p-063.vercel.app").rstrip("/")
    return RedirectResponse(url=f"{base_url}/workplace")
