/**
 * Template 1: Hook Reel - "The Scroll-Stopper"
 *
 * Animates the post's thesis statement with kinetic typography
 * on a branded gradient background. Word-by-word spring animation.
 *
 * Duration: 5-10s (150-300 frames at 30fps)
 * Best for: LinkedIn Video, Reels, Shorts
 */
import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { AccentLine } from "../components/AccentLine";
import { AnimatedText } from "../components/AnimatedText";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { resolveBrand, BrandContext } from "../styles/brand";
import type { HookReelProps } from "../types";

export const HookReel: React.FC<HookReelProps> = (props) => {
  const { thesis, attribution, ctaText = "zivraviv.com" } = props;
  const resolvedBrand = resolveBrand(props.brand);
  const { durationInFrames } = useVideoConfig();
  const ctaDelay = durationInFrames - resolvedBrand.fps * 2; // Show CTA 2s before end

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
          padding: "80px 60px",
          gap: 40,
        }}
      >
        {/* Accent line enters first */}
        <Sequence from={10}>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <AccentLine width={100} height={5} />
          </div>
        </Sequence>

        {/* Thesis text - word by word */}
        <Sequence from={20}>
          <AnimatedText
            text={thesis}
            fontSize={56}
            fontWeight={700}
            color={resolvedBrand.white}
            wordByWord
            style={{
              maxWidth: 900,
              padding: "0 20px",
            }}
          />
        </Sequence>

        {/* Attribution line */}
        {attribution && (
          <Sequence from={60}>
            <AnimatedText
              text={attribution}
              fontSize={24}
              fontWeight={400}
              color={resolvedBrand.textMuted}
              style={{ letterSpacing: "0.03em" }}
            />
          </Sequence>
        )}
      </AbsoluteFill>

      {/* CTA footer */}
      <Sequence from={ctaDelay}>
        <BrandFooter ctaText={ctaText} />
      </Sequence>
    </AbsoluteFill>
    </BrandContext.Provider>
  );
};
