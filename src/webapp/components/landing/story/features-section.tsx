"use client";

import React from "react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { FEATURE_CARDS } from "../fixtures";

export function FeaturesSection() {
  return (
    <section
      id="features"
      aria-labelledby="features-heading"
      className="scroll-mt-20 py-12 border-t border-outline-variant/60 max-w-6xl mx-auto px-4"
    >
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 mb-8">
        <div>
          <h2 id="features-heading" className="text-2xl font-bold tracking-tight text-on-surface">
            All features
          </h2>
          <p className="mt-1 text-sm text-secondary max-w-xl">
            Explore our three core modules with mock data only. Every preview connects into one unified system.
          </p>
        </div>
        <Badge variant="outline" className="self-start sm:self-auto text-xs">
          Mock data only · Safe testing
        </Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {FEATURE_CARDS.map((feat) => (
          <Card key={feat.key} className="p-4 flex flex-col justify-between space-y-4">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Badge variant="secondary" className="text-[10px]">
                  {feat.badge}
                </Badge>
                <span className="material-symbols-outlined !text-[16px] text-primary" aria-hidden="true">
                  {feat.key === "workplace"
                    ? "splitscreen"
                    : feat.key === "driver"
                    ? "forum"
                    : "rule"}
                </span>
              </div>
              <h3 className="font-bold text-sm text-on-surface">
                {feat.title}
              </h3>
              <p className="text-xs text-secondary leading-relaxed">
                {feat.desc}
              </p>
            </div>

            <Link
              href={feat.route}
              aria-label={feat.linkLabel}
              className="inline-flex min-h-[44px] items-center justify-center rounded border border-primary px-4 text-xs font-semibold text-primary hover:bg-primary hover:text-on-primary transition-colors cursor-pointer focus-visible:outline-2 focus-visible:outline-primary"
            >
              Open {feat.title}
            </Link>
          </Card>
        ))}
      </div>
    </section>
  );
}
