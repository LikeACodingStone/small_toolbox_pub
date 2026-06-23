import React, {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { CSSProperties, ReactNode } from "react";
import { Reorder, useDragControls } from "framer-motion";
import Draggable from "react-draggable";
import {
  fetchTodoData,
  hasLocalTodoData,
  isTodoDataEqual,
  loadRemoteSnapshot,
  loadTodoData,
  pushTodoData,
  saveRemoteSnapshot,
  saveTodoData,
  TODO_WEB_DEBUG_VERSION,
  uid,
  type Priority,
  type TaskBadge,
  type Task,
  type TodoData,
  type ViewOrderPrefs,
} from "./todoData";

export type ViewMode = "wish" | "board" | "week" | "month" | "year" | "delay";

export interface ViewConfig {
  id: string;
  title: ReactNode;
  mode: ViewMode;
  priority?: Priority; // board default
  barClass?: string;
  dimOnHover?: boolean;
}

type DetailAnchor = {
  left: number;
  top: number;
  right: number;
  bottom: number;
  width: number;
  height: number;
};

type OpenDetailFn = (id: string, anchor?: DetailAnchor) => void;

const rectToAnchor = (rect: DOMRect): DetailAnchor => ({
  left: rect.left,
  top: rect.top,
  right: rect.right,
  bottom: rect.bottom,
  width: rect.width,
  height: rect.height,
});

interface DatabaseContextValue {
  tasks: Task[];
  viewOrders?: Record<string, ViewOrderPrefs>;
  detailId: string | null;
  detailAnchor: DetailAnchor | null;
  openDetail: OpenDetailFn;
  closeDetail: () => void;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
  toggleOpenEndedDay: (id: string, dayKey: string) => void;
  discardChanges: () => void;
  createFromView: (
    view: ViewMode,
    title: string,
    extra?: { tag?: string; priority?: Priority },
  ) => string | null;
  createDelay: (payload: {
    title: string;
    category?: string;
    end?: string;
    note?: string;
  }) => void;
  updateTask: (id: string, patch: Partial<Task>) => void;
  deleteTask: (id: string) => void;
  setViewOrder: (viewId: string, order: ViewOrderPrefs) => void;
  syncEnabled: boolean;
  hasPendingChanges: boolean;
  isSyncing: boolean;
  syncError: string | null;
  lastSyncedAt: number | null;
  pushChanges: () => Promise<void>;
  pullChanges: () => Promise<void>;
}

const DatabaseContext = createContext<DatabaseContextValue | null>(null);

const useTodoDatabase = () => {
  const ctx = useContext(DatabaseContext);
  if (!ctx) throw new Error("TodoDatabaseProvider is missing");
  return ctx;
};

const hexToRgba = (hex: string, alpha = 1) => {
  const value = hex.replace("#", "");
  const normalized =
    value.length === 3
      ? value
          .split("")
          .map((c) => c + c)
          .join("")
      : value.padEnd(6, "0");

  const int = parseInt(normalized.slice(0, 6), 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const parseYmd = (v?: string) => {
  if (!v) return null;
  // Avoid Date.parse timezone quirks for "YYYY-MM-DD" by constructing local dates.
  const m = v.trim().match(/^(\d{4})[\/-](\d{1,2})[\/-](\d{1,2})$/);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]) - 1;
  const day = Number(m[3]);
  const d = new Date(year, month, day);
  if (Number.isNaN(d.getTime())) return null;
  // Guard against invalid dates like 2025/02/30
  if (d.getFullYear() !== year || d.getMonth() !== month || d.getDate() !== day)
    return null;
  return d;
};

const startOfDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};

const isOverdue = (end?: string) => {
  const d = parseYmd(end);
  if (!d) return false;
  return d < startOfDay(new Date());
};

const getOverdueDays = (end?: string) => {
  const d = parseYmd(end);
  if (!d) return 0;
  const diff = startOfDay(new Date()).getTime() - startOfDay(d).getTime();
  return diff > 0 ? Math.floor(diff / (1000 * 60 * 60 * 24)) : 0;
};

const isTaskOpenEnded = (task: Task) =>
  typeof task.openEnded === "boolean" ? task.openEnded : !task.end;

const isTaskOverdue = (task: Task) =>
  !isTaskOpenEnded(task) && isOverdue(task.end);

const getTaskOverdueDays = (task: Task) =>
  isTaskOpenEnded(task) ? 0 : getOverdueDays(task.end);

const getTaskDueTime = (task: Task) =>
  isTaskOpenEnded(task)
    ? Number.POSITIVE_INFINITY
    : (parseYmd(task.end)?.getTime() ?? Number.POSITIVE_INFINITY);

const toYmd = (d: Date) => {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}/${mm}/${dd}`;
};

const autoResizeTextarea = (el?: HTMLTextAreaElement | null) => {
  if (!el) return;
  el.style.height = "auto";
  el.style.height = `${el.scrollHeight}px`;
};

const getOpenEndedRecordKey = (task: Task, baseDate = new Date()) => {
  const offset = task.openEndedRecordDay === "yesterday" ? -1 : 0;
  const d = new Date(baseDate);
  if (offset) d.setDate(d.getDate() + offset);
  return toYmd(d);
};

const getOpenEndedRecordLabel = (task: Task) =>
  task.openEndedRecordDay === "yesterday" ? "yesterday" : "today";

const getOpenEndedRecordShortLabel = (task: Task) =>
  task.openEndedRecordDay === "yesterday" ? "yesterday" : "today";

const hasOpenEndedDay = (task: Task, dayKey: string) => {
  if (task.openEndedLastDone === dayKey) return true;
  return Array.isArray(task.openEndedHistory)
    ? task.openEndedHistory.includes(dayKey)
    : false;
};

const startOfWeek = (d: Date) => {
  const x = startOfDay(d);
  const day = x.getDay();
  const diff = (day + 6) % 7; // Monday = 0
  x.setDate(x.getDate() - diff);
  return x;
};

type HeatmapDay = {
  key: string;
  level: number;
  isToday: boolean;
  isFuture: boolean;
};

type HeatmapWeek = {
  label: string;
  days: HeatmapDay[];
};

const buildOpenEndedHeatmap = (history: string[] | undefined, weeks = 36) => {
  const today = startOfDay(new Date());
  const todayKey = toYmd(today);
  const activity = new Set(history ?? []);
  const endWeekStart = startOfWeek(today);
  const start = new Date(endWeekStart);
  start.setDate(start.getDate() - (weeks - 1) * 7);

  let lastMonth = -1;
  const result: HeatmapWeek[] = [];
  for (let w = 0; w < weeks; w += 1) {
    const weekStart = new Date(start);
    weekStart.setDate(start.getDate() + w * 7);
    const month = weekStart.getMonth();
    const label = month !== lastMonth ? `${month + 1}` : "";
    lastMonth = month;
    const days: HeatmapDay[] = [];
    for (let d = 0; d < 7; d += 1) {
      const day = new Date(weekStart);
      day.setDate(weekStart.getDate() + d);
      const key = toYmd(day);
      const isFuture = day > today;
      const level = isFuture ? 0 : activity.has(key) ? 3 : 0;
      days.push({
        key,
        level,
        isToday: key === todayKey,
        isFuture,
      });
    }
    result.push({ label, days });
  }

  return { weeks: result, total: activity.size };
};

const SectionShell: React.FC<{
  title: ReactNode;
  barClass?: string;
  className?: string;
  children: ReactNode;
}> = ({ title, barClass = "section-bar-primary", className, children }) => (
  <section className={`section${className ? ` ${className}` : ""}`}>
    <div className={`section-bar ${barClass}`}>
      <span>{title}</span>
    </div>
    <div className="section-card">{children}</div>
  </section>
);

type CategoryKey =
  | "reminder"
  | "execution"
  | "week"
  | "month"
  | "year"
  | "delay"
  | "uncategorized";

const categoryOrder: CategoryKey[] = [
  "reminder",
  "execution",
  "week",
  "month",
  "year",
  "delay",
  "uncategorized",
];

const categoryLabels: Record<CategoryKey, string> = {
  reminder: "Reminder",
  execution: "Execution",
  week: "This week",
  month: "This month",
  year: "This year",
  delay: "Overdue",
  uncategorized: "Uncategorized",
};

const getTaskCategory = (task: Task): CategoryKey => {
  if (!task.done && isTaskOverdue(task)) return "delay";
  if (task.important) return "reminder";
  if (task.week) return "week";
  if (task.month) return "month";
  if (task.annual) return "year";
  if (task.execution) return "execution";
  return "uncategorized";
};

const delayBadgePresets: TaskBadge[] = [
  { label: "Urgent", tone: "info" },
  { label: "Important", tone: "danger" },
];
const delayBadgeLabels = new Set(delayBadgePresets.map((badge) => badge.label));

const countUrgentImportant = (tasks: Task[]) => {
  const urgentLabel = "Urgent";
  const importantLabel = "Important";
  let urgent = 0;
  let important = 0;
  tasks.forEach((task) => {
    const labels = (task.badges || []).map((badge) => badge.label);
    if (labels.includes(urgentLabel)) urgent += 1;
    if (labels.includes(importantLabel)) important += 1;
  });
  return { urgent, important };
};

export const TodoDatabaseProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const syncEnabled = true;
  const initialData = loadTodoData();
  const initialSnapshot = syncEnabled ? loadRemoteSnapshot() : null;
  const hasLocal = syncEnabled ? hasLocalTodoData() : false;
  const initialDirty = syncEnabled
    ? initialSnapshot
      ? !isTodoDataEqual(initialData, initialSnapshot.data)
      : hasLocal
    : false;
  const initialDirtyRef = React.useRef(initialDirty);

  const [data, setData] = useState<TodoData>(initialData);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailAnchor, setDetailAnchor] = useState<DetailAnchor | null>(null);
  const [remoteSnapshot, setRemoteSnapshot] = useState(initialSnapshot);
  const cleanSnapshotRef = React.useRef<TodoData>(
    initialSnapshot?.data ?? initialData,
  );
  const [hasPendingChanges, setHasPendingChanges] = useState(initialDirty);
  const [isSyncing, setIsSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<number | null>(
    initialSnapshot?.savedAt ?? null,
  );
  const [isLoadingRemote, setIsLoadingRemote] = useState(syncEnabled);

  useEffect(() => {
    saveTodoData(data);
  }, [data]);

  useEffect(() => {
    if (remoteSnapshot) {
      cleanSnapshotRef.current = remoteSnapshot.data;
    }
  }, [remoteSnapshot]);

  useEffect(() => {
    if (!syncEnabled) return;
    if (!remoteSnapshot) {
      setHasPendingChanges(true);
      return;
    }
    setHasPendingChanges(!isTodoDataEqual(data, remoteSnapshot.data));
  }, [data, remoteSnapshot, syncEnabled]);

  useEffect(() => {
    if (!syncEnabled) return;
    let cancelled = false;

    const loadRemote = async () => {
      setIsLoadingRemote(true);
      setSyncError(null);

      try {
        const remoteData = await fetchTodoData();
        if (cancelled) return;

        if (!initialDirtyRef.current) {
          setData(remoteData);
          saveTodoData(remoteData);
        }

        const snapshot = saveRemoteSnapshot(remoteData);
        if (snapshot) {
          setRemoteSnapshot(snapshot);
          setLastSyncedAt(snapshot.savedAt);
        }
      } catch (error) {
        if (!cancelled) {
          setSyncError(
            error instanceof Error ? error.message : "Unable to load Todo data",
          );
        }
      } finally {
        if (!cancelled) {
          setIsLoadingRemote(false);
        }
      }
    };

    loadRemote();

    return () => {
      cancelled = true;
    };
  }, [syncEnabled]);

  const setTasks = (updater: (prev: Task[]) => Task[]) =>
    setData((prev) => ({ ...prev, tasks: updater(prev.tasks) }));

  const setViewOrder = (viewId: string, order: ViewOrderPrefs) => {
    setData((prev) => {
      const prevOrders = prev.viewOrders || {};
      const prevOrder = prevOrders[viewId];
      const nextManualOrder =
        order.manualOrder !== undefined
          ? order.manualOrder.length
            ? order.manualOrder
            : undefined
          : prevOrder?.manualOrder;
      const nextManualOrderByPriority =
        order.manualOrderByPriority !== undefined
          ? {
              ...(prevOrder?.manualOrderByPriority || {}),
              ...order.manualOrderByPriority,
            }
          : prevOrder?.manualOrderByPriority;
      const nextOrder: ViewOrderPrefs = {
        manualOrder: nextManualOrder,
        manualOrderByPriority: nextManualOrderByPriority,
      };
      if (areViewOrdersEqual(prevOrder, nextOrder)) return prev;
      return {
        ...prev,
        viewOrders: {
          ...prevOrders,
          [viewId]: nextOrder,
        },
      };
    });
  };

  const deleteTask = (id: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== id));
    setDetailId((cur) => (cur === id ? null : cur));
  };

  const updateTask = (id: string, patch: Partial<Task>) => {
    const now = Date.now();
    setTasks((prev) =>
      prev.map((t) => (t.id === id ? { ...t, ...patch, updatedAt: now } : t)),
    );
  };

  const toggleDone = (id: string) => {
    const now = Date.now();
    setTasks((prev) =>
      prev.map((t) =>
        t.id === id ? { ...t, done: !t.done, updatedAt: now } : t,
      ),
    );
  };

  const incrementOpenEndedCount = (id: string) => {
    const baseDate = new Date();
    const now = Date.now();
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        if (!isTaskOpenEnded(t)) return t;
        const recordKey = getOpenEndedRecordKey(t, baseDate);
        if (hasOpenEndedDay(t, recordKey)) return t;
        const nextHistory = Array.isArray(t.openEndedHistory)
          ? t.openEndedHistory.includes(recordKey)
            ? t.openEndedHistory
            : [...t.openEndedHistory, recordKey]
          : [recordKey];
        const baseCount =
          typeof t.openEndedCount === "number"
            ? t.openEndedCount
            : (t.openEndedHistory?.length ?? 0);
        const nextCount = baseCount + 1;
        const nextLastDone = nextHistory.length
          ? nextHistory.reduce(
              (latest, cur) => (cur > latest ? cur : latest),
              nextHistory[0],
            )
          : undefined;
        return {
          ...t,
          openEndedCount: nextCount,
          openEndedLastDone: nextLastDone,
          openEndedHistory: nextHistory,
          updatedAt: now,
        };
      }),
    );
  };

  const decrementOpenEndedCount = (id: string) => {
    const baseDate = new Date();
    const now = Date.now();
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        if (!isTaskOpenEnded(t)) return t;
        const recordKey = getOpenEndedRecordKey(t, baseDate);
        const history = Array.isArray(t.openEndedHistory)
          ? t.openEndedHistory
          : [];
        const baseCount =
          typeof t.openEndedCount === "number"
            ? t.openEndedCount
            : history.length;
        if (baseCount <= 0 && history.length === 0) return t;

        let nextHistory = history;
        let removed: string | null = null;
        if (history.length > 0) {
          if (history.includes(recordKey)) {
            removed = recordKey;
          } else {
            removed = history.reduce(
              (latest, cur) => (cur > latest ? cur : latest),
              history[0],
            );
          }
          nextHistory = history.filter((d) => d !== removed);
        }

        let nextLastDone = t.openEndedLastDone;
        if (removed && nextLastDone === removed) {
          nextLastDone = nextHistory.length
            ? nextHistory.reduce(
                (latest, cur) => (cur > latest ? cur : latest),
                nextHistory[0],
              )
            : undefined;
        } else if (!removed && t.openEndedLastDone === recordKey) {
          nextLastDone = undefined;
        }

        if (
          nextHistory.length > 0 &&
          (!nextLastDone || !nextHistory.includes(nextLastDone))
        ) {
          nextLastDone = nextHistory.reduce(
            (latest, cur) => (cur > latest ? cur : latest),
            nextHistory[0],
          );
        }

        const nextCount = Math.max(baseCount - 1, 0);

        return {
          ...t,
          openEndedCount: nextCount,
          openEndedHistory: nextHistory.length ? nextHistory : undefined,
          openEndedLastDone: nextLastDone,
          updatedAt: now,
        };
      }),
    );
  };

  const toggleOpenEndedDay = (id: string, dayKey: string) => {
    const day = parseYmd(dayKey);
    if (!day) return;
    const normalized = toYmd(day);
    const today = startOfDay(new Date());
    if (startOfDay(day) > today) return;
    const now = Date.now();
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== id) return t;
        if (!isTaskOpenEnded(t)) return t;

        const historyArr = Array.isArray(t.openEndedHistory)
          ? t.openEndedHistory
          : [];
        const historySet = new Set(historyArr);
        if (t.openEndedLastDone) {
          historySet.add(t.openEndedLastDone);
        }
        const hasDay = historySet.has(normalized);
        const baseCount =
          typeof t.openEndedCount === "number"
            ? Math.max(t.openEndedCount, historySet.size)
            : historySet.size;

        const nextHistorySet = new Set(historySet);
        const nextCount = hasDay ? Math.max(baseCount - 1, 0) : baseCount + 1;

        if (hasDay) {
          nextHistorySet.delete(normalized);
        } else {
          nextHistorySet.add(normalized);
        }

        const nextHistory = Array.from(nextHistorySet);
        const nextLastDone = nextHistory.length
          ? nextHistory.reduce(
              (latest, cur) => (cur > latest ? cur : latest),
              nextHistory[0],
            )
          : undefined;

        return {
          ...t,
          openEndedCount: nextCount,
          openEndedHistory: nextHistory.length ? nextHistory : undefined,
          openEndedLastDone: nextLastDone,
          updatedAt: now,
        };
      }),
    );
  };

  const createFromView = (
    view: ViewMode,
    title: string,
    extra?: { tag?: string; priority?: Priority },
  ) => {
    const trimmed = title.trim();
    if (!trimmed) return null;

    const now = Date.now();
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const yesterdayStr = toYmd(yesterday);

    const id = uid();
    const task: Task = {
      id,
      title: trimmed,
      tag: extra?.tag?.trim() || undefined,
      createdAt: now,
      updatedAt: now,
    };

    if (view === "wish") {
      task.important = true;
    }

    if (view === "board") {
      task.execution = true;
      task.priority = extra?.priority ?? "none";
    }

    if (view === "week") {
      task.week = true;
    }

    if (view === "month") {
      task.month = true;
    }

    if (view === "year") {
      task.annual = true;
    }

    if (view === "delay") {
      // Create inside the overdue view so it appears there immediately.
      task.execution = true;
      task.end = yesterdayStr;
      task.badges = [{ label: "Important", tone: "danger" }];
    }

    setTasks((prev) => [...prev, task]);
    return id;
  };

  const createDelay = (payload: {
    title: string;
    category?: string;
    end?: string;
    note?: string;
  }) => {
    const trimmed = payload.title.trim();
    if (!trimmed) return;

    const now = Date.now();
    const today = new Date();
    const start = toYmd(today);
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const defaultEnd = toYmd(yesterday);

    setTasks((prev) => [
      ...prev,
      {
        id: uid(),
        title: trimmed,
        execution: true,
        category: payload.category?.trim() || "Uncategorized",
        start,
        end: payload.end?.trim() || defaultEnd,
        note: payload.note?.trim() || undefined,
        badges: [{ label: "Important", tone: "danger" }],
        createdAt: now,
        updatedAt: now,
      },
    ]);
  };

  const pushChanges = async () => {
    if (!syncEnabled || isSyncing) return;
    setIsSyncing(true);
    setSyncError(null);

    try {
      await pushTodoData(data);
      const snapshot = saveRemoteSnapshot(data);
      if (snapshot) {
        setRemoteSnapshot(snapshot);
        setLastSyncedAt(snapshot.savedAt);
      }
      setHasPendingChanges(false);
      initialDirtyRef.current = false;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Push failed";
      setSyncError(message);
      throw error;
    } finally {
      setIsSyncing(false);
    }
  };

  const pullChanges = async () => {
    if (!syncEnabled || isSyncing) return;
    setIsSyncing(true);
    setSyncError(null);

    try {
      const remoteData = await fetchTodoData();
      setData(remoteData);
      saveTodoData(remoteData);
      const snapshot = saveRemoteSnapshot(remoteData);
      if (snapshot) {
        setRemoteSnapshot(snapshot);
        setLastSyncedAt(snapshot.savedAt);
      }
      setHasPendingChanges(false);
      initialDirtyRef.current = false;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Pull failed";
      setSyncError(message);
      throw error;
    } finally {
      setIsSyncing(false);
    }
  };

  const discardChanges = () => {
    const clean = cleanSnapshotRef.current;
    if (!clean) return;
    setData(clean);
    setDetailId(null);
    setDetailAnchor(null);
    setHasPendingChanges(false);
    initialDirtyRef.current = false;
  };

  const value: DatabaseContextValue = {
    tasks: data.tasks,
    viewOrders: data.viewOrders,
    detailId,
    detailAnchor,
    openDetail: (id, anchor) => {
      setDetailAnchor(anchor ?? null);
      setDetailId(id);
    },
    closeDetail: () => {
      setDetailId(null);
      setDetailAnchor(null);
    },
    toggleDone,
    incrementOpenEndedCount,
    decrementOpenEndedCount,
    toggleOpenEndedDay,
    discardChanges,
    createFromView,
    createDelay,
    updateTask,
    deleteTask,
    setViewOrder,
    syncEnabled,
    hasPendingChanges,
    isSyncing: isSyncing || isLoadingRemote,
    syncError,
    lastSyncedAt,
    pushChanges,
    pullChanges,
  };

  return (
    <DatabaseContext.Provider value={value}>
      {children}
      <DatabaseDetailDrawer />
    </DatabaseContext.Provider>
  );
};

const formatSyncTime = (timestamp: number) => {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

interface TodoSyncBarProps {
  onLock: () => void;
}

export const TodoSyncBar: React.FC<TodoSyncBarProps> = ({ onLock }) => {
  const {
    tasks,
    openDetail,
    toggleDone,
    incrementOpenEndedCount,
    decrementOpenEndedCount,
    viewOrders,
    syncEnabled,
    hasPendingChanges,
    isSyncing,
    syncError,
    lastSyncedAt,
    pushChanges,
    pullChanges,
    discardChanges,
  } = useTodoDatabase();
  const [confirmMode, setConfirmMode] = useState<
    "push" | "pull" | "discard" | null
  >(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showAllModal, setShowAllModal] = useState(false);
  const [allOrderByCategory, setAllOrderByCategory] = useState<
    Partial<Record<CategoryKey, string[]>>
  >(() => loadAllOrderByCategory());
  const allModalRef = useRef<HTMLDivElement>(null);
  const stopOverlayClose = (event: React.SyntheticEvent) => {
    event.stopPropagation();
  };

  useEffect(() => {
    saveAllOrderByCategory(allOrderByCategory);
  }, [allOrderByCategory]);

  useEffect(() => {
    if (!showAllModal) return;

    const onGlobalClick = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const target = event.target as Node | null;
      const modal = allModalRef.current;
      if (!target || !modal) return;

      const drawerPanel = document.querySelector(".task-drawer__panel");
      if (drawerPanel && drawerPanel.contains(target)) return;

      if (modal.contains(target)) return;
      setShowAllModal(false);
    };

    window.addEventListener("click", onGlobalClick, true);
    return () => window.removeEventListener("click", onGlobalClick, true);
  }, [showAllModal]);

  if (!syncEnabled) return null;

  const statusText = isSyncing
    ? "Syncing..."
    : hasPendingChanges
      ? "Unpushed changes"
      : "Synced";

  const taskSummary = useMemo(() => {
    const total = tasks.length;
    const done = tasks.filter((t) => !!t.done).length;
    const overdue = tasks.filter((t) => !t.done && isTaskOverdue(t)).length;
    return { total, done, overdue };
  }, [tasks]);

  const mergePriorityOrders = (
    orders?: Partial<Record<Priority, string[]>>,
  ) => {
    if (!orders) return undefined;
    const merged: string[] = [];
    const seen = new Set<string>();
    priorityOrder.forEach((priority) => {
      const list = orders[priority] || [];
      list.forEach((id) => {
        if (seen.has(id)) return;
        seen.add(id);
        merged.push(id);
      });
    });
    return merged.length ? merged : undefined;
  };

  const getCategorySort = (category: CategoryKey) => {
    const viewMap: Record<CategoryKey, { id: string; mode: ViewMode } | null> =
      {
        reminder: { id: "wish", mode: "wish" },
        execution: { id: "board-high", mode: "board" },
        week: { id: "week", mode: "week" },
        month: { id: "month", mode: "month" },
        year: { id: "year", mode: "year" },
        delay: { id: "delay", mode: "delay" },
        uncategorized: null,
      };
    const view = viewMap[category];
    if (!view) return { sort: "updated" as SortMode, manualOrder: undefined };
    const prefs = loadViewPrefs(view.id, view.mode, viewOrders?.[view.id]);
    const manualOrder =
      view.mode === "board" && prefs.sort === "manual"
        ? mergePriorityOrders(prefs.manualOrderByPriority)
        : prefs.manualOrder;
    return { sort: prefs.sort, manualOrder };
  };

  const groupedTasks = useMemo(() => {
    const buckets = new Map<CategoryKey, Task[]>();
    categoryOrder.forEach((key) => buckets.set(key, []));
    tasks.forEach((task) => {
      const category = getTaskCategory(task);
      buckets.get(category)?.push(task);
    });

    return categoryOrder.map((category) => {
      const list = buckets.get(category) ?? [];
      const { sort, manualOrder } = getCategorySort(category);
      const sorted = sortByMode(list, sort, manualOrder);
      const ids = sorted.map((task) => task.id);
      const current = allOrderByCategory[category] || [];
      const existing = new Set(ids);
      const merged = [
        ...current.filter((id) => existing.has(id)),
        ...ids.filter((id) => !current.includes(id)),
      ];
      const taskMap = new Map(sorted.map((task) => [task.id, task]));
      return {
        category,
        ids: merged,
        tasks: merged
          .map((id) => taskMap.get(id))
          .filter((item): item is Task => !!item),
      };
    });
  }, [tasks, allOrderByCategory, showAllModal, viewOrders]);

  const groupedRows = useMemo(() => {
    let displayIndex = 0;
    return groupedTasks.map((group) => ({
      ...group,
      rows: group.tasks.map((task) => {
        displayIndex += 1;
        return { task, index: displayIndex };
      }),
    }));
  }, [groupedTasks]);

  const handlePush = () => {
    if (isSyncing || !hasPendingChanges) return;
    setConfirmMode("push");
  };

  const handlePull = () => {
    if (isSyncing) return;
    if (hasPendingChanges) {
      setConfirmMode("pull");
      return;
    }
    pullChanges()
      .then(() => {
        setNotice("Pulled latest data");
        window.setTimeout(() => setNotice(null), 2400);
      })
      .catch(() => {
        // The error message is already shown in state.
      });
  };

  const handleOpenAll = () => {
    if (isSyncing) return;
    setShowAllModal(true);
  };

  const handleDiscard = () => {
    if (isSyncing || !hasPendingChanges) return;
    setConfirmMode("discard");
  };

  const handleDebug = () => {
    window.open("/api/debug/env", "_blank", "noopener,noreferrer");
  };

  const handleConfirm = async () => {
    if (isSyncing) return;
    const mode = confirmMode;
    setConfirmMode(null);
    setNotice(null);

    if (mode === "discard") {
      discardChanges();
      setNotice("Local changes discarded");
      window.setTimeout(() => setNotice(null), 2400);
      return;
    }

    if (mode === "pull") {
      try {
        await pullChanges();
        setNotice("Pulled latest data");
        window.setTimeout(() => setNotice(null), 2400);
      } catch {
        // The error message is already shown in state.
      }
      return;
    }

    if (mode === "push") {
      try {
        await pushChanges();
        setNotice("Pushed to GitHub");
        window.setTimeout(() => setNotice(null), 2400);
      } catch {
        // The error message is already shown in state.
      }
    }
  };

  return (
    <>
      <div className="todo-sync-bar">
        <div className="todo-sync-status">
          <span
            className={`sync-dot ${hasPendingChanges ? "dirty" : "clean"}`}
            aria-hidden="true"
          />
          <span className="sync-text">{statusText}</span>
          {lastSyncedAt && (
            <span className="sync-time">
              Last sync: {formatSyncTime(lastSyncedAt)}
            </span>
          )}
          {notice && <span className="sync-notice">OK {notice}</span>}
          {syncError && (
            <span className="sync-error">Sync failed: {syncError}</span>
          )}
          <span className="sync-debug-version" title={TODO_WEB_DEBUG_VERSION}>
            debug {TODO_WEB_DEBUG_VERSION}
          </span>
        </div>
        <div className="sync-actions">
          <button
            type="button"
            className="sync-lock-btn"
            onClick={onLock}
            aria-label="Lock"
            title="Lock"
          >
            <svg
              className="sync-lock-btn__svg"
              viewBox="0 0 24 24"
              aria-hidden="true"
              focusable="false"
            >
              <path d="M8 10V7a4 4 0 0 1 8 0v3" />
              <rect x="7" y="10" width="10" height="10" rx="2" />
            </svg>
          </button>
          <button
            type="button"
            className="sync-btn ghost"
            onClick={handleDiscard}
            disabled={!hasPendingChanges || isSyncing}
          >
            Discard changes
          </button>
          <button
            type="button"
            className="sync-btn ghost"
            onClick={handlePull}
            disabled={isSyncing}
          >
            {isSyncing ? "Pulling..." : "Pull"}
          </button>
          <button
            type="button"
            className="sync-btn"
            onClick={handlePush}
            disabled={!hasPendingChanges || isSyncing}
          >
            {isSyncing ? "Pushing..." : "Push"}
          </button>
          <button
            type="button"
            className="sync-btn cute"
            onClick={handleOpenAll}
            disabled={isSyncing}
          >
            {"All"}
          </button>
          <button
            type="button"
            className="sync-btn debug"
            onClick={handleDebug}
            title="Open deployment diagnostics"
          >
            Debug
          </button>
        </div>
      </div>

      {confirmMode && (
        <div
          className="todo-modal-overlay"
          onClick={() => setConfirmMode(null)}
        >
          <div className="todo-modal" onClick={(e) => e.stopPropagation()}>
            <div className="todo-modal-emoji">!</div>
            <div className="todo-modal-title">
              {confirmMode === "push"
                ? "Push changes to GitHub?"
                : confirmMode === "pull"
                  ? "Pull the latest data from GitHub?"
                  : "Discard local changes?"}
            </div>
            <div className="todo-modal-desc">
              {confirmMode === "push"
                ? "This will overwrite the remote Todo data and sync immediately."
                : confirmMode === "pull"
                  ? "This will overwrite local changes with remote data and sync immediately."
                  : "This will restore the last synced data. Unpushed local changes will be lost."}
            </div>
            <div className="todo-modal-actions">
              <button
                type="button"
                className="modal-btn ghost"
                onClick={() => setConfirmMode(null)}
              >
                Not yet
              </button>
              <button
                type="button"
                className="modal-btn primary"
                onClick={handleConfirm}
                disabled={isSyncing}
              >
                {confirmMode === "push"
                  ? "Push now"
                  : confirmMode === "pull"
                    ? "Pull now"
                    : "Confirm discard"}
              </button>
            </div>
          </div>
        </div>
      )}

      {showAllModal && (
        <div
          className="todo-modal-overlay todo-modal-overlay--pass"
          onClick={stopOverlayClose}
          onMouseDown={stopOverlayClose}
          onPointerDown={stopOverlayClose}
        >
          <div className="todo-modal-drag-area">
            <Draggable
              handle=".todo-all-bar"
              cancel=".todo-all-bar button"
              bounds="parent"
              nodeRef={allModalRef as React.RefObject<HTMLElement>}
            >
              <div className="todo-modal todo-all-modal" ref={allModalRef}>
                <div className="todo-all-bar">
                  <div className="todo-all-heading">
                    <span className="dot purple" />
                    <div>
                      <div className="todo-all-title">{"All Tasks"}</div>
                      <div className="todo-all-meta">
                        {`Total ${taskSummary.total} - Done ${taskSummary.done} - Overdue ${taskSummary.overdue}`}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="icon-btn subtle"
                    aria-label={"Close"}
                    onClick={() => setShowAllModal(false)}
                  >
                    {"x"}
                  </button>
                </div>
                <div className="todo-all-inner">
                  <div className="sub-toolbar todo-all-sub">
                    <div className="toolbar-chip">{"All ToDo"}</div>
                    <span className="muted">
                      {taskSummary.total}
                      {" items"}
                    </span>
                  </div>
                  {tasks.length === 0 ? (
                    <div className="todo-all-empty">
                      {"No tasks yet"}
                    </div>
                  ) : (
                    <div className="todo-all-scroll">
                      {groupedRows.map((group) =>
                        group.rows.length === 0 ? null : (
                          <Reorder.Group
                            key={group.category}
                            as="ol"
                            className="year-list todo-all-list"
                            axis="y"
                            values={group.ids}
                            onReorder={(ids) =>
                              setAllOrderByCategory((prev) => ({
                                ...prev,
                                [group.category]: ids,
                              }))
                            }
                          >
                            {group.rows.map((row) => (
                              <AllModalRowItem
                                key={row.task.id}
                                task={row.task}
                                index={row.index}
                                openDetail={openDetail}
                                toggleDone={toggleDone}
                                incrementOpenEndedCount={
                                  incrementOpenEndedCount
                                }
                                decrementOpenEndedCount={
                                  decrementOpenEndedCount
                                }
                              />
                            ))}
                          </Reorder.Group>
                        ),
                      )}
                    </div>
                  )}
                </div>
              </div>
            </Draggable>
          </div>
        </div>
      )}
    </>
  );
};

const priorityTitle: Record<Priority, string> = {
  high: "High priority",
  mid: "Medium priority",
  low: "Low priority",
  none: "No priority",
};

const priorityOrder: Priority[] = ["high", "mid", "low", "none"];

const priorityTone: Record<Priority, string> = {
  high: "#6bc4a5",
  mid: "#7aa3ff",
  low: "#c08bff",
  none: "#8a92a2",
};

const indexTonePalette = [
  "#7fb1ff",
  "#c79bff",
  "#ff8a8a",
  "#7bd8b2",
  "#ffd166",
  "#ff9f80",
  "#8fd3ff",
  "#f59ab4",
];

const getIndexToneById = (id: string) => {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) {
    hash = (hash * 31 + id.charCodeAt(i)) | 0;
  }
  const idx = Math.abs(hash) % indexTonePalette.length;
  return indexTonePalette[idx];
};

type BoardPriority = Priority | "all";

type SortMode = "manual" | "updated" | "title" | "due" | "overdue";

type ViewPrefs = {
  query: string;
  hideDone: boolean;
  sort: SortMode;
  manualOrder?: string[];
  manualOrderByPriority?: Partial<Record<Priority, string[]>>;
};

const viewPrefsKey = (viewId: string) => `todo-view-prefs-v1:${viewId}`;

const sortOptionsByMode: Record<ViewMode, SortMode[]> = {
  wish: ["updated", "title", "manual"],
  board: ["updated", "title", "due", "manual"],
  week: ["due", "updated", "title", "manual"],
  month: ["due", "updated", "title", "manual"],
  year: ["updated", "title", "manual"],
  delay: ["overdue", "updated", "title", "manual"],
};

const defaultPrefsForMode = (mode: ViewMode): ViewPrefs => ({
  query: "",
  hideDone: false,
  sort: sortOptionsByMode[mode][0],
});

const areStringArraysEqual = (a?: string[], b?: string[]) => {
  if (a === b) return true;
  if (!a || !b) return !a && !b;
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i += 1) {
    if (a[i] !== b[i]) return false;
  }
  return true;
};

const areOrderByPriorityEqual = (
  a?: Partial<Record<Priority, string[]>>,
  b?: Partial<Record<Priority, string[]>>,
) => {
  if (a === b) return true;
  const keys: Priority[] = ["high", "mid", "low", "none"];
  return keys.every((key) => areStringArraysEqual(a?.[key], b?.[key]));
};

const areViewOrdersEqual = (a?: ViewOrderPrefs, b?: ViewOrderPrefs) =>
  areStringArraysEqual(a?.manualOrder, b?.manualOrder) &&
  areOrderByPriorityEqual(a?.manualOrderByPriority, b?.manualOrderByPriority);

const loadViewPrefs = (
  viewId: string,
  mode: ViewMode,
  orderOverride?: ViewOrderPrefs,
): ViewPrefs => {
  const fallback = defaultPrefsForMode(mode);
  try {
    const raw = localStorage.getItem(viewPrefsKey(viewId));
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<ViewPrefs> & {
      manualOrder?: unknown;
      manualOrderByPriority?: unknown;
    };
    const sortOptions = sortOptionsByMode[mode];
    const sort = sortOptions.includes(parsed.sort as SortMode)
      ? (parsed.sort as SortMode)
      : fallback.sort;

    const pickStringArray = (v: unknown) =>
      Array.isArray(v)
        ? v.filter((x): x is string => typeof x === "string")
        : undefined;

    const rawByPriority = parsed.manualOrderByPriority;
    const manualOrderByPriority =
      rawByPriority && typeof rawByPriority === "object"
        ? ({
            high: pickStringArray(
              (rawByPriority as Record<string, unknown>).high,
            ),
            mid: pickStringArray(
              (rawByPriority as Record<string, unknown>).mid,
            ),
            low: pickStringArray(
              (rawByPriority as Record<string, unknown>).low,
            ),
            none: pickStringArray(
              (rawByPriority as Record<string, unknown>).none,
            ),
          } satisfies Partial<Record<Priority, string[]>>)
        : undefined;

    const resolvedManualOrder = orderOverride?.manualOrder;
    const resolvedManualOrderByPriority = orderOverride?.manualOrderByPriority;

    return {
      query: typeof parsed.query === "string" ? parsed.query : "",
      hideDone: typeof parsed.hideDone === "boolean" ? parsed.hideDone : false,
      sort,
      manualOrder:
        resolvedManualOrder ?? pickStringArray(parsed.manualOrder) ?? undefined,
      manualOrderByPriority:
        resolvedManualOrderByPriority ?? manualOrderByPriority,
    };
  } catch {
    return fallback;
  }
};

const saveViewPrefs = (viewId: string, prefs: ViewPrefs) => {
  try {
    localStorage.setItem(viewPrefsKey(viewId), JSON.stringify(prefs));
  } catch {
    // ignore quota errors
  }
};

const allOrderKey = "todo-all-order-v1";

function loadAllOrderByCategory(): Partial<Record<CategoryKey, string[]>> {
  try {
    const raw = localStorage.getItem(allOrderKey);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, unknown>;
    if (!parsed || typeof parsed !== "object") return {};
    const pickStringArray = (v: unknown) =>
      Array.isArray(v)
        ? v.filter((x): x is string => typeof x === "string")
        : undefined;
    const result: Partial<Record<CategoryKey, string[]>> = {};
    categoryOrder.forEach((key) => {
      const ids = pickStringArray(parsed[key]);
      if (ids && ids.length) result[key] = ids;
    });
    return result;
  } catch {
    return {};
  }
}

function saveAllOrderByCategory(order: Partial<Record<CategoryKey, string[]>>) {
  try {
    localStorage.setItem(allOrderKey, JSON.stringify(order));
  } catch {
    // ignore quota errors
  }
}

const nextSortMode = (mode: ViewMode, current: SortMode) => {
  const options = sortOptionsByMode[mode] || ["updated"];
  const idx = options.indexOf(current);
  return options[(idx + 1) % options.length];
};

const matchTaskQuery = (t: Task, q: string) => {
  const query = q.trim().toLowerCase();
  if (!query) return true;
  const haystack = [t.title, t.tag, t.category, t.note, t.start, t.end]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
  return haystack.includes(query);
};

const compareTitle = (a: Task, b: Task) =>
  a.title.localeCompare(b.title, "zh-Hans-CN", {
    numeric: true,
    sensitivity: "base",
  });

const compareDueAsc = (a: Task, b: Task) => {
  const at = getTaskDueTime(a);
  const bt = getTaskDueTime(b);
  if (at !== bt) return at - bt;
  return (b.updatedAt || 0) - (a.updatedAt || 0);
};

const compareOverdueDesc = (a: Task, b: Task) => {
  const ao = getTaskOverdueDays(a);
  const bo = getTaskOverdueDays(b);
  if (ao !== bo) return bo - ao;
  return (b.updatedAt || 0) - (a.updatedAt || 0);
};

const sortByManualOrder = (list: Task[], manualOrder?: string[]) => {
  const idx = new Map<string, number>();
  for (const [i, id] of (manualOrder || []).entries()) {
    idx.set(id, i);
  }

  const sorted = [...list];
  sorted.sort((a, b) => {
    const ad = !!a.done;
    const bd = !!b.done;
    if (ad !== bd) return ad ? 1 : -1;

    const ai = idx.get(a.id);
    const bi = idx.get(b.id);
    if (ai != null && bi != null) return ai - bi;
    if (ai != null) return -1;
    if (bi != null) return 1;

    return (b.updatedAt || 0) - (a.updatedAt || 0);
  });
  return sorted;
};

const sortByMode = (list: Task[], mode: SortMode, manualOrder?: string[]) => {
  if (mode === "manual") return sortByManualOrder(list, manualOrder);

  const sorted = [...list];
  sorted.sort((a, b) => {
    const ad = !!a.done;
    const bd = !!b.done;
    if (ad !== bd) return ad ? 1 : -1;

    if (mode === "title") return compareTitle(a, b);
    if (mode === "due") return compareDueAsc(a, b);
    if (mode === "overdue") return compareOverdueDesc(a, b);
    return (b.updatedAt || 0) - (a.updatedAt || 0);
  });
  return sorted;
};

const applyViewPrefs = (list: Task[], prefs: ViewPrefs) => {
  const filtered = list.filter(
    (t) => matchTaskQuery(t, prefs.query) && (!prefs.hideDone || !t.done),
  );
  return sortByMode(filtered, prefs.sort, prefs.manualOrder);
};

const getOpenEndedDividerIndex = (list: Task[]) => {
  if (list.length < 2) return null;
  let firstOpen = -1;
  let lastOpen = -1;
  let openCount = 0;
  list.forEach((task, idx) => {
    if (!isTaskOpenEnded(task)) return;
    openCount += 1;
    if (firstOpen === -1) firstOpen = idx;
    lastOpen = idx;
  });

  if (openCount === 0 || openCount === list.length) return null;
  const openBlock = lastOpen - firstOpen + 1 === openCount;
  if (!openBlock) return null;
  if (firstOpen === 0) return lastOpen + 1;
  if (lastOpen === list.length - 1) return firstOpen;
  return null;
};

const getOpenEndedToneDividerIndex = (list: Task[]) => {
  if (list.length < 2) return null;
  let firstOpen = -1;
  let lastOpen = -1;
  let openCount = 0;
  list.forEach((task, idx) => {
    if (!isTaskOpenEnded(task)) return;
    openCount += 1;
    if (firstOpen === -1) firstOpen = idx;
    lastOpen = idx;
  });

  if (openCount < 2) return null;
  const openBlock = lastOpen - firstOpen + 1 === openCount;
  if (!openBlock) return null;

  const tones = list
    .slice(firstOpen, lastOpen + 1)
    .map((task) =>
      task.openEndedTone === "negative" ? "negative" : "positive",
    );
  const hasPositive = tones.includes("positive");
  const hasNegative = tones.includes("negative");
  if (!hasPositive || !hasNegative) return null;

  const firstTone = tones[0];
  const splitIndex = tones.findIndex((tone) => tone !== firstTone);
  if (splitIndex === -1) return null;
  for (let i = splitIndex; i < tones.length; i += 1) {
    if (tones[i] === firstTone) return null;
  }
  return firstOpen + splitIndex;
};

export const DatabaseView: React.FC<{ view: ViewConfig }> = ({ view }) => {
  const {
    tasks,
    toggleDone,
    incrementOpenEndedCount,
    decrementOpenEndedCount,
    createFromView,
    openDetail,
    detailId,
    deleteTask,
    viewOrders,
    setViewOrder,
  } = useTodoDatabase();

  const [prefs, setPrefs] = useState<ViewPrefs>(() =>
    loadViewPrefs(view.id, view.mode, viewOrders?.[view.id]),
  );
  const [searchOpen, setSearchOpen] = useState(false);
  const searchRef = React.useRef<HTMLInputElement>(null);
  const searchVisible = searchOpen || prefs.query.trim().length > 0;
  const hoverReveal =
    view.mode === "week" || view.mode === "month" || view.mode === "year";
  const sectionClassName =
    [
      hoverReveal ? "section--hover-reveal" : null,
      view.dimOnHover ? "section--dim-hover" : null,
    ]
      .filter(Boolean)
      .join(" ") || undefined;

  useEffect(() => {
    saveViewPrefs(view.id, prefs);
  }, [view.id, prefs]);

  useEffect(() => {
    const order = viewOrders?.[view.id];
    if (!order) return;
    setPrefs((prev) => {
      const prevOrder: ViewOrderPrefs = {
        manualOrder: prev.manualOrder,
        manualOrderByPriority: prev.manualOrderByPriority,
      };
      if (areViewOrdersEqual(prevOrder, order)) return prev;
      return {
        ...prev,
        manualOrder: order.manualOrder,
        manualOrderByPriority: order.manualOrderByPriority,
      };
    });
  }, [view.id, viewOrders]);

  useEffect(() => {
    if (!searchVisible) return;
    const t = window.setTimeout(() => searchRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [searchVisible]);

  const sortLabel: Record<SortMode, string> = {
    manual: "Manual",
    updated: "Latest",
    title: "Title",
    due: "Due date",
    overdue: "Overdue",
  };

  const clearSearch = () => {
    setPrefs((prev) => ({ ...prev, query: "" }));
    setSearchOpen(false);
  };

  const toggleSearch = () => {
    if (searchVisible) {
      clearSearch();
      return;
    }
    setSearchOpen(true);
  };

  const toggleHideDone = () =>
    setPrefs((prev) => ({ ...prev, hideDone: !prev.hideDone }));
  const cycleSort = () =>
    setPrefs((prev) => ({ ...prev, sort: nextSortMode(view.mode, prev.sort) }));

  const [expanded, setExpanded] = useState(true);

  const [activePriority, setActivePriority] = useState<BoardPriority>(
    view.priority ?? "high",
  );

  const selectedTask = useMemo(
    () => tasks.find((t) => t.id === detailId) || null,
    [tasks, detailId],
  );

  useEffect(() => {
    if (view.mode === "board") {
      setActivePriority(view.priority ?? "high");
    }
  }, [view.mode, view.priority]);

  const importantTasks = useMemo(
    () => tasks.filter((t) => !!t.important),
    [tasks],
  );

  const executionTasks = useMemo(
    () => tasks.filter((t) => !!t.execution),
    [tasks],
  );

  const annualTasks = useMemo(() => tasks.filter((t) => !!t.annual), [tasks]);

  const weekTasks = useMemo(() => tasks.filter((t) => !!t.week), [tasks]);

  const monthTasks = useMemo(() => tasks.filter((t) => !!t.month), [tasks]);

  const delayTasks = useMemo(
    () => tasks.filter((t) => !t.done && isTaskOverdue(t)),
    [tasks],
  );

  const executionFiltered = useMemo(
    () =>
      executionTasks.filter(
        (t) => matchTaskQuery(t, prefs.query) && (!prefs.hideDone || !t.done),
      ),
    [executionTasks, prefs.hideDone, prefs.query],
  );

  const boardCounts = useMemo(() => {
    const counts: Record<Priority, number> = {
      high: 0,
      mid: 0,
      low: 0,
      none: 0,
    };
    for (const t of executionFiltered) {
      const p = (t.priority ?? "none") as Priority;
      counts[p] += 1;
    }
    const list: Array<{
      id: BoardPriority;
      title: string;
      tone: string;
      count: number;
    }> = priorityOrder.map((id) => ({
      id,
      title: priorityTitle[id],
      tone: priorityTone[id],
      count: counts[id],
    }));
    list.push({
      id: "all",
      title: "All",
      tone: "#8fa2bb",
      count: executionFiltered.length,
    });
    return list;
  }, [executionFiltered]);

  const boardTasks = useMemo(() => {
    if (activePriority === "all") {
      return sortByMode(executionFiltered, prefs.sort, prefs.manualOrder);
    }
    return sortByMode(
      executionFiltered.filter(
        (t) => (t.priority ?? "none") === activePriority,
      ),
      prefs.sort,
      prefs.manualOrderByPriority?.[activePriority],
    );
  }, [
    activePriority,
    executionFiltered,
    prefs.manualOrder,
    prefs.manualOrderByPriority,
    prefs.sort,
  ]);
  const boardBadgeCounts = useMemo(
    () => countUrgentImportant(boardTasks),
    [boardTasks],
  );

  const barClass =
    view.barClass ||
    (view.mode === "delay" ? "section-bar-gold" : "section-bar-primary");

  const titleNode =
    view.mode === "board" ? (
      <span className="pink">{view.title}</span>
    ) : (
      view.title
    );

  const renderProgress = (total: number, done: number) => {
    const percent = total ? Math.round((done / total) * 100) : 0;
    return (
      <div className="progress-inline" aria-label={`Done ${done}/${total}`}>
        <span
          className={`progress-eyes ${percent >= 100 ? "is-done" : ""}`}
          aria-hidden="true"
        >
          <span className="eye" />
          <span className="eye" />
        </span>
        <div className="progress-track">
          <div
            className="progress-fill"
            style={{ width: `${percent}%` }}
            aria-hidden="true"
          />
        </div>
        <span className="progress-text">{percent}%</span>
      </div>
    );
  };

  const deleteSelectedTask = () => {
    if (!selectedTask) return;
    if (window.confirm("Delete this task?")) {
      deleteTask(selectedTask.id);
    }
  };

  const renderSelectedDeleteButton = (visibleTasks: Task[]) => {
    if (
      !selectedTask ||
      !visibleTasks.some((task) => task.id === selectedTask.id)
    ) {
      return null;
    }

    return (
      <button
        className="icon-btn danger"
        aria-label="Delete selected task"
        title="Delete selected task"
        onClick={(event) => {
          event.stopPropagation();
          deleteSelectedTask();
        }}
        data-keep-detail-open="true"
        type="button"
      >
        <TrashIcon />
      </button>
    );
  };

  if (view.mode === "wish") {
    const list = applyViewPrefs(importantTasks, prefs);
    const badgeCounts = countUrgentImportant(list);
    const doneCount = list.filter((t) => t.done).length;
    return (
      <SectionShell
        title={titleNode}
        barClass={barClass}
        className={sectionClassName}
      >
        <div className="toolbar">
          <span className="dot purple" />
          <span className="pill pill-ban">No procrastination</span>
          {renderProgress(list.length, doneCount)}
          <span className="pill pill-urgent">{`Urgent ${badgeCounts.urgent}`}</span>
          <span className="pill pill-important">{`Important ${badgeCounts.important}`}</span>
          <div className="toolbar-right">
            <button
              className={`icon-btn ${prefs.hideDone ? "active" : ""}`}
              aria-label={prefs.hideDone ? "Show completed" : "Hide completed"}
              title={prefs.hideDone ? "Show completed" : "Hide completed"}
              onClick={toggleHideDone}
              type="button"
            >
              <FilterIcon />
            </button>
            <button
              className="icon-btn"
              aria-label="Change sort"
              title={`Sort: ${sortLabel[prefs.sort]}`}
              onClick={cycleSort}
              type="button"
            >
              <SortIcon />
            </button>
            <button
              className={`icon-btn ${searchVisible ? "active" : ""}`}
              aria-label={searchVisible ? "Close search" : "Search"}
              title={searchVisible ? "Close search" : "Search"}
              onClick={toggleSearch}
              type="button"
            >
              <SearchIcon />
            </button>
            {renderSelectedDeleteButton(list)}
          </div>
        </div>

        {searchVisible && (
          <div className="toolbar-search">
            <input
              ref={searchRef}
              className="field search"
              placeholder="Search reminders..."
              value={prefs.query}
              onChange={(e) =>
                setPrefs((prev) => ({ ...prev, query: e.target.value }))
              }
            />
            <button
              className="icon-btn"
              aria-label="Clear search"
              onClick={clearSearch}
              type="button"
            >
              <ClearIcon />
            </button>
          </div>
        )}

        {list.length === 0 ? null : (
          <Reorder.Group
            as="ol"
            className="wish-list"
            axis="y"
            values={list.map((t) => t.id)}
            onReorder={(ids) => {
              setPrefs((prev) => ({
                ...prev,
                sort: "manual",
                manualOrder: ids,
              }));
              setViewOrder(view.id, { manualOrder: ids });
            }}
          >
            {list.map((item, idx) => (
              <WishRowItem
                key={item.id}
                task={item}
                index={idx}
                openDetail={openDetail}
                toggleDone={toggleDone}
                incrementOpenEndedCount={incrementOpenEndedCount}
                decrementOpenEndedCount={decrementOpenEndedCount}
              />
            ))}
          </Reorder.Group>
        )}
      </SectionShell>
    );
  }

  if (view.mode === "board") {
    const createNew = () => {
      const nextPriority =
        activePriority === "all" ? "none" : (activePriority as Priority);
      const id = createFromView("board", "New task", {
        priority: nextPriority,
      });
      if (id) openDetail(id);
    };

    const doneCount = boardTasks.filter((t) => t.done).length;
    const openEndedSplitIndex = getOpenEndedDividerIndex(boardTasks);
    const openEndedToneSplitIndex = getOpenEndedToneDividerIndex(boardTasks);
    return (
      <SectionShell
        title={titleNode}
        barClass={barClass}
        className={sectionClassName}
      >
        <div className="toolbar">
          <span className="dot purple" />
          <span className="pill pill-ban">No procrastination</span>
          {renderProgress(boardTasks.length, doneCount)}
          <span className="pill pill-urgent">{`Urgent ${boardBadgeCounts.urgent}`}</span>
          <span className="pill pill-important">{`Important ${boardBadgeCounts.important}`}</span>
          <div className="toolbar-right">
            <button
              className={`icon-btn ${prefs.hideDone ? "active" : ""}`}
              aria-label={prefs.hideDone ? "Show completed" : "Hide completed"}
              title={prefs.hideDone ? "Show completed" : "Hide completed"}
              onClick={toggleHideDone}
              type="button"
            >
              <FilterIcon />
            </button>
            <button
              className="icon-btn"
              aria-label="Change sort"
              title={`Sort: ${sortLabel[prefs.sort]}`}
              onClick={cycleSort}
              type="button"
            >
              <SortIcon />
            </button>
            <button
              className={`icon-btn ${searchVisible ? "active" : ""}`}
              aria-label={searchVisible ? "Close search" : "Search"}
              title={searchVisible ? "Close search" : "Search"}
              onClick={toggleSearch}
              type="button"
            >
              <SearchIcon />
            </button>
            <button
              className="icon-btn"
              aria-label="Add task"
              onClick={createNew}
              type="button"
            >
              <AddIcon />
            </button>
            {renderSelectedDeleteButton(boardTasks)}
          </div>
        </div>

        {searchVisible && (
          <div className="toolbar-search">
            <input
              ref={searchRef}
              className="field search"
              placeholder="Search execution tasks..."
              value={prefs.query}
              onChange={(e) =>
                setPrefs((prev) => ({ ...prev, query: e.target.value }))
              }
            />
            <button
              className="icon-btn"
              aria-label="Clear search"
              onClick={clearSearch}
              type="button"
            >
              <ClearIcon />
            </button>
          </div>
        )}

        <div className="board-stage">
          <div className="status-row">
            {boardCounts.map((st) => (
              <button
                key={st.id}
                className={`status-chip ${activePriority === st.id ? "active" : ""}`}
                onClick={() => setActivePriority(st.id)}
                style={
                  {
                    "--tone": st.tone,
                    "--tone-soft": hexToRgba(st.tone, 0.2),
                  } as CSSProperties
                }
                type="button"
              >
                <span>{st.title}</span>
                <span className="status-num">{st.count}</span>
              </button>
            ))}
          </div>

          {boardTasks.length > 0 && (
            <Reorder.Group
              as="ol"
              className="wish-list board-list"
              axis="y"
              values={boardTasks.map((t) => t.id)}
              onReorder={(ids) => {
                setPrefs((prev) =>
                  activePriority === "all"
                    ? {
                        ...prev,
                        sort: "manual",
                        manualOrder: ids,
                      }
                    : {
                        ...prev,
                        sort: "manual",
                        manualOrderByPriority: {
                          ...(prev.manualOrderByPriority || {}),
                          [activePriority]: ids,
                        },
                      },
                );
                if (activePriority === "all") {
                  setViewOrder(view.id, { manualOrder: ids });
                } else {
                  setViewOrder(view.id, {
                    manualOrderByPriority: { [activePriority]: ids },
                  });
                }
              }}
            >
              {(() => {
                let openEndedIndex = 0;
                let fixedIndex = 0;
                const splitIndices = [
                  openEndedSplitIndex,
                  openEndedToneSplitIndex,
                ]
                  .filter((value): value is number => typeof value === "number")
                  .sort((a, b) => a - b);
                const isGroupStart = (idx: number) =>
                  idx === 0 || splitIndices.includes(idx);
                const isGroupEnd = (idx: number) =>
                  idx === boardTasks.length - 1 ||
                  splitIndices.includes(idx + 1);
                return boardTasks.map((task, index) => {
                  const isOpenEnded = isTaskOpenEnded(task);
                  if (openEndedToneSplitIndex === index) {
                    openEndedIndex = 0;
                  }
                  const displayIndex = isOpenEnded
                    ? openEndedIndex++
                    : fixedIndex++;
                  const indexTone = isOpenEnded
                    ? undefined
                    : getIndexToneById(task.id);
                  return (
                    <React.Fragment key={task.id}>
                      {openEndedSplitIndex === index ? (
                        <li className="todo-divider" aria-hidden="true" />
                      ) : null}
                      {openEndedToneSplitIndex === index ? (
                        <li className="todo-divider" aria-hidden="true" />
                      ) : null}
                      <BoardRowItem
                        task={task}
                        index={displayIndex}
                        indexTone={indexTone}
                        groupStart={isGroupStart(index)}
                        groupEnd={isGroupEnd(index)}
                        openDetail={openDetail}
                        toggleDone={toggleDone}
                        incrementOpenEndedCount={incrementOpenEndedCount}
                        decrementOpenEndedCount={decrementOpenEndedCount}
                      />
                    </React.Fragment>
                  );
                });
              })()}
            </Reorder.Group>
          )}
        </div>
      </SectionShell>
    );
  }

  if (view.mode === "week" || view.mode === "month") {
    const list = applyViewPrefs(
      view.mode === "week" ? weekTasks : monthTasks,
      prefs,
    );
    const badgeCounts = countUrgentImportant(list);
    const doneCount = list.filter((t) => t.done).length;
    const previewLimit = 3;
    const visible = expanded ? list : list.slice(0, previewLimit);
    const hiddenCount = Math.max(0, list.length - visible.length);

    return (
      <SectionShell
        title={titleNode}
        barClass={barClass}
        className={sectionClassName}
      >
        <div className="toolbar">
          <span className="dot purple" />
          <span className="pill pill-ban">No procrastination</span>
          {renderProgress(list.length, doneCount)}
          <span className="pill pill-urgent">{`Urgent ${badgeCounts.urgent}`}</span>
          <span className="pill pill-important">{`Important ${badgeCounts.important}`}</span>
          <div className="toolbar-right">
            <button
              className={`icon-btn ${prefs.hideDone ? "active" : ""}`}
              aria-label={prefs.hideDone ? "Show completed" : "Hide completed"}
              title={prefs.hideDone ? "Show completed" : "Hide completed"}
              onClick={toggleHideDone}
              type="button"
            >
              <FilterIcon />
            </button>
            <button
              className="icon-btn"
              aria-label="Change sort"
              title={`Sort: ${sortLabel[prefs.sort]}`}
              onClick={cycleSort}
              type="button"
            >
              <SortIcon />
            </button>
            <button
              className={`icon-btn ${searchVisible ? "active" : ""}`}
              aria-label={searchVisible ? "Close search" : "Search"}
              title={searchVisible ? "Close search" : "Search"}
              onClick={toggleSearch}
              type="button"
            >
              <SearchIcon />
            </button>
            {renderSelectedDeleteButton(list)}
          </div>
        </div>

        {searchVisible && (
          <div className="toolbar-search">
            <input
              ref={searchRef}
              className="field search"
              placeholder={`Search ${view.mode === "week" ? "weekly" : "monthly"} tasks...`}
              value={prefs.query}
              onChange={(e) =>
                setPrefs((prev) => ({ ...prev, query: e.target.value }))
              }
            />
            <button
              className="icon-btn"
              aria-label="Clear search"
              onClick={clearSearch}
              type="button"
            >
              <ClearIcon />
            </button>
          </div>
        )}

        {list.length === 0 ? null : (
          <>
            <div className="sub-toolbar">
              {list.length > previewLimit && (
                <button
                  className="link-btn"
                  onClick={() => setExpanded((v) => !v)}
                  type="button"
                >
                  {expanded ? "Collapse" : "Expand"}
                </button>
              )}
            </div>
            <Reorder.Group
              as="ul"
              className="plain-list"
              axis="y"
              values={visible.map((t) => t.id)}
              onReorder={(ids) => {
                const visibleIds = new Set(visible.map((t) => t.id));
                const rest = list
                  .map((t) => t.id)
                  .filter((id) => !visibleIds.has(id));
                const nextOrder = expanded ? ids : [...ids, ...rest];
                setPrefs((prev) => ({
                  ...prev,
                  sort: "manual",
                  manualOrder: nextOrder,
                }));
                setViewOrder(view.id, { manualOrder: nextOrder });
              }}
            >
              {visible.map((task) => (
                <ListRowItem
                  key={task.id}
                  task={task}
                  openDetail={openDetail}
                  toggleDone={toggleDone}
                  incrementOpenEndedCount={incrementOpenEndedCount}
                  decrementOpenEndedCount={decrementOpenEndedCount}
                />
              ))}
              {!expanded && hiddenCount > 0 && (
                <li className="muted">{hiddenCount} more items...</li>
              )}
            </Reorder.Group>
          </>
        )}
      </SectionShell>
    );
  }

  if (view.mode === "year") {
    const list = applyViewPrefs(annualTasks, prefs);
    const badgeCounts = countUrgentImportant(list);
    const doneCount = list.filter((t) => t.done).length;
    return (
      <SectionShell
        title={titleNode}
        barClass={barClass}
        className={sectionClassName}
      >
        <div className="toolbar">
          <span className="dot purple" />
          <span className="pill pill-ban">No procrastination</span>
          {renderProgress(list.length, doneCount)}
          <span className="pill pill-urgent">{`Urgent ${badgeCounts.urgent}`}</span>
          <span className="pill pill-important">{`Important ${badgeCounts.important}`}</span>
          <div className="toolbar-right">
            <button
              className={`icon-btn ${prefs.hideDone ? "active" : ""}`}
              aria-label={prefs.hideDone ? "Show completed" : "Hide completed"}
              title={prefs.hideDone ? "Show completed" : "Hide completed"}
              onClick={toggleHideDone}
              type="button"
            >
              <FilterIcon />
            </button>
            <button
              className="icon-btn"
              aria-label="Change sort"
              title={`Sort: ${sortLabel[prefs.sort]}`}
              onClick={cycleSort}
              type="button"
            >
              <SortIcon />
            </button>
            <button
              className={`icon-btn ${searchVisible ? "active" : ""}`}
              aria-label={searchVisible ? "Close search" : "Search"}
              title={searchVisible ? "Close search" : "Search"}
              onClick={toggleSearch}
              type="button"
            >
              <SearchIcon />
            </button>
            {renderSelectedDeleteButton(list)}
          </div>
        </div>

        {searchVisible && (
          <div className="toolbar-search">
            <input
              ref={searchRef}
              className="field search"
              placeholder="Search yearly goals..."
              value={prefs.query}
              onChange={(e) =>
                setPrefs((prev) => ({ ...prev, query: e.target.value }))
              }
            />
            <button
              className="icon-btn"
              aria-label="Clear search"
              onClick={clearSearch}
              type="button"
            >
              <ClearIcon />
            </button>
          </div>
        )}

        <div className="sub-toolbar" />

        {list.length === 0 ? null : (
          <Reorder.Group
            as="ol"
            className="year-list"
            axis="y"
            values={list.map((t) => t.id)}
            onReorder={(ids) => {
              setPrefs((prev) => ({
                ...prev,
                sort: "manual",
                manualOrder: ids,
              }));
              setViewOrder(view.id, { manualOrder: ids });
            }}
          >
            {list.map((t, idx) => (
              <YearRowItem
                key={t.id}
                task={t}
                index={idx}
                openDetail={openDetail}
                toggleDone={toggleDone}
                incrementOpenEndedCount={incrementOpenEndedCount}
                decrementOpenEndedCount={decrementOpenEndedCount}
              />
            ))}
          </Reorder.Group>
        )}
      </SectionShell>
    );
  }

  // delay (view-only)
  const delayList = sortByMode(
    delayTasks.filter(
      (t) =>
        matchTaskQuery(t, prefs.query) && (!prefs.hideDone || !!t.note?.trim()),
    ),
    prefs.sort,
    prefs.manualOrder,
  );

  const delayTagCounts = (() => {
    const urgentLabel = "Urgent";
    const importantLabel = "Important";
    let urgent = 0;
    let important = 0;
    delayList.forEach((task) => {
      const labels = (task.badges || []).map((badge) => badge.label);
      if (labels.includes(urgentLabel)) urgent += 1;
      if (labels.includes(importantLabel)) important += 1;
    });
    return { urgent, important };
  })();
  const delayDoneCount = delayList.filter((t) => t.done).length;
  const delaySectionClassName =
    [
      sectionClassName,
      delayList.length > 0 ? "section--dim-hover-active" : null,
    ]
      .filter(Boolean)
      .join(" ") || undefined;

  return (
    <SectionShell
      title={titleNode}
      barClass={barClass}
      className={delaySectionClassName}
    >
      <div className="toolbar">
        <span className="dot purple" />
        <span className="pill pill-ban">No procrastination</span>
        {renderProgress(delayList.length, delayDoneCount)}
        <span className="pill pill-urgent">{`Urgent ${delayTagCounts.urgent}`}</span>
        <span className="pill pill-important">{`Important ${delayTagCounts.important}`}</span>
        <div className="toolbar-right">
          <button
            className={`icon-btn ${prefs.hideDone ? "active" : ""}`}
            aria-label={prefs.hideDone ? "Show all" : "Only with notes"}
            title={prefs.hideDone ? "Show all" : "Only with notes"}
            onClick={toggleHideDone}
            type="button"
          >
            <FilterIcon />
          </button>
          <button
            className="icon-btn"
            aria-label="Change sort"
            title={`Sort: ${sortLabel[prefs.sort]}`}
            onClick={cycleSort}
            type="button"
          >
            <SortIcon />
          </button>
          <button
            className={`icon-btn ${searchVisible ? "active" : ""}`}
            aria-label={searchVisible ? "Close search" : "Search"}
            title={searchVisible ? "Close search" : "Search"}
            onClick={toggleSearch}
            type="button"
          >
            <SearchIcon />
          </button>
          {renderSelectedDeleteButton(delayList)}
        </div>
      </div>

      {searchVisible && (
        <div className="toolbar-search">
          <input
            ref={searchRef}
            className="field search"
            placeholder="Search overdue tasks..."
            value={prefs.query}
            onChange={(e) =>
              setPrefs((prev) => ({ ...prev, query: e.target.value }))
            }
          />
          <button
            className="icon-btn"
            aria-label="Clear search"
            onClick={clearSearch}
            type="button"
          >
            <ClearIcon />
          </button>
        </div>
      )}

      <div className="sub-toolbar delay-sub" />

      {delayList.length === 0 ? null : (
        <Reorder.Group
          as="div"
          className="delay-grid"
          axis="y"
          values={delayList.map((t) => t.id)}
          onReorder={(ids) => {
            setPrefs((prev) => ({
              ...prev,
              sort: "manual",
              manualOrder: ids,
            }));
            setViewOrder(view.id, { manualOrder: ids });
          }}
        >
          {delayList.map((task) => (
            <DelayCardItem
              key={task.id}
              task={task}
              openDetail={openDetail}
              toggleDone={toggleDone}
              incrementOpenEndedCount={incrementOpenEndedCount}
              decrementOpenEndedCount={decrementOpenEndedCount}
            />
          ))}
        </Reorder.Group>
      )}
    </SectionShell>
  );
};

const FlagToggle: React.FC<{
  label: string;
  active: boolean;
  onClick: () => void;
}> = ({ label, active, onClick }) => (
  <button
    type="button"
    className={`toggle-pill ${active ? "active" : ""}`}
    onClick={onClick}
  >
    {label}
  </button>
);
const AddIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M12 5v14M5 12h14"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    />
  </svg>
);

const SearchIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <circle cx="11" cy="11" r="6" stroke="currentColor" strokeWidth="1.7" />
    <path
      d="M16.5 16.5L20 20"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
    />
  </svg>
);

const SortIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M8 6h8M8 12h6M8 18h4"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
    />
    <path
      d="M16 6l2-2 2 2M18 4v12"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const FilterIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M4 6h16l-6 7v5l-4-2v-3L4 6z"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinejoin="round"
      strokeLinecap="round"
    />
  </svg>
);

const ClearIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M8 8l8 8M16 8l-8 8"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
    />
  </svg>
);

const TrashIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <path
      d="M5 7h14M10 11v6M14 11v6M8 7l1-3h6l1 3M7 7l1 13h8l1-13"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const HeatmapIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <rect x="4" y="4" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="10" y="4" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="16" y="4" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="4" y="10" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="10" y="10" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="16" y="10" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="4" y="16" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="10" y="16" width="4" height="4" rx="1.2" fill="currentColor" />
    <rect x="16" y="16" width="4" height="4" rx="1.2" fill="currentColor" />
  </svg>
);

const DragIcon: React.FC = () => (
  <svg
    className="icon-svg"
    viewBox="0 0 24 24"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <circle cx="9" cy="7" r="1.2" fill="currentColor" opacity="0.95" />
    <circle cx="15" cy="7" r="1.2" fill="currentColor" opacity="0.95" />
    <circle cx="9" cy="12" r="1.2" fill="currentColor" opacity="0.95" />
    <circle cx="15" cy="12" r="1.2" fill="currentColor" opacity="0.95" />
    <circle cx="9" cy="17" r="1.2" fill="currentColor" opacity="0.95" />
    <circle cx="15" cy="17" r="1.2" fill="currentColor" opacity="0.95" />
  </svg>
);

const DragHandle: React.FC<{
  controls: ReturnType<typeof useDragControls>;
  label?: string;
}> = ({ controls, label = "Drag to sort" }) => (
  <button
    type="button"
    className="icon-btn subtle drag-handle"
    aria-label={label}
    title={label}
    onClick={(e) => e.stopPropagation()}
    onPointerDown={(e) => {
      e.stopPropagation();
      controls.start(e as unknown as PointerEvent);
    }}
  >
    <DragIcon />
  </button>
);

const getAllModalTags = (task: Task) => {
  const tags: CategoryKey[] = [];
  if (task.important) tags.push("reminder");
  if (task.execution) tags.push("execution");
  if (task.week) tags.push("week");
  if (task.month) tags.push("month");
  if (task.annual) tags.push("year");
  if (!task.done && isTaskOverdue(task)) tags.push("delay");
  if (tags.length === 0) tags.push("uncategorized");

  const seen = new Set<CategoryKey>();
  return tags.filter((tag) => {
    if (seen.has(tag)) return false;
    seen.add(tag);
    return true;
  });
};

const OpenEndedHeatmap: React.FC<{
  task: Task;
  onClose: () => void;
}> = ({ task, onClose }) => {
  const { toggleOpenEndedDay } = useTodoDatabase();
  const heatmapRef = useRef<HTMLDivElement>(null);
  const weekCount = 36;
  const history = useMemo(() => {
    const base = Array.isArray(task.openEndedHistory)
      ? task.openEndedHistory
      : [];
    if (task.openEndedLastDone && !base.includes(task.openEndedLastDone)) {
      return [...base, task.openEndedLastDone];
    }
    return base;
  }, [task.openEndedHistory, task.openEndedLastDone]);
  const { weeks, total: historyTotal } = useMemo(
    () => buildOpenEndedHeatmap(history, weekCount),
    [history, weekCount],
  );
  const total =
    typeof task.openEndedCount === "number"
      ? task.openEndedCount
      : historyTotal;
  const dayLabels = ["Mon", "", "Wed", "", "Fri", "", ""];
  const recordShortLabel = getOpenEndedRecordShortLabel(task);

  useEffect(() => {
    const onGlobalClick = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const target = event.target as Node | null;
      const panel = heatmapRef.current;
      if (!target || !panel) return;
      if (panel.contains(target)) return;
      onClose();
    };

    window.addEventListener("click", onGlobalClick, true);
    return () => window.removeEventListener("click", onGlobalClick, true);
  }, [onClose]);

  return (
    <div
      className="todo-heatmap"
      ref={heatmapRef}
      onClick={(e) => e.stopPropagation()}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="todo-heatmap__header">
        <div className="todo-heatmap__title">{`Total ${total} days - Last ${weekCount} weeks`}</div>
        <button
          type="button"
          className="icon-btn subtle"
          aria-label="Close heatmap"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
        >
          {"x"}
        </button>
      </div>
      <div
        className="todo-heatmap__months"
        style={{ "--heatmap-weeks": weeks.length } as CSSProperties}
      >
        {weeks.map((week, index) =>
          week.label ? (
            <span
              key={`${week.label}-${index}`}
              className="todo-heatmap__month"
              style={{ gridColumn: index + 1 }}
            >
              {week.label}
            </span>
          ) : null,
        )}
      </div>
      <div className="todo-heatmap__body">
        <div className="todo-heatmap__labels">
          {dayLabels.map((label, index) => (
            <span key={`${label}-${index}`} className="todo-heatmap__label">
              {label}
            </span>
          ))}
        </div>
        <div className="todo-heatmap__grid">
          {weeks.map((week, weekIndex) => (
            <div key={`week-${weekIndex}`} className="todo-heatmap__col">
              {week.days.map((day) => (
                <button
                  key={day.key}
                  type="button"
                  className={`todo-heatmap__cell level-${day.level}${
                    day.isFuture ? " future" : " clickable"
                  }${day.isToday ? " today" : ""}`}
                  title={`${day.key} ${day.level > 0 ? "recorded" : "not recorded"}`}
                  aria-label={`${day.key} ${day.level > 0 ? "recorded" : "not recorded"}${
                    day.isToday ? ", today" : ""
                  }`}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (day.isFuture) return;
                    toggleOpenEndedDay(task.id, day.key);
                  }}
                />
              ))}
            </div>
          ))}
        </div>
      </div>
      <div className="todo-heatmap__footer">
        <span className="todo-heatmap__hint">
          Click squares to toggle records. Use the count button to record or undo {recordShortLabel}.
        </span>
      </div>
    </div>
  );
};

const AllModalRowItem: React.FC<{
  task: Task;
  index: number;
  openDetail: OpenDetailFn;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
}> = ({
  task,
  index,
  openDetail,
  toggleDone,
  incrementOpenEndedCount,
  decrementOpenEndedCount,
}) => {
  const controls = useDragControls();
  const dragLabel = "Drag to sort";
  const tags = getAllModalTags(task);
  const openEnded = isTaskOpenEnded(task);
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const showHeatmap = openEnded && heatmapOpen;
  const dueLabel = openEnded ? "Ongoing" : task.end ? `Due ${task.end}` : "";
  const startLabel = task.start ? `Start ${task.start}` : "";
  const dateLabel = [startLabel, dueLabel].filter(Boolean).join(" - ");
  return (
    <Reorder.Item
      as="li"
      value={task.id}
      className={`year-row todo-all-row ${task.accent ? "accent" : ""} ${openEnded ? "open-ended" : ""} ${showHeatmap ? "heatmap-open" : ""}`}
      dragListener={false}
      dragControls={controls}
      role="button"
      tabIndex={0}
      onClick={(e) =>
        openDetail(
          task.id,
          rectToAnchor(
            (e.currentTarget as HTMLElement).getBoundingClientRect(),
          ),
        )
      }
      onKeyDown={(e) => {
        const target = e.target as HTMLElement | null;
        if (target?.closest?.("input,button")) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openDetail(
            task.id,
            rectToAnchor(
              (e.currentTarget as HTMLElement).getBoundingClientRect(),
            ),
          );
        }
      }}
    >
      <DragHandle controls={controls} label={dragLabel} />
      <span className="year-index">{index}</span>
      <span className={`year-text ${task.done ? "done" : ""}`}>
        {task.title || "Untitled task"}
      </span>
      {renderTaskBadges(task)}
      {dateLabel ? (
        <button
          type="button"
          className="todo-all-date todo-date-btn"
          onClick={(e) => openDetailFromTarget(e, task.id, openDetail)}
        >
          {dateLabel}
        </button>
      ) : null}
      {task.tag && <span className="mini-tag ghost">{task.tag}</span>}
      <div className="todo-all-tags">
        {tags.map((tag) => (
          <span key={tag} className={`todo-all-category ${tag}`}>
            {categoryLabels[tag]}
          </span>
        ))}
      </div>
      <div className="row-actions">
        {renderCompletionControl(
          task,
          toggleDone,
          incrementOpenEndedCount,
          "wish-checkbox",
          "Mark as completed",
          {
            onOpenHeatmap: () => setHeatmapOpen(true),
            onDecrement: () => decrementOpenEndedCount(task.id),
          },
        )}
      </div>
      {showHeatmap ? (
        <OpenEndedHeatmap task={task} onClose={() => setHeatmapOpen(false)} />
      ) : null}
    </Reorder.Item>
  );
};

const BoardRowItem: React.FC<{
  task: Task;
  index: number;
  indexTone?: string;
  groupStart?: boolean;
  groupEnd?: boolean;
  openDetail: OpenDetailFn;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
}> = ({
  task,
  index,
  indexTone,
  groupStart,
  groupEnd,
  openDetail,
  toggleDone,
  incrementOpenEndedCount,
  decrementOpenEndedCount,
}) => {
  const controls = useDragControls();
  const openEnded = isTaskOpenEnded(task);
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const showHeatmap = openEnded && heatmapOpen;

  return (
    <Reorder.Item
      as="li"
      value={task.id}
      className={`wish-row ${openEnded ? "open-ended" : ""} ${showHeatmap ? "heatmap-open" : ""} ${groupStart ? "group-start" : ""} ${groupEnd ? "group-end" : ""} ${groupStart || groupEnd || openEnded ? "group-frame" : ""}`}
      style={
        indexTone ? ({ "--index-tone": indexTone } as CSSProperties) : undefined
      }
      dragListener={false}
      dragControls={controls}
    >
      <DragHandle controls={controls} />
      <button
        type="button"
        className="wish-left wish-open"
        onClick={(e) =>
          openDetail(
            task.id,
            rectToAnchor(e.currentTarget.getBoundingClientRect()),
          )
        }
      >
        <span className="wish-index">{index + 1}.</span>
        <span className={`wish-text ${task.done ? "done" : ""}`}>
          {task.title}
          {task.tag && <span className="mini-tag">{task.tag}</span>}
        </span>
      </button>
      <div className="row-meta">
        {renderTaskBadges(task)}
        {renderDueTag(task, openDetail)}
        <div className="row-actions">
          {renderCompletionControl(
            task,
            toggleDone,
            incrementOpenEndedCount,
            "wish-checkbox",
            undefined,
            {
              onOpenHeatmap: () => setHeatmapOpen(true),
              onDecrement: () => decrementOpenEndedCount(task.id),
            },
          )}
        </div>
      </div>
      {showHeatmap ? (
        <OpenEndedHeatmap task={task} onClose={() => setHeatmapOpen(false)} />
      ) : null}
    </Reorder.Item>
  );
};

function openDetailFromTarget(
  e: React.MouseEvent<HTMLElement>,
  taskId: string,
  openDetail: OpenDetailFn,
) {
  e.stopPropagation();
  openDetail(
    taskId,
    rectToAnchor((e.currentTarget as HTMLElement).getBoundingClientRect()),
  );
}

const renderTaskBadges = (task: Task) => {
  const badges = (task.badges || []).filter((badge) =>
    delayBadgeLabels.has(badge.label),
  );
  if (!badges.length) return null;
  return (
    <div className="row-badges">
      {badges.map((badge) => (
        <span key={badge.label} className={`badge badge-${badge.tone}`}>
          {badge.label}
        </span>
      ))}
    </div>
  );
};

const renderDueTag = (task: Task, openDetail?: OpenDetailFn) => {
  if (isTaskOpenEnded(task)) {
    if (!openDetail) {
      return <span className="mini-tag ghost open-ended">Ongoing</span>;
    }
    return (
      <button
        type="button"
        className="mini-tag ghost open-ended mini-tag-btn"
        onClick={(e) => openDetailFromTarget(e, task.id, openDetail)}
      >
        Ongoing
      </button>
    );
  }
  if (!task.end) return null;
  const overdue = !task.done && isTaskOverdue(task);
  if (!openDetail) {
    return (
      <span className={`mini-tag ghost ${overdue ? "due-overdue" : ""}`}>
        Due {task.end}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={`mini-tag ghost mini-tag-btn ${overdue ? "due-overdue" : ""}`}
      onClick={(e) => openDetailFromTarget(e, task.id, openDetail)}
    >
      Due {task.end}
    </button>
  );
};

const renderCompletionControl = (
  task: Task,
  toggleDone: (id: string) => void,
  incrementOpenEndedCount: (id: string) => void,
  checkboxClass: string,
  ariaLabel = "Mark as completed",
  options?: { onOpenHeatmap?: () => void; onDecrement?: () => void },
) => {
  if (isTaskOpenEnded(task)) {
    const baseDate = new Date();
    const recordKey = getOpenEndedRecordKey(task, baseDate);
    const recordLabel = getOpenEndedRecordLabel(task);
    const recordLabelShort = getOpenEndedRecordShortLabel(task);
    const countedRecordDay = hasOpenEndedDay(task, recordKey);
    const count = task.openEndedCount ?? 0;
    const isNegative = task.openEndedTone === "negative";
    const countLabel = `Total ${count} days`;
    const dayLabel = isNegative
      ? countedRecordDay
        ? `${recordLabel}: missed`
        : `${recordLabel}: done`
      : countedRecordDay
        ? `${recordLabelShort} recorded`
        : `${recordLabelShort} not recorded`;
    const dayChipLabel = isNegative
      ? countedRecordDay
        ? `${recordLabel}: missed`
        : `${recordLabel}: done`
      : countedRecordDay
        ? `${recordLabelShort} recorded`
        : `${recordLabelShort} not recorded`;
    const canDecrement = typeof options?.onDecrement === "function";
    const canOpenHeatmap = typeof options?.onOpenHeatmap === "function";
    const handleDecrement = (event: React.MouseEvent<HTMLButtonElement>) => {
      event.preventDefault();
      event.stopPropagation();
      options?.onDecrement?.();
    };
    const handleIncrement = (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      incrementOpenEndedCount(task.id);
    };
    const handleOpenHeatmap = (event: React.MouseEvent<HTMLButtonElement>) => {
      event.stopPropagation();
      options?.onOpenHeatmap?.();
    };
    return (
      <div className="todo-count-group">
        <button
          type="button"
          className={`todo-count ${countedRecordDay ? "counted" : ""}`}
          aria-label={`${countLabel}, ${dayLabel}${canDecrement ? ", right-click to undo one day" : ""}`}
          title={
            countedRecordDay
              ? `${countLabel} - click to undo ${recordLabelShort} / right-click to undo one day`
              : `${countLabel} - click to record ${recordLabelShort} / right-click to undo one day`
          }
          onClickCapture={(e) => {
            if (countedRecordDay && canDecrement) {
              handleDecrement(e);
              return;
            }
            handleIncrement(e);
          }}
          onContextMenu={(e) => {
            if (!canDecrement) return;
            handleDecrement(e);
          }}
        >
          <span className="todo-count__num">{count}</span>
          <span className="todo-count__unit">days</span>
        </button>
        <span
          className={`todo-count-today ${countedRecordDay ? "counted" : "missed"} ${isNegative ? "negative" : ""}`}
        >
          {dayChipLabel}
        </span>
        {canOpenHeatmap ? (
          <button
            type="button"
            className="icon-btn subtle todo-heatmap-btn"
            aria-label="Open heatmap"
            title="Open heatmap"
            onClick={handleOpenHeatmap}
          >
            <HeatmapIcon />
          </button>
        ) : null}
      </div>
    );
  }

  return (
    <input
      type="checkbox"
      className={checkboxClass}
      checked={!!task.done}
      readOnly
      aria-label={ariaLabel}
      onClickCapture={(e) => {
        e.stopPropagation();
        toggleDone(task.id);
      }}
    />
  );
};

const WishRowItem: React.FC<{
  task: Task;
  index: number;
  openDetail: OpenDetailFn;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
}> = ({
  task,
  index,
  openDetail,
  toggleDone,
  incrementOpenEndedCount,
  decrementOpenEndedCount,
}) => {
  const controls = useDragControls();
  const openEnded = isTaskOpenEnded(task);
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const showHeatmap = openEnded && heatmapOpen;

  return (
    <Reorder.Item
      as="li"
      value={task.id}
      className={`wish-row ${openEnded ? "open-ended" : ""} ${showHeatmap ? "heatmap-open" : ""}`}
      dragListener={false}
      dragControls={controls}
    >
      <DragHandle controls={controls} />
      <button
        type="button"
        className="wish-left wish-open"
        onClick={(e) =>
          openDetail(
            task.id,
            rectToAnchor(e.currentTarget.getBoundingClientRect()),
          )
        }
      >
        <span className="wish-index">{index + 1}.</span>
        <span className={`wish-text ${task.done ? "done" : ""}`}>
          {task.title}
          {task.tag && <span className="mini-tag">{task.tag}</span>}
        </span>
      </button>
      <div className="row-meta">
        {renderTaskBadges(task)}
        {renderDueTag(task, openDetail)}
        <div className="row-actions">
          {renderCompletionControl(
            task,
            toggleDone,
            incrementOpenEndedCount,
            "wish-checkbox",
            undefined,
            {
              onOpenHeatmap: () => setHeatmapOpen(true),
              onDecrement: () => decrementOpenEndedCount(task.id),
            },
          )}
        </div>
      </div>
      {showHeatmap ? (
        <OpenEndedHeatmap task={task} onClose={() => setHeatmapOpen(false)} />
      ) : null}
    </Reorder.Item>
  );
};

const ListRowItem: React.FC<{
  task: Task;
  openDetail: OpenDetailFn;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
}> = ({
  task,
  openDetail,
  toggleDone,
  incrementOpenEndedCount,
  decrementOpenEndedCount,
}) => {
  const controls = useDragControls();
  const openEnded = isTaskOpenEnded(task);
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const showHeatmap = openEnded && heatmapOpen;

  return (
    <Reorder.Item
      as="li"
      value={task.id}
      className={`list-row ${openEnded ? "open-ended" : ""} ${showHeatmap ? "heatmap-open" : ""}`}
      dragListener={false}
      dragControls={controls}
    >
      <DragHandle controls={controls} />
      <button
        type="button"
        className={`list-title-btn ${task.done ? "done" : ""}`}
        onClick={(e) =>
          openDetail(
            task.id,
            rectToAnchor(e.currentTarget.getBoundingClientRect()),
          )
        }
      >
        {task.title}
      </button>
      <div className="row-meta">
        {renderTaskBadges(task)}
        {renderDueTag(task, openDetail)}
        <div className="row-actions">
          {renderCompletionControl(
            task,
            toggleDone,
            incrementOpenEndedCount,
            "list-checkbox",
            undefined,
            {
              onOpenHeatmap: () => setHeatmapOpen(true),
              onDecrement: () => decrementOpenEndedCount(task.id),
            },
          )}
        </div>
      </div>
      {showHeatmap ? (
        <OpenEndedHeatmap task={task} onClose={() => setHeatmapOpen(false)} />
      ) : null}
    </Reorder.Item>
  );
};

const YearRowItem: React.FC<{
  task: Task;
  index: number;
  openDetail: OpenDetailFn;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
}> = ({
  task,
  index,
  openDetail,
  toggleDone,
  incrementOpenEndedCount,
  decrementOpenEndedCount,
}) => {
  const controls = useDragControls();
  const openEnded = isTaskOpenEnded(task);
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const showHeatmap = openEnded && heatmapOpen;

  return (
    <Reorder.Item
      as="li"
      value={task.id}
      className={`year-row ${task.accent ? "accent" : ""} ${openEnded ? "open-ended" : ""} ${showHeatmap ? "heatmap-open" : ""}`}
      dragListener={false}
      dragControls={controls}
      role="button"
      tabIndex={0}
      onClick={(e) =>
        openDetail(
          task.id,
          rectToAnchor(
            (e.currentTarget as HTMLElement).getBoundingClientRect(),
          ),
        )
      }
      onKeyDown={(e) => {
        const target = e.target as HTMLElement | null;
        if (target?.closest?.("input,button")) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openDetail(
            task.id,
            rectToAnchor(
              (e.currentTarget as HTMLElement).getBoundingClientRect(),
            ),
          );
        }
      }}
    >
      <DragHandle controls={controls} />
      <span className="year-index">{index + 1}</span>
      <span className={`year-text ${task.done ? "done" : ""}`}>
        {task.title}
      </span>
      {task.tag && <span className="mini-tag ghost">{task.tag}</span>}
      {renderTaskBadges(task)}
      {renderDueTag(task, openDetail)}
      <div className="row-actions">
        {renderCompletionControl(
          task,
          toggleDone,
          incrementOpenEndedCount,
          "wish-checkbox",
          "Mark as completed",
          {
            onOpenHeatmap: () => setHeatmapOpen(true),
            onDecrement: () => decrementOpenEndedCount(task.id),
          },
        )}
      </div>
      {showHeatmap ? (
        <OpenEndedHeatmap task={task} onClose={() => setHeatmapOpen(false)} />
      ) : null}
    </Reorder.Item>
  );
};

const DelayCardItem: React.FC<{
  task: Task;
  openDetail: OpenDetailFn;
  toggleDone: (id: string) => void;
  incrementOpenEndedCount: (id: string) => void;
  decrementOpenEndedCount: (id: string) => void;
}> = ({
  task,
  openDetail,
  toggleDone,
  incrementOpenEndedCount,
  decrementOpenEndedCount,
}) => {
  const controls = useDragControls();
  const openEnded = isTaskOpenEnded(task);
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const showHeatmap = openEnded && heatmapOpen;

  return (
    <Reorder.Item
      as="div"
      value={task.id}
      className={`delay-card ${openEnded ? "open-ended" : ""} ${showHeatmap ? "heatmap-open" : ""}`}
      dragListener={false}
      dragControls={controls}
      role="button"
      tabIndex={0}
      onClick={(e) =>
        openDetail(
          task.id,
          rectToAnchor(
            (e.currentTarget as HTMLElement).getBoundingClientRect(),
          ),
        )
      }
      onKeyDown={(e) => {
        const target = e.target as HTMLElement | null;
        if (target?.closest?.("input,button")) return;
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          openDetail(
            task.id,
            rectToAnchor(
              (e.currentTarget as HTMLElement).getBoundingClientRect(),
            ),
          );
        }
      }}
    >
      <div className="delay-head">
        <div className="delay-head-left">
          <DragHandle controls={controls} />
          <span className="mini-tag ghost">{task.category || "Uncategorized"}</span>
        </div>
        <div className="row-actions">
          {renderCompletionControl(
            task,
            toggleDone,
            incrementOpenEndedCount,
            "wish-checkbox",
            "Mark as completed",
            {
              onOpenHeatmap: () => setHeatmapOpen(true),
              onDecrement: () => decrementOpenEndedCount(task.id),
            },
          )}
        </div>
      </div>
      <div className="delay-title">{task.title}</div>
      {task.note && <div className="delay-note">{task.note}</div>}
      <div className="delay-dates">
        <button
          type="button"
          className="date-chip date-chip-btn"
          onClick={(e) => openDetailFromTarget(e, task.id, openDetail)}
        >
          {task.start || "--"}
        </button>
        <span className="arrow">-&gt;</span>
        <button
          type="button"
          className="date-chip date-chip-btn"
          onClick={(e) => openDetailFromTarget(e, task.id, openDetail)}
        >
          {task.end || "--"}
        </button>
      </div>
      <div className="delay-tags">
        {(task.badges || []).map((tg) => (
          <span key={tg.label} className={`badge badge-${tg.tone}`}>
            {tg.label}
          </span>
        ))}
      </div>
      <div className="delay-footer">
        <span className="badge badge-overdue">
          Overdue by {getTaskOverdueDays(task)} days
        </span>
      </div>
      {showHeatmap ? (
        <OpenEndedHeatmap task={task} onClose={() => setHeatmapOpen(false)} />
      ) : null}
    </Reorder.Item>
  );
};

const DatabaseDetailDrawer: React.FC = () => {
  const {
    tasks,
    detailId,
    detailAnchor,
    closeDetail,
    updateTask,
    deleteTask,
    toggleDone,
  } = useTodoDatabase();
  const titleRef = React.useRef<HTMLInputElement>(null);
  const noteRef = React.useRef<HTMLTextAreaElement>(null);
  const dragRef = React.useRef<HTMLDivElement>(null);
  const lastEndByIdRef = React.useRef<Map<string, string | undefined>>(
    new Map(),
  );
  const selectedTask = useMemo(
    () => tasks.find((t) => t.id === detailId) || null,
    [tasks, detailId],
  );
  const selectedId = selectedTask?.id ?? null;
  const [panelPos, setPanelPos] = useState<{
    top: number;
    left: number;
  } | null>(null);

  useLayoutEffect(() => {
    if (!selectedId) return;
    if (!detailAnchor) {
      setPanelPos(null);
      return;
    }

    const el = dragRef.current;
    if (!el) return;

    const margin = 12;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const panelRect = el.getBoundingClientRect();
    const panelW = panelRect.width || 360;
    const panelH = panelRect.height || 260;

    // Center vertically around the clicked item, then clamp to viewport.
    const anchorMidY = detailAnchor.top + detailAnchor.height / 2;
    let top = anchorMidY - panelH / 2;
    top = Math.max(margin, Math.min(vh - margin - panelH, top));

    // Prefer opening to the right of the clicked item; fallback to left; then clamp.
    const rightX = detailAnchor.right + margin;
    const leftX = detailAnchor.left - margin - panelW;
    let left: number;
    if (rightX + panelW <= vw - margin) left = rightX;
    else if (leftX >= margin) left = leftX;
    else
      left = Math.max(
        margin,
        Math.min(vw - margin - panelW, detailAnchor.left),
      );

    setPanelPos({ top, left });
  }, [selectedId, detailAnchor]);

  useLayoutEffect(() => {
    if (!selectedId) return;
    autoResizeTextarea(noteRef.current);
  }, [selectedId, selectedTask?.note]);

  useEffect(() => {
    if (!selectedTask) return;
    if (selectedTask.end) {
      lastEndByIdRef.current.set(selectedTask.id, selectedTask.end);
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") closeDetail();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedTask, closeDetail]);

  useEffect(() => {
    if (!selectedId) return;

    const onGlobalClick = (event: MouseEvent) => {
      if (event.button !== 0) return;
      const target = event.target as Node | null;
      const panel = dragRef.current;
      if (!target || !panel) return;
      if (panel.contains(target)) return;
      if (
        target instanceof Element &&
        target.closest("[data-keep-detail-open='true']")
      ) {
        return;
      }
      closeDetail();
    };

    window.addEventListener("click", onGlobalClick, true);
    return () => window.removeEventListener("click", onGlobalClick, true);
  }, [selectedId, closeDetail]);

  useEffect(() => {
    if (!selectedId) return;
    const t = window.setTimeout(() => {
      titleRef.current?.focus();
      titleRef.current?.select();
    }, 0);
    return () => window.clearTimeout(t);
  }, [selectedId]);

  if (!selectedTask) return null;

  // Overdue status is derived from the deadline and only meaningful for unfinished tasks.
  const overdueDays = selectedTask.done ? 0 : getTaskOverdueDays(selectedTask);
  const badgeLabels = new Set(
    (selectedTask.badges || []).map((badge) => badge.label),
  );
  const isOpenEnded = isTaskOpenEnded(selectedTask);
  const openEndedTone =
    selectedTask.openEndedTone === "negative" ? "negative" : "positive";
  const openEndedRecordDay =
    selectedTask.openEndedRecordDay === "yesterday" ? "yesterday" : "today";

  const toggleBadge = (badge: TaskBadge) => {
    const current = selectedTask.badges || [];
    const hasBadge = current.some((item) => item.label === badge.label);
    const next = hasBadge
      ? current.filter((item) => item.label !== badge.label)
      : [...current, badge];
    updateTask(selectedTask.id, { badges: next.length ? next : undefined });
  };

  const onDelete = () => {
    if (window.confirm("Delete this task?")) {
      deleteTask(selectedTask.id);
    }
  };

  const setOpenEnded = (next: boolean) => {
    if (next) {
      if (selectedTask.end) {
        lastEndByIdRef.current.set(selectedTask.id, selectedTask.end);
      }
      updateTask(selectedTask.id, { openEnded: true, end: undefined });
      return;
    }
    const fallback =
      lastEndByIdRef.current.get(selectedTask.id) ||
      selectedTask.end ||
      toYmd(new Date());
    updateTask(selectedTask.id, { openEnded: false, end: fallback });
  };

  const setDuePreset = (offsetDays: number) => {
    const d = new Date();
    d.setDate(d.getDate() + offsetDays);
    const end = toYmd(d);
    lastEndByIdRef.current.set(selectedTask.id, end);
    updateTask(selectedTask.id, { openEnded: false, end });
  };

  const todayStr = toYmd(new Date());
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const tomorrowStr = toYmd(tomorrow);
  const activeDuePreset = isOpenEnded
    ? "open"
    : selectedTask.end === todayStr
      ? "today"
      : selectedTask.end === tomorrowStr
        ? "tomorrow"
        : null;

  return (
    <div className="task-drawer">
      <Draggable
        handle=".task-drawer__header"
        cancel=".task-drawer__header button"
        bounds="parent"
        nodeRef={dragRef as React.RefObject<HTMLElement>}
      >
        <div
          className="task-drawer__panel"
          ref={dragRef}
          style={
            panelPos
              ? { top: panelPos.top, left: panelPos.left, right: "auto" }
              : undefined
          }
        >
          <div className="task-drawer__header">
            <div className="task-drawer__title">
              <div className="task-drawer__titleText">Task properties</div>
              <div className="task-drawer__subtitle" title={selectedTask.title}>
                {selectedTask.title || "Untitled task"}
              </div>
            </div>
            <button
              className="icon-btn"
              onClick={closeDetail}
              aria-label="Close"
              type="button"
            >
              x
            </button>
          </div>

          <div className="toggle-group">
            <FlagToggle
              label="Reminder"
              active={!!selectedTask.important}
              onClick={() =>
                updateTask(selectedTask.id, {
                  important: !selectedTask.important,
                })
              }
            />
            <FlagToggle
              label="Execution"
              active={!!selectedTask.execution}
              onClick={() =>
                updateTask(selectedTask.id, {
                  execution: !selectedTask.execution,
                })
              }
            />
            <FlagToggle
              label="This week"
              active={!!selectedTask.week}
              onClick={() => {
                const next = !selectedTask.week;
                updateTask(selectedTask.id, { week: next });
              }}
            />
            <FlagToggle
              label="This month"
              active={!!selectedTask.month}
              onClick={() => {
                const next = !selectedTask.month;
                updateTask(selectedTask.id, { month: next });
              }}
            />
            <FlagToggle
              label="This year"
              active={!!selectedTask.annual}
              onClick={() =>
                updateTask(selectedTask.id, { annual: !selectedTask.annual })
              }
            />
            <FlagToggle
              label={selectedTask.done ? "Completed" : "Incomplete"}
              active={!!selectedTask.done}
              onClick={() => toggleDone(selectedTask.id)}
            />
          </div>

          <div className="prop-list">
            <div className="prop-item">
              <div className="prop-key">Title</div>
              <div className="prop-control">
                <input
                  className="field"
                  ref={titleRef}
                  value={selectedTask.title}
                  placeholder="Enter a title..."
                  onChange={(e) =>
                    updateTask(selectedTask.id, { title: e.target.value })
                  }
                />
              </div>
            </div>

            <div className="prop-item">
              <div className="prop-key">Tag</div>
              <div className="prop-control">
                <input
                  className="field"
                  value={selectedTask.tag || ""}
                  placeholder="Optional"
                  onChange={(e) =>
                    updateTask(selectedTask.id, {
                      tag: e.target.value || undefined,
                    })
                  }
                />
              </div>
            </div>

            <div className="prop-grid2">
              <div className="prop-item">
                <div className="prop-key">Priority</div>
                <div className="prop-control">
                  <select
                    className="field select"
                    value={selectedTask.priority || "none"}
                    onChange={(e) =>
                      updateTask(selectedTask.id, {
                        priority: e.target.value as Priority,
                      })
                    }
                    disabled={!selectedTask.execution}
                  >
                    <option value="high">High</option>
                    <option value="mid">Medium</option>
                    <option value="low">Low</option>
                    <option value="none">None</option>
                  </select>
                </div>
              </div>
              <div className="prop-item">
                <div className="prop-key">Overdue</div>
                <div className="prop-control">
                  <div className="field readonly">{overdueDays} days</div>
                </div>
              </div>
            </div>

            <div className="prop-grid2 prop-grid2--dates">
              <div className="prop-item">
                <div className="prop-key">Start</div>
                <div className="prop-control">
                  <input
                    className="field"
                    type="date"
                    value={(selectedTask.start || "").replace(/\//g, "-")}
                    onChange={(e) =>
                      updateTask(selectedTask.id, {
                        start: e.target.value
                          ? e.target.value.replace(/-/g, "/")
                          : undefined,
                      })
                    }
                  />
                </div>
              </div>
              <div className="prop-item">
                <div className="prop-key">Due</div>
                <div className="prop-control">
                  <div className="field-row date-row">
                    {isOpenEnded ? (
                      <input
                        className="field readonly"
                        type="text"
                        value="Ongoing"
                        readOnly
                      />
                    ) : (
                      <input
                        className="field"
                        type="date"
                        value={(selectedTask.end || "").replace(/\//g, "-")}
                        onChange={(e) => {
                          const nextValue = e.target.value
                            ? e.target.value.replace(/-/g, "/")
                            : undefined;
                          if (nextValue) {
                            lastEndByIdRef.current.set(
                              selectedTask.id,
                              nextValue,
                            );
                          }
                          updateTask(selectedTask.id, {
                            end: nextValue,
                            openEnded: false,
                          });
                        }}
                      />
                    )}
                    <div className="date-quick">
                      <button
                        type="button"
                        className={`toggle-pill ${
                          activeDuePreset === "open" ? "active" : ""
                        }`}
                        onClick={() => setOpenEnded(!isOpenEnded)}
                      >
                        Ongoing
                      </button>
                      <button
                        type="button"
                        className={`toggle-pill ${
                          activeDuePreset === "today" ? "active" : ""
                        }`}
                        onClick={() => setDuePreset(0)}
                      >
                        Today
                      </button>
                      <button
                        type="button"
                        className={`toggle-pill ${
                          activeDuePreset === "tomorrow" ? "active" : ""
                        }`}
                        onClick={() => setDuePreset(1)}
                      >
                        Tomorrow
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div className="prop-item">
              <div className="prop-key">Category</div>
              <div className="prop-control">
                <input
                  className="field"
                  value={selectedTask.category || ""}
                  placeholder="Optional"
                  onChange={(e) =>
                    updateTask(selectedTask.id, {
                      category: e.target.value || undefined,
                    })
                  }
                />
              </div>
            </div>

            <div className="prop-item">
              <div className="prop-key">Link</div>
              <div className="prop-control">
                <input
                  className="field"
                  value={selectedTask.link || ""}
                  placeholder="Optional"
                  onChange={(e) =>
                    updateTask(selectedTask.id, {
                      link: e.target.value || undefined,
                    })
                  }
                />
              </div>
            </div>

            {isOpenEnded ? (
              <div className="prop-item">
                <div className="prop-key">Tone</div>
                <div className="prop-control">
                  <div className="prop-toggle-group">
                    <button
                      type="button"
                      className={`toggle-pill ${openEndedTone === "positive" ? "active" : ""}`}
                      onClick={() =>
                        updateTask(selectedTask.id, {
                          openEndedTone: "positive",
                        })
                      }
                    >
                      Positive
                    </button>
                    <button
                      type="button"
                      className={`toggle-pill ${openEndedTone === "negative" ? "active" : ""}`}
                      onClick={() =>
                        updateTask(selectedTask.id, {
                          openEndedTone: "negative",
                        })
                      }
                    >
                      Negative
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            {isOpenEnded ? (
              <div className="prop-item">
                <div className="prop-key">Record day</div>
                <div className="prop-control">
                  <div className="prop-toggle-group">
                    <button
                      type="button"
                      className={`toggle-pill ${
                        openEndedRecordDay === "today" ? "active" : ""
                      }`}
                      onClick={() =>
                        updateTask(selectedTask.id, {
                          openEndedRecordDay: "today",
                        })
                      }
                    >
                      Today
                    </button>
                    <button
                      type="button"
                      className={`toggle-pill ${
                        openEndedRecordDay === "yesterday" ? "active" : ""
                      }`}
                      onClick={() =>
                        updateTask(selectedTask.id, {
                          openEndedRecordDay: "yesterday",
                        })
                      }
                    >
                      Yesterday
                    </button>
                  </div>
                </div>
              </div>
            ) : null}

            <div className="prop-item">
              <div className="prop-key">{"Overdue tags"}</div>
              <div className="prop-control">
                <div className="badge-toggle-group">
                  {delayBadgePresets.map((badge) => {
                    const active = badgeLabels.has(badge.label);
                    return (
                      <button
                        key={badge.label}
                        type="button"
                        className={`badge badge-${badge.tone} badge-toggle ${
                          active ? "active" : "inactive"
                        }`}
                        onClick={() => toggleBadge(badge)}
                      >
                        {badge.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="prop-item prop-item--textarea">
              <div className="prop-key">Note</div>
              <div className="prop-control">
                <textarea
                  className="field textarea"
                  rows={3}
                  ref={noteRef}
                  value={selectedTask.note || ""}
                  placeholder="Optional"
                  onChange={(e) => {
                    autoResizeTextarea(e.currentTarget);
                    updateTask(selectedTask.id, {
                      note: e.target.value || undefined,
                    });
                  }}
                />
              </div>
            </div>
          </div>

          <div className="drawer-actions">
            <button className="danger-btn" onClick={onDelete} type="button">
              Delete task
            </button>
          </div>
        </div>
      </Draggable>
    </div>
  );
};
