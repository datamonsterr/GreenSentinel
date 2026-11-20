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
        p0: "bg-gs-red text-white font-bold",
        p0Soft: "bg-gs-red-soft text-gs-red border border-gs-red/30 font-bold",
        p1: "bg-gs-amber text-white font-bold",
        p1Soft: "bg-gs-amber-soft text-gs-amber-ink border border-gs-amber/30 font-bold",
        p2: "bg-gs-blue text-white font-bold",
        p2Soft: "bg-gs-blue-soft text-gs-blue border border-gs-blue/30 font-bold",
        emeraldSoft: "bg-gs-green-soft text-gs-green-ink border border-gs-green/30 font-medium",
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
