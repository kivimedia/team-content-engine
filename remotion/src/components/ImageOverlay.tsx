/**
 * ImageOverlay - displays a screenshot/B-roll image with a subtle Ken Burns zoom.
 * Used in NarratedVideo for screen recording segments (V1: static images).
 */
import React from "react";
import {
  Img,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { BRAND } from "../styles/brand";

interface Props {
  src: string;
  caption?: string;
  /** Zoom intensity - 1.0 = no zoom, 1.1 = 10% zoom over segment */
  zoomIntensity?: number;
}

export const ImageOverlay: React.FC<Props> = ({
  src,
  caption,
  zoomIntensity = 1.08,
}) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Ken Burns slow zoom
  const scale = interpolate(frame, [0, durationInFrames], [1, zoomIntensity], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Fade in
  const opacity = interpolate(frame, [0, 10], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          width: "85%",
          maxHeight: "75%",
          borderRadius: 12,
          overflow: "hidden",
          boxShadow: "0 16px 48px rgba(0,0,0,0.5)",
          border: `2px solid rgba(46, 163, 242, 0.3)`,
        }}
      >
        <Img
          src={src}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            transform: `scale(${scale})`,
          }}
        />
      </div>
      {caption && (
        <div
          style={{
            marginTop: 20,
            fontFamily: BRAND.bodyFont,
            fontSize: 22,
            fontWeight: 600,
            color: BRAND.textMuted,
            textAlign: "center",
          }}
        >
          {caption}
        </div>
      )}
    </div>
  );
};
