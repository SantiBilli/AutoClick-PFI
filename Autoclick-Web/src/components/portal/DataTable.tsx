"use client";
import { motion } from "framer-motion";
import type { ReactNode } from "react";
import { revealGroup, revealViewport } from "../../lib/motion";

export interface DataTableColumn {
  key: string;
  header: string;
  className?: string;
}

export function DataTable({
  columns,
  children,
  stickyHeader = false,
  empty,
  isEmpty = false,
  className = "",
}: {
  columns: DataTableColumn[];
  children: ReactNode;
  stickyHeader?: boolean;
  /** Rendered inside the table when there is nothing to list. */
  empty?: ReactNode;
  isEmpty?: boolean;
  className?: string;
}) {
  return (
    <div className="table-wrap">
      <table className={`portal-table ${stickyHeader ? "portal-table--sticky" : ""} ${className}`.trim()}>
        <thead>
          <tr>{columns.map((column) => <th key={column.key} className={column.className}>{column.header}</th>)}</tr>
        </thead>
        <motion.tbody variants={revealGroup} initial="hidden" whileInView="visible" viewport={revealViewport}>
          {isEmpty ? (
            <tr className="portal-table__empty">
              <td colSpan={columns.length}>{empty ?? "No hay resultados para mostrar."}</td>
            </tr>
          ) : (
            children
          )}
        </motion.tbody>
      </table>
    </div>
  );
}
