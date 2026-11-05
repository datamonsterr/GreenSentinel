import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { TripPipeline } from "@/components/test-console/TripPipeline";
import type { TestRunTraceStage } from "@/lib/testApiClient";

describe("TripPipeline", () => {
  const sampleStages: TestRunTraceStage[] = [
    {
      stage: "created",
      state: "done",
      occurred_at: "2026-10-17T01:00:00Z",
      detail: { title: "Chuyến thử nghiệm 01" },
    },
    {
      stage: "driving_to_pickup",
      state: "done",
      occurred_at: "2026-10-17T01:01:00Z",
      detail: null,
    },
    {
      stage: "picked_up",
      state: "active",
      occurred_at: "2026-10-17T01:02:00Z",
      detail: null,
    },
    {
      stage: "driving_to_destination",
      state: "waiting",
      occurred_at: null,
      detail: null,
    },
    {
      stage: "completed",
      state: "waiting",
      occurred_at: null,
      detail: null,
    },
    {
      stage: "published",
      state: "waiting",
      occurred_at: null,
      detail: null,
    },
    {
      stage: "classifier_received",
      state: "waiting",
      occurred_at: null,
      detail: null,
    },
    {
      stage: "classified",
      state: "waiting",
      occurred_at: null,
      detail: null,
    },
    {
      stage: "case_created",
      state: "waiting",
      occurred_at: null,
      detail: null,
    },
  ];

  it("renders all 9 stages in order", () => {
    render(<TripPipeline stages={sampleStages} status="RUNNING" />);

    expect(screen.getByTestId("pipeline-stage-1")).toHaveAttribute("data-stage-key", "created");
    expect(screen.getByTestId("pipeline-stage-2")).toHaveAttribute("data-stage-key", "driving_to_pickup");
    expect(screen.getByTestId("pipeline-stage-3")).toHaveAttribute("data-stage-key", "picked_up");
    expect(screen.getByTestId("pipeline-stage-4")).toHaveAttribute("data-stage-key", "driving_to_destination");
    expect(screen.getByTestId("pipeline-stage-5")).toHaveAttribute("data-stage-key", "completed");
    expect(screen.getByTestId("pipeline-stage-6")).toHaveAttribute("data-stage-key", "published");
    expect(screen.getByTestId("pipeline-stage-7")).toHaveAttribute("data-stage-key", "classifier_received");
    expect(screen.getByTestId("pipeline-stage-8")).toHaveAttribute("data-stage-key", "classified");
    expect(screen.getByTestId("pipeline-stage-9")).toHaveAttribute("data-stage-key", "case_created");
  });

  it("highlights the active stage as current", () => {
    render(<TripPipeline stages={sampleStages} status="RUNNING" />);

    expect(screen.getByTestId("pipeline-stage-3")).toHaveAttribute("data-current", "true");
    expect(screen.getByTestId("pipeline-stage-1")).toHaveAttribute("data-current", "false");
  });

  it("shows detail modal when stage is clicked and closes on close button", () => {
    render(<TripPipeline stages={sampleStages} status="RUNNING" />);

    const stage1 = screen.getByTestId("pipeline-stage-1");
    fireEvent.click(stage1);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("stage-detail-json")).toHaveTextContent("Chuyến thử nghiệm 01");

    const closeBtn = screen.getByLabelText("Đóng chi tiết");
    fireEvent.click(closeBtn);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
