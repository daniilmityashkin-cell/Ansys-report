"""Запуск CRM: python -m crm  (порт 8100). Переменные окружения CRM_* - см. crm/config.py и docs/CRM.md.
Добавить менеджера из консоли: python -m crm adduser почта пароль [admin]"""
import os
import sys

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "adduser":
        from sqlalchemy import select
        from .app import hash_password
        from .config import Settings
        from .models import Manager, make_db
        _, Session = make_db(Settings().db_url)
        with Session() as db:
            email = sys.argv[2].strip().lower()
            m = db.scalar(select(Manager).where(Manager.email == email)) or Manager(email=email, name="")
            m.password_hash, m.role, m.active = hash_password(sys.argv[3]), ("admin" if len(sys.argv) > 4 and sys.argv[4] == "admin" else m.role or "manager"), True
            db.add(m)
            db.commit()
        print("Готово:", email)
        sys.exit(0)
    import uvicorn
    uvicorn.run("crm.wsgi:app", host=os.environ.get("CRM_HOST", "127.0.0.1"), port=int(os.environ.get("CRM_PORT", "8100")))
