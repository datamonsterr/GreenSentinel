import type { Locale } from "@/lib/locale";

export const cockpitMessages = {
  en: {
    noData: "No data yet",
    copy: "Copy",
    tripId: "Trip ID",
    fare: "Fare",
    driverStatus: "Driver status",
    match: "Matching",
    customer: "Customer",
    driver: "Driver",
    agent: "GSupport agent",
    system: "System",
    noMessages: "No messages between driver and customer were recorded for this trip.",
    noEvents: "Status changes and cancel events appear here once recorded.",
    duration: "Duration until next status",
  },
  vi: {
    noData: "Chưa có dữ liệu",
    copy: "Sao chép",
    tripId: "Mã chuyến đi",
    fare: "Giá cước",
    driverStatus: "Trạng thái tài xế",
    match: "Ghép chuyến",
    customer: "Khách hàng",
    driver: "Tài xế",
    agent: "Trợ lý GSupport",
    system: "Hệ thống",
    noMessages: "Chưa ghi nhận tin nhắn giữa tài xế và khách hàng cho chuyến này.",
    noEvents: "Thay đổi trạng thái và sự kiện huỷ chuyến sẽ hiển thị tại đây.",
    duration: "Thời lượng đến trạng thái kế tiếp",
  },
} as const satisfies Record<Locale, Record<string, string>>;

export function numberLocale(locale: Locale): string {
  return locale === "vi" ? "vi-VN" : "en-US";
}

export function formatClock(value: string | null | undefined, locale: Locale): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? null
    : date.toLocaleTimeString(numberLocale(locale), { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
