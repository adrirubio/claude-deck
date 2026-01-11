// Output Style TypeScript types matching backend schemas

export type OutputStyleScope = "user" | "project";

export interface OutputStyle {
  name: string;
  scope: OutputStyleScope;
  description?: string | null;
  keep_coding_instructions: boolean;
  content: string;
}

export interface OutputStyleCreate {
  name: string;
  scope: OutputStyleScope;
  description?: string;
  keep_coding_instructions?: boolean;
  content: string;
}

export interface OutputStyleUpdate {
  description?: string;
  keep_coding_instructions?: boolean;
  content?: string;
}

export interface OutputStyleListResponse {
  output_styles: OutputStyle[];
}
