/**
 * Template 6: Narrated Video - voiceover-driven composition.
 *
 * Duration is set dynamically from the audio file via calculateMetadata().
 * Each segment maps to a Remotion Sequence wrapping the correct visual component.
 * Audio plays continuously while visuals appear in sync based on Whisper timestamps.
 */
import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import { resolveBrand, BrandContext } from "../styles/brand";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { SegmentRenderer } from "../components/SegmentRenderer";
import type { NarratedVideoProps } from "../types";

export const NarratedVideo: React.FC<NarratedVideoProps> = (props) => {
  const { audioUrl, segments, ctaText } = props;
  const resolvedBrand = resolveBrand(props.brand);
  const { fps, durationInFrames } = useVideoConfig();

  // Resolve audio: if it looks like a URL, use directly; otherwise staticFile()
  const resolvedAudio = audioUrl.startsWith("http")
    ? audioUrl
    : staticFile(audioUrl);

  // Show a BrandFooter CTA in the last 3 seconds if ctaText is provided
  // and no segment already covers the end
  const lastSeg = segments[segments.length - 1];
  const lastSegEndFrame = lastSeg ? Math.round(lastSeg.endSec * fps) : 0;
  const ctaDuration = 3 * fps; // 3 seconds
  const showCta = ctaText && durationInFrames - lastSegEndFrame > fps; // at least 1s gap

  return (
    <BrandContext.Provider value={resolvedBrand}>
    <AbsoluteFill>
      <BrandBackground variant="gradient" />

      {/* Continuous voiceover audio */}
      <Audio src={resolvedAudio} />

      {/* Render each segment as a timed Sequence */}
      {segments.map((seg, i) => {
        const startFrame = Math.round(seg.startSec * fps);
        const durationFrames = Math.max(
          1,
          Math.round((seg.endSec - seg.startSec) * fps)
        );

        return (
          <Sequence key={i} from={startFrame} durationInFrames={durationFrames}>
            <SegmentRenderer
              visualType={seg.visualType}
              visualProps={seg.visualProps}
            />
          </Sequence>
        );
      })}

      {/* CTA footer at the end */}
      {showCta && (
        <Sequence
          from={Math.max(lastSegEndFrame, durationInFrames - ctaDuration)}
          durationInFrames={ctaDuration}
        >
          <AbsoluteFill
            style={{
              display: "flex",
              alignItems: "flex-end",
              justifyContent: "center",
              paddingBottom: 80,
            }}
          >
            <BrandFooter ctaText={ctaText} />
          </AbsoluteFill>
        </Sequence>
      )}
    </AbsoluteFill>
    </BrandContext.Provider>
  );
};
