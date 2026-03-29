/**
 * RevealText - text that fades in with a scale-up effect.
 * Extracted from BeforeAfter composition for reuse in NarratedVideo.
 */
import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { BRAND } from "../styles/brand";

interface Props {
  text: string;
  fontSize?: number;
  delay?: number;
}

export const RevealText: React.FC<Props> = ({
  text,
  fontSize = 46,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const entrance = spring({
    fps,
    frame: frame - delay,
    config: { damping: 200, mass: 1, stiffness: 200 },
  });
  const opacity = interpolate(entrance, [0, 1], [0, 1]);
  const y = interpolate(entrance, [0, 1], [30, 0]);
  const scale = interpolate(entrance, [0, 1], [0.95, 1]);

  return (
    <div
      style={{
        fontFamily: BRAND.headingFont,
        fontSize,
        fontWeight: 700,
        color: BRAND.accent,
        textAlign: "center",
        lineHeight: 1.4,
        opacity,
        transform: `translateY(${y}px) scale(${scale})`,
      }}
    >
      {text}
    </div>
  );
};
