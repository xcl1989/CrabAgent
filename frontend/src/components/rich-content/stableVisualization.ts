import { useEffect, useMemo, useRef, useState } from "react";

export interface ParsedVisualization<T> {
  key: string;
  value: T;
}

export function keepStableVisualization<T>(
  current: ParsedVisualization<T> | null,
  candidate: ParsedVisualization<T> | null,
): ParsedVisualization<T> | null {
  if (!candidate || candidate.key === current?.key) return current;
  return candidate;
}

function parseVisualization<T>(source: string, parse: (source: string) => T): ParsedVisualization<T> | null {
  try {
    const value = parse(source);
    return { key: JSON.stringify(value), value };
  } catch {
    return null;
  }
}

/**
 * Keeps the chart input reference stable when markdown keeps changing after a
 * complete visualization payload has already arrived over SSE.
 */
export function useStableVisualization<T>(source: string, parse: (source: string) => T) {
  const candidate = useMemo(() => parseVisualization(source, parse), [source, parse]);
  const [stable, setStable] = useState<ParsedVisualization<T> | null>(candidate);
  const stableRef = useRef(stable);

  useEffect(() => {
    const next = keepStableVisualization(stableRef.current, candidate);
    if (next === stableRef.current) return;
    stableRef.current = next;
    setStable(next);
  }, [candidate]);

  return { candidate, stable };
}
