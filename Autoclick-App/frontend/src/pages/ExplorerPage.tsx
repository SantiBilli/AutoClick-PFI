import {
  AlertCircle,
  ArrowUpDown,
  Bot,
  CalendarDays,
  FileJson,
  FolderOpen,
  Globe2,
  Mail,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Table2,
  Trash2,
  X,
  type LucideIcon,
} from 'lucide-react';
import { AnimatePresence, motion, MotionConfig, useReducedMotion } from 'framer-motion';
import { useEffect, useMemo, useState, type FormEvent } from 'react';
import {
  desktopBridge,
  type ApiErrorCode,
  type ApiResponse,
  type BotCatalog,
  type BotDescriptor,
} from '@/app/DesktopBridge';
import { Alert } from '@/components/Alert';
import { Button } from '@/components/Button';
import { Input } from '@/components/Input';
import { Mascot } from '@/components/Mascot';
import { Panel } from '@/components/Panel';
import { OverlayDialog } from '@/features/editor/OverlayDialog';
import { fadeUp, staggerContainer } from '@/lib/motion';

type RequestKind = 'select' | 'refresh';
const initialBridgeRetryMs = 200;

const dateFormatter = new Intl.DateTimeFormat('es-AR', {
  day: 'numeric',
  month: 'short',
  year: 'numeric',
});

const botIcons: Record<string, LucideIcon> = {
  browser: Globe2,
  email: Mail,
  file: FileJson,
  spreadsheet: Table2,
};

function safeErrorMessage(code: ApiErrorCode, action: 'load' | RequestKind) {
  if (code === 'DESKTOP_BRIDGE_UNAVAILABLE') {
    return 'La integración de escritorio no está disponible. Abrí AutoClick desde la aplicación de escritorio.';
  }
  if (action === 'refresh') {
    return 'No se pudo actualizar la carpeta. Intentá nuevamente.';
  }
  if (action === 'select') {
    return 'No se pudo leer la carpeta seleccionada. Intentá nuevamente.';
  }
  return 'No se pudo cargar la carpeta. Intentá nuevamente.';
}

function waitForInitialBridgeRetry() {
  return new Promise<void>((resolve) => window.setTimeout(resolve, initialBridgeRetryMs));
}

async function loadInitialCatalog() {
  try {
    const response = await desktopBridge.getBotCatalog();
    const shouldRetry =
      !response.ok &&
      (response.error.code === 'DESKTOP_BRIDGE_UNAVAILABLE' ||
        response.error.code === 'CATALOG_READ_FAILED');
    if (!shouldRetry) return response;
  } catch {
    // A remembered session can reach Explorer before pywebview finishes injecting its API.
  }

  await waitForInitialBridgeRetry();
  return desktopBridge.getBotCatalog();
}

function BotCard({
  bot,
  disabled,
  onDelete,
}: {
  bot: BotDescriptor;
  disabled?: boolean;
  onDelete: (bot: BotDescriptor) => void;
}) {
  const Icon = bot.icon ? (botIcons[bot.icon] ?? Bot) : Bot;
  const blockLabel = `${bot.blockCount} ${bot.blockCount === 1 ? 'bloque' : 'bloques'}`;
  const modifiedLabel = dateFormatter.format(new Date(bot.modifiedAt));

  return (
    <motion.article
      aria-label={bot.name}
      className="card-glow-ring shimmer-sweep flex h-full min-w-0 flex-col rounded-panel p-5 shadow-card transition-shadow duration-200 ease-out hover:shadow-card-hover"
      variants={fadeUp}
      whileHover={{ y: -3 }}>
      <div className="mb-5 flex min-w-0 items-start justify-between gap-4">
        <motion.div
          aria-label={bot.icon ? `Ícono ${bot.icon}` : 'Ícono de bot'}
          className="grid size-11 shrink-0 place-items-center rounded-control bg-gradient-to-br from-blue-50 to-blue-100 text-primary shadow-[inset_0_0_0_1px_rgb(191,219,254)]"
          role="img"
          transition={{ duration: 0.2, ease: [0.34, 1.56, 0.64, 1] }}
          whileHover={{ rotate: -6, scale: 1.08 }}>
          <Icon aria-hidden="true" size={23} strokeWidth={1.8} />
        </motion.div>
        <span className="max-w-full shrink-0 rounded-full border border-border bg-bg px-2.5 py-1 text-right text-[11px] font-extrabold tracking-[0.04em] break-words text-text-muted uppercase">
          {blockLabel}
        </span>
      </div>
      <h2 className="m-0 min-w-0 text-[17px] leading-6 font-extrabold tracking-[-0.01em] break-words">
        {bot.name}
      </h2>
      <p className="mt-2 mb-6 min-w-0 flex-1 text-[13px] leading-5 break-words text-text-muted">
        {bot.description || 'Sin descripción.'}
      </p>
      <div className="mt-auto grid shrink-0 gap-2.5 border-t border-[#93c5fd] pt-4 text-[12px] text-text-muted">
        <span className="flex min-w-0 items-center gap-2">
          <FileJson aria-hidden="true" className="shrink-0 text-secondary" size={15} />
          <span className="truncate font-mono" title={bot.filename}>
            {bot.filename}
          </span>
        </span>
        <span className="flex items-center gap-2">
          <CalendarDays aria-hidden="true" className="shrink-0" size={15} />
          <time dateTime={bot.modifiedAt}>{modifiedLabel}</time>
        </span>
        <div className="mt-2 flex items-center gap-2">
          <motion.a
            className="inline-flex h-9 flex-1 items-center justify-center gap-2 rounded-control border border-border bg-white px-4 font-bold text-text no-underline hover:border-blue-300 hover:bg-blue-100 hover:text-primary focus-visible:outline-none focus-visible:shadow-focus"
            href={`#/bots/${encodeURIComponent(bot.entryId)}`}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.97 }}>
            <Pencil aria-hidden="true" size={15} />
            Editar
          </motion.a>
          <motion.button
            aria-label={`Eliminar bot ${bot.name}`}
            className="inline-flex h-9 size-9 shrink-0 items-center justify-center rounded-control border border-border bg-white text-text-muted transition-colors hover:border-red-200 hover:bg-red-50 hover:text-danger focus-visible:outline-none focus-visible:shadow-focus disabled:opacity-50"
            disabled={disabled}
            onClick={() => onDelete(bot)}
            title={`Eliminar ${bot.name}`}
            type="button"
            whileHover={disabled ? undefined : { scale: 1.06 }}
            whileTap={disabled ? undefined : { scale: 0.94 }}>
            <Trash2 aria-hidden="true" size={15} />
          </motion.button>
        </div>
      </div>
    </motion.article>
  );
}

type SortOption = 'date-desc' | 'date-asc' | 'name-asc' | 'name-desc';

export function ExplorerPage() {
  const reduceMotion = useReducedMotion();
  const [catalog, setCatalog] = useState<BotCatalog | null>(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [pending, setPending] = useState<RequestKind | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [botToDelete, setBotToDelete] = useState<BotDescriptor | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortOrder, setSortOrder] = useState<SortOption>('date-desc');

  const filteredAndSortedBots = useMemo(() => {
    if (!catalog) return [];
    const query = searchQuery.trim().toLowerCase();

    const filtered = query
      ? catalog.bots.filter(
          (bot) =>
            bot.name.toLowerCase().includes(query) ||
            (bot.description && bot.description.toLowerCase().includes(query)) ||
            bot.filename.toLowerCase().includes(query)
        )
      : catalog.bots;

    return [...filtered].sort((a, b) => {
      switch (sortOrder) {
        case 'name-asc':
          return a.name.localeCompare(b.name, 'es', { sensitivity: 'base' });
        case 'name-desc':
          return b.name.localeCompare(a.name, 'es', { sensitivity: 'base' });
        case 'date-asc':
          return new Date(a.modifiedAt).getTime() - new Date(b.modifiedAt).getTime();
        case 'date-desc':
        default:
          return new Date(b.modifiedAt).getTime() - new Date(a.modifiedAt).getTime();
      }
    });
  }, [catalog, searchQuery, sortOrder]);

  function applyResponse(response: ApiResponse<BotCatalog | null>, action: 'load' | RequestKind) {
    if (response.ok) {
      setCatalog(response.data);
      setError(null);
      setNotice(null);
      return;
    }

    if (response.error.code === 'DIRECTORY_SELECTION_CANCELLED') return;

    if (response.error.code === 'DIRECTORY_UNAVAILABLE') {
      if (action === 'select') {
        setError(safeErrorMessage(response.error.code, action));
        return;
      }
      setCatalog(null);
      setError(null);
      setNotice('La carpeta guardada ya no está disponible.');
      return;
    }

    setError(safeErrorMessage(response.error.code, action));
  }

  useEffect(() => {
    let active = true;

    async function loadCatalog() {
      try {
        const response = await loadInitialCatalog();
        if (active) applyResponse(response, 'load');
      } catch {
        if (active) setError('No se pudo cargar la carpeta. Intentá nuevamente.');
      } finally {
        if (active) setInitialLoading(false);
      }
    }

    void loadCatalog();
    return () => {
      active = false;
    };
  }, []);

  async function runRequest(kind: RequestKind) {
    setPending(kind);
    setError(null);
    if (kind === 'select') setNotice(null);

    try {
      const response =
        kind === 'select'
          ? await desktopBridge.selectBotDirectory()
          : await desktopBridge.getBotCatalog();
      applyResponse(response, kind);
    } catch {
      setError(safeErrorMessage('CATALOG_READ_FAILED', kind));
    } finally {
      setPending(null);
    }
  }

  async function createBot(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = createName.trim();
    if (!name) {
      setCreateError('Ingresá un nombre para el bot.');
      return;
    }

    setCreating(true);
    setCreateError(null);
    try {
      const response = await desktopBridge.createBot(name);
      if (response.ok) {
        setCreateOpen(false);
        window.location.hash = `/bots/${encodeURIComponent(response.data.descriptor.entryId)}`;
        return;
      }
      if (response.error.code === 'DIRECTORY_UNAVAILABLE') {
        setCatalog(null);
        setCreateOpen(false);
        setNotice('La carpeta guardada ya no está disponible.');
        return;
      }
      if (response.error.code === 'BOT_INVALID') {
        setCreateError('El nombre debe tener entre 1 y 120 caracteres.');
        return;
      }
      if (response.error.code === 'DESKTOP_BRIDGE_UNAVAILABLE') {
        setCreateError(
          'La integración de escritorio no está disponible. Abrí AutoClick desde la aplicación de escritorio.'
        );
        return;
      }
      setCreateError('No se pudo crear el bot. Intentá nuevamente.');
    } catch {
      setCreateError('No se pudo crear el bot. Intentá nuevamente.');
    } finally {
      setCreating(false);
    }
  }

  function openCreateDialog() {
    setCreateName('');
    setCreateError(null);
    setCreateOpen(true);
  }

  function promptDeleteBot(bot: BotDescriptor) {
    setDeleteError(null);
    setBotToDelete(bot);
  }

  async function confirmDelete() {
    if (!botToDelete) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      const response = await desktopBridge.deleteBot(botToDelete.entryId);
      if (response.ok) {
        setBotToDelete(null);
        void runRequest('refresh');
        return;
      }
      if (response.error.code === 'DIRECTORY_UNAVAILABLE') {
        setCatalog(null);
        setBotToDelete(null);
        setNotice('La carpeta guardada ya no está disponible.');
        return;
      }
      if (response.error.code === 'BOT_ENTRY_NOT_FOUND') {
        setBotToDelete(null);
        void runRequest('refresh');
        return;
      }
      if (response.error.code === 'DESKTOP_BRIDGE_UNAVAILABLE') {
        setDeleteError('La función para eliminar requiere reiniciar la aplicación de escritorio.');
        return;
      }
      setDeleteError(
        'No se pudo eliminar el bot. Verificá los permisos del archivo e intentá nuevamente.'
      );
    } catch {
      setDeleteError('No se pudo eliminar el bot. Intentá nuevamente.');
    } finally {
      setDeleting(false);
    }
  }

  const isPending = pending !== null || creating || deleting;

  return (
    <div className="mx-auto min-w-0 w-full max-w-[1400px]">
      <MotionConfig reducedMotion="user">
        <motion.header
          animate={{ opacity: 1, y: 0 }}
          className="mb-6 flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between"
          initial={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}>
          <div className="min-w-0">
            <p className="m-0 text-[11px] font-extrabold tracking-[0.14em] text-secondary uppercase">
              Biblioteca local
            </p>
            <h1 className="mt-1.5 mb-2 text-[clamp(28px,4vw,38px)] leading-tight font-extrabold tracking-[-0.035em]">
              Explorador
            </h1>
            <p className="m-0 max-w-2xl leading-5 text-text-muted">
              Revisá los bots válidos de una carpeta local. Los archivos se verifican sin abrir ni
              ejecutar su contenido.
            </p>
          </div>
          {catalog ? (
            <div className="flex w-full gap-2 sm:w-auto">
              <Button
                className="min-w-0 flex-1 sm:flex-none"
                disabled={isPending}
                onClick={() => void runRequest('select')}
                variant="secondary">
                <FolderOpen aria-hidden="true" size={17} />
                {pending === 'select' ? 'Cambiando…' : 'Cambiar carpeta'}
              </Button>
              <Button
                aria-busy={pending === 'refresh'}
                className="shrink-0 px-3"
                disabled={isPending}
                onClick={() => void runRequest('refresh')}
                variant="secondary">
                <RefreshCw
                  aria-hidden="true"
                  className={
                    pending === 'refresh'
                      ? 'motion-safe:animate-spin [animation-duration:1.8s]'
                      : ''
                  }
                  size={17}
                />
                <span aria-live="polite">
                  {pending === 'refresh' ? 'Actualizando…' : 'Actualizar'}
                </span>
              </Button>
            </div>
          ) : null}
        </motion.header>

        <AnimatePresence initial={false}>
          {error ? <Alert className="mb-4">{error}</Alert> : null}
        </AnimatePresence>

        {notice ? (
          <div
            className="mb-4 flex items-center gap-2 rounded-control border border-border bg-surface px-3.5 py-2.5 text-[12px] text-text-muted"
            role="status">
            <FolderOpen aria-hidden="true" size={15} />
            {notice}
          </div>
        ) : null}

        {initialLoading ? (
          <Panel className="grid min-h-48 place-items-center p-6 text-center" role="status">
            <div>
              <Mascot className="mx-auto mb-2" size={72} state="walk" />
              <p className="m-0 font-bold">Cargando carpeta guardada…</p>
            </div>
          </Panel>
        ) : catalog ? (
          <>
            <motion.div
              animate={{ opacity: 1, y: 0 }}
              className="mb-5 flex min-w-0 flex-col gap-3 rounded-panel border border-border bg-surface px-4 py-3.5 shadow-card sm:flex-row sm:items-center sm:justify-between"
              initial={{ opacity: 0, y: 10 }}
              transition={{ duration: 0.35, delay: 0.05, ease: [0.16, 1, 0.3, 1] }}>
              <div className="flex min-w-0 items-center gap-3">
                <div className="grid size-9 shrink-0 place-items-center rounded-control bg-sidebar text-white">
                  <FolderOpen aria-hidden="true" size={18} />
                </div>
                <div className="min-w-0">
                  <p className="m-0 min-w-0 text-[11px] font-extrabold tracking-[0.08em] break-words text-text-muted uppercase">
                    {catalog.directoryName}
                  </p>
                  <p
                    className="m-0 truncate font-mono text-[12px] text-text"
                    title={catalog.directoryPath}>
                    {catalog.directoryPath}
                  </p>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap items-center gap-3">
                <div className="group relative">
                  {!isPending ? (
                    <span className="pointer-events-none absolute -top-3 -left-3 z-10 opacity-0 drop-shadow-md transition-opacity group-hover:opacity-100">
                      <Mascot float={false} interactive={false} size={30} state="wave" />
                    </span>
                  ) : null}
                  <Button
                    className="shimmer-sweep h-9 px-3.5 text-[13px]"
                    disabled={isPending}
                    onClick={openCreateDialog}>
                    <Plus aria-hidden="true" size={16} />
                    Crear bot
                  </Button>
                </div>
                <span className="shrink-0 text-[12px] font-bold text-text-muted">
                  {searchQuery.trim()
                    ? `${filteredAndSortedBots.length} de ${catalog.bots.length} ${catalog.bots.length === 1 ? 'bot' : 'bots'}`
                    : `${catalog.bots.length} ${catalog.bots.length === 1 ? 'bot válido' : 'bots válidos'}`}
                </span>
              </div>
            </motion.div>

            {catalog.bots.length > 0 ? (
              <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="relative min-w-0 flex-1 max-w-md">
                  <Search
                    aria-hidden="true"
                    className="pointer-events-none absolute top-1/2 left-3.5 -translate-y-1/2 text-text-muted"
                    size={16}
                  />
                  <Input
                    aria-label="Buscar bots"
                    className="h-10 w-full rounded-control bg-white pr-9 pl-10 text-[13px] placeholder:text-text-muted/70"
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder="Buscar por nombre, descripción o archivo..."
                    type="search"
                    value={searchQuery}
                  />
                  {searchQuery ? (
                    <button
                      aria-label="Limpiar búsqueda"
                      className="absolute top-1/2 right-2.5 grid size-6 -translate-y-1/2 place-items-center rounded-full text-text-muted transition-colors hover:bg-slate-100 hover:text-text focus-visible:outline-none focus-visible:shadow-focus"
                      onClick={() => setSearchQuery('')}
                      type="button">
                      <X aria-hidden="true" size={14} />
                    </button>
                  ) : null}
                </div>

                <div className="flex shrink-0 items-center gap-2">
                  <label
                    className="flex items-center gap-1.5 text-[12px] font-bold text-text-muted"
                    htmlFor="explorer-sort-select">
                    <ArrowUpDown aria-hidden="true" size={14} />
                    <span>Ordenar:</span>
                  </label>
                  <select
                    aria-label="Ordenar bots"
                    className="field-control h-10 rounded-control bg-white px-3 text-[13px] font-bold text-text transition-[border-color,box-shadow] duration-150"
                    id="explorer-sort-select"
                    onChange={(event) => setSortOrder(event.target.value as SortOption)}
                    value={sortOrder}>
                    <option value="date-desc">Fecha (más reciente)</option>
                    <option value="date-asc">Fecha (más antiguo)</option>
                    <option value="name-asc">Nombre (A - Z)</option>
                    <option value="name-desc">Nombre (Z - A)</option>
                  </select>
                </div>
              </div>
            ) : null}

            {catalog.invalidCount > 0 ? (
              <p
                className="mb-4 flex items-center gap-1.5 text-[12px] font-bold text-red-900"
                role="status">
                <span className="relative inline-flex size-4 shrink-0 items-center justify-center">
                  {!reduceMotion ? (
                    <motion.span
                      animate={{ scale: [1, 1.9], opacity: [0.55, 0] }}
                      className="absolute inset-0 rounded-full bg-red-800/50"
                      transition={{ duration: 1.4, repeat: Infinity, ease: 'easeOut' }}
                    />
                  ) : null}
                  <AlertCircle aria-hidden="true" className="relative text-red-800" size={13} />
                </span>
                {catalog.invalidCount}{' '}
                {catalog.invalidCount === 1
                  ? 'archivo JSON inválido no se muestra'
                  : 'archivos JSON inválidos no se muestran'}
              </p>
            ) : null}

            {catalog.bots.length > 0 ? (
              filteredAndSortedBots.length > 0 ? (
                <motion.div
                  animate="show"
                  className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3"
                  initial="hidden"
                  key={`${sortOrder}-${searchQuery ? 'filtered' : 'all'}`}
                  variants={staggerContainer(0.06, 0.05)}
                  viewport={{ once: true, amount: 0.1 }}
                  whileInView="show">
                  {filteredAndSortedBots.map((bot) => (
                    <BotCard
                      bot={bot}
                      disabled={isPending}
                      key={bot.entryId}
                      onDelete={promptDeleteBot}
                    />
                  ))}
                </motion.div>
              ) : (
                <Panel className="grid min-h-64 place-items-center p-6 text-center">
                  <div className="max-w-sm">
                    <Mascot className="mx-auto mb-4" size={88} state="thinking" />
                    <h2 className="m-0 text-lg font-extrabold">No se encontraron bots</h2>
                    <p className="mt-2 mb-4 text-[13px] leading-5 text-text-muted">
                      No hay bots que coincidan con &ldquo;{searchQuery}&rdquo;.
                    </p>
                    <Button
                      className="h-9 px-4 text-[13px]"
                      onClick={() => setSearchQuery('')}
                      type="button"
                      variant="secondary">
                      Limpiar búsqueda
                    </Button>
                  </div>
                </Panel>
              )
            ) : (
              <Panel className="grid min-h-64 place-items-center p-6 text-center">
                <div className="max-w-sm">
                  <Mascot className="mx-auto mb-4" size={104} state="idle" />
                  <h2 className="m-0 text-xl font-extrabold">No hay bots válidos</h2>
                  <p className="mt-2 mb-0 leading-5 text-text-muted">
                    Agregá un bot compatible a esta carpeta o actualizá para revisar nuevos
                    archivos.
                  </p>
                </div>
              </Panel>
            )}
          </>
        ) : (
          <motion.div
            animate={{ opacity: 1, scale: 1 }}
            initial={{ opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}>
            <Panel className="grid min-h-72 place-items-center p-6 text-center">
              <div className="max-w-md">
                <Mascot className="mx-auto mb-3" size={124} state="present" />
                <h2 className="m-0 text-xl font-extrabold">Elegí dónde están tus bots</h2>
                <p className="mt-2 mb-5 leading-5 text-text-muted">
                  AutoClick revisará los archivos JSON de la carpeta y mostrará solamente los bots
                  válidos.
                </p>
                <Button
                  className="shimmer-sweep"
                  disabled={isPending}
                  onClick={() => void runRequest('select')}>
                  <FolderOpen aria-hidden="true" size={17} />
                  {pending === 'select' ? 'Seleccionando…' : 'Seleccionar carpeta'}
                </Button>
              </div>
            </Panel>
          </motion.div>
        )}

        <OverlayDialog
          className="inset-0 h-screen w-screen p-4"
          dismissible={!creating}
          labelledBy="create-bot-title"
          onDismiss={() => setCreateOpen(false)}
          open={createOpen}>
          <form
            className="relative mx-auto mt-[max(12vh,3rem)] w-full max-w-md rounded-panel border border-border bg-surface p-5 pt-10 shadow-overlay"
            onSubmit={(event) => void createBot(event)}>
            <div className="absolute -top-10 -left-4 z-10 drop-shadow-xl">
              <Mascot entrance="bounce" float={false} size={72} state="present" />
            </div>
            <h2 className="m-0 text-lg font-extrabold" id="create-bot-title">
              Crear bot
            </h2>
            <p className="mt-2 mb-5 leading-5 text-text-muted">
              El bot se guardará en la carpeta seleccionada y se abrirá en el editor.
            </p>
            <label className="mb-1.5 block text-[13px] font-bold" htmlFor="create-bot-name">
              Nombre del bot
            </label>
            <Input
              autoComplete="off"
              data-dialog-initial-focus
              disabled={creating}
              id="create-bot-name"
              maxLength={120}
              onChange={(event) => {
                setCreateName(event.target.value);
                if (createError) setCreateError(null);
              }}
              required
              value={createName}
            />
            {createError ? (
              <p className="mt-2 mb-0 text-[13px] text-danger" role="alert">
                {createError}
              </p>
            ) : null}
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                disabled={creating}
                onClick={() => setCreateOpen(false)}
                type="button"
                variant="secondary">
                Cancelar
              </Button>
              <Button aria-busy={creating} disabled={creating} type="submit">
                {creating ? 'Creando…' : 'Crear'}
              </Button>
            </div>
          </form>
        </OverlayDialog>

        <OverlayDialog
          className="inset-0 h-screen w-screen p-4"
          dismissible={!deleting}
          labelledBy="delete-bot-title"
          onDismiss={() => {
            if (!deleting) {
              setBotToDelete(null);
              setDeleteError(null);
            }
          }}
          open={botToDelete !== null}>
          <div className="relative mx-auto mt-[max(12vh,3rem)] w-full max-w-md rounded-panel border border-border bg-surface p-5 pt-10 shadow-overlay">
            <div className="absolute -top-10 -left-4 z-10 drop-shadow-xl">
              <Mascot entrance="bounce" float={false} size={72} state="thinking" />
            </div>
            <div className="min-w-0 flex-1">
              <h2 className="m-0 text-lg font-extrabold text-text" id="delete-bot-title">
                ¿Eliminar &quot;{botToDelete?.name}&quot;?
              </h2>
              <p className="mt-2 mb-3 text-[13px] leading-5 text-text-muted">
                Esta acción eliminará el archivo del bot de forma permanente de tu carpeta local.
                Esta acción no se puede deshacer.
              </p>
              {botToDelete ? (
                <div className="rounded-control border border-border bg-bg p-2.5 text-[12px] font-mono text-text-muted">
                  <span className="block truncate" title={botToDelete.filename}>
                    Archivo: {botToDelete.filename}
                  </span>
                </div>
              ) : null}
              {deleteError ? (
                <p className="mt-3 mb-0 text-[13px] text-danger" role="alert">
                  {deleteError}
                </p>
              ) : null}
            </div>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                disabled={deleting}
                onClick={() => {
                  setBotToDelete(null);
                  setDeleteError(null);
                }}
                type="button"
                variant="secondary">
                Cancelar
              </Button>
              <Button
                aria-busy={deleting}
                className="border-transparent bg-red-700 text-white hover:bg-red-700 focus-visible:shadow-focus"
                disabled={deleting}
                onClick={() => void confirmDelete()}
                type="button">
                {deleting ? 'Eliminando…' : 'Eliminar definitivamente'}
              </Button>
            </div>
          </div>
        </OverlayDialog>
      </MotionConfig>
    </div>
  );
}
