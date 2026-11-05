import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { getApiBaseUrl } from "@/lib/api-client";

describe("getApiBaseUrl — host matrix (BUG 2b)", () => {
  const originalWindow = global.window;
  const originalEnv = process.env;

  beforeEach(() => {
    process.env = { ...originalEnv };
    delete process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
  });

  afterEach(() => {
    process.env = originalEnv;
    if (originalWindow === undefined) {
      // @ts-expect-error test cleanup
      delete global.window;
    } else {
      global.window = originalWindow;
    }
  });

  function setWindowHostname(hostname: string) {
    global.window = {
      location: {
        hostname,
      },
    } as unknown as Window & typeof globalThis;
  }

  it("returns '' for localhost", () => {
    setWindowHostname("localhost");
    expect(getApiBaseUrl()).toBe("");
  });

  it("returns dev backend for p-063-dev.vercel.app", () => {
    setWindowHostname("p-063-dev.vercel.app");
    expect(getApiBaseUrl()).toBe("https://p063-backend-dev.up.railway.app");
  });

  it("returns staging backend for p-063-staging", () => {
    setWindowHostname("p-063-staging.up.railway.app");
    expect(getApiBaseUrl()).toBe("https://p063-backend-staging.up.railway.app");
  });

  it("returns production backend for p-063.vercel.app", () => {
    setWindowHostname("p-063.vercel.app");
    expect(getApiBaseUrl()).toBe("https://p063-backend-production.up.railway.app");
  });
});

