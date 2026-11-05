"use client";

import React from "react";

export interface DriverRelayTurn {
  role?: string;
  sender?: string;
  text?: string;
  content?: string;
  timestamp?: string;
  created_at?: string;
  occurred_at?: string;
  turn_id?: string;
  id?: string;
  [key: string]: unknown;
}

interface DriverRelayTabProps {
  transcript: DriverRelayTurn[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onRetry: () => void;
  sending: boolean;
  error: string | null;
  closed: boolean;
}

function isAnalystTurn(turn: DriverRelayTurn): boolean {
  return turn.role === "analyst" || turn.sender === "analyst";
}

function turnRoleLabel(turn: DriverRelayTurn): string {
  if (isAnalystTurn(turn)) return "Chuyên viên Thẩm định";
  if (turn.role === "driver" || turn.role === "driver_agent") return "Tài xế";
  if (turn.role === "agent") return "GSupport";
  return "Hệ thống";
}

export const DriverRelayTab: React.FC<DriverRelayTabProps> = ({
  transcript,
  input,
  onInputChange,
  onSend,
  onRetry,
  sending,
  error,
  closed,
}) => {
  const seen = new Set<string>();
  const relayTurns = transcript.filter((turn) => {
    if (!["driver", "driver_agent", "agent", "analyst"].includes(turn.role ?? "")) return false;
    // A driver and agent can share a turn_id; only repeated messages within
    // the same role are echoes. Prefer the canonical message id for rendering.
    const identity = turn.turn_id ? `${turn.role}:${turn.turn_id}` : turn.id;
    if (!identity) return true;
    if (seen.has(identity)) return false;
    seen.add(identity);
    return true;
  });
  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="px-3 py-2 border-b border-slate-200 bg-slate-50/70 shrink-0">
        <p className="text-[11px] font-semibold text-slate-700">
          Kênh trao đổi trực tiếp với tài xế (GSupport)
        </p>
        <p className="text-[10px] text-slate-500">
          Chỉ hiển thị hội thoại tài xế · GSupport · chuyên viên thẩm định
        </p>
      </div>

      {/* Relay transcript feed — driver, GSupport and analyst turns only */}
      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-2.5 space-y-2 text-xs">
        {relayTurns.length === 0 ? (
          <p className="py-4 text-center text-xs text-slate-500">Chưa có trao đổi nào với tài xế.</p>
        ) : (
          relayTurns.map((turn, index) => {
            const text = turn.text ?? turn.content ?? "";
            const key = turn.id ?? (turn.turn_id ? `${turn.role}-${turn.turn_id}` : `${turn.role ?? "turn"}-${index}`);
            const analyst = isAnalystTurn(turn);
            const timestamp = turn.created_at ?? turn.timestamp ?? turn.occurred_at;
            const bubbleClass = analyst
              ? "bg-indigo-50 border border-indigo-200 text-indigo-950"
              : turn.role === "driver" || turn.role === "driver_agent"
              ? "bg-emerald-600 text-white"
              : "bg-white border border-slate-200 text-slate-800";

            return (
              <div key={key} className="space-y-0.5">
                <div className="flex items-center gap-1 text-[9px] text-slate-500 px-1">
                  {analyst && (
                    <span className="font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 rounded px-1 py-0.5">
                      [Chuyên viên Thẩm định]
                    </span>
                  )}
                  <span className="font-semibold">{turnRoleLabel(turn)}</span>
                  {timestamp && (
                    <span>
                      • {new Date(timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  )}
                </div>
                <div className={`max-w-[90%] rounded-lg px-2.5 py-1.5 text-[11px] leading-relaxed shadow-2xs ${bubbleClass}`}>
                  {text}
                </div>
              </div>
            );
          })
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="mx-2.5 mb-1 flex items-center justify-between gap-2 rounded border border-rose-200 bg-rose-50 px-2 py-1.5 text-[11px] text-rose-700"
        >
          <span>{error}</span>
          <button
            type="button"
            onClick={onRetry}
            disabled={closed || sending}
            className="shrink-0 rounded border border-rose-300 bg-white px-2 py-0.5 font-medium text-rose-700 hover:bg-rose-100"
          >
            Thử lại
          </button>
        </div>
      )}

      {closed && (
        <div
          role="status"
          className="mx-2.5 mb-1 rounded border border-slate-300 bg-slate-100 px-2 py-1.5 text-[11px] font-medium text-slate-600"
        >
          Phiên trao đổi đã kết thúc
        </div>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (!closed && !sending && input.trim()) onSend();
        }}
        className="p-2 border-t border-slate-200 bg-white shrink-0 flex items-center gap-1"
      >
        <input
          type="text"
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="Nhập nội dung trao đổi với tài xế…"
          disabled={closed || sending}
          className="flex-1 h-8 rounded border border-slate-200 bg-slate-50 px-2 text-xs text-slate-800 placeholder-slate-400 focus:bg-white focus:outline-none focus:ring-1 focus:ring-emerald-600 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={closed || sending || !input.trim()}
          aria-label="Gửi"
          title="Gửi yêu cầu tới tài xế"
          className="rounded bg-emerald-600 p-1.5 text-white transition-colors hover:bg-emerald-700 disabled:opacity-40"
        >
          <span aria-hidden="true" className="material-symbols-outlined text-[14px]">send</span>
        </button>
      </form>
    </div>
  );
};
