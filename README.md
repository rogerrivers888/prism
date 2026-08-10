# Prism

Personal investment research and portfolio platform. Monorepo, deployed to
Railway. Currently backend only (`backend/` — FastAPI + PostgreSQL).

## Running it locally

You need two things installed:

1. **Docker Desktop** — runs the database. Get it from
   [docker.com](https://www.docker.com/products/docker-desktop/).
2. **uv** — manages Python and the project's dependencies, so you don't need to
   install Python yourself. Install it with:

   ```sh
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

### 1. Start the database

From the repo root:

```sh
docker compose up -d
```

This starts PostgreSQL in the background (on port 5435, so it won't clash with
any Postgres you already have installed). It keeps its data between restarts.
To stop it later: `docker compose down`.

### 2. Start the backend

```sh
cd backend
uv run alembic upgrade head    # apply database migrations
uv run uvicorn app.main:app --reload
```

The first `uv run` will automatically download Python 3.12 and install all
dependencies — no separate install step needed. `--reload` means the server
restarts itself whenever you edit the code.

### 3. Check it's working

Open <http://localhost:8000/health> in a browser. You should see:

```json
{"status": "ok", "service": "prism-api"}
```

Interactive API docs live at <http://localhost:8000/docs>.

## Configuration

The backend reads `DATABASE_URL` from the environment (Railway sets this
automatically in production). Locally it defaults to the docker-compose
database, so you don't need to configure anything. To override it, create a
`backend/.env` file with a line like:

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## Deployment

Railway builds the backend with Railpack (no Dockerfile). Config lives in
`backend/railway.json`: migrations run as a pre-deploy step, then Uvicorn
serves the app, with `/health` as the healthcheck. The Railway service's root
directory must be set to `backend`, and it needs an explicit `PORT=8080`
environment variable.

Uvicorn binds `0.0.0.0` (IPv4) because Railway's healthchecker reaches the
container over IPv4 — an IPv6-only `::` bind passes the build but fails the
healthcheck. If a service ever needs to be reachable over Railway's IPv6-only
private network, the app will have to listen on both stacks (e.g. a server
that supports multiple binds), not just switch back to `::`.
