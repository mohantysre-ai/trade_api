from __future__ import annotations

import logging

import uvicorn

from .app import create_app
from .config import Settings

logging.basicConfig(level=logging.INFO)
settings = Settings.from_env()
app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8787)
