/**
 * Prop interfaces for all video templates.
 * These map 1:1 to the JSON payload the Python agent writes.
 */

/** Template 1: Hook Reel - animated thesis statement */
export interface HookReelProps {
  thesis: string;
  attribution?: string;
  ctaText?: string;
}

/** Template 2: Stat Reveal - number count-up with claim */
export interface StatRevealProps {
  statValue: number;
  statSuffix?: string; // e.g. "%", "x", "M", "K"
  claimText: string;
  sourceText?: string;
  ctaText?: string;
}

/** Template 3: Before/After Split */
export interface BeforeAfterProps {
  title?: string;
  before: string;
  after: string;
  ctaText?: string;
}

/** Template 4: Framework Steps */
export interface StepFrameworkProps {
  title: string;
  steps: Array<{ num: number; text: string }>;
  ctaText?: string;
  ctaKeyword?: string;
}

/** Template 5: Post Teaser */
export interface PostTeaserProps {
  hookText: string;
  platform: "linkedin" | "facebook";
  imageUrl?: string;
  ctaKeyword?: string;
}

/** Visual type for a narration segment */
export type NarrationVisualType =
  | "animated_text"
  | "number_counter"
  | "crossed_text"
  | "reveal_text"
  | "step_card"
  | "brand_footer"
  | "image_overlay"
  | "typing_text";

/** A single segment in a narrated video */
export interface NarrationSegment {
  narratorText: string;
  visualType: NarrationVisualType;
  visualProps: Record<string, unknown>;
  startSec: number;
  endSec: number;
}

/** Template 6: Narrated Video - voiceover-driven composition */
export interface NarratedVideoProps {
  audioUrl: string;
  segments: NarrationSegment[];
  ctaText?: string;
}
