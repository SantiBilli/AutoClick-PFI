const dateFormatter = new Intl.DateTimeFormat("es-AR", { dateStyle: "medium" });
const numberFormatter = new Intl.NumberFormat("es-AR");
const currencyFormatter = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS", maximumFractionDigits: 0 });

export function formatDate(value: string | Date): string { return dateFormatter.format(new Date(value)); }
export function formatNumber(value: number): string { return numberFormatter.format(value); }
export function formatCurrency(value: number): string { return currencyFormatter.format(value); }
export function formatPercentage(value: number): string { return `${numberFormatter.format(value)}%`; }
