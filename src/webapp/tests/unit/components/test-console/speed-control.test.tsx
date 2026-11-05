import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { SpeedControl } from "@/components/test-console/SpeedControl";

describe("SpeedControl", () => {
  it("renders current factor and highlights matching preset button", () => {
    render(<SpeedControl value={5} onChange={vi.fn()} />);

    expect(screen.getByTestId("speed-factor-display")).toHaveTextContent("5x");
    const btn5 = screen.getByRole("button", { name: "Tốc độ 5x" });
    expect(btn5.className).toContain("bg-primary");
  });

  it("calls onChange when slider value changes", () => {
    const handleChange = vi.fn();
    render(<SpeedControl value={1} onChange={handleChange} />);

    const slider = screen.getByLabelText("Thanh trượt tốc độ mô phỏng");
    fireEvent.change(slider, { target: { value: "10" } });
    expect(handleChange).toHaveBeenCalledWith(10);
  });

  it("calls onChange when preset button is clicked", () => {
    const handleChange = vi.fn();
    render(<SpeedControl value={1} onChange={handleChange} />);

    const btn10 = screen.getByRole("button", { name: "Tốc độ 10x" });
    fireEvent.click(btn10);
    expect(handleChange).toHaveBeenCalledWith(10);
  });

  it("respects disabled prop", () => {
    render(<SpeedControl value={2} onChange={vi.fn()} disabled={true} />);

    expect(screen.getByLabelText("Thanh trượt tốc độ mô phỏng")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Tốc độ 2x" })).toBeDisabled();
  });
});
