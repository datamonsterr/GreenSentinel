import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { DriverAuthBoundary } from "@/components/driver/driver-auth-boundary";
import { DriverI18nProvider } from "@/lib/driver/i18n-provider";
import * as apiClient from "@/lib/api-client";

let mockAuth: {
  getToken: ReturnType<typeof vi.fn>;
  isLoaded: boolean;
  userId: string | null;
} = {
  getToken: vi.fn(),
  isLoaded: true,
  userId: "user_test_123",
};

vi.mock("@clerk/nextjs", () => ({
  useAuth: () => mockAuth,
}));

vi.mock("@/lib/api-client", () => ({
  setApiTokenProvider: vi.fn(),
}));

function renderWithI18n(ui: React.ReactElement) {
  return render(<DriverI18nProvider locale="en">{ui}</DriverI18nProvider>);
}

describe("DriverAuthBoundary", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockAuth = {
      getToken: vi.fn().mockResolvedValue("initial-token"),
      isLoaded: true,
      userId: "user_test_123",
    };
  });

  it("renders loading message when auth is not loaded", () => {
    mockAuth = {
      getToken: vi.fn(),
      isLoaded: false,
      userId: null,
    };

    renderWithI18n(
      <DriverAuthBoundary>
        <div data-testid="driver-content">Driver Content</div>
      </DriverAuthBoundary>
    );

    expect(screen.getByRole("status")).toHaveTextContent("Loading session…");
    expect(screen.queryByTestId("driver-content")).not.toBeInTheDocument();
    expect(apiClient.setApiTokenProvider).not.toHaveBeenCalled();
  });

  it("renders loading message when userId is missing", () => {
    mockAuth = {
      getToken: vi.fn(),
      isLoaded: true,
      userId: null,
    };

    renderWithI18n(
      <DriverAuthBoundary>
        <div data-testid="driver-content">Driver Content</div>
      </DriverAuthBoundary>
    );

    expect(screen.getByRole("status")).toHaveTextContent("Loading session…");
    expect(screen.queryByTestId("driver-content")).not.toBeInTheDocument();
  });

  it("renders children and registers token provider when authenticated", async () => {
    renderWithI18n(
      <DriverAuthBoundary>
        <div data-testid="driver-content">Driver Content</div>
      </DriverAuthBoundary>
    );

    expect(screen.getByTestId("driver-content")).toBeInTheDocument();
    expect(apiClient.setApiTokenProvider).toHaveBeenCalledWith(expect.any(Function));

    // Verify token provider callback delegates to getToken
    const registeredProvider = vi.mocked(apiClient.setApiTokenProvider).mock.calls[0][0];
    expect(registeredProvider).not.toBeNull();
    const token = await registeredProvider?.({ skipCache: true });
    expect(token).toBe("initial-token");
    expect(mockAuth.getToken).toHaveBeenCalledWith({ skipCache: true });
  });

  it("cleans up token provider on unmount", () => {
    const { unmount } = renderWithI18n(
      <DriverAuthBoundary>
        <div data-testid="driver-content">Driver Content</div>
      </DriverAuthBoundary>
    );

    unmount();
    expect(apiClient.setApiTokenProvider).toHaveBeenLastCalledWith(null);
  });

  it("delegates to the updated getToken when getToken changes", async () => {
    const initialGetToken = vi.fn().mockResolvedValue("first-token");
    const updatedGetToken = vi.fn().mockResolvedValue("second-token");

    mockAuth = {
      getToken: initialGetToken,
      isLoaded: true,
      userId: "user_test_123",
    };

    const { rerender } = renderWithI18n(
      <DriverAuthBoundary>
        <div data-testid="driver-content">Driver Content</div>
      </DriverAuthBoundary>
    );

    const registeredProvider = vi.mocked(apiClient.setApiTokenProvider).mock.calls[0][0];
    expect(registeredProvider).not.toBeNull();

    // Rerender with new getToken
    mockAuth = {
      getToken: updatedGetToken,
      isLoaded: true,
      userId: "user_test_123",
    };

    rerender(
      <DriverI18nProvider locale="en">
        <DriverAuthBoundary>
          <div data-testid="driver-content">Driver Content</div>
        </DriverAuthBoundary>
      </DriverI18nProvider>
    );

    // Call the registered provider and ensure it calls updatedGetToken
    const token = await registeredProvider?.();
    expect(token).toBe("second-token");
    expect(updatedGetToken).toHaveBeenCalled();
  });
});
