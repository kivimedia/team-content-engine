/**
 * Brand constants - single source of truth for all video templates.
 * Derived from zivraviv.com live CSS.
 *
 * Per-client overrides: Pass a `brand` prop to any composition.
 * Components read from BrandContext (falls back to these defaults).
 */
import React from "react";

export const BRAND = {
  // Colors
  accent: "#2ea3f2",
  accentDark: "#1a8fd8",
  dark: "#222222",
  overlay: "#1f1f1f",
  text: "#000000",
  textMuted: "#666666",
  white: "#ffffff",
  offWhite: "#f5f5f5",
  error: "#d63637",
  success: "#22c55e",

  // Gradient backgrounds for video templates
  gradientDark: "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
  gradientAccent: "linear-gradient(135deg, #0f3460 0%, #1a8fd8 100%)",

  // Typography
  headingFont: "Poppins",
  bodyFont: "Open Sans",

  // Video defaults
  fps: 30,
} as const;

/** Standard resolutions */
export const RESOLUTIONS = {
  reel: { width: 1080, height: 1920 },     // 9:16 - Reels, Shorts, Stories
  landscape: { width: 1920, height: 1080 }, // 16:9 - YouTube, LinkedIn Video
  square: { width: 1080, height: 1080 },    // 1:1 - Feed posts
} as const;

/** Animation presets */
export const ANIM = {
  /** Standard entrance spring config - professional, decisive */
  entrance: { damping: 200, mass: 1, stiffness: 200 },
  /** Softer spring for secondary elements */
  soft: { damping: 150, mass: 0.8, stiffness: 120 },
  /** Stagger delay between sequential elements (in frames at 30fps) */
  stagger: 12,
  /** Duration for accent line scale-in (frames) */
  accentLine: 15,
  /** CTA hold duration at end (seconds) */
  ctaHoldSeconds: 2,
} as const;

/** Shape of per-client brand override (all fields optional). */
export interface BrandOverride {
  accent?: string;
  accentDark?: string;
  dark?: string;
  overlay?: string;
  text?: string;
  textMuted?: string;
  white?: string;
  offWhite?: string;
  error?: string;
  success?: string;
  gradientDark?: string;
  gradientAccent?: string;
  headingFont?: string;
  bodyFont?: string;
  logoUrl?: string;
}

/** Resolved brand values (BRAND defaults + overrides). */
export type ResolvedBrand = typeof BRAND & { logoUrl?: string };

/**
 * React Context that carries the active brand.
 * Default = the hardcoded BRAND constants.
 */
export const BrandContext = React.createContext<ResolvedBrand>({ ...BRAND });

/** Merge overrides on top of BRAND defaults. */
export function resolveBrand(overrides?: BrandOverride): ResolvedBrand {
  if (!overrides) return { ...BRAND };
  return {
    ...BRAND,
    ...Object.fromEntries(
      Object.entries(overrides).filter(([, v]) => v !== undefined && v !== "")
    ),
  } as ResolvedBrand;
}

/** Hook to read the active brand from context. */
export function useBrand(): ResolvedBrand {
  return React.useContext(BrandContext);
}
