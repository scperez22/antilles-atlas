import pathlib

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.routes import router

STATIC = pathlib.Path(__file__).resolve().parent / "static"

app = FastAPI(title="antilles-atlas")
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}


# Mounted LAST, at "/". Starlette tries routes in the order they were added,
# so /claims, /sources, /geometries and /health are matched before the static
# mount ever sees the request. Move this above include_router and the static
# mount would answer first and every API call would 404.
app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
