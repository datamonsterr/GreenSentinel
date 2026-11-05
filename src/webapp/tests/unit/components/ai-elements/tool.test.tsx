import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  Tool,
  ToolHeader,
  ToolContent,
  ToolInput,
  ToolOutput,
} from "@/components/ai-elements/tool";

describe("Tool Component", () => {
  it("renders ToolHeader with tool name and status badge", () => {
    render(
      <Tool defaultOpen>
        <ToolHeader
          title="query_driver_history"
          type="tool-driver-history"
          state="output-available"
        />
        <ToolContent>
          <ToolInput input={{ driverId: "drv-123", days: 30 }} />
          <ToolOutput output={{ total_disputes: 2 }} errorText={undefined} />
        </ToolContent>
      </Tool>
    );

    expect(screen.getByText("query_driver_history")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Parameters")).toBeInTheDocument();
    expect(screen.getByText("Result")).toBeInTheDocument();
  });

  it("renders error state when errorText is present", () => {
    render(
      <Tool defaultOpen>
        <ToolHeader
          title="fetch_gis_telemetry"
          type="tool-gis"
          state="output-error"
        />
        <ToolContent>
          <ToolOutput output={null} errorText="Network timeout connecting to OSRM" />
        </ToolContent>
      </Tool>
    );

    expect(
      screen.getByRole("heading", { name: "Error" })
    ).toBeInTheDocument();
    expect(
      screen.getByText("Network timeout connecting to OSRM")
    ).toBeInTheDocument();
  });
});
