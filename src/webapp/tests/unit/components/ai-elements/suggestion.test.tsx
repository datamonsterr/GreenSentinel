import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Suggestions, Suggestion } from "@/components/ai-elements/suggestion";

describe("Suggestion Component", () => {
  it("renders Suggestions list and dispatches onClick callback", () => {
    const handleClick = vi.fn();

    render(
      <Suggestions>
        <Suggestion
          suggestion="Kiểm tra GPS stall"
          onClick={handleClick}
        />
        <Suggestion
          suggestion="So sánh lộ trình OSRM"
          onClick={handleClick}
        />
      </Suggestions>
    );

    const btn1 = screen.getByText("Kiểm tra GPS stall");
    const btn2 = screen.getByText("So sánh lộ trình OSRM");

    expect(btn1).toBeInTheDocument();
    expect(btn2).toBeInTheDocument();

    fireEvent.click(btn1);
    expect(handleClick).toHaveBeenCalledWith("Kiểm tra GPS stall");
  });
});
