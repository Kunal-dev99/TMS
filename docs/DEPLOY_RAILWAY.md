# Deploying to Railway

The Treasury Register runs as two Railway services in one project: a
backend (FastAPI) and a frontend (Next.js). This document is the whole
setup, in order.

## Prerequisites

- The repository pushed to **private** GitHub, GitLab or Bitbucket.
  Nobody browsing the deployed URLs will see your Python — but the
  source lives in whichever repo you point Railway at, so keep it
  private if you care about that.
- A Railway account (`railway.app`). The Hobby plan at $5/mo is
  sufficient for a prototype demo.
- Your Groq API key for the AI features. If you don't set it, every AI
  feature falls back to a deterministic paragraph and the app still
  works — just without the model's prose.

## Step 1 — Create the project

1. In Railway, **New Project** → **Deploy from GitHub repo** → select
   this repository.
2. Railway will offer to deploy the repo as a single service. Skip the
   auto-detect for now — we'll add two services manually so each gets
   its own root directory.

## Step 2 — The backend service

1. **New Service** → **GitHub repo** → this repo.
2. **Settings** → **Root Directory** → `backend`.
3. Railway auto-detects Python from `requirements.txt`. `railway.json`
   in the backend root sets the start command and the health check.
4. **Volumes** → **New Volume** → mount at `/data`. Give it 1 GB;
   this is where the SQLite database lives across restarts.
5. **Variables** — set the following:

   | Name | Value | Notes |
   |---|---|---|
   | `TREASURY_DATABASE_URL` | `sqlite:////data/treasury.db` | Four slashes: `sqlite://` scheme + `/data/treasury.db` absolute path. |
   | `TREASURY_MODEL_API_KEY` | `gsk_...` | Your Groq key. Omit if you want fallback-only. |
   | `TREASURY_MODEL_NAME` | `openai/gpt-oss-120b` | Or another model your key can reach. |

6. **Networking** — the service is internal-only by default. Generate a
   public domain only if you want to call the backend directly (usually
   you don't — the frontend calls it internally). Note the private URL
   Railway shows you, of the form
   `<backend-service-name>.railway.internal`.

7. Deploy. The bootstrap script runs `alembic upgrade head`, seeds the
   book if empty, then starts uvicorn on the port Railway assigns. The
   `/health` endpoint is polled to confirm it came up.

## Step 3 — The frontend service

1. **New Service** → **GitHub repo** → same repo.
2. **Settings** → **Root Directory** → `frontend`.
3. Railway auto-detects Next.js. `railway.json` sets the start command
   and the root health check.
4. **Variables** — set:

   | Name | Value | Notes |
   |---|---|---|
   | `TREASURY_API_ORIGIN` | `http://<backend-service-name>.railway.internal:8000` | Replace `<backend-service-name>` with what Railway called your backend service. Port is whatever the backend `$PORT` bound to; for internal traffic Railway routes on 8000 by default. |

5. **Networking** — click **Generate Domain**. This is the URL your
   users will open.

6. Deploy. Next.js builds and starts on the port Railway assigns.
   Rewrites in `next.config.mjs` proxy `/api/*` calls through to the
   backend service on the private URL, so the browser only ever talks
   to the frontend origin — no CORS to configure.

## Step 4 — Verify

- Open the frontend domain. The sign-in page should render.
- Sign in as `m.doran@northgate.example` / `treasury`.
- The dashboard should load with the seeded book.
- Click **Reset** in the header. The book resets (uses the persistent
  volume, so it survives redeploys unless you press Reset).
- Click **Run the nightly job**. If your Groq key is set, the advisory
  panel will populate. If not, the panel still populates via the
  fallback ranker.

## Redeploys

Push to the branch Railway is watching. Both services rebuild
automatically. Because the database lives on the mounted volume,
**the book survives redeploys**. If you want the deploy to reset the
book, unmount the volume — every restart will start fresh from the
seed.

## What deploys and what doesn't

- **Everything in the repo** is uploaded to Railway's build system to
  produce the running app. The source is not served from the running
  app; users see only the compiled Next.js bundle in their browser and
  the FastAPI responses.
- **`.env` files are gitignored** and never reach Railway. Set every
  secret via the Variables tab instead.
- **`treasury.db` on the volume** is Railway-only; it is not part of
  the repo. First boot seeds it.

## Troubleshooting

**The frontend loads but every request returns a 500.**
The frontend can't reach the backend. Check that `TREASURY_API_ORIGIN`
on the frontend service exactly matches the backend's private URL,
including the scheme (`http://`) and the port.

**"Cannot open database file".**
The volume is not mounted. Check the backend service's Volumes tab —
`/data` must be mounted before the first request.

**Health check keeps failing.**
Look at the backend logs. The bootstrap script prints each step
(`running alembic upgrade head`, `seeding the book`, `starting
uvicorn`); the failure will be after whichever step succeeded last.

**Every book reset loses my data.**
Either the volume isn't attached, or `TREASURY_DATABASE_URL` still
points to the container's ephemeral filesystem. It must be
`sqlite:////data/treasury.db` (four slashes).

## Cost

At Hobby ($5/month), both services and one 1 GB volume fit
comfortably. The Groq key is billed separately by Groq; per-run cost
for the demo is fractions of a cent.

## What is not covered

- Real Oracle Fusion adapters (still stubbed).
- Real credit news feed (seeded snippets only).
- Multi-tenancy for real (one seeded tenant).
- PostgreSQL (phase 4 work; SQLite on a volume is fine for a demo).
- Custom domain, TLS beyond Railway's default. If needed, add via
  Railway → Settings → Custom Domain.
