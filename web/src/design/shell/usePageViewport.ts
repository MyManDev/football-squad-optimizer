import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router";

/** Keep route changes, history restores and delayed anchor targets separate. */
export function usePageViewport(focusPage: () => void) {
  const location = useLocation();
  const navigation = useNavigationType();
  const current = useRef(location);
  const positions = useRef(new Map<string, number>());

  useEffect(() => {
    const previous = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    const remember = () => positions.current.set(current.current.key, window.scrollY);
    window.addEventListener("scroll", remember, { passive: true });
    return () => {
      window.removeEventListener("scroll", remember);
      window.history.scrollRestoration = previous;
    };
  }, []);

  useLayoutEffect(() => {
    const before = current.current;
    current.current = location;
    const saved = navigation === "POP" ? positions.current.get(location.key) : undefined;
    let id = "";
    try {
      id = decodeURIComponent(location.hash.slice(1));
    } catch {
      // A malformed anchor must not interrupt navigation.
    }
    const moved = before.pathname !== location.pathname;
    if (saved === undefined && !id) {
      if (moved) {
        window.scrollTo({ top: 0, behavior: "instant" });
        focusPage();
      }
      return;
    }

    let observer: MutationObserver | undefined;
    let resize: ResizeObserver | undefined;
    let timer = 0;
    const stop = () => {
      observer?.disconnect();
      resize?.disconnect();
      window.clearTimeout(timer);
      window.removeEventListener("wheel", stop);
      window.removeEventListener("touchstart", stop);
      window.removeEventListener("keydown", stop);
    };
    const reveal = () => {
      if (saved !== undefined) {
        window.scrollTo({ top: saved, behavior: "instant" });
        return Math.abs(window.scrollY - saved) < 2;
      }
      const target = document.getElementById(id);
      target?.scrollIntoView?.({ block: "start" });
      return target !== null;
    };
    if (reveal()) return;
    const retry = () => {
      if (reveal()) stop();
    };
    observer = new MutationObserver(retry);
    observer.observe(document.body, { childList: true, subtree: true });
    if (typeof ResizeObserver !== "undefined") {
      resize = new ResizeObserver(retry);
      resize.observe(document.body);
    }
    timer = window.setTimeout(stop, 5000);
    window.addEventListener("wheel", stop, { passive: true });
    window.addEventListener("touchstart", stop, { passive: true });
    window.addEventListener("keydown", stop);
    return stop;
  }, [location, navigation, focusPage]);
}
