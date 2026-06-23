# Vercel Environment Variables

This project uses five main environment variables. Three are values you generate or choose yourself, and two come from GitHub.

## 1. `VITE_ENCRYPTION_KEY`

Used to encrypt and decrypt Todo data in the browser.

Generate one with either command:

```bash
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

```bash
openssl rand -hex 32
```

Use the 64-character hex string in both `.env` and Vercel.

## 2. `LOCK_SCREEN_PASSWORD`

Used as the lock-screen password.

Choose a strong password yourself, for example `mY_2026_Todo!88`. Avoid relying on the local development default in production.

## 3. `LOCK_SCREEN_SESSION_SECRET`

Used to sign the lock-screen session cookie.

Generate one with either command:

```bash
node -e "console.log(require('crypto').randomBytes(48).toString('hex'))"
```

```bash
openssl rand -hex 48
```

Use at least 64 characters. Longer is better.

## 4. `GITHUB_TOKEN`

Used by `/api/todo-data` to read and write the Todo data file in your repository.

Recommended GitHub setup:

1. Open GitHub.
2. Go to `Settings` -> `Developer settings` -> `Personal access tokens`.
3. Create a fine-grained token.
4. Set `Repository access` to `Only select repositories`.
5. Select this `ToDo` repository.
6. Grant repository `Contents: Read and write`.
7. Save the generated token immediately. GitHub only shows it once.

A classic token with at least `repo` access can work, but it is broader and less safe.

## 5. `GITHUB_REPO`

Repository name in `owner/repo` format.

Example:

```env
GITHUB_REPO=glownight/ToDo
```

Change `glownight` to your actual GitHub username or organization.

## Local `.env` Template

```env
VITE_ENCRYPTION_KEY=your-64-character-hex-key
LOCK_SCREEN_PASSWORD=your-lock-screen-password
LOCK_SCREEN_SESSION_SECRET=your-long-random-session-secret
GITHUB_TOKEN=your-github-personal-access-token
GITHUB_REPO=your-github-username/ToDo
```

## Quick Check

Check that the repository name is correct:

```bash
curl -i https://api.github.com/repos/your-github-username/ToDo
```

A `200` response means the repository path is valid.

If deployment returns `GitHub token not configured`, add or fix `GITHUB_TOKEN` in Vercel project settings.

If `/api/lock/session` returns `Lock screen password is not configured.`, add
`LOCK_SCREEN_PASSWORD` in Vercel project settings. Production intentionally
refuses access when the lock password is missing.

Open `/api/debug/env` on the deployed site to confirm Vercel can see the
required variables. The endpoint returns booleans only for secret variables,
plus a `debugApiVersion` marker for confirming the newest code is deployed.

## References

- [Managing your personal access tokens](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [REST API endpoints for repository contents](https://docs.github.com/rest/repos/contents)
- [Vercel environment variables](https://vercel.com/docs/environment-variables)
- [Managing Vercel environment variables](https://vercel.com/docs/environment-variables/managing-environment-variables)
- [Vite env variables and modes](https://vite.dev/guide/env-and-mode)
