import { defineConfig, devices } from "@playwright/test";
import path from "node:path";
const root = path.resolve(import.meta.dirname, "..");
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${root}/.venv/bin/python scripts/e2e_server.py`,
      cwd: root,
      url: "http://127.0.0.1:8012/health",
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        DATABASE_URL:
          process.env.E2E_DATABASE_URL ||
          "postgresql+psycopg://farm:farm@localhost:5432/farm_frontend_e2e_test",
        JWT_SECRET: "isolated-browser-test-secret-over-32-characters",
        DARAJA_MODE: "disabled",
        SMS_MODE: "dry-run",
      },
    },
    {
      command: "npm run dev -- --port 5174",
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      env: { VITE_API_BASE_URL: "http://127.0.0.1:8012" },
    },
  ],
});
