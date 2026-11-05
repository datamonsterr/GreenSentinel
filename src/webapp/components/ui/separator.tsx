import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const separatorVariants = cva("shrink-0 bg-outline-variant/60", {
  variants: {
    orientation: {
      horizontal: "h-px w-full",
      vertical: "h-full w-px",
    },
  },
  defaultVariants: { orientation: "horizontal" },
});

interface SeparatorProps extends React.HTMLAttributes<HTMLDivElement>, VariantProps<typeof separatorVariants> {}

const Separator = React.forwardRef<HTMLDivElement, SeparatorProps>(
  ({ className, orientation = "horizontal", ...props }, ref) => (
    <div
      {...props}
      ref={ref}
      role="separator"
      aria-orientation={orientation ?? "horizontal"}
      className={cn(separatorVariants({ orientation }), className)}
    />
  ),
);
Separator.displayName = "Separator";

export { Separator };
