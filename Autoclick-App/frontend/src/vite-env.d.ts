/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AWS_REGION: string;
  readonly VITE_COGNITO_USER_POOL_ID: string;
  readonly VITE_COGNITO_CLIENT_ID: string;
  readonly VITE_AUTOCLICK_AI_URL: string;
  readonly VITE_AUTOCLICK_CLOUD_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

type DesktopApi = import('./app/DesktopBridge').DesktopApi;

interface Window {
  pywebview?: {
    api: DesktopApi;
  };
}
