import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary disabled:pointer-events-none disabled:opacity-50 select-none cursor-pointer",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-on-primary shadow hover:bg-primary-container",
        destructive:
          "bg-error text-on-error shadow-sm hover:bg-error/90",
        outline:
          "border border-outline-variant/80 bg-surface-container-lowest hover:bg-surface-container hover:text-on-surface",
        secondary:
          "bg-surface-container text-on-surface shadow-xs hover:bg-surface-container-high",
        ghost: "hover:bg-surface-container hover:text-on-surface",
        link: "text-primary underline-offset-4 hover:underline",
        emerald: "bg-emerald-600 hover:bg-emerald-700 text-white shadow-xs",
        amber: "bg-amber-500 hover:bg-amber-600 text-white shadow-xs",
      },
      size: {
        default: "h-8 px-3 py-1.5",
        sm: "h-7 rounded px-2 text-xs",
        lg: "h-9 rounded px-4 text-sm",
        icon: "h-7 w-7",
        "icon-sm": "h-6 w-6 text-xs",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
