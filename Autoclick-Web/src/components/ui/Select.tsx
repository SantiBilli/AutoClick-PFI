"use client";
import { Children, isValidElement, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { ChangeEvent, CSSProperties, ReactNode, SelectHTMLAttributes } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown, Search } from 'lucide-react';
import { useApiActivity } from '../../lib/api-activity';
import { Avatar } from './Avatar';
import type { User } from '../../lib/domain';
type Option = { value: string; label: string; disabled: boolean };
type Props = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'multiple' | 'size'> & { searchable?: boolean; people?: User[] };
function labelText(node: ReactNode): string { return Children.toArray(node).map(child => isValidElement<{ children?: ReactNode }>(child) ? labelText(child.props.children) : String(child)).join(''); }
function optionsFrom(children: ReactNode): Option[] {
  return Children.toArray(children).flatMap(child => {
    if (!isValidElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>(child)) return [];
    if (child.type !== 'option') return optionsFrom(child.props.children);
    const label = labelText(child.props.children);
    return [{ value: String(child.props.value ?? label), label, disabled: !!child.props.disabled }];
  });
}
/** Bounded, searchable select, rendered outside table overflow. */
export function Select({ children, className = '', searchable = false, people, value, defaultValue, onChange, disabled, name, required, id, ...props }: Props) {
  const generatedId = useId();
  const controlId = id ?? generatedId;
  const listId = `${controlId}-options`;
  const options = useMemo(() => optionsFrom(children), [children]);
  const peopleById = useMemo(() => new Map(people?.map(person => [person.id, person])), [people]);
  const [internal, setInternal] = useState(String(defaultValue ?? ''));
  const selected = String(value ?? internal);
  const current = options.find(option => option.value === selected) ?? options[0];
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState<CSSProperties>({ top: 0, left: 0, width: 240, maxHeight: 300 });
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const pending = useApiActivity().pending > 0;
  const blocked = disabled || pending;
  const filtered = options.filter(option => option.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const close = () => { setOpen(false); trigger.current?.focus({ preventScroll: true }); };
  function choose(option: Option) {
    if (blocked || option.disabled) return;
    setInternal(option.value);
    const target = { value: option.value, name: name ?? '', id: controlId };
    onChange?.({ target, currentTarget: target } as ChangeEvent<HTMLSelectElement>);
    close();
  }
  function show() {
    if (blocked) return;
    setQuery(''); setActive(Math.max(0, options.findIndex(option => option.value === current?.value))); setOpen(true);
  }
  useLayoutEffect(() => {
    if (!open || blocked) return;
    const update = () => {
      const rect = trigger.current?.getBoundingClientRect();
      const menu = popup.current;
      if (!rect || !menu) return;
      if (rect.bottom <= 0 || rect.top >= window.innerHeight) { setOpen(false); return; }
      const below = Math.max(0, window.innerHeight - rect.bottom - 18);
      const above = Math.max(0, rect.top - 18);
      const width = Math.min(Math.max(rect.width, 240), window.innerWidth - 24);
      const list = menu.querySelector<HTMLElement>('[role=listbox]');
      const searchHeight = menu.querySelector<HTMLElement>('.app-select-search')?.getBoundingClientRect().height ?? 0;
      const desiredHeight = Math.min(300, (list?.scrollHeight ?? 0) + searchHeight + (searchable ? 4 : 0) + 12);
      const upwards = below < desiredHeight && above > below;
      // Anchor the bottom edge when opening above. maxHeight is a limit, not
      // the actual menu height (four options take much less than 300px).
      const next = { top: upwards ? undefined : rect.bottom + 6, bottom: upwards ? window.innerHeight - rect.top + 6 : undefined,
        left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)), width, maxHeight: Math.min(300, upwards ? above : below) };
      setPosition(previous => Object.keys(next).every(key => previous[key as keyof CSSProperties] === next[key as keyof typeof next]) ? previous : next);
    };
    const observer = new ResizeObserver(update);
    if (popup.current) observer.observe(popup.current);
    if (trigger.current) observer.observe(trigger.current);
    update(); window.addEventListener('resize', update); window.addEventListener('scroll', update, true);
    return () => { observer.disconnect(); window.removeEventListener('resize', update); window.removeEventListener('scroll', update, true); };
  }, [open, blocked, query, options, searchable]);
  useLayoutEffect(() => {
    if (open) (search.current ?? popup.current?.querySelector<HTMLElement>('[role=listbox]'))?.focus({ preventScroll: true });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => { if (!popup.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', outside); document.addEventListener('focusin', outside);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('focusin', outside); };
  }, [open]);
  useEffect(() => {
    const list = popup.current?.querySelector<HTMLElement>('[role=listbox]');
    const item = list?.querySelector<HTMLElement>('[data-active="true"]');
    if (!list || !item) return;
    const row = item.getBoundingClientRect(); const viewport = list.getBoundingClientRect();
    // Scroll only the options, never the document behind the popup.
    if (row.top < viewport.top) list.scrollTop -= viewport.top - row.top;
    else if (row.bottom > viewport.bottom) list.scrollTop += row.bottom - viewport.bottom;
  }, [active, open]);
  function keyboard(event: React.KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key === 'Tab') { close(); }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      const direction = event.key === 'ArrowUp' ? -1 : 1;
      let next = event.key === 'Home' ? 0 : event.key === 'End' ? filtered.length - 1 : (active + direction + filtered.length) % filtered.length;
      for (let i = 0; i < filtered.length && filtered[next]?.disabled; i++) next = (next + direction + filtered.length) % filtered.length;
      setActive(next);
    }
    if (event.key === 'Enter' || (!searchable && event.key === ' ')) { event.preventDefault(); if (filtered[active]) choose(filtered[active]); }
    if (!searchable && event.key.length === 1 && event.key !== ' ') {
      const index = filtered.findIndex(option => !option.disabled && option.label.toLocaleLowerCase().startsWith(event.key.toLocaleLowerCase()));
      if (index >= 0) setActive(index);
    }
  }
  return <>
    <button ref={trigger} type="button" id={controlId} className={`ui-select app-select ${className}`} disabled={blocked}
      role="combobox" aria-haspopup="listbox" aria-expanded={open && !blocked} aria-controls={open ? listId : undefined}
      aria-label={props['aria-label']} aria-labelledby={props['aria-labelledby']} aria-describedby={props['aria-describedby']} aria-required={required}
      onClick={() => open ? close() : show()} onKeyDown={event => { if (['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); show(); } }}>
      <span>{current?.label ?? 'Seleccionar…'}</span><ChevronDown size={16} aria-hidden="true" />
    </button>
    {name && <input type="hidden" name={name} value={current?.value ?? ''} />}
    {open && !blocked && createPortal(<div ref={popup} data-select-popup className="app-select-popup" style={position} tabIndex={-1} onKeyDown={keyboard}>
      {searchable && <div className="app-select-search"><Search size={16} aria-hidden="true" /><input ref={search} autoComplete="off" placeholder="Buscar por nombre o correo…" aria-label="Buscar opciones" role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls={listId} aria-activedescendant={filtered[active] ? `${listId}-${active}` : undefined} value={query} onChange={event => { setQuery(event.target.value); setActive(0); }} /></div>}
      <div id={listId} className="app-select-options" role="listbox" tabIndex={searchable ? -1 : 0} aria-label={props['aria-label'] ?? 'Opciones'} aria-activedescendant={filtered[active] ? `${listId}-${active}` : undefined}>
        {filtered.map((option, index) => <div key={option.value} id={`${listId}-${index}`} role="option" aria-selected={option.value === current?.value} aria-disabled={option.disabled} data-active={index === active} className="app-select-option" onPointerMove={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(option)}>
          <span className="app-select-person">{peopleById.has(option.value) && <Avatar user={peopleById.get(option.value)} className="portal-avatar" />}<span>{option.label}</span></span>{option.value === current?.value && <Check size={15} aria-hidden="true" />}
        </div>)}
        {!filtered.length && <p className="app-select-empty">No se encontraron resultados.</p>}
      </div>
    </div>, document.body)}
  </>;
}
