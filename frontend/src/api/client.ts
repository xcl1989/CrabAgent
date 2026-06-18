const API_BASE = "/api";

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
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string>),
    };
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
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  get<T>(path: string, params?: Record<string, string>) {
    if (params) {
      const qs = new URLSearchParams(params).toString();
      return this.request<T>(`${path}?${qs}`);
    }
    return this.request<T>(path);
  }

  post<T>(path: string, body: unknown) {
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
