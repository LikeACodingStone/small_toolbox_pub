import { existsSync, promises as fs, readFileSync } from "node:fs";
import path from "node:path";
import type { IncomingMessage, ServerResponse } from "node:http";
import type { ServerOptions as HttpsServerOptions } from "node:https";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

type TodoTask = {
  id: string;
  title: string;
  [key: string]: unknown;
};

type TodoPayload = {
  tasks: TodoTask[];
};

type EncryptedTodoPayload = {
  encrypted: true;
  v?: number;
  payload: string;
};

const todoDataPath = path.resolve(__dirname, "src/pages/Todo/todo-data.json");
const lockCookieName = "todo_lock_screen_session";
const lockSessionMaxAge = 60 * 60 * 24 * 3;
const defaultDevHttpsKeyPath = "certs/dev-key.pem";
const defaultDevHttpsCertPath = "certs/dev-cert.pem";

const resolveProjectPath = (filePath: string) =>
  path.isAbsolute(filePath) ? filePath : path.resolve(__dirname, filePath);

const getRequiredDevHttpsOptions = (
  env: Record<string, string>,
): HttpsServerOptions => {
  const keyPath = resolveProjectPath(
    env.VITE_DEV_HTTPS_KEY || defaultDevHttpsKeyPath,
  );
  const certPath = resolveProjectPath(
    env.VITE_DEV_HTTPS_CERT || defaultDevHttpsCertPath,
  );
  const missingFiles: string[] = [];

  if (!existsSync(keyPath)) {
    missingFiles.push(`key: ${keyPath}`);
  }

  if (!existsSync(certPath)) {
    missingFiles.push(`cert: ${certPath}`);
  }

  if (missingFiles.length > 0) {
    throw new Error(
      [
        "Missing HTTPS certificate files for the Vite dev server.",
        ...missingFiles.map((file) => `- ${file}`),
        "Create them with the Linux openssl command in README.md, or set VITE_DEV_HTTPS_KEY and VITE_DEV_HTTPS_CERT.",
      ].join("\n"),
    );
  }

  return {
    key: readFileSync(keyPath),
    cert: readFileSync(certPath),
  };
};

const parseCookieHeader = (cookieHeader?: string) => {
  const cookies = new Map<string, string>();
  if (!cookieHeader) return cookies;

  for (const segment of cookieHeader.split(";")) {
    const [rawKey, ...rawValue] = segment.trim().split("=");
    if (!rawKey) continue;
    cookies.set(rawKey, rawValue.join("="));
  }

  return cookies;
};

const readBody = async (req: IncomingMessage) => {
  const chunks: Buffer[] = [];
  for await (const chunk of req) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  return Buffer.concat(chunks).toString("utf8");
};

const normalizePayload = (
  payload: unknown,
): TodoPayload | EncryptedTodoPayload | null => {
  if (Array.isArray(payload)) {
    return { tasks: payload as TodoTask[] };
  }

  if (payload && typeof payload === "object") {
    const obj = payload as Record<string, unknown>;

    if (obj.encrypted === true && typeof obj.payload === "string") {
      return {
        encrypted: true,
        v: typeof obj.v === "number" ? obj.v : 1,
        payload: obj.payload,
      };
    }

    if (Array.isArray(obj.tasks)) {
      return { tasks: obj.tasks as TodoTask[] };
    }
  }

  return null;
};

const sendJson = (res: ServerResponse, status: number, data: unknown) => {
  const body = JSON.stringify(data);
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("Cache-Control", "no-store");
  res.end(body);
};

const handleTodoData = async (req: IncomingMessage, res: ServerResponse) => {
  if (req.method === "OPTIONS") {
    res.statusCode = 200;
    res.end();
    return;
  }

  if (req.method === "GET") {
    try {
      const raw = await fs.readFile(todoDataPath, "utf8");
      const parsed = JSON.parse(raw) as unknown;
      sendJson(res, 200, parsed);
      return;
    } catch {
      sendJson(res, 200, { tasks: [] });
      return;
    }
  }

  if (req.method === "POST") {
    try {
      const rawBody = await readBody(req);
      const parsed = rawBody ? (JSON.parse(rawBody) as unknown) : null;
      const normalized = normalizePayload(parsed);

      if (!normalized) {
        sendJson(res, 400, { error: "Invalid data format" });
        return;
      }

      await fs.writeFile(todoDataPath, `${JSON.stringify(normalized, null, 2)}\n`, "utf8");
      sendJson(res, 200, { success: true });
      return;
    } catch (error) {
      sendJson(res, 500, {
        error: "Local dev todo API failed",
        message: error instanceof Error ? error.message : "Unknown error",
      });
      return;
    }
  }

  sendJson(res, 405, { error: "Method not allowed" });
};

const handleLockSession = async (req: IncomingMessage, res: ServerResponse) => {
  const lockPassword =
    process.env.LOCK_SCREEN_PASSWORD ||
    process.env.VITE_LOCK_SCREEN_PASSWORD ||
    "bj8964";
  const cookieHeader = req.headers.cookie;
  const cookies = parseCookieHeader(cookieHeader);

  if (req.method === "GET") {
    sendJson(res, 200, {
      authenticated: cookies.get(lockCookieName) === "1",
      enabled: Boolean(lockPassword),
    });
    return;
  }

  if (req.method === "DELETE") {
    res.setHeader(
      "Set-Cookie",
      `${lockCookieName}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax`,
    );
    sendJson(res, 200, { success: true });
    return;
  }

  if (req.method !== "POST") {
    sendJson(res, 405, { error: "Method not allowed" });
    return;
  }

  try {
    const rawBody = await readBody(req);
    const parsed = rawBody ? (JSON.parse(rawBody) as { password?: unknown }) : {};
    const password = typeof parsed.password === "string" ? parsed.password.trim() : "";

    if (!password) {
      sendJson(res, 400, { error: "Password is required." });
      return;
    }

    if (password !== lockPassword) {
      sendJson(res, 401, { error: "Password is incorrect." });
      return;
    }

    res.setHeader(
      "Set-Cookie",
      `${lockCookieName}=1; Max-Age=${lockSessionMaxAge}; Path=/; HttpOnly; SameSite=Lax`,
    );
    sendJson(res, 200, { success: true });
  } catch {
    sendJson(res, 400, { error: "Invalid request payload." });
  }
};

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");

  return {
    server:
      command === "serve"
        ? {
            host: "0.0.0.0",
            port: 5173,
            https: getRequiredDevHttpsOptions(env),
          }
        : undefined,
    plugins: [
      react(),
      {
        name: "todo-local-dev-api",
        apply: "serve",
        configureServer(server) {
          server.middlewares.use(async (req, res, next) => {
            const pathname = req.url?.split("?")[0] || "";

            if (pathname === "/api/todo-data" || pathname === "/dev-api/todo-data") {
              await handleTodoData(req, res);
              return;
            }

            if (pathname === "/api/lock/session" || pathname === "/dev-api/lock/session") {
              await handleLockSession(req, res);
              return;
            }

            next();
          });
        },
      },
    ],
  };
});
