/// <reference types="vite/client" />

interface Window {
  desktop?: {
    backendUrl: string;
    platform: string;
    versions: Record<string, string>;
  };
}
