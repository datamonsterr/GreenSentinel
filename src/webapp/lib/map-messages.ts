import type { Locale } from "@/lib/locale";

export type MapMessages = {
  centerTrip: string;
  followDriver: string;
  followingDriver: string;
  followTitle: string;
  followingTitle: string;
  route: string;
  speedTitle: string;
  gpsTitle: string;
  traffic: string;
  breadcrumbs: string;
  roadRoute: string;
  hotspots: string;
  probeCheck: string;
  dataStatus: string;
  unavailable: string;
  noData: string;
  noTraffic: string;
  loadingMap: string;
  noTripData: string;
  noRoute: string;
  dataGap: string;
  closeRoute: string;
  distance: string;
  duration: string;
  signals: string;
  density: string;
  clear: string;
  congested: string;
  corroboration: string;
  multiDriverCorroboration: string;
  refuted: string;
  corroborated: string;
  insufficientData: string;
  suspectDriver: string;
  publicService: string;
  peerDrivers: string;
  conclusion: string;
  pause: string;
  replay: string;
  estimatedRoute: string;
  gpsGapLastPosition: string;
  unknownRouteLastPosition: string;
  recordedGps: string;
  noGps: string;
  position: string;
  startRange: string;
  endRange: string;
  replayTime: string;
  startTime: string;
  endTime: string;
  stallPoint: string;
  daviDrift: string;
  ambient: string;
};

const en: MapMessages = {
  centerTrip: "Center whole trip", followDriver: "Follow driver", followingDriver: "Follow vehicle: On",
  followTitle: "Follow the driver's location in real time", followingTitle: "Following the driver's vehicle (click to stop)",
  route: "Route:", speedTitle: "Current vehicle speed", gpsTitle: "GPS latency / network signal quality",
  traffic: "Traffic", breadcrumbs: "Breadcrumbs", roadRoute: "Road route", hotspots: "Hotspots", probeCheck: "Probe Check",
  dataStatus: "Map data status", unavailable: "Unavailable", noData: "No data yet", noTraffic: "No traffic data", loadingMap: "Loading map…",
  noTripData: "No trip data", noRoute: "No route", dataGap: "Data gap:", closeRoute: "Close route details",
  distance: "Distance:", duration: "Duration:", signals: "Signals:", density: "Density:", clear: "Clear", congested: "Congested",
  corroboration: "Corroboration", multiDriverCorroboration: "MULTI-DRIVER TRAFFIC CORROBORATION", refuted: "Refuted",
  corroborated: "Corroborated", insufficientData: "Insufficient data", suspectDriver: "Subject driver:", publicService: "Public service",
  peerDrivers: "Peer drivers:", conclusion: "Conclusion:", pause: "Pause", replay: "Replay", estimatedRoute: "Estimated route",
  gpsGapLastPosition: "GPS gap · last position", unknownRouteLastPosition: "Unknown route · last position", recordedGps: "Recorded GPS",
  noGps: "No GPS", position: "Position:", startRange: "Start time range", endRange: "End time range", replayTime: "Replay time",
  startTime: "Start time", endTime: "Trip end time (Destination)", stallPoint: "Stall point:", daviDrift: "DAVI drift:", ambient: "Ambient:"
};

const vi: MapMessages = {
  centerTrip: "Căn giữa toàn bộ chuyến đi", followDriver: "Theo dõi xe", followingDriver: "Theo dõi xe: Bật",
  followTitle: "Theo dõi vị trí tài xế theo thời gian thực", followingTitle: "Đang tự động bám theo xe tài xế (click để dừng)",
  route: "Tuyến:", speedTitle: "Vận tốc tức thời của phương tiện", gpsTitle: "Độ trễ GPS / Chất lượng tín hiệu mạng",
  traffic: "Giao thông", breadcrumbs: "Hành trình GPS", roadRoute: "Lộ trình đường bộ", hotspots: "Điểm nóng", probeCheck: "Đối chứng",
  dataStatus: "Trạng thái dữ liệu bản đồ", unavailable: "Không khả dụng", noData: "Chưa có dữ liệu", noTraffic: "Chưa có dữ liệu giao thông", loadingMap: "Đang tải bản đồ…",
  noTripData: "Chưa có dữ liệu hành trình", noRoute: "Chưa có tuyến đường", dataGap: "Khoảng trống dữ liệu:", closeRoute: "Đóng thông tin tuyến",
  distance: "Khoảng cách:", duration: "Thời gian:", signals: "Tín hiệu:", density: "Mật độ:", clear: "Thông thoáng", congested: "Ùn ứ",
  corroboration: "Đối chứng", multiDriverCorroboration: "ĐỐI CHỨNG GIAO THÔNG ĐA TÀI XẾ", refuted: "Bác bỏ",
  corroborated: "Xác nhận", insufficientData: "Chưa đủ dữ liệu", suspectDriver: "Tài xế đối tượng:", publicService: "Dịch vụ công cộng",
  peerDrivers: "Tài xế cùng tuyến:", conclusion: "Kết luận:", pause: "Tạm dừng", replay: "Phát lại", estimatedRoute: "Ước tính theo đường",
  gpsGapLastPosition: "Mất GPS · vị trí cuối", unknownRouteLastPosition: "Chưa rõ đường · vị trí cuối", recordedGps: "GPS ghi nhận",
  noGps: "Chưa có GPS", position: "Vị trí:", startRange: "Bắt đầu khoảng thời gian", endRange: "Kết thúc khoảng thời gian", replayTime: "Thời điểm phát lại",
  startTime: "Thời gian bắt đầu", endTime: "Thời gian kết thúc chuyến (Đích đến)", stallPoint: "Điểm dừng:", daviDrift: "Độ lệch DAVI:", ambient: "Môi trường:"
};

export const mapMessages: Record<Locale, MapMessages> = { en, vi };
