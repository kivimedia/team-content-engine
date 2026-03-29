/**
 * SegmentRenderer - dispatches a visual type string to the correct component.
 * Used by NarratedVideo to render each segment's visuals.
 */
import React from "react";
import { AbsoluteFill, staticFile } from "remotion";
import { AnimatedText } from "./AnimatedText";
import { BrandFooter } from "./BrandFooter";
import { CrossedText } from "./CrossedText";
import { ImageOverlay } from "./ImageOverlay";
import { NumberCounter } from "./NumberCounter";
import { RevealText } from "./RevealText";
import { StepCard } from "./StepCard";
import { TypingText } from "./TypingText";
import type { NarrationVisualType } from "../types";

interface Props {
  visualType: NarrationVisualType;
  visualProps: Record<string, unknown>;
}

export const SegmentRenderer: React.FC<Props> = ({ visualType, visualProps }) => {
  const p = visualProps; // shorthand

  const content = (() => {
    switch (visualType) {
      case "animated_text":
        return (
          <AnimatedText
            text={(p.text as string) || ""}
            fontSize={(p.fontSize as number) || 44}
            fontWeight={(p.fontWeight as number) || 700}
            color={p.color as string | undefined}
            wordByWord={(p.wordByWord as boolean) || false}
            delay={(p.delay as number) || 0}
            style={p.style as React.CSSProperties | undefined}
          />
        );

      case "number_counter":
        return (
          <NumberCounter
            value={(p.value as number) || 0}
            suffix={(p.suffix as string) || ""}
            fontSize={(p.fontSize as number) || 120}
            color={p.color as string | undefined}
            delay={(p.delay as number) || 0}
            countFrames={(p.countFrames as number) || undefined}
          />
        );

      case "crossed_text":
        return (
          <CrossedText
            text={(p.text as string) || ""}
            fontSize={(p.fontSize as number) || 42}
            delay={(p.delay as number) || 0}
          />
        );

      case "reveal_text":
        return (
          <RevealText
            text={(p.text as string) || ""}
            fontSize={(p.fontSize as number) || 46}
            delay={(p.delay as number) || 0}
          />
        );

      case "step_card":
        return (
          <StepCard
            num={(p.num as number) || 1}
            text={(p.text as string) || ""}
            delay={(p.delay as number) || 0}
            isLast={(p.isLast as boolean) || false}
          />
        );

      case "brand_footer":
        return (
          <BrandFooter
            ctaText={(p.ctaText as string) || "zivraviv.com"}
            delay={(p.delay as number) || 0}
          />
        );

      case "image_overlay": {
        // Resolve src: staticFile for local paths, raw for URLs
        const rawSrc = (p.src as string) || "";
        const src = rawSrc.startsWith("http") ? rawSrc : staticFile(rawSrc);
        return (
          <ImageOverlay
            src={src}
            caption={p.caption as string | undefined}
            zoomIntensity={(p.zoomIntensity as number) || undefined}
          />
        );
      }

      case "typing_text":
        return (
          <TypingText
            text={(p.text as string) || ""}
            fontSize={(p.fontSize as number) || 36}
            delay={(p.delay as number) || 0}
            charsPerFrame={(p.charsPerFrame as number) || undefined}
          />
        );

      default:
        // Fallback: show the visual type name so it's visible during dev
        return (
          <div style={{ color: "#ff6b6b", fontSize: 24, textAlign: "center" }}>
            Unknown visual: {visualType}
          </div>
        );
    }
  })();

  // Use less padding for image_overlay so images fill more space
  const isImage = visualType === "image_overlay";

  return (
    <AbsoluteFill
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: isImage ? "20px" : "60px 50px",
      }}
    >
      {content}
    </AbsoluteFill>
  );
};
