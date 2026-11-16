import { useRef, useState, useEffect, useId, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  AlertCircle,
  CheckCircle2,
  LoaderCircle,
  ArrowRight,
} from "lucide-react";
import { ApiError, queryClient } from "./api";
import { label, phone } from "./utils";
export type Values = Record<string, string>;
export interface Field {
  name: string;
  label: string;
  type?: string;
  required?: boolean;
  default?: string;
  options?: { value: string; label: string }[];
  hint?: string;
  min?: number;
  max?: number;
  step?: string;
  validate?: (value: string) => string | undefined;
}
export function Alert({
  children,
  tone = "error",
}: {
  children: ReactNode;
  tone?: "error" | "success" | "info";
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`notice ${tone}`}
    >
      {tone === "error" ? (
        <AlertCircle size={18} />
      ) : (
        <CheckCircle2 size={18} />
      )}
      <div>{children}</div>
    </div>
  );
}
export function State({
  loading,
  error,
  empty,
  children,
}: {
  loading?: boolean;
  error?: Error | null;
  empty?: boolean;
  children: ReactNode;
}) {
  if (loading)
    return (
      <div role="status" className="state">
        <LoaderCircle className="spin" />
        Loading your farm…
      </div>
    );
  if (error)
    return (
      <Alert>
        {error.message}{" "}
        <button onClick={() => queryClient.invalidateQueries()}>
          Try again
        </button>
      </Alert>
    );
  if (empty)
    return (
      <div className="state">
        Nothing here yet. New records will appear here.
      </div>
    );
  return <>{children}</>;
}
export function Badge({ value }: { value: string }) {
  return (
    <span
      className={`badge ${["paid", "completed", "delivered", "succeeded", "ready", "dry-run"].includes(value) ? "good" : ["cancelled", "expired", "failed", "uncertain"].includes(value) ? "bad" : "neutral"}`}
    >
      {label(value)}
    </span>
  );
}
export function Heading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action}
    </header>
  );
}
export function Panel({
  title,
  children,
  className = "",
}: {
  title?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}
export function Stat({
  title,
  value,
  detail,
}: {
  title: string;
  value: ReactNode;
  detail?: string;
}) {
  return (
    <div className="stat">
      <span>{title}</span>
      <strong>{value}</strong>
      {detail && <small>{detail}</small>}
    </div>
  );
}
export function SmartForm({
  fields,
  onSubmit,
  submit = "Save record",
  success = "Saved successfully.",
  validate,
  children,
}: {
  fields: Field[];
  onSubmit: (v: Values) => Promise<unknown>;
  submit?: string;
  success?: string;
  validate?: (v: Values) => { field: string; message: string } | undefined;
  children?: ReactNode;
}) {
  const id = useId();
  const schema = z.record(z.string(), z.string()).superRefine((values, ctx) => {
    for (const f of fields) {
      const v = values[f.name] || "";
      let error: string | undefined;
      if (f.required !== false && !v.trim()) error = "This field is required.";
      else if (
        v &&
        f.type === "number" &&
        (!Number.isFinite(Number(v)) ||
          (f.min !== undefined && Number(v) < f.min) ||
          (f.max !== undefined && Number(v) > f.max))
      )
        error = `Enter a number${f.min !== undefined ? " of at least " + f.min : ""}${f.max !== undefined ? " and at most " + f.max : ""}.`;
      else if (v && f.type === "tel" && !phone(v))
        error = "Enter a Kenyan mobile number, such as 0712345678.";
      else if (
        f.type === "password" &&
        submit.toLowerCase().includes("create") &&
        v.length < 12
      )
        error = "Use at least 12 characters.";
      else if (
        v &&
        f.type === "number" &&
        (f.step || "1") === "1" &&
        !Number.isInteger(Number(v))
      )
        error = "Enter a whole number.";
      else if (v && f.options && !f.options.some((o) => o.value === v))
        error = "Choose a valid option.";
      error = error || f.validate?.(v);
      if (error)
        ctx.addIssue({ code: "custom", path: [f.name], message: error });
    }
    const cross = validate?.(values);
    if (cross)
      ctx.addIssue({
        code: "custom",
        path: [cross.field],
        message: cross.message,
      });
  });
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: Object.fromEntries(
      fields.map((f) => [f.name, f.default || ""]),
    ),
  });
  const [message, setMessage] = useState("");
  const lock = useRef(false);
  const mutation = useMutation({
    mutationFn: onSubmit,
    onSuccess: () => {
      setMessage(success);
      queryClient.invalidateQueries();
    },
    onError: (e: Error) => {
      if (e instanceof ApiError)
        for (const [name, msg] of Object.entries(e.fields)) {
          if (fields.some((f) => f.name === name))
            form.setError(name, { message: msg });
        }
      queryClient.invalidateQueries();
    },
  });
  return (
    <form
      noValidate
      onSubmit={form.handleSubmit(async (v) => {
        if (lock.current) return;
        lock.current = true;
        setMessage("");
        try {
          await mutation.mutateAsync(v);
        } catch {
        } finally {
          lock.current = false;
        }
      })}
      className="form-grid"
    >
      {fields.map((f) => (
        <div
          className={`field ${f.type === "textarea" ? "wide" : ""}`}
          key={f.name}
        >
          <label htmlFor={`${id}-${f.name}`}>
            {f.label}
            {f.required === false && <small> Optional</small>}
          </label>
          {f.options ? (
            <select
              id={`${id}-${f.name}`}
              {...form.register(f.name)}
              aria-invalid={!!form.formState.errors[f.name]}
              aria-describedby={`${id}-hint-${f.name}`}
            >
              <option value="">Select…</option>
              {f.options.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : f.type === "textarea" ? (
            <textarea
              id={`${id}-${f.name}`}
              {...form.register(f.name)}
              rows={3}
              aria-invalid={!!form.formState.errors[f.name]}
              aria-describedby={`${id}-hint-${f.name}`}
            />
          ) : (
            <input
              id={`${id}-${f.name}`}
              type={f.type || "text"}
              {...form.register(f.name)}
              step={f.step}
              min={f.min}
              max={f.max}
              autoComplete={
                f.type === "password"
                  ? "current-password"
                  : f.type === "tel"
                    ? "tel"
                    : "off"
              }
              aria-invalid={!!form.formState.errors[f.name]}
              aria-describedby={`${id}-hint-${f.name}`}
            />
          )}
          <span id={`${id}-hint-${f.name}`}>
            {form.formState.errors[f.name] ? (
              <small className="field-error">
                {String(form.formState.errors[f.name]?.message)}
              </small>
            ) : (
              f.hint && <small>{f.hint}</small>
            )}
          </span>
        </div>
      ))}
      {children}
      <div className="wide">
        {mutation.error && <Alert>{mutation.error.message}</Alert>}
        {message && <Alert tone="success">{message}</Alert>}
        <button
          className="button"
          disabled={mutation.isPending || form.formState.isSubmitting}
        >
          {mutation.isPending ? (
            <LoaderCircle size={17} className="spin" />
          ) : (
            <ArrowRight size={17} />
          )}{" "}
          {mutation.isPending ? "Saving…" : submit}
        </button>
      </div>
    </form>
  );
}
export function Action({
  children,
  run,
  confirm,
  danger = false,
  disabled = false,
}: {
  children: ReactNode;
  run: () => Promise<unknown>;
  confirm?: string;
  danger?: boolean;
  disabled?: boolean;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const ref = useRef<HTMLButtonElement>(null);
  const lock = useRef(false);
  const action = useMutation({
    mutationFn: run,
    onSuccess: () => {
      queryClient.invalidateQueries();
      dialog.current?.close();
    },
    onError: () => queryClient.invalidateQueries(),
  });
  const submit = async () => {
    if (lock.current) return;
    lock.current = true;
    try {
      await action.mutateAsync();
    } catch {
    } finally {
      lock.current = false;
    }
  };
  useEffect(() => () => dialog.current?.close(), []);
  return (
    <div className="action">
      <button
        type="button"
        ref={ref}
        disabled={disabled || action.isPending}
        className={`button ${danger ? "danger" : "secondary"}`}
        onClick={() => (confirm ? dialog.current?.showModal() : submit())}
      >
        {action.isPending ? "Saving…" : children}
      </button>
      {confirm && (
        <dialog ref={dialog} onClose={() => ref.current?.focus()}>
          <h2>Confirm action</h2>
          <p>{confirm}</p>
          {action.error && <Alert>{action.error.message}</Alert>}
          <div className="actions">
            <button
              className="button secondary"
              disabled={action.isPending}
              type="button"
              onClick={() => dialog.current?.close()}
            >
              Go back
            </button>
            <button
              className={`button ${danger ? "danger" : ""}`}
              disabled={action.isPending}
              type="button"
              onClick={submit}
            >
              Confirm
            </button>
          </div>
        </dialog>
      )}
      {!confirm && action.error && <Alert>{action.error.message}</Alert>}
    </div>
  );
}
export function DataTable({
  headers,
  rows,
}: {
  headers: string[];
  rows: ReactNode[][];
}) {
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th scope="col" key={h}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="state">No records yet.</div>}
    </div>
  );
}
