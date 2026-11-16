import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { Link, useParams } from "react-router-dom";
import { Leaf, Package, ClipboardList, ArrowUpRight, Plus } from "lucide-react";
import { useApi, usePages, send, newKey } from "./api";
import { useAuth } from "./auth";
import { money, quantity, date, label, manager, today } from "./utils";
import type {
  Business,
  Product,
  Order,
  Movement,
  Summary,
  Notification,
  User,
} from "./types";
import {
  Action,
  Alert,
  Badge,
  DataTable,
  Heading,
  Panel,
  SmartForm,
  State,
  Stat,
  type Field,
} from "./ui";
const BusinessContext = createContext<{
  id: number | undefined;
  businesses: Business[];
  loading: boolean;
  error: Error | null;
  select: (id: number) => void;
}>(null!);
export function BusinessProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const result = useApi<Business[]>(
    "/businesses/managed/list",
    manager(user?.role),
  );
  const [selected, setSelected] = useState<number>();
  const id = result.data?.some((b) => b.id === selected)
    ? selected
    : result.data?.[0]?.id;
  useEffect(() => setSelected(undefined), [user?.id]);
  return (
    <BusinessContext.Provider
      value={{
        id,
        businesses: result.data || [],
        loading: manager(user?.role) && result.isPending,
        error: result.error,
        select: setSelected,
      }}
    >
      {children}
    </BusinessContext.Provider>
  );
}
export const useBusiness = () => useContext(BusinessContext);
export function BusinessSelect() {
  const b = useBusiness();
  return (
    <div className="business-select">
      <label htmlFor="active-business">Active farm</label>
      <select
        id="active-business"
        value={b.id || ""}
        onChange={(e) => b.select(Number(e.target.value))}
      >
        {b.businesses.map((x) => (
          <option key={x.id} value={x.id}>
            {x.name}
          </option>
        ))}
      </select>
      {b.error && <Alert>{b.error.message}</Alert>}
      {!b.loading && !b.businesses.length && (
        <Alert tone="info">
          No farm assigned. Ask an administrator to grant business access.
        </Alert>
      )}
    </div>
  );
}
export function Dashboard() {
  const { user } = useAuth();
  const b = useBusiness();
  const orders = usePages<Order>("/orders");
  const products = usePages<Product>("/products");
  const summary = useApi<Summary>(
    `/businesses/${b.id}/summary?start=${today()}&end=${today()}`,
    !!b.id,
  );
  const ownProducts =
    products.data?.filter((p) => p.business_id === b.id) || [];
  const ownOrders = orders.data?.filter((o) => o.business_id === b.id) || [];
  return (
    <>
      <Heading
        eyebrow="YOUR FARM AT A GLANCE"
        title="A good day to grow."
        description="Keep the farm healthy, the stock ready, and every order on track."
        action={<span className="date-chip">{date(today())} · EAT</span>}
      />
      <BusinessSelect />
      <State
        loading={orders.isPending || products.isPending || b.loading}
        error={orders.error || products.error || b.error}
      >
        <div className="stats-grid">
          <Stat
            title="Active orders"
            value={
              ownOrders.filter(
                (o) =>
                  !["completed", "cancelled", "expired"].includes(o.status),
              ).length
            }
            detail="Reserved or in fulfilment"
          />
          <Stat
            title="Cash received today"
            value={summary.data ? money(summary.data.cash_received) : "—"}
            detail="Recorded cash only · KES"
          />
          <Stat
            title="Products on sale"
            value={ownProducts.length}
            detail="Across your selling units"
          />
          <Stat
            title="Eggs recorded today"
            value={summary.data?.eggs ?? "—"}
            detail="Production, before stock transfers"
          />
        </div>
        {summary.error && <Alert>{summary.error.message}</Alert>}
        <div className="dashboard-banner">
          <div>
            <span className="eyebrow">A LITTLE CARE, EVERY DAY</span>
            <h2>
              Healthy flocks.
              <br />A thriving farm.
            </h2>
            <p>Log today’s production and keep your farm story complete.</p>
            <Link className="button light" to="/farm">
              Open farm records <ArrowUpRight size={17} />
            </Link>
          </div>
          <Leaf size={120} strokeWidth={1} />
        </div>
        <div className="section-heading">
          <h2>Recent orders</h2>
          <Link className="text-link" to="/orders">
            View all orders <ArrowUpRight size={16} />
          </Link>
        </div>
        <Panel>
          <DataTable
            headers={["Order", "Placed", "Total", "Status", "Payment"]}
            rows={ownOrders.slice(0, 6).map((o) => [
              <Link className="order-reference" to={`/orders/${o.id}`}>
                {o.reference}
              </Link>,
              date(o.created_at),
              money(o.total),
              <Badge value={o.status} />,
              <Badge value={o.payment_status} />,
            ])}
          />
        </Panel>
        <div className="quick-links">
          <Link to="/manage/products">
            <Package />
            <strong>Manage your produce</strong>
            <span>Catalogue, prices & stock</span>
            <ArrowUpRight />
          </Link>
          <Link to="/farm">
            <Leaf />
            <strong>Check your flocks</strong>
            <span>Daily care & production</span>
            <ArrowUpRight />
          </Link>
          <Link to="/summary">
            <ClipboardList />
            <strong>See the bigger picture</strong>
            <span>Sales, costs & production</span>
            <ArrowUpRight />
          </Link>
        </div>
        <p className="muted">
          Signed in as {label(user?.role || "")}. Dashboard figures come from
          your selected farm’s records.
        </p>
      </State>
    </>
  );
}
export const productFields = (p?: Product): Field[] => [
  {
    name: "name",
    label: "Product name",
    default: p?.name,
    validate: (v) =>
      v.length > 120 ? "Use at most 120 characters." : undefined,
  },
  {
    name: "category",
    label: "Category",
    default: p?.category,
    options: ["eggs", "live_broilers", "dressed_chicken", "spent_layers"].map(
      (value) => ({ value, label: label(value) }),
    ),
  },
  {
    name: "unit",
    label: "Selling unit",
    default: p?.unit,
    options: ["bird", "kilogram", "egg", "tray"].map((value) => ({
      value,
      label: label(value),
    })),
    hint: "Egg products use egg/tray. Other products use bird/kilogram.",
  },
  {
    name: "price",
    label: "Unit price (KES)",
    type: "number",
    min: 0.01,
    step: "0.01",
    default: p?.price,
  },
  {
    name: "description",
    label: "Description",
    type: "textarea",
    required: false,
    default: p?.description,
    validate: (v) =>
      v.length > 2000 ? "Use at most 2,000 characters." : undefined,
  },
];
export function ManageProducts() {
  const b = useBusiness();
  const products = usePages<Product>("/products");
  const [create, setCreate] = useState(false);
  const rows = products.data?.filter((p) => p.business_id === b.id) || [];
  return (
    <>
      <Heading
        eyebrow="YOUR MARKETPLACE"
        title="Produce & inventory"
        description="Keep your catalogue fresh and your stock accurate. Reserved stock is already committed to orders."
        action={
          <button
            className="button"
            onClick={() => setCreate(!create)}
            disabled={!b.id}
          >
            <Plus size={17} />
            {create ? "Close form" : "Add product"}
          </button>
        }
      />
      <BusinessSelect />
      {create && b.id && (
        <Panel title="Create product">
          <SmartForm
            key={b.id}
            fields={productFields()}
            submit="Create product"
            validate={(v) =>
              (v.category === "eggs") !== ["egg", "tray"].includes(v.unit)
                ? {
                    field: "unit",
                    message:
                      "Choose a selling unit that matches the product category.",
                  }
                : undefined
            }
            onSubmit={(v) => send("/products", { ...v, business_id: b.id })}
          />
        </Panel>
      )}
      <State
        loading={products.isPending || b.loading}
        error={products.error || b.error}
      >
        <Panel>
          <DataTable
            headers={[
              "Product",
              "Selling unit",
              "Unit price",
              "On hand",
              "Reserved",
              "Available",
              "",
            ]}
            rows={rows.map((p) => [
              <Link className="order-reference" to={`/manage/products/${p.id}`}>
                {p.name}
              </Link>,
              label(p.unit),
              money(p.price),
              quantity(p.stock),
              quantity(p.reserved),
              quantity(p.available),
              <Link
                to={`/manage/products/${p.id}`}
                className="button secondary"
              >
                Manage
              </Link>,
            ])}
          />
        </Panel>
      </State>
    </>
  );
}
export function ManageProduct() {
  const { id } = useParams();
  const b = useBusiness();
  const p = useApi<Product>(`/products/${id}`);
  const movements = useApi<Movement[]>(`/products/${id}/movements`);
  const [mode, setMode] = useState("stock");
  const [source] = useState(newKey());
  return (
    <>
      <Link to="/manage/products" className="back-link">
        ← Produce & inventory
      </Link>
      <State loading={p.isPending || b.loading} error={p.error || b.error}>
        {p.data &&
          (!b.businesses.some((x) => x.id === p.data!.business_id) ? (
            <Alert>You do not have access to this farm’s inventory.</Alert>
          ) : (
            <>
              <Heading
                eyebrow="CATALOGUE & STOCK"
                title={p.data.name}
                description="Product changes apply to new orders. Existing order items retain their original price and description."
              />
              <div className="stats-grid three">
                <Stat
                  title="On hand"
                  value={`${quantity(p.data.stock)} ${p.data.unit}`}
                />
                <Stat title="Reserved" value={quantity(p.data.reserved)} />
                <Stat
                  title="Available to sell"
                  value={quantity(p.data.available)}
                />
              </div>
              <div className="tabs">
                <button
                  className={mode === "stock" ? "selected" : ""}
                  onClick={() => setMode("stock")}
                >
                  Receive stock
                </button>
                <button
                  className={mode === "adjust" ? "selected" : ""}
                  onClick={() => setMode("adjust")}
                >
                  Stock adjustment
                </button>
                <button
                  className={mode === "edit" ? "selected" : ""}
                  onClick={() => setMode("edit")}
                >
                  Edit product
                </button>
              </div>
              <Panel
                title={
                  mode === "edit"
                    ? "Edit product"
                    : mode === "adjust"
                      ? "Adjust inventory"
                      : "Receive purchased / opening stock"
                }
              >
                {mode === "edit" ? (
                  <SmartForm
                    key={`edit-${p.data.id}`}
                    fields={productFields(p.data)}
                    submit="Save product"
                    onSubmit={(v) =>
                      send(
                        `/products/${id}`,
                        { ...v, business_id: p.data!.business_id },
                        "PATCH",
                      )
                    }
                  />
                ) : (
                  <>
                    <p className="muted">
                      Use farm production transfers for eggs or birds produced
                      on your farm.{" "}
                      {mode === "adjust"
                        ? "Negative quantities remove unreserved stock. Use a unique reference that explains the adjustment."
                        : "Reuse the same reference if a request needs retrying."}
                    </p>
                    <SmartForm
                      key={mode}
                      fields={[
                        {
                          name: "quantity",
                          label:
                            mode === "adjust"
                              ? "Adjustment quantity"
                              : "Quantity to add",
                          type: "number",
                          step: p.data.unit === "kilogram" ? "0.001" : "1",
                          ...(mode === "stock"
                            ? { min: p.data.unit === "kilogram" ? 0.001 : 1 }
                            : {}),
                          validate: (v) =>
                            Number(v) === 0
                              ? "Enter a nonzero quantity."
                              : undefined,
                        },
                        {
                          name: "source",
                          label: "Stock reference / reason",
                          default: `${mode}-${source}`,
                        },
                      ]}
                      submit={
                        mode === "adjust" ? "Apply adjustment" : "Add stock"
                      }
                      onSubmit={async (v) => {
                        if (
                          mode === "adjust" &&
                          Number(v.quantity) < 0 &&
                          !window.confirm(
                            "Remove this quantity from saleable stock?",
                          )
                        )
                          throw new Error(
                            "Adjustment cancelled. No stock changed.",
                          );
                        return send(
                          `/products/${id}/${mode === "adjust" ? "adjustments" : "stock"}`,
                          v,
                        );
                      }}
                    />
                  </>
                )}
              </Panel>
              <Panel title="Inventory movements">
                <State loading={movements.isPending} error={movements.error}>
                  <DataTable
                    headers={[
                      "When",
                      "Movement",
                      "Quantity",
                      "Source",
                      "Order",
                    ]}
                    rows={(movements.data || []).map((m) => [
                      date(m.created_at),
                      label(m.kind),
                      quantity(m.quantity),
                      m.source,
                      m.order_id ? (
                        <Link to={`/orders/${m.order_id}`}>#{m.order_id}</Link>
                      ) : (
                        "—"
                      ),
                    ])}
                  />
                </State>
              </Panel>
            </>
          ))}
      </State>
    </>
  );
}
export function Admin() {
  const b = useBusiness();
  const users = useApi<User[]>("/admin/users");
  const notes = useApi<Notification[]>("/admin/notifications");
  return (
    <>
      <Heading
        eyebrow="ADMINISTRATION"
        title="People & notifications"
        description="Privileged accounts and farm access are managed here. Notification submissions are not handset delivery confirmations."
      />
      <div className="detail-grid">
        <Panel title="Create privileged account">
          <SmartForm
            fields={[
              { name: "phone", label: "Kenyan phone", type: "tel" },
              {
                name: "password",
                label: "Initial password",
                type: "password",
                hint: "At least 12 characters. Share securely.",
              },
              {
                name: "role",
                label: "Role",
                options: ["seller", "staff", "rider", "admin"].map((value) => ({
                  value,
                  label: label(value),
                })),
              },
            ]}
            submit="Create account"
            onSubmit={(v) => send("/admin/users", v)}
          />
        </Panel>
        <Panel title="Grant farm access">
          <BusinessSelect />
          {b.id && (
            <SmartForm
              key={b.id}
              fields={[
                {
                  name: "user_id",
                  label: "Seller / staff member",
                  options: (users.data || [])
                    .filter((u) => ["seller", "staff"].includes(u.role))
                    .map((u) => ({
                      value: String(u.id),
                      label: `${u.phone} · ${u.role}`,
                    })),
                },
              ]}
              submit="Grant farm access"
              onSubmit={(v) =>
                send(`/businesses/${b.id}/members`, {
                  user_id: Number(v.user_id),
                })
              }
            />
          )}
        </Panel>
      </div>
      <Panel title="Accounts">
        <State loading={users.isPending} error={users.error}>
          <DataTable
            headers={["User ID", "Phone", "Role"]}
            rows={(users.data || []).map((u) => [
              u.id,
              u.phone,
              <Badge value={u.role} />,
            ])}
          />
        </State>
      </Panel>
      <Panel title="SMS notification submissions">
        <State loading={notes.isPending} error={notes.error}>
          <DataTable
            headers={["Event", "Status", "Attempts", "Next scheduled attempt"]}
            rows={(notes.data || []).map((n) => [
              n.event_key,
              <Badge value={n.status} />,
              n.attempts,
              n.status === "pending" ? date(n.next_attempt) : "—",
            ])}
          />
        </State>
        <p className="muted">
          Dry-run means no SMS was sent. Accepted means provider submission
          only; handset delivery receipts are not implemented.
        </p>
      </Panel>
    </>
  );
}
