import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Render a stall duration; missing evidence shows as "Không đủ dữ liệu", never as 0. */
export function formatStallDuration(seconds: number | null | undefined): string {
  return seconds === null || seconds === undefined ? "Không đủ dữ liệu" : `${seconds}s`;
}
