import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold transition-colors focus:outline-none focus:ring-1 focus:ring-ring select-none",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-on-primary",
        secondary:
          "border-transparent bg-secondary-container text-on-secondary-container",
        destructive:
          "border-transparent bg-error text-on-error",
        outline: "text-foreground border border-outline-variant",
        p0: "bg-red-600 text-white font-bold",
        p0Soft: "bg-red-100 text-red-700 border border-red-200 font-bold",
        p1: "bg-amber-500 text-white font-bold",
        p1Soft: "bg-amber-100 text-amber-800 border border-amber-200 font-bold",
        p2: "bg-blue-600 text-white font-bold",
        p2Soft: "bg-blue-100 text-blue-800 border border-blue-200 font-bold",
        emeraldSoft: "bg-emerald-50 text-emerald-700 border border-emerald-200 font-medium",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
