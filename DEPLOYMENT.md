# Retirement Income Planner — Deployment & Configuration Guide

> **Last updated:** 2026-03-10  
> **Version:** Phase 2 (Dockerization)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│  VPS (Ubuntu 24.04) — 72.61.146.47                  │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
│  │ Pension       │  │ Market Data  │  │ Day       │  │
│  │ Planner       │  │ API          │  │ Tracker   │  │
│  │ :8001         │  │ :8000        │  │ :8002     │  │
│  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘  │
│         │                 │                │        │
│  ┌──────┴─────────────────┴────────────────┴─────┐  │
│  │              Nginx (80/443)                    │  │
│  │  planner.countdays.co.uk → :8001              │  │
│  │  marketdata.countdays.co.uk → :8000           │  │
│  │  countdays.co.uk → :8002                      │  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

**Target state (post-Coolify):** Nginx replaced by Traefik; all apps in Docker containers.

---

## 2. Application Inventory

| App | Port | URL | Path (legacy) | Docker Status |
|-----|------|-----|---------------|---------------|
| Pension Planner | 8001 | planner.countdays.co.uk | /opt/pensionplanner/ | ✅ Dockerfile ready |
| Market Data API | 8000 | marketdata.countdays.co.uk | /opt/retirement-api/ | ⏳ Pending |
| Day Tracker | 8002 | countdays.co.uk | /opt/daytracker/ | ✅ Already Dockerized |

---

## 3. Pension Planner — Docker Configuration

### 3.1 Environment Variables (.env)

| Variable | Purpose | Default |
|----------|---------|--------|
| `FLASK_ENV` | Flask environment | `production` |
| `SECRET_KEY` | Session encryption key | *(required)* |
| `APP_USERNAME` | Login username | `PensionPlanner` |
| `APP_PASSWORD` | Login password (plaintext, hashed at runtime) | *(required)* |
| `APP_SALT` | Password hash salt | `iom_pension_2025` |
| `MARKET_DATA_API_URL` | Market Data API endpoint | `https://marketdata.countdays.co.uk/api/v1/reference-data` |

### 3.2 Persistent Data (Volumes)

| Mount | Container Path | Purpose |
|-------|---------------|--------|
| `planner-scenarios` | `/app/scenarios/` | Saved comparison scenarios |
| `planner-config` | `/app/output/` | Generated CSV/charts |
| Bind mount | `/app/config_active.json` | Active user configuration |

### 3.3 Docker Commands

```bash
# Build
docker compose build

# Start (detached)
docker compose up -d

# View logs
docker compose logs -f planner

# Restart after code change
docker compose up -d --build

# Stop
docker compose down
```

### 3.4 Health Check

The container includes a built-in health check that pings `/login` every 30 seconds.

```bash
docker inspect --format='{{.State.Health.Status}}' pension-planner
```

---

## 4. Migration Phases

| Phase | Description | Status |
|-------|-------------|--------|
| P1 | Standardize environment variables | ✅ Complete |
| P2 | Dockerize all applications | 🔄 In progress |
| P3 | Install Coolify on VPS | ⏳ Pending |
| P4 | Deploy via Coolify + GitHub integration | ⏳ Pending |
| P5 | Remove legacy Nginx/systemd configs | ⏳ Pending |

### Phase 2 Checklist

- [x] Pension Planner: Dockerfile created
- [x] Pension Planner: .dockerignore created
- [x] Pension Planner: docker-compose.yml created
- [ ] Market Data API: Dockerfile created
- [ ] Market Data API: docker-compose.yml created
- [ ] Verify Docker builds on VPS
- [ ] Test containers locally before Coolify

---

## 5. File Inventory

### Application Files (copied into image)

| File | Purpose |
|------|---------|
| `app.py` | Flask web application |
| `retirement_engine.py` | Core projection engine |
| `optimiser.py` | Drawdown optimization |
| `market_data.py` | Live market data integration |
| `retirement_planner.py` | CLI entry point |
| `config_default.json` | Default configuration template |
| `asset_model.json` | 6-asset class model |
| `HOW_IT_WORKS.html` | Methodology page |
| `templates/` | Jinja2 HTML templates |
| `static/` | CSS and JavaScript assets |

### Runtime / Persistent Files (NOT in image)

| File | Purpose |
|------|---------|
| `.env` | Environment secrets |
| `config_active.json` | User's active configuration |
| `scenarios/*.json` | Saved comparison scenarios |
| `output/` | Generated reports |

---

## 6. Legacy Deployment (pre-Docker)

These files remain for reference until Phase 5 cleanup:

| File | Purpose |
|------|---------|
| `pensionplanner.service` | systemd unit file |
| `pensionplanner_nginx.conf` | Nginx site config |
| `deploy.sh` | Manual deployment script |

---

## 7. Security Notes

- `.env` is **never** committed to Git (enforced by `.gitignore`)
- Passwords are stored as plaintext in `.env` and hashed at runtime with SHA-256 + salt
- Login is case-insensitive for the username
- Sessions use Flask's `SecureCookieSession` with `SESSION_COOKIE_SECURE=True`
- HTTPS enforced via Nginx (currently) / Traefik (post-Coolify)
