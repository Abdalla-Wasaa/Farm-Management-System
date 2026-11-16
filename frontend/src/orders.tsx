import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ClipboardList, Truck, ArrowUpRight } from "lucide-react";
import {
  useApi,
  usePages,
  api,
  send,
  postOnce,
  pendingBody,
  queryClient,
} from "./api";
import { useAuth } from "./auth";
import type { Order, User, Intent, Config } from "./types";
import { money, date, label, manager, quantity } from "./utils";
import {
  Action,
  Alert,
  Badge,
  DataTable,
  Heading,
  Panel,
  SmartForm,
  State,
} from "./ui";
const activeIntents = ["queued", "submitting", "pending", "uncertain"];
export function Orders({ deliveries = false }: { deliveries?: boolean }) {
  const orders = usePages<Order>("/orders", !deliveries);
  const assigned = useApi<Order[]>("/deliveries/assigned", deliveries);
  const result = deliveries ? assigned : orders;
  const [filter, setFilter] = useState("all");
  const rows =
    result.data?.filter(
      (o) =>
        filter === "all" ||
        (filter === "active"
          ? !["completed", "cancelled", "expired"].includes(o.status)
          : o.status === filter),
    ) || [];
  return (
    <>
      <Heading
        eyebrow={deliveries ? "ON THE MOVE" : "EVERY ORDER, ACCOUNTED FOR"}
        title={deliveries ? "Your deliveries" : "Orders"}
        description={
          deliveries
            ? "Your assigned jobs, from farm pickup to the final handover."
            : "Track each order from its first reservation to a happy handover."
        }
      />
      <div className="toolbar">
        <div className="tabs">
          {["all", "active", "pending", "completed", "cancelled"].map((f) => (
            <button
              key={f}
              aria-pressed={filter === f}
              className={filter === f ? "selected" : ""}
              onClick={() => setFilter(f)}
            >
              {label(f)}
            </button>
          ))}
        </div>
        <button className="button secondary" onClick={() => result.refetch()}>
          Refresh orders
        </button>
      </div>
      <State loading={result.isPending} error={result.error}>
        <Panel>
          <DataTable
            headers={[
              "Order",
              "Placed",
              "Farm",
              "Total",
              "Order status",
              "Payment",
              "",
            ]}
            rows={rows.map((o) => [
              <Link to={`/orders/${o.id}`} className="order-reference">
                {o.reference}
              </Link>,
              date(o.created_at),
              o.business_name,
              money(o.total),
              <Badge value={o.status} />,
              <Badge value={o.payment_status} />,
              <Link
                aria-label={`View ${o.reference}`}
                className="icon-button"
                to={`/orders/${o.id}`}
              >
                <ArrowUpRight size={18} />
              </Link>,
            ])}
          />
        </Panel>
      </State>
    </>
  );
}
export function OrderDetail() {
  const { id } = useParams();
  const [search] = useSearchParams();
  const { user } = useAuth();
  const order = useApi<Order>(`/orders/${id}`);
  const config = useApi<Config>("/marketplace/config");
  const riders = useApi<User[]>(
    "/admin/users?role=rider",
    user?.role === "admin",
  );
  const [until, setUntil] = useState(() => Date.now() + 120_000);
  const intents = useQuery<Intent[]>({
    queryKey: [`/orders/${id}/payments/mpesa`],
    queryFn: ({ signal }) => api(`/orders/${id}/payments/mpesa`, { signal }),
    enabled: !!order.data,
    refetchInterval: (q) =>
      Date.now() < until &&
      q.state.data?.some((i) =>
        ["queued", "submitting", "pending"].includes(i.status),
      )
        ? 3000
        : false,
  });
  useEffect(() => {
    if (intents.data?.some((i) => i.status === "succeeded"))
      queryClient.invalidateQueries({ queryKey: [`/orders/${id}`] });
  }, [intents.data, id]);
  useEffect(() => {
    if (order.data && search.get("payment") === "mpesa") {
      document
        .getElementById("mpesa-payment")
        ?.scrollIntoView({ block: "start" });
      document.getElementById("mpesa-payment")?.focus({ preventScroll: true });
    }
  }, [order.data?.id, search]);
  const o = order.data;
  const manage = manager(user?.role);
  const rider = user?.role === "rider" && o?.rider_id === user.id;
  const buyer = user?.role === "buyer";
  const active = intents.data?.some((i) => activeIntents.includes(i.status));
  const transitions: Record<string, string> = {
    pending: "confirmed",
    confirmed: "preparing",
    preparing: "ready",
  };
  return (
    <>
      <Link
        to={user?.role === "rider" ? "/deliveries" : "/orders"}
        className="back-link"
      >
        ← {user?.role === "rider" ? "Assigned deliveries" : "All orders"}
      </Link>
      <State loading={order.isPending} error={order.error}>
        {o && (
          <>
            <Heading
              eyebrow={`${label(o.fulfillment)} ORDER`}
              title={o.reference}
              description={`Placed ${date(o.created_at)} · ${o.business_name}`}
              action={
                <button
                  className="button secondary"
                  onClick={() => {
                    order.refetch();
                    intents.refetch();
                    setUntil(Date.now() + 120_000);
                  }}
                >
                  Refresh status
                </button>
              }
            />
            <div className="status-strip">
              <div>
                <small>Order</small>
                <Badge value={o.status} />
              </div>
              <div>
                <small>Payment</small>
                <Badge value={o.payment_status} />
              </div>
              <div>
                <small>Delivery</small>
                <Badge value={o.delivery_status} />
              </div>
            </div>
            <div className="detail-grid order-grid">
              <div>
                <Panel title="Order items">
                  <DataTable
                    headers={["Produce", "Quantity", "Unit price", "Subtotal"]}
                    rows={o.items.map((i) => [
                      <>
                        <strong>{i.name}</strong>
                        <small className="block">{i.description}</small>
                      </>,
                      `${quantity(i.quantity)} ${i.unit}`,
                      money(i.price),
                      money(i.line_total),
                    ])}
                  />
                  <div className="summary-line">
                    <span>Delivery fee</span>
                    <strong>{money(o.fee)}</strong>
                  </div>
                  <div className="summary-line total">
                    <span>Total · KES</span>
                    <strong>{money(o.total)}</strong>
                  </div>
                </Panel>
                <Panel
                  title={
                    o.fulfillment === "delivery"
                      ? "Delivery & pickup details"
                      : "Pickup details"
                  }
                >
                  <div className="info-grid">
                    <div>
                      <small>Farm / pickup contact</small>
                      <strong>{o.business_name}</strong>
                      <a href={`tel:${o.seller_phone}`}>{o.seller_phone}</a>
                      <p className="muted">
                        Contact the farm to arrange the exact pickup point.
                      </p>
                    </div>
                    <div>
                      <small>Buyer contact</small>
                      <a href={`tel:${o.buyer_phone}`}>{o.buyer_phone}</a>
                      {o.fulfillment === "delivery" && (
                        <>
                          <small>Deliver to</small>
                          <strong>{o.address}</strong>
                        </>
                      )}
                    </div>
                  </div>
                  {o.rider_id && (
                    <p className="muted">Assigned rider #{o.rider_id}</p>
                  )}
                </Panel>
                <Panel title="Payment records">
                  {o.payments.length ? (
                    <DataTable
                      headers={["Method", "Amount", "Reference", "Recorded"]}
                      rows={o.payments.map((p) => [
                        p.method === "mpesa_sandbox"
                          ? "M-Pesa sandbox (simulation)"
                          : label(p.method),
                        money(p.amount),
                        p.receipt,
                        date(p.created_at),
                      ])}
                    />
                  ) : (
                    <p className="muted">
                      No payment received. Payment becomes available after
                      pickup or delivery is completed.
                    </p>
                  )}
                </Panel>
              </div>
              <div>
                <Panel title="Next steps">
                  <div className="flow-note">
                    <ClipboardList size={22} />
                    <p>
                      {o.status === "pending"
                        ? "The farm will confirm this order. Your stock is reserved."
                        : o.status === "completed"
                          ? "Handover is complete. Check payment status below."
                          : o.status === "cancelled" || o.status === "expired"
                            ? "This order is closed. Reserved stock was released."
                            : "Your order is moving through the farm’s fulfilment process."}
                    </p>
                  </div>
                  <div className="actions vertical">
                    {manage && transitions[o.status] && (
                      <Action
                        run={() =>
                          send(`/orders/${id}/status`, {
                            status: transitions[o.status],
                          })
                        }
                      >
                        Mark {label(transitions[o.status]).toLowerCase()}
                      </Action>
                    )}
                    {manage &&
                      o.status === "ready" &&
                      o.fulfillment === "pickup" && (
                        <Action
                          confirm="Confirm the buyer has collected this order? This consumes the reserved stock."
                          run={() =>
                            send(`/orders/${id}/status`, {
                              status: "completed",
                            })
                          }
                        >
                          Complete pickup
                        </Action>
                      )}
                    {rider &&
                      o.status === "ready" &&
                      o.delivery_status === "assigned" && (
                        <Action
                          confirm="Confirm you have collected this order from the farm and are starting delivery?"
                          run={() =>
                            send(`/orders/${id}/delivery`, {
                              status: "dispatched",
                            })
                          }
                        >
                          Dispatch delivery
                        </Action>
                      )}
                    {rider && o.delivery_status === "dispatched" && (
                      <Action
                        confirm="Confirm the buyer has received the order?"
                        run={() =>
                          send(`/orders/${id}/delivery`, {
                            status: "delivered",
                          })
                        }
                      >
                        Mark delivered
                      </Action>
                    )}
                    {(manage || buyer) &&
                      o.payment_status === "unpaid" &&
                      !active &&
                      intents.data &&
                      ["pending", "confirmed", "preparing", "ready"].includes(
                        o.status,
                      ) &&
                      o.delivery_status !== "dispatched" && (
                        <Action
                          danger
                          confirm="Cancel this order? Its reserved stock will be released. This cannot be undone."
                          run={() =>
                            send(`/orders/${id}/status`, {
                              status: "cancelled",
                            })
                          }
                        >
                          Cancel order
                        </Action>
                      )}
                  </div>
                </Panel>
                {user?.role === "admin" &&
                  o.fulfillment === "delivery" &&
                  ["confirmed", "preparing", "ready"].includes(o.status) &&
                  !o.rider_id && (
                    <Panel title="Assign a rider">
                      <State
                        loading={riders.isPending}
                        error={riders.error}
                        empty={!riders.data?.length}
                      >
                        <SmartForm
                          fields={[
                            {
                              name: "rider_id",
                              label: "Rider",
                              options:
                                riders.data?.map((r) => ({
                                  value: String(r.id),
                                  label: r.phone,
                                })) || [],
                            },
                          ]}
                          submit="Assign rider"
                          onSubmit={(v) =>
                            send(`/orders/${id}/rider`, {
                              rider_id: Number(v.rider_id),
                            })
                          }
                        />
                      </State>
                      {riders.data?.length === 0 && (
                        <Link to="/admin">Create a rider account</Link>
                      )}
                    </Panel>
                  )}
                {(buyer || manage || rider) && (
                  <div id="mpesa-payment" tabIndex={-1}>
                    <Panel title="M-Pesa sandbox">
                      <p className="sandbox-tag">SANDBOX · NO LIVE PAYMENT</p>
                      <p className="muted">
                        Request an STK prompt after placing your order, before
                        or after handover. A queued or accepted STK request is
                        not proof of payment. Only verified provider success
                        marks the order paid.
                      </p>
                      <State
                        loading={intents.isPending && !!o}
                        error={intents.error}
                      >
                        {intents.data?.map((i) => (
                          <div className="payment-intent" key={i.id}>
                            <strong>
                              {i.result_code === "1032"
                                ? "Cancelled by payer"
                                : label(i.status)}
                            </strong>
                            <Badge value={i.status} />
                            <small>
                              Request #{i.id} · {money(i.amount)}
                              {i.result_code
                                ? ` · Result ${i.result_code}`
                                : ""}
                            </small>
                            {i.status === "uncertain" && (
                              <Alert tone="info">
                                The outcome is uncertain. Do not pay again or
                                collect cash. Ask the farm administrator to
                                investigate this request.
                              </Alert>
                            )}
                          </div>
                        ))}
                      </State>
                      {active && (
                        <p className="muted">
                          Automatic refresh runs for up to 2 minutes while this
                          screen is open. Use Refresh status to check again; it
                          does not send another prompt.
                        </p>
                      )}
                      {buyer && !active && !!pendingBody(`mpesa.${id}`) && (
                        <Action
                          run={async () => {
                            await postOnce(
                              `mpesa.${id}`,
                              `/orders/${id}/payments/mpesa`,
                              pendingBody(`mpesa.${id}`),
                            );
                            setUntil(Date.now() + 120_000);
                          }}
                        >
                          Recover previous payment request
                        </Action>
                      )}
                      {buyer &&
                        !["cancelled", "expired"].includes(o.status) &&
                        o.payment_status === "unpaid" &&
                        !active &&
                        intents.data && (
                          <>
                            {!config.data?.mpesa_ready ? (
                              <Alert tone="info">
                                Sandbox payments are not ready. A public HTTPS
                                callback URL must be configured by the
                                administrator.
                              </Alert>
                            ) : (
                              <SmartForm
                                fields={[
                                  {
                                    name: "phone",
                                    label: "M-Pesa phone",
                                    type: "tel",
                                    default: user?.phone,
                                    hint: "A sandbox request sends a test prompt. Use your own approved test number.",
                                  },
                                ]}
                                submit={
                                  intents.data.some(
                                    (i) => i.status === "failed",
                                  )
                                    ? "Retry sandbox payment"
                                    : "Request sandbox payment"
                                }
                                success="Request queued. This is not a payment confirmation."
                                onSubmit={async (v) => {
                                  const result = await postOnce<{
                                    status: string;
                                  }>(
                                    `mpesa.${id}`,
                                    `/orders/${id}/payments/mpesa`,
                                    { phone: v.phone },
                                  );
                                  if (
                                    ![
                                      "queued",
                                      "pending",
                                      "submitting",
                                    ].includes(result.status)
                                  )
                                    throw new Error(
                                      `The existing request is ${result.status}. Refresh status before deciding whether to retry.`,
                                    );
                                  setUntil(Date.now() + 120_000);
                                }}
                              />
                            )}
                          </>
                        )}
                      {active && (
                        <Alert tone="info">
                          Cancellation is blocked while payment is active or
                          uncertain, so a payment cannot arrive after stock is
                          released.
                        </Alert>
                      )}
                      {o.payment_status === "paid" &&
                        o.status !== "completed" && (
                          <Alert tone="success">
                            Payment verified. Your order is still being
                            fulfilled; paid orders cannot be cancelled without a
                            refund workflow.
                          </Alert>
                        )}
                    </Panel>
                  </div>
                )}
                {(manage || rider) &&
                  o.status === "completed" &&
                  o.payment_status === "unpaid" && (
                    <Panel title="Record cash received">
                      {active ? (
                        <Alert tone="info">
                          Resolve the active M-Pesa request before collecting
                          cash.
                        </Alert>
                      ) : (
                        <>
                          <p>
                            Record only cash you have physically received:{" "}
                            <strong>{money(o.total)}</strong>.
                          </p>
                          <SmartForm
                            fields={[
                              {
                                name: "receipt",
                                label: "Cash receipt reference",
                                hint: "Use your unique receipt number. Keep the same reference when retrying.",
                              },
                            ]}
                            submit="Record cash payment"
                            success="Cash receipt recorded."
                            onSubmit={(v) =>
                              send(`/orders/${id}/payments`, {
                                amount: o.total,
                                receipt: v.receipt,
                              })
                            }
                          />
                        </>
                      )}
                    </Panel>
                  )}
              </div>
            </div>
          </>
        )}
      </State>
    </>
  );
}
