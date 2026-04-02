import React from "react";
import { AbsoluteFill } from "remotion";
import { useBrand } from "../styles/brand";

interface Props {
  variant?: "dark" | "accent" | "gradient";
}

export const BrandBackground: React.FC<Props> = ({ variant = "gradient" }) => {
  const brand = useBrand();

  const bg =
    variant === "dark"
      ? brand.dark
      : variant === "accent"
        ? brand.gradientAccent
        : brand.gradientDark;

  return (
    <AbsoluteFill
      style={{
        background: bg,
      }}
    />
  );
};
