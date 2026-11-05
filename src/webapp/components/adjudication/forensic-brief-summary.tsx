import type { ForensicBriefResponse } from "@/types/schemas";

const intentLabels = {
  possible_intentional_exploit: "Có thể khai thác để hưởng lợi",
  possible_accidental: "Có thể ngoài ý muốn",
  unclear_insufficient_data: "Chưa đủ dữ liệu về ý định",
};

export function ForensicBriefSummary({ brief }: { brief?: ForensicBriefResponse | null }) {
  const assessment = brief?.motivation_assessment;
  return (
    <section aria-label="Forensic Brief" className="bg-white border border-indigo-200 rounded-lg p-3 shadow-xs">
      <h3 className="text-xs font-semibold text-slate-800">Forensic Brief</h3>
      {brief?.summary_text && <p className="mt-2 text-[11px] text-slate-600 leading-relaxed">{brief.summary_text}</p>}
      <div aria-label="Đánh giá động cơ tài xế" className="mt-3 border-t border-slate-100 pt-3">
        <h4 className="text-xs font-semibold text-slate-800">Động cơ tài xế</h4>
        <p className="mt-1 text-[11px] font-semibold text-indigo-700">{assessment ? intentLabels[assessment.intent_profile] : "Chưa có đánh giá động cơ"}</p>
        <p className="mt-2 text-[11px] text-slate-700 leading-relaxed whitespace-pre-line">
          {assessment?.natural_vietnamese_narrative || "Chưa có đánh giá động cơ cho hồ sơ này."}
        </p>
        <p className="mt-2 text-[11px] text-slate-500">
          Lợi ích tăng thêm ước tính: <span className="font-mono font-semibold text-slate-900">
            {assessment ? new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(assessment.economic_incentive_reward) : "Chưa xác định"}
          </span>
        </p>
      </div>
    </section>
  );
}
