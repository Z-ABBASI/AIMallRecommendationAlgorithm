from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.sql import func
from database import Base


class Mall(Base):
    __tablename__ = "malls"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    city = Column(String(120), index=True)
    country = Column(String(120))
    sq_ft = Column(Integer)
    floors = Column(Integer)
    aesthetic = Column(String(120))      # can later normalize into tags
    opening = Column(Integer)
    closing = Column(Integer)
    subculture = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Store(Base):
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    category = Column(String(120))
    subcategory = Column(String(120))
    mall_based = Column(Boolean, default=False)
    aesthetic = Column(String)
    subculture = Column(String)
    price_range = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Food(Base):
    __tablename__ = "food"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    category = Column(String(120))
    cuisine = Column(String(120))
    mall_based = Column(Boolean, default=False)
    aesthetic = Column(String)
    subculture = Column(String)
    price_range = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, unique=True, index=True)
    category = Column(String(120))
    subcategory = Column(String(120))
    subculture = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class MallStore(Base):
    __tablename__ = "mall_stores"

    mall_id = Column(Integer, ForeignKey("malls.id", ondelete="CASCADE"), primary_key=True)
    store_id = Column(Integer, ForeignKey("stores.id", ondelete="CASCADE"), primary_key=True)


class MallFood(Base):
    __tablename__ = "mall_food"

    mall_id = Column(Integer, ForeignKey("malls.id", ondelete="CASCADE"), primary_key=True)
    food_id = Column(Integer, ForeignKey("food.id", ondelete="CASCADE"), primary_key=True)


class MallActivity(Base):
    __tablename__ = "mall_activities"

    mall_id = Column(Integer, ForeignKey("malls.id", ondelete="CASCADE"), primary_key=True)
    activity_id = Column(Integer, ForeignKey("activities.id", ondelete="CASCADE"), primary_key=True)


class Interaction(Base):
    __tablename__ = "interactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(128), nullable=False, index=True)
    mall_id = Column(Integer, ForeignKey("malls.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(32), nullable=False, index=True)  # impression/click/like/favorite/not_for_me
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_interactions_user_mall", "user_id", "mall_id"),
    )