import logging

import uvicorn

from app.api import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host="0.0.0.0", port=8080, workers=1)
