import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Sources,
  SourcesTrigger,
  SourcesContent,
  Source,
} from "@/components/ai-elements/sources";

describe("Sources Component", () => {
  it("renders source citation links with trigger count", () => {
    render(
      <Sources defaultOpen>
        <SourcesTrigger count={2} />
        <SourcesContent>
          <Source href="https://example.com/source1" title="Tài liệu tiền lệ 1" />
          <Source href="https://example.com/source2" title="Tài liệu tiền lệ 2" />
        </SourcesContent>
      </Sources>
    );

    expect(screen.getByText("Used 2 sources")).toBeInTheDocument();
    expect(screen.getByText("Tài liệu tiền lệ 1")).toBeInTheDocument();
    expect(screen.getByText("Tài liệu tiền lệ 2")).toBeInTheDocument();

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(2);
    expect(links[0]).toHaveAttribute("href", "https://example.com/source1");
  });
});
