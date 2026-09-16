"""FastAPI application factory.

The API exposes domain queries. Web clients never reach DuckDB directly, and
routes must not recompute factors.
"""

from fastapi import FastAPI

SERVICE_NAME = "A-Stock Lens"


def create_app() -> FastAPI:
    """Build the API application without opening storage or computing data."""
    application = FastAPI(title=SERVICE_NAME)

    @application.get("/health")
    def health() -> dict[str, str]:
        """Report process liveness only."""
        return {"status": "ok", "service": SERVICE_NAME}

    return application
