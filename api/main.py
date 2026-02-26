from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Event(BaseModel):
    user_id: str
    item_id: str
    event_type: str  # "impression" | "click" | "like" | etc.

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/event")
def log_event(event: Event):
    # later: write to Postgres
    return {"received": event.model_dump()}

@app.get("/recommendations")
def recommendations(user_id: str):
    # later: query DB and return personalized list
    return {"user_id": user_id, "items": ["item_1", "item_2", "item_3"]}