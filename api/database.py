# this file handles the sqlite database connection and the db models

from sqlalchemy import create_engine, Column, Integer, String, Text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./thesis_recom.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserProfile(Base):
    # this table stores the onboarding questionnaire answers
    __tablename__ = "user_profiles"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True)
    city = Column(String(100))
    tags = Column(Text)            # comma-separated tags
    favorite_artists = Column(Text)  # comma-separated artists


class Event(Base):
    # this table stores events created by admin
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200))
    city = Column(String(100))
    date = Column(String(20))      # YYYY-MM-DD for simplicity
    language = Column(String(50))  # greek / english / both
    tags = Column(Text)            # comma-separated tags
    artists = Column(Text)         # comma-separated artists


def init_db():
    # this function creates the tables if not exist
    Base.metadata.create_all(bind=engine)
