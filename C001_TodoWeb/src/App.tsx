import { useCallback, useEffect, useRef, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import "./App.css";
import LockScreen from "./pages/LockScreen/LockScreen";
import Todo from "./pages/Todo";

const AUTO_LOCK_TIME = 5 * 60 * 60 * 1000;
const AUTO_LOCK_CHECK_INTERVAL = 60 * 1000;

const verifyLockSession = async () => {
  try {
    const response = await fetch("/api/lock/session", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
    });

    if (!response.ok) {
      return false;
    }

    const payload = (await response.json().catch(() => null)) as
      | { authenticated?: boolean }
      | null;

    return payload?.authenticated === true;
  } catch {
    return false;
  }
};

function App() {
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const lastActivityAtRef = useRef<number>(Date.now());

  const handleLock = useCallback(async () => {
    try {
      await fetch("/api/lock/session", {
        method: "DELETE",
        credentials: "include",
      });
    } catch {
      // Ignore network errors and still force local lock state.
    } finally {
      setAuthenticated(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;

    const run = async () => {
      const ok = await verifyLockSession();
      if (!cancelled) {
        setAuthenticated(ok);
      }
    };

    void run();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authenticated) return;

    lastActivityAtRef.current = Date.now();
    let locking = false;

    const markActive = () => {
      lastActivityAtRef.current = Date.now();
    };

    const events = [
      "mousedown",
      "mousemove",
      "keydown",
      "scroll",
      "touchstart",
      "pointerdown",
      "click",
    ] as const;

    events.forEach((eventName) => {
      window.addEventListener(eventName, markActive, { passive: true });
    });

    const timer = window.setInterval(() => {
      if (locking) return;
      const inactiveMs = Date.now() - lastActivityAtRef.current;
      if (inactiveMs < AUTO_LOCK_TIME) return;
      locking = true;
      void handleLock();
    }, AUTO_LOCK_CHECK_INTERVAL);

    return () => {
      window.clearInterval(timer);
      events.forEach((eventName) => {
        window.removeEventListener(eventName, markActive);
      });
    };
  }, [authenticated, handleLock]);

  if (authenticated === null) {
    return <div className="app-loading">Verifying access...</div>;
  }

  return (
    <Routes>
      <Route
        path="/"
        element={
          authenticated ? (
            <Navigate to="/todo" replace />
          ) : (
            <LockScreen redirectTarget="/todo" siteTitle="ToDo" />
          )
        }
      />
      <Route
        path="/todo"
        element={
          authenticated ? (
            <div className="app">
              <div className="container columns">
                <main className="main-left full-width">
                  <Todo onLock={handleLock} />
                </main>
              </div>
            </div>
          ) : (
            <Navigate to="/" replace />
          )
        }
      />
      <Route
        path="*"
        element={<Navigate to={authenticated ? "/todo" : "/"} replace />}
      />
    </Routes>
  );
}

export default App;
