const API_BASE = "/api";

export class ApiError extends Error {
  status: number;
  data: any;
  constructor(message: string, status: number, data: any) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

class ApiClient {
  private token: string | null = null;

  constructor() {
    this.token = localStorage.getItem("crab_token");
  }

  setToken(token: string) {
    this.token = token;
    localStorage.setItem("crab_token", token);
  }

  clearToken() {
    this.token = null;
    localStorage.removeItem("crab_token");
  }

  getToken(): string | null {
    return this.token;
  }

  private async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const isFormData = options.body instanceof FormData;
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };
    if (!isFormData) {
      headers["Content-Type"] = "application/json";
    }
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    if (res.status === 401) {
      this.clearToken();
      window.location.reload();
      throw new Error("Unauthorized");
    }
    if (res.status === 204) return undefined as T;
    const data = await res.json();
    if (!res.ok) {
      const detail = data.detail || `HTTP ${res.status}`;
      throw new ApiError(typeof detail === "string" ? detail : JSON.stringify(detail), res.status, data);
    }
    return data;
  }

  get<T>(path: string, params?: Record<string, string>, signal?: AbortSignal) {
    const qs = params ? `?${new URLSearchParams(params).toString()}` : "";
    return this.request<T>(`${path}${qs}`, { signal });
  }

  post<T>(path: string, body: unknown) {
    if (body instanceof FormData) {
      return this.request<T>(path, { method: "POST", body });
    }
    return this.request<T>(path, { method: "POST", body: JSON.stringify(body) });
  }

  patch<T>(path: string, body: unknown) {
    return this.request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
  }

  put<T>(path: string, body: unknown) {
    return this.request<T>(path, { method: "PUT", body: JSON.stringify(body) });
  }

  del<T>(path: string, body?: unknown) {
    return this.request<T>(path, {
      method: "DELETE",
      body: body ? JSON.stringify(body) : undefined,
    });
  }
}

export const api = new ApiClient();