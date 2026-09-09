/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_REPO?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
