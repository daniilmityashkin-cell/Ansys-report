"""Запуск: python -m server  (для разработки). На боевом сервере - через systemd и nginx, см. docs/DEPLOY_SERVER.md."""
import os
import uvicorn

if __name__ == "__main__":
    uvicorn.run("server.wsgi:app", host=os.environ.get("ASR_HOST", "127.0.0.1"), port=int(os.environ.get("ASR_PORT", "8000")))
