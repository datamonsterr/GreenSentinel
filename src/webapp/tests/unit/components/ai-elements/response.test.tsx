import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Response } from "@/components/ai-elements/response";

describe("Response Component", () => {
  it("renders streaming markdown response with streamdown", () => {
    render(
      <Response>
        {"**Case Evaluation**: Confidence score is **0.87**."}
      </Response>
    );

    expect(screen.getByText("Case Evaluation")).toBeInTheDocument();
    expect(screen.getByText("0.87")).toBeInTheDocument();
  });
});
