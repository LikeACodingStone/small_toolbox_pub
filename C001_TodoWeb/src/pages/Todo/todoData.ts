import {
    decryptToString,
    encrypt,
    getEncryptionKey,
    isEncrypted,
} from "../../utils/security/encryptionBrowser";

export type Priority = "high" | "mid" | "low" | "none";

export interface TaskBadge {
    label: string;
    tone: "info" | "danger" | "warn" | "note";
}

export interface Task {
    id: string;
    title: string;
    tag?: string;

    // Core properties
    done?: boolean;
    priority?: Priority;

    // View-driving flags (like Notion filters)
    important?: boolean; // Reminder view
    execution?: boolean; // Execution/board view
    annual?: boolean; // This year view
    week?: boolean; // This week view
    month?: boolean; // This month view

    // Extra properties
    accent?: boolean;
    note?: string;
    start?: string; // yyyy/mm/dd
    end?: string; // yyyy/mm/dd
    openEnded?: boolean;
    openEndedCount?: number;
    openEndedLastDone?: string; // yyyy/mm/dd
    openEndedHistory?: string[]; // yyyy/mm/dd[]
    openEndedTone?: "positive" | "negative";
    openEndedRecordDay?: "today" | "yesterday";
    category?: string;
    link?: string;
    badges?: TaskBadge[];

    createdAt: number;
    updatedAt: number;
}

export type ViewOrderPrefs = {
    manualOrder?: string[];
    manualOrderByPriority?: Partial<Record<Priority, string[]>>;
};

export interface TodoData {
    tasks: Task[];
    viewOrders?: Record<string, ViewOrderPrefs>;
}

export interface RemoteSnapshot {
    data: TodoData;
    savedAt: number;
}

type EncryptedTodoPayload = {
    encrypted: true;
    v: number;
    payload: string;
};

export const defaultData: TodoData = {
    tasks: [],
};

const STORAGE_KEY = "todo-local-data-v3";
const REMOTE_SNAPSHOT_KEY = "todo-remote-snapshot-v1";
const LEGACY_V2_KEY = "todo-local-data-v2";
const LEGACY_V1_KEY = "todo-local-data-v1";

type LegacyV2Task = {
    id?: string;
    title?: string;
    tag?: string;
    bucket?: string;
    priority?: Priority;
    checked?: boolean;
    done?: boolean;
    accent?: boolean;
    note?: string;
    start?: string;
    end?: string;
    category?: string;
    badges?: TaskBadge[];
};

type LegacyV2Data = { tasks?: LegacyV2Task[] };

type LegacyV1 = Record<string, unknown>;

const normalizeTitleKey = (title: string) =>
    title
        .trim()
        .replace(/^\d+\.\s*/, "")
        .replace(/^-\s*/, "")
        .trim();

const toYmd = (d: Date) => {
    const yyyy = d.getFullYear();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    return `${yyyy}/${mm}/${dd}`;
};

const fromLegacyV2 = (legacy: LegacyV2Data): TodoData | null => {
    if (!legacy.tasks || !Array.isArray(legacy.tasks)) return null;

    const today = new Date();
    const todayStr = toYmd(today);
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const yesterdayStr = toYmd(yesterday);

    const byKey = new Map<string, Task>();

    for (const lt of legacy.tasks) {
        const rawTitle = lt.title || "";
        const key = normalizeTitleKey(rawTitle);
        if (!key) continue;

        const existing = byKey.get(key);
        const t: Task = existing || {
            id: lt.id || uid(),
            title: key,
            createdAt: Date.now(),
            updatedAt: Date.now(),
        };

        const bucket = lt.bucket;

        // Flags
        if (bucket === "wish") t.important = true;
        if (bucket === "board") t.execution = true;
        if (bucket === "year") t.annual = true;
        if (bucket === "week" || bucket === "month" || bucket === "delay") t.execution = true;
        if (bucket === "week") t.week = true;
        if (bucket === "month") t.month = true;

        // Completion
        const legacyDone = !!lt.done || !!lt.checked;
        if (legacyDone) t.done = true;

        // Priority
        if (bucket === "board" && lt.priority) t.priority = lt.priority;

        // Other fields (keep the first non-empty)
        t.tag = t.tag || lt.tag;
        t.note = t.note || lt.note;
        t.start = t.start || lt.start;
        t.end = t.end || lt.end;
        t.category = t.category || lt.category;
        t.badges = t.badges || lt.badges;
        t.accent = t.accent || lt.accent;

        // Make sure legacy week/month/delay items still show up in their views after migration
        if ((bucket === "week" || bucket === "month") && !t.end) {
            t.end = todayStr;
        }
        if (bucket === "delay" && !t.end) {
            t.end = yesterdayStr;
        }

        byKey.set(key, t);
    }

    const tasks = Array.from(byKey.values()).filter((t) => t.title.trim().length > 0);
    return tasks.length ? { tasks } : null;
};

const legacyV1ToV2 = (legacy: LegacyV1): LegacyV2Data | null => {
    // v1 uses an object shape (wishes/columns/week/month/year/delayed).
    const tasks: LegacyV2Task[] = [];

    const pushSimple = (arr: unknown, bucket: string) => {
        if (!Array.isArray(arr)) return;
        for (const item of arr) {
            const obj = item as Record<string, unknown>;
            const title = (obj.text as string) || (obj.title as string) || "";
            tasks.push({
                id: (obj.id as string) || uid(),
                title,
                tag: obj.tag as string | undefined,
                bucket,
                checked: !!obj.checked,
                done: !!obj.done,
                accent: !!obj.accent,
            });
        }
    };

    // wishes
    pushSimple(legacy.wishes, "wish");

    // columns
    if (Array.isArray(legacy.columns)) {
        for (const col of legacy.columns) {
            const c = col as Record<string, unknown>;
            const colId = (c.id as Priority) || "high";
            if (Array.isArray(c.tasks)) {
                for (const t of c.tasks) {
                    const tt = t as Record<string, unknown>;
                    tasks.push({
                        id: (tt.id as string) || uid(),
                        title: (tt.title as string) || "",
                        tag: tt.tag as string | undefined,
                        bucket: "board",
                        priority: colId,
                        done: !!tt.done,
                    });
                }
            }
        }
    }

    pushSimple(legacy.week, "week");
    pushSimple(legacy.month, "month");
    pushSimple(legacy.year, "year");

    if (Array.isArray(legacy.delayed)) {
        for (const d of legacy.delayed) {
            const dd = d as Record<string, unknown>;
            tasks.push({
                id: (dd.id as string) || uid(),
                title: (dd.title as string) || "",
                category: dd.category as string | undefined,
                note: dd.note as string | undefined,
                start: dd.start as string | undefined,
                end: dd.end as string | undefined,
                badges: dd.tags as TaskBadge[] | undefined,
                bucket: "delay",
            });
        }
    }

    return tasks.length ? { tasks } : null;
};

const isV3Task = (t: unknown): t is Task => {
    if (!t || typeof t !== "object") return false;
    const obj = t as Record<string, unknown>;
    return typeof obj.id === "string" && typeof obj.title === "string";
};

const pickStringArray = (v: unknown) =>
    Array.isArray(v)
        ? v.filter((x): x is string => typeof x === "string")
        : undefined;

const normalizeViewOrders = (
    raw: unknown
): Record<string, ViewOrderPrefs> | undefined => {
    if (!raw || typeof raw !== "object") return undefined;
    const result: Record<string, ViewOrderPrefs> = {};
    for (const [viewId, value] of Object.entries(raw as Record<string, unknown>)) {
        if (!value || typeof value !== "object") continue;
        const obj = value as Record<string, unknown>;
        const manualOrder = pickStringArray(obj.manualOrder);
        const rawByPriority = obj.manualOrderByPriority;
        let manualOrderByPriority:
            | Partial<Record<Priority, string[]>>
            | undefined;
        if (rawByPriority && typeof rawByPriority === "object") {
            const byPriority: Partial<Record<Priority, string[]>> = {};
            (["high", "mid", "low", "none"] as Priority[]).forEach((priority) => {
                const arr = pickStringArray(
                    (rawByPriority as Record<string, unknown>)[priority]
                );
                if (arr && arr.length) {
                    byPriority[priority] = arr;
                }
            });
            if (Object.keys(byPriority).length) {
                manualOrderByPriority = byPriority;
            }
        }
        if ((manualOrder && manualOrder.length) || manualOrderByPriority) {
            result[viewId] = {
                manualOrder: manualOrder?.length ? manualOrder : undefined,
                manualOrderByPriority,
            };
        }
    }
    return Object.keys(result).length ? result : undefined;
};

const normalizeV3 = (data: TodoData): TodoData => {
    const now = Date.now();
        return {
            tasks: (data.tasks || []).filter(isV3Task).map((t) => ({
                ...t,
                // Canonicalize optional boolean flags (treat `false` the same as `undefined`).
                done: t.done ? true : undefined,
                important: t.important ? true : undefined,
                execution: t.execution ? true : undefined,
                annual: t.annual ? true : undefined,
                week: t.week ? true : undefined,
                month: t.month ? true : undefined,
                openEnded: t.openEnded ? true : undefined,
                openEndedCount:
                    typeof t.openEndedCount === "number" ? t.openEndedCount : undefined,
                openEndedLastDone:
                    typeof t.openEndedLastDone === "string"
                        ? t.openEndedLastDone
                        : undefined,
                openEndedHistory: Array.isArray(t.openEndedHistory)
                    ? t.openEndedHistory.filter(
                          (entry): entry is string => typeof entry === "string"
                      )
                    : undefined,
                openEndedTone:
                    t.openEndedTone === "positive" || t.openEndedTone === "negative"
                        ? t.openEndedTone
                        : undefined,
                openEndedRecordDay:
                    t.openEndedRecordDay === "today" ||
                    t.openEndedRecordDay === "yesterday"
                        ? t.openEndedRecordDay
                        : undefined,
                link: typeof t.link === "string" ? t.link : undefined,
                accent: t.accent ? true : undefined,
                badges: Array.isArray(t.badges) && t.badges.length ? t.badges : undefined,
                priority: t.priority ?? "none",
                createdAt: typeof t.createdAt === "number" ? t.createdAt : now,
                updatedAt: typeof t.updatedAt === "number" ? t.updatedAt : now,
        })),
        viewOrders: normalizeViewOrders(data.viewOrders),
    };
};

const normalizeTodoPayload = (payload: unknown): TodoData | null => {
    if (Array.isArray(payload)) {
        return normalizeV3({ tasks: payload as Task[] });
    }

    if (payload && typeof payload === "object") {
        const data = payload as Partial<TodoData>;
        if (Array.isArray(data.tasks)) {
            return normalizeV3({
                tasks: data.tasks as Task[],
                viewOrders: data.viewOrders,
            });
        }
    }

    return null;
};

const isEncryptedTodoPayload = (
    payload: unknown
): payload is EncryptedTodoPayload => {
    if (!payload || typeof payload !== "object") return false;
    const obj = payload as Record<string, unknown>;
    return obj.encrypted === true && typeof obj.payload === "string";
};

const encryptTodoPayload = async (data: TodoData): Promise<EncryptedTodoPayload> => {
    const encryptionKey = getEncryptionKey();
    if (!encryptionKey) {
        throw new Error("Todo decrypt failed: VITE_ENCRYPTION_KEY missing");
    }
    const normalized = normalizeV3(data);
    const payload = JSON.stringify({
        tasks: normalized.tasks,
        viewOrders: normalized.viewOrders,
    });
    const encrypted = await encrypt(payload, encryptionKey);
    return { encrypted: true, v: 1, payload: encrypted };
};

const decryptTodoPayload = async (
    payload: EncryptedTodoPayload | string
): Promise<TodoData | null> => {
    const encryptionKey = getEncryptionKey();
    if (!encryptionKey) {
        throw new Error("Todo decrypt failed: VITE_ENCRYPTION_KEY is missing");
    }
    const encrypted = typeof payload === "string" ? payload : payload.payload;
    const decrypted = await decryptToString(encrypted, encryptionKey);
    const parsed = JSON.parse(decrypted) as unknown;
    return normalizeTodoPayload(parsed);
};

export const loadTodoData = (): TodoData => {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        if (raw) {
            const parsed = JSON.parse(raw) as Partial<TodoData>;
            if (Array.isArray(parsed.tasks)) {
                return normalizeV3({
                    tasks: parsed.tasks as Task[],
                    viewOrders: parsed.viewOrders,
                });
            }
        }

        // v2 (bucket-based)
        const legacyV2Raw = localStorage.getItem(LEGACY_V2_KEY);
        if (legacyV2Raw) {
            const parsed = JSON.parse(legacyV2Raw) as LegacyV2Data;
            const migrated = fromLegacyV2(parsed);
            if (migrated) return normalizeV3(migrated);
        }

        // v1
        const legacyV1Raw = localStorage.getItem(LEGACY_V1_KEY);
        if (legacyV1Raw) {
            const parsed = JSON.parse(legacyV1Raw) as LegacyV1;
            const v2 = legacyV1ToV2(parsed);
            if (v2) {
                const migrated = fromLegacyV2(v2);
                if (migrated) return normalizeV3(migrated);
            }
        }
    } catch {
        // ignore
    }

    return normalizeV3(defaultData);
};

export const saveTodoData = (data: TodoData) => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
    } catch {
        // ignore quota errors
    }
};

export const hasLocalTodoData = () => {
    try {
        return !!localStorage.getItem(STORAGE_KEY);
    } catch {
        return false;
    }
};

// For dirty-checking we only care about user-meaningful fields, not touch timestamps.
export const serializeTodoData = (data: TodoData) => {
    const normalized = normalizeV3(data);
    return JSON.stringify({
        tasks: normalized.tasks.map(({ createdAt: _c, updatedAt: _u, ...rest }) => rest),
        viewOrders: normalized.viewOrders,
    });
};

export const isTodoDataEqual = (a: TodoData, b: TodoData) =>
    serializeTodoData(a) === serializeTodoData(b);

export const loadRemoteSnapshot = (): RemoteSnapshot | null => {
    try {
        const raw = localStorage.getItem(REMOTE_SNAPSHOT_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw) as RemoteSnapshot;
        if (!parsed || typeof parsed.savedAt !== "number") return null;
        const normalized = normalizeTodoPayload(parsed.data);
        if (!normalized) return null;
        return { data: normalized, savedAt: parsed.savedAt };
    } catch {
        return null;
    }
};

export const saveRemoteSnapshot = (data: TodoData): RemoteSnapshot | null => {
    try {
        const snapshot: RemoteSnapshot = {
            data: normalizeV3(data),
            savedAt: Date.now(),
        };
        localStorage.setItem(REMOTE_SNAPSHOT_KEY, JSON.stringify(snapshot));
        return snapshot;
    } catch {
        return null;
    }
};

const resolveTodoApiUrl = () =>
    import.meta.env.DEV ? "/dev-api/todo-data" : "/api/todo-data";

export const fetchTodoData = async (): Promise<TodoData> => {
    const apiUrl = resolveTodoApiUrl();
    const response = await fetch(apiUrl);
    if (!response.ok) {
        throw new Error(`API load failed: ${response.status}`);
    }
    const rawText = await response.text();
    const trimmed = rawText.trim();

    let payload: unknown = null;
    if (trimmed) {
        try {
            payload = JSON.parse(trimmed) as unknown;
        } catch {
            payload = trimmed;
        }
    }

    if (isEncryptedTodoPayload(payload)) {
        const decrypted = await decryptTodoPayload(payload);
        if (!decrypted) {
            throw new Error("Todo decrypt failed: invalid payload");
        }
        return decrypted;
    }

    if (typeof payload === "string" && isEncrypted(payload)) {
        const decrypted = await decryptTodoPayload(payload);
        if (!decrypted) {
            throw new Error("Todo decrypt failed: invalid payload");
        }
        return decrypted;
    }

    const normalized = normalizeTodoPayload(payload);
    if (!normalized) {
        throw new Error("Todo data format invalid");
    }
    return normalized;
};

export const pushTodoData = async (data: TodoData) => {
    const apiUrl = resolveTodoApiUrl();
    const encryptedPayload = await encryptTodoPayload(data);
    const response = await fetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(encryptedPayload),
    });

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
            errorData.message || errorData.error || `API update failed: ${response.status}`
        );
    }
};

export const uid = () =>
    typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `id_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
