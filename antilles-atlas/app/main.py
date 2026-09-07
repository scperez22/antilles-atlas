from fastapi import FastAPI

app = FastAPI(title="antilles-atlas")


@app.get("/health")
def health():
    return {"status": "ok"}
