import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useBrand } from "../styles/brand";

interface Props {
  width?: number;
  height?: number;
  color?: string;
  delay?: number;
}

export const AccentLine: React.FC<Props> = ({
  width = 80,
  height = 4,
  color,
  delay = 0,
}) => {
  const brand = useBrand();
  const resolvedColor = color ?? brand.accent;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const progress = spring({
    fps,
    frame: frame - delay,
    config: { damping: 200, mass: 1, stiffness: 200 },
  });

  const scaleX = interpolate(progress, [0, 1], [0, 1]);

  return (
    <div
      style={{
        width,
        height,
        backgroundColor: resolvedColor,
        borderRadius: height / 2,
        transform: `scaleX(${scaleX})`,
        transformOrigin: "left center",
      }}
    />
  );
};
