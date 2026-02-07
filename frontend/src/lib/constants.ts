export const API_BASE_URL = import.meta.env.VITE_API_URL || '/api/v1/'

export const CLICKABLE_CARD = 'cursor-pointer border-2 hover:border-primary/50 transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none'

export const MODAL_SIZES = {
  SM: 'max-w-2xl max-h-[80vh] overflow-y-auto',
  MD: 'max-w-3xl max-h-[85vh]',
  LG: 'max-w-4xl max-h-[90vh]',
} as const
