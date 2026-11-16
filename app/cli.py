import argparse
import getpass
from sqlalchemy import select
from app.db import SessionLocal
from app.auth import create_user
from app.config import settings
from app.models import Business
from app.schemas import Register

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['create-admin'])
    parser.add_argument('--phone', required=True)
    args = parser.parse_args()
    password = getpass.getpass('Administrator password (12+ characters): ')
    data = Register(phone=args.phone, password=password)
    with SessionLocal.begin() as db:
        user = create_user(db, data.phone, data.password, 'admin')
        if not db.scalar(select(Business.id).limit(1)):
            db.add(Business(name=settings.farm_name, owner_id=user.id))
    print('Administrator created. First farm created if no business existed.')

if __name__ == '__main__':
    main()
