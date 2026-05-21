import { api } from "./client";

export interface TokenResponse {
  access_token: string;
}

export interface UserResponse {
  id: number;
  username: string;
  role: string;
}

export async function login(username: string, password: string): Promise<TokenResponse> {
  return api.post<TokenResponse>("/auth/login", { username, password });
}

export async function register(username: string, password: string): Promise<UserResponse> {
  return api.post<UserResponse>("/auth/register", { username, password });
}
