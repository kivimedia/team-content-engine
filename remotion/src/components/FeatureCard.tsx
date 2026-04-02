/**
 * FeatureCard - animated feature card with icon bullet + text.
 * Used in ProductDemo "features" scenes.
 */
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useBrand } from "../styles/brand";

interface FeatureCardProps {
  text: string;
  index: number;
  delay?: number;
}

export const FeatureCard: React.FC<FeatureCardProps> = ({
  text,
  index,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const brand = useBrand();

  const staggerDelay = delay + index * 12;

  const entrance = spring({
    frame: frame - staggerDelay,
    fps,
    config: { damping: 200, mass: 1, stiffness: 180 },
  });

  const translateX = interpolate(entrance, [0, 1], [-40, 0]);
  const opacity = interpolate(entrance, [0, 1], [0, 1]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "14px 20px",
        transform: `translateX(${translateX}px)`,
        opacity,
      }}
    >
      {/* Check icon */}
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: "50%",
          background: brand.accent,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          flexShrink: 0,
          fontSize: 18,
          color: brand.white,
          fontWeight: 700,
        }}
      >
        {"\u2713"}
      </div>
      {/* Feature text */}
      <span
        style={{
          fontSize: 28,
          color: brand.white,
          fontFamily: brand.bodyFont,
          fontWeight: 500,
          lineHeight: 1.3,
        }}
      >
        {text}
      </span>
    </div>
  );
};
