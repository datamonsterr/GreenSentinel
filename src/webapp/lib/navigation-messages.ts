import type { Locale } from "./locale";

type NavigationMessages = {
  opening: string; catalog: string; apps: string; cockpit: string;
  analytics: string; profile: string; search: string; searchPlaceholder: string;
  languages: string; english: string; vietnamese: string; e2e: string;
};

export const navigationMessages: Record<Locale, NavigationMessages> = {
  en: {
    opening: "Opening workspace…", catalog: "GreenSentinel app catalog",
    apps: "GreenSentinel Apps", cockpit: "Unified Adjudication",
    analytics: "Fleet Telemetry & Analytics", profile: "Analyst Profile & Audit",
    search: "Search workspace",
    searchPlaceholder: "Search driver ID, vehicle plate, geohash, rule tag (e.g. usr:8492, #ERR-02)...",
    languages: "Application language", english: "Switch language to English",
    vietnamese: "Switch language to Vietnamese", e2e: "E2E Mode",
  },
  vi: {
    opening: "Đang mở không gian làm việc…", catalog: "Danh mục ứng dụng GreenSentinel",
    apps: "Ứng dụng GreenSentinel", cockpit: "Xét duyệt hợp nhất",
    analytics: "Dữ liệu đội xe và phân tích", profile: "Hồ sơ chuyên viên và nhật ký",
    search: "Tìm kiếm không gian làm việc",
    searchPlaceholder: "Tìm mã tài xế, biển số xe, geohash, mã quy tắc (ví dụ: usr:8492, #ERR-02)...",
    languages: "Ngôn ngữ ứng dụng", english: "Chuyển ngôn ngữ sang tiếng Anh",
    vietnamese: "Chuyển ngôn ngữ sang tiếng Việt", e2e: "Chế độ E2E",
  },
};
