from app.database import SessionLocal
from app.models.user import User

db = SessionLocal()

users = db.query(User).all()

if not users:
    print("⚠️ No users found in the database.")
else:
    print(f"✅ Found {len(users)} user(s):")
    for u in users:
        print(f" - ID: {u.id} | Email: {u.email} | Name: {u.full_name}")
