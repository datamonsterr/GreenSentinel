
# PRD – Trợ lý AI hỗ trợ tài xế giải trình vi phạm

Nov 19, 2026 · @Pham Thanh Dat


## 1. Tổng quan

Trợ lý AI giúp tài xế (TX) giải trình nghi vấn gian lận ngay trên Driver App, rồi chuyển cho Vận hành (VH) một hồ sơ đã được đối chiếu với dữ liệu hệ thống. Bản PRD này nâng Trợ lý từ một luồng hỏi đáp cố định thành một agent học được qua từng case và thay đổi cách hỏi theo tình huống.

Luồng cơ bản giữ nguyên: TX chọn lý do và trả lời form; agent điều tra, khớp kịch bản và hỏi bổ sung trong tối đa N_max lượt; TX xác nhận bản tổng hợp; hồ sơ sang VH. PRD này tập trung vào chính Driver Agent:

- Khớp kịch bản và workflow đã duyệt: agent đọc tri thức KSGL đã phát hành qua tool, không tự đặt ra cách hỏi.
- Vòng suy luận có giới hạn: suy nghĩ, gọi tool, quan sát, hỏi TX; dừng khi đủ căn cứ hoặc hết N_max lượt do VH cấu hình.
- Kêu cứu VH: khi kẹt, agent chuyển case lên đầu hàng chờ VH và báo VH ưu tiên; agent vẫn là bên nói với TX.
- Mục AI Agent (mục 8): chỉ dẫn, mô hình, vòng suy luận, tool, bộ nhớ, guardrail, đánh giá và giám sát.
KSGL xác định gian lận và sở hữu tri thức; VH thẩm định case. Việc KSGL nhập chính sách, khai báo, duyệt và phát hành tri thức, cấu hình agent và agent giám sát nằm ở PRD "Kho tri thức và cấu hình cho Trợ lý AI giải trình" (Admin Portal). VH vẫn thẩm định case ở UNDER_REVIEW theo luồng hiện tại.

Phạm vi: phần Detection. Mức phạt, truy thu và mọi chuyển trạng thái sau UNDER_REVIEW vẫn thuộc VH, KSGL và squad Decision theo luồng hiện tại.


## 2. Bối cảnh

Giải trình vi phạm hiện tốn trung bình 2–4 giờ nhân sự cho mỗi case, và TX phải chờ 3–7 ngày. Nội dung TX viết thường mơ hồ, thiếu thời điểm, địa điểm và bằng chứng, nên VH phải đọc lại từ đầu và tự đối chiếu trên nhiều công cụ.

- Phase 1 (đã triển khai): AI hỗ trợ VH trên Admin Portal. AI phản biện lý do TX chọn bằng dữ liệu hệ thống và gợi ý kết luận. Nếu TX giải trình thiếu, VH vẫn phải trả hồ sơ về để TX bổ sung.
- Phase 2 (đang thiết kế): thu đủ thông tin ngay từ TX qua hai lớp: form có bộ câu hỏi cố định theo lý do, và Trợ lý AI chỉ vào cuộc khi giải trình lần 1 còn thiếu hoặc mâu thuẫn.
Thiết kế Phase 2 còn sáu điểm yếu. PRD này giải quyết phần thuộc Driver Agent; phần thuộc KSGL nằm ở PRD Kho tri thức.


| # | Điểm yếu | Hệ quả | Giải pháp |
|---|---|---|---|
| 1 | Mỗi case bắt đầu từ trắng, AI không nhớ case cũ | Cùng một kiểu giải trình bị hỏi lại từ đầu, tốn lượt | US2 khớp kịch bản, US5 bộ nhớ |
| 2 | Tri thức KSGL nằm tĩnh trong bộ câu hỏi phản biện theo rule | Đổi cách hỏi phải qua PO và dev | US6 tool đọc tri thức; PRD Kho tri thức |
| 3 | AI không có cách xin trợ giúp | Case lạ chạy hết lượt rồi gắn ai_inconclusive | US3 kêu cứu VH |
| 4 | Nhiều nguồn dữ liệu chưa kết nối (ticket tổng đài, ngày thanh lý hợp đồng, lịch sử XLVP, sự cố GPS hệ thống) | AI ghi "không tra được" và đẩy VH tra tay | US3 cho từng phiên; agent giám sát ở PRD Kho tri thức |
| 5 | Không ai rà soát hội thoại có hệ thống | Lỗi giọng hỏi, câu hỏi thừa chỉ lộ qua khiếu nại | Mục 8.7, 8.8; agent giám sát ở PRD Kho tri thức |
| 6 | Tri thức đi từ KSGL vào AI qua vòng KSGL → PO → dev → nghiệm thu | Mỗi thay đổi mất nhiều tuần | PRD Kho tri thức |


## 3. Mục tiêu

Giúp TX giải trình nhanh, đủ thông tin và đúng hạn, để VH thẩm định nhanh hơn mà không tăng kết luận sai. Agent phải tốt lên theo thời gian: cùng một kịch bản, lần sau hỏi ít lượt hơn và ít phải kêu cứu hơn.


| Loại | Chỉ số | Mục tiêu |
|---|---|---|
| Primary | Thời gian VH thẩm định trung bình / case | Giảm <MỤC_TIÊU_A>% |
| Secondary | % giải trình đúng hạn SLA; % giải trình qua AI; % phiên AI hoàn tất; % VH đồng thuận gợi ý AI | <MỤC_TIÊU_B> |
| Học qua case | % case có workflow đã duyệt phù hợp; số lượt hỏi trung bình / phiên theo kịch bản; % ai_inconclusive theo tháng; % phiên phải kêu cứu | Xu hướng giảm theo tháng |
| Vận hành kêu cứu | Thời gian VH trả lời kêu cứu (P50 / P90); số kêu cứu / ngày so với năng lực VH | Trong <SLA_KÊU_CỨU> phút |
| Tool | Số đề xuất tool được duyệt / quý; % "không tra được" sau khi tool lên | Theo dõi |
| Guardrail | % kết luận VH khác gợi ý AI; % không giải trình; số khiếu nại của TX về AI; % kết luận bị lật khi khiếu nại; số phiên vi phạm quy tắc hỏi | Không tăng so với mốc trước pilot |


## 4. Vai trò và mức tự chủ của agent

Driver Agent nói chuyện với TX và đối chiếu dữ liệu, nhưng không kết luận và không tự học ngoài những gì KSGL đã duyệt.


| Vai trò | Làm gì trong PRD này |
|---|---|
| TX | Trả lời form và câu hỏi của agent; xác nhận hoặc sửa bản tổng hợp trước khi gửi |
| Driver Agent | Điều tra, khớp kịch bản, hỏi bổ sung, kêu cứu, tổng hợp hồ sơ |
| VH | Trả lời kêu cứu; thẩm định hồ sơ và phản hồi có cấu trúc; cấu hình N_max |
| KSGL | Sở hữu và phát hành tri thức agent đọc (PRD Kho tri thức) |


| Agent tự làm | Cần người | Agent không bao giờ làm |
|---|---|---|
| Hỏi TX theo workflow đã duyệt | Kết luận cuối của case (VH) | Nói với TX là TX vi phạm, hoặc nêu mức phạt |
| Gọi tool workflow cho phép, cập nhật kế hoạch hỏi | Kiểm tra bằng chứng agent không có tool (VH, qua kêu cứu) | Nhắc case hoặc TX khác |
| Đóng phiên khi đủ căn cứ hoặc hết N_max | Tri thức mới (KSGL duyệt) | Dùng lịch sử của TX làm bằng chứng vi phạm |
| Gửi kêu cứu, đề xuất tri thức nháp | Đổi N_max, SLA, ngưỡng (VH, KSGL) | Dùng tri thức nháp, hỏi quá N_max lượt |


## 5. Luồng tổng thể

Form vẫn đi trước, agent chỉ hỏi khi cần TX bổ sung, VH vẫn là người chốt. Điểm khác là agent điều tra và khớp kịch bản trước khi hỏi, chạy một vòng suy luận có giới hạn lượt, và kêu cứu VH khi bị kẹt.

vòng Driver Agent · điều tra, hỏi, kêu cứu, gửi VH

Mỗi câu trả lời của TX quay lại vòng suy nghĩ; vòng dừng khi đủ căn cứ hoặc hết N_max lượt do VH cấu hình.

- TX nhận thông báo, chọn lý do và trả lời form: bộ câu hỏi cố định của lý do, cộng tối đa K câu động từ workflow đã duyệt (US1).
- Agent điều tra: nhận diện hành vi, tính động cơ, khớp kịch bản. Khớp thì nạp workflow; không khớp thì gắn novel_scenario (US2).
- Agent đánh giá đợt 1 ra 1 trong 4 trạng thái. Cần TX bổ sung thì vào vòng hỏi (US2).
- Vòng hỏi: suy nghĩ → gọi tool → quan sát → hỏi TX. Mỗi câu trả lời của TX quay lại vòng. Dừng khi đủ căn cứ hoặc N ≥ N_max (US2).
- Kẹt thì kêu cứu: case lên đầu hàng chờ VH, VH đọc case và hội thoại rồi trả lời, agent hỏi tiếp (US3).
- Đóng phiên: agent hiện bản tổng hợp, TX xác nhận hoặc sửa. Xác nhận thì gửi, agent đánh giá đợt 2, hồ sơ sang VH ở UNDER_REVIEW (US2, US4).
- VH chốt theo luồng hiện tại và phản hồi có cấu trúc. Case đã chốt và câu trả lời kêu cứu thành tri thức nháp cho KSGL duyệt ở PRD Kho tri thức.

## 6. Requirement (JTBD)

Mỗi job story viết theo mẫu "Khi …, tôi muốn …, để …". Cột cuối nối job với user story ở mục 7.


### 6.1. Tài xế (TX)


| Mã | Khi | Tôi muốn | Để | US |
|---|---|---|---|---|
| J-TX-01 | tôi nhận yêu cầu giải trình và chọn lý do | biết ngay cần cung cấp những gì, bằng câu hỏi ngắn | không phải tự viết dài và trả lời đủ ngay lần đầu | US1 |
| J-TX-02 | giải trình của tôi còn thiếu | chỉ bị hỏi đúng điểm còn thiếu, không bị hỏi lại điều đã trả lời | xong nhanh và không phải giải trình lại | US2 |
| J-TX-03 | tôi đưa ra bằng chứng mà AI không tự kiểm tra được (mã ticket tổng đài, xác nhận của Depot) | bằng chứng đó được người có thẩm quyền kiểm tra ngay | giải trình đúng của tôi không bị bỏ qua | US3 |
| J-TX-04 | tôi không muốn hoặc không thể tiếp tục chat | kết thúc sớm và vẫn gửi được những gì đã khai | không bị tính là không giải trình | US2 |
| J-TX-05 | tôi không đồng ý cách AI hiểu giải trình của mình | xem và xác nhận hoặc sửa bản tổng hợp trước khi gửi | điều tôi khai được ghi đúng và có đường khiếu nại | US2, US4 |


### 6.2. Vận hành (VH)


| Mã | Khi | Tôi muốn | Để | US |
|---|---|---|---|---|
| J-VH-01 | tôi mở một hồ sơ giải trình | nhận hồ sơ đã đối chiếu, kèm gợi ý và nguồn gốc của gợi ý | chỉ kiểm tra điểm còn vướng | US4 |
| J-VH-02 | agent bị kẹt khi đang hỏi TX | được báo ngay và trả lời trong vài thao tác | phiên không bị treo và tôi không phải tra lại khi thẩm định | US3 |
| J-VH-03 | tôi không đồng ý gợi ý của AI | ghi rõ AI sai ở đâu (dữ kiện, suy luận, câu hỏi, tool) | lỗi đó được sửa đúng chỗ | US4 |

Job của KSGL (nhập chính sách, khai báo và phát hành tri thức, rà soát agent) nằm ở PRD Kho tri thức.


## 7. Specification

Luồng nhận thông báo / pop-up, màn chi tiết giải trình, nhắc SLA và danh sách nhiều case đang chạy đã có ở hệ thống hiện tại, nên không đưa vào user story triển khai.

Mỗi US giữ nguyên yêu cầu của bản trước và ghi rõ phần cải tiến. Giá trị cấu hình (N, K, T, ngưỡng) viết dạng <TÊN>; giá trị thật do KSGL chốt và không ghi trong tài liệu này.


### US1 – Tài xế trả lời bộ câu hỏi theo lý do (cố định + động)

User story: Là tài xế, tôi muốn trả lời một bộ câu hỏi rõ ràng theo đúng lý do mình chọn, để biết cần cung cấp gì và không phải tự viết dài.

Cải tiến: bộ câu hỏi cố định được nối thêm tối đa <K> câu lấy từ workflow đã duyệt. Các câu này là những câu mà các case cùng kịch bản trước đây hay phải hỏi lại trong phiên chat, nên đưa lên form để TX trả lời luôn.

Acceptance criteria

- Sau khi chọn lý do, TX chuyển sang màn Form câu hỏi của lý do đó.
- Lý do có bộ câu hỏi: mỗi câu là 1 trường có đánh dấu bắt buộc / không bắt buộc. Loại trường: text ngắn, giờ, địa điểm, chọn một, số tiền, ảnh, mã ticket. Bộ cố định lấy từ phần câu hỏi cơ bản trong bộ câu hỏi phản biện của KSGL, cấu hình theo rule.
- Câu động: hệ thống chọn workflow đã duyệt khớp với rule + loại hợp đồng / dịch vụ + lý do, rồi thêm tối đa <K> câu "hỏi trước" của workflow đó vào cuối form. Câu động luôn không bắt buộc. Không có workflow khớp thì form chỉ gồm bộ cố định.
- Câu động chỉ lấy từ câu đã được KSGL duyệt sẵn trong workflow; AI không tự sinh câu mới trên form. Mỗi bản form lưu kèm form_version và workflow_id + phiên bản.
- Lý do không có bộ câu hỏi (ví dụ đã nghỉ việc, muốn giải trình trực tiếp với VH): form chỉ gồm ô nội dung tự do + đính kèm ảnh như hiện tại.
- Thiếu câu bắt buộc thì không cho gửi, highlight câu còn thiếu.
- Lưu nháp theo violation_id: thoát rồi mở lại vẫn còn câu trả lời; SLA vẫn chạy.
- Form không hiển thị dữ liệu đối chiếu (GPS, ODO, telemetry…) và không tiết lộ là câu nào đến từ workflow.

### US2 – Agent điều tra, khớp kịch bản và hỏi bổ sung

User story: Là tài xế, tôi muốn chỉ bị hỏi đúng điểm còn thiếu, theo cách KSGL đã duyệt cho tình huống của mình, để giải trình đủ căn cứ ngay lần này và không bị yêu cầu giải trình lại.

Cải tiến: gộp US2 (đánh giá đợt 1) và US3 (phiên bổ sung) của bản trước thành một vòng agent: điều tra, khớp kịch bản, nạp workflow, rồi hỏi trong giới hạn N_max lượt.

Acceptance criteria – Điều tra (đợt 1)

- TX bấm Gửi thì lưu statement_v1; TX không sửa được nữa, mọi bổ sung lưu thành phiên bản riêng. Thời điểm gửi form là thời điểm TX đã giải trình (xét SLA). TX thấy "Đang kiểm tra giải trình".
- Agent gọi identify_behavior, list_motives / compute_motive và match_scenario (US6). Khớp kịch bản ≥ <NGƯỠNG_TƯƠNG_ĐỒNG> thì gọi get_workflow; không khớp thì gắn novel_scenario = true và dùng bộ câu hỏi phản biện mặc định của rule. novel_scenario là một điều kiện kêu cứu (US3).
- Agent đọc thêm tối đa <TOP_K> thẻ kịch bản đã phát hành gần nhất và lịch sử giải trình của chính TX này (US5).
- Agent đối chiếu giải trình lần 1 với nguồn dữ liệu workflow chỉ định và ra 1 trong 4 trạng thái dùng chung cho mọi đợt:

| Trạng thái | Khi nào | Bước tiếp |
|---|---|---|
| Đủ điều kiện vận doanh (Không vi phạm) | Giải trình khớp dữ liệu, đủ căn cứ | Chuyển VH (UNDER_REVIEW) |
| Không đủ điều kiện vận doanh (Vi phạm) | Đủ căn cứ và không còn điểm cần TX giải thích | Chuyển VH (UNDER_REVIEW) |
| Cần tài xế bổ sung thông tin | Thiếu, mơ hồ, hoặc có mâu thuẫn TX chưa được hỏi làm rõ | Vào vòng hỏi |
| Thiếu thông tin nội bộ | Hệ thống không đủ dữ liệu để kết luận | Chuyển VH kèm danh sách cần tra cứu |

- Mâu thuẫn TX chưa được hỏi làm rõ luôn ra "Cần tài xế bổ sung thông tin", không kết luận Vi phạm ngay ở đợt 1.
- Kế hoạch hỏi: danh sách điểm cần làm rõ có thứ tự (thiếu → bằng chứng → mâu thuẫn), mỗi điểm gắn nguồn đối chiếu và bước workflow. Chỉ VH và KSGL thấy.
- TX không thấy kết quả của agent. Với 3 trạng thái chuyển VH, TX thấy "Đã gửi giải trình, VH sẽ phản hồi trong Y giờ".
Acceptance criteria – Vòng hỏi

- Đợt 1 là "Cần tài xế bổ sung thông tin" thì TX được chuyển sang Trợ lý AI và bắt buộc tương tác. Agent mở bằng 1 câu tóm tắt giải trình lần 1, không hỏi lại điều đã trả lời trên form.
- Mỗi lượt agent chạy: suy nghĩ → gọi tool workflow cho phép → quan sát kết quả → hỏi TX 1 câu, hoặc dừng. Tool lỗi hoặc chưa có thì ghi "không tra được" kèm lý do, không suy đoán.
- Kế hoạch động: sau mỗi câu trả lời, agent bỏ điểm đã rõ, thêm điểm mới, đổi thứ tự khi cần; mỗi lần cập nhật được ghi log.
- Đổi nhánh: TX đưa lý do mới (ví dụ "GPS lỗi") thì gắn statement_changed = true, gọi lại match_scenario và hỏi theo workflow của lý do mới trong số lượt còn lại.
- Điều kiện dừng: đủ căn cứ thì đóng phiên; bị kẹt thì kêu cứu (US3); N ≥ N_max thì đóng phiên và gắn ai_inconclusive = true. N_max do VH cấu hình theo rule trên Admin Portal (PRD Kho tri thức, US7). 1 lượt = 1 câu hỏi của agent + 1 câu trả lời của TX; thời gian chờ kêu cứu không tính là lượt.
- Đóng phiên: agent báo "Mình đã ghi nhận thông tin, mình sẽ gửi cho vận hành xem xét." và hiện bản tổng hợp (lần 1 + bổ sung). TX chọn Xác nhận hoặc Sửa. Sửa thì TX nhập phần cần sửa và agent cập nhật bản tổng hợp, tối đa <SỐ_LẦN_SỬA> lần. Xác nhận thì submit, agent đánh giá đợt 2, hồ sơ sang UNDER_REVIEW.
- TX trả lời bằng chat text, đính kèm được ảnh và mã ticket. TX bấm "Kết thúc" bất kỳ lúc nào thì đi thẳng tới bản tổng hợp. TX 2 lượt liên tiếp không trả lời được thì agent đề nghị kết thúc.
- Lưu nháp phiên trong T phút từ lần tương tác cuối. Quá T phút hoặc sự cố thì tự submit với dữ liệu đã có, gắn session_interrupted = true; TX không bị trễ SLA.
- Quy tắc hỏi: lịch sự, không buộc tội, không dẫn dắt; mỗi mâu thuẫn hỏi tối đa 1 câu, giọng trung tính; không nói về TX khác; không nêu mức phạt hoặc kết quả XLVP; không phản ứng gay gắt khi TX xúc phạm.

### US3 – Agent kêu cứu VH khi bị kẹt

User story: Là tài xế, tôi muốn bằng chứng AI không tự kiểm tra được được người có thẩm quyền xem ngay trong phiên, để giải trình đúng của tôi không bị bỏ qua.

Cải tiến: kêu cứu chuyển tiếp case và báo VH ưu tiên hỗ trợ. Phần VH nhận và trả lời trên portal nằm ở PRD Kho tri thức (US4); US này lo phần trong phiên với TX.

Acceptance criteria

- Điều kiện kêu cứu (bất kỳ): novel_scenario = true; độ tin cậy dưới <NGƯỠNG_TIN_CẬY> sau <M> lượt; TX đưa bằng chứng agent không có tool kiểm tra; hai nguồn dữ liệu nội bộ mâu thuẫn; TX nêu tai nạn, sự cố an toàn hoặc nội dung nhạy cảm.
- Agent gọi request_help với: tóm tắt case, điểm kẹt, dữ kiện đã tra, 2–3 phương án. Case lên đầu hàng chờ VH và VH được báo.
- Agent vẫn là bên nói với TX. Trong lúc chờ, agent báo "Mình cần kiểm tra thêm thông tin, bạn chờ mình một chút nhé" và có thể hỏi điểm khác trong kế hoạch. VH không chat trực tiếp với TX.
- VH trả lời thì agent dùng câu trả lời để hỏi tiếp hoặc đóng phiên. Agent được nêu dữ kiện VH đã tra với TX, không nêu ai đã tra.
- Hết hạn <SLA_KÊU_CỨU> mà chưa có trả lời: agent tiếp tục theo bộ câu hỏi mặc định hoặc đóng phiên, ghi điểm kẹt thành "điểm còn vướng" cho VH. Nếu TX đã thoát app, câu trả lời của VH dùng cho đánh giá đợt 2.
- Hạn mức: tối đa <SỐ_KÊU_CỨU> lần / phiên. Hàng chờ VH vượt trần thì agent không kêu cứu nữa và gắn asked_for_help_skipped = true.
- Mỗi lần kêu cứu lưu: thời điểm, điều kiện, người trả lời, nội dung, thời gian chờ; hiển thị cho VH (US4).

### US4 – VH nhận giải trình đã đối chiếu, kèm gợi ý và nguồn gốc của gợi ý

User story: Là VH / Risk Ops, tôi muốn nhận giải trình đã được đối chiếu, kèm gợi ý, độ tin cậy và tri thức agent đã dựa vào, để chỉ kiểm tra điểm còn vướng và phản hồi đúng chỗ AI sai.

Acceptance criteria

- Trang chi tiết vi phạm trên Admin Portal hiển thị lịch sử đánh giá theo từng đợt: thời điểm, nguồn (form / phiên AI), trạng thái, căn cứ khớp, mâu thuẫn, điểm còn vướng, thay đổi nội dung giải trình. Với "Thiếu thông tin nội bộ", liệt kê thông tin không tra được.
- Hiển thị transcript, các phiên bản giải trình và các cờ statement_changed, ai_inconclusive, session_interrupted, novel_scenario, asked_for_help.
- Nguồn gốc gợi ý: kịch bản, hành vi, động cơ và workflow đã dùng (mã + phiên bản), tối đa 3 thẻ kịch bản tương tự, các lần kêu cứu kèm câu trả lời của VH.
- Gợi ý = kết quả đợt mới nhất, kèm mã lý do đề xuất, độ tin cậy, động cơ khả dĩ, câu hỏi đề xuất VH hỏi thêm, số lượt đã dùng / N_max.
- Phản hồi có cấu trúc: VH chọn Đồng ý hoặc Không đồng ý. Không đồng ý thì bắt buộc chọn ít nhất 1 loại lỗi: sai dữ kiện; sai suy luận; thiếu câu hỏi; câu hỏi thừa hoặc sai giọng; thiếu tool / nguồn dữ liệu; dùng sai kịch bản hoặc workflow. Kèm góp ý tự do.
- Case đã chốt được gửi sang PRD Kho tri thức (US5) để sinh thẻ kịch bản nháp, kèm phản hồi của VH.
- AI không ra quyết định. Mọi chuyển trạng thái sau UNDER_REVIEW giữ nguyên luồng hiện tại.

### US5 – Bộ nhớ phiên và lịch sử của TX

User story: Là tài xế, tôi muốn agent nhớ điều tôi đã nói trong phiên và ở các lần giải trình trước, để không bị hỏi lại điều đã rõ.

Cải tiến: thẻ kịch bản và workflow chuyển sang kho tri thức của PRD Kho tri thức; agent đọc chúng qua tool (US6). US này chỉ còn hai lớp gắn với TX.

Acceptance criteria

- Bộ nhớ phiên: kế hoạch hỏi, câu trả lời, kết quả tool và câu trả lời kêu cứu của phiên đang chạy; mất khi phiên đóng, bản ghi lưu vào lịch sử đánh giá.
- Lịch sử của TX: lý do và lời khai cũ của chính TX này và kết quả cuối. Chỉ dùng để chọn câu hỏi và hiển thị cho VH; không nêu với TX như bằng chứng vi phạm và không tự nó làm tăng kết luận Vi phạm.
- Agent không nhắc đến TX hoặc case khác khi nói với TX.
- Thời gian lưu lịch sử của TX theo <THỜI_GIAN_LƯU>; cần đánh giá tác động bảo vệ dữ liệu cá nhân trước pilot.

### US6 – Agent đọc tri thức của KSGL qua tool

User story: Là KSGL, tôi muốn agent lấy động cơ, hành vi, kịch bản và workflow từ những gì tôi đã phát hành, qua tool có ghi nguồn, để mọi suy luận của agent đều truy ngược được.


| Tool | Đầu vào | Trả về |
|---|---|---|
| identify_behavior | Mã case | Hành vi khớp, tín hiệu và giá trị đã dùng, mã + phiên bản |
| list_motives | Mã case hoặc kịch bản | Động cơ áp dụng cho chính sách và loại TX của case |
| compute_motive | Mã động cơ, mã case | Giá trị lợi ích, tham số đã dùng, có vượt <NGƯỠNG_ĐỘNG_CƠ> hay không |
| match_scenario | Mã case, lý do TX chọn | Kịch bản khớp nhất + workflow, hoặc novel_scenario |
| get_workflow | Mã workflow | Chỉ dẫn, các bước, tool được phép, điều kiện dừng và kêu cứu |
| request_help | Điểm kẹt, phương án | Thẻ kêu cứu trong hàng chờ VH (US3) |
| propose_knowledge | Nội dung đề xuất | Bản nháp chờ KSGL; agent không phát hành được |

Acceptance criteria

- Agent chỉ đọc bản đã phát hành. Mỗi kết luận hoặc câu hỏi ghi mã + phiên bản tri thức đã dùng (US4).
- Agent không tự đặt tên hành vi hay động cơ ngoài danh mục; gặp tình huống ngoài danh mục thì gắn novel_scenario và kêu cứu (US3).
- Công thức lỗi hoặc thiếu tham số thì tool trả "không tính được" kèm lý do; agent không ước đoán giá trị.
- Giá trị động cơ chỉ hiển thị cho VH và KSGL, không nói với TX. Động cơ lớn không tự nó là bằng chứng vi phạm.
- Khai báo, duyệt, phát hành tri thức và agent giám sát nằm ở PRD Kho tri thức (US1–US8 của PRD đó).

### Yêu cầu chung cho các US

- Audit: mọi lần truy xuất thẻ, chọn workflow, gọi tool, kêu cứu và duyệt đều ghi log có thời điểm, người / agent thực hiện, phiên bản.
- Pháp lý: AI không ra quyết định bất lợi với TX; VH xem xét và TX có đường khiếu nại theo luồng hiện tại. Cần rà soát bảo vệ dữ liệu cá nhân cho lớp lịch sử của TX trước pilot.
- Song ngữ: nội dung AI sinh cho VH có bản Việt và Anh như Phase 1; lời TX và dữ liệu gốc hiển thị nguyên bản.

## 8. AI Agent

Mục này mô tả chính Driver Agent: nó nhận gì, suy luận thế nào, được gọi gì, nhớ gì, bị chặn ở đâu và được đo thế nào trước và sau khi chạy thật.


### 8.1. Thẻ agent


| Mục | Nội dung |
|---|---|
| Mục tiêu | Thu đủ thông tin từ TX và đối chiếu với dữ liệu, để VH thẩm định nhanh mà không tăng kết luận sai |
| Người dùng | TX (Driver App), VH (Admin Portal) |
| Kích hoạt | TX gửi form giải trình |
| Đầu vào | Case vi phạm, form, dữ liệu case theo workflow, tri thức đã phát hành, cấu hình (N_max, K, T, SLA) |
| Đầu ra | Câu hỏi cho TX; bản tổng hợp cho TX xác nhận; hồ sơ đã đối chiếu cho VH; yêu cầu kêu cứu; đề xuất tri thức nháp |
| Không làm | Kết luận vi phạm, nêu mức phạt, tự phát hành tri thức (mục 4) |


### 8.2. Chỉ dẫn hệ thống

- Một bản chỉ dẫn có phiên bản: vai trò, quy tắc hỏi (US2), mức tự chủ (mục 4), định dạng đầu ra. Đổi chỉ dẫn phải chạy lại bộ đánh giá 8.7 và được duyệt như tri thức.
- Tri thức nghiệp vụ (động cơ, hành vi, kịch bản, workflow) không nằm trong chỉ dẫn mà được đọc qua tool, để KSGL đổi được mà không sửa chỉ dẫn.
- Đầu ra nội bộ (trạng thái, kế hoạch hỏi, căn cứ) theo lược đồ có cấu trúc; sai lược đồ thì loại và ghi lỗi.

### 8.3. Mô hình

- Mô hình ngôn ngữ và phiên bản do SA chọn (<MÔ_HÌNH>), ghi vào mỗi phiên. Đổi mô hình phải chạy lại 8.7 trước khi bật.
- Công thức động cơ và điều kiện hành vi do hệ thống tính qua tool; mô hình không tự tính số.
- Dữ liệu case không được dùng để huấn luyện mô hình của nhà cung cấp (cần Pháp chế xác nhận trong hợp đồng).

### 8.4. Vòng suy luận


| Bước | Agent làm gì | Dừng hoặc rẽ nhánh khi |
|---|---|---|
| Điều tra | identify_behavior, compute_motive, match_scenario | Không khớp → novel_scenario |
| Nạp workflow | get_workflow | Không có workflow → bộ câu hỏi mặc định của rule |
| Suy nghĩ | Chọn điểm tiếp theo trong kế hoạch | Đủ căn cứ → đóng phiên |
| Gọi tool | Chỉ tool workflow cho phép | Lỗi → "không tra được" |
| Quan sát | So kết quả với lời khai, cập nhật kế hoạch | Kẹt → kêu cứu VH |
| Hỏi TX | 1 câu / lượt | N ≥ N_max → đóng phiên, ai_inconclusive |
| Tổng hợp | Bản tổng hợp cho TX | TX Sửa → cập nhật; Xác nhận → đợt 2, sang VH |


### 8.5. Tool và bộ nhớ

Tool theo US6; bộ nhớ phiên và lịch sử TX theo US5; kho tri thức theo PRD Kho tri thức. Agent không có bộ nhớ riêng ngoài các lớp này; mọi thứ agent "học" đều đi qua propose_knowledge và KSGL duyệt.


### 8.6. Guardrail và an toàn

- Prompt injection: lời TX và ảnh TX gửi là dữ liệu, không phải chỉ dẫn. Câu kiểu "bỏ qua quy tắc" được ghi cờ cho VH và agent giám sát.
- Kiểm tra mỗi câu trước khi gửi TX: không chứa mức phạt, kết luận, ngưỡng, động cơ, công thức, thông tin TX khác; giọng không buộc tội. Không đạt thì viết lại hoặc dùng câu mẫu của workflow.
- TX nêu tai nạn, sự cố an toàn thì kêu cứu ngay (US3).
- Không quyết định tự động: VH thẩm định và TX có đường khiếu nại theo luồng hiện tại.

### 8.7. Đánh giá trước khi bật

- Bộ case vàng theo kịch bản (do KSGL chọn ở PRD Kho tri thức), gồm case vi phạm và không vi phạm.
- Mô phỏng hội thoại với TX giả lập theo vài kiểu: khai thật, khai không thật rồi đổi lời, khó hiểu câu hỏi, xúc phạm, chèn câu lệnh vào lời khai.
- Chỉ số: khớp kết luận VH; tỷ lệ gợi ý Vi phạm trên case Không vi phạm; số lượt trung bình; % hết N_max; % kêu cứu; số lần vi phạm quy tắc hỏi (phải bằng 0).
- Chạy lại khi đổi chỉ dẫn, mô hình, tool; cổng đạt: không chỉ số nào xấu đi quá <BIÊN_ĐỘ_CHO_PHÉP>.

### 8.8. Giám sát vận hành

- Độ trễ mỗi lượt (P50 / P95), chi phí mỗi phiên, tỷ lệ lỗi tool, tỷ lệ đầu ra sai lược đồ.
- Theo tuần: % novel_scenario, % kêu cứu, % VH không đồng ý, % hết N_max; tăng quá <NGƯỠNG_CẢNH_BÁO> thì cảnh báo KSGL. Rà soát hội thoại hằng tuần do agent giám sát ở PRD Kho tri thức làm.
- Mô hình không phản hồi hoặc lỗi tool hàng loạt: tự chuyển về form và bộ câu hỏi mặc định; TX không bị trễ SLA. Kill switch nằm ở PRD Kho tri thức (US7).

## 9. Câu hỏi mở


| # | Câu hỏi | Vì sao quan trọng |
|---|---|---|
| Q1 | N_max mặc định là bao nhiêu và có khác nhau theo rule không? | VH cấu hình; cần giá trị ban đầu cho pilot |
| Q2 | TX bấm Sửa bản tổng hợp có tính vào N_max không? | Tránh TX bị khóa sửa vì hết lượt |
| Q3 | TX chờ kêu cứu tối đa bao lâu thì chấp nhận được? | Quyết định SLA kêu cứu và trải nghiệm TX |
| Q4 | VH có đủ quyền tra ticket tổng đài, xác nhận Depot khi trả lời kêu cứu không? | Nếu không, kêu cứu không giải quyết được bằng chứng ngoài |
| Q5 | Nhà cung cấp mô hình và vùng lưu dữ liệu? | Ảnh hưởng đánh giá bảo vệ dữ liệu cá nhân |

Câu hỏi về kho tri thức (người duyệt, danh mục tham số, cách viết công thức) nằm ở PRD Kho tri thức.


## 10. Ví dụ: Cuốc ảo cho Car Platform, TX giải trình "Có khách thật"

Tình huống TX khai không trung thực; N = 5 lượt. Dữ liệu là giả lập. Ví dụ chỉ ra chỗ bộ nhớ, workflow, kêu cứu và agent giám sát làm khác đi so với luồng cũ.

Bước 1 – Thông báo và chọn lý do. TX nhận noti "Bạn có 1 giải trình mới, hạn trước HH:mm". Màn chi tiết: "Cuốc ABC123 lúc 14:05 ngày 10/11 có quãng đường thực tế thấp bất thường so với quãng đường tính tiền." TX chọn "Có khách thật, tôi chở thật".

Bước 2 – Form câu hỏi (US1). Hệ thống tìm thấy workflow đã duyệt "Cuốc ảo · Car Platform · Có khách thật" nên thêm 1 câu động (câu 8). Câu này có vì ở các case trước AI hay phải hỏi lại trong phiên chat.


| # | Câu hỏi trên form | Bắt buộc | TX trả lời |
|---|---|---|---|
| 1 | Bạn đón khách ở đâu? | Có | Cổng chợ X |
| 2 | Đón lúc mấy giờ? | Có | Khoảng 14:00 |
| 3 | Mô tả khách (giới tính, độ tuổi, mang theo gì) | Có | Nữ, khoảng 40 tuổi, xách 2 túi đồ |
| 4 | Khách xuống ở đâu? | Có | Khu Y |
| 5 | Đi đường nào, có dừng giữa chừng không? | Có | Đường Z, không dừng |
| 6 | Khách trả tiền bằng cách nào, bao nhiêu? | Có | Tiền mặt, 85.000đ |
| 7 | Ảnh / bằng chứng (nếu có) | Không | — |
| 8 | Trong cuốc, điện thoại hoặc định vị của bạn có gặp vấn đề gì không? (câu động) | Không | Không |

Bước 3 – Agent điều tra (US2). identify_behavior trả về "xe gần như đứng yên trong cuốc"; compute_motive cho "thưởng mốc chuyến" vượt ngưỡng; match_scenario khớp "Cuốc ảo · Car Platform · Có khách thật" và nạp workflow của kịch bản đó. Giải trình chưa khớp dữ liệu nên kết quả là Cần tài xế bổ sung thông tin. Kế hoạch hỏi (chỉ VH thấy): (1) xe đứng yên, (2) nếu TX nói GPS lỗi thì tra GPS các cuốc khác và ngày sự cố hệ thống, (3) điểm đón so với Orders.

Bước 4 – Vòng hỏi và kêu cứu (US2, US3).


| Lượt | Agent | TX | Ghi chú hệ thống |
|---|---|---|---|
| Mở | "Mình đã nhận giải trình của bạn: đón khách tại cổng chợ X lúc 14:00, chở về khu Y, thu tiền mặt 85.000đ. Mình cần làm rõ thêm vài điểm nhé." | — | Tóm tắt giải trình lần 1 |
| 1 | "Hệ thống ghi nhận xe gần như đứng yên trong thời gian cuốc. Bạn có muốn bổ sung gì không?" | "Chắc GPS điện thoại bị lag thôi, tôi chạy thật mà" | Lý do mới → statement_changed = true; match_scenario lại, chuyển nhánh "GPS lỗi" |
| 2 | "Bạn thấy GPS lỗi thế nào? Các cuốc khác trong ngày có bị như vậy không?" | "Lỗi suốt, hôm đó còn gọi tổng đài báo rồi, mã ticket 0000-1234" | Tool theo workflow: các cuốc khác đủ điểm GPS, không phải ngày sự cố → mâu thuẫn. Không có tool tra ticket → kêu cứu VH |
| Chờ | "Mình cần kiểm tra thêm thông tin, bạn chờ mình một chút nhé." | — | Case lên đầu hàng chờ VH. VH tra tay: ticket có thật nhưng tạo sau thời điểm TX nhận yêu cầu giải trình. Thời gian chờ không tính lượt |
| 3 | "Các cuốc khác trong ngày định vị bình thường, và ticket bạn báo được tạo sau khi bạn nhận yêu cầu giải trình. Lúc đi cuốc bạn có báo lỗi cho ai không?" | "Không, lúc đó chưa báo" | Lý do "GPS lỗi" không được chứng minh |
| 4 | "Điểm đón hệ thống ghi nhận không phải cổng chợ X. Bạn có thể nói rõ lại điểm đón không?" | "À chắc tôi nhớ nhầm, đón ở đâu tôi không nhớ rõ" | Giải trình đổi lần 2. Mọi mâu thuẫn đã hỏi → đóng phiên ở 4 / N_max lượt |
| Đóng | Bản tổng hợp | TX bấm Xác nhận | Đánh giá đợt 2: Không đủ điều kiện vận doanh, độ tin cậy cao. UNDER_REVIEW |

Bước 5 – VH xem hồ sơ (US4). VH thấy 2 đợt đánh giá; các mâu thuẫn; giải trình đổi 2 lần; kịch bản, hành vi, động cơ và workflow đã dùng; 1 lần kêu cứu kèm câu trả lời của VH. VH chọn Đồng ý và chốt theo luồng hiện tại.

Bước 6 – Quay về kho tri thức (PRD Kho tri thức). Case đã chốt sinh thẻ kịch bản nháp; câu trả lời kêu cứu sinh bước workflow nháp "TX nêu mã ticket → so thời điểm tạo ticket với thời điểm nhận yêu cầu giải trình". KSGL duyệt cả hai. Agent giám sát thấy nhiều kêu cứu cùng chủ đề và đề xuất tool tra ticket tổng đài.

So với luồng cũ: cùng số lượt hỏi, nhưng bằng chứng "đã báo tổng đài" được VH kiểm tra ngay trong phiên, và cách xử lý được giữ lại cho case sau.
