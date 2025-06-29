# database.py  (identity-service)

import os, sqlalchemy
from sqlalchemy import create_engine, text, Column, Integer, String, Text, \
                      ForeignKey, DateTime, Uuid
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL",
                         "postgresql://user:password@localhost/lantern_identity")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ─────────── MODELS ───────────
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(Text, unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    servers = relationship("Server", back_populates="owner",
                           cascade="all, delete-orphan")
    permissions = relationship("SharingPermission", back_populates="user",
                               cascade="all, delete-orphan")

class Server(Base):
    __tablename__ = "servers"
    id = Column(Integer, primary_key=True, index=True)
    server_unique_id = Column(Uuid, unique=True, index=True, nullable=False)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    friendly_name = Column(Text, nullable=False)

    # NEW columns that may be missing in an old DB
    local_url = Column(Text, nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)

    owner = relationship("User", back_populates="servers")
    permissions = relationship("SharingPermission", back_populates="server",
                               cascade="all, delete-orphan")

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
    resource_type = Column(Text, nullable=False, default="full_access")
    resource_id = Column(Text, nullable=False, default="*")

    user = relationship("User", back_populates="permissions")
    server = relationship("Server", back_populates="permissions")

    __table_args__ = (sqlalchemy.UniqueConstraint(
        'user_id', 'server_id', 'resource_type', 'resource_id',
        name='_user_server_resource_uc'),)

# ─────────── Mini “aut migrate” helper ───────────
def _ensure_column(engine, table, column_def_sql):
    """
    If the column is missing on the given table, issue ALTER TABLE … ADD COLUMN …
    Example call:
        _ensure_column(engine,
                       "servers",
                       "local_url TEXT")
    """
    with engine.connect() as conn:
        res = conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = :table AND column_name = :col
        """), {"table": table, "col": column_def_sql.split()[0]})
        if res.first() is None:
            conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column_def_sql}'))
            conn.commit()

# Run once on import
Base.metadata.create_all(bind=engine)
_ensure_column(engine, "servers", "local_url TEXT")
_ensure_column(engine, "servers", "last_heartbeat TIMESTAMPTZ")

# ─────────── Session dependency ───────────
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()