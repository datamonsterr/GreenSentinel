import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import { Loader } from "@/components/ai-elements/loader";

describe("Loader Component", () => {
  it("renders animated spinner loader with SVG title", () => {
    const { container } = render(<Loader size={20} className="text-primary" />);

    const spinner = container.querySelector(".animate-spin");
    expect(spinner).toBeInTheDocument();

    const svg = container.querySelector("svg");
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute("width", "20");
    expect(svg).toHaveAttribute("height", "20");
  });
});
