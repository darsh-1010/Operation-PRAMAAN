# Frontend

Web UI for Operation PRAMAN — checkpoint screening dashboard (React + Vite + Tailwind).

## Dev

```bash
cp .env.example .env   # if not already present
npm install
npm run dev            # http://localhost:3000
```

Currently ships with mock data (see [src/screening.ts](src/screening.ts)) since the 4 backend
services under `../services/` have no endpoints yet. "Run screening" simulates the pipeline and
fills the dashboard with a mock result — swap `runScreening()` for real calls to
`VITE_OCR_SERVICE_URL` / `VITE_FORENSICS_SERVICE_URL` / `VITE_BIOMETRIC_SERVICE_URL` /
`VITE_RISK_SERVICE_URL` once those exist.
