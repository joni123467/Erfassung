import runtime
import sys
from app import crud,database,schemas
with database.SessionLocal() as db:
    user=crud.create_user(db,schemas.UserCreate(username=sys.argv[1],full_name=sys.argv[1],email=f'{sys.argv[1]}@example.com',password='Browser!12345'))
    user.must_change_password=False
    db.commit()
