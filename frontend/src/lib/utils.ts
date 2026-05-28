import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function claudeProjectFolderFromPath(path: string) {
  return path.replace(/\/+$/, '').replace(/\//g, '-').replace(/\./g, '-')
}
