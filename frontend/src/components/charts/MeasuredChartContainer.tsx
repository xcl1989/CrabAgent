import { useLayoutEffect, useRef, useState, type ReactNode } from "react";

interface Props {
  height: number;
  children: (size: { width: number; height: number }) => ReactNode;
}

/**
 * Supplies Recharts with explicit dimensions instead of its ResponsiveContainer.
 * It ignores hidden/zero-width layouts and only updates after a real resize.
 */
export function MeasuredChartContainer({ height, children }: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const widthRef = useRef(0);
  const frameRef = useRef<number | null>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const element = elementRef.current;
    if (!element) return;

    const update = (nextWidth: number) => {
      const rounded = Math.floor(nextWidth);
      if (rounded < 1 || rounded === widthRef.current) return;
      widthRef.current = rounded;
      setWidth(rounded);
    };
    const scheduleUpdate = (nextWidth: number) => {
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null;
        update(nextWidth);
      });
    };

    update(element.getBoundingClientRect().width);
    const observer = new ResizeObserver((entries) => {
      scheduleUpdate(entries[0]?.contentRect.width || 0);
    });
    observer.observe(element);

    return () => {
      observer.disconnect();
      if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
    };
  }, []);

  return (
    <div ref={elementRef} style={{ width: "100%", height }}>
      {width > 0 && children({ width, height })}
    </div>
  );
}
