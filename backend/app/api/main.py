from app.core.middleware import attach_middlewares
import dotenv

dotenv.load_dotenv()

import json
import os
# Set OpenMP to single-threaded BEFORE any imports that might use it
# This prevents threading conflicts with other libraries on macOS
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api import routes
from app.engine.deep_research import routes as deep_research_routes
from app.core.startup_state import run_startup_background

# Configure logging once, here at the application entry point. Every other
# module just does `logging.getLogger(__name__)` and inherits this config —
# no per-module handlers, which previously caused duplicate log lines.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()],
    force=True,  # Force reconfiguration even if logging was already configured
)

logger = logging.getLogger(__name__)

# Create FastAPI app.
# Interactive docs / OpenAPI schema are disabled by default: in browser mode
# there is no auth, so there's no reason to expose the API surface. Opt in for
# local development with QUANTSCRIPT_DEBUG=1.
_debug = os.environ.get("QUANTSCRIPT_DEBUG") == "1"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Begin loading models in the background so /startup_status can report progress."""
    import asyncio

    logger.info("Starting up application (background load)...")
    asyncio.create_task(run_startup_background())
    yield


app = FastAPI(
    title="QuantScript Backend",
    description="Backend for QuantScript",
    docs_url="/docs" if _debug else None,
    redoc_url="/redoc" if _debug else None,
    openapi_url="/openapi.json" if _debug else None,
    lifespan=lifespan,
)


# Rate limiter: the routes module owns the shared Limiter instance (so its
# decorators wrap endpoints at import time, in the standard slowapi order). We
# only need to register it on app.state and wire up the 429 handler here.
# No X-Forwarded-For handling needed because of local-only deployment.
app.state.limiter = routes.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

attach_middlewares(app)

# Include routes
app.include_router(routes.router)
app.include_router(deep_research_routes.router)

