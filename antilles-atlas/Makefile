.PHONY: up migrate test revision dev reset

up: 
	docker compose up -d

migrate:
	alembic upgrade head

test:
	pytest -v 

revision:
	alembic revision --autogenerate -m "$(message)"

dev:
	uvicorn app.main:app --reload

reset:
	docker compose down -v
	docker compose up -d