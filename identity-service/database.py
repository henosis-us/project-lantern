# database.py (for Identity Service - PostgreSQL)
import os
import sqlalchemy
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Uuid
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/lantern_identity")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- ORM Models ---
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    servers = relationship("Server", back_populates="owner", cascade="all, delete-orphan")
    permissions = relationship("SharingPermission", back_populates="user", cascade="all, delete-orphan")

class Server(Base):
    __tablename__ = "servers"
    id = Column(Integer, primary_key=True, index=True)
    server_unique_id = Column(Uuid, unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    friendly_name = Column(Text, nullable=False)
    last_known_url = Column(Text, nullable=True)
    owner = relationship("User", back_populates="servers")
    permissions = relationship("SharingPermission", back_populates="server", cascade="all, delete-orphan")

class ClaimToken(Base):
    __tablename__ = "claim_tokens"
    token = Column(Text, primary_key=True)
    server_unique_id = Column(Uuid, unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)

class SharingPermission(Base):
    __tablename__ = "sharing_permissions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    server_id = Column(Integer, ForeignKey("servers.id"), nullable=False)
    resource_type = Column(Text, nullable=False, default="full_access") # e.g., 'full_access', 'library', 'movie'
    resource_id = Column(Text, nullable=False, default="*") # e.g., '*', '123', '456'
    user = relationship("User", back_populates="permissions")
    server = relationship("Server", back_populates="permissions")
    __table_args__ = (
        # Ensures a user can't be granted the same permission on the same resource twice
        sqlalchemy.UniqueConstraint('user_id', 'server_id', 'resource_type', 'resource_id', name='_user_server_resource_uc'),
    )

# --- Dependency for getting a DB session ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Optional: A small main block to create tables ---
if __name__ == "__main__":
    print("Attempting to create database tables for Lantern Identity Service...")
    # The ensure_database_exists already ran when the module was loaded.
    # Now, Base.metadata.create_all connects to the specific database.
    Base.metadata.create_all(bind=engine)
    print("Database tables created or updated successfully.")