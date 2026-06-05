from fastapi import FastAPI

from .api import health, query, readings
from .core import logging_config  # noqa: F401
from .db import Base, engine, run_startup_migrations

Base.metadata.create_all(bind=engine)
run_startup_migrations()

app = FastAPI(title="Data Logger Backend")

app.include_router(health.router)
app.include_router(readings.router, prefix="/api/v1/readings")
app.include_router(query.router, prefix="/api/v1")
