/**
 * CrossedText - text that appears then gets a strikethrough line drawn across it.
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

export const CrossedText: React.FC<Props> = ({
  text,
  fontSize = 42,
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

  // Strikethrough line draws across after text appears
  const strikeDelay = delay + 30;
  const strikeProgress = spring({
    fps,
    frame: frame - strikeDelay,
    config: { damping: 200, mass: 1, stiffness: 150 },
  });
  const strikeWidth = interpolate(strikeProgress, [0, 1], [0, 100]);
  // Fade text to muted after strikethrough
  const textOpacity = interpolate(strikeProgress, [0, 0.5, 1], [1, 1, 0.5]);

  return (
    <div
      style={{
        position: "relative",
        opacity,
        transform: `translateY(${y}px)`,
      }}
    >
      <div
        style={{
          fontFamily: BRAND.headingFont,
          fontSize,
          fontWeight: 600,
          color: BRAND.error,
          textAlign: "center",
          lineHeight: 1.4,
          opacity: textOpacity,
        }}
      >
        {text}
      </div>
      {/* Strikethrough line */}
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "5%",
          height: 4,
          width: `${strikeWidth * 0.9}%`,
          backgroundColor: BRAND.error,
          borderRadius: 2,
          transform: "translateY(-50%)",
        }}
      />
    </div>
  );
};
