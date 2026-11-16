import {
  test,
  expect,
  type Page,
  type APIRequestContext,
} from "@playwright/test";
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "../..");
const accounts = () =>
  JSON.parse(readFileSync(path.join(root, ".local/e2e-accounts.json"), "utf8"));
const backend = "http://127.0.0.1:8012";
async function login(page: Page, role: string) {
  const a = accounts()[role];
  await page.goto("/login");
  await page.getByLabel("Kenyan mobile number", { exact: true }).fill(a.phone);
  await page.getByLabel("Password", { exact: true }).fill(a.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
}
async function confirm(page: Page) {
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Confirm", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
}
async function auth(request: APIRequestContext, role: string) {
  const a = accounts()[role];
  if (role === "buyer")
    await request.post(backend + "/auth/register", { data: a });
  const r = await request.post(backend + "/auth/login", {
    data: { phone: a.phone, password: a.password },
  });
  expect(r.ok()).toBeTruthy();
  return { Authorization: "Bearer " + (await r.json()).access_token };
}
async function completedOrder(request: APIRequestContext) {
  const a = accounts();
  const seller = await auth(request, "seller");
  const buyer = await auth(request, "buyer");
  const product = await request.post(backend + "/products", {
    headers: seller,
    data: {
      business_id: a.business_id,
      name: "Payment test eggs",
      description: "Sandbox UI testing only",
      category: "eggs",
      unit: "tray",
      price: "450.00",
    },
  });
  expect(product.ok()).toBeTruthy();
  const p = await product.json();
  await request.post(`${backend}/products/${p.id}/stock`, {
    headers: seller,
    data: { quantity: "5", source: crypto.randomUUID() },
  });
  const r = await request.post(backend + "/orders", {
    headers: { ...buyer, "Idempotency-Key": crypto.randomUUID() },
    data: {
      items: [{ product_id: p.id, quantity: "1" }],
      fulfillment: "pickup",
      address: "",
    },
  });
  expect(r.ok()).toBeTruthy();
  const o = await r.json();
  for (const status of ["confirmed", "preparing", "ready", "completed"])
    expect(
      (
        await request.post(`${backend}/orders/${o.id}/status`, {
          headers: seller,
          data: { status },
        })
      ).ok(),
    ).toBeTruthy();
  return o.id as number;
}
function paymentStep(step: string) {
  execFileSync(
    path.join(root, ".venv/bin/python"),
    [path.join(root, "scripts/e2e_payment_step.py"), step],
    {
      cwd: root,
      env: {
        ...process.env,
        DATABASE_URL:
          process.env.E2E_DATABASE_URL ||
          "postgresql+psycopg://farm:farm@localhost:5432/farm_frontend_e2e_test",
      },
    },
  );
}

test("buyer → seller → admin → rider → cash receipt, then production transfer", async ({
  browser,
}) => {
  const a = accounts();
  const seller = await browser.newPage();
  const buyer = await browser.newPage();
  const admin = await browser.newPage();
  const rider = await browser.newPage();
  await login(seller, "seller");
  await seller.goto("/manage/products");
  await seller
    .getByRole("button", { name: "Add product", exact: true })
    .click();
  await seller.getByLabel("Product name").fill("Browser eggs");
  await seller.getByLabel("Category", { exact: true }).selectOption("eggs");
  await seller.getByLabel("Selling unit").selectOption("tray");
  await seller.getByLabel("Unit price (KES)").fill("450.00");
  await seller
    .getByLabel(/^Description/)
    .fill("Fresh eggs for browser testing");
  await seller
    .getByRole("button", { name: "Create product", exact: true })
    .click();
  await expect(seller.getByText("Saved successfully.")).toBeVisible();
  await seller.getByRole("link", { name: "Browser eggs", exact: true }).click();
  const productId = seller.url().split("/").at(-1)!;
  await seller.getByLabel("Quantity to add").fill("10");
  await seller.getByLabel("Stock reference / reason").fill("browser-opening");
  await seller.getByRole("button", { name: "Add stock", exact: true }).click();
  await expect(
    seller.locator(".stat").filter({ hasText: "Available to sell" }),
  ).toContainText("10");
  await buyer.goto("/register");
  await buyer.getByLabel("Kenyan mobile number").fill(a.buyer.phone);
  await buyer.getByLabel("Password", { exact: true }).fill(a.buyer.password);
  await buyer.getByRole("button", { name: "Create buyer account" }).click();
  await expect(buyer).toHaveURL(/catalogue/);
  await buyer
    .getByRole("link")
    .filter({
      has: buyer.getByRole("heading", { name: "Browser eggs", exact: true }),
    })
    .click();
  await buyer.getByLabel("Quantity (tray)").fill("2");
  await buyer.getByRole("button", { name: "Add to basket" }).click();
  await buyer.goto("/cart");
  await buyer.getByLabel("Delivery", { exact: true }).check();
  await buyer
    .getByLabel("Delivery address")
    .fill("Nairobi test gate, blue entrance");
  await expect(buyer.locator(".summary-line.total")).toContainText(
    "KES 1,100.00",
  );
  await buyer.getByRole("button", { name: "Place order" }).click();
  await expect(buyer).toHaveURL(/orders\/\d+$/);
  const orderPath = new URL(buyer.url()).pathname;
  await expect(buyer.locator(".status-strip")).toContainText("Pending");
  await seller.goto(orderPath);
  for (const step of ["confirmed", "preparing", "ready"])
    await seller
      .getByRole("button", { name: `Mark ${step}`, exact: true })
      .click();
  await expect(seller.locator(".status-strip")).toContainText("Ready");
  await login(admin, "admin");
  await admin.goto(orderPath);
  await admin
    .getByLabel("Rider", { exact: true })
    .selectOption(String(a.rider.id));
  await admin
    .getByRole("button", { name: "Assign rider", exact: true })
    .click();
  await expect(admin.getByText("Saved successfully.")).toBeVisible();
  await login(rider, "rider");
  await expect(rider).toHaveURL(/deliveries/);
  await rider.getByRole("link", { name: /^PF-/, exact: false }).first().click();
  await expect(
    rider.getByText("Nairobi test gate, blue entrance", { exact: true }),
  ).toBeVisible();
  await expect(rider.getByRole("link", { name: a.seller.phone })).toBeVisible();
  await rider.getByRole("button", { name: "Dispatch delivery" }).click();
  await confirm(rider);
  await rider.getByRole("button", { name: "Mark delivered" }).click();
  await confirm(rider);
  await rider.getByLabel("Cash receipt reference").fill("browser-cash-receipt");
  await rider.getByRole("button", { name: "Record cash payment" }).click();
  await expect(rider.locator(".status-strip")).toContainText("Paid");
  await buyer.reload();
  await expect(buyer.locator(".status-strip")).toContainText("Completed");
  await expect(buyer.locator(".status-strip")).toContainText("Delivered");
  await expect(buyer.locator(".status-strip")).toContainText("Paid");
  await expect(
    buyer.getByText("browser-cash-receipt", { exact: true }),
  ).toBeVisible();
  await seller.goto("/farm");
  await seller.getByRole("button", { name: "Add flock" }).click();
  await seller.getByLabel("Batch name").fill("Browser layer batch");
  await seller.getByLabel("Flock type").selectOption("layer");
  await seller.getByLabel("Initial bird count").fill("100");
  await seller.getByRole("button", { name: "Create flock" }).click();
  await seller
    .getByRole("link")
    .filter({
      has: seller.getByRole("heading", {
        name: "Browser layer batch",
        exact: true,
      }),
    })
    .click();
  await seller.getByLabel("Mortality (birds)").fill("2");
  await seller.getByLabel("Eggs produced").fill("60");
  await seller.getByLabel("Feed consumed (kg)").fill("12.5");
  await seller.getByRole("button", { name: "Save daily record" }).click();
  await expect(seller.getByText("Saved successfully.")).toBeVisible();
  await seller.getByRole("button", { name: "Transfer to inventory" }).click();
  await seller.getByLabel("Destination product").selectOption(productId);
  await seller.getByLabel("Saleable quantity").fill("2");
  await seller.getByLabel("Egg production record").selectOption({ index: 1 });
  await seller
    .getByLabel("Production source reference")
    .fill("browser-production-001");
  await seller.getByRole("button", { name: "Transfer production" }).click();
  await expect(seller.getByText("Saved successfully.")).toBeVisible();
  await seller.goto(`/manage/products/${productId}`);
  await expect(
    seller.locator(".stat").filter({ hasText: "On hand" }),
  ).toContainText("10 tray");
  await expect(
    seller.locator(".stat").filter({ hasText: "Reserved" }),
  ).toContainText("0");
  await Promise.all([
    seller.close(),
    buyer.close(),
    admin.close(),
    rider.close(),
  ]);
});

test("role restrictions, session expiry and mobile navigation", async ({
  browser,
  request,
}) => {
  const buyer = await browser.newPage({
    viewport: { width: 390, height: 844 },
  });
  await auth(request, "buyer");
  await login(buyer, "buyer");
  await buyer.goto("/manage/products");
  await expect(
    buyer.getByRole("heading", { name: "Access restricted" }),
  ).toBeVisible();
  expect(
    (
      await request.get(backend + "/admin/users", {
        headers: await auth(request, "buyer"),
      })
    ).status(),
  ).toBe(403);
  await buyer.getByRole("button", { name: "Open navigation" }).click();
  await expect(
    buyer.getByRole("navigation", { name: "Main navigation" }),
  ).toBeVisible();
  await buyer
    .getByRole("navigation")
    .getByRole("link", { name: "Marketplace", exact: true })
    .click();
  await expect(buyer).toHaveURL(/catalogue/);
  expect(
    await buyer.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await buyer.evaluate(() =>
    sessionStorage.setItem("kuku.token", "expired.invalid.token"),
  );
  await buyer.goto("/orders");
  await expect(buyer).toHaveURL(/login/);
  await expect(
    buyer.getByText("Your session expired. Sign in again to continue."),
  ).toBeVisible();
  await buyer.close();
});

test("M-Pesa UI uses real intent endpoints with mocked provider success", async ({
  page,
  request,
}) => {
  const oid = await completedOrder(request);
  await login(page, "buyer");
  await page.goto(`/orders/${oid}`);
  await page.getByRole("button", { name: "Request sandbox payment" }).click();
  await expect(page.locator(".payment-intent").last()).toContainText("Queued");
  await expect(page.locator(".status-strip")).toContainText("Unpaid");
  paymentStep("accepted");
  await page
    .getByRole("button", { name: "Refresh status", exact: true })
    .click();
  await expect(page.locator(".payment-intent")).toContainText("Pending");
  paymentStep("success");
  await page
    .getByRole("button", { name: "Refresh status", exact: true })
    .click();
  await expect(page.locator(".status-strip")).toContainText("Paid");
  await expect(
    page.getByText("M-Pesa sandbox (simulation)", { exact: true }),
  ).toBeVisible();
});

test("M-Pesa cancellation allows retry; ambiguous timeout blocks repeat prompt", async ({
  page,
  request,
}) => {
  const oid = await completedOrder(request);
  await login(page, "buyer");
  await page.goto(`/orders/${oid}`);
  await page.getByRole("button", { name: "Request sandbox payment" }).click();
  await expect(page.locator(".payment-intent").last()).toContainText("Queued");
  paymentStep("accepted");
  paymentStep("cancelled");
  await page
    .getByRole("button", { name: "Refresh status", exact: true })
    .click();
  await expect(
    page.getByText("Cancelled by payer", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Retry sandbox payment" }).click();
  await expect(page.locator(".payment-intent").last()).toContainText("Queued");
  paymentStep("timeout");
  await page
    .getByRole("button", { name: "Refresh status", exact: true })
    .click();
  await expect(
    page.getByText("The outcome is uncertain.", { exact: false }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Retry sandbox payment" }),
  ).toHaveCount(0);
  await expect(page.locator(".status-strip")).toContainText("Unpaid");
});

test("lost checkout response is recovered once, and cancellation requires confirmation", async ({
  page,
  request,
}) => {
  const a = accounts();
  const seller = await auth(request, "seller");
  const buyer = await auth(request, "buyer");
  const p = await (
    await request.post(backend + "/products", {
      headers: seller,
      data: {
        business_id: a.business_id,
        name: "Recovery eggs",
        description: "One tray only",
        category: "eggs",
        unit: "tray",
        price: "400.00",
      },
    })
  ).json();
  await request.post(`${backend}/products/${p.id}/stock`, {
    headers: seller,
    data: { quantity: "1", source: "recovery-opening" },
  });
  const before = (
    await (await request.get(backend + "/orders", { headers: buyer })).json()
  ).length;
  await login(page, "buyer");
  await page.goto(`/products/${p.id}`);
  await page.getByRole("button", { name: "Add to basket" }).click();
  await page.goto("/cart");
  let lost = false;
  await page.route(`${backend}/orders`, async (route) => {
    if (route.request().method() === "POST" && !lost) {
      lost = true;
      const response = await route.fetch();
      expect(response.status()).toBe(201);
      await route.abort("failed");
    } else await route.continue();
  });
  await page.getByRole("button", { name: "Place order" }).click();
  await expect(
    page.getByText("A saved submission may already have reserved stock.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Recover saved submission" }).click();
  await expect(page).toHaveURL(/orders\/\d+$/);
  expect(
    (await (await request.get(backend + "/orders", { headers: buyer })).json())
      .length,
  ).toBe(before + 1);
  await page.getByRole("button", { name: "Cancel order", exact: true }).click();
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Go back" })
    .click();
  await expect(page.locator(".status-strip")).toContainText("Pending");
  await page.getByRole("button", { name: "Cancel order", exact: true }).click();
  await confirm(page);
  await expect(page.locator(".status-strip")).toContainText("Cancelled");
  const stock = await (await request.get(`${backend}/products/${p.id}`)).json();
  expect(Number(stock.available)).toBe(1);
});

test("expense entry and date-based production/sales reports use real records", async ({
  page,
  request,
}) => {
  await login(page, "seller");
  await page.goto("/expenses");
  await page.getByRole("button", { name: "Record expense" }).click();
  await page.getByLabel("Category", { exact: true }).fill("feed");
  await page.getByLabel("Amount (KES)").fill("650.00");
  await page
    .getByLabel("Expense / invoice reference")
    .fill("browser-feed-invoice");
  await page.getByRole("button", { name: "Save expense" }).click();
  await expect(page.getByText("Saved successfully.")).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "KES 650.00", exact: true }),
  ).toBeVisible();
  await page.goto("/summary");
  await expect(
    page.locator(".stat").filter({ hasText: "Expenses" }).first(),
  ).toContainText("650.00");
  await expect(
    page.getByRole("heading", { name: "Sales by selling unit" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Update report" }).click();
  await expect(page.getByText("Report period updated.")).toBeVisible();
  await page.goto("/dashboard");
  await expect(
    page.getByRole("heading", { name: "A good day to grow." }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(root, ".local/frontend-dashboard.png"),
    fullPage: true,
  });
  await page.goto("/catalogue");
  await expect(
    page.getByRole("heading", { name: "Fresh from the farm.", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Loading your farm…", { exact: true }),
  ).toHaveCount(0);
  await page.screenshot({
    path: path.join(root, ".local/frontend-marketplace.png"),
    fullPage: true,
  });
});

test("M-Pesa provider failure stays unpaid and offers an explicit retry", async ({
  page,
  request,
}) => {
  const oid = await completedOrder(request);
  await login(page, "buyer");
  await page.goto(`/orders/${oid}`);
  await page.getByRole("button", { name: "Request sandbox payment" }).click();
  await expect(page.locator(".payment-intent")).toContainText("Queued");
  paymentStep("accepted");
  paymentStep("failed");
  await page
    .getByRole("button", { name: "Refresh status", exact: true })
    .click();
  await expect(page.locator(".payment-intent")).toContainText("Failed");
  await expect(
    page.getByRole("button", { name: "Retry sandbox payment" }),
  ).toBeVisible();
  await expect(page.locator(".status-strip")).toContainText("Unpaid");
});
