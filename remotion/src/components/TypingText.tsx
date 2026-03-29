/**
 * TypingText - typewriter effect with blinking cursor.
 * Extracted from PostTeaser composition for reuse in NarratedVideo.
 */
import React from "react";
import { useCurrentFrame } from "remotion";
import { BRAND } from "../styles/brand";

interface Props {
  text: string;
  fontSize?: number;
  delay?: number;
  charsPerFrame?: number;
}

export const TypingText: React.FC<Props> = ({
  text,
  fontSize = 28,
  delay = 0,
  charsPerFrame = 0.8,
}) => {
  const frame = useCurrentFrame();

  const adjustedFrame = Math.max(0, frame - delay);
  const visibleChars = Math.min(
    text.length,
    Math.floor(adjustedFrame * charsPerFrame)
  );
  const displayText = text.slice(0, visibleChars);

  // Blinking cursor
  const showCursor =
    visibleChars < text.length && Math.floor(frame / 8) % 2 === 0;

  return (
    <div
      style={{
        fontFamily: BRAND.headingFont,
        fontSize,
        fontWeight: 700,
        color: BRAND.white,
        lineHeight: 1.4,
        textAlign: "left",
      }}
    >
      {displayText}
      {showCursor && (
        <span style={{ color: BRAND.accent, fontWeight: 300 }}>|</span>
      )}
    </div>
  );
};
