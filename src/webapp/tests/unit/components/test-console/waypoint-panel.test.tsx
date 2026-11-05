import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { WaypointPanel, WaypointItem } from "@/components/test-console/WaypointPanel";

describe("WaypointPanel", () => {
  const waypoints: WaypointItem[] = [
    { id: "wp-1", lat: 21.025, lon: 105.835, leg: "pickup", name: "Điểm 1" },
    { id: "wp-2", lat: 21.03, lon: 105.84, leg: "destination", name: "Điểm 2" },
  ];

  it("renders waypoints in numbered order", () => {
    render(
      <WaypointPanel
        waypoints={waypoints}
        isClickMode={false}
        onToggleClickMode={vi.fn()}
        onUpdateWaypointLeg={vi.fn()}
        onRemoveWaypoint={vi.fn()}
        onMoveWaypoint={vi.fn()}
      />
    );

    expect(screen.getByTestId("waypoint-badge-1")).toHaveTextContent("1");
    expect(screen.getByTestId("waypoint-badge-2")).toHaveTextContent("2");
    expect(screen.getByText("Điểm 1")).toBeInTheDocument();
    expect(screen.getByText("Điểm 2")).toBeInTheDocument();
  });

  it("triggers onUpdateWaypointLeg when leg select changes", () => {
    const handleUpdateLeg = vi.fn();
    render(
      <WaypointPanel
        waypoints={waypoints}
        isClickMode={false}
        onToggleClickMode={vi.fn()}
        onUpdateWaypointLeg={handleUpdateLeg}
        onRemoveWaypoint={vi.fn()}
        onMoveWaypoint={vi.fn()}
      />
    );

    const select = screen.getByLabelText("Chặng của điểm rẽ 1");
    fireEvent.change(select, { target: { value: "destination" } });
    expect(handleUpdateLeg).toHaveBeenCalledWith("wp-1", "destination");
  });

  it("triggers onMoveWaypoint when up/down buttons clicked", () => {
    const handleMove = vi.fn();
    render(
      <WaypointPanel
        waypoints={waypoints}
        isClickMode={false}
        onToggleClickMode={vi.fn()}
        onUpdateWaypointLeg={vi.fn()}
        onRemoveWaypoint={vi.fn()}
        onMoveWaypoint={handleMove}
      />
    );

    const downButtons = screen.getAllByLabelText("Di chuyển điểm rẽ xuống");
    fireEvent.click(downButtons[0]);
    expect(handleMove).toHaveBeenCalledWith("wp-1", "down");

    const upButtons = screen.getAllByLabelText("Di chuyển điểm rẽ lên");
    fireEvent.click(upButtons[1]);
    expect(handleMove).toHaveBeenCalledWith("wp-2", "up");
  });

  it("triggers onRemoveWaypoint when trash button clicked", () => {
    const handleRemove = vi.fn();
    render(
      <WaypointPanel
        waypoints={waypoints}
        isClickMode={false}
        onToggleClickMode={vi.fn()}
        onUpdateWaypointLeg={vi.fn()}
        onRemoveWaypoint={handleRemove}
        onMoveWaypoint={vi.fn()}
      />
    );

    const removeButtons = screen.getAllByLabelText("Xóa điểm rẽ");
    fireEvent.click(removeButtons[0]);
    expect(handleRemove).toHaveBeenCalledWith("wp-1");
  });

  it("disables controls when disabled prop is true", () => {
    render(
      <WaypointPanel
        waypoints={waypoints}
        isClickMode={false}
        onToggleClickMode={vi.fn()}
        onUpdateWaypointLeg={vi.fn()}
        onRemoveWaypoint={vi.fn()}
        onMoveWaypoint={vi.fn()}
        disabled={true}
      />
    );

    expect(screen.getByRole("button", { name: /Bật chế độ nhấp bản đồ để thêm điểm rẽ/i })).toBeDisabled();
    expect(screen.getByLabelText("Chặng của điểm rẽ 1")).toBeDisabled();
    screen.getAllByLabelText("Xóa điểm rẽ").forEach((btn) => expect(btn).toBeDisabled());
  });
});
