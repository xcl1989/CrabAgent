import { useEffect, useState, type ReactNode } from "react";
import { ArrowDown, ArrowUp, Clock, Layers, Zap } from "lucide-react";
import { Tooltip } from "./ui";
import { cn } from "../lib/cn";
import {
  getSessionUsageSummary,
  type SessionUsageSummary,
} from "../api/tokenUsage";

interface Props {
  sessionId: string | null;
  /** 变化时重新拉取（如 messages.length、sending 状态） */
  refreshKey?: number;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtElapsed(sec: number): string {
  if (sec >= 3600) return `${(sec / 3600).toFixed(1)}h`;
  if (sec >= 60) return `${Math.floor(sec / 60)}m${Math.round(sec % 60)}s`;
  return `${sec.toFixed(sec < 10 ? 1 : 0)}s`;
}

function Stat({
  icon,
  label,
  value,
  sub,
  subClass,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  sub?: string;
  subClass?: string;
  detail?: string;
}) {
  return (
    <Tooltip
      content={
        <span>
          <span className="text-[var(--text-primary)] font-medium">{detail || label}</span>
        </span>
      }
      side="bottom"
    >
      <span className="flex items-center gap-1 shrink-0">
        <span className="text-[var(--text-tertiary)]">{icon}</span>
        <span className="font-medium text-[var(--text-secondary)]">{value}</span>
        {sub && <span className={cn("text-[var(--text-tertiary)]", subClass)}>{sub}</span>}
      </span>
    </Tooltip>
  );
}

/**
 * 会话级用量统计条：总 tokens / 输入（缓存·非缓存）/ 输出 / 累计耗时 / 调用次数。
 * 数据来自 /token-usage/session/{id}/summary，随 refreshKey 变化防抖刷新。
 */
export function SessionStatsBar({ sessionId, refreshKey = 0 }: Props) {
  const [summary, setSummary] = useState<SessionUsageSummary | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setSummary(null);
      return;
    }
    let cancelled = false;
    const timer = setTimeout(() => {
      getSessionUsageSummary(sessionId)
        .then((data) => {
          if (!cancelled) setSummary(data);
        })
        .catch(() => {});
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [sessionId, refreshKey]);

  if (!summary || summary.calls === 0) return null;

  const cacheRate = Math.round(summary.cache_hit_rate * 100);
  const cacheGood = summary.cache_hit_rate >= 0.7;

  return (
    <div className="flex items-center gap-3 overflow-x-auto pb-1.5 mb-1.5 scrollbar-none text-[11px]">
      <Stat
        icon={<Zap size={12} />}
        label="累计 tokens"
        value={fmtTokens(summary.total_tokens)}
        detail={`累计 ${summary.total_tokens.toLocaleString()} tokens`}
      />
      <Stat
        icon={<ArrowUp size={12} className="text-[var(--accent)]" />}
        label="输入 tokens"
        value={fmtTokens(summary.prompt_tokens)}
        sub={`缓存 ${fmtTokens(summary.cached_tokens)} · ${cacheRate}%`}
        subClass={cacheGood ? "text-[var(--success)]" : undefined}
        detail={`输入 ${summary.prompt_tokens.toLocaleString()} tokens（缓存命中 ${summary.cached_tokens.toLocaleString()}，非缓存 ${summary.non_cached_tokens.toLocaleString()}，命中率 ${cacheRate}%）`}
      />
      <Stat
        icon={<ArrowDown size={12} className="text-[var(--warning)]" />}
        label="输出 tokens"
        value={fmtTokens(summary.completion_tokens)}
        detail={`输出 ${summary.completion_tokens.toLocaleString()} tokens${
          summary.reasoning_tokens > 0
            ? `（含推理 ${summary.reasoning_tokens.toLocaleString()}）`
            : ""
        }`}
      />
      <Stat
        icon={<Clock size={12} />}
        label="累计耗时"
        value={fmtElapsed(summary.elapsed)}
        detail={`累计耗时 ${summary.elapsed.toLocaleString()}s · ${summary.turns} 轮任务`}
      />
      <Stat
        icon={<Layers size={12} />}
        label="调用次数"
        value={`${summary.calls}`}
        detail={`${summary.calls} 次 LLM 调用`}
      />
    </div>
  );
}
