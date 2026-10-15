"""
Initialisation du moteur SQLAlchemy et fourniture des sessions DB.
Fonctionne out-of-the-box avec SQLite ; il suffit de changer DATABASE_URL
(dans .env) pour basculer vers PostgreSQL sans toucher au code.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependance FastAPI : fournit une session DB et la ferme proprement."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Cree les tables si elles n'existent pas (suffisant pour ce projet ;
    pour une vraie prod on utiliserait Alembic pour les migrations)."""
    from app import models  # noqa: F401 (assure l'enregistrement des modeles)
    Base.metadata.create_all(bind=engine)
