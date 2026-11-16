import { QueryClient, useQuery } from "@tanstack/react-query";
export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL || "http://localhost:8001"
).replace(/\/$/, "");
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 15_000, retry: 1, refetchOnWindowFocus: true },
    mutations: { retry: false },
  },
});
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public fields: Record<string, string> = {},
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    key?: string;
    signal?: AbortSignal;
    anonymous?: boolean;
  } = {},
): Promise<T> {
  const token = options.anonymous ? null : sessionStorage.getItem("kuku.token");
  let response: Response;
  try {
    response = await fetch(API_BASE + path, {
      method: options.method || "GET",
      signal: options.signal,
      headers: {
        ...(options.body !== undefined
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.key ? { "Idempotency-Key": options.key } : {}),
      },
      body:
        options.body !== undefined ? JSON.stringify(options.body) : undefined,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(
      0,
      "Cannot reach the farm server. Your input is saved. Check your connection before retrying.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && token)
      window.dispatchEvent(new Event("kuku.session-expired"));
    const fields: Record<string, string> = {};
    if (Array.isArray(data.detail))
      for (const e of data.detail) {
        const field = e.loc?.filter((x: unknown) => x !== "body").join(".");
        if (field) fields[field] = e.msg;
      }
    const message =
      typeof data.detail === "string"
        ? data.detail
        : response.status === 403
          ? "You do not have permission to perform this action."
          : Object.values(fields).join(" · ") ||
            `Request failed (${response.status}). Please try again.`;
    throw new ApiError(response.status, message, fields);
  }
  return data as T;
}
export const send = <T>(path: string, body: unknown, method = "POST") =>
  api<T>(path, { body, method });
export function useApi<T>(path: string, enabled = true) {
  return useQuery<T, ApiError>({
    queryKey: [path],
    queryFn: ({ signal }) => api<T>(path, { signal }),
    enabled,
  });
}
export async function allPages<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T[]> {
  const result: T[] = [];
  for (let offset = 0; ; offset += 100) {
    const chunk = await api<T[]>(
      `${path}${path.includes("?") ? "&" : "?"}limit=100&offset=${offset}`,
      { signal },
    );
    result.push(...chunk);
    if (chunk.length < 100) return result;
  }
}
export function usePages<T>(path: string, enabled = true) {
  return useQuery<T[], ApiError>({
    queryKey: [path],
    queryFn: ({ signal }) => allPages<T>(path, signal),
    enabled,
  });
}
export const newKey = () => crypto.randomUUID();
// Save the exact request across network failures and page reloads. Never auto-retry writes.
export async function postOnce<T>(scope: string, path: string, body: unknown) {
  const slot = `kuku.request.${scope}.${sessionStorage.getItem("kuku.user") || "guest"}`;
  const serialized = JSON.stringify(body);
  const saved = sessionStorage.getItem(slot);
  const pending = saved
    ? JSON.parse(saved)
    : { key: newKey(), body: serialized };
  if (pending.body !== serialized)
    throw new ApiError(
      0,
      "A previous submission has an unknown outcome. Retry its original details or check your order history before changing them.",
    );
  sessionStorage.setItem(slot, JSON.stringify(pending));
  try {
    const result = await api<T>(path, {
      method: "POST",
      body,
      key: pending.key,
    });
    sessionStorage.removeItem(slot);
    return result;
  } catch (e) {
    if (
      e instanceof ApiError &&
      e.status >= 400 &&
      e.status < 500 &&
      e.status !== 408 &&
      e.status !== 429
    )
      sessionStorage.removeItem(slot);
    throw e;
  }
}

export function pendingBody(scope: string): unknown | undefined {
  const slot = `kuku.request.${scope}.${sessionStorage.getItem("kuku.user") || "guest"}`;
  try {
    const value = sessionStorage.getItem(slot);
    return value ? JSON.parse(JSON.parse(value).body) : undefined;
  } catch {
    return undefined;
  }
}
