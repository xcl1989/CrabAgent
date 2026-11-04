import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import { cn } from "../../lib/cn";

export type FloatingMenuPlacement = "bottom-start" | "bottom-end" | "top-start" | "top-end";

interface FloatingMenuProps {
  /** Whether the menu is currently shown. When false nothing is rendered. */
  open: boolean;
  /** Ref of the anchor element the menu is positioned against. */
  anchorRef: RefObject<HTMLElement | null>;
  /**
   * Ref that receives the portal menu element. Pass it when the parent has an
   * outside-click handler so portal clicks are not mistaken for outside clicks.
   */
  menuRef?: RefObject<HTMLDivElement | null>;
  /** Which edge of the anchor the menu attaches to, and how it aligns. */
  placement?: FloatingMenuPlacement;
  /** Distance in px between anchor and menu. */
  gap?: number;
  className?: string;
  /** Extra inline styles merged after the computed position (e.g. maxHeight). */
  style?: CSSProperties;
  children: ReactNode;
}

const EDGE_MARGIN = 8;
const MIN_MENU_HEIGHT = 120;

/**
 * Renders floating menus/dropdowns through a portal into document.body with
 * fixed positioning, so they are never clipped by `overflow-x-auto` /
 * `overflow-hidden` / `overflow-y-auto` ancestors (the same approach used by
 * WorkspaceSwitcher). The position is recomputed on window resize and on any
 * scroll (capture phase), and the menu flips vertically when it would not fit.
 */
export default function FloatingMenu({
  open,
  anchorRef,
  menuRef,
  placement = "bottom-start",
  gap = 4,
  className,
  style,
  children,
}: FloatingMenuProps) {
  const internalRef = useRef<HTMLDivElement | null>(null);
  const menuElementRef = menuRef ?? internalRef;
  const [posStyle, setPosStyle] = useState<CSSProperties>({ visibility: "hidden" });

  useLayoutEffect(() => {
    if (!open) return;
    const update = () => {
      const anchor = anchorRef.current;
      const menu = menuElementRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const menuWidth = menu?.offsetWidth || 0;
      const menuHeight = menu?.offsetHeight || 0;
      let top: number;
      let left: number;
      const opensUp = placement.startsWith("top");
      if (opensUp) {
        top = rect.top - menuHeight - gap;
        if (top < EDGE_MARGIN) {
          // Not enough space above: allow flipping down, clamped to viewport.
          top = Math.max(EDGE_MARGIN, Math.min(rect.bottom + gap, window.innerHeight - Math.max(menuHeight, MIN_MENU_HEIGHT) - EDGE_MARGIN));
        }
      } else {
        top = rect.bottom + gap;
        if (menuHeight && top + menuHeight > window.innerHeight - EDGE_MARGIN) {
          // Not enough space below: allow flipping up, clamped to viewport.
          top = Math.max(EDGE_MARGIN, Math.min(rect.top - menuHeight - gap, window.innerHeight - Math.max(menuHeight, MIN_MENU_HEIGHT) - EDGE_MARGIN));
        }
      }
      left = placement.endsWith("end") ? rect.right - menuWidth : rect.left;
      if (menuWidth) left = Math.max(EDGE_MARGIN, Math.min(left, window.innerWidth - menuWidth - EDGE_MARGIN));
      setPosStyle({ top: Math.max(EDGE_MARGIN, top), left, visibility: "visible" });
    };
    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, placement, gap, anchorRef, menuElementRef]);

  if (!open) return null;
  return createPortal(
    <div ref={menuElementRef} className={cn("fixed z-50", className)} style={{ ...posStyle, ...style }}>
      {children}
    </div>,
    document.body,
  );
}
