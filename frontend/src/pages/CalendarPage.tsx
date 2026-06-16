import { useState, useEffect, useMemo, useCallback } from "react";
import {
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Plus,
  Clock,
  MapPin,
  Trash2,
  RefreshCw,
  Bell,
  Sun,
  Settings as SettingsIcon,
  X,
  Link2,
} from "lucide-react";
import {
  calendarApi,
  type CalendarEvent,
  type TodayOverview,
  type IcalSource,
  type CalendarSettings,
} from "../api/calendar";
import { Modal, Button, Input, Textarea } from "../components/ui";
import { toast } from "../components/ui/Toast";
import { cn } from "../lib/cn";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TYPE_COLORS: Record<string, { dot: string; bg: string; border: string; text: string }> = {
  task: { dot: "bg-red-500", bg: "bg-red-500/10", border: "border-red-500/30", text: "text-red-400" },
  manual: { dot: "bg-amber-500", bg: "bg-amber-500/10", border: "border-amber-500/30", text: "text-amber-400" },
  agent: { dot: "bg-green-500", bg: "bg-green-500/10", border: "border-green-500/30", text: "text-green-400" },
  external: { dot: "bg-blue-500", bg: "bg-blue-500/10", border: "border-blue-500/30", text: "text-blue-400" },
};

const TYPE_LABELS: Record<string, string> = {
  task: "任务截止",
  manual: "手动事件",
  agent: "Agent创建",
  external: "外部同步",
};

const WEEKDAYS = ["日", "一", "二", "三", "四", "五", "六"];
const MONTHS = ["一月", "二月", "三月", "四月", "五月", "六月", "七月", "八月", "九月", "十月", "十一月", "十二月"];

type ViewMode = "month" | "week" | "day";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toDateStr(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseDate(s: string): Date {
  return new Date(s.includes("T") ? s : s + "T00:00:00");
}

function isSameDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

function getMonthMatrix(year: number, month: number): Date[][] {
  const first = new Date(year, month, 1);
  const startDay = first.getDay();
  const weeks: Date[][] = [];
  let cursor = new Date(year, month, 1 - startDay);
  for (let w = 0; w < 6; w++) {
    const row: Date[] = [];
    for (let d = 0; d < 7; d++) {
      row.push(new Date(cursor));
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(row);
  }
  return weeks;
}

function getWeekDays(center: Date): Date[] {
  const monday = new Date(center);
  const day = monday.getDay();
  monday.setDate(monday.getDate() - (day === 0 ? 6 : day - 1));
  const days: Date[] = [];
  for (let i = 0; i < 7; i++) {
    days.push(new Date(monday));
    monday.setDate(monday.getDate() + 1);
  }
  return days;
}

function formatTime(s: string): string {
  const d = parseDate(s);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function formatDuration(min: number): string {
  const h = Math.floor(min / 60);
  const m = min % 60;
  if (h && m) return `${h}小时${m}分`;
  if (h) return `${h}小时`;
  return `${m}分钟`;
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function CalendarPage() {
  const [view, setView] = useState<ViewMode>("month");
  const [cursor, setCursor] = useState(new Date());
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [overview, setOverview] = useState<TodayOverview | null>(null);
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [loading, setLoading] = useState(false);
  const [icalSources, setIcalSources] = useState<IcalSource[]>([]);

  // Calculate date range based on view
  const { rangeStart, rangeEnd } = useMemo(() => {
    if (view === "month") {
      const m = getMonthMatrix(cursor.getFullYear(), cursor.getMonth());
      return { rangeStart: toDateStr(m[0][0]), rangeEnd: toDateStr(m[5][6]) };
    } else if (view === "week") {
      const days = getWeekDays(cursor);
      return { rangeStart: toDateStr(days[0]), rangeEnd: toDateStr(days[6]) };
    } else {
      return { rangeStart: toDateStr(cursor), rangeEnd: toDateStr(cursor) };
    }
  }, [view, cursor]);

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    try {
      const [evts, today, sources] = await Promise.all([
        calendarApi.listEvents(rangeStart, rangeEnd),
        calendarApi.getToday(),
        calendarApi.listIcalSources(),
      ]);
      setEvents(evts);
      setOverview(today);
      setIcalSources(sources);
    } catch (_e: unknown) {
      console.error("Failed to load calendar:", _e);
    } finally {
      setLoading(false);
    }
  }, [rangeStart, rangeEnd]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  const eventsByDay = useMemo(() => {
    const map: Record<string, CalendarEvent[]> = {};
    for (const e of events) {
      if (!e.start_time) continue;
      const day = e.start_time.slice(0, 10);
      if (!map[day]) map[day] = [];
      map[day].push(e);
    }
    return map;
  }, [events]);

  const navigate = (dir: -1 | 1) => {
    const d = new Date(cursor);
    if (view === "month") d.setMonth(d.getMonth() + dir);
    else if (view === "week") d.setDate(d.getDate() + dir * 7);
    else d.setDate(d.getDate() + dir);
    setCursor(d);
  };

  const goToday = () => setCursor(new Date());

  const titleStr = useMemo(() => {
    if (view === "month") return `${cursor.getFullYear()}年 ${MONTHS[cursor.getMonth()]}`;
    if (view === "week") {
      const days = getWeekDays(cursor);
      return `${toDateStr(days[0]).slice(5)} ~ ${toDateStr(days[6]).slice(5)}`;
    }
    return toDateStr(cursor);
  }, [view, cursor]);

  return (
    <div className="flex h-full overflow-hidden bg-[var(--bg-primary)]">
      {/* Main calendar area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-6 py-3 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-1">
            <button
              onClick={() => navigate(-1)}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] transition-colors"
            >
              <ChevronLeft size={18} />
            </button>
            <button
              onClick={() => navigate(1)}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] transition-colors"
            >
              <ChevronRight size={18} />
            </button>
          </div>
          <h2 className="text-base font-semibold text-[var(--text-primary)] min-w-[140px]">{titleStr}</h2>
          <Button size="sm" variant="ghost" onClick={goToday}>
            今天
          </Button>
          <div className="ml-auto flex items-center gap-2">
            {/* View switcher */}
            <div className="flex items-center rounded-lg border border-[var(--border)] overflow-hidden">
              {(["month", "week", "day"] as ViewMode[]).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={cn(
                    "px-3 py-1 text-xs font-medium transition-colors",
                    view === v
                      ? "bg-[var(--accent)] text-white"
                      : "text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)]",
                  )}
                >
                  {v === "month" ? "月" : v === "week" ? "周" : "日"}
                </button>
              ))}
            </div>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              <Plus size={14} className="mr-1" /> 新建事件
            </Button>
            <button
              onClick={() => setShowSettings(true)}
              className="p-1.5 rounded-lg hover:bg-[var(--bg-tertiary)] text-[var(--text-secondary)] transition-colors"
            >
              <SettingsIcon size={16} />
            </button>
          </div>
        </div>

        {/* Calendar body */}
        <div className="flex-1 overflow-y-auto p-6">
          {view === "month" && (
            <MonthView matrix={getMonthMatrix(cursor.getFullYear(), cursor.getMonth())} eventsByDay={eventsByDay} onEventClick={setSelectedEvent} cursor={cursor} />
          )}
          {view === "week" && <WeekView days={getWeekDays(cursor)} events={events} onEventClick={setSelectedEvent} />}
          {view === "day" && <DayView day={cursor} events={events.filter((e) => e.start_time && isSameDay(parseDate(e.start_time), cursor))} onEventClick={setSelectedEvent} />}
        </div>
      </div>

      {/* Right sidebar — today overview */}
      <div className="w-80 shrink-0 border-l border-[var(--border)] flex flex-col overflow-hidden bg-[var(--bg-secondary)]">
        <div className="px-4 py-3 border-b border-[var(--border)] shrink-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-[var(--text-primary)]">
            <Sun size={15} className="text-amber-400" />
            今日概览
          </div>
          {overview && <p className="text-xs text-[var(--text-tertiary)] mt-1">{overview.summary}</p>}
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {overview?.events.length === 0 && <p className="text-xs text-[var(--text-tertiary)] text-center py-8">今天没有事件</p>}
          {overview?.events.map((e) => {
            const colors = TYPE_COLORS[e.type] || TYPE_COLORS.manual;
            return (
              <div
                key={e.id}
                onClick={() => setSelectedEvent(e)}
                className={cn("rounded-lg border p-3 cursor-pointer transition-colors hover:border-[var(--border-strong)]", colors.bg, colors.border)}
              >
                <div className="flex items-start gap-2">
                  <div className={cn("w-2 h-2 rounded-full mt-1.5 shrink-0", colors.dot)} />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-[var(--text-primary)] truncate">{e.title}</p>
                    {!e.all_day && e.start_time && (
                      <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
                        <Clock size={11} className="inline mr-1" />
                        {formatTime(e.start_time)}
                        {e.end_time && ` - ${formatTime(e.end_time)}`}
                      </p>
                    )}
                    {e.location && (
                      <p className="text-xs text-[var(--text-tertiary)] mt-0.5">
                        <MapPin size={11} className="inline mr-1" />
                        {e.location}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {/* Free slots */}
          {overview && overview.free_slots.length > 0 && (
            <div className="pt-2 border-t border-[var(--border)]">
              <p className="text-xs font-medium text-[var(--text-secondary)] mb-2">🟢 空闲时段</p>
              {overview.free_slots.map((slot, i) => (
                <div key={i} className="flex items-center gap-2 text-xs text-[var(--text-tertiary)] mb-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-green-500/50" />
                  {formatTime(slot.start)} - {formatTime(slot.end)}
                  <span className="text-[var(--text-tertiary)]">({formatDuration(slot.duration_min)})</span>
                </div>
              ))}
            </div>
          )}
        </div>
        {/* iCal sources summary */}
        {icalSources.length > 0 && (
          <div className="px-4 py-2 border-t border-[var(--border)] shrink-0">
            <div className="flex items-center gap-1.5 text-xs text-[var(--text-tertiary)]">
              <Link2 size={12} />
              {icalSources.length} 个外部日历
            </div>
          </div>
        )}
      </div>

      {/* Modals */}
      {showCreate && (
        <CreateEventModal
          defaultDate={toDateStr(cursor)}
          onClose={() => setShowCreate(false)}
          onCreated={() => {
            setShowCreate(false);
            fetchEvents();
          }}
        />
      )}
      {selectedEvent && (
        <EventDetailModal
          event={selectedEvent}
          onClose={() => setSelectedEvent(null)}
          onChanged={() => {
            setSelectedEvent(null);
            fetchEvents();
          }}
        />
      )}
      {showSettings && (
        <CalendarSettingsModal onClose={() => setShowSettings(false)} onChanged={fetchEvents} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Month View
// ---------------------------------------------------------------------------

function MonthView({ matrix, eventsByDay, onEventClick, cursor }: {
  matrix: Date[][];
  eventsByDay: Record<string, CalendarEvent[]>;
  onEventClick: (e: CalendarEvent) => void;
  cursor: Date;
}) {
  const today = new Date();
  return (
    <div>
      {/* Weekday header */}
      <div className="grid grid-cols-7 gap-2 mb-2">
        {WEEKDAYS.map((d, i) => (
          <div key={d} className={cn("text-center text-xs font-medium py-1", i === 0 || i === 6 ? "text-[var(--accent-2)]" : "text-[var(--text-tertiary)]")}>
            {d}
          </div>
        ))}
      </div>
      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-2">
        {matrix.flat().map((day, i) => {
          const dayStr = toDateStr(day);
          const dayEvents = eventsByDay[dayStr] || [];
          const isCurrentMonth = day.getMonth() === cursor.getMonth();
          const isToday = isSameDay(day, today);
          return (
            <div
              key={i}
              className={cn(
                "min-h-[88px] rounded-lg border p-1.5 transition-colors",
                isCurrentMonth ? "border-[var(--border)] bg-[var(--bg-primary)]" : "border-transparent bg-[var(--bg-tertiary)] opacity-50",
                "hover:border-[var(--border-strong)]",
              )}
            >
              <div className={cn(
                "text-xs font-medium mb-1 flex items-center justify-center w-6 h-6 rounded-full",
                isToday ? "bg-[var(--accent)] text-white" : "text-[var(--text-secondary)]",
              )}>
                {day.getDate()}
              </div>
              <div className="space-y-0.5">
                {dayEvents.slice(0, 3).map((e) => {
                  const colors = TYPE_COLORS[e.type] || TYPE_COLORS.manual;
                  return (
                    <div
                      key={e.id}
                      onClick={() => onEventClick(e)}
                      className={cn("text-[10px] px-1.5 py-0.5 rounded truncate cursor-pointer transition-colors", colors.bg, colors.text)}
                    >
                      {e.all_day ? "" : e.start_time ? formatTime(e.start_time) + " " : ""}{e.title}
                    </div>
                  );
                })}
                {dayEvents.length > 3 && (
                  <div className="text-[10px] text-[var(--text-tertiary)] px-1.5">+{dayEvents.length - 3} 更多</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Week View
// ---------------------------------------------------------------------------

function WeekView({ days, events, onEventClick }: {
  days: Date[];
  events: CalendarEvent[];
  onEventClick: (e: CalendarEvent) => void;
}) {
  const today = new Date();
  return (
    <div className="grid grid-cols-7 gap-2 h-full">
      {days.map((day, i) => {
        const dayEvents = events.filter((e) => e.start_time && isSameDay(parseDate(e.start_time), day));
        return (
          <div key={i} className="rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] flex flex-col overflow-hidden">
            <div className={cn(
              "text-center py-2 border-b border-[var(--border)] shrink-0",
              isSameDay(day, today) && "bg-[var(--accent-bg)]",
            )}>
              <div className="text-xs text-[var(--text-tertiary)]">{WEEKDAYS[day.getDay()]}</div>
              <div className={cn(
                "text-lg font-semibold mt-0.5",
                isSameDay(day, today) ? "text-[var(--accent)]" : "text-[var(--text-primary)]",
              )}>
                {day.getDate()}
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-1.5 space-y-1">
              {dayEvents.map((e) => {
                const colors = TYPE_COLORS[e.type] || TYPE_COLORS.manual;
                return (
                  <div
                    key={e.id}
                    onClick={() => onEventClick(e)}
                    className={cn("rounded-md border p-1.5 cursor-pointer transition-colors hover:border-[var(--border-strong)]", colors.bg, colors.border)}
                  >
                    {!e.all_day && e.start_time && (
                      <p className={cn("text-[10px] font-mono", colors.text)}>{formatTime(e.start_time)}</p>
                    )}
                    <p className="text-xs text-[var(--text-primary)] truncate">{e.title}</p>
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Day View (timeline)
// ---------------------------------------------------------------------------

function DayView({ day, events, onEventClick }: {
  day: Date;
  events: CalendarEvent[];
  onEventClick: (e: CalendarEvent) => void;
}) {
  const HOUR_HEIGHT = 48;
  const hours = Array.from({ length: 24 }, (_, i) => i);

  // Split events into timeline blocks (with end_time) and reminder pins (time-point events)
  // Block events = time-spanning events (meetings, tasks with duration)
  // Pin events   = time-point reminders (deadlines, tasks without end_time)
  const blockEvents: (CalendarEvent & {_start:Date;_end:Date;_top:number;_height:number;colors:{dot:string;bg:string;border:string;text:string}})[] = [];
  const pinEvents: (CalendarEvent & {_start:Date;_top:number;colors:{dot:string;bg:string;border:string;text:string}})[] = [];
  for (const e of events) {
    if (e.all_day || !e.start_time) continue;
    try {
      const start = parseDate(e.start_time);
      if (isNaN(start.getTime())) continue;
      const startMin = start.getHours() * 60 + start.getMinutes();
      const top = (startMin / 60) * HOUR_HEIGHT + 8;
      if (isNaN(top)) continue;
      const colors = TYPE_COLORS[e.type] || TYPE_COLORS.manual;

      // Block: has end_time AND is not a task-type (task deadlines = pins)
      if (e.end_time && e.type !== 'task') {
        const end = parseDate(e.end_time);
        const endMin = end.getHours() * 60 + end.getMinutes();
        const durationMin = Math.max(endMin - startMin, 30);
        const height = (durationMin / 60) * HOUR_HEIGHT;
        if (isNaN(height)) continue;
        blockEvents.push(Object.assign(e, {_start:start,_end:end,_top:top,_height:height,colors}));
      } else {
        // Pin: task deadline or any event without end_time
        pinEvents.push(Object.assign(e, {_start:start,_top:top,colors}));
      }
    } catch(ex) {
      console.warn("DayView: skip event", e.id, ex);
    }
  }

  const allDayEvents = events.filter((e) => e.all_day);
  const hasPins = pinEvents.length > 0;
  const PIN_ZONE = 150; // px reserved on the right for pin labels

  return (
    <div className="max-w-2xl mx-auto">
      {allDayEvents.length > 0 && (
        <div className="mb-4 space-y-1">
          {allDayEvents.map((e) => {
            const colors = TYPE_COLORS[e.type] || TYPE_COLORS.manual;
            return (
              <div key={e.id} onClick={() => onEventClick(e)} className={cn("rounded-lg border px-3 py-2 cursor-pointer", colors.bg, colors.border)}>
                <span className={cn("text-sm", colors.text)}>{e.title}</span>
              </div>
            );
          })}
        </div>
      )}
      <div className="flex gap-3" style={{ minHeight: 24 * HOUR_HEIGHT + 8 }}>
        <div className="w-12 shrink-0 relative" style={{ height: 24 * HOUR_HEIGHT + 8 }}>
          {hours.map((h) => (
            <div key={h} className="absolute text-xs text-[var(--text-tertiary)] font-mono" style={{ top: h * HOUR_HEIGHT + 2, left: 0 }}>
              {String(h).padStart(2, "0")}:00
            </div>
          ))}
        </div>
        <div className="flex-1 relative" style={{ height: 24 * HOUR_HEIGHT + 8 }}>
          {hours.map((h) => (
            <div key={h} className="absolute left-0 right-0 border-t border-[var(--border)]" style={{ top: h * HOUR_HEIGHT + 8 }} />
          ))}
          {/* ── Block events ── */}
          {blockEvents.map((e) => (
            <div
              key={e.id}
              onClick={() => onEventClick(e)}
              className={cn(
                "absolute rounded-lg border p-1.5 cursor-pointer overflow-hidden text-xs z-10",
                e.colors.bg, e.colors.border,
              )}
              style={{
                top: e._top,
                height: Math.max(e._height, 36),
                left: 4,
                right: hasPins ? PIN_ZONE : 4,
              }}
            >
              <span className="font-mono text-[10px] text-[var(--text-tertiary)] block">
                {formatTime(e.start_time!)}{e.end_time ? `-${formatTime(e.end_time)}` : ''}
              </span>
              <span className="text-xs text-[var(--text-primary)] leading-tight block truncate">{e.title}</span>
            </div>
          ))}
          {/* ── Pin (reminder) events ── */}
          {pinEvents.map((e) => (
            <div
              key={e.id}
              onClick={() => onEventClick(e)}
              className="absolute z-20 flex items-center gap-1.5 px-2.5 py-0.5 rounded-md cursor-pointer whitespace-nowrap transition-colors hover:bg-red-500/15"
              style={{
                top: e._top,
                right: 10,
                transform: 'translateY(-50%)',
                backgroundColor: 'rgba(239, 68, 68, 0.07)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                color: '#ef4444',
              }}
            >
              <span className="font-mono text-[11px] font-medium">{formatTime(e.start_time!)}</span>
              <span className="w-1.5 h-1.5 rounded-full bg-red-500 shrink-0" />
              <span className="text-xs font-medium truncate" style={{ maxWidth: 100 }}>{e.title}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create Event Modal
// ---------------------------------------------------------------------------

function CreateEventModal({ defaultDate, onClose, onCreated }: {
  defaultDate: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(defaultDate);
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("");
  const [allDay, setAllDay] = useState(false);
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [reminder, setReminder] = useState("15");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!title.trim()) {
      toast.error("请输入事件标题");
      return;
    }
    setSaving(true);
    try {
      await calendarApi.createEvent({
        title: title.trim(),
        start_time: allDay ? date : `${date}T${startTime}:00`,
        end_time: endTime && !allDay ? `${date}T${endTime}:00` : undefined,
        all_day: allDay,
        location: location.trim(),
        description: description.trim(),
        reminder_minutes: parseInt(reminder) || 0,
      });
      toast.success("事件已创建");
      onCreated();
    } catch (_e: unknown) {
      toast.error("创建失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal open onOpenChange={() => onClose()} title="新建事件" size="md">
      <div className="space-y-4">
        <Input
          placeholder="事件标题"
          value={title}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => setTitle(e.target.value)}
          autoFocus
        />
        <div className="flex items-center gap-2">
          <input type="checkbox" id="all-day" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} className="rounded" />
          <label htmlFor="all-day" className="text-sm text-[var(--text-secondary)] cursor-pointer">全天事件</label>
        </div>
        <div className="flex items-center gap-2">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="flex-1" />
          {!allDay && (
            <>
              <Input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} className="w-28" />
              <span className="text-[var(--text-tertiary)]">-</span>
              <Input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} className="w-28" placeholder="结束" />
            </>
          )}
        </div>
        <Input placeholder="地点（可选）" value={location} onChange={(e) => setLocation(e.target.value)} />
        <Textarea placeholder="描述（可选）" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
        <div className="flex items-center gap-2">
          <Bell size={14} className="text-[var(--text-tertiary)]" />
          <select
            value={reminder}
            onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setReminder(e.target.value)}
            className="w-32 px-3 py-1.5 rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] text-sm text-[var(--text-primary)]"
          >
            <option value="0">不提醒</option>
            <option value="5">提前5分钟</option>
            <option value="15">提前15分钟</option>
            <option value="30">提前30分钟</option>
            <option value="60">提前1小时</option>
            <option value="1440">提前1天</option>
          </select>
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-6">
        <Button variant="ghost" onClick={onClose}>取消</Button>
        <Button onClick={handleSave} disabled={saving}>{saving ? "保存中..." : "创建"}</Button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Event Detail Modal
// ---------------------------------------------------------------------------

function EventDetailModal({ event, onClose, onChanged }: {
  event: CalendarEvent;
  onClose: () => void;
  onChanged: () => void;
}) {
  const colors = TYPE_COLORS[event.type] || TYPE_COLORS.manual;
  const isTask = event.type === "task";

  const handleDelete = async () => {
    if (isTask || typeof event.id === "string") {
      toast.info("任务截止事件由任务系统管理，无法在日历中删除");
      return;
    }
    try {
      await calendarApi.deleteEvent(event.id as number);
      toast.success("事件已删除");
      onChanged();
    } catch {
      toast.error("删除失败");
    }
  };

  return (
    <Modal open onOpenChange={() => onClose()} title="事件详情" size="md">
      <div className="space-y-3">
        <div className={cn("rounded-lg border p-3", colors.bg, colors.border)}>
          <div className="flex items-center gap-2 mb-1">
            <div className={cn("w-3 h-3 rounded-full", colors.dot)} />
            <span className={cn("text-xs font-medium", colors.text)}>{TYPE_LABELS[event.type] || event.type}</span>
          </div>
          <h3 className="text-base font-semibold text-[var(--text-primary)]">{event.title}</h3>
        </div>
        {event.start_time && (
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <Clock size={14} className="text-[var(--text-tertiary)]" />
            {event.all_day ? "全天" : formatTime(event.start_time)}
            {event.end_time && !event.all_day && ` - ${formatTime(event.end_time)}`}
          </div>
        )}
        {event.location && (
          <div className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
            <MapPin size={14} className="text-[var(--text-tertiary)]" />
            {event.location}
          </div>
        )}
        {event.description && (
          <p className="text-sm text-[var(--text-secondary)] bg-[var(--bg-tertiary)] rounded-lg p-3">{event.description}</p>
        )}
        {event.project && (
          <div className="text-xs text-[var(--text-tertiary)]">📁 {event.project}</div>
        )}
      </div>
      <div className="flex justify-between mt-6">
        {!isTask && typeof event.id === "number" ? (
          <Button variant="danger" size="sm" onClick={handleDelete}>
            <Trash2 size={13} className="mr-1" /> 删除
          </Button>
        ) : <div />}
        <Button variant="ghost" onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Settings Modal
// ---------------------------------------------------------------------------

function CalendarSettingsModal({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [settings, setSettings] = useState<CalendarSettings | null>(null);
  const [sources, setSources] = useState<IcalSource[]>([]);
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");
  const [newSourceType, setNewSourceType] = useState<"ical" | "caldav">("ical");
  const [newCalUser, setNewCalUser] = useState("");
  const [newCalPass, setNewCalPass] = useState("");
  const [syncing, setSyncing] = useState<number | null>(null);

  useEffect(() => {
    Promise.all([calendarApi.getSettings(), calendarApi.listIcalSources()]).then(([s, src]) => {
      setSettings(s);
      setSources(src);
    });
  }, []);

  const updateSetting = (key: keyof CalendarSettings, value: string | boolean) => {
    if (!settings) return;
    const updated = { ...settings, [key]: value };
    setSettings(updated);
    calendarApi.updateSettings({ [key]: value }).catch(() => {});
  };

  const addSource = async () => {
    if (!newName.trim()) {
      toast.error("请填写名称");
      return;
    }
    if (newSourceType === "ical" && !newUrl.trim()) {
      toast.error("请填写 iCal 订阅链接");
      return;
    }
    if (newSourceType === "caldav" && (!newUrl.trim() || !newCalUser.trim() || !newCalPass.trim())) {
      toast.error("请填写 CalDAV 服务器、用户名和密码");
      return;
    }
    try {
      await calendarApi.createIcalSource({
        name: newName.trim(),
        url: newSourceType === "ical"
          ? newUrl.trim()
          : (newUrl.trim() || "https://caldav.wecom.work"),
        source_type: newSourceType,
        caldav_username: newSourceType === "caldav" ? newCalUser.trim() : undefined,
        caldav_password: newSourceType === "caldav" ? newCalPass.trim() : undefined,
      });
      setNewName("");
      setNewUrl("");
      setNewCalUser("");
      setNewCalPass("");
      const updated = await calendarApi.listIcalSources();
      setSources(updated);
      toast.success("订阅源已添加");
    } catch {
      toast.error("添加失败");
    }
  };

  const deleteSource = async (id: number) => {
    try {
      await calendarApi.deleteIcalSource(id);
      setSources(sources.filter((s) => s.id !== id));
      toast.success("已删除");
      onChanged();
    } catch {
      toast.error("删除失败");
    }
  };

  const syncSource = async (id: number) => {
    setSyncing(id);
    try {
      const result = await calendarApi.syncIcalSource(id);
      toast.success(`同步了 ${result.synced} 个事件`);
      const updated = await calendarApi.listIcalSources();
      setSources(updated);
      onChanged();
    } catch (_e: unknown) {
      toast.error("同步失败");
    } finally {
      setSyncing(null);
    }
  };

  return (
    <Modal open onOpenChange={() => onClose()} title="日历设置" size="md">
      <div className="space-y-5">
        {/* Notification settings */}
        <div className="space-y-3">
          <h4 className="text-sm font-semibold text-[var(--text-primary)]">通知设置</h4>
          <div className="flex items-center justify-between">
            <label className="text-sm text-[var(--text-secondary)] flex items-center gap-1.5">
              <Sun size={13} /> 晨报推送
            </label>
            <input
              type="checkbox"
              checked={settings?.morning_brief_enabled || false}
              onChange={(e) => updateSetting("morning_brief_enabled", e.target.checked)}
              className="rounded"
            />
          </div>
          {settings?.morning_brief_enabled && (
            <div className="flex items-center justify-between pl-5">
              <label className="text-xs text-[var(--text-tertiary)]">推送时间</label>
              <Input
                type="time"
                value={settings?.morning_brief_time || "08:00"}
                onChange={(e) => updateSetting("morning_brief_time", e.target.value)}
                className="w-28"
              />
            </div>
          )}
          <div className="flex items-center justify-between">
            <label className="text-sm text-[var(--text-secondary)] flex items-center gap-1.5">
              <Bell size={13} /> 事件提醒
            </label>
            <input
              type="checkbox"
              checked={settings?.event_reminder_enabled ?? true}
              onChange={(e) => updateSetting("event_reminder_enabled", e.target.checked)}
              className="rounded"
            />
          </div>
        </div>

        {/* iCal sources */}
        <div className="space-y-3 pt-3 border-t border-[var(--border)]">
          <h4 className="text-sm font-semibold text-[var(--text-primary)] flex items-center gap-1.5">
            <Link2 size={14} /> 外部日历订阅
          </h4>
          {sources.length === 0 && (
            <p className="text-xs text-[var(--text-tertiary)] py-2">
              添加钉钉/飞书/企业微信的 iCal 订阅链接，自动同步外部日程
            </p>
          )}
          {sources.map((s) => (
            <div key={s.id} className="flex items-center gap-2 bg-[var(--bg-tertiary)] rounded-lg p-2.5">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5">
                  <p className="text-sm text-[var(--text-primary)] truncate">{s.name}</p>
                  {s.source_type === "caldav" && (
                    <span className="text-[9px] px-1 py-0.5 rounded bg-[var(--accent-bg)] text-[var(--accent)] shrink-0">CalDAV</span>
                  )}
                </div>
                <p className="text-xs text-[var(--text-tertiary)] truncate">
                  {(s.sync_event_count ?? 0) > 0 ? `${s.sync_event_count} 个事件` : "未同步"}
                  {s.last_sync_status === "error" && " · ❌ 错误"}
                </p>
              </div>
              <button
                onClick={() => syncSource(s.id)}
                disabled={syncing === s.id}
                className="p-1.5 rounded hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)] disabled:opacity-50"
              >
                <RefreshCw size={14} className={syncing === s.id ? "animate-spin" : ""} />
              </button>
              <button
                onClick={() => deleteSource(s.id)}
                className="p-1.5 rounded hover:bg-[var(--bg-secondary)] text-[var(--text-secondary)]"
              >
                <X size={14} />
              </button>
            </div>
          ))}
          {/* Add new source */}
          <div className="space-y-2">
            {/* Type switcher */}
            <div className="flex items-center gap-2">
              <button
                onClick={() => setNewSourceType("ical")}
                className={cn(
                  "px-3 py-1 text-xs rounded-md font-medium transition-colors",
                  newSourceType === "ical"
                    ? "bg-[var(--accent)] text-white"
                    : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border border-[var(--border)]",
                )}
              >
                📋 iCal 链接
              </button>
              <button
                onClick={() => setNewSourceType("caldav")}
                className={cn(
                  "px-3 py-1 text-xs rounded-md font-medium transition-colors",
                  newSourceType === "caldav"
                    ? "bg-[var(--accent)] text-white"
                    : "bg-[var(--bg-tertiary)] text-[var(--text-secondary)] border border-[var(--border)]",
                )}
              >
                💼 企业微信 CalDAV
              </button>
            </div>
            {/* Common field */}
            <Input placeholder="名称（如：企业微信日历）" value={newName} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewName(e.target.value)} />
            {newSourceType === "ical" ? (
              <Input placeholder="iCal 订阅链接（如：webcal://... 改为 https://...）" value={newUrl} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewUrl(e.target.value)} />
            ) : (
              <>
                <Input placeholder="服务器地址（默认 https://caldav.wecom.work）" value={newUrl} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewUrl(e.target.value)} />
                <Input placeholder="CalDAV 用户名" value={newCalUser} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewCalUser(e.target.value)} />
                <Input placeholder="CalDAV 密码" value={newCalPass} onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewCalPass(e.target.value)} />
                <p className="text-[11px] text-[var(--text-tertiary)] leading-relaxed">
                  💡 获取方式：企业微信 PC 端 → 头像 → 设置 → 日程 → 同步至其他日历 → 复制用户名和密码
                </p>
              </>
            )}
            <Button size="sm" onClick={addSource}>添加</Button>
          </div>
        </div>
      </div>
      <div className="flex justify-end mt-6">
        <Button onClick={onClose}>完成</Button>
      </div>
    </Modal>
  );
}
