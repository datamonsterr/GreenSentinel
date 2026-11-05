import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Message,
  MessageContent,
  MessageActions,
  MessageAction,
  MessageResponse,
} from "@/components/ai-elements/message";

describe("Message Component", () => {
  it("renders user and assistant messages with role classes", () => {
    const { container: userContainer } = render(
      <Message from="user" data-testid="user-msg">
        <MessageContent>User inquiry about trip</MessageContent>
      </Message>
    );

    expect(screen.getByText("User inquiry about trip")).toBeInTheDocument();
    expect(userContainer.firstChild).toHaveClass("is-user");

    const { container: asstContainer } = render(
      <Message from="assistant" data-testid="asst-msg">
        <MessageContent>Analyst AI copilot response</MessageContent>
      </Message>
    );

    expect(screen.getByText("Analyst AI copilot response")).toBeInTheDocument();
    expect(asstContainer.firstChild).toHaveClass("is-assistant");
  });

  it("renders MessageActions and MessageAction buttons", () => {
    render(
      <MessageActions>
        <MessageAction tooltip="Copy message">
          <span>Copy</span>
        </MessageAction>
      </MessageActions>
    );

    const actionBtn = screen.getByRole("button");
    expect(actionBtn).toBeInTheDocument();
    expect(screen.getByText("Copy")).toBeInTheDocument();
  });

  it("renders MessageResponse markdown streaming content", () => {
    render(
      <MessageResponse>
        {"### Forensic Verdict\n\nGPS telematics indicates route diversion."}
      </MessageResponse>
    );

    expect(screen.getByText(/Forensic Verdict/)).toBeInTheDocument();
    expect(screen.getByText(/GPS telematics indicates route diversion/)).toBeInTheDocument();
  });
});
