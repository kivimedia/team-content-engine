/**
 * StepCard - numbered step with badge and text, slides in from left.
 * Extracted from StepFramework composition for reuse in NarratedVideo.
 */
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BRAND } from "../styles/brand";

interface Props {
  num: number;
  text: string;
  delay?: number;
  isLast?: boolean;
}

export const StepCard: React.FC<Props> = ({
  num,
  text,
  delay = 0,
  isLast = false,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    fps,
    frame: frame - delay,
    config: { damping: 200, mass: 1, stiffness: 200 },
  });
  const opacity = interpolate(entrance, [0, 1], [0, 1]);
  const x = interpolate(entrance, [0, 1], [-40, 0]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 24,
        opacity,
        transform: `translateX(${x}px)`,
      }}
    >
      {/* Number badge */}
      <div
        style={{
          minWidth: 56,
          height: 56,
          borderRadius: 28,
          backgroundColor: isLast ? BRAND.accent : "rgba(46, 163, 242, 0.2)",
          border: `2px solid ${BRAND.accent}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: BRAND.headingFont,
          fontSize: 26,
          fontWeight: 800,
          color: isLast ? BRAND.white : BRAND.accent,
        }}
      >
        {num}
      </div>

      {/* Step text */}
      <div
        style={{
          fontFamily: BRAND.headingFont,
          fontSize: 34,
          fontWeight: 500,
          color: BRAND.white,
          lineHeight: 1.4,
          flex: 1,
          paddingTop: 8,
        }}
      >
        {text}
      </div>
    </div>
  );
};
