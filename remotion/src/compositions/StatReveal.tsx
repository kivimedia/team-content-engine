/**
 * Template 2: Stat Reveal - "The Proof Point"
 *
 * Large number counts up from 0 to the stat value,
 * claim text fades in below, source attribution at bottom.
 *
 * Duration: 8-15s (240-450 frames at 30fps)
 * Best for: LinkedIn feed, Reels
 */
import React from "react";
import { AbsoluteFill, Sequence, useVideoConfig } from "remotion";
import { AccentLine } from "../components/AccentLine";
import { AnimatedText } from "../components/AnimatedText";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { NumberCounter } from "../components/NumberCounter";
import { resolveBrand, BrandContext } from "../styles/brand";
import type { StatRevealProps } from "../types";

export const StatReveal: React.FC<StatRevealProps> = (props) => {
  const { statValue, statSuffix = "", claimText, sourceText, ctaText = "zivraviv.com" } = props;
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
          padding: "80px 60px",
          gap: 30,
        }}
      >
        {/* Big number with count-up */}
        <Sequence from={15}>
          <NumberCounter
            value={statValue}
            suffix={statSuffix}
            fontSize={140}
            countFrames={50}
          />
        </Sequence>

        {/* Accent line */}
        <Sequence from={50}>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <AccentLine width={120} height={4} />
          </div>
        </Sequence>

        {/* Claim text */}
        <Sequence from={60}>
          <AnimatedText
            text={claimText}
            fontSize={40}
            fontWeight={500}
            color={resolvedBrand.white}
            style={{
              maxWidth: 800,
              padding: "0 40px",
              lineHeight: "1.4",
            }}
          />
        </Sequence>

        {/* Source attribution */}
        {sourceText && (
          <Sequence from={90}>
            <AnimatedText
              text={sourceText}
              fontSize={20}
              fontWeight={400}
              color={resolvedBrand.textMuted}
              style={{ letterSpacing: "0.02em" }}
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
