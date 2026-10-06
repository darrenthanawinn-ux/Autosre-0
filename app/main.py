"""Demo service the swarm evolves, secures, deploys and monitors."""
from fastapi import FastAPI

app = FastAPI(title="AutoSRE Demo Service")

ITEMS = {1: "alpha", 2: "beta"}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/items/{item_id}")
def get_item(item_id: int):
    if item_id not in ITEMS:
        return {"error": "not found"}
    return {"id": item_id, "name": ITEMS[item_id]}
