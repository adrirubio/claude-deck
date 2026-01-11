// Status Line TypeScript types matching backend schemas

export interface StatusLineConfig {
  type: string;
  command: string | null;
  padding: number | null;
  enabled: boolean;
  script_content: string | null;
}

export interface StatusLineUpdate {
  type?: string;
  command?: string;
  padding?: number;
  enabled?: boolean;
}

export interface StatusLinePreset {
  id: string;
  name: string;
  description: string;
  script: string;
}

export interface StatusLinePresetsResponse {
  presets: StatusLinePreset[];
}

export interface StatusLinePreviewRequest {
  script: string;
}

export interface StatusLinePreviewResponse {
  success: boolean;
  output: string;
  error: string | null;
}

export interface PowerlinePreset {
  id: string;
  name: string;
  description: string;
  theme: string;
  style: string;
  command: string;
}

export interface PowerlinePresetsResponse {
  presets: PowerlinePreset[];
}

export interface NodejsCheckResponse {
  available: boolean;
  version: string | null;
}
