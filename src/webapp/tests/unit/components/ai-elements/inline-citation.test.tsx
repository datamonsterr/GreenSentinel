import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  InlineCitation,
  InlineCitationText,
  InlineCitationCard,
  InlineCitationCardTrigger,
  InlineCitationCardBody,
  InlineCitationSource,
  InlineCitationQuote,
} from "@/components/ai-elements/inline-citation";

describe("InlineCitation Component", () => {
  it("renders inline citation trigger with source host and count badge", () => {
    render(
      <InlineCitation>
        <InlineCitationText>Theo quy chuẩn vận tải</InlineCitationText>
        <InlineCitationCard>
          <InlineCitationCardTrigger
            sources={["https://vinuni.edu.vn/policy", "https://vinuni.edu.vn/faq"]}
          />
          <InlineCitationCardBody>
            <InlineCitationSource
              title="Chính sách vận hành"
              url="https://vinuni.edu.vn/policy"
              description="Quy định xử phạt gian lận cuốc xe"
            />
            <InlineCitationQuote>
              {"Tài xế không được cố ý kéo dài thời gian đón trả khách."}
            </InlineCitationQuote>
          </InlineCitationCardBody>
        </InlineCitationCard>
      </InlineCitation>
    );

    expect(screen.getByText("Theo quy chuẩn vận tải")).toBeInTheDocument();
    expect(screen.getByText(/vinuni\.edu\.vn/)).toBeInTheDocument();
  });
});
