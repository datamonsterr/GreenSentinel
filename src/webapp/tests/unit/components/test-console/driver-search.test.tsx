import React from "react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import { DriverSearch } from "@/components/test-console/DriverSearch";
import * as testApiClient from "@/lib/testApiClient";

vi.mock("@/lib/testApiClient", async (importOriginal) => {
  const actual = await importOriginal<typeof testApiClient>();
  return {
    ...actual,
    searchClerkDrivers: vi.fn(),
    fetchClerkLinkedDrivers: vi.fn(),
  };
});

describe("DriverSearch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  const mockDrivers: testApiClient.ClerkLinkedDriver[] = [
    {
      driver_id: "drv-clerk-101",
      display_name: "Nguyen Van A",
      email: "driver.a@example.com",
      principal_id: "user_clerk_101",
      vehicle_id: "veh-1",
      license_plate: "29A-12345",
    },
  ];

  it("does not search when query length is less than 3 chars", async () => {
    render(<DriverSearch selectedDriver={null} onSelectDriver={vi.fn()} />);

    const input = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(input, { target: { value: "dr" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });

    expect(testApiClient.searchClerkDrivers).not.toHaveBeenCalled();
  });

  it("debounces search by 300ms for queries >= 3 chars", async () => {
    vi.mocked(testApiClient.searchClerkDrivers).mockResolvedValue(mockDrivers);

    render(<DriverSearch selectedDriver={null} onSelectDriver={vi.fn()} />);

    const input = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(input, { target: { value: "driver" } });

    // Not called immediately
    expect(testApiClient.searchClerkDrivers).not.toHaveBeenCalled();

    // Advance to 299ms - still not called
    await act(async () => {
      await vi.advanceTimersByTimeAsync(299);
    });
    expect(testApiClient.searchClerkDrivers).not.toHaveBeenCalled();

    // Advance the final millisecond - now called exactly once
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });

    expect(testApiClient.searchClerkDrivers).toHaveBeenCalledTimes(1);
    expect(testApiClient.searchClerkDrivers).toHaveBeenCalledWith("driver");

    expect(screen.getByText("Nguyen Van A")).toBeInTheDocument();
    expect(screen.getByText("driver.a@example.com")).toBeInTheDocument();
  });

  it("renders empty state when search returns no drivers", async () => {
    vi.mocked(testApiClient.searchClerkDrivers).mockResolvedValue([]);

    render(<DriverSearch selectedDriver={null} onSelectDriver={vi.fn()} />);

    const input = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(input, { target: { value: "unknown@example.com" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });

    expect(screen.getByTestId("driver-search-empty")).toBeInTheDocument();
  });

  it("renders error state when API request fails", async () => {
    vi.mocked(testApiClient.searchClerkDrivers).mockRejectedValue(new Error("Clerk API unavailable"));

    render(<DriverSearch selectedDriver={null} onSelectDriver={vi.fn()} />);

    const input = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(input, { target: { value: "driver" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });

    expect(screen.getByTestId("driver-search-error")).toHaveTextContent("Clerk API unavailable");
  });

  it("triggers onSelectDriver with chosen Clerk driver and renders selected card", async () => {
    vi.mocked(testApiClient.searchClerkDrivers).mockResolvedValue(mockDrivers);
    const handleSelect = vi.fn();

    const { rerender } = render(
      <DriverSearch selectedDriver={null} onSelectDriver={handleSelect} />
    );

    const input = screen.getByLabelText("Tìm tài xế");
    fireEvent.change(input, { target: { value: "driver" } });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(350);
    });

    expect(screen.getByText("Nguyen Van A")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Nguyen Van A"));
    expect(handleSelect).toHaveBeenCalledWith(mockDrivers[0]);

    // Rerender with selected driver
    rerender(
      <DriverSearch selectedDriver={mockDrivers[0]} onSelectDriver={handleSelect} />
    );

    expect(screen.getByTestId("selected-driver-card")).toBeInTheDocument();
    expect(screen.getByText("Nguyen Van A")).toBeInTheDocument();
    expect(screen.getByText("driver.a@example.com")).toBeInTheDocument();
    expect(screen.getByText(/29A-12345/)).toBeInTheDocument();

    // Deselect
    const deselectBtn = screen.getByLabelText("Đổi tài xế");
    fireEvent.click(deselectBtn);
    expect(handleSelect).toHaveBeenCalledWith(null);
  });
});
