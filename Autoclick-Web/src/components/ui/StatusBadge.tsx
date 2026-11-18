import { Badge } from "./Badge";

type Status = "activo" | "inactivo" | "pendiente" | "error" | "borrador";

const labels: Record<Status, string> = {
  activo: "Activo",
  inactivo: "Inactivo",
  pendiente: "Pendiente",
  error: "Error",
  borrador: "Borrador",
};

export function StatusBadge({ status }: { status: Status }) {
  const tone = status === "activo" ? "green" : status === "error" ? "red" : status === "pendiente" ? "amber" : "slate";
  return <Badge tone={tone}>{labels[status]}</Badge>;
}
