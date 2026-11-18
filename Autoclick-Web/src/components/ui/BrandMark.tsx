import Image from "next/image";

export function BrandMark({
  inverse = false,
  showLabel = true,
  className = "",
}: {
  inverse?: boolean;
  showLabel?: boolean;
  className?: string;
}) {
  return (
    <span className={`brand-mark ${inverse ? "brand-mark--inverse" : ""} ${className}`.trim()}>
      <Image
        className="brand-mark__logo"
        src="/logo/autoclick-logo-dark.png"
        alt=""
        width={28}
        height={28}
        priority
      />
      {showLabel && "AutoClick"}
    </span>
  );
}
