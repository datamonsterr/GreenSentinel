import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    testTimeout: 15_000,
    maxWorkers: process.env.CI ? 1 : 2,
    // Worker start timeout is not configurable; see patches/vitest@5.0.1.patch (#613).
    pool: "forks",
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./"),
    },
  },
});
