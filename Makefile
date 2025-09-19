.ONESHELL:

.PHONY: up down logs psql seed reset

up:
	cp -n .env.example .env || true
	docker compose up -d
	@echo "Waiting for Postgres to be healthy..."
	@for i in $$(seq 1 60); do \
	  docker inspect --format='{{json .State.Health.Status}}' accurate_pg | grep -q healthy && break || sleep 1; \
	done
	@echo "Postgres is up."

down:
	docker compose down -v

logs:
	docker compose logs -f

psql:
	docker exec -it accurate_pg psql -U $$(grep POSTGRES_USER .env | cut -d= -f2) -d $$(grep POSTGRES_DB .env | cut -d= -f2)

seed:
	python3 -m venv .venv
	. .venv/bin/activate && pip install -r requirements.txt
	. .venv/bin/activate && DATABASE_URL=$$(grep DATABASE_URL .env | cut -d= -f2-) python seed.py

reset: down up seed
