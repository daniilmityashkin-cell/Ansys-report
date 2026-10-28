"""Точка входа для uvicorn: crm.wsgi:app"""
from .app import create_app

app = create_app()
