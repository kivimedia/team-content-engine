/**
 * Template 5: Post Teaser - "The Cross-Promo"
 *
 * Simulated social post card with hook text typing in,
 * "Comment [keyword] for the full guide" end card.
 *
 * Duration: 10s (300 frames at 30fps)
 * Best for: Reels, Stories (cross-platform promotion)
 */
import React from "react";
import {
  AbsoluteFill,
  Img,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { AnimatedText } from "../components/AnimatedText";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { TypingText } from "../components/TypingText";
import { resolveBrand, BrandContext } from "../styles/brand";
import type { PostTeaserProps } from "../types";

export const PostTeaser: React.FC<PostTeaserProps> = (props) => {
  const { hookText, platform = "linkedin", imageUrl, ctaKeyword } = props;
  const resolvedBrand = resolveBrand(props.brand);
  const frame = useCurrentFrame();
  const { fps, durationInFrames } = useVideoConfig();
  const ctaDelay = durationInFrames - fps * 3;

  // Card entrance
  const cardEntrance = spring({
    fps,
    frame: frame - 10,
    config: { damping: 200, mass: 1, stiffness: 180 },
  });
  const cardOpacity = interpolate(cardEntrance, [0, 1], [0, 1]);
  const cardScale = interpolate(cardEntrance, [0, 1], [0.92, 1]);

  const platformColor = platform === "linkedin" ? "#0077b5" : "#1877f2";
  const platformLabel = platform === "linkedin" ? "LinkedIn" : "Facebook";

  return (
    <BrandContext.Provider value={resolvedBrand}>
    <AbsoluteFill>
      <BrandBackground variant="dark" />

      <AbsoluteFill
        style={{
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          alignItems: "center",
          padding: "60px 40px",
        }}
      >
        {/* Simulated social post card */}
        <div
          style={{
            width: "90%",
            maxWidth: 900,
            backgroundColor: "#ffffff",
            borderRadius: 16,
            overflow: "hidden",
            opacity: cardOpacity,
            transform: `scale(${cardScale})`,
            boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
          }}
        >
          {/* Post header with platform badge */}
          <div
            style={{
              padding: "24px 30px 16px",
              display: "flex",
              alignItems: "center",
              gap: 16,
            }}
          >
            {/* Avatar circle */}
            <div
              style={{
                width: 48,
                height: 48,
                borderRadius: 24,
                backgroundColor: resolvedBrand.accent,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: resolvedBrand.headingFont,
                fontSize: 20,
                fontWeight: 700,
                color: resolvedBrand.white,
              }}
            >
              ZR
            </div>
            <div>
              <div
                style={{
                  fontFamily: resolvedBrand.headingFont,
                  fontSize: 18,
                  fontWeight: 700,
                  color: resolvedBrand.dark,
                }}
              >
                Ziv Raviv
              </div>
              <div
                style={{
                  fontFamily: resolvedBrand.bodyFont,
                  fontSize: 14,
                  color: resolvedBrand.textMuted,
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                }}
              >
                <span
                  style={{
                    display: "inline-block",
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: platformColor,
                  }}
                />
                {platformLabel}
              </div>
            </div>
          </div>

          {/* Hook text typing effect */}
          <div style={{ padding: "8px 30px 24px" }}>
            <Sequence from={25}>
              <TypingText text={hookText} fontSize={28} delay={0} />
            </Sequence>
          </div>

          {/* Optional image */}
          {imageUrl && (
            <Sequence from={60}>
              <div style={{ position: "relative", width: "100%", height: 300 }}>
                <Img
                  src={imageUrl}
                  style={{
                    width: "100%",
                    height: "100%",
                    objectFit: "cover",
                  }}
                />
              </div>
            </Sequence>
          )}

          {/* Engagement bar (fake) */}
          <Sequence from={80}>
            <div
              style={{
                padding: "16px 30px",
                borderTop: "1px solid #eee",
                display: "flex",
                gap: 30,
                fontFamily: resolvedBrand.bodyFont,
                fontSize: 14,
                color: resolvedBrand.textMuted,
              }}
            >
              <span>Like</span>
              <span>Comment</span>
              <span>Share</span>
            </div>
          </Sequence>
        </div>

        {/* CTA keyword end card */}
        {ctaKeyword && (
          <Sequence from={ctaDelay}>
            <div
              style={{
                marginTop: 40,
                textAlign: "center",
              }}
            >
              <AnimatedText
                text={`Comment "${ctaKeyword}" to get the full guide`}
                fontSize={32}
                fontWeight={700}
                color={resolvedBrand.accent}
              />
            </div>
          </Sequence>
        )}
      </AbsoluteFill>

      {/* CTA footer */}
      <Sequence from={ctaDelay}>
        <BrandFooter ctaText="zivraviv.com" />
      </Sequence>
    </AbsoluteFill>
    </BrandContext.Provider>
  );
};
