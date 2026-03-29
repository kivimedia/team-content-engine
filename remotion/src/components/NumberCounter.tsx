import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BRAND } from "../styles/brand";

interface Props {
  value: number;
  suffix?: string;
  fontSize?: number;
  color?: string;
  delay?: number;
  /** Duration of the count-up in frames */
  countFrames?: number;
}

export const NumberCounter: React.FC<Props> = ({
  value,
  suffix = "",
  fontSize = 120,
  color = BRAND.accent,
  delay = 0,
  countFrames = 45,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Entrance animation
  const entrance = spring({
    fps,
    frame: frame - delay,
    config: { damping: 200, mass: 1, stiffness: 200 },
  });

  // Count-up interpolation
  const adjustedFrame = Math.max(0, frame - delay);
  const displayValue = Math.round(
    interpolate(adjustedFrame, [0, countFrames], [0, value], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    })
  );

  const opacity = interpolate(entrance, [0, 1], [0, 1]);
  const scale = interpolate(entrance, [0, 1], [0.8, 1]);

  return (
    <div
      style={{
        fontFamily: BRAND.headingFont,
        fontSize,
        fontWeight: 800,
        color,
        opacity,
        transform: `scale(${scale})`,
        textAlign: "center",
        letterSpacing: "-0.02em",
      }}
    >
      {displayValue}
      {suffix}
    </div>
  );
};
