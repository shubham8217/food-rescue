from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import admin_or_service
from app.models import User
from app.services import health

router = APIRouter(tags=["health"])


@router.get("/health/pipeline")
def pipeline(user: User = Depends(admin_or_service()), db: Session = Depends(get_db)):
    return health.pipeline_health(db)
