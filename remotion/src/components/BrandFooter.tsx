import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BRAND } from "../styles/brand";

interface Props {
  ctaText?: string;
  delay?: number;
}

export const BrandFooter: React.FC<Props> = ({
  ctaText = "zivraviv.com",
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    fps,
    frame: frame - delay,
    config: { damping: 150, mass: 0.8, stiffness: 120 },
  });

  const opacity = interpolate(progress, [0, 1], [0, 0.9]);
  const y = interpolate(progress, [0, 1], [20, 0]);

  return (
    <div
      style={{
        position: "absolute",
        bottom: 80,
        left: 0,
        right: 0,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        gap: 12,
        opacity,
        transform: `translateY(${y}px)`,
      }}
    >
      <div
        style={{
          width: 60,
          height: 3,
          backgroundColor: BRAND.accent,
          borderRadius: 2,
        }}
      />
      <div
        style={{
          fontFamily: BRAND.bodyFont,
          fontSize: 28,
          fontWeight: 600,
          color: BRAND.accent,
          letterSpacing: "0.05em",
        }}
      >
        {ctaText}
      </div>
    </div>
  );
};
