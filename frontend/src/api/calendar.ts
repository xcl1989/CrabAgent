import { api } from "./client";

export interface CalendarEvent {
  id: number | string;
  title: string;
  description?: string;
  start_time: string;
  end_time?: string | null;
  all_day: boolean;
  type: string; // manual | agent | external | task
  source?: string;
  linked_task_id?: number | null;
  project?: string;
  location?: string;
  color?: string;
  reminder_minutes?: number;
  priority?: string;
  status?: string;
}

export interface TodayOverview {
  date: string;
  events: CalendarEvent[];
  timed_events: number;
  all_day_events: number;
  due_tasks: CalendarEvent[];
  free_slots: { start: string; end: string; duration_min: number }[];
  summary: string;
}

export interface IcalSource {
  id: number;
  name: string;
  url: string;
  source_type?: string; // "ical" | "caldav"
  enabled: boolean;
  last_sync_at?: string | null;
  last_sync_status?: string;
  sync_event_count?: number;
  last_error?: string;
}

export interface CalendarSettings {
  morning_brief_enabled: boolean;
  morning_brief_time: string;
  morning_brief_channel: string;
  event_reminder_enabled: boolean;
}

export const calendarApi = {
  listEvents: (start?: string, end?: string) =>
    api.get<CalendarEvent[]>("/calendar/events", {
      ...(start ? { start } : {}),
      ...(end ? { end } : {}),
    }),

  createEvent: (data: {
    title: string;
    start_time: string;
    end_time?: string;
    all_day?: boolean;
    description?: string;
    location?: string;
    project?: string;
    reminder_minutes?: number;
  }) => api.post<CalendarEvent>("/calendar/events", data),

  updateEvent: (id: number, data: Partial<CalendarEvent>) =>
    api.put<CalendarEvent>(`/calendar/events/${id}`, data),

  deleteEvent: (id: number) => api.del(`/calendar/events/${id}`),

  getToday: () => api.get<TodayOverview>("/calendar/today"),

  // iCal sources
  listIcalSources: () => api.get<IcalSource[]>("/calendar/ical-sources"),
  createIcalSource: (data: {
    name: string;
    url: string;
    source_type?: string;
    caldav_username?: string;
    caldav_password?: string;
  }) => api.post<IcalSource>("/calendar/ical-sources", data),
  deleteIcalSource: (id: number) => api.del(`/calendar/ical-sources/${id}`),
  syncIcalSource: (id: number) =>
    api.post<{ ok: boolean; synced: number }>(`/calendar/ical-sources/${id}/sync`, {}),

  // Settings
  getSettings: () => api.get<CalendarSettings>("/calendar/settings"),
  updateSettings: (data: Partial<CalendarSettings>) =>
    api.put<CalendarSettings>("/calendar/settings", data),
};
