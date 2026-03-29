import React from "react";
import { AbsoluteFill } from "remotion";

interface Props {
  variant?: "dark" | "accent" | "gradient";
}

export const BrandBackground: React.FC<Props> = ({ variant = "gradient" }) => {
  const bg =
    variant === "dark"
      ? "#1a1a2e"
      : variant === "accent"
        ? "linear-gradient(135deg, #0f3460 0%, #1a8fd8 100%)"
        : "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)";

  return (
    <AbsoluteFill
      style={{
        background: bg,
      }}
    />
  );
};
