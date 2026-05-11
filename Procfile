web: uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}
worker: python -m src.cli.main sync-loop --interval 3600 --iterations -1
