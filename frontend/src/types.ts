export type Role = "admin" | "seller" | "staff" | "buyer" | "rider";
export interface User {
  id: number;
  phone: string;
  role: Role;
}
export interface Business {
  id: number;
  name: string;
  owner_id: number;
}
export interface Product {
  id: number;
  business_id: number;
  name: string;
  description: string;
  category: string;
  unit: string;
  price: string;
  stock: string;
  reserved: string;
  available: string;
  currency: string;
}
export interface Payment {
  id: number;
  amount: string;
  method: string;
  receipt: string;
  created_at: string;
}
export interface OrderItem {
  id: number;
  product_id: number;
  name: string;
  description: string;
  unit: string;
  price: string;
  quantity: string;
  line_total: string;
}
export interface Order {
  id: number;
  reference: string;
  buyer_id: number;
  business_id: number;
  business_name: string;
  seller_phone: string;
  buyer_phone: string;
  status: string;
  payment_status: string;
  delivery_status: string;
  fulfillment: "pickup" | "delivery";
  address: string;
  fee: string;
  total: string;
  currency: string;
  rider_id: number | null;
  expires_at: string;
  created_at: string;
  items: OrderItem[];
  payments: Payment[];
}
export interface Intent {
  id: number;
  status: string;
  amount: string;
  environment: string;
  checkout_id: string | null;
  result_code: string | null;
  checks: number;
}
export interface Config {
  delivery_fee: string;
  currency: string;
  tray_size: number;
  mpesa_mode: string;
  mpesa_ready: boolean;
  mpesa_timing: string;
}
export interface Movement {
  id: number;
  kind: string;
  quantity: string;
  source: string;
  created_at: string;
  order_id: number | null;
}
export interface Flock {
  id: number;
  business_id: number;
  name: string;
  kind: string;
  initial_birds: number;
  live_birds: number;
  started_on: string;
}
export interface Daily {
  id: number;
  flock_id: number;
  day: string;
  mortality: number;
  eggs: number;
  feed_kg: string;
  transferred_eggs: number;
}
export interface Transfer {
  id: number;
  product_id: number;
  source: string;
  quantity: string;
  birds_removed: number;
  daily_record_id: number | null;
  created_at: string;
}
export interface Expense {
  id: number;
  day: string;
  category: string;
  description: string;
  amount: string;
  source: string;
  flock_id: number | null;
}
export interface Summary {
  currency: string;
  start: string;
  end: string;
  mortality: number;
  eggs: number;
  feed_kg: string;
  expenses: string;
  cash_received: string;
  cash_less_expenses: string;
  sales_by_unit: { unit: string; quantity: string; item_revenue: string }[];
  note: string;
}
export interface Notification {
  id: number;
  event_key: string;
  event_type: string | null;
  order_id: number | null;
  recipient_masked: string;
  last_error: string | null;
  submitted_at: string | null;
  delivered_at: string | null;
  provider_message_id: string | null;
  can_retry: boolean;
  status: string;
  attempts: number;
  next_attempt: string;
  history: { outcome: string; created_at: string }[];
}
