"""Точка входа для uvicorn: server.wsgi:app"""
from .app import create_app

app = create_app()
app.state.recover()                 # незавершённые расчёты после перезапуска
app.state.start_reconciler(120)     # раз в 2 минуты сверять ожидающие платежи с провайдером
