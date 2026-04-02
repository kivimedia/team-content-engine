/**
 * Template 3: Before/After Split - "The Shift"
 *
 * Split-screen sequential reveal. "Before" state in muted/red, crossed out.
 * "After" state highlights in brand blue. Transition between them.
 *
 * Duration: 12s (360 frames at 30fps)
 * Best for: Reels, LinkedIn Video
 */
import React from "react";
import {
  AbsoluteFill,
  Sequence,
  useVideoConfig,
} from "remotion";
import { AccentLine } from "../components/AccentLine";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { CrossedText } from "../components/CrossedText";
import { RevealText } from "../components/RevealText";
import { resolveBrand, BrandContext } from "../styles/brand";
import type { BeforeAfterProps } from "../types";

export const BeforeAfter: React.FC<BeforeAfterProps> = (props) => {
  const { title, before, after, ctaText = "zivraviv.com" } = props;
  const resolvedBrand = resolveBrand(props.brand);
  const { durationInFrames } = useVideoConfig();
  const ctaDelay = durationInFrames - resolvedBrand.fps * 2;

  return (
    <BrandContext.Provider value={resolvedBrand}>
    <AbsoluteFill>
      <BrandBackground variant="gradient" />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          padding: "80px 50px",
          gap: 40,
        }}
      >
        {/* Optional title */}
        {title && (
          <Sequence from={5}>
            <div
              style={{
                fontFamily: resolvedBrand.bodyFont,
                fontSize: 22,
                fontWeight: 600,
                color: resolvedBrand.textMuted,
                textTransform: "uppercase",
                letterSpacing: "0.15em",
              }}
            >
              {title}
            </div>
          </Sequence>
        )}

        {/* BEFORE label */}
        <Sequence from={15}>
          <div
            style={{
              fontFamily: resolvedBrand.bodyFont,
              fontSize: 18,
              fontWeight: 700,
              color: resolvedBrand.error,
              textTransform: "uppercase",
              letterSpacing: "0.2em",
            }}
          >
            BEFORE
          </div>
        </Sequence>

        {/* Before text with strikethrough */}
        <Sequence from={20}>
          <div style={{ maxWidth: 850, padding: "0 20px" }}>
            <CrossedText text={before} fontSize={42} delay={0} />
          </div>
        </Sequence>

        {/* Accent line divider */}
        <Sequence from={80}>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <AccentLine width={140} height={4} />
          </div>
        </Sequence>

        {/* AFTER label */}
        <Sequence from={95}>
          <div
            style={{
              fontFamily: resolvedBrand.bodyFont,
              fontSize: 18,
              fontWeight: 700,
              color: resolvedBrand.accent,
              textTransform: "uppercase",
              letterSpacing: "0.2em",
            }}
          >
            AFTER
          </div>
        </Sequence>

        {/* After text with reveal */}
        <Sequence from={100}>
          <div style={{ maxWidth: 850, padding: "0 20px" }}>
            <RevealText text={after} fontSize={46} delay={0} />
          </div>
        </Sequence>
      </AbsoluteFill>

      {/* CTA footer */}
      <Sequence from={ctaDelay}>
        <BrandFooter ctaText={ctaText} />
      </Sequence>
    </AbsoluteFill>
    </BrandContext.Provider>
  );
};
