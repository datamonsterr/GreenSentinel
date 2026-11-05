import { describe, it, expect } from "vitest";
import { shouldAutoSendCaseCheck, buildAutoSendPrompt } from "@/lib/driver/chat-auto-send";

describe("shouldAutoSendCaseCheck", () => {
  it("does not send before history has loaded", () => {
    expect(
      shouldAutoSendCaseCheck({ historyLoaded: false, messageCount: 0, alreadySent: false })
    ).toBe(false);
  });

  it("sends once history is loaded, thread is empty, and not yet sent", () => {
    expect(
      shouldAutoSendCaseCheck({ historyLoaded: true, messageCount: 0, alreadySent: false })
    ).toBe(true);
  });

  it("does not send when the thread already has messages", () => {
    expect(
      shouldAutoSendCaseCheck({ historyLoaded: true, messageCount: 2, alreadySent: false })
    ).toBe(false);
  });

  it("does not send twice (StrictMode-safe guard)", () => {
    expect(
      shouldAutoSendCaseCheck({ historyLoaded: true, messageCount: 0, alreadySent: true })
    ).toBe(false);
  });
});

describe("buildAutoSendPrompt", () => {
  it("interpolates the short case code into the template", () => {
    expect(buildAutoSendPrompt("Check details of case {code}", "#018F")).toBe(
      "Check details of case #018F"
    );
  });
});
