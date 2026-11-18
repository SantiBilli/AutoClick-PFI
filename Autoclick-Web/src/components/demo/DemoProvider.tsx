"use client";

import type { ReactNode } from "react";
import { CloudGate } from "../../lib/cloud-store";
import { DemoStoreProvider } from "../../lib/demo-store";
import { ApiFeedback } from "../ui/ApiFeedback";

export function DemoProvider({ children }: { children: ReactNode }) {
  return <ApiFeedback><DemoStoreProvider><CloudGate>{children}</CloudGate></DemoStoreProvider></ApiFeedback>;
}
