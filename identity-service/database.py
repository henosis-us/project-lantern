# database.py (for Identity Service - PostgreSQL)
import os
import sqlalchemy # NEW: Import sqlalchemy for text() and UniqueConstraint
from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime, Uuid
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.sql import func
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse # NEW: For parsing DB URL

load_dotenv()

# It's recommended to use environment variables for connection details
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/lantern_identity")

# --- Function to ensure database exists ---
def ensure_database_exists(db_url):
    parsed_url = urlparse(db_url)
    db_name = parsed_url.path.lstrip('/') # Get database name from the path part of the URL
        
    # Construct a URL for connecting to the default 'postgres' database
    # This assumes the user specified in DATABASE_URL has access to the 'postgres' database
    default_db_url = urlunparse(parsed_url._replace(path='/postgres'))
    
    # Temporary engine to connect to 'postgres' database
    # The `isolation_level="AUTOCOMMIT"` is crucial for CREATE DATABASE as it cannot run within a transaction
    temp_engine = create_engine(default_db_url, isolation_level="AUTOCOMMIT")
        
    try:
        with temp_engine.connect() as connection:
            # Check if the target database exists
            # Use sqlalchemy.text() for raw SQL queries
            result = connection.execute(sqlalchemy.text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'"))
            if not result.scalar():
                # If not, create it
                print(f"Database '{db_name}' does not exist. Creating it now...")
                connection.execute(sqlalchemy.text(f"CREATE DATABASE {db_name}"))
                print(f"Database '{db_name}' created successfully.")
            else:
                print(f"Database '{db_name}' already exists.")
    except Exception as e:
        print(f"Error ensuring database '{db_name}' exists: {e}")
        print("Please ensure your PostgreSQL server is running and the user specified in DATABASE_URL has permissions to connect to 'postgres' database and create new databases.")
        raise # Re-raise the exception to stop the application startup

# Ensure the database exists BEFORE creating the main engine for the specific database.
# This makes sure the target database is ready before SQLAlchemy tries to connect to it for table creation.
ensure_database_exists(DATABASE_URL)
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