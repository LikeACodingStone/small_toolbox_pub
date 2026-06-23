import { createHmac, timingSafeEqual } from "node:crypto";
import type { VercelRequest, VercelResponse } from "@vercel/node";

const LOCK_COOKIE_NAME = "todo_lock_screen_session";
const LOCK_SESSION_MAX_AGE = 60 * 60 * 12;
const DEBUG_API_VERSION = "2026-06-23-env-debug-v1";

const json = (res: VercelResponse, status: number, data: unknown) => {
  res.status(status);
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.setHeader("X-Todo-Debug-Version", DEBUG_API_VERSION);
  return res.send(JSON.stringify(data));
};

const readEnv = (keys: string[]) => {
  for (const key of keys) {
    const value = process.env[key];
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
};

const getLockScreenPassword = () =>
  readEnv(["LOCK_SCREEN_PASSWORD", "BLOG_LOCK_SCREEN_PASSWORD", "VITE_LOCK_SCREEN_PASSWORD"]);

const getLockScreenSessionSecret = () =>
  readEnv([
    "LOCK_SCREEN_SESSION_SECRET",
    "EDITOR_SESSION_SECRET",
    "GITHUB_TOKEN",
    "LOCK_SCREEN_PASSWORD",
    "BLOG_LOCK_SCREEN_PASSWORD",
  ]);

const safeCompare = (left: string, right: string) => {
  if (left.length !== right.length) {
    return false;
  }

  const leftBuffer = Buffer.from(left, "utf8");
  const rightBuffer = Buffer.from(right, "utf8");

  return timingSafeEqual(leftBuffer, rightBuffer);
};

const signPayload = (payload: string) => {
  const secret = getLockScreenSessionSecret();

  if (!secret) {
    throw new Error("Could not create lock screen session.");
  }

  return createHmac("sha256", secret).update(payload).digest("base64url");
};

const createLockSessionToken = () => {
  const payload = Buffer.from(
    JSON.stringify({ exp: Date.now() + LOCK_SESSION_MAX_AGE * 1000 }),
    "utf8",
  ).toString("base64url");

  const signature = signPayload(payload);
  return `${payload}.${signature}`;
};

const parseCookieHeader = (cookieHeader?: string) => {
  const result = new Map<string, string>();
  if (!cookieHeader) return result;

  for (const chunk of cookieHeader.split(";")) {
    const [rawKey, ...rawValue] = chunk.trim().split("=");
    if (!rawKey) continue;
    result.set(rawKey, rawValue.join("="));
  }

  return result;
};

const getCookie = (req: VercelRequest, key: string) => {
  const cookies = parseCookieHeader(req.headers.cookie);
  return cookies.get(key) ?? "";
};

const hasValidLockSession = (req: VercelRequest) => {
  const token = getCookie(req, LOCK_COOKIE_NAME);
  if (!token) {
    return false;
  }

  try {
    const [payload, signature] = token.split(".");
    if (!payload || !signature) {
      return false;
    }

    const expectedSignature = signPayload(payload);
    if (!safeCompare(signature, expectedSignature)) {
      return false;
    }

    const parsed = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf8"),
    ) as { exp?: number };

    return typeof parsed.exp === "number" && parsed.exp > Date.now();
  } catch {
    return false;
  }
};

const buildCookie = (req: VercelRequest, value: string, maxAge = LOCK_SESSION_MAX_AGE) => {
  const forwardedProto = req.headers["x-forwarded-proto"];
  const isSecure =
    (Array.isArray(forwardedProto)
      ? forwardedProto[0]
      : forwardedProto?.toString() ?? ""
    ).toLowerCase() === "https";

  return [
    `${LOCK_COOKIE_NAME}=${value}`,
    `Max-Age=${maxAge}`,
    "Path=/",
    "HttpOnly",
    "SameSite=Lax",
    isSecure ? "Secure" : "",
  ]
    .filter(Boolean)
    .join("; ");
};

const readPasswordFromBody = (req: VercelRequest): string | null => {
  const body = req.body;

  if (body && typeof body === "object" && "password" in body) {
    const password = (body as { password?: unknown }).password;
    return typeof password === "string" ? password : null;
  }

  if (typeof body === "string") {
    try {
      const parsed = JSON.parse(body) as { password?: unknown };
      return typeof parsed.password === "string" ? parsed.password : null;
    } catch {
      return null;
    }
  }

  return null;
};

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method === "OPTIONS") {
    return json(res, 200, { ok: true });
  }

  const lockPassword = getLockScreenPassword();

  if (req.method === "GET") {
    if (!lockPassword) {
      return json(res, 503, {
        authenticated: false,
        enabled: false,
        error: "Lock screen password is not configured.",
      });
    }

    return json(res, 200, { authenticated: hasValidLockSession(req), enabled: true });
  }

  if (req.method === "DELETE") {
    res.setHeader("Set-Cookie", buildCookie(req, "", 0));
    return json(res, 200, { success: true });
  }

  if (req.method !== "POST") {
    return json(res, 405, { error: "Method not allowed" });
  }

  if (!lockPassword) {
    return json(res, 503, { error: "Lock screen password is not configured." });
  }

  const password = readPasswordFromBody(req);
  if (typeof password !== "string") {
    return json(res, 400, { error: "Invalid request payload." });
  }

  if (!password.trim()) {
    return json(res, 400, { error: "Password is required." });
  }

  if (!safeCompare(password.trim(), lockPassword)) {
    return json(res, 401, { error: "Password is incorrect." });
  }

  try {
    const token = createLockSessionToken();
    res.setHeader("Set-Cookie", buildCookie(req, token));
    return json(res, 200, { success: true });
  } catch (error) {
    return json(res, 500, {
      error:
        error instanceof Error && error.message
          ? error.message
          : "Could not create lock screen session.",
    });
  }
}
