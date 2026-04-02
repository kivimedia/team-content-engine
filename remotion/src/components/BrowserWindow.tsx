/**
 * BrowserWindow - fake browser chrome wrapping a screenshot or video.
 * Used in ProductDemo template to showcase app UI.
 */
import React from "react";
import {
  AbsoluteFill,
  Img,
  OffthreadVideo,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { useBrand } from "../styles/brand";

interface BrowserWindowProps {
  /** URL of screenshot or video to display inside the browser */
  src: string;
  /** Whether src is a video (true) or image (false, default) */
  isVideo?: boolean;
  /** Optional URL bar text */
  urlText?: string;
  /** Delay in frames before entrance animation */
  delay?: number;
}

export const BrowserWindow: React.FC<BrowserWindowProps> = ({
  src,
  isVideo = false,
  urlText = "app.example.com",
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const brand = useBrand();

  const entrance = spring({
    frame: frame - delay,
    fps,
    config: { damping: 200, mass: 1, stiffness: 150 },
  });

  const scale = interpolate(entrance, [0, 1], [0.9, 1]);
  const opacity = interpolate(entrance, [0, 1], [0, 1]);

  return (
    <div
      style={{
        transform: `scale(${scale})`,
        opacity,
        width: "90%",
        maxWidth: 900,
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
        margin: "0 auto",
      }}
    >
      {/* Title bar */}
      <div
        style={{
          background: "#2d2d2d",
          padding: "10px 16px",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}
      >
        {/* Traffic lights */}
        <div style={{ display: "flex", gap: 6 }}>
          <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#ff5f57" }} />
          <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#febc2e" }} />
          <div style={{ width: 12, height: 12, borderRadius: "50%", background: "#28c840" }} />
        </div>
        {/* URL bar */}
        <div
          style={{
            flex: 1,
            background: "#1a1a1a",
            borderRadius: 6,
            padding: "4px 12px",
            fontSize: 13,
            color: "#999",
            fontFamily: "monospace",
            textAlign: "center",
          }}
        >
          {urlText}
        </div>
      </div>
      {/* Content area */}
      <div style={{ position: "relative", width: "100%", aspectRatio: "16/10", background: "#111" }}>
        {isVideo ? (
          <OffthreadVideo
            src={src}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        ) : (
          <Img
            src={src}
            style={{ width: "100%", height: "100%", objectFit: "cover" }}
          />
        )}
      </div>
    </div>
  );
};
