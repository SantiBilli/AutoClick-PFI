"use client";
import { useId, useState } from "react";
import { Search, SlidersHorizontal } from "lucide-react";
import { Select } from "./Select";

export interface FilterBarFilter {
  id: string;
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}

export function FilterBar({
  searchValue,
  onSearchChange,
  searchPlaceholder = "Buscar",
  filters = [],
  resultCount,
  resultLabel = "resultados",
}: {
  searchValue: string;
  onSearchChange: (value: string) => void;
  searchPlaceholder?: string;
  filters?: FilterBarFilter[];
  resultCount?: number;
  resultLabel?: string;
}) {
  const [panelOpen, setPanelOpen] = useState(false);
  const searchId = useId();

  return (
    <div className="portal-filterbar">
      <div className="portal-filterbar__row">
        <label className="search-field portal-filterbar__search" htmlFor={searchId}>
          <Search size={16} aria-hidden="true" />
          <input
            id={searchId}
            type="search"
            value={searchValue}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={searchPlaceholder}
          />
        </label>
        {filters.length > 0 && (
          <button
            className="ui-icon-button portal-filterbar__toggle"
            type="button"
            aria-expanded={panelOpen}
            aria-label="Mostrar filtros"
            onClick={() => setPanelOpen((value) => !value)}
          >
            <SlidersHorizontal size={18} aria-hidden="true" />
          </button>
        )}
        {typeof resultCount === "number" && (
          <span className="portal-filterbar__count">{resultCount} {resultLabel}</span>
        )}
      </div>
      {filters.length > 0 && (
        <div className={`portal-filterbar__panel ${panelOpen ? "portal-filterbar__panel--open" : ""}`.trim()}>
          {filters.map((filter) => (
            <label className="form-field portal-filterbar__filter" key={filter.id}>
              {filter.label}
              <Select value={filter.value} onChange={(event) => filter.onChange(event.target.value)} aria-label={filter.label}>
                {filter.options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </Select>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
