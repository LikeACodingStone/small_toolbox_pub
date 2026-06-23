import type { VercelRequest, VercelResponse } from "@vercel/node";

const GITHUB_TOKEN = process.env.GITHUB_TOKEN;
const GITHUB_REPO = process.env.GITHUB_REPO || "glownight/ToDo";
const FILE_PATH = "src/pages/Todo/todo-data.json";

interface TodoTask {
  id: string;
  title: string;
  [key: string]: unknown;
}

interface TodoPayload {
  tasks: TodoTask[];
}

interface EncryptedTodoPayload {
  encrypted: true;
  v?: number;
  payload: string;
}

interface GitHubFileResponse {
  content: string;
  sha: string;
}

const isEncryptedPayload = (payload: unknown): payload is EncryptedTodoPayload => {
  if (!payload || typeof payload !== "object") return false;
  const obj = payload as Record<string, unknown>;
  return obj.encrypted === true && typeof obj.payload === "string";
};

const isEncryptedString = (value: string): boolean => {
  const base64Regex = /^[A-Za-z0-9+/]+=*$/;
  if (!base64Regex.test(value)) return false;
  try {
    const buffer = Buffer.from(value, "base64");
    return buffer.length >= 32 + 16 + 16 + 1;
  } catch {
    return false;
  }
};

const normalizePayload = (
  payload: unknown
): TodoPayload | EncryptedTodoPayload | null => {
  if (Array.isArray(payload)) {
    return { tasks: payload as TodoTask[] };
  }

  if (payload && typeof payload === "object") {
    if (isEncryptedPayload(payload)) {
      return payload;
    }
    const data = payload as Partial<TodoPayload>;
    if (Array.isArray(data.tasks)) {
      return { tasks: data.tasks as TodoTask[] };
    }
  }

  return null;
};

export default async function handler(req: VercelRequest, res: VercelResponse) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  if (!GITHUB_TOKEN) {
    return res.status(500).json({
      error: "GitHub token not configured",
      message: "Configure GITHUB_TOKEN in Vercel environment variables.",
    });
  }

  const apiUrl = `https://api.github.com/repos/${GITHUB_REPO}/contents/${FILE_PATH}`;

  try {
    if (req.method === "GET") {
      const response = await fetch(apiUrl, {
        headers: {
          Authorization: `Bearer ${GITHUB_TOKEN}`,
          Accept: "application/vnd.github.v3+json",
        },
      });

      if (response.status === 404) {
        return res.status(200).json({ tasks: [] });
      }

      if (!response.ok) {
        throw new Error(`GitHub API error: ${response.statusText}`);
      }

      const data = (await response.json()) as GitHubFileResponse;
      const content = Buffer.from(data.content, "base64").toString("utf-8");

      let parsed: unknown;
      try {
        parsed = JSON.parse(content) as unknown;
      } catch {
        if (isEncryptedString(content)) {
          return res.status(200).json({ encrypted: true, v: 1, payload: content });
        }
        throw new Error("Todo data parse error");
      }

      if (typeof parsed === "string" && isEncryptedString(parsed)) {
        return res.status(200).json({ encrypted: true, v: 1, payload: parsed });
      }

      return res.status(200).json(parsed);
    }

    if (req.method === "POST") {
      const payload = normalizePayload(req.body);

      if (!payload) {
        return res.status(400).json({ error: "Invalid data format" });
      }

      let sha: string | undefined;
      try {
        const getResponse = await fetch(apiUrl, {
          headers: {
            Authorization: `Bearer ${GITHUB_TOKEN}`,
            Accept: "application/vnd.github.v3+json",
          },
        });

        if (getResponse.ok) {
          const data = (await getResponse.json()) as GitHubFileResponse;
          sha = data.sha;
        }
      } catch {
        // file not exist yet
      }

      const content = Buffer.from(JSON.stringify(payload, null, 2), "utf-8").toString(
        "base64"
      );

      const updateResponse = await fetch(apiUrl, {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${GITHUB_TOKEN}`,
          Accept: "application/vnd.github.v3+json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: `Update Todo data ${new Date().toISOString()}`,
          content,
          sha,
        }),
      });

      if (!updateResponse.ok) {
        const errorData = await updateResponse.json();
        throw new Error(`Failed to update file: ${JSON.stringify(errorData)}`);
      }

      return res.status(200).json({ success: true });
    }

    return res.status(405).json({ error: "Method not allowed" });
  } catch (error) {
    console.error("API Error:", error);
    return res.status(500).json({
      error: "Internal server error",
      message: error instanceof Error ? error.message : "Unknown error",
    });
  }
}
