# Incident History Frontend (React + TypeScript)

## Run locally

```powershell
cd frontend
npm install
npm run dev
```

App route in dev server:

- `http://localhost:5173/history`

## Build static assets for FastAPI

```powershell
cd frontend
npm run build
```

Build output is generated to:

- `app/static/history/`

FastAPI serves:

- `GET /history` -> `app/static/history/index.html`
- `GET /static/history/*` -> bundled assets

## Backend API calls used

```http
GET /incident-analysis?start_date=2026-01-01&end_date=2026-12-31&service_name=product-service&classification=Performance%20Degradation&min_confidence=60&limit=20&offset=0
GET /incident-analysis/summary?start_date=2026-01-01&end_date=2026-12-31&service_name=product-service&classification=Performance%20Degradation&min_confidence=60
```

Bonus similar incidents in drawer:

```http
GET /incident-analysis?start_date=2025-01-01&end_date=2026-12-31&service_name=product-service&anomaly_score_min=0.42&anomaly_score_max=0.62&limit=3&offset=0
```

