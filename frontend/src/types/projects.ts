/**
 * TypeScript types for Project Management
 */

export interface ProjectBase {
  name: string;
  path: string;
}

export interface ProjectResponse extends ProjectBase {
  id: number;
  is_active: boolean;
  last_accessed: string;
  created_at: string;
}

export interface ProjectListResponse {
  projects: ProjectResponse[];
}

export interface ProjectDiscoveryRequest {
  base_path: string;
}

export interface ProjectDiscoveryResponse {
  discovered: ProjectBase[];
}

export interface SetActiveProjectRequest {
  project_id: number;
}

export interface ProjectCreate {
  name: string;
  path: string;
}
