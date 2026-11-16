import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Plus, Leaf, ArrowUpRight } from "lucide-react";
import { useApi, usePages, send, newKey } from "./api";
import type {
  Flock,
  Daily,
  Product,
  Transfer,
  Expense,
  Summary,
} from "./types";
import { useBusiness, BusinessSelect } from "./workspace";
import { money, quantity, date, label, today } from "./utils";
import { Alert, DataTable, Heading, Panel, SmartForm, State, Stat } from "./ui";
export function Flocks() {
  const b = useBusiness();
  const flocks = useApi<Flock[]>(`/businesses/${b.id}/flocks`, !!b.id);
  const [create, setCreate] = useState(false);
  return (
    <>
      <Heading
        eyebrow="HEALTHY FLOCKS, EVERY DAY"
        title="Your farm"
        description="Track the birds you care for. Biological flock counts stay separate from saleable stock."
        action={
          <button
            disabled={!b.id}
            className="button"
            onClick={() => setCreate(!create)}
          >
            <Plus size={17} />
            {create ? "Close form" : "Add flock"}
          </button>
        }
      />
      <BusinessSelect />
      {b.id && create && (
        <Panel title="New flock / batch">
          <SmartForm
            key={b.id}
            fields={[
              { name: "name", label: "Batch name" },
              {
                name: "kind",
                label: "Flock type",
                options: [
                  { value: "broiler", label: "Broiler" },
                  { value: "layer", label: "Layer" },
                ],
              },
              {
                name: "initial_birds",
                label: "Initial bird count",
                type: "number",
                min: 1,
              },
              {
                name: "started_on",
                label: "Start date",
                type: "date",
                default: today(),
              },
            ]}
            submit="Create flock"
            onSubmit={(v) =>
              send("/flocks", {
                ...v,
                initial_birds: Number(v.initial_birds),
                business_id: b.id,
              })
            }
          />
        </Panel>
      )}
      <State
        loading={b.loading || (!!b.id && flocks.isPending)}
        error={b.error || flocks.error}
        empty={!flocks.data?.length}
      >
        <div className="flock-grid">
          {flocks.data?.map((f) => (
            <Link to={`/farm/${f.id}`} className="flock-card" key={f.id}>
              <div className="flock-card-top">
                <Leaf size={24} />
                <span className="badge neutral">{label(f.kind)}</span>
              </div>
              <h2>{f.name}</h2>
              <strong>
                {f.live_birds.toLocaleString()} <small>live birds</small>
              </strong>
              <div className="flock-card-bottom">
                <span>Started {date(f.started_on)}</span>
                <ArrowUpRight size={18} />
              </div>
            </Link>
          ))}
        </div>
      </State>
    </>
  );
}
export function FlockDetail() {
  const { id } = useParams();
  const b = useBusiness();
  const flocks = useApi<Flock[]>(`/businesses/${b.id}/flocks`, !!b.id);
  const flock = flocks.data?.find((f) => String(f.id) === id);
  const daily = useApi<Daily[]>(`/flocks/${id}/daily-records`, !!flock);
  const transfers = useApi<Transfer[]>(`/flocks/${id}/transfers`, !!flock);
  const products = usePages<Product>("/products");
  const [tab, setTab] = useState("daily");
  const [source] = useState(newKey());
  const eligible = products.data?.filter((p) => p.business_id === b.id) || [];
  return (
    <>
      <Link to="/farm" className="back-link">
        ← Your flocks
      </Link>
      <BusinessSelect />
      <State
        loading={b.loading || (!!b.id && flocks.isPending)}
        error={flocks.error || b.error}
      >
        {!flock ? (
          <Alert tone="info">
            Select the farm that owns this flock, or return to your flock list.
          </Alert>
        ) : (
          <>
            <Heading
              eyebrow={`${label(flock.kind)} BATCH`}
              title={flock.name}
              description={`Started ${date(flock.started_on)}. Daily records are immutable; repeat identical submissions safely, but do not change a submitted date’s values.`}
            />
            <div className="stats-grid three">
              <Stat
                title="Live biological count"
                value={flock.live_birds.toLocaleString()}
                detail="Birds currently in the flock"
              />
              <Stat
                title="Initial birds"
                value={flock.initial_birds.toLocaleString()}
              />
              <Stat
                title="Farm / batch"
                value={`#${flock.id}`}
                detail="This is not saleable inventory"
              />
            </div>
            <div className="tabs">
              <button
                className={tab === "daily" ? "selected" : ""}
                onClick={() => setTab("daily")}
              >
                Daily care & production
              </button>
              <button
                className={tab === "transfer" ? "selected" : ""}
                onClick={() => setTab("transfer")}
              >
                Transfer to inventory
              </button>
            </div>
            {tab === "daily" ? (
              <Panel title="Record daily care">
                <SmartForm
                  key={flock.id}
                  fields={[
                    {
                      name: "day",
                      label: "Record date",
                      type: "date",
                      default: today(),
                    },
                    {
                      name: "mortality",
                      label: "Mortality (birds)",
                      type: "number",
                      min: 0,
                      default: "0",
                      max: flock.live_birds,
                    },
                    ...(flock.kind === "layer"
                      ? [
                          {
                            name: "eggs",
                            label: "Eggs produced",
                            type: "number",
                            min: 0,
                            default: "0",
                          },
                        ]
                      : []),
                    {
                      name: "feed_kg",
                      label: "Feed consumed (kg)",
                      type: "number",
                      step: "0.001",
                      min: 0,
                      default: "0",
                    },
                  ]}
                  submit="Save daily record"
                  onSubmit={(v) =>
                    send(`/flocks/${id}/daily-records`, {
                      day: v.day,
                      mortality: Number(v.mortality),
                      eggs: Number(v.eggs || 0),
                      feed_kg: v.feed_kg,
                    })
                  }
                />
              </Panel>
            ) : (
              <Panel title="Transfer production into saleable stock">
                <p className="muted">
                  Eggs need a recorded production day. One tray = 30 eggs. Bird
                  harvests remove live birds and create measured saleable stock.
                  Reuse the same source reference when retrying.
                </p>
                <State
                  loading={products.isPending || daily.isPending}
                  error={products.error || daily.error}
                >
                  <SmartForm
                    key={`${id}-transfer`}
                    fields={[
                      {
                        name: "product_id",
                        label: "Destination product",
                        options: eligible.map((p) => ({
                          value: String(p.id),
                          label: `${p.name} · ${p.unit}`,
                        })),
                      },
                      {
                        name: "quantity",
                        label: "Saleable quantity",
                        type: "number",
                        min: 0.001,
                        step: "0.001",
                      },
                      {
                        name: "daily_record_id",
                        label: "Egg production record",
                        required: false,
                        options: (daily.data || []).map((d) => ({
                          value: String(d.id),
                          label: `${d.day} · ${d.eggs - d.transferred_eggs} eggs untransferred`,
                        })),
                      },
                      {
                        name: "birds_removed",
                        label: "Birds removed for harvest",
                        type: "number",
                        min: 0,
                        default: "0",
                        hint: "Use 0 for egg transfers.",
                      },
                      {
                        name: "source",
                        label: "Production source reference",
                        default: `production-${source}`,
                      },
                    ]}
                    submit="Transfer production"
                    validate={(v) => {
                      const p = eligible.find(
                        (p) => p.id === Number(v.product_id),
                      );
                      if (p?.category === "eggs" && !v.daily_record_id)
                        return {
                          field: "daily_record_id",
                          message: "Select the egg production record.",
                        };
                      if (
                        p?.category !== "eggs" &&
                        Number(v.birds_removed) <= 0
                      )
                        return {
                          field: "birds_removed",
                          message: "Specify the birds removed by this harvest.",
                        };
                      if (
                        p?.unit !== "kilogram" &&
                        !Number.isInteger(Number(v.quantity))
                      )
                        return {
                          field: "quantity",
                          message:
                            "Only kilogram quantities can be fractional.",
                        };
                      return undefined;
                    }}
                    onSubmit={(v) =>
                      send(`/flocks/${id}/transfers`, {
                        source: v.source,
                        product_id: Number(v.product_id),
                        quantity: v.quantity,
                        birds_removed: Number(v.birds_removed),
                        daily_record_id: v.daily_record_id
                          ? Number(v.daily_record_id)
                          : null,
                      })
                    }
                  />
                </State>
              </Panel>
            )}
            <Panel title="Daily production records">
              <State loading={daily.isPending} error={daily.error}>
                <DataTable
                  headers={[
                    "Date",
                    "Mortality",
                    "Eggs produced",
                    "Eggs transferred",
                    "Feed (kg)",
                  ]}
                  rows={(daily.data || []).map((d) => [
                    date(d.day),
                    d.mortality,
                    d.eggs,
                    d.transferred_eggs,
                    quantity(d.feed_kg),
                  ])}
                />
              </State>
            </Panel>
            <Panel title="Production transfer history">
              <State loading={transfers.isPending} error={transfers.error}>
                <DataTable
                  headers={[
                    "When",
                    "Product",
                    "Quantity",
                    "Birds removed",
                    "Source",
                  ]}
                  rows={(transfers.data || []).map((t) => [
                    date(t.created_at),
                    eligible.find((p) => p.id === t.product_id)?.name ||
                      `#${t.product_id}`,
                    quantity(t.quantity),
                    t.birds_removed,
                    t.source,
                  ])}
                />
              </State>
            </Panel>
          </>
        )}
      </State>
    </>
  );
}
export function Expenses() {
  const b = useBusiness();
  const expenses = useApi<Expense[]>(`/businesses/${b.id}/expenses`, !!b.id);
  const flocks = useApi<Flock[]>(`/businesses/${b.id}/flocks`, !!b.id);
  const [source] = useState(newKey());
  const [create, setCreate] = useState(false);
  return (
    <>
      <Heading
        eyebrow="EVERY SHILLING, ACCOUNTED FOR"
        title="Expenses"
        description="Record the cost of keeping your farm running."
        action={
          <button
            disabled={!b.id}
            className="button"
            onClick={() => setCreate(!create)}
          >
            <Plus size={17} />
            Record expense
          </button>
        }
      />
      <BusinessSelect />
      {create && b.id && (
        <Panel title="New expense">
          <SmartForm
            key={b.id}
            fields={[
              {
                name: "day",
                label: "Expense date",
                type: "date",
                default: today(),
              },
              {
                name: "category",
                label: "Category",
                hint: "For example feed, veterinary care or transport.",
              },
              {
                name: "amount",
                label: "Amount (KES)",
                type: "number",
                min: 0.01,
                step: "0.01",
              },
              {
                name: "flock_id",
                label: "Flock",
                required: false,
                options: (flocks.data || []).map((f) => ({
                  value: String(f.id),
                  label: f.name,
                })),
              },
              {
                name: "description",
                label: "Description",
                type: "textarea",
                required: false,
              },
              {
                name: "source",
                label: "Expense / invoice reference",
                default: `expense-${source}`,
              },
            ]}
            submit="Save expense"
            onSubmit={(v) =>
              send("/expenses", {
                ...v,
                business_id: b.id,
                flock_id: v.flock_id ? Number(v.flock_id) : null,
              })
            }
          />
        </Panel>
      )}
      <State
        loading={b.loading || (!!b.id && expenses.isPending)}
        error={expenses.error || b.error}
      >
        <Panel>
          <DataTable
            headers={["Date", "Category", "Description", "Amount", "Reference"]}
            rows={(expenses.data || []).map((e) => [
              date(e.day),
              label(e.category),
              e.description || "—",
              money(e.amount),
              e.source,
            ])}
          />
        </Panel>
      </State>
    </>
  );
}
export function Summaries() {
  const b = useBusiness();
  const [range, setRange] = useState({
    start: today().slice(0, 8) + "01",
    end: today(),
  });
  const data = useApi<Summary>(
    `/businesses/${b.id}/summary?start=${range.start}&end=${range.end}`,
    !!b.id,
  );
  return (
    <>
      <Heading
        eyebrow="THE BIGGER PICTURE"
        title="Production & sales"
        description="Real records, clear numbers. All dates use Africa/Nairobi calendar days."
      />
      <BusinessSelect />
      <Panel title="Reporting period">
        <SmartForm
          fields={[
            {
              name: "start",
              label: "From",
              type: "date",
              default: range.start,
            },
            { name: "end", label: "To", type: "date", default: range.end },
          ]}
          submit="Update report"
          success="Report period updated."
          validate={(v) =>
            v.start > v.end
              ? {
                  field: "end",
                  message: "End date must be on or after the start date.",
                }
              : undefined
          }
          onSubmit={async (v) => setRange({ start: v.start, end: v.end })}
        />
      </Panel>
      <State loading={!!b.id && data.isPending} error={data.error}>
        {data.data && (
          <>
            <div className="stats-grid">
              <Stat
                title="Cash received"
                value={money(data.data.cash_received)}
                detail="Excludes sandbox simulations"
              />
              <Stat title="Expenses" value={money(data.data.expenses)} />
              <Stat
                title="Cash less expenses"
                value={money(data.data.cash_less_expenses)}
                detail="Not accounting profit"
              />
              <Stat title="Eggs produced" value={data.data.eggs} />
            </div>
            <div className="stats-grid three">
              <Stat title="Mortality" value={`${data.data.mortality} birds`} />
              <Stat
                title="Feed consumed"
                value={`${quantity(data.data.feed_kg)} kg`}
              />
              <Stat
                title="Reporting days"
                value={`${date(range.start)} – ${date(range.end)}`}
              />
            </div>
            <Panel title="Sales by selling unit">
              <DataTable
                headers={["Unit", "Quantity sold", "Item revenue"]}
                rows={data.data.sales_by_unit.map((s) => [
                  label(s.unit),
                  quantity(s.quantity),
                  money(s.item_revenue),
                ])}
              />
              <p className="muted">{data.data.note}</p>
            </Panel>
          </>
        )}
      </State>
    </>
  );
}
