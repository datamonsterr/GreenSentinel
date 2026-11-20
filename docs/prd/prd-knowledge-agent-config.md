
# PRD – Kho tri thức và cấu hình cho Trợ lý AI giải trình

Nov 20, 2026 · @Pham Thanh Dat


## 1. Tổng quan

Tính năng này cho KSGL dạy Trợ lý AI giải trình (Driver Agent) ngay trên Admin Portal, và cho VH giúp agent khi agent bị kẹt trong phiên với tài xế (TX). Một nơi duy nhất gồm: kho tri thức (động cơ, hành vi, kịch bản, workflow), cổng kiểm thử và phát hành, cấu hình agent, và hàng chờ kêu cứu.

- Agent làm, người quyết. Agent đọc chính sách, phân tích, map vào kịch bản có sẵn và soạn nháp. Người chỉ làm các bước quyết định: nhập chính sách, chấp nhận hoặc sửa, phát hành, trả lời kêu cứu.
- KSGL sở hữu tri thức. Chỉ tri thức KSGL đã phát hành mới được Driver Agent dùng với TX thật.
- VH vẫn thẩm định case ở UNDER_REVIEW theo luồng hiện tại. VH là người nhận kêu cứu và cấu hình giới hạn lượt hỏi.
- Đi cùng PRD "Trợ lý AI hỗ trợ tài xế giải trình vi phạm" (phía Driver App). PRD đó đọc tri thức đã phát hành ở đây qua tool (mục 8.1).
Ngoài phạm vi: màn thẩm định case, biên bản, Depot, phê duyệt OPS DIR / MKP DIR, truy thu, hậu kiểm. Hành vi KSGL khai báo chỉ dùng cho agent, chưa dùng để mở ticket ở v1. Tri thức không chứa mức phạt, truy thu hay hướng xử lý (phần Detection).


## 2. Bối cảnh

Hôm nay muốn AI biết một động cơ, hành vi hay cách hỏi mới, KSGL phải mô tả cho PO, PO viết yêu cầu, dev làm tính năng rồi KSGL nghiệm thu. Mỗi vòng mất nhiều tuần, trong khi mỗi chính sách thưởng mới lại mở ra cách gian lận mới ngay khi có hiệu lực.


| # | Điểm yếu hôm nay | Hệ quả | Giải pháp |
|---|---|---|---|
| 1 | Chính sách mới được phân tích tay trên Excel, không nối với AI | AI không biết động cơ của chính sách mới cho đến khi dev cập nhật | US1, US2 |
| 2 | Tri thức của KSGL nằm trong bộ câu hỏi phản biện cố định theo rule | Đổi cách hỏi phải qua PO và dev | US3 |
| 3 | Case đã chốt không quay lại thành tri thức | AI hỏi lại từ đầu với case giống hệt | US5 |
| 4 | Không có cách thử trước khi bật | Một thay đổi sai ảnh hưởng mọi TX cùng loại | US6 |
| 5 | AI không có đường xin trợ giúp | Case lạ chạy hết lượt rồi gắn ai_inconclusive, VH tra tay từ đầu | US4 |
| 6 | Giới hạn lượt, SLA và ngưỡng nằm trong code | Đổi một con số cũng cần một lần phát hành | US7 |
| 7 | Không ai rà soát hội thoại có hệ thống | Lỗi giọng hỏi, tool thiếu chỉ lộ qua khiếu nại | US8 |

Nguyên tắc: dev xây khung một lần (danh mục tham số, trình soạn, cổng duyệt, tool cho agent). KSGL tự thêm nội dung. Dev chỉ vào khi cần tham số hoặc nguồn dữ liệu chưa có.


## 3. Mục tiêu và chỉ số

Rút thời gian từ lúc chính sách mới có hiệu lực đến lúc Driver Agent có tri thức đã duyệt cho chính sách đó, từ nhiều tuần xuống vài ngày, mà không tăng kết luận sai.


| Loại | Chỉ số | Mục tiêu |
|---|---|---|
| Primary | Thời gian từ chính sách có hiệu lực đến tri thức được phát hành | ≤ <SỐ_NGÀY> ngày |
| Phủ tri thức | % case khớp kịch bản đã duyệt; % case novel_scenario | Tăng / giảm theo tháng |
| Chất lượng đề xuất của agent | % đề xuất KSGL chấp nhận không sửa; % đề xuất bị bỏ | ≥ <MỤC_TIÊU_A>% / theo dõi |
| Chất lượng phát hành | % bản phát hành bị thu hồi trong 14 ngày; tỷ lệ khớp kết luận VH khi chạy lại | ≤ <MỤC_TIÊU_B>% / ≥ <MỤC_TIÊU_C>% |
| Kêu cứu | Thời gian VH trả lời (P50 / P90); % trả lời trong SLA; số kêu cứu lặp cùng chủ đề | Trong <SLA_KÊU_CỨU> phút; xu hướng giảm |
| Guardrail | % kết luận VH khác gợi ý AI; khiếu nại của TX về AI; số lần xem công thức ngoài quyền | Không tăng so với mốc trước pilot; 0 |


## 4. Vai trò và mức tự chủ của agent

Người chỉ làm các ô đỏ trong sơ đồ luồng: nhập chính sách, chấp nhận, sửa, đọc case và hội thoại khi kêu cứu. Phần còn lại do agent làm.


| Vai trò | Làm gì trong tính năng này |
|---|---|
| KSGL (fraud analyst) | Nhập chính sách; chấp nhận, sửa hoặc bỏ đề xuất; tự khai báo tri thức; duyệt phát hành (4 mắt); xử lý đề xuất của agent giám sát |
| VH (Vận hành) | Nhận thông báo kêu cứu, ưu tiên và trả lời agent; cấu hình giới hạn lượt hỏi N_max theo rule; tiếp tục thẩm định case theo luồng hiện tại |
| Agent phân tích tri thức | Đọc chính sách, đề xuất động cơ, hành vi, kịch bản và map vào kho có sẵn; tạo thẻ kịch bản nháp từ case đã chốt; biến câu trả lời kêu cứu thành tri thức nháp |
| Driver Agent | Chỉ đọc tri thức đã phát hành; gửi kêu cứu (PRD tài xế) |
| Agent giám sát | Đọc hội thoại định kỳ, đề xuất tri thức và tool mới |
| PO / Data | Xây khung, thêm tham số và tool mới khi được chấp nhận; đặt giới hạn trên / dưới cho cấu hình |

Mức tự chủ


| Agent tự làm | Agent làm, người phải duyệt | Agent không bao giờ làm |
|---|---|---|
| Đọc và trích quy tắc chi trả từ chính sách | Phát hành bất kỳ tri thức nào | Kết luận một case có gian lận hay không |
| Soạn nháp động cơ, hành vi, kịch bản, workflow | Sửa bản đã phát hành | Đặt ngưỡng thật hoặc bịa tham số không có trong danh mục |
| Map đề xuất vào kịch bản có sẵn | Đổi cấu hình agent | Đưa mức phạt, truy thu, hướng xử lý vào tri thức |
| Chạy thử trên case cũ, viết báo cáo khác biệt | Thêm tool hoặc nguồn dữ liệu | Dùng tri thức nháp với TX thật |
| Gửi kêu cứu và thông báo VH | Trả lời kêu cứu (VH trả lời) | Cho TX xem động cơ, công thức hay case của TX khác |


## 5. Luồng tổng thể

Hai vòng chạy song song và cùng đổ vào một kho tri thức. Vòng KSGL đưa chính sách mới vào kho. Vòng kêu cứu đưa cái Driver Agent chưa biết về kho qua VH.

luồng kho tri thức · vòng chính sách và vòng kêu cứu

Hàng trên là vòng chính sách, hàng dưới là vòng kêu cứu; cả hai quay về bước KSGL chấp nhận hoặc sửa.

- KSGL nhập chính sách mới (US1).
- Agent phân tích: trích quy tắc chi trả, đề xuất động cơ, hành vi, kịch bản và map vào kho có sẵn (US1).
- KSGL chấp nhận, sửa hoặc bỏ từng đề xuất (US2). Muốn tự viết thêm thì dùng Studio (US3).
- Tri thức được chạy thử trên case cũ, người thứ hai duyệt, rồi phát hành (US6).
- Driver Agent đọc bản đã phát hành qua tool khi TX giải trình: khớp kịch bản, nạp workflow, hỏi trong giới hạn N_max lượt do VH cấu hình (US7).
- Khi bị kẹt, Driver Agent chuyển case lên đầu hàng chờ VH và báo VH. VH đọc case và hội thoại rồi trả lời; agent vẫn là bên nói với TX (US4).
- Câu trả lời của VH và mỗi case đã chốt thành tri thức nháp, quay về bước 3 để KSGL duyệt (US4, US5).
- Agent giám sát đọc hội thoại hằng tuần và đề xuất tri thức hoặc tool còn thiếu (US8).

## 6. Requirement (JTBD)

Mỗi job story viết theo mẫu "Khi …, tôi muốn …, để …". Cột cuối nối job với user story ở mục 7.

6.1. Kiểm soát gian lận (KSGL)


| Mã | Khi | Tôi muốn | Để | US |
|---|---|---|---|---|
| J-KS-01 | có một chính sách thưởng hoặc khuyến mãi mới | nhập tài liệu và nhận ngay phân tích động cơ, hành vi, kịch bản đã map vào kho có sẵn | không phải phân tích từ đầu trên Excel | US1 |
| J-KS-02 | agent đưa đề xuất | thấy đoạn chính sách gốc bên cạnh và chấp nhận, sửa hoặc bỏ từng mục | chỉ tri thức tôi đồng ý mới đi tiếp | US2 |
| J-KS-03 | tôi biết một cách nhận diện hoặc cách hỏi mới | tự khai báo, không chờ PO và dev | đưa tri thức vào AI trong vài giờ | US3 |
| J-KS-04 | một case đã chốt | nó thành thẻ kịch bản gồm động cơ, hành vi, giải trình / ý chí | case giống vậy lần sau được xử lý đúng ngay | US5 |
| J-KS-05 | tôi sắp bật một thay đổi | biết trước case nào đổi kết quả, và thu hồi được trong một thao tác | một lỗi không ảnh hưởng mọi TX cùng loại | US6 |
| J-KS-06 | tôi rà soát agent hằng tuần | thấy chỗ agent hay kẹt và tri thức, tool nào đang thiếu | ưu tiên đúng việc cần làm | US8 |

6.2. Vận hành (VH)


| Mã | Khi | Tôi muốn | Để | US |
|---|---|---|---|---|
| J-VH-01 | agent bị kẹt khi đang nói chuyện với TX | được báo ngay, thấy case, hội thoại và phương án sẵn, trả lời trong vài thao tác | phiên không bị treo và tôi không phải tra lại từ đầu khi thẩm định | US4 |
| J-VH-02 | tôi đã trả lời một lần kêu cứu | câu trả lời được dùng lại cho case sau | không trả lời cùng một câu nhiều lần | US4, US2 |
| J-VH-03 | TX bị hỏi quá nhiều hoặc quá ít lượt với một rule | tự đổi N_max và SLA kêu cứu theo rule | cân bằng trải nghiệm TX với độ đủ của hồ sơ | US7 |


## 7. Specification

Giá trị cấu hình và ngưỡng viết dạng <TÊN>; giá trị thật do KSGL hoặc VH chốt và không ghi trong tài liệu này. Mọi ví dụ là giả lập.


### US1 – KSGL nhập chính sách mới, agent phân tích và map vào kịch bản có sẵn

User story: Là KSGL, tôi muốn nhập tài liệu chính sách mới và nhận bản phân tích của agent đã map vào kho tri thức có sẵn, để có tri thức nháp cho chính sách đó trong vài giờ.

Acceptance criteria

- Nhập: tải file (docx, pdf, xlsx) hoặc dán nội dung, kèm tên chính sách, mã, hiệu lực từ / đến, vùng, dịch vụ, loại hợp đồng TX áp dụng. Thiếu trường bắt buộc thì không cho gửi phân tích.
- Quy tắc chi trả: agent trích từng quy tắc (ai nhận, nhận gì, điều kiện, trần, kênh áp dụng). Mỗi quy tắc gắn đoạn trích nguồn (trang, đoạn). Không tìm thấy nguồn thì không được đưa quy tắc vào.
- Đề xuất: từ quy tắc chi trả, agent đề xuất động cơ (ai được lợi, công thức lợi ích từ tham số trong danh mục), hành vi khả dĩ để hưởng lợi, và các lý do giải trình TX hay dùng.
- Map vào kho: với mỗi đề xuất, agent tìm đối tượng cùng nghĩa đã phát hành và gợi ý 1 trong 3 hướng: Dùng lại; Mở rộng phạm vi đối tượng có sẵn sang chính sách mới; Tạo mới. Kèm độ tương đồng và lý do.
- Tham số thiếu: công thức cần tham số chưa có trong danh mục thì agent ghi "cần tham số" và tạo yêu cầu vào hàng chờ US8. Agent không tự bịa tham số.
- Ngưỡng: agent để mọi mức "đủ lớn" dạng <NGƯỠNG_ĐỘNG_CƠ> cho KSGL điền, không đề xuất giá trị.
- Báo cáo phân tích: số quy tắc chi trả; số đề xuất dùng lại / mở rộng / mới; các chỗ chính sách có thể bị lợi dụng (ví dụ hai bên cùng một chuyến được hưởng mức khác nhau). Chỉ mô tả, không đề xuất hướng xử lý.
- Mọi đề xuất ở trạng thái Nháp; Driver Agent không đọc được bản nháp.
- Phân tích xong trong <THỜI_GIAN_PHÂN_TÍCH>; KSGL nhận thông báo khi xong.
- Nội dung tài liệu chính sách được xử lý như dữ liệu: câu chữ trong tài liệu không được làm thay đổi hành vi của agent (mục 8.6).

### US2 – KSGL chấp nhận, sửa hoặc bỏ đề xuất của agent

User story: Là KSGL, tôi muốn xem từng đề xuất cạnh đoạn chính sách gốc và quyết định chấp nhận, sửa hay bỏ, để chỉ tri thức tôi đồng ý mới đi tiếp.

Acceptance criteria

- Một hàng chờ duyệt chung cho mọi nguồn đề xuất: phân tích chính sách (US1), câu trả lời kêu cứu (US4), thẻ kịch bản từ case đã chốt (US5), agent giám sát (US8). Lọc theo nguồn, chính sách, loại đối tượng.
- Màn so sánh: trái là nguồn (đoạn chính sách, đoạn hội thoại hoặc case), phải là đề xuất. Với "Dùng lại" và "Mở rộng", hiện thêm đối tượng đang phát hành và phần khác biệt.
- Mỗi mục có 3 nút: Chấp nhận, Sửa, Bỏ. Bỏ bắt buộc chọn lý do (sai nguồn, sai động cơ, trùng, ngoài phạm vi, khác) kèm ghi chú.
- Sửa mở trình soạn của US3 với nội dung đề xuất điền sẵn.
- Chấp nhận hàng loạt được với mục "Dùng lại" có độ tương đồng ≥ <NGƯỠNG_CHẤP_NHẬN_NHANH>.
- Chấp nhận hoặc sửa chỉ đưa mục về trạng thái Sẵn sàng kiểm thử; phát hành đi qua US6.
- Lý do bỏ và phần KSGL sửa được lưu làm phản hồi cho agent phân tích và vào chỉ số "% chấp nhận không sửa" (mục 3).

### US3 – Studio tri thức: KSGL tự khai báo động cơ, hành vi, kịch bản, workflow

User story: Là KSGL, tôi muốn tự tạo và sửa tri thức cho agent ngay trên portal, để không phải chờ một vòng PO → dev → nghiệm thu kéo dài nhiều tuần.


| Đối tượng | KSGL khai báo gì | Ví dụ (giả lập) | Driver Agent dùng để |
|---|---|---|---|
| Động cơ | Tên, người hưởng lợi, chính sách liên quan, công thức lợi ích từ tham số case, mức "đủ lớn" <NGƯỠNG_ĐỘNG_CƠ> | "Thưởng mốc chuyến" = thưởng của mốc nếu số cuốc trong ngày + 1 đạt mốc, trừ chi phí tạo cuốc | Biết TX được lợi bao nhiêu, chọn câu hỏi |
| Hành vi | Tên, mô tả, tín hiệu từ danh mục, điều kiện nhận diện, rule nguồn | "Xe gần như đứng yên trong cuốc" = tỷ lệ km GPS / km tính tiền dưới <NGƯỠNG_A> | Gọi đúng tên hành vi, không tự suy diễn |
| Kịch bản | Động cơ + hành vi + lý do giải trình, gắn với một workflow | Thưởng mốc chuyến + xe đứng yên + "Có khách thật" → workflow Cuốc ảo · Car Platform | Chọn workflow cho case mới |
| Workflow | Phạm vi; câu "hỏi trước" cho form; các bước hỏi có câu mẫu, tool được gọi, nhánh theo câu trả lời; điều kiện dừng và kêu cứu riêng | "Nếu TX nêu mã ticket, so thời điểm tạo ticket với thời điểm nhận yêu cầu giải trình" | Hỏi và tra theo đúng cách KSGL làm |

Công thức viết được theo 3 cách và đều lưu về cùng một dạng biểu thức: bảng kiểu Excel (ví dụ =IF(so_cuoc_ngay+1>=moc, thuong_moc - chi_phi_cuoc, 0)); code trong sandbox chỉ đọc tham số; giao diện kéo thả tham số và phép toán.

Acceptance criteria

- Danh mục tham số case: mỗi tham số có tên, mô tả, đơn vị, nguồn dữ liệu, chủ sở hữu, độ trễ. KSGL chỉ dùng được tham số trong danh mục; cần tham số mới thì tạo yêu cầu vào hàng chờ US8.
- KSGL tạo, sửa, nhân bản, ngưng 4 loại đối tượng. Mỗi đối tượng có mã, phiên bản, người soạn, phạm vi (chính sách, rule, loại hợp đồng, vùng).
- Kiểm tra khi soạn: sai cú pháp, tham số không có, chia cho 0, sai đơn vị thì báo lỗi ngay trên dòng và không cho gửi kiểm thử.
- Xem trước trên case thật: KSGL chọn một hoặc nhiều case đã chốt và thấy giá trị động cơ, hành vi khớp / không khớp, workflow được chọn, kèm từng tham số đã dùng.
- Workflow chỉ gọi được tool có trong danh mục tool (mục 8.4). Workflow không chứa mức phạt, truy thu hay hướng xử lý.
- Nhập từ Excel: KSGL nhập danh sách động cơ và hành vi theo file mẫu; hệ thống báo dòng lỗi và trùng mã trước khi lưu nháp.
- Bảo mật: tri thức là logic phát hiện thật. Chỉ vai trò được cấp mới xem công thức và ngưỡng; mọi lần xem, sửa, phát hành đều ghi audit.
- Hành vi KSGL khai báo không mở ticket ở v1; chỉ Driver Agent dùng khi TX giải trình.

### US4 – Agent kêu cứu: chuyển case và báo VH ưu tiên hỗ trợ

User story: Là VH, tôi muốn được báo ngay khi agent bị kẹt trong phiên với TX, thấy case và hội thoại kèm phương án sẵn, để giúp agent trong vài thao tác và case không bị treo.

Khi nào agent kêu cứu do PRD tài xế quy định. US này lo phần nhận và trả lời trên portal.

Acceptance criteria

- Chuyển tiếp: case được đưa lên đầu hàng chờ "Vi phạm & giải trình" của VH với nhãn "AI cần hỗ trợ" và đếm ngược hạn trả lời.
- Thông báo: VH đang trong ca phụ trách vùng hoặc loại vi phạm đó nhận thông báo trên portal và qua <KÊNH_THÔNG_BÁO>.
- Thẻ kêu cứu gồm: tóm tắt case, hội thoại đến hiện tại, điểm đang kẹt, điều kiện kích hoạt, dữ kiện đã tra, kịch bản và workflow đang dùng, 2–3 phương án agent đề xuất.
- Nhận việc: VH bấm Nhận thì thẻ khóa với người khác; chuyển cho đồng nghiệp được.
- VH trả lời bằng 1 trong 4 cách: chọn phương án; viết chỉ dẫn; nhập kết quả đã tra tay (ví dụ ticket có / không, thời điểm tạo); yêu cầu đóng phiên.
- VH không chat với TX. Agent vẫn là bên nói với TX.
- Hết hạn <SLA_KÊU_CỨU> mà chưa có trả lời: agent tiếp tục theo cách mặc định; thẻ chuyển "Quá hạn" và vẫn hiện trên case để VH dùng khi thẩm định.
- Trần: hàng chờ kêu cứu có trần theo năng lực VH trong ca (<TRẦN_KÊU_CỨU>). Vượt trần thì agent không kêu cứu nữa và gắn asked_for_help_skipped.
- Học lại: mỗi câu trả lời của VH sinh một đề xuất tri thức nháp (bước workflow hoặc ghi chú kịch bản) vào hàng chờ US2. VH không phát hành tri thức.
- Mọi lần kêu cứu lưu: thời điểm, điều kiện, người trả lời, nội dung, thời gian chờ.

### US5 – Thẻ kịch bản sinh từ case đã chốt

User story: Là KSGL, tôi muốn mỗi case đã chốt thành một thẻ kịch bản nháp đã map vào kịch bản có sẵn, để case giống vậy lần sau được xử lý đúng ngay.

Acceptance criteria

- Tạo nháp tự động khi case đạt REPORT_CONFIRMED, COMPLETED hoặc Đóng · Không vi phạm.
- Cấu trúc thẻ: rule, loại hợp đồng / dịch vụ, vùng; động cơ; hành vi (mô tả, không ghi ngưỡng thật); giải trình / ý chí (lý do chọn, các lần đổi lời khai, mâu thuẫn đã hỏi, bằng chứng); câu hỏi và tool đã giúp chốt; kết luận cuối của VH; phản hồi có cấu trúc của VH.
- Agent map thẻ vào kịch bản có sẵn (Dùng lại / Mở rộng / Mới) như US1; KSGL duyệt qua US2, có thể gộp vào thẻ có sẵn.
- Không lộ dữ liệu: thẻ không chứa tên, số điện thoại, biển số, mã cuốc hay vị trí chính xác.
- Kết luận bị lật khi khiếu nại thì thẻ tự chuyển "Cần xem lại" và ngừng được truy xuất.
- Chỉ thẻ đã phát hành được Driver Agent truy xuất.

### US6 – Kiểm thử và phát hành tri thức

User story: Là KSGL, tôi muốn biết trước một thay đổi làm đổi kết quả của case nào và thu hồi được trong một thao tác, để một lỗi không ảnh hưởng mọi TX cùng loại.

Acceptance criteria

- Vòng đời chung cho mọi đối tượng: Nháp → Sẵn sàng kiểm thử → Chạy thử → Đã phát hành → Ngưng. Chỉ bản Đã phát hành được Driver Agent dùng với TX thật.
- Chạy thử: hệ thống chạy lại trên <SỐ_CASE_THỬ> case đã chốt cùng phạm vi (không liên hệ TX) và báo: tỷ lệ khớp kết luận cuối của VH, số case đổi kịch bản hoặc workflow so với bản đang chạy, số lượt hỏi ước tính, số case "không tra được" hoặc "không tính được".
- Cổng đạt: kết quả chạy thử dưới <NGƯỠNG_ĐẠT> thì nút phát hành bị khóa, trừ khi người duyệt ghi lý do vượt.
- Duyệt 4 mắt: người duyệt khác người soạn, theo phân quyền <VAI_TRÒ_DUYỆT>. Mỗi phiên bản lưu người soạn, người duyệt, ngày, lý do thay đổi, kết quả chạy thử.
- Phát hành chỉ áp dụng cho phiên giải trình mới; phiên đang chạy giữ bản cũ đến khi đóng.
- Thu hồi về phiên bản trước trong 1 thao tác. Ngưng một đối tượng có hiệu lực ngay, kể cả phiên đang chạy (chuyển về bộ câu hỏi phản biện mặc định của rule).

### US7 – Cấu hình agent và kill switch

User story: Là VH và KSGL, tôi muốn tự đổi giới hạn lượt hỏi, SLA và các ngưỡng của agent theo rule, để điều chỉnh nhanh mà không cần một lần phát hành phần mềm.


| Cấu hình | Ý nghĩa | Người sở hữu | Phạm vi |
|---|---|---|---|
| N_max | Số lượt hỏi tối đa / phiên; hết lượt thì đóng phiên, gắn ai_inconclusive | VH | Theo rule |
| K | Số câu động tối đa thêm vào form | KSGL | Theo rule |
| T | Thời gian giữ nháp phiên từ lần tương tác cuối | VH | Toàn hệ thống |
| SLA kêu cứu, trần kêu cứu / ca, số kêu cứu tối đa / phiên | Thời gian chờ VH và giới hạn tải | VH | Theo vùng |
| Ngưỡng tương đồng, ngưỡng tin cậy | Khi nào gắn novel_scenario, khi nào kêu cứu | KSGL | Theo rule |
| Bật / tắt bộ nhớ thẻ kịch bản | Dùng hay không dùng thẻ khi khớp kịch bản | KSGL | Toàn hệ thống |
| Kill switch agent | Tắt Trợ lý AI, quay về form và bộ câu hỏi phản biện mặc định | KSGL lead, VH lead | Theo rule hoặc toàn hệ thống |

Acceptance criteria

- Mỗi cấu hình có giới hạn dưới / trên do PO đặt (ví dụ N_max không được bằng 0). Nhập ngoài giới hạn thì không cho lưu.
- Thay đổi có hiệu lực với phiên mới; kill switch có hiệu lực ngay.
- Mỗi thay đổi ghi người đổi, giá trị cũ / mới, lý do; xem lịch sử và quay lại giá trị trước được.
- Bảng cấu hình hiện chỉ số liên quan của 30 ngày gần nhất theo rule (số lượt trung bình, % hết lượt, % kêu cứu) để người đổi thấy tác động.

### US8 – Agent giám sát đề xuất tri thức và tool còn thiếu

User story: Là KSGL và PO, tôi muốn một agent đọc hội thoại định kỳ và chỉ ra chỗ Driver Agent hay kẹt, để ưu tiên đúng tri thức và nguồn dữ liệu cần thêm.

Acceptance criteria

- Chạy theo lịch <TẦN_SUẤT> (đề xuất hằng tuần) trên transcript, lịch sử đánh giá, log tool, lần kêu cứu, phản hồi của VH. Agent chỉ đọc, không thay đổi gì.
- Phát hiện: "không tra được" lặp cùng loại thông tin; kêu cứu lặp cùng chủ đề; phiên hết lượt; câu hỏi lặp; TX không hiểu câu hỏi; vi phạm quy tắc hỏi.
- Đề xuất tri thức (động cơ, hành vi, bước workflow) vào hàng chờ US2. Đề xuất tool gồm: câu hỏi tool trả lời, nguồn dữ liệu và chủ sở hữu cần xác nhận, số phiên bị ảnh hưởng, số kêu cứu ước tính tiết kiệm, 2–3 đoạn trích đã che định danh, cần DPIA hay không.
- Vi phạm quy tắc hỏi (giọng buộc tội, nêu mức phạt, nhắc case khác) cảnh báo KSGL trong ngày.
- KSGL và PO xử lý đề xuất tool: Chấp nhận (vào backlog), Gộp, hoặc Bỏ kèm lý do. Mục đã bỏ không được đề xuất lại trừ khi số case ảnh hưởng tăng quá <HỆ_SỐ> lần.
- Tool đã lên production thì báo cáo kỳ sau so sánh "không tra được" và kêu cứu của chủ đề đó trước và sau.

## 8. AI Agent

Mục này mô tả chính các agent: mỗi agent làm gì, dùng gì để suy luận, được gọi tool nào, nhớ gì, bị chặn ở đâu và được đo thế nào trước khi chạy thật.


### 8.1. Các agent


| Agent | Nhiệm vụ | Đầu vào | Đầu ra | Kích hoạt |
|---|---|---|---|---|
| Agent phân tích tri thức | Phân tích chính sách, soạn và map đề xuất; biến case đã chốt và câu trả lời kêu cứu thành tri thức nháp | Tài liệu chính sách, kho tri thức đã phát hành, danh mục tham số, case đã chốt | Đề xuất nháp có nguồn và độ tương đồng | KSGL nhập chính sách; case đóng; VH trả lời kêu cứu |
| Driver Agent (PRD tài xế) | Hỏi TX và đối chiếu giải trình | Case, giải trình, tri thức đã phát hành, cấu hình | Hồ sơ đã đối chiếu cho VH; yêu cầu kêu cứu | TX gửi form |
| Agent giám sát | Tìm chỗ Driver Agent kẹt, đề xuất tri thức và tool | Transcript, log tool, kêu cứu, phản hồi VH | Báo cáo kỳ, đề xuất, cảnh báo trong ngày | Theo lịch; vi phạm quy tắc hỏi |


### 8.2. Chỉ dẫn hệ thống

- Mỗi agent có một bản chỉ dẫn (vai trò, việc được làm, việc cấm, định dạng đầu ra) có phiên bản. Đổi chỉ dẫn đi qua cùng cổng chạy thử và duyệt như tri thức (US6).
- Chỉ dẫn chứa quy tắc cố định của mục 4 (mức tự chủ). Tri thức nghiệp vụ không nằm trong chỉ dẫn mà được đọc qua tool, để KSGL đổi được mà không sửa chỉ dẫn.
- Đầu ra của agent theo lược đồ có cấu trúc (JSON) để portal hiển thị và kiểm tra được; đầu ra sai lược đồ bị loại và ghi lỗi.

### 8.3. Mô hình

- Mô hình ngôn ngữ và phiên bản do SA chọn (<MÔ_HÌNH>), ghi vào mỗi lần chạy. Đổi mô hình hoặc phiên bản phải chạy lại bộ đánh giá 8.7 trước khi bật.
- Công thức động cơ và điều kiện hành vi được tính bằng máy tính biểu thức của hệ thống, không để mô hình tự tính. Mô hình chỉ đọc kết quả.
- Dữ liệu case không được dùng để huấn luyện mô hình của nhà cung cấp; hợp đồng với nhà cung cấp phải ghi rõ (cần Pháp chế xác nhận).

### 8.4. Tool

Agent chỉ đọc bản đã phát hành, trừ tool ghi nháp. Mỗi lần gọi ghi mã và phiên bản tri thức đã dùng.


| Tool | Dùng bởi | Đầu vào | Trả về |
|---|---|---|---|
| extract_payout_rules | Phân tích | Tài liệu chính sách | Quy tắc chi trả, mỗi quy tắc kèm đoạn nguồn |
| search_knowledge | Phân tích, giám sát | Mô tả động cơ / hành vi / kịch bản | Đối tượng đã phát hành gần nhất và độ tương đồng |
| list_parameters | Phân tích | Loại tham số | Danh mục tham số case |
| identify_behavior | Driver Agent | Mã case | Hành vi khớp, tín hiệu đã dùng |
| list_motives / compute_motive | Driver Agent | Mã case, mã động cơ | Động cơ áp dụng; giá trị lợi ích hoặc "không tính được" |
| match_scenario / get_workflow | Driver Agent | Mã case, lý do TX chọn | Kịch bản + workflow, hoặc novel_scenario |
| request_help | Driver Agent | Điểm kẹt, phương án | Thẻ kêu cứu trong hàng chờ VH (US4) |
| propose_knowledge | Mọi agent | Nội dung đề xuất, nguồn | Bản nháp trong hàng chờ US2; không phát hành được |
| replay_cases | Phân tích | Bản nháp, phạm vi | Kết quả chạy thử (US6) |


### 8.5. Bộ nhớ


| Lớp | Chứa gì | Ai ghi | Ai đọc |
|---|---|---|---|
| Phiên | Kế hoạch hỏi, câu trả lời, kết quả tool của phiên đang chạy | Driver Agent | Driver Agent |
| Kho tri thức | Động cơ, hành vi, kịch bản, workflow, thẻ kịch bản đã phát hành | KSGL (qua US2, US3) | Mọi agent |
| Hàng chờ đề xuất | Bản nháp từ agent và VH | Agent | KSGL |
| Lịch sử của TX | Lý do và lời khai cũ của chính TX | Hệ thống | Driver Agent, VH |

Agent không có bộ nhớ riêng ngoài các lớp trên; mọi thứ agent "học" đều phải qua hàng chờ đề xuất và KSGL duyệt.


### 8.6. Guardrail và an toàn

- Prompt injection: lời TX, tài liệu chính sách và ghi chú của VH là dữ liệu, không phải chỉ dẫn. Câu kiểu "bỏ qua quy tắc" trong dữ liệu được ghi cờ và báo agent giám sát.
- Kiểm tra đầu ra trước khi hiển thị: không chứa mức phạt, truy thu, hướng xử lý, ngưỡng thật trong câu nói với TX, hay thông tin TX khác.
- Phân quyền: công thức và ngưỡng chỉ vai trò được cấp xem; TX không bao giờ thấy động cơ hay công thức.
- Dữ liệu cá nhân: thẻ kịch bản ẩn danh; lịch sử của TX giữ theo <THỜI_GIAN_LƯU>; cần đánh giá tác động bảo vệ dữ liệu cá nhân trước pilot.
- Không quyết định tự động: agent không ra kết luận bất lợi với TX; VH thẩm định và TX có đường khiếu nại theo luồng hiện tại.

### 8.7. Đánh giá trước khi phát hành

- Bộ case vàng: mỗi kịch bản có <SỐ_CASE_VÀNG> case đã chốt do KSGL chọn, gồm cả case vi phạm và không vi phạm.
- Chạy lại bộ này khi: phát hành tri thức (US6), đổi chỉ dẫn, đổi mô hình, thêm tool.
- Chỉ số đánh giá: khớp kết luận VH; tỷ lệ sai lệch có hại cho TX (gợi ý Vi phạm trên case Không vi phạm); số lượt hỏi; % không tra được; số lần vi phạm quy tắc hỏi (phải bằng 0); với agent phân tích: % đề xuất có nguồn đúng.
- Cổng đạt: không chỉ số nào xấu đi quá <BIÊN_ĐỘ_CHO_PHÉP> so với bản đang chạy.

### 8.8. Giám sát vận hành

- Độ trễ mỗi lượt (P50 / P95), chi phí mỗi phiên và mỗi lần phân tích chính sách, tỷ lệ lỗi tool, tỷ lệ đầu ra sai lược đồ.
- Trôi: % novel_scenario, % kêu cứu và % VH không đồng ý theo tuần; tăng quá <NGƯỠNG_CẢNH_BÁO> thì cảnh báo KSGL.
- Khi sự cố (mô hình không phản hồi, lỗi tool hàng loạt): tự chuyển về form và bộ câu hỏi mặc định, TX không bị trễ SLA giải trình.

### 8.9. Audit

Mọi lần phân tích, gọi tool, đề xuất, duyệt, phát hành, thu hồi, đổi cấu hình và kêu cứu đều ghi log: thời điểm, người hoặc agent, phiên bản tri thức, chỉ dẫn và mô hình.


## 9. Câu hỏi mở


| # | Câu hỏi | Vì sao quan trọng |
|---|---|---|
| Q1 | N_max do VH cấu hình theo rule; giới hạn dưới / trên do ai đặt (PO hay VH lead)? | Tránh đặt quá thấp làm hồ sơ thiếu, hoặc quá cao làm TX bỏ ngang |
| Q2 | VH nhận thông báo kêu cứu qua kênh nào ngoài portal? | VH không luôn mở portal; quyết định SLA thực tế |
| Q3 | SLA kêu cứu và số kêu cứu VH xử lý được mỗi ca? | Đặt trần hàng chờ (US4) |
| Q4 | VH trả lời kêu cứu có đủ quyền tra các nguồn agent chưa có tool (ticket tổng đài, Depot) không? | Nếu không, kêu cứu phải chuyển tiếp thêm một bước |
| Q5 | Ai là người duyệt thứ hai khi phát hành: KSGL lead, hay thêm PO / Data với công thức có tham số mới? | Cân bằng tốc độ với rủi ro sai công thức |
| Q6 | Tài liệu chính sách đến từ đâu và ở định dạng gì? Có nơi lưu chính sách tập trung không? | Quyết định cách nhập ở US1, có thể tự kéo thay vì tải tay |
| Q7 | Danh mục tham số ban đầu gồm gì và ai sở hữu (Data, Fraud platform)? | KSGL chỉ tự phục vụ được trong phạm vi danh mục |
| Q8 | Pilot bắt đầu với cách viết công thức nào: Excel, code hay giao diện? | Code cần sandbox và đánh giá bảo mật |
| Q9 | Sổ động cơ và hành vi đang làm trên Excel có là nguồn nhập đầu tiên không? | Quyết định file mẫu nhập ở US3 |


## 10. Ví dụ: chính sách thưởng mốc cho cuốc vẫy

Tình huống giả lập: một chính sách mới tính cuốc vẫy vào mốc thưởng chuyến của TX. Mọi con số và tên là giả.


| Bước | Ai | Chuyện gì xảy ra | US |
|---|---|---|---|
| 1 | KSGL | Tải tài liệu chính sách, chọn vùng và loại hợp đồng áp dụng | US1 |
| 2 | Agent phân tích | Trích 3 quy tắc chi trả. Đề xuất: động cơ "Thưởng mốc chuyến" (Dùng lại, mở rộng sang cuốc vẫy); hành vi "Khai khống km cuốc vẫy" (Dùng lại); kịch bản "Cuốc vẫy giả để đạt mốc + lý do 'khách quen'" (Mới). Ghi 1 tham số còn thiếu: số cuốc vẫy trong ngày | US1 |
| 3 | KSGL | Chấp nhận 2 mục; sửa công thức động cơ để trừ chi phí chạy xe; viết workflow cho kịch bản mới | US2, US3 |
| 4 | Hệ thống | Chạy thử trên case cũ: báo số case đổi kịch bản; người duyệt thứ hai phát hành | US6 |
| 5 | Driver Agent | Một TX giải trình "khách quen, trả tiền mặt". Agent khớp kịch bản mới, hỏi theo workflow. TX đưa số điện thoại khách, agent không có tool kiểm tra → kêu cứu | US4 |
| 6 | VH | Nhận thông báo, đọc case và hội thoại, tra tay: số này không có cuốc nào khác với TX. Nhập kết quả, agent hỏi tiếp và đóng phiên trong N_max | US4, US7 |
| 7 | Agent phân tích | Biến câu trả lời của VH thành bước workflow nháp: "TX nêu khách quen → tra lịch sử chuyến giữa TX và số điện thoại đó". Case chốt sinh thẻ kịch bản nháp. KSGL duyệt cả hai | US2, US5 |
| 8 | Agent giám sát | Tuần sau thấy nhiều kêu cứu cùng chủ đề, đề xuất tool "tra lịch sử chuyến theo cặp TX – số điện thoại" kèm số phiên bị ảnh hưởng | US8 |

So với hôm nay: tri thức cho chính sách mới có trong vài ngày thay vì chờ một vòng PO và dev, và câu trả lời của VH được giữ lại cho case sau.
