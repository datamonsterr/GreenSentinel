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

  it("returns dev backend for green-sentinel-dev.vercel.app", () => {
    setWindowHostname("green-sentinel-dev.vercel.app");
    expect(getApiBaseUrl()).toBe("https://greensentinel-backend-dev.up.railway.app");
  });

  it("returns staging backend for green-sentinel-staging", () => {
    setWindowHostname("green-sentinel-staging.up.railway.app");
    expect(getApiBaseUrl()).toBe("https://greensentinel-backend-staging.up.railway.app");
  });

  it("returns production backend for green-sentinel.vercel.app", () => {
    setWindowHostname("green-sentinel.vercel.app");
    expect(getApiBaseUrl()).toBe("https://greensentinel-backend-production.up.railway.app");
  });
});

