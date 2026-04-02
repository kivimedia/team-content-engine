import React from "react";
import { Composition, staticFile } from "remotion";
import { getAudioDurationInSeconds } from "@remotion/media-utils";
import { BeforeAfter } from "./compositions/BeforeAfter";
import { HookReel } from "./compositions/HookReel";
import { NarratedVideo } from "./compositions/NarratedVideo";
import { PostTeaser } from "./compositions/PostTeaser";
import { ProductDemo } from "./compositions/ProductDemo";
import { StatReveal } from "./compositions/StatReveal";
import { StepFramework } from "./compositions/StepFramework";
import { BRAND, RESOLUTIONS } from "./styles/brand";
import type { NarratedVideoProps, ProductDemoProps } from "./types";

/* eslint-disable @typescript-eslint/no-explicit-any */
// Remotion 4.x Composition expects 2 type args (Schema, Props).
// We cast components to avoid adding Zod schemas for every composition.
const C = Composition as React.FC<any>;

export const Root: React.FC = () => {
  return (
    <>
      {/* ---- Hook Reel ---- */}
      <C
        id="HookReel"
        component={HookReel}
        durationInFrames={8 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        defaultProps={{
          thesis: "AI does not replace consultants. It replaces the ones who refuse to learn.",
          attribution: "Ziv Raviv",
          ctaText: "zivraviv.com",
        }}
      />
      <C
        id="HookReelSquare"
        component={HookReel}
        durationInFrames={8 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        defaultProps={{
          thesis: "AI does not replace consultants. It replaces the ones who refuse to learn.",
          attribution: "Ziv Raviv",
          ctaText: "zivraviv.com",
        }}
      />

      {/* ---- Stat Reveal ---- */}
      <C
        id="StatReveal"
        component={StatReveal}
        durationInFrames={10 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        defaultProps={{
          statValue: 73,
          statSuffix: "%",
          claimText: "of agencies still manage social media manually",
          sourceText: "Source: 2026 Agency Benchmark Report",
          ctaText: "zivraviv.com",
        }}
      />
      <C
        id="StatRevealSquare"
        component={StatReveal}
        durationInFrames={10 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        defaultProps={{
          statValue: 73,
          statSuffix: "%",
          claimText: "of agencies still manage social media manually",
          sourceText: "Source: 2026 Agency Benchmark Report",
          ctaText: "zivraviv.com",
        }}
      />

      {/* ---- Before/After ---- */}
      <C
        id="BeforeAfter"
        component={BeforeAfter}
        durationInFrames={12 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        defaultProps={{
          title: "The Shift",
          before: "I need to manually write 5 posts per week per client",
          after: "An AI engine delivers branded content I just approve",
          ctaText: "zivraviv.com",
        }}
      />
      <C
        id="BeforeAfterSquare"
        component={BeforeAfter}
        durationInFrames={12 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        defaultProps={{
          title: "The Shift",
          before: "I need to manually write 5 posts per week per client",
          after: "An AI engine delivers branded content I just approve",
          ctaText: "zivraviv.com",
        }}
      />
      <C
        id="BeforeAfterLandscape"
        component={BeforeAfter}
        durationInFrames={12 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.landscape.width}
        height={RESOLUTIONS.landscape.height}
        defaultProps={{
          title: "The Shift",
          before: "I need to manually write 5 posts per week per client",
          after: "An AI engine delivers branded content I just approve",
          ctaText: "zivraviv.com",
        }}
      />

      {/* ---- Step Framework ---- */}
      <C
        id="StepFramework"
        component={StepFramework}
        durationInFrames={20 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        defaultProps={{
          title: "The 3-Step Agency AI Playbook",
          steps: [
            { num: 1, text: "Feed the engine your best-performing posts" },
            { num: 2, text: "Let the AI learn your voice and audience" },
            { num: 3, text: "Review, approve, and post in minutes" },
          ],
          ctaText: "zivraviv.com",
          ctaKeyword: "PLAYBOOK",
        }}
      />
      <C
        id="StepFrameworkSquare"
        component={StepFramework}
        durationInFrames={20 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        defaultProps={{
          title: "The 3-Step Agency AI Playbook",
          steps: [
            { num: 1, text: "Feed the engine your best-performing posts" },
            { num: 2, text: "Let the AI learn your voice and audience" },
            { num: 3, text: "Review, approve, and post in minutes" },
          ],
          ctaText: "zivraviv.com",
          ctaKeyword: "PLAYBOOK",
        }}
      />

      {/* ---- Post Teaser ---- */}
      <C
        id="PostTeaser"
        component={PostTeaser}
        durationInFrames={10 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        defaultProps={{
          hookText: "Stop writing social posts from scratch. There is a better way.",
          platform: "linkedin",
          ctaKeyword: "GUIDE",
        }}
      />
      <C
        id="PostTeaserSquare"
        component={PostTeaser}
        durationInFrames={10 * BRAND.fps}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        defaultProps={{
          hookText: "Stop writing social posts from scratch. There is a better way.",
          platform: "linkedin",
          ctaKeyword: "GUIDE",
        }}
      />

      {/* ---- Narrated Video (dynamic duration from audio) ---- */}
      <C
        id="NarratedVideo"
        component={NarratedVideo}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        durationInFrames={30 * BRAND.fps}
        defaultProps={{
          audioUrl: "audio/sample.mp3",
          segments: [
            {
              narratorText: "Most agency owners are drowning in content creation",
              visualType: "animated_text",
              visualProps: { text: "Content Creation Crisis", fontSize: 44 },
              startSec: 0,
              endSec: 4,
            },
            {
              narratorText: "73 percent of agencies still manage social manually",
              visualType: "number_counter",
              visualProps: { value: 73, suffix: "%" },
              startSec: 4,
              endSec: 8,
            },
          ],
          ctaText: "zivraviv.com",
        }}
        calculateMetadata={async ({ props }: { props: NarratedVideoProps }) => {
          try {
            const src = props.audioUrl.startsWith("http") ? props.audioUrl : staticFile(props.audioUrl);
            const duration = await getAudioDurationInSeconds(src);
            return { durationInFrames: Math.ceil(duration * BRAND.fps) };
          } catch {
            const lastSeg = props.segments[props.segments.length - 1];
            const estDuration = lastSeg ? lastSeg.endSec + 2 : 30;
            return { durationInFrames: Math.ceil(estDuration * BRAND.fps) };
          }
        }}
      />
      <C
        id="NarratedVideoSquare"
        component={NarratedVideo}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        durationInFrames={30 * BRAND.fps}
        defaultProps={{
          audioUrl: "audio/sample.mp3",
          segments: [],
          ctaText: "zivraviv.com",
        }}
        calculateMetadata={async ({ props }: { props: NarratedVideoProps }) => {
          try {
            const src = props.audioUrl.startsWith("http") ? props.audioUrl : staticFile(props.audioUrl);
            const duration = await getAudioDurationInSeconds(src);
            return { durationInFrames: Math.ceil(duration * BRAND.fps) };
          } catch {
            const lastSeg = props.segments[props.segments.length - 1];
            const estDuration = lastSeg ? lastSeg.endSec + 2 : 30;
            return { durationInFrames: Math.ceil(estDuration * BRAND.fps) };
          }
        }}
      />
      <C
        id="NarratedVideoLandscape"
        component={NarratedVideo}
        fps={BRAND.fps}
        width={RESOLUTIONS.landscape.width}
        height={RESOLUTIONS.landscape.height}
        durationInFrames={30 * BRAND.fps}
        defaultProps={{
          audioUrl: "audio/sample.mp3",
          segments: [],
          ctaText: "zivraviv.com",
        }}
        calculateMetadata={async ({ props }: { props: NarratedVideoProps }) => {
          try {
            const src = props.audioUrl.startsWith("http") ? props.audioUrl : staticFile(props.audioUrl);
            const duration = await getAudioDurationInSeconds(src);
            return { durationInFrames: Math.ceil(duration * BRAND.fps) };
          } catch {
            const lastSeg = props.segments[props.segments.length - 1];
            const estDuration = lastSeg ? lastSeg.endSec + 2 : 30;
            return { durationInFrames: Math.ceil(estDuration * BRAND.fps) };
          }
        }}
      />

      {/* ---- Product Demo ---- */}
      <C
        id="ProductDemo"
        component={ProductDemo}
        fps={BRAND.fps}
        width={RESOLUTIONS.reel.width}
        height={RESOLUTIONS.reel.height}
        durationInFrames={30 * BRAND.fps}
        defaultProps={{
          productName: "KMBoards",
          tagline: "AI-powered content engine for agencies",
          scenes: [
            { type: "title", durationSec: 4, content: {} },
            { type: "problem", durationSec: 4, content: { text: "Agencies waste hours writing social posts from scratch" } },
            { type: "features", durationSec: 6, content: { title: "What You Get", features: ["AI-generated social posts", "Brand-consistent video content", "Weekly lead magnets"] } },
            { type: "cta", durationSec: 4, content: {} },
          ],
          ctaText: "kmboards.co",
        }}
        calculateMetadata={async ({ props }: { props: ProductDemoProps }) => {
          const totalSec = props.scenes.reduce((sum: number, s: { durationSec: number }) => sum + s.durationSec, 0);
          return { durationInFrames: Math.ceil(totalSec * BRAND.fps) };
        }}
      />
      <C
        id="ProductDemoSquare"
        component={ProductDemo}
        fps={BRAND.fps}
        width={RESOLUTIONS.square.width}
        height={RESOLUTIONS.square.height}
        durationInFrames={30 * BRAND.fps}
        defaultProps={{
          productName: "KMBoards",
          tagline: "AI-powered content engine for agencies",
          scenes: [
            { type: "title", durationSec: 4, content: {} },
            { type: "features", durationSec: 6, content: { title: "Key Features", features: ["AI content generation", "Brand-consistent videos"] } },
            { type: "cta", durationSec: 4, content: {} },
          ],
          ctaText: "kmboards.co",
        }}
        calculateMetadata={async ({ props }: { props: ProductDemoProps }) => {
          const totalSec = props.scenes.reduce((sum: number, s: { durationSec: number }) => sum + s.durationSec, 0);
          return { durationInFrames: Math.ceil(totalSec * BRAND.fps) };
        }}
      />
      <C
        id="ProductDemoLandscape"
        component={ProductDemo}
        fps={BRAND.fps}
        width={RESOLUTIONS.landscape.width}
        height={RESOLUTIONS.landscape.height}
        durationInFrames={30 * BRAND.fps}
        defaultProps={{
          productName: "KMBoards",
          tagline: "AI-powered content engine for agencies",
          scenes: [
            { type: "title", durationSec: 4, content: {} },
            { type: "demo", durationSec: 8, content: { src: "", urlText: "kmboards.co" } },
            { type: "cta", durationSec: 4, content: {} },
          ],
          ctaText: "kmboards.co",
        }}
        calculateMetadata={async ({ props }: { props: ProductDemoProps }) => {
          const totalSec = props.scenes.reduce((sum: number, s: { durationSec: number }) => sum + s.durationSec, 0);
          return { durationInFrames: Math.ceil(totalSec * BRAND.fps) };
        }}
      />
    </>
  );
};
