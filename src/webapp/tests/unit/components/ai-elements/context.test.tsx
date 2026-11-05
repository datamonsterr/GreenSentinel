import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Context,
  ContextTrigger,
  ContextContent,
  ContextContentHeader,
  ContextContentBody,
  ContextContentFooter,
  ContextInputUsage,
  ContextOutputUsage,
} from "@/components/ai-elements/context";

describe("Context Component", () => {
  it("renders Context trigger with formatted token usage percentage", () => {
    render(
      <Context
        usedTokens={4000}
        maxTokens={16000}
        usage={{
          inputTokens: 3000,
          outputTokens: 1000,
          totalTokens: 4000,
        } as any}
      >
        <ContextTrigger />
        <ContextContent>
          <ContextContentHeader />
          <ContextContentBody>
            <ContextInputUsage />
            <ContextOutputUsage />
          </ContextContentBody>
          <ContextContentFooter />
        </ContextContent>
      </Context>
    );

    // 4000 / 16000 = 25%
    expect(screen.getByText("25%")).toBeInTheDocument();
  });
});
