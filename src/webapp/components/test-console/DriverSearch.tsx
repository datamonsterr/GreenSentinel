"use client";

import React, { useState, useEffect, useRef } from "react";
import { Search, UserCheck, X, AlertCircle, Loader2 } from "lucide-react";
import {
  searchClerkDrivers,
  fetchClerkLinkedDrivers,
  type ClerkLinkedDriver,
} from "@/lib/testApiClient";

export interface DriverSearchProps {
  selectedDriver: ClerkLinkedDriver | null;
  onSelectDriver: (driver: ClerkLinkedDriver | null) => void;
  disabled?: boolean;
  className?: string;
}

export function DriverSearch({
  selectedDriver,
  onSelectDriver,
  disabled = false,
  className = "",
}: DriverSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ClerkLinkedDriver[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const searchRequestIdRef = useRef(0);

  // Debounced search on query change
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 3) return;

    const timer = setTimeout(() => {
      const requestId = ++searchRequestIdRef.current;
      setLoading(true);
      setError(null);

      searchClerkDrivers(trimmed)
        .then((drivers) => {
          if (requestId !== searchRequestIdRef.current) return;
          setResults(drivers);
          setHasSearched(true);
          setIsOpen(true);
        })
        .catch((err) => {
          if (requestId !== searchRequestIdRef.current) return;
          setError(err instanceof Error ? err.message : "Lỗi khi tìm kiếm tài xế");
          setResults([]);
          setHasSearched(true);
          setIsOpen(true);
        })
        .finally(() => {
          if (requestId === searchRequestIdRef.current) {
            setLoading(false);
          }
        });
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  // Load available linked drivers on initial focus / click if no query yet
  const handleFocus = () => {
    if (!query.trim() && results.length === 0 && !hasSearched) {
      setLoading(true);
      fetchClerkLinkedDrivers()
        .then((drivers) => {
          setResults(drivers);
          setIsOpen(true);
        })
        .catch(() => {
          // ignore background preload error
        })
        .finally(() => setLoading(false));
    } else {
      setIsOpen(true);
    }
  };

  return (
    <div data-testid="driver-search-container" className={`space-y-1.5 ${className}`}>
      <label className="text-[11px] font-bold text-secondary uppercase tracking-wider block">
        Tài xế thực hiện (Clerk-linked)
      </label>

      {/* Selected Driver Card */}
      {selectedDriver ? (
        <div
          data-testid="selected-driver-card"
          className="flex items-center justify-between p-2 bg-emerald-50 border border-emerald-300 rounded text-xs"
        >
          <div className="flex items-center gap-2 min-w-0">
            <UserCheck className="w-4 h-4 text-emerald-700 shrink-0" />
            <div className="min-w-0">
              <div className="font-bold text-emerald-950 truncate">
                {selectedDriver.display_name}
              </div>
              <div className="text-[11px] text-emerald-800 font-mono truncate">
                {selectedDriver.email}
              </div>
              {selectedDriver.license_plate && (
                <div className="text-[10px] text-emerald-700">
                  Biển số: {selectedDriver.license_plate}
                </div>
              )}
            </div>
          </div>

          {!disabled && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                onSelectDriver(null);
                setQuery("");
                setResults([]);
                setHasSearched(false);
              }}
              aria-label="Đổi tài xế"
              title="Đổi tài xế khác"
              className="p-1 text-emerald-700 hover:text-rose-600 hover:bg-rose-50 rounded transition cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
      ) : (
        /* Driver Search Input */
        <div className="relative">
          <div className="flex items-center border border-slate-300 rounded bg-white px-2 h-8 focus-within:border-primary focus-within:ring-1 focus-within:ring-primary">
            <Search className="w-3.5 h-3.5 text-slate-400 shrink-0 mr-1.5" />
            <input
              type="text"
              value={query}
              disabled={disabled}
              placeholder="Tìm tài xế theo email (tối thiểu 3 ký tự)..."
              aria-label="Tìm tài xế"
              onFocus={handleFocus}
              onChange={(e) => {
                const val = e.target.value;
                setQuery(val);
                if (val.trim().length < 3) {
                  setResults([]);
                  setError(null);
                  setLoading(false);
                  setHasSearched(false);
                }
              }}
              className="w-full text-xs text-slate-800 placeholder:text-slate-400 bg-transparent focus:outline-none disabled:cursor-not-allowed"
            />
            {loading && <Loader2 className="w-3.5 h-3.5 text-primary animate-spin shrink-0" />}
            {query && !loading && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  setResults([]);
                  setError(null);
                  setLoading(false);
                  setHasSearched(false);
                }}
                aria-label="Xóa nội dung tìm kiếm"
                className="text-slate-400 hover:text-slate-600 p-0.5"
              >
                <X className="w-3 h-3" />
              </button>
            )}
          </div>

          {/* Search Results Dropdown */}
          {isOpen && (query.trim().length >= 3 || results.length > 0) && (
            <div
              data-testid="driver-search-results"
              className="absolute left-0 right-0 top-full mt-1 bg-white border border-slate-200 rounded-md shadow-lg max-h-48 overflow-y-auto z-40 text-xs"
            >
              {error && (
                <div
                  data-testid="driver-search-error"
                  className="p-2 text-rose-600 flex items-center gap-1.5 text-[11px]"
                >
                  <AlertCircle className="w-3.5 h-3.5 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {!error && results.length === 0 && hasSearched && (
                <div
                  data-testid="driver-search-empty"
                  className="p-2 text-slate-500 text-center italic text-[11px]"
                >
                  Không tìm thấy tài xế Clerk nào phù hợp.
                </div>
              )}

              {results.length > 0 && (
                <ul className="py-1 divide-y divide-slate-100" role="listbox">
                  {results.map((driver) => (
                    <li key={driver.driver_id} role="option" aria-selected="false">
                      <button
                        type="button"
                        onClick={() => {
                          onSelectDriver(driver);
                          setIsOpen(false);
                          setQuery("");
                        }}
                        className="w-full text-left px-2.5 py-1.5 hover:bg-slate-50 flex items-center justify-between cursor-pointer"
                      >
                        <div className="min-w-0 pr-2">
                          <div className="font-semibold text-slate-900 truncate">
                            {driver.display_name}
                          </div>
                          <div className="text-[10px] text-slate-500 font-mono truncate">
                            {driver.email}
                          </div>
                        </div>
                        {driver.license_plate && (
                          <span className="text-[10px] px-1.5 py-0.5 bg-slate-100 rounded text-slate-600 shrink-0">
                            {driver.license_plate}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
