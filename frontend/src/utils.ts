import Decimal from "decimal.js";
export const money = (value: string | number) =>
  `KES ${new Decimal(value).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",")}`;
export const quantity = (value: string | number) =>
  new Decimal(value).toString();
export const label = (value: string) =>
  value.replaceAll("_", " ").replace(/^./, (s) => s.toUpperCase());
export const date = (value: string) =>
  new Intl.DateTimeFormat("en-KE", {
    dateStyle: "medium",
    ...(value.includes("T") ? { timeStyle: "short" } : {}),
    timeZone: "Africa/Nairobi",
  }).format(new Date(value.includes("T") ? value : value + "T12:00:00+03:00"));
export const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Africa/Nairobi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const phone = (value: string) => {
  let p = value.replace(/[\s()-]/g, "");
  if (p.startsWith("0")) p = "+254" + p.slice(1);
  if (p.startsWith("254")) p = "+" + p;
  return /^\+254[17]\d{8}$/.test(p) ? p : null;
};
export const manager = (role?: string) =>
  ["admin", "seller", "staff"].includes(role || "");
