export type KeyboardEventLike = Pick<
  KeyboardEvent,
  'key' | 'code' | 'ctrlKey' | 'shiftKey' | 'altKey' | 'metaKey'
>;

const NAMED_KEYS: Record<string, string> = {
  Backspace: 'backspace',
  Tab: 'tab',
  Enter: 'enter',
  Escape: 'escape',
  ' ': 'space',
  Spacebar: 'space',
  Delete: 'delete',
  Insert: 'insert',
  Home: 'home',
  End: 'end',
  PageUp: 'pageup',
  PageDown: 'pagedown',
  ArrowLeft: 'left',
  ArrowRight: 'right',
  ArrowUp: 'up',
  ArrowDown: 'down',
  CapsLock: 'capslock',
  NumLock: 'numlock',
  ScrollLock: 'scrolllock',
  Pause: 'pause',
  PrintScreen: 'printscreen',
  AudioVolumeUp: 'volumeup',
  AudioVolumeDown: 'volumedown',
  AudioVolumeMute: 'volumemute',
  BrowserBack: 'browserback',
  BrowserFavorites: 'browserfavorites',
  BrowserForward: 'browserforward',
  BrowserHome: 'browserhome',
  BrowserRefresh: 'browserrefresh',
  BrowserSearch: 'browsersearch',
  BrowserStop: 'browserstop',
  ContextMenu: 'apps',
  MediaTrackNext: 'nexttrack',
  MediaTrackPrevious: 'prevtrack',
  MediaPlayPause: 'playpause',
  MediaStop: 'stop',
  MediaSelect: 'launchmediaselect',
  LaunchApplication1: 'launchapp1',
  LaunchApplication2: 'launchapp2',
  LaunchMail: 'launchmail',
  LaunchMediaPlayer: 'launchmediaselect',
  Accept: 'accept',
  Clear: 'clear',
  Convert: 'convert',
  Execute: 'execute',
  FinalMode: 'final',
  Help: 'help',
  JunjaMode: 'junja',
  KanaMode: 'kana',
  KanjiMode: 'kanji',
  ModeChange: 'modechange',
  NonConvert: 'nonconvert',
  Select: 'select',
  Sleep: 'sleep',
};

const NUMPAD_CODES: Record<string, string> = {
  NumpadDecimal: 'decimal',
  NumpadAdd: 'add',
  NumpadSubtract: 'subtract',
  NumpadMultiply: 'multiply',
  NumpadDivide: 'divide',
  NumpadSeparator: 'separator',
  NumpadComma: 'separator',
  NumpadEnter: 'enter',
};

const MODIFIER_KEYS = new Set(['Alt', 'AltGraph', 'Control', 'Meta', 'OS', 'Shift']);
const UNSUPPORTED_KEYS = new Set(['Dead', 'Process', 'Unidentified']);

function mainKey(event: KeyboardEventLike): string | null {
  if (UNSUPPORTED_KEYS.has(event.key) || MODIFIER_KEYS.has(event.key)) return null;

  const numpadDigit = /^Numpad([0-9])$/.exec(event.code);
  if (numpadDigit) return `num${numpadDigit[1]}`;
  if (NUMPAD_CODES[event.code]) return NUMPAD_CODES[event.code];
  if (NAMED_KEYS[event.key]) return NAMED_KEYS[event.key];

  const functionKey = /^F([1-9]|1[0-9]|2[0-4])$/i.exec(event.key);
  if (functionKey) return `f${functionKey[1]}`;

  if (/^[a-z0-9]$/i.test(event.key)) return event.key.toLowerCase();
  const characterCode = /^(?:Key([A-Z])|Digit([0-9]))$/.exec(event.code);
  return (characterCode?.[1] ?? characterCode?.[2])?.toLowerCase() ?? null;
}

export function normalizeKeyboardEvent(event: KeyboardEventLike): string | null {
  const key = mainKey(event);
  if (!key) return null;

  const modifiers = [
    event.ctrlKey ? 'ctrl' : null,
    event.shiftKey ? 'shift' : null,
    event.altKey ? 'alt' : null,
    event.metaKey ? 'win' : null,
  ].filter((modifier): modifier is string => modifier !== null);

  return [...modifiers, key].join('+');
}

const DISPLAY_LABELS: Record<string, string> = {
  ctrl: 'Ctrl',
  shift: 'Shift',
  alt: 'Alt',
  win: 'Win',
  esc: 'Escape',
  escape: 'Escape',
  space: 'Space',
  pageup: 'Page Up',
  pagedown: 'Page Down',
  pgup: 'Page Up',
  pgdn: 'Page Down',
  printscreen: 'Print Screen',
  capslock: 'Caps Lock',
  numlock: 'Num Lock',
  scrolllock: 'Scroll Lock',
  volumeup: 'Volume Up',
  volumedown: 'Volume Down',
  volumemute: 'Volume Mute',
};

function formatKey(key: string) {
  if (DISPLAY_LABELS[key]) return DISPLAY_LABELS[key];
  if (/^f(?:[1-9]|1[0-9]|2[0-4])$/.test(key)) return key.toUpperCase();
  const numpadDigit = /^num([0-9])$/.exec(key);
  if (numpadDigit) return `Num ${numpadDigit[1]}`;
  return key.length === 1 ? key.toUpperCase() : `${key[0]?.toUpperCase() ?? ''}${key.slice(1)}`;
}

export function formatKeybind(value: string): string {
  return value.split('+').filter(Boolean).map(formatKey).join(' + ');
}
