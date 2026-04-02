/**
 * Template 4: Framework Steps - "The Method"
 *
 * Steps appear one by one with number badges, each dwells 4-5s,
 * ends with CTA keyword overlay.
 *
 * Duration: 15-25s depending on step count (auto-calculated)
 * Best for: Reels, Shorts
 */
import React from "react";
import {
  AbsoluteFill,
  Sequence,
  useVideoConfig,
} from "remotion";
import { AccentLine } from "../components/AccentLine";
import { AnimatedText } from "../components/AnimatedText";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { StepCard } from "../components/StepCard";
import { resolveBrand, BrandContext } from "../styles/brand";
import type { StepFrameworkProps } from "../types";

export const StepFramework: React.FC<StepFrameworkProps> = (props) => {
  const { title, steps, ctaText = "zivraviv.com", ctaKeyword } = props;
  const resolvedBrand = resolveBrand(props.brand);
  const { durationInFrames } = useVideoConfig();
  const ctaDelay = durationInFrames - resolvedBrand.fps * 2;

  // Space steps evenly across the available time (before CTA)
  const availableFrames = ctaDelay - 60; // 60 frames for title + accent line
  const stepInterval = Math.floor(availableFrames / Math.max(steps.length, 1));

  return (
    <BrandContext.Provider value={resolvedBrand}>
    <AbsoluteFill>
      <BrandBackground variant="gradient" />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "80px 60px",
          gap: 20,
        }}
      >
        {/* Title */}
        <Sequence from={10}>
          <AnimatedText
            text={title}
            fontSize={44}
            fontWeight={700}
            color={resolvedBrand.white}
            style={{ textAlign: "left", marginBottom: 8 }}
          />
        </Sequence>

        {/* Accent line under title */}
        <Sequence from={20}>
          <AccentLine width={80} height={4} />
        </Sequence>

        {/* Steps container */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 28,
            marginTop: 20,
          }}
        >
          {steps.map((step, i) => (
            <Sequence key={i} from={50 + i * stepInterval}>
              <StepCard
                num={step.num}
                text={step.text}
                delay={0}
                isLast={i === steps.length - 1}
              />
            </Sequence>
          ))}
        </div>

        {/* CTA keyword callout (if different from footer) */}
        {ctaKeyword && (
          <Sequence from={ctaDelay - 30}>
            <div
              style={{
                marginTop: 30,
                padding: "16px 32px",
                backgroundColor: "rgba(46, 163, 242, 0.15)",
                borderLeft: `4px solid ${resolvedBrand.accent}`,
                borderRadius: 4,
              }}
            >
              <AnimatedText
                text={`Comment "${ctaKeyword}" for the full guide`}
                fontSize={26}
                fontWeight={600}
                color={resolvedBrand.accent}
                style={{ textAlign: "left" }}
              />
            </div>
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
