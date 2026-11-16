import {
  createContext,
  useContext,
  useEffect,
  useState,
  useRef,
  type ReactNode,
} from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import Decimal from "decimal.js";
import {
  Egg,
  Bird,
  Package,
  ShoppingBag,
  ArrowRight,
  Search,
  Trash2,
  Truck,
  MapPin,
} from "lucide-react";
import {
  useApi,
  usePages,
  postOnce,
  pendingBody,
  queryClient,
  ApiError,
} from "./api";
import type { Product, Business, Config, Order } from "./types";
import { useAuth } from "./auth";
import { money, quantity, label } from "./utils";
import { Heading, State, Alert, Panel, Action } from "./ui";
interface CartItem {
  product_id: number;
  quantity: string;
}
interface CartContext {
  items: CartItem[];
  add: (p: Product, q: string) => void;
  remove: (id: number) => void;
  clear: () => void;
  change: (id: number, q: string) => void;
}
const Cart = createContext<CartContext>(null!);
export function CartProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<CartItem[]>(() => {
    try {
      return JSON.parse(sessionStorage.getItem("kuku.cart") || "[]");
    } catch {
      return [];
    }
  });
  useEffect(() => {
    sessionStorage.setItem("kuku.cart", JSON.stringify(items));
  }, [items]);
  useEffect(() => {
    const clear = () => setItems([]);
    window.addEventListener("kuku.cart-clear", clear);
    return () => window.removeEventListener("kuku.cart-clear", clear);
  }, []);
  const products = usePages<Product>("/products");
  const add = (product: Product, q: string) => {
    const known = products.data || [];
    if (
      items.some(
        (i) =>
          known.find((p) => p.id === i.product_id)?.business_id !==
          product.business_id,
      )
    )
      throw new Error(
        "Your basket contains another seller’s products. Clear it first to start a new seller order.",
      );
    const old = items.find((i) => i.product_id === product.id);
    const total = new Decimal(old?.quantity || 0).plus(q);
    if (total.gt(product.available))
      throw new Error("That quantity exceeds available stock.");
    setItems((prev) => [
      ...prev.filter((i) => i.product_id !== product.id),
      { product_id: product.id, quantity: total.toString() },
    ]);
  };
  return (
    <Cart.Provider
      value={{
        items,
        add,
        remove: (id) =>
          setItems((prev) => prev.filter((i) => i.product_id !== id)),
        clear: () => setItems([]),
        change: (id, q) =>
          setItems((prev) =>
            prev.map((i) => (i.product_id === id ? { ...i, quantity: q } : i)),
          ),
      }}
    >
      {children}
    </Cart.Provider>
  );
}
export const useCart = () => useContext(Cart);
export const ProductIcon = ({ category }: { category: string }) =>
  category === "eggs" ? (
    <Egg />
  ) : category === "dressed_chicken" ? (
    <Package />
  ) : (
    <Bird />
  );
export function Catalogue() {
  const products = usePages<Product>("/products");
  const businesses = usePages<Business>("/businesses");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("all");
  const filtered =
    products.data?.filter(
      (p) =>
        (category === "all" || p.category === category) &&
        `${p.name} ${p.description}`
          .toLowerCase()
          .includes(search.toLowerCase()),
    ) || [];
  return (
    <>
      <Heading
        eyebrow="FROM OUR FARMS"
        title="Fresh from the farm."
        description="Good food starts with good farming. Find your next farm-fresh favourite."
        action={
          <Link className="button secondary" to="/cart">
            <ShoppingBag size={17} />
            View basket
          </Link>
        }
      />
      <div className="market-banner">
        <div>
          <span className="eyebrow">RAISED WITH CARE</span>
          <h2>
            Fresh produce.
            <br />
            Straightforward shopping.
          </h2>
          <p>
            Choose your produce, place an order, and collect or have it
            delivered.
          </p>
          <a href="#products" className="text-link">
            Explore the marketplace <ArrowRight size={16} />
          </a>
        </div>
        <div className="egg-art" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </div>
      <section id="products">
        <div className="toolbar">
          <div className="tabs" aria-label="Filter products">
            {[
              ["all", "All produce"],
              ["eggs", "Eggs"],
              ["live_broilers", "Live broilers"],
              ["dressed_chicken", "Dressed chicken"],
              ["spent_layers", "Spent layers"],
            ].map(([value, text]) => (
              <button
                key={value}
                aria-pressed={value === category}
                className={value === category ? "selected" : ""}
                onClick={() => setCategory(value)}
              >
                {text}
              </button>
            ))}
          </div>
          <label className="search">
            <Search size={17} />
            <span className="sr-only">Search products</span>
            <input
              placeholder="Search produce…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
        </div>
        <State
          loading={products.isPending || businesses.isPending}
          error={products.error || businesses.error}
          empty={!filtered.length}
        >
          <div className="product-grid">
            {filtered.map((p) => (
              <Link
                className="product-card"
                key={p.id}
                to={`/products/${p.id}`}
              >
                <div className={`product-art ${p.category}`}>
                  <ProductIcon category={p.category} />
                  <span className="stock-pill">
                    {new Decimal(p.available).gt(0)
                      ? `${quantity(p.available)} ${p.unit}${p.available === "1" ? "" : "s"} available`
                      : "Out of stock"}
                  </span>
                </div>
                <div className="product-info">
                  <small>
                    {businesses.data?.find((b) => b.id === p.business_id)
                      ?.name || `Seller ${p.business_id}`}
                  </small>
                  <h2>{p.name}</h2>
                  <p>{p.description || label(p.category)}</p>
                  <div className="price-row">
                    <strong>
                      {money(p.price)} <small>/ {p.unit}</small>
                    </strong>
                    <span className="round-arrow">
                      <ArrowRight size={18} />
                    </span>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </State>
      </section>
    </>
  );
}
export function ProductDetail() {
  const { id } = useParams();
  const p = useApi<Product>(`/products/${id}`);
  const businesses = usePages<Business>("/businesses");
  const cart = useCart();
  const { user } = useAuth();
  const [q, setQ] = useState("1");
  const [error, setError] = useState("");
  const [added, setAdded] = useState(false);
  const add = () => {
    setError("");
    try {
      if (!p.data || !new Decimal(q).gt(0))
        throw new Error("Choose a positive quantity.");
      if (p.data.unit !== "kilogram" && !new Decimal(q).isInteger())
        throw new Error("This product is sold in whole units.");
      cart.add(p.data, q);
      setAdded(true);
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <>
      <Link to="/catalogue" className="back-link">
        ← All produce
      </Link>
      <State loading={p.isPending} error={p.error}>
        {p.data && (
          <div className="detail-grid">
            <div className={`product-art detail-art ${p.data.category}`}>
              <ProductIcon category={p.data.category} />
            </div>
            <Panel>
              <span className="eyebrow">
                {
                  businesses.data?.find((b) => b.id === p.data!.business_id)
                    ?.name
                }
              </span>
              <h1>{p.data.name}</h1>
              <p>{p.data.description || label(p.data.category)}</p>
              <h2>
                {money(p.data.price)} <small>per {p.data.unit}</small>
              </h2>
              <p>
                {quantity(p.data.available)} {p.data.unit}s currently available
              </p>
              <label className="field" htmlFor="quantity">
                Quantity ({p.data.unit})
                <input
                  id="quantity"
                  type="number"
                  min={p.data.unit === "kilogram" ? "0.001" : "1"}
                  step={p.data.unit === "kilogram" ? "0.001" : "1"}
                  value={q}
                  onChange={(e) => {
                    setQ(e.target.value);
                    setAdded(false);
                  }}
                />
              </label>
              {error && <Alert>{error}</Alert>}
              {added && (
                <Alert tone="success">
                  Added to your basket.{" "}
                  <Link to="/cart">Continue to checkout</Link>
                </Alert>
              )}
              {!user || user.role === "buyer" ? (
                <button
                  className="button"
                  disabled={new Decimal(p.data.available).lte(0)}
                  onClick={add}
                >
                  <ShoppingBag size={18} />
                  Add to basket
                </button>
              ) : (
                <p>Sign in with a buyer account to place orders.</p>
              )}
              <p className="muted">
                Stock is reserved when your order is placed, not when added to
                your basket.
              </p>
            </Panel>
          </div>
        )}
      </State>
    </>
  );
}
const checkoutSchema = z
  .object({
    fulfillment: z.enum(["pickup", "delivery"]),
    payment: z.enum(["cash", "mpesa"]),
    address: z.string().max(500),
  })
  .superRefine((v, c) => {
    if (v.fulfillment === "delivery" && !v.address.trim())
      c.addIssue({
        code: "custom",
        path: ["address"],
        message: "Enter a delivery address.",
      });
  });
export function Checkout() {
  const cart = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();
  const products = usePages<Product>("/products");
  const config = useApi<Config>("/marketplace/config");
  const [error, setError] = useState("");
  const form = useForm<z.infer<typeof checkoutSchema>>({
    resolver: zodResolver(checkoutSchema),
    defaultValues: {
      fulfillment: "pickup",
      address: "",
      payment: "cash",
      ...JSON.parse(sessionStorage.getItem("kuku.checkout") || "{}"),
    },
  });
  const fulfillment = form.watch("fulfillment");
  const address = form.watch("address");
  const payment = form.watch("payment");
  useEffect(() => {
    sessionStorage.setItem(
      "kuku.checkout",
      JSON.stringify({ fulfillment, address, payment }),
    );
  }, [fulfillment, address, payment]);
  const rows = cart.items.map((i) => ({
    item: i,
    product: products.data?.find((p) => p.id === i.product_id),
  }));
  const invalid = rows.some(
    ({ item: i, product: p }) =>
      !p ||
      !/^\d+(\.\d{1,3})?$/.test(i.quantity) ||
      new Decimal(i.quantity || 0).lte(0) ||
      new Decimal(i.quantity || 0).gt(p.available) ||
      (p.unit !== "kilogram" && !new Decimal(i.quantity || 0).isInteger()),
  );
  const subtotal = rows.reduce(
    (total, { item: i, product: p }) =>
      total.plus(
        p
          ? new Decimal(p.price)
              .times(/^\d+(\.\d{1,3})?$/.test(i.quantity) ? i.quantity : 0)
              .toDecimalPlaces(2)
          : 0,
      ),
    new Decimal(0),
  );
  const fee =
    fulfillment === "delivery" ? config.data?.delivery_fee || "0" : "0";
  const submitting = useRef(false);
  const finish = (order: Order) => {
    cart.clear();
    sessionStorage.removeItem("kuku.checkout");
    queryClient.invalidateQueries();
    navigate(
      `/orders/${order.id}${payment === "mpesa" ? "?payment=mpesa#mpesa-payment" : ""}`,
    );
  };
  const mutation = useMutation({
    mutationFn: async (values: z.infer<typeof checkoutSchema>) => {
      if (values.payment === "mpesa" && !config.data?.mpesa_ready)
        throw new ApiError(
          503,
          "M-Pesa sandbox requires a configured public HTTPS callback URL.",
        );
      if (invalid)
        throw new ApiError(
          422,
          "Some products or quantities are unavailable. Refresh stock and update your basket.",
        );
      return postOnce<Order>("checkout", "/orders", {
        items: cart.items,
        fulfillment: values.fulfillment,
        address: values.fulfillment === "delivery" ? values.address : "",
      });
    },
    onSuccess: finish,
    onError: (e: Error) => {
      setError(e.message);
      products.refetch();
    },
  });
  return (
    <>
      <Heading
        eyebrow="YOUR NEXT FARM-FRESH ORDER"
        title="Your basket"
        description="One farm per order. Stock and prices are checked again when you place the order."
      />
      <State
        loading={products.isPending || config.isPending}
        error={products.error || config.error}
      >
        {!rows.length ? (
          <Panel>
            <ShoppingBag size={30} />
            <h2>A little empty in here.</h2>
            <p>Add some fresh produce to get started.</p>
            <Link to="/catalogue" className="button">
              Explore produce
            </Link>
          </Panel>
        ) : (
          <div className="checkout-grid">
            <Panel title="Your produce">
              {rows.map(({ item: i, product: p }) => (
                <div className="cart-row" key={i.product_id}>
                  <div className={`mini-art ${p?.category}`}>
                    <ProductIcon category={p?.category || "eggs"} />
                  </div>
                  <div className="cart-description">
                    <Link to={`/products/${i.product_id}`}>
                      <strong>{p?.name || "Unavailable product"}</strong>
                    </Link>
                    <small>
                      {p
                        ? `${money(p.price)} / ${p.unit}`
                        : "Remove this product to continue"}
                    </small>
                    {p && (
                      <small className="block">
                        Available now: {quantity(p.available)} {p.unit}
                      </small>
                    )}
                  </div>
                  <label>
                    <span className="sr-only">Quantity for {p?.name}</span>
                    <input
                      aria-label={`Quantity for ${p?.name}`}
                      className="quantity-input"
                      type="number"
                      min="0.001"
                      step={p?.unit === "kilogram" ? "0.001" : "1"}
                      value={i.quantity}
                      onChange={(e) =>
                        cart.change(i.product_id, e.target.value)
                      }
                    />
                  </label>
                  <button
                    className="icon-button"
                    aria-label={`Remove ${p?.name}`}
                    onClick={() => cart.remove(i.product_id)}
                  >
                    <Trash2 size={18} />
                  </button>
                </div>
              ))}
              {invalid && (
                <Alert>
                  Stock or availability has changed. Update unavailable products
                  or quantities before ordering.
                </Alert>
              )}
              <button className="text-link" onClick={() => products.refetch()}>
                Refresh stock & prices
              </button>
              <Link className="back-link" to="/catalogue">
                ← Continue shopping
              </Link>
            </Panel>
            <Panel title="Order summary">
              <div className="summary-line">
                <span>Produce subtotal</span>
                <strong>{money(subtotal.toString())}</strong>
              </div>
              <form
                onSubmit={form.handleSubmit(async (v) => {
                  if (submitting.current) return;
                  submitting.current = true;
                  setError("");
                  try {
                    await mutation.mutateAsync(v);
                  } catch {
                  } finally {
                    submitting.current = false;
                  }
                })}
                noValidate
              >
                <fieldset>
                  <legend>How would you like your order?</legend>
                  <div className="fulfillment-options">
                    <label
                      className={fulfillment === "pickup" ? "selected" : ""}
                    >
                      <MapPin size={18} />
                      <input
                        type="radio"
                        value="pickup"
                        {...form.register("fulfillment")}
                      />
                      Pickup
                    </label>
                    <label
                      className={fulfillment === "delivery" ? "selected" : ""}
                    >
                      <Truck size={18} />
                      <input
                        type="radio"
                        value="delivery"
                        {...form.register("fulfillment")}
                      />
                      Delivery
                    </label>
                  </div>
                </fieldset>
                <fieldset>
                  <legend>Payment option</legend>
                  <div className="fulfillment-options payment-options">
                    <label className={payment === "cash" ? "selected" : ""}>
                      <input
                        type="radio"
                        value="cash"
                        {...form.register("payment")}
                      />
                      Cash on handover
                    </label>
                    <label className={payment === "mpesa" ? "selected" : ""}>
                      <input
                        type="radio"
                        value="mpesa"
                        {...form.register("payment")}
                        disabled={!config.data?.mpesa_ready}
                      />
                      M-Pesa STK (sandbox)
                    </label>
                  </div>
                  {!config.data?.mpesa_ready && (
                    <small>
                      M-Pesa is unavailable until the backend has a valid public
                      HTTPS callback configuration.
                    </small>
                  )}
                  {payment === "mpesa" && (
                    <p className="muted">
                      Place your order first, then confirm the phone number and
                      request the STK prompt on the next screen. No prompt is
                      sent automatically.
                    </p>
                  )}
                </fieldset>
                {fulfillment === "delivery" && (
                  <div className="field">
                    <label htmlFor="address">Delivery address</label>
                    <textarea
                      id="address"
                      {...form.register("address")}
                      aria-invalid={!!form.formState.errors.address}
                    />
                    {form.formState.errors.address && (
                      <small className="field-error">
                        {form.formState.errors.address.message}
                      </small>
                    )}
                  </div>
                )}
                <div className="summary-line">
                  <span>Delivery</span>
                  <strong>{money(fee)}</strong>
                </div>
                <div className="summary-line total">
                  <span>Total</span>
                  <strong>{money(subtotal.plus(fee).toString())}</strong>
                </div>
                <p className="muted">
                  {user
                    ? `Order updates: ${user.phone}`
                    : "Sign in as a buyer to continue."}{" "}
                  {payment === "cash"
                    ? "Cash is recorded after pickup or delivery completion."
                    : "M-Pesa sandbox can be requested as soon as your order is placed. Sandbox success is not real money."}
                </p>
                {error && (
                  <Alert>
                    {error} <Link to="/orders">Check existing orders</Link>{" "}
                    before retrying an uncertain request.
                  </Alert>
                )}
                {!!pendingBody("checkout") && (
                  <div className="recovery">
                    <Alert tone="info">
                      A saved submission may already have reserved stock.
                      Recover it using its original request instead of creating
                      another order.
                    </Alert>
                    <Action
                      run={async () =>
                        finish(
                          await postOnce<Order>(
                            "checkout",
                            "/orders",
                            pendingBody("checkout"),
                          ),
                        )
                      }
                    >
                      Recover saved submission
                    </Action>
                  </div>
                )}
                {user?.role === "buyer" ? (
                  <button
                    className="button full"
                    disabled={mutation.isPending || invalid || !config.data}
                  >
                    {mutation.isPending
                      ? "Placing order…"
                      : payment === "mpesa"
                        ? "Place order & continue to M-Pesa"
                        : "Place order"}
                    <ArrowRight size={18} />
                  </button>
                ) : (
                  <Link className="button full" to="/login">
                    Sign in to checkout
                  </Link>
                )}
              </form>
            </Panel>
          </div>
        )}
      </State>
    </>
  );
}
