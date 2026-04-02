/**
 * ProductDemo - product showcase composition with screen recordings/screenshots.
 *
 * Renders a sequence of scenes: title, problem, demo, features, stats, cta.
 * Each scene has its own duration and content. Used for KMBoards, Shake, etc.
 */
import React from "react";
import {
  AbsoluteFill,
  Audio,
  Sequence,
  staticFile,
  useVideoConfig,
} from "remotion";
import { resolveBrand, BrandContext, useBrand } from "../styles/brand";
import type { ProductDemoProps } from "../types";
import { AnimatedText } from "../components/AnimatedText";
import { AccentLine } from "../components/AccentLine";
import { BrandBackground } from "../components/BrandBackground";
import { BrandFooter } from "../components/BrandFooter";
import { BrowserWindow } from "../components/BrowserWindow";
import { FeatureCard } from "../components/FeatureCard";
import { NumberCounter } from "../components/NumberCounter";

/** Title scene - product name + tagline on gradient */
const TitleScene: React.FC<{ productName: string; tagline: string }> = ({
  productName,
  tagline,
}) => {
  const brand = useBrand();
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 60,
      }}
    >
      <BrandBackground variant="gradient" />
      <div style={{ position: "relative", zIndex: 1, textAlign: "center" }}>
        <AnimatedText text={productName} fontSize={72} fontWeight={800} delay={10} />
        <div style={{ height: 20 }} />
        <AccentLine width={120} delay={20} />
        <div style={{ height: 24 }} />
        <AnimatedText text={tagline} fontSize={36} color={brand.textMuted} delay={25} />
      </div>
    </AbsoluteFill>
  );
};

/** Problem scene - pain point text overlay */
const ProblemScene: React.FC<{ text: string; subtext?: string }> = ({
  text,
  subtext,
}) => {
  const brand = useBrand();
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 60,
      }}
    >
      <BrandBackground variant="dark" />
      <div style={{ position: "relative", zIndex: 1, textAlign: "center", maxWidth: 800 }}>
        <AnimatedText text={text} fontSize={48} color={brand.error} delay={10} />
        {subtext && (
          <>
            <div style={{ height: 24 }} />
            <AnimatedText text={subtext} fontSize={30} color={brand.white} delay={25} />
          </>
        )}
      </div>
    </AbsoluteFill>
  );
};

/** Demo scene - browser window with screenshot or video */
const DemoScene: React.FC<{
  src: string;
  isVideo?: boolean;
  caption?: string;
  urlText?: string;
}> = ({ src, isVideo, caption, urlText }) => {
  const brand = useBrand();
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 40,
      }}
    >
      <BrandBackground variant="dark" />
      <div style={{ position: "relative", zIndex: 1, width: "100%", textAlign: "center" }}>
        <BrowserWindow src={src} isVideo={isVideo} urlText={urlText} delay={10} />
        {caption && (
          <div
            style={{
              marginTop: 20,
              fontSize: 24,
              color: brand.white,
              fontFamily: brand.bodyFont,
              opacity: 0.9,
            }}
          >
            {caption}
          </div>
        )}
      </div>
    </AbsoluteFill>
  );
};

/** Features scene - list of feature cards */
const FeaturesScene: React.FC<{ title?: string; features: string[] }> = ({
  title,
  features,
}) => {
  const brand = useBrand();
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        padding: 60,
      }}
    >
      <BrandBackground variant="gradient" />
      <div style={{ position: "relative", zIndex: 1 }}>
        {title && (
          <>
            <AnimatedText text={title} fontSize={44} delay={5} />
            <div style={{ height: 12 }} />
            <AccentLine width={80} delay={15} />
            <div style={{ height: 30 }} />
          </>
        )}
        {features.map((feat, i) => (
          <FeatureCard key={i} text={feat} index={i} delay={20} />
        ))}
      </div>
    </AbsoluteFill>
  );
};

/** Stats scene - big number + claim */
const StatsScene: React.FC<{
  statValue: number;
  statSuffix?: string;
  claimText: string;
}> = ({ statValue, statSuffix, claimText }) => {
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 60,
      }}
    >
      <BrandBackground variant="accent" />
      <div style={{ position: "relative", zIndex: 1, textAlign: "center" }}>
        <NumberCounter value={statValue} suffix={statSuffix || ""} fontSize={120} delay={10} />
        <div style={{ height: 20 }} />
        <AnimatedText text={claimText} fontSize={32} delay={30} />
      </div>
    </AbsoluteFill>
  );
};

/** CTA scene - call to action */
const CTAScene: React.FC<{ ctaText: string; productName: string }> = ({
  ctaText,
  productName,
}) => {
  const brand = useBrand();
  return (
    <AbsoluteFill
      style={{
        justifyContent: "center",
        alignItems: "center",
        padding: 60,
      }}
    >
      <BrandBackground variant="gradient" />
      <div style={{ position: "relative", zIndex: 1, textAlign: "center" }}>
        <AnimatedText text={`Try ${productName}`} fontSize={56} delay={10} />
        <div style={{ height: 20 }} />
        <AccentLine width={100} delay={20} />
        <BrandFooter ctaText={ctaText} delay={25} />
      </div>
    </AbsoluteFill>
  );
};

/** Main ProductDemo composition */
export const ProductDemo: React.FC<ProductDemoProps> = (props) => {
  const { fps } = useVideoConfig();
  const resolvedBrand = resolveBrand(props.brand);

  // Calculate frame offsets for each scene
  let frameOffset = 0;
  const sceneFrames: Array<{ from: number; durationInFrames: number }> = [];
  for (const scene of props.scenes) {
    const dur = Math.ceil(scene.durationSec * fps);
    sceneFrames.push({ from: frameOffset, durationInFrames: dur });
    frameOffset += dur;
  }

  const audioSrc = props.audioUrl
    ? props.audioUrl.startsWith("http")
      ? props.audioUrl
      : staticFile(props.audioUrl)
    : null;

  return (
    <BrandContext.Provider value={resolvedBrand}>
      <AbsoluteFill>
        {audioSrc && <Audio src={audioSrc} />}

        {props.scenes.map((scene, i) => {
          const { from, durationInFrames } = sceneFrames[i];
          const c = scene.content || {};

          return (
            <Sequence key={i} from={from} durationInFrames={durationInFrames}>
              {scene.type === "title" && (
                <TitleScene
                  productName={props.productName}
                  tagline={props.tagline}
                />
              )}
              {scene.type === "problem" && (
                <ProblemScene
                  text={(c.text as string) || "The Problem"}
                  subtext={c.subtext as string}
                />
              )}
              {scene.type === "demo" && (
                <DemoScene
                  src={
                    (c.src as string) ||
                    props.demoVideoUrl ||
                    (props.screenshotUrls?.[0] ?? "")
                  }
                  isVideo={c.isVideo as boolean}
                  caption={c.caption as string}
                  urlText={c.urlText as string}
                />
              )}
              {scene.type === "features" && (
                <FeaturesScene
                  title={c.title as string}
                  features={(c.features as string[]) || []}
                />
              )}
              {scene.type === "stats" && (
                <StatsScene
                  statValue={(c.statValue as number) || 0}
                  statSuffix={c.statSuffix as string}
                  claimText={(c.claimText as string) || ""}
                />
              )}
              {scene.type === "cta" && (
                <CTAScene ctaText={props.ctaText} productName={props.productName} />
              )}
            </Sequence>
          );
        })}
      </AbsoluteFill>
    </BrandContext.Provider>
  );
};
