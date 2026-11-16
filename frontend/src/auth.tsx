import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router-dom";
import { useApi, api, queryClient } from "./api";
import type { User } from "./types";
interface Auth {
  user: User | undefined;
  loading: boolean;
  error: Error | null;
  login: (phone: string, password: string) => Promise<User>;
  logout: () => void;
  expired: boolean;
}
const Context = createContext<Auth>(null!);
export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState(sessionStorage.getItem("kuku.token"));
  const [expired, setExpired] = useState(false);
  const navigate = useNavigate();
  const me = useApi<User>("/users/me", !!token);
  const logout = () => {
    sessionStorage.removeItem("kuku.token");
    sessionStorage.removeItem("kuku.user");
    sessionStorage.removeItem("kuku.cart");
    sessionStorage.removeItem("kuku.checkout");
    window.dispatchEvent(new Event("kuku.cart-clear"));
    queryClient.clear();
    setToken(null);
    navigate("/login");
  };
  useEffect(() => {
    const handle = () => {
      logout();
      setExpired(true);
    };
    window.addEventListener("kuku.session-expired", handle);
    return () => window.removeEventListener("kuku.session-expired", handle);
  }, []);
  const login = async (phone: string, password: string) => {
    const result = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: { phone, password },
      anonymous: true,
    });
    queryClient.clear();
    sessionStorage.setItem("kuku.token", result.access_token);
    const user = await api<User>("/users/me");
    sessionStorage.setItem("kuku.user", String(user.id));
    queryClient.setQueryData(["/users/me"], user);
    setToken(result.access_token);
    setExpired(false);
    return user;
  };
  return (
    <Context.Provider
      value={{
        user: token ? me.data : undefined,
        loading: !!token && me.isPending,
        error: me.error,
        login,
        logout,
        expired,
      }}
    >
      {children}
    </Context.Provider>
  );
}
export const useAuth = () => useContext(Context);
