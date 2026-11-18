import { ArrowLeft, Menu, Pencil, X } from 'lucide-react';
import { AnimatePresence, motion } from 'framer-motion';
import { useState } from 'react';
import { Mascot } from '@/components/Mascot';
import { OverlayDialog } from '@/features/editor/OverlayDialog';

const DESCRIPTION_MAX_LENGTH = 500;

type Props = {
  name: string;
  description: string;
  editingDisabled: boolean;
  onBack: () => void;
  onCatalogOpen: () => void;
  onChangeDescription: (value: string) => void;
  onChangeName: (value: string) => void;
};

function EditMetadataButton({ disabled, onClick }: { disabled: boolean; onClick: () => void }) {
  const [hovered, setHovered] = useState(false);
  return (
    <span className="relative inline-flex shrink-0">
      <motion.button
        aria-label="Editar nombre y descripción"
        className="grid size-5 place-items-center rounded text-text-muted/70 transition-colors hover:bg-blue-50/60 hover:text-primary focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-40"
        disabled={disabled}
        onClick={() => {
          setHovered(false);
          onClick();
        }}
        onHoverEnd={() => setHovered(false)}
        onHoverStart={() => setHovered(true)}
        type="button"
        whileHover={disabled ? undefined : { scale: 1.15 }}
        whileTap={disabled ? undefined : { scale: 0.9 }}>
        <Pencil aria-hidden="true" size={11} />
      </motion.button>
      <AnimatePresence>
        {hovered && !disabled ? (
          <motion.span
            animate={{ opacity: 1, y: 0, scale: 1 }}
            className="pointer-events-none absolute top-full right-0 z-30 mt-2 rounded-control bg-sidebar px-2.5 py-1.5 text-[11px] font-bold whitespace-nowrap text-white shadow-overlay"
            exit={{ opacity: 0, y: 4, scale: 0.95 }}
            initial={{ opacity: 0, y: 4, scale: 0.95 }}
            transition={{ duration: 0.12 }}>
            Editar nombre/descripción
          </motion.span>
        ) : null}
      </AnimatePresence>
    </span>
  );
}

export function EditorToolbar({ name, description, editingDisabled, onBack, onCatalogOpen, onChangeDescription, onChangeName }: Props) {
  const [editOpen, setEditOpen] = useState(false);

  return (
    <>
      <header className="relative z-20 border-b border-border bg-gradient-to-r from-white via-blue-50/60 to-cyan-50/50 px-3 py-2.5 shadow-[0_1px_3px_rgb(15_23_42/6%)] sm:px-4">
        <div className="flex min-w-0 items-center gap-2">
          <motion.button aria-label="Volver al Explorador" className="grid size-8 shrink-0 place-items-center rounded-control border border-border bg-white text-text shadow-sm hover:border-blue-200 hover:bg-blue-50/60 hover:text-primary focus-visible:outline-none focus-visible:shadow-focus" onClick={onBack} type="button" whileHover={{ scale: 1.06, x: -1 }} whileTap={{ scale: 0.92 }}>
            <ArrowLeft aria-hidden="true" size={16} />
          </motion.button>
          <button aria-label="Abrir catálogo de bloques" className="grid size-9 place-items-center rounded-control border border-border hover:bg-bg focus-visible:outline-none focus-visible:shadow-focus disabled:cursor-not-allowed disabled:opacity-50 lg:hidden" disabled={editingDisabled} onClick={onCatalogOpen} type="button">
            <Menu aria-hidden="true" size={17} />
          </button>
          <input
            aria-label="Nombre actual del bot"
            className="field-control h-6 min-w-0 flex-1 cursor-default rounded-md bg-transparent px-1 text-[12px] font-bold text-text-muted"
            readOnly
            tabIndex={-1}
            value={name}
          />
          <EditMetadataButton disabled={editingDisabled} onClick={() => setEditOpen(true)} />
        </div>
      </header>
      <OverlayDialog
        ariaLabel="Editar nombre y descripción"
        className="hidden inset-0 h-screen w-screen p-4 open:grid open:place-items-center"
        onDismiss={() => setEditOpen(false)}
        open={editOpen}>
        <div className="relative w-full max-w-md rounded-panel border border-border bg-surface shadow-overlay">
          <div className="absolute -top-10 -left-4 z-10 drop-shadow-xl">
            <Mascot decorative={false} entrance="bounce" float={false} size={72} state="present" />
          </div>
          <div className="flex items-center gap-3 border-b border-border px-5 pt-9 pb-3.5">
            <span className="grid size-10 shrink-0 place-items-center rounded-control bg-blue-50 text-primary shadow-sm">
              <Pencil aria-hidden="true" size={17} />
            </span>
            <h2 className="m-0 min-w-0 flex-1 truncate text-lg font-extrabold">Nombre y descripción</h2>
            <button
              aria-label="Cerrar edición de nombre y descripción"
              className="shrink-0 rounded-control p-1.5 text-text-muted transition-colors hover:bg-black/5 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
              data-dialog-initial-focus
              onClick={() => setEditOpen(false)}
              type="button">
              <X aria-hidden="true" size={18} />
            </button>
          </div>
          <div className="grid gap-3 p-5">
            <label className="text-[11px] font-extrabold tracking-[0.04em] uppercase">
              Nombre
              <input
                aria-label="Nombre del bot"
                className="field-control mt-1.5 h-10 w-full rounded-control bg-white px-3 text-[14px] font-normal transition-[border-color,box-shadow] duration-150 ease-out"
                disabled={editingDisabled}
                id="bot-name-edit"
                maxLength={120}
                onChange={(event) => onChangeName(event.target.value)}
                value={name}
              />
            </label>
            <label className="text-[11px] font-extrabold tracking-[0.04em] uppercase">
              Descripción
              <textarea
                aria-label="Descripción del bot"
                className="field-control mt-1.5 min-h-20 w-full resize-y rounded-control bg-white px-3 py-2 text-[13px] font-normal transition-[border-color,box-shadow] duration-150 ease-out"
                disabled={editingDisabled}
                id="bot-description-edit"
                maxLength={DESCRIPTION_MAX_LENGTH}
                onChange={(event) => onChangeDescription(event.target.value)}
                placeholder="Agregar descripción"
                value={description}
              />
            </label>
            <span aria-hidden="true" className="-mt-1.5 block text-right text-[10px] font-bold text-text-muted">
              {description.length}/{DESCRIPTION_MAX_LENGTH}
            </span>
          </div>
        </div>
      </OverlayDialog>
    </>
  );
}
