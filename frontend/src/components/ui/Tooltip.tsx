import {
  Provider as TooltipProvider,
  Root as TooltipRoot,
  Trigger as TooltipTrigger,
  Content as TooltipContent,
  Portal as TooltipPortal,
} from "@radix-ui/react-tooltip";
import { type ReactNode, type HTMLAttributes } from "react";
import { cn } from "../../lib/cn";

interface TooltipProps {
  content: ReactNode;
  /** Delay before showing, in ms. Default 300 */
  delayMs?: number;
  /** Side of trigger to display */
  side?: "top" | "right" | "bottom" | "left";
  /** Render tooltip as a child wrapper (default span) */
  asChild?: boolean;
  children: ReactNode;
}

export function Tooltip({
  content,
  delayMs = 300,
  side = "top",
  asChild,
  children,
}: TooltipProps) {
  return (
    <TooltipProvider delayDuration={delayMs}>
      <TooltipRoot>
        <TooltipTrigger asChild={asChild}>
          {asChild ? children : <span className="inline-flex">{children}</span>}
        </TooltipTrigger>
        <TooltipPortal>
          <TooltipContent
            side={side}
            sideOffset={6}
            className={cn(
              "z-50 max-w-xs px-2.5 py-1.5 rounded-md",
              "bg-[var(--bg-elevated)] text-[var(--text-primary)]",
              "border border-[var(--border)] shadow-[var(--shadow-md)]",
              "text-xs leading-tight",
              "data-[state=delayed-open]:animate-fade-in",
            )}
          >
            {content}
          </TooltipContent>
        </TooltipPortal>
      </TooltipRoot>
    </TooltipProvider>
  );
}

/** Container to wrap once at app root — note: each Tooltip above already provides its own Provider */
export function TooltipContainer({ children }: { children: ReactNode }) {
  return <TooltipProvider delayDuration={300}>{children}</TooltipProvider>;
}
