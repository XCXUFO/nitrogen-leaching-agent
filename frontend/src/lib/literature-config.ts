export function literaturePdfLimitMb() {
  const configured = Number(process.env.LITERATURE_MAX_PDF_MB ?? 100);
  return Number.isInteger(configured) && configured >= 1 && configured <= 500 ? configured : 100;
}
