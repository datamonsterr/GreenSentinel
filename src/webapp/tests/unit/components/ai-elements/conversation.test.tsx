import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Conversation,
  ConversationContent,
  ConversationEmptyState,
} from "@/components/ai-elements/conversation";

describe("Conversation Component", () => {
  it("renders Conversation with role='log' for accessibility", () => {
    render(
      <Conversation data-testid="conversation-root">
        <ConversationContent>
          <div>Message 1</div>
        </ConversationContent>
      </Conversation>
    );

    const logElement = screen.getByRole("log");
    expect(logElement).toBeInTheDocument();
    expect(screen.getByText("Message 1")).toBeInTheDocument();
  });

  it("renders ConversationEmptyState with title and description", () => {
    render(
      <ConversationEmptyState
        title="Bắt đầu hội thoại"
        description="Đặt câu hỏi về chuyến đi hoặc bằng chứng gian lận"
      />
    );

    expect(screen.getByText("Bắt đầu hội thoại")).toBeInTheDocument();
    expect(
      screen.getByText("Đặt câu hỏi về chuyến đi hoặc bằng chứng gian lận")
    ).toBeInTheDocument();
  });
});
