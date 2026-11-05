import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTools,
} from "@/components/ai-elements/prompt-input";

describe("PromptInput Component", () => {
  it("renders textarea with placeholder and handles submit action", () => {
    const handleSubmit = vi.fn((e) => e.preventDefault());

    render(
      <PromptInput onSubmit={handleSubmit}>
        <PromptInputBody>
          <PromptInputTextarea
            placeholder="Hỏi trợ lý điều tra gian lận..."
            aria-label="Prompt input query"
          />
        </PromptInputBody>
        <PromptInputFooter>
          <PromptInputTools>
            <span>Tools</span>
          </PromptInputTools>
          <PromptInputSubmit aria-label="Gửi truy vấn" />
        </PromptInputFooter>
      </PromptInput>
    );

    const textarea = screen.getByPlaceholderText("Hỏi trợ lý điều tra gian lận...");
    expect(textarea).toBeInTheDocument();
    expect(textarea).toHaveAttribute("aria-label", "Prompt input query");

    fireEvent.change(textarea, { target: { value: "Phân tích cuốc xe #8492" } });
    expect(textarea).toHaveValue("Phân tích cuốc xe #8492");

    const submitBtn = screen.getByLabelText("Gửi truy vấn");
    expect(submitBtn).toBeInTheDocument();
  });
});
