import type { VercelRequest, VercelResponse } from "@vercel/node";

const DEBUG_API_VERSION = "2026-06-23-env-debug-v1";

const hasEnv = (key: string) =>
  typeof process.env[key] === "string" && Boolean(process.env[key]?.trim());

const json = (res: VercelResponse, status: number, data: unknown) => {
  res.status(status);
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("X-Todo-Debug-Version", DEBUG_API_VERSION);
  return res.send(JSON.stringify(data, null, 2));
};

export default function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "GET") {
    return json(res, 405, { error: "Method not allowed" });
  }

  return json(res, 200, {
    ok: true,
    debugApiVersion: DEBUG_API_VERSION,
    timestamp: new Date().toISOString(),
    vercel: {
      env: process.env.VERCEL_ENV || "",
      region: process.env.VERCEL_REGION || "",
      urlConfigured: hasEnv("VERCEL_URL"),
      gitCommitSha: process.env.VERCEL_GIT_COMMIT_SHA || "",
      gitCommitRef: process.env.VERCEL_GIT_COMMIT_REF || "",
    },
    env: {
      GITHUB_TOKEN: hasEnv("GITHUB_TOKEN"),
      GITHUB_REPO: hasEnv("GITHUB_REPO"),
      LOCK_SCREEN_PASSWORD: hasEnv("LOCK_SCREEN_PASSWORD"),
      BLOG_LOCK_SCREEN_PASSWORD: hasEnv("BLOG_LOCK_SCREEN_PASSWORD"),
      LOCK_SCREEN_SESSION_SECRET: hasEnv("LOCK_SCREEN_SESSION_SECRET"),
      VITE_ENCRYPTION_KEY: hasEnv("VITE_ENCRYPTION_KEY"),
    },
    todoApi: {
      githubRepo: process.env.GITHUB_REPO || "glownight/ToDo",
      filePath: "src/pages/Todo/todo-data.json",
    },
  });
}
