import { useState } from "react";
import {
  Link,
  NavLink,
  Navigate,
  Outlet,
  Route,
  Routes,
  useNavigate,
  useLocation,
} from "react-router-dom";
import {
  Bird,
  LayoutDashboard,
  ShoppingBasket,
  ClipboardList,
  Truck,
  Leaf,
  ReceiptText,
  ChartNoAxesCombined,
  Users,
  Package,
  LogOut,
  Menu,
  X,
  ArrowUpRight,
} from "lucide-react";
import { useAuth } from "./auth";
import { useCart, Catalogue, ProductDetail, Checkout } from "./market";
import { Dashboard, ManageProducts, ManageProduct, Admin } from "./workspace";
import { Flocks, FlockDetail, Expenses, Summaries } from "./farm";
import { Orders, OrderDetail } from "./orders";
import { api } from "./api";
import { manager, label, today, date } from "./utils";
import { Alert, SmartForm, State } from "./ui";
import type { Role } from "./types";
export function Protected({ roles }: { roles?: Role[] }) {
  const { user, loading, error } = useAuth();
  if (loading) return <State loading>{null}</State>;
  if (!user)
    return error ? (
      <Alert>{error.message}</Alert>
    ) : (
      <Navigate to="/login" replace />
    );
  if (roles && !roles.includes(user.role))
    return (
      <>
        <h1>Access restricted</h1>
        <Alert>
          This page is not available for your role. The server also checks
          permissions on every action.
        </Alert>
        <Link to="/">Go to your home</Link>
      </>
    );
  return <Outlet />;
}
export function Layout() {
  const { user, logout, loading } = useAuth();
  const cart = useCart();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const links = [
    {
      to: "/catalogue",
      label: "Marketplace",
      icon: ShoppingBasket,
      show: true,
    },
    {
      to: "/dashboard",
      label: "Overview",
      icon: LayoutDashboard,
      show: manager(user?.role),
    },
    {
      to: "/manage/products",
      label: "Produce & inventory",
      icon: Package,
      show: manager(user?.role),
    },
    {
      to: "/orders",
      label: "Orders",
      icon: ClipboardList,
      show: !!user && user.role !== "rider",
    },
    {
      to: "/deliveries",
      label: "My deliveries",
      icon: Truck,
      show: user?.role === "rider",
    },
    {
      to: "/farm",
      label: "Flocks & production",
      icon: Leaf,
      show: manager(user?.role),
    },
    {
      to: "/expenses",
      label: "Expenses",
      icon: ReceiptText,
      show: manager(user?.role),
    },
    {
      to: "/summary",
      label: "Reports",
      icon: ChartNoAxesCombined,
      show: manager(user?.role),
    },
    {
      to: "/admin",
      label: "People & SMS",
      icon: Users,
      show: user?.role === "admin",
    },
  ].filter((l) => l.show);
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <Link className="brand" to="/">
          <div className="brand-mark">
            <Bird size={27} />
          </div>
          <div>
            Kuku Farm<span>GROW. CONNECT. THRIVE.</span>
          </div>
        </Link>
        <button
          className="mobile-close icon-button"
          onClick={() => setOpen(false)}
          aria-label="Close navigation"
        >
          <X />
        </button>
        <div className="nav-label">YOUR WORKSPACE</div>
        <nav aria-label="Main navigation">
          {links.map(({ icon: Icon, ...l }) => (
            <NavLink key={l.to} to={l.to} onClick={() => setOpen(false)}>
              <Icon size={19} />
              {l.label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="farm-note">
            <Leaf size={21} />
            <strong>Rooted in good farming.</strong>
            <p>A little care, every day.</p>
          </div>
          {user ? (
            <div className="profile">
              <span className="avatar">
                {user.role.slice(0, 1).toUpperCase()}
              </span>
              <div>
                <strong>{label(user.role)}</strong>
                <small>{user.phone}</small>
              </div>
              <button
                aria-label="Log out"
                className="icon-button"
                onClick={() => {
                  logout();
                  setOpen(false);
                }}
              >
                <LogOut size={18} />
              </button>
            </div>
          ) : (
            <Link className="button full" to="/login">
              Sign in <ArrowUpRight size={16} />
            </Link>
          )}
        </div>
      </aside>
      {open && (
        <button
          aria-label="Close menu backdrop"
          className="menu-backdrop"
          onClick={() => setOpen(false)}
        />
      )}
      <div className="main-wrap">
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              aria-expanded={open}
              onClick={() => setOpen(true)}
            >
              <Menu />
            </button>
            <span>Kuku Farm</span>
            <span>/</span>
            <strong>
              {links.find((l) => location.pathname.startsWith(l.to))?.label ||
                "Welcome"}
            </strong>
          </div>
          <div className="top-actions">
            <span className="live-dot" />{" "}
            <span className="desktop-label">Farm & marketplace</span>
            {(!user || user.role === "buyer") && (
              <Link to="/cart" className="basket-link">
                <ShoppingBasket size={19} />
                <span>Basket</span>
                <b>{cart.items.length}</b>
              </Link>
            )}
          </div>
        </header>
        <main id="main" tabIndex={-1}>
          {loading ? <State loading>{null}</State> : <Outlet />}
          <footer>
            Made for everyday farming.
            <span>Kuku Farm · Kenya · {date(today())}</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
function Home() {
  const { user } = useAuth();
  return (
    <Navigate
      to={
        manager(user?.role)
          ? "/dashboard"
          : user?.role === "rider"
            ? "/deliveries"
            : "/catalogue"
      }
      replace
    />
  );
}
function AuthPage({ register = false }: { register?: boolean }) {
  const auth = useAuth();
  const navigate = useNavigate();
  if (auth.user) return <Home />;
  return (
    <div className="auth-page">
      <div className="auth-illustration">
        <Bird size={70} strokeWidth={1} />
        <span className="eyebrow">WELCOME TO KUKU FARM</span>
        <h1>
          Good things
          <br />
          grow together.
        </h1>
        <p>Fresh produce, healthy flocks, and a community that keeps moving.</p>
      </div>
      <section className="auth-form">
        <span className="eyebrow">
          {register ? "JOIN THE FARM COMMUNITY" : "YOUR FARM, WITHIN REACH"}
        </span>
        <h1>{register ? "Create your buyer account" : "Welcome back."}</h1>
        <p>
          {register
            ? "Shop directly from farms in Kenya. Seller and staff accounts are created by an administrator."
            : "Sign in to pick up where you left off."}
        </p>
        {auth.expired && (
          <Alert>Your session expired. Sign in again to continue.</Alert>
        )}
        <SmartForm
          key={register ? "register" : "login"}
          fields={[
            {
              name: "phone",
              label: "Kenyan mobile number",
              type: "tel",
              hint: "0712345678 or +254712345678",
            },
            {
              name: "password",
              label: "Password",
              type: "password",
              hint: register ? "At least 12 characters." : undefined,
              validate: (v) =>
                register && v.length < 12
                  ? "Use at least 12 characters."
                  : undefined,
            },
          ]}
          submit={register ? "Create buyer account" : "Sign in"}
          onSubmit={async (v) => {
            if (register)
              await api("/auth/register", {
                method: "POST",
                body: v,
                anonymous: true,
              });
            const user = await auth.login(v.phone, v.password);
            navigate(
              manager(user.role)
                ? "/dashboard"
                : user.role === "rider"
                  ? "/deliveries"
                  : "/catalogue",
            );
          }}
        />
        {register ? (
          <p>
            Already have an account? <Link to="/login">Sign in</Link>
          </p>
        ) : (
          <p>
            New here? <Link to="/register">Create a buyer account</Link>
          </p>
        )}
      </section>
    </div>
  );
}
export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Home />} />
        <Route path="catalogue" element={<Catalogue />} />
        <Route path="products/:id" element={<ProductDetail />} />
        <Route path="cart" element={<Checkout />} />
        <Route path="login" element={<AuthPage />} />
        <Route path="register" element={<AuthPage register />} />
        <Route element={<Protected />}>
          <Route path="orders" element={<Orders />} />
          <Route path="orders/:id" element={<OrderDetail />} />
        </Route>
        <Route element={<Protected roles={["rider"]} />}>
          <Route path="deliveries" element={<Orders deliveries />} />
        </Route>
        <Route element={<Protected roles={["admin", "seller", "staff"]} />}>
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="manage/products" element={<ManageProducts />} />
          <Route path="manage/products/:id" element={<ManageProduct />} />
          <Route path="farm" element={<Flocks />} />
          <Route path="farm/:id" element={<FlockDetail />} />
          <Route path="expenses" element={<Expenses />} />
          <Route path="summary" element={<Summaries />} />
        </Route>
        <Route element={<Protected roles={["admin"]} />}>
          <Route path="admin" element={<Admin />} />
        </Route>
        <Route
          path="*"
          element={
            <>
              <h1>Page not found</h1>
              <Link to="/">Return home</Link>
            </>
          }
        />
      </Route>
    </Routes>
  );
}
