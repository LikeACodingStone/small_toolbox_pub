# ToDo

A React Todo project that can run locally or deploy to Vercel. It includes:

- A password-protected lock screen.
- A Todo workspace with reminder, execution, weekly, monthly, yearly, and overdue views.
- A GitHub-backed sync API for `src/pages/Todo/todo-data.json`.

## Local Development on Linux

This app should be opened through HTTPS when you use the Linux server IP. Browser
encryption APIs are blocked on plain HTTP LAN URLs.

Use Node.js 20.19+ or 22.12+, then install dependencies, create a local
certificate, and start Vite:

```bash
npm install
cp .env.example .env
mkdir -p certs
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout certs/dev-key.pem \
  -out certs/dev-cert.pem \
  -days 365 \
  -subj "/CN=172.30.2.199" \
  -addext "subjectAltName=IP:172.30.2.199,DNS:localhost"
npm run dev
```

Open `https://172.30.2.199:5173/`.

If your Linux server IP changes, replace `172.30.2.199` in the `openssl`
command and in the browser URL. Vite is configured to listen on
`0.0.0.0:5173` and read the HTTPS certificate from `VITE_DEV_HTTPS_KEY` and
`VITE_DEV_HTTPS_CERT`. If the browser shows a certificate warning, accept it
for local development or trust the generated certificate.

In local development, the lock password defaults to `bj8964` unless you set `LOCK_SCREEN_PASSWORD` or `VITE_LOCK_SCREEN_PASSWORD` in `.env`.

## Routes

- `/` lock screen
- `/todo` Todo workspace

## Environment Variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

Required or recommended variables:

- `VITE_ENCRYPTION_KEY`
- `LOCK_SCREEN_PASSWORD`
- `LOCK_SCREEN_SESSION_SECRET`
- `VITE_DEV_HTTPS_KEY` for local Linux HTTPS
- `VITE_DEV_HTTPS_CERT` for local Linux HTTPS
- `GITHUB_TOKEN` for deployed GitHub sync
- `GITHUB_REPO` for deployed GitHub sync, for example `yourname/ToDo`

## Vercel Deployment

1. Create a GitHub repository, for example `ToDo`, and push this project.
2. Import the repository in Vercel.
3. Add the environment variables listed above in Vercel project settings.
4. Deploy.

If `/todo` shows a sync error after deployment, open `/api/todo-data`.
`GitHub token not configured` means `GITHUB_TOKEN` is missing in Vercel. If
the app stays on the lock screen and reports that the password is not
configured, add `LOCK_SCREEN_PASSWORD` in Vercel and redeploy.

For a safe deployment diagnostic that does not expose secret values, open
`/api/debug/env`. It reports whether each required environment variable is
present and includes a `debugApiVersion` marker so you can confirm Vercel is
running the latest code.

## API

- `GET/POST /api/todo-data`
  - Reads and writes `src/pages/Todo/todo-data.json` through the GitHub Contents API in production.
- `GET/POST/DELETE /api/lock/session`
  - Checks the lock session, signs in, and signs out.
- `GET /api/debug/env`
  - Reports deployment diagnostics without printing secret values.

## Build

```bash
npm run build
npm run preview
```
