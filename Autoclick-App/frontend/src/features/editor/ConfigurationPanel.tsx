import { ChevronDown, Crosshair, FolderOpen, Info, LockKeyhole, Trash2, Variable } from 'lucide-react';
import { desktopBridge } from '@/app/DesktopBridge';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { actionsById, type ActionField } from '@/bot/registry';
import { isPendingParameter } from '@/bot/pending';
import type { BotEditorNode } from '@/bot/model';
import type { ValidationIssue } from '@/bot/validation';
import { Button } from '@/components/Button';
import { CONDITION_OPERATORS, conditionSchema, type Condition, type ConditionClause } from '@/bot/conditions';
import { formatKeybind, normalizeKeyboardEvent } from '@/features/editor/keyboardKeybind';

type Props = {
  node: BotEditorNode | null;
  issues: ValidationIssue[];
  onChange: (fieldName: string, value: unknown) => void;
  onDelete?: () => void;
  onCaptureCoordinates?: (nodeId: string) => void;
  captureActive?: boolean;
  captureButtonRef?: RefObject<HTMLButtonElement | null>;
  captureDisabled?: boolean;
  captureFeedback?: { kind: 'status' | 'error'; message: string } | null;
  captureNodeId?: string | null;
  disabled?: boolean;
  goToTargets?: Array<{ id: string; label: string }>;
  hideHeader?: boolean;
};

const MOUSE_COORDINATE_ACTIONS = new Set(['mouse.move', 'mouse.click', 'mouse.rightClick', 'mouse.doubleClick']);
const UNARY_OPERATORS = new Set(['empty', 'notEmpty']);
const OPERATOR_LABELS = {
  eq: 'Es igual a', ne: 'No es igual a', lt: 'Es menor que', lte: 'Es menor o igual que',
  gt: 'Es mayor que', gte: 'Es mayor o igual que', contains: 'Contiene', startsWith: 'Comienza con',
  endsWith: 'Termina con', in: 'Está en', empty: 'Está vacío', notEmpty: 'No está vacío',
} as const;

function operandText(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value ?? null);
}

function OperandControl({ label, value, disabled, onChange }: { label: string; value: unknown; disabled: boolean; onChange: (value: ConditionClause['left']) => void }) {
  const [type, setType] = useState<'text' | 'json'>(typeof value === 'string' ? 'text' : 'json');
  const [draft, setDraft] = useState(() => operandText(value));

  useEffect(() => {
    setDraft(operandText(value));
  }, [value]);

  return <label className="text-[11px] font-bold">{label}
    <span className="mt-1 flex gap-1">
      <select aria-label={`${label}: tipo`} className="field-control h-9 rounded-control bg-white px-1" disabled={disabled} onChange={(event) => {
        const nextType = event.target.value as 'text' | 'json';
        setType(nextType);
        if (nextType === 'text') {
          const text = operandText(value);
          setDraft(text);
          onChange(text);
        } else {
          setDraft(JSON.stringify(value ?? null));
        }
      }} value={type}>
        <option value="text">Texto</option><option value="json">JSON</option>
      </select>
      <input aria-label={label} className="field-control h-9 min-w-0 flex-1 rounded-control px-2" disabled={disabled} onChange={(event) => {
        const nextDraft = event.target.value;
        setDraft(nextDraft);
        if (type === 'text') {
          onChange(nextDraft);
          return;
        }
        try {
          onChange(JSON.parse(nextDraft));
        } catch {
          // Keep incomplete JSON locally so typing does not switch the control to text mode.
        }
      }} value={draft} />
    </span>
  </label>;
}

function ConditionControl({ id, value, invalid, disabled, onChange }: { id: string; value: unknown; invalid: boolean; disabled: boolean; onChange: (value: Condition) => void }) {
  const parsed = conditionSchema.safeParse(value);
  const condition: Condition = parsed.success ? parsed.data : { combinator: 'all', clauses: [{ left: '', operator: 'eq', right: '' }] };
  function updateClause(index: number, update: Partial<ConditionClause>) {
    onChange({ ...condition, clauses: condition.clauses.map((clause, clauseIndex) => {
      if (clauseIndex !== index) return clause;
      const next = { ...clause, ...update };
      if (UNARY_OPERATORS.has(next.operator)) delete next.right;
      return next;
    }) });
  }
  return <fieldset aria-invalid={invalid} className="rounded-control border border-border bg-bg/55 p-3 @sm:col-span-2 @xl:col-span-3" id={id} tabIndex={-1}>
    <legend className="px-1 text-[11px] font-extrabold tracking-[0.04em] uppercase text-text-muted">Condición</legend>
    <label className="mb-3 block text-[11px] font-bold">
      Combinar cláusulas
      <select aria-label="Combinar cláusulas" className="field-control ml-2 h-8 rounded-control bg-white px-2" disabled={disabled} onChange={(event) => onChange({ ...condition, combinator: event.target.value as 'all' | 'any' })} value={condition.combinator}>
        <option value="all">Todas</option><option value="any">Cualquiera</option>
      </select>
    </label>
    <div className="grid gap-2">
      {condition.clauses.map((clause, index) => <div className="grid gap-2 rounded-control border border-border bg-white p-2 @sm:grid-cols-[1fr_1fr_1fr_auto]" key={index}>
        <OperandControl disabled={disabled} label={`Cláusula ${index + 1}: operando izquierdo`} onChange={(left) => updateClause(index, { left })} value={clause.left} />
        <label className="text-[11px] font-bold">Operador<select aria-label={`Cláusula ${index + 1}: operador`} className="field-control mt-1 h-9 w-full rounded-control bg-white px-2" disabled={disabled} onChange={(event) => {
          const operator = event.target.value as ConditionClause['operator'];
          updateClause(index, { operator, ...(UNARY_OPERATORS.has(operator) ? {} : { right: clause.right ?? '' }) });
        }} value={clause.operator}>{CONDITION_OPERATORS.map((operator) => <option key={operator} value={operator}>{OPERATOR_LABELS[operator]}</option>)}</select></label>
        {!UNARY_OPERATORS.has(clause.operator) ? <OperandControl disabled={disabled} label={`Cláusula ${index + 1}: operando derecho`} onChange={(right) => updateClause(index, { right })} value={clause.right} /> : <span />}
        <Button aria-label={`Eliminar cláusula ${index + 1}`} className="self-end" disabled={disabled || condition.clauses.length === 1} onClick={() => onChange({ ...condition, clauses: condition.clauses.filter((_, clauseIndex) => clauseIndex !== index) })} type="button" variant="secondary">Eliminar</Button>
      </div>)}
    </div>
    <Button className="mt-2" disabled={disabled} onClick={() => onChange({ ...condition, clauses: [...condition.clauses, { left: '', operator: 'eq', right: '' }] })} type="button" variant="secondary">Agregar cláusula</Button>
  </fieldset>;
}

function KeybindControl({ id, value, invalid, disabled, onChange }: { id: string; value: unknown; invalid: boolean; disabled: boolean; onChange: (value: string) => void }) {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState('');
  const recorderRef = useRef<HTMLDivElement>(null);
  const keybind = typeof value === 'string' ? value : '';

  useEffect(() => {
    if (listening) recorderRef.current?.focus();
  }, [listening]);

  useEffect(() => {
    if (disabled) {
      setListening(false);
      setError('');
    }
  }, [disabled]);

  return (
    <div
      aria-disabled={disabled}
      aria-invalid={invalid}
      aria-label="Combinacion de teclas"
      className={`rounded-control border bg-white p-2.5 outline-none transition-[border-color,box-shadow] duration-150 ease-out focus:shadow-focus ${
        invalid ? 'border-danger' : 'border-border focus:border-primary'
      }`}
      id={id}
      onKeyDown={(event) => {
        if (event.target !== event.currentTarget || !listening || disabled) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.repeat) return;

        const normalized = normalizeKeyboardEvent(event);
        if (!normalized) {
          if (!['Alt', 'AltGraph', 'Control', 'Meta', 'OS', 'Shift'].includes(event.key)) {
            setError('Tecla no compatible. Intenta con otra tecla.');
          }
          return;
        }

        setError('');
        setListening(false);
        onChange(normalized);
      }}
      ref={recorderRef}
      role="group"
      tabIndex={listening ? 0 : -1}>
      <div className="flex min-h-9 items-center justify-between gap-3">
        <span
          className={`font-mono font-bold ${
            keybind
              ? 'inline-flex items-center rounded-md border border-slate-200 bg-slate-100 px-2.5 py-1 text-[13px] text-text shadow-xs'
              : 'text-[12px] text-text-muted'
          }`}>
          {keybind ? formatKeybind(keybind) : 'Sin configurar'}
        </span>
        <div className="flex shrink-0 items-center gap-2">
          {listening ? (
            <Button
              className="h-8 px-3 text-[12px]"
              disabled={disabled}
              onClick={() => {
                setListening(false);
                setError('');
              }}
              type="button"
              variant="secondary">
              Cancelar
            </Button>
          ) : (
            <Button
              className="h-8 px-3 text-[12px]"
              disabled={disabled}
              onClick={() => {
                setError('');
                setListening(true);
              }}
              type="button"
              variant="secondary">
              Registrar tecla
            </Button>
          )}
          {keybind ? (
            <Button
              className="h-8 px-3 text-[12px] text-danger hover:border-red-200 hover:bg-red-50"
              disabled={disabled}
              onClick={() => onChange('')}
              type="button"
              variant="secondary">
              Borrar
            </Button>
          ) : null}
        </div>
      </div>
      {error || listening ? (
        <p
          aria-live="polite"
          className={`mt-1.5 mb-0 text-[11px] font-semibold ${error ? 'text-danger' : 'text-text-muted'}`}
          role={error ? 'alert' : 'status'}>
          {error || (listening ? 'Presiona una tecla o combinacion...' : '')}
        </p>
      ) : null}
    </div>
  );
}

function FieldControl({
  field,
  nodeType,
  value,
  invalid,
  disabled,
  onChange,
}: {
  field: ActionField;
  nodeType?: string;
  value: unknown;
  invalid: boolean;
  disabled: boolean;
  onChange: (value: unknown) => void;
}) {
  const id = `field-${field.name}`;
  if (isPendingParameter(value)) value = undefined;
  const className = 'field-control h-9 w-full rounded-control bg-white px-3 transition-[border-color,box-shadow] duration-150 ease-out';
  if (field.type === 'condition') {
    return <ConditionControl disabled={disabled} id={id} invalid={invalid} onChange={onChange} value={value} />;
  }
  if (field.type === 'key') {
    return <KeybindControl disabled={disabled} id={id} invalid={invalid} onChange={onChange} value={value} />;
  }
  if (field.type === 'boolean') {
    return (
      <input
        aria-invalid={invalid}
        checked={value === true}
        className="size-4 accent-primary"
        disabled={disabled}
        id={id}
        onChange={(event) => onChange(event.target.checked)}
        type="checkbox"
      />
    );
  }
  if (field.type === 'select') {
    return (
      <select
        aria-invalid={invalid}
        className={className}
        disabled={disabled}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={typeof value === 'string' ? value : ''}>
        {!field.required ? <option value="">Sin definir</option> : null}
        {field.options?.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }
  if (field.type === 'multiline' || field.type === 'json') {
    return (
      <textarea
        aria-invalid={invalid}
        className={`${className} min-h-20 resize-y py-2`}
        disabled={disabled}
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={field.type === 'json' && typeof value !== 'string' ? JSON.stringify(value, null, 2) : typeof value === 'string' ? value : ''}
      />
    );
  }
  if (field.type === 'file') {
    const isFolder = Boolean(nodeType?.startsWith('folder.'));
    const isSave = Boolean(field.name === 'destination' || (nodeType === 'excel.save' && field.name === 'path'));
    const dialogType = isFolder ? 'folder' : isSave ? 'save' : 'file';
    const labelType = isFolder ? 'carpeta' : 'archivo';

    return (
      <div className="relative flex items-center">
        <input
          aria-label={field.label}
          aria-invalid={invalid}
          className={`${className} pr-9`}
          disabled={disabled}
          id={id}
          onChange={(event) => onChange(event.target.value)}
          placeholder={field.required ? `Seleccionar ${labelType}...` : `Opcional (ruta de ${labelType})...`}
          type="text"
          value={typeof value === 'string' ? value : ''}
        />
        <button
          type="button"
          aria-label={`Explorar ${labelType}`}
          title={`Explorar ${labelType}`}
          disabled={disabled}
          onClick={async () => {
            const res = await desktopBridge.pickFilePath(dialogType);
            if (res.ok && res.data) {
              onChange(res.data);
            }
          }}
          className="absolute right-1.5 flex size-6 items-center justify-center rounded text-text-muted hover:bg-slate-100 hover:text-text focus:outline-none disabled:opacity-50 transition-colors"
        >
          <FolderOpen className="size-4" />
        </button>
      </div>
    );
  }
  if (field.type === 'integer' || field.type === 'number') {
    const isVariable = typeof value === 'string' && (value.includes('{{') || value.startsWith('{') || isNaN(Number(value)));

    return (
      <div className="relative flex items-center">
        <input
          aria-label={field.label}
          aria-invalid={invalid}
          className={`${className} pr-8`}
          disabled={disabled}
          id={id}
          max={isVariable ? undefined : field.max}
          min={isVariable ? undefined : field.min}
          onChange={(event) => onChange(event.target.value)}
          placeholder={
            isVariable
              ? '{{variable}}'
              : field.required
              ? 'Ej: 100 o {{variable}}'
              : 'Opcional (ej: 100 o {{variable}})...'
          }
          type={isVariable ? 'text' : 'number'}
          value={typeof value === 'string' || typeof value === 'number' ? value : ''}
        />
        <button
          type="button"
          aria-label={isVariable ? 'Cambiar a valor numérico' : 'Usar variable'}
          title={isVariable ? 'Cambiar a valor numérico fijo' : 'Insertar o usar variable (ej: {{variable}})'}
          disabled={disabled}
          onClick={() => {
            if (isVariable) {
              onChange('');
            } else {
              onChange('{{}}');
            }
          }}
          className={`absolute right-1 flex size-6 items-center justify-center rounded text-[11px] font-bold focus:outline-none disabled:opacity-50 transition-colors ${
            isVariable
              ? 'bg-primary/10 text-primary hover:bg-primary/20'
              : 'text-text-muted hover:bg-slate-100 hover:text-text'
          }`}
        >
          <Variable className="size-3.5" />
        </button>
      </div>
    );
  }
  return (
    <input
      aria-label={field.label}
      aria-invalid={invalid}
      className={className}
      disabled={disabled}
      id={id}
      max={field.max}
      min={field.min}
      onChange={(event) => onChange(event.target.value)}
      type="text"
      value={typeof value === 'string' || typeof value === 'number' ? value : ''}
    />
  );
}

export function ConfigurationPanel({
  node,
  issues,
  captureActive = false,
  captureButtonRef,
  captureDisabled = false,
  captureFeedback = null,
  captureNodeId = null,
  disabled = false,
  onCaptureCoordinates,
  onChange,
  onDelete,
  goToTargets = [],
  hideHeader = false,
}: Props) {
  if (!node) {
    return (
      <section
        aria-label="Configuración del bloque"
        className="grid min-h-28 place-items-center border-t border-border bg-surface px-5 py-4 text-center text-[13px] text-text-muted">
        Seleccioná un bloque para configurar sus parámetros.
      </section>
    );
  }
  const action = actionsById.get(node.data.actionType);
  if (!action) {
    return (
      <section
        aria-label="Configuración del bloque"
        className={`bg-surface p-4 ${hideHeader ? '' : 'border-t border-border'}`}>
        <div className="flex items-center gap-2 font-extrabold">
          <LockKeyhole aria-hidden="true" size={17} /> Tipo no compatible
        </div>
        <p className="mt-1 mb-3 text-[12px] text-text-muted">
          {node.data.actionType} · {node.id}
        </p>
        <pre className="m-0 max-h-36 overflow-auto rounded-control bg-sidebar p-3 font-mono text-[11px] text-slate-200">
          {JSON.stringify(node.data.params, null, 2)}
        </pre>
      </section>
    );
  }

  const isVisionDetect = action.id === 'vision.detectElement';
  const visionScope = String(node.data.params.scope ?? 'pantalla');
  const visibleFields = action.fields.filter((field) => {
    if (isVisionDetect && visionScope !== 'region') {
      if (['x', 'y', 'width', 'height'].includes(field.name)) return false;
    }
    return true;
  });
  const usesCoordinateGrouping = MOUSE_COORDINATE_ACTIONS.has(action.id);
  const coordinateFields = visibleFields.filter((field) => field.name === 'x' || field.name === 'y');
  const regularFields = visibleFields.filter((field) => !usesCoordinateGrouping || (field.name !== 'x' && field.name !== 'y'));
  const selectingThisNode = captureActive && captureNodeId === node.id;
  const publishChange = (fieldName: string, value: unknown) => {
    if (!disabled) onChange(fieldName, value);
  };
  const renderField = (field: ActionField) => {
    const fieldIssues = issues.filter(
      (issue) => issue.nodeId === node.id && issue.fieldName === field.name
    );
    const isSingleField = regularFields.length === 1;
    const colSpanClass = isSingleField
      ? '@sm:col-span-2 @xl:col-span-3'
      : field.type === 'multiline' || field.type === 'json' || field.type === 'key'
      ? '@sm:col-span-2 @xl:col-span-3'
      : '';

    if (field.type === 'condition') {
      return <div className="@sm:col-span-2 @xl:col-span-3" key={`${node.id}-${field.name}`}>
        <ConditionControl disabled={disabled} id={`field-${field.name}`} invalid={fieldIssues.length > 0} onChange={(value) => publishChange(field.name, value)} value={isPendingParameter(node.data.params[field.name]) ? undefined : node.data.params[field.name]} />
        {fieldIssues.map((issue) => <span className="mt-1 block text-[11px] text-danger" key={issue.code}>{issue.message}</span>)}
      </div>;
    }
    if (node.data.actionType === 'flow.goTo' && field.name === 'targetNodeId') {
      return <label className={colSpanClass} key={field.name}>
        <span className="mb-1.5 flex items-center justify-between gap-2 text-[11px] font-extrabold tracking-[0.04em] uppercase">{field.label}<span className="font-semibold tracking-normal text-text-muted normal-case">Obligatorio</span></span>
        <select aria-label={field.label} aria-invalid={fieldIssues.length > 0} className="field-control h-9 w-full rounded-control bg-white px-3" disabled={disabled} id={`field-${field.name}`} onChange={(event) => publishChange(field.name, event.target.value)} value={String(node.data.params[field.name] ?? '')}>
          <option value="">Seleccioná un bloque</option>
          {goToTargets.map((target) => <option key={target.id} value={target.id}>{target.label}</option>)}
        </select>
        {fieldIssues.map((issue) => <span className="mt-1 block text-[11px] text-danger" key={issue.code}>{issue.message}</span>)}
      </label>;
    }
    if (field.type === 'key') {
      return <div className={colSpanClass || '@sm:col-span-2 @xl:col-span-3'} key={`${node.id}-${field.name}`}>
        <span className="mb-1.5 flex items-center justify-between gap-2 text-[11px] font-extrabold tracking-[0.04em] uppercase">
          {field.label}
          <span className="font-semibold tracking-normal text-text-muted normal-case">
            {field.required ? 'Obligatorio' : 'Opcional'}
          </span>
        </span>
        <FieldControl
          disabled={disabled}
          field={field}
          nodeType={node.data.actionType}
          invalid={fieldIssues.length > 0}
          onChange={(value) => publishChange(field.name, value)}
          value={node.data.params[field.name]}
        />
        {fieldIssues.map((issue) => <span className="mt-1 block text-[11px] text-danger" key={issue.code}>{issue.message}</span>)}
      </div>;
    }
    return (
      <label className={colSpanClass} key={field.name}>
        <span className="mb-1.5 flex items-center justify-between gap-2 text-[11px] font-extrabold tracking-[0.04em] uppercase">
          {field.label}
          <span className="font-semibold tracking-normal text-text-muted normal-case">
            {field.required ? 'Obligatorio' : 'Opcional'}
          </span>
        </span>
        <FieldControl
          disabled={disabled}
          field={field}
          nodeType={node.data.actionType}
          invalid={fieldIssues.length > 0}
          onChange={(value) => publishChange(field.name, value)}
          value={node.data.params[field.name]}
        />
        {fieldIssues.map((issue) => (
          <span className="mt-1 block text-[11px] text-danger" key={issue.code}>
            {issue.message}
          </span>
        ))}
      </label>
    );
  };

  const coordinateGroup = usesCoordinateGrouping ? (
    <fieldset className="rounded-control border border-border bg-bg/55 p-3 @sm:col-span-2">
      <legend className="px-1 text-[11px] font-extrabold tracking-[0.04em] uppercase text-text-muted">
        Coordenadas
      </legend>
      <div className="grid grid-cols-2 gap-3">
        {coordinateFields.map((coordinateField) => {
          const fieldIssues = issues.filter(
            (issue) => issue.nodeId === node.id && issue.fieldName === coordinateField.name
          );
          return (
            <label key={coordinateField.name}>
              <span className="mb-1.5 flex items-center justify-between gap-2 text-[11px] font-extrabold tracking-[0.04em] uppercase">
                {coordinateField.label}
                <span className="font-semibold tracking-normal text-text-muted normal-case">
                  {coordinateField.required ? 'Obligatorio' : 'Opcional'}
                </span>
              </span>
              <FieldControl
                disabled={disabled}
                field={coordinateField}
                invalid={fieldIssues.length > 0}
                onChange={(value) => publishChange(coordinateField.name, value)}
                value={node.data.params[coordinateField.name]}
              />
              {fieldIssues.map((issue) => (
                <span className="mt-1 block text-[11px] text-danger" key={issue.code}>{issue.message}</span>
              ))}
            </label>
          );
        })}
      </div>
      {onCaptureCoordinates ? <>
        <Button
          aria-busy={selectingThisNode}
          className="mt-3 h-8 px-3 text-[12px]"
          disabled={disabled || captureDisabled}
          onClick={() => {
            if (!disabled) onCaptureCoordinates(node.id);
          }}
          ref={captureButtonRef}
          type="button"
          variant="secondary">
          <Crosshair aria-hidden="true" size={14} />
          {selectingThisNode ? 'Seleccionando...' : 'Seleccionar en pantalla'}
        </Button>
        {captureFeedback ? (
          <p
            className={`mt-2 mb-0 text-[11px] ${captureFeedback.kind === 'error' ? 'text-danger' : 'text-text-muted'}`}
            role={captureFeedback.kind === 'error' ? 'alert' : 'status'}>
            {captureFeedback.message}
          </p>
        ) : null}
      </> : null}
    </fieldset>
  ) : null;

  return (
    <section
      aria-label="Configuración del bloque"
      className={`@container bg-gradient-to-b from-white to-blue-50/25 p-4 ${hideHeader ? '' : 'border-t border-border'}`}>
      {hideHeader ? null : (
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="m-0 text-sm font-extrabold">{action.title}</h2>
            <p className="mt-1 mb-0 font-mono text-[10px] text-text-muted">{node.id}</p>
          </div>
          {onDelete ? (
            <Button aria-keyshortcuts="Delete" className="h-9 text-danger" disabled={disabled} onClick={() => {
              if (!disabled) onDelete();
            }} variant="secondary">
              <Trash2 aria-hidden="true" size={15} />
              Eliminar bloque
            </Button>
          ) : null}
        </div>
      )}
      {isVisionDetect ? (
        <details className="group mb-4 rounded-control border border-border bg-bg/60 text-[12px] text-text-muted transition-colors open:bg-bg/80">
          <summary className="flex cursor-pointer list-none items-center justify-between p-3 font-semibold text-text select-none hover:text-primary focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary rounded-control">
            <div className="flex items-center gap-2">
              <Info aria-hidden="true" className="size-4 shrink-0 text-primary" />
              <span>Ver variables generadas por Visión</span>
            </div>
            <ChevronDown aria-hidden="true" className="size-4 shrink-0 text-text-muted transition-transform duration-200 group-open:rotate-180 group-hover:text-primary" />
          </summary>
          <div className="border-t border-border/60 p-3 pt-2.5">
            <p className="mb-2.5 leading-relaxed">
              Este bloque busca texto en pantalla mediante OCR y genera las siguientes variables usando el nombre base configurado en <strong className="text-text">{String(node.data.params.outputVariable || 'variable')}</strong> (sin mover el cursor):
            </p>
            <div className="grid gap-2 @sm:grid-cols-2 font-mono text-[11px]">
              <div className="rounded border border-border/60 bg-surface/80 p-2">
                <span className="font-bold text-primary">{`{{${String(node.data.params.outputVariable || 'variable')}_centroX}}`}</span> / <span className="font-bold text-primary">{`{{${String(node.data.params.outputVariable || 'variable')}_centroY}}`}</span>
                <p className="mt-1 mb-0 font-sans text-[11px] text-text-muted">Centro del elemento (ideal para bloques de Click o Mover mouse).</p>
              </div>
              <div className="rounded border border-border/60 bg-surface/80 p-2">
                <span className="font-bold text-text">{`{{${String(node.data.params.outputVariable || 'variable')}_x}}`}</span> / <span className="font-bold text-text">{`{{${String(node.data.params.outputVariable || 'variable')}_y}}`}</span>
                <p className="mt-1 mb-0 font-sans text-[11px] text-text-muted">Esquina superior izquierda del elemento.</p>
              </div>
              <div className="rounded border border-border/60 bg-surface/80 p-2">
                <span className="font-bold text-text">{`{{${String(node.data.params.outputVariable || 'variable')}_ancho}}`}</span> / <span className="font-bold text-text">{`{{${String(node.data.params.outputVariable || 'variable')}_alto}}`}</span>
                <p className="mt-1 mb-0 font-sans text-[11px] text-text-muted">Dimensiones del recuadro detectado en píxeles.</p>
              </div>
              <div className="rounded border border-border/60 bg-surface/80 p-2">
                <span className="font-bold text-text">{`{{${String(node.data.params.outputVariable || 'variable')}_confianza}}`}</span> / <span className="font-bold text-text">{`{{${String(node.data.params.outputVariable || 'variable')}_textoDetectado}}`}</span>
                <p className="mt-1 mb-0 font-sans text-[11px] text-text-muted">Nivel de confianza (0 a 1) y texto exacto leído.</p>
              </div>
            </div>
          </div>
        </details>
      ) : null}
      {usesCoordinateGrouping ? (
        <div className="grid gap-3 @sm:grid-cols-3">
          <div className="grid content-start gap-3">{regularFields.map(renderField)}</div>
          {coordinateGroup}
        </div>
      ) : (
        <div className="grid gap-3 @sm:grid-cols-2 @xl:grid-cols-3">
          {regularFields.map(renderField)}
        </div>
      )}
      {action.outputs.length || action.output ? (
        <p className="mt-3 mb-0 text-[11px] text-text-muted">
          Salida: Se guarda en <strong>{(action.outputs[0] ?? action.output)!.field}</strong>.
        </p>
      ) : null}
    </section>
  );
}
