import { useEffect } from "react";
import "./WenzhaiLockScreen.css";

declare global {
  interface Window {
    __todoLockInteractionLoaded?: boolean;
    __todoLockVisualLoaded?: boolean;
    __initTodoLockScreen?: () => void;
  }
}

type LockScreenProps = {
  redirectTarget?: string;
  siteTitle?: string;
};

const THREE_CDN =
  "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
const LOCK_INTERACTION_SCRIPT = "/scripts/lock-screen.js";
const LOCK_VISUAL_SCRIPT = "/scripts/lock-screen-visual.js";

const ensureScript = (id: string, src: string) =>
  new Promise<void>((resolve, reject) => {
    const existing = document.getElementById(id) as HTMLScriptElement | null;
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error(`Script load failed: ${src}`)),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.id = id;
    script.src = src;
    script.async = true;
    script.defer = true;

    script.addEventListener(
      "load",
      () => {
        script.dataset.loaded = "true";
        resolve();
      },
      { once: true },
    );

    script.addEventListener(
      "error",
      () => reject(new Error(`Script load failed: ${src}`)),
      { once: true },
    );

    document.body.appendChild(script);
  });

const LockScreen = ({
  redirectTarget = "/todo",
  siteTitle = "ToDo",
}: LockScreenProps) => {
  useEffect(() => {
    document.body.classList.add("lock-screen-page");

    const load = async () => {
      try {
        if (!window.__todoLockInteractionLoaded) {
          await ensureScript("todo-lock-interaction", LOCK_INTERACTION_SCRIPT);
          window.__todoLockInteractionLoaded = true;
        }
        window.__initTodoLockScreen?.();
      } catch (error) {
        console.error("Failed to load lock screen interaction:", error);
      }

      if (window.__todoLockVisualLoaded) {
        return;
      }

      try {
        void ensureScript("todo-lock-three", THREE_CDN)
          .then(() => ensureScript("todo-lock-visual", LOCK_VISUAL_SCRIPT))
          .then(() => {
            window.__todoLockVisualLoaded = true;
          })
          .catch((error) => {
            console.error("Failed to load lock screen visuals:", error);
          });
      } catch (error) {
        console.error("Failed to start lock screen visuals:", error);
      }
    };

    void load();

    return () => {
      document.body.classList.remove("lock-screen-page");
    };
  }, []);

  return (
    <div className="aegis-lockscreen">
      <div id="webgl-container" aria-hidden="true"></div>
      <div className="scanlines" aria-hidden="true"></div>

      <div className="hud">
        <div className="crosshair ch-tl"></div>
        <div className="crosshair ch-tr"></div>
        <div className="crosshair ch-bl"></div>
        <div className="crosshair ch-br"></div>

        <main className="center-cluster">
          <div
            className="clock-container"
            id="lock-screen-clock"
            data-revealed="true"
            aria-hidden="false"
          >
            <div className="time" id="clock-display">
              <span id="clock-hm">00:00</span>
              <span className="sec" id="clock-sec">
                00
              </span>
            </div>
            <div className="date-container">
              <span className="mono-label" id="date-display">
                0000-00-00 / System online
              </span>
            </div>
          </div>

          <form
            className="auth-panel"
            id="lock-screen-form"
            data-redirect={redirectTarget}
            data-revealed="true"
            aria-hidden="false"
            noValidate
          >
            <div
              className="unlock-wrapper"
              id="unlock-btn"
              role="button"
              tabIndex={0}
              aria-label={`Verify password and enter ${siteTitle}`}
            >
              <div className="unlock-ring-outer" aria-hidden="true"></div>
              <div className="unlock-core" aria-hidden="true"></div>

              <svg className="progress-svg" aria-hidden="true">
                <circle
                  className="progress-circle"
                  id="progress-circle"
                  cx="45"
                  cy="45"
                  r="43"
                ></circle>
              </svg>

              <div className="unlock-label mono-label blink-cursor" id="unlock-text">
                Click to verify
              </div>
            </div>

            <div className="auth-input-row">
              <label className="mono-label" htmlFor="lock-password">
                Access password
              </label>
              <input
                className="auth-input mono-value"
                id="lock-password"
                name="password"
                type="password"
                autoComplete="current-password"
                enterKeyHint="go"
                placeholder="Enter access password"
                required
              />
            </div>

            <p
              className="auth-status mono-label"
              id="lock-screen-status"
              role="status"
              aria-live="polite"
            >
              Enter the password, then press Enter or click verify.
            </p>

            <div className="auth-actions">
              <button
                className="auth-cancel mono-label"
                id="lock-screen-cancel"
                type="button"
              >
                Cancel
              </button>
            </div>

            <button
              className="sr-only"
              type="submit"
              aria-label={`Verify password and enter ${siteTitle}`}
            ></button>
          </form>
        </main>
      </div>
    </div>
  );
};

export default LockScreen;
