# Tài Liệu Brief: Vấn Đề & Giải Pháp
*Dự án: GreenSM Xanh Bike — Release 1 Human-in-the-Loop (HITL) Enforcement*  
*Tài liệu đối chiếu gốc: [`docs/ba/PRD.md`](PRD.md) | Phân kỳ: [`docs/ba/MVP.md`](MVP.md)*

---

## 1. Bối Cảnh Vận Hành & Lỗ Hổng Kỹ Thuật
- **Đối tượng:** Dịch vụ xe máy điện Xanh Bike thuộc [Green Smart Mobility (GSM)](https://www.greensm.com/).
- **Bất đối xứng dữ liệu:** Khác với ô tô điện (có camera cabin kép và hộp đen TCU chuẩn CAN-bus), xe máy điện **100% phụ thuộc vào điện thoại thông minh của tài xế**.
- **Lỗ hổng & Nguy cơ:**
  - Không có thiết bị ghi hình hoặc cảm biến vật lý cố định.
  - GPS di động chịu nhiễu đô thị nghiêm trọng (dội sóng tại hẻm nhỏ, nhà cao tầng).
  - Rủi ro gian lận cao: Tài xế dùng ứng dụng giả lập vị trí (Fake GPS / Mock Provider), tắt app hoặc ngắt kết nối mạng có chủ đích.
- **Ràng buộc chi phí:** Không thể lắp thêm hộp đen/camera cho toàn bộ đội xe máy vì chi phí thiết bị và bảo trì quá lớn. Bắt buộc xử lý bài toán hoàn toàn dựa trên dữ liệu viễn thông app và API điều phối.

---

## 2. Vấn Đề Cốt Lõi: Khủng Hoảng Kép (Dual-Perspective Crisis)

Hệ thống Xanh Bike rơi vào thế bế tắc đồng thời ở cả hai chiều:

### 2.1. Phía Khách Hàng (Nạn nhân của Tài xế ép hủy cuốc — DIC / `ERR-02`)
- **Hành vi gian lận:** Khi được gán các cuốc xe không mong muốn (quãng đường ngắn, giờ cao điểm tắc đường, điểm đến khó đón khách mới), tài xế không bấm hủy trực tiếp (để tránh bị phạt Tỷ lệ nhận cuốc - AR và Tỷ lệ hoàn thành - CR). Thay vào đó, tài xế **cố tình đứng yên hoặc di chuyển ra xa điểm đón** ($DAVI \le 0$).
- **Hậu quả:** Ép hành khách hết kiên nhẫn phải tự bấm hủy. Khách hàng bị mắc kẹt 10–20 phút, mất quyền lợi mã giảm giá (voucher), mất niềm tin và chuyển sang dịch vụ đối thủ (Grab, Be).

### 2.2. Phía Vận Hành (Quá tải thẩm định & Phạt oan tài xế trung thực)
- **Áp lực rà soát:** Hệ thống ghi nhận hơn **2.000 cảnh báo bất thường/ngày**. Chuyên viên chống gian lận (Fraud Analyst) phải mở nhiều công cụ để dựng lại bản đồ tọa độ GPS thô, kiểm tra trạm phát sóng di động và nhật ký điều phối.
- **Tồn đọng & Oan sai:** Thời gian xử lý thủ công mất **10–15 phút/ca**, dẫn đến **75% hồ sơ bị dồn ứ** quá 24 giờ. Đồng thời, **tỷ lệ phạt oan (False Alarm Ratio - FAR) vượt mức 35%**, trừng phạt nhầm những tài xế trung thực chỉ đang kẹt xe ngoài ý muốn hoặc mất sóng cục bộ.

---

## 3. Giải Pháp: Chu Trình Giám Sát Có Con Người (HITL Lifecycle — L06)

Thiết lập một quy trình khép kín kết hợp giữa can thiệp thời gian thực và tự động hóa hồ sơ pháp y số:

```
[ Telemetry Real-time ] ──> [ Chấm điểm Động học & Cứu hộ Khách ] ──> [ Cổng Giải trình Tài xế ]
                                                                                │
                                                                                ▼
[ 100% Quyết định có Người ký ] <── [ Buồng lái Thẩm định Cockpit ] <── [ Multi-Agent LangGraph ]
```

1. **Cứu hộ hành khách thời gian thực (`FR-L06-01`–`06`):**
   - Thuật toán động học ($DAVI$) nhận diện hành vi cố tình đứng yên hoặc di chuyển xa dần điểm đón.
   - Gửi pop-up hỏi ý kiến với lời văn trung lập, cho phép khách chọn đổi tài xế khác ngay lập tức mà **giữ nguyên 100% giá ban đầu, voucher, điểm đón và điểm đến**.
2. **Cổng nộp chứng cứ an toàn cho tài xế (`FR-L06-07`–`09`):**
   - Sau khi chuyến kết thúc, tài xế nhận thông báo và khung giờ giải trình.
   - **Chỉ cho phép gửi khi xe đã đứng yên** (nghiêm cấm quay video khi đang lái xe). Hệ thống tự động phân tách lỗi rớt mạng/lỗi ứng dụng của nền tảng để không phạt oan.
3. **Tổng hợp chứng cứ tự động bằng Multi-Agent LangGraph (`FR-L06-10`):**
   - Tác tử AI tự động xâu chuỗi GPS breadcrumbs, đối chiếu lộ trình OSRM, rà soát 5 nhóm mã lỗi vi phạm (`ERR-01` đến `ERR-05`), tổng hợp giải trình và xuất bản tóm tắt pháp y tự nhiên.
4. **Buồng lái Thẩm định Tập trung (Trọng tâm Phase 1 MVP — [`MVP.md`](MVP.md)):**
   - Thay thế việc tra cứu thủ công bằng giao diện hợp nhất (tải dữ liệu $\le 1.5$s).
   - Chuyên viên thao tác 1 chạm theo phân quyền: `Bỏ qua (Oan sai)`, `Cảnh báo`, `Phạt tiền`, `Khóa tài khoản`, hoặc `Leo thang`.
   - Rút ngắn thời gian xử lý từ 12.5 phút xuống **< 45 giây/ca**.
5. **Tuân thủ HITL Tuyệt đối & Kháng cáo Ẩn danh (`FR-L06-12`–`17`):**
   - **Không phạt tự động bằng thuật toán**: Mọi quyết định chế tài tài chính hoặc khóa tài khoản đều bắt buộc có chữ ký số và lý do từ chuyên viên con người.
   - Phúc khảo cấp 2 được thiết kế ẩn danh (blinded review): Giấu hoàn toàn quyết định và danh tính của người duyệt trước để loại bỏ thiên kiến neo (anchoring bias).

---

## 4. Mục Tiêu Định Lượng & Tác Động

| Chỉ số | Định nghĩa / Công thức | Baseline Hiện tại | Mục tiêu Dự án | Mức độ Cải thiện |
|---|---|---|---|---|
| **Mean Time to Resolve (MTTR)** | Thời gian trung bình chuyên viên điều tra 1 ca | 12.5 phút (10–15 min) | **< 45 giây** | **Rút ngắn 94%** thời gian xử lý |
| **Triage Backlog** | Tỷ lệ hồ sơ nghi vấn tồn đọng quá 24 giờ | ~75% | **< 5%** | Giải tỏa dứt điểm ùn tắc vận hành |
| **False Alarm Ratio (FAR)** | Tỷ lệ tài xế bị xử phạt oan được lật lại án | > 35% | **< 5%** | Giảm thiểu tranh chấp và bảo vệ đối tác |
| **Tính toàn vẹn HITL** | Tỷ lệ án phạt/khóa tài khoản có người phê duyệt | 100% | **100.0%** | Tuyệt đối không để AI tự động xử phạt |
| **Tỷ lệ khách rời bỏ vì DIC** | Tỷ lệ hành khách bỏ dùng dịch vụ sau sự cố DIC | Đang theo dõi | **Giảm 50%** | Bảo vệ doanh thu và lòng trung thành |

---

## 5. Phân Kỳ Triển Khai (Phasing)
- **Phase 1 (MVP Demo Day):** Hoàn thiện **Buồng lái Thẩm định Gian lận (Adjudication Cockpit)** tích hợp LangGraph Multi-Agent tổng hợp hồ sơ chứng cứ tự động ([`US-L06-04`](USER_STORIES.md#L94-L122), [`UC-L06-04`](USE_CASES.md#L73-L94)).
- **Phase 2:** Triển khai pop-up gợi ý đổi xe theo thời gian thực trên mobile, cơ chế điều phối giữ giá/voucher và cổng thu thập bằng chứng an toàn cho tài xế.
- **Phase 3:** Cơ chế phúc khảo ẩn danh, hàng đợi hiệu chuẩn chính sách hàng tuần và quy trình tự động rollback khi phát hiện chỉ số bất thường.
