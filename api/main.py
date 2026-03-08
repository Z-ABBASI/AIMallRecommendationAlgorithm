from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from database import engine, SessionLocal
import models  # <-- IMPORTANT: ensures Item/Tag/etc classes are loaded
from models import Base, Mall, Store, Food, Activity, MallStore, MallFood, MallActivity
from sqlalchemy import select
from typing import Optional
from collections import defaultdict

app = FastAPI()

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class Event(BaseModel):
    user_id: str
    item_id: str
    event_type: str

class RecRequest(BaseModel):
    store_ids: list[int] = []
    food_ids: list[int] = []
    activity_ids: list[int] = []

    subculture: Optional[int] = None          # match malls.subculture (currently int in DB)
    aesthetic: Optional[str] = None

    food_category: Optional[str] = None       # match Food.category
    hobbies: list[str] = []                   # match Activity.category/subcategory (best-effort)

    floors: Optional[int] = None
    sq_ft: Optional[int] = None
    opening: Optional[int] = None
    closing: Optional[int] = None

    weights: dict[str, float] = {
        "stores": 2.0,
        "foods": 2.0,
        "activities": 2.0,
        "subculture": 3.0,
        "aesthetic": 3.0,
        "food_category": 2.0,
        "hobbies": 2.0,
        "floors": 0.5,
        "sq_ft": 0.5,
        "opening": 0.5,
        "closing": 0.5
    }
    limit: int = 10

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/event")
def log_event(event: Event):
    # later: write to Postgres
    return {"received": event.model_dump()}

@app.post("/recommendations")
def recommend(req: RecRequest, db: Session = Depends(get_db)):
    w = req.weights

    # Load all malls
    malls = db.query(Mall).all()

    # Build mall -> sets of linked IDs
    mall_store_ids = defaultdict(set)
    for mall_id, store_id in db.query(MallStore.mall_id, MallStore.store_id).all():
        mall_store_ids[mall_id].add(store_id)

    mall_food_ids = defaultdict(set)
    for mall_id, food_id in db.query(MallFood.mall_id, MallFood.food_id).all():
        mall_food_ids[mall_id].add(food_id)

    mall_activity_ids = defaultdict(set)
    for mall_id, activity_id in db.query(MallActivity.mall_id, MallActivity.activity_id).all():
        mall_activity_ids[mall_id].add(activity_id)

    # Optional: lookup names for "why"
    store_name = dict(db.query(Store.id, Store.name).all())
    food_name = dict(db.query(Food.id, Food.name).all())
    activity_name = dict(db.query(Activity.id, Activity.name).all())

    # Optional: category lookups for req.food_category + req.hobbies best-effort
    food_category_by_id = dict(db.query(Food.id, Food.category).all())
    activity_cat_by_id = dict(db.query(Activity.id, Activity.category).all())
    activity_subcat_by_id = dict(db.query(Activity.id, Activity.subcategory).all())

    pref_store = set(req.store_ids)
    pref_food = set(req.food_ids)
    pref_act = set(req.activity_ids)

    results = []
    for m in malls:
        score = 0.0
        why = {"stores": [], "foods": [], "activities": [], "meta": []}

        # Store overlap
        if pref_store:
            matched = pref_store & mall_store_ids[m.id]
            if matched:
                score += w.get("stores", 0.0) * len(matched)
                why["stores"] = [{"id": sid, "name": store_name.get(sid)} for sid in sorted(matched)]

        # Food overlap
        if pref_food:
            matched = pref_food & mall_food_ids[m.id]
            if matched:
                score += w.get("foods", 0.0) * len(matched)
                why["foods"] = [{"id": fid, "name": food_name.get(fid)} for fid in sorted(matched)]

        # Activity overlap
        if pref_act:
            matched = pref_act & mall_activity_ids[m.id]
            if matched:
                score += w.get("activities", 0.0) * len(matched)
                why["activities"] = [{"id": aid, "name": activity_name.get(aid)} for aid in sorted(matched)]

        # Aesthetic match (string)
        if req.aesthetic and m.aesthetic and req.aesthetic.strip().lower() == m.aesthetic.strip().lower():
            score += w.get("aesthetic", 0.0)
            why["meta"].append("aesthetic_match")

        # Subculture match (int, per current DB)
        if req.subculture is not None and m.subculture is not None and req.subculture == m.subculture:
            score += w.get("subculture", 0.0)
            why["meta"].append("subculture_match")

        # Food category preference (best-effort: if any linked food has that category)
        if req.food_category:
            target = req.food_category.strip().lower()
            linked_foods = mall_food_ids[m.id]
            if any((food_category_by_id.get(fid) or "").strip().lower() == target for fid in linked_foods):
                score += w.get("food_category", 0.0)
                why["meta"].append("food_category_match")

        # Hobbies preference (best-effort: match against activity category/subcategory)
        if req.hobbies:
            hobbies = {h.strip().lower() for h in req.hobbies if h.strip()}
            linked_acts = mall_activity_ids[m.id]
            if linked_acts and hobbies:
                def act_tags(aid: int) -> set[str]:
                    return {
                        ((activity_cat_by_id.get(aid) or "").strip().lower()),
                        ((activity_subcat_by_id.get(aid) or "").strip().lower()),
                    }
                if any(len(act_tags(aid) & hobbies) > 0 for aid in linked_acts):
                    score += w.get("hobbies", 0.0)
                    why["meta"].append("hobbies_match")

        # Numeric preferences: treat as "closeness" rather than exact
        def closeness(pref: int | None, val: int | None) -> float:
            if pref is None or val is None:
                return 0.0
            # Simple: +1 if within 20%, +0.5 if within 50%
            if pref == 0:
                return 0.0
            ratio = abs(val - pref) / max(pref, 1)
            if ratio <= 0.2:
                return 1.0
            if ratio <= 0.5:
                return 0.5
            return 0.0

        score += w.get("floors", 0.0) * closeness(req.floors, m.floors)
        score += w.get("sq_ft", 0.0) * closeness(req.sq_ft, m.sq_ft)
        score += w.get("opening", 0.0) * closeness(req.opening, m.opening)
        score += w.get("closing", 0.0) * closeness(req.closing, m.closing)

        results.append({
            "mall": {
                "id": m.id,
                "name": m.name,
                "city": m.city,
                "country": m.country,
                "sq_ft": m.sq_ft,
                "floors": m.floors,
                "aesthetic": m.aesthetic,
                "opening": m.opening,
                "closing": m.closing,
                "subculture": m.subculture,
            },
            "score": round(score, 3),
            "why": why,
        })

    results.sort(key=lambda x: x["score"], reverse=True)
    return {"count": min(req.limit, len(results)), "results": results[: req.limit]}

@app.get("/stores")
def list_stores(db: Session = Depends(get_db)):
    return db.query(Store.id, Store.name, Store.category).order_by(Store.id).all()

@app.get("/foods")
def list_foods(db: Session = Depends(get_db)):
    return db.query(Food.id, Food.name, Food.category, Food.cuisine).order_by(Food.id).all()

@app.get("/activities")
def list_activities(db: Session = Depends(get_db)):
    return db.query(Activity.id, Activity.name, Activity.category, Activity.subcategory).order_by(Activity.id).all()

@app.get("/malls")
def list_malls(db: Session = Depends(get_db)):
    return db.query(Mall).order_by(Mall.id).all()

@app.post("/seed")
def seed(db: Session = Depends(get_db)):
    # --- Create malls ---
    malls = [
        # Mall(name="", city="", country="", sq_ft=, floors=, aesthetic=, opening=, closing=, subculture=),
        Mall(name="Square One", city="Mississauga", country="Canada", sq_ft=2200000, floors=2, opening=10, closing=8),
        Mall(name="The ONE", city="Hong Kong", country="Hong Kong", sq_ft=400000, floors=29, opening=10, closing=11),
        Mall(name="Galeria do Rock", city="São Paulo", country="Brazil", floors=7, aesthetic="Rock", opening=9, closing=7),
        Mall(name="Laforet Harajuku", city="Tokyo", country="Japan", sq_ft=167852, floors=13, aesthetic="Harajuku", opening=11, closing=8),
        Mall(name="Evropeyskiy Shopping Mall", city="Moscow", country="Russia", sq_ft=678000, floors=8, aesthetic="Cyberpunk", opening=10, closing=10),
        Mall(name="Stonestown Galleria", city="San Francisco", country="USA", sq_ft=803837, floors=2, opening=11, closing=8),
        Mall(name="Mall of America", city="Bloomington", country="Minesota", sq_ft=5600000, floors=4, opening=10, closing=9),
        Mall(name="Westfield Topanga", city="Los Angeles", country="USA", sq_ft=1588050, floors=2, opening=10, closing=8)
    ]
    db.add_all(malls)
    db.commit()
    for m in malls:
        db.refresh(m)

    # --- Create stores ---
    stores = [
        # Store(name="", category="", subcategory="", mall_based=, aesthetic="", subculture="", price_range="")
        Store(name="Zumiez", category="Fashion", subcategory="Clothing", mall_based=True, aesthetic="Biker", price_range="30-100+"),
        Store(name="Hot Topic", category="Fashion", subcategory="Clothes/Accessories", mall_based=True, aesthetic="Emo", price_range="9-100"),
        Store(name="Spencers", category="Lifestyle", subcategory="Novelty", mall_based=True, aesthetic="Alternative", price_range="15-100"),
        Store(name="Fashion Nova", category="Fashion", subcategory="Clubwear", mall_based=False, aesthetic="Baddie", price_range="15-200"),
        Store(name="Uniqlo", category="Fashion", subcategory="Activewear", mall_based=True, aesthetic="Minimalist", price_range="10-150"),
        Store(name="Apple", category="Tech", subcategory="Electronics", mall_based=False, price_range="200-7000+"),
        Store(name="Bath & Body Works", category="Bodycare", subcategory="Scented", mall_based=True, price_range="14-21"),
        Store(name="MINISO", category="Lifestyle", mall_based=True, aesthetic="Minimalist Kawaii", price_range="5-50"),
        Store(name="GameStop", category="Tech", subcategory="Gaming", mall_based=True, aesthetic="Gaming", price_range="30-70"),
    ]
    db.add_all(stores)
    db.commit()
    for s in stores:
        db.refresh(s)

    # --- Create food ---
    food = [
        # Food(name="", category="", cuisine="", mall_based=, aesthetic="", subculture="", price_range="")
        Food(name="Wetzel Pretzels", category="Snack", cuisine="Pretzels", mall_based=True, price_range="6-13"),
        Food(name="Cinnabon", category="Dessert", cuisine="Cinnamon Rolls", mall_based=True, price_range="6-10"),
        Food(name="Coldstone", category="Dessert", cuisine="Ice Cream", mall_based=True, price_range="7-45"),
        Food(name="Rock Burguer", category="Main Course", cuisine="Burger", mall_based=True, aesthetic="Rock", price_range="55-65")
        # 
    ]
    db.add_all(food)
    db.commit()
    for f in food:
        db.refresh(f)

    # --- Create activities ---
    activities = [Activity(name="Movie Theater"), Activity(name="Round One"), Activity(name="Rock Concerts"), Activity(name="Nickeloden Universe"), Activity(name="Cyberpunk Elevators")]
    db.add_all(activities)
    db.commit()
    for a in activities:
        db.refresh(a)

    # Stores
    db.add_all([
        # Square One
        MallStore(mall_id=malls[0].id, store_id=stores[0].id),
        MallStore(mall_id=malls[0].id, store_id=stores[1].id),
        MallStore(mall_id=malls[0].id, store_id=stores[4].id),
        MallStore(mall_id=malls[0].id, store_id=stores[5].id),
        MallStore(mall_id=malls[0].id, store_id=stores[6].id),
        MallStore(mall_id=malls[0].id, store_id=stores[7].id),
        MallStore(mall_id=malls[0].id, store_id=stores[8].id),

        # Stonestown Galleria
        MallStore(mall_id=malls[5].id, store_id=stores[0].id),
        MallStore(mall_id=malls[5].id, store_id=stores[4].id),
        MallStore(mall_id=malls[5].id, store_id=stores[5].id),
        MallStore(mall_id=malls[5].id, store_id=stores[7].id),
        MallStore(mall_id=malls[5].id, store_id=stores[8].id),

        # Mall of America
        MallStore(mall_id=malls[6].id, store_id=stores[0].id),
        MallStore(mall_id=malls[6].id, store_id=stores[1].id),
        MallStore(mall_id=malls[6].id, store_id=stores[2].id),
        MallStore(mall_id=malls[6].id, store_id=stores[4].id),
        MallStore(mall_id=malls[6].id, store_id=stores[5].id),
        MallStore(mall_id=malls[6].id, store_id=stores[6].id),
        MallStore(mall_id=malls[6].id, store_id=stores[7].id),
        MallStore(mall_id=malls[6].id, store_id=stores[8].id),

        # Westfield Topanga
        MallStore(mall_id=malls[7].id, store_id=stores[0].id),
        MallStore(mall_id=malls[7].id, store_id=stores[1].id),
        MallStore(mall_id=malls[7].id, store_id=stores[2].id),
        MallStore(mall_id=malls[7].id, store_id=stores[3].id),
        MallStore(mall_id=malls[7].id, store_id=stores[4].id),
        MallStore(mall_id=malls[7].id, store_id=stores[5].id),
        MallStore(mall_id=malls[7].id, store_id=stores[6].id),
        MallStore(mall_id=malls[7].id, store_id=stores[7].id),
    ])

    # Food
    db.add_all([
        # Square One
        MallFood(mall_id=malls[0].id, food_id=food[0].id),

        # The ONE
        MallFood(mall_id=malls[1].id, food_id=food[0].id),

        # Galeria do Rock
        MallFood(mall_id=malls[2].id, food_id=food[3].id),

        # Stonestown Galleria
        MallFood(mall_id=malls[5].id, food_id=food[0].id),

        # Mall of America
        MallFood(mall_id=malls[6].id, food_id=food[0].id),
        MallFood(mall_id=malls[6].id, food_id=food[1].id),
        MallFood(mall_id=malls[6].id, food_id=food[2].id),

        # Westfield Topanga
        MallFood(mall_id=malls[7].id, food_id=food[0].id),
        MallFood(mall_id=malls[7].id, food_id=food[1].id),
    ])

    # Activities
    db.add_all([
        # Square One
        MallActivity(mall_id=malls[0].id, activity_id=activities[0].id),

        # The ONE
        MallActivity(mall_id=malls[1].id, activity_id=activities[0].id),

        # Galeria do Rock
        MallActivity(mall_id=malls[2].id, activity_id=activities[2].id),

        # Evropeyskiy Shopping Mall
        MallActivity(mall_id=malls[4].id, activity_id=activities[0].id),
        MallActivity(mall_id=malls[4].id, activity_id=activities[4].id),

        # Stonestown Galleria
        MallActivity(mall_id=malls[5].id, activity_id=activities[0].id),
        MallActivity(mall_id=malls[5].id, activity_id=activities[1].id),

        # Mall of America
        MallActivity(mall_id=malls[6].id, activity_id=activities[0].id),
        MallActivity(mall_id=malls[6].id, activity_id=activities[3].id),

        # Westfield Topanga
        MallActivity(mall_id=malls[7].id, activity_id=activities[0].id),
    ])

    db.commit()

    return {"ok": True, "malls": [m.id for m in malls]}