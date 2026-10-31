import { useEffect, useRef, useState } from "react";

/** Fetch on mount and whenever `deps` change. Ignores stale responses. Optional polling. */
export function useFetch(fn, deps, pollMs) {
  const [state, setState] = useState({ data: null, error: null, loading: true });
  const seq = useRef(0);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!pollMs) return undefined;
    const t = setInterval(() => setTick((x) => x + 1), pollMs);
    return () => clearInterval(t);
  }, [pollMs]);

  useEffect(() => {
    const id = ++seq.current;
    setState((s) => ({ ...s, loading: true }));
    Promise.resolve()
      .then(fn)
      .then((data) => id === seq.current && setState({ data, error: null, loading: false }))
      .catch((error) => id === seq.current && setState((s) => ({ data: s.data, error, loading: false })));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { ...state, reload: () => setTick((x) => x + 1) };
}
