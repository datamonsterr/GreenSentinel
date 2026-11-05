import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  DriverCardWidget,
  ChoiceSelectorWidget,
  ListSelectorWidget,
  TicketPreviewWidget,
  WeatherWidget,
  TrafficWidget,
  renderChatContent,
} from "@/components/ui/chat-widgets";

describe("Cockpit Chat Widgets & XML Parsers", () => {
  it("renders DriverCardWidget with complete driver operational metrics", () => {
    const data = {
      driver_id: "drv-8492-nguyen-van-a",
      full_name: "Nguyễn Văn A",
      vehicle_plate: "29E-123.45",
      vehicle_model: "Green SM Car - VF e34",
      rating: 4.82,
      acceptance_rate: "89.5%",
      completion_rate: "91.0%",
      account_status: "ACTIVE",
      total_trips: 1250,
      badge: "Xanh SM Partner",
    };

    render(<DriverCardWidget data={data} />);

    expect(screen.getByText("Nguyễn Văn A")).toBeInTheDocument();
    expect(screen.getByText("drv-8492-nguyen-van-a")).toBeInTheDocument();
    expect(screen.getByText(/29E-123.45/)).toBeInTheDocument();
    expect(screen.getByText("4.82")).toBeInTheDocument();
    expect(screen.getByText("89.5%")).toBeInTheDocument();
    expect(screen.getByText("ACTIVE")).toBeInTheDocument();
  });

  it("renders ChoiceSelectorWidget and handles selection callback", () => {
    const onSelectChoice = vi.fn();
    const data = {
      title: "Phương án xử lý kiến nghị",
      description: "Chọn chế tài phù hợp với tài xế",
      options: [
        { id: "opt1", label: "Phạt cảnh cáo và nhắc nhở", detail: "Vi phạm lần 1" },
        { id: "opt2", label: "Phạt 500.000đ và tạm đình chỉ 24h", detail: "Vi phạm nghiêm trọng" },
      ],
    };

    render(<ChoiceSelectorWidget data={data} onSelectChoice={onSelectChoice} />);

    expect(screen.getByText("Phương án xử lý kiến nghị")).toBeInTheDocument();
    expect(screen.getByText("Phạt cảnh cáo và nhắc nhở")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Phạt cảnh cáo và nhắc nhở"));
    expect(onSelectChoice).toHaveBeenCalledWith("opt1", "Phạt cảnh cáo và nhắc nhở");
  });

  it("renders ListSelectorWidget with multi-driver vehicle sharing warning", () => {
    const onSelectCase = vi.fn();
    const data = {
      vehicle_plate: "29E-123.45",
      multi_driver_sharing_flag: true,
      risk_summary: "Phát hiện nhiều tài xế dùng chung phương tiện",
      related_cases: [
        {
          case_id: "018f2f4e-a000-7000-8000-000000000001",
          driver_name: "Nguyễn Văn A",
          plate_number: "29E-123.45",
          status: "CLOSED",
          priority: "P1",
        },
        {
          case_id: "018f2f4e-a000-7000-8000-000000000002",
          driver_name: "Trần Văn B",
          plate_number: "29E-123.45",
          status: "IN_REVIEW",
          priority: "P0",
        },
      ],
    };

    render(<ListSelectorWidget data={data} onSelectCase={onSelectCase} />);

    expect(screen.getAllByText(/29E-123.45/).length).toBeGreaterThan(0);
    expect(screen.getByText("CẢNH BÁO TRÁO XE")).toBeInTheDocument();
    expect(screen.getByText("018f2f4e-a000-7000-8000-000000000001")).toBeInTheDocument();

    fireEvent.click(screen.getByText("018f2f4e-a000-7000-8000-000000000001"));
    expect(onSelectCase).toHaveBeenCalledWith("018f2f4e-a000-7000-8000-000000000001");
  });

  it("renders TicketPreviewWidget with fine amount and violation details", () => {
    const data = {
      ticket_id: "TCK-20260930-A1B2C3",
      driver_id: "drv-8492-nguyen-van-a",
      case_id: "018f2f4e-a000-7000-8000-000000000001",
      violation_code: "ERR-02",
      penalty_type: "FINE_AND_SUSPENSION",
      fine_amount_vnd: 500000,
      suspension_hours: 24,
      reason: "Cố tình dừng đỗ 210s nhằm ép hành khách hủy cuốc (DIC)",
      policy_clause: "Điều 14.2 Quy chế GreenSM",
    };

    render(<TicketPreviewWidget data={data} />);

    expect(screen.getByText("TCK-20260930-A1B2C3")).toBeInTheDocument();
    expect(screen.getByText("500,000 VNĐ")).toBeInTheDocument();
    expect(screen.getByText("Tạm khóa 24 giờ")).toBeInTheDocument();
    expect(screen.getByText("ERR-02")).toBeInTheDocument();
    expect(screen.getByText(/Điều 14.2 Quy chế GreenSM/)).toBeInTheDocument();
  });

  it("renders WeatherWidget and TrafficWidget correctly", () => {
    const weatherData = {
      temperature_c: 29.5,
      precipitation_mm: 45.0,
      wind_speed_kmh: 35.0,
      condition_desc: "Mưa to kèm dông sét",
      force_majeure: true,
      force_majeure_note: "Điều 12.2: Đủ điều kiện miễn trừ bất khả kháng",
    };

    render(<WeatherWidget data={weatherData} />);

    expect(screen.getByText("29.5°C")).toBeInTheDocument();
    expect(screen.getByText("45 mm")).toBeInTheDocument();
    expect(screen.getByText("Miễn trừ Điều 12.2")).toBeInTheDocument();

    const trafficData = {
      distance_km: 8.4,
      baseline_duration_sec: 720,
      observed_speed_kmh: 7.2,
      congestion_level: "heavy_gridlock",
      corroborates_delay: true,
      verdict: "Xác nhận ùn tắc giao thông nghiêm trọng",
    };

    render(<TrafficWidget data={trafficData} />);

    expect(screen.getByText("8.4 km")).toBeInTheDocument();
    expect(screen.getByText("12 phút")).toBeInTheDocument();
    expect(screen.getByText("7.2 km/h")).toBeInTheDocument();
    expect(screen.getByText("Xác nhận ùn tắc giao thông nghiêm trọng")).toBeInTheDocument();
  });

  it("renderChatContent parses XML tags and embeds interactive widgets seamlessly", () => {
    const rawText = `Chào bạn! Dưới đây là thông tin tài xế:\n<driver_card>{"driver_id": "drv-001", "full_name": "Lê Văn C", "account_status": "ACTIVE"}</driver_card>\nVà thời tiết hiện tại:\n<weather_widget>{"temperature_c": 31, "condition_desc": "Nắng gắt", "force_majeure": false}</weather_widget>`;

    render(<div>{renderChatContent(rawText)}</div>);

    expect(screen.getByText("Lê Văn C")).toBeInTheDocument();
    expect(screen.getByText("drv-001")).toBeInTheDocument();
    expect(screen.getByText("31°C")).toBeInTheDocument();
    expect(screen.getByText("Nắng gắt")).toBeInTheDocument();
  });
});
