import { useState, useEffect, useCallback } from "react";
import { api } from "../api/client";

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState(!!api.getToken());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setIsAuthenticated(!!api.getToken());
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const { login: doLogin } = await import("../api/auth");
      const res = await doLogin(username, password);
      api.setToken(res.access_token);
      setIsAuthenticated(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Login failed");
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const register = useCallback(async (username: string, password: string) => {
    setLoading(true);
    setError(null);
    try {
      const { register: doRegister } = await import("../api/auth");
      await doRegister(username, password);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Register failed");
      throw e;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(() => {
    api.clearToken();
    setIsAuthenticated(false);
  }, []);

  return { isAuthenticated, loading, error, login, register, logout };
}
