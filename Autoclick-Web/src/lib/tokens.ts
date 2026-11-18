// Breakpoint constants kept hand-synced with the @media values already used
// throughout globals.css (720px is the existing mobile/tablet boundary,
// 1000px the existing tablet/desktop boundary) so JS and CSS never drift.
export const breakpoints = { sm: 480, md: 640, lg: 720, xl: 1000 } as const;
