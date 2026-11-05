"use client";

import React, { useState, useEffect } from "react";
import {
  fetchAccountSettings,
  updateAccountSettings,
} from "@/lib/api-client";
import { UserAccountSettings } from "@/types/schemas";

interface AccountSettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function AccountSettingsModal({ isOpen, onClose }: AccountSettingsModalProps) {
  const [settings, setSettings] = useState<UserAccountSettings | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingName, setSavingName] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;
    let active = true;
    setLoading(true);
    setMessage(null);

    fetchAccountSettings()
      .then((data) => {
        if (!active) return;
        setSettings(data);
        setDisplayName(data.display_name);
      })
      .catch((err) => {
        if (active) setMessage(err instanceof Error ? err.message : "Failed to load account settings");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSaveName = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!displayName.trim() || savingName) return;
    setSavingName(true);
    setMessage(null);
    try {
      const updated = await updateAccountSettings({ display_name: displayName.trim() });
      setSettings(updated);
      setMessage("Profile name updated successfully");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to update profile name");
    } finally {
      setSavingName(false);
    }
  };

  const getRoleBadge = (role: string) => {
    switch (role) {
      case "admin":
        return "bg-purple-100 text-purple-800 border-purple-200";
      case "driver":
        return "bg-amber-100 text-amber-800 border-amber-200";
      case "fraud_analyst":
      case "analyst":
      default:
        return "bg-emerald-100 text-emerald-800 border-emerald-200";
    }
  };

  const formatRoleLabel = (role: string) => {
    switch (role) {
      case "admin":
        return "System Admin";
      case "driver":
        return "Driver (Driver App)";
      case "fraud_analyst":
      case "analyst":
        return "Fraud Analyst (Adjudication)";
      default:
        return role;
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-settings-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
    >
      <div className="bg-white rounded-lg shadow-xl border border-slate-200 max-w-2xl w-full max-h-[90vh] flex flex-col overflow-hidden">
        {/* Header */}
        <div className="px-5 py-3 border-b border-slate-200 flex items-center justify-between bg-slate-50">
          <div className="flex items-center gap-2">
            <span className="material-symbols-outlined text-emerald-600 text-[20px]">manage_accounts</span>
            <h2 id="account-settings-title" className="text-sm font-semibold text-slate-800">
              Account Settings &amp; Permissions
            </h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close settings"
            className="text-slate-400 hover:text-slate-600 p-1 rounded"
          >
            <span className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>

        {/* Content */}
        <div className="p-5 overflow-y-auto space-y-6 text-xs text-slate-700">
          {message && (
            <div
              role="alert"
              className={`p-2.5 rounded border text-xs ${
                message.includes("success") || message.includes("updated")
                  ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                  : "bg-red-50 border-red-200 text-red-700"
              }`}
            >
              {message}
            </div>
          )}

          {loading ? (
            <div className="py-8 text-center text-slate-500">Loading account configuration…</div>
          ) : settings ? (
            <>
              {/* Profile Card */}
              <div className="p-3.5 bg-slate-50 rounded border border-slate-200 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold text-sm text-slate-900">{settings.display_name}</div>
                    <div className="text-[11px] text-slate-500 font-mono">ID: {settings.id}</div>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded-full text-[11px] font-medium border ${getRoleBadge(
                      settings.primary_role
                    )}`}
                  >
                    {formatRoleLabel(settings.primary_role)}
                  </span>
                </div>

                <form onSubmit={handleSaveName} className="flex items-center gap-2 pt-1">
                  <label htmlFor="settings-name-input" className="sr-only">
                    Display Name
                  </label>
                  <input
                    id="settings-name-input"
                    type="text"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Enter display name"
                    className="flex-1 h-7 px-2 border rounded bg-white text-xs border-slate-300 focus:outline-none focus:border-emerald-600"
                  />
                  <button
                    type="submit"
                    disabled={savingName || !displayName.trim()}
                    className="h-7 px-3 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded font-medium text-xs transition-colors"
                  >
                    {savingName ? "Saving…" : "Save Name"}
                  </button>
                </form>
              </div>

              {/* Roles and Capabilities Summary */}
              <div className="space-y-2">
                <h3 className="font-semibold text-slate-800 text-xs">Role Capabilities</h3>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                  <div
                    className={`p-2.5 rounded border text-[11px] ${
                      settings.roles.includes("fraud_analyst") || settings.roles.includes("analyst")
                        ? "bg-emerald-50/60 border-emerald-300 text-emerald-950 font-medium"
                        : "bg-slate-50 border-slate-200 text-slate-500"
                    }`}
                  >
                    <div className="font-semibold mb-1">Fraud Analyst</div>
                    <p className="text-[10px] leading-tight">
                      Adjudicate dispute cases: Approve, Dismiss, or Reject cases.
                    </p>
                  </div>

                  <div
                    className={`p-2.5 rounded border text-[11px] ${
                      settings.roles.includes("admin")
                        ? "bg-purple-50/60 border-purple-300 text-purple-950 font-medium"
                        : "bg-slate-50 border-slate-200 text-slate-500"
                    }`}
                  >
                    <div className="font-semibold mb-1">System Admin</div>
                    <p className="text-[10px] leading-tight">
                      Fleet analytics, audit logs, and system operations.
                    </p>
                  </div>

                  <div
                    className={`p-2.5 rounded border text-[11px] ${
                      settings.roles.includes("driver")
                        ? "bg-amber-50/60 border-amber-300 text-amber-950 font-medium"
                        : "bg-slate-50 border-slate-200 text-slate-500"
                    }`}
                  >
                    <div className="font-semibold mb-1">Driver</div>
                    <p className="text-[10px] leading-tight">
                      Restricted to Driver Care Portal (/driver) for trip dispute review.
                    </p>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <p className="text-red-600">Unable to load account settings.</p>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-2.5 border-t border-slate-200 bg-slate-50 flex justify-end">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-900 text-white font-medium text-xs transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
