import {
  forwardRef,
  useState,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import { Eye, EyeOff } from "lucide-react";
import { cn } from "../../lib/cn";

const baseField =
  "w-full rounded-lg bg-[var(--bg-tertiary)] border border-[var(--border)] " +
  "text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] " +
  "transition-colors duration-150 " +
  "focus:outline-none focus:border-[var(--brand)] focus:bg-[var(--bg-secondary)] focus:ring-2 focus:ring-[var(--brand)]/30 " +
  "disabled:opacity-50 disabled:cursor-not-allowed " +
  "font-sans";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
  leftIcon?: ReactNode;
  rightSlot?: ReactNode;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { label, error, hint, leftIcon, rightSlot, className, id, ...rest },
  ref,
) {
  const inputId = id || rest.name || undefined;
  return (
    <div className="flex flex-col gap-1.5 w-full">
      {label && (
        <label
          htmlFor={inputId}
          className="text-xs font-medium text-[var(--text-secondary)]"
        >
          {label}
        </label>
      )}
      <div className="relative flex items-center">
        {leftIcon && (
          <span className="absolute left-3 text-[var(--text-tertiary)] pointer-events-none">
            {leftIcon}
          </span>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            baseField,
            "h-9 px-3 text-sm",
            !!leftIcon && "pl-9",
            !!rightSlot && "pr-10",
            !!error &&
              "border-[var(--danger)] focus:border-[var(--danger)] focus:ring-[var(--danger)]/30",
            className,
          )}
          {...rest}
        />
        {rightSlot && (
          <span className="absolute right-2 text-[var(--text-tertiary)]">
            {rightSlot}
          </span>
        )}
      </div>
      {error && (
        <p className="text-xs text-[var(--danger)]" role="alert">
          {error}
        </p>
      )}
      {hint && !error && (
        <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>
      )}
    </div>
  );
});

export interface PasswordInputProps extends InputProps {
  /** Override the show/hide toggle visibility */
  showToggle?: boolean;
}

export function PasswordInput({
  showToggle = true,
  ...rest
}: PasswordInputProps) {
  const [shown, setShown] = useState(false);
  return (
    <Input
      {...rest}
      type={shown ? "text" : "password"}
      rightSlot={
        showToggle ? (
          <button
            type="button"
            tabIndex={-1}
            onClick={() => setShown((v) => !v)}
            className="p-1 rounded hover:bg-[var(--bg-elevated)] transition-colors text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
            aria-label={shown ? "Hide password" : "Show password"}
          >
            {shown ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        ) : undefined
      }
    />
  );
}

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  error?: string;
  hint?: string;
  /** Auto-grow the height up to maxRows as user types */
  autoGrow?: boolean;
  minRows?: number;
  maxRows?: number;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  function Textarea(
    { label, error, hint, className, id, autoGrow, minRows = 1, maxRows = 8, onInput, ...rest },
    ref,
  ) {
    const inputId = id || rest.name || undefined;
    return (
      <div className="flex flex-col gap-1.5 w-full">
        {label && (
          <label
            htmlFor={inputId}
            className="text-xs font-medium text-[var(--text-secondary)]"
          >
            {label}
          </label>
        )}
        <textarea
          ref={ref}
          id={inputId}
          onInput={(e) => {
            if (autoGrow) {
              const el = e.currentTarget;
              el.style.height = "auto";
              const lineHeight = 20;
              const maxH = lineHeight * maxRows;
              el.style.height = Math.min(el.scrollHeight, maxH) + "px";
            }
            onInput?.(e);
          }}
          className={cn(
            baseField,
            "px-3 py-2 text-sm resize-none",
            `min-h-[${minRows * 24}px]`,
            error &&
              "border-[var(--danger)] focus:border-[var(--danger)] focus:ring-[var(--danger)]/30",
            className,
          )}
          {...rest}
        />
        {error && (
          <p className="text-xs text-[var(--danger)]" role="alert">
            {error}
          </p>
        )}
        {hint && !error && (
          <p className="text-xs text-[var(--text-tertiary)]">{hint}</p>
        )}
      </div>
    );
  },
);
