import type { Locale } from './locale';
const en = {
  tabs: { overview: 'Overview', trip: 'Trip', maps: 'Maps', customer: 'Customer', driver: 'Driver', finalization: 'Complete' },
  views: 'Case views', triage: 'Triage queue', activeQueue: 'Active Queue', historyQueue: 'Case History', loadingWorkspace: 'Loading workspace', loadingCase: 'Loading case', thought: 'Thought', thoughtStatus: 'Thought status', reviewing: 'Reviewing case evidence and relevant policy…', tool: 'Tool', singleTurn: 'Single turn', unavailable: 'Unavailable', unknown: 'Undetermined', notAssessed: 'Not assessed',
  start: 'Driver start', pickup: 'Pickup', destination: 'Destination', status: 'Status', match: 'Matching', fare: 'Fare',
  behavior: 'Observed behavior', brief: 'Forensic Brief', motivation: 'Motivation', willingness: 'Willingness',
  noBrief: 'Factual brief unavailable. Review source evidence in Maps.',
  motivationUnknown: 'No verified motive.',
  willingnessUnknown: 'Intent is undetermined.',
  modelEstimate: 'Model estimate; verify against source evidence.', originalEvidence: 'Source evidence retains its original language.',
  source: 'Source', viewMaps: 'Review map evidence', viewDriver: 'Review driver evidence',
  tripDetails: 'Trip details', caseId: 'Case ID', tripId: 'Trip ID', driverStatus: 'Driver status', cancellationReason: 'Cancellation reason', cancellationActor: 'Cancellation actor', milestones: 'Trip milestones', noMilestones: 'No milestones available',
  claim: 'Claim', claimCase: 'Claim case', claiming: 'Claiming…', release: 'Release', releaseCase: 'Release case', releasing: 'Releasing…', reject: 'Reject',
  ownedOther: 'Claimed by another analyst', readOnly: 'Read-only: another analyst owns this case.', archived: 'Archived',
  finalization: 'Finalization', outcome: 'Outcome', rationaleLabel: 'Rationale', actor: 'Actor', recorded: 'Recorded', economicIncentive: 'Economic incentive', policies: 'Policies', finalDecision: 'Final decision', matchedPrecedent: 'Matched precedent', similarity: 'Similarity', procedure: 'Procedure', applyProcedure: 'Apply matched procedure', appliedPrecedent: 'Applied precedent',    viewAI: 'View AI results', gateIntro: 'Save your judgment before viewing AI.',
  judgment: 'Independent judgment', suspected: 'Suspected fraud', noFraud: 'No fraud / force majeure', needEvidence: 'Insufficient evidence',
  judgmentNote: 'Judgment note (optional)', saveJudgment: 'Save judgment & view AI', saving: 'Saving…',
  aiResults: 'AI results', classification: 'Classification', confidence: 'Classifier confidence', reasonCodes: 'Reason codes', recommendation: 'Recommendation',
  confidenceHelp: 'Model confidence in the classification; not a calibrated probability of fraud.',
  counterargument: 'Counterargument', counterargumentText: 'Check alternative explanations before deciding.',
  deltaMatch: 'Matches AI recommendation', deltaMismatch: 'Differs from AI recommendation (mismatch)',
  rationale: 'Decision rationale', rationalePlaceholder: 'Verified evidence and rationale (10+ characters).',
  rationaleMinimum: 'Rationale requires at least 10 characters.', notes: 'Additional notes', approve: 'Approve conclusion', rejectConclusion: 'Dismiss', request: 'Request evidence', requestTimeout: 'Request timed out. Check the case before retrying.',
  unauthorized: 'Your account is not authorized to adjudicate.', leaseRequired: 'Claim this case before saving judgments or decisions.',
  judgmentRequired: 'Save your preliminary judgment to enable final decisions.',
  saveError: 'Unable to save decision. Retry after refreshing ownership.', judgmentError: 'Unable to save judgment. Your input is retained.',
  claimError: 'Unable to update ownership. Retry after refreshing.', conflict: 'Ownership changed. The latest server state has been reloaded.',
  saved: 'Decision saved', retry: 'Retry', queueError: 'Unable to load cases', detailError: 'Unable to load case',
  active: 'Active', history: 'History', refresh: 'Refresh cases', search: 'Search cases by driver identity or vehicle plate', searchPlaceholder: 'Search driver, plate, ID…', clearSearch: 'Clear search',
  lockFilter: 'Case lock filter', availableCases: 'Available cases', mine: 'Claimed by me', historyFilter: 'Case history status filter', allProcessed: 'All processed', resolved: 'Resolved (approved)', dismissed: 'Dismissed', autoDismissed: 'Auto-dismissed',
  noSearch: 'No cases match search', noHistory: 'No processed cases found', noCases: 'No available cases', previousPage: 'Previous history page', nextPage: 'Next history page', prev: 'Previous', next: 'Next', of: 'of',
  selectCase: 'Select a case to review', workspace: 'Case workspace', retryCase: 'Retry case', finalized: 'Case finalized', version: 'Version', archiveReadOnly: 'Preserved archive · Read-only', decisionBy: 'Decision by',
  incomplete: 'Evidence incomplete. Review before approving.',






   sourceOnly: 'Unsaved notes · not model evidence.',
  states: { picking_up: 'Picking up', in_progress: 'In progress', coming: 'Coming', driver_arriving: 'Driver arriving', completed: 'Completed', cancelled: 'Cancelled', active: 'Active', suspended: 'Suspended', under_review: 'Under review', in_review: 'In review', open: 'Open', ready: 'Ready', assigned: 'Assigned', pending: 'Pending', escalated: 'Escalated', resolved: 'Resolved', closed: 'Closed', overdue: 'Overdue', unknown: 'Unknown', now: 'Now', auto: 'Automatic' } as Record<string, string>,
};
type Messages = { [K in keyof typeof en]: typeof en[K] extends Record<string, string> ? Record<keyof typeof en[K], string> : string };
const vi: Messages = {
  tabs: { overview: 'Tổng quan', trip: 'Chuyến đi', maps: 'Bản đồ', customer: 'Khách hàng', driver: 'Tài xế', finalization: 'Hoàn tất' },
  views: 'Nội dung vụ việc', triage: 'Danh sách thẩm định', activeQueue: 'Hàng đợi đang xử lý', historyQueue: 'Lịch sử vụ việc', loadingWorkspace: 'Đang tải không gian thẩm định', loadingCase: 'Đang tải vụ việc', thought: 'Suy nghĩ', thoughtStatus: 'Trạng thái suy nghĩ', reviewing: 'Đang xem xét bằng chứng và quy định liên quan…', tool: 'Công cụ', singleTurn: 'Một lượt', unavailable: 'Chưa có dữ liệu', unknown: 'Chưa xác định', notAssessed: 'Chưa đánh giá',
  start: 'Vị trí đầu tài xế', pickup: 'Điểm đón', destination: 'Điểm đến', status: 'Trạng thái', match: 'Ghép chuyến', fare: 'Cước phí',
  behavior: 'Hành vi quan sát được', brief: 'Tóm tắt bằng chứng', motivation: 'Động cơ', willingness: 'Ý định thực hiện',
  noBrief: 'Chưa có tóm tắt thực tế. Xem bằng chứng gốc tại Bản đồ.', motivationUnknown: 'Chưa xác minh động cơ.', willingnessUnknown: 'Chưa xác định ý định.',
  modelEstimate: 'Ước tính của mô hình; cần đối chiếu bằng chứng gốc.', originalEvidence: 'Bằng chứng được giữ nguyên ngôn ngữ gốc.',
  source: 'Nguồn', viewMaps: 'Xem bằng chứng bản đồ', viewDriver: 'Xem bằng chứng tài xế', tripDetails: 'Chi tiết chuyến đi', caseId: 'Mã vụ việc', tripId: 'Mã chuyến đi', driverStatus: 'Trạng thái tài xế', cancellationReason: 'Lý do huỷ', cancellationActor: 'Bên huỷ', milestones: 'Mốc chuyến đi', noMilestones: 'Chưa có mốc chuyến đi',
  claim: 'Nhận', claimCase: 'Nhận vụ việc', claiming: 'Đang nhận…', release: 'Trả', releaseCase: 'Trả vụ việc', releasing: 'Đang trả…', reject: 'Bác bỏ', ownedOther: 'Thẩm định viên khác đã nhận', readOnly: 'Chỉ đọc: thẩm định viên khác đang giữ vụ việc.', archived: 'Lưu trữ',
  finalization: 'Kết luận', outcome: 'Kết quả', rationaleLabel: 'Lý do', actor: 'Người thực hiện', recorded: 'Đã ghi nhận', economicIncentive: 'Động cơ kinh tế', policies: 'Quy định', finalDecision: 'Quyết định cuối', matchedPrecedent: 'Án lệ tương đồng', similarity: 'Độ tương đồng', procedure: 'Quy trình', applyProcedure: 'Áp dụng quy trình tương đồng', appliedPrecedent: 'Đã áp dụng án lệ',    viewAI: 'Xem kết quả AI', gateIntro: 'Lưu phán đoán độc lập trước khi xem AI.', judgment: 'Phán đoán độc lập', suspected: 'Nghi ngờ vi phạm', noFraud: 'Nghi oan-bất khả kháng', needEvidence: 'Chưa đủ cơ sở', judgmentNote: 'Ghi chú phán đoán (tuỳ chọn)', saveJudgment: 'Lưu phán đoán và xem AI', saving: 'Đang lưu…', requestTimeout: 'Yêu cầu hết thời gian. Kiểm tra vụ việc trước khi thử lại.',
  aiResults: 'Kết quả AI', classification: 'Phân loại', confidence: 'Độ tin cậy phân loại', reasonCodes: 'Mã lý do', recommendation: 'Khuyến nghị', confidenceHelp: 'Độ tin cậy của mô hình về phân loại; không phải xác suất vi phạm đã hiệu chỉnh.',
  counterargument: 'Phản biện', counterargumentText: 'Kiểm tra khả năng khác trước khi quyết định.',
  deltaMatch: 'Trùng khớp với khuyến nghị AI', deltaMismatch: 'Khác biệt với khuyến nghị AI (lệch)',
  rationale: 'Lý do thẩm định', rationalePlaceholder: 'Căn cứ đã xác minh và lý do (từ 10 ký tự).', rationaleMinimum: 'Lý do thẩm định yêu cầu tối thiểu 10 ký tự.', notes: 'Ghi chú bổ sung', approve: 'Chấp thuận kết luận', rejectConclusion: 'Bác bỏ', request: 'Yêu cầu bằng chứng',
  unauthorized: 'Tài khoản không có thẩm quyền thẩm định.', leaseRequired: 'Nhận vụ việc trước khi lưu phán đoán hoặc quyết định.',
  judgmentRequired: 'Lưu phán đoán độc lập để kích hoạt quyết định kết luận.',
  saveError: 'Không thể lưu quyết định. Tải lại quyền sở hữu rồi thử lại.', judgmentError: 'Không thể lưu phán đoán. Nội dung đã nhập được giữ lại.', claimError: 'Không thể cập nhật quyền sở hữu. Tải lại rồi thử lại.', conflict: 'Quyền sở hữu đã thay đổi. Đã tải lại trạng thái từ máy chủ.', saved: 'Đã lưu quyết định', retry: 'Thử lại', queueError: 'Không thể tải danh sách vụ việc', detailError: 'Không thể tải vụ việc',
  active: 'Đang xử lý', history: 'Lịch sử', refresh: 'Tải lại vụ việc', search: 'Tìm vụ việc theo danh tính tài xế hoặc biển số', searchPlaceholder: 'Tìm tài xế, biển số, mã…', clearSearch: 'Xoá tìm kiếm', lockFilter: 'Lọc quyền sở hữu', availableCases: 'Vụ việc có thể nhận', mine: 'Vụ việc của tôi', historyFilter: 'Lọc trạng thái lịch sử', allProcessed: 'Tất cả đã xử lý', resolved: 'Đã giải quyết (chấp thuận)', dismissed: 'Đã bác bỏ', autoDismissed: 'Tự động bác bỏ', noSearch: 'Không có kết quả phù hợp', noHistory: 'Chưa có vụ việc đã xử lý', noCases: 'Chưa có vụ việc có thể nhận', previousPage: 'Trang lịch sử trước', nextPage: 'Trang lịch sử sau', prev: 'Trước', next: 'Sau', of: 'trên', selectCase: 'Chọn vụ việc để xem', workspace: 'Không gian thẩm định', retryCase: 'Tải lại vụ việc', finalized: 'Vụ việc đã kết luận', version: 'Phiên bản', archiveReadOnly: 'Bản lưu trữ · Chỉ đọc', decisionBy: 'Người quyết định', incomplete: 'Bằng chứng chưa đầy đủ. Xem xét trước khi chấp thuận.',
                          sourceOnly: 'Ghi chú chưa lưu · không phải bằng chứng mô hình.',
  states: { picking_up: 'Đang đón khách', in_progress: 'Đang thực hiện', coming: 'Đang đến', driver_arriving: 'Tài xế đang đến', completed: 'Hoàn thành', cancelled: 'Đã huỷ', active: 'Hoạt động', suspended: 'Đình chỉ', under_review: 'Đang xem xét', in_review: 'Đang xử lý', open: 'Mới mở', ready: 'Sẵn sàng', assigned: 'Đã phân công', pending: 'Chờ xử lý', escalated: 'Đã chuyển cấp', resolved: 'Đã xử lý', closed: 'Đã đóng', overdue: 'Quá hạn', unknown: 'Chưa xác định', now: 'Ngay', auto: 'Tự động' },
};
export const workspaceMessages: Record<Locale, Messages> = { en, vi };
export function workspaceState(value: string | undefined, locale: Locale) { return value ? workspaceMessages[locale].states[value] || value : workspaceMessages[locale].unavailable; }
