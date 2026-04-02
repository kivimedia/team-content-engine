import React from "react";
import { interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { useBrand } from "../styles/brand";

interface Props {
  text: string;
  fontSize?: number;
  color?: string;
  fontWeight?: number;
  delay?: number;
  style?: React.CSSProperties;
  /** Animate word-by-word instead of all at once */
  wordByWord?: boolean;
}

export const AnimatedText: React.FC<Props> = ({
  text,
  fontSize = 64,
  color,
  fontWeight = 700,
  delay = 0,
  style,
  wordByWord = false,
}) => {
  const brand = useBrand();
  const resolvedColor = color ?? brand.white;
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  if (wordByWord) {
    const words = text.split(" ");
    return (
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.25em",
          justifyContent: "center",
          ...style,
        }}
      >
        {words.map((word, i) => {
          const wordDelay = delay + i * 4;
          const progress = spring({
            fps,
            frame: frame - wordDelay,
            config: { damping: 200, mass: 1, stiffness: 200 },
          });
          const opacity = interpolate(progress, [0, 1], [0, 1]);
          const y = interpolate(progress, [0, 1], [20, 0]);

          return (
            <span
              key={i}
              style={{
                fontFamily: brand.headingFont,
                fontSize,
                fontWeight,
                color: resolvedColor,
                opacity,
                transform: `translateY(${y}px)`,
                display: "inline-block",
              }}
            >
              {word}
            </span>
          );
        })}
      </div>
    );
  }

  // Single block animation
  const progress = spring({
    fps,
    frame: frame - delay,
    config: { damping: 200, mass: 1, stiffness: 200 },
  });
  const opacity = interpolate(progress, [0, 1], [0, 1]);
  const y = interpolate(progress, [0, 1], [30, 0]);

  return (
    <div
      style={{
        fontFamily: brand.headingFont,
        fontSize,
        fontWeight,
        color: resolvedColor,
        opacity,
        transform: `translateY(${y}px)`,
        textAlign: "center",
        lineHeight: 1.3,
        ...style,
      }}
    >
      {text}
    </div>
  );
};
